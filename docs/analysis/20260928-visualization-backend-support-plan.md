# Visualization 后端功能支持执行计划

> 日期：2026-09-28；状态：pending；代码基线：`1aa0db4`。
> 设计范围已确认，实施尚未开始。本文件完整定义后端交付，不需要其它讨论材料补充语义。
> 实施顺序：先完成本计划并交付 Endpoint 契约，再实施配套的 [前端执行计划](20260928-visualization-frontend-implementation-plan.md)。两份计划中的 API 编号一致。
> 规约依据：根目录 AGENTS.md；现行模块设计与 `docs/endpoint/`。执行期间同步真实设计和接口文档，尚未实现的能力不得写成当前事实。

## 1. 目标、范围与完成定义

让 Visualization 成为同一个 Agent 的交互、配置、知识浏览与运行观察界面。后端提供真实业务状态、受理接口、只读 owner 视图和有界观测，不要求前端从日志推导运行内核或读写项目私有文件。

本轮交付：

1. 批量配置应用、active/saved 双视图、命名运行方案、模型 family/collapsed 展示属性。
2. 当前 LLM、Embedding、JEV 的配置与用途描述完整披露；生图仅由前端预留页面，不增加生图后端字段、adapter 或 Action。
3. 类型化提问/回复、活动交互与当日/归档 Session 查询。
4. 活动 Context 的只读概览、段正文与渐进披露。
5. Home/Memory 浏览、Workspace 有界读取及归档读取，页面内容 Search 与统一资源身份解析。
6. Jobs、ACP、MCP、环境来源的查询支持，必要的模型/Action 展示观测。
7. 完整 Endpoint 文档、代表性契约样例、相关测试与项目规定门禁。

不新增通用 Action RPC、第二套检索引擎、持久聊天日志、历史完整 Context 数据库或 UI 专用运行调度器。普通用户 Turn 与浏览接口不取得 actual Home、持久 Memory、Session 解释的写权限；用户可发起 Reflection，由同一 Agent 执行。

完成不能只以路由存在判定：每个 API 必须来自正确 owner，前端所需状态可明确解释，模型用途和 Search 结果与实际执行对应，接口样例可由真实实现生成。

## 2. 当前基础与架构规则

### 2.1 可复用实现

- `agent/`：根调度、TurnHandle、generation、日级服务 lease、SDK 服务注册。
- `kernel/action/`：唯一 Action 执行体系、ModelUseDescriptor/Binding、Action catalog。
- `kernel/retrieval/`：有限函数管道、真实内容投影、SearchViews 与续页。
- `kernel/context/`：Segment registry、三槽四形状、纯读取 render、DisclosurePage。
- `plugins/session/`：User Turn 事实、解释、交互投影和归档 codec。
- `plugins/home/`、`memory/`、`workspace/`：资源事实、读写与索引 owner。
- `infra/config/editing/`：候选校验、ConfigFileTransaction、PreparedConfigActivation。
- `infra/model_services/`：generation 共享 JEV/Embedding 客户端与 Provider 顺序；Home/Memory 各自维护向量索引。
- `gateway/endpoint/`：v2 协议、状态/Turn/Reflection/config/Workspace/Observation。

当前缺口包括配置 apply/presets、双配置视图、完整浏览接口、结构化问题及回复、活动交互视图、模型来源和部分运行查询。现有前端仍有 v1 协议与事件推导逻辑，后端本轮只交付正式 v2 契约，不为该逻辑保留平行接口。

### 2.2 所有权与生命周期

| 内容 | 权威来源 | 生命周期 |
| --- | --- | --- |
| 活动/排队 work、状态 | Agent/TurnHandle | 进程与句柄保留窗口 |
| 已受理输入、问题、回复 | Inputs/Inbox/Trace | Turn；完成后必要事实进入 Session |
| 用户对话与语义地图 | Session | 当日；日切归档 |
| Context | 已安装 Segment | 活动 Turn，close 后不可再读 live Context |
| Home | actual + 跨日 overlay | 项目；effective 是组合读取视图 |
| Memory | 活动 Memory.md + 五类持久文档 | 活动记录按日，持久知识跨日 |
| Workspace | 当日磁盘、manifest、Trash | 当日；归档只读 |
| Search result | 原 SearchSession/SearchViews | Turn/profile 或 SDK generation/day lease |
| Job | Job owner 与 backend | 只能属于一个 Turn |
| ACP/MCP 连接与目录 | 已装配的能力 owner | generation；空闲 ACP 可跨 Turn |
| 模型过程与诊断 | Observation buffer/journal | 有界保留，不代替持久事实 |

依赖方向沿用 `infra → runtime/llm → kernel → plugins/environment → agent → gateway`。插件公开窄服务，SDK 绑定 lease，Endpoint 只进行参数校验和协议映射。新增模块先检查既有职责；不因一个页面而创建一层空服务。

### 2.3 失败与只读边界

沿用三层失败语义：可修正局部结果、模块边界失败、Runtime 控制转移。HTTP 映射已有有限失败，不把无结果、未记录、资源不存在、查询失效、配置错误、运行不可用都变成“连接失败”。取消服从所属生命周期；短 owner 操作 join 后传播取消。

