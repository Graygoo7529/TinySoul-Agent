# TinySoul 协作规约

本文档约定 TinySoul 项目的分析、设计、实现和文档维护规则。目标是保持设计清晰、代码干净、讨论充分，并让文档与实际实现长期一致。

## 核心定义（AGENT 请不要修改这一个标题下的内容）

用户轮/User Turn：从用户发起一轮输入开始，到响应该输入的一次完整 Agent 执行结束；其中包含多次模型调用和工具调用，也包含期间用户追加的提示、Agent 自发提示的插入，以及最终回答。

执行轮/Agent Cycle：Agent 内部的一个执行轮。TinySoul 的一个执行轮由 3 个执行单元（Phase）组成：（1）更新语境与决策行动域；（2）生成行动参数；（3）采取行动。每个 Phase 都是一个独立执行单元，并对应一次具体的 Task/LLM Call；每个 Phase 都可以有对应的 task prompt。

模型轮/LLM Call/LLM Task：一次模型调用。TinySoul 通过 /llm 模块提供模型调用抽象；LLM Task 的主要输入是构造完成的 message stack，由整体语境（context）和临时性的本次任务提示（task prompt）共同构成。

行动执行/Action：一次智能体行动执行。TinySoul 通过 /action 模块提供行动执行抽象；Phase1 不直接暴露全部 action，而是暴露可选择的 action domain；Phase2 只在已选 domain 内暴露具体 Action Tools，并基于每个 action 的工具调用结构（name、description、schema）和补充语义（use_when、avoid_when、effects、examples）生成 ActionCall；Phase3 再将 ActionCall 装配为自包含的 ActionBatch 进行实际执行。每个 action 还具有框架内定义，例如超时、并发策略、hook 列表和后端执行方式。行动主要由 NATIVE 内部函数调用、受控子进程、临时脚本和需要嵌套 LLM Task 的动作构成；NATIVE 只能通过 ActionExecutionControl 协作式响应超时，受控子进程和临时脚本承担需要硬停止的执行语义；不再支持持续性/长期 ONGOING action，所有动作都在所属批次内收敛为成功、失败或超时。

模型侧工具/Tool Message：TinySoul 可以在 LLM Task 中向模型提供模型侧工具定义，用于约束模型生成结构化调用意图。模型侧工具分为两类：（1）Control Tools，框架内部控制工具，用于在 Phase1 中生成对于 WorkingContext、BackgroundContext 和用于 Phase2 行动选择等操作意图；（2）Action Tools，智能体行动工具，用于在 Phase2 中为已选择的 Action 生成调用参数。模型侧工具只表达模型输出协议，不等同于实际工具执行。Control Tools 的结果由 Phase1 汇聚、校验并转化为内部操作信号后，由对应上层模块消费；Action Tools 的结果由 Phase2 归一化为 Action 参数，再交由 Phase3 执行。

持久化/内存/模型反馈：表述和编码时要注意三个层次。模型反馈是最终查询给模型的提示词（构造后的 message stack）；内存是各个上层模块维护的数据结构与信息；持久化是本地目录下组织的文档、资源和知识库。三者应当保持一致性：上层模块维护运行时各段消息的状态，依据运行状态在调用 llm task 时“构造” message stack，并将状态变更同步回写到持久化的本地文件系统中。

语块与渐进式加载：我们认为，语言的表述以语块的形式促进理解。从发音到单词、到短语、到某种固定表达，交流双方仅通过特定前缀即可“匹配”特定语块的含义，并理解对方大致表达的内容。渐进式加载是一种策略：Agent 在 Context 中“看到”访问内容的“链接/Link”，在需要进一步释义时调用工具加载细节。语块的形成是从细节到抽象，而渐进式加载是从抽象到细节。

语境/Context：我们认为，语言交流是一种“语言游戏”。语言游戏的参与双方基于各自语境，通过语言交流推测对方意图，以相互理解并达成共同目标。语境包含当前游戏状态和规则，帮助 Agent 做出决策和行动。完整语境包含以下部分：（1）BackgroundContext，用户轮开始前的背景，包含智能体世界观和方法论的整体性认知，以及当日会话历程（当日会话中以前用户轮的归纳）；（2）TurnTraceContext，本轮为完成工作而产生的行为轨迹，包含当前轮次 Agent 的行动决策和行动反馈；（3）WorkingContext，本轮任务执行状态，给予 Agent 一种“工作台”，描述当日工作区内的文档资源（工作区/Workspace），以及本轮任务执行状态：里程碑（MileStone，类似储存重要状态与结论的寄存器）和待办事项（Todo）。

