# Visualization Chat v2 基线恢复与界面重构执行计划

> 建立日期：2026-10-01  
> 状态：`pending`  
> 视觉基线：`c479ca0`（35f1440 之前的 Chat、LiveStatus、Turn Trace 和滚动交互）  
> 数据与接口契约：当前 v2 Endpoint、owner snapshot、Session、Context 和 Observation  ���  
> 当前实施路线：在最新代码上直接重构，旧提交只作为表现层参考，不恢复 v1 API 或 v1 状态模型。

## 1. 目标与边界

本轮工作恢复 c479ca0 中已经打磨完成的主对话体验，并把它干净地接到当前 v2 数据和生命周期上：

- 每天的已完成会话连续显示在同一个 Chat 页面中，新 Turn 自然追加到当天会话末尾；
- running Turn 显示思考摘要、滚动动作轨迹、动作预览、Working 状态、计时和停止入口；
- Turn 完成后保留回答、问题/选项、追加输入和结果的层级与动画收束；历史内容不重复播放运行时动画；
- 从当前 Turn 打开完整的 Turn Trace，继续呈现 Cycle、Phase、Action、LLM Task、专用模型调用、Job 和必要的结果细节；
- 右上角 Context 变为统一 Inspector，按子页查看当前安装 Context、Session map、当前 Turn 实际加载的 Home 和 Memory；
- 设置、Home、Memory、Workspace、Runtime、Resource Router、Search 和 CodeBlock 等已有 v2 页面继续复用，不被 Chat 恢复工作重新建立一套数据或导航模型；
- 设置页最后统一中文显示，但稳定的 action id、provider id、模型 id、Link 和协议字段保持原值。

本轮明确不做以下事情：

- 不恢复 `/v1` HTTP/WebSocket 接口、旧 `protocol_version=1` 握手或旧事件回放状态；
- 不恢复旧 `appStore`、`derive/chat` 作为业务事实来源；
- 不由浏览器推导 Turn、Action 或提交状态，不让 Observation 覆盖 owner snapshot；
- 不为当前 UI 增加新的通用 Action 状态机、第二个 Session owner 或长期事件日志；
- 不把 actual/effective Home 浏览和 Agent 运行时 `read_top()` 混为同一条路径。

## 2. 当前事实与问题定位

### 2.1 LiveStatus 没有事件输入

v2 Observation 的父级关系由 `scope` 表达，事件没有稳定的顶层 `turn_id`。当前 [connection.ts](../../visualization/src/app/connection.ts) 和 [activityBuffer.ts](../../visualization/src/features/chat/activityBuffer.ts) 读取 `event.turn_id`，导致真实的 Phase、Action、模型和 Working 事件被忽略。

当前 `LiveStatus` 的主要滚动轨迹、思考流、动画节奏和 Working 区域仍然存在，缺少的是正确的事件身份适配和真实事件 fixture 覆盖。

### 2.2 Chat 只显示一个 Turn

当前 `ChatView` 根据 `turnStore.turnId` 在 `DayEntryList` 和 `ConversationView` 之间二选一。`sessionTurns` 只作为历史入口列表，打开一个 Turn 后其它当天 Turn 不再显示，所以用户必须返回历史才能看到当天已有内容。

v2 已提供 `/v2/session/turns` 和 `/v2/session/turns/{turn_id}`，问题属于前端缺少当天只读会话投影，不是缺少 v1 接口。

### 2.3 Context 与 Trace 入口层次不完整

右上角 Context 当前只打开当前 Turn 的 installed Context overview；Session map 仍在 History 内，已加载 Home/Memory 没有在同一 Inspector 中形成可切换子页。

当前 `features/trace` 已拥有 Process、Action、ModelCall、Search 和 Job 面板，`ModelCallPanel` 也能读取 v2 `mode=model` 事件并展示 provider-neutral messages/provenance。需要恢复的是旧版 Trace 的主呈现层级和进入路径，而不是重新实现模型调用接口。

### 2.4 存在重复的 Chat 表现入口

`features/chat/TurnView.tsx` 当前没有生产引用，并且包含与 `ChatView` 不一致的简化表现逻辑。完成迁移后应删除它，或将其改造成唯一的 TurnCard 内部组件；不得保留两个可独立演化的对话表现模型。

### 2.5 现有测试没有覆盖真实事件形状