状态概览与目录 GET 不自动连接 MCP、调用模型、Organize、Reflection、load/evict 或提交持久内容。资源正文读取可做 owner I/O，Context 段正文只读已安装状态。页面搜索是显式 POST，可调用配置选择的模型，但不成为 Agent Action。

## 3. 统一接口目录

表中路径均以 `/v2` 为前缀。标记“扩展/新增”是本轮任务，不能在完成前宣称已可调用。ID 表示一组同职责接口。

| ID | 方法与路径 | 状态 | 用途 |
| --- | --- | --- | --- |
| API-01 | GET /health、/status；POST /restart | 复用 | 连接、ready、runtime、宿主重启 |
| API-02 | POST /turns；GET /turns/{id}；POST /turns/{id}/input、reply、grant、cancel | 扩展 reply | 明确新轮/追加/回复/补额/取消 |
| API-03 | GET /turns/{id}/interactions | 新增 | 活动/保留句柄交互投影 |
| API-04 | GET /reflection；POST /reflection | 复用/必要补齐 | 可整理目标和同一根队列中的 Reflection |
| API-05 | GET /config?view=saved或active；GET /config/catalog；GET /config/actions?scenario=…；PATCH /config；POST /config/reload | 扩展读取 | 设置值、声明、运行能力与已有保存/激活入口 |
| API-06 | POST /config/apply | 新增 | 整批保存并发布 generation |
| API-07 | GET/POST /config/presets；GET/PUT/DELETE /config/presets/{id} | 新增 | 项目命名方案 |
| API-08 | GET /days；GET /session/turns、/session/turns/{id}、/session/map、/session/inspect | 新增 | 日目录、历史对话和地图 |
| API-09 | GET /turns/{id}/context、/context/segments/{segment_id}、/context/inspect | 新增 | 当前 Context 只读浏览 |
| API-10 | GET /home/catalog、/home/content、/home/changes、/home/diff | 新增 | Home 阅读与变化 |
| API-11 | GET /memory/active、/memory/catalog、/memory/document | 新增 | 活动与持久 Memory |
| API-12 | /workspace 现有 manifest/resource/blob/directory/move/tags/edit/append/trash/restore 路由 | 扩展读取 | 保留编辑；增加归档和大内容支持 |
| API-13 | POST /home/search、/memory/search、/workspace/search | 新增 | SDK owner 内容检索，返回现有 SearchPage |
| API-14 | GET /turns/{id}/jobs；POST /turns/{id}/jobs/{job_id}/stop；GET /turns/{id}/jobs/{job_id}、/output | 后两项新增 | Job 状态与输出 |
| API-15 | GET /subagent | 新增 | ACP 目标及 generation 连接状态 |
| API-16 | GET /expand/servers、/expand/tools；POST /expand/servers/{server_id}/refresh | 新增 | MCP 快照及明确刷新 |
| API-17 | GET /events；WS /events/ws | 扩展过滤/内容 | 定向过程读取、变化通知 |
| API-18 | GET /resources/resolve | 新增 | Link/ref/相对引用解析为逻辑 ResourceLocator |

HTTP 查询参数用 URL 编码，Link、含点 ID、模型名作为原子值处理。真实完整路由、request/response schema 和错误样例写入 `docs/endpoint/`；实现后不留“或其它类似接口”的歧义。

### 3.1 共同 DTO 与分页

新增 DTO 采用明确类型，在 owner/SDK 形成，HTTP 序列化为 JSON：

| DTO | 必需语义 |
| --- | --- |
| ResourceLocator | `link` 或 `ref`，以及确有意义的 day/turn_id/view；可带已解析目标；不含物理路径 |
| DaySummary | day、active/archived；有事实才返回归档时间 |
| InteractionItem | 稳定 id、role、turn_id、content，适用的 input_id/question_id/call_id/ref/reply_to、delivery |
| ContextOverview | turn_id、generation_id、day、captured_at、segments |
| SegmentView | descriptor、root_refs、适用的 selection/usage、正文页及原始消息位置 |
| ResourceDocument | locator、title、media_type、有界 text/content、direct_refs、truncated、next_continuation |
| JobOutputPage | items[{channel,text,可用顺序}]、next_continuation、result_locators、truncated |
| PresetSummary | id、name、description、included_scopes、active_match、saved_match、validation_issues、updated_at |

普通列表 `items + next_continuation`，默认 30 项、上限 100；普通文本页默认 16000 字符、上限 64000。已有 SearchPage/DisclosurePage 保留自己的协议和 owner 预算，不重复包一套节点身份。overview 不携带全部正文。

continuation 绑定读取内容及实际生命周期。相关内容变化时返回既有 owner 的失效原因，前端重新获取该对象；不增加全局 revision 或内容 CAS。已截断且无法再取得的 Observation 必须区分于可继续读取的资源分页。省略 day 的入口返回实际解析日；归档链接必须携带 day。

### 3.2 错误与返回状态

