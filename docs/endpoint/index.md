# Endpoint 协议

## Contract artifacts

The versioned response projection used by visualization is documented in
[`contracts/`](contracts/README.md). It includes fixed envelopes, page/search
schemas, and sanitized fixtures for runtime, Turn, Context, Home, Memory,
Search, Job, ACP, MCP, and model observations.

Endpoint 是 loopback 本地协议。除 `GET /v2/health` 外，HTTP 请求都需要 `Authorization: Bearer <token>`；WebSocket 在连接建立后发送 token 首帧。连接描述由 App 发布，包含 host、port、token、instance_id、project_identity 和 project_root，Visualization 必须核对实例身份。

## 路由总表

| 领域 | 路径 | 语义 |
| --- | --- | --- |
| Health | `GET /v2/health` | 匿名进程探活 |
| Runtime | `GET /v2/status` | 当前进程与 Runtime snapshot |
| Runtime | `POST /v2/input` | 提交 User input |
| Runtime | `POST /v2/control` | 提交 stop/exit control |
| Runtime | `POST /v2/restart` | 请求宿主重建 Agent generation，保持 Endpoint instance |
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
| Workspace | `/v2/workspace/*` | 当前/归档浏览，活动日编辑 |
| Configuration | `POST /v2/config/apply`、`/v2/config/presets` | 整批发布、命名方案 |
| Inspection | `/v2/days`、`/v2/session/*`、`/v2/turns/{id}/context*`、`/v2/turns/{id}/interactions` | 已提交历史、已安装 Context、活动交互与已安装 Heap 正文快照 |
| Resources | `/v2/home/*`、`/v2/memory/*`、`/v2/resources/resolve` | owner 浏览与定位；search 为显式 POST |
| Capabilities | `/v2/subagent`、`/v2/expand/*`、Job detail/output | 现有连接、目录与 backend 的只读投影 |

不存在 `/v2/actions/catalog`、`/v2/config/sections/{section_id}`、`/v2/config/validate` 或 Session 外部编辑接口。`GET /openapi.json`（需鉴权）是路径和请求 schema 的机器可读权威描述。新增读取协议见 [浏览与定位](inspection.md)。

Action 目录以 execution.executor、model_uses、retrieval 和有效工具 schema 呈现能力；模型配置和调用观察见 configuration/events。检索通过 Agent Action 与 SDK 查询服务提供，本协议不增加通用 `/v2/actions/run`。

## 错误

```json
{"error":{"code":"workspace.conflict","message":"Workspace request conflicts with the current resource or is invalid.","details":{}}}
```

`401` 表示鉴权失败，`409` 表示未 ready、运行中、目标冲突或 owner 拒绝的资源操作，`413` 表示大小超限，`422` 表示 schema/配置值无效，`500` 表示未预期的内部失败，`503` 表示服务或来源不可用。

服务在世代或日期切换后失效返回 `409 service.stale`；Endpoint 无可用绑定或 Agent 尚未完成激活时返回 `409 service.unavailable`；已进入 SDK 但 Agent 停止受理的请求返回 `409 agent.not_ready`。SDK 的 `AgentServiceUnavailableError` 默认返回 `503 service.unavailable`，details 包含 module/kind；其中活动 Context 不可用映射为 `409 context.unavailable`，动态资源缺少来源绑定映射为 `422 resource.unresolved_origin`。客户端重新读取当前状态后决定后续操作，后端不自动重放写入。

结构化受理满载为 `409 agent.queue_full`，请求身份冲突为 `409 agent.command_rejected`；Inbox 容量与等待关联错误分别为 `409 turn.inbox_full`、`409 turn.command_rejected`。未知/淘汰 Turn 为 `404 turn.not_found`，已回收或不属于该 Turn 的 Job 为 `404 turn.resource_not_found`。所有错误采用同一 envelope，不暴露原始异常文本。

未挂载宿主重启能力返回 `409 endpoint.lifecycle_unavailable`；重启中的 Runtime 失败返回 `503 agent.restart_failed`，details 只包含稳定 reason。Endpoint 保持可用，客户端可查询状态并显式重试。

v1 路由不再存在；HTTP 不提供项目 reset，初始化仍由 CLI 提供。`POST /v2/restart` 只请求宿主重建 Agent generation，不迁移 Turn/Job；失败和重启期间通过 status 读取当前服务状态。ACP Job 应答不属于通用 Gateway 协议。

详细协议见 [runtime](runtime.md)、[reflection](reflection.md)、[events](events.md)、[configuration](configuration.md)、[workspace](workspace.md)、[inspection](inspection.md) 和 [frontend integration](frontend-integration.md)。
