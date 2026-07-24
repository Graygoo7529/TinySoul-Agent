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

LLM Task/Call “构造式” MessageStack：LLM Task/Call 的主要输入为 MessageStack。MessageStack 可以分为多个区段，分别由上层不同模块提供语境（Context）或附加任务提示（task prompt），并在实际 LLM Task 前“构造”为完整的 MessageStack。当前构造顺序为 system identity、UserInputs、BackgroundContext、TurnTraceContext、WorkingContext、task prompt overlay；除 identity 使用 system role 外，其余用户态语境段和 task prompt 均作为 user role messages 提供给模型。TurnTrace 在前表达本轮按发生顺序积累的行为轨迹，Working 在后表达当前物化状态；Working 模型消息通过 `as_of_trace` 绑定同次组装观察到的 canonical Trace head/revision，但不宣称全部 Working 变化都由 Trace 产生。

除了上述语境，task prompt 由 TaskPrompt 表达，并由可切分的 PromptBlock 组成；其稳定语义分为任务引导、任务输入和期望输出三组，当前实现分别以 guide_blocks、input_blocks、output_blocks 承载，并可渲染为多条 user role message。例如，Phase1、Phase2 会说明当前处于执行轮/Agent Cycle 的哪一个阶段、可用输入和期望输出；Phase2 会自动注入 domain HOW 作为 guide block；Phase3 Action 内部嵌套的 LLM Task 可同时自动注入 domain HOW 与 action HOW；这不同于通用 HOW 和普通渐进式加载，`how_domain`/`how_action` 是框架的局部自动挂载机制，分别作用于 domain（Phase2，并可延续到 Phase3 内部 LLM task）和 domain 内 action（Phase3 内部 LLM task）。通用 LLM action 使用 `reference_links` 解析只读资源；workspace LLM action 使用 `target_link` 与 `reference_links`，并在 action 内部局部读取目标和参考正文。“构造式”表示为每次 LLM Task 制定不同的 MessageStack，并在上层维护通用语境，在 Task 完成后对语境进行反馈和修改。

工作区/WorkSpace：每日会话为 Agent 维护一个专用的、可操作的本地路径，Agent 可以在其中操作文件和执行脚本。WorkSpace 内资源在语境中有专属的链接/Link 标识（例如 workspace:doc/doc.md），并使用相对路径读取资源。WorkSpace 有一个专用描述文件，用于记录工作区结构和其中各文件摘要，并可在用户轮开始时映射到 WorkingContext 语境中，同时采用约定的目录结构和命名风格。工作区中文件读取具有特定约定：文件内容（如文档、脚本、图片）通常不应出现在语境/Context 中，也就是说，行动/工具执行结果不应返回实际内容并记录到 TurnTraceContext；Context（工具的输入和输出）仅记录相关资源的链接/Link。例如需要修改的文档，或可以作为参考的相关文档、图片等，只在 Phase3 具体 action 执行期读取；Phase2/Phase3 边界只传递链接语义：只读资料使用 `reference_links`，工作区操作目标使用 `target_link`；需要 LLM 的 workspace action 在 Phase3 action 内部把 `target_link`/`reference_links` 局部解析为临时 task prompt input block。真正的文件变更仍由 workspace.write/patch/delete/rewrite 等变更 action 通过 `target_link` 表达。

Agent Home 与链接/Link：Agent Home 存储 Agent 的持久身份规约、用户偏好、知识与技能；长期日期记忆属于独立 Memory 模块，不属于 Agent Home。Agent Home 主要以 Markdown 文档组织，分为顶层内容和渐进式内容。顶层内容默认或逐步（通过 Phase1）加载到 BackgroundContext，顶层内容通过特殊链接（例如使用 @ 而非 /）标识；渐进式内容不放在 BackgroundContext 中，主要通过行为/工具以工具结果返回到 TurnTraceContext 中。以下分别描述 Agent Home 的内容形式、运行位置与链接：

（1）AGENT.md 是顶层内容，类似一本参考全书目录，记录 AGENT 所具有的整体规范、行为设定、核心规则、用户偏好等。运行时 core 使用 `home:agent@AGENT`，其它 Agent 顶层内容使用相对于 `home/agent/` 的无后缀逻辑路径，例如 `home:agent@user/user`；Layout 将其确定性映射到对应 `.md` 文件。在 user.md 中可以进一步链接渐进式内容。`home:*@...` 只表示该 Link 是可进入 BackgroundContext 的顶层内容，不等于自动加载；Home provider 每个 User Turn 必须自动加载不可逐出的 core，并对 explicit allowlist 中 effective 存在的 `home:agent@context/background`、`home:agent@context/turn-trace`、`home:agent@context/working` 与 `home:agent@user/user` 自动加载不可逐出的正文；其它 Agent/WHAT/WHY/通用 HOW 顶层内容按需加载；

（2）WHAT 是一个 Knowledge 库，用于标注（a）实体（b）领域概念。WHAT Link 显式包含分类和相对于 `home/what/` 的无后缀逻辑路径，例如 `home:what@entity/tiny-soul`、`home:what@concept/daily-lifecycle`，分别映射同路径 `.md` 文件；因此 entity 与 concept 中的同名文件仍是不同顶层对象，新 WHAT 的分类无需再由 Link 之外的平行参数表达。WHAT 文档记录定义和关联内容，可通过语义匹配 top-k 交付语境模块，也可通过未来的 backlink 能力反向查询引用该 Link 的其它 Home 内容；WHAT 不应有时间戳，只记录当前认为正确且重要的内容；

（3）WHY 是另一个 Knowledge 库，用于标注问题的原因和解答。WHY Link 使用相对于 `home/why/` 的无后缀逻辑路径，名称应直接表达问题，例如 `home:why@why-is-updating-home-important`，并映射同路径 `.md` 文件；WHY 文档是顶层内容，并可通过语义匹配 top-k 交付语境模块；