沿用 `{"error":{"code":"…","message":"…","details":{}}}`，不增加另一种错误外壳。已有路由保留既有稳定 code；新增读取错误由所属服务定义有限原因，并在 Endpoint 统一映射。

| 情况 | HTTP/协议 | 客户端行为 |
| --- | --- | --- |
| 请求/配置字段错误 | 422，request.invalid 或 config.invalid，details 指向 key/source | 定位字段，保留草稿 |
| 当前不可激活 | 409 config.activation_unavailable | 保留编辑，等待真实可用状态 |
| Turn/资源不存在 | 404，沿 owner 的 not_found 原因 | 显示不存在，不换到当前日同名资源 |
| live Context 已关闭 | 409 context.unavailable | 停止续读，转 Session/观测入口 |
| 无法确定历史动态绑定 | 422 resource.unresolved_origin | 请求明确定位，不替换成当前目标 |
| Search 参数/范围问题 | 422 search.invalid_request 或 search.scope_required | 修改范围/条件，不隐式裁剪 |
| Search 视图失效 | 409 search.view_expired | 保留已读页，用户选择重新搜索 |
| Search 来源不可用 | 503 search.source_unavailable | 显示真实来源问题，不当作空结果 |
| 可反馈的模型步骤失败 | 422 search.operation_failed | 呈现有限 step 原因，不换另一实现重试 |
| 不可继续的模块失败/服务不可用 | 503 或已有 service.unavailable 映射，保留 module/kind | 呈现实际范围，不自动重启 Agent |

Search code 由现有 SearchFailureKind 映射，不新增一套检索失败体系。非 Search 的 continuation 失效沿 owner 原因；200 空 items 是有效空集合。Observation gap 是成功响应的覆盖说明，不包装为请求失败。

## 4. 配置应用与真实配置状态

### 4.1 saved、active 与草稿

`GET /config` 默认 saved。saved 表示当前配置源合成结果；active 表示本 generation 实际激活的有效值，不能临时从磁盘重新合成冒充 active。候选发布时保留不可变的有效值投影及脱敏凭据状态，重启/重载时一起更新。

返回 `view`、`generation_id`、activity、pending_reload、sources、fields，以及已有 runtime/凭据/进程外壳投影。active 的来源信息是激活时的说明；写入路由始终以当前 saved sources 为准。

前端草稿不持久化在后端。其它客户端保存了未激活配置时，pending_reload 保持真实；放弃本地草稿不修改 saved。整批应用以 fresh saved 为基线，因此会同时激活已有 pending 内容；UI 必须显示这一点，不能暗中只激活自身字段。

### 4.2 apply 请求与单一发布流程

请求二选一，不允许混用：

```json
{"operations":[{"source_id":"project:configs/loop.toml","path":"loop.user.max_cycles","op":"set","value":30}]}
```

source_id 由当前配置源目录选择，上例表示项目 loop.toml；其它字段按 catalog 的标量、数组或完整对象边界提交。

```json
{"preset_id":"balanced"}
```

步骤：

1. 进入 ConfigController 的同一锁与现有 activation 协调；确认 Agent 可以激活，不能只检查无正在运行的模型。waiting Turn、根队列、日切或既有激活同样阻止应用。
2. 重新读取配置源，应用 mutations 或编译 preset，形成候选配置与文件写集合；`.env` 与 TOML 一起校验。
3. 复用正式配置编译、模型用途依赖校验和候选 generation prepare；prepare 不读取未提交的旧配置代替候选，不提前启动其环境来源。
4. 通过 ConfigFileTransaction 写入并保留 rollback receipt。
5. 复用 PreparedConfigActivation 的唯一 commit 发布候选 generation；commit 的成功发布点必须明确。发布前失败：abort 候选并 rollback 本批文件；旧 active 不变。
6. 发布成功：完成 receipt、更新 active/saved/pending 状态；retire 旧资源，清理诊断不推翻成功。

复用现有 activation 源停启和 generation 生命周期，不增加平行锁管理器或第二套 reload 状态机。若现有 prepare/commit 对共享资源有特殊要求，在原激活协议内整理顺序，不能以新接口绕过它。

返回 `state=active`、generation_id、pending_reload=false、changed_fields、changed_sources、方案匹配投影、可选 cleanup_diagnostics。断线后客户端重新读取状态，不能无条件重放 apply。此处只承诺既有正常进程内应用语义，不新增崩溃恢复事务平台。

PATCH 保留“只保存”，reload 保留“激活 saved”，两者与 apply 共用候选/激活函数。前端主流程使用 apply，不自行串联 PATCH/reload 伪造整批应用。

### 4.3 配置边界与凭据

- mutation 沿用 source_id/path/op=set|delete/value；不允许 set(null)。缺省通过清除覆盖表达。
- dotenv 写入与本批 TOML 使用同一候选环境。候选校验不先读进程旧值覆盖新凭据；进程环境和只读来源仍不可写。
- 返回凭据引用名与就绪状态，不回显 secret；方案不包含凭据；错误不包含原始 key。
- `action.models.bindings` 是原子数组；`action.retrieval` 是完整对象，其内部含点 Action ID 不拆层级。
- MCP tools 及其它 catalog 声明 object 的字段整体提交；不为字段名含点新增转义路径系统。
- apply 失败保留前端草稿；后端只撤回本批文件写，不撤回早已存在的 pending 保存。

