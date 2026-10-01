# Visualization Chat 基线恢复与 v2 对接改进执行计划

状态：`in_progress`

本计划建立在根目录 `AGENTS.md`、
`docs/analysis/20260928-visualization-frontend-implementation-plan.md` 和已确认的
前端重构方案之上。旧界面基线取 `35f1440^`（当前为 `c479ca0`）；
`35f1440` 之后的 v2 clients、owner snapshot、turnStore、Inspector、Home/Memory/
Runtime/Settings 页面和后端 v2 契约作为能力底座。计划不恢复旧 v1 API、旧事件权威状态、
旧导出接口或第二套 Action/Trace 状态机。

## 目标

本轮目标是把原有 Chat 和 Turn Trace 的成熟交互恢复到 v2 数据和生命周期之上，并继续承接
近期新增能力：

- 保留原 Chat 的会话历史层级、消息宽度、滚动锚定、过程折叠、LiveStatus、ActivityStep、
  ActionGlimpse、回答打字机和 terminal 到 document 的 settle 动效；
- 继续使用 v2 的正式 Interaction/TurnSnapshot/Session/Question/Budget/Pending/Echo 语义；
- 让运行中的活跃状态、活动时间线、Cycle/Phase/Action/LLM/Job 详情均由一套 v2
  presentation projection 呈现；
- 保留当前 Settings、Home、Memory、Runtime、ResourceRouter、Search 和 CodeBlock 能力；
- 将 Settings 的用户可见文字统一为中文，技术标识和协议值保持原样；
- 修正已确认的后端配置 catalog 契约缺口，并单独厘清 Home 顶层文档的 runtime 读取语义；
- 以真实后端、正常用户路径和基线视觉行为验收，最后同步前端文档与 review 结论。

## 明确边界

### 保留的旧体验

以下行为以 `35f1440^` 的实现和现有视觉文档为基线，不以当前 v2 Chat 的简化呈现作为新基线：

- 连续的当日会话历史和只读历史 Turn；
- 用户气泡、Agent 回答、等待问题、活动状态和最终回答之间的稳定层级；
- LiveStatus 的流光标题、thinking 概要、活动轨迹、working 状态、计时和停止反馈；
- running 到 settled 的同一卡片折叠、展开和新 Turn 开始后的自然收起；
- Action 的规划/执行两阶段摘要与有限内容预览；
- Turn Trace 抽屉中的 Cycle、Phase、控制操作、模型任务、Action 输入输出和活动时间线；
- 原有的 answer card、顶部跟随、用户手动滚动接管、恢复历史不重复播放动画等节奏。

### 不恢复的旧结构

- `src/api` 下的 v1 请求模块、`src/derive` 作为独立状态权威、旧 `appStore` 事件回放状态；
- `exportTrace`、任意旧路径兼容层或 v1 protocol_version；
- 前端自行决定 Turn/Action 终态、用事件覆盖 owner snapshot、或把完整事件流保存成第二份业务日志；
- 另建通用 action preview 或第二套 Action registry。

旧组件可以作为布局、样式和交互行为的移植材料，但必须改造成 v2 类型和 owner 读取的消费者。

## 当前事实与主要缺口

1. 根计划要求保留原 Chat 的消息、过程折叠、滚动和动效，但当前实施文档记录删除了旧
   `src/components/chat`、`src/components/trace` 和 `src/derive`。当前 `features/chat/ChatView`
   已有 v2 Interaction、Question、Budget、pending/echo、ActionGlimpse 和回答动画，缺少旧版
   LiveStatus 的完整活跃状态层和旧版 Trace 的主呈现层。
2. `features/trace/facts.ts`、`eventWindow.ts`、Action registry、ProcessPanel、ModelCallPanel、
   SearchResultView 和 JobPanel 已提供 v2 过程详情基础，但 ProcessPanel 的树形 Inspector 不能
   单独替代旧版主 Chat 中的活动轨迹、沉淀卡和 TurnTraceDrawer 体验。
3. WebSocket 已以 verbose 模式接收 ObservationEvent，当前连接层主要把事件作为失效通知，
   没有提供给 LiveStatus 的短生命周期活动投影。v2 事件已经包含 phase、action、execution、
   LLM、retrieval、context 和 working 所需的正常路径事实；需要先复用现有事件，再判断是否有
   缺失字段，避免新增 UI 专用 endpoint。