（4）HOW 是另一个 Knowledge 库，它是当前智能体设计中 Skill 的变种，在语境中通过 `home:how@skill_name` 标识。该 Link 是保留的框架 skill identity，映射 `how/<skill_name>/SKILL.md`，不伪装为普通文件路径；HOW 渐进资源则保留真实相对路径和扩展名，如 `home:how/skill_name/references/ref.md`、`home:how/skill_name/scripts/script.py`。每个通用 `SKILL.md` 必须使用 YAML `---` frontmatter，且 frontmatter 只包含非空、单行、有界的 `title` 与 `description`；Home 在启动/reconcile、runtime 恢复和 top write/patch 边界统一严格解析。每个 User Turn preparation 都从 effective Home 动态扫描全部通用 HOW，把 Link/title/description 作为 Context-owned、不可逐出的自动 Background catalog 交给 Phase1，使 Phase1 知道可通过内部 `load_background` control tool 加载哪个顶层 HOW 正文；catalog 不是一个伪造的 Home 顶层文件，正文仍按需加载。完整 metadata catalog 受总字符上限约束，超限时显式失败，不截断 description 或丢弃 skill；runtime create/modify/delete 在后续 Turn 的 effective catalog 中反映。通用 HOW 的 runtime 包额外包含 `SKILL_MEMORY.md`：它只存在于 `runtime/home/how/<skill_name>/`，记录自上次 Home Maintenance 以来该 skill 的临时工作记忆、使用反馈和待 review 变更，供后续 User Turn 与 Home Maintenance review 使用；它不属于 actual Home，对应 skill 的 Home Maintenance review 完成后必须清空。除了通用 HOW，还有两类与行动域绑定的自动 HOW：`how_domain` 作用于 domain，使用 `home:how_domain:<domain>` 在 Phase2 自动注入，并可在 Phase3 的 action 内部 LLM task 中继续作为 domain 约束；`how_action` 作用于 domain 内具体 action，使用 `home:how_action:<domain>/<action>` 在 Phase3 中带内部 LLM task 的 action 自动注入。这两类 Link 同样是保留的框架 mount identity，不附加物理 `DOMAIN.md`/`.md` 文件名。`how_domain` 与 `how_action` 不参与通用 HOW metadata catalog 或普通渐进式加载，也不由模型通过 `home.resource.read` 主动读取；它们可以透明物化到 runtime，并通过专用 prompt mount mutation action 修改。逻辑 mount 的创建和删除由框架根据 Action Catalog 中的 domain/action 自动维护，模型不负责 create/delete；它们不创建 `SKILL_MEMORY.md`、`DOMAIN_MEMORY.md` 或其它平行 memory 文件；

长期记忆/Memory 与链接/Link：Memory 是与 Agent Home 平级的独立持久模块。每个被提炼的 Business Day 对应一个 `memory/yyyy/mm/yyyy-mm-dd.md` 日志，并使用无格式后缀的日期逻辑身份 `memory:YYYY-MM-DD` 标识；Memory 模块将其确定性映射到物理年月 Markdown 路径，二者不能由其它模块自行拼接。Memory 在普通 User Turn 中只读，不建立 runtime copy、不参与 Home runtime diff，也不通过 Home action 修改。`<memory:YYYY-MM-DD>` 可出现在 Context 和 MEMORY 正文中，表示应通过 Memory recall 加载指定日期，不表示内联正文或 Home 顶层内容。

每个 User Turn 的 preparation 都按同一 Business Day 与业务时区确定“昨日”；若精确的昨日 MEMORY 存在，Memory provider 将完整但受文档上限约束的正文作为自动 Background entry 交给 Context。缺失昨日 MEMORY 是正常状态，不回退到更早日期；文件存在但不是非空、可读、上限内的 UTF-8 文本时是 Memory 模块失败。该 entry 每 Turn 重建，在 Context 压力回收时可被逐出；Home core 与 effective 存在时自动加载的 allowlisted Context/user Agent Top 正文仍是不可逐出的默认规约。其它日期 MEMORY 不进入可加载 Home 目录，只能通过 `memory.search(query, top_k)` 与 `memory.recall(memory_link)` 按需访问；search 以单日文档为候选，只返回稳定 Link、日期和有界摘要，recall 返回完整但受上限约束的单日 Markdown，两者的 ActionResult 都进入当前 TurnTraceContext，不修改 Background。

Memory Maintenance 读取 Session 为指定日期提供的专用 facts projection：Session 按需递归已提交 Summary 图，只交付唯一、可达并按 Turn 开始时间稳定排序的事实，不暴露 store 或 archive 文件结构。单日 MEMORY 是自由结构 Markdown，不要求上午、下午、晚上或其它固定章节；旧 MEMORY 只要是非空、可读、上限内的 UTF-8 文本，无论既有格式如何，都可在人工重写时作为同日期附加 source 与 Session facts 一起执行有界分层 consolidation。LLM 严格返回一个 Markdown body，Memory 只确定性渲染日期 H1。正文中的 Home top Link 必须指向当前 actual Home 中已存在的顶层内容，`<memory:YYYY-MM-DD>` 必须指向已存在的其它日期 MEMORY；完整 catalog 只用于本地校验，模型只接收从 source 提取的有界有效 Link hints，非法或不存在的 Link 以有界模型反馈重新生成。Session archive 缺失或 projection 为空时 `skipped` 且不创建、不覆盖、不删除 MEMORY；否则生成完整新 MEMORY 并原子覆盖，不 append、不读取其它日期 MEMORY 正文作为 consolidation 输入。自动任务若目标 MEMORY 已存在且可读取、非空、未超限，则在读取 Session 或调用模型前 `skipped`；人工任务可结合旧 MEMORY 与 Session 重写。启动自动提示只检查昨日且要求 projection 非空：存在昨日非空 Session facts 且不存在昨日 MEMORY 时提示；不自动扫描更早日期，人工命令仍可显式指定日期。

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

