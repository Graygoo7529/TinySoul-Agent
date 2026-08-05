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


一个用户轮由多个执行轮/Agent Cycle 构成，执行轮依次进行执行单元/Phase。
（Phase1）更新语境与决策行动域：基于完整语境/Context，调用 LLM Task。Phase1 可以向模型提供框架内部 Control Tools，例如状态更新工具、背景更新工具和 Phase2 行动域选择工具；模型返回的 Control Tool Calls 不直接修改状态，而是在 Phase1 结束后被汇聚、校验、归一化并转化为内部操作信号，由 WorkingContext、BackgroundContext、Loop 等上层模块分别消费；从而执行（a）加载或逐出 BackgroundContext 中的顶层内容；（b）更新 WorkingContext 中的里程碑或待办；（c）选择一个或多个 action domain 进入 Phase2；Phase1 不生成完整行动参数，也不暴露全部二级 action 定义。`load_background` 接受一个或多个开放字符串形式的 Top Link，不把完整 effective top catalog 编码为模型工具候选；模型应从当前 Context 已暴露的默认 Agent Top 前向 Link、通用 HOW metadata、Home search 或 ActionResult 等来源取得 Link，工具定义至多是这种已有 Link 的强化提示，Context 在提交前仍按当前 effective provider catalog 校验 Link 是否真实可加载；
（Phase2）生成行动参数：为 Phase1 选择的 domain 生成具体 ActionCall，调用 LLM Task。Phase2 只向模型提供已选 domain 内的 Action Tools、对应 action 的工具调用结构与补充语义，并自动注入 domain HOW；模型返回的 Action Tool Calls 被归一化为 ActionCall；
（Phase3）采取行动：一个 map-reduce 风格的执行器，将 Phase2 的 ActionCall 装配为 ActionBatch 并实际执行。每个 action 除了反馈给模型的工具调用结构和补充语义外，还有框架内配置，例如超时时长、并发策略和通用/专用 hook 等。action 执行器会（a）将 ActionCall 补充为包含已解析 ActionSpec、运行时 action id、批次 id、执行参数、框架配置的自包含执行输入；（b）对每个 action 执行通用/专用 hook 检查；（c）等待全部行动执行完成或超时，并优先通过协作取消或进程终止收束执行体；（d）为每个 action 返回结构化 ActionResult（包括检查失败、执行失败和超时等结果）；（e）渲染和处理 ActionResult，例如需要反馈给模型的结果、日志记录的结果等。Batch 只是执行编排容器，不额外定义 batch result。

每日生命周期与 Maintenance：只有 Session、Workspace 和 active Trash 具有强制 Business Day 生命周期。新日开始时，框架必须先完成不依赖 LLM 的确定性日切：恢复未完成的日切 journal，完整 reconcile 旧日 Session 与 Workspace，把 Session、Workspace、Trash 移到同一个时间戳归档，再建立同一新日的空 Session/Workspace roots；在确定性日切完成前不能接受新日 User Turn。程序持续运行时由内置 scheduler 在配置的日界触发，程序未运行时由下次启动补做。Home 不参与每日日切，也不进入 archive。恢复保证覆盖 Python 进程异常与文件操作失败：participant 已移动但 step journal 未提交、active roots 已初始化但 step 未提交、final rename 失败等窗口都通过 persisted facts 前滚；不宣称断电、磁盘缓存刷新或跨目录原子事务级持久性。

`runtime/home` 是跨 Turn、跨 Business Day、跨重启保留的懒加载可写 overlay。Home 顶层内容、渐进资源和 HOW 在真正使用时通过 Trap 透明物化，并始终从 `runtime override/tombstone -> actual Home fallback` 的 effective view 读取；所有普通 User Turn 修改只写 runtime。未触发 Home Maintenance 时，当前 runtime diff 就是 Agent 继续透明读写的事实对象，不清空、不归档。Context 在每个 User Turn 重建通用 Background，Home 只提供其拥有的 core 与可加载顶层条目；Phase1 临时加载项不依靠内存跨 Turn 保留。

`home.top.search` 只检索 WHAT、WHY 与通用 HOW，不包含 `agent`、`how_domain`、`how_action` 或 MEMORY。搜索由 Home-owned 独立服务基于 effective catalog 构造有界 metadata，不物化全部 runtime copy，也不把完整正文自动加入 Background；WHAT/WHY 的标题取 Markdown 首个 H1，短摘要取首个有效正文段，缺失时分别回退 Link name 与有界正文前缀；通用 HOW 必须复用严格校验的 frontmatter title/description，不从正文产生第二套 skill metadata。搜索先以 link/name/title/summary/prefix 做确定性候选限制，再通过受控 LLM task rerank；validator 只接受候选内 Link，rerank 失败时返回确定性候选而不使只读搜索整体失败。MEMORY 的搜索、召回和日期 Link 全部归 `tinysoul.memory` 拥有。

Maintenance 是与 User Turn 同级的 Program work。`tinysoul.app` 拥有顶层请求队列和 Program frame，并将 `UserTurnRequest` 分派给 User Turn，将 `MaintenanceRequest` 分派给 `MaintenanceEngine`，将 `ExitRequest` 交给 Program trap；输入源和 scheduler 只能投递 typed request，不能越过 Program 直接操作 Session、Workspace、Home 或 Memory。手动命令与定时触发只在 request 的 trigger、目标日期和可选 rebuild 参数上不同，进入 Maintenance 后使用同一个任务编排和结果协议；全程自动执行，不需要人工 approval，不建立 decision channel，也不因等待人类输入而阻塞。显式命令为 `/maintenance` 或 `/maintenance daily`、`/maintenance home`、`/maintenance memory YYYY-MM-DD [--rebuild]`。长运行 App 的 scheduler 按 `maintenance.schedule` 每日投递一个 Daily request；手动和定时 Daily 都运行当前 Home task，并且最多只运行当前 Maintenance BusinessDay 的昨日 Memory task，更早的 Memory 欠账继续保留供按日期精确执行。程序启动只补做确定性日切、刷新唯一 Maintenance availability 并报告一个聚合 Home 待办和全部 Memory 日期，不追补启动前错过的 LLM Maintenance。计划时刻前已启动的进程会按时投递；运行中跨过计划时刻或多日休眠后只合并投递一个当前日 Daily request。

`tinysoul.maintenance` 是唯一维护门面和业务 owner，并分为 Archive、Home、Memory 三个独立包。Archive 先执行不依赖模型的日切、恢复和只读归档投影，禁止把仍开放的当天作为 Memory 目标。每次 Archive 完成或恢复后，Maintenance 只检查该归档日：Archive Session facts 非空且该日有效 MEMORY 缺失时，把日期增量登记到持久 `memory_days`；Archive Workspace 只提供 Memory Turn 情景，不单独产生待办。既有 `memory_days` 跨重启保留并在刷新时删除已经存在有效 MEMORY 的日期，因此正常启动不扫描全部 Archive days，也不只猜测昨日。Home 不进入日期列表；每次刷新都由 Home owner 重新计算当前 diff 与 `SKILL_MEMORY.md` 计数。两类信息共同原子写入唯一 Maintenance availability：它是前端的唯一提示单和 Maintenance-owned 待办投影，不是 plan、review、approval 或 settlement 状态；前端把 Home pending 投影为至多一个聚合任务，并把每个 Memory 日期投影为独立可执行任务。Archive、Memory、Home owner facts 仍是执行与提交前必须复验的权威状态。Home Maintenance 逐个 inspect runtime Home diff，并通过专用 action 接受、拒绝或整理改写后合并到 actual Home；`SKILL_MEMORY.md` 是独立 HOW review，只有 inspect 后才能 reject/rewrite，非法 HOW rewrite 在写入前被拒绝；完成后移除空的 `runtime/home`。Memory Maintenance 必须以明确日期为目标，通过专用 action 完整写入该日 MEMORY；默认不覆盖已有有效 MEMORY，显式 `--rebuild` 才重写。Home 或某个日期 Memory 失败只形成各自 task outcome，不回滚已完成的其它维护任务，失败待办继续保留。

