# TinySoul 桌面前端设计

> 本文档描述 `visualization/` 目录内的前端设计思路与整体架构。前端只负责可视化与交互，不直接操作后端业务目录；所有状态通过已运行的 `tinysoul start` Endpoint 获取。

## 定位与边界

- **仅前端**：编辑范围限定在 `visualization/` 目录；不修改后端 Python/Rust 业务代码。
- **纯连接模式**：Tauri 不启动、不持有、不停止 Python 进程；前端只读取 App 发布的项目实例连接描述，发现并连接当前已运行的 Endpoint。
- **后端为真相源**：Workspace 通过 Endpoint REST 管理；Agent 运行过程与真实模型语境通过 Observation 展示。前端不直接读取 `runtime/`、`home/`、`memory/` 或 `archive/`。
- **MODEL 级事件订阅**：WebSocket 始终订阅 `model` 等级事件；前端在本地按名称、scope、identity 派生展示。服务端只在连接起始读一次鉴权帧，切换游标/等级通过重连实现。

## 核心设计原则

1. **对话优先**：主界面是用户轮（user message + agent answer）构成的聊天历史，内部执行细节默认收纳。
2. **运行状态动态披露**：进行中的用户轮在主对话界面实时展示当前阶段、正在执行的 action、todo/milestone 快照与滚动 activity feed。
3. **Turn 内部细节滑窗**：每个用户轮可从右侧拉出细节滑窗，按 Cycle → Phase 呈现 control ops（domain 选择、背景加载、todo/milestone 维护）、每次 LLM 调用的完整 message stack、action 输入输出与执行状态，并支持导出该轮完整 trace（Markdown / JSON）。
4. **语义化呈现**：domain、link、todo/milestone、脚本与命令执行、工作区变更等都有专属的视觉表达；结构化 JSON 用可折叠语法着色树渲染。
5. **全局背景独立显示**：Background Context 是跨 Turn 的全局面板，不嵌在单个 Turn 内部。
6. **三档明度的中性工具风**：浅色为主、亮暗双主题，CSS 变量驱动，圆角与阴影克制（详见 visual-system.md）。

## 整体布局

```text
+---------------------------------------------------------------+
| Nav    |  Header (title + turn badge + Maintenance / Context) |
| 52px   +------------------------------------------------------+
| Chat   |                                                      |
| Work-  |              Main Content Area                       |  <= Turn Trace Drawer
| space  |              (Chat / Workspace / Monitor)            |     (right slide-over)
| Monitor+------------------------------------------------------+
| Theme  |              Status Bar                              |
| Settings                                                      |
+---------------------------------------------------------------+
```

## 代码结构

- `src/api/` — Endpoint HTTP 客户端与 WebSocket 事件流（指数退避重连、gap 检测）。
- `src/derive/` — 从扁平事件流派生对话模型：`chat.ts`（Turn/Cycle/Phase/control ops/working state/activity feed/usage）、`model.ts`（派生类型）、`export.ts`（turn trace 导出）。
- `src/store/appStore.ts` — Zustand store：连接、事件、workspace 缓存、UI 状态（主题、滑窗、toast）；仅持久化 projectRoot / theme / activeTab。
- `src/components/ui/` — 设计系统基元（Button/Badge/Card/Modal/Tabs/Toast/JsonTree/Collapsible/CopyButton/EmptyState）。
- `src/components/markdown/` — 复用的 Markdown 渲染模块（react-markdown + GFM），服务于最终回答、工作区文档预览、背景内容等。
- `src/components/chat/` — 主对话界面（消息列表、LiveStatus 运行状态卡、Composer）。
- `src/components/trace/` — Turn 细节滑窗（Cycle/Phase/ControlOps/LlmCall/MessageStack/ActionCard 与各 domain 渲染器）。
- `src/components/workspace/` — 工作区视图（目录树、编辑器 + Markdown 预览、二进制预览、回收站）。
- `src/components/monitor/` — 原始观察事件监视器（等级过滤、搜索、payload 展开）。
- `src/components/shell/` — 应用外壳（导航、Header、StatusBar、设置、背景面板、维护面板、断连引导）。

## 连接与恢复

- 实例发现由 Rust 侧 `discover_backend` 完成（identity = 规范化路径 SHA256），HTTP 轮询 `/v1/status` 检测后端重启。
- 轮询失败不清空连接、不切走对话：顶部横幅 + 状态栏 "not responding…"，保留现场自动重试；轮询恢复后若 instance_id 变化（后端重启、端口/token 已变）自动重新走实例发现。
- 浏览器开发模式（无 Tauri shell）可用 `?host=&port=&token=` 查询参数直连（持久化到 localStorage），用于截图验收与纯前端调试。
- WS gap 时清空事件派生视图并重读 status/manifest/maintenance，界面顶部给出提示条。
- 用户输入采用本地回声：提交时记录 command_id → 文本，派生层在 command accepted 后回填到对应 Turn；非本端输入（如 Terminal）从首个 message stack 的 `user_input` 段恢复。
- Turn trace 导出通过 Tauri dialog 选择目录、Rust 命令 `write_export_files` 写盘（校验相对路径防逃逸）；浏览器模式回退为单文件下载。
