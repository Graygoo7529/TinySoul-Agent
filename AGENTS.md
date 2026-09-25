# TinySoul 协作规约

本文档约定 TinySoul 项目的分析、设计、实现和文档维护规则。目标是保持设计清晰、代码干净、讨论充分，并让文档与实际实现长期一致。

## 核心定义

本节定义稳定概念、所有权与协作语义。具体类型、字段、配置和存储协议由代码及 `docs/design/` 说明；历轮迁移过程与验证记录保留在 `docs/analysis/done/`，不以过渡条款覆盖当前规约。

### 执行模型

Agent 是嵌入式运行门面与根 work 的唯一调度者，拥有类型化请求队列、运行世代、环境事件路由和日期协调。SDK、Terminal、HTTP 与定时来源共用该入口，不各自维护执行状态机。

用户轮/User Turn：从用户输入开始，到对应执行收敛为回答、等待用户、停止、耗尽、取消或失败。一个 Turn 可以包含多次 Cycle、LLM Task 和 Action，接受期间追加输入或明确回复；结束一轮不宣告整体多轮目标完成。

Reflection Turn：同一个 Agent 的专门执行情景，与 User Turn 同级。Home/Memory Reflection 复用同一 Turn/Cycle/Phase 内核，通过 TurnProfile 取得独立 Context、Action 策略、来源视图和受约束服务；来源实例及生命周期属于 generation 的 PluginGeneration，profile 不拥有来源；不发布用户回答，不写入 User Session。每日策略或用户明确允许本次整理后，安排独立根 work；单次授权不形成持续许可。

执行轮/Agent Cycle：Turn 内的一次完整“理解、决策、行动”循环：

1. Phase1 更新语境并选择一个或多个行动域；模型只看到 Control Tools 和域级语义。
2. Phase2 在已选域内生成并归一化 ActionCall；模型只看到这些域内的 Action Tools。
3. Phase3 组装并执行 ActionBatch，把结构化结果反馈到当前 Turn。

LLM Task：一次独立生成模型调用。上层提供已经构造好的 MessageStack、TaskPrompt、模型工具作用域和输出约束；LLM 负责模型选择、供应商适配、重试与解释，不选择或执行业务 Action、不修改 Context。LLMTaskRunner.invoke 提供可组合结果与模块失败，run 复用相同调用并增加 Runtime bridge。Embedding/JEV 使用 infra.model_services 的 typed 输入输出；业务 owner 决定模型用途、Context 和候选语义。

TaskPrompt：只服务当前 LLM Task 的临时提示层，包含引导、输入和期望输出。Phase2 可挂载 domain Skill；Action 内部任务可同时挂载 domain/action Skill。目标与参考资源在所属 Action 内局部解析，不自动进入通用 Context。

Action：一次模型可选择、具有模型语义和执行策略的行动。execution.executor 绑定业务实现，runtime 管理唯一总时限和批次策略；宿主内执行、受控进程和模型依赖由实现组合。代码声明 model-use，配置选择实现与 target，ActionCall 不指定任意 provider/model。每次调用在所属批次内收敛；成功、失败、超时返回局部结果，取消、未执行和结果未知保留类型化执行事实，不伪造工具结果。需要跨 Cycle 监督的执行由 Job 承载；启动、检查、回应、等待或停止仍是独立 Action。

Job：属于唯一 Turn 的后台工作，可跨 Cycle，不能跨所属 Turn。kernel/jobs 监督状态、结果与待答，backend 持有实际执行资源；异步协议不等于所有行动都在后台。即时 shell/script 仍可等待结果后返回，长执行可启动 Job。Turn 收尾先停止并收集 Job，再提交必要事实和释放 session；执行终态与资源释放分开。

模型侧 Tool Message：约束模型生成结构化意图，不表示工具已执行。Control Tools 的意图经校验交给对应 owner，Action Tools 归一化为 ActionCall 后交给 Phase3。供应商原生 tool calling 只存在于 LLM 适配边界。

domain 是能力分组，TurnProfile 是同一 Agent 的执行情景。domain 提供可覆盖的默认选择，单动作可覆盖域选择；visibility 只筛选已经授予且可用的能力，不能授予缺失的写服务或 backend。

