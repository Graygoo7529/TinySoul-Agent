# Chat 与运行时活动

Chat 以 c479ca0 的主对话体验为视觉基线，并使用 v2 的正式 Session/Turn 投影和 Observation 事件。两者职责分开：Session/Turn 决定哪些交互已经成为事实，Observation 只负责把正在运行的细节及时呈现给用户。

## 连续会话

`ChatView` 在当前日显示一条连续的阅读流：已完成的 User Turn 按时间顺序排列，当前活动 Turn 接在末尾。`turnController.refreshSessionTurns` 读完 `/v2/session/turns` 的目录分页，再读取每个 Turn 的正式 Session 投影；不可变的已完成正文在同一连接内复用。当前 Turn ID 从历史列表中排除，避免交接时重复显示；刷新或重新连接仍从 owner 恢复正文。

历史日仍使用独立的历史浏览入口。历史 Turn 是只读投影，不能在其中写入 Action 或 Context。

## LiveStatus 与思考流

`ActivityBuffer` 订阅 v2 Observation，并以 Turn scope 识别归属。`action.call` 形成计划条目，`action.execution` 更新执行图标，`action.result` 形成独立结果条目；取消、未执行与未知结果不伪造工具返回。思考流来自 `llm.model.response.reasoning.summary`，没有摘要时不生成思考文字。Working 从当前 Turn 已安装的 plan 段读取，不将模型 Control Tool 意图当成已安装事实。

活动缓冲不保留完整模型请求，模型响应仅保留摘要；最多保留 2000 条事件并明确标记不完整。挂载或重连后，定向 replay 与现有流按 sequence 合并。需要查看模型请求、Context 和响应时，从 Trace 进入 ModelCall 详情。

## Turn Trace

`ProcessPanel` 按真实 scope 顺序组织 Cycle/Phase，首个 Action 产生前也能显示模型任务。Action 执行按 execution/result 所属阶段定位。阶段卡片保留推理预览、控制请求和模型 context 按钮；模型详情在同一 Inspector 导航栈中向左展开，窄屏覆盖显示。活动 Turn 定期刷新有界 Trace，历史读取明确显示留存窗口与缺失情况。

Working Context 显示最后一次留存模型请求中的 plan 快照，并标明捕获时点。Job 状态由 Turn snapshot 提供；历史 Activity 复用 `ActivityBuffer`。Trace 导出当前读取窗口的 JSON，保留窗口边界与截断标记，不承诺未留存的历史记录。

## Context Inspector

Chat 右上角 Context Inspector 提供四个子页：当前 Context、Session map、已加载 Home、已加载 Memory。Home/Memory 子页只读取当前 Turn 的 `context.overview` 与已安装段的 captured snapshot，展示 runtime 中实际已经加载的内容。它不会调用 `read_top`，也不会因为用户打开 Inspector 而改变 Agent 的 Context 或 Home/Memory owner 状态。

## 渲染和交互

- 用户消息、Agent 回答、动作摘要和等待问题沿用主对话的卡片、Markdown、动画和滚动锚点。
- `ConversationRows` 负责交互行与回答呈现，`ChatView` 负责当天布局与操作入口，`useConversationScroll` 管理滚动。最新 Turn 在顶沿下 20px 停泊；运行中不追逐卡片底部，仅长回答打字时跟随正文。滚轮和触摸交还用户控制。
- 回答在活动卡收束后流入，再从 terminal 样式过渡为文档；Session 接管时保持已显示交互的表现身份。历史正文和 reduced-motion 不重播这些动画。
- 完成栏使用正式状态与交互记录中的 Action 统计；活动记录可附捕获耗时。历史 Session 未提供的耗时和模型用量不以零值代替，留存模型详情从 Trace 按需读取。
- 活动动作只显示有限的语义摘要；完整输入输出、失败诊断和模型消息在 Trace 中按需展开。
- 新增功能通过现有 Chat/Trace/Context 组件接入，禁止引入第二套 Turn/Chat 状态机或平行的 v1 事件派生模型。
- v2 API 缺少界面所需事实时，应补充稳定的 owner 投影或 Observation 字段，再由前端适配；不通过读取 runtime 文件或猜测字段补齐。