LLM Task/Call “构造式” MessageStack：LLM Task/Call 的主要输入为 MessageStack。MessageStack 可以分为多个区段，分别由上层不同模块提供语境（Context）或附加任务提示（task prompt），并在实际 LLM Task 前“构造”为完整的 MessageStack。除了上述语境，task prompt 会包含 task_guide、task_input、task_output_desc，以引导模型生成。例如，Phase1、Phase2 会说明当前处于执行轮/Agent Cycle 的哪一个阶段和期望输出；Phase2、Phase3 会附加 Action domain 级别 Skills，见关于 How 定义。“构造式”表示为每次 LLM Task 制定不同的 MessageStack，并在上层维护通用语境，在 Task 完成后对语境进行反馈和修改。

工作区/WorkSpace：每日会话为 Agent 维护一个专用的、可操作的本地路径，Agent 可以在其中操作文件和执行脚本。WorkSpace 内资源在语境中有专属的链接/Link 标识（例如 workspace:doc/doc.md），并使用相对路径读取资源。WorkSpace 有一个专用描述文件，用于记录工作区结构和其中各文件摘要，并可在用户轮开始时映射到 WorkingContext 语境中，同时采用约定的目录结构和命名风格。工作区中文件读取具有特定约定：文件内容（如文档、脚本、图片）通常不应出现在语境/Context 中，也就是说，行动/工具执行结果不应返回实际内容并记录到 TurnTraceContext；Context（工具的输入和输出）仅记录相关资源的链接/Link。例如需要修改的文档，或可以作为参考的相关文档、图片等，在 Phase3 具体执行中才读取具体文件，并作为临时性 Task Prompt。

Agent Home 与链接/Link：Agent Home 存储持久化语境，包含 Agent 记忆、知识、技能。Agent Home 主要以 Markdown 文档组织，分为顶层内容和渐进式内容。顶层内容默认或逐步（通过 Phase1）加载到 BackgroundContext，顶层内容通过特殊链接（例如使用 @ 而非 /）标识；渐进式内容不放在 BackgroundContext 中，主要通过行为/工具以工具结果返回到 TurnTraceContext 中。以下分别描述相关语境在 Agent Home 中的形式、运行位置与链接：

（1）AGENT.md 是顶层内容，类似一本参考全书目录，记录 AGENT 所具有的整体规范、行为设定、核心规则、用户偏好等。AGENT 可以通过链接指向多个顶层内容，例如 home:agent@user/user.md；在 user.md 中可以进一步链接渐进式内容；

（2）WHAT 是一个 Knowledge 库，在语境中通过 home:what@what_name 标识，用于标注（a）实体（b）领域概念。WHAT 使用 what_name.md 记录对于实体和概念的定义以及关联内容（通过链接）。what_name.md 是顶层内容，并可通过语义匹配 top-k why 交付语境模块；也可通过工具反向查询 Agent Home 中具有 what_name 标识的其他顶层内容。what_name.md 不应有时间戳，只记录当前认为正确且重要的内容。AGENT 规约应说明 WHAT 的使用方式，并要求 llm 在输出时也使用这种标识；

（3）WHY 是另一个 Knowledge 库，在语境中通过 home:why@question_content 标识，用于标注问题的原因和解答。WHY 使用 question_content.md 记录问题的具体内容以及关联内容（通过链接）。question_content.md 是顶层内容，并可通过语义匹配 top-k why 交付语境模块；

