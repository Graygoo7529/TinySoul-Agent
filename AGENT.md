# TinySoul 协作规约

本文档约定 TinySoul 项目的分析、设计、实现和文档维护规则。目标是保持设计清晰、代码干净、讨论充分，并让文档与实际实现长期一致。

## 核心定义

用户轮/User Turn：从用户发起一轮输入开始，到响应该输入的一次完整 Agent 执行结束；其中包含多次模型调用和工具调用，也包含期间用户追加的提示、Agent 自发提示的插入，以及最终回答。

执行轮/Agent Cycle：Agent 内部的一个执行轮。TinySoul 的一个执行轮由 3 个执行单元（Phase）组成：（1）更新语境与决策行动域；（2）生成行动参数；（3）采取行动。每个 Phase 都是一个独立执行单元，并对应一次具体的 Task/LLM Call；每个 Phase 都可以有对应的 task prompt。

模型轮/LLM Call/LLM Task：一次模型调用。TinySoul 通过 /llm 模块提供模型调用抽象；LLM Task 的主要输入是构造完成的 message stack，由整体语境（context）和临时性的本次任务提示（task prompt）共同构成。

行动执行/Action：一次智能体行动执行。TinySoul 通过 /action 模块提供行动执行抽象；Phase1 不直接暴露全部 action，而是暴露可选择的 action domain；Phase2 只在已选 domain 内暴露具体 Action Tools，并基于每个 action 的工具调用结构（name、description、schema）和补充语义（use_when、avoid_when、effects、examples）生成 ActionCall；Phase3 再将 ActionCall 装配为自包含的 ActionBatch 进行实际执行。每个 action 还具有框架内定义，例如超时、并发策略、hook 列表和后端执行方式。行动主要由 NATIVE 内部函数调用、受控子进程、临时脚本和需要嵌套 LLM Task 的动作构成；NATIVE 只能通过 ActionExecutionControl 协作式响应超时，受控子进程和临时脚本承担需要硬停止的执行语义；不再支持持续性/长期 ONGOING action，所有动作都在所属批次内收敛为成功、失败或超时。

模型侧工具/Tool Message：TinySoul 可以在 LLM Task 中向模型提供模型侧工具定义，用于约束模型生成结构化调用意图。模型侧工具分为两类：（1）Control Tools，框架内部控制工具，用于在 Phase1 中生成对于 WorkingContext、BackgroundContext 和用于 Phase2 行动选择等操作意图；（2）Action Tools，智能体行动工具，用于在 Phase2 中为已选择的 Action 生成调用参数。模型侧工具只表达模型输出协议，不等同于实际工具执行。Control Tools 的结果由 Phase1 汇聚、校验并转化为内部操作信号后，由对应上层模块消费；Action Tools 的结果由 Phase2 归一化为 Action 参数，再交由 Phase3 执行。

持久化/内存/模型反馈：表述和编码时要注意三个层次。模型反馈是最终查询给模型的提示词（构造后的 message stack）；内存是各个上层模块维护的数据结构与信息；持久化是本地目录下组织的文档、资源和知识库。三者应当保持一致性：上层模块维护运行时各段消息的状态，依据运行状态在调用 llm task 时“构造” message stack，并将状态变更同步回写到持久化的本地文件系统中。

语块与渐进式加载：我们认为，语言的表述以语块的形式促进理解。从发音到单词、到短语、到某种固定表达，交流双方仅通过特定前缀即可“匹配”特定语块的含义，并理解对方大致表达的内容。渐进式加载是一种策略：Agent 在 Context 中“看到”访问内容的“链接/Link”，在需要进一步释义时调用工具加载细节。语块的形成是从细节到抽象，而渐进式加载是从抽象到细节。