Maintenance 是与 User Turn 同级、可独立触发的 Program work：（1）Home Maintenance 直接比较当前 active runtime Home 与 actual Home，由夜间后台 Agent 全自动 review/apply/discard，或由人工入口在终端逐项确认；人工确认使用 Maintenance 专用 decision channel，不形成 User Turn append，Home 模块不直接读取 stdin。处理完成的 overlay record/content 被清除，使 effective runtime 与 actual Home 一致。它不创建 Home archive，不保存独立 plan、review result、apply journal、status 或其它跨重启状态；中断后重新比较仍存在的 runtime diff 与 actual Home。启动 Home pending 只统计与 current actual 仍有真实差异的 created/modified/deleted，以及尚存在的通用 HOW `SKILL_MEMORY.md`；纯 copied 和 actual 已一致但尚未清理的恢复残留不触发提示。`SKILL_MEMORY.md` 参与通用 HOW review，完成后清空。（2）Memory Maintenance 读取指定日期 Session archive 与可选的同日期旧 MEMORY，完整重写固定日期文件。人工命令允许基于任意既有 Markdown 格式的旧 MEMORY 和 Session 重写同日文件；自动任务若目标 MEMORY 已存在且是非空、可读、未超限的 UTF-8 文本，则在读取 Session 或调用模型前 `skipped`，不覆盖。两个任务可以由独立命令触发，结果和失败边界彼此独立；内置 scheduler 只向 Program 投递 typed event，不绕过 Program 直接操作模块。自动夜间处理必须先完成 Daily Rollover，再依次在业务时区默认 `00:05` 投递 Home Maintenance、在 `00:15` 投递目标为昨日的 Memory Maintenance；时刻属于 App 配置。scheduler 只随长运行 `TinySoulApp.run()` 启动，不随 `run_once` 启动；所有 User Turn 与 Program work 仍在执行前做 Daily preflight。前一 Maintenance 失败不阻止另一任务独立执行。程序启动先补做 Daily Rollover，再分别检查 active Home diff，以及昨日存在非空 Session facts但缺少 MEMORY 的情况并给出非阻塞提示。显式命令为 `/maintenance home` 与 `/maintenance memory [YYYY-MM-DD]`，未指定 Memory 日期时默认昨日；在活跃 User Turn 中进入 Program queue，不成为 append。人工 `apply`、`discard`、`stop` 与 EOF 只由 App-owned decision channel 分流；Program 退出会先停止正在等待的人工 review。Program 级 normal 事件保留 `program.maintenance.available` 与每项 work 的唯一结果；Daily 由 Loop owner 发布 verbose `daily.transition.started` 和 normal `completed/recovered/failed`，Home 与 Memory owner 分别发布 verbose 的 started、局部 item（仅 Home）和 terminal 事件。事件只携带日期、Link、状态、稳定错误类型、digest 与计数等有界事实，不包含正文、diff、reasoning、绝对路径或持久化执行状态。

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
- Infra 提供配置环境、JSON 边界、受控文件读写、当前 Python 解释器的 distribution/module/executable 可用性检查和稳定公共门面。依赖检查通过 metadata/spec/`shutil.which` 检测但不导入、执行或安装目标依赖，也不解释 capability enabled 语义。项目模块配置位于 `configs/`，由 `tinysoul.toml` 显式 include；include 与 env file 都必须是项目根内的相对路径，拒绝绝对路径、`..` 越界和解析后越出项目根的符号链接。Infra 只负责加载、合并并提供 section tree，app/capabilities/context/home/memory/loop/session/workspace/llm 等实际模块各自解析所属配置并由所属 Runtime bridge 映射配置失败。配置显式加载、显式传递，模块不在导入时读取配置或创建全局单例；来自 dotenv、TOML、环境变量、模型输出或外部接口的动态数据，在进入模块内部边界时转换为明确结构，配置语义失败统一表达为 `ConfigError`，不以裸 `ValueError`/`TypeError` 越过 infra 公共边界。Infra 的 immutable JSON sequence pager 只拥有字符/条目硬预算、coverage 和 digest-bound cursor 算法，并以结构化 reason/constraint 报告通用分页失败；owner 可以交付不与 pager 字段冲突的 opaque cursor binding，Infra 只将其纳入 current/next cursor 和最终响应字符预算，不解释其业务含义。Context/Session 各自拥有 ref、owner、record kind 与 store 导航语义。
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
- Action 后端分工：native 运行在宿主线程，只能协作式响应取消；`subprocess` 必须在当前 Action batch 内结束；`supervised_process` 可以在启动 Action 返回后保留 Turn-scoped job 并由后续 Cycle 监督。`tinysoul/action/backends/process.py` 是不注册到 ActionEngine 的 retained process/文件捕获/进程树终止原语；`subprocess.py` 在其上提供同步 adapter 与唯一默认注册的 `subprocess.default`；`tinysoul.capabilities.supervised_process` 复用同一原语并拥有共享 job manager，但不提供同名通用 executor。Script 与 Shell 使用不同 handler、schema 和 policy，共用 `backend.kind=supervised_process`；旧 `backend.kind=script` 已删除且无 alias。`llm_action` 表示 action 内部受控 LLM task 的执行方式，共享能力由 `tinysoul/action/backends/llm_action.py` 提供。TOML Action Catalog 位于 `tinysoul/action/catalog`，是随 wheel 发布的版本化只读 package resource；项目不配置 catalog path、不复制或覆盖内置定义。Catalog 只保存真实 domain/action；backend 的存在不等于向模型暴露任意 shell/script。Action 自有动作位于 `tinysoul/action/builtins`，业务模块或 capability 通过所属 `actions.py` 注册 handler，核心逻辑仍位于 engine/service/client/evaluator。`backend.kind` 表达通用执行方式，`backend.handler` 表达具体 executor 落点；options 在 Catalog 加载期由 handler validator 校验。Capability 的 enabled 配置与当前解释器依赖共同决定 effective Catalog：禁用 action 不检查依赖并移除，启用但缺依赖在 App 装配期失败。需要硬停止的 worker 使用固定入口、有界结构化请求和共用 managed process，`subprocess.default` 不表示任意命令执行。
- Action 成功结果的 trace 生命周期由 Catalog `[runtime.result] trace_mode` 声明，只允许 `standard` 与 `foldable`。standard 结果不得返回 trace projection；foldable 结果必须由业务 executor 提供非空 `canonical_payload` 与有界、去重的 `origin_refs`，完整 payload 只作为当前 Turn visible overlay，canonical payload 是持久 trace 中的业务投影。Context pressure 或显式 fold 可以移除 overlay；TurnSummary/Session 无论是否发生压缩都只持久化 canonical envelope/payload。Catalog 只决定生命周期，不能从任意业务 JSON 自动猜测 canonical 字段；failed/timeout 结果不折叠。`context.trace.recall`、`session.history.recall` 与 Workspace inspection 共用该框架，不在 Context/Session 中增加 action-specific 分支。
- Resource conversion capability 只通过 `resource.convert_with_markitdown` 与 `resource.convert_with_pypdf` 把 Workspace document 转换为 Markdown 和 sibling `.assets/`，不调用 LLM、不做 OCR，也不把正文或二进制放入 ActionResult。图片/附件/PDF 页面只以 Workspace Link 交付，后续作为 reference 读取时才构造 ImagePart。source/output/page/asset count/asset bytes 上限是强失败边界，不能降级为 partial warning；worker staged output/manifest 不满足 host 协议时收敛为局部 `worker_protocol_invalid`。executor 在 source staging、worker 返回和 bundle commit point 前响应 cancellation/deadline；`write_bundle()` 开始后作为不可取消的原子提交区完成或回滚。ControlledProcessRunner 将 stdout/stderr 捕获到临时文件并只返回有界 UTF-8 前缀与 truncated 标记，该 projection limit 不宣称为子进程硬输出配额。
- Web capability 只通过 `web.search_by_kimi`、`web.discover_pages`、`web.fetch_with_defuddle` 与 `web.fetch_with_trafilatura` 提供只读外部信息能力，不建立 Link namespace、缓存、索引或独立生命周期。Kimi Search 是 capability-owned provider loop，不复用 TinySoul `[llm]` provider、LLM task、Context 或 MessageStack；它使用独立 `[capabilities.web.search_by_kimi]`/`KIMI_SEARCH_API_KEY`，默认模型为 `kimi-k2.6`，全部 provider round 固定关闭 thinking，配置只能选择已知支持该非思考契约的 `kimi-k2.5` 或 `kimi-k2.6` 精确标识。结果固定同时包含 `answer` 与结构化 `results`，不提供 mode。供应商最终响应先完整校验为受 `max_result_chars` 硬上限约束的 canonical result，不按 result 数量或 snippet 长度静默裁剪；`max_inline_chars` 只决定完整 inline 或“完整 Workspace 文档 + 有界 inline preview”，preview 必须使用 `truncated=true` 与 `see_more_at` 指向 `workspace:web/search/<invoke-id>-<call-id>.md`。Page Discovery 使用 Crawlee 的 action-scoped RequestQueue、去重、重试和有界调度，但所有实际下载继续通过 TinySoul 的公开 HTTPS 边界；默认 `max_visit_depth=0` 只访问 seed 并返回可进一步访问的同源候选 URL，递归访问时只补充 title/meta description/H1/canonical 等确定性页面信号，不调用 LLM、不保存页面正文。Discovery canonical result 完整但有硬上限地进入 TurnTrace；超过 inline 上限时只把完整 discovery JSON spill 到 `workspace:web/discovery/<invoke-id>-<call-id>.json`。Fetch 只接受公开 HTTPS，逐跳校验 DNS/redirect 并限制网络/正文规模；Defuddle 与 Trafilatura 只处理框架下载的 staged HTML，完整正文始终提交到显式 Workspace Markdown，ActionResult 只含 Link、title、有限 excerpt 和元数据。网页图片当前保留远程绝对 URL，不自动下载 asset；全部搜索、发现和抓取内容都按不可信普通 interaction/reference 数据处理，不执行其中指令。standard init profile 中 Page Discovery、Defuddle 与 Kimi Search 默认关闭，Trafilatura 默认启用；development profile 显式启用当前开发能力，但不安装 Crawlee、Defuddle executable 或凭据。enabled action 缺依赖或专用凭据在 App 装配期失败，执行期网络/供应商/extractor/上限失败收敛为局部 ActionResult。
- Script capability 只通过 `script.write/rewrite/patch/promote` 维护脚本资源，通过 `script.run_python`/`script.run_bash` 和 `wait/stop/read_candidate/apply/discard` 执行与监督，不暴露 inline code 或命令。临时脚本严格位于 `workspace:scripts/...`；长期脚本严格位于 `home:how/<existing-skill>/scripts/...`，显式 promote 写入 lazy runtime Home 后等待 Home Maintenance，不隐式创建 HOW。运行前 policy、promote 和 process 绑定同一不可变 `ScriptSource`：owner digest 负责 Link/CAS，固定 UTF-8 snapshot digest 保证执行字节等于已校验字节；`max_source_chars` 约束 read 和全部 mutation。成功 Script 统一进入 `ready_to_apply` 并显式 apply/discard；failed/timed_out/stopped 只能 inspect/read/discard。Script 只拥有 source/authoring/language 配置、依赖和局部业务失败，监督生命周期由共享 manager 拥有。
- Supervised Process / Shell：`tinysoul.capabilities.supervised_process` 是 capability-internal、非模型 domain 的 Turn-scoped execution manager；同一 Turn 跨 Script/Shell 最多一个 unresolved job，并对 execution id、Turn scope 和 owner 做统一校验。共享 pacing、runtime/log/mirror/candidate 上限、最小环境、Signal wait、额外 Cycle、answer guard 和 cleanup；实际 mirror/diff/CAS/bundle mutation 仍由 Workspace 拥有。job staging 固定为 `runtime/.staging/supervised-process-job-*`，日志和未提交候选不建立 Link、不进入 Workspace/Session/Home/Memory/archive；job 不持久化、不跨 Turn/重启。只有进程完成或当前 Turn 中协议有效的 input/control Signal 可以提前解除 Cycle pacing；普通预算耗尽后仅 running job 可申请有界额外 Cycle，每个 Cycle 仍从 Phase1 开始，结果只进入 TurnTrace。Cycle pacing 与额外 Cycle 判断等共享 non-Action activity failure 归 `supervised_process` Runtime bridge；Turn 离开时在 `finally` 中独立尝试回收 watcher/process/staging，cleanup 错误在全部回收尝试结束后聚合并由 Loop 形成 Observation，不能替换原始异常或 transfer。
- Shell 是独立 action domain，只接受有界 inline `command` 和 mirror 内相对 `working_directory`，提供 PowerShell、Cmd 与可选 Bash run，以及 wait/stop/read_candidate/apply/discard；模型不能指定 executable/flags/env/stdin，不提供 PTY、交互 stdin、跨重启 job 或长期 `.ps1`/`.cmd`。PowerShell、Cmd、Bash 分别使用框架固定 argv，宿主始终 `shell=False`。成功且无 mirror diff 时自动完成并清理；成功且有 diff 时显式 apply/discard；失败/超时/停止时 retained 供 read/discard。Workspace mirror 只保护 TinySoul 提交边界，不能阻止宿主绝对路径、网络、环境或子进程副作用，也不能回滚 mirror 外影响，因此不宣称硬沙箱；首版依靠项目显式 enabled，不增加逐命令 approval 或关键字 denylist。standard init profile 关闭整个 Shell capability；development profile 启用 PowerShell/Cmd、关闭 Bash。禁用 domain 不创建 prompt mount，已启用 capability 的 domain HOW 使用 `home/how_domain/<domain>/DOMAIN.md`。
- Context 模块向上层提供唯一装配与调用入口（组装门面），持有本轮 UserInputs、Context-owned Background、WorkingContext 与 TurnTraceHeap，负责构造式 MessageStack、语境控制工具与压力回收服务。Background 通过通用 provider 协议聚合 Home 顶层条目、昨日 Memory 与 Session 历史，不归 Home 或 Memory 任一模块所有。provider catalog 可额外交付属于自己的有界 Link/title/description 目录；Context 在每 Turn 自动将其渲染为 `background:catalog:<owner>` JSON user message，它不是已加载正文 Link，且不可由 Phase1 逐出。Home 使用该机制自动交付全部通用 HOW metadata，Phase1 再通过支持一次加载多个 Top Link 的 `load_background` 内部 control tool 按需加载当前 Context 已暴露的顶层正文；工具参数不枚举或泄漏完整 effective top catalog，Context 在提交前依据内部 provider catalog 校验开放字符串 Link。MessageStack 构造顺序为 system identity、UserInputs、SessionBackground、通用 Phase1 Background、TurnTraceHeap、WorkingContext、task prompt overlay；除 identity 使用 system role 外，其余用户态语境和 TaskPrompt 均使用 user role messages。Trace 正常增长是 append-only，Working 则是原位替换的当前快照；Working 模型消息携带组装时生成的 `as_of_trace {ref, canonical_revision}`，该临时锚点不进入 Working 持久状态或 TurnSummary。ContextEngine 不向上层暴露 heap node 等可变状态持有者；语境变更只有作用域化信号的事务批次提交与 Turn 生命周期两类入口。TurnTraceHeap 在 Turn 内保存 canonical trace，通过 branch/leaf head、inspect 和带 continuation cursor 的有界 recall 渐进恢复；recall result 使用 foldable projection，后续压力回收折叠回 origin ref。TurnSummary 在 Turn 结束时提供输入、Working/Background 终态、trace digest、provider-neutral 完整 JSON trace 与 heap 元数据，由 TurnCompletion 交给 Session 持久化。
- Context 信号协议：context.working.patch、context.workspace.sync、context.session.sync、context.background.patch、context.trace.append、context.input.append，均为 JSON 安全载荷并按命名空间消费。Context 先从 SignalBus 捕获绑定当前 Turn id 的可重放批次，再解析、校验 Turn scope、投影 Working/Background/Workspace 变更并准备全部懒加载背景，最后提交可行变更；Home 缺页或压缩陷入发生在提交前，由 Module runner 重试同一批次，不丢信号也不留下半提交。Loop 通过 `ContextSignalConsumer.emit_and_consume` 将同一逻辑步骤产生的 decision、action results 或 phase notes 成组发送并作为一个批次提交，不逐条破坏事务边界。`context.session.sync` 是 Session 独占且仅在 Turn preparation 接受的版本化全量历史头部；`context.workspace.sync` 是 Workspace 独占的 `{revision, resources}` 全量替换协议；普通 Working patch 只管理 milestone/todo。input append 与 loop control 必须携带当前 Turn frame，旧 Turn 信号不能写入新 Turn。Context 不再设置静态文本字符上限；LLM 依据模型必填窗口和 `compression_trigger_ratio` 检查完整请求，压力恢复按 `compression_target_ratio` 把 token 缺口投影为字符回收量。Composer 仍统计各 section 字符并执行内联图片总字节硬限制。Trap 压缩处理器在 Module frame 可用时优先重试 Module，否则重试 Phase；action-internal LLM task 会在容量异常 payload 中携带当前 target/reference links，Workspace 压力清理不得移动这些活动资源。
- Loop 模块是 TinySoul 的运行编排层，按 Program/Turn/Cycle/Phase/Module 消费 Runtime 运行位置与运行转移；Phase 单元只组合 ContextEngine、ActionEngine 与 LLMTaskRunner，不复制三者内部语义。Program 通过可注入 IANA 时区时钟在每项 work 开始时捕获唯一 `BusinessDay`，同一 User Turn 跨午夜仍归属开始日，日切只发生在 work/Turn 边界。`DailyLifecycleCoordinator` 先以 `.pending-*` journal 按 Session、Workspace/Trash 顺序确定性归档旧日，在旧日 roots 已移出 active runtime 后初始化同一新日的 Session/Workspace，最终原子形成不含 Home 的 `archive/<timestamp>/`；transition 不包含 `HOME_ARCHIVED`、`settlement_status` 或任何 Maintenance 状态。participant move、step journal、active init 和 final rename 的进程级中断窗口通过 persisted facts 幂等前滚，连续跨日会先恢复 pending transition 再继续目标日；该保证不包含 power-loss/fsync。Home 不参与 active day claim、daily archive 或新日初始化。Loop 只通过 `session_archive_for(day)` 解释跨模块 transition 并定位归档 Session 根；Session 再校验自身 manifest/graph，并通过专用 Memory facts projection 递归交付可达 Turn 事实，Loop 不读取 Session record。Program 已调度独立的 Home Maintenance 与 Memory Maintenance work：前者直接 review active Home overlay，后者按日期读取 Session archive；内置 scheduler、启动提醒和人工命令都只投递对应 Program event。目标 Turn preparation 依次重建 Context-owned Background（Home 默认项与可选的昨日 Memory）、投影 Session 历史和 Workspace Manifest；指向当前 Turn 的 RETRY 只重放 preparation，不重复 begin Turn。`core.answer` 经 TurnOutput Trap 结束 Turn；`TurnOutcomeStatus`/`TurnFailure` 区分 answered、exhausted、stopped、failed，normal Observation 和 `--once` exit code 不允许无回答静默成功。Context 结束后，`TurnCompletionPipeline` 默认先由 Session 幂等持久化完整 TurnSummary 与 TurnOutput，再运行其它后处理。
- App 模块是 TinySoul 的进程装配、生命周期、项目初始化和外部输入边界层。TinySoulAppBuilder 显式加载配置环境，构建 LLM、Workspace、Session、Agent Home、Memory、Action、Context、SignalBus、RuntimeTrap 与各级 loop runner，调用模块 registrar 装配 Workspace/Session/Home/Memory/core action executor，并按各 capability 的 effective settings检查依赖、注册或移除 capability action。外部输入源只生产带稳定 command identity 的 InputEvent，由 InputCommandParser 纯解析为输入意图；InputDispatcher 原子读取 active Turn scope，用同一快照分类输入并发出 Program event、`loop.control.request` / `context.input.append` 及权威 command receipt Observation。`tinysoul start` 是唯一交互运行入口，同一 App 同时拥有 Terminal 与 Endpoint；`--mode` 只控制 Console route，Endpoint route 固定为 model。每个项目启动前持有 App-owned 进程 lease，Endpoint ready 后在当前用户运行目录发布带 instance/project identity 的临时连接描述，退出时清理；重复启动不得构建第二个业务 Engine。`tinysoul start --once` 保留无交互单 Turn验收且同样持有 lease。`tinysoul/assets/project` 是唯一 init 模板源，只保存一份 README/`.gitignore`/`tinysoul.toml`/Home，并保存完整 standard/development config profile；`tinysoul init [DIRECTORY] --config-profile ...` 只在初始化期把所选 profile 物化为普通 `configs/` 与 `.env.example`，不保存 profile identity、不进入 Infra 配置层、不安装依赖或凭据，并继续拒绝覆盖。AppCommandGateway 只统一可信命令输入，输出统一经 ObservationEmitter/Router 分发，不合并为万能双向 Gateway。AppBuilder 只做跨模块装配并按真实模块归属桥接配置错误，不直接实现业务能力或读取业务资源正文。
- 项目模板维护只允许修改 `tinysoul/assets/project`，不得在仓库根重建 `configs/`、`home/`、`tinysoul.toml` 或 `.env.example` 镜像。默认 Home 文档只在共享 `project/home/` 中维护；新增、重命名或删除配置片段时，standard/development 必须保持相同相对 TOML 文件集合和可独立初始化的完整性，只有安全开关、provider 选择、模型顺序等已说明的 profile 值可以不同。standard 保持 provider disabled 与 host-sensitive capability 安全默认值；development 保存维护者当前启用但不含凭据的配置。每套 `.env.example` 必须覆盖该 profile 引用的环境变量名且不得含真实值。新增资源层级或扩展名时同步检查 `pyproject.toml` package-data；完成后至少验证两种 initializer 输出、共享 Home、config 文件形状和 wheel 隔离安装。已生成项目归用户所有，不从模板反向同步，也不得作为模板事实源。
- Endpoint 模块是本地桌面前端的外部协议适配层，只允许 loopback bind，并以进程级 bearer token 鉴权 HTTP、以首帧 token 鉴权 WebSocket。它只随 `tinysoul start` 接入同一个 ProgramRunner、InputDispatcher、DailyLifecycleCoordinator、SessionEngine、WorkspaceEngine 和 HomeDecisionBroker；Endpoint 不拥有进程退出权、业务状态或持久目录。ObservationRouter 为 Console 与 Endpoint sink 保留独立上限，Endpoint event buffer 固定接收 normal/verbose/model 全部事件，只做有界进程内 sequence replay/gap；前端永远以 model 订阅并在本地切割展示。Endpoint 暴露结构化普通输入、control、Home/Memory Maintenance request、decision 和当前 Maintenance status，全部进入同一 AppCommandGateway；decision required/resolved 与 Program work lifecycle 必须经共享 Router 广播。Workspace/Session 请求持有 active-day lease；UI mutation 在同一 WorkspaceEngine 锁内校验 revision/digest，成功后在活跃 Turn 发布 full snapshot。Endpoint request failure 是稳定 HTTP 局部结果，服务启动失败经 RuntimeEndpointBridge 映射为 startup failure；FastAPI/Uvicorn/WebSockets 是 `tinysoul start` 所需的核心运行依赖，ASGI adapter 仍只在 EndpointHost 启动时延迟导入。
- Workspace 模块负责 `workspace:` 链接、`runtime/workspace` 当日工作区根目录、schema v3 Manifest、磁盘 reconciliation、扫描诊断、临时 task prompt 输入、文件变更 action、可恢复 Trash 和日归档。Manifest 持有显式 business day；磁盘是内容事实源，Manifest 是版本化索引与语义描述层，WorkingContext workspace 段是当前 Turn 的同 revision 投影。`WorkspaceReconciler` 只在完整扫描后提交，description 与当前 digest 绑定。Workspace 为本地转换能力提供受 kind/bytes/digest 约束的 document read，以及在同一 Engine 锁内预检、写入、完整 reconcile、单 revision 返回并在失败时恢复原字节与 Manifest 的 bundle mutation；成功 executor 只能在 bundle 提交后发布一次同 revision `context.workspace.sync`。Trash 固定位于 active root 的 `.tinysoul/trash`、被扫描忽略且不进入资源 Manifest；活动日内 `workspace.trash.list`/`workspace.restore` 提供恢复，日切时 Trash 被提取到归档时间戳下的独立 `trash/`，旧日 Trash 不再进入 active API。压力回收只移动未被当前 action target/reference links 保护的 ephemeral/turn 资源，失败必须回滚；显式 delete 不自动撤销。Workspace 的明确一致性等级是单进程单写者、同一 Engine 实例内线性化；不宣称跨进程 CAS 或数据文件与 Manifest 的跨文件系统原子事务。跨模块归档调度归 Loop，Workspace 门面只负责完整 reconcile 和自身 workspace/trash 的可恢复移动。
- Workspace inspection 是核心定义中“文件内容通常不应进入 Context”的明确窄化例外：禁止隐式、自动或无界整文件读取，但允许显式有界范围偶然覆盖很短的完整文件。`workspace.read` 只接受一个明确 UTF-8 text Link、1-based 闭区间和可选 cursor/max chars/expected digest；`workspace.search_text` 只做有界单行字面量搜索，scope 必须显式为单文件、目录 prefix 或整个 Workspace，返回带 Link/digest/行范围的 fragments 和预算不足后的 line hints，并分别报告 result truncation 与 scan coverage。两者只读、不发布 Workspace snapshot，正文使用 foldable ActionResult。`workspace.analyze` 只接受 Phase2 已选择的非空去重 text `reference_links` 与 intent，不接受目录或 Workspace scope，不在 Phase3 重新选择资源；references 必须完整且在单文件/总 source budget 内，否则不调用 LLM并局部失败。成功时只执行一次禁用工具的 action-internal LLM task，返回有界 answer 与经验证的来源定位，使用 standard trace，不修改 Workspace，原始 references 不进入 ActionResult。
- Agent Home 模块负责 `home:` 链接、顶层背景目录、渐进式资源、domain/action HOW、通用 HOW 的 `SKILL_MEMORY.md` 和跨日可写 overlay。actual 内容严格位于 `home/` 且普通 User Turn 与确定性日切都只读；runtime overlay 严格位于 `runtime/home/`，由 revision、baseline/runtime digest、state 和可前滚 operation journal 管理，但不再以 Business Day 作为身份或归档边界。Home 内容在首次实际读取时通过 `HOME_RUNTIME_COPY_REQUIRED` Trap 透明物化，handler 只在调用前 runtime 文件缺失且调用后确实存在时重试一次。Context 每个 User Turn 清空通用 Background，再通过 `HomeBackgroundEntryProvider` 从统一 effective catalog 提供不可逐出的默认 core、effective 存在时同样不可逐出的 allowlisted `home:agent@context/*` 与 `home:agent@user/user`、内部可加载目录和全部通用 HOW 的严格 frontmatter Link/title/description；不得把任意 Agent Top 自动升级为默认正文。Top Link 格式只表示 Background 资格，不表示自动加载。该 catalog 按 `runtime override -> tombstone -> actual fallback` 解释 top，runtime-only top 在后续 Turn 可见，Phase1 临时加载项不跨 Turn 留存。通用 `SKILL.md` frontmatter 只允许 YAML `title`/`description`，单项和总 catalog 都有界，启动/reconcile 与 top mutation 共用同一 parser；总量超限显式失败。`HomeTopSearchService` 对 HOW 复用同一 frontmatter metadata，对 WHAT/WHY 使用 H1/正文段，再构造确定性候选；专用 `home_search` LLM task 只重排候选，非法或失败结果回退稳定候选；搜索 actual 不创建 runtime copy，action 不返回完整正文或自动加载 Background。渐进资源使用 `home.resource.*`，但 Top Markdown 与通用 HOW `SKILL.md` 不接受 Resource Link 别名；顶层内容使用 `home.top.write/patch/delete`，新 WHAT Link 必须包含 `entity/`/`concept/` 分类并使用无后缀逻辑路径，`home:agent@AGENT` 禁止 delete；自动 HOW 使用 `home.prompt_mount.write/patch`，合法 mount 由 App 从 ActionEngine 的 catalog identities 交给 Home 自动 reconcile，模型不能 create/delete mount。`SKILL_MEMORY.md` 只允许位于通用 `runtime/home/how/<skill>/` 且要求对应 effective HOW skill 存在；actual Home、how_domain/how_action 和其它空间禁止平行 memory 文件。所有普通修改只落 runtime。`HomeMaintenanceService` 每次从 active overlay 与 current actual 重新构造有界 baseline/runtime/actual change；copied 与已和 actual 一致的 record 确定性清理，created/modified/deleted 由自动 `home_maintenance` LLM reviewer 或上层注入的人工 decision provider 逐项 apply/discard，core tombstone 在 review 前即拒绝。apply 使用单文件原子替换或删除，处理完成后移除对应 overlay；`SKILL_MEMORY.md` 作为同 skill change 的 review context，并在该 skill review 完成后清理。diff、decision、outcome 只存在内存，不创建 Home archive、review/plan/apply store；actual 写后清理前中断时，下次通过 runtime/actual 一致性自动收束。Home 不再解释 `memory:` Link、Memory 目录、Memory search/recall 或 Memory Maintenance。
- Memory 模块负责 `memory:YYYY-MM-DD` Link、默认位于项目顶层的 `memory/yyyy/mm/yyyy-mm-dd.md` 存储、有界 search/recall、昨日 Background provider 和 Memory Maintenance。显式绝对 root 是受信任的部署或测试覆盖，但 Link 映射后的文件始终受配置 root 约束。Memory 只读地消费 Session facts projection，通过注入的 Home 顶层 Link catalog 校验 `<home:...>`，不读取 Home overlay；`<memory:...>` 由 Memory 自身校验并提示 Agent 召回。Memory 没有 runtime overlay 或普通 mutation action，只由 Memory Maintenance 对指定日期文件原子完整重写。`memory.search` 是按日候选发现 Action，在 Agent 不知道精确日期时返回唯一日期 Link 与有界摘要；`memory.recall` 是精确读取 Action，在已知 Link 时返回受上限约束的完整单日 Markdown；结果都进入 TurnTrace。实现统一位于 `tinysoul.memory`，使用独立 `[memory]` 配置、Action domain 和 Runtime bridge；Home 不接受 Memory space、旧 Link 或旧路径。

