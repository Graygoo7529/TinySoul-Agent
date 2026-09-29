# Visualization 后端实施 Review

> 日期：2026-09-28。Review 状态：done；R1–R4 后续改进已于 2026-09-29 完成。
> 核对代码：`5993913`，主要实施提交 `d3d0bf2`，计划提交 `4093b94`。
> 核对依据：重新读取的根目录 `AGENTS.md`、`docs/analysis/done/20260928-done-visualization-backend-support-plan.md`、当前模块设计、Endpoint 文档与实际代码。
> 本文只记录评审和补齐建议，没有修改业务实现，也没有重新实施前端。

## 1. 结论与完成判断

**整体架构方向合理，主要后端能力已经落地，可以承接下一阶段前端建设；但还不能把这份后端计划按全部交付完成验收。** 剩余问题集中在页面导航的正常功能与契约交接，不需要新增一轮架构重构。

以上是 2026-09-28 初始 Review 结论；R1–R4 已由后续执行计划完成并在本文末复核，当前 Review 可归档。

本次实现沿用了 Agent 根调度、插件 owner、generation/day lease、Action/ModelUse、Search/Disclosure、Session 事实与旁路 Observation。没有发现为了页面新建第二套 Search、聊天事实库、模型执行体系或运行调度器。配置 apply/presets、结构化问答、只读浏览、运行查询的主要路径与既定设计一致。

建议先补齐 R1–R3 的正常导航缺口和 R4 的接口交接，再冻结前端接入契约。前端布局、视觉与独立组件可以并行准备；Context 导航、统一 ResourceRouter 和 API 类型层应在这些问题修复后接入，避免前端自行猜测或修补后端身份。

| 编号 | 优先级 | 当前缺口 | 涉及计划 |
| --- | --- | --- | --- |
| R1 | P2，验收前修复 | Context 的 `root_refs` 实际返回路由前缀，不能直接 inspect | B3 / API-09 |
| R2 | P2，验收前修复 | Resource resolve 不认识压缩 Trace 节点，动态 Memory 定位丢失 fragment | B3 / API-18 |
| R3 | P2，验收前修复 | Home 浏览产生的 direct refs 与 owner 的规范链接规则不同 | B4 / API-10、18 |
| R4 | P2，交接前补齐 | 新响应缺少完整机器可核对契约和实际生成样例，交接说明仍有旧流程 | B0、B7 |

这里的 P2 表示应修正的功能或交付缺口。没有把特殊故障恢复、任意插件拔除、执行安全隔离或全局事务治理扩充为本轮要求。

## 2. 已完成并应保留的设计

### 2.1 配置与运行方案

`infra/config/editing/controller.py` 的 apply 在同一个发布流程中完成候选编译、准备 generation、提交文件与发布；沿用既有 transaction/activation 能力。失败处理区分发布前撤回与发布后的退休诊断，没有要求前端逐字段保存后再猜测激活结果。

active/saved 是不同事实：active 来自成功发布的配置，saved 重新读取配置源。方案保存到 `configs/presets/*.json`，没有变成另一层运行时覆盖 source。完整替换 LLM models/tasks/用途绑定，结合受管 retrieval 字段和可选预算，符合命名方案的范围。Provider 凭据、知识库 embedding use、检索能力开放范围等仍留在基础配置中。

`family/collapsed` 已进入 LLM 模型声明、解析、catalog 和模板，是展示属性。当前 Action 继续按 descriptor/consumer/implementation/target 表达模型用途；没有恢复 `llm_action` 专用执行器，也没有把 Reflection 重新拆成另一套模型链。Embedding/JEV 仍使用专用能力与 Provider 绑定；生图未增加假执行器，符合仅预留前端归属的决定。

### 2.2 问答与历史

`kernel/interaction.py` 建立了共用的 QuestionContent/QuestionAnswer。`core.ask` 支持结构化内容和受限代码块协议，choice 回复转换为可读选项文字及补充意见，输入事实中保留类型化回答。

活动交互读取 Context facts，尚未安装的输入读取 Inbox；queued 根请求单独呈现。问题与预算保留各自身份，不合成新的“恢复”命令。Turn 完成后进入 Session 正式交互投影；前端应整轮替换活动视图，不能把完成后的 Session 再追加一次。

