# Activity 语义、阶段呈现与 Turn 入场执行计划

状态：`done`。实施核对：2026-10-03；代码分析开始于 2026-10-02。

视觉与交互基线：`c479ca0`。代码复核基点：`72e015f`；其工作树内容与 `9e6546d` 相同。接口与正式事实来源继续采用 v2。

## 1. 目标与范围

本轮修正主对话中仍未对齐的活动信息、阶段提示和启动顺序，并为右侧 Details 的 Activity 增加连续的阶段底色。已有表现优先提取 `c479ca0` 的组件结构和语义，再适配当前数据；不靠延长动画或隐藏整个卡片掩盖消息位置与身份问题。

范围包括：LiveStatus、Activity、Thinking 筛选与思考条、初始用户输入的呈现衔接，以及必要的 Context 控制结果观察。保留现有连续会话、完成收束、动作浮层、模型调用抽屉与结束后背景快照。前后端均可修改，但不恢复 v1，不改变 Turn/Cycle/Phase、Context prepare/install 或资源 owner 的基本语义。

## 2. 实施前核对的问题与原版依据

| 问题 | c479ca0 的做法 | 当前事实与判断 |
|---|---|---|
| 无内容的阶段条目 | `derive/chat.ts` 的阶段事件更新 Phase 状态，不为正常阶段开始追加 Activity | `features/chat/activityBuffer.ts` 将 `loop.phase.started` 直接转为 `phase_start`。应移除这类列表条目，阶段事件仍驱动抬头、计时与 Trace。 |
| 抬头过于抽象 | `derive/model.ts` 的 `PHASE_META.running` 为完整运行句；具体执行时显示行动与目标 | 当前使用 Understanding / Planning / Executing。恢复原版阶段句，并保留 v2 实际执行事件提供的具体行动。 |
| Activity 语义不完整 | `addControlActivity` 呈现 todo、milestone、域选择 intent；`applyBackgroundEvent` 呈现实际加载/逐出 | 当前只有背景 refs 与域标签，todo/milestone 类型虽存在，却没有活动事件来源。不能只屏蔽初始 Loaded 文案。 |
| 初始 Loaded Home | 原版 snapshot 用于建立已加载列表；活动加载行只读取 `loaded_links`，并不把 snapshot 的完整列表当成加载操作 | 当前把 snapshot 的 `links` 全部转成 Loaded。初始化现态与 Agent 控制行为被混淆。 |
| intent 不进入思考呈现 | 原版保留独立 `intent` 行，带域标签，归入 Activity 的 Thinking 筛选 | 当前 ActivityBuffer 在压缩模型响应时丢掉 tool_calls，intent 只在部分 Phase 详情可见。恢复该来源；按确认意见，顶部思考条保持原版，仅呈现 reasoning。 |
| Turn 启动跳位 | 原版 `components/chat/TurnView.tsx` 始终先排用户气泡，再排单一 Agent 区域 | 当前 `CurrentTurnControls` 把所有 outgoing 放在 AgentRow 内、LiveStatus 下方；正式 `user.input` 则由顶部另一个节点渲染，产生移位和重新淡入。发送无当前 Turn 时，echo 还可能没有独立显示位置。 |
| Details Activity 缺少原版功能 | `components/trace/TurnTraceDrawer.tsx` 有 All / Thinking / Actions / Context / Errors 筛选、倒序时间、动作定位 | 当前 `ProcessPanel.ActivityTimeline` 仅呈现顺序条目。恢复这些直接相关的原版结构，再加入连续阶段底色。 |

计划建立时，启动问题由用户体验和渲染路径共同定位。实施阶段补充了从发送开始的浏览器证据与节点连续性验证，见第 8 节；不能仅检查最终气泡位置。

## 3. 统一的数据与表现语义

### 3.1 三类信息各司其职

| 信息 | 数据来源 | 呈现位置 |
|---|---|---|
| 此刻正在做什么 | 正式 Turn 状态、Phase 边界、实际 Action execution | LiveStatus 抬头、运行计时、Trace 阶段状态 |
| 刚刚发生什么 | 模型显式 reasoning/intent、已应用控制操作、行动计划与结果、重试、任务 Skill provenance | LiveStatus 滚动条目与 Details Activity 共用同一语义适配 |
| 当前已有哪些内容 | Context 已安装 plan / background；结束后对应 Session 快照 | WorkingZone、Context Inspector 与历史读取 |

