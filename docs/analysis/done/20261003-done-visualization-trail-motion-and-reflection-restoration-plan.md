# LiveStatus 滚动与 Reflection 对话呈现恢复计划

状态：`done`。2026-10-04 完成实施、基线对照、契约同步与必要验证。

2026-10-03 确认补充：用户再次体验后确认动作卡片滚动正常，本项调整为对照 c479ca0 核查；没有明确复现证据时保持现有动画实现，不进行预防性修改。

2026-10-04 补充核查：比较结果卡片的展开节奏，确认活动从顶部插入、旧行仅向下移动，落位后不自动改变高度或重新定位。手动展开/收起、窗口宽度变化和整轮结束收束保留各自明确交互语义。

日期：2026-10-03。代码复核基点：`c741252`。视觉与交互基线：`c479ca0`；正式数据与接口契约：v2。

## 1. 目标与边界

本轮继续在最新代码上恢复 c479ca0 已打磨的交互。保留当前更丰富的动作预览内容，重点检查滚动几何、预览生命周期，以及缺失的 Reflection 入口和对话呈现。原版已有结构优先直接提取并适配；不以反复调整时长、淡出阈值或增加一套动画状态机代替原因分析。

已恢复的当天连续 User Turn、输入气泡身份、入场锚点、回答收束动效、intent/Selected domains 分离、Thinking 筛选、Context 控制执行事实、Details 阶段底色和 Todo 标签均为保留项。

Reflection 是同一 Agent 的独立根 Turn。Chat 可以呈现它的运行过程，但不把它变成用户输入或正式回答，不写入 User Session，不改变整理授权、来源选择、持久写权限与根队列调度。

## 2. 实施前复核与诊断证据

### 2.1 动作卡片滚动

基线依据：`c479ca0:visualization/src/components/chat/LiveStatus.tsx`、`ActionGlimpse.tsx`、`ChatView.tsx`，以及 `hooks/useOverflowing.ts`、`styles/index.css`。

原版设计是普通文档流中的顶部插入，不是把卡片逐个移出队列的轮播：

- 释放游标按实际活动顺序逐条推进，新行从高度零展开，旧行被整体向下推。
- 普通动作分两拍：行先落位，预览随后展开；快速释放时预览提前展开。
- 预览一旦展开，就保持在该行中，即使进入底部渐隐区域也不自动收起。用户手动收起是独立操作。
- 视窗限制为 16rem，已达到的高度不自动收缩；渐隐 mask 在首次溢出后保持。
- 渲染窗口保留 14 行，其目的正是让淘汰发生在裁切区之外。边界上的半张卡片仍在正常布局中。
- Turn 完成沿同一个 LiveStatus 节点收束；主动展开全部轨迹属于另一次用户交互。

当前 `features/chat/LiveStatus.tsx` 已保留上述大部分骨架，包括 14 行窗口、释放节奏、展开集合、底部 mask 与高度下限。没有 IntersectionObserver 或“刚离开可见区就删除”的分支。`useOverflowing` 与原版无差异；`Crossfade` 的差异仅为注释。

当前 `ActivityGlimpse` 与原版仍有可核对的结构差异：原版预览有 `grow-in` 包装，外层高度动画使用统一 `EASE_CALM`；当前预览直接包裹 Crossfade，并使用另一处默认 transition。此差异尚不能单独证明用户观察到的回退原因。

本次在真实 Chromium、关闭 reduced-motion 的条件下做了独立组件诊断：

| 输入场景 | 结果 |
|---|---|
| 18 条无预览的短行，间隔约 1.3 秒 | 可见行未回退；被删除行在 256px 视窗以下 |
| 18 条具有命令预览的动作，间隔约 1.3 秒 | 可见行未回退、未缩高；旧行移除前位置约在视窗顶下 1260px |
| 32 条命令预览短时间连续到达，触发快速释放 | 可见行未回退、未缩高；视窗 scrollTop 保持零 |

结论：没有发现“底部可见性判断直接删除卡片”的实现或复现证据。用户再次体验后确认滚动正常，本轮不再把偶发观感当作已确认缺陷；重点核对原版结构、预览节奏和真实浏览器几何。当前预览展开恢复原版 `EASE_CALM` 与 `grow-in` 包装，保留 350ms 外层展开、400ms 延后展开以及原版深窗口和裁切机制。

诊断脚本留在忽略目录 `.local-test/trail-motion-diagnosis.mjs`，仅为本次分析辅助；正式验收应落入仓库的浏览器验证，而非依赖该本地文件。