（4）HOW 是另一个 Knowledge 库，它是当前智能体设计中 Skill 的变种，在语境中通过 home:how@skill_name 标识。skill 下的 skill_name.md 是顶层内容，并可通过链接渐进式加载相关内容，如 home:how/skill_name/ref.md、home:how/skill_name/script.py。所有 skill_name 和 skill_desc 应形成一份清单（或通过 metadata 动态扫描），这份描述清单也是顶层内容，且 AGENT 规约应说明 HOW 的使用方式。除了 Skill 这种顶层 HOW，还有一种与行动域绑定的 HOW（how to use domain action），可以自动在 Phase2、Phase3 对已选行动域提出引导，并添加到 task prompt 中；自动绑定加载的 HOW 文档约束为 domain 层级，因为 Phase1 选择的是 domain 而非某个 action；

（5）MEMORY 是长期记忆库，每天形成一个 yyyy-mm-dd.md 的日志，且日志可以通过 home:memory@yyyy-mm-dd 标识为顶层内容。它记录当天记忆内容，并在日志中使用链接指向关联内容；也可通过工具反向查询 Agent Home 中具有 home:memory@yyyy-mm-dd 标识的其他顶层内容；可通过语义匹配 top-k memory 交付语境模块，且 AGENT 规约应说明 MEMORY 的使用方式；

基于以上设计，只需要存在三种链接/Link：（1）链接指向顶层内容，主要通过自动加载或 Phase1 直接加载到 BackgroundContext；（2）链接指向 Agent Home 中的非顶层内容，Agent 可在 Phase1 选择加载行动，在 Phase2 中指定加载链接，并通过行动结果加载到 TurnTraceContext；（3）workspace 链接，指向工作区资源，Agent 可在 Phase2 生成相关行动参数时使用它们，标识这些行动的操作目标或参考资料，但工作区资源本身不会被加载到 Context 中。归纳如下：
（1）home:xxx@ 表示“加载为背景语境的顶层知识”
（2）home:xxx/ 表示“可被行动读取或使用的资源”
（3）workspace: 永远是工作区资源句柄


一个用户轮由多个执行轮/Agent Cycle 构成，执行轮依次进行执行单元/Phase。
（Phase1）更新语境与决策行动域：基于完整语境/Context，调用 LLM Task。Phase1 可以向模型提供框架内部 Control Tools，例如状态更新工具、背景更新工具和 Phase2 行动域选择工具；模型返回的 Control Tool Calls 不直接修改状态，而是在 Phase1 结束后被汇聚、校验、归一化并转化为内部操作信号，由 WorkingContext、BackgroundContext、Loop 等上层模块分别消费；从而执行（a）加载或逐出 BackgroundContext 中的顶层内容；（b）更新 WorkingContext 中的里程碑或待办；（c）选择一个或多个 action domain 进入 Phase2；Phase1 不生成完整行动参数，也不暴露全部二级 action 定义；
（Phase2）生成行动参数：为 Phase1 选择的 domain 生成具体 ActionCall，调用 LLM Task。Phase2 只向模型提供已选 domain 内的 Action Tools，以及对应 action 的工具调用结构、补充语义和 HOW 文档；模型返回的 Action Tool Calls 被归一化为 ActionCall；
（Phase3）采取行动：一个 map-reduce 风格的执行器，将 Phase2 的 ActionCall 装配为 ActionBatch 并实际执行。每个 action 除了反馈给模型的工具调用结构和补充语义外，还有框架内配置，例如超时时长、并发策略和通用/专用 hook 等。action 执行器会（a）将 ActionCall 补充为包含已解析 ActionSpec、运行时 action id、批次 id、执行参数、框架配置的自包含执行输入；（b）对每个 action 执行通用/专用 hook 检查；（c）等待全部行动执行完成或超时，并优先通过协作取消或进程终止收束执行体；（d）为每个 action 返回结构化 ActionResult（包括检查失败、执行失败和超时等结果）；（e）渲染和处理 ActionResult，例如需要反馈给模型的结果、日志记录的结果等。Batch 只是执行编排容器，不额外定义 batch result。

