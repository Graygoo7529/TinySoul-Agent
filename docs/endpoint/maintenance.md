# Maintenance

`GET /v1/maintenance` 返回持久化 availability projection，包括 Home pending 和待处理 Memory dates。Endpoint 不扫描 Archive，也不建立第二份维护状态。

`POST /v1/maintenance` 提交 `kind=daily|home|memory`、command id、metadata；Memory 必须携带 `target_day`。协议不包含 `rebuild_memory`。请求进入 Program queue，和 scheduler 使用相同 MaintenanceEngine 流程。

User Turn、Maintenance Turn 或 daily transition 期间配置页面仍可读取，但 `PATCH /v1/config` 会返回 `409 config.activation_unavailable`；维护请求本身按其所属队列语义处理。