### 2.2 Reflection 缺失的链路

| 位置 | c479ca0 行为 | 当前事实 |
|---|---|---|
| `components/shell/TopBar.tsx` | 工具图标与 Maintenance 入口，待整理时提示 | 仅 History、Context、Restart，整理入口缺失 |
| 原版 `components/chat/TurnView.tsx` | 右侧中性气泡，工具图标、Home/Memory、目标日与触发方式；下方复用 LiveStatus 和 Details | 当前 ConversationTurn 依赖用户初始输入，没有整理来源气泡 |
| `features/chat/turnController.ts` | 原版派生视图能呈现维护 Turn | 当前 `syncFromStatus` 只让 `user_turn` 接管活动视图 |
| `app/connection.ts`、`presentationStore.ts` | 活动属于各自 Turn | 当前仅向所显示的 User Turn 缓冲投递活动，Reflection 事件主要触发 status 刷新 |
| `features/resources/ReflectionDialog.tsx` | 提交后回到可见的维护过程 | Home/Memory 页面可以提交，但回执只引导到 Runtime；没有加入 Chat 的过程链路 |

这不是后端不能运行 Reflection，而是前端恢复时仍保留了只展示 User Turn 的假设。

### 2.3 v2 已有支持与需要补齐的事实

已有支持：

- `POST /v2/reflection` 提交一次明确授权；Home 使用 instructions，Memory 必须指定 target_day。
- `GET /v2/turns/{id}` 返回正式状态、问题、预算、取消意图和结果；reply/grant/cancel 复用同一 Inbox。
- Reflection 内核 Turn ID 使用 request_id，与请求回执及 scope 能关联；生命周期事件 `reflection.started/completed` 本身不一定带 Turn frame，不能简单归给当前显示轮。
- `/v2/events` 可按 turn_id/task_id/call_id 读取 Phase、Action、ModelCall；ProcessPanel 已具备复用条件。
- 活动 Context 接口遍历 profile 寻找所属 Turn，不限 User。完成后的 Reflection interactions 返回结果和空正文，不进入 Session 接管。

实际缺口：

1. status 只发现活动与排队身份，没有列出近期已结束、仍保留的 Turn。刷新时前端无法通过正式目录找回这些 Reflection。
2. TurnSnapshot 缺少 Reflection 的 trigger、target_day 与请求摘要，也未暴露 owner 的日期绑定和时间信息。仅靠本窗口回执，无法完整显示从 Terminal、定时来源或另一前端发起的整理。
3. Session 目录有正式顺序，但没有供跨来源显示定位的时间字段；不能把“整理发生日”误用成 Memory 的历史目标日。
4. 前端 `TurnResult` 主要按 User 结果声明，`deriveTurnStatus` 把未知终态视为 answered。Reflection 的 completed/partial/skipped/awaiting_user/exhausted 等需要准确展示。
5. Home 无差异时，`HomeReflectionTask._prepare` 会清理可清理的 overlay 并返回 skipped，不一定进入模型 Turn。当前弹窗“无差异仍可整理 accepted content”的说明不准确。

## 3. 滚动对照范围

本节保留原始诊断方法与行为准则；按确认后的范围，只恢复有代码依据的预览入场差异并验证几何，不新增可见性淘汰、位置补偿或冻结布局状态。

### 3.1 先确定发生回退的层级

在完整 ChatView 中接入可控 v2 事件流，逐帧记录同一 step ID 的：视窗相对位置、行高、预览高、视窗高度与 scrollTop，以及外层 Chat 滚动位置。覆盖命令/输出、搜索结果、diff、短 thinking/intent、域和资源标签的混合序列，普通释放与快速释放都检查。

同时记录该行挂载/卸载、glimpse 展开状态及数据内容的变化，区分以下原因：行过早淘汰、预览被撤回或重挂载、父子高度动画相互影响、外层跟随把局部滚动变成回退。每种判断都需要对应几何或节点证据。

### 3.2 以原版布局契约修复

