# Reflection

`GET /v1/maintenance` 返回持久化 availability projection，包括 Home pending 和待处理 Memory dates。Endpoint 不扫描 Archive，也不建立第二份维护状态。

`POST /v1/maintenance` 提交 `kind=daily|home|memory`、command id、metadata；Memory 必须携带 `target_day`。协议不包含 `rebuild_memory`。请求通过 AgentCommands 进入有界根队列；daily 展开成 Home 和触发日前一日的独立 Memory 请求，返回整批受理回执；执行前完成日切并由 owner 检查来源。更早 backlog 使用明确日期请求。容量不足返回 `accepted=false, state=full`，没有任何子请求被部分接受。scheduler 使用相同入口，满载时保留请求等待重试。

User Turn、Reflection Turn 或 daily transition 期间仍可读取配置并 PATCH 保存候选；`POST /v1/config/reload` 返回 `409 config.activation_unavailable`，待 idle 后激活。维护请求本身按其所属队列语义处理。

## Lifecycle Observation

Endpoint 的 `/v1/events` 和 WebSocket 会转发 Reflection owner 的生命周期事件。`maintenance.started`
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
启动的 `turn.started.business_day` 同样是执行日，历史 Session、Memory 与归档 Workspace 独立绑定目标日。
Reflection 不写入 User Session。`maintenance.completed` 使用 `request_id` 和同一
`business_day`，允许历史恢复在缺少新版 started 字段时补全执行日。`request_id` 是两类事件与
`turn.started.request_id` 的关联键。
