# Activity 语义与 Turn 入场核对

状态：`done`；日期：2026-10-03。

执行计划：[Activity 语义、阶段呈现与 Turn 入场](../../../../docs/analysis/done/20261003-done-visualization-activity-semantics-and-turn-entry-plan.md)。视觉基线为 c479ca0，正式数据与接口仍为 v2。

| 关注项 | 实施与核对 |
|---|---|
| 空阶段条目 | ActivityBuffer 不再把 phase started 变成活动；清除类型、正文与图标映射中的旧分支。Phase 仍驱动标题、计时与 Process。 |
| 运行抬头 | presentation 的阶段元数据恢复原版三句运行说明；单个实际执行 Action 显示真实名称/目标，多项显示运行数量。阶段完成计时停止。 |
| 阶段底色 | ProcessPanel 的 Activity 先按连续 Cycle/Phase 分段再筛选；组容器绘制淡底色，行间无色泽间隙。恢复倒序、时间、原版筛选和行动详情入口，不改变 LiveStatus 背景。 |
| Turn 入场 | ChatView 顶部 UserBubble 从本地发送至 receipt、正式输入和 Session 接管保持节点与表现 key。scroll 使用稳定槽位，保留原版 20px/700ms 停泊；queued 不提前显示运行卡，追加和回复保持各自位置。 |
| 控制活动 | 后端安装成功后提供 context.control.applied，前端显示 todo、milestone、Background load/evict；初始背景快照不生成 Loaded。任务 Skill provenance 以任务指导展示，同一 task 去重，共用资源标签。Working 继续读取已安装 plan。 |
| intent | Phase1 的域选择 intent 保留独立来源与接受状态，可就地展开并进入 Thinking 筛选；顶部仍只呈现 reasoning。同文不重复正文。 |

基线对照覆盖原版 TurnView、LiveStatus、ActivityStep、TurnTraceDrawer、derive/chat 与阶段元数据。保留前一轮已恢复的动作浮层、折叠、回答打字/收束、Context 背景快照与模型双抽屉。没有新增 v1 适配器、平行运行状态机或活动持久日志。

验证：Python Full 1226 项、ty；Vitest 90 个文件 808 项；TypeScript/Vite；真实 Agent/Endpoint + 脚本模型的两条浏览器流程通过。浏览器覆盖从 sending 开始的节点身份、连续两轮、上下顺序、入场滑动、完成折叠/回答流入、真实控制记录与 intent、连续底色/筛选、明暗及 800px 窄窗、Session 接管。截图位于忽略的 `.local-test/playwright-output/`，通过 `test/e2e/chat-flow.pw.ts` 重建。外部供应商网络未纳入本地验收。

完整门禁另发现 Workspace 等长编辑可能漏发通知：成功写入的 Link 现在与 manifest 差异共用变更投影，Observation/环境事件一致发布。固定时间戳回归与 Workspace 78 项通过；没有增加文件哈希或日志。后端设计和 Endpoint 说明同步更新。

修改范围：前端 chat/trace 投影、共享 ActivityStep/UserBubble、滚动定位及测试；后端 Context control/engine、Loop phase 完成观察、Workspace 变更发布及测试；设计和 Endpoint 文档。旧记录缺少 applied 观察时不补造控制活动。