语境/Context：我们认为，语言交流是一种“语言游戏”。语言游戏的参与双方基于各自语境，通过语言交流推测对方意图，以相互理解并达成共同目标。语境包含当前游戏状态和规则，帮助 Agent 做出决策和行动。完整语境包含以下部分：（1）本轮 UserInputs，包含当前用户轮的初始输入和已合并追加输入，是该用户轮的出发点；（2）BackgroundContext，用户轮开始前的背景，由 Context 持有并聚合 Home、Memory 和 Session 等模块提供的投影，包含智能体世界观、方法论、昨日长期记忆（如有）与当日会话历程；（3）TurnTraceContext，本轮为完成工作而产生的行为轨迹，包含当前轮次 Agent 的行动决策和行动反馈，不保存原始用户输入历史；（4）WorkingContext，本轮任务执行状态，给予 Agent 一种“工作台”，描述当日工作区内的文档资源（工作区/Workspace），以及本轮任务执行状态：里程碑（MileStone，类似储存重要状态与结论的寄存器）和待办事项（Todo）。BackgroundContext 是 Context-owned 的通用 Phase1 Background，不得以 Home 命名或让任一内容提供模块拥有整个 Background。

LLM Task/Call “构造式” MessageStack：LLM Task/Call 的主要输入为 MessageStack。MessageStack 可以分为多个区段，分别由上层不同模块提供语境（Context）或附加任务提示（task prompt），并在实际 LLM Task 前“构造”为完整的 MessageStack。当前构造顺序为 system identity、UserInputs、BackgroundContext、TurnTraceContext、WorkingContext、task prompt overlay；除 identity 使用 system role 外，其余用户态语境段和 task prompt 均作为 user role messages 提供给模型。TurnTrace 在前表达本轮按发生顺序积累的行为轨迹，Working 在后只表达当前 milestones、todos 与 Workspace resource Links/summary。revision、digest 等完整性事实只由确实需要持久化、Endpoint、CAS 或 cursor binding 的 owner 协议维护，不因内部存在就自动暴露给模型，也不为没有消费者的投影建立平行版本身份。

除了上述语境，task prompt 由 TaskPrompt 表达，并由可切分的 PromptBlock 组成；其稳定语义分为任务引导、任务输入和期望输出三组，当前实现分别以 guide_blocks、input_blocks、output_blocks 承载，并可渲染为多条 user role message。例如，Phase1、Phase2 会说明当前处于执行轮/Agent Cycle 的哪一个阶段、可用输入和期望输出；Phase2 会自动注入 domain HOW 作为 guide block；Phase3 Action 内部嵌套的 LLM Task 可同时自动注入 domain HOW 与 action HOW；这不同于通用 HOW 和普通渐进式加载，`how_domain`/`how_action` 是框架的局部自动挂载机制，分别作用于 domain（Phase2，并可延续到 Phase3 内部 LLM task）和 domain 内 action（Phase3 内部 LLM task）。通用 LLM action 使用 `reference_links` 解析只读资源；workspace LLM action 使用 `target_link` 与 `reference_links`，并在 action 内部局部读取目标和参考正文。“构造式”表示为每次 LLM Task 制定不同的 MessageStack，并在上层维护通用语境，在 Task 完成后对语境进行反馈和修改。

工作区/WorkSpace：每日会话为 Agent 维护一个专用的、可操作的本地路径，Agent 可以在其中操作文件和执行脚本。WorkSpace 内资源在语境中有专属的链接/Link 标识（例如 workspace:doc/doc.md），并使用相对路径读取资源。WorkSpace 有一个专用描述文件，用于记录工作区结构和其中各文件摘要，并可在用户轮开始时映射到 WorkingContext 语境中，同时采用约定的目录结构和命名风格。工作区中文件读取具有特定约定：文件内容（如文档、脚本、图片）通常不应出现在语境/Context 中，也就是说，行动/工具执行结果不应返回实际内容并记录到 TurnTraceContext；Context（工具的输入和输出）仅记录相关资源的链接/Link。例如需要修改的文档，或可以作为参考的相关文档、图片等，只在 Phase3 具体 action 执行期读取；Phase2/Phase3 边界只传递链接语义：只读资料使用 `reference_links`，工作区操作目标使用 `target_link`；需要 LLM 的 workspace action 在 Phase3 action 内部把 `target_link`/`reference_links` 局部解析为临时 task prompt input block。真正的文件变更仍由 workspace.write/patch/delete/rewrite 等变更 action 通过 `target_link` 表达。