## 5. 模型配置、用途与运行方案

### 5.1 模型目录与声明

LLM 使用现有 providers/models/tasks；专用模型使用 `infra.model_services.providers/models/uses` 数组。保持两者协议和 owner，复用合理的 UI 描述，不创建统一“大模型万能协议”。

Action catalog 继续返回 execution.executor、model_uses、retrieval 与生成的 tool.schema。model-use descriptor 表达 consumer、operation、允许实现及参数、target 类型、embedding_owner；binding 表达实际 implementation/target/options。不能把所有 Action 简化成一个模型选择字段。

候选表单用 package-owned catalog 描述与本地草稿值生成；当前运行可用性仍来自 active Action catalog。新草稿与 active 不一致时明确标记“待应用”，不假装已经验证远端。候选静态校验在 apply/方案捕获时复用正式编译，激活时完成所选依赖检查；不新增另一个配置 DSL。

Provider/model/use/task 的“被谁使用”由配置引用和已登记 consumer 生成。共享 registry 声明只保留一份；可在既有 config/catalog/actions 投影补足，不需要新建 consumer 数据库。

### 5.2 family/collapsed

LLM ModelSpec、解析器、catalog、标准/开发模板和配置投影增加：

- `family: str`，可省略，空值表示未分组。
- `collapsed: bool`，缺省 false，表示默认不在普通模型列表展开。

它们不影响模型可用性、链校验、调用顺序或历史读取。选择器可以显示被引用的折叠模型；没有真实消费者的专用模型展示扩展不顺带增加。

### 5.3 真实模型与操作能力

- Phase1/Phase2 继续使用 LLM task profiles。
- 生成动作依实际 descriptor 配置 llm_task；task profile ID 即使名为 llm_action，也只是普通可复用链名。
- Search select/rerank 按 descriptor 配置 LLM/JEV/Embedding；JEV 使用实际 Score，不能声明为任意结构化生成。
- query 通道由 retrieval policy 配置；Home/Memory 的 embedding_use 指向专用模型 use，向量索引属于各自 owner。
- filter 无模型。Workspace/Context/MCP 不因共用 Search 而自动获得向量能力。
- memory.write/write_daily、home.review 不额外套 LLM；Reflection 只是场景能力扩充，共用已有用途绑定。
- 专用 Provider 现有 proxy/timeout/max_retries 和有序 provider_bindings 完整进入 catalog；LLM Provider 表单遵循其真实字段，不补造尚未支持的代理字段。
- 生图本轮不增加配置解析枚举、连接探测、空 use 或执行器。

### 5.4 运行方案范围

方案是下列配置组的完整逻辑快照，不是额外 TOML source，也不是运行时覆盖层。应用后普通配置文件就是当前配置。

| scope | 捕获范围 | 规则 |
| --- | --- | --- |
| models | 完整 llm.models，包括 provider bindings、adapter/options、family/collapsed | 必选；延续完整模型配置语义 |
| tasks | 完整 llm.tasks | 必选；Task 的 max_cycles 不是 Turn 额度 |
| routing | loop.cycle.phase1_task_profile、phase2_task_profile；完整 action.models.bindings | 必选；包括 LLM/JEV/Embedding 实现、target、options |
| retrieval | 已有 retrieval policy 的 query.channels | 必选；只管理内部通道选择，不授予新的来源/操作 |
| budgets | 以下白名单组 | 可选，捕获时默认选中；不含则保留当前值 |

预算白名单：

- loop.user.max_cycles；reflection.home.max_cycles；reflection.memory.max_cycles。
- session.background_max_chars。
- context.budget_max_image_bytes、compression_trigger_ratio、compression_target_ratio、trace_chunk_max_chars、trace_branch_factor、trace_min_hot_entries、trace_inspect_max_chars。
- 每个已登记 action.retrieval 项的 max_steps、snapshot_max_chars、page.max_items、page.max_chars，以及已开放 select/rerank 的 input_max_chars。

不捕获 Provider 连接/凭据、专用 models/uses 目录、home.search.embedding_use、memory.search.embedding_use、paths、system_text、调度时间、visibility、retrieval.sources/operations/allowed_context、资源正文、本地偏好。

所以方案可以切换 select 的 LLM/JEV use、启停已有 Embedding 查询通道，但不能改变知识库向量空间。Embedding rerank 仍引用 owner 绑定。LLM models 整组捕获意味着 family/collapsed 也随方案，这一点在方案范围详情如实显示。

内部以规范化值与“使用默认值”表示快照。对 action.retrieval 的局部组应用时，读取当前完整 map，替换已管理字段，再编译单个原子 mutation；保留未管理的能力字段。目标操作已不存在或依赖缺失时报告配置问题，不自动重新开放或换模型。

完整组替换不得遗留上一个方案的模型/任务/绑定；若只读来源使预期有效配置无法成立，拒绝并指出来源，不静默合并为近似方案。方案不保存机器 source_id 或绝对路径，应用时按现有可写配置源路由。