- Action 局部失败的唯一事实源是 typed `ActionLocalFailure(reason, scope, disposition, feedback, constraint)`。success 禁止 failure，failed/timeout 必须携带 failure；业务 payload 不承载 `payload.failure`，`ActionResult`、envelope、foldable projection 和 HookOutcome 都必须在构造边界拒绝该保留字段，frame data 不重复失败语义。普通 hook 拒绝通过 `HookOutcome.failure` 直接交付该事实，可选 payload 交付模型所需业务数据，可选 frame data 仅进入 trace/Observation；hook success 为空且不生成额外 ActionResult，pipeline 只补 hook identity，注册缺失或实现异常由 pipeline 构造自己的 typed failure。`ActionResultRenderer` 只是 Action-owned 投影边界，统一生成 model/trace 及 visible/canonical ToolResult envelope，不推断事实。foldable canonical result 保留 `action/status/stage/failure` 包络，只替换业务 `canonical_payload`。
- Context trace recall 与 Session history inspect/trace 共享 Infra immutable JSON sequence hard pager，但分别拥有 ref/store/source 语义；字符预算与条目数量都使用 requested/effective 双层限制，`max_entries=1` 可精确读取已知 index；普通 entry 原子返回，oversized entry 只通过 digest-bound 服务端 cursor 按 Unicode 字符续读，最终 JSON 不得突破生效字符预算。只有 owner-defined typed request error 可转为局部 Action failure，I/O 与 invariant 经所属 Runtime bridge 结束 Turn。Working model tools 固定为 `set_milestone`、`remove_milestone`、`set_todo`、`remove_todo`，每次调用表达一个非空完整操作，多调用按 sequence 投影验证后原子消费；不保留 `update_working` alias。
- Session Background 是 Turn preparation 期间注入的固定、不可逐出历史段；超预算时以 immutable Summary 递归收缩，极端时使用 overflow head。`session.history.inspect` 无 ref 导航 authoritative root、以 Summary ref 展开 direct children、以 Turn ref 读取有界 preview，且不扫描 Action；root cursor 绑定 Manifest revision。`session.history.actions` 只从具体 Turn 的 immutable canonical trace 确定性派生完整 Action summary、failure groups 与 trace indexes；projector 严格报告 missing/orphan/duplicate/name mismatch，name mismatch 拆为真实 call/result action occurrence。`session.history.recall` 只恢复具体 Turn canonical trace，不导航 Summary，不返回 Background/preview/Action summary。Session-owned Turn/Summary validators 在写入、生命周期 reconciliation、inspect/actions/recall 与 Memory projection 统一校验 record 结构、确定性身份及物化 Background；Turn 的 ask/answer/references/outcome/trace identity 从内在事实重投影，历史 action detail 不按当前配置重选，但必须逐项证明来自 canonical trace。canonical trace 是证据，digest 是完整性事实，action history 和 Background 都不是第二事实源。三个查询都是普通 Action，结果进入 Interaction 而不改写 SessionBackground；无 ref inspect 只观察最近一次已提交的 authoritative Manifest root，已知 ref 可读取原子落盘且有效但尚未接入 root 的 orphan record，二者都不触发 reconciliation 或 revision 变化。Endpoint 的 Session Explorer 必须以 root revision/status/event 判断已提交导航头部；view-local actions/trace 独立收敛并保存有界页轨迹，切换 Turn/client 时取消旧请求，迟到响应仍由 reducer 拒绝，root revision 变化时清空整个旧导航快照。三个查询都不调用 LLM，因此只维护 Catalog 和 Session Domain HOW，不建立 Action HOW。Turn record 直接使用当前 schema，不保留旧 schema adapter。
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

