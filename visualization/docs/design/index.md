# TinySoul 桌面前端设计

> 本文档描述 `visualization/` 目录内的前端设计思路与整体架构。前端只负责可视化与交互，不直接操作后端业务目录；所有状态通过已运行的 `tinysoul start` Endpoint 获取。

## 定位与边界

- **仅前端**：`kimi-agent` 的编辑范围限定在 `visualization/` 目录；不修改后端 Python/Rust 业务代码。
- **纯连接模式**：Tauri 不启动、不持有、不停止 Python 进程；前端只读取 App 发布的项目实例连接描述，发现并连接当前已运行的 Endpoint。
- **后端为真相源**：Workspace、Session、Home、Memory 等持久状态一律通过 Endpoint REST/WebSocket 获取；前端不直接读取 `runtime/`、`home/`、`memory/` 或 `archive/`。
- **MODEL 级事件订阅**：WebSocket 始终订阅 `model` 等级事件，前端按事件名称、scope、identity 在本地切割展示 normal/verbose/model 信息。

## 核心设计原则

1. **对话优先**：主界面是用户与 Agent 的聊天历史，内部执行细节默认隐藏。
2. **渐进展开**：点击后可展开 Turn → Cycle → Phase → Action/Result → LLM Context 的多层结构。
3. **运行时语义可视化**：每个 Cycle 展开后能看到 Phase1 选了哪些 domain、Phase2 计划了哪些 action、Phase3 执行结果如何。
4. **全局背景独立显示**：Background Context 是跨 Turn 的全局面板，不嵌在单个 Turn 内部。
5. **冷静聚焦的视觉**：深色主题、充足留白、清晰排版、克制动效。

## 整体布局

```text
+-----------------------------------------------------------+
|  Sidebar  |  Header (title + Connect / Context / Maint.)  |
|  64px     +-----------------------------------------------+
|           |                                               |
|  Chat     |              Main Content Area                |
|  Files    |         (Chat / Workspace / Session)          |
|  History  |                                               |
|           +-----------------------------------------------+
|  Settings |              Status Bar                       |
+-----------------------------------------------------------+
```

- **左侧 Sidebar**：Chat、Files（Workspace）、History（Session）、Settings。
- **顶部 Header**：连接状态、Background Context 开关、Maintenance 入口、Settings 入口。
- **主内容区**：根据 active tab 渲染对应视图。
- **右侧 Background Context**：全局侧边栏，展示当前加载的 top links。
- **底部 Status Bar**：连接状态、active day、workspace revision、turn active 等。

## 连接与生命周期

详见 [connection.md](./connection.md)。

## 各视图设计

- [chat.md](./chat.md) — 对话、执行轨迹、运行时语义展开。
- [workspace.md](./workspace.md) — 工作区文件管理与编辑器。
- [session.md](./session.md) — 当日 Turn 历史与 canonical trace 召回。
- [visual-system.md](./visual-system.md) — 视觉 token 与组件风格。
