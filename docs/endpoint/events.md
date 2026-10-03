# Events

## Replay

`GET /v2/events?after=0&mode=model&limit=200` 返回 `instance_id`、`events`、`next_sequence` 和 `gap`。mode 为 `normal`、`verbose` 或 `model`。重连附带上次 `instance_id`；实例不同或 after 超出当前序号时，从当前保留窗口重新 replay 并置 gap。前端先从 status 捕获 `latest_event_sequence`，再按 cursor 分页到该目标；`gap=true` 时清理事件派生视图并重新读取权威 status、活动 Turn、Reflection 和 Workspace projection。

## WebSocket

HTTP replay 还接受 `turn_id, task_id, call_id, search_id, step_index, through`。过滤条件同时满足；step_index 必须与 search_id 同用。through 是固定扫描上界。next_sequence 表示扫描过的全局位置，无匹配也前进；不能按返回条数推进游标。WS 仍只按 normal/verbose/model 分级；默认订阅 verbose，展开模型正文时按 task_id/call_id 查询 model。

连接地址为 `/v2/events/ws`，首帧为：

```json
{"token":"...","after":0,"mode":"model","instance_id":"previous-instance"}
```

首次连接可省略 instance_id。服务端先返回 authenticated（protocol_version=2），立即 replay，再发送 events 或 heartbeat；两者均携带当前 instance_id。heartbeat 不增加 sequence。前端按 `(instance_id, sequence)` 去重和续传，事件流不写入业务持久事实。无效认证首帧关闭连接，断线不取消 Turn。

## 运行失败诊断

运行控制事件的 `reason` 与业务失败分类是两层协议：`runtime.trap` 报告 reason 和 transfer；`turn.failed` 等结果事件按自身投影报告 module、kind 等摘要，不保证每个观察事件都携带完整 Runtime payload。客户端按结构化字段识别失败，不解析 message 文本。

`runtime.source_status` 报告原生 Workspace 监听故障，source 为 `workspace.fswatch`，payload 包含 `state=failed`、受影响 topics 和有限 `error_type`。客户端以 status 中的 `runtime.sources` 查询当前状态；不将其解释为文件修改失败或 Agent 已停止。恢复监听使用显式 reload/restart。

`workspace.changed` 的 `updated_links` 包含 owner 正式写入的已有资源；即使等长内容写入后文件时间戳相同，也会通知更新。外部监听变化仍由 owner reconcile 后发布。

LLM 容量恢复使用 `llm.context_capacity_exceeded`，对应模块失败 kind 为 `llm.model_context_pressure`；Context 自身预算原因仍为 `context.compression_required`。共享配置源/Infra 配置的装配失败归 Agent（`agent.configuration_failed`），各业务配置失败归各自 owner；User Turn 的执行资源准备失败归 `loop.resource_preparation_failed`。

message 是 owner 提供的有限说明，不再透传原始 Python 异常文本。配置诊断仅包含有界 key/expected，不包含原始值和 source；Home 副本恢复不提供 source_path/runtime_path。恢复使用的资源 Link 和容量度量仍保留在内部协议中。前端不能依赖被删除的诊断字段获得文件访问能力，也不能用 Observation 是否到达判断业务是否提交。

## 模型用途观察

LLM 继续使用现有 task_id 关联一次调用，Action 内部任务增加 consumer、implementation 和 target，实际 provider/model 与尝试沿现有 LLM 事件报告，不增加重复调用身份。Embedding/JEV 使用 `model.call.started/retry/completed/failed/cancelled`，verbose payload 包括 call_id、consumer、implementation、target、provider、model、attempt/retry、elapsed_seconds、usage 和有限 failure；Embedding 另外报告 input_count/dimensions，不返回向量。

LLM 请求 detail 的 provenance 包含 `segment_id, owner, slot, shape, message_indices, refs`，索引为零起始，对应同 payload 的实际 messages。TaskPrompt/guidance 单独标识，Home refs 来自 owner。resolved_references 保存该次消息实际绑定的动态资源定位。它们不是提示正文，不影响供应商请求；这里展示的是 provider-neutral MessageStack，不是原始 HTTP 包。

`llm.model.response.tool_calls` 中供应商未提供的 `kind` 由该次请求的可见 ToolScope 补齐为 `control` 或 `action`；未登记的调用保留空类别。该类别只标识工具语义，不表示调用已通过校验或已执行。Phase1 的 `select_action_domains.arguments.intent` 可用于展示域选择思路，实际接受的域仍由 Phase 完成事件报告。

`context.background.snapshot` 在 Turn 打开 Heap 时给出当前 top-level refs；`context.background.changed` 给出真实 `loaded_links`、`evicted_links` 和变化后的 `links`。`context.installed` 只提示所属 turn_id 的段已安装；`expand.directory.changed` 提示 MCP 目录已变化。发生 gap 后重新读取 owner 视图，不以事件代替事实。

`loop.phase.started/completed` 沿 scope 标识 Turn/Cycle/Phase，时间取事件 `created_at`。completed 的 `cancelled` 表示取消，`failed` 表示局部 Phase 或模块失败；`ended/transfer_action` 描述运行转移，不单独推断失败。Phase1 成功完成时另外提供已接受的 `selected_domains`，不能把模型 Control Tool 请求当成已接受选择。这些事件供 Activity/Trace 展示，正文仍从 Context/Session owner 读取。

`context.control.applied` 在 Context 批次安装成功后按操作顺序发布，verbose payload 为 `call_id, operation, details`，scope 保留原请求的 Turn/Cycle/Phase。operation 为 set/remove_todo、set/remove_milestone、load/evict_background；details 分别包含 key/content/status、key/content、移除 key 或 links。它报告已应用的显式控制，不报告初始背景装配或任务局部 Skill；整个批次先安装，再发布观察，不表示中间状态逐个对模型可见。现态仍读取 Context 的 plan/background。

Phase1 的 completed 事件如有局部控制拒绝，会携带 `control_results`（call_id、tool_name、status、stage、feedback），即使该 Phase 随后失败也保留。consume 阶段的 tool_name 可能是 Signal 名，客户端按 call_id 关联原始 Control Tool 请求。拒绝的控制不发布 applied；Observation 缺失不能反向解释为操作未提交。

显式 model 分级可收到 `model.call.detail` 的已准备输入/结果。父 Turn/Cycle/Action 关联沿 Observation scope；SDK 查询无父 Action 时使用独立 call_id，不伪造 invoke_id。事件是旁路，sink 失败不改变模型调用或业务提交；catalog 不保存最近调用结果。

## Journal

可选 Journal 位于 runtime Endpoint 目录，失败时降级到有界内存 buffer。Journal 是可重建的观察索引，不是 Session 或审计数据库；status 只暴露 enabled、degraded 和保留 sequence 范围。

## 检索步骤关联

retrieval.step.completed 在 verbose 级提供 search_id、action、step_index、op、input/output 数量（模型步骤另有 evaluated）及 elapsed_seconds。即使同一次 Search 两次执行 rerank，step_index 也分别标识其位置。空集合上的步骤记录零数量，不伪造模型调用。

LLM 的 retrieval.model.invoked 通过 search_id、step_index、op、consumer 与 task_id 连接现有 LLM 事件；它只表示任务已发起，成功失败仍读 LLM 终态。专用模型 model.call 事件带相同 search_id 和 step_index；query 通道的 phase 为 source、step_index 为 null，候选操作的 phase 为 step。沿现有 call_id 追踪专用调用，不复制模型或搜索历史。