这条实现路径符合“一套事实，按生命周期投影”。真实 SDK/HTTP 测试覆盖追加、提问、回复、补额、完成以及从 Session 恢复回答。

### 2.3 Context、Session 与资源读取

Context installed overview/body 使用已安装段 render，UI inspect 调用原 disclosure 路径，没有调用 ActionRunner、seal 或模型回载保护消费。关闭后的 live Context 不再冒充历史快照。Session 增加只读 view，页面 GET 不用 reconcile 来整理历史事实。

Home 区分 actual/effective，变化与 diff 读取没有发放 review 写权限。Memory 区分活动 Memory.md 与持久文档；持久文档 inspect 读取原文并披露 redirect chain，不用重定向目标正文覆盖原文。Workspace 增加当前/归档读取、分页、编辑完整正文和 Range/blob 流；归档身份携带 day。

这些所有权选择正确，剩余问题在导航入口和链接投影，见 R1–R3。

### 2.4 Search 与运行观察

页面 Search 复用 owner SDK 服务、正式 request parser、retrieval policy 和 SearchPage。SDK 搜索只接受局部上下文，不借用活动 Turn 的 Context。既有 query/backlinks/directory 来源与 filter/select/rerank 管道、真实候选预览、独立 lexical/embedding 通道及冻结续页没有被另写一份。

Job detail/output 读取同一个 Job backend，输出续接不消费父 Agent 通知；Turn 收尾后不把已回收 Job 包装成永久历史服务。ACP/MCP 页面读 owner 状态，MCP GET 不隐式连接，refresh 是显式 I/O。

模型 provenance 在 MessageStack/TaskPrompt 真正组装时形成；LLM 层负责转送，不解释业务语义。EventFilter 支持按 Turn/Task/Call/Search/step 查询，游标表示扫描过的全局位置。事件用于过程呈现与刷新，不取代持久事实。

### 2.5 异常处理与代码组织

主要新增路径沿 owner 错误、SDK 不可用状态、Endpoint 有限 HTTP 映射组织。局部引用错误、Context 关闭、Search 失效与运行不可用能够区分；没有发现需要为正常使用增加大规模防御性恢复链的理由。

`agent/services.py` 现在承担较多查询组合，但大部分仍转交 owner，文件长度本身不是架构不合格的证据。真正应收口的是 R2/R3 暴露的资源身份规则重复：具体 ref/Link 语法应由 owner 的小型解析能力维护，SDK 显式组合，Endpoint 转送。不要因为这个问题再构建一个拥有全部内容和操作的通用资源 Gateway。

## 3. R1：Context 根入口不能直接打开

**状态：done。** 后续计划已由 `NavigableSegment` owner roots 和 overview 投影完成。

位置：`tinysoul/kernel/context/engine.py:842`；Trace descriptor 位于 `kernel/context/builtin/core.py`，Session descriptor 位于 `plugins/session/projection.py:241`。

当前代码：

```python
"root_refs": list(descriptor.ref_prefixes)
```

`ref_prefixes` 是路由识别范围，不是节点身份。一个活动 Turn 的实际 HTTP 复现：

| 概览字段/请求 | 实际结果 |
| --- | --- |
| session.root_refs | `["session:"]` |
| GET context/inspect，ref=session: | 404 `unknown_ref` |
| trace.root_refs | `["turn:trace"]` |
| GET context/inspect，ref=turn:trace | 422 `invalid_ref` |
| 同一活动 Context inspect session:map | 200 |
| 同一活动 Context inspect turn:trace@review-main | 200 |

前端从右上 Context 页面点开 Session map 或 Trace 根节点就会遇到这个问题。它与压缩规模、故障恢复无关。

**建议修订：**

1. 保留 descriptor.ref_prefixes 的路由职责，不把它改成某个 Turn 的完整根节点，否则反而破坏对子节点的路由。
2. 从已打开 segment 的公开、纯读取导航投影取得真实 roots。可以为具有 inspect 能力的段增加一个窄的 roots/navigation 方法：Session 提供 `session:map`，Trace 提供自身 `head_ref()`；不要求所有段都实现空导航。
3. Context overview 只汇总 owner 的 roots。Background 的 available/loaded/protected selection 继续沿原能力投影，不为 UI 发起 load。
4. Kernel 不硬编码 Session 语法；前端也不自行拼接这些根节点。