### 5.5 方案存储与 CRUD

配置模块在项目 `configs/presets/*.json` 保存 schema_version、id、name、description、included_scopes、snapshot、created_at/updated_at。该目录不进入 TOML include/source 图，不进入日归档。

- POST /config/presets：`name, description?, source=active|saved, operations?, include_budgets`。先在内存构造目标有效配置；operations 只用于捕获，不保存/激活项目配置。
- PUT /config/presets/{id}：修改 name/description；明确提供 capture 对象才覆盖快照，capture 使用上述 source/operations/include_budgets。
- GET 列表/详情：含管理范围、引用问题、active_match/saved_match；比较规范化受管值，不把名称当作激活证据。
- DELETE：只删除方案记录，不修改当前 active 或 saved。
- 激活仅走 API-06 的 preset_id。

多个方案可以匹配同一配置；若保存最近应用的 id，它只用于选择器关联，不成为配置事实。用户改变受管字段后显示自定义/已修改，不把未应用草稿当作当前方案。

## 6. 类型化问题与正式交互

### 6.1 唯一问题协议

QuestionContent：`text`、`options[{id,label,description?}]`、`allow_other`（缺省 true）。options 为空是自由回答；本轮单选，最多 8 项，ID 唯一。text 上限 16000 字符、ID 128、label 256、description 2000。只有一个活动 question，可与 budget_request 同时存在。

`core.ask` 显式参数与一个完整 `tinysoul-question` fence 都规范化到同一内容类型。fence JSON：

```json
{"question":"采用哪种方式？","options":[{"id":"a","label":"直接执行"},{"id":"b","label":"先说明方案"}],"allow_other":true}
```

协议不含 Turn/question ID、HTTP 地址或脚本。外层正文可作为说明保留；正式问题内容只从指定结构取得。显式参数与 fence 内容冲突、多块或格式错误返回局部 Action 参数失败，不猜优先级。普通 Markdown 中出现 fence 不打开 Inbox。

SDK、Terminal、HTTP 共用 typed answer：

```json
{"question_id":"q1","answer":{"kind":"choice","option_id":"a","comment":"先处理主要部分"}}
```

```json
{"question_id":"q1","answer":{"kind":"text","text":"我希望采用另一种方式"}}
```

choice 校验当前 option ID；comment 可省略；Other 就是 text，不伪造 option ID。自由输入若有选项且 allow_other=false 则不受理。后端生成包含选项正文的规范文本反馈给模型，并保留结构化选择与 question_id；不只反馈“A”。

QuestionContent 同步进入 Action 结果、TurnSnapshot、Inputs、Session codec 和交互投影。HTTP response 字符串协议在本轮协同替换，不保留两个活跃入口。若读取既存归档缺少 option ID，只在 codec 边界按原文只读，不猜选项身份。

### 6.2 活动交互 API-03

响应含 turn_id、generation_id、day、state、items、pending_items、next_continuation。roles 为 user.input/append/reply、agent.question/reason/action/output，与 Session 交互投影一致。

- 当前已安装事实来自公开的纯读取快照，不调用 seal_trace/end_turn，也不重新编号部分 Action。
- 未安装但已受理的输入从 Inbox 公开只读快照取得；pending_items 单列，不能把 Inbox sequence 混成 Trace 总序。
- id 使用既有输入/问题/Action 身份。delivery 只描述有证据的 queued/accepted/installed/visible；不能将受理、安装误称模型已消费。
- queued 根请求不是已进入 Context 的输入；以 queued_request 状态呈现。
- final drain 保留已受理但未被模型看到的输入事实；客户端断开不使其丢失。
- Turn 完成后以 Session 正式投影替换该轮活动内容，不重复拼接。Session 必要提交失败时保留有限 TurnResult 与失败提示，不从事件伪造已保存历史。

读取身份有界保留；未知句柄为既有 not_found。API-02 的受理回执不能冒充执行完成；重复 input/reply 的 accepted=false 继续表示已受理，不显示成失败。

## 7. Session、Context 与资源身份

### 7.1 API-08

- GET /days：`before?, limit=30`，Archive/日期 owner 返回活动及归档日。
- GET /session/turns：`day?, continuation?, limit?`，只返回摘要：turn_id/ref/day/status/initial_input_excerpt/output_excerpt/question_count。
- GET /session/turns/{id}：`day, continuation?`，返回该轮有界交互和结果摘要。
- GET /session/map：`day?`，地图根、thread/note 入口、状态、关系、统计与有限线索。
- GET /session/inspect：`day, ref?, query?, continuation?`，复用 DisclosurePage；只提供已声明的确定性 query 能力。

Session 同一事实存储服务 background、inspect 与 UI。共享节点/回路保留真实 ID，树只是导航。解释包含 evidence refs，事实与解释分开；撤回解释仍可作为历史证据展开。归档缺失不退回今天；不提供外部 Session 编辑 HTTP。

### 7.2 API-09

在 kernel Context 的公开只读协议上提供 installed overview/body 和 ref disclosure，经当前 Turn 的 SDK 查询门面暴露。优先复用已有 segment render、descriptor、inspect；核实 seal/snapshot 的真实行为，不能因方法名相似就调用会结束 Trace 的接口。

