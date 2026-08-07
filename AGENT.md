# TinySoul 协作规约

本文档约定 TinySoul 项目的分析、设计、实现和文档维护规则。目标是保持设计清晰、代码干净、讨论充分，并让文档与实际实现长期一致。

## 核心定义

本节定义 TinySoul 的稳定概念和设计语义。具体类型、字段、方法、配置与存储协议由代码和 `docs/design/` 说明，不在此重复展开。

### 执行模型

用户轮/User Turn：从用户发起一轮输入开始，到该输入对应的 Agent 执行结束。一个 User Turn 可以包含多次 Agent Cycle、LLM Task 和 Action，也可以合并期间追加的用户输入；它最终收敛为回答、停止、耗尽或失败。

维护轮/Maintenance Turn：与 User Turn 同级的 Program work，用于 Home 与 Memory 等需要模型推理的维护任务。它复用同一套 Turn/Cycle/Phase 内核，但拥有独立语境、可用 Action 和完成条件，不产生用户回答，也不写入 User Session。

执行轮/Agent Cycle：Turn 内的一次完整“理解、决策、行动”循环，由三个顺序 Phase 组成：

1. Phase1 更新语境并选择一个或多个行动域；模型只看到 Control Tools 和域级语义，不看到全部 Action。
2. Phase2 在已选域内生成并归一化一个或多个 ActionCall；模型只看到这些域内的 Action Tools。
3. Phase3 将 ActionCall 组装为 ActionBatch 并执行，把结构化结果反馈到当前 Turn。

模型轮/LLM Call/LLM Task：一次独立模型调用。其输入是上层已经构造好的 MessageStack、当前 TaskPrompt、模型侧工具作用域和输出约束；LLM 模块负责模型选择、供应商适配、重试与结果解释，不负责业务状态变更或实际工具执行。

任务提示/TaskPrompt：只服务当前 LLM Task 的临时提示层，由任务引导、任务输入和期望输出三类 PromptBlock 组成。Phase2 可自动挂载领域 Skill；Action 内部的 LLM Task 可同时挂载领域 Skill 与动作 Skill。目标资源和参考资源只在所属 Action 内局部解析为任务输入，不进入通用 Context。

行动执行/Action：一次模型可选择的智能体行动。Action 定义同时包含模型可见的调用语义与框架执行语义；每个调用必须在所属批次内收敛为成功、失败或超时。需要跨 Cycle 监督的外部任务可以保留 Turn-scoped job，但每次启动、等待、检查、提交或停止仍是独立且已收敛的 Action。

模型侧工具/Tool Message：用于约束模型生成结构化调用意图，不等于工具已执行。Control Tools 在 Phase1 表达语境和流程控制意图，结果经校验后由对应模块消费；Action Tools 在 Phase2 表达行动参数，结果归一化为 ActionCall 后交给 Phase3。供应商原生 tool calling 只是 LLM 适配层映射，不进入 TinySoul 的核心身份和业务协议。

### 语境模型

语境/Context：Agent 对当前语言游戏状态与规则的整体认识，只属于一个活动 Turn。它由以下语义段组成：

- User Inputs：当前 Turn 的初始输入与已合并追加输入。
- Session Background：同一 Business Day 内已完成 prior Turns 的固定投影，在 Turn preparation 时注入，本轮内固定且不可逐出。
- BackgroundContext：由 Home、Memory 等 owner 提供的通用背景与目录；每个 Turn 重建，可按规则渐进加载或逐出。
- TurnTrace/TurnTraceContext：当前 Turn 按发生顺序积累的决策、Action 请求、结果和必要反馈；它可以压缩为可渐进检查的语义结构，但不因此复制第二份历史事实。
- WorkingContext：当前任务工作台，只表达 milestones、todos 与 Workspace 资源链接/摘要等现态，不保存文件正文。