Program 必须在 Endpoint 对外就绪前完成 Archive preflight 和 availability 持久化。Endpoint 的 Maintenance GET 只读取这份持久投影；`program.maintenance.available`、`maintenance.completed` 与 availability changed Observation 仅通知前端重新读取，不能作为跨重启事实来源。`BusinessDay` 是 Session、Workspace、Loop 与 Maintenance 共用的 owner-neutral Infra 值对象；业务时区、BusinessClock 和日切策略仍归 Maintenance。Maintenance Engine 只把明确的、可继续的 task failure 收敛为 task outcome；Runtime transfer、未分类程序错误、Archive 或 availability 不变量失败必须传播到相应 Program/Runtime 边界，不能被宽泛异常捕获降级。

User Turn 与 Maintenance Turn 复用 `tinysoul.loop` 的 owner-neutral Turn、Cycle 和相同 3-stage Phase 内核；`loop.user.UserTurnBuilder/UserTurnEntry` 拥有 User 主线的完整 Context、Action、preparation、completion 和 runtime policy，`maintenance.MaintenanceBuilder` 与 `maintenance.turn.MaintenanceTurnEntry` 拥有维护支线的对应语义，Loop 根不认识 Maintenance 业务。Maintenance Turn 仍处于完整情景中：它拥有与 User Turn 同结构的 Background、Session 和 Workspace；Home task 使用 actual Home 作为 Background 基线并结合当前 Session/Workspace，Memory task 使用另一个独立 Context，并注入 actual Home 与目标关闭日的 Session/Workspace 只读投影。归档 Session/Workspace 绑定由 `tinysoul.maintenance.memory.ArchivedMemoryMaintenanceContext` 所有，并校验 archive、Workspace、Session 与 Memory Turn 的目标日一致。通用只读 `core.context.inspect` 与 `core.session.inspect` 可由两类 Turn 复用；Maintenance catalog 物理位于 `tinysoul.maintenance` 包，User catalog 中不存在 maintenance domain，Home 与 Memory 两种 Maintenance Turn 又通过精确 action set 互相隔离。Maintenance Turn 不提供 `core.answer`，必须由 owner-bound `maintenance.complete` 验证任务后置条件后结束；它的 pressure/trap 只回收自己的 Context，不注册 active Workspace cleanup、Workspace trash restore 或 Home runtime copy。

actual Home 在普通 User Turn 和确定性日切中严格只读。顶层内容使用专用 `home.top.write/patch/delete` 修改 runtime；允许创建不存在的顶层内容，新 WHAT 必须在无后缀 Link 中显式包含 `entity/` 或 `concept/`，`home:agent@AGENT` 允许 write/patch 但禁止 delete。how_domain/how_action 使用专用 prompt mount write/patch 修改 runtime，逻辑 create/delete 由框架按 Action Catalog 维护。actual Home 的知识与 HOW 只由 Home Maintenance 修改；顶层 `memory/` 中的长期 MEMORY 只由 Memory Maintenance 修改。此前讨论中的“Settlement 可变状态”不是 TinySoul 业务概念，不应引入独立 `settlement/` 状态根或持久 Settlement 状态机。

目录边界如下：

- `home/`：已经由 Maintenance 提交的 actual Home；
- `memory/`：Memory-owned 的单日长期记忆，按 `yyyy/mm/yyyy-mm-dd.md` 组织，不建立 runtime 副本；
- `runtime/`：保存运行中的可变状态；
  - `session/`：当日跨 Turn 会话事实；
  - `workspace/`：当日工作区及 active `.tinysoul/trash`；
  - `home/`：Agent Home 内容的跨日懒加载 overlay，直到 Home Maintenance 处理后才清理对应 diff；
- `archive/<timezone-timestamp>/`：一个已冻结 Business Day，包含 `transition.json`、`session/`、`workspace/`、`trash/`，不包含 Home；旧日 Trash 只是归档事实，不再进入 active list/restore 或其它语义追踪 API。

Trap/异常和信号：TinySoul 使用统一的异常定义和内部信号处理，采用 OS-中断设计思路和实现风格。对于异常，可以分为（1）模块层面暂时抛出并局部处理，例如 Action 执行中的失败，被执行器捕获后结构化为 Action Result，以及 llm 模块的模型重试和切换；（2）上层逻辑层面的全局处理，并在触发后陷入处理流程，例如语境过长需要压缩、home 副本拷贝等框架层面的机制（类似页表换出），以及响应用户外部指令，例如中断当前用户轮、中断程序，或追加用户输入（陷入处理后转化为内部信号给内部模块消费）。TinySoul 整体异常处理分成如下层次：（a）局部修复策略（llm 模块的模型重试和切换）和错误映射（Action 异常转换为模型反馈），局部处理失败后再向上层报错；（b）由全局处理决定继续当前用户轮（返回异常陷入位置）/中断当前用户轮/退出程序；

异常与内部信号处理的区别在于，异常决定恢复位置和期间执行的大型任务。内部信号主要用来清晰描述内部模块的行为，例如 action result 结束后发出信号去追加 TurnTraceContext；Phase1 完成后通过信号去变更 BackgroundContext。信号可以使意图和实际消费执行过程分离，使代码更清晰。

tinysoul 运行层级：依次可分为（1）模块级，模块内部完成特定任务；后面两个层级对于用户可见；（2）用户轮级，协调各个模块完成一次用户对话，在用户轮启动时，用户可以追加对话进入用户轮；（3）顶层，循环等待用户新一轮对话输入或者指令，指令可以是 exit，也可以是执行与用户轮同层工作（例如每日沉淀），执行过程可以通过异常陷入处理执行；同层工作执行中不再接受用户输入。

tinysoul 可观测性：实现三个层级的终端显示（正常运行/VERBOSE/MODEL：专门附加反馈给模型的上下文，便于调试）。代码层面由业务所有者发布简约、JSON 安全且不参与控制流的 ObservationEvent，App 层统一过滤、扇出并渲染；Observation sink 失败不能反向改变业务提交。


## 项目规约

本节是已实现模块的运行方式规约，随模块实现动态补充，供后续模块设计时理解既有模块的协作方式；详细设计见 docs/design/ 对应文档。

