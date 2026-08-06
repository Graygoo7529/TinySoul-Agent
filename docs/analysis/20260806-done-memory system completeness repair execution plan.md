# Memory 系统完整性修复执行计划

## 状态

- `done`：主体修复、文档复核与全量验收已完成
- `done`：修复事务恢复、检索边界、Maintenance 暂存视图与引用校验
- `done`：收敛 embedding 凭据身份并写入本地专用环境变量
- `done`：Memory/Maintenance/Infra/App 定向测试、Full 和 typecheck 已通过

## 背景

`20260806-done-memory system redesign execution plan.md` 已完成 Memory 三层语义、五类
持久 Link、User Action、Maintenance Turn、触发路径与 embedding 基础设施的主体实现。
本轮重新加载根 `AGENT.md`、原执行计划、当前设计文档和代码后，确认整体模块划分与
设计方向合理，但部分实现只覆盖了正常路径，尚未完整满足原计划已经声明的边界。

本计划不是再次重构 Memory，也不新增第二套索引、持久状态或 Maintenance 流程。目标是
修正现有协议之间的不一致，使 Markdown 唯一业务事实、owner 一致性边界、有界渐进发现和
先检索后维护真正落到所有执行路径。

## 保持不变的语义

1. User Turn 只通过 `memory.memorize` 修改当日活动 `Memory.md`；daily、entity、concept、
   fact、note 只由 Memory Maintenance Turn 维护。
2. User 与 Home Maintenance Context 使用不可逐出的
   `memory:current + optional memory:latest`；Memory Maintenance Context 使用不可逐出的
   `memory:target + optional memory:latest`。
3. 自动与手动显式触发进入同一个 Memory Maintenance Turn。自动路径额外以目标 daily
   缺失防止重复触发；手动显式目标允许复查和修改已有 daily。
4. `relations` 只指向 entity/concept，`evidence` 只指向 daily/fact/note；已有持久 Link
   不 hard delete，非 active 文档保留非空迁移说明和非 daily redirect。
5. Markdown 是唯一业务事实；catalog、backlinks、lexical 数据和 embedding cache 均为
   可删除重建的派生数据。
6. 不引入 graph node、aliases、第二份正文或独立 activity 账本等新业务概念。

## 实现核对结论

### 1. Transaction journal 存在两个崩溃窗口

当前 `MemoryTransactionService._prepare()` 直接创建最终
`transactions/<transaction-id>/`，逐个写 staged Markdown，最后才写 manifest。进程若在
manifest 完成前退出，下一次 `recover()` 会把这个半成品目录当成可恢复事务并因 manifest
缺失而阻断启动。

全部目标文档写入后，当前实现直接递归删除最终事务目录。若清理中途退出，残留目录同样
可能已经缺少 manifest 或 staged 文件，下一次恢复不能区分“尚未提交”和“已提交、只待
清理”。这与原计划要求的每个 operation、complete 和 cleanup 中断后均可幂等前滚不一致。

### 2. `memory.inspect` 只约束 items，没有约束完整 ActionResult

query/link 两种模式只用 `page_max_chars` 计算 `items`。link 模式仍额外返回完整 outgoing、
backlinks 和一部分 related 数组；高连接文档可以绕过整页预算。Continuation 只绑定 catalog
generation 和 offset，未绑定 query/link、kinds 等请求身份，同一个 token 可以被错误地用于
另一条检索。

Maintenance 的 `inspect_sources` 只分页 Session facts，却在每一页返回全部 Workspace
resource metadata，也存在相同的无界结果问题。

### 3. Catalog 尚未实现原计划的有限 tie-break

当前目录条目没有携带 `updated_on`、activity 和 fact confidence，query 排序只有
lexical/semantic 总分和 Link 字符串。原计划明确相关性是主排序，activity、recency 和 fact
confidence 只能在相关性相同时作为有限 tie-break。当前实现既未消费这些字段，也未把
activity 投影到 inspect item。

### 4. Maintenance 只对 exact staged Link 提供局部可见性