overview descriptor：id、owner、slot、shape、order、capabilities、root_refs，适用的 available/loaded/protected refs、字符/图像用量及度量说明。字符不是精确 token。

段正文从已安装视图取得，返回 messages 与原始位置、有限分页。不能用 owner 最新文件代替已安装正文；TaskPrompt 是具体模型调用的局部层，不伪造为永久 Context 段。

UI inspect 共用 ref 路由和 DisclosurePage 读取，不走 ActionRunner、不追加工具结果/overlay、不改变 reclaim 保护。读取只观察同一次已安装状态；无需为 UI 停止 Turn。关段后返回 context_unavailable，历史从 Session/Observation 读取，不另存完整 Context 快照。

### 7.3 API-18

`GET /resources/resolve?reference=...&origin_link=...&day=...&turn_id=...&view=...`。返回 `kind, locator, capabilities`，只解析身份，不读取全文、调用模型或执行命令。相对引用由 origin_link 所属 owner 解释；网页链接由前端直接打开，不经后端代理。

扩展既有 Link/reference 解析与插件公开定位能力，按 owner 显式注册实际支持的资源族。它不是任意文件服务，也不是统一业务操作 Gateway。

动态 memory:current/latest/target 优先使用源 Context/Task 已记录的 resolved locator；补足返回它的投影。没有原绑定时不得用今天的 latest 冒充历史目标，返回有限 unresolved_origin，前端可以让用户明确选择打开当前资源。

Workspace 归档保留 day，Home 保留 actual/effective 视图；Session/Trace ref 与文件 Link 分开。内部 Search result_ref、模型短 ID 不能被解析为永久资源。

## 8. Home、Memory、Workspace 与页面 Search

### 8.1 API-10 Home

- catalog：`view=effective|actual`（默认 effective）、space?、query?、continuation?。query 只筛目录名称/已有摘要，不隐式全文检索或调模型。
- content：`link, view, continuation?`，区分 top、resource、domain/action guidance，owner 决定读取方式。
- changes：overlay 变更列表，带真实创建/修改/删除种类与资源 locator。
- diff：`link, continuation?`，actual/effective 的真实差异、必要覆盖说明和基线偏离状态。

Home owner 公开只读 review projection；不给 HTTP review token 或接受/拒绝写权限。整理走 API-04。Home 与 overlay 跨日，不提供虚构的日快照。目录可浏览局部 guidance；通用 Search 仍按原语义排除这些局部 mount。

### 8.2 API-11 Memory

- active：`day?, continuation?`，当前或归档 Memory.md。
- catalog：`kind?, query?, continuation?`，五类持久文档目录与摘要，query 是确定性目录筛选。
- document：`link, continuation?`，持久文档正文、类型、direct refs、真实迁移/redirect 信息。反链通过 API-13，不夹带另一套无分页反链结果。

活动 Memory.md 与 persistent daily 分开。持久文档不因为查看某日而自动变为历史版本。动态链接先按 API-18/源绑定定位。所有页面浏览不提交知识写入。

### 8.3 API-12 Workspace

完整保留当前 HTTP 动作：GET manifest/resource/blob/trash；PUT resource/blob/tags；POST directory/move/edit/append/trash/restore。写操作只针对活动日。

扩展 GET manifest/resource/blob/trash 接受 day；归档通过 Archive + Workspace 只读 owner 解析。资源文本提供有界正文与 continuation、可编辑类型、总大小；编辑器需要全文时明确拉取完整可编辑文本，不能把第一页保存成完整文档。

blob 支持流式读取及标准单 Range，返回真实 Content-Type/长度；无须构建复杂下载调度。文本分页与二进制 Range 分别由 owner/transport 解释。写失败若含已提交 locator，保留此事实，不能统一报告“未发生修改”。不新增 digest/revision/CAS。

### 8.4 API-13 Search

仅当前 SDK owner 搜索范围：Home effective、持久 Memory、活动 Workspace。actual Home 和归档 Workspace 允许浏览/目录定位，本轮不在 SDK Search 上伪造对应历史向量/语境支持。

三个 POST body 直接使用现有 Search 请求，不再设计 text/semantic 平行格式：

```json
{"source":{"kind":"query","scope":"all","query":"部署约定"},"steps":[{"op":"rerank","criterion":"优先直接可执行的约定","context":"none"}],"page":{"limit":20,"max_chars":8000}}
```

```json
{"source":{"kind":"result","result_ref":"<原 SDK 结果句柄>"},"steps":[{"op":"select","criterion":"仅保留尚未验证的方案","context":"none"}]}
```

```json
{"continuation":"<原 SDK 查询 continuation>"}
```

以正式 parser/schema 为准：source 支持 query/backlinks/directory/refs/result；steps 支持 filter/select/rerank；where、exclude_refs、Workspace resource scope、Memory document_ref query 复用原声明。continuation 单独提供；HTTP 不接收 implementation/provider/model 参数。