每日任务与 WorkSpace、Agent Home 内容加载和变更：WorkSpace、Agent Home 都具有“每日”属性，WorkSpace 每日归档，Agent Home 知识和记忆每日沉淀。在实现中，可以通过独立接口触发执行，调用独立 LLM Task 完成 Agent Home 知识和记忆的每日沉淀（待开发完成并部署时定时触发）。另一方面，Agent Home 在当日可能被修改和变更，但最终应该在每日沉淀中进行 diff，并决策最终合并。因此，对于模型来说，它只知道通过链接/Link 加载或编辑 Agent Home 中的文档或代码；但事实上，TinySoul 框架层需要进行额外处理：原始 Agent Home 在每日更新任务以外只读，Agent 在运行时自动或通过链接加载 Agent Home 内容时（语义检索等只读操作仍看原始内容），同步将原始 Agent Home 所需内容拷贝到运行时副本（保持目录结构）。之后，Agent 对语境内容的变更都在副本中进行。进一步地，对于 HOW 类型技能包（与实际任务相关，变更可能频繁），还会为其维护一份内部的 SKILL_MEMORY.md，用于记录当日处理任务时使用该技能包的情况、反馈、变更记录等。最后，每日归档任务基于 Agent Home 当日副本情况，再分析和考虑是否提交与合并修改。由于 WorkSpace、Agent Home 事实上都是基于链接/Link/相对路径的读写机制，因此在实现层面应当在 infra 中维护公共读写机制。上述机制可以用目录结构描述：

- home：原始内容
- runtime：每日运行时
  - archive：时间戳保存的旧的归档
  - workspace：当前工作区
  - home：Agent Home 动态“懒加载”副本
    - agent（AGENT.md, /user, /identity）
    - what（/entity，/concept）
    - why（/QA_*.md）
    - how（/skill_name/(SKILL.md+reference/+SKILL_MEMORY.md))
    - how_action（/domain_name/(DOMAIN.md+DOMAIN_MEMORY.md))
    - this_day_memory.md（以前 memory 只读，在 home 中不需要拉过来，查询即可）

Trap/异常和信号：TinySoul 使用统一的异常定义和内部信号处理，采用 OS-中断设计思路和实现风格。对于异常，可以分为（1）模块层面暂时抛出并局部处理，例如 Action 执行中的失败，被执行器捕获后结构化为 Action Result，以及 llm 模块的模型重试和切换；（2）上层逻辑层面的全局处理，并在触发后陷入处理流程，例如语境过长需要压缩、home 副本拷贝等框架层面的机制（类似页表换出），以及响应用户外部指令，例如中断当前用户轮、中断程序，或追加用户输入（陷入处理后转化为内部信号给内部模块消费）。TinySoul 整体异常处理分成如下层次：（a）局部修复策略（llm 模块的模型重试和切换）和错误映射（Action 异常转换为模型反馈），局部处理失败后再向上层报错；（b）由全局处理决定继续当前用户轮（返回异常陷入位置）/中断当前用户轮/退出程序；

异常与内部信号处理的区别在于，异常决定恢复位置和期间执行的大型任务。内部信号主要用来清晰描述内部模块的行为，例如 action result 结束后发出信号去追加 TurnTraceContext；Phase1 完成后通过信号去变更 BackgroundContext。信号可以使意图和实际消费执行过程分离，使代码更清晰。

tinysoul 运行层级：依次可分为（1）模块级，模块内部完成特定任务；后面两个层级对于用户可见；（2）用户轮级，协调各个模块完成一次用户对话，在用户轮启动时，用户可以追加对话进入用户轮；（3）顶层，循环等待用户新一轮对话输入或者指令，指令可以是 exit，也可以是执行与用户轮同层工作（例如每日沉淀），执行过程可以通过异常陷入处理执行；同层工作执行中不再接受用户输入。

tinysoul 可观测性：实现三个层级的终端显示（正常运行/VERBOSE/MODEL：专门附加反馈给模型的上下文，便于调试）。代码层面应该统一插入简约的观测代码，然后在 infra 层将接收到的 trace 进行渲染。


## 项目规约

本节是已实现模块的运行方式规约，随模块实现动态补充，供后续模块设计时理解既有模块的协作方式；详细设计见 docs/design/ 对应文档。