当前 Maintenance `inspect` 仅在请求 Link 已经 staged 时直接返回该文档；query inspect、
backlinks、related 和其它 Link 的一跳探索仍读取旧 catalog。因此同一 Maintenance Turn
新建或重写的文档不能被后续 query 正确发现，新关系也不会进入 backlinks。

同一 Link 再次 `stage_rewrite` 或 `stage_redirect` 时，当前实现重新读取磁盘文档并直接覆盖
`draft.changes[link]`。这会丢失先前暂存修改，也没有用实际暂存 digest 证明模型看到的是
当前草稿。`stage_create` 取得的 query inspection ref 还没有保留 `kinds`，不能验证“先检索
相同 kind 或包含该 kind 的集合”。

### 5. Relation 终点约束只应用于 active note

文档 schema 已允许 entity、concept、fact、note 都持有 `relations`，原设计要求旧 relation
可以保留，但必须沿 redirect 最终解析到 active entity/concept。当前 catalog 只校验 active
note，因此 active entity/concept/fact 仍可能指向最终为 active fact/note 或未有效迁移的
entity/concept。

### 6. 核对时 Embedding 凭据身份混用

当前 Infra 与项目模板使用 `api_key_envs = ["GLM_API_KEY", "ZHIPU_API_KEY"]`。这会让
embedding 复用模型凭据，并保留没有明确 owner 的 fallback。确认后的身份应为：

- `GLM_API_KEY`：只用于 GLM LLM provider；
- `GLM_EMBEDDING_API_KEY`：只用于顶层 `[embedding]`；
- `ZHIPU_API_KEY`：从当前配置、模板、测试和设计说明中移除，不作为任何 fallback。

本地 `.env` 可以同时保存两种用途的 key，但 TOML、日志、测试和文档不得保存真实值。

## 修复设计

### A. Transaction 使用目录身份表达可恢复阶段

事务目录改为三个明确状态，状态切换只使用同一 filesystem 内的原子 rename：

```text
memory/.tinysoul/transactions/
  .preparing-<transaction-id>/   # 尚未发布，绝不修改业务 Markdown
  <transaction-id>/              # 已发布，可幂等前滚
  .completed-<transaction-id>/   # 业务 Markdown 已全部提交，只待清理
```

Prepare 先在 `.preparing-*` 中写全部 staged 文档和 manifest，重新读取并验证 staged digest、
schema、目标日、字符上限和最终文档集合，然后原子 rename 为正式 `<transaction-id>`。只有
正式目录能够进入 target write 阶段；因此 `.preparing-*` 即使不完整也没有业务副作用，恢复
时可在严格校验目录身份后清理。

Apply 在第一次目标写入前完成全部 CAS 和最终文档集合校验。所有目标均为 new digest 后，
把正式目录原子 rename 为 `.completed-*`；之后递归清理。恢复时：

1. 清理合法 `.preparing-*`；
2. 对正式目录重做完整校验并幂等前滚；
3. 清理合法 `.completed-*`；
4. 其它文件、symlink 或非法名称仍视为 Memory invariant failure。

这样 cleanup 中断只留下可再次清理的 completed 目录，不再把半清理目录误判为待提交事务。
事务 manifest 保留目标日、base generation、每个 Link 的 old/new digest；不新增业务状态库。

### B. Inspect 将完整 payload 作为唯一分页预算

`MemoryInspectResult` 收敛为一个有序、分页后的 `items` 集合。每个 item 用 `reasons` 明确
`outgoing`、`backlink`、`lexical_related` 或 `semantic`，不再同时返回完整 Links 数组。
link 模式额外只返回计数：

```text
outgoing_count
backlink_count
related_count
candidate_count
continuation
```

计数用于判断是否继续探索，不复制未选中的 Link。`page_max_chars` 对最终 JSON payload
整体计费，包含 items、计数、continuation 和固定 metadata；任何模式都不能通过附加字段
绕过预算。

