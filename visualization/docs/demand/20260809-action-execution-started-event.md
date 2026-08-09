# 需求：Action 执行开始事件 action.execution.started（可选、非阻塞）

日期：2026-08-09 · 提出方：前端（visualization） · 状态：pending

## 背景

`action.call` 只在 Phase2 归一化成功后发射一次（scope 永远带 `phase:phase2`），Phase3 执行
ActionBatch 时不重发；Phase3 期间前端能收到的事件只有 `action.batch.started/completed` 与
逐个 `action.result`。因此"批次内哪个 action 正在执行"在协议上不可直接观测。

前端目前采用纯前端方案：收到 `loop.phase.started(phase3)` / `action.batch.started` 时，把
Phase2 的 planned 记录预镜像进 Phase3，假定"最早无 result 的镜像记录"为运行项，按 call_id
认领 result。该方案已上线且效果良好（运行中标题、action 计时、执行进度 (i/n) 均可用）。

其局限是：批次内多个 action 并发执行时，前端只能串行式地展示"第一个未完成项在跑"，
与真实并发执行情况有偏差；长耗时 action 的精确开始时刻也无从得知。

## 需求（建议）

在后端 ActionRunner 启动单个 action 执行处，发射 VERBOSE 级事件（如
`action.execution.started`，source `action.runner`，scope 带当前 phase3 帧）：

```json
{ "call_id": "…", "action": "execution.run_python_script", "batch_id": "…", "invoke_id": "…" }
```

前端收到后按 call_id 精确标记运行项（可多个并发）；未收到时维持现有镜像启发式回退。

## 现状

不阻塞。phase3 预镜像启发式已覆盖串行批次的全部展示需求；仅并发批次的运行项精确度
与真实开始时刻不可得。