- 修改代码后、声明任务完成前，必须运行并通过：

```powershell
python -m pytest tests -q
$env:TINYSOUL_PYTHON='当前设备的 TinySoul python.exe'; .\scripts\typecheck.ps1
```

多设备环境不要在 `pyproject.toml` 固定本机 Python 路径；类型检查统一通过 `scripts/typecheck.ps1` 选择当前设备的解释器，或显式传入 `ty --python <当前环境 python>`。

若当前 Windows PowerShell execution policy 禁止直接运行仓库脚本，使用仅作用于该子进程的方式，不修改机器级策略：

```powershell
$env:TINYSOUL_PYTHON='当前设备的 TinySoul python.exe'
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\typecheck.ps1
```

测试运行语义与环境边界：

- `python -m pip install -e ".[dev]"` 是日常开发环境入口；它使用当前源码和 dev extras。构建后端可能为 PEP 660 安装生成临时 editable wheel，但这不是可发布 wheel，也不完成发布资源验收。普通 `python -m pytest tests -q` 覆盖所有本地测试，默认 skip 真实供应商和显式 opt-in 网络测试。
- `tests/release/test_wheel.py` 是独立发布验收：测试内部从 clean source copy 执行 `pip wheel --no-deps --no-build-isolation`，检查 package data，再用 `pip install --target` 隔离安装并从安装结果运行 `tinysoul init`。不应把 `pip install .` 当作该验收的替代；需要单独检查发布资源时运行 `python -m pytest tests/release/test_wheel.py -q`。
- 受限沙箱或 Windows 用户 Temp/LOCALAPPDATA ACL 导致 pytest setup、`.pytest_cache` 或 ProjectInstanceLease 失败时，把临时目录和单实例目录都置于仓库内的 ignored 路径，并禁用 pytest cache：