**最小验收：** 从 overview 取得的每个可 inspect root，直接传入同一 Turn 的 inspect，均返回成功或有明确定义的空内容；读取前后 Context 已安装内容和保护状态不变。至少覆盖 Session 与有压缩节点的 Trace。

## 4. R2：统一 ResourceLocator 尚未覆盖真实 ref，并丢失动态锚点

**状态：done。** 后续计划已由 Trace owner identity resolver、动态 locator fragment 保留完成。

### 4.1 压缩 Trace 节点被当作无 owner

位置：`tinysoul/agent/services.py:695`；实际节点生成位置 `kernel/context/builtin/trace.py:876`。

解析入口只识别 `turn:trace@<turn_id>`，而 Trace owner 的压缩节点生成格式是：

```text
turn:trace/<turn_id>/<node_id>
```

本次通过真实 `TurnTraceHeap` 追加文字并 compact，取得 owner 产生的节点 ref。owner.inspect 成功；将同一 ref 交给 `GET /v2/resources/resolve` 得到 422 `resource.invalid_reference`，说明为 “Resource has no supported owner”。

因此，从折叠层级或其线索点击节点时，统一 ResourceRouter 无法沿同一入口继续导航；目前只能迫使前端特殊绕过 resolver。

**建议：** 在 Trace owner 提供共用的 ref 身份解析，覆盖 head、entry/fact 及 branch/leaf 等实际公开格式，返回 turn 身份与原 ref。SDK 显式调用该解析能力，保留原节点，不将叶子归一化成 head。继续保留“历史 live Context 不保证可读”的已有边界，不因此新建历史 Context 数据库。

### 4.2 Memory 动态定位丢失 fragment

位置：`tinysoul/agent/services.py:649` 及显式 day 分支 `:658`。

同一活动 Turn 的请求：

```text
GET /v2/resources/resolve?reference=memory:current%23notes&turn_id=review-main
```

返回 200，但 locator 只含 `memory:current` 和原 day，`#notes` 仅残留在 resolved_from。前端按正式 locator 跳转时锚点消失。显式 day 绑定 current/target 的分支也丢掉 fragment。

**建议：** 先使用原绑定解析资源，再把请求的 fragment 应用到返回的目标 link/ref；不要原地修改共享 binding。保持原 day，不使用当前 latest 重新绑定。片段归属前端导航或 owner 披露沿现有协议，不扩充额外全局锚点库。

**共同验收：** owner 真实生成的 Trace head/entry/压缩节点能够 resolve；来源 Turn/day 保留；动态 Memory 的有/无 fragment 请求保持同一绑定，只有片段不同。所有支持的 ref 格式在接口契约中有代表性样例。

## 5. R3：Home direct refs 没有复用 Home 自身的规范化

**状态：done。** 后续计划已由 Home canonical markdown reference helper 完成。

位置：`tinysoul/plugins/home/engine.py:449`、`:459`。同文件 `resolve_relative()` 已有正确的 layout 映射。

`browse_content()` 使用 `_direct_refs()`，后者只调用通用 `relative_reference()` 拼出路径型 `home:` 链接；`resolve_relative()` 则进一步通过 `layout.link_for_relative()` 生成 HomeTopLink/HomePromptMountLink/资源链接。两条正常读取路径给出不同身份。

复现：在 `home:skills_action:core/answer` 正文放置指向 Workspace domain guidance 的正常相对 Markdown 链接：

```markdown
[Workspace guidance](../../skills_domain/workspace/DOMAIN.md)
```

| 读取方式 | 返回/结果 |
| --- | --- |
| GET home/content 的 metadata.direct_refs | `home:skills_domain/workspace/DOMAIN.md` |
| 将上面的 direct ref 交给 resources/resolve | 422 `resource.invalid` |
| 原始相对链接 + origin_link 交给 resources/resolve | 200，`home:skills_domain:workspace` |

普通 agent/Skill top 的相对链接也可能返回路径型别名而非 catalog 中的 canonical top。guidance 的例子进一步证明，这不只是字符串风格差异，而会产生打不开的链接。