Observation 是有界过程披露，不能成为另一套正式 Working/Background 状态或持久日志。重连/gap 后从 owner 重新读取现态；未保留的旧事件不以模型请求或当前文件补造。

### 3.2 阶段抬头与真实条目

恢复原版文案：

| 运行位置 | 抬头 |
|---|---|
| Turn 准备中，尚无实际 Phase | `Preparing context` |
| Phase1 | `Maintaining context and selecting domains…` |
| Phase2 | `Generating action parameters…` |
| Phase3，无可具体命名的运行 Action | `Executing actions…` |

复用一份阶段表现元数据供 LiveStatus 与 Trace 使用，区分阶段标题、运行句与阶段色。不要在未出现 Phase 时默认假定 Phase1 已开始；PhaseHeadline 的阶段允许为空。

单个实际运行 Action 可显示名称与真实目标；并行多个 Action 显示实际运行数量，不随意选第一个冒充唯一正在运行的行动。等待用户、预算与停止中的提示继续由正式 Turn 状态覆盖。阶段结束但尚未进入下一阶段时按实际状态呈现，不继续累加已结束阶段的计时。

从 Activity 类型、生成分支、渲染器、图标映射和测试中清理 `phase_start`，不保留永远不会生成的兼容分支。不删除 Phase 原始事件或 Process 树中的阶段信息。

### 3.3 Control Tool 的已应用事实

旧版直接根据模型 tool_calls 修改前端 Working 并输出活动，这一数据处理不能原样移植。当前 Control Tool 只是请求，Context 校验并完成 prepare/install 后才有已应用事实。

采用以下后端支持方案：

1. 在 `ContextEngine.consume_signal_batch` 成功 install 后，为来源为 `context.controls`、实际通过校验的操作发布 verbose `context.control.applied`。覆盖 `set_todo`、`remove_todo`、`set_milestone`、`remove_milestone`、`load_background`、`evict_background` 六类。
2. 事件沿用原始 Signal 的 Turn/Cycle/Phase scope，保留 `call_id`、规范化操作名和操作所需的有限语义字段：todo 的 key/content/status、milestone 的 key/content、移除的 key、背景操作的 links。复用 typed patch 和现有序列化设施，不透传任意模型 arguments 或正文快照。
3. 应用记录由成功候选按原序生成，发布发生在整个批次安装成功之后；prepare 失败、被拒绝的 patch 不发布 applied。同批多个操作是一次已提交批次内的控制记录，不宣称事务中间状态曾逐个暴露给模型。
4. 保持 `consume_signal_batch` 当前的失败反馈返回契约，不为了观察成功操作而在返回值中混入 success：现有消费者有“返回非空即存在局部拒绝”的判断。成功观察与现有局部失败返回不是同一职责。
5. 在已有 `loop.phase.completed` 中披露 Phase1Outcome 的有限 `control_results`，包括 call_id、tool_name、status、stage、feedback。失败阶段同样保留这些结果。消费阶段的 tool_name 可能是 Signal 名，前端以 call_id 关联该次模型请求的工具名，不能把 Signal 名当成新的 Control Tool。

新增事件的 owner 为 Context，Endpoint 只通过既有 Observation 通道传递；不新增业务写接口或活动日志。控制操作的失败留在现有 Phase/Trace 反馈语义，失败事件不被呈现为成功操作；成功控制也不因随后域选择失败而被抹去。

前端共用一份 typed 解析结果：

- todo 支持 pending / in_progress / done / cancelled 以及移除；展示具体内容，完成状态可用原版勾选与弱化样式。
- milestone 展示“记录/更新/移除的重要事实”。当前后端 milestone 没有 todo 式完成状态，移除前端未使用的 `done/blocked/skipped` 强制假设，不能一律画完成勾。
- 已应用加载/逐出显示资源名和链接标签；操作失败显示短反馈，详细请求仍在对应 ModelCall/Control 详情中。
- WorkingZone 继续由 `useActivityDetails` 读取已安装 plan，不靠 Activity 补丁计算正式现态。

