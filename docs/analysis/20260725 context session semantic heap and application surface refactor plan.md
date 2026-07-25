# Context/Session 语义堆与应用表面重构执行计划

状态：pending

日期：2026-07-25

## 意图

Context 和 Session 分别拥有当前 Turn 与已完成 prior Turn 的渐进历史。二者都采用“堆顶给出有界概况、模型沿稳定 ref 逐层展开”的认知方式，但其数据结构、生命周期和压缩责任不同：Context 是当前 Turn 的可变 append-only trace heap，Session 是跨 Turn 的 immutable Turn/Summary graph。重构只统一模型侧的探索语法与 Core action 入口，不建立跨 owner 的通用历史服务、通用堆实现或第二事实源。

应用侧只自然呈现后端真实运行过程。Chat 继续负责可信指令输入和 Observation 展示，Workspace 继续负责业务资源管理；删除为了独立 Session Explorer 建立的 REST 诊断协议、前端 History 页面和后端持久诊断结构。完整 LLM MessageStack 与其中真实进入模型的 Session Background、TurnTrace 仍通过既有 model Observation 展示。

## 已确认语义

- Workspace read 与 Script/Shell candidate read 保留各自现有 cursor，不纳入本轮调整；
- Context 与 Session 的模型侧 inspect 统一使用稳定 `ref`、可选 opaque `continuation` 和可选 `next_continuation`；
- `ref` 选择堆节点，`continuation` 只继续展开同一节点尚未交付完的直接内容，不能替代 ref、跨节点移动或把语义堆退化为线性历史分页；
- Context 与 Session 都只保留一个模型侧 inspect action，删除独立 recall，以及 Context 的显式 fold action；
- 两个 inspect action 进入 Core domain，原 Context/Session action domain、Catalog 目录和 Domain HOW 删除；
- Session record 直接升级为 schema v4，Manifest 升级为只持有根 ref 的 schema v2，不读取或迁移旧 schema；允许清理现有 active/archive v3 Session 数据；
- Session Background、模型 inspect 和 Memory facts 必须从同一 immutable record graph 按用途派生；
- Context canonical trace 与 heap 只保留为当前 Turn 的运行时事实，不写入 Session，不经 Endpoint 暴露；
- 删除 Endpoint Session history/actions/trace 和 visualization Session Explorer。前端不建立独立 Session 审计状态或历史事实投影。

## 顶层设计

### 1. 相同的探索习惯，不同的 owner 结构

模型面对两类历史时使用同一种规则：

1. 从 MessageStack 当前可见的堆顶、Summary、Turn 或 heap node ref 开始；
2. 调用对应 inspect，只展开该 ref 的下一层或该叶子的语义内容；
3. 选择响应中新出现的 ref 继续向下；
4. 仅当当前节点响应带 `next_continuation` 时，以同一 ref 和该 continuation 继续；
5. 所需事实已经可见时不调用 inspect。

Context 与 Session 不共享节点类型、压缩算法或 Engine。Infra 只提供有界 JSON 切分和 opaque continuation codec；owner 负责 ref 解析、节点定位、内容投影、continuation binding 与失败语义。

不增加统一的 `core.inspect` dispatcher。模型工具为：

```text
core.context.inspect
core.session.inspect
```

Action 名称以 Core domain 为前缀，符合 Catalog 与 Home prompt mount 的现有 identity 约束；native backend handler 和 Engine 仍分别由 Context、Session registrar 注入。两个 action 不调用 LLM，不建立 Action HOW。Core domain 不为此新增会污染 `core.answer`/`core.reason` 内部 LLM Task 的 Domain HOW；使用边界由 Core domain 的简洁 selection hint、两个工具的 description/use_when/avoid_when 表达。

### 2. Ref 与 continuation

统一模型协议为：

```json
{
  "ref": "owner-issued-node-ref",
  "continuation": "optional-opaque-token"
}
```

Session root inspect 允许省略 `ref`；其续读仍保持省略 ref，并提交 owner 返回的 continuation。响应只在当前节点仍有未交付直接内容时包含：

```json
{
  "next_continuation": "opaque-token"
}
```

continuation 是 versioned、owner/action/ref-bound 的 opaque token。其内部可以包含位置、immutable node content binding，或 active Session head 的 revision binding；这些字段不进入工具 schema 或模型结果。无效、过期、owner/ref 不匹配统一反馈“重新 inspect 当前 ref”，不向模型解释 index、offset、digest 或 revision。

