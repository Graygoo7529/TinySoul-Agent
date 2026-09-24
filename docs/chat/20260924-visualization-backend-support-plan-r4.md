# Visualization 重构：后端功能支持执行计划

> 日期：2026-09-24；交付版本：20260924-r4。
> 状态：pending。本文已完成设计整理，实施、文档同步和验证尚未开始。
> 最新检出：10b43c9e1b9d245da9029fd713510317b754e662。本次新增提交仅调整文档；业务代码与已复核的 f4965082011f5c654e4a877f6aea3e8d3fe053bd 一致，AGENTS.md 未变。
> 配套计划：[前端重构与建设执行计划](../../visualization/docs/analysis/20260924-visualization-refactor-plan-r4.md)。
> r4 替代 r3：补充实际模型消费者审查、Reflection 模型归属和 Action 模型使用设计。Q-02 为本轮待讨论的界面归属/描述契约建议；Embedding 真实迁移与 JEV 预配置继续为已确认范围。业务代码尚未实施。
> 本文中的“新增”“扩展”均表示目标契约，不能作为当前已存在接口的说明。实现后逐项同步 docs/endpoint 与 docs/design。
> 后续讨论：[Action 模型用途与 Reflection 写入架构提案](20260924-action-model-usage-architecture-proposal.md)。该提案的 Q-03 建议进一步替换 §5.7 的仅描述方案，涉及动作用途绑定、输入构造和 Memory compose；尚未确认，不作为当前已获准实施范围。

阅读顺序：§1～3 定义目标和所有权；§4 配置/方案；§5 专用模型的完整修订；§6～10 交互/查询/观测；§11～13 接口与实施验收；§16 复核和 Q-01；附录给出双方交接约束。本文仍是目标计划，当前已实施事实见 §2。

## 1. 目标与已确认设计

本次后端工作让 Visualization 能准确呈现和使用已重构 Agent 的能力。Agent 仍是唯一根调度者；Context、Session、Workspace、Home、Memory、Jobs 和能力插件继续拥有各自事实。Endpoint 提供类型化服务映射及观测查询，不保存另一份对话、知识、工作区或运行状态。

| 编号 | 已确认语义 |
|---|---|
| D1 | 设置在前端形成整批草稿，通过配置应用命令保存并重载；激活发布前失败撤回本批配置文件修改。 |
| D2 | 运行方案按项目由后端保存，包含模型、任务链、调用分配，并可包含明确的 Context 与 Turn 预算；入口在对话输入区旁。 |
| D3 | 方案仅在 Agent 可激活新世代时切换，不在活动/等待 Turn 中途换配置，不给排队 Turn 增加独立方案调度。 |
| D4 | core.ask 的交互表单回复同一 Turn；普通回答中的表单只填入输入框，由用户提交后续输入。 |
| D5 | UI 查看不等于模型加载；插件数据、活动 Context 投影、历史模型请求是三种不同视图。 |
| D6 | llm.models 增加 family、collapsed；前者为模型簇，后者为默认折叠标记，仅用于展示。 |
| D7 | JEV、图像生成等设计能力分类、配置和 Provider 接入方式；实际 JEV 检索/Action 和图像生成业务另行实施，不更换本次 Loop 决策逻辑。 |
| D8 | 扩展采用显式组合；不建设动态插件市场、通用远程 Action 执行器或另一套执行状态机。 |
| D9 | 本轮迁移真实 Embedding 用途/单模型/Provider 链，并支持保存 JEV 预配置；实际 JEV 调用另行建设。 |
| D10 | 前端对话/Workspace 保留原版主要布局与视觉交互，Context 从右上入口按需打开；设置整体重组但保留模型相关对象编辑逻辑。此调整不改变既有 HTTP 能力范围。 |

本次支持 Home/Memory 浏览、追溯及发起 Reflection。直接人工提交 actual Home、持久 Memory、编辑 Session 解释，不属于本次接口范围。Workspace 保留正式用户编辑能力。

## 2. 代码依据与需要消除的旧假设

已复核最新提交新增的 SDK、Visualization 与 Reflection 讨论记录。讨论记录用于解释意图；当前事实以 AGENTS.md、正式设计文档和实际代码为准，历史动作命名不作为恢复旧接口的依据。

### 2.1 可复用基础

- tinysoul/agent/sdk.py、services.py、handles.py：SDK、世代服务、Turn/Job 快照。
- tinysoul/agent/composition/builder.py：PreparedConfigActivation 的 prepare/commit/abort/retire 与唯一世代切换。
- tinysoul/infra/config/editing/controller.py、transaction.py：候选构建、配置校验、来源图、文件提交回执。
- tinysoul/kernel/context/segments：SegmentDescriptor、三个槽位、四种形状、纯 render、inspect 路由。
- tinysoul/kernel/context/disclosure.py：Trace/Session 的 DisclosurePage 与 continuation。
- tinysoul/kernel/loop/interaction/inbox.py：追加、回复、待答、补额和收尾。
- tinysoul/plugins/session/views/interaction.py：已有确定性事实交互投影，应扩充后供 UI 共用。
- tinysoul/plugins/archive：归档日索引、冻结来源解析。
- HomeService、SessionService、MemoryReadService、WorkspaceService：现有 owner 服务。
- tinysoul/gateway/endpoint/events：有界 Observation buffer/journal；不是业务数据库。

### 2.2 当前事实

现有 Endpoint 为 /v2；配置 PATCH 只保存候选，reload 才激活。结构化 Turn、ask/reply、grant、Job 列表/停止和 Reflection 已存在。Workspace 不再接收 digest/revision/retention。

尚缺 Home/Memory/Session 浏览、活动交互与 Context 只读投影、ACP/MCP 完整管理视图、配置应用组合命令和运行方案。模型 family/collapsed 尚未被配置解析器接受。

action.execution 已有实际执行状态，不新增平行的 action.started 协议。旧 demand 的 mounted skills 和写入预览，按本计划转换为结构化来源和有界观测展示数据。

## 3. 服务、数据和接口边界

### 3.1 四类数据

| 数据 | 唯一来源 | 保存与有效期 |
|---|---|---|
| 当前执行事实 | Agent/TurnInbox/Context/Jobs | 活动或保留句柄期间，绑定 generation/turn |
| 完成的用户交互与语义图 | Session | 当日 Session，日切后归档 |
| 资源、知识、配置 | 各自 owner | 依各 owner 正式生命周期 |
| 模型调用、动作展示与诊断 | Observation | 有界保留；允许正文不可用，不承担业务恢复 |

UI 查询使用 owner 公共 snapshot/read 方法。Endpoint 不读取私有字段、拼物理路径或扫描目录解释业务。

### 3.2 SDK 暴露方式

- 活动 Turn 交互与 Context：Agent 提供按 turn_id 取得只读快照、段正文和披露页的窄方法，内部调用活动 Turn 的公开读取端口。不得把整个 Loop/Context 对象返回给 Gateway。
- Session/Home/Memory：扩展既有服务的浏览能力；实际内容解释留在插件。需要区分读与写授予时提取只读接口，不复制 owner。
- 归档：Archive 解析日身份并向 Session/Workspace/Memory owner 提供冻结来源；各 owner 使用自己的 codec。Endpoint 只收到日、Link、DTO，不收到 ArchiveProjection 的物理路径。
- ACP/MCP：由 Subagent/Expand 插件显式导出查询服务，绑定 generation。Job 监督仍走统一 kernel/jobs。
- 配置方案：由配置模块保存、校验、编译和比较，Agent 提供激活端口；不是新的业务 Plugin，也不属于 Home/Memory。
- 每次 HTTP 请求重新取得对应服务；长连接不持有跨世代可写服务。插件注册、SDK export 和生命周期使用现有显式装配规则。

新增 SPI 必须有本文列出的真实消费者。共享类型置于最低共同依赖层，避免 plugins 反向导入 agent/gateway 的 DTO。

## 4. 配置应用、草稿与运行方案

### 4.1 当前配置与已保存配置

扩展 GET /v2/config 为 view=saved|active，默认 saved：

- saved：从当前配置来源图读出的已保存候选；
- active：当前 generation 的配置快照的脱敏投影；
- 返回 view、generation_id、pending_reload、activity、sources、fields；沿用现有字段描述与 source_id；
- 活动值不能从已保存文件反推；active 投影不能重复扫描凭据目录；
- /v2/status 仍只返回轻量状态，不为了配置页面扩大热路径；
- 环境变量/宿主 overrides 的只读覆盖关系可见。写入被覆盖字段不能被误报为已改变有效运行值。

前端草稿独立于二者；后端不保存每个控件的编辑中状态。

### 4.2 新增配置应用命令

POST /v2/config/apply 请求为以下两种之一，不允许同时携带：

~~~json
{"operations":[{"op":"set","source_id":"project:configs/loop.toml","path":"loop.user.max_cycles","value":30}]}
~~~

~~~json
{"preset_id":"preset_example"}
~~~

source_id 示例必须以实际 GET config/catalog 返回的来源为准，不硬编码示例文件。