### 语境模型

Context 只属于一个活动 Turn。Kernel 按 Background、Trace、Working 三个槽位组合 Segment；段描述声明 owner、顺序、形状、引用路由及能力，领域内容由外围 owner 维护。State/Heap/Stack/Map 表达内容形状，渐进披露是访问方式，不是另一套持久化模型。

当前装配顺序为 system identity → Session → User Inputs → Home/Memory → TurnTrace → plan/Workspace/连接状态 → TaskPrompt。identity 使用 system role；用户态语境和任务提示使用 user role；TinySoul 工具结果保留内部语义，由 provider adapter 映射。

- Inputs 保存当前 Turn 初始输入、已接受追加与回复；排队但未接受的文本不是事实。
- Session 段组合语义地图引用与下方按历史顺序一次呈现的交互正文。本轮 prior-Turn 来源集合固定，已安装解释可以经 Organize 更新；多话题不复制正文，未归类 Turn 仍可见。
- Home/Memory 等 Heap 段维护本轮目录、默认内容、按需加载与逐出，不反向拥有整个 Context。
- TurnTrace 是当前 Turn 按 owner 观察顺序积累的输入可见位置、决策、执行事实与必要反馈。Stack 压缩保留原始引用和可读取的事实，不复制平行历史。
- Working 表达 plan 的 milestones/todos 及各插件的现态投影。Workspace 只提供 Link/说明等资源状态，不常驻文件正文。

构造式 MessageStack 在每个 LLM Task 前根据已安装段重新生成；render 纯读取，无文件操作。Signal 固定批次先解析、校验和 prepare，全部候选成功后同步 install；安装不重放已提交业务操作。prepare 不提交持久事实，completion 承担必要提交，close 只回收本轮视图。

持久化是 owner 保存的长期或跨 Turn 事实，内存是运行状态，模型反馈是两者的有界投影。三者须可相互解释，不能互相替代。revision、digest、cursor 等仅在确有消费者的 owner 协议中使用，不因内部存在就自动暴露给模型。

渐进披露以稳定 ref、标题、线索和直接入口引导按需读取。Trace 与 Session 共用 DisclosurePage/continuation；`core.context.inspect` 只读，query 在指定范围做确定性定位，不调用额外模型或永久展开 Background。完整 inspect 结果进入一次实际返回的决策模型请求后才允许折叠；容量拒绝不能解除保护。分页绑定实际读取内容，单纯背景折叠及无关注释变化不使未变页面失效。

Search 按 query discovery、seed refinement、backlink search 区分候选来源；Stage2 只选择已登记模式和业务参数，模型实现及 provider 由用途配置决定。seed 的显式 scope/filter 只定义资格，相关性由必需的 LLM/JEV selector 判断，不做隐藏词法或向量预筛；rank 保留候选，select 可以排除并返回空集。反链必须来自真实引用边，边归来源 owner，目标身份归目标 owner。Search 结果分页绑定 Turn/profile 或 SDK 服务 lease，辅助模型调用不解除 Inspect 展示保护。

Session 的地图和交互正文共用一个背景预算，只在自身高水位响应回收。先保留完整多轮交互，超限才明确摘录/折叠；问题、完整选项和关联回复不能被拆成孤立选择。最低投影保留事实与解释目录，同一轮刷新沿用已缩减预算。

### 资源与持久化

Link 是跨模块稳定资源身份，不是任意模块拼接的物理路径。所属 owner 负责解析、校验和映射：

- `home:<space>@<logical-path>`：可进入 Background 的顶层内容。
- `home:<space>/<resource-path>`：只能由 Action 渐进读取的 Home 资源，保留真实扩展名。
- `home:skills_domain:<domain>`、`home:skills_action:<domain>/<action>`：仅用于对应任务的局部 Skill mount。
- `memory:daily/YYYY-MM-DD`、`memory:entity/<name>`、`memory:concept/<name>`、`memory:fact/<cite>`、`memory:note/<cite>`：五类持久 Markdown。`memory:current/latest/target` 是 Context 内动态引用。
- `workspace:<relative-path>`：当日工作区资源。Session/Trace ref 定位原始交互或语义解释，不是文件 Link；归档资源保持原日身份。