部分测试使用了带有顶层 `turn_id` 的宽松事件对象，因此能通过类型检查和单元测试，却无法发现真实 v2 `scope` 事件无法进入 ActivityBuffer 的问题。本轮必须使用真实契约 fixture 验证。

## 3. 实施路线决策

采用“最新代码直接重构”路线：

1. 以 `c479ca0` 只读提取 ChatView 的布局、滚动锚点、动画节奏、LiveStatus、ActivityStep、ActionGlimpse、回答收束和 Turn Trace 的视觉行为；
2. 在当前 `visualization/src/features/` 中继续使用 v2 client、turnStore、connectionStore、Inspector、owner snapshot 和 typed API；
3. 建立明确的 v2 presentation adapter，把正式事实和短生命周期 Observation 映射为旧版组件需要的表现类型；
4. 必要时可以从 c479ca0 建立临时 worktree 做截图或交互对照，但该 worktree 不作为第二个实现分支，也不合并旧 v1 API、旧 appStore 或旧事件推导层。

选择该路线的原因是当前代码已经包含 v2 的设置、资源、Home/Memory、Runtime、Trace 和 Inspector 能力。直接恢复旧完整前端会同时引入旧协议和新协议的权威冲突，增加合并复杂度，并形成 AGENTS.md 禁止的第二套状态模型。

## 4. 统一数据流

```text
v2 TurnSnapshot / InteractionPage
        │
        ├── TurnPresentation ──┐
        │                      ├── TurnCard / Answer / Question / Budget
v2 Session turn pages ────────┘

v2 ObservationEvent
        │
        └── turnIdOfObservation → ActivityBuffer → ActivityPresentation
                                             └── LiveStatus / ActionGlimpse

v2 Process / Action / Model / Job reads
        └── Trace projection → Turn Trace Inspector

v2 Context overview + Session map + installed refs
        └── Context Inspector tabs
```

正式的 Turn、Session、Context 和 Job 数据决定内容与状态；Observation 只提供 running Turn 的过程细节和动画输入。连接重建、事件 gap、页面切换或历史读取失败时，界面保留已知内容并通过 owner snapshot 恢复，不从 Observation 拼造缺失结果。

## 5. 分阶段执行计划

### P0：基线清单与数据契约冻结

- 从 c479ca0 对照提取主对话需要保留的行为：连续 Turn、用户气泡、回答卡、问题卡、LiveStatus、动作预览、滚动锚点、回答打字/收束、手动滚动接管、Trace 入口和 reduced-motion。
- 对照当前 `features/chat`、`features/trace`、`api/v2` 和 `store`，标出已可复用、需要接线、需要重写和应删除的代码。
- 明确当前计划不把旧组件名称当作 v2 协议；所有组件输入先经过 v2 presentation 类型。

验收：形成一份实现清单和代表性页面状态，能够逐项说明每个旧行为的 v2 数据来源。

### P1：修正 Observation Turn 识别

- 在 v2 events API 层增加统一的 `turnIdOfObservation(event)` typed helper；优先读取 `scope` 中 `level="turn"` 的 frame，只有契约明确提供时才使用 payload fallback。
- `connection.routeEvent`、`ActivityBuffer.addEvent` 和 `ActivityBuffer.loadEvents` 全部使用该 helper，不允许在组件内直接读取动态字段。
- 没有 Turn scope 的全局事件继续用于状态/快照失效通知，但不附着到当前 Turn 的活动轨迹。
- 使用真实 `model-observation.json`、包含 Turn scope 的 verbose 事件以及无 Turn scope 的全局事件补充单元测试。
- 验证正常运行时 Phase headline、thinking、ActionGlimpse、Working 状态、计时和停止按钮均能由 v2 事件驱动。

验收：真实 v2 事件进入当前 Turn 的 ActivityBuffer；不再依赖不存在的顶层 `event.turn_id`；事件 gap 后可以通过 replay 重建有界活动窗口。

### P2：建立当天连续会话投影

