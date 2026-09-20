# Runtime 与 Turn

## 状态与生命周期

`GET /v2/status` 返回 `protocol_version=2`、instance/project identity、ready、active day、Turn 活动状态和 Observation cursor/journal 摘要。`runtime` 与 SDK `Agent.runtime_status()` 使用同一内存投影：generation、activity/activation、active day、active_turn_id、queued_turn_ids 和来源状态。状态查询不触发日切或加载文件；工作受理后的确定性准备仍由 Agent 负责。

`runtime.sources` 为来源 owner 投影，包含 source、state、topics 和有界 error_type。监听故障不表示正式 Workspace 操作不可用。进程初始化、reset、start 由 CLI 提供；SDK 的 restart/shutdown 由宿主控制。HTTP 通过独立 `POST /v2/restart` 请求宿主重建当前 Agent generation，不提供项目 reset；配置世代切换使用显式 config/reload。

`POST /v2/restart` 等待旧 generation 收尾并由宿主装配、激活新 generation 后返回 `accepted`、新的 runtime projection 和 cleanup diagnostics。Endpoint server、`instance_id`、Observation journal 与游标空间保持稳定，`generation_id` 改变；旧 commands、services 和 Turn/Job lease 失效，调用者重新读取状态并获取当前 facade。重启期间 generation 暂不可用时，status 仍可访问并返回 `ready=false`。

宿主未挂载重启能力时返回 `409 endpoint.lifecycle_unavailable`。重建的 Runtime 失败返回 `503 agent.restart_failed`，只附带稳定 reason；Endpoint 保持可访问，可读取 status 并显式再次请求 restart。未绑定 generation 时，业务操作返回 `409 service.unavailable`，健康检查、状态与 Observation replay 仍可使用；不自动重试重启请求。

## 结构化 Turn

`POST /v2/turns` 创建独立根请求，已有活动或等待 Turn 时排队；text 中的斜杠命令保持普通文本，不进入终端解析器。

```json
{"kind":"user","text":"analyze the workspace","command_id":"command_123","metadata":{"client_message_id":"msg_123"}}
```

kind 默认 user；home/memory 表示同一 Agent 的独立 Reflection 情景，使用 instructions，memory 还必须指定 target_day。User 不接受 Reflection 字段，Reflection 不接受 text。`POST /v2/reflection` 是限定维护情景的领域入口，复用同一受理实现。

成功返回 202 和 `accepted / command_id / turn_id / kind / state`。这是受理事实，不是执行结果；相同 command_id 与内容在活动及结果保留窗口内复用同一 Turn，内容不同返回 409。容量不足返回 409 agent.queue_full。未提供 command_id 时由服务端生成；需要安全重试的客户端应主动指定。

`GET /v2/turns/{turn_id}` 返回与 SDK TurnSnapshot 相同的投影：kind、state、cancel_requested、wait_reason、question、budget_request、result、jobs。state 为 queued/preparing/running/waiting/finalizing/finished。问题与预算请求可同时存在；reply 不补预算，grant 不冒充回复。

result 尚未完成时为 null；完成后与 SDK TurnResult.to_json() 一致。User 结果包含正式 output 或 completion、有限 failure、finish_failures 和独立 cleanup；Reflection 结果保留各任务及其目标日期；执行前取消/失败使用 request_failure，不伪造执行事实。结果不包含 Context trace、Runtime transfer 或私有对象。

句柄保留有界。未知或已淘汰身份返回 404 turn.not_found；Endpoint 不从 Observation 或 Session 重新构造运行结果。reload 后已完成的句柄仍保留原结果；SDK restart 重新装配后，旧服务拒绝操作，旧持有句柄只能读取原结果。

| 操作 | 请求体 | 回执 |
|---|---|---|
| POST /v2/turns/{id}/input | text、可选 input_id | Inbox sequence、record_id、accepted |
| POST /v2/turns/{id}/reply | question_id、response | Inbox sequence、record_id、accepted |
| POST /v2/turns/{id}/grant | request_id、正整数 count | turn_id、request_id、accepted |
| POST /v2/turns/{id}/cancel | 无 | turn_id、accepted |
| GET /v2/turns/{id}/jobs | 无 | turn_id、jobs |
| POST /v2/turns/{id}/jobs/{job_id}/stop | 无 | owner 的 JobSnapshot |

重复 input/reply 的 accepted=false 表示该记录已受理，不代表执行失败。过期等待或关闭的 Inbox 返回 409。cancel 的 accepted 仅表示取消意图可受理；最终结果需继续查询，收尾已经完成时不会改写它。

Job 查询和停止经 Agent 服务进入 Job owner；返回 job_id、kind、state、summary、reason。停止等待受控执行收敛，不等于取消 Turn；Job 在所属 Turn 收尾后被回收，列表为空，不另建历史表。停止与收尾由同一 owner 串行处理；错误只暴露有限分类。跨 Turn 或已回收 Job 返回 404 turn.resource_not_found。Job 应答不提供通用 Gateway 路由，随 S6 ACP adapter 的真实权限请求协议另行细化。

## 终端式输入与控制

`POST /v2/input` 接受 text、command_id、metadata，保留明确的终端式输入语义：空闲时新建 User Turn，活动时追加，且支持本地命令语法。需要固定身份/排队语义的客户端使用上述结构化 Turn 接口。该入口返回原有 CommandReceipt；满载为 accepted=false、state=full。

`POST /v2/control` 接受 stop_turn 或 exit_program，经共享 Agent 命令门面执行。前者取消活动根 Turn，保留排队请求；后者停止受理、取消当前与排队工作。Endpoint 不自行终止进程；关闭 WebSocket 或前端窗口不提交退出控制。