Workspace 是当日可操作资源空间。磁盘是内容事实，manifest 是索引、说明和标签；pinned/tmp/library 标签不改变日生命周期。短 owner 操作串行、单文件原子提交；不维护内容 CAS、来源 read-set 或提交前复验。execution 直接操作真实当天 Workspace，取消不回滚已写文件，外部共写可能覆盖内容。Trash 由显式操作维护，不因 Context 压力删除文件。

Home 持有身份规约、用户偏好、通用 Skill 和行动指导。actual Home 是已接受基线；普通 Turn 的修改写入跨日 runtime overlay，形成 effective Home，只有 Home Reflection 的受约束 review 服务能接受回 actual Home。审核来源 token 保护真正的 review 语义，与 Workspace 不使用 CAS 不冲突。

 Memory 持有活动 Memory.md、五类持久 Markdown、Link/codec、catalog、backlinks 与可重建 embedding cache。普通 Turn 在 memory 域通过 memorize 原子 patch 活动记忆、search 发现候选、inspect 读取已知文档内容和 direct refs；search 的 backlink 模式查询真实入边，inspect 不包含 backlinks。只有 Memory Reflection 的写服务可提交持久文档。每次 write_daily/write 原子替换单个完整文档，引用目标须先存在，不建立多文档 draft/commit/journal。已有 daily 可重组和补充，无严格冻结语义；既有持久 Link 不 hard delete，迁移说明与 redirect 由 Memory 校验。

Session 持有当日已完成 User Turn 的不可变事实，以及单独的有来源语义注释。事实的 contains/precedes/replies_to/references 确定性派生；解释的 thread/note、成员和推导关系只由 User Turn 内 `core.session.organize` 原子修改。语义图允许共享与回路，森林只是导航投影，不另存树。修订/撤回保留稳定身份，不改写事实；合流创建新解释入口，保留旧分支。当前已接受输入或已结算 Action 可作补充证据，不能提前成为历史成员。Session 不承担通用日志、前端审计或跨日语义图职责。

主要目录：

- `home/`：actual Home；`memory/`：持久 Markdown 与可删除重建的派生缓存。
- `runtime/`：带活动 Memory.md 和 map.json 的当日 Session、Workspace、Trash、跨日 Home overlay 及进程服务状态。
- `archive/<timestamp>/`：冻结日的 Session（含 Memory.md、map）、Workspace 与 Trash；不包含 Home 或持久 memory。

### 运行控制

运行层级由外到内是 Agent、Turn、Cycle、Phase、Module。asyncio 承载唯一根调度；User 和 Reflection 共用内核，等待用户、Job、事件、定时器或预算仍占根执行位置，后续根 work 排队。

CalendarDay 由 infra 的统一时区时钟确定，Turn 的 active_day lease 持续到必要收尾完成。进入新日 work 前，agent/lifecycle 协调 owner 完成确定性日切、归档和新根初始化，不依赖 LLM 或 Reflection 成功。新日活动 Memory.md 为空，Session/map 为空；Home、overlay 和持久 Memory 跨日保留。Reflection 的 source_day/target_day 与执行日分开。

Trap/Runtime 语义异常只表达运行转移，例如容量恢复、重试 frame、结束 Cycle/Turn/Agent 或启动失败。模块先完成局部恢复和失败归类；只有局部流程不能继续或需要协调时进入 Trap，转移目标须是当前捕获作用域内的合法且可重放 frame。

Signal 表达需要业务 owner 消费的状态变更与跨模块数据，不决定全局恢复位置。EnvironmentEvent 由 Agent EventRouter 定向或按订阅进入 TurnInbox；独立 Trigger 可以排新根请求，Job 事件不能创建新根 Turn。观察事件 Observation 是面向终端、前端、日志和宿主的 JSON 安全旁路，normal/verbose/model 分级，sink 失败不影响业务。

TurnInbox 在等待期间持续受理，有界保存关键元数据，大输出由 owner 落盘；capture → prepare/install → ack 保持固定批次，新到输入留给后批。取消与预算决定不排在普通进度后。已接受关键事件在存活进程中不静默丢弃，不承诺崩溃续跑 Turn。预算耗尽进入受限 SUSPEND，由用户补额或中断；模型不依赖内部 Cycle 余额。