SDK 输入 context=none；拒绝 current，不从活动 Turn 偷取 Context。给模型的候选仍必须使用当前真实内容投影与已配置内部预算。相应 owner 没开放某来源/操作时用正式局部失败，不暗中换算法。页面查询遵守该 SDK 服务的 retrieval policy；不将当前 Turn 选域或 Action visibility 误当作用户资源浏览的开关。

返回当前 SearchPage：result_ref、scope/source、items、coverage、page、continuation。items 的 content_coverage/preview_coverage、evidence、evaluation 保持原意；lexical 与 Embedding 独立召回融合，不用 UI 词法重筛覆盖语义命中；select 可删、rerank 保留全体、filter 不调用模型。

AgentRuntimeServices 已按有效 generation/day 缓存服务；HTTP 每次取该服务，不每次创建 SearchSession。翻页读冻结结果，不重新检索/调用模型；结果过期反馈失效，用户明确重新搜索。不要把 Turn/profile 的 result_ref 或 continuation 接到 SDK 会话，也不为历史 Agent 卡片补一套永久结果缓存。

backlinks anchor 可跨空间，来源 owner 只搜索自己的真实引用边。更深内容通过资源读取/Inspect/describe，Search 不增加正文游标。

## 9. Jobs、ACP、MCP 与环境

### 9.1 API-14

Job 详情复用 JobSnapshot，加 backend 的有界只读 describe。output 的 opaque continuation 封装实际执行/ACP 输出位置，返回 channel/text/顺序与 result_locators；不承诺不同流的精确因果总序。

在现有 Job/backend 公共边界增加读取方法，collect 与 HTTP 复用它，不复制缓冲区、不通过 HTTP 执行 collect Action。只读轮询不消费父 Agent 的通知或改变决策。stop 复用已有 owner 流程。

Job 待答仍由父 Agent subagent.respond 处理；需用户判断时使用同一个 ask/reply。不新增 Job 通用 reply API。Turn 结束后 Job 回收，历史仅查看实际存留产物和 Observation。

### 9.2 API-15

返回 configured targets 与真实 connections：ID/描述、state、适用 turn_id/job_id、cwd locator，以及确有事实的建立/活动时间。目标、连接、Job 是不同对象。

从 SubagentEngine 同一连接池生成 generation 只读视图，保留已有 Turn Working 视图。UI 不创建自己的连接，也不提供脱离 Turn 的任意 connect/delegate RPC。

### 9.3 API-16

servers：配置 enabled、连接状态、discovered 状态、工具数量和有限错误。tools：server_id、continuation，读取已发现目录；提供单工具完整 schema 的有界详情，可用 tool_name 查询同一路由。

GET 不调用 discover。POST refresh 明确触发已配置服务器的连接/目录刷新，复用 owner 已有并发与关闭规则，不新建连接副本。配置变更走 config apply。没有通用工具执行测试 API。

### 9.4 Environment

复用 status.runtime.sources 与已有来源观测；确缺少时补 source/topic/event_id/目标 Turn/接收消费阶段的有限摘要。不复制 Inbox 正文、不让前端注入任意环境事件。Workspace watcher 故障不等于正式读写不可用；日切/重载沿原来源生命周期处理。

## 10. 观测、模型来源与 Action 呈现

API-17 GET 保留 after/mode/limit/instance_id，增加 turn_id/task_id/call_id/search_id/step_index/through。过滤为同时满足；step_index 需配合 search_id。through 固定本次扫描上界；next cursor 表示扫描过的全局位置，无匹配也前进，gap 保留原语义。

复用 buffer/journal 查询，不新建模型任务数据库。WS 保留 normal/verbose/model 分级；前端默认 verbose，model 正文按需查询。必须为必要状态/摘要提供轻量事件，不迫使所有页面订阅完整输入。

在消息真实组装处附 provenance：segment_id、owner、slot、shape、实际 message indices；TaskPrompt/局部 guidance 独立标识，并附真实 Home refs。扩展当前只含文本的 ActionSkillGuidance 等必要边界，使 LLM 层原样转送来源元数据而不理解业务 owner。来源不能靠标题解析。

LLM 按 task_id 展示 provider-neutral MessageStack、profile、attempts、可用 usage；没有网络原始包就不称“完整 HTTP 请求”。JEV/Embedding 用 call_id、consumer、target 与真实 typed input/output；Search 通过 search_id/step_index 关联，来源 query 通道也有来源阶段标记。只保留现有观测等级允许的内容，不生成未披露的内部推理。

Action 外壳保留 invoke/call identity、state、result/failure。Search 直接消费原 SearchPage；Inspect 直接消费原 DisclosurePage；只在正式结果不足以呈现且有真实消费者时添加旁路 presentation，例如 resource_change、process_output、delegation。字段有 kind、locator、实际有界片段、truncated；历史 before/after/diff 必须由提交 owner 当时产生。不要为通用 schema 重复存所有业务结果。

### 10.1 页面失效通知

复用现有提交/完成事件，缺口才补轻量 owner 变化观测：