```powershell
$test_root = Join-Path (Get-Location) (".pytest-local-tmp-" + [guid]::NewGuid().ToString("N"))
$local_app_data = Join-Path $test_root "local-app-data"
$pytest_root = Join-Path $test_root "pytest"
New-Item -ItemType Directory -Force $local_app_data | Out-Null
$previous_local_app_data = $env:LOCALAPPDATA
$env:LOCALAPPDATA = $local_app_data
try {
    python -m pytest tests -q --basetemp $pytest_root -p no:cacheprovider
} finally {
    if ($null -eq $previous_local_app_data) {
        Remove-Item Env:LOCALAPPDATA -ErrorAction SilentlyContinue
    } else {
        $env:LOCALAPPDATA = $previous_local_app_data
    }
}
```

该命令只在测试期间改变 pytest 临时目录和 Windows 用户级 `LOCALAPPDATA`，从而把项目实例锁放进本次唯一测试根；它不会改变生产运行时默认目录。唯一根还避免复用旧 pytest 目录时继承不可写 ACL。若测试在沙箱外运行且系统 Temp/LOCALAPPDATA 可写，优先使用标准命令。不要为全量测试设置 `TINYSOUL_INSTANCE_DIR`：`TINYSOUL_*` 同时是项目配置环境命名空间，该变量会被解释为未知顶层配置。