Agent Home 与链接/Link：Agent Home 存储 Agent 的持久身份规约、用户偏好、知识与技能；长期日期记忆属于独立 Memory 模块，不属于 Agent Home。Agent Home 主要以 Markdown 文档组织，分为顶层内容和渐进式内容。顶层内容默认或逐步（通过 Phase1）加载到 BackgroundContext，顶层内容通过特殊链接（例如使用 @ 而非 /）标识；渐进式内容不放在 BackgroundContext 中，主要通过行为/工具以工具结果返回到 TurnTraceContext 中。以下分别描述 Agent Home 的内容形式、运行位置与链接：

（1）AGENT.md 是顶层内容，类似一本参考全书目录，记录 AGENT 所具有的整体规范、行为设定、核心规则、用户偏好等。运行时 core 使用 `home:agent@AGENT`，其它 Agent 顶层内容使用相对于 `home/agent/` 的无后缀逻辑路径，例如 `home:agent@user/user`；Layout 将其确定性映射到对应 `.md` 文件。在 user.md 中可以进一步链接渐进式内容。`home:*@...` 只表示该 Link 是可进入 BackgroundContext 的顶层内容，不等于自动加载；Home provider 每个 User Turn 必须自动加载不可逐出的 core，并对 explicit allowlist 中 effective 存在的 `home:agent@context/background`、`home:agent@context/turn-trace`、`home:agent@context/working` 与 `home:agent@user/user` 自动加载不可逐出的正文；其它 Agent/WHAT/WHY/通用 HOW 顶层内容按需加载；

（2）WHAT 是一个 Knowledge 库，用于标注（a）实体（b）领域概念。WHAT Link 显式包含分类和相对于 `home/what/` 的无后缀逻辑路径，例如 `home:what@entity/tiny-soul`、`home:what@concept/daily-lifecycle`，分别映射同路径 `.md` 文件；因此 entity 与 concept 中的同名文件仍是不同顶层对象，新 WHAT 的分类无需再由 Link 之外的平行参数表达。WHAT 文档记录定义和关联内容，可通过语义匹配 top-k 交付语境模块，也可通过未来的 backlink 能力反向查询引用该 Link 的其它 Home 内容；WHAT 不应有时间戳，只记录当前认为正确且重要的内容；

（3）WHY 是另一个 Knowledge 库，用于标注问题的原因和解答。WHY Link 使用相对于 `home/why/` 的无后缀逻辑路径，名称应直接表达问题，例如 `home:why@why-is-updating-home-important`，并映射同路径 `.md` 文件；WHY 文档是顶层内容，并可通过语义匹配 top-k 交付语境模块；