SDK 服务绑定运行世代，日级服务同时绑定 CalendarDay；切换后旧对象失效，调用者重新获取。Agent.wait_for_exit 等待宿主最终退出并跨 restart，不消费 Signal；等待者取消不取消运行，显式 shutdown 使未完成退出等待收到 CancelledError。

行为模式：TinySoul 是主动、耐心的思考与执行伙伴，允许超长时间后台多步运行。先探索理解，再设计规划，逐步落实、检查迭代，少量多次完成细节。可自行调查或有界恢复的问题先在当前 Turn 处理；依赖用户重大判断、信息或授权时，core.answer 可请求进一步指示并正常结束本轮，core.ask 可暂停同一轮等待明确回复。两者均不要求所有 todos 完成，也不宣告长期目标完成。

## 项目规约

### 总体边界

- 依赖方向为 `infra → runtime/llm → kernel → plugins/environment → agent → gateway`。上层通过稳定门面、服务、provider、snapshot 或 signal 协作，不绕过 owner 操作私有状态。
- 每项持久事实只有一个 owner；运行状态、模型投影和持久内容分层，不复制状态、不建立平行日志、不保留语义不清的兼容别名。
- 显式 PluginProfileExtension 贡献服务、段、动作、preparation/completion 和事件适配；PluginGeneration 持有代级 owner、来源与永久 close。只有具有仓库内真实消费者的 SPI 才加入协议，不构建动态发现平台。

### 模块职责

- `infra`：配置来源、JSON、文件、动态校验、时钟、HTTP、受控进程、标准 Markdown 引用语法及专用模型 typed 协议等无业务设施。ModelServices 持 generation 共享客户端，Home/Memory 各自拥有可重建向量索引；不拥有业务失败恢复或 Runtime bridge。
- `runtime`：运行位置、Trap/transfer、Signal、环境 envelope 和 Observation；不导入上层业务、不执行 Action 或访问业务存储。
- `llm`：统一消息/工具、模型选择、供应商适配、重试和输出解释。
- `kernel`：唯一 Turn/Cycle/Phase 骨架；action 负责 catalog、参数归一化、批次/timeout/hook 与模型用途绑定；context 负责段组合、控制意图和本轮事实；retrieval 组合有界候选、选择/排序与生命周期内分页，不拥有来源存储；jobs 负责 Turn-owned 监督。
- `plugins`：Session、Workspace、Home、Memory 等事实 owner 及 Reflection/Archive 协作。每个插件暴露单一组装门面，实际服务权限由情景授予。
- `plugins/execution`：真实 Workspace 上的 shell/script/process 能力；监督复用 kernel/jobs，进程控制复用 infra/process。
- `plugins/capabilities`：Web、资源、ACP subagent、MCP expand 等外围能力。可以持有 Agent 生命周期管理的 I/O 资源与派生目录，不另建调度器或与核心 owner 平行的持久事实。
- `environment`：输入适配、Workspace 文件监听和通用定时等待，通过注入端口协作；不解释 Reflection 业务策略。
- `agent`：SDK、根队列、世代装配、事件路由、服务 lease 和日协调；不复制内核。
- `gateway`：CLI、Terminal、Endpoint 和项目命令。Endpoint 负责鉴权、协议映射及 Observation replay，不拥有业务状态、退出权或任意文件 API。

### 关键协作语义