- 在现有 turnStore 或同一 chat feature 内增加只读的 `DayConversationProjection`，不建立新的执行状态机。
- 使用 `/v2/session/turns` 获取当天正式 Turn 顺序，再按需要读取 `/v2/session/turns/{turn_id}` 的正式交互正文；以 owner 返回的顺序和 Turn identity 合并，不按网络返回时间排序。
- 当前活动 Turn 使用 TurnSnapshot/InteractionPage 实时投影；完成后由 Session 正式正文接管，同一个 Turn ID 不重复渲染。
- 历史 Turn 只读，不显示 Composer、停止、追加、回复或预算操作；当前活动 Turn 保留追加、回复、预算和取消等既有语义。
- 将 c479ca0 的多 Turn ChatView 滚动容器、顶部锚点、底部留白、自动跟随、手动滚动接管和“有新内容”提示接回当前 v2 projection。
- 已完成 Turn 只显示 settled 内容，不重新播放 LiveStatus、回答打字或入场动画；新 Turn 追加时只对新增内容执行动画。
- 首先复用现有逐 Turn 读取接口。只有真实本地联调证明请求数量造成明显延迟时，才设计由 Session owner 提供的有界批量正文读取接口，不把多个 Turn 合并成新的持久事实。

验收：同一天完成多个 Turn 后，主对话页面连续呈现全部交互；新 Turn 能自然追加；刷新页面仍从 Session 恢复完整正文；打开旧日期仍保持只读历史体验。

### P3：恢复 c479ca0 Chat 表现层

- 将旧版 `TurnView` 的表现行为拆成当前 v2 可复用的 `TurnCard`、`ConversationTurn`、`LiveActivityCard` 和 Answer/Question/Result 子组件，避免把约 900 行逻辑重新集中到一个组件。
- 保留用户消息、Agent 回答、等待问题、选项和 Other 输入、预算请求、pending item、queued request、outgoing echo 及错误收束。
- 复用现有 `LiveStatus`、`ActivityStep`、`ActionGlimpse` 和 motion utilities，恢复流光标题、thinking 摘要、动作上浮/滚动轨迹、Working 区域、计时与停止反馈。
- 恢复 terminal → document 的回答转换、settle 动画、最新 Turn 进入时的锚定和用户手动滚动后的接管规则。
- 生产代码中只保留一个 Turn 表现入口。确认没有引用后删除 `features/chat/TurnView.tsx`，并清除对应死代码和测试，不以兼容别名保留第二套渲染逻辑。

验收：空会话、连续多 Turn、running、waiting question、budget、completed、failed、cancelled、reduced-motion 和刷新恢复等状态均保持清晰的层级和动效。

### P4：恢复 Turn Trace 主呈现

- 以当前 `features/trace` 为唯一 v2 Trace 数据入口，把 ProcessPanel 的 Cycle/Phase/Action 结构组织成旧版 TurnTraceDrawer 的主层级。
- Overview 区显示当前 Turn 的阶段、动作数量、模型调用、Job 和必要的摘要；Working、控制操作和 Activity timeline 作为可展开区域。
- Action 行继续进入 ActionDetailPanel；LLM/JEV/Embedding/Search 行进入 ModelCallPanel；Job 行进入 JobPanel；不复制这些 owner 面板的数据或状态。
- LLM Task 详情使用 v2 `mode=model` 事件中的 provider-neutral MessageStack、provenance、tools 和 response。模型上下文是某次模型调用的详情，与右上角当前 Context 分开命名和导航。
- 保留 truncated、missing、cancelled、not executed、unknown result 等诚实状态；JSON 只作为详情中的次级展开，不作为主视觉。
- Trace 面板关闭或切换 Turn 后释放读取句柄，不能继续显示另一个 Turn 的 late response。

验收：从当前 Turn 的 Details/Trace 入口可以看到完整 Cycle/Phase/Action/Model/Job 层级，并能进入对应模型消息上下文；历史 Turn 的 Trace 只读且不伪造实时状态。

### P5：重做右上角 Context Inspector

右上角按钮打开一个统一 Inspector，并提供以下子页：

1. **当前 Context**：读取 `/v2/turns/{turn_id}/context`，按 Background、Trace、Working 显示已安装段；点击段后读取已安装消息，不用最新 owner 内容替换当前快照。
2. **Session map**：读取 `/v2/session/map`，展示当天语义地图和交互入口；只读，不把地图变成前端自己的导航状态。
3. **已加载 Home**：从当前 Context 的已安装 refs 中筛选 Home 引用，展示实际加载的片段和 Link；打开详情继续使用 Context inspect 或已安装消息。
4. **已加载 Memory**：同样只展示当前 Turn 实际加载的 Memory 引用和片段，不把整个 Memory catalog 当作已加载内容。