Continuation 改为 owner 生成的 opaque token，至少绑定：catalog generation、inspect mode、
canonical request identity 和 next offset。Request identity 由 query/link、kinds 和其它实际
影响候选集合的字段确定；token 用到不同请求时返回局部 stale/invalid failure。

Maintenance `inspect_sources` 增加明确的 `source=session|workspace` 参数，同一调用只分页一个
source：Session 返回 facts，Workspace 返回 resource metadata。`memory:target`、latest 和
existing daily 继续由 Background/exact recall 提供，不在每一页复制正文或整个 manifest。

### C. 排序只在相关性相同时使用持久元数据

`MemoryCatalogEntry` 从已解析 Markdown 投影以下已有事实，不新增持久字段：

```text
updated_on
last_activated_on
activation_count
confidence (optional)
```

lexical 与 semantic 继续决定主相关性。稳定排序使用显式 tuple：相关性降序，然后在相同
相关性内按最近 activation/updated date、activation count、fact confidence 和 canonical Link
稳定排序。Activity/count 不加入可累积的大权重，不引入衰减配置，避免高频但不相关文档
越过语义匹配。

Inspect item 返回有界 activity、updated date 和可选 confidence metadata，帮助模型在多个
同等相关候选中选择需要 recall 的 Link。

### D. Maintenance 在 Memory owner 的暂存文档集合上检索

Memory owner 提供从“当前 Markdown + draft changes”构建临时 catalog snapshot 的内部能力；
它复用同一 codec、引用校验、backlinks、lexical 和可选 semantic 逻辑，不持久化，不建立
第二份事实。Maintenance 的 inspect/recall 全部基于该 snapshot，因此 staged create、rewrite、
redirect 会立即影响 query、Link exploration、backlinks 和 exact recall。

`MemoryInspectionRef` 增加 canonical request identity 与 `kinds`，并为每个涉及 Link 绑定
实际 Markdown digest。暂存文档使用框架渲染后的真实 SHA-256，不再使用字符串 `staged`。
Ref 仍不绑定整个 draft revision：无关 Link 的 stage 不应让已有 ref 失效；对同一 Link 的
后续 mutation 则必须重新 recall 当前暂存版本。

`stage_create` 只接受未筛选 query ref，或 `kinds` 中明确包含待创建 kind 的 query ref。
同一 Link 已 staged 时：

- 后续 rewrite 必须持有当前暂存 digest，修改当前暂存文档，同时保留最初的
  expected-absent/expected old digest CAS；
- redirect 的 source 必须是已有持久 Link，且 ref 绑定当前暂存 source digest；target 可以是
  本轮 staged active 文档；
- 旧 ref 与当前暂存 digest 不匹配时返回局部 stale failure，不静默覆盖草稿。

Preview 继续绑定完整 draft revision，并在“当前 Markdown + 全部最终 draft changes”上统一
校验。Inspection ref 不承担审批或持久 review 状态。

### E. Relation 统一验证最终 entity/concept 语义

对每个 active entity、concept、fact、note 的每条 relation：

1. 允许直接指向 active entity/concept；
2. 允许指向旧 entity/concept Link，但 redirect chain 必须在 hop limit 内终止于 active
   entity/concept；
3. 最终为 daily/fact/note、非 active 且无有效 redirect、缺失或 cycle 均为 invariant failure。

Evidence 继续保存历史来源，可指向 daily/fact/note 的 active 或非 active Link；不强制把
证据重写到 redirect 终点，也不允许 `redirect_to` 指向 daily。

该校验用于启动 catalog rebuild、单文档 write、changeset preview、transaction apply/recover
的最终文档集合，避免恢复路径绕过正常提交校验。

### F. Embedding 使用单一专用环境变量

本轮已将 `EmbeddingSettings` 与 `[embedding]` 配置改为：

```toml
[embedding]
api_key_env = "GLM_EMBEDDING_API_KEY"
```

