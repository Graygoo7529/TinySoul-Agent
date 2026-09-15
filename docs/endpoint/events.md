# Events

## Replay

`GET /v1/events?after=0&mode=model&limit=200` 返回 `events`、`next_sequence` 和 `gap`。mode 为 `normal`、`verbose` 或 `model`。前端先从 status 捕获 `latest_event_sequence`，再按 cursor 分页到该目标；`gap=true` 时清理事件派生视图并重新读取权威 status、Maintenance 和 Workspace projection。

## WebSocket

连接地址为 `/v1/events/ws`，首帧为：

```json
{"token":"...","after":0,"mode":"model"}
```

服务端先返回 authenticated，之后发送 events 或 heartbeat。heartbeat 不增加 sequence。前端按 `(instance_id, sequence)` 去重和续传，事件流不写入业务持久事实。

## 运行失败诊断

运行控制事件的 `reason` 与业务失败分类是两层协议：`runtime.trap` 报告 reason 和 transfer；`turn.failed` 等结果事件按自身投影报告 module、kind 等摘要，不保证每个观察事件都携带完整 Runtime payload。客户端按结构化字段识别失败，不解析 message 文本。

LLM 容量恢复使用 `llm.context_capacity_exceeded`，对应模块失败 kind 为 `llm.model_context_pressure`；Context 自身预算原因仍为 `context.compression_required`。共享配置源/Infra 配置的装配失败归 App（`app.configuration_failed`），各业务模块的配置失败仍归各自 owner；User Turn 的执行资源准备失败归 `loop.resource_preparation_failed`。

message 是 owner 提供的有限说明，不再透传原始 Python 异常文本。配置诊断仅包含有界 key/expected，不包含原始值和 source；Home 副本恢复不提供 source_path/runtime_path。恢复使用的资源 Link 和容量度量仍保留在内部协议中。前端不能依赖被删除的诊断字段获得文件访问能力，也不能用 Observation 是否到达判断业务是否提交。

## Journal

可选 Journal 位于 runtime Endpoint 目录，失败时降级到有界内存 buffer。Journal 是可重建的观察索引，不是 Session 或审计数据库；status 只暴露 enabled、degraded 和保留 sequence 范围。