1. 保留单一顶部插入文档流，继续复用原版释放游标、两拍展开和快速释放机制；不另建绝对定位轮播。
2. 将原版 ActionGlimpse 的入场包装与配套动效作为优先复用对象，接入当前 v2 预览正文。是否替换某层动画，由第 3.1 节的对照决定，避免未经测量叠加两层高度补偿。
3. 动作计划正文来自该次 call，结果正文来自独立 result；execution 只更新紧凑状态标记，不以结果替换或撤走旧计划预览。重投影保持 step 身份及手动展开状态。
4. 预览滚入渐隐区时不收起、不清空、不改成紧凑占位；底部使用统一视窗裁切与空间渐隐，保持半张卡片可见。
5. 只在视窗之外回收旧行。优先保留原版深窗口；检查项目支持的字号/缩放后，如果 14 行不足以覆盖裁切范围，再以实际行几何补足离屏余量，不加每张卡片的可见性开关。
6. 视窗高度上限与 never-shrink 下限使用同一尺寸依据，避免 CSS 的 rem 与 JS 的固定像素在字号变化后各自解释。
7. 固定内容且无用户操作时，已落位旧行相对视窗只保持或向下移动。主动展开/收起、布局宽度改变和整轮完成收束是明确例外，不能用此约束冻结所有交互。
8. 自动淘汰与点击 Show all/fewer 分开；Show all 保留原版紧凑披露意图。reduced-motion 直接得到正确布局；完成折叠不重复挂载可见行。

本项以核对原版并验证上述行为为完成标准。未复现的偶发问题不宣称已定位或已修复，也不增加额外缓存、观察器或状态对象。

## 4. Reflection 的界面与数据方案

### 4.1 恢复入口，共用现有请求表单

- TopBar 恢复原版工具图标和紧凑按钮，界面名称为“整理”；窄屏使用带明确 accessible label 的图标入口。
- 弹窗以 Home / Memory 切换呈现。复用当前 ReflectionDialog 的 owner availability、Memory 日期分页、整理要求与提交逻辑，不保留第二套 Maintenance 请求表单。
- Home 展示待审核差异和 Skill memory 数量；Memory 展示来源日期，区分“可再次整理”和“缺少 daily”。不把可选历史日数量显示成必须完成的任务总数。
- 提交成功后关闭表单，并在主对话定位对应整理气泡；Home/Memory 页面通过同一个表单执行相同跳转。Runtime 保留运行总览职责。
- 文案准确说明 Home 无待审核差异时会跳过；单次操作不授予持续许可。队列等待仅在确实需要时显示简短状态，不增加用户输入模式选择。

### 4.2 提取原版特殊气泡与收束结构

直接提取 c479ca0 TurnView 的维护气泡结构：右对齐、中性淡底色、细边框、工具图标，不使用普通用户输入的强调色。

气泡主要内容示例：`Home 整理  手动`；`Memory 整理  2026-10-02  自动`。Memory 日期表示来源，运行位置属于执行日。用户提供的整理要求显示短摘要，长内容就地展开；不把后端内部整理提示写成用户消息。

气泡下方复用 AgentRow、LiveStatus、WorkingZone 与 Details：

- 排队只显示等待状态；preparing/running/waiting 由正式 snapshot 决定，真实活动到达后展示思考与动作。
- 完成时同一 LiveStatus 节点收束。显示“整理完成”“无须整理”“部分完成”“需要进一步指示”等正式结果，不播放普通用户回答的打字终端动画。
- 读取 `tasks[].turn.completion` 中实际可读的完成总结；优先展示本次任务的结果和必要失败说明，结构化 details 按实际类型做简短呈现，完整数据留在 Details。
- 跳过或执行前取消可能没有模型/Phase 事件，这时不展示空的思考过程。
- Details 使用同一 Process → Action → ModelCall → Context 导航，不创建 Reflection 专属 Trace 实现。

### 4.3 一套 Turn 投影，区分显示目标与输入目标

调整现有 turnStore / turnController / presentationStore，使 runtime snapshot 与活动缓冲按 Turn ID 组织；User 与 Reflection 共用读取、更新、Observation 关联和展示适配。Session 列表继续只保存 User Turn。不得复制出 ReflectionBuffer、ReflectionLoop 或另一套事件解释器。活动事件只为当前运行、最近收束或用户正在查看的 Turn 保留有界缓冲，历史详情按需读取；目录刷新不批量加载所有 Turn 的模型正文。

正式状态仍从 owner 获取；Observation 只提示刷新并提供活动正文。身份由 snapshot.kind 确认，不能根据当前页面、最近一个请求或 message 文案猜测。

当天 Chat 的显示列表合并：正式 Session User Turn、后端仍保留的 Reflection、当前根工作和本窗口尚未进入 Session 的 User 请求。按 Turn ID 去重；Reflection 完成后保留在原位置，直到离开所属日期或超出可恢复窗口。手动历史浏览不被新活动抢占。