- Phase1/Phase2 可修正协议失败是局部 PhaseFailure：在失败 Phase 结束当前 Cycle，反馈给下一完整 Cycle；不在 Phase 内重试协议，不以空 ActionBatch 继续 Phase3。
- owner 先提交事实，再发刷新 Signal；段 prepare/install 更新本轮投影。Session 记录走唯一必要 completion，close 不再次提交。
- 当前证据快照纯读取，不调用 seal_trace 或 end_turn，不对已结算 Action 子集重新编号。Session 解释引用映射，Kernel 不解释语义图。
- User/Home Reflection 默认加载受保护的 memory:current/latest；Memory Reflection 加载目标来源的 target/latest，latest 严格早于来源日，缺失时省略。
- 普通对话不取得持久 Memory、actual Home 或 Reflection 专属写权限。SessionOrganizeService 只注入 User；SDK SessionService 与 Reflection 保持只读，无外部 Session 编辑 HTTP 接口。
- MCP expand 的 describe_servers/describe_tools/search/call 共用目录。自然语言检索是已登记 SearchPolicy 约束下的一次有界 LLM/JEV 候选精炼，Stage2 只能选择有限 scope、mode 和参数，超容量由父 Agent 缩小服务范围；MCP 配置支持 stdio 与 Streamable HTTP。ACP 显式连接后委派，空闲连接可跨 Turn 复用；Job 不跨 Turn，结束先停止 Job 再释放协议 session。
- 原生 watcher 只提供线索，Workspace owner 统一正式写入与外部变化，提交后发布事件；Context 在固定批次刷新。只监听活动 Workspace，来源故障停止并有限反馈，正式操作继续；不构建自动恢复状态机。日切/重载先停止并 join 来源，再切换绑定。

### 失败与控制流

- 三层失败严格区分：可修正局部结果、无法继续的模块边界异常、需要 Trap 改变运行位置的 Runtime 语义异常。
- 局部 Action/LLM/Phase 失败保留稳定有限原因和短反馈，不携带原始异常、traceback、敏感路径或大块正文。
- 取消复用所属生命周期。短 owner 操作完整 join 后才传播取消，长执行使用受控进程；必要 finish 失败影响结果，附属 close 诊断不能覆盖已提交主结果。
- Milestone 是少量可复用事实寄存器，可记录尝试、失败、阻塞、计算值、决定与来源，须明确状态，不能伪装成 todo 完成。

### 实现约束

- 动态边界尽早转换为明确类型；配置显式加载与传递，禁止导入时读取配置或创建隐式全局状态。
- 公共设施不私有化在业务模块；不建设万能 Gateway、任意文件 API、第二套 Loop/Action 状态机或无消费者抽象。
- 文档、代码与测试共同描述当前事实；旧设计和测试不作为保留重复实现、含糊边界或兼容层的理由。
- 架构语义应统一、接口简约、owner 清晰，支持插件替换与长期演进。先保证正常主线与结束边界，不为假设极端情况堆叠逐层防御、恢复链路或平行实现。
- 运行环境为个人使用的长期独立主机与远端前端；按受信主机假设设计，不为没有真实需求的企业级安全治理增加负担。

## 工作方式

- 设计和实现前，应先理解现有设计思路、项目目标、模块边界和历史取舍。
- 在进行重要设计、架构调整、模块拆分或代码实现前，应先与项目维护者充分讨论，并呈现改动预览。
- 不应在未讨论清楚目标和边界时直接大规模实现。
- 如果发现当前设想与既有目标冲突，应先提出冲突点、可选方案和影响，再继续修改。
- 在继续设计或实现时，如果发现实际代码、外部接口或新需求与之前讨论规划产生冲突，应立即澄清问题并重新讨论清楚。不要用敷衍的临时性补丁绕过冲突。
- 基于 AGENTS.md 整体设计思路与规约，先明确整体设计意图、现有代码思路，充分理解和分析后再进行进一步设计，避免重复冗余、边界模糊；要真实地分析问题所在，从上至下、从设计、架构到细节实现地考虑问题。在设计上不要被旧代码、工作量和测试兼容所约束；要关注架构合理、边界清晰、干净一致的设计与业务实现，不做临时补丁式最小实现。

## 设计原则