- TinySoul 拥有独立的上层动作层。动作选择、上下文选择、参数生成、动作执行结果管理不依赖模型供应商的原生 tool calling 接口；供应商原生 tool calling 只作为 LLM 适配层可选映射方式。
- Infra 提供配置环境与 JSON 边界。配置显式加载、显式传递，模块不在导入时读取配置或创建全局单例；来自模型输出、配置文件或外部接口的动态 JSON 数据，在进入模块内部边界时转换为明确的 JSON 值结构。
- Runtime 提供运行位置（RunScope）、Runtime 语义异常、Trap 处理器表、运行转移和 SignalBus。控制流变化（结束 Turn/Cycle/Program、全局恢复）统一构造 Runtime 语义异常进入 Trap，Trap 返回指向运行位置栈 frame 的运行转移，由各级运行器消费；模块事件与状态变更请求通过信号表达，由信号处理器在明确边界批量消费。
- LLM 模块负责模型调用输入输出的统一表达、供应商适配、能力校验、模型选择、重试切换、输出解释，以及 TinySoul 模型侧工具语义与供应商工具协议之间的映射。LLM 模块不负责执行工具、不修改 Context，也不消费 Control Tool 或 Action Tool 的业务语义。
- Assistant 消息表达模型历史输出，可以包含可见内容和可选推理内容。推理内容用于上层在构造后续上下文时保留模型推理轨迹；是否保留、如何压缩由上层语境或动作层决定，具体传入供应商的回放形态由 LLM 适配层依据 provider options 和供应商能力决定。
- LLM 消息内容需要支持灵活的多片段结构，以表达文本、图像和由上层构造的结构化上下文。结构化上下文属于消息内容的一部分，而不是供应商 tool calling 协议的一部分。
- TinySoul 可以定义自己的 tool message 语义，用于表达模型侧工具定义、工具调用意图和工具结果回放。Provider 原生 `tool` message、`tool_calls`、`tool_call_id` 或 Responses `function_call` 不直接进入 TinySoul 核心语义，应由供应商适配层映射为 TinySoul 内部工具调用结构。
- Phase1 使用 Control Tools 表达框架内部控制操作。Control Tool Calls 在 Phase1 汇聚后转化为操作信号，并由对应上层模块按自身信号消费协议批量处理。
- Phase2 使用 Action Tools 表达行动参数生成。Phase2 只接收 Phase1 选择的 action domain，并基于已选 domain 内 action 的工具调用结构、补充语义、HOW 和工具 schema 生成 ActionCall。
- 工具、技能或外部动作执行结果应由上层整理为普通上下文输入，或在需要进行模型侧工具结果回放时转换为 TinySoul tool result message。消息内容可以标注其来源、动作名称、参数、结果和状态，但 provider 原生 tool message 只存在于供应商适配层。
- TinySoul 内部应使用自己的 tool call id；供应商 tool call id 只作为适配层相关性信息保留，不应成为 Context、Action 或 Loop 模块依赖的主键。
- Action 模块向上层提供唯一装配与调用入口（组装门面），内部承担 Phase1 域作用域、Phase2 动作作用域与归一化、Phase3 批次执行。每个模型侧 action tool call 在 Action 模块内恰好收敛为一个局部 ActionResult；无法归因到单个 call 的阶段性问题收敛为 phase-level result。
- Action 后端分工：native 运行在宿主线程，只能协作式响应取消；需要硬停止语义的动作使用 subprocess 或 script 后端。后端 options 属动态边界，在 catalog 加载期由按 handler 注册的校验器校验。
- Context 模块向上层提供唯一装配与调用入口（组装门面），持有三段语境（Background/Working/TurnTrace）与本轮用户输入列表，负责构造式 MessageStack、语境控制工具与语境压缩服务。ContextEngine 不向上层暴露可变状态持有者；语境变更只有两类入口：信号的批量可行提交与 Turn 生命周期；Control Tool Calls 先归一化为信号，不直接修改状态。
- Context 信号协议：context.working.patch、context.background.patch、context.trace.append、context.input.append，均为 JSON 安全载荷并按命名空间消费。信号消费先解析同批信号，再对 Working/Background 变更做投影验证并提交可行变更；trace append 使用 text/json 多片段内容投影并可保留 provider-neutral assistant reasoning，但不解释供应商回放语义。语境预算超限由 context bridge 映射为语境压缩 Runtime 原因，Trap 压缩处理器调用压缩服务（裁剪 TurnTrace 旧条目 + 合并摘要占位）后重试当前 Phase。
- Loop 模块是 TinySoul 的运行编排层，按 Program/Turn/Cycle/Phase 消费 Runtime 运行位置与运行转移；Phase 单元只组合 ContextEngine、ActionEngine 与 LLMTaskRunner，不复制三者内部语义。Turn 结束以 `core.answer` action 执行成功为唯一正常完成条件，cycle 上限只作为兜底保护。ProgramRunner 等待 app 层已分类的 ProgramInputEvent；Turn 内控制流变化仍由运行器构造 Runtime 语义异常进入 Trap。
- App 模块是 TinySoul 的进程装配、生命周期和外部输入边界层。TinySoulAppBuilder 显式加载配置环境，构建 LLM、Workspace、Agent Home、Action、Context、SignalBus、RuntimeTrap 与各级 loop runner，注册内置 native action、llm_step 执行器和 Trap 处理器。外部输入源只生产 InputEvent，由 InputCommandParser 纯解析为输入意图，再由 InputDispatcher 投递 ProgramInputEvent 或发出 `loop.control.request` / `context.input.append` 信号。AppBuilder 只装配 Workspace 与 Agent Home 的门面，不直接扫描 workspace，不直接读取 `AGENT.md`、HOW、WHAT、WHY 或 MEMORY 文件。
- Workspace 模块负责 `workspace:` 链接、当日工作区根目录、资源扫描、manifest 读写、单资源摘要刷新和 WorkingContext 资源摘要投影。`workspace.scan` 与 `workspace.describe` 由 Workspace 模块提供 handler/executor，通过 `context.working.patch` 信号同步 `WorkspaceResource(link, summary)`；Context 和 Action 结果不保存 workspace 文件正文。当前已实现扫描、单资源摘要刷新、Engine 内部有界文本读取与 manifest 切面；workspace 正文进入临时 task prompt 的通道、write/patch/delete 和日终归档仍需继续在 Workspace 模块内扩展。
- Agent Home 模块负责 `home:` 链接、顶层背景条目、渐进式资源、domain HOW guidance 和运行时副本准备。`home:agent@core` 由 Agent Home 提供给 BackgroundContext；`home:how_action@<domain>` 由 `HomeDomainGuidanceProvider` 注入 Phase2；`home.resource.read` 读取有界渐进式资源并返回局部 ActionResult；`HOME_RUNTIME_COPY_REQUIRED` 由 Agent Home Trap handler 准备 runtime home 副本并重试当前 frame。当前已实现背景/guidance/resource read 的 runtime 副本读取语义：链接内容进入运行期时读取 runtime home，副本缺失由 Trap 建立后重试；启动背景装配阶段由 AppBuilder 调用同一 runtime copy Trap handler 准备默认和可加载背景副本后重试读取。home 写入、检索、memory append、HOW 使用反馈和每日沉淀仍未实现。