内部顺序：

1. 取得 ConfigController 现有锁，并通过现有世代激活 admission 预留空闲位置，防止检查后新 Turn 插入。
2. 读取当前来源图，构建候选；方案先编译为同一种 ConfigMutation。
3. 执行 owner 配置校验；构建候选 generation。此阶段不发布候选。
4. 使用 ConfigFileTransaction 保存本批文件，保留 receipt，不立即 complete。
5. 执行 PreparedConfigActivation.commit；以 handle.activate 为发布点。
6. 发布成功后 complete 文件 receipt，更新配置快照/方案关联，retire 旧资源。
7. 发布前失败：abort 候选并 rollback 本批文件，恢复旧世代来源。UI 草稿由客户端自行保留。

把 patch/reload/apply 的候选校验和激活代码提取成同一条内部流水线，避免复制三份。patch 仍表示只保存，reload 仍表示激活已保存文件，apply 表示一次具体编辑的保存与激活组合。

当前 begin_activation 位于 generation 准备方法内部；重构时将 admission 边界放到明确位置，每次应用只进入一次，不在 Controller 和 Builder 重复预留。若应用前已有 saved-but-pending 候选，失败恢复的是“本次应用前的文件和 pending 状态”，不是自动回滚到 active 的旧文件；应用成功则激活用户预览过的完整 saved + draft 候选。

成功返回 state=active、generation_id、pending_reload=false、changed_fields、changed_sources、preset projection、cleanup_diagnostics。旧资源清理诊断不撤销已经发布的成功。

错误沿现有 error envelope 返回：

- 422：配置字段/引用不合法，details.key 定位字段；
- 409 config.activation_unavailable：有活动或等待 Turn、排队工作、日切或其他 activation；
- 配置构建/发布前失败：说明本批修改已撤回；
- 真实 rollback IO 失败需明确返回有限的未恢复来源及实际状态，不能声称“完全未保存”。不为此建立长期事务日志或自动恢复服务。

取消按现有 JoinedOperations 收束至确定提交点。这里保证正常进程中的批量应用语义，不扩张为配置文件、日归档、外部服务的分布式事务；已有文件外部修改仍遵循现有项目协作假设。

### 4.2.1 凭据也属于整批候选

当前 ConfigController._candidate 已支持 dotenv source，旧 CredentialsSettingsPage 却逐项 PATCH 并提示 active。前端改造必须一起清除此假设；本次不额外建立 Credentials 服务。

新增/替换/删除环境变量值与 TOML mutations 放进同一 operations，请求中 source_id 使用服务返回的 dotenv 来源。候选 runtime_env、引用校验、配置 receipt 和失败回滚一起覆盖 .env；不能先保存密码再单独尝试激活模型。

GET config 继续只返回敏感值的就绪/来源信息。未改动的占位符不生成 set；“删除变量”是显式 delete；输入空字符串不能默默当作删除。前端刚输入的值只在内存草稿保存，apply 结果/差异/日志不回显它。操作摘要可列变量名与新增/替换/删除。

方案不保存 .env 或代理认证值；从含凭据编辑的草稿捕获方案时，只捕获已声明 scope，显示排除的修改。process env/host override 的只读覆盖继续如实披露，不承诺修改 .env 就改变更高优先级环境值。

### 4.3 运行方案管理范围

方案是“指定配置范围的完整快照”，不叠加成新的配置 source。切换后普通配置文件就是当前配置，运行时不再额外读取一层 preset overlay。

| scope | 范围 | 必选 |
|---|---|---|
| models | 完整 llm.models，包括 Provider bindings、adapter_options、request_overrides、family/collapsed | 是 |
| tasks | 完整 llm.tasks；这里的 max_cycles 是一次 LLM Task 的链轮询次数 | 是 |
| routing | loop.cycle.phase1_task_profile、phase2_task_profile；action.llm_action.default_task_profile、overrides | 是 |
| budgets | 下列明确字段的完整快照 | 保存方案时可选，默认勾选 |

budgets 字段白名单：

- loop.user.max_cycles；
- reflection.home.max_cycles、reflection.memory.max_cycles；
- session.background_max_chars；
- context.budget_max_image_bytes；
- context.compression_trigger_ratio、compression_target_ratio；
- context.trace_chunk_max_chars、trace_branch_factor、trace_min_hot_entries、trace_inspect_max_chars。

不纳入 system_text、路径、Endpoint、凭据、Provider 连接定义、Reflection 定时规则、Action 授权/visibility、Workspace 文件限制、知识正文和本地外观。未包含 budgets 的方案保持当前预算；包含 budgets 的方案完整替换该组，缺省项按正式配置默认语义恢复，不继承上一个方案的偶然值。

逻辑快照保留“使用默认值”的含义。可选值未配置时，以缺省字段表示；编译时清除相应配置覆盖，不生成不被当前 mutation 协议接受的 set(null)。

模型 Provider bindings 会引用共享 llm.providers。删除/禁用 Provider 后，依赖它的方案在校验中报告问题，不复制凭据。非 LLM 服务目录不自动成为此 scope；未来确有方案级用途时显式扩充 scope。

### 4.4 方案保存与应用

