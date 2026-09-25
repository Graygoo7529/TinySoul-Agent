# Events

## Replay

`GET /v2/events?after=0&mode=model&limit=200` 返回 `instance_id`、`events`、`next_sequence` 和 `gap`。mode 为 `normal`、`verbose` 或 `model`。重连附带上次 `instance_id`；实例不同或 after 超出当前序号时，从当前保留窗口重新 replay 并置 gap。前端先从 status 捕获 `latest_event_sequence`，再按 cursor 分页到该目标；`gap=true` 时清理事件派生视图并重新读取权威 status、活动 Turn、Reflection 和 Workspace projection。

## WebSocket

连接地址为 `/v2/events/ws`，首帧为：

```json
{"token":"...","after":0,"mode":"model","instance_id":"previous-instance"}
```

首次连接可省略 instance_id。服务端先返回 authenticated（protocol_version=2），立即 replay，再发送 events 或 heartbeat；两者均携带当前 instance_id。heartbeat 不增加 sequence。前端按 `(instance_id, sequence)` 去重和续传，事件流不写入业务持久事实。无效认证首帧关闭连接，断线不取消 Turn。

## 运行失败诊断

运行控制事件的 `reason` 与业务失败分类是两层协议：`runtime.trap` 报告 reason 和 transfer；`turn.failed` 等结果事件按自身投影报告 module、kind 等摘要，不保证每个观察事件都携带完整 Runtime payload。客户端按结构化字段识别失败，不解析 message 文本。

`runtime.source_status` 报告原生 Workspace 监听故障，source 为 `workspace.fswatch`，payload 包含 `state=failed`、受影响 topics 和有限 `error_type`。客户端以 status 中的 `runtime.sources` 查询当前状态；不将其解释为文件修改失败或 Agent 已停止。恢复监听使用显式 reload/restart。

LLM 容量恢复使用 `llm.context_capacity_exceeded`，对应模块失败 kind 为 `llm.model_context_pressure`；Context 自身预算原因仍为 `context.compression_required`。共享配置源/Infra 配置的装配失败归 Agent（`agent.configuration_failed`），各业务配置失败归各自 owner；User Turn 的执行资源准备失败归 `loop.resource_preparation_failed`。

message 是 owner 提供的有限说明，不再透传原始 Python 异常文本。配置诊断仅包含有界 key/expected，不包含原始值和 source；Home 副本恢复不提供 source_path/runtime_path。恢复使用的资源 Link 和容量度量仍保留在内部协议中。前端不能依赖被删除的诊断字段获得文件访问能力，也不能用 Observation 是否到达判断业务是否提交。

## 模型用途观察

LLM 继续使用现有 task_id 关联一次调用，Action 内部任务增加 consumer、implementation 和 target，实际 provider/model 与尝试沿现有 LLM 事件报告，不增加重复调用身份。Embedding/JEV 使用 `model.call.started/retry/completed/failed/cancelled`，verbose payload 包括 call_id、consumer、implementation、target、provider、model、attempt/retry、elapsed_seconds、usage 和有限 failure；Embedding 另外报告 input_count/dimensions，不返回向量。

显式 model 分级可收到 `model.call.detail` 的已准备输入/结果。父 Turn/Cycle/Action 关联沿 Observation scope；SDK 查询无父 Action 时使用独立 call_id，不伪造 invoke_id。事件是旁路，sink 失败不改变模型调用或业务提交；catalog 不保存最近调用结果。

## Journal

可选 Journal 位于 runtime Endpoint 目录，失败时降级到有界内存 buffer。Journal 是可重建的观察索引，不是 Session 或审计数据库；status 只暴露 enabled、degraded 和保留 sequence 范围。