节点之间只能通过响应中的新 ref 导航。continuation 不形成可持久 Link，不进入 Session record、Background 或 WorkingContext；foldable inspect 的 compact canonical result 至多保留 origin ref 和继续入口。

## Context 重构

### 1. 保留运行时 trace heap 与压缩算法

`TurnTraceHeap` 继续保存 append-only canonical entries、当前可见 hot entries、immutable cold leaf/branch nodes 和 root ids。Context pressure recovery 保持以下顺序：

1. 先折叠 inspect 等 foldable ActionResult 的完整 visible overlay；
2. 再按完整 Cycle 把较旧 hot entries 移入 cold leaf；
3. 按 branch factor 合并较旧 root，形成多层 branch；
4. MessageStack 只渲染 heap head 与剩余 hot entries；
5. 模型沿 head/branch/leaf ref 恢复被压缩事实。

inspect 不修改 heap 拓扑，不把恢复内容重新变成 canonical 历史，也不建立第二份热历史。完整 inspect 结果只作为当前 ActionResult visible overlay 进入 TurnTrace；其 foldable canonical payload 保留紧凑的 origin ref/continuation。后续压力优先移除 overlay，避免“恢复历史再次放大历史”的递归增长。

### 2. 单一 Context inspect

`core.context.inspect` 只接受当前 MessageStack 已暴露的 `turn:trace@...` head 或 `turn:trace/...` node ref：

- head ref：返回当前 cold roots 的紧凑 header；hot entries 已在 MessageStack 中，不复制；
- branch ref：返回直接 child headers；
- leaf ref：返回该 leaf 中按原顺序排列的语义 interaction items；若一次无法完整交付，返回同 ref 的 `next_continuation`；
- head roots 与 branch children 由 `branch_factor` 结构性限制，不进行线性分页；continuation 只用于同一 leaf 的超限语义内容，不用于从 head 自动遍历到 leaf。

公开 header 只保留定位所需事实，例如 ref、kind、直接 child/entry count、Action names 和 interaction kinds；删除 level、cycle ids、char count 等实现元数据。leaf item 只投影 decision、Action request、Action outcome/result/failure、references 和必要 phase note，不暴露 entry id、call id、cycle id、phase/stage、trace index、digest、coverage 或 pager limits。

删除：

- `context.trace.inspect` Catalog identity；
- `context.trace.recall` action、Engine 公共 recall 门面和 Catalog；
- `context.trace.fold` action、Engine 公共 fold 门面和 Catalog；
- 模型公开的 `JsonPageCursor` 结构、trace digest/source/coverage/requested/effective limit 响应；
- 仅服务旧 recall 路径的 `TraceRecallPage` 和重复 recall helper。

保留 `TurnTraceHeap.fold_overlays()` 作为 Context pressure recovery 的内部机制。

### 3. Turn completion 边界

Context 不再生成可持久 JSON `TurnSummary`。`end_turn()` 产生 typed、immutable 的当前 Turn completion snapshot，包含：

- turn identity；
- 有序 UserInput 文本及接收时间；
- WorkingContext 终态；
- Background top links；
- 仅含有序 canonical entries 的 sealed trace。

该 snapshot 只在 Loop completion pipeline 内传递。heap nodes、root ids 和压缩布局不离开 Context；若保留 `SealedTurnTrace` 类型，应将其收敛为 turn id 与 immutable entries，而不是序列化 heap topology。Session 在提交边界消费 typed trace，验证 Action call/result 一一配对并投影自己的业务记录；Session 落盘成功后不保留 trace、heap、trace summary 或 trace digest。Context 的 sealed trace 不成为跨 Turn 查询协议。

## Session 重构

### 1. 显式 immutable schema

删除以通用 `content: JsonObject` 表达 Turn/Summary 的 `SessionRecord`，改为两个显式 frozen record 类型。Turn record schema v4 只保存不可变业务事实：

```json
{
  "schema_version": 4,
  "kind": "turn",
  "ref": "session:turn/turn_9114acc6",
  "day": "2026-07-25",
  "recorded_at_ns": 0,
  "inputs": [
    {"text": "请帮我搜索本体论知识", "received_at": 0.0}
  ],
  "working": {},
  "background_links": [],
  "output": {
    "text": "已完成本体论知识检索……",
    "references": ["workspace:docs/ontology-knowledge.md"]
  },
  "exhausted": false,
  "actions": [
    {
      "action": "workspace.write",
      "request": {"target_link": "workspace:docs/ontology-knowledge.md"},
      "outcome": "success",
      "result": {"link": "workspace:docs/ontology-knowledge.md"},
      "references": []
    }
  ]
}
```