- TinySoul 拥有独立的上层动作层。动作选择、上下文选择、参数生成、动作执行结果管理不依赖模型供应商的原生 tool calling 接口；供应商原生 tool calling 只作为 LLM 适配层可选映射方式。
- Infra 提供配置环境、JSON 边界、受控文件读写、当前 Python 解释器的 distribution/module/executable 可用性检查和稳定公共门面。依赖检查通过 metadata/spec/`shutil.which` 检测但不导入、执行或安装目标依赖，也不解释 capability enabled 语义。项目模块配置位于 `configs/`，由 `tinysoul.toml` 显式 include；include 与 env file 都必须是项目根内的相对路径，拒绝绝对路径、`..` 越界和解析后越出项目根的符号链接。Infra 只负责加载、合并并提供 section tree，app/capabilities/context/home/memory/loop/session/workspace/llm 等实际模块各自解析所属配置并由所属 Runtime bridge 映射配置失败。配置显式加载、显式传递，模块不在导入时读取配置或创建全局单例；来自 dotenv、TOML、环境变量、模型输出或外部接口的动态数据，在进入模块内部边界时转换为明确结构，配置语义失败统一表达为 `ConfigError`，不以裸 `ValueError`/`TypeError` 越过 infra 公共边界。Infra 只提供 owner-neutral 的 JSON 字符硬预算切片和 versioned opaque continuation 编解码原语；公开结果只含业务 items/content fragment 与 `next_continuation`，位置、内容绑定和 owner binding 只存在 token 内部。Context/Session 各自拥有 ref、堆导航与 continuation 失效语义；Workspace、Script 和 Shell 已有的业务 cursor 不受该原语影响。
- Runtime 提供运行位置（RunScope）、Runtime 语义异常、Trap 处理器表、运行转移、可重放 Module runner 和 SignalBus。控制流变化（结束 Turn/Cycle/Program、全局恢复、Turn 正常输出）统一构造 Runtime 语义异常进入 Trap，Trap 返回指向当前捕获 RunScope 内 frame 的运行转移，由各级运行器消费；Trap 必须拒绝处理器返回的 scope 外 target。Module runner 捕获一次 RuntimeException、发出 Trap 信号并消费指向自身的 RETRY，指向上层 frame 的 transfer 只展开传播而不重复陷入。未注册 reason 由显式 fallback 结束最近 Turn（启动阶段结束 Program）；SignalBus 只提供信封、队列和批量选择能力，业务模块在自身明确边界按 exact/name/namespace 协议消费，不设置无业务所有权的通用 SignalHandlerRegistry。Runtime 自身对象、SignalBus/Trap 注册表和 payload 边界仍使用 `RuntimeContractError`/`RuntimeInvariantError` 表达契约与装配不变量错误，不进入 fallback。
- LLM 模块负责模型调用输入输出的统一表达、供应商适配、能力与上下文窗口校验、模型选择、重试切换、输出解释，以及 TinySoul 模型侧工具语义与供应商工具协议之间的映射。LLM 配置解析以 `LLMConfigParser` 为公共门面，内部按 provider/model/task section parser 拆分；每个模型必须声明当前 endpoint/套餐下有效的 `context_window_tokens`。provider id 表达独立端点与凭据身份，adapter 表达可复用协议行为，因此 Kimi 开放平台与 Coding Plan 使用不同 provider id 和模型名但共享 `kimi` adapter。OpenAI SDK 形态适配位于 `tinysoul.llm.provider.openai_sdk` 包内，按 client protocol、payload mapper、response parser、common helper、adapter 组合拆分；供应商 option behavior 可读取完整请求，并按 Kimi K2.x/K3 等真实模型协议分别映射思考保留、推理力度与工具选择。TinySoul 工具名是 provider-neutral 稳定 identity，可以保留 Action Catalog 的 dotted namespace；OpenAI SDK 适配器为每个请求基于可见工具和工具历史建立唯一的 provider-safe 临时名称映射，统一编码工具定义、调用历史与结果名称，并在响应边界解码，别名不得进入 ToolScope、ActionCall、Context 或 trace。供应商原生工具历史只按有序 assistant turn 原子回放完整的 call/result 集合；Phase3 嵌套 LLM task 发生时尚未完成的当前 Action decision 继续保留在 Context/trace，但不得作为缺少结果的 provider tool exchange 发送。`tool_use=disabled` 的嵌套任务不发送 provider-native call/result，带 tool call 的 assistant turn 及其 provider-native reasoning 一并跳过，ToolResultMessage 以普通 user context 保留反馈。LLM task cancellation contract 在重试、切换和 provider 调用前检查 Action deadline/cancel，并将剩余时限交给 provider adapter。每次候选模型调用前按 Context 配置的硬水位执行保守 token 预检；同一 LLM Task 的模型链始终复用唯一 MessageStack，不保存容量恢复 checkpoint。Context-built Task 超水位时中止整个 LLM Task 并进入压缩 Trap，Home/Memory 内部 Task 则结束当前流程，不清理 Context。LLM 领域对象与注册表使用 `LLMContractError`/`LLMInvariantError` 表达模块语义失败，不以裸 `ValueError`、`TypeError` 或 `KeyError` 越过 LLM 内部边界；JSON object 兼容解析在规范化完整 fenced JSON 后使用标准 `json.loads`，不自行扫描括号。Provider 错误在模型链内部统一完成同模型重试或切换，只有模型链耗尽或模型上下文压力才作为稳定 bridge failure 改变 Runtime 控制流。LLM 模块不负责执行工具、不修改 Context，也不消费 Control Tool 或 Action Tool 的业务语义。
- Assistant 消息表达模型历史输出，可以包含可见内容和可选推理内容。推理内容用于上层在构造后续上下文时保留模型推理轨迹；是否保留、如何压缩由上层语境或动作层决定，具体传入供应商的回放形态由 LLM 适配层依据 provider options 和供应商能力决定。
- LLM 消息内容需要支持灵活的多片段结构，以表达文本、图像和由上层构造的结构化上下文。结构化上下文属于消息内容的一部分，而不是供应商 tool calling 协议的一部分。
- TinySoul 可以定义自己的 tool message 语义，用于表达模型侧工具定义、工具调用意图和工具结果回放。Provider 原生 `tool` message、`tool_calls`、`tool_call_id` 或 Responses `function_call` 不直接进入 TinySoul 核心语义，应由供应商适配层映射为 TinySoul 内部工具调用结构。
- Phase1 使用 Control Tools 表达框架内部控制操作。Control Tool Calls 在 Phase1 汇聚后转化为操作信号，并由对应上层模块按自身信号消费协议批量处理。
- Phase2 使用 Action Tools 表达行动参数生成。Phase2 只接收 Phase1 选择的 action domain，并基于已选 domain 内 action 的工具调用结构、补充语义、工具 schema 和自动注入的 domain HOW 生成 ActionCall。
- 工具、技能或外部动作执行结果应由上层整理为普通上下文输入，或在需要进行模型侧工具结果回放时转换为 TinySoul tool result message。消息内容可以标注其来源、动作名称、参数、结果和状态，但 provider 原生 tool message 只存在于供应商适配层。
- TinySoul 内部应使用自己的 tool call id；供应商 tool call id 只作为适配层相关性信息保留，不应成为 Context、Action 或 Loop 模块依赖的主键。
- Action 模块向上层提供唯一装配与调用入口（组装门面），内部承担 Phase1 域作用域、Phase2 动作作用域与归一化、Phase3 批次执行；catalog、builder、runner、renderer 等组件保持为 ActionEngine 私有实现，不从门面暴露。每个模型侧 action tool call 在 Action 模块内恰好收敛为一个局部 ActionResult；无法归因到单个 call 的阶段性问题收敛为 phase-level result。Action 顶层包同时暴露业务模块实现 executor 所需的 `ActionExecution`、`ActionExecutionContext`、`ActionExecutor`、结果类型和模块错误公共 SPI；Workspace/Home/Loop 不直接依赖 `action.core`，但上层调用仍必须经过 ActionEngine 门面。Action hook 的普通拒绝、注册缺失和实现异常收敛为局部 ActionResult；hook success 只放行且不携带结果数据，hook reject 以 typed failure、可选业务 payload 和 observation-only frame data 对齐同一结果链路，pipeline 只补真实 hook identity。`RuntimeException` 与 `RuntimeTransferInterrupt` 已表达全局恢复或运行转移，normalize/execution hook pipeline 和并行 runner 必须原样传播，不得降级。并行执行发现 Runtime transfer 时立即请求取消同组 sibling；subprocess/supervised_process 通过取消回调终止进程树，native 在短暂 grace 内协作退出，不能协作退出的 native 不得继续阻塞 Runtime transfer。
- Action 后端分工：native 运行在宿主进程的 worker 线程中，只能协作式响应取消；owner-specific executor 直接构造 `ActionResult`，`ActionExecutionCancelled` 由 runner 统一收敛为 timeout，不提供 callable adapter 或 default native executor。`subprocess` 必须在当前 Action batch 内结束；`supervised_process` 可以在启动 Action 返回后保留 Turn-scoped job 并由后续 Cycle 监督。`tinysoul/action/backends/process.py` 是不注册到 ActionEngine 的 retained process/文件捕获/进程树终止原语；`subprocess.py` 在其上提供必须于当前 Action 收敛的 `ControlledProcessRunner`，不注册通用或 default executor；`tinysoul.capabilities.supervised_process` 复用同一原语，拥有共享 job manager，并只为 `execution.wait/stop/read_candidate/apply/discard` 提供通用生命周期 executor。Script 与 Shell 仍使用不同启动 handler、schema 和 policy，共用 `backend.kind=supervised_process`；旧 `backend.kind=script` 已删除且无 alias。`llm_action` 表示 action 内部受控 LLM task 的执行方式，共享能力由 `tinysoul/action/backends/llm_action.py` 提供；runner 从 owner deadline 预留 5 秒协作收尾，并在成功返回边界重新检查该窗口，内部到期只反馈普通 Action timeout；迟返的 Task failure 保留原失败事实。项目配置 `[action] llm_action_timeout_seconds`（默认 300）在 catalog 加载期填充未声明专用超时的 `llm_action` owner timeout；catalog 专用值覆盖通用默认（完整工件 write/rewrite/script 240s，`workspace.analyze` 180s）。完整工件 `workspace.write/rewrite` 与 `execution.write_script/rewrite_script` 由 Catalog 配置 180 秒 owner timeout，generation token 与工件字符上限仍是独立边界。TOML Action Catalog 位于 `tinysoul/action/catalog`，是随 wheel 发布的版本化只读 package resource；项目不配置 catalog path、不复制或覆盖内置定义。Catalog 只保存真实 domain/action；backend 的存在不等于向模型暴露任意 shell/script。Action 自有动作位于 `tinysoul/action/builtins`，业务模块或 capability 通过所属 `actions.py` 注册 handler，核心逻辑仍位于 engine/service/client/evaluator。`backend.kind` 表达通用执行方式，`backend.handler` 表达具体 executor 落点；共享 options 在 Catalog 加载期由 backend kind validator 校验，不为没有消费者的单个 handler 保留 validator 注册通道。Capability 的 enabled 配置与当前解释器依赖共同决定 effective Catalog：禁用 action 不检查依赖并移除，启用但缺依赖在 App 装配期失败。需要硬停止的 worker 使用固定入口、有界结构化请求和共用 managed process；每个 subprocess Action 必须由所属业务模块显式注册 executor，不能仅凭 backend kind 或 Catalog options 获得任意命令执行。
- Action 成功结果的 trace 生命周期由 Catalog `[runtime.result] trace_mode` 声明，只允许 `standard` 与 `foldable`。standard 结果不得返回 trace projection；foldable 结果必须由业务 executor 提供非空 `canonical_payload` 与有界、去重的 `origin_refs`，完整 payload 只作为当前 Turn visible overlay，canonical payload 是当前 Turn 可恢复 trace 中的紧凑业务投影。Context pressure recovery 可以移除 overlay；Catalog 只决定生命周期，不能从任意业务 JSON 自动猜测 canonical 字段；failed/timeout 结果不折叠。Turn completion 时 Session 从已校验 Action call/result 投影不可变业务事实，不持久化 Context trace 或 visible/canonical 消息。`core.context.inspect`、`core.session.inspect` 与 Workspace inspection 各自在所属 owner 边界形成可渐进展开的紧凑结果，并继续使用统一 ActionResult 生命周期。
- Resource conversion capability 通过 Workspace Domain 的 `workspace.convert_with_markitdown` 与 `workspace.convert_with_pypdf` 把 Workspace document 转换为 Markdown 和 sibling `.assets/`；Capability 不因 Action Domain 合并而改变配置、依赖或 handler 所有权。转换不调用 LLM、不做 OCR，也不把正文或二进制放入 ActionResult。图片/附件/PDF 页面只以 Workspace Link 交付，后续作为 reference 读取时才构造 ImagePart。source/output/page/asset count/asset bytes 上限是强失败边界，不能降级为 partial warning；worker staged output/manifest 不满足 host 协议时收敛为局部 `worker_protocol_invalid`。executor 在 source staging、worker 返回和 bundle commit point 前响应 cancellation/deadline；`write_bundle()` 开始后作为不可取消的原子提交区完成或回滚。ControlledProcessRunner 将 stdout/stderr 捕获到临时文件并只返回有界 UTF-8 前缀与 truncated 标记，该 projection limit 不宣称为子进程硬输出配额。
- Web capability 只通过 `web.search_by_kimi`、`web.discover_pages`、`web.fetch_with_defuddle` 与 `web.fetch_with_trafilatura` 提供只读外部信息能力，不建立 Link namespace、缓存、索引或独立生命周期。Kimi Search 是 capability-owned provider loop，不复用 TinySoul `[llm]` provider、LLM task、Context 或 MessageStack；它使用独立 `[capabilities.web.search_by_kimi]`/`KIMI_SEARCH_API_KEY`，默认模型为 `kimi-k2.6`，全部 provider round 固定关闭 thinking，配置只能选择已知支持该非思考契约的 `kimi-k2.5` 或 `kimi-k2.6` 精确标识。结果固定同时包含 `answer` 与结构化 `results`，不提供 mode。供应商最终响应先完整校验为受 `max_result_chars` 硬上限约束的 canonical result，不按 result 数量或 snippet 长度静默裁剪；`max_inline_chars` 只决定完整 inline 或“完整 Workspace 文档 + 有界 inline preview”，preview 必须使用 `truncated=true` 与 `see_more_at` 指向 `workspace:web/search/<invoke-id>-<call-id>.md`。Page Discovery 使用 Crawlee 的 action-scoped RequestQueue、去重、重试和有界调度，但所有实际下载继续通过 TinySoul 的公开 HTTPS 边界；默认 `max_visit_depth=0` 只访问 seed 并返回可进一步访问的同源候选 URL，递归访问时只补充 title/meta description/H1/canonical 等确定性页面信号，不调用 LLM、不保存页面正文。Discovery canonical result 完整但有硬上限地进入 TurnTrace；超过 inline 上限时只把完整 discovery JSON spill 到 `workspace:web/discovery/<invoke-id>-<call-id>.json`。Fetch 只接受公开 HTTPS，逐跳校验 DNS/redirect 并限制网络/正文规模；Defuddle 与 Trafilatura 只处理框架下载的 staged HTML，完整正文始终提交到显式 Workspace Markdown，ActionResult 只含 Link、title、有限 excerpt 和元数据。网页图片当前保留远程绝对 URL，不自动下载 asset；全部搜索、发现和抓取内容都按不可信普通 interaction/reference 数据处理，不执行其中指令。standard init profile 中 Page Discovery、Defuddle 与 Kimi Search 默认关闭，Trafilatura 默认启用；development profile 显式启用当前开发能力，但不安装 Crawlee、Defuddle executable 或凭据。enabled action 缺依赖或专用凭据在 App 装配期失败，执行期网络/供应商/extractor/上限失败收敛为局部 ActionResult。
- Script capability 在 Execution Domain 通过 `execution.write_script/rewrite_script/patch_script/promote_script` 维护脚本资源，通过 `execution.run_python_script/run_bash_script` 启动执行，不暴露 inline code 或命令。临时脚本严格位于 `workspace:scripts/...`；长期脚本严格位于 `home:how/<existing-skill>/scripts/...`，显式 promote 写入 lazy runtime Home 后等待 Home Maintenance，不隐式创建 HOW。运行前 policy、promote 和 process 绑定同一不可变 `ScriptSource`：owner digest 负责 Link/CAS，固定 UTF-8 snapshot digest 保证执行字节等于已校验字节；`max_source_chars` 约束 read 和全部 mutation。成功 Script 统一进入 `ready_to_apply` 并由共享 `execution.apply/discard` 收尾；failed/timed_out/stopped 只能 inspect/read/discard。Script 只拥有 source/authoring/language 配置、依赖、启动 handler 和局部业务失败，监督生命周期由共享 manager 与 lifecycle executor 拥有。
- Supervised Process / Shell：`tinysoul.capabilities.supervised_process` 是 capability-internal、非模型 domain 的 Turn-scoped execution manager；同一 Turn 跨 Script/Shell 最多一个 unresolved job。启动时记录实际 owner，后续 `execution.wait/stop/read_candidate/apply/discard` 只接收 execution id 并由 Manager 在当前 Turn 内解析 owner，不让模型预判 job 来自 Script 还是 Shell。共享层拥有 lifecycle executor、pacing、runtime/log/mirror/candidate 上限、最小环境、Signal wait、额外 Cycle、answer guard 和 cleanup；实际 mirror/diff/CAS/bundle mutation仍由 Workspace 拥有。job staging 固定为 `runtime/.staging/supervised-process-job-*`，日志和未提交候选不建立 Link、不进入 Workspace/Session/Home/Memory/archive；job 不持久化、不跨 Turn/重启。模型 wait 的绝对范围为 15 至 60 秒，effective Action Schema 投影项目实际 minimum/default/maximum；无显式 wait 时 running job 使用 15 秒 Cycle 防空转间隔，显式 wait 正常到期后不叠加自动等待。进程完成或当前 Turn 中协议有效的 input/control Signal 可以提前唤醒；job observation 只向 TurnTrace 投影 wake、实际等待、剩余运行时间和日志/候选 observed activity，不解释业务进度。普通预算耗尽后任一 unresolved job 都可申请有界监督/收尾 Cycle，每个 Cycle 仍从 Phase1 开始。Cycle pacing 与额外 Cycle 判断等共享 non-Action activity failure 归 `supervised_process` Runtime bridge；Turn 离开时在 `finally` 中独立尝试回收 watcher/process/staging，cleanup 错误在全部回收尝试结束后聚合并由 Loop 形成 Observation，不能替换原始异常或 transfer。
- Shell capability 在 Execution Domain 提供 `execution.run_powershell`、`execution.run_cmd` 与可选 `execution.run_bash_command`，只接受有界 inline `command` 和 mirror 内相对 `working_directory`；模型不能指定 executable/flags/env/stdin，不提供 PTY、交互 stdin、跨重启 job 或长期 `.ps1`/`.cmd`。PowerShell、Cmd、Bash 分别使用框架固定 argv，宿主始终 `shell=False`。成功且无 mirror diff 时自动完成并清理；成功且有 diff 时由共享 lifecycle 显式 apply/discard；失败/超时/停止时 retained 供 read/discard。Workspace mirror 只保护 TinySoul 提交边界，不能阻止宿主绝对路径、网络、环境或子进程副作用，也不能回滚 mirror 外影响，因此不宣称硬沙箱；首版依靠项目显式 enabled，不增加逐命令 approval 或关键字 denylist。standard init profile 关闭整个 Shell capability；development profile 启用 PowerShell/Cmd、关闭 Bash。只有 Execution Domain 内全部有效 Action 都被禁用时才移除该 domain 和 `home/how_domain/execution/DOMAIN.md` mount。
- Context 模块向上层提供唯一装配与调用入口（组装门面），持有本轮 UserInputs、Context-owned Background、WorkingContext 与 TurnTraceHeap，负责构造式 MessageStack、语境控制工具与压力回收服务。Background 通过通用 provider 协议聚合 Home 顶层条目、昨日 Memory 与 Session 历史，不归 Home 或 Memory 任一模块所有。provider catalog 可额外交付属于自己的有界 Link/title/description 目录；Context 在每 Turn 自动将其渲染为 `background:catalog:<owner>` JSON user message，它不是已加载正文 Link，且不可由 Phase1 逐出。Home 使用该机制自动交付全部通用 HOW metadata，Phase1 再通过支持一次加载多个 Top Link 的 `load_background` 内部 control tool 按需加载当前 Context 已暴露的顶层正文；工具参数不枚举或泄漏完整 effective top catalog，Context 在提交前依据内部 provider catalog 校验开放字符串 Link。MessageStack 构造顺序为 system identity、UserInputs、SessionBackground、通用 Phase1 Background、TurnTraceHeap、WorkingContext、task prompt overlay；除 identity 使用 system role 外，其余用户态语境和 TaskPrompt 均使用 user role messages。Trace 正常增长是 append-only，Working 则是原位替换的当前快照；模型侧 Working 只呈现 milestones、todos 与 Workspace resource Links/summary，Trace heap 自动 header 与 `core.context.inspect` 的 head 呈现同一组语义导航事实。Context 不维护独立 Trace anchor、canonical revision 或持久 trace digest；canonical entries、不可变 heap node和 sealed completion snapshot 分别承担本轮记录、压力回收与 Session 提交输入。Workspace manifest revision 仍由 Workspace/Context 内部同步协议使用，不进入模型 Working 投影。ContextEngine 不向上层暴露 heap node 等可变状态持有者；语境变更只有作用域化信号的事务批次提交与 Turn 生命周期两类入口。TurnTraceHeap 只在当前 Turn 内保存可恢复 trace，`core.context.inspect` 通过 head/branch/leaf ref 和 opaque `continuation` 渐进展开；inspect 结果使用 foldable projection，后续压力回收折叠回 origin ref。Turn 结束时 `ContextTurnCompletion` 只向 Session 交付输入、输出状态和已封存 trace entries，不定义持久 Session 结构。
- Context 信号协议：context.working.patch、context.workspace.sync、context.session.sync、context.background.patch、context.trace.append、context.input.append，均为 JSON 安全载荷并按命名空间消费。Context 先从 SignalBus 捕获绑定当前 Turn id 的可重放批次，再解析、校验 Turn scope、投影 Working/Background/Workspace 变更并准备全部懒加载背景，最后提交可行变更；Home 缺页或压缩陷入发生在提交前，由 Module runner 重试同一批次，不丢信号也不留下半提交。Loop 通过 `ContextSignalConsumer.emit_and_consume` 将同一逻辑步骤产生的 decision、action results 或 phase notes 成组发送并作为一个批次提交，不逐条破坏事务边界。`context.session.sync` 是 Session 独占且仅在 Turn preparation 接受的版本化全量历史头部；`context.workspace.sync` 是 Workspace 独占的 `{revision, resources}` 全量替换协议；普通 Working patch 只管理 milestone/todo。input append 与 loop control 必须携带当前 Turn frame，旧 Turn 信号不能写入新 Turn。Context 不再设置静态文本字符上限；LLM 依据模型必填窗口和 `compression_trigger_ratio` 检查完整请求，压力恢复按 `compression_target_ratio` 把 token 缺口投影为字符回收量。Composer 仍统计各 section 字符并执行内联图片总字节硬限制。Trap 压缩处理器在 Module frame 可用时优先重试 Module，否则重试 Phase；action-internal LLM task 会在容量异常 payload 中携带当前 target/reference links，Workspace 压力清理不得移动这些活动资源。
- Loop 根只拥有可复用的 Turn/Cycle/Phase 运行内核、通用 assembly/pipeline/protocol，不拥有 Program、请求队列、scheduler、每日生命周期或 Maintenance 类型。`assembly.py` 组合 owner-neutral kernel，`turn.py` 负责通用 Turn runner，`cycle.py`/`phases.py` 负责共用 3-stage 内核；`loop.user` 组合 User Context/Action/preparation/completion/runtime policy 并对 App 暴露轻量 `UserTurnEntry`，Maintenance profile 全部归 `tinysoul.maintenance.turn`。Phase 只组合 ContextEngine、ActionEngine 与 LLMTaskRunner，不复制三者内部语义。Phase1 重试耗尽不抛 turn 级异常：返回空 domain 选择与 phase note，无有效 domain 时先消费有效控制调用再带反馈重试；Cycle 可进入下一轮，TurnRunner 连续 Phase1 选择失败达有界次数（默认 3）才收敛为 Turn failed。两类 Turn 都在开始时捕获一个权威 `BusinessDay` 并在该 Turn 内保持不变；指向当前 Turn 的 RETRY 只重放 preparation，不重复 begin Turn。User Turn 的 `UserAnswerCompletionDetector` 直接把唯一成功的 `core.answer` 转换为 completion 和用户输出，并由 Session completion 持久化 sealed schema v4 Turn。Maintenance Turn 不产生用户回答或写入 User Session，只由 `maintenance.complete` 和 task owner 后置条件结束；Maintenance-owned typed entry 负责展开指向外层 Program 的 Runtime transfer，task 不直接解释通用 TurnOutcome。
- Maintenance 模块拥有业务时钟、确定性日切、archive catalog、到期计算、持久 availability 和 Archive/Home/Memory 任务编排，不建立 `MaintenancePlan`。Archive 以 `.pending-*` journal 按 Session、Workspace/Trash 顺序归档旧日，在旧日 roots 移出 active runtime 后初始化同一新日 roots，最终形成不含 Home 的 `archive/<timestamp>/`，并原子维护按 BusinessDay 定位的 `archive/catalog.json`；进程级中断通过 persisted facts 幂等前滚。Home 不参与 active day claim、daily archive 或新日初始化。Archive 只向其它维护任务提供按 Business Day 定位的只读 Session/Workspace roots；Session 与 Workspace 各自校验和解释内部事实，Maintenance 不读取它们的私有 store。Home/Memory 需要模型推理时调用独立 Maintenance Turn，不把推理塞进 Archive 流程。
- App 模块是 TinySoul 的进程 composition、顶层 Program、项目初始化和外部输入边界层。`app.program` 拥有串行请求队列与 Program frame，只分派 `UserTurnRequest`、`MaintenanceRequest` 和 `ExitRequest`；`app.sources` 中的 Terminal、Endpoint adapter 与 scheduler 都只进入这一边界。外部 `InputEvent` 由 InputCommandParser 纯解析，InputDispatcher 基于一次 active Turn scope 快照将普通输入变为新 User Turn 或当前 Turn append/control，并始终将 Maintenance 命令变为 Program queue 中的 MaintenanceRequest。TinySoulAppBuilder 显式加载配置环境并构建进程级 LLM、Workspace、Session、Home、Memory、SignalBus 与服务，然后分别调用 `UserTurnBuilder` 和 `MaintenanceBuilder`；它不导入或构造 Phase1/2/3、Cycle、ContextSignalConsumer、Maintenance controller/task 或两类 Turn trap。Program 使用独立的 Program-only trap。App 的测试 override API 使用显式 `with_user_*` 命名，不保留旧 alias。`tinysoul start` 是唯一交互运行入口，同一 App 同时拥有 Terminal 与 Endpoint；`--mode` 只控制 Console route，Endpoint route 固定为 model。`tinysoul/assets/project` 是唯一 init/reset 模板源；AppCommandGateway 只统一可信命令输入，输出统一经 ObservationEmitter/Router 分发。
- 项目模板维护只允许修改 `tinysoul/assets/project`，不得在仓库根重建 `configs/`、`home/`、`tinysoul.toml` 或 `.env.example` 镜像。默认 Home 文档只在共享 `project/home/` 中维护；新增、重命名或删除配置片段时，standard/development 必须保持相同相对 TOML 文件集合和可独立初始化的完整性，只有安全开关、provider 选择、模型顺序等已说明的 profile 值可以不同。standard 保持 provider disabled 与 host-sensitive capability 安全默认值；development 保存维护者当前启用但不含凭据的配置。每套 `.env.example` 必须覆盖该 profile 引用的环境变量名且不得含真实值。新增资源层级或扩展名时同步检查 `pyproject.toml` package-data；完成后至少验证两种 initializer 输出、reset 的清空/.env 保留/故障恢复/lease 拒绝、共享 Home、config 文件形状和 wheel 隔离安装。已生成项目归用户所有，不从模板反向同步，也不得作为模板事实源。
- Endpoint 模块是本地桌面前端的外部协议适配层，只允许 loopback bind，并以进程级 bearer token 鉴权 HTTP、以首帧 token 鉴权 WebSocket。它只随 `tinysoul start` 接入同一个 ProgramRunner/InputDispatcher、MaintenanceEngine 和 WorkspaceEngine；Endpoint 不直接持有 SessionEngine，不拥有进程退出权、业务状态或持久目录。ObservationRouter 为 Console 与 Endpoint sink 保留独立上限，Endpoint event buffer 固定接收 normal/verbose/model 全部事件；内存 deque 作热缓存，`runtime/endpoint/events/` 分段 NDJSON Journal 提供有界持久深读与进程重启后续号，`/v1/events` 协议不变，超出 journal 保留范围才 `gap=true`，journal 写失败降级为仅内存且不反向影响业务。阻塞 HTTP handler 使用同步 `def` 由 FastAPI 线程池执行，避免冻结 ASGI 事件循环；`/v1/health` 与 WebSocket 帧路径保持异步。active-day lease 为共享读 / 日切独占写，User Turn 与 Endpoint 可并发持读。`stop_turn`/`exit_program` 经 Gateway 发出控制信号的同时置位 Turn 取消令牌，加速放弃在途 LLM 等待（孤儿结果丢弃）；SignalBus 在 Phase 边界的消费仍是权威控制流。Endpoint 暴露结构化普通输入、control、Daily/Home/Memory Maintenance request、Maintenance availability 和 Workspace API，全部进入同一 AppCommandGateway 或 owner 门面；不存在 Maintenance decision/approval API 或 pending-blocking 状态。Workspace 请求持有 active-day 读 lease，UI mutation 在同一 WorkspaceEngine 锁内校验 revision/digest，成功后在活跃 Turn 发布 full snapshot。Endpoint 不提供 Session/Context 审计 REST；前端从真实 `llm.model.request` MessageStack 观察实际进入模型的 Session/Context 信息。Endpoint request failure 是稳定 HTTP 局部结果，服务启动失败经 RuntimeEndpointBridge 映射为 startup failure；FastAPI/Uvicorn/WebSockets 是 `tinysoul start` 所需的核心运行依赖，ASGI adapter 仍只在 EndpointHost 启动时延迟导入。
- Workspace 模块负责 `workspace:` 链接、`runtime/workspace` 当日工作区根目录、schema v3 Manifest、磁盘 reconciliation、扫描诊断、临时 task prompt 输入、文件变更 action、可恢复 Trash、日归档 participant 和归档只读 manifest projection。Manifest 持有显式 business day；磁盘是内容事实源，Manifest 是版本化索引与语义描述层，WorkingContext workspace 段是当前 Turn 的同 revision 投影。`WorkspaceReconciler` 只在完整扫描后提交，description 与当前 digest 绑定。Workspace 为本地转换能力提供受 kind/bytes/digest 约束的 document read，以及在同一 Engine 锁内预检、写入、完整 reconcile、单 revision 返回并在失败时恢复原字节与 Manifest 的 bundle mutation；成功 executor 只能在 bundle 提交后发布一次同 revision `context.workspace.sync`。Trash 固定位于 active root 的 `.tinysoul/trash`、被扫描忽略且不进入资源 Manifest；活动日内 `workspace.trash.list`/`workspace.restore` 提供恢复，日切时 Trash 被提取到独立 `trash/`。压力回收只移动未被当前 action target/reference links 保护的 ephemeral/turn 资源。Workspace 的一致性等级是单进程单写者、同一 Engine 实例内线性化；跨模块归档调度归 Maintenance Archive，Workspace 门面只负责自身 reconcile、workspace/trash 移动和 archive projection。
- Workspace inspection 是核心定义中“文件内容通常不应进入 Context”的明确窄化例外：禁止隐式、自动或无界整文件读取，但允许显式有界范围偶然覆盖很短的完整文件。`workspace.read` 只接受一个明确 UTF-8 text Link、1-based 闭区间和可选 cursor/max chars/expected digest；`workspace.search_text` 只做有界单行字面量搜索，scope 必须显式为单文件、目录 prefix 或整个 Workspace，返回带 Link/digest/行范围的 fragments 和预算不足后的 line hints，并分别报告 result truncation 与 scan coverage。两者只读、不发布 Workspace snapshot，正文使用 foldable ActionResult。`workspace.analyze` 只接受 Phase2 已选择的非空去重 text `reference_links` 与 intent，不接受目录或 Workspace scope，不在 Phase3 重新选择资源；references 必须完整且在单文件/总 source budget 内，否则不调用 LLM并局部失败。成功时只执行一次禁用工具的 action-internal LLM task，返回有界 answer 与经验证的来源定位，使用 standard trace，不修改 Workspace，原始 references 不进入 ActionResult。
- Agent Home 模块负责 `home:` 链接、顶层背景目录、渐进式资源、domain/action HOW、通用 HOW 的 `SKILL_MEMORY.md` 和跨日可写 overlay。actual 内容严格位于 `home/` 且普通 User Turn 与确定性日切都只读；runtime overlay 严格位于 `runtime/home/`。Home 内容在 User Turn 首次实际读取时通过 `HOME_RUNTIME_COPY_REQUIRED` Trap 透明物化；Maintenance Turn 不注册该 handler，并使用 Maintenance-owned `ActualHomeBackgroundEntryProvider` 读取 actual Home。Home owner 的中性能力位于 `home.review`：`HomeReviewService`、`review_pending()`、`review_snapshot()`、`resolve_review()` 与 `remove_resolved_overlay()` 只从 active overlay/current actual 构造 review 并执行单项 mutation，不拥有 Maintenance task、LLM reviewer、时钟、scheduler、stdin 或审批状态。copied/consistent record 确定性清理；普通 diff 的 accept/rewrite 原子替换，reject 保留 actual；`SKILL_MEMORY.md` 只有 inspect 后才能 reject/rewrite。全部 pending 解决后移除空 runtime Home；actual 写后清理前中断时，下次通过 runtime/actual 一致性自动收束。
- Memory 模块负责 `memory:YYYY-MM-DD` Link、默认位于项目顶层的 `memory/yyyy/mm/yyyy-mm-dd.md` 存储、有界 search/recall、昨日 Background provider和 owner-neutral consolidation。Memory 只读地消费 Session facts projection，通过注入的 Home 顶层 Link catalog 校验 `<home:...>`，不读取 Home overlay。Memory 没有 runtime overlay 或普通 mutation action；写入能力位于 `memory.consolidation`，公开 `MemoryConsolidationService`、`consolidation_eligible()` 与 `consolidate()`，使用 `[memory.consolidation]` 预算和 `memory_consolidation` LLM profile，且不知道 scheduler/request/Maintenance Turn。Maintenance 模块通过这些门面完成指定日期的原子完整重写。`memory.search` 与 `memory.recall` 仍只读并进入 TurnTrace；Home 不接受 Memory space、旧 Link 或旧路径。