测试结果应区分：测试断言失败、测试依赖缺失/显式 skip、沙箱或 ACL setup failure，以及 wheel 子进程安装失败。后两类不能通过修改业务代码掩盖。

- 测试约定：
  - 测试按 `tests/<module>/test_<切面>.py` 组织，镜像模块结构；
  - 触网或调用真实供应商的测试默认 skip，需显式开启。

- 用户对接：每次产生修改后阐述本轮改动了哪些文件，以及提供用于 commit 的文本内容
- 前后端协作：后端 agent 仅修改后端项目代码，不过多考虑 visualization；前端 agent 工作仅限于在 visualization 目录下修改，不改动后端项目代码；后端项目代码接口应全部通过 endpoint 向前端提供能力支持，在修改后端实现时，若发生 endpoint 改动，需即时在 docs\endpoint 中建立和调整文档，供前端对接；前端在进行前端设计和实现时，若发生缺失能力，不要阻塞设计和实现工作，允许暂时假定可行接口，并通过 visualization\docs\demand 向后端 agent 提出进一步能力需求。


## 当前任务

当前任务已从核心模块重构转入 TinySoul 整体应用构建与优化。`reference/tinysoul_v1` 只作为历史设计与行为参考；当前代码、模块设计文档和已完成执行记录才是实现事实。后续工作不得使用兼容层、重复状态或跨模块捷径。