4. Home 的 Agent 运行时读取与 Endpoint 浏览读取保持两条有意分离的路径：
   - `AgentHomeEngine.read_top()` 使用 runtime read path。实际副本缺失时抛出
     `AgentHomeRuntimeCopyRequired`，由 Agent runtime copy handler 物化 runtime 副本并重试；
   - Endpoint 的 `browse_catalog/browse_content` 使用独立 browse projection：`actual` 读取
     actual 源，`effective` 只读取已存在的 runtime overlay，不调用 `read_top()` 或触发 copy。

因此，前端 `/v2/home/content` 的 effective 语义现在已经与双视图浏览契约一致；Agent 的透明
runtime 读取仍由 `read_top()` 和 recovery handler 负责。`home:agent@AGENT` 在 actual 目录可读，
未物化前不会出现在 effective 目录，前端无需重试或直接调用 `read_top()`。

## 可行性核对

本计划可行，原因和限制如下：

- v2 已有正式的 Turn/Session/Interaction/Question/Budget/Job/Resource 数据，能够承接旧 Chat
  的消息、历史、输入和结果层；不需要恢复 v1 的请求协议。
- v2 WebSocket 已提供 verbose ObservationEvent，`/v2/events` 已支持按 Turn 定向 replay；
  旧 LiveStatus 所需的大部分 phase、action、execution、LLM、retrieval、context 和 working
  事实已有来源。缺少的只是前端实时呈现投影，不是后端需要重新建立一套执行状态机。
- 当前 `features/trace` 已有事件解析、分页窗口、Action registry、Process/Action/Model/Job
  Inspector，可复用为旧 Trace 的数据和下钻层。需要补的是控制操作、消息栈和活动时间线的展示
  投影，不是第二套过程模型。
- P7 的 catalog 对齐和 P8 的 Home browse projection 已完成，均属于明确的小范围后端契约修正；
  浏览接口不触发 Agent runtime copy，架构上与现有 `read_top()` recovery 分离。
- 主要工作量集中在 Chat 呈现层移植和行为回归。旧组件代码可从 `35f1440^` 取得，但不能直接
  复制其 v1 imports；必须先改成 v2 presentation projection。这样可以恢复视觉基线，同时避免
  旧状态权威、旧事件回放和新 v2 owner 之间出现第二套语义。

实施依赖为 P0 → P1/P2 → P3/P4；P5/P6 可与 P3/P4 的稳定呈现并行；P7 先于 Home 页面最终验收，
P8 先于 Home demand 归档，P9 统一做真实页面和门禁验证。当前 F0–F6 的 v2 页面和基础设施已存在，
但 Chat 基线恢复和最终 F7 收口尚未完成，因此不能把当前进度标记为 done。

## 当前执行状态

- P7：后端 catalog choices 已完成并有 owner enum/catalog 回归测试。
- P8：后端 Home actual/effective browse projection 已完成；Agent `read_top()` runtime copy
  语义保持不变，并有 actual/effective/no-side-effect 回归测试。
- P0–P6、P9：按计划继续由前端实施和最终联调；本计划整体仍为 `in_progress`。

## 设计方案

### P0：基线冻结与行为清单

以 `35f1440^` 只读提取旧实现和视觉资料，形成可核对的行为清单和代表性截图：

- `ChatView`、`TurnView`、`LiveStatus`、`ActivityStep`、旧 `ActionGlimpse`；
- `TurnTraceDrawer`、`LlmTaskDrawer`、消息栈和控制操作呈现；
- 会话历史、恢复、running/settled、问题等待、追加输入和回答动画；
- 明暗主题、窄窗口、`prefers-reduced-motion` 和滚动接管。

清单只描述可观察行为、布局和视觉节奏，不把旧类型签名重新作为协议。确认哪些旧功能已经由
当前 v2 页面覆盖，哪些需要恢复；将对照记录放在 `visualization/docs/review/`，不修改根执行计划。

### P1：v2 Chat presentation projection

在 `visualization/src/features/chat/` 与 `visualization/src/features/trace/` 内增加面向呈现的
纯类型和适配函数：

