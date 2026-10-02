# c479ca0 组件细节恢复与 v2 语境快照执行计划

状态：`done`。建立及核对日期：2026-10-02。视觉与交互基线：`c479ca0`；接口：v2。D1–D6 的实现、文档与必要验证已逐项核对。

## 目标与核对结论

上一轮完成了连续会话和 v2 接线，但完成记录没有充分区分功能可用与组件细节对齐。本轮补齐 Turn 起止编排、动作预览节奏、Activity 语义、Context 结束后读取和 Trace 状态展示。原版布局、领域色、光泽、Markdown 和 motion 常量继续使用，新增能力在同一组件体系中实现。

实施路线是在最新代码上提取、复用原版表现实现，再适配 v2 事实。以 c479ca0 的 TurnView、LiveStatus、ActionGlimpse 与 Trace 组件作为源码对照，不通过继续叠加动画参数替代原版生命周期和布局编排；不恢复 v1 接口或旧事件状态机。

## 设计

### Turn 与动效

以 Turn ID 稳定挂载统一的对话组件，正式内容可以从活动交互切换为 Session 记录，不因来源变化重播或丢失组件状态。运行状态仍由 Turn owner 决定。首次历史恢复直接定位，新 Turn 以 700ms 滑动停泊于顶部下方 20px；恢复期间 ResizeObserver 不抢先定位。运行中不追逐卡片底部，只有长回答流入时跟随。用户滚动立即接管，展开详情暂时暂停跟随。

原版完成编排为停留 600ms、活动区折叠 700ms、回答在 1580ms 后流入、打字后 1600ms 文档转换。等待问题/预算是等待态，不混为 Turn 完成。历史和 reduced-motion 直接呈现。原版动作行先用 420ms 落位、340ms 横向显现，再于 400ms 后用 350ms 展开预览；快速排队释放保留预展开，手动收起有退出动画且不会被重新自动打开。

### Activity 与预览

一个 typed 适配入口供 LiveStatus 和 Trace 共用。背景 snapshot/changed 根据真实 loaded/evicted refs 显示通用 Skill 与具体资源；context.installed 仅用于刷新，不再制造重复的泛泛日志。模型摘要形成 thinking；Control Tool 保留“请求”含义；已接受域选择由 Phase 完成事实提供。任务局部 Skill 由模型请求 provenance 显示为“本次任务挂载”，不混为 Background 加载。

标题按实际运行 Action 与目标变化，保留阶段含义、计时和取消中的反馈。紧凑预览从 v2 参数/结果提取命令、终端输出尾部、检索命中、修改片段和写入摘要；与完整详情共用事实解析，Chat 不直接嵌入整个详情页。没有适当紧凑内容时只显示行动事实，完整诊断留在 Trace。Thinking 的单行截断同样提供展开，标题与思考使用同一节奏。

### Context 持续阅读

Context 仍只属于活动 Turn。Home/Memory 的已安装 Heap 在必要 completion 中保存正文快照，沿既有 segments → Session 记录链路提交，不增加平行日志，不读取当前文件重建旧正文。新增 v2 只读 background 页面：活动 Turn 从已安装 Heap 读取，已完成 User Turn 从 Session 读取，均使用同一资源项投影及现有分页设施。旧 Session 没有正文快照时明确说明不可用，不伪造正文。

顶部 Context 在运行时绑定活动 Turn，结束后可以查看最近 User Turn 的背景快照，明确标记历史来源；刷新后也可读取。当前 Context 总览仍为活动安装段，历史背景不是一份仍活动的完整 Context。Session map 按所属日期读取。Home/Memory 子页直接显示每项标题、链接、来源和短正文，长正文就地展开，不经 segment → owner 多层跳转；技术元信息放次级详情。浏览不会调用 read_top，也不会把 actual/effective Home 目录称为已加载内容。

### Trace 与信息收口

恢复 Cycle/Phase 运行状态、高亮、耗时、动作胶囊、阶段 Context 入口与模型统计。模型 token 统计基于实际留存响应，不当作持久 Turn 结果，窗口不完整时明确范围。模型消息继续在同一 Inspector 栈向左展开。原版的摘要与紧凑内容保留，新增 Job/Search/专用模型入口继续可用。

## 执行顺序与验收

| 阶段 | 工作 | 验收 |
|---|---|---|
| D1 | Heap 结束快照、活动/Session background SDK 与 v2 路由；Phase 已接受域事件 | 加载正文与结束后读取一致，修改 Home 不改写历史；分页和旧记录缺失语义明确 |
| D2 | 统一 Turn 组件与滚动协调、原版动效编排 | 连续两轮、完成接管、手动展开、reduced-motion 与刷新不重播；新 Turn 确实滑动 |
| D3 | Activity 语义、标题、thinking、两拍预览 | Skill/资源名可见，执行意图与结果分开；命令/搜索/写入可读；长单行思考可展开 |
| D4 | Context 四子页直接阅读与历史背景 | 结束后首次打开、切换子页、关闭重开、刷新均能读最近背景，且来源准确 |
| D5 | Trace 状态、计时和统计 | 与 c479ca0 Phase/Cycle/Model 组件逐项对照，真实 v2 事实可解释 |
| D6 | 契约、设计文档、测试和浏览器对照 | 前端完整测试/类型/构建、Python Full/ty，通过多步骤真实 Endpoint 脚本模型联调 |