- 项目设计应从当前目标出发，参考既有思路，但不被旧实现牵制。
- 旧设计、旧测试和旧调用方式只作为理解历史意图的材料，不应成为保留模糊边界或兼容不清晰接口的理由。若旧测试与当前清晰架构冲突，应修改或删除旧测试，而不是用兼容层维持旧假设。
- 设计时应先检查现有设计、类别和边界，优先考虑复用或修改已有结构。只有在现有结构无法清晰表达新职责时，才引入新的类型、方法或模块，避免产生边界重复的抽象。
- 无需为了兼容历史结构而牺牲清晰度。必要时可以修改测试、删除旧假设、修改函数签名、重构架构，以保持项目清晰干净，干净地清除历史遗留问题。
- 设计应保持整体一致性：模块职责、对象关系、控制流、错误处理和状态模型必须能相互解释，不应各自独立演化。明确现有设计思路和整体设计意图，关注架构清晰、功能明确、一致干净的业务实现，进行深入分析、设计与规划。
- 以整体重构目标和真实功能主线评价抽象：通过一套统一的生命周期、owner 和类型化协议封装能力，使插件可维护、可替换、可扩展，对外接口简约明确并能长期演进。先把正常运行的数据流与结束边界设计清楚，再处理有证据的失败；避免重复状态机、缺少复用的平行实现、过度防御的逐层检验，以及围绕假设极端情况增加的迂回流程。简洁不是删除必要所有权或合理抽象，也不是重建 CAS 等与当前协作语义不符的约束。
- 模型语境只呈现有助于理解任务、选择行动和解释结果的语义。schema version、reconcile、revision、digest 等实现信息由相应 owner 封装；仅在确有模型侧消费者时才有界投影，不能把内部存储或恢复协议变成模型必须遵守的操作流程。
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
- 新模块接入 Runtime 时，应优先遵循 LLM 和 Action 的模式；Infra 保持纯基础设施，不设置 Runtime bridge，由实际调用 owner 解释其失败：模块内用 `failures.py` 维护服务于 Runtime bridge 的稳定失败枚举；需要 Runtime 协调控制流的失败由模块自带的 runtime bridge（统一位于所属 owner 包内 `runtime_bridge.py`）通过映射表转换为 Runtime 语义异常；Trap 原因常量由定义该原因的 owner 声明并登记处理器，`runtime` 只声明自身的启动失败与结束 Turn/Cycle/Agent 原因；模块内部可自行处理或结构化返回的失败不进入 Runtime，也不必强行纳入 bridge failure 枚举。
- 模块 failure payload 应保持稳定、精简和 JSON 安全。跨 Runtime 边界时 payload 至少应能表达模块名和模块失败类型，其中 `kind` 使用 `<module>.<failure_name>` 格式的全局稳定标识，`module` 字段继续保留用于筛选和展示；并可按需携带 `error_type`、配置 key、profile、资源句柄等摘要字段；不要放原始异常对象、traceback、大块文件内容、完整消息栈或业务模块内部对象。
- Runtime 语义异常应通过稳定原因标识进入 Trap，由 Trap 处理器返回运行转移；Runtime 原因应收敛为启动失败、结束 Turn、结束 Cycle、结束 Agent 和少量全局恢复原因，不要为恢复、中断、退出和无法处理的错误过早扩展庞大的异常继承树。
- Runtime 运行转移应以运行位置栈中的 frame 为目标，并收敛为重试 frame 或结束 frame；重试目标必须具备可重放语义，结束 Agent frame 表示退出程序。
- 控制流变化应统一通过 Runtime 语义异常进入 Trap；信号只表达需要业务模块消费的事件和状态变更请求，Trap 处理过程中需要业务状态变更时也应发出信号交由对应模块消费；不参与业务提交、只面向外部输出的事件使用 ObservationEvent，不能反向改变控制流。
- 允许引入轻量、灵活、基础性的外部依赖，用于配置、数据校验、HTTP/API 客户端、序列化等通用基础能力。引入依赖时应说明其职责边界，避免为很小的问题引入沉重框架。
- 测试应保护当前稳定契约、可观察行为和真实风险，不固化可编辑内容、实现细节、历史残影或重复快照。
- 同一契约原则上由其 owner 完整覆盖一次；跨模块测试只验证协作边界和代表性路径，回归与参数化用例保持能够区分真实行为的最小集合。
- 只有顺序、精确值或文本本身属于机器协议或明确稳定语义时才逐项断言；否则优先验证类型、结构、数据流、状态变化和结构化失败语义。
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
  - 以时间戳笔记记录对项目代码、架构和潜在问题的分析。文件名使用 `yyyymmdd 主题.md` 格式。
  - 分析项应标记状态，例如 `pending`、`in_progress`、`done` 或 `dropped`。
  - 已解决的问题应说明对应设计或实现位置。
  - 执行计划只有在计划条目、对应实现、文档同步和必要验证均已逐项核对完成后，才能标记为 `done`。完成时必须在文件名中加入 `-done-` 标记，并将文件移动至 `docs/analysis/done/`；尚未完成的执行计划保留在 `docs/analysis/`。

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