构造式 MessageStack：Context 在每次 LLM Task 前根据当前状态重新构造输入，稳定顺序为 system identity、User Inputs、Session Background、通用 Background、TurnTrace、WorkingContext、TaskPrompt overlay。identity 使用 system role；用户态语境和任务提示使用 user role；TinySoul Tool Result 保留内部工具结果语义，再由供应商适配层映射。revision、digest、cursor 等完整性事实只在确有消费者时由 owner 协议维护，不因内部存在就自动暴露给模型。

持久化、内存与模型反馈：持久化是 owner 写入本地目录的长期或跨 Turn 事实；内存是模块在运行期维护的状态；模型反馈是从这些状态投影并构造出的 MessageStack 或 ActionResult。三者必须可相互解释，但不能混为同一份数据或互相替代。

语块与渐进式加载：语块把细节归纳为可识别的稳定表达；渐进式加载则让 Agent 先看到 Link、摘要或语义节点，再在确有需要时显式展开细节。Context 默认承载决策所需的有界语义，不自动内联完整知识、历史或资源正文。

### 资源与持久化

链接/Link：跨模块传递的稳定资源身份，不是可由任意模块拼接的物理路径。Link 由所属 owner 解析、校验和映射，主要分为五类：

- `home:<space>@<logical-path>` 表示可进入 Background 的 Home 顶层内容；`agent` 存放身份规约与用户偏好，`skills` 存放通用技能。
- `home:<space>/<resource-path>` 表示只能由 Action 渐进读取或使用的 Home 资源，保留真实扩展名。
- `memory:daily/YYYY-MM-DD`、`memory:entity/<name>`、`memory:concept/<name>`、`memory:fact/<cite>` 与 `memory:note/<cite>` 表示五类持久 Memory Markdown；`memory:current`、`memory:latest`、`memory:target` 只是在特定 Context 中解析的动态背景引用，不是持久 Link。
- `workspace:<relative-path>` 表示当日工作区资源句柄。
- `home:skills_domain:<domain>` 与 `home:skills_action:<domain>/<action>` 表示局部自动 prompt mount，只进入对应 Phase 或 Action 内部任务，不作为普通 Background 或资源读取入口。

工作区/Workspace：当前 Business Day 的可操作资源空间。磁盘文件是内容事实，manifest 是资源索引和摘要，WorkingContext 只接收同一状态的 Link/summary 投影。文件正文通常不进入 Context；显式有界读取可作为当前交互结果，LLM 辅助的资源操作则在 Action 内部按 `target_link` 和 `reference_links` 局部读取，并在提交前复验来源版本。

Agent Home：Agent 的持久身份规约、用户偏好、通用 Skill 和行动指导，不包含日期 Memory。actual Home 是已由 Maintenance 接受的基线；普通 User Turn 通过跨日 runtime overlay 形成 effective Home，只有 Home Maintenance 可以把变更提交回 actual Home。顶层内容可进入 Background，渐进资源只通过 Action 使用，领域/动作 Skill 只在对应任务局部挂载。

记忆/Memory：与 Home 平级，分为活动记忆、daily 情景证据和 entity/concept/fact/note 持久知识。活动 `Memory.md` 位于当日 Session root，User Turn 只通过 `memory.memorize` 做 CAS patch；五类持久 Markdown 只由 Memory Maintenance 维护。User Turn 通过 `memory.inspect` 结合 lexical、grep、正向引用、backlinks 和可选语义检索发现 Link，再由 `memory.recall` 精确召回完整文档。Markdown 是唯一业务事实，catalog 与 embedding cache 均是可删除重建的派生数据。

会话/Session：同一 Business Day 内已经完成的 User Turns 所形成的不可变业务事实。Session 从同一事实图派生 prior-turn Background、渐进检查和 Memory facts，不保存当前 Turn 的运行时 trace，不承担通用日志或前端审计数据库职责。

主要持久目录：

- `home/`：Maintenance 已接受的 actual Home。
- `memory/`：daily/entity/concept/fact/note 五类持久 Markdown，以及可删除的 `.tinysoul/` 派生缓存和事务 journal。
- `runtime/`：活动状态，主要包括带 `Memory.md` 的当日 Session、Workspace、active Trash、跨日 Home overlay 和进程服务状态。
- `archive/<timestamp>/`：已冻结 Business Day 的 Session（包含当日 `Memory.md`）、Workspace 与 Trash；不包含 Home，持久 `memory/` 也不随日切移入归档。