浏览器验收需检查正文与动态过程，不仅判断按钮存在：记录新 Turn 位置变化、动作落位与预览展开、完成折叠与回答流入；覆盖 Skill/背景变化、长 thinking、连续多轮和结束后 Context 正文。外部真实 provider 测试不作为本地门禁。全部逐项核对后填写实现证据并归档。

## 实施核对（2026-10-02）

| 阶段 | 实现与核对证据 |
|---|---|
| D1 | `HeapSegment.seal` 保存正文；Context/Session 的 background 通过现有 PageResponse 分页。HTTP 契约测试用真实 Agent 验证活动内容可读、结束后 Home 修改不影响原快照；旧记录与已保存空集合分别表达。Phase 完成事件增加已接受域、失败和取消事实。 |
| D2 | `ChatView` 统一 Turn 挂载、按 role/ordinal 保留表现身份；`useConversationScroll` 复用原版几何与滑动公式，防止恢复/换 Turn 时被 ResizeObserver 抢先定位。浏览器采样验证滑动到 20px、折叠中间高度、回答打字和收束；Session 接管后原 Turn 与活动卡 DOM 仍连接。 |
| D3 | `ActivityBuffer/facts` 保留 Skill provenance、背景加载/逐出、已接受域和真实执行结果；`semantic` 按现有 Activity 类型接回原版图标和颜色。`ActivityGlimpse` 复用原版 diff、terminal tail、前三项命中与紧凑布局，输入边界使用 v2。LiveStatus 测试覆盖行先出现、浮层延后、持续重渲染不推迟、手动收起不重开与 reduced-motion；内容测试覆盖终端、检索和有序 edits。 |
| D4 | `BackgroundPanel` 共用一次 Home/Memory 读取，保留子页展开状态；短正文直接可见，长正文就地展开，动态 Memory 头单独呈现。Markdown 保留 ref/day/Turn。浏览器覆盖运行中、关闭重开、完成后首次打开与页面刷新后的正文和来源。 |
| D5 | `ProcessPanel/facts` 恢复阶段运行图标、高亮、计时、动作胶囊、Cycle 时间与数量、留存 token 统计及调用 Context 入口。测试区分 Control 请求与成功接受的域、失败阶段与完成阶段；模型详情仍在同一 Inspector 栈向左展开。 |
| D6 | 同步 Context/Session 设计、Endpoint 浏览与事件契约、前端 Chat 设计和进度。最终验证记录见下表；外部 provider/network 未调用。 |

### c479ca0 源码对照

| 原版表现来源 | 当前承接 | 保留与适配 |
|---|---|---|
| `components/chat/TurnView.tsx` | `features/chat/ChatView.tsx`、`conversationRows.tsx` | 单一 Agent 列、气泡、最新轮 settled card、回答折叠/打字/文档转换；追加输入、问题与回复沿 v2 正式交互扩充。 |
| `components/chat/ChatView.tsx` | `useConversationScroll.ts` | 20px 锚点、700ms 四次缓出滑动、动态尾部留白、运行中停泊和长回答跟随；显式保护历史恢复和用户展开。 |
| `components/chat/LiveStatus.tsx` | `features/chat/LiveStatus.tsx` | 队列逐条释放、thinking 擦除/出现、600/700ms 收束、两拍 gist 和 drain 预展开；等待态继续活动，不误作停止。 |
| `components/chat/ActionGlimpse.tsx` | `features/chat/ActivityGlimpse.tsx` | 原版 diff 行组件直接提取；命令/输出尾部/检索前三项的结构保留，参数与结果改读 v2，完整详情独立。 |
| 原版 Trace 的 Cycle/Phase 与模型 Context | `ProcessPanel.tsx` 与现有 ModelCall Inspector | 状态、耗时、胶囊与侧向 Context 入口；v2 的实际阶段、模型请求与结果承担数据来源，不借用顶部 Context。 |
| 原版 Home 直接阅读 | `BackgroundPanel.tsx` | 可见正文与本地展开；新增 Memory/Session map 子页，完成后读取 Session 的真实结束快照。 |

保留边界：历史 Session 未记录的模型用量/耗时不伪造；本次增加的背景正文仅能服务实际保存了它的记录。共享样式、主题光泽与回答 motion 常量未重设。

### 最终验证

| 检查 | 结果 |
|---|---|
| Python Full | 1224 passed，25 deselected；含真实 HTTP owner 协作与 wheel 验收 |
| `scripts/typecheck.ps1` | Python 3.13.12 / ty 0.0.84，通过 |
| TypeScript / Vite | 通过；保留既有大 chunk 提示 |
| Vitest | 90 个文件、799 项通过；最后将 Search 浮层改用契约样例的 evidence.text 后，相关 14 项与 TypeScript 再次通过 |
| Playwright | 真实 Agent/Endpoint 与脚本模型；连续两轮、Skill 加载、真实 Workspace 读取、问题回复、双抽屉、背景快照与刷新恢复通过；逐帧验证新 Turn 位置和完成编排 |

浏览器截图位于 `visualization/.local-test/playwright-output/`，由 `test/e2e/chat-flow.pw.ts` 重建；动作延迟与手动展开契约由组件测试补充。只读页面没有引入资源加载、v1 接口或另一套运行事实。