## 工作方式

- 设计和实现前，应先理解现有设计思路、项目目标、模块边界和历史取舍。
- 在进行重要设计、架构调整、模块拆分或代码实现前，应先与项目维护者充分讨论，并呈现改动预览。
- 不应在未讨论清楚目标和边界时直接大规模实现。
- 如果发现当前设想与既有目标冲突，应先提出冲突点、可选方案和影响，再继续修改。
- 在继续设计或实现时，如果发现实际代码、外部接口或新需求与之前讨论规划产生冲突，应立即澄清问题并重新讨论清楚。不要用敷衍的临时性补丁绕过冲突。

## 设计原则

- 项目设计应从当前目标出发，参考既有思路，但不被旧实现牵制。
- 旧设计、旧测试和旧调用方式只作为理解历史意图的材料，不应成为保留模糊边界或兼容不清晰接口的理由。若旧测试与当前清晰架构冲突，应修改或删除旧测试，而不是用兼容层维持旧假设。
- 设计时应先检查现有设计、类别和边界，优先考虑复用或修改已有结构。只有在现有结构无法清晰表达新职责时，才引入新的类型、方法或模块，避免产生边界重复的抽象。
- 无需为了兼容历史结构而牺牲清晰度。必要时可以修改测试、删除旧假设、修改函数签名、重构架构，以保持项目清晰干净，干净地清除历史遗留问题。
- 设计应保持整体一致性：模块职责、对象关系、控制流、错误处理和状态模型必须能相互解释，不应各自独立演化。
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
- 模块 failure payload 应保持稳定、精简和 JSON 安全。跨 Runtime 边界时 payload 至少应能表达模块名和模块失败类型，并可按需携带 `error_type`、配置 key、profile、资源句柄等摘要字段；不要放原始异常对象、traceback、大块文件内容、完整消息栈或业务模块内部对象。
- Runtime 语义异常应通过稳定原因标识进入 Trap，由 Trap 处理器返回运行转移；Runtime 原因应收敛为启动失败、结束 Turn、结束 Cycle、结束 Program 和少量全局恢复原因，不要为恢复、中断、退出和无法处理的错误过早扩展庞大的异常继承树。
- Runtime 运行转移应以运行位置栈中的 frame 为目标，并收敛为重试 frame 或结束 frame；重试目标必须具备可重放语义，结束 Program frame 表示退出程序。
- 控制流变化应统一通过 Runtime 语义异常进入 Trap；信号只表达模块事件、状态变更请求和可观测事件，Trap 处理过程中需要业务状态变更时也应发出信号交由对应模块消费。
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