由配置模块保存到项目 configs/presets/*.json；该目录是明确的命名方案资料，不进入 TOML include/source 图，不进入日归档。新增项目模板时声明该目录，不能把每个方案自动载入配置。

持久结构：schema_version、id、name、description、included_scopes、snapshot、created_at、updated_at。不保存绝对 source_id/机器路径来表达方案值。配置 source 路由在应用时重新解析。

新增接口：

| 方法与路径 | 语义 |
|---|---|
| GET /v2/config/presets | 方案摘要、管理范围、active/saved 匹配状态、当前关联 |
| GET /v2/config/presets/{id} | 脱敏的完整逻辑快照与本地引用校验问题 |
| POST /v2/config/presets | 从 source=active 或 saved 的配置及可选 operations 捕获；name、description、include_budgets |
| PUT /v2/config/presets/{id} | 修改名称/说明；显式携带 capture 时才重新捕获并覆盖快照 |
| DELETE /v2/config/presets/{id} | 删除方案记录，不改当前运行配置 |
| POST /v2/config/apply | preset_id 激活，复用唯一应用流程 |

创建/覆盖方案不激活；从草稿保存时只在候选内计算 operations，不顺带 PATCH 正式配置。请求的 capture 结构固定为 source、operations、include_budgets；不混入任意配置文件上传接口。

编译器按正式配置来源和 collection.create_source 生成 set/delete：删除目标范围内已经不在快照中的条目，替换完整对象和有序链，保留范围外内容。覆盖项分布在多个来源时需处理所有可写片段；只读覆盖使有效 scope 无法匹配时明确拒绝，不能悄悄新增更高优先级来源。

配置模块可保存“最近明确应用的方案 id”作为选择元数据；真实匹配以当前 active scope 比较为准。手动改配置后显示 modified；修改方案本身不自动改 active；删除正在使用的方案后 active 仍有效，关联为空。相同配置可有多个名字，以最近明确选择为展示偏好。

## 5. 模型展示元数据与非通用模型配置

### 5.1 family 与 collapsed

在 llm.models.<id> 顶层增加：

~~~toml
family = "example-series"
collapsed = false
~~~

family 是稳定、可由用户编辑的分组名称，缺省为空，UI 放入“未分组”。collapsed 为严格 bool，缺省 false，表示默认收起旧模型。解析时做类型和合理长度校验，不把 family 推断为 adapter/provider。

更新 ModelConfigParser、ModelSpec、配置 catalog、模型序列化/列表投影、模板和相关测试。字段不得传入供应商请求、不改变 eligibility、重试、capabilities 或模型顺序。

折叠模型在模型目录的收起区域显示数量；搜索可命中；任务链中已引用的模型始终可见。历史调用始终显示当时 model_id，不能因当前标记折叠而隐藏事实。模型簇不是新的模型层，不增加 family 调用路由。

### 5.2 LLM 与专用模型：一致的是选择关系，不是执行协议

本节设计范围已经维护者确认：本轮迁移真实 Embedding 用途绑定与 Provider 链，支持保存 JEV 预配置。JEV 业务调用与未选定的生图 adapter 后续设计；B1b 是正式实施项。

| 层次 | 当前 LLM | 专用模型目标设计 |
|---|---|---|
| 调用意图 | Phase/Action 引用 task profile | 消费模块引用具名 use，例如 embedding、decision、image_generation |
| 意图内容 | 消息、工具范围、输出协议、推理参数及选择策略 | 要求的 capability_kind，以及一个具体 model 引用；业务输入由调用模块构造 |
| 模型选择 | task.models 有序 Model Chain | use.model 单个模型，不增加 Model Chain |
| Provider 选择 | ModelSpec.providers 有序 bindings | 同样采用单模型内有序 bindings，每项 provider + provider_model |
| 连接 | 地址、凭据及 adapter 匹配 | 复用连接字段与构造设施；由专用 adapter 校验协议 |
| 返回值 | LLM TaskResult、tool intents 等 | EmbeddingBatch 或未来各自的结构化/图像结果；不强塞进 TaskResult |
| 失败处理 | 已有模型链/Provider 选择与重试 | 具体能力的有界尝试；消费者解释失败，不复制 LLM 状态机 |

这里的“嵌入”“结构化判断”“生图”是能力类型，具名用途表达“把哪个配置好的模型用于哪项能力”。JEV 是结构化判断模型的名字，不作为整个抽象层的固定类型名。用户可把 decision 用途的显示名称改为“JEV 判断”。

三个名称必须分清：

- capability_kind：embedding / structured_decision / image_generation，决定配置和结果类型。
- use.id：稳定用途名；默认提供 embedding、decision、image_generation。不同消费场景真有必要时再增加用途，例如另一个独立检索用途。
- model.family：只用于模型库展示分簇，不能代替 capability_kind 或 use。

删除 r1 的 capability_family 命名，避免与已确认的模型簇混淆。Web Search 是另一类服务，本次继续由 Web owner 配置，不为统一页面制造“搜索模型”。

### 5.3 配置结构与所有权

建议正式 scope 为 infra.model_services，文件为 configs/infra/model_services.toml。Infra 只解释用途、模型、连接和专用协议；Memory 继续拥有检索融合、向量缓存和降级，未来生成插件拥有生成工作及 Workspace 产物。

~~~toml
[infra.model_services.providers.embedding_direct]
protocols = ["openai_embedding"]
base_url = "https://open.bigmodel.cn/api/paas/v4"
api_key_envs = ["GLM_EMBEDDING_API_KEY"]
enabled = true

[infra.model_services.providers.embedding_relay]
protocols = ["openai_embedding"]
base_url = "https://embedding-relay.example/v1"
api_key_envs = ["EMBEDDING_RELAY_KEY"]
enabled = true
# proxy_env = "MODEL_HTTP_PROXY"

[infra.model_services.models.embedding_main]
kind = "embedding"
adapter = "openai_embedding"
providers = [
  { provider = "embedding_direct", provider_model = "embedding-3" },
  { provider = "embedding_relay", provider_model = "embedding-3" }
]
[infra.model_services.models.embedding_main.options]
dimensions = 1024
batch_size = 64
timeout_seconds = 30

[infra.model_services.uses.embedding]
kind = "embedding"
model = "embedding_main"

[infra.model_services.providers.typesafe_direct]
protocols = ["typesafe_system_one"]
base_url = "https://api.typesafe.ai"
api_key_envs = ["TYPESAFE_API_KEY"]
enabled = true

[infra.model_services.models.jev_main]
kind = "structured_decision"
adapter = "typesafe_system_one"
providers = [{ provider = "typesafe_direct", provider_model = "jev-latest" }]
[infra.model_services.models.jev_main.options]
timeout_seconds = 30

[infra.model_services.uses.decision]
kind = "structured_decision"
model = "jev_main"
~~~

示例中的 relay 地址仅展示配置形状，不是可使用的服务。目录可以保存多个具体模型；用途一次只引用一个。未绑定用途可保存 model="" 并显示未配置；真实消费者引用它时必须验证已有具体模型。Provider bindings 表示同一逻辑模型的不同接入，不能靠把 provider_model 指向其他模型来暗中实现 Model Chain。

image_generation 使用相同的 use/model/provider 关系；只有被显式注册且有明确 schema 的协议可被选择。未选定生图服务商前，不定义万能 image options，不假定所有接口共有 size/quality/style。可以保存类别和已有协议的连接/模型映射；具体参数控件由该协议描述提供。协议未注册时只显示能力说明，不接受任意协议字符串为可调用模型。

配置类型在入口转换为 ModelUseSpec、专用模型配置判别联合和 Provider 连接类型；各 kind.options 有自己的字段校验，不在运行内部传播 dict[str, Any]。引用在完整候选上校验，允许同一批次同时创建 Provider、模型和用途。

共享部分抽到 Infra 的小型公共 provider 设施：连接参数、凭据引用投影、ModelProviderBinding、有序引用校验和 HTTP client 构造。LLM 与 Embedding 已有真实消费者，足以支持这些抽取；不添加统一 invoke(kind, payload) 或万能能力调度器。

LLM 继续拥有 llm.providers/models/tasks 和其 adapter 类型，专用目录拥有 infra.model_services。二者不是同一数据的两份来源，而是各协议目录；UI 使用 collection + id 定位，不能同名自动联动。可用显式“复制连接”一次生成可编辑草稿，并复用同一环境变量；不建设隐藏的跨目录继承。将来若明确需要全局共享 Provider，再单独迁移其所有权，本轮不夹带这项迁移。

### 5.4 配置支持与执行支持分别声明

本轮交付以下范围；确认记录见 §16：

1. 专用模型 catalog、parser、用途绑定、Provider 连接与排序，接入既有 GET config/catalog 和批量 apply。
2. 迁移现有 Embedding 消费链路，真正支持用途绑定和 Provider 顺序，而不只是画出设置控件。
3. JEV 保存连接、模型映射、超时与用途定义；目录标记 execution_support=not_integrated，consumer_refs 为空。不调用 JEV，不增加 JEV Action/检索流程，也不创建运行插件或空客户端。
4. 生图建立 capability 描述与同一编辑器入口；本轮未选定 adapter 的部分展示“尚未接入协议”，不编造可用请求参数。以后增加确定的 adapter 描述后，该页自然接受其具体配置。
5. catalog 区分可保存配置、运行 adapter 支持、消费者引用、凭据就绪；这些是派生说明，不再持久保存另一张能力状态表。

配置定义本身有设置管理消费者，但不代表已经具备 Agent 执行能力。启动只实例化被真实消费的 client。JEV 预存配置缺少凭据可以显示待补齐，不阻止与其无关的 Agent 启动；被启用 Memory 检索实际引用的 embedding 必须至少有一个启用且凭据就绪的 Provider；目录列出其余不可用接入的原因，运行时略过这些接入。现有 LLM enabled Provider 的校验语义不在本轮被无意更改。

无需新增 /infer 或前端直连供应商端点。专用目录编辑仍使用 API-06/07。凭据值仍按配置源的既有能力管理；Provider 存引用。

运行方案继续使用已确认的 LLM models/tasks/routing + 可选 budgets 范围。专用模型目录和 uses 作为项目设置，不随对话框方案切换；尤其不因切换聊天推理方案反复更换 Memory 向量空间。此处是对既有方案范围的明确化，不额外要求用户重新确认。

### 5.5 Embedding 迁移与 Provider 切换

当前真实调用位置是 MemoryPlugin.build_generation → build_embedding_client → MemoryEngine → MemoryEmbeddingIndex；当前 InfraSettings 只接受 infra.embedding。必须同时修改 parser、装配、catalog、模板与消费者，不能只加新 catalog 字段。

建议在 MemorySettings.semantic_search 增加 embedding_use（默认空字符串表示不用向量检索）；用户启用时引用 infra.model_services.uses.embedding。这样“是否为 Memory 使用向量检索”属于 Memory，具体模型连接属于 Infra。未来其他消费模块按需声明自己的 use 引用，不共享一个偷偷控制所有业务的全局 enabled。

构造返回窄的 EmbeddingRoutes，包含按配置排序的候选 EmbeddingClient 及统一 close；每个 client 保留现有 identity / max_batch_size / embed 协议，固定一个 Provider。Memory generation 创建并拥有这些客户端，不在 Infra 另设调度者。

MemoryEmbeddingIndex 使用现有操作锁，在一次 similarities 的固定 query/documents 集合中：

1. 按序选一个启用且配置可用的 route；整个尝试固定这个 client。
2. identity 匹配时可复用已有缓存；不匹配时从空候选向量集合准备，不能只比较 dimensions。
3. 用同一 client 完成所需文档批次及 query embedding；成功后才安装该候选缓存并计算相似度。
4. Provider 请求失败可换下一个 route，重新准备该 route 所需文档及 query，不把上一 route 的部分批次带过去。每个候选有界尝试，不引入轮询、熔断调度或后台恢复。
5. 配置/业务存储 IO 失败不靠切 Provider 修复；所有可用 route 用尽时沿当前 Memory lexical/reference 降级，查询结果说明实际检索方式。

缓存身份包含实际 adapter/endpoint/provider_model/维度及影响向量空间的模型选项。即使配置者认为两个转发地址相同，也不根据维度相同自动共享缓存。仍保留一份当前可重建缓存，不建立多 Provider 向量数据库。切换可能引起一次重建和额外请求量，前端说明即可；不为此加复杂自动预热。

旧 infra.embedding 字段通过显式迁移工具或项目迁移步骤转为 provider/model/use + Memory 引用；更新部署配置和模板后删除旧 parser/catalog。不能启动时同时读取新旧两套并猜优先级。注入客户端的 SDK 使用方式应保持明确借用/拥有语义，按真实使用点调整窄类型，不为旧配置保留平行执行链。

### 5.6 代理与不同能力的切换语义

API 转发是另一个 base_url/Provider binding；出站网络代理是单个 Provider 的传输设置。建议公共字段 proxy_env 引用 HTTP(S) 代理地址，缺省沿现有 HTTP transport 的默认环境行为；显式引用不存在则配置错误。proxy_env 的实际值由同一 runtime_env 解析，展示为就绪状态，不把认证代理 URL 当普通日志输出。

本轮让 LLM 与实际 Embedding HTTP client 消费该字段，避免只画“代理”开关；需要更新各实际 adapter 的 client 注入/关闭方式。JEV 的同字段为预存连接配置。SOCKS 等额外协议只有实际 transport 安装并通过验证才声明支持，不把 API 地址、HTTP CONNECT 代理和 MCP transport 混为一物。

| 能力 | Provider 切换责任 |
|---|---|
| LLM | 继续复用现有 Task Model Chain 与 Model Provider Chain，公共连接抽取不重写选择器 |
| Embedding | Memory 固定一次检索 route，文档/query 同源；Infra 负责单 route 请求与有限 EmbeddingError |
| JEV | 未来结构化判断 adapter/消费 owner 处理一次明确请求的有界尝试；不走聊天工具协议 |
| 图像生成 | 未来生成 owner 根据是否已受理处理后续查询，长任务接现有 Job；本轮不提前建立第二套生成 Job 状态机 |
| Web Search | 保留 Web owner 的服务与 fallback，不注册成专用模型以凑统一形式 |

网络 SDK 异常在 adapter 处压缩为有限模块错误；Memory 的可选检索失败仍由 Memory 降级。配置错误返回现有 ConfigError，真正需要改变 Turn 控制流时由实际消费模块 bridge 处理，不在 Infra 增加 Runtime bridge。

### 5.7 Action 的模型使用：配置视图与实际执行归属

状态：proposed（Q-02）。这一节提出 Action 页集中管理实际模型使用及所需描述契约，不承诺本轮接入 JEV 执行，也不将所有 Action 迁移到一个通用模型 runner。

#### 5.7.1 当前代码审查

| 真实消费者 | 当前路径/行为 | 前端应表达 |
|---|---|---|
| Phase1 / Phase2 | kernel/loop/config.py 的两个 task_profile；plugins/reflection/builder.py 也传入相同 cycle_settings | 循环分配共用；不虚构 Reflection 专属模型链 |
| 真正的 LLM Action | kernel/action/config.py 的默认/override；agent/composition/actions.py 给各情景同样的 resolver | Actions 模型使用可编辑继承或覆盖；路由仍属于 action.llm_action |
| home.top.search | catalog 为 native；plugins/home/content/search.py 的 LLMHomeSearchReranker 使用固定 TaskProfile.HOME_SEARCH | 原生动作内部也有模型依赖；显示固定 home_search 引用及链编辑链接，不假装支持 action override |
| memory.write / write_daily、home.review | 原生服务提交/审核；内容由正常决策和实际 LLM 动作准备 | 不为提交动作增加模型选择器，不把 Reflection 当成一种模型类型 |
| Memory 语义检索 | Memory owner 的检索/向量缓存；本轮 B1b 迁移 embedding_use | 共享服务消费，不为每个关联 Action 复制 Embedding 绑定 |
| llm.tasks.memory_daily | 预置配置与 TaskProfile 枚举仍存在；仓库内未找到内置生产调用 | 显示配置对象及未发现内置引用，不当作当前 Reflection 使用链；不自动删除用户配置 |

backend.kind 描述执行入口，不能独自回答“该动作内部是否使用模型”。同样，处于 memory_reflection 情景也不能证明动作本身是 LLM Action。UI 不按 action 名字、domain 或 task id 猜调用关系。

#### 5.7.2 本轮建议落地的窄描述契约

复用 GET /v2/config/catalog 与 GET /v2/config/actions（API-06），由真实消费者/owner 向配置描述层贡献模型使用信息；Endpoint 只做映射。不增加一组 Action 模型写入 API，不解析源码、不从 Observation 反推配置。

可采用最小 ModelUsageDescriptor；以下为目标 DTO，不是运行中的抽象基类：

| 字段 | 含义与真实消费 |
|---|---|
| owner / usage_id / label | 一个 owner 内稳定的模型用途与可读名称，例如候选重排；一个动作允许多项 |
| action_ids | 关联动作；服务级消费允许空，不能为 UI 强造 Action |
| binding_kind / target_ref | llm_task 或 model_use，引用真实 collection/id；不是随意字符串 model id |
| source | 默认继承、显式覆盖、固定绑定或关联共享服务；前端说明值从哪里来 |
| edit_ref（可选） | 已有配置字段/对象定位；不存在可写路由时只提供查看或跳转，不生成输入框 |
| supported / reason | 当前实现能否消费该绑定及简短原因；JEV 预配置不能显示成已支持 Action 执行 |

静态引用由 owner 声明，配置引用由现有 resolver/config 构造；不建设运行时反射注册平台。描述当前生效绑定与候选草稿必须有清楚来源，配置候选校验使用同一解析规则。动作的授权/可见性与模型使用分开，情景筛选不创建当前不存在的 profile 专属路由。目录描述已配置动作与各情景状态，不能仅返回当前 User 情景 available 的动作而遗漏 Reflection 能力；模型路由可编辑资格仍由其真正支持的配置契约决定。

任务链页保留链定义及循环分配。Action 默认/override 只有一个主要编辑入口（Actions 模型使用）；旧 Action Routing 入口链接到这里。存储继续使用 action.llm_action.default_task_profile/overrides，经统一 ConfigDraft/API-07 应用。既有 llm_action override 只接受实际 LLM_ACTION 的校验不放宽为“所有 native 均可覆写”。固定 Home 检索链通过链定义页编辑，改变其 profile 身份需要另行明确 Home 配置与消费代码，不能由 UI 假造。

#### 5.7.3 未来可选择实现的设计边界

“模型使用”首先是业务用途，再选择该用途真正支持的实现。例如候选选择/重排可以在 owner 内实现 LLM 路径或 JEV 路径；必须先明确输入候选、允许选择范围、输出顺序/分值需求及失败语义，并验证各实现能满足同一结果契约。这个例子是候选方向，不是本轮认定的 JEV 消费功能。

推荐关系为：消费位置（Action 或服务）→ 具名用途 → 已实现方式 → LLM Task Profile 或专用 model use → 模型内 Provider 顺序。它不是所有场景都多出一套配置节点：当前固定消费者仍沿现有直接绑定；只有真正增加多实现时，才在该 owner 配置加入判别字段并替换该用途原单一路由。不要同时让旧 override 与新 binding 对同一用途生效。

- LLM 分支继续消费 TaskProfile/MessageStack/TaskResult；专用分支消费自己的输入/结果，owner 映射到业务结果。Embedding 向量、图像产物不伪装为 LLM 文本或 Tool Message。
- 一个 Action 可使用多个用途，例如检索向量与候选重排；各自有选择范围。不为每个 Action 定义万能的单一 model 属性。
- 可选方式由实际安装并实现的 owner 声明。只有 LLM 时显示链选择，不放失效的“切换到 JEV”开关；原生文件写入无模型选择；生图模型只供实现了生图输入/产物契约的功能使用。
- 方式在配置中显式选择。初次实现不增加跨类型自动回退链；每个模型内部的 Provider 链按各能力既有语义尝试。若未来需要 LLM/JEV 自动回退，应由具体业务证明结果等价后单独设计。
- 不因统一 UI 建立 UniversalModelRunner、万能 invoke、第二套 Action 状态机。选项描述与业务执行接口是两层；后者继续由具体插件拥有。

运行方案的本轮范围不变，包含 LLM models/tasks/routing 和可选 budgets。专用服务与 Embedding use 不随聊天方案切换。未来确实引入 Action 的多实现选择时，必须同时明确该选择是否纳入方案快照、未包含时如何呈现；本轮不预造无法执行的配置或把 JEV 开关隐含纳入方案。

#### 5.7.4 实施与验收

Q-02 确认后纳入 B1/F2：描述内核、LLM Action、固定 Home 重排与 Memory 服务四类真实来源；Actions 编辑后仍落同一配置对象；链/Provider 变化能通过引用关系解释到实际使用位置。代表性契约验证应覆盖 native 内部 LLM、默认/override 和共享服务，不能只测 llm_action 名单。

JEV 执行、生图及多实现业务选择仍为后续功能；本轮保存预配置、显示“尚未接入”即可。不能为使列表好看注册空执行器。

## 6. 交互事实与结构化问题

### 6.1 活动交互读取

新增 GET /v2/turns/{turn_id}/interactions?continuation=...：

- 返回 turn_id、generation_id、day、state、items、next_continuation。
- installed 事实从 Context/Trace 纯快照取得；尚未安装但已接受的用户记录从 Inbox 的公开只读捕获取得。
- 使用现有 input_id、question_id、Action call/result identity 去重和关联；不得按相同文本去重。
- queued Turn 的请求文本标记为 queued_request，尚不是 Session/Context 已接受输入。
- 交互角色与 SessionInteraction 对齐：user.input、user.append、user.reply、agent.question、agent.reason、agent.action、agent.output。
- 每项具有稳定 identity、来源 ref、关联、实际存在的 accepted/installed/visible 标记。不要根据时间或动画猜测“模型已经看到”。
- 当前 current_facts 仅有 inputs/actions，需要补充不封存 Trace 的公开事实快照方法；不能调用 end_turn/seal_trace 作为读取实现。
- pending Inbox 记录与已安装事实按稳定身份归并。事实列表用 owner 顺序；尚无事实位置的 pending 项单独表示，不能把 Inbox sequence 当成 Trace sequence。

轮结束后由 Session 必要 completion 保存事实；UI 以 turn_id 为容器，切换到正式 Session 投影并整体替换该轮的活动交互列表，不能拼接两份正文。输入复用现有 input_id，有结果的动作暴露既有 result_id 以关联；没有结果身份的取消/未执行动作不靠文本或列表下标猜配对。Session ref 用于历史导航，与活动 event/call identity 分开。已有 final drain 路径保留未进入模型请求的输入事实，并准确标示未可见。完成前取消的 queued request 不伪造 Session Turn。

新增只读交互投影不另建持久 transcript。若完成句柄仍存在而 Session 提交失败，则展示 TurnResult 的有限结果和持久化失败；不要用事件伪造已保存历史。

### 6.2 问题统一类型

定义单一 QuestionContent：text、options[{id,label,description?}]、allow_other。options 可为空表示自由回答；有选项时 allow_other 默认 true。继续只允许同一 Turn 一个活动 question，可与 budget_request 同时存在。

core.ask 结构化参数和 text 中的一个完整 tinysoul-question 代码块都归一化为 QuestionContent：

~~~json
{
  "question": "采用哪一种交付方式？",
  "options": [
    {"id":"patch","label":"提交代码修改","description":"交付可审查的变更"},
    {"id":"design","label":"只完善设计","description":"保留当前实现"}
  ],
  "allow_other": true
}
~~~

代码块不携带 question_id、Turn id、URL、HTTP 方法或可执行脚本；身份由实际 core.ask 执行结果提供。显式 options 与代码块同时表达冲突内容时返回局部参数失败，不猜优先级。单纯普通 Markdown 出现该块不能打开 Inbox 问题。

与现有小型代码块约束相称：最多 8 个选项、id 唯一、正文/说明有界，模型协议错误进入局部 Action 反馈。解析只处理指定 fence，不解析整篇 Markdown 为程序。

### 6.3 回复与历史

将 HTTP reply 的规范请求更新为带类型的 answer，SDK/Terminal 一同调整：

~~~json
{"question_id":"question_1","answer":{"kind":"choice","option_id":"patch","comment":""}}
~~~

~~~json
{"question_id":"question_1","answer":{"kind":"text","text":"我希望分两步交付……"}}
~~~

后端校验选项属于当前问题，生成可读的规范回复文本，保存 option_id 和自由文本的结构化选择事实。LLM 始终看到完整可理解回复，不仅看到“A”。

QuestionContent、TurnSnapshot、Action result、Inputs 和 Session 投影使用同一种结构；旧 HTTP response 字段在本次协同迁移中替换，不维持两种活跃协议。终端自由文本通过同一 text answer 入口。

旧归档没有选项 id 时按原始问题/选项文本只读呈现，不能猜测它等价于新的选择事实；历史 reader 适配保存在 codec 边界，不把旧活跃协议带回前端。

普通回答中的同类代码块保留原 Markdown；前端以 compose 模式呈现，只生成输入草稿。历史 ask 表单只读，不能把旧 question_id 发给新 Turn。

## 7. Session、Context 与日期读取

### 7.1 Session 浏览

新增接口：

| 方法与路径 | 用途 |
|---|---|
| GET /v2/days?before=YYYY-MM-DD&limit=30 | 当前日及归档日目录，来自 Archive catalog |
| GET /v2/session/turns?day=YYYY-MM-DD&continuation=... | 完成 User Turns 的摘要，稳定分页 |
| GET /v2/session/turns/{turn_id}?day=YYYY-MM-DD&continuation=... | 单 Turn 交互投影、结果摘要、事实 refs |
| GET /v2/session/map?day=YYYY-MM-DD | 地图根、导航入口、事实/解释统计和必要线索 |
| GET /v2/session/inspect?day=...&ref=...&query=...&continuation=... | 按既有 DisclosurePage 逐层追溯 |

请求省略 day 时解析为活动日，并在响应中返回实际 day；历史资源导航必须显式携带 day。列表/导航不能加载整日所有模型日志。

Map 返回 thread/note 的稳定身份、状态、来源引用、关系类型与共享节点身份；森林仅是导航投影，前端不能另存一棵语义树。撤回解释可以作为历史证据展开，不改写对话事实。Reflection 不进入 User Session。

Session 归档读取由 Session codec 解码原日事实和 map；缺少归档为明确 not_found，不自动切换到当前日。

### 7.2 活动 Context 读取

新增接口：

| 方法与路径 | 用途 |
|---|---|
| GET /v2/turns/{turn_id}/context | 已安装段目录与当前概览 |
| GET /v2/turns/{turn_id}/context/segments/{segment_id} | 某段本轮已安装正文与元数据 |
| GET /v2/turns/{turn_id}/context/inspect?ref=...&query=...&continuation=... | 只读披露页；复用 Segment inspector |

概览项包含 id、owner、slot、shape、order、capabilities、root_refs、available/loaded refs（适用时）、字符/图像量及其度量说明。不要把字符数伪称精确 token 数。

段正文从已安装 segment.render/公开 snapshot 派生；不能用 owner 最新文件替代旧的已安装内容。metadata 随 SegmentProjection 保留，不再通过 message.label 前缀猜测。

UI inspect 与模型 core.context.inspect 共用 ref 路由和 DisclosurePage 的读取能力；UI 不走 ActionRunner、不追加工具结果、不生成 overlay，不改变 reclaim 保护。query 仍是 owner 支持范围内的确定性定位。

仅活动 Turn 存在可操作的 live Context。Turn 完成后关闭段，接口返回 context_unavailable；历史交互从 Session、历史消息栈从保留的 Observation 读取，不持久化第二份完整 Context。

## 8. Home、Memory 与 Workspace 资源视图

统一 ResourceLocator 只表达逻辑身份：

~~~json
{"link":"workspace:reports/result.md","day":"2026-09-23"}
~~~

附加字段按资源实际需要为 view、turn_id；不发送物理路径。动态 memory:current/latest/target 必须带来源 Turn/日或由 Context 返回已解析的目标，不能脱离绑定去打开“现在的 latest”。

### 8.1 Home

新增：

- GET /v2/home/catalog?view=effective|actual&space=...&query=...&continuation=...
- GET /v2/home/content?link=...&view=effective|actual
- GET /v2/home/changes?continuation=...
- GET /v2/home/diff?link=...

query 是 owner 目录/文本的确定性筛选，不复用需要模型调用的 Home search Action。目录同时覆盖顶层、资源和 Skill mount，但在 DTO 中保留不同 Link 类型。实际源码读取由 Home owner 完成，不能把 top/resource/skill 三种 Link 统一拼文件名。

changes/diff 为只读 review projection，提供创建/修改/删除、actual/effective 内容或有界 diff、truncated 和是否偏离 overlay baseline。它不发放 HomeReviewService 的写授权，不暴露 review token 作为前端提交凭证。发起整理用现有 POST /v2/reflection。

Home baseline 和 overlay 跨日，页面不提供虚构的每日 Home 快照。历史 action 的当时 diff 若仍被 Observation 保留则另行展示，并明确不同于当前差异。

### 8.2 Memory

新增：

- GET /v2/memory/active?day=YYYY-MM-DD：当日活动或冻结归档 Memory.md；
- GET /v2/memory/catalog?kind=...&query=...&continuation=...：确定性目录/文本筛选；
- GET /v2/memory/document?link=...：正文、类型、元数据、出链/反链与实际存在的来源；
- POST /v2/memory/search：query、mode=text|semantic、可选 kinds、limit。

普通目录读取不自动调用 Embedding。用户显式语义搜索复用 Memory inspect/检索 owner，并返回实际检索方式；未启用语义服务时给出明确提示，不伪造语义分数。持久 daily 与某日活动 Memory.md 是两个入口。

document 只接受持久 Memory Link；动态引用交由有绑定的 Context/active 路由。浏览接口不提交知识写入。

### 8.3 Workspace

复用全部现有 /v2/workspace 接口。扩展 manifest/resource/blob 的 GET 支持 day；历史来源由 Archive + Workspace 只读视图解析。写接口仍只作用当前日，不增加历史 PUT。

大文件内容读取补充有界分页/范围能力；blob 以 Range 或流式响应服务预览/下载，具体类型沿已有资源协议。界面可编辑类型通过 manifest/资源响应描述，不重新引入 digest/revision 或 retention。

Workspace 文档写入、append、edit、move、trash/restore 和 tags 返回正式 owner 结果。错误若携带已提交 Link，UI 据此重新读取，而不是统一提示“没有修改”。

## 9. Jobs、ACP、MCP 与环境

### 9.1 Job 详情

已有 Job 列表与 stop 保留；新增：

- GET /v2/turns/{turn_id}/jobs/{job_id}：统一 JobSnapshot 与有界 backend.describe 详情；
- GET /v2/turns/{turn_id}/jobs/{job_id}/output?continuation=...：只读、有界输出页。

输出页用统一 envelope：items（channel、text、可用顺序）、next_continuation、result_locators、truncated。opaque continuation 内部封装 execution 的 stdout/stderr cursor 或 ACP cursor，前端不猜字节与字符单位。

在 Jobs owner 中增加只读 output 能力，现有 execution.collect/subagent.collect 与 HTTP 共用后端读取函数；不把具体 backend 实例暴露给 Endpoint，也不建立另一套 collect 缓冲。若内部为读取而 flush 输出，它仍不改变执行决策。

pending_inputs 继续表示父 Agent 的待处理请求。用户需要参与时由父 Agent core.ask 转交，不新增 Job 通用 reply 路由。Turn 结束后 Job 被回收；历史输出由已写 Workspace 资源和 Session/Observation 关联呈现。

### 9.2 ACP 查询

新增 GET /v2/subagent，返回已配置 targets 和实际 connections：

- target/agent id、description；
- connection_id、ready/busy/unavailable、当前 turn_id、active_job_id；
- cwd 的 ResourceLocator、建立与最近活动时间（owner 已有或补充的事实）。

当前 SubagentEngine.connections(turn_id) 是本轮 Working 投影；增加 generation 范围只读列表以覆盖跨 Turn 空闲连接。两者派生自同一连接池，不能让监控页创建自己的连接。

本次 UI 提供查看、跳转 Job 和“将委派意图填入对话”；不增加脱离 Turn 的任意 delegate/permission API。配置页管理 agent 定义，模型仍使用 subagent.connect/delegate/respond 等正式动作。

### 9.3 MCP 查询与明确刷新

新增：

- GET /v2/expand/servers：配置启用、实际连接、目录是否已发现、已知 tool 数与最近失败；
- GET /v2/expand/tools?server_id=...&continuation=...：已发现目录的只读分页；
- POST /v2/expand/servers/{server_id}/refresh：用户明确要求建立连接/刷新目录。

GET 不隐式调用 discover 建立远端连接；ExpandEngine 当前 discover 包含真实 I/O，需要增加纯 snapshot 与显式 refresh 两条不同用途的公共方法，仍共用同一目录和连接 owner。

“配置允许”“连接就绪”“工具可调用”“当前 Turn 已检索/调用”分别表示，不能用一个绿点代替。tools 名含点/数字时仍以整个 tools 对象提交配置。

### 9.4 环境与 watcher

复用 status.runtime.sources 与 runtime.source_status。Workspace.changed 驱动查询失效；环境/Job 通知按正式 Observation 展示，不能直接将任意 EnvironmentEvent 注入为用户消息。

需要扩充的环境旁路只包含 source/topic/event id、目标 Turn、接收/消费阶段等必要摘要，不复制 Inbox 大正文。没有保留记录时标注观测窗口有限。watcher 故障只影响监听状态，不宣告 Workspace 无法写入。

## 10. Observation 与模型调用展示支持

### 10.1 定向查询

扩展 GET /v2/events：

- 保留 after、mode、limit、instance_id；
- 增加可选 turn_id、task_id、through；
- through 固定本次读取上界，避免用户打开详情时持续追赶新事件；
- cursor 表示已扫描的全局位置，过滤无匹配也应前进；gap 语义不变；
- scope 过滤在 buffer/journal 层完成，索引可重建，不新建任务数据库。

WebSocket 仍使用现有 normal/verbose/model 分级。默认 UI 订阅 verbose；model 大正文在查看详情时按 task_id 查询。若现有某类结果只在 model 级，补充轻量摘要，不强迫所有客户端接收完整提示词。

### 10.2 Task 与消息来源

在实际构造消息处保留轻量 provenance：segment_id、owner、slot、shape、message index 范围，以及 task-local guidance refs。经过 task 构造传入 LLM observation，不反向让 LLM 模块理解 Home/Session。

记录 task_id、所选 task profile、模型/Provider attempts 和实际可用 usage。请求视图明确为 TinySoul 的 provider-neutral MessageStack；供应商适配若未记录原始 HTTP payload，就不能标为“完整网络请求”。

保留真实消息顺序。TaskPrompt 单列为任务局部层；expand.search 返回内容属于工具 Trace，不放 Working。挂载技能可追溯至 domain/action、Link 和本次具体 task，不从文本标题推断。

只展示后端实际披露的 reasoning summary/结构化 reason 和 Action；不生成或声称能展开未披露的供应商内部推理。

### 10.3 动作展示数据

Action 执行外壳沿用 invoke/call identity、domain/action、state、result/failure。为 rich preview 增加有界的 owner 生成展示片段，例如 resource_change、search_hits、process_output、delegation、context_disclosure。

这些片段走 Observation，不污染模型 ActionResult 的错误反馈，不让 Hook 读取业务存储生成猜测。写入 owner 捕获当时真实 before/after/diff；无法得到时明确缺省。

大展示内容复用现有有界 journal 保留，超过限额标记 truncated；不为 UI 单独建立永久 diff 数据库。业务产物仍由 Workspace/Home/Memory owner 保存，观测中的资源链接携带来源身份。展开当前文件与展开历史 diff 是两个按钮。

旧 visualization/docs/demand 的处理：

| 旧需求 | 本次结论 |
|---|---|
| action-execution-started-event | 已由 action.execution 满足；前端迁移并关闭旧需求 |
| action-result-content-preview | 由 owner 提交时提供有界展示片段；覆盖现有真实写动作 |
| mounted-skills-event | 纳入 Task provenance/guidance refs，不另建技能挂载状态表 |

## 11. Endpoint 契约总表

E=现有，X=扩展，N=新增。请求/响应 JSON Schema 与 docs/endpoint 是实现后的唯一 wire 规范；本表是两份计划共享的对接清单。

| ID | 状态 | Endpoint 组 | 主要消费者 |
|---|---|---|---|
| API-01 | E | GET /v2/health；GET /v2/status | 连接、全局状态、运行观察 |
| API-02 | E | POST /v2/turns；GET /v2/turns/{turn_id} | 新轮、排队、状态/结果 |
| API-03 | X | POST /v2/turns/{turn_id}/input；reply；grant；cancel | 追加、表单、预算、停止；reply 更新类型 |
| API-04 | N | GET /v2/turns/{turn_id}/interactions | 活动对话及重连 |
| API-05 | E/X | GET /v2/events；WS /v2/events/ws | 实时、定向历史观测 |
| API-06 | X | GET /v2/config；GET /v2/config/catalog；GET /v2/config/actions | 设置、active/saved、模型元数据、能力分类；Q-02 建议补实际模型用途描述 |
| API-07 | E/N | PATCH /v2/config；POST /v2/config/reload；POST /v2/config/apply | 唯一配置控制器 |
| API-08 | N | /v2/config/presets 及 /{id} | 方案管理；激活走 API-07 |
| API-09 | N | GET /v2/days | 日期导航 |
| API-10 | N | /v2/session/turns、/turns/{turn_id}、/map、/inspect（GET） | 历史交互、Session map |
| API-11 | N | /v2/turns/{turn_id}/context、/context/segments/{segment_id}、/context/inspect（GET） | 活动 Context |
| API-12 | N | /v2/home/catalog、/content、/changes、/diff（GET） | Home 内容与差异 |
| API-13 | N | /v2/memory/active、/catalog、/document（GET）；POST /v2/memory/search | Memory 页面 |
| API-14 | E/X | 现有 /v2/workspace/*，GET 增加 day 和有界大内容读取 | Workspace 与资源路由 |
| API-15 | E | GET/POST /v2/reflection | Home/Memory 整理 |
| API-16 | E/N | GET /v2/turns/{turn_id}/jobs；GET /jobs/{job_id}；GET /jobs/{job_id}/output；POST /jobs/{job_id}/stop | 统一 Jobs |
| API-17 | N | GET /v2/subagent | ACP 目标与连接 |
| API-18 | N | GET /v2/expand/servers；GET /v2/expand/tools；POST /v2/expand/servers/{server_id}/refresh | MCP |
| API-19 | E | POST /v2/restart；POST /v2/control | 明确生命周期控制 |

表中 API-16 的 /jobs 后缀均在 /v2/turns/{turn_id} 下，不是全局 Job 路径。所有分页沿 owner 的有界 continuation；大内容不放 status。

## 12. 实施组织与阶段验收

| 阶段 | 内容 | 前端对应 | 状态 |
|---|---|---|---|
| B0 | 契约 DTO、API 清单、源代码依据与旧需求归并 | F0 | pending |
| B1 | active/saved、apply、model family/collapsed、preset scope/CRUD | F1/F2 | pending |
| B1b | 专用用途目录、Embedding 迁移/Provider 顺序、公共代理传输；已确认范围 | F2 专用模型页 | pending |
| B2 | 活动交互投影、QuestionContent、结构化 reply、Session 接续 | F3 | pending |
| B3 | 日期/归档查询、Session 浏览、Context 目录和只读 inspect | F3/F4 | pending |
| B4 | Home/Memory 浏览、Workspace 归档、大资源读取 | F5 | pending |
| B5 | Job 详情/输出、ACP/MCP 查询及显式 refresh | F6 | pending |
| B6 | 定向事件查询、Task provenance、动作展示片段 | F4/F6 | pending |
| B7 | 端到端联调、旧路径清理、正式文档与门禁 | F7 | pending |

### B0：契约落地

- [ ] 逐项确定请求/响应类型、稳定错误与分页语义；路径按 API 表固定。
- [ ] 建立 owner 到 SDK 到 Endpoint 的调用图，避免路由直接读私有存储。
- [ ] 为真实数据准备小型集成 fixture；前端 mock 使用相同 DTO。
- [ ] 正式 docs/endpoint 只在接口落地时更新，规划状态保留本文。

### B1：设置闭环

Q-02 确认后追加 §5.7 的模型用途/消费者描述；不迁移实际 LLM 路由存储，不实现跨模型种类自动回退。

- [ ] 合并 apply/reload 共用内部流程；验证 busy、非法整批、候选构建失败、成功发布。
- [ ] 新增字段允许解析并展示，collapsed 不影响调用。
- [ ] Preset 捕获与编译覆盖 includes/deletes；A→B→A 不遗留字段。
- [ ] preset budgets 可选组的包含/不包含行为一致；任务重试次数与 Turn 额度没有混淆。
- [ ] 凭据 .env 与 TOML 编辑参与同一候选/receipt；active/saved 脱敏且草稿不误清。
- [ ] catalog capability_kind 不与模型 family 混用；Web 保留服务语义。

### B1b：专用模型（范围已确认，待实施）

- [ ] 保存用途 → 单模型 → 有序 Provider；kind/adapter/引用在候选内完整校验。
- [ ] Memory 消费 embedding_use；删除 infra.embedding 双轨配置，交付显式配置迁移步骤。
- [ ] 切 route 时文档/query 不混空间；失败保持原缓存或明确重建，不把存储失败当 Provider 故障。
- [ ] 专用 adapter 与 LLM 实际消费公共代理字段；借用/拥有客户端的 close 正确。
- [ ] JEV 只存配置且消费者为空；无全局 client 启动、无假 enabled 状态。
- [ ] UI 可以区分支持配置、支持运行、已被消费和凭据就绪。

### B2/B3：交互与 Context

- [ ] 正常问答、追加、ask/choice/other、暂停补额、取消、排队分别能查询。
- [ ] 同一输入在收据、Inbox、Context、Session 中保持 input_id；历史动作 ref 不冒充活动 call identity。
- [ ] 重连读取不遗漏已接受未安装的输入；最终收尾保留未进入模型请求的输入事实。
- [ ] 读取 live Context/inspect 不添加 Trace，不改变 loaded refs、folding 或保护状态。
- [ ] Session map 保持事实/解释区别、共享节点和日归档，查询不触发 organize。

### B4/B5/B6：资源与观察

- [ ] Home effective/actual/diff 来源一致，HTTP 不拿到 review 写服务。
- [ ] Memory active/daily/持久文档可区分，动态引用能定位来源。
- [ ] 归档 Workspace Link 打开原日资源；旧日编辑拒绝。
- [ ] ACP 空闲复用连接可观察；Job 输出查询与 Action collect 共用读取能力。
- [ ] MCP GET 不发起连接，显式 refresh 与 Action 使用同一目录。
- [ ] filtered events 游标前进、through 上界和 gap 保持一致。
- [ ] 模型请求顺序与来源准确；历史 preview 不依赖最新文件。

### B7：验证与收口

- 聚焦 owner 契约测试，不重复每个字段在四层中的同一断言。
- Gateway 集成覆盖代表性完整链路；外部 ACP/MCP/模型以本地 fake transports 验证，真实服务测试单独显式启用。
- 运行脚本 Fast 做日常反馈；最终运行 scripts/test.ps1 -Suite Full 与 scripts/typecheck.ps1，按 AGENTS 要求记录结果。
- 同步 docs/design 对应模块和 docs/endpoint 的 runtime、configuration、events、workspace、reflection，并新增 context/session/home/memory/capabilities 的真实协议文档。
- 不保留 v1/maintenance、旧 Workspace CAS、旧字符串推断或第二套 questions/activation 实现。
- 本计划只有实现、配套文档和验证逐项完成后才更名 -done- 并归档。

## 13. 必须关注的正常主线

1. 用户批量改设置 → 校验出错保留草稿 → 修正并应用 → 新世代实际值与 UI 一致。
2. 保存两个包含预算的方案 → 对话旁切换 → 链和预算整体替换 → 活动 Turn 中不能切换。
3. 折叠旧模型 → 默认目录收起 → 被任务引用仍可见/调用 → 日志不丢失。
4. User Turn → 追加 → ask → 选择/其他 → grant → 完成 → Session 历史 → 日归档。
5. Context 折叠 → UI inspect 逐层读取 → 模型上下文保持原状。
6. Home overlay → diff 浏览 → 发起 Home Reflection → owner 提交后更新。
7. ACP 连接 → 委派 Job → 输出/待答 → 父 Agent ask → 收尾 → 空闲连接继续可见。
8. MCP 配置保存 → 尚未连接 → 显式发现 → 工具展示 → Agent Action 使用同一目录。
9. 历史任务详情超过观测保留窗口 → 显示正文不可用，Session 的问答与事实仍存在。

## 14. JEV 依据与后续应用边界

核对日期：2026-09-23。官方 Quick start/API 使用 POST https://api.typesafe.ai/v1/systemone，输入 state、model、questions，问题为 Choice、Score、Noul 等类型；示例模型为 jev-latest。Choice 的结果是给定集合中的选择及概率/置信信息。这支持将其归为独立结构化判断能力，而不是通用聊天模型。

本项目未来可以在检索或显式 JEV Action 中消费此能力；本文不决定调用位置、不宣称已接入，也不据文档营销描述承诺性能。正式实现时重新核对供应商 schema。

- [TypeSafe Quick start](https://docs.typesafe.ai/introduction/quickstart)
- [TypeSafe API](https://docs.typesafe.ai/api)
- [Choice](https://docs.typesafe.ai/primitives/choice)
- [Jev with coding agents](https://docs.typesafe.ai/introduction/coding-agents)

## 15. 本次文档交付记录

- 已完成：代码/AGENTS/Endpoint 核查、用户确认语义合并、后端目标契约与实施阶段设计。
- 未执行：任何后端功能修改、数据库/配置迁移、外部服务调用或实现门禁测试。
- 配套前端计划与本文使用同一版本、同一 API 编号；没有把已确认的方案范围、写边界或表单语义重新列为待确认。

## 16. r4 复核结论与确认记录

结论：在现有 SDK、PluginGeneration、ConfigController、owner service 和 Observation 之上增加窄的读视图及组合命令，合理且可落地。主要工作量是补齐查询契约和重写旧前端数据流，不需要再次改造 Agent 执行骨架。

| 复核点 | r1 缺口/风险 | 修订后的处理 |
|---|---|---|
| 专用模型 | 只有未来 capability 页，没有用途绑定与实际 Provider 链 | §5 固定 uses/models/providers，Embedding 迁移方案完整，已确认纳入 B1b |
| 可替换性 | 容易为一致 UI 造通用模型/重试框架 | 只共用连接与 binding；LLM/向量/结构化/图像仍有自己的协议 |
| 配置闭环 | 凭据页未明确纳入整批操作 | §4.2.1 纳入同一 candidate/receipt，无新凭据状态机 |
| 活动到历史 | 活动 call id 不等于 Session 中生成的 ref | 按 Turn 容器替换，保留 input_id/result_id，避免强行同 ID |
| 页面数据量 | 单轮历史/段正文仍可能很长 | 补充正文 continuation、明确快照与消息索引，不全量事件重建 |
| 能力就绪 | “已配置”“可执行”“已消费”容易混淆 | catalog 返回可解释投影，JEV 预配置不激活任何业务 |
| 连接迁移 | 旧桌面/浏览器有 protocol_version=1 假设 | F1 同时修正发现、health/status、WS 与错误呈现 |
| 设计交接 | 页面概述不能决定按钮行为与刷新时机 | 前端计划补充布局、状态、接口、逐文件迁移和验收样例 |

范围确认与本轮新增建议：

| ID | 决定或建议 | 实施边界 | 状态 |
|---|---|---|---|
| Q-01 | 本轮迁移 Embedding 的真实用途绑定与 Provider 链，并支持保存 JEV 预配置 | Embedding 完成配置到 Memory 消费闭环；JEV 暂不增加调用业务或运行插件。生图承接后续已注册协议。 | confirmed |
| Q-02 | Actions 页集中编辑真实模型使用；API-06 增加 owner 提供的窄使用描述 | 原 default/override 存储不变；固定引用只读跳转；共享服务不复制绑定；未来 LLM/JEV 按相容用途显式选实现 | proposed |
| Q-03 | 进一步整理 Action 模型用途层、Home 通用检索路由与 Reflection 生成写入 | 见独立架构提案；若确认，替换 Q-02 中保留旧路由结构的部分并迁移方案快照 | proposed |

既有范围继续成立，B1b 的 pending 表示设计已确认、代码尚待实施。r4 新增 Q-02 等待维护者确认编辑入口与模型用途描述方案；它不影响先推进已确认的基础工作。具体生图服务商与 JEV 消费场景仍属于后续功能，不重新打开 Q-01。

其他已确认事项不重新讨论：配置应用、LLM 运行方案及可选预算、表单回复、Session 日归档、Home/Memory 写入归属、显式插件组合。本次也不把备份更新、独立收藏库、浏览器代理等长期灵感夹带为隐含交付义务；相应资源/代码块/能力接口能继续承接。

## 附录 A. 新增查询的核心 DTO 约束

本附录固定前后端真正共同消费的数据，避免实施时把页面直接绑定 owner 私有存储。已有 Endpoint 的响应不为追求统一外壳而全部改写；新增 DTO 在对应 schema 中声明。

| DTO | 必要字段/含义 |
|---|---|
| DaySummary | day、state=active或archived；归档时间仅在 owner 存在该事实时返回 |
| SessionTurnSummary | turn_id、ref、day、status、initial_input_excerpt、output_excerpt、question_count；摘要只由既有事实截取 |
| InteractionItem | id、role、turn_id、ref（有正式事实时）、input_id/question_id/reply_to 等适用身份、content、delivery；delivery 区分 queued/accepted/installed/visible，不要求四阶段都出现 |
| ContextOverview | turn_id、generation_id、day、captured_at、segments；只表示当次已安装状态 |
| SegmentView | descriptor、root_refs、selection（可选）、usage、messages（仅段正文请求）；descriptor 直接投影已注册描述 |
| ResourceDocument | locator、title、media_type、text或有界结构化content、truncated、next_continuation；二进制通过 blob 获取 |
| ConnectionView | owner、id、state、关联 turn/job、只读资源定位；configured 与 connection state 分开 |
| JobOutputPage | job_id、items[{channel,text}]、next_continuation、result_locators、truncated；channel 不承诺外部 stdout/stderr 的精确因果总序 |
| PresetSummary | id、name、description、included_scopes、active_match、saved_match、validation_issues、updated_at |

QuestionContent 结构的 text/options 是问题事实；代码块 question 字段只在归一化边界映射为 text。提交 answer 的 choice.option_id 必须来自该问题；Other 使用 kind=text，不额外制造一个属于模型候选集合的假 option id。

普通列表采用 items + next_continuation；Session/Context 披露页保留既有 DisclosurePage 结构及其 continuation，不在前端再次包装一套导航节点身份。返回日/世代/来源身份是为避免读错对象，不是用于客户端提交 CAS。

新分页入口默认建议为 30 项，允许范围和字节上限由 owner 的既有容量约束决定；实现时在对应 Endpoint schema 中固定，不能仅依赖 UI 截断。静态 overview 不顺带展开全部正文。

## 附录 B. 接口实现与前端交接补充

### B.1 Catalog 与专用设置

在现有 catalog 的 collection/field/source 体系上增加能力描述，不建立第二份编辑 schema。配置语义和数据值分开：

| 投影 | 内容 | 消费者 |
|---|---|---|
| capability descriptor | capability_kind、标题、editor、支持的 adapter 描述、execution_support | 设置导航和条件表单 |
| use descriptor | use_id、kind、model_ref、consumer_refs；未绑定可为空 | 用途页及引用反查 |
| model descriptor | kind、adapter、options schema、有序 Provider bindings | 专用模型编辑器 |
| connection descriptor | source/collection、id、协议、地址摘要、credential_state、proxy_state | Provider 编辑与状态说明 |

字段/schema 为 package-owned 描述；状态和值来自 active/saved 的相应候选，不把“运行中 client”投影伪装为 saved 配置。消费者列表由显式装配声明/配置引用反查，不能让每个页面维护一张 use-to-plugin 私有表。JEV 的 consumer_refs 为空正是预配置状态。

已有 LLM catalog 保留各 collection 的身份；可用共享组件呈现，但不移动其 owner。专用模型在 LLM Task Chain 选择器中不可选，LLM 模型也不能填入 Embedding use。

Q-02 确认后，Action/catalog 的模型使用描述按 §5.7 交付。扩展“在哪里被使用”的查询投影，不新增另一份路由数据；模型种类可选范围由真实用途实现决定，不能因 JEV 预配置存在就标为 Action 可选。

### B.2 分页、读取与新鲜度

- API-04 和 API-10 单轮交互都返回有界 items + next_continuation；Turn 列表分页与正文分页分开。请求旧页不能重复产生交互。
- API-11 段正文返回有界 messages、原始 message index、捕获位置及下一页。对读视图的 continuation 绑定被读取内容；底层发生相关变化时提示重新获取该段，不拼接两份快照。复用已有 owner 披露协议，不增加全局 revision。
- API-10/11 DisclosurePage 使用原协议 ref/continuation；query 只在声明支持的范围定位。列表检索与 ref 披露共用导航组件，但不假定所有 State/Heap 都有 query。
- API-12 Home content/diff 与 API-13 Memory document 同样返回真实 truncated/continuation；如果某种格式没有更多可读内容，明确区分“观测已经截断”与“可继续分页”。
- 资源目录查询纯读；不为浏览进行 Organize、Context load、Reflection、模型检索或 MCP 自动 discover。

### B.3 变化通知的最小补齐

前端把事件视为更新线索，读取 owner 正式结果。优先复用现有提交/完成事件；确实没有覆盖时，在 owner 提交后补一个有限的 view invalidation 观测，带 owner、相关 day/turn/resource identity，不携带全文或生成新事实日志。

| 变化 | 应失效的查询 |
|---|---|
| Turn 接受输入/问题/补额/结束 | 该 Turn snapshot/interactions；完成后 Session 摘要/正文/地图 |
| Context 固定批次安装 | 活动 Context overview；用户打开的相关段显示可刷新提示 |
| Session Organize 提交 | 同日 map/相关 inspect 页，不重新请求所有 Turn 正文 |
| Workspace 提交或 watcher 变化 | 该日 manifest/相关资源；保留前端正在编辑的草稿 |
| Home/Memory 提交 | 对应 catalog/content/diff/search 结果；不覆盖历史模型请求 |
| Job 进度/目录发现 | 特定 Job/ACP/MCP 视图；打开输出时继续 cursor |
| config activation | active/saved/config readiness/preset 和代级能力快照 |

Observation 丢失时，页面聚焦、手动刷新或重连读取正式快照即可恢复；不为 UI 维护有保证送达的第二条事件总线。

### B.4 契约交接样例与错误呈现

B0 需交付真实 schema 对应的小型 fixtures：空项目；活动 UserTurn 含 accepted-but-not-installed input；ask 同时等待预算；已完成带问答的 Session；共享节点 map；已折叠 trace；Home overlay diff；Memory active 与 daily；ACP 空闲连接及 Job；MCP 尚未发现/已发现；active 与 saved 不同；混合凭据/TOML 的失败 apply。

每个新增路由给出 owner/SDK 调用入口、请求/响应样例、分页字段、稳定错误 code。不存在/context_unavailable、不可激活、字段错误、观测缺失属于不同展示状态；不得统一变成“连接失败”。沿现有 error envelope 和异常映射实现，不设计另一个 HTTP 控制流系统。

### B.5 Action 展示片段的最小结构

B6 在原 action.execution 关联信息下附可选 presentation，不取代正式 state/result/failure。片段至少有 kind、title、truncated 及适用 locators；已记录正文才带有限 content。kind 采用 resource_change/search_hits/process_output/delegation/context_disclosure 等有真实 renderer 的判别值，未知值前端仍能按 JSON 查看。

resource_change 的 before/after/diff 仅来自该次提交 owner；没有真实差异就只给改变的 locator 与操作种类。process_output 可以只给 Job/产物引用；不把整个 stdout 再复制到每条事件。模型 provenance 的 message index 指向实际发送的 TinySoul MessageStack；一个来源跨多条消息时给真实索引范围，不根据渲染标题重建。

片段格式由后端与 renderer fixture 同步维护；只新增有当前消费的类型和字段，不预设覆盖一切 Action 的巨大 schema。对模型的 ActionResult 与面向人的 presentation 分别是有界反馈与旁路展示，不建立两份业务执行事实。