### 3.4 初始背景、显式加载与任务 Skill

`context.background.snapshot` 和 `context.background.changed` 继续服务 Context 刷新与观察，不直接生成重复的 Agent 控制活动。显式加载/逐出活动改由 `context.control.applied` 提供，因此初始化快照自然不会显示为 Loaded。

资源类条目复用原版 SkillsBody 的紧凑标签结构：短操作动词 + 可读资源名，完整 ref 保留在 tooltip/详情。通用 Skill、其他 Home 和 Memory 背景可用相同资源标签布局，按 ref/owner 区分资源。

保留自动任务 Skill 的辅助展示：从真实 `llm.model.request` provenance 提取 `home:skills_domain:*` / `home:skills_action:*`，以“任务指导”类条目共用标签组件。它不是 Background 加载，不出现在“已加载 Home”列表中。同一 task 的 provider 重试只展示一次相同 mount；不同 task 可以分别展示。没有 provenance 时不推测挂载。

Activity 围绕 Agent 显式行为展开；系统初始化与自动容量调整的现态继续由 Context 页面解释，不再把每次背景刷新包装成 Agent 的加载操作。历史旧版本若没有 applied 事件，只能展示留存请求与实际记录，不回退到将请求冒充执行。

### 3.5 intent 与 reasoning 共用阅读体验，保留来源

v2 的 `llm.model.response.tool_calls` 已保留 `select_action_domains.arguments.intent`，无需新增推理接口或更改 LLM 协议。

调整 ActivityBuffer 的有界投影：丢弃完整消息/无关大参数之前，提取 task_id、call_id、Phase1 域选择 intent 和请求域；reasoning.summary 继续独立保留。只接受当前 Phase1 的该 Control Tool，Action 内部任务或其他同名字段不能误入域选择思考。

单次模型响应允许生成 reasoning 与 intent 两个语义项。条目 ID 从事件 sequence 加语义类型/call_id 派生；同一 replay 不重复，不能再假设一个事件只能产生一个活动条目。

- reasoning：模型显式返回的摘要，沿用现有 Markdown 思考条。
- intent：单独的“域选择意图”，用原版 IntentBody 的文字与域标签结构；长文本可就地展开。
- 域标签的正式“已选择”状态仍以 Phase1 完成事件的 `selected_domains` 为准。响应刚到时是请求；完成后可在同一条目补齐确认状态，避免再生成内容重复的 Selected domains 行。没有 intent 时仍可展示实际接受的域。
- 顶部思考条只选择最新的非空 reasoning，保持原版交替与展开动效；intent 仅在活动与 Thinking 筛选中呈现，不进入顶部思考条。
- Details 的 Thinking 筛选包含 reasoning、intent 和任务指导，延续原版；Phase 展开区与模型详情复用相同提取语义，不另造一份思考记录。

同一响应若 reasoning 与 intent 在去除首尾空白后完全相同，不重复展示两段正文，可在 intent 行保留域选择信息。不同内容均可在 Activity/Thinking 阅读，不做模糊文本相似度判断。完整模型响应仍通过 ModelCall 查看。

## 4. Details Activity 的阶段底色

### 4.1 分组与归属

复用原版 `TurnTraceDrawer.ActivityTimeline` 的筛选、倒序列表、时间与点击行动定位，适配现有 ProcessPanel / Inspector 导航。共享 ActivityStep 正文，不建立 Details 专用的第二套事件解释。

ActivityStep 增加可空的 `cycleId`、`phase` 与必要 task/call 关联。归属取事件 scope；只有存在精确 task/call 对应时才补齐归属，不把缺失 scope 的记录统一塞入 Phase1，也不按当前屏幕显示阶段猜测旧条目。

先按原始活动顺序划出连续的 `(cycleId, phase)` 区段，再应用筛选与倒序展示；过滤隐藏条目不把原本不连续的两段拼成同一个阶段。不同 Cycle 中的 Phase1 可以用相同颜色，但保留各自区段身份。未知阶段采用中性背景。

### 4.2 视觉预览

| 阶段 | 淡底色建议 | 视觉含义 |
|---|---|---|
| Phase1 | 现有 accent 系的淡靛紫 | 语境维护与域选择 |
| Phase2 | 现有 info 系的淡蓝 | 行动参数生成 |
| Phase3 | 现有绿色系的极淡底色 | 行动执行；此颜色不表达成功 |