### 已完成基础

- Runtime、LLM、Action、Context、Loop、App 已形成完整 User Turn、Agent Cycle、Phase、Action、Trap 和 Program 生命周期；provider、tool protocol、context window、deadline、失败 scope/disposition 与输出完整性边界已经闭环。
- Session、Workspace、Agent Home、Memory 与 Daily Lifecycle 已拥有各自持久化、Link、投影、Maintenance、reconciliation 和失败语义；Workspace 保持单进程单写者、Engine 实例内线性化，并通过 revision/digest CAS、Trash 和 transaction mirror 管理变更。
- Resource、Web、Script、Shared Supervised Process 与 Shell capability 已完成，Action Catalog、HOW、配置裁剪、事务提交和 Turn cleanup 均接入正式 AppBuilder。
- `tinysoul start`、项目单实例连接描述、AppCommandGateway、ObservationRouter、authenticated Endpoint 和 `visualization/` Tauri/React 前端已经形成 Terminal-owned 后端与纯连接前端的统一应用链路。历史实现与验收保存在 `docs/analysis/*-done-*.md`，不再在本节重复维护逐阶段日志。
- Session record 完整性现由唯一 Session-owned validator 统一维护，history 查询不再隐式 reconciliation；Action hook reject 已对齐 failure/payload/frame_data 三通道，测试不依赖本地真实运行记录。完成记录见 `docs/analysis/20260724-done-session record integrity and hook outcome boundary correction plan.md`。

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