### 运行控制

运行层级：从外到内为 Program、Turn、Cycle、Phase、Module。Program 拥有类型化请求队列与进程生命周期；Turn 表达一项完整的 User 或 Maintenance work；Cycle 和 Phase 组织推理与行动；Module 是 LLM、Action、Context 或持久化 owner 的具体执行边界。

Business Day 与每日生命周期：业务日由统一时区规则确定，并在一个 Turn 内保持不变。Session、Session root 内的活动 `Memory.md`、Workspace 和 active Trash 具有强制日生命周期；进入新日工作前必须先完成不依赖 LLM 的确定性日切、恢复、归档和新根初始化。新日 `Memory.md` 初始正文为空。Home 与持久 Memory 跨日保留且不进入归档；关闭日 daily 与知识由独立 Memory Maintenance 维护。

Trap/Runtime 语义异常：只用于需要改变运行位置的控制流，例如全局恢复、重试某一 frame、结束 Turn/Cycle/Program 或启动失败。模块应先完成自身局部恢复和失败归类，只有局部流程无法继续或需要全局协调时才进入 Trap；Trap 产生的运行转移必须指向当前捕获作用域内的合法 frame。

内部信号/Signal：用于需要业务模块消费的状态变更和跨模块数据传递，例如提交 Context patch、追加 TurnTrace、同步 Workspace 或合并用户追加输入。Signal 不决定全局恢复位置，消费与提交仍由拥有该协议的模块负责。

观察事件/Observation：只面向终端、前端、日志或嵌入方的 JSON 安全旁路事实，不参与业务提交和控制流。可观测性分为 normal、verbose、model 三个层级，其中 model 用于展示真实交给模型的上下文；Observation sink 失败不能反向影响业务结果。

行为模式：TinySoul-Agent 是一个面向个人的、允许超长时间后台多步运行的智能体，整体行为先充分探索和思考再进行产出：一步一步落实、把每一步工作都耐心仔细做好。智能体不急于回答和交付，而是精细于每一步工作；总体上秉持先探索思考，再设计规划，再产出执行，最后检查迭代的行动思路；细节上会合理拆分多步任务，不急于一次完成，少量多次地尝试和产出，每次做好局部细节的打磨和提交，最后检查交付完整成果。


## 项目规约

本节描述当前实现中各模块的长期职责与协作边界；具体实现以 `docs/design/` 和代码为准。设计或实现变更必须先判断所有权、数据流和失败归属，再同步更新相应设计文档与测试。

### 总体边界

- TinySoul 由 Program、Turn、Cycle、Phase 和 Module 组成的分层运行结构承载。外层负责装配、请求分派和生命周期，内层负责单一领域语义；上层不得绕过下层门面直接操作其私有状态。
- 每项持久事实只有一个 owner。跨模块协作使用稳定的类型化门面、provider、snapshot 或 signal；不复制状态、不建立平行日志、不保留语义不清的兼容别名。
- 运行时状态、模型反馈和持久化内容必须分层管理。模块维护自己的内存状态，Context 在调用模型前构造 MessageStack，持久化模块只在其提交边界写入事实。

### 模块职责

