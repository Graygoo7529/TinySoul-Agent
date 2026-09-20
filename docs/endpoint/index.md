# Endpoint 协议

Endpoint 是 loopback 本地协议。除 `GET /v2/health` 外，HTTP 请求都需要 `Authorization: Bearer <token>`；WebSocket 在连接建立后发送 token 首帧。连接描述由 App 发布，包含 host、port、token、instance_id、project_identity 和 project_root，Visualization 必须核对实例身份。

## 路由总表

| 领域 | 路径 | 语义 |
| --- | --- | --- |
| Health | `GET /v2/health` | 匿名进程探活 |
| Runtime | `GET /v2/status` | 当前进程与 Runtime snapshot |
| Runtime | `POST /v2/input` | 提交 User input |
| Runtime | `POST /v2/control` | 提交 stop/exit control |
| Turn | `POST /v2/turns`、`GET /v2/turns/{id}` | 结构化受理和 owner 状态/结果 |
| Turn | `POST /v2/turns/{id}/input`、`reply`、`grant`、`cancel` | 指定 Turn 的输入与控制 |
| Job | `GET /v2/turns/{id}/jobs`、`POST /v2/turns/{id}/jobs/{job_id}/stop` | Turn-owned 查询与停止 |
| Reflection | `GET/POST /v2/reflection` | 读取 availability、提交维护请求 |
| Events | `GET /v2/events` | Observation replay |
| Events | `WS /v2/events/ws` | Observation stream |
| Configuration | `GET /v2/config` | 配置源/effective fields/runtime 状态 |
| Configuration | `GET /v2/config/catalog` | Infra 配置展示 catalog |
| Configuration | `GET /v2/config/actions` | 当前 Generation Action 配置投影 |
| Configuration | `PATCH /v2/config` | 校验并保存配置候选 |
| Configuration | `POST /v2/config/reload` | 在 idle 边界显式激活候选 |
| Workspace | `/v2/workspace/*` | manifest、resource/blob、trash/restore |

不存在 `/v2/actions/catalog`、`/v2/config/sections/{section_id}`、`/v2/config/validate` 或 `/v2/session/*`。`GET /openapi.json`（需鉴权）是路径和 schema 的机器可读权威描述。

## 错误

```json
{"error":{"code":"workspace.conflict","message":"Workspace request conflicts with the current resource or is invalid.","details":{}}}
```

`401` 表示鉴权失败，`409` 表示未 ready、运行中、目标冲突或 owner 拒绝的资源操作，`413` 表示大小超限，`422` 表示 schema/配置值无效，`500` 表示收敛后的模块或服务失败。

服务在世代或日期切换后失效返回 `409 service.stale`；Agent 停止受理返回 `409 agent.not_ready`；owner 准备失败返回 `409 service.unavailable`，details 中包含 module/kind。客户端重新读取当前状态后决定后续操作，后端不自动重放写入。

结构化受理满载为 `409 agent.queue_full`，请求身份冲突为 `409 agent.command_rejected`；Inbox 容量与等待关联错误分别为 `409 turn.inbox_full`、`409 turn.command_rejected`。未知/淘汰 Turn 为 `404 turn.not_found`，已回收或不属于该 Turn 的 Job 为 `404 turn.resource_not_found`。所有错误采用同一 envelope，不暴露原始异常文本。

v1 路由不再存在；HTTP 不提供项目 reset 或 Agent restart，初始化与进程重建由 CLI/SDK 宿主负责。

详细协议见 [runtime](runtime.md)、[reflection](reflection.md)、[events](events.md)、[configuration](configuration.md)、[workspace](workspace.md) 和 [frontend integration](frontend-integration.md)。
