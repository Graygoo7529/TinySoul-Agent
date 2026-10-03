# Chat 与运行时活动

Chat 以 c479ca0 的主对话体验为视觉基线，并使用 v2 的正式 Session/Turn 投影和 Observation 事件。两者职责分开：Session/Turn 决定哪些交互已经成为事实，Observation 只负责把正在运行的细节及时呈现给用户。

## 连续会话

`ChatView` 在当前日显示一条连续的阅读流：已完成的 User Turn 按时间顺序排列，当前活动 Turn 接在末尾。`turnController.refreshSessionTurns` 读完 `/v2/session/turns` 的目录分页，再读取每个 Turn 的正式 Session 投影；不可变的已完成正文在同一连接内复用。列表按 Turn ID 去重并稳定挂载同一组件，正式交互从活动投影切换到 Session 时不重新挂载回答或 Activity；刷新或重新连接仍从 owner 恢复正文。

历史日仍使用独立的历史浏览入口。历史 Turn 是只读投影，不能在其中写入 Action 或 Context。

## 输入与入场

Composer 在没有未完成 User Turn 时创建新 Turn；已有可接受输入的 User Turn 时直接追加，不提供发送模式选择。目标由运行状态、正式快照和本窗口的创建回执确定，并在提交时固定。已知目标尚未同步、取消中或收尾中时保留可编辑草稿，暂不发送；追加失败不会自动改投下一轮。QuestionCard 的明确回复与普通追加仍使用各自入口。Reflection 不接受用户追加，本窗口在其执行期间创建的 User Turn 由 Agent 调度。

初始输入立即成为顶部气泡，提交中和已接受提示只占气泡边角，不额外占行；正式输入接管时同一节点原位更新。请求摘要仅在没有完整输入时作为内容线索，不单独显示排队文本条，也不据此判断执行阶段。正式 snapshot 已就绪后才出现单一 Agent 区域及 LiveStatus；准备态不依赖首条 Observation，实际未开始的请求只显示等待抬头，不虚构阶段和计时。

停止入口位于 Composer：目标可取消且输入为空时显示停止，有文字时显示发送。LiveStatus 不重复提供停止按钮。停止请求只针对交互目标 User Turn，由后端确认执行状态。

## LiveStatus 与思考流

`ActivityBuffer` 订阅 v2 Observation，并以 Turn scope 识别归属。`action.call` 形成计划条目，`action.execution` 更新执行图标，`action.result` 形成独立结果条目；取消、未执行与未知结果不伪造工具返回。思考流来自 `llm.model.response.reasoning.summary`，没有摘要时不生成思考文字。Working 从当前 Turn 已安装的 plan 段读取，不将模型 Control Tool 意图当成已安装事实。

活动缓冲不保留完整模型请求；响应只保留 reasoning、Phase1 域选择的 intent/域和控制调用身份。最多保留 2000 条事件并明确标记不完整。挂载或重连后，定向 replay 与现有流按 sequence 合并。需要查看完整模型请求、Context 和响应时，从 Trace 进入 ModelCall 详情。

Activity 只把 `context.control.applied` 作为 todo、milestone、Background 加载/逐出的执行事实；初始背景快照和刷新事件不生成活动条目。模型请求提取局部任务 Skill provenance，以任务指导展示，同一 task 的相同挂载去重，并与 Background 共用资源标签。milestone 是事实寄存器，不默认标记为已完成任务。

Phase 边界只驱动抬头与计时，不添加 Understanding/Planning/Executing 空条目。运行句沿用 c479ca0；完成的阶段计时停止。顶部思考条只取 reasoning；域选择 intent 与 reasoning 共用思考条目样式和 Details 的 Thinking 筛选，正文可展开，所选域作为独立活动直接显示。任务指导归入 Context，长 milestone/todo 可就地展开；待处理的待办设置标为 Set todo，进行中的更新标为 Update todo，完成、取消和移除使用各自标签，悬停显示本次写入的具体状态。域选择请求由 Phase 完成事件确认，同一响应中完全相同的 reasoning/intent 不重复正文。思考与标题共用节奏，等待用户/预算保持活动卡，取消状态单独表达。