`scripts/test.ps1` 默认运行 Fast 本地业务逻辑 pytest suite，排除项目/资源生成、wheel 发布验收和真实 provider/network 测试；`-Suite Generation` 只运行项目/资源生成契约与 wheel 验收，`-Suite Full` 运行全部非 external 本地测试，`-Suite External` 只选择真实 provider/network 测试，后者仍需显式环境开关和凭据。每次运行使用 `.local-test/runs/<uuid>` 隔离 pytest、临时文件、实例锁和 cache，失败时保留工件。若当前 PowerShell 禁止脚本执行，使用 `powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\test.ps1`，不要把执行策略错误当作 pytest 失败。

标准工作流为：先按修改模块运行聚焦路径，再运行默认 Fast；完成前运行 `-Suite Full` 和 typecheck。日常开发环境通过 `conda activate TinySoul` 或设置 `TINYSOUL_PYTHON` 选择包含 pytest/ty 的 Python，随后通过 `python -m pip install -e ".[dev]"` 安装依赖。直接 `python -m pytest` 仍有 `tests/conftest.py` 兜底，会创建唯一 `.local-test` 临时目录，但标准入口优先，因为它还负责 cache 生命周期和 suite 语义。

- 测试约定：
  - 测试按 `tests/<module>/test_<切面>.py` 组织，镜像模块结构；
  - 触网或调用真实供应商的测试默认 skip，需显式开启。
  - `generation` marker 表示 package-owned 项目或资源生成契约；默认 Fast 不重复运行生产生成器。
  - `release` marker 表示 wheel 构建和隔离安装验收；`external` marker 表示真实 provider 或网络服务，默认不进入 Fast/Full。

- 用户对接：每次产生修改后阐述本轮改动了哪些文件，以及提供用于 commit 的文本内容
- 前后端协作：后端 agent 仅修改后端项目代码，不过多考虑 visualization；前端 agent 工作仅限于在 visualization 目录下修改，不改动后端项目代码；后端项目代码接口应全部通过 endpoint 向前端提供能力支持，在修改后端实现时，若发生 endpoint 改动，需即时在 docs\endpoint 中建立和调整文档，供前端对接；前端在进行前端设计和实现时，若发生缺失能力，不要阻塞设计和实现工作，允许暂时假定可行接口，并通过 visualization\docs\demand 向后端 agent 提出进一步能力需求。


## 推进与交付

执行计划记录范围、确认点、实际进展及证据；有含糊语义或与已确认目标的冲突时立即讨论。只在实现、设计文档和必要验证逐项核对后完成并归档，不能以轮次或测试数量推定功能完成。

每个阶段同步受影响的设计与 Endpoint 协议；历史迁移记录保留在归档计划，不再添加覆盖正文的过渡条款。长期目标是构建可用、可维护的泛用智能体，并通过 Home 与 Memory 支持持续稳定运行的个性化助手。

## 工作经验

- 从 TOML、JSON、环境变量或外部 API 进入项目的数据属于动态边界。应在入口处尽早校验并转换为项目内部的明确类型，避免让 `dict[str, Any]`、未知泛型或宽泛 `object` 在内部逻辑中扩散。
- 面对 `ty` 关于泛型不变性或类型收窄的报错时，应优先检查真实类型边界是否清楚。必要的 `cast` 应局限在已经经过运行时判断或校验的位置，并配合明确的转换函数使用。
- 不要把 `Mapping[object, object]` 当作“可接受任意映射”的通用入口。若内部需要字符串键配置，应直接表达为字符串键映射，并在动态数据入口做字符串键校验。
- 全新代码同样会滋生兼容 alias、空壳类型、未消费字段与参数这类死抽象；review 时应把死抽象作为专项检查项，而不是只检查错误处理与类型。
- 编码中容易按习惯抛出裸 `ValueError` 等内置异常而绕过三层失败语义。新增或修改 raise/except 时，应显式对照三层语义归类；review 时把裸内置异常和过宽的 `except Exception` 作为检查项。