- `infra` 只提供配置来源、动态数据校验、JSON、文件和其他无业务基础设施；各业务模块自行解释自己的配置和失败。
- `runtime` 只负责运行位置、Trap、运行转移、信号和观察事件。它不执行 Action、不构造 Context、不访问业务存储。
- `app` 负责进程装配、Program 请求队列、外部输入解析和输出路由；Terminal、Endpoint、scheduler 等输入源只能提交类型化请求或控制意图。
- `loop` 提供可复用的 Turn/Cycle/Phase 内核。User Turn 与 Maintenance Turn 共用执行骨架，但各自拥有独立的 Context、Action 视图、准备流程和完成语义。
- `llm` 负责统一消息、模型侧工具协议、供应商适配、模型选择、重试和输出解释；它不选择或执行业务 Action，也不修改 Context。
- `action` 负责域与动作 catalog、Phase2 参数生成、Phase3 批次执行、超时/并发/hook 和结构化结果。供应商原生 tool calling 只存在于 LLM 适配边界。
- `context` 只拥有当前 Turn 的 User Inputs、Background、TurnTrace 和 Working，并按固定顺序构造 MessageStack。Home、Memory、Session、Workspace 通过明确投影提供内容，不能反向拥有整个 Context。
- `session` 只保存当日已完成 Turn 的不可变业务事实，并从同一事实图派生历史 Background、渐进检查和 Memory facts；它不是通用日志或前端审计库。
- `workspace` 是 `workspace:` 资源链接和当日工作区的唯一 owner，负责磁盘事实、manifest、版本一致性、文件变更、Trash 和归档投影。Context 只接收链接和摘要，文件正文只能在明确、有界的 Action 执行期读取。
- `home` 是 `home:` 内容和 Skill 的唯一 owner。actual Home 在普通运行中只读，User Turn 的改动写入跨日 runtime overlay；Home Maintenance 才能把审核后的变更提交回 actual Home。长期日期记忆不属于 Home。
- `memory` 是活动 `Memory.md`、五类持久 `memory:` Link、Markdown codec、检索 catalog、backlinks、派生 embedding cache 和多文档事务的唯一 owner。User Turn 只能 patch 活动记忆并 inspect/recall 持久记忆；Memory Maintenance 才能联合维护目标 daily 与 entity/concept/fact/note。
- `maintenance` 拥有业务时钟、确定性日切、归档以及 Home/Memory 维护任务的编排。Archive、Home、Memory 的私有存储仍由各自 owner 解释，维护任务之间不互读私有实现。
- `capabilities` 只承载无独立持久化和生命周期的具体能力，通过 Action 注册自身服务和执行器；不得另建与 Workspace、Home、Memory 或 Session 平行的状态模块。
- `endpoint` 是本地客户端协议适配层，与 Terminal 共用同一 App 和业务 Engine。它负责鉴权、请求映射和 Observation replay，不拥有业务状态、退出权或任意文件 API。

### 关键协作语义

- Phase1 只确定行动域并处理语境控制意图，Phase2 在已选域内生成 ActionCall，Phase3 执行 ActionBatch；每个调用都应归一化为可记录、可反馈的结果。
- Phase1/Phase2 framework Task 的可修正协议失败属于当前 Cycle 的局部 `PhaseFailure`：当前 Cycle 在失败 Phase 边界结束，反馈进入下一个完整 Cycle；Phase 不自行重复协议调用，Runtime 仍以 cycle budget、取消和 bridge 负责全局生命周期。Phase2 失败不得以空 ActionBatch 继续 Phase3。
- Context 的 Background、TurnTrace、Working 和 task prompt 是不同语义层：Background 提供可复用背景，Trace 记录本轮行为，Working 表达当前工作状态，task prompt 只服务当前 LLM Task。资源正文不因存在链接而自动进入 Context。
- Link 是跨模块资源身份，不是物理路径拼接约定。`home:`、`memory:`、`workspace:` 各自由 owner 解析；顶层内容、渐进资源、工作区资源和局部 Skill mount 不得混用。
- User 与 Home Maintenance Context 加载不可逐出的 `memory:current + optional memory:latest`；Memory Maintenance Context 加载不可逐出的 `memory:target + optional memory:latest`，其中 latest 始终是严格早于 Context 日的最近 daily，缺失时静默省略。
- Memory Maintenance 必须先 inspect/recall 已有内容再复用、修正或新增。既有持久 Link 不 hard delete；合并、替代或撤回保留非空迁移说明和有效非 daily redirect。`relations` 只表达 entity/concept 关系，daily/fact/note 来源由 `evidence` 表达。
- Session、Workspace、Home overlay 和 Memory 文档的写入都必须在 owner 的一致性边界完成，使用校验、reconcile、CAS 或原子替换保证不会产生半提交状态。LLM 生成期间读取的资源集合必须在提交时复验。
- User Turn 与 Maintenance Turn 都在完整情景中运行；Maintenance 是自治的 Program work，不等待人工审批，不把维护状态塞入 User Session，也不让维护请求绕过 Program 队列。

