# TinySoul 桌面前端设计

> 本文档描述 `visualization/` 目录内的前端设计思路与整体架构。前端只负责可视化与交互，不直接操作后端业务目录；所有状态通过已运行的 `tinysoul start` Endpoint 获取。

## 定位与边界

- **仅前端**：编辑范围限定在 `visualization/` 目录；不修改后端 Python/Rust 业务代码。
- **纯连接模式**：Tauri 不启动、不持有、不停止 Python 进程；前端只读取 App 发布的项目实例连接描述，发现并连接当前已运行的 Endpoint。
- **后端为真相源**：Workspace 与项目配置通过 Endpoint REST 管理；Agent 运行过程与真实模型语境通过 Observation 展示。前端不直接读取 `runtime/`、`home/`、`memory/`、`archive/` 或配置文件。
- **MODEL 级事件订阅**：WebSocket 始终订阅 `model` 等级事件；前端在本地按名称、scope、identity 派生展示。服务端只在连接起始读一次鉴权帧，切换游标/等级通过重连实现。

## 核心设计原则

1. **对话优先**：主界面是用户轮（user message + agent answer）构成的聊天历史，内部执行细节默认收纳。
2. **运行状态动态披露**：进行中的用户轮在主对话界面实时展示当前阶段、正在执行的 action（含 stage2 输入与 stage3 结果要点的内联详情）、todo/milestone 快照与滚动 activity feed。
3. **Turn 追溯抽屉**：每个用户轮可从右侧拉出 TurnTraceDrawer，按 Cycle → Phase 呈现 control ops（domain 选择、背景加载、todo/milestone 维护）、每次 LLM 任务的完整 message stack、action 输入输出与执行状态，并支持导出该轮完整 trace（Markdown / JSON）。
4. **语义化呈现**：action 呈现语义集中在 `derive/actions/` registry（verb/family/调用摘要/结果摘要），视图层按呈现家族（patch/command/search/fetch/memory…）差异化渲染；domain、link、todo/milestone、工作区变更等都有专属视觉表达；结构化 JSON 用可折叠语法着色树兜底，不隐藏任何信息。
5. **全局背景独立显示**：Background Context 是跨 Turn 的全局抽屉，不嵌在单个 Turn 内部。
6. **Luminous 视觉系统**：三档明度中性底 + 光泽层级 + 域色系统，亮暗双主题，CSS 变量驱动（详见 visual-system.md）。

## 整体布局

```text
+---------------------------------------------------------------+
| NavRail |  TopBar (title + turn badge + Maintenance / Context)|
| 52px    +-----------------------------------------------------+
| Chat    |                                                     |
| Work-   |              Main Content Area                      |  <= TurnTraceDrawer
| space   |              (Chat / Workspace / Monitor)           |     (right slide-over)
| Monitor |              (Chat / Workspace / Monitor / Settings)|
| Settings+-----------------------------------------------------+
| Theme   |              StatusBar                              |
| Settings                                                      |
+---------------------------------------------------------------+
```

## 区域命名地图

交流时统一使用以下名称；覆盖层约定：右侧滑出为 `*Drawer`，居中弹窗为 `*Dialog`。

| 交流用语 | 代码组件 | 文件 |
|---|---|---|
| NavRail 导航栏 | `NavRail` | `components/shell/NavRail.tsx` |
| TopBar 顶栏 | `TopBar` | `components/shell/TopBar.tsx` |
| StatusBar 状态栏 | `StatusBar` | `components/shell/StatusBar.tsx` |
| ChatView 对话视图 | `ChatView` | `components/chat/ChatView.tsx` |
| ├ 用户轮 | `TurnView` | `components/chat/TurnView.tsx` |
| ├ LiveStatus 活跃状态 | `LiveStatus` | `components/chat/LiveStatus.tsx` |
| ├ 活动条目 | `ActivityStep` | `components/chat/ActivityStep.tsx` |
| ├ action 内联详情 | `ActionGlimpse` | `components/chat/ActionGlimpse.tsx` |
| └ 输入框 | `Composer` | `components/chat/Composer.tsx` |
| TurnTraceDrawer 追溯抽屉（Details 面板） | `TurnTraceDrawer` | `components/trace/TurnTraceDrawer.tsx` |
| ├ Cycle 卡 | `CycleSection` | `components/trace/CycleSection.tsx` |
| ├ Phase 行 | `PhaseSection` | `components/trace/PhaseSection.tsx` |
| ├ Action 卡 | `ActionCard` | `components/trace/ActionCard.tsx` |
| ├ 家族渲染器 | — | `components/trace/renderers/` |
| └ 活动时间线 | `ActivityTimeline` | `TurnTraceDrawer.tsx` 内 |
| LlmTaskDrawer 模型任务抽屉 | `LlmTaskDrawer` | `components/trace/LlmTaskDrawer.tsx` |
| BackgroundDrawer 背景抽屉 | `BackgroundDrawer` | `components/shell/BackgroundDrawer.tsx` |
| MaintenanceDialog 维护对话框 | `MaintenanceDialog` | `components/shell/MaintenanceDialog.tsx` |
| Settings 设置页面 | `SettingsPage` | `features/settings/SettingsPage.tsx` |
| WorkspaceView 工作区视图 | `WorkspaceView` | `components/workspace/WorkspaceView.tsx` |
| MonitorView 监视器视图 | `MonitorView` | `components/monitor/MonitorView.tsx` |

