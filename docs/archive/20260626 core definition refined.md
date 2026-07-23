## 核心定义

用户轮/User Turn：从用户发起一轮输入开始，到响应该输入的一次完整 Agent 执行结束；其中包含多次模型调用和工具调用，也包含期间用户追加的提示、Agent 自发提示的插入，以及最终回答。

执行轮/Agent Cycle：Agent 内部的一个执行轮。TinySoul 的一个执行轮由 3 个执行单元（Phase）组成：（1）更新语境与决策行动；（2）生成行动参数；（3）采取行动。每个 Phase 都是一个独立执行单元，并对应一次具体的 Task/LLM Call；每个 Phase 都可以有对应的 task prompt。

模型轮/LLM Call/LLM Task：一次模型调用。TinySoul 通过 /llm 模块提供模型调用抽象；LLM Task 的主要输入是构造完成的 message stack，由整体语境（context）和临时性的本次任务提示（task prompt）共同构成。

行动执行/工具调用/Action/Tool Call：一次工具调用。TinySoul 通过 /action 模块提供行动执行抽象；全局 action 会在启动时检测执行环境并注册；Phase1 会将当前可用 actions（meta）作为 task prompt input 反馈给模型；Phase2 会将选择执行的 actions（detail）反馈给模型并生成参数；Phase3 再进行实际工具执行，其中也可能发生 LLM Task。行动主要由两类构成，一类是 NATIVE 内部函数调用，一类是 Terminal（python/cli/bash 指令）。对于 python，还可区分临时脚本和长期脚本：在语境中可以使用工作区链接的相对路径引用临时脚本，使用 HOW 链接引用长期脚本。

持久化/内存/模型反馈：表述和编码时要注意三个层次。模型反馈是最终查询给模型的提示词（构造后的 message stack）；内存是各个上层模块维护的数据结构与信息；持久化是本地目录下组织的文档、资源和知识库。三者应当保持一致性：上层模块维护运行时各段消息的状态，依据运行状态在调用 llm task 时“构造” message stack，并将状态变更同步回写到持久化的本地文件系统中。

语块与渐进式加载：我们认为，语言的表述以语块的形式促进理解。从发音到单词、到短语、到某种固定表达，交流双方仅通过特定前缀即可“匹配”特定语块的含义，并理解对方大致表达的内容。渐进式加载是一种策略：Agent 在 Context 中“看到”访问内容的“链接/Link”，在需要进一步释义时调用工具加载细节。语块的形成是从细节到抽象，而渐进式加载是从抽象到细节。

语境/Context：我们认为，语言交流是一种“语言游戏”。语言游戏的参与双方基于各自语境，通过语言交流推测对方意图，以相互理解并达成共同目标。语境包含当前游戏状态和规则，帮助 Agent 做出决策和行动。完整语境包含以下部分：（1）BackgroundContext，用户轮开始前的背景，包含智能体世界观和方法论的整体性认知，以及当日会话历程（当日会话中以前用户轮的归纳）；（2）TurnTraceContext，本轮为完成工作而产生的行为轨迹，包含当前轮次 Agent 的行动决策和行动反馈；（3）WorkingContext，本轮任务执行状态，给予 Agent 一种“工作台”，描述当日工作区内的文档资源（工作区/Workspace），以及本轮任务执行状态：里程碑（MileStone，类似储存重要状态与结论的寄存器）和待办事项（Todo）。

LLM Task/Call “构造式” MessageStack：LLM Task/Call 的主要输入为 MessageStack。MessageStack 可以分为多个区段，分别由上层不同模块提供语境（Context）或附加任务提示（task prompt），并在实际 LLM Task 前“构造”为完整的 MessageStack。除了上述语境，task prompt 会包含 task_guide、task_input、task_output_desc，以引导模型生成。例如，Phase1、Phase2 会说明当前处于执行轮/Agent Cycle 的哪一个阶段和期望输出；Phase2、Phase3 会附加 Action 级别 Skills，见关于 How 定义。“构造式”表示为每次 LLM Task 制定不同的 MessageStack，并在上层维护通用语境，在 Task 完成后对语境进行反馈和修改。