### 失败与控制流

- 失败按三层处理：可由模型或上层继续处理的局部事实返回结构化结果；模块契约、配置、依赖或持久化不满足时停在模块边界；只有需要改变全局运行位置时才转换为 Runtime 语义异常。
- 局部 Action、LLM 或 phase 失败必须带有稳定、有限、可反馈的原因和摘要，不携带原始异常、traceback、绝对路径、敏感值或大块资源正文。
- Milestone 是少量、持久、可复用的事实寄存器；除完成事实外，也可以记录有价值的尝试、失败、阻塞、计算值、决定、来源 Link、版本和 digest，但必须明确状态，不能伪装成 todo 完成。
- Runtime 异常只表达全局恢复、重试、中断或结束；signal 用于业务模块消费的状态变更和跨模块数据传递；Observation 只面向外部观察，不能反向改变控制流。
- 超时、取消、并发和受控进程必须服从所属 Action/Turn 的生命周期。需要硬停止的工作使用受控进程，不能让无法取消的本地任务阻塞 Runtime 转移。

### 实现约束

- 所有动态边界（配置、模型输出、外部协议、文件内容）在入口处校验并转换为明确类型；配置显式加载、显式传递，禁止导入时读取配置或创建隐式全局状态。
- 优先复用既有模块和门面；不预先建设通用插件平台、万能 Gateway、任意文件 API、第二套 Loop/Action 状态机或没有真实消费者的抽象。
- 文档、代码和测试共同描述当前实现事实。历史设计和旧测试只能帮助理解意图，不能成为保留模糊边界、重复状态或兼容层的理由。

## 工作方式

- 设计和实现前，应先理解现有设计思路、项目目标、模块边界和历史取舍。
- 在进行重要设计、架构调整、模块拆分或代码实现前，应先与项目维护者充分讨论，并呈现改动预览。
- 不应在未讨论清楚目标和边界时直接大规模实现。
- 如果发现当前设想与既有目标冲突，应先提出冲突点、可选方案和影响，再继续修改。
- 在继续设计或实现时，如果发现实际代码、外部接口或新需求与之前讨论规划产生冲突，应立即澄清问题并重新讨论清楚。不要用敷衍的临时性补丁绕过冲突。
- 基于 AGENT.md 整体设计思路与规约，先明确整体设计意图、现有代码思路，充分理解和分析后再进行进一步设计，避免重复冗余、边界模糊；要真实地分析问题所在，从上至下、从设计、架构到细节实现地考虑问题。在设计上不要被旧代码、工作量和测试兼容所约束；要关注架构合理、边界清晰、干净一致的设计与业务实现，不做临时补丁式最小实现。

## 设计原则

- 项目设计应从当前目标出发，参考既有思路，但不被旧实现牵制。
- 旧设计、旧测试和旧调用方式只作为理解历史意图的材料，不应成为保留模糊边界或兼容不清晰接口的理由。若旧测试与当前清晰架构冲突，应修改或删除旧测试，而不是用兼容层维持旧假设。
- 设计时应先检查现有设计、类别和边界，优先考虑复用或修改已有结构。只有在现有结构无法清晰表达新职责时，才引入新的类型、方法或模块，避免产生边界重复的抽象。
- 无需为了兼容历史结构而牺牲清晰度。必要时可以修改测试、删除旧假设、修改函数签名、重构架构，以保持项目清晰干净，干净地清除历史遗留问题。
- 设计应保持整体一致性：模块职责、对象关系、控制流、错误处理和状态模型必须能相互解释，不应各自独立演化。明确现有设计思路和整体设计意图，关注架构清晰、功能明确、一致干净的业务实现，进行深入分析、设计与规划。
- 基础的、公共的能力应放在通用目录或基础设施模块中，而不是放进某个业务模块。业务模块只保留自身语义，避免 JSON 边界、HTTP 客户端、序列化、通用校验等公共设施被局部模块私有化后重复出现。
- 架构设计要有长期视角，但实现必须落在真实功能上。不要因为当前规模小而采用短视结构，也不要预留没有实际功能的类型、接口或抽象。
- TinySoul 是个人项目，应优先服务真实能力和日常使用体验，不为工程完备性引入沉重的降级链路、复杂治理或企业级可靠性机制；但轻量不等于短视，模块边界、对象关系和能力模型必须从长远考虑想清楚，不能用阶段划分作为短视设计或临时补丁的理由。
- 不夸大设计价值。文档和代码都应准确描述当前能力、边界和风险。