- `Interaction`、`TurnSnapshot`、`PendingItem`、`TurnResult` 映射为旧 Chat 的消息、状态和
  操作行；
- Session 历史和活动 Turn 使用同一套消息呈现，历史数据没有实时动画；
- formal owner snapshot 决定状态、问题、预算、结果、取消和是否允许输入；
- Observation facts 只提供过程细节和动画输入，不改变正式状态；
- Action renderer 继续复用现有 canonical registry，不恢复旧别名。

当前 `turnStore` 保持唯一正式 Turn 投影。presentation projection 可以随连接代际和 Turn
切换重建，不保存跨 Turn 的第二份业务事实。

### P2：短生命周期 Observation activity buffer

为活跃 Turn 增加有界、可丢弃的观察活动投影：

- WebSocket `onEvent` 将当前 Turn 的事件交给 activity projector；非当前 Turn 事件只触发
  既有 owner refresh；
- 进入活跃 Turn、重连或 event gap 后，用 `/v2/events` 的 `turn_id`、`mode=verbose`、
  `through` 和 continuation replay 重新建立活动窗口；
- projector 产生 phase headline、thinking、domain/skill、context、todo/milestone、
  action plan/result、provider retry 和 working 摘要；
- 连接断开、gap 或观察窗口截断时，保留已显示内容并明确标记“不完整”，由 snapshot 继续
  驱动正式状态；
- 不把该 buffer 当作 Session、Turn 或 Action owner，不用它覆盖结果，不为缺失事件补造结果。

如果现有 ObservationEvent 缺少正常路径必须呈现的稳定字段，只扩展已有事件的 typed payload
和后端契约；不新增平行的 UI 状态 endpoint。

### P3：恢复 Chat 基线

使用 P1/P2 投影重建旧版 Chat 表面：

- 恢复旧版 TurnView 的消息顺序、活动卡、最终回答和状态尾部；
- 恢复 LiveStatus 的 live/settled 两种模式、滚动轨迹、working 区域和停止反馈；
- 恢复 ActivityStep 的语义条目和 ActionGlimpse 的双阶段预览；
- 保留 v2 QuestionCard、BudgetCard、pending item、OutgoingEcho、queued request、方案入口；
- 保留旧版回答 stream/settle、anchor follow、manual scroll takeover 和 reduced-motion；
- 历史 Turn、Session 接管和 event gap 不重播历史动画；
- 使用当前 ResourceRouter 和 Inspector 打开资源、Action、Model、Search、Job 详情。

必要时拆分当前约 900 行的 ChatView，把滚动容器、会话列表、Turn presentation 和输入区分开，
避免恢复过程再次形成一个拥有全部状态的巨型组件。

### P4：恢复 Turn Trace 主呈现

在现有 `features/trace` 单一数据模型上恢复旧版 Trace 交互：

- 将 ProcessPanel 的 Cycle/Phase/Action 数据与旧版活动时间线合并到 Turn Trace 面板；
- 增加 Phase 控制操作、背景加载、todo/milestone、MessageStack 和 LLM task 的分组呈现；
- 继续从 Action detail、ModelCallPanel、SearchResultView、JobPanel 下钻，不复制这些 owner 面板；
- 保留事件窗口边界、truncated、缺少 result、取消、未执行和结果未知的诚实状态；
- 旧导出入口如保留，导出 v2 定向 observation window 与正式交互快照的 JSON；不恢复 v1 文件导出 API。

### P5：Session history 与新增 v2 页面收敛

- 主 Chat 采用旧版会话历史阅读层级，Session Day/Turn browser 作为按需入口继续保留；
- 只读历史不允许 Composer 提交，历史问题只展示答案事实；
- Home、Memory、Workspace、Runtime、Context、ResourceRouter、Search 和 CodeBlock 页面不回退，
  只统一回到 Luminous tokens、domain colors 和既有 Inspector 壳；
- Home 页面提供简单的 `actual` / `effective` 浏览切换：前者查看全部 actual Home，后者只查看
  已物化 runtime Home；两者都使用 owner 浏览接口，不调用 Agent 运行时 `read_top()`。
- 不在 Chat 顶部新增长期日期栏、常驻 Session map 或模型参数工具条。

### P6：Settings 中文化

增加集中式设置界面文案映射，覆盖：