工作区/WorkSpace：每日会话为 Agent 维护一个专用的、可操作的本地路径，Agent 可以在其中操作文件和执行脚本。WorkSpace 内资源在语境中有专属的链接/Link 标识（例如 workspace:doc/doc.md），并使用相对路径读取资源。WorkSpace 有一个专用描述文件，用于记录工作区结构和其中各文件摘要，并可在用户轮开始时映射到 WorkingContext 语境中，同时采用约定的目录结构和命名风格。工作区中文件读取具有特定约定：文件内容（如文档、脚本、图片）通常不应出现在语境/Context 中，也就是说，行动/工具执行结果不应返回实际内容并记录到 TurnTraceContext；Context（工具的输入和输出）仅记录相关资源的链接/Link。例如需要修改的文档，或可以作为参考的相关文档、图片等，在 Phase3 具体执行中才读取具体文件，并作为临时性 Task Prompt。

Agent Home 与链接/Link：Agent Home 存储持久化语境，包含 Agent 记忆、知识、技能。Agent Home 主要以 Markdown 文档组织，分为顶层内容和渐进式内容。顶层内容默认或逐步（通过 Phase1）加载到 BackgroundContext，顶层内容通过特殊链接（例如使用 @ 而非 /）标识；渐进式内容不放在 BackgroundContext 中，主要通过行为/工具以工具结果返回到 TurnTraceContext 中。以下分别描述相关语境在 Agent Home 中的形式、运行位置与链接：

（1）AGENT.md 是顶层内容，类似一本参考全书目录，记录 AGENT 所具有的整体规范、行为设定、核心规则、用户偏好等。AGENT 可以通过链接指向多个顶层内容，例如 home:agent@user/user.md；在 user.md 中可以进一步链接渐进式内容；

（2）WHAT 是一个 Knowledge 库，在语境中通过 home:what@what_name 标识，用于标注（a）实体（b）领域概念。WHAT 使用 what_name.md 记录对于实体和概念的定义以及关联内容（通过链接）。what_name.md 是顶层内容，并可通过语义匹配 top-k why 交付语境模块；也可通过工具反向查询 Agent Home 中具有 what_name 标识的其他顶层内容。what_name.md 不应有时间戳，只记录当前认为正确且重要的内容。AGENT 规约应说明 WHAT 的使用方式，并要求 llm 在输出时也使用这种标识；

（3）WHY 是另一个 Knowledge 库，在语境中通过 home:why@question_content 标识，用于标注问题的原因和解答。WHY 使用 question_content.md 记录问题的具体内容以及关联内容（通过链接）。question_content.md 是顶层内容，并可通过语义匹配 top-k why 交付语境模块；

（4）HOW 是另一个 Knowledge 库，它是当前智能体设计中 Skill 的变种，在语境中通过 home:how@skill_name 标识。skill 下的 skill_name.md 是顶层内容，并可通过链接渐进式加载相关内容，如 home:how/skill_name/ref.md、home:how/skill_name/script.py。所有 skill_name 和 skill_desc 应形成一份清单（或通过 metadata 动态扫描），这份描述清单也是顶层内容，且 AGENT 规约应说明 HOW 的使用方式。除了 Skill 这种顶层 HOW，还有一种与具体工具/行动绑定的 HOW（how to use action_name），可以自动在 Phase2、Phase3 对具体行动提出引导，并添加到 task prompt 中；

（5）MEMORY 是长期记忆库，每天形成一个 yyyy-mm-dd.md 的日志，且日志可以通过 home:memory@yyyy-mm-dd 标识为顶层内容。它记录当天记忆内容，并在日志中使用链接指向关联内容；也可通过工具反向查询 Agent Home 中具有 home:memory@yyyy-mm-dd 标识的其他顶层内容；可通过语义匹配 top-k memory 交付语境模块，且 AGENT 规约应说明 MEMORY 的使用方式；