## 代码风格

- 采用面向对象的代码风格，清楚设计每个类的意图、职责和生命周期。
- 保持代码质量和清晰架构，不做临时补丁式最小实现。
- 需要装配的业务模块对上层（Loop/Context）暴露单一组装门面（Engine/Builder 风格）作为装配与调用入口；模块内部散件默认只服务于模块内部与测试。
- 类型标注应尽量具体，避免不必要的 `Any`。确实需要动态边界时，应把 `Any` 限制在接口边缘，并尽快转换为明确结构。
- 错误处理、状态变更和副作用边界应显式表达，不依赖隐式约定或字符串拼接。
- 稳定标识符（失败类型、执行阶段、状态、模式等）使用 `StrEnum`；核心数据对象使用 frozen dataclass，并在 `__post_init__` 中校验不变量。
- 模块失败处理应区分三层语义：（1）可反馈局部结果，表示一次模型输出、一次 action call 或一次 phase 执行已经完成但不满足局部协议，可由调用方写入 Context 并反馈给后续模型；（2）模块边界异常，表示模块调用契约、配置、供应商、执行环境或内部不变量失败，当前局部流程不能继续；（3）Runtime 语义异常，表示需要由 Trap 改变全局运行控制流。不要把这三层混用。
- 可反馈局部结果应由模块自己的结果类型表达，例如 LLM 的 task failure result、Action 的 action result 或 phase result。局部结果应包含面向模型的简短反馈和框架内部摘要数据，但不应携带完整消息栈、原始异常对象、traceback、大块文件内容或不可 JSON 化对象。
- 正常业务流中可以被模型或上层策略修正的问题，应优先转为局部结果，而不是抛出普通异常。例如模型回答不符合任务解释协议、action 参数不符合 schema、hook 拒绝、action 执行失败、action 超时、phase 无法准备可用 action scope 等，都应成为局部结果，由 Context 或上层模块决定如何记录和反馈。
- 模块边界异常用于表达当前流程无法继续的契约性或环境性失败，例如配置无法解释、模型链耗尽、供应商不可恢复失败、调用参数违反模块契约、catalog 不变量破坏、内部对象不变量破坏等。这类异常不应作为普通上下文反馈继续执行，而应在模块公共边界转换为 Runtime 语义异常。
- 模块内部可以使用普通 Python 异常或模块私有异常表达内部失败；跨出模块边界并交给 Runtime 处理的异常，应在模块边界转换为 Runtime 可理解的语义异常，避免供应商、解析器或具体实现错误类型污染全局运行控制。
- 表达模块语义失败时，不直接抛出裸 `ValueError`、`TypeError` 等内置异常；应转为局部结果或使用模块私有异常；需要改变运行控制流时，再由模块边界的 bridge 转换为 Runtime 语义异常。
- 模块稳定失败语义应由模块内部维护；需要交给 Runtime 的失败由专门 bridge 映射为少量通用 Runtime 原因。bridge 应显式构造 message 和 JSON payload；原始异常链用于调试，不作为 payload 协议。
- 新模块接入 Runtime 时，应优先遵循 LLM、Action 和 Infra 的模式：模块内用 `failures.py` 维护服务于 Runtime bridge 的稳定失败枚举；需要 Runtime 协调控制流的失败由 `tinysoul/runtime/bridge/` 下的专门桥接代码通过映射表转换为 Runtime 语义异常；模块内部可自行处理或结构化返回的失败不进入 Runtime，也不必强行纳入 bridge failure 枚举。
- 模块 failure payload 应保持稳定、精简和 JSON 安全。跨 Runtime 边界时 payload 至少应能表达模块名和模块失败类型，其中 `kind` 使用 `<module>.<failure_name>` 格式的全局稳定标识，`module` 字段继续保留用于筛选和展示；并可按需携带 `error_type`、配置 key、profile、资源句柄等摘要字段；不要放原始异常对象、traceback、大块文件内容、完整消息栈或业务模块内部对象。
- Runtime 语义异常应通过稳定原因标识进入 Trap，由 Trap 处理器返回运行转移；Runtime 原因应收敛为启动失败、结束 Turn、结束 Cycle、结束 Program 和少量全局恢复原因，不要为恢复、中断、退出和无法处理的错误过早扩展庞大的异常继承树。
- Runtime 运行转移应以运行位置栈中的 frame 为目标，并收敛为重试 frame 或结束 frame；重试目标必须具备可重放语义，结束 Program frame 表示退出程序。
- 控制流变化应统一通过 Runtime 语义异常进入 Trap；信号只表达需要业务模块消费的事件和状态变更请求，Trap 处理过程中需要业务状态变更时也应发出信号交由对应模块消费；不参与业务提交、只面向外部输出的事件使用 ObservationEvent，不能反向改变控制流。
- 允许引入轻量、灵活、基础性的外部依赖，用于配置、数据校验、HTTP/API 客户端、序列化等通用基础能力。引入依赖时应说明其职责边界，避免为很小的问题引入沉重框架。
- 测试应服务于当前真实架构契约，而不是机械延续历史测试假设。
- 代码应通过 `ty` 语言服务器的类型检查。若类型检查暴露真实设计问题，应修正设计或类型边界，而不是用宽泛忽略掩盖问题。
- 增加新的 py 文件时要谨慎，先考虑现有设计，再考虑是否有必要新增，避免出现职责重复的文件或类型，避免架构模糊不清晰。

