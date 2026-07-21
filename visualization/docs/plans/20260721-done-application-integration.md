# 20260721 Done：应用接入与前端纯连接模式

> 状态：已完成  
> 对应后端设计/记录：`docs/analysis/20260721-done-application integration next stage plan.md`

## 已完成内容

1. **单一运行入口与实例发现**
   - `tinysoul start --root <project> --mode normal|verbose|model` 是唯一交互运行入口。
   - Endpoint 事件路由固定为 `model`；`--mode` 只影响 Terminal Console 输出。
   - 后端持有项目级进程锁，Endpoint ready 后在用户运行目录原子写入连接描述。

2. **前端纯连接模式**
   - Tauri Rust 侧只提供 `discover_backend` 命令读取连接描述，不再启动/停止 sidecar。
   - React 侧 `useBackend` 负责发现、身份校验、HTTP status 轮询、WebSocket 连接与 gap 恢复。
   - 未连接时展示推荐启动命令与重试按钮，不唤起 Terminal。

3. **统一命令与 Maintenance 状态**
   - 普通输入、control、Maintenance request/decision 均通过 Endpoint 结构化 API 进入同一 `AppCommandGateway`。
   - 前端实现 Maintenance 状态查询面板与 decision 确认/丢弃/停止交互。
   - `app.command.accepted/rejected`、work lifecycle、decision required/resolved 事件驱动 UI 收敛。

4. **事件流与恢复**
   - WebSocket 首帧与 status 均校验 instance/project identity。
   - raw event store 以 `(instance_id, sequence)` 去重。
   - gap 后清空临时执行视图，重新拉取 status、Workspace Manifest、Maintenance 权威投影。

5. **验证**
   - 全量 pytest、Python 静态类型检查、TypeScript/Vite 构建、Rust `cargo check` 均通过。
   - Tauri production build（MSI/NSIS）成功生成。

## 前端相关文件

- `visualization/src-tauri/src/lib.rs` — `discover_backend` 命令。
- `visualization/src/hooks/useBackend.ts` — 连接、轮询、事件流、gap 恢复。
- `visualization/src/api/tinysoul.ts` — Endpoint HTTP client。
- `visualization/src/api/events.ts` — WebSocket 管理。
- `visualization/src/components/MaintenancePanel.tsx` — Maintenance 状态与 decision UI。