Action 顺序即 occurrence identity，不重复持久 occurrence。正常完成的 Turn 必须拥有可一一配对的 Action call/result；missing、orphan、duplicate 或 name mismatch 是 completion invariant failure，不持久化 `incomplete` 诊断 occurrence。Action record 保存 Action schema request、success/failed/timeout outcome、标准/foldable canonical result、typed failure 和 references；不保存 call id、trace location、cycle/phase/stage、pairing issue 或 backend metadata。

Summary record schema v4 只保存 ref、day、recorded time 和 ordered child refs。summary ref 继续由 day 与 child refs 确定性生成；它是不可变索引节点，不复制 child Background、char count 或 Action counts。

Manifest schema v2 只保存 day、内部 revision 和 ordered root refs：

```json
{
  "schema_version": 2,
  "day": "2026-07-25",
  "revision": 12,
  "refs": ["session:summary/summary_x", "session:turn/turn_y"]
}
```

kind 由 ref 语法和实际 record 共同校验。Background 字符估算、Turn preview、Summary turn count 和时间范围均在读取时从 record graph 派生。Manifest root 数量受 Summary 收缩控制，因此不为读取性能重新持久化派生 item。

record/manifest 直接拒绝 v3/v1，不增加 adapter、兼容 alias 或自动 migration。测试和开发运行目录中的旧 Session 数据由使用者显式清理；archive snapshot 对新数据使用同一 v4 validator。

### 2. 唯一事实和投影

Session completion projector 是 typed Context completion 到 `SessionTurnRecord` 的唯一转换边界。后续能力全部读取已验证 record graph：

- Session Background 投影 ask、answer、references、exhausted 和按 Action 名称聚合的 outcome，以及确定性 Action collection ref；
- `core.session.inspect` 投影 Summary、Turn、Action collection 和具体 Action；
- Memory facts 投影有序 Turn inputs、Working、Background links、output、Actions 和 exhausted；
- reconciliation 校验 ref、record kind、day、Summary child graph、重复引用、环和 orphan Turn；
- 幂等提交比较同 ref 的完整 immutable record，不比较持久派生 Background 或 digest。

删除 canonical trace、trace heap、trace summary、trace digest、persisted background、action_history、SessionHistoryItem 及其 projector/validator 重算链。若某项诊断没有 Session Background、inspect、Memory、reconciliation 或幂等提交的真实消费者，则不进入新 record。

### 3. 单一 Session inspect 与堆顶语义

Session Background 是模型默认看到的有界堆顶，不因 inspect 改写。Summary 收缩仍保留最近 Turn，并把较旧连续 roots 组成递归 immutable Summary graph。`core.session.inspect` 按 ref 的节点种类展开：

- 无 ref：返回 authoritative active root，只用于 overflow 恢复或显式重新查看堆顶；
- Summary ref：返回其 direct child Summary/Turn headers；
- Turn ref：返回该 Turn 的 ask、answer、references、exhausted、Action outcome summary 和 Action collection ref；仅当单个 Turn 语义对象本身超出 hard limit 时，以同一 ref continuation 续读；
- Action collection ref：按发生顺序返回直接 Action leaf headers，可选按已知 Action name 过滤；失败/timeout header 附带有界 failure feedback 和非空失败 result；成功 header 不内联 result；
- Action leaf ref：返回一个 Action 的 request、outcome、result/references 或 failure；超大单 Action 才使用同 ref continuation 分段。

以上是 `root -> Summary -> Turn -> Action collection -> Action leaf` 的节点展开，不是 Turn 或 trace 的连续分页。root、Summary 和 Action collection 仅在直接 children 超过 owner hard limit 时返回 continuation。Turn 与 Action leaf 通常一次完整交付，只在单个语义对象超限时使用同 ref continuation。

Session Action collection/leaf ref 继续由 immutable Turn record 中的有序 Action 列表确定性派生，不落盘、不进入 Manifest。模型复制 owner 返回的 ref，不解释或构造 `#actions`/`#action/<n>` 后缀。

## Infra paging 清理

`tinysoul.infra.paging` 不再向 Context/Session 模型协议直接输出 `JsonPageCursor`、cursor unit、entry index、char offset、entry digest、coverage、remaining、requested/effective limits 或 source revision。