- Action 局部失败的唯一事实源是 typed `ActionLocalFailure(reason, scope, disposition, feedback, constraint)`。success 禁止 failure，failed/timeout 必须携带 failure；业务 payload 不承载 `payload.failure`，`ActionResult`、envelope、foldable projection 和 HookOutcome 都必须在构造边界拒绝该保留字段，frame data 不重复失败语义。普通 hook 拒绝通过 `HookOutcome.failure` 直接交付该事实，可选 payload 交付模型所需业务数据，可选 frame data 仅进入 trace/Observation；hook success 为空且不生成额外 ActionResult，pipeline 只补 hook identity，注册缺失或实现异常由 pipeline 构造自己的 typed failure。`ActionResultRenderer` 只是 Action-owned 投影边界，统一生成 model/trace 及 visible/canonical ToolResult envelope，不推断事实。foldable canonical result 保留 `action/status/stage/failure` 包络，只替换业务 `canonical_payload`。
- Context 与 Session 的模型侧渐进探索统一使用 `ref`、可选 opaque `continuation` 和 `next_continuation`，但各自保持 heap 导航而不是扁平连续读取。Context 的 head/branch/leaf 与压缩堆同源，只恢复当前 Turn；Session 的 root/Summary/Turn/Action collection/Action leaf 从 schema v4 record 确定性派生，只恢复已提交历史。continuation 只是在同一语义节点超预算时继续，不替代 ref、不暴露位置/revision/digest；错误 token、内容或 root 变化会稳定失效。`core.context.inspect` 与 `core.session.inspect` 都是不调用 LLM 的 core domain foldable Action；最小使用边界只由 Core Catalog 的 domain description、selection hint 和 action semantic 表达，不建立 Core/Context/Session Domain HOW 或 inspect Action HOW。Working model tools 固定为 `set_milestone`、`remove_milestone`、`set_todo`、`remove_todo`，每次调用表达一个非空完整操作，多调用按 sequence 投影验证后原子消费；不保留 `update_working` alias。
- Session schema v4 只持久化不可变业务事实：输入、输出、逐 Action 的名称/request/outcome/result或 typed failure/references，以及 Summary 的 direct child refs；Manifest v2 只持有 authoritative root refs。Session-owned completion validator 在提交边界唯一负责 call/result 配对、名称/status/failure 一致性和业务投影；Session reconciliation 只校验记录与可达图，不从 trace 重建第二套事实。旧 schema v3 不兼容、可直接清除。Session Background、`core.session.inspect` 和 Memory facts 全部从同一已验证记录派生：Background 是 Turn preparation 注入的固定不可逐出历史段，超预算时沿 immutable Summary 堆递归收缩，Turn 项只呈现 ask/answer/references/exhausted 与按 action 名聚合的非零 success/failed/timeout counts；inspect 从 root 到 Summary、Turn、Action collection、Action leaf 渐进展开，失败 leaf 可直接给出有界 failure/result。inspect 结果只进入当前 Turn Interaction，不改写固定 Background。Session 不提供独立 actions/recall Action、不保存 canonical trace/action history/digest/revision，也不向 Endpoint 提供专用历史协议。
- Workspace write/rewrite 的 prompt source、版本证明和提交 read set 全归 Workspace 所有。Engine 在一次锁内读取 target/references，LLM 在锁外执行，提交时在一次锁内验证 target 仍为相同 digest或仍 absent、全部 references 仍 present 且 digest 相同；任一变化以 `source_changed` 局部 Action failure 拒绝提交。instruction 中出现的 Link 只是文本，所有生成依赖必须显式进入 `reference_links`。

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

