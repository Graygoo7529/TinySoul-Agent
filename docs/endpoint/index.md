# Endpoint 协议

Endpoint 是 loopback 本地协议。除 `GET /v1/health` 外，HTTP 请求都需要 `Authorization: Bearer <token>`；WebSocket 在连接建立后发送 token 首帧。连接描述由 App 发布，包含 host、port、token、instance_id、project_identity 和 project_root，Visualization 必须核对实例身份。

## 路由总表

| 领域 | 路径 | 语义 |
| --- | --- | --- |
| Health | `GET /v1/health` | 匿名进程探活 |
| Runtime | `GET /v1/status` | 当前进程与 Runtime snapshot |
| Runtime | `POST /v1/input` | 提交 User input |
| Runtime | `POST /v1/control` | 提交 stop/exit control |
| Maintenance | `GET/POST /v1/maintenance` | 读取 availability、提交维护请求 |
| Events | `GET /v1/events` | Observation replay |
| Events | `WS /v1/events/ws` | Observation stream |
| Configuration | `GET /v1/config` | 配置源/effective fields/runtime 状态 |
| Configuration | `GET /v1/config/catalog` | Infra 配置展示 catalog |
| Configuration | `GET /v1/config/actions` | 当前 Generation Action 配置投影 |
| Configuration | `PATCH /v1/config` | 持久化并激活配置 |
| Workspace | `/v1/workspace/*` | manifest、resource/blob、trash/restore |

不存在 `/v1/actions/catalog`、`/v1/config/sections/{section_id}`、`/v1/config/validate` 或 `/v1/session/*`。`GET /openapi.json`（需鉴权）是路径和 schema 的机器可读权威描述。

## 错误

```json
{"error":{"code":"workspace.conflict","message":"Workspace revision mismatch.","details":{}}}
```

`401` 表示鉴权失败，`409` 表示未 ready、运行中或 CAS 冲突，`413` 表示大小超限，`422` 表示 schema/配置值无效，`500` 表示收敛后的模块或服务失败。

详细协议见 [runtime](runtime.md)、[maintenance](maintenance.md)、[events](events.md)、[configuration](configuration.md)、[workspace](workspace.md) 和 [frontend integration](frontend-integration.md)。