采用与 Kimi Search 相同的单变量 owner 配置，不保留 `api_key_envs` 列表或旧键兼容分支。
App 只通过 `ConfigEnvironment.runtime_env` 解析该变量。Standard/development 的 GLM LLM
provider 改为只使用 `GLM_API_KEY`；`.env.example` 增加空的
`GLM_EMBEDDING_API_KEY=` 并删除 `ZHIPU_API_KEY=`。当前设计文档、已完成计划中的配置示例
和相关测试同步更新；历史 archive 文档不作为当前配置事实，无需批量重写。

## 接口预览

```text
EmbeddingSettings.api_key_env: str

MemoryCatalog.inspect(request, documents=optional draft documents)
MemoryInspectResult:
  mode
  items
  outgoing_count
  backlink_count
  related_count
  candidate_count
  continuation

maintenance.memory.inspect_sources:
  source: session | workspace
  offset
  limit
```

具体方法名可在实现时按现有类职责调整，但所有权不变：临时 catalog 仍由 Memory 构建，
Maintenance 只持有 draft 和 inspection refs，Action executor 不自行解析 Markdown 或计算
backlinks。

## 具体改动预览

以下预览把修复落到现有模块、类和方法，不改变 User/Maintenance Turn 的触发语义，也不
把临时计算结果写入 `memory/`。

### 1. `tinysoul/memory/catalog.py` 与 `engine.py`

- 保留 `MemoryCatalog` 为正向引用、backlinks、lexical 和 semantic 的唯一 owner；将当前
  `rebuild()` 内的“由 StoredMemoryDocument 建立 entries”提取为同一类的内部构造路径，
  增加接受 `documents` 的临时 snapshot 方法。传入的文档覆盖同 Link 的磁盘文档，但不
  改变进程级 `_snapshot`。
- `MemoryEngine.inspect(request, documents=())` 和
  `MemoryEngine.recall(link, documents=())` 继续是 Maintenance 的唯一读取门面；User
  调用不传 `documents`。Maintenance 每次 action 执行前从 draft 构造 tuple，避免
  `maintenance.memory` 直接访问 Store 或 Catalog 私有字段。
- `MemoryCatalogEntry` 从已解析文档投影 `updated_on`、`last_activated_on`、
  `activation_count`、可选 `confidence`；`MemoryInspectItem` 返回有界 activity/date/
  confidence metadata。主分数仍来自 lexical/semantic，只有同分时使用这些字段和 Link
  稳定排序。
- `MemoryInspectResult` 删除完整 `outgoing/backlinks/related` Link 数组，改为三个 count；
  Link 模式的所有候选仍通过 `items.reasons` 分页返回。增加统一 `to_json()`，由 catalog
  计算完整结果大小，保证 items、counts、candidate_count、continuation 一起不超过
  `page_max_chars`。
- continuation token 绑定 catalog generation、mode、query 或 Link、kinds、limit 和 next
  offset。解析时先验证请求身份，再使用 offset；跨请求复用返回局部 contract failure。
- `_validate_stored()` 对每个 active entity/concept/fact/note 的 relations 执行相同的
  redirect chain 终点校验；该方法同时被启动 rebuild、单文档写入、changeset prepare 和
  transaction apply/recover 的最终文档集合调用。

### 2. `tinysoul/maintenance/memory/actions.py`

- `MemoryInspectionRef` 增加 canonical request identity、kinds 和实际 digest 映射；暂存
  文档 digest 使用 `MemoryDocumentCodec.stored(document).digest`，不再使用 `"staged"`。
- 增加一个仅供 controller 使用的 draft document tuple helper。`inspect`、`recall`、
  `_inspection_ref` 和 exact ref 校验都使用当前 tuple；query、link、backlinks、related
  因此看到同一 Turn 内的最终暂存文档集合。
- `stage_create` 保留现有“必须先 query inspect”规则，并检查 ref 的 kinds 为空或包含待
  创建 kind。它不要求 query 必须命中，是否新建仍由模型结合 recall 判断。
- `stage_rewrite` 若目标已有暂存 change，必须使用当前暂存 digest；重写后的 change 保留
  原始 `expected_absent` 或磁盘 `expected_digest`，只替换文档内容，不静默覆盖未被 recall
  的草稿。没有暂存 change 时维持现有磁盘 digest CAS。