## 文档规则

文档分为三类，目录职责如下：

- `docs/design/`
  - 存放整体或模块级设计思路。
  - 描述设计目标、模块职责、关键概念、边界和取舍。
  - 重要设计调整应即时同步到对应设计文档。
  - 可以使用稳定的核心类型名标识模块协议对象，但不罗列类型字段清单、方法清单或代码业务细节。
  - 必须与实际代码保持一致，不能描述尚未落地的能力为已实现能力。
  - 创建和编辑文档时，不使用带有“第一版”“短期”“折中”等倾向的表述；文档应直接描述当前设计边界和职责，而不是阶段性权宜说法。

- `docs/chat/`
  - 以时间戳笔记记录与项目维护者的讨论、原始灵感、阶段性想法和未定稿方案。文件名使用 `yyyymmdd 主题.md` 格式。
  - 可以保留较原始的思考过程，但需要标明时间和上下文。

- `docs/analysis/`
  - 以时间戳笔记记录对项目代码、架构和潜在问题的分析。文件名使用 `yyyymmdd 主题.md` 格式；全部条目完结后，可在文件名中加 `-done-` 标记。
  - 分析项应标记状态，例如 `pending`、`in_progress`、`done` 或 `dropped`。
  - 已解决的问题应说明对应设计或实现位置。

## 运行环境与验证

- 默认运行环境为 Conda 环境 `TinySoul`。
- 需要运行 Python、测试或开发命令前，优先使用：

```powershell
conda activate TinySoul
```

- 修改代码后的日常反馈使用 Fast 测试；声明任务完成前，必须运行并通过完整本地门禁：

```powershell
.\scripts\test.ps1 -Suite Full
.\scripts\typecheck.ps1
```

`scripts/test.ps1` 默认运行 Fast 本地 pytest suite，排除 wheel 发布验收和真实 provider/network 测试；`-Suite Full` 加入 wheel 验收，`-Suite External` 只选择真实 provider/network 测试，后者仍需显式环境开关和凭据。每次运行使用 `.local-test/runs/<uuid>` 隔离 pytest、临时文件、实例锁和 cache，失败时保留工件。若当前 PowerShell 禁止脚本执行，使用 `powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\test.ps1`，不要把执行策略错误当作 pytest 失败。