底色只在右侧 Details → Activity 的区段外层绘制。每段内部条目用 padding 形成间距，移除逐行 margin、独立底板或单行圆角造成的色泽间隙；整个相邻段容器可裁切外沿圆角，阶段交界直接换色。时间列、轨道与展开正文均位于同一连续底色内。

保留原版的小图标、领域标签与失败颜色；阶段色不覆盖成功/失败状态。每段可用一处低调的 Cycle/Phase 提示，不为每条活动重复写阶段标题。明暗主题分别调节淡色强度，以正文可读和视觉轻量为验收条件。

LiveStatus 的卡片、条目、浮层背景和动画不应用这些阶段底色；阶段色也不扩散到整个 Trace 树或模型抽屉。

## 5. Turn 入场：先统一结构，再复用动画

### 5.1 消息来源切换不改变布局职责

初始用户消息无论来自本地 echo、已受理请求或正式 `user.input`，都由同一个 Turn 顶部输入槽渲染；AgentRow 始终排在其后。把新 Turn echo 从 `CurrentTurnControls` 移出，避免让新消息出现在上一轮 Agent 区域或 LiveStatus 下方。

在没有当前 Turn 时，发送中的消息也应立即拥有可见的本地输入槽；它是明确的 sending 展示，不是假造已接受 Turn 或正式 interaction。失败在原位保留重试/关闭入口；queued 的请求呈现排队状态，不提前出现运行中的 LiveStatus。

利用既有 command_id/receipt.turn_id 关系保持本地表现身份。当前后端路径为 `RuntimeFacade.submit_turn` → `UserTurnRequest.request_id` → `TurnHandle.turn_id`，已支持关联；没有必要为本问题新增资源接口或消息日志。前端以受理回执核实绑定，在正式 projection 到达时更新同一输入组件的数据来源和交付状态，不销毁再创建气泡。

表现 key 与业务状态分离：本地 sending 不等于 owner running。仅在当前页面生命周期保留必要的表现身份映射，正式内容始终服从 owner。相同文本的不同 Turn 不能相互收敛；避免依赖全文相等或不受 Turn 约束的 role 序号识别新请求。

追加和回复仍依所属 Turn/input_id/question_id 位于各自交互位置，不能因修复初始输入而一并搬到顶部。未轮到的 queued echo 也不能混进当前运行 Turn 的输入槽。

### 5.2 一次入场与连续挂载

1. 本地初始气泡先出现在正确槽位；后端状态到达后，LiveStatus 从其下方进入。
2. 本地标识与正式 Turn 身份衔接保持同一表现组件；一次初始输入只触发一次淡入和一次新轮停泊，不随接口返回顺序重播。
3. 延续 c479ca0 的 20px 停泊位置、700ms 缓出滑动、动态尾部空间与手动滚动接管。滑动目标绑定稳定的输入槽，而不是暂时为空的 Agent 框。
4. 区分首次历史恢复与当前新输入等待 projection。不能用同一个 loading 布尔值，把新消息当作历史恢复先瞬移再补动画。
5. 不再用“Loading the conversation…”替换已经显示的本地初始正文；无本地内容的真正恢复仍允许加载提示。运行卡首次出现时不早于对应输入槽。
6. 保留当前完成时的单一 LiveStatus 实例、600/700ms 折叠与回答流入；reduced-motion 直接呈现但仍满足相同顺序和身份要求。

## 6. 实施步骤