（4）HOW 是另一个 Knowledge 库，它是当前智能体设计中 Skill 的变种，在语境中通过 `home:how@skill_name` 标识。该 Link 是保留的框架 skill identity，映射 `how/<skill_name>/SKILL.md`，不伪装为普通文件路径；HOW 渐进资源则保留真实相对路径和扩展名，如 `home:how/skill_name/references/ref.md`、`home:how/skill_name/scripts/script.py`。每个通用 `SKILL.md` 必须使用 YAML `---` frontmatter，且 frontmatter 只包含非空、单行、有界的 `title` 与 `description`；Home 在启动/reconcile、runtime 恢复和 top write/patch 边界统一严格解析。每个 User Turn preparation 都从 effective Home 动态扫描全部通用 HOW，把 Link/title/description 作为 Context-owned、不可逐出的自动 Background catalog 交给 Phase1，使 Phase1 知道可通过内部 `load_background` control tool 加载哪个顶层 HOW 正文；catalog 不是一个伪造的 Home 顶层文件，正文仍按需加载。完整 metadata catalog 受总字符上限约束，超限时显式失败，不截断 description 或丢弃 skill；runtime create/modify/delete 在后续 Turn 的 effective catalog 中反映。通用 HOW 的 runtime 包额外包含 `SKILL_MEMORY.md`：它只存在于 `runtime/home/how/<skill_name>/`，记录自上次 Home Maintenance 以来该 skill 的临时工作记忆、使用反馈和待 review 变更，供后续 User Turn 与 Home Maintenance review 使用；它不属于 actual Home，对应 skill 的 Home Maintenance review 完成后必须清空。除了通用 HOW，还有两类与行动域绑定的自动 HOW：`how_domain` 作用于 domain，使用 `home:how_domain:<domain>` 在 Phase2 自动注入，并可在 Phase3 的 action 内部 LLM task 中继续作为 domain 约束；`how_action` 作用于 domain 内具体 action，使用 `home:how_action:<domain>/<action>` 在 Phase3 中带内部 LLM task 的 action 自动注入。这两类 Link 同样是保留的框架 mount identity，不附加物理 `DOMAIN.md`/`.md` 文件名。`how_domain` 与 `how_action` 不参与通用 HOW metadata catalog 或普通渐进式加载，也不由模型通过 `home.resource.read` 主动读取；它们可以透明物化到 runtime，并通过专用 prompt mount mutation action 修改。逻辑 mount 的创建和删除由框架根据 Action Catalog 中的 domain/action 自动维护，模型不负责 create/delete；它们不创建 `SKILL_MEMORY.md`、`DOMAIN_MEMORY.md` 或其它平行 memory 文件；

长期记忆/Memory 与链接/Link：Memory 是与 Agent Home 平级的独立持久模块。每个被提炼的 Business Day 对应一个 `memory/yyyy/mm/yyyy-mm-dd.md` 日志，并使用无格式后缀的日期逻辑身份 `memory:YYYY-MM-DD` 标识；Memory 模块将其确定性映射到物理年月 Markdown 路径，二者不能由其它模块自行拼接。Memory 在普通 User Turn 中只读，不建立 runtime copy、不参与 Home runtime diff，也不通过 Home action 修改。`<memory:YYYY-MM-DD>` 可出现在 Context 和 MEMORY 正文中，表示应通过 Memory recall 加载指定日期，不表示内联正文或 Home 顶层内容。

每个 User Turn 的 preparation 都按同一 Business Day 与业务时区确定“昨日”；若精确的昨日 MEMORY 存在，Memory provider 将完整但受文档上限约束的正文作为自动 Background entry 交给 Context。缺失昨日 MEMORY 是正常状态，不回退到更早日期；文件存在但不是非空、可读、上限内的 UTF-8 文本时是 Memory 模块失败。该 entry 每 Turn 重建，在 Context 压力回收时可被逐出；Home core 与 effective 存在时自动加载的 allowlisted Context/user Agent Top 正文仍是不可逐出的默认规约。其它日期 MEMORY 不进入可加载 Home 目录，只能通过 `memory.search(query, top_k)` 与 `memory.recall(memory_link)` 按需访问；search 以单日文档为候选，只返回稳定 Link、日期和有界摘要，recall 返回完整但受上限约束的单日 Markdown，两者的 ActionResult 都进入当前 TurnTraceContext，不修改 Background。