动作浮层复用 c479ca0 的紧凑结构：命令、两行输出尾部、前三个命中和修改 diff；完整结果留在 Trace。行先落位，预览再展开；快速释放的队列预展开。手动收起保持关闭，扩大轨迹时折叠滚动窗口外的预览。

## Turn Trace

`ProcessPanel` 按真实 scope 顺序组织 Cycle/Phase，首个 Action 产生前也能显示模型任务。Action 执行按 execution/result 所属阶段定位。阶段卡片保留推理预览、控制请求和模型 context 按钮；模型详情在同一 Inspector 导航栈中向左展开，窄屏覆盖显示。活动 Turn 定期刷新有界 Trace，历史读取明确显示留存窗口与缺失情况。

Working Context 显示最后一次留存模型请求中的 plan 快照，并标明捕获时点。Job 状态由 Turn snapshot 提供；历史 Activity 复用 `ActivityBuffer`。Trace 导出当前读取窗口的 JSON，保留窗口边界与截断标记，不承诺未留存的历史记录。

Details 的 Activity 恢复倒序、时间、All/Thinking/Actions/Context/Errors 筛选及行动详情入口。先按连续 Cycle/Phase 分组再筛选，阶段淡底色绘制在组容器上，组内行间无底色间隙；缺少阶段归属时使用中性色。此底色仅用于 Details，不改变 LiveStatus。旧事件缺少 applied 事实时不把控制请求推测为成功。

## Context Inspector

Chat 右上角 Context Inspector 提供四个子页：当前 Context、Session map、已加载 Home、已加载 Memory。Home/Memory 共用 background 页读取，活动 Turn 显示已安装内容，完成后显示 Session 中的结束快照并标明来源；无活动 Turn 时可读取最近会话。标题、ref 和短正文直接呈现，长正文就地展开，子页切换保留展开状态。它不会调用 `read_top`，也不会改变 Agent 的 Context 或 Home/Memory owner 状态。

抽屉打开时绑定 Turn 和日期，Session map 使用同一来源日；当前 Context 总览不把历史快照解释成活动语境。旧 Session 没有背景正文时明确提示，不能重新读当前文件冒充旧正文。Markdown 链接保留资源、日期与 Turn 来源。

## 渲染和交互

- 用户消息、Agent 回答、动作摘要和等待问题沿用主对话的卡片、Markdown、动画和滚动锚点。
- 新 Turn 的初始气泡固定在顶部输入槽；从本地发送、回执绑定到正式输入及 Session 接管保持同一节点和表现 key，只入场一次。不同 Turn 保持独立槽位；未读取其运行快照前不提前展示 LiveStatus。追加与回复保留各自交互位置。
- `ConversationRows` 负责交互行与回答呈现，`ChatView` 负责当天布局与操作入口，`useConversationScroll` 管理滚动。最新 Turn 在顶沿下 20px 停泊；运行中不追逐卡片底部，仅长回答打字时跟随正文。滚轮和触摸交还用户控制。
- 回答在活动卡收束后流入，再从 terminal 样式过渡为文档；Session 接管时保持已显示交互的表现身份。历史正文和 reduced-motion 不重播这些动画。
- 完成栏使用正式状态与交互记录中的 Action 统计；活动记录可附捕获耗时。历史 Session 未提供的耗时和模型用量不以零值代替，留存模型详情从 Trace 按需读取。
- 活动动作只显示有限的语义摘要；完整输入输出、失败诊断和模型消息在 Trace 中按需展开。
- Trace 的阶段状态、已接受域和耗时来自真实 Phase 事件，模型 token 只统计留存响应，并标明统计范围。
- 新增功能通过现有 Chat/Trace/Context 组件接入，禁止引入第二套 Turn/Chat 状态机或平行的 v1 事件派生模型。
- v2 API 缺少界面所需事实时，应补充稳定的 owner 投影或 Observation 字段，再由前端适配；不通过读取 runtime 文件或猜测字段补齐。