**建议：** Home 在自己的模块中共用一处“相对路径 → 正式 Link”的映射，browse direct refs 和资源定位都调用它。可复用现有 resolve_relative/layout 能力，正文只解析一次、结果复用；不放宽 HomeResourceLink 以容忍错误 guidance 形式，不在前端维护第二套转换规则。

当前 `test_home_browser_reads_actual_effective_guidance_and_direct_refs_without_copy` 仅断言 `home:agent/guide.md` 出现在 metadata，未检验链接能否按 canonical 身份继续访问。应调整这个测试，让它验证 catalog/body/direct_refs/resolve 对同一资源给出一致身份，并覆盖 guidance 相对链接。

**最小验收：** Home 浏览输出的每个受支持 direct ref 都能继续 resolve/read；top、Skill resource、domain/action guidance 和 fragment 分别覆盖一个正常样例；actual/effective 视图按调用来源保留。

## 6. R4：B0/B7 前端契约交接（已完成）

**状态：done。** 已补齐关键 response model、OpenAPI schema、contracts/examples 和代表性校验测试。

计划第 3、12 节明确要求完整 request/response、稳定错误、分页/失效说明，以及从真实 DTO 生成的正常/空态/等待/失败样例。当前新增 `docs/endpoint/inspection.md` 主要是路由和字段概述，没有覆盖这些完整实例。仓库中也没有本轮 Endpoint 响应 fixture 包。

实际读取 `/openapi.json`，`GET /v2/turns/{turn_id}/context` 的 200 响应为：

```json
{"description":"Successful Response","content":{"application/json":{"schema":{}}}}
```

其它若干新增 inspection 路由同样没有明确返回模型。请求参数可从 OpenAPI 获得，但不能据此生成可靠的响应类型。普通分页还可能返回 `content_fragment` 而非 items，当前交接文本只笼统描述拼接，没有一个可供前端验证的完整续页实例。

另外，`docs/endpoint/frontend-integration.md` 仍将配置流程描述为 PATCH + reload，没有纳入本轮主流程 apply/presets、active/saved 与新的只读浏览/恢复入口。新旧文件没有统一成为一份可直接执行的接入契约。

**建议补齐，保持轻量：**

1. 为新增固定外壳明确响应类型/结构：ContextOverview、SegmentView、InteractionPage、ResourceLocator、Preset、JobOutput 等。复用 owner 现有类型与序列化边界；SearchPage/DisclosurePage 引用现有协议，不再包装复制。
2. 固定字段、可选字段、枚举、null/缺省、分页和失效写清楚。OpenAPI 能自然导出时导出；不能自然导出的多态内容提供一份可校验 schema/完整契约。不要仅把任意 JsonObject 解释为已完成类型交接。
3. 用实际 owner/SDK/HTTP 序列化生成一组小型、去除敏感信息的 fixtures，固定或规范化随机身份，保留真实字段结构。无需大规模快照测试或新增 DTO 生成框架。
4. fixtures 至少覆盖：active/saved 与 preset；queued/pending/ask/choice reply/finished Session；Context roots 和 fragment 续页；Home actual/effective/diff 与 Memory redirect；带 evidence 的 Search 和续页；Job 输出/ACP/MCP；LLM/JEV/Embedding 的用途及过程关联。
5. 同步 frontend-integration 与前端计划的具体接入说明。错误样例沿本次实现的稳定 code，不根据 HTTP 状态猜业务。

**验收：** 前端开发者只凭正式接口文档、schema 和上述样例，就能实现类型层、分片读取、状态恢复和资源路由，不必阅读 Python 内部字典来猜响应。R1–R3 的真实结果进入这批契约验证。

不要求为所有返回值新建一整层重复 Pydantic 模型；目标是可依赖、可核对的一个公共协议。

## 7. 对执行计划的逐阶段判断

| 阶段 | 判断 | 依据与剩余项 |
| --- | --- | --- |
| B0 契约 | 已完成交接 | 路由目录、response model、OpenAPI schemas 与 fixtures 已同步 |
| B1 配置与方案 | 主要完成 | 单发布流程、双视图、完整组替换、预算与边界有实现和测试 |
| B2 问题与交互 | 主要完成 | typed ask/reply、Inbox、Context、Session 同一事实链 |
| B3 Session/Context/定位 | 已完成 | owner navigation roots、Trace identity 和生命周期边界已统一 |
| B4 资源与 Search | 已完成 | Home canonical direct refs、Resource resolve 和动态 fragment 已统一 |
| B5 运行观察 | 主要完成 | Job、ACP、MCP 复用运行 owner，GET/refresh 边界清楚 |
| B6 呈现与观测 | 主要完成 | provenance 来自消息组装；EventFilter 延续原游标体系 |
| B7 收口 | 已完成 | response model、OpenAPI、contracts/examples、Full 与 ty 均已核对 |

