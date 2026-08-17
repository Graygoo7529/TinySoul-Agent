# 需求：Maintenance Turn 运行期间的用户输入语义

日期：2026-08-18 · 提出方：前端（visualization） · 状态：pending

## 背景

前端已将 Maintenance Turn 与 User Turn 同形呈现（发起气泡、LiveStatus、停止按钮、
终态通知）。maintenance 轮经共享 Turn 内核运行，事件协议与 user 轮一致
（`turn.started` 带 `input_source: maintenance.home|maintenance.memory`）。

遗留一个输入语义问题：`app/inputs.py` 在 `turn_active` 时把用户自由文本一律路由为
`APPEND_INPUT`，append 信号发往当前轮 scope；maintenance 轮与 user 轮共用同一个
`ContextEngine`，会把该文本并入维护轮的 User Inputs——用户的话被吞进维护语境，
既不是用户意图，也污染维护任务。

## 需求（建议）

经与维护者确认，期望语义：**maintenance 轮运行期间接受用户追加输入，作为用户指示
被维护轮显式消费**——与 user 轮的追加输入同构（在 cycle 边界合并进当前轮语境、
对模型可见），而非静默混入或丢失。维护轮不产生用户回答的语义不变；追加的指示
只影响维护工作的走向。

替代方案（次选）：maintenance 期间的用户输入排队为下一个 user turn，在维护轮
结束后启动。两案都需要后端在输入路由处区分当前轮种。

## 可选加固（非阻塞）

`turn.started` payload 目前只带 `input_source`；前端通过 `maintenance.started` 的
`request_id` 关联推导 trigger/target_day。若 `turn.started` 直接携带
`maintenance: {kind, trigger, target_day}` 则更稳，前端可去掉关联逻辑。

## 现状

前端侧不阻塞：maintenance 运行中 Composer 保持可发送（停止按钮照常），追加文本
已能显示为维护轮内的用户气泡（`app.command.accepted` 的 `append_input` 路径）。
在后端语义落地前，追加文本会被并入维护轮 User Inputs（影响限于维护任务语境）。