Memory Maintenance 读取 Session 为指定日期提供的专用 facts projection：Session 按需递归已提交 Summary 图，只交付唯一、可达并按 Turn 开始时间稳定排序的事实，不暴露 store 或 archive 文件结构。单日 MEMORY 是自由结构 Markdown，不要求上午、下午、晚上或其它固定章节；旧 MEMORY 只要是非空、可读、上限内的 UTF-8 文本，无论既有格式如何，都可在人工重写时作为同日期附加 source 与 Session facts 一起执行有界分层 consolidation。LLM 严格返回一个 Markdown body，Memory 只确定性渲染日期 H1。正文中的 Home top Link 必须指向当前 actual Home 中已存在的顶层内容，`<memory:YYYY-MM-DD>` 必须指向已存在的其它日期 MEMORY；完整 catalog 只用于本地校验，模型只接收从 source 提取的有界有效 Link hints，非法或不存在的 Link 以有界模型反馈重新生成。Session archive 缺失或 projection 为空时 `skipped` 且不创建、不覆盖、不删除 MEMORY；否则生成完整新 MEMORY 并原子覆盖，不 append、不读取其它日期 MEMORY 正文作为 consolidation 输入。自动任务若目标 MEMORY 已存在且可读取、非空、未超限，则在读取 Session 或调用模型前 `skipped`；人工任务可结合旧 MEMORY 与 Session 重写。启动自动提示不再只检查昨日：Archive 完成的每个新关闭日按 Session facts 增量登记，已持久的日期列表跨重启保留并逐项清理；人工命令仍可显式指定日期。

基于以上设计，链接/Link 语义分为五类：（1）Home 顶层知识入口，可通过默认加载或 Phase1 加载到 BackgroundContext；（2）Agent Home 非顶层资源，通过 action 结果进入 TurnTraceContext；（3）Memory-owned 日期记忆，昨日可在 Turn preparation 自动加载，其它记忆通过 search/recall 进入 TurnTraceContext；（4）workspace 资源句柄；（5）how_domain/how_action 局部自动 prompt mount。归纳如下：
（1）`home:agent@<path>`、`home:what@entity|concept/<path>`、`home:why@<path>` 与 `home:how@<skill>` 表示“顶层知识入口”；它们都使用无格式后缀的逻辑身份，前三类由 Layout 追加 `.md`，HOW 映射固定 `SKILL.md`；顶层知识可加载为 BackgroundContext；
（2）home:xxx/ 表示“可被行动读取或使用的资源”加载到 TurnTraceContext；资源 Link 保留真实扩展名，但不得用 `/` 形式访问已属于 Top identity 的 Agent/WHAT/WHY Markdown 或通用 HOW `SKILL.md`；
（3）`memory:YYYY-MM-DD` 表示单日长期记忆；`<memory:YYYY-MM-DD>` 是提示 Agent 按需 recall 的稳定引用；
（4）workspace: 永远是工作区资源句柄；
（5）home:how_domain:<domain> 和 home:how_action:<domain>/<action> 表示临时、局部自动 prompt mount，只进入对应 Phase/task prompt；


根目录结构如下：

- `home/`：已经由 Maintenance 提交的 actual Home；
- `memory/`：Memory-owned 的单日长期记忆，按 `yyyy/mm/yyyy-mm-dd.md` 组织，不建立 runtime 副本；
- `runtime/`：保存运行中的可变状态；
  - `session/`：当日跨 Turn 会话事实；
  - `workspace/`：当日工作区及 active `.tinysoul/trash`；
  - `home/`：Agent Home 内容的跨日懒加载 overlay，直到 Home Maintenance 处理后才清理对应 diff；
- `archive/<timezone-timestamp>/`：一个已冻结 Business Day，包含 `transition.json`、`session/`、`workspace/`、`trash/`，不包含 Home；旧日 Trash 只是归档事实，不再进入 active list/restore 或其它语义追踪 API。