| 变化 | 前端刷新对象 |
| --- | --- |
| 输入/问题/预算/Turn 完成 | Turn/interactions；完成后 Session |
| Context install | Context overview；已打开段提示更新 |
| Session Organize | 当日 map/相关披露，不刷新全部正文 |
| Workspace 写入/外部变化 | 对应 day/locator，保留编辑草稿 |
| Home/Memory 提交 | 目录/正文/diff；新搜索提示，不改冻结结果页 |
| Job/ACP/MCP 变化 | 对应状态与输出位置 |
| config activation | active/saved、catalog、方案、全部代级查询 |

事件丢失后靠快照恢复，不增加可靠投递总线或全局 UI revision。

## 11. 实施步骤与文件职责

所有步骤初始 pending；阶段之间是依赖顺序，不削减本轮交付。

| 阶段 | 工作与主要位置 | 退出条件 |
| --- | --- | --- |
| B0 契约 | 固定 API-01～18、DTO、错误和 fixtures；核对 sdk export、Context 读边界 | 请求/结果/owner/生命周期逐项可追溯 |
| B1 配置与方案 | infra/config/editing、agent/lifecycle、llm/config 与 catalog；API-05～07 | 整批应用和失败回退、真实 active、方案范围正确 |
| B2 问题与交互 | kernel/loop/interaction、core.ask、Context facts、Session codec/views、agent/handles | 类型化 ask/reply、受理到完成的事实链完整 |
| B3 Session/Context/定位 | 各 owner 只读方法、SDK lease、reference resolver；API-08/09/18 | 读不改变 Context/Session；归档与动态绑定正确 |
| B4 资源与 Search | Home/Memory/Workspace/Archive 服务、HTTP schemas；API-10～13 | 真内容、当前/归档边界、分页/续接及模型用途一致 |
| B5 运行观察 | Jobs、subagent、expand、environment 窄投影；API-14～16 | 同一个 backend/连接/目录，无隐式远端操作 |
| B6 呈现与观测 | Observation 查询、消息 provenance、必要 presentation；API-17 | 可由真实调用定位到显示片段与来源 |
| B7 收口 | docs/design、docs/endpoint、catalog/templates、tests | 全部验收通过，交付前端完整契约包 |

B0/B1 的类型命名可以沿现有代码细化，但不能自行变更已确定的业务职责、来源和协议含义。后端改动限定后端与其文档，不直接重做 visualization。

## 12. 验证、交接与完成清单

测试优先覆盖真实风险与正常主线，owner 契约只完整测一次，不为每个页面重复后端集成测试。使用 fake 模型/协议后端，不用真实网络或长 sleep 作为默认门禁。

- [ ] active/saved 明确；混合 dotenv/TOML apply 成功、校验失败、prepare 失败、发布前回退、发布后清理诊断各有正确结果。
- [ ] waiting/queued/day transition 不应用；前端可编辑草稿；已有 pending 保存不会被本地 reset 撤销。
- [ ] preset 完整替换受管组，保留未管理能力；缺引用/只读源明确失败；budget 缺省/包含和 LLM/JEV 切换正确。
- [ ] family/collapsed 不影响执行；Action descriptor、绑定、激活和真实调用一致；生图未新增伪配置。
- [ ] ask→choice/text→追加→完成→Session；问题/预算并存；accepted-but-not-installed、取消与 final drain 不丢事实。
- [ ] Session 地图共享节点、证据、归档读取；Reflection 不进入 User Session。
- [ ] Context 查询不 seal/compose 新任务、不 load/evict、不解除模型 inspect 保护；close 后明确不可用。
- [ ] Home effective/actual/guidance、Memory active/persistent/redirect、Workspace 当前/归档/编辑全文正确。
- [ ] Search 双通道保留真实命中、模型输入片段真实、rerank 不删成员、翻页不调模型、跨 lease 句柄不可混用。
- [ ] Job output 不消费 Agent 消息；ACP 空闲连接跨 Turn，Job 不跨 Turn；MCP GET 不 connect、refresh 明确 I/O。
- [ ] Event 过滤游标可前进；缺失观测不伪造正文；provenance 来自实际组装。
- [ ] ResourceLocator 解析保留 day/view/绑定，不能把历史动态链接解析为当前资源。

B7 执行仓库标准 Full 与 typecheck（优先 Conda TinySoul 或显式 TINYSOUL_PYTHON；按 AGENTS.md 的 scripts/test.ps1、scripts/typecheck.ps1），记录命令、环境、结果；只有业务实现完成才运行并声明实现门禁。本计划编写本身不意味着测试或实现已经完成。

前端交接必须包含：每个 API 的请求/响应、稳定错误 code、分页/失效说明；生成自实际 DTO 的空态/正常/等待/失败样例；LLM/JEV/Embedding 与 Search 的真实结构样例；一条可复现的 User Turn 追加/问答/补额/完成流程，以及 Home/Memory/Job/MCP 场景。同步文档，不只交付截图或路由名。

只有 B0～B7、接口文档、模板和必要验证全部完成，才能标为 done，并按 AGENTS.md 移入 `docs/analysis/done/` 加入 `-done-` 文件名；前端尚未完成不影响后端阶段自身验收，但不能据此宣称整体 Visualization 已完成。