- 导航、页面标题、section、字段说明、按钮、状态、校验反馈和空状态；
- Action、Search policy、model-use、provider/model/chain 的用户解释；
- aria-label、tooltip、Retry/Apply/Reset 等辅助文字。

配置路径、Action canonical ID、provider/model ID、枚举值、HTTP code、failure kind 和代码块协议
保留原始值；不把中文文案写进后端配置或协议 payload。

### P7：后端 catalog 契约修正（后端已实施）

先修复两个已明确、不涉及 Home 语义争议的 pending demand：

1. `capabilities.resource.render_pdf_pages` 的 catalog choices 与实际接受的
   `disabled/on_no_text` 对齐；不在本轮凭空增加未实现的 `always`。
2. `capabilities.web.search_by_kimi.model` 在 catalog 中声明代码实际接受的
   `kimi-k2.5/kimi-k2.6`；前端 Settings 后续改为消费 choices，不再硬编码。

后端 catalog 测试、endpoint 说明和前端配置覆盖说明已同步；设置页消费 choices 属于后续
前端收口。

### P8：Home 顶层文档读取语义（后端已实施）

后端实现遵循以下已经确认的语义：

- Agent 通过 Context、Skill 或 Action 读取 top content 时，`read_top()` 始终确保
  `runtime/home` 副本，再从 runtime 副本读取。现有设计文档和 runtime copy Trap 支持这一语义，
  当前代码的 `read_top()` 也已经以缺副本触发 recovery 的方式实现。
- 前端直接调用 `/v2/home/catalog` 和 `/v2/home/content` 时，不调用 Agent 的 `read_top()`，
  也不因为用户打开页面就伪造一次 Agent 已读取。两个 view 都是 Home owner 的浏览数据接口：
  `view=actual` 展示全部 actual Home，`view=effective` 只展示已经存在于 `runtime/home` 的副本。
- Home 页面提供简单的 actual/effective 切换按钮。effective 目录和内容都以 runtime
  materialization 为资格，未物化的 actual 条目不出现在 effective 列表；effective 直接读取未物化
  Link 时返回当前 owner 的不可用/不存在结果，前端如实显示空态或读取失败，不回退 actual、不触发
  runtime copy。
- `read_top()` 仍只服务 Agent 的 Context/Skill/Action 运行路径：缺副本时由 Runtime copy
  handler 物化并重试。浏览接口与 Agent 运行时读取接口在职责、调用来源和副作用上保持分离。

当前 `browse_catalog`、`browse_content` 已使用清晰分开的 owner 读取集合；
`home:agent@AGENT` 在 actual view 中可直接展示，尚未被 Agent 读取时不出现在 effective view，
Agent 读取并物化后才出现在 effective view。目录和内容 endpoint 对同一 view 给出一致的可读性
事实，不把 503 转为空正文，也不让前端用 `read_top()` 代替浏览接口。相关 Home、catalog 和
endpoint 回归已通过。

### P9：完整验收和文档收口

前端：

- vitest、tsc、Vite build；
- 真实后端 Playwright：新 Turn、追加、回复、问题等待、预算等待、running LiveStatus、settled
  fold、历史 Turn、Trace、Search、Home/Memory、Settings 中文、窄窗口和明暗主题；
- 以 `35f1440^` 基线截图和行为清单核对 Chat/Trace，不只验证页面非空；
- reduced-motion、event gap、历史恢复和截断状态至少保留结构性测试。

后端（P7/P8 有代码修改时）：

- 相应 pytest、endpoint contract/fixture、`ty` typecheck 和完整本地门禁；
- 更新 `docs/design/agent_home.md`、endpoint 文档和 visualization demand 结论；
- Home demand 只有在读取 view、runtime copy、catalog 和页面状态全部一致并验证后才能归档。

计划只有 P0–P9 的代码、文档、测试和真实页面验收均完成后，才按 `AGENTS.md` 改名加入
`docs/analysis/done/`。本计划虽已确认 P8 的语义，仍须等 P0–P9 的代码、文档、测试和真实页面
验收全部完成后才能归档。
# Archived as superseded on 2026-10-01. Status: dropped. The recorded completion claims are historical and are replaced by the new 20261001 visualization chat v2 baseline restoration plan.