| 步骤 | 状态 | 修改范围与输出 | 完成条件 |
|---|---|---|---|
| S1 基线复现 | done | 对照原版 TurnView、LiveStatus、ActivityStep、TurnTraceDrawer 和 derive；记录当前新轮从发送首帧开始的过程 | 复现首轮与连续第二轮的倒置/重挂载，记录源组件与数据路径 |
| S2 控制观察契约 | done | Context engine/control、Loop Phase 完成投影、相关 owner 测试；同步 Endpoint events 与 Context 设计 | 仅 install 成功才报告 applied；失败反馈、域选择与 scope 正确，返回契约不变 |
| S3 Activity 语义 | done | activityBuffer、presentation、facts、ActivityStep 与 LiveStatus | 无空阶段条目；原版运行句；todo/milestone/load/evict、任务指导、intent/reasoning 共用适配 |
| S4 Details 表现 | done | ProcessPanel.ActivityTimeline、semantic 与局部样式，提取原版筛选/定位结构 | 连续阶段底色、时间、Thinking 等筛选与行动跳转；LiveStatus 样式不受影响 |
| S5 Turn 入场 | done | ChatView、ConversationRows、turnController、turnStore/interactions、useConversationScroll | echo 到正式输入位置与节点连续；首轮、下一轮、queued、追加与回复各归其位 |
| S6 联调与复核 | done | 定向测试、浏览器动态检查、完整门禁、文档与进度记录 | 六个用户关注项逐条验证，并再次对照原版组件后归档 |

允许 S3 的纯表现部分与 S5 独立推进，数据接口以 S2 契约为准。改动尽量落在现有模块；不新增通用活动平台、第二套运行状态机或全站布局重构。

## 7. 验收与验证

### 7.1 关键行为用例

- 只有阶段边界而没有语义活动时：抬头与计时正确，Activity 不生成三条空记录，不保留空 Activity 区块。
- 初始 Home/Memory 装配可在 Context Inspector 看见，但 LiveStatus 不显示初始 Loaded；Phase1 真正应用 load/evict 后出现一次明确资源条目。
- set/remove todo 与 milestone，todo 完成/取消，正常拒绝一次无效操作：活动准确，WorkingZone 与 owner 一致；milestone 不被默认展示为已完成任务。
- Phase1 有 intent 而无 reasoning、两者都有、两者同文、域选择被拒绝：Thinking 筛选可读，顶部仅含 reasoning，来源与接受状态准确，无重复域选择行。
- 一个 Phase1 内多条控制、随后 Phase2/3、再一个 Cycle：同一连续阶段底色无间隙，不跨 Cycle 合并；筛选和展开后仍成立。
- 任务 Skill 在相同 task 的 provider 重试不刷重复条目，Background 与任务指导的资源标签风格一致、含义不同。
- 初始发送尚未回执、已回执尚未读到 interactions、Observation 先到、正式输入到达：全过程只有一个初始气泡、位于 Agent 区域之前，身份和位置连续。
- 连续两轮、活动中排下一轮、追加、回复、发送失败：没有跨 Turn echo，无重复淡入；历史恢复和 reduced-motion 不重播新轮动画。

### 7.2 验证方式

后端在 Context owner 测试覆盖成功安装/拒绝与 scope；Loop 测试只验证 Phase 结果披露的协作边界；Endpoint 用代表性事件验证传递，不重复建立同一业务契约。

前端纯适配测试覆盖事件去重、一对多语义项、域选择确认、阶段归属与分组。组件测试重点检查实际内容、来源、DOM 顺序和节点连续性，不只统计气泡数量或固定可编辑文案。

浏览器联调继续使用真实 Agent/Endpoint 与脚本模型。延迟回执/交互读取用于观察正常异步阶段，逐帧采样从点击发送开始，而非等待卡片出现后才开始。检查气泡与卡片的相对位置、一次停泊、展开/折叠、阶段底色连贯性、明暗主题与窄窗。脚本模型提供真实 control calls，不能通过伪造成功事件绕过 Context 安装。

实施期间运行相关聚焦测试和 Fast；宣告实施完成前运行 Python Full、ty、前端完整测试、TypeScript、构建与上述浏览器检查。外部 provider/network 不作为本地验收的必要步骤。

同步文档：`docs/endpoint/events.md`、必要的 runtime/契约样例说明、`docs/design/context.md`、`visualization/docs/design/chat.md` 与 `visualization/docs/plans/` 中的执行记录。已有归档计划保留为历史，不改写成此次问题已经完成的证明。

## 8. 实施与基线复核

以下是本轮对应实现，不以先前归档记录代替验证。