生图只有前端设置归属预留；没有后端执行器不构成本轮缺失。未新增通用 Action RPC、任意历史 Context、HTTP Memory/Home 持久写入口，同样符合计划。无需因为“统一”再添加这些能力。

## 8. 验证记录

代码在独立 worktree 检查，保留原工作目录。安装 Python 3.13.15、项目 `.[dev]`，静态工具 ty 0.0.84。当前环境没有 Conda/PowerShell，采用与 Full 相同的 `not external` 选择以及显式 Python 的 ty 命令；没有宣称运行过 Windows 脚本。

```bash
python -m pytest -m 'not external' --durations=10 -ra
ty check --python /absolute/path/to/review-venv/bin/python
```

最终验证结果：

| 检查 | 结果 |
| --- | --- |
| 全部非 external 本地测试 | **1191 passed、6 skipped、25 deselected，176.98 秒** |
| ty 0.0.84，显式使用本次 Python 3.13.15 环境 | **All checks passed** |
| git diff --check | 无差异格式错误 |
| 额外正常路径探查 | R1/R2/R3 均复现，具体 HTTP 结果见对应章节 |

6 个 skip 中，5 个是 Windows 专用进程/路径行为，1 个是当前环境未安装 Defuddle CLI。25 个 external 测试没有调用。这里不将 Linux 结果表述为已复测 Windows 平台行为，也不将 fake 模型测试表述为供应商连通性验证。

第一次完整运行有 13 项失败，查明测试环境缺少 SOCKS 代理依赖和 pip 构建工具。补齐 `socksio`、`pip`、`wheel` 后，这 13 项定向复测全部通过；其中 OpenAI 客户端部分构造导致的异步清理异常也消失。未把这些环境问题列为项目修改要求。

额外使用真实 Agent + ASGI HTTP 客户端验证 R1/R2/R3；压缩节点由真实 TurnTraceHeap 产生。没有对业务源码打补丁，模型采用测试 fake，不调用真实收费模型或使用供应商密钥。

类型检查和已有测试通过不覆盖新增断链问题：当前 overview 测试主要断言存在 segments/generation_id，Home 测试检查字段出现，没有验证返回的线索可继续打开。这正是补充少量跨接口正常路径测试的价值。

## 9. 已完成的收尾顺序（历史记录）

以下保留当时提出的实施顺序；对应事项已由后续计划完成。

1. 修 R1：segment owner 提供可打开的真实导航 roots。
2. 修 R2/R3：Trace 身份解析与 Home canonical Link 各回到 owner；保留动态资源 fragment/day/view。
3. 从修正后的实际接口生成 R4 契约样例，同步 Endpoint 对接文档。
4. 聚焦验证导航、问答到历史、配置应用和 Search 续接，最后运行 Full 与 typecheck；完成后更新计划验收状态。
5. 开始前端 F0 类型接入，再按前端计划实施各页面。不要在 TypeScript 中增加上述缺口的兼容分支。

本次只新增本 Review 文档，未改动用户已提交的 done 计划或业务实现。建议本文的提交说明：

```text
docs: review visualization backend delivery at 5993913
```

## Follow-up completion (2026-09-29)

The follow-up plan is archived as
`docs/analysis/done/20260929-done-visualization-backend-review-followup-improvement-plan.md`.
R1–R4 are resolved by the owner navigation protocol, Trace reference resolver,
dynamic locator fragment preservation, Home canonical reference helper, and the
critical v2 response/OpenAPI contract artifacts. The current validation is
`scripts/test.ps1 -Suite Full`: 1203 passed, 25 deselected; `scripts/typecheck.ps1`
with the `TinySoul` Conda interpreter and ty 0.0.84 passed; `git diff --check`
passed. The older numerical test result above remains a historical review
record; the follow-up result is the authoritative completion check.