- `stage_redirect` 的 source 仍要求已有持久 Link；target 可为当前暂存 active 文档。源和
  目标 ref 都必须绑定当前实际 digest，redirect 状态、同 kind 规则、非 daily 目标和环路
  校验继续由文档/Memory owner 负责。
- `preview` 传入同一 draft tuple，先完成最终引用校验，再生成 changeset；任何 stage 使
  `preview_revision` 失效，但无关 Link 的 inspection ref 不因全局 revision 变化而失效。
- `inspect_sources` 的参数增加 `source=session|workspace`（缺省保持 session），同一调用
  只返回一种资源的当前页、`offset`、`has_more` 和 `total_count`。Workspace 页只返回有界
  manifest 摘要，完整正文继续由 `read_workspace` 按 Link/digest 读取。

### 3. `tinysoul/memory/transaction.py`

- `_prepare()` 在 `.preparing-<id>` 中写 staged 文件和 manifest，完成 codec、digest、
  source CAS、最终文档集合校验后，使用同目录 `replace()` 发布为 `<id>`。正式目录发布
  前不会写任何业务 Markdown。
- `recover()` 严格识别 `.preparing-*`、`<id>`、`.completed-*` 三种目录；前者可清理，正式
  事务执行 `_apply()`，后者只做清理。未知名称、symlink、半结构目录仍为 invariant failure。
- `_apply()` 在第一份目标写入前通过 Memory owner 校验回调验证全部暂存文档和当前 Store，
  再按 stable order 执行 CAS/atomic replace。所有目标达到 new digest 后把正式目录原子
  rename 为 `.completed-*`，清理失败不会丢失可恢复身份。
- `MemoryEngine` 在装配 `MemoryTransactionService` 时注入自身 catalog 的最终文档校验
  回调；recover 完成后才重建进程 catalog。事务服务不解释 Memory kind 或关系业务。

### 4. Action catalog、设计文档与测试

- 更新 `memory.inspect` 和 `maintenance.memory.inspect_sources` 的 schema/description，
  明确 count、continuation、source 参数和有界结果，不新增 User action。
- 同步 `docs/design/memory.md`、Memory Maintenance prompt 和
  当前执行计划；旧完成记录只保留基线完成事实，不再把本轮 pending 修复描述为已完成。
- 聚焦测试覆盖：完整 payload page budget、continuation request binding、activity tie-break、
  staged query/backlinks/recall、same-Link staged CAS、四类 relation 终点、三种事务目录
  状态及每个恢复窗口、Session/Workspace 独立分页。

### 5. 实施顺序与提交边界

1. 先完成 catalog result/validation 和 Maintenance draft tuple，使所有新行为仍停留在
   内存中并可由 focused tests 验证。
2. 再接入 transaction preparing/ready/completed 和最终文档校验，先通过故障注入测试后
   才替换旧清理逻辑。
3. 最后更新 Action catalog、设计文档和验收记录，运行 Memory/Maintenance/Infra/App 定向
   测试、Full 和 typecheck。每一步都保持 `MemoryEngine`、`MemoryMaintenanceActionController`
   和 `MaintenanceEngine` 的现有 owner 边界。

## 实施阶段

### Stage 1：修复派生检索与 Maintenance 草稿协议（done）

- 收敛 inspect result、完整页预算、request-bound continuation 和 source 分页；
- catalog 投影 activity/recency/confidence，并按有限 tie-break 排序；
- 建立 draft-aware 临时 catalog，补齐 ref kinds、真实暂存 digest和同 Link mutation CAS；
- 对全部 active 知识文档统一验证 relation redirect 终点；
- 更新 Memory/Maintenance focused tests 和 Action 语义。

### Stage 2：加固事务发布、完成标记与恢复（done）

- 引入 preparing -> ready -> completed 的原子目录状态切换；
- apply/recover 在首个 target write 前验证全部 staged 文档、CAS 和最终引用集合；
- 覆盖 staged write、manifest、publish、每个 target、complete rename 和 cleanup 中断；
- 确认 startup recover 后才重建 catalog 并向新 Turn 暴露 Memory。