没有活动 Turn 时，当前 Context、已加载 Home 和已加载 Memory 显示诚实的空状态；Session map 仍可按当前日期读取。actual/effective Home 的完整浏览属于 Home 页面，Agent runtime 的 `read_top()` 不由此 Inspector 调用。

LLM 调用上下文从 Trace 的模型行进入 ModelCallPanel，不与当前 Context 子页合并。Context generation 只在后端明确发布 Context 安装/背景变更事件后提示刷新，读取失败时保留最后一次已捕获视图并标记来源。

验收：右上角 Context 能在四个语义明确的子页之间切换，显示内容与当前 Turn snapshot、Session owner 和已安装引用一致；不会把 actual/effective、runtime Home copy、LLM MessageStack 混在一起。

### P6：设置页中文化与视觉收口

- 将用户可见的 Settings 分组、页面标题、按钮、提示、状态、错误和空状态翻译为简洁中文。
- 保留 provider/model/action/task/endpoint、Link、scope、profile、catalog value 等协议标识；必要时提供中文说明，不翻译稳定 ID。
- 不改变现有批量草稿、Apply/Discard/Reset、generation reload 和未应用草稿保护逻辑。
- 继续使用 c479ca0 的 Luminous 明暗主题、领域色、边框光泽和 motion token；删除重复标签、无意义 JSON 展示和只为说明架构而存在的小字。
- 对 Chat、Trace、Context、Settings 做一次视觉收口，优先恢复主对话的成熟层级，再补充 v2 信息。

验收：设置页主要用户路径中文可读；技术标识仍可复制和定位；草稿、批量应用、失败回滚和 reload 行为不变。

### P7：真实联调、门禁与文档收口

- 使用本地 `127.0.0.1:1430` 连接真实 v2 Endpoint；远端仅在已有隧道/转发存在时替换 IP:Port。
- 至少验证以下正常路径：空会话、新 Turn、多 Turn 连续显示、追加输入、问题选项、预算等待、LiveStatus、ActionGlimpse、ModelCall、Context 四子页、Session map、Home/Memory loaded refs、刷新恢复和历史只读。
- 为事件身份、当天会话合并、动画不重播、Context 子页来源和旧 Turn 不被新 Turn 覆盖增加 Vitest/组件测试；使用真实契约 fixture，不用宽泛的顶层字段替代。
- 运行 visualization 的完整测试、TypeScript 检查和 Vite build；如果本轮没有后端代码变更，不把前端测试结果冒充 Python 后端门禁；若新增后端接口，再运行项目要求的 Full 和 typecheck。
- 所有计划项、实现、测试、Endpoint 文档和 `visualization/docs` 记录逐项核对后，才将本计划改为 `done` 并移入 `docs/analysis/done/`。

## 6. 后端变更边界

第一阶段不需要恢复或新增后端接口。v2 已有的 Observation scope、Session Turn 正文、Context overview/segments/inspect、Session map 和 `mode=model` 事件足以支持本轮正常路径。

前端不能通过新增顶层 `turn_id` 复制 Observation scope 的父级语义。若 P2 的真实联调证明逐 Turn 读取不可接受，再提出一个由 Session owner 提供、带有界分页和明确顺序的批量读取契约；该接口仍然属于 v2，不改变 Session 的事实所有权。

任何实际后端契约调整必须同步 `docs/endpoint/`、`docs/endpoint/contracts/` 和前端 typed client，并通过真实 endpoint 验证后再继续 UI 实现。缺少能力时先记录到 `visualization/docs/demand`，不能在前端假定一个不存在的 v1 或写入接口。

## 7. 完成判定

本计划只有在以下条件全部满足后才能归档：

- c479ca0 基线中要求保留的 Chat、LiveStatus、连续历史、滚动和 Trace 行为在 v2 正常路径可用；
- v2 owner snapshot、Session、Context 和 Observation 的所有权没有被前端复制或覆盖；
- 右上角 Context 的四个子页来源明确，LLM MessageStack 与 Context 语义分离；
- 旧 `TurnView`、v1 API、旧事件 authority 和重复状态模型已经清除；
- 设置页中文化和视觉收口不改变批量配置语义；
- 真实联调、组件测试、TypeScript 检查和构建均通过，文档与实际实现一致。