基于以上设计，只需要存在三种链接/Link：（1）链接指向顶层内容，主要通过自动加载或 Phase1 直接加载到 BackgroundContext；（2）链接指向 Agent Home 中的非顶层内容，Agent 可在 Phase1 选择加载行动，在 Phase2 中指定加载链接，并通过行动结果加载到 TurnTraceContext；（3）workspace 链接，指向工作区资源，Agent 可在 Phase2 生成相关行动参数时使用它们，标识这些行动的操作目标或参考资料，但工作区资源本身不会被加载到 Context 中。归纳如下：
（1）home:xxx@ 表示“加载为背景语境的顶层知识”
（2）home:xxx/ 表示“可被行动读取或使用的资源”
（3）workspace: 永远是工作区资源句柄


一个用户轮由多个执行轮/Agent Cycle 构成，执行轮依次进行执行单元/Phase。
（Phase1）更新语境与决策行动：基于完整语境/Context，调用 LLM Task（action meta 作为 task prompt），执行（a）加载或逐出 BackgroundContext 中的顶层内容；（b）更新 WorkingContext 中的里程碑或待办；（c）选择多个可以并行执行的行动；
（Phase2）生成行动参数：为上一步决策的多个行动生成行动参数，调用 LLM Task（自动使用对应的 action detail 和 how 文档作为 task prompt）；
（Phase3）采取行动：一个 map-reduce 风格的并行执行器，将 Phase2 的行动决策转为实际执行。事实上，每个行动除了反馈给模型的 meta-detail 外，还有框架内配置，例如超时时长、是否允许并行，以及专用参数检查 hook 等。action 执行器会（a）先获得一个执行 invoke，包含运行时 action id、执行参数、框架配置等；（b）然后对每个 action 执行通用/专用 hook 检查；（c）等待全部行动执行完成或超时，每个 action 返回结构化 action result（包括执行过程中的检查和超时等错误）；（d）渲染和处理 action result，例如需要反馈给模型的结果、日志记录的结果等。

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
    - how_action（/action_name/(ACTION.md+ACTION_MEMORY.md))
    - this_day_memory.md（以前 memory 只读，在 home 中不需要拉过来，查询即可）

Trap/异常和信号：TinySoul 使用统一的异常定义和内部信号处理，采用 OS-中断设计思路和实现风格。对于异常，可以分为（1）模块层面暂时抛出并局部处理，例如 Action 执行中的失败，被执行器捕获后结构化为 Action Result，以及 llm 模块的模型重试和切换；（2）上层逻辑层面的全局处理，并在触发后陷入处理流程，例如语境过长需要压缩、home 副本拷贝等框架层面的机制（类似页表换出），以及响应用户外部指令，例如中断当前用户轮、中断程序，或追加用户输入（陷入处理后转化为内部信号给内部模块消费）。TinySoul 整体异常处理分成如下层次：（a）局部修复策略（llm 模块的模型重试和切换）和错误映射（Action 异常转换为模型反馈），局部处理失败后再向上层报错；（b）由全局处理决定继续当前用户轮（返回异常陷入位置）/中断当前用户轮/退出程序；

异常与内部信号处理的区别在于，异常决定恢复位置和期间执行的大型任务。内部信号主要用来清晰描述内部模块的行为，例如 action result 结束后发出信号去追加 TurnTraceContext；Phase1 完成后通过信号去变更 BackgroundContext。信号可以使意图和实际消费执行过程分离，使代码更清晰。

tinysoul 运行层级：依次可分为（1）模块级，模块内部完成特定任务；后面两个层级对于用户可见；（2）用户轮级，协调各个模块完成一次用户对话，在用户轮启动时，用户可以追加对话进入用户轮；（3）顶层，循环等待用户新一轮对话输入或者指令，指令可以是 exit，也可以是执行与用户轮同层工作（例如每日沉淀），执行过程可以通过异常陷入处理执行；同层工作执行中不再接受用户输入。

tinysoul 可观测性：实现三个层级的终端显示（正常运行/VERBOSE/MODEL：专门附加反馈给模型的上下文，便于调试）。代码层面应该统一插入简约的观测代码，然后在 infra 层将接收到的 trace 进行渲染。