### Stage 3：配置复核、文档同步与全量验收（done）

- 复核已完成的单一 `GLM_EMBEDDING_API_KEY` 配置与当前 `ZHIPU_API_KEY` 清理结果；
- 更新项目配置模板、`.env.example`、设计文档、执行记录与配置测试；
- 运行 Memory/Maintenance/Infra/App 定向测试、Fast、Full、typecheck；
- 重新核对 `AGENT.md`、当前设计文档与实现，完成后将本计划标记并重命名为 done。

## 验证结果

- Memory/Maintenance 定向测试：`16 passed`；
- Full：`864 passed, 2 skipped, 21 deselected, 1 warning`；
- typecheck：`All checks passed!`；
- `git diff --check`：通过；
- embedding 配置只声明 `GLM_EMBEDDING_API_KEY`，GLM LLM provider 仍只声明 `GLM_API_KEY`；真实密钥仅存在于本地 `.env`，未写入 Git 跟踪文件。

## 测试矩阵

### Inspect 与排序

- query/link 的完整 JSON 均不超过 `page_max_chars`；高 backlinks 文档不会无界返回；
- continuation 不能跨 query、Link 或 kinds 复用，catalog generation 变化后失效；
- 多页无重复、无遗漏，排序稳定；
- 相同相关性下 activity/recency/confidence 生效，不相关高 activity 文档不能越级；
- Maintenance Session/Workspace sources 独立分页。

### Draft 与引用

- staged create 可被同 Turn query、inspect、recall 和 backlinks 发现；
- staged rewrite 后旧 ref 失效，新 ref 可继续精炼且保留原始 CAS；
- query ref kind 不匹配时不能 create；
- unrelated stage 不使 exact ref 失效，preview 后任何 stage 仍使 preview revision 失效；
- entity/concept/fact/note relation 都必须最终解析到 active entity/concept；
- staged target redirect、redirect cycle/hop 和 evidence 历史 Link 语义正确。

### Transaction

- preparing 的每个写入点退出后可恢复且没有业务 Markdown 变化；
- ready 的每个 target operation 退出后幂等前滚，daily 始终最后；
- ready -> completed 前后退出均可恢复；
- completed 的部分清理可重复完成；
- 非法 transaction entry、symlink、digest/CAS/引用冲突继续阻断提交。

### Credential

- embedding enabled 只读取 `GLM_EMBEDDING_API_KEY`；缺失时报告
  `embedding.api_key_env`；
- `GLM_API_KEY` 不被 embedding 读取，仍可供 GLM LLM provider 使用；
- 当前代码、配置、模板、设计和测试不再使用 `ZHIPU_API_KEY`；
- 真实 key 不进入 Git、日志、测试输出、文档或 embedding cache。

## 完成判据

1. 原计划声明的 transaction crash roll-forward 在 prepare、apply、complete 和 cleanup
   各窗口均成立。
2. inspect 的所有模型可见结果严格有界，continuation 只能继续原请求。
3. Maintenance 对当前 draft 的 query、引用和 digest 认识一致，不会静默覆盖同 Link 的
   暂存修改。
4. 所有 active 知识文档的 relations 最终解析到 active entity/concept。
5. 排序保持相关性优先，并真实使用 Markdown 已有的 activity、updated_on 和 confidence。
6. Embedding 只使用 `GLM_EMBEDDING_API_KEY`；GLM 模型 key 与 embedding key 完全分离。
7. 当前设计文档、配置模板、实现和测试一致，Full 门禁与 typecheck 通过。

## 非目标

- 不改变已确认的自动/手动 Maintenance 触发语义；
- 不新增 daily append、`--rebuild`、启动时自动 LLM 维护或 backlog 批处理；
- 不建立数据库、持久检索索引、持久 draft 或 inspection 审批状态；
- 不让 User Turn 修改五类持久 Memory 文档；
- 不在默认测试中调用真实 embedding provider。