Composer 的目标独立于“最近显示的卡片”：

- 活动 User Turn 仍按既有规则追加；Reflection 运行时输入创建独立 User Turn，由 Agent 排队，绝不 append 给 Reflection。
- 原 User 输入为空显示停止、有文字显示发送的交互不变。
- Reflection 的停止入口放在该整理卡的紧凑操作栏，明确标为“停止整理”或“取消本次整理”，按该 turn_id 请求取消；不恢复 User 气泡上的重复停止入口。
- Reflection 的 core.ask 与预算等待复用现有问答/补额组件，但所有操作显式绑定其 turn_id 和 question/request ID；不得通过当前 User store 隐式选目标。
- Reflection 进行中另有 User 请求时，两个节点各自稳定；运行跟随目标与用户主动定位分开，不能因 queued User 的读取覆盖 Reflection 的 LiveStatus。

### 4.4 v2 最小补充：现有句柄的只读投影

推荐补充后端，避免用完整 Observation replay 拼出一份正式任务目录。数据仍来自 AgentScheduler 已维护的有界 TurnHandle 集合。

| 补充 | 契约和消费用途 |
|---|---|
| `GET /v2/turns` | 当前 Agent 保留的 Turn 简要目录，覆盖 queued/active/finished。只投影 identity、kind、state、终态摘要、日期/时间及整理来源，不放模型正文、完整 result 或 Job 输出。User 与 Reflection 使用同一目录，不另建 Reflection 历史表。 |
| TurnSnapshot/目录的生命周期信息 | 暴露 handle 的 generation_id、active_day；增加 owner 记录的 accepted_at、started_at、finished_at。时间用 UTC ISO 文本；started_at 定义为根执行开始，包含准备过程，不冒充首次模型调用。queued 的 started_at/active_day 可以为空；完成前取消不编造开始时间。 |
| Reflection 来源 | kind 使用现有 home/memory；附 trigger、target_day。目录只给 instructions_excerpt 与 truncated；单 Turn 详情给原请求 instructions（沿用最多 16000 字符的现有上限），支持就地展开。请求来源由原 typed request 投影，不透传任意 metadata 或内部提示。 |
| Session Turn 目录的 recorded_at | 从已有 record.recorded_at_ns 投影提交时间，无新增 Session 持久字段。供已结束 Reflection 在连续 User 历史中的位置合并使用，不称作 Turn 开始时间。 |

目录复用现有保留上限与队列容量，返回一次有界快照及范围说明；不引入新的长期存储或独立分页游标生命周期。运行中详情继续 GET `/v2/turns/{id}`；等待、取消、结果和 jobs 不通过目录推算。

已完成 User 顺序以 Session 为准。完成的 Reflection 依 finished_at 插入对应的 Session 提交时间间隙；活动根工作放在完成记录之后，尚未运行的请求按受理顺序显示。active_day 决定日期归属，target_day 只决定 Memory 来源。新旧投影接管保留显示 key，避免重新入场。

句柄淘汰或 Agent restart 后，不承诺恢复已不存在的 Reflection 正式状态；已有 Observation 仅供留存 Trace 浏览。刷新可恢复的范围以正式目录为准。Endpoint restart 的事件保留与 SDK 句柄保留不是一回事。该限制应在历史/详情需要时表达，不给每个正常运行气泡添加说明小字。

这些元信息属于实际存在的 UI 消费，不进入模型 Context。SDK、Gateway protocol、HTTP schema、示例和前端类型同时对齐；Endpoint 不直接访问 scheduler 私有集合。

### 4.5 结果和 Context 的语义收口

- 按 snapshot.kind 与后端实际结果结构收窄 User/Reflection/request_failure，纠正当前所有 finished 默认 answered 的适配。未知终态只显示“已结束”，不标记成功。
- `awaiting_user` 的结束结果与 snapshot.waiting 的同轮等待分开；结束结果不能留下仍可提交的答题表单。
- Reflection 当前 Context 从所属 profile 读取；完成后不请求 Session 来冒充它的背景快照。已打开抽屉可保留明确标注捕获时点的只读内容，之后通过实际留存 ModelCall 查看当时 Context。
- Memory Reflection 的 Session map 如果呈现任务来源，应明确绑定 target_day；“今日 Session”仍属于执行日。抽屉标明来源，不能由全局 active_day 悄悄替换历史来源。
- Home/Memory 页面仍是 owner 资源浏览，前端查看不调用 Agent 的 read_top，也不制造加载副作用。