一个用户轮由多个执行轮/Agent Cycle 构成，执行轮依次进行执行单元/Phase。
（Phase1）更新语境与决策行动域：基于完整语境/Context，调用 LLM Task。Phase1 可以向模型提供框架内部 Control Tools，例如状态更新工具、背景更新工具和 Phase2 行动域选择工具；模型返回的 Control Tool Calls 不直接修改状态，而是在 Phase1 结束后被汇聚、校验、归一化并转化为内部操作信号，由 WorkingContext、BackgroundContext、Loop 等上层模块分别消费；从而执行（a）加载或逐出 BackgroundContext 中的顶层内容；（b）更新 WorkingContext 中的里程碑或待办；（c）选择一个或多个 action domain 进入 Phase2；Phase1 不生成完整行动参数，也不暴露全部二级 action 定义。`load_background` 接受一个或多个开放字符串形式的 Top Link，不把完整 effective top catalog 编码为模型工具候选；模型应从当前 Context 已暴露的默认 Agent Top 前向 Link、通用 HOW metadata、Home search 或 ActionResult 等来源取得 Link，工具定义至多是这种已有 Link 的强化提示，Context 在提交前仍按当前 effective provider catalog 校验 Link 是否真实可加载；
（Phase2）生成行动参数：为 Phase1 选择的 domain 生成具体 ActionCall，调用 LLM Task。Phase2 只向模型提供已选 domain 内的 Action Tools、对应 action 的工具调用结构与补充语义，并自动注入 domain HOW；模型返回的 Action Tool Calls 被归一化为 ActionCall；
（Phase3）采取行动：一个 map-reduce 风格的执行器，将 Phase2 的 ActionCall 装配为 ActionBatch 并实际执行。每个 action 除了反馈给模型的工具调用结构和补充语义外，还有框架内配置，例如超时时长、并发策略和通用/专用 hook 等。action 执行器会（a）将 ActionCall 补充为包含已解析 ActionSpec、运行时 action id、批次 id、执行参数、框架配置的自包含执行输入；（b）对每个 action 执行通用/专用 hook 检查；（c）等待全部行动执行完成或超时，并优先通过协作取消或进程终止收束执行体；（d）为每个 action 返回结构化 ActionResult（包括检查失败、执行失败和超时等结果）；（e）渲染和处理 ActionResult，例如需要反馈给模型的结果、日志记录的结果等。Batch 只是执行编排容器，不额外定义 batch result。

每日生命周期与 Maintenance：只有 Session、Workspace 和 active Trash 具有强制 Business Day 生命周期。新日开始时，框架必须先完成不依赖 LLM 的确定性日切：恢复未完成的日切 journal，完整 reconcile 旧日 Session 与 Workspace，把 Session、Workspace、Trash 移到同一个时间戳归档，再建立同一新日的空 Session/Workspace roots；在确定性日切完成前不能接受新日 User Turn。程序持续运行时由内置 scheduler 在配置的日界触发，程序未运行时由下次启动补做。Home 不参与每日日切，也不进入 archive。恢复保证覆盖 Python 进程异常与文件操作失败：participant 已移动但 step journal 未提交、active roots 已初始化但 step 未提交、final rename 失败等窗口都通过 persisted facts 前滚；不宣称断电、磁盘缓存刷新或跨目录原子事务级持久性。


Trap/异常和信号：TinySoul 使用统一的异常定义和内部信号处理，采用 OS-中断设计思路和实现风格。对于异常，可以分为（1）模块层面暂时抛出并局部处理，例如 Action 执行中的失败，被执行器捕获后结构化为 Action Result，以及 llm 模块的模型重试和切换；（2）上层逻辑层面的全局处理，并在触发后陷入处理流程，例如语境过长需要压缩、home 副本拷贝等框架层面的机制（类似页表换出），以及响应用户外部指令，例如中断当前用户轮、中断程序，或追加用户输入（陷入处理后转化为内部信号给内部模块消费）。TinySoul 整体异常处理分成如下层次：（a）局部修复策略（llm 模块的模型重试和切换）和错误映射（Action 异常转换为模型反馈），局部处理失败后再向上层报错；（b）由全局处理决定继续当前用户轮（返回异常陷入位置）/中断当前用户轮/退出程序；

异常与内部信号处理的区别在于，异常决定恢复位置和期间执行的大型任务。内部信号主要用来清晰描述内部模块的行为，例如 action result 结束后发出信号去追加 TurnTraceContext；Phase1 完成后通过信号去变更 BackgroundContext。信号可以使意图和实际消费执行过程分离，使代码更清晰。