### 已完成基础

- Runtime、LLM、Action、Context、Loop、App 已形成完整 User Turn、Agent Cycle、Phase、Action、Trap 和 Program 生命周期；provider、tool protocol、context window、deadline、失败 scope/disposition 与输出完整性边界已经闭环。
- Session、Workspace、Agent Home、Memory 与 Daily Lifecycle 已拥有各自持久化、Link、投影、Maintenance、reconciliation 和失败语义；Workspace 保持单进程单写者、Engine 实例内线性化，并通过 revision/digest CAS、Trash 和 transaction mirror 管理变更。
- Resource、Web、Script、Shared Supervised Process 与 Shell capability 已完成，Action Catalog、HOW、配置裁剪、事务提交和 Turn cleanup 均接入正式 AppBuilder。
- `tinysoul start`、项目单实例连接描述、AppCommandGateway、ObservationRouter、authenticated Endpoint 和 `visualization/` Tauri/React 前端已经形成 Terminal-owned 后端与纯连接前端的统一应用链路。历史实现与验收保存在 `docs/analysis/*-done-*.md`，不再在本节重复维护逐阶段日志。
- Action hook reject 已对齐 failure/payload/frame_data 三通道，测试不依赖本地真实运行记录。完整工件 `workspace.write/rewrite` 与 `execution.write_script/rewrite_script` 使用 180 秒 Catalog owner timeout，`LLMActionTaskRunner` 为协作收尾预留 5 秒并在成功返回边界重检；Context 已删除无消费者的 Trace anchor/canonical revision。完成记录见 `docs/analysis/20260724-done-session record integrity and hook outcome boundary correction plan.md` 与 `docs/analysis/20260725-done-action authoring deadline and model context transparency execution plan.md`。
- Context 与 Session 的渐进探索已统一收敛为 core domain 的 `core.context.inspect` / `core.session.inspect`，模型侧只使用 heap ref 和 opaque continuation。Session schema v4 仅保存不可变业务事实，Background、inspect 和 Memory facts 从同一 record 派生；旧 history/actions/recall、canonical trace、Context/Session Domain HOW、Endpoint Session REST 与前端 Session Explorer 已删除，前端只通过真实 MessageStack 观察模型上下文。完成记录见 `docs/analysis/20260725-done-context session semantic heap and application surface refactor plan.md`。
- Maintenance Availability、Archive 日期索引与 User/Maintenance Turn 边界已完成收敛：启动先完成 Archive 和唯一提示单，Memory 日期列表增量跨重启保留，Home pending 每次从 owner 重算；启动前端提示一个聚合 Home 任务和全部 Memory 日期，Daily 只自动处理昨日 Memory，更早日期由明确目标 request 精确执行。Endpoint/前端只通过 GET 提示单和失效事件协同。完成记录见 `docs/analysis/20260804-done-maintenance availability and boundary cleanup execution plan.md`。
- User/Maintenance Turn 所有权与 App 装配已完成收敛：`loop` 根只保留 owner-neutral kernel，`loop.user` 和 `maintenance` 分别拥有两类 Turn 入口与 runtime policy；Maintenance catalog、Context、Prompt、completion 和 bridge 已内聚到 Maintenance，Home/Memory 对外能力改为中性的 Review/Consolidation，App 只调用两个轻量 builder。完成记录见 `docs/analysis/20260804-done-maintenance turn ownership and app assembly refactor execution plan.md`。

### 当前目标

构建可持续使用的 TinySoul 桌面应用，围绕真实用户工作流优化前后端协作、运行可靠性和交互质量。


### 推进顺序

当前实施进度可参照 docs\analysis 中的执行计划；已完成计划标记为 done；有含糊不明确的决策点/待确认的设计语义即时与用户讨论确认；即时将确认的设计语义，实施前明确的执行事项写入执行计划；即时维护执行计划，保持有限活跃的执行计划与计划更新

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