## 5. 实施顺序与状态

| 编号 | 状态 | 工作与完成依据 |
|---|---|---|
| P01 | done | 与 c479ca0 的 LiveStatus、ActionGlimpse、useOverflowing 和 CSS 对照。按用户复核结果收窄为结构与几何核查，未将未复现观感标为缺陷。 |
| P02 | done | ActivityGlimpse 恢复原版缓动与 grow-in；真实 Chromium 检查结果预览展开、底部半卡、稳定旧行、思考锚点快速释放和积压快速释放，未发现可见回退、缩高或提前移除。 |
| P03 | done | TurnHandle/Snapshot 投影受理、开始、完成时间、来源和日绑定；Scheduler/SDK 公开保留目录，Endpoint GET /v2/turns 与 schema 同步；Session 只投影已有 recorded_at_ns。 |
| P04 | done | turnStore 保存有界运行目录与独立快照，presentationStore/useTurnPresentation 共用按 Turn ID 的活动缓冲；ChatView 合并当天记录，Composer 不向 Reflection 追加，删除无消费者的 eventReplay.ts。 |
| P05 | done | TopBar 恢复整理入口，共用 ReflectionDialog；ReflectionTurn 提取原版中性维护气泡，复用 LiveStatus 和 Details，成功提交直接定位 Chat；Home 无差异说明与 owner 一致。 |
| P06 | done | Reflection 正式终态和 tasks 完成总结独立于用户回答；问题/补额/取消显式绑定 Turn；完成背景不退回 Session，Memory map 绑定 target_day。单元与真实 Endpoint 浏览器场景已覆盖代表路径。 |
| P07 | done | 后端 Fast/Full 与 ty、前端 808 项测试和生产构建通过；真实 Endpoint 的 Reflection、连续 User 会话、入场及独立动效场景通过。设计、Endpoint 契约和本计划已同步并归档。 |

主要实施位置：

- 前端：`features/chat/LiveStatus.tsx`、`ActivityGlimpse.tsx`、`ChatView.tsx`、`ConversationRows.tsx`、`adapters.ts`、`presentation.ts`、`presentationStore.ts`、`turnController.ts`、`useActivityDetails.ts`；`store/turnStore.ts` 与 `app/connection.ts`。
- 入口与资源页：`components/shell/TopBar.tsx`、`features/resources/ReflectionDialog.tsx`、Home/Memory 页；必要的 Trace/Context 和 Runtime 消费点随公共投影同步，不复制实现。
- 后端：`agent/handles.py`、`dispatch/scheduler.py`、`services.py`、SDK 门面；`plugins/session/views/inspection.py`；Endpoint engine/protocol/routes/schemas。尽量在现有职责中扩展，不拆出无消费者的设施。
- 文档：`visualization/docs/design/chat.md` 及受影响的资源/运行设计；`docs/design/agent.md`、`docs/design/endpoint.md`、`docs/endpoint/runtime.md`、`reflection.md` 及相关 schema/示例。Reflection 的基本业务语义不变。

## 6. 验收与验证

### 6.1 浏览器动效

- 使用实际 React/Motion/CSS 和正常动画偏好，以计划/结果高矮卡片、思考条切换和密集到达作为代表路径，覆盖单条和快速批量。
- 可见旧行无非交互性向上回退，无自动缩高；底边可显示半张卡片，后续插入使它继续下移并自然渐隐。
- 新条目不使外层 turn 顶部漂移；用户主动滚动/展开仍能接管。沿用既有自适应与主题样式，浏览器连续会话同时检查既有窄屏和明暗主题视图。
- 手动收起不被重新自动打开；Show all/fewer、reduced-motion、同轮完成收束正确。
- 动效验证记录逐帧几何及截图；最终截图与 jsdom 测试不单独作为滚动行为依据。

### 6.2 Reflection 正常主线