保留一个内部 hard-budget sequence/chunk primitive，并增加小型 opaque continuation codec。primitive 返回 typed internal position 与可选 next position；Context/Session owner 将 position 与 owner、action、ref、内容 identity 绑定后编码。oversized JSON 的字符 offset/digest 仍可在 token 内使用，但不出现在模型 schema 和 payload。

Context 配置将旧 `trace_recall_max_chars/trace_recall_max_entries` 收敛为 owner-only 的 `trace_inspect_max_chars`；Session 将旧 `history_page_max_chars/history_page_max_entries/actions_page_max_items` 收敛为 owner-only 的 `inspect_max_chars`。工具 schema 不允许模型覆盖这些 hard limits。字符预算已经约束响应大小，因此不再维持独立公开 entry/item 数量预算。

该清理不改变 Workspace、Script、Shell 当前 pager/cursor 类型，也不要求它们采用 continuation codec。

## Endpoint 与 visualization 清理

### Endpoint

删除：

- `GET /v1/session/history`；
- `GET /v1/session/actions`；
- `GET /v1/session/trace`；
- EndpointEngine 对应 Session 查询方法、query 参数、错误映射与 OpenAPI schema；
- `/v1/status` 中无前端消费者的 `session_revision`；
- frontend integration 文档中的 Session REST、revision/cursor 和 replay-gap Session 重读说明。

移除 EndpointEngine/AppBuilder 为这些查询注入的直接 SessionEngine 依赖。保留 authenticated input/control/Maintenance/decision/status、Observation HTTP replay/WebSocket 和 Workspace API。Endpoint 不增加 Context/Session snapshot 替代接口。

### Visualization

删除：

- Sidebar History/Session 入口和全局 active tab；
- `SessionView`、`useSessionExplorer` 及 reducer/test；
- Session history/actions/trace API client、TypeScript types、分页状态和样式；
- active Session Explorer 设计文档与当前能力索引。

Chat 继续从 `llm.task.*` model Observation 展示每次真实 MessageStack，从 `context.background.*` 展示运行时 Background，从 Phase/Action 事件展示执行过程。Workspace 保持独立业务资源界面。event replay 出现 gap 时只清理 event-derived 临时执行视图并等待后续真实 baseline，不通过已删除的 Session REST 构造另一份模型历史。

已完成的 dated analysis/plan 文档作为历史实施记录保留，但在新实现完成时标记为被本计划取代；现行 AGENT、design、endpoint 和 visualization design 文档不得继续声明 Session Explorer 或 schema v3 是当前能力。

## 实施阶段

### Stage 1：契约与 Core Catalog

状态：pending

- 定义 Context/Session ref/continuation/next_continuation 共同语法和 owner binding；
- 将两个 inspect Catalog 移入 Core，命名为 `core.context.inspect`、`core.session.inspect`；
- 更新 Core domain description/selection hint 和两个 action semantic；
- 删除 Context/Session domain、recall/fold actions 与两个 Domain HOW；
- 调整 Home prompt mount reconciliation、package assets 和 Catalog 回归断言。

### Stage 2：Context semantic heap inspect

状态：pending

- 保留并整理 `TurnTraceHeap` 的 hot/cold、Cycle 原子压缩、leaf/branch 和 root coalescing；
- 让一个 inspect 门面覆盖 head、branch、leaf，输出紧凑 header 或语义 interaction；
- 接入 opaque continuation 和 owner hard budget；
- 删除公开 recall/fold、重复 recall page/helper 和模型公开 pager 元数据；
- 验证 inspect overlay 在 Context pressure 下优先折叠，canonical trace 不因 inspect 递归膨胀；
- 将 Turn 结束输出收敛为 typed completion snapshot，只转交 canonical entries，不再构造持久 JSON trace/heap/digest 或转交 heap topology。

### Stage 3：Session schema v4 与唯一投影

状态：pending

- 引入显式 Turn/Summary/Action/Input/Output immutable record 类型；
- 将 Manifest 收敛为 v2 ordered root refs；
- 用 typed trace projector 在 completion 边界构造并验证 Action business facts；
- 重写 store、validator、summary compaction、idempotency 和 orphan reconciliation；
- 从同一 record graph 派生 Background 与 Memory facts；
- 删除 v3 generic content、SessionHistoryItem、canonical trace/digest/heap、persisted background、action_history 及不再有 owner 职责的旧 projection/navigation 实现；
- 不提供旧 active/archive Session 读取或迁移。

### Stage 4：Session semantic heap inspect

状态：pending

