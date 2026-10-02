# TinySoul Visualization 当前设计

本文描述当前前端实现。`c479ca0` 只作为对话界面的视觉和交互基线；数据、状态和接口全部以 v2 为准，不保留 v1 兼容层。

## 设计边界

- 前端只通过 Endpoint 的 v2 HTTP/WebSocket 接口获取状态、Session 投影、Context 快照、Trace 和设置数据。
- Session、Turn、Context 和 Action 的事实由后端 owner 提供。前端只维护页面状态和短期 Observation 展示，不从事件流重建业务事实。
- Observation 用于运行中的 LiveStatus、动作浮层和活动时间线；正式对话内容来自 v2 Session/Turn 读取接口。
- 当前运行 Turn 的 Context Inspector 只展示该 Turn 已捕获的 runtime 内容，不主动调用 Home/Memory owner 的读取操作。

## 页面结构

应用外壳由导航栏、顶部栏、主内容区和状态栏组成。主内容包括：

- Chat：连续展示当前日已提交的 User Turn，并在尾部展示当前运行 Turn 的活动状态、动作和回答。
- Workspace：浏览和编辑当日工作区资源。
- Home：切换 actual 基线与 runtime Home 内容，只读浏览不会调用 Agent 的 `read_top`。
- Memory：浏览活动记忆、持久文档与真实引用关系。
- Runtime：查看环境事件、Job、MCP、ACP 和运行状态；Trace 通过统一 Inspector 展开。
- Settings：编辑后端 ConfigDraft 和前端连接偏好，批量应用后重新加载 generation。

Chat 右上角的 Context Inspector 以子页展示当前 Context、Session map、已加载 Home 和已加载 Memory。它们都是读取投影；实际 owner 的读写仍由 Agent/Action 完成。

## 代码组织

| 责任 | 入口 |
|---|---|
| v2 HTTP/WS 与类型 | `src/api/v2/`、`src/app/connection.ts` |
| 运行状态与 Turn 投影 | `src/store/turnStore.ts`、`src/store/connectionStore.ts` |
| 主对话与连续 Session | `src/features/chat/ChatView.tsx`、`turnController.ts` |
| Observation 活动语义 | `src/features/chat/activityBuffer.ts` |
| Context Inspector | `src/features/context/ContextInspectorPanel.tsx` |
| Process/Trace | `src/features/trace/` |
| Settings | `src/features/settings/` |

`TurnView`、`src/derive/`、旧 action registry 和 `/v1` 接口不属于当前运行时模型；历史文档中的引用仅保留在归档记录中。

## 视觉原则

主对话优先保持 c479ca0 的连续阅读、LiveStatus、动作浮层、思考提示、滚动锚点和渐进动画。新 v2 数据只通过适配层接入这些组件，不另建第二套 Chat 状态机。结构化详情使用折叠卡片、摘要和 Context 子页呈现，原始 JSON 只作为明确的诊断入口。
