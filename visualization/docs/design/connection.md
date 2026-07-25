# 前端连接与生命周期设计

## 运行模型

`tinysoul start --root <project-root> --mode normal` 是当前唯一的交互运行入口。Terminal 拥有后端进程与退出生命周期；前端只发现并连接当前项目已经运行的实例。

- `--mode` 只控制该 Terminal 的 Console 输出等级；Endpoint 的事件路由固定为 `model`。
- 后端在构建业务 Engine 前持有项目级进程锁；Endpoint ready 后在当前用户运行目录原子写入连接描述。
- 未发现有效实例时，前端弹窗展示推荐启动命令，由用户自行在 Terminal 中运行。
- 前端关闭只断开连接，不请求 `exit_program`；Terminal 中的后端负责正常退出。

## 连接描述

Tauri 通过 Rust 命令读取 App 发布的连接描述（JSON），包含：

```json
{
  "schema_version": 1,
  "protocol_version": 1,
  "instance_id": "instance_...",
  "project_root": "...",
  "project_identity": "sha256-of-canonical-root",
  "pid": 1234,
  "host": "127.0.0.1",
  "port": 49152,
  "token": "process-local-bearer-token"
}
```

前端根据规范化项目根计算 `project_identity`，与描述中的身份校验一致后才建立 HTTP/WebSocket 连接。

## 身份与状态校验

- `GET /v1/status` 返回 instance/project identity、active day、turn active、workspace revision、最新 event sequence 和 maintenance decision pending 状态。
- 若 status 中的 identity 与连接描述不一致，立即断开并回到未连接状态。
- `ready=false` 时继续轮询重试，不能绕过 Daily 初始化访问本地目录。

## 事件流

- **HTTP 补拉**：`GET /v1/events?after=<seq>&mode=model&limit=200`。
- **WebSocket**：`/v1/events/ws`，首帧发送 `{"token": "...", "after": <seq>, "mode": "model"}`。
- 首次连接使用 `after=0`，避免跳过启动 Maintenance 提示。
- 断线重连使用客户端最后提交到 store 的 sequence。
- raw event store 以 `(instance_id, sequence)` 去重并保持因果顺序。
- 收到 `gap=true` 时清空临时执行视图，并重新读取 status、Workspace Manifest、Maintenance 权威投影。

## 安全边界

- token 只保存在 Tauri/React 当前内存，不写入 localStorage、日志或 URL。
- 所有 HTTP 请求携带 `Authorization: Bearer <token>`。
- 401 表示 token 错误；409 表示 Maintenance decision 待处理、revision/digest 过期或状态冲突。

## 前端实现要点

- `src-tauri/src/lib.rs` 提供 `discover_backend` 命令，按项目根定位并读取连接描述。
- `src/hooks/useBackend.ts` 负责发现、身份校验、状态轮询、WebSocket 连接与 gap 恢复。
- `src/api/events.ts` 管理 WebSocket 重连与事件分页。
- `src/store/appStore.ts` 保存当前连接、原始事件流、Workspace 缓存与 UI 选择。
