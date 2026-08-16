# Events

## Replay

`GET /v1/events?after=0&mode=model&limit=200` 返回 `events`、`next_sequence` 和 `gap`。mode 为 `normal`、`verbose` 或 `model`。前端先从 status 捕获 `latest_event_sequence`，再按 cursor 分页到该目标；`gap=true` 时清理事件派生视图并重新读取权威 status、Maintenance 和 Workspace projection。

## WebSocket

连接地址为 `/v1/events/ws`，首帧为：

```json
{"token":"...","after":0,"mode":"model"}
```

服务端先返回 authenticated，之后发送 events 或 heartbeat。heartbeat 不增加 sequence。前端按 `(instance_id, sequence)` 去重和续传，事件流不写入业务持久事实。

## Journal

可选 Journal 位于 runtime Endpoint 目录，失败时降级到有界内存 buffer。Journal 是可重建的观察索引，不是 Session 或审计数据库；status 只暴露 enabled、degraded 和保留 sequence 范围。
