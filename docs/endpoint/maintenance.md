# Maintenance

`GET /v1/maintenance` 返回持久化 availability projection，包括 Home pending 和待处理 Memory dates。Endpoint 不扫描 Archive，也不建立第二份维护状态。

`POST /v1/maintenance` 提交 `kind=daily|home|memory`、command id、metadata；Memory 必须携带 `target_day`。协议不包含 `rebuild_memory`。请求进入 Program queue，和 scheduler 使用相同 MaintenanceEngine 流程。

User Turn、Maintenance Turn 或 daily transition 期间配置页面仍可读取，但 `PATCH /v1/config` 会返回 `409 config.activation_unavailable`；维护请求本身按其所属队列语义处理。

## Lifecycle Observation

Endpoint 的 `/v1/events` 和 WebSocket 会转发 Maintenance owner 的生命周期事件。`maintenance.started`
的 payload 形状为：

```json
{
  "business_day": "2026-08-18",
  "request": {
    "scope": "memory",
    "trigger": "manual",
    "request_id": "command_x",
    "target_day": "2026-08-17",
    "source": "endpoint",
    "metadata": {}
  }
}
```

顶层 `business_day` 是维护请求的当前执行日；`request.target_day` 是 Memory 目标日。维护任务
启动的 `turn.started.business_day` 可能等于目标日（Memory Maintenance），前端不得用它替代
生命周期执行日判断主对话归属。`maintenance.completed` 使用 `request_id` 和同一
`business_day`，允许历史恢复在缺少新版 started 字段时补全执行日。`request_id` 是两类事件与
`turn.started.request_id` 的关联键。
