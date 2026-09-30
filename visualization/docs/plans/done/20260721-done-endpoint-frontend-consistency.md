# 20260721 Done：Endpoint-Frontend 一致性收尾

> 完成日期：2026-07-19  
> 责任范围：前端（`visualization/`）  
> 依据：`docs/endpoint/frontend integration.md`  
> 原执行计划：`20260721-plan-endpoint-frontend-consistency.md`（已归档删除）

## 完成项

### 1. `ready=false` 状态单独处理

- `useBackend.connect` 在 `GET /v1/status` 成功后检查 `status.ready`。
- `ready=false` 时连接状态置为 `initializing`，UI 展示“Backend is initializing…”并继续轮询。
- 只有 `ready=true` 才建立 `TinySoulClient` 与 WebSocket 事件流并渲染主界面。
- 影响文件：`src/hooks/useBackend.ts`、`src/App.tsx`、`src/components/AppShell.tsx`。

### 2. `workspace.changed` 失效刷新

- WebSocket 事件处理监听 `workspace.changed`。
- 比较事件 `revision/day` 与本地 Manifest：若事件更新则拉取最新 Manifest。
- 刷新后仅替换 `workspace` 缓存，保留 `openResource.draft`；若当前打开资源已被删除/移动则关闭编辑器。
- 影响文件：`src/hooks/useBackend.ts`。

### 3. Workspace 冲突时保留编辑草稿

- `useWorkspace` 识别 HTTP 409 / `workspace.conflict` 错误，不再清空 Workspace 缓存。
- 冲突时设置 `workspaceConflict` 标志，并刷新 Manifest 与当前资源正文。
- `WorkspaceView` 展示冲突提示条，提供“Overwrite”与“Reload”选项。
- 影响文件：`src/hooks/useWorkspace.ts`、`src/components/WorkspaceView.tsx`、`src/store/appStore.ts`。

### 4. Sequence gap 后执行视图不完整提示

- gap 后设置 `eventStreamInterrupted=true`。
- `ChatView` 在消息区顶部展示非侵入提示条。
- 收到 `turn.started` 或 `context.background.snapshot` 后清除标志。
- 影响文件：`src/hooks/useBackend.ts`、`src/components/ChatView.tsx`、`src/store/appStore.ts`。

### 5. MODEL 事件安全消费

- 审查并移除可能完整打印 MODEL payload 的日志。
- WebSocket 错误仅打印 `error.name/message`，不打印事件内容。
- `appStore` persist 仍只持久化 `projectRoot`，不持久化 events/connection info。
- 影响文件：`src/hooks/useBackend.ts`、`src/store/appStore.ts`。

### 6. Maintenance decision 阻塞输入提示

- `ChatView` 在 `status.maintenance_decision_pending === true` 时于 composer 上方展示提示条。
- 发送按钮在 maintenance pending 时禁用，避免用户发送后收到 409。
- 影响文件：`src/components/ChatView.tsx`。

### 7. Session hard pager 协议同步（历史记录）

本节记录当时已完成的混合 recall 适配；该协议先于 2026-07-24 被 Session Explorer 方案取代，随后 Session Explorer 及其三条 REST 又于 2026-07-25 整体删除。当前前端只从真实 MessageStack Observation 呈现 Session 内容；现行记录见 `20260725-done-session-explorer-removal.md`。

## 验证

- `pnpm exec tsc --noEmit` ✅
- `pnpm run build` ✅
- `pnpm tauri build` ✅
- `python -m pytest tests -q` ✅
- `ty check` ✅