| 步骤 | 实际实施与复核 |
|---|---|
| S1 | 对照 c479ca0 的 `derive/chat.ts`、`components/chat/TurnView.tsx`、`LiveStatus.tsx`、`ActivityStep.tsx` 和 `TurnTraceDrawer.tsx`。修改前用真实 Endpoint 延迟提交复现首轮 sending 气泡不可见；旧代码把后续新轮 echo 放在上一轮 Agent 内。修复后验证首轮/连续轮次的节点、上下顺序和停泊。 |
| S2 | `ContextEngine.consume_signal_batch` 仅在 install 后发布 normalized control 的 applied 观察；顺序和 scope 保留。控制模块负责紧凑投影，Loop 完成事件披露控制反馈。消费返回值仍仅含失败；无新增持久记录或业务状态机。 |
| S3 | `ActivityBuffer` 一处解释事件，支持同一响应的 reasoning/intent 多条语义项；阶段边界不再生成空条目。还原三阶段运行句，阶段结束计时停止；任务指导和 Background 复用 LinkChip。Working 仍从 owner 读取。 |
| S4 | `ProcessPanel.ActivityTimeline` 恢复原版筛选、倒序、时间与行动入口；连续阶段容器使用淡底色，先分组再筛选。共享 ActivityStep，LiveStatus 不增加阶段底色。 |
| S5 | `ChatView` 顶部初始槽使用同一 UserBubble，回执绑定的本地 key 延续至正式/Session 投影。新轮 echo 不再渲染于 CurrentTurnControls，排队项不显示运行卡。滚动目标使用槽身份；追加、回复、等待和失败入口保留。 |
| S6 | 已同步 Context/Workspace 设计、Endpoint events、前端 Chat 设计及实施记录；完整门禁与逐项复核通过，计划归档。 |

与原版的具体对照：

- 原版的用户气泡 → 单一 Agent 列 → LiveStatus/回答布局保持；入场修正的是 v2 异步数据的槽位和挂载身份，没有继续叠加动画参数。
- 20px 顶部停泊、700ms 缓出、LiveStatus 滚动节奏、完成折叠/回答流入参数保持。浏览器逐帧测量同时覆盖入场与结束，不能仅以最后一帧正确判定恢复。
- 恢复原版阶段运行句及 intent/域标签阅读；intent 加入 Thinking 筛选，但不进入顶部 reasoning 条。长 intent 可就地展开。
- 原版显式控制操作的语义由 v2 安装成功观察承接；初始 Home/Memory 快照继续服务 Context Inspector。milestone 保留事实寄存器语义，不复活旧版的伪完成状态。
- 新增连续阶段底色仅在右侧 Activity；浅色、深色与 800px 窄窗已截图核对。

### 验证记录

- Kernel Fast：336 passed，覆盖安装成功、批次准备失败后重放、控制拒绝、六类控制的顺序与 scope、owner 刷新不混入、Phase 完成反馈。
- 浏览器真实 Agent/Endpoint + 脚本模型：2 条流程通过，包含连续会话、初始 sending→回执→正式节点不变、思考与 intent 区分、todo/milestone/load 真实控制、Details 阶段区段无间隙、筛选、明暗/窄窗、Context 与模型抽屉、完成动效和 Session 接管。
- TypeScript、Vite 与 ty 已通过；Vite 仍有既有的大 chunk 提示。
- 前端全量：90 个文件、808 项通过。Python Full：1226 passed，25 deselected；TinySoul Python 3.13.12、ty 0.0.84 通过。TypeScript/Vite 最终构建通过。

### 门禁发现的相邻观察缺陷

两次 Full 在既有 Workspace 等长编辑观察用例漏掉 edit 事件，独立运行通过。分析确认正式写入仅依赖 manifest 差异，文件大小与时间戳相同时会漏发通知。S6 补充修正 `WorkspaceChange`：由成功 mutation 结果提供实际写入 Link，和 manifest 差异共用一个变更投影；Observation 与合并后的环境事件统一使用它，不新增日志、哈希或重试。固定时间戳的真实文件回归同时覆盖 edit/bundle 和环境事件合并；Workspace 78 项及 ty 通过。设计与 Endpoint 文档已同步。

截图保留在忽略目录 `visualization/.local-test/playwright-output/`，可运行 `test/e2e/chat-flow.pw.ts` 重建。旧历史缺少 applied 观察时仍只展示留存事实；本轮不补造过往控制活动，不验证外部供应商网络。
