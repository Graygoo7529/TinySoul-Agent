# 需求：Maintenance Turn 运行期间的用户输入语义

日期：2026-08-18 · 提出方：前端（visualization） · 状态：pending

## 背景

前端已将 Maintenance Turn 与 User Turn 同形呈现（发起气泡、LiveStatus、停止按钮、
终态通知）。经前后端代码核实，**追加输入的机制链路对维护轮已经完整可用、无需改动**：

- 路由：`app/inputs.py` 在 `turn_active` 时把自由文本路由为 `APPEND_INPUT`（不区分轮种）；
- 信号：`build_input_append_signal` 带当前轮 scope 发射；
- 消费：维护轮与 user 轮共用同一个 `ContextEngine` 类，`SIGNAL_INPUT_APPEND` 照常并入
  该轮 User Inputs（`context/engine.py`）；
- 合并：内核在每个 cycle 边界 `merge_pending_inputs()`（`loop/cycle.py`），追加文本进入
  下一次 MessageStack 构造的 User Inputs 段，对模型可见。

即：今天在维护轮运行中追加的文本**已经会进入维护轮语境并对模型可见**。

## 需求（建议）：补齐"显式消费"的三层语义

1. **提示层语义**：维护轮的身份/任务提示从未告诉模型 User Inputs 里可能出现用户指示、
   应如何对待（遵循优先级、与维护纪律冲突时的取舍）。需要在维护语境的提示层定义追加
   输入的角色与处理约定，避免模型把它当作任务文本的一部分而忽略或误读。
2. **追加与完成判定的交互**：维护轮完成由任务归敛条件决定（`MaintenanceTurnEntry` 检查
   `completion.task` 匹配）；目前没有任何环节考虑未处理的追加指示——追加到达与轮收尾
   存在竞态，用户指示可能落空。需要明确：完成判定前追加指示必须已被处理，或显式说明
   追加不延长维护轮。
3. **结果可见性（可选）**：维护轮不产生用户回答，用户无法直接确认指示是否被采纳。可在
   `maintenance.completed` 的 details 或轮摘要中体现"收到并处理了 N 条用户指示"。

## 可选加固（非阻塞）

`turn.started` payload 目前只带 `input_source`；前端通过 `maintenance.started` 的
`request_id` 关联推导 trigger/target_day。若 `turn.started` 直接携带
`maintenance: {kind, trigger, target_day}` 则更稳，前端可去掉关联逻辑。

## 现状

前端侧不阻塞：maintenance 运行中 Composer 保持可发送（停止按钮照常），追加文本
已能显示为维护轮内的用户气泡（`app.command.accepted` 的 `append_input` 路径），
且机制上已并入维护轮 User Inputs；缺的是上述三层显式语义。