标准工作流为：先按修改模块运行聚焦路径，再运行默认 Fast；完成前运行 `-Suite Full` 和 typecheck。日常开发环境通过 `conda activate TinySoul` 或设置 `TINYSOUL_PYTHON` 选择包含 pytest/ty 的 Python，随后通过 `python -m pip install -e ".[dev]"` 安装依赖。直接 `python -m pytest` 仍有 `tests/conftest.py` 兜底，会创建唯一 `.local-test` 临时目录，但标准入口优先，因为它还负责 cache 生命周期和 suite 语义。

- 测试约定：
  - 测试按 `tests/<module>/test_<切面>.py` 组织，镜像模块结构；
  - 触网或调用真实供应商的测试默认 skip，需显式开启。
  - `release` marker 表示 wheel 构建和隔离安装验收；`external` marker 表示真实 provider 或网络服务，默认不进入 Fast/Full。

- 用户对接：每次产生修改后阐述本轮改动了哪些文件，以及提供用于 commit 的文本内容
- 前后端协作：后端 agent 仅修改后端项目代码，不过多考虑 visualization；前端 agent 工作仅限于在 visualization 目录下修改，不改动后端项目代码；后端项目代码接口应全部通过 endpoint 向前端提供能力支持，在修改后端实现时，若发生 endpoint 改动，需即时在 docs\endpoint 中建立和调整文档，供前端对接；前端在进行前端设计和实现时，若发生缺失能力，不要阻塞设计和实现工作，允许暂时假定可行接口，并通过 visualization\docs\demand 向后端 agent 提出进一步能力需求。


## 当前任务

当前任务已从核心模块重构转入 TinySoul-AGENT 整体应用构建与优化，后端构建清晰正确的功能支持、前端提供美观的信息呈现。当前代码、模块设计文档和已完成执行记录才是实现事实；后续工作不得使用兼容层、重复状态或跨模块捷径。


### 推进顺序

当前实施进度可参照 docs\analysis 中的执行计划；已完成计划标记为 done；有含糊不明确的决策点/待确认的设计语义即时与用户讨论确认；即时将确认的设计语义，实施前明确的执行事项写入执行计划；即时维护执行计划，保持有限活跃的执行计划与计划更新。

### 实现纪律

- 保持模块所有权和三层失败语义。新增失败必须先归类为局部结果、模块边界异常或 Runtime 语义异常，不得用裸 `ValueError`、`RuntimeError` 或宽泛异常掩盖归属。
- 不预先建设通用插件平台、万能 Gateway、任意文件 API 或第二套 Loop/Action 状态机。
- 每完成一个应用阶段，同步更新 `docs/design/`、`docs/endpoint/`、前端协议文档、对应 `-done-` 执行记录和本节当前状态。

## 工作经验

- 从 TOML、JSON、环境变量或外部 API 进入项目的数据属于动态边界。应在入口处尽早校验并转换为项目内部的明确类型，避免让 `dict[str, Any]`、未知泛型或宽泛 `object` 在内部逻辑中扩散。
- 面对 `ty` 关于泛型不变性或类型收窄的报错时，应优先检查真实类型边界是否清楚。必要的 `cast` 应局限在已经经过运行时判断或校验的位置，并配合明确的转换函数使用。
- 不要把 `Mapping[object, object]` 当作“可接受任意映射”的通用入口。若内部需要字符串键配置，应直接表达为字符串键映射，并在动态数据入口做字符串键校验。
- 全新代码同样会滋生兼容 alias、空壳类型、未消费字段与参数这类死抽象；review 时应把死抽象作为专项检查项，而不是只检查错误处理与类型。
- 编码中容易按习惯抛出裸 `ValueError` 等内置异常而绕过三层失败语义。新增或修改 raise/except 时，应显式对照三层语义归类；review 时把裸内置异常和过宽的 `except Exception` 作为检查项。