- 用单一 inspect 实现 active root、Summary、Turn、Action collection 和 Action leaf 展开；
- 让 continuation 只服务同一节点的 direct children 或 oversized leaf；
- 在 Action collection 中直接交付有界失败 feedback/result，成功 result 保持 leaf-on-demand；
- 删除模型 recall executor、旧 detailed history/actions/trace 查询和相关配置；
- 验证 inspect 只产生当前 Turn foldable ActionResult，不修改固定 Session Background 或 Manifest。

### Stage 5：Endpoint 与前端表面收缩

状态：pending

- 删除三条 Session REST、OpenAPI、status 字段、Endpoint tests 和对接文档声明；
- 删除 visualization History/Session Explorer、client/types/hooks/tests/styles；
- 保持 Chat model events、Background、Phase/Action 和 Workspace 无回归；
- 更新 visualization 当前设计与计划索引，历史 done 记录标记为 superseded。

### Stage 6：文档、发布与验收

状态：pending

- 更新 AGENT 项目规约和当前任务状态；
- 重写 Context、Session、Action、Endpoint 设计文档；
- 同步唯一 init 模板中的 Catalog/Home/config，删除失效资源；
- 更新 release wheel 内容断言，不保留 context/session domain 或 Session Explorer 协议；
- 完成定向测试、全量 pytest、类型检查、frontend test/build、compileall、diff check 和 clean-source wheel 验收；
- 全部完成后将本文件改名为 `20260725-done-context session semantic heap and application surface refactor plan.md`。

## 测试重点

测试使用构造的 typed Turn/Action 数据，不读取 `reference/running_trace`，也不建立与特定真实轨迹绑定的 fixture。

1. Context 只按完整 Cycle 压缩，head/branch/leaf refs 能逐层恢复，inspect 不改变 heap topology；
2. Context leaf continuation 不能用于其它 ref/Turn，压力恢复先折叠 inspect overlay，再移动 hot entries；
3. 模型结果不含 cursor/index/offset/digest/revision/coverage/cycle/phase/stage；
4. Session v4 Turn record 是 Background、inspect、Memory facts 的唯一输入，三种投影对 ask/answer/action outcome 一致；
5. malformed Action pairing 在 completion 时失败，不产生部分 record；
6. Summary 递归收缩、deterministic ref、幂等重放、orphan Turn reconciliation 和 archive facts 保持成立；
7. Session inspect 必须按 root/Summary/Turn/Action collection/Action leaf ref 逐层导航，continuation 不能跨节点；
8. 失败 Action header 直接包含有界失败证据，成功 result 只在 leaf inspect 出现；
9. Catalog 只暴露 Core 下两个 inspect，不存在 Context/Session domain、recall/fold 或对应 HOW mount；
10. Endpoint OpenAPI 不含 Session REST，visualization 不含 History tab/client/state，Chat model MessageStack 与 Workspace 仍正常；
11. 新 init 和 wheel 只包含当前 Catalog/Home 资源，不携带已删除协议文件；
12. 既有 Workspace/Script/Shell cursor 行为完全不变。

## 非目标

- 不统一 Workspace、Script、Shell 的 cursor；
- 不建立 Context/Session 共用 heap class、跨模块 node schema 或全局 history service；
- 不把 inspect 内容写回 Background、WorkingContext、Session graph 或 Workspace；
- 不增加前端 Session/Context snapshot、持久 LLM task replay 或审计数据库；
- 不实施 Session Turn 之间的逻辑符号/语义地图；该方向只作为未来 Session 演进背景；
- 不兼容或迁移 schema v3 Session 数据；
- 不为没有内部 LLM Task 的 inspect action 建立 Action HOW。

## 完成标准

- Context 和 Session 对模型呈现同一种 ref-driven、heap-first 探索习惯，但保持各自 owner、生命周期和压缩实现；
- continuation 只表示同一节点未完成的有界展开，模型不再看到 pager 或完整性实现字段；
- 当前 Turn canonical trace 只存在于 Context 运行时，跨 Turn Session 只保存 immutable business facts；
- Session Background、inspect、Memory facts 没有重复持久事实或平行 projector；
- Core domain 是唯一历史 inspect 选择入口，Catalog/HOW 边界简洁且不污染嵌套 LLM Task；
- Endpoint 和 visualization 不再维护独立 Session Explorer，前端只呈现真实 MessageStack/Observation 与 Workspace；
- 不引入兼容层、第二事实源、万能路由器或为前端诊断服务的后端业务结构。