- 修改代码后、声明任务完成前，必须运行并通过：

```powershell
python -m pytest tests -q
python -m ty check
```

- 测试约定：
  - 测试按 `tests/<module>/test_<切面>.py` 组织，镜像模块结构；
  - 触网或调用真实供应商的测试默认 skip，需显式开启。

## 当前任务
彻底地重构 reference\tinysoul_v1。注意，这次重构不是简单的改造原有代码，而是把原有代码和设计思路作为思路，重新干净地去设计和实现每个模块。原有项目代码已经迁移到目录 reference\tinysoul_v1 中。重构应按模块边界逐步推进，不必一对一克隆旧的逻辑，并优先考虑更清晰的设计思路。

当前进度：infra、runtime、llm、action、context、loop、app（含 TinySoulApp 装配入口与输入边界）已完成；Workspace 与 Agent Home 已完成基础接入，覆盖 workspace 链接扫描、manifest、单资源摘要刷新、WorkingContext 摘要同步、Engine 内部有界文本读取、home 顶层背景、how_action 注入、渐进式资源只读 action 和 runtime home 缺页式副本准备。下一步建议继续推进 Workspace 正文进入临时 task prompt 的通道、write/patch/delete、Agent Home 检索与写入、HOW 使用反馈、memory append 和每日沉淀。每完成一个模块或重要切面，应同步补充「项目规约」中该模块的运行方式规约，并更新本节进度。

重构实现纪律：

- 实现必须遵守项目失败处理三层语义与 Runtime 异常体系。新增任何 raise 前，先归类该失败属于局部结果、模块边界异常还是 Runtime 语义异常（见「代码风格」）；不得按个人编码习惯随手抛出 ValueError、RuntimeError 等通用异常表达模块失败。
- 新模块的失败语义、组装入口、动态边界处理应对照已完成模块的既有模式（failures.py、bridge、Engine/Builder、加载期校验器），不自行发明平行机制。

## 工作经验

- 从 TOML、JSON、环境变量或外部 API 进入项目的数据属于动态边界。应在入口处尽早校验并转换为项目内部的明确类型，避免让 `dict[str, Any]`、未知泛型或宽泛 `object` 在内部逻辑中扩散。
- 面对 `ty` 关于泛型不变性或类型收窄的报错时，应优先检查真实类型边界是否清楚。必要的 `cast` 应局限在已经经过运行时判断或校验的位置，并配合明确的转换函数使用。
- 不要把 `Mapping[object, object]` 当作“可接受任意映射”的通用入口。若内部需要字符串键配置，应直接表达为字符串键映射，并在动态数据入口做字符串键校验。
- 全新代码同样会滋生兼容 alias、空壳类型、未消费字段与参数这类死抽象；review 时应把死抽象作为专项检查项，而不是只检查错误处理与类型。
- 编码中容易按习惯抛出裸 `ValueError` 等内置异常而绕过三层失败语义。新增或修改 raise/except 时，应显式对照三层语义归类；review 时把裸内置异常和过宽的 `except Exception` 作为检查项。