- Home 手动整理、Memory 明确选择历史目标日、Terminal/定时来源启动：均显示正确来源气泡和同一套 LiveStatus/Details。
- 当前 User Turn 后排队 Reflection、Reflection 期间新建 User Turn：顺序和身份正确，正文、输入、停止、问题与预算不串轮。
- Reflection 完成或 skipped：卡片原位收束，结果文字准确，User Session 数量与内容不因整理而增加。
- Home 无差异可不产生 LLM 事件；界面显示无须整理及实际清理结果，不出现伪造 thinking 或空 Details 树。
- 刷新/重连恢复后端仍保留的整理；已淘汰事实不由 Observation 重建为正式结果。进入新日不把历史 Memory 目标作为执行日。
- Details 能从 Action 到 ModelCall，再查看真实请求 Context；Reflection 不误走 Session fallback。

### 6.3 必要检查

聚焦测试保护有界目录及元信息的 owner 契约、结果类型、前端显示/输入目标分离和代表性活动链路；复用既有 mock Endpoint、浏览器及 scripted provider 基础设施，不另建大套演示状态。

实施代码后依项目规约运行相关聚焦测试与 Fast；完成前运行：

```powershell
conda activate TinySoul
.\scripts\test.ps1 -Suite Full
.\scripts\typecheck.ps1
```

前端运行 `npm.cmd test`、`npm.cmd run build`，以及相关 Playwright 场景。新增 Endpoint 投影同步通过仓库现有契约生成/校验流程。最终按 P01–P07 和 c479ca0 组件逐项说明证据，不能把测试通过代替视觉核对。

## 7. 实施核对

后端仍由 Agent 调度 Reflection，目录来自既有保留句柄，不新增持久历史。前端恢复整理来源气泡、实时活动、等待交互、Details 与完成总结，复用 User Turn 的表现组件和 v2 读取设施。Reflection 结果不进入 User Session，不产生普通回答气泡；刷新只恢复后端仍保留的范围，重启后不凭 Observation 重建正式结果。

已同步 `docs/design/agent.md`、`docs/design/endpoint.md`、`docs/endpoint/{index,runtime,inspection,reflection}.md`、契约 schema/示例和 `visualization/docs/design/chat.md`。

| 核对面 | 实施与验证证据 |
|---|---|
| 原版预览节奏 | 普通行 420ms、预览延后 400ms、外层展开 350ms；恢复 EASE_CALM 与 grow-in。原版顶部插入、14 行深窗口、底部裁切、手动折叠机制保留。 |
| 抬头与思考联动 | 对照原版 LiveStatus 和 useThrottledValue：抬头/顶部思考共用 1500ms 节拍；reasoning 换段以该思考条目为快速释放目标，并非每次标题文字变化都清空队列。intent 仍只进入活动，不驱动顶部思考。 |
| 密集活动 | 保留普通 1100ms、快速 240ms 的逐条释放；达到 10 条积压先释放较早 6 条。正常帧检查记录快速间隔约 240–270ms，两条触发路径均通过。 |
| 几何与结果预览 | trail-motion.pw.ts 记录 2341 帧，42 条计划/结果及一个思考锚点；可见旧行回退、缩高、落位后改高、可见区域移除均为 0；视窗 scrollTop 始终为 0，半卡经过边界正常。 |
| Reflection 主线 | chat-flow.pw.ts 使用真实 Agent/owner/Endpoint 和 scripted provider：整理入口、等待问题、刷新恢复、回复、同节点完成折叠、Details → ModelCall Context、再次刷新均通过；User Session 数量不变。 |
| 目标隔离与无过程结果 | ChatView.test.tsx 覆盖 Memory 历史来源、User 排队时 Reflection 活动不丢失、回复/补额/取消绑定所属 Turn、partial 总结及 scheduled skipped 不伪造过程；contextDrawer.test.tsx 覆盖结束背景不走 Session fallback。 |
| 门禁 | Fast：1223 passed、30 deselected；Full：1228 passed、25 deselected；ty 通过。前端 90 个测试文件、808 项通过，TypeScript/Vite build 通过。真实浏览器四类场景均通过。 |

Full 工件：`.local-test/runs/42e894f607964b8fbb33c6335bb9a766`。浏览器动效记录和边界截图位于 `visualization/.local-test/trail-motion-output/`；Reflection 完成截图位于 `visualization/.local-test/reflection-output/`。这些均为可重建本地验证工件；正式验证入口保留在 `visualization/test/e2e/{chat-flow,trail-motion}.pw.ts`。

本轮删除未使用的 `features/chat/eventReplay.ts`，其活动读取职责由既有 readEventWindow 与按 Turn ID 的同一缓冲承担；没有另建 Reflection 事件解释器。滚动偶发问题未复现，不宣称已定位此类原因；改动只针对与原版明确不同的预览入场包装和缓动。