术语约定：

- 业务层级严格对齐 AGENT.md：User Turn / Agent Cycle / Phase1·2·3。UI 与文档统一用 **Phase**，不使用 Stage 说法；`ActionResult.stage`（normalize/execute/…）是后端执行阶段枚举，UI 标注为 "stage: \<value\>"。
- store 字段与之一致：`traceTurnId` / `openTurnTrace` / `closeTurnTrace`。

## 代码结构

- `src/api/` — Endpoint HTTP 客户端与 WebSocket 事件流（指数退避重连、gap 检测）。
- `src/derive/` — 从扁平事件流派生对话模型：`chat.ts`（Turn/Cycle/Phase/control ops/working state/activity feed/usage）、`model.ts`（派生类型）、`actions/`（action 呈现 registry：verb/family/调用摘要/结果摘要）、`phaseSummary.ts`（Cycle/Phase 折叠行文案）、`activitySemantics.ts`（skills 与文本辅助）、`export.ts`（turn trace 导出）。
- `src/store/appStore.ts` — Zustand store：连接、事件、workspace 缓存、UI 状态（主题、抽屉、toast）；仅持久化 projectRoot / theme / activeTab。
- `src/store/configStore.ts` — 非持久化 Endpoint 配置快照、写入和激活后重读状态；实例切换时清空。
- `src/features/settings/` — 独立 Settings 页面、二级导航、TOML 类型化字段、Credentials 与客户端偏好。
- `src/components/ui/` — 设计系统基元（Button/Badge/Card/Modal/Tabs/Toast/JsonTree/Collapsible/CopyButton/EmptyState）。
- `src/components/markdown/` — 复用的 Markdown 渲染模块（react-markdown + GFM），服务于最终回答、工作区文档预览、背景内容等。
- `src/components/chat/` — ChatView 对话视图（TurnView 用户轮、LiveStatus 活跃状态、ActivityStep 活动条目、ActionGlimpse 内联详情、Composer 输入框）。
- `src/components/trace/` — TurnTraceDrawer 追溯抽屉（CycleSection/PhaseSection/ActionCard、renderers/ 家族渲染器、LlmTaskDrawer、MessageStackView、ControlOpsView、semantic 共享语义芯片）。
- `src/components/workspace/` — WorkspaceView 工作区视图（目录树、编辑器 + Markdown 预览、二进制预览、回收站）。
- `src/components/monitor/` — MonitorView 原始观察事件监视器（等级过滤、搜索、payload 展开）。
- `src/components/shell/` — 应用外壳（NavRail、TopBar、StatusBar、BackgroundDrawer、MaintenanceDialog、DisconnectedScreen）。
- `src/hooks/notifiers/` — 通知检测层：把派生状态转变转为 toast 的小型 watcher，由 AppShell 经 `useNotifiers(turns)` 单一挂载（任何 tab 下都工作）。约定：只盯派生状态、不碰原始事件流（恢复重放/终态清扫已由 derive 解决）；prev 以当前值初始化，恢复历史不误报；抑制语境（activeTab、`chatPinnedToBottom` 等）在触发时经 `getState()` 非响应式读取；toast 由纯函数构造。首个成员为轮次完成通知（`turnCompletion.ts`）。toast 的展示/队列层是 store `toasts` + `pushToast` + `Toasts` 组件（可选 action 按钮）；动作反馈与连接生命周期提示由各处就地 push，不经过检测层。

## 连接与恢复

- 实例发现由 Rust 侧 `discover_backend` 完成（identity = 规范化路径 SHA256），HTTP 轮询 `/v1/status` 检测后端重启。
- 轮询失败不清空连接、不切走对话：顶部横幅 + 状态栏 "not responding…"，保留现场自动重试；轮询恢复后若 instance_id 变化（后端重启、端口/token 已变）自动重新走实例发现。
- 浏览器开发模式（无 Tauri shell）可用 `?host=&port=&token=` 查询参数直连（持久化到 localStorage），用于截图验收与纯前端调试。
- WS gap 时清空事件派生视图并重读 status/manifest/maintenance，界面顶部给出提示条。
- 用户输入采用本地回声：提交时记录 command_id → 文本，派生层在 command accepted 后回填到对应 Turn；非本端输入（如 Terminal）从首个 message stack 的 `user_input` 段恢复。
- Turn trace 导出通过 Tauri dialog 选择目录、Rust 命令 `write_export_files` 写盘（校验相对路径防逃逸）；浏览器模式回退为单文件下载。