tinysoul 运行层级：依次可分为（1）模块级，模块内部完成特定任务；后面两个层级对于用户可见；（2）用户轮级，协调各个模块完成一次用户对话，在用户轮启动时，用户可以追加对话进入用户轮；（3）顶层，循环等待用户新一轮对话输入或者指令，指令可以是 exit，也可以是执行与用户轮同层工作（例如每日沉淀），执行过程可以通过异常陷入处理执行；同层工作执行中不再接受用户输入。

tinysoul 可观测性：实现三个层级的终端显示（正常运行/VERBOSE/MODEL：专门附加反馈给模型的上下文，便于调试）。代码层面由业务所有者发布简约、JSON 安全且不参与控制流的 ObservationEvent，App 层统一过滤、扇出并渲染；Observation sink 失败不能反向改变业务提交。


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
- `home` 是 `home:` 内容和 HOW 的唯一 owner。actual Home 在普通运行中只读，User Turn 的改动写入跨日 runtime overlay；Home Maintenance 才能把审核后的变更提交回 actual Home。长期日期记忆不属于 Home。
- `memory` 是 `memory:YYYY-MM-DD` 日期记忆的唯一 owner。普通 User Turn 只读，昨日记忆可作为 Background，其余日期按需召回；Memory Maintenance 对单日文档执行原子完整写入。
- `maintenance` 拥有业务时钟、确定性日切、归档以及 Home/Memory 维护任务的编排。Archive、Home、Memory 的私有存储仍由各自 owner 解释，维护任务之间不互读私有实现。
- `capabilities` 只承载无独立持久化和生命周期的具体能力，通过 Action 注册自身服务和执行器；不得另建与 Workspace、Home、Memory 或 Session 平行的状态模块。
- `endpoint` 是本地客户端协议适配层，与 Terminal 共用同一 App 和业务 Engine。它负责鉴权、请求映射和 Observation replay，不拥有业务状态、退出权或任意文件 API。

### 关键协作语义

- Phase1 只确定行动域并处理语境控制意图，Phase2 在已选域内生成 ActionCall，Phase3 执行 ActionBatch；每个调用都应归一化为可记录、可反馈的结果。
- Context 的 Background、TurnTrace、Working 和 task prompt 是不同语义层：Background 提供可复用背景，Trace 记录本轮行为，Working 表达当前工作状态，task prompt 只服务当前 LLM Task。资源正文不因存在链接而自动进入 Context。
- Link 是跨模块资源身份，不是物理路径拼接约定。`home:`、`memory:`、`workspace:` 各自由 owner 解析；顶层知识、渐进资源、工作区资源和局部 HOW mount 不得混用。
- Session、Workspace、Home overlay 和 Memory 文档的写入都必须在 owner 的一致性边界完成，使用校验、reconcile、CAS 或原子替换保证不会产生半提交状态。LLM 生成期间读取的资源集合必须在提交时复验。
- User Turn 与 Maintenance Turn 都在完整情景中运行；Maintenance 是自治的 Program work，不等待人工审批，不把维护状态塞入 User Session，也不让维护请求绕过 Program 队列。

### 失败与控制流

- 失败按三层处理：可由模型或上层继续处理的局部事实返回结构化结果；模块契约、配置、依赖或持久化不满足时停在模块边界；只有需要改变全局运行位置时才转换为 Runtime 语义异常。
- 局部 Action、LLM 或 phase 失败必须带有稳定、有限、可反馈的原因和摘要，不携带原始异常、traceback、绝对路径、敏感值或大块资源正文。
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

当前任务已从核心模块重构转入 TinySoul 整体应用构建与优化。`reference/tinysoul_v1` 只作为历史设计与行为参考；当前代码、模块设计文档和已完成执行记录才是实现事实。后续工作不得使用兼容层、重复状态或跨模块捷径。


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
