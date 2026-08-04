# 需求：重启后端后保留当天会话与 Turn Trace

日期：2026-08-04 · 提出方：前端（visualization） · 状态：pending

## 现象

后端重启后，前端丢失当天全部会话历史与 Turn 内部细节：

- 观察事件只存在于 Endpoint 进程内的有界 buffer（2000 条 / 32MB），进程退出即消失；
- 前端发现 instance_id 变化后会清空事件派生视图；`docs/endpoint/frontend integration.md` 明确不存在 `/v1/session/*` 查询，历史无法补拉；
- 用户因此无法在重启后回顾"当天之前聊了什么、每轮做了什么"。

## 目标体验

重启后端并重新连接后，前端仍能展示**当天（当前 Business Day）全部已完成用户轮**：

- 主对话界面恢复每轮的用户输入与最终回答（含状态）；
- 每轮的 Turn Trace 滑窗仍可打开，呈现 cycle/stage/action 输入输出，以及每次 LLM 调用的 message stack（Request+Response）。

## 已确认的后端事实（供设计参考）

- Session 模块（schema v4）已持久化不可变业务事实：输入、输出、逐 Action 的名称/request/outcome/result/references、Summary 图；`core.session.inspect` 可从 record 派生 Projection，但仅供模型侧在当前 Turn 内调用，无对外读取端点。
- `llm.model.request/response` 的完整 payload（message stack、tools、usage、reasoning）目前只在 Observation 流中即时出现，**不落盘**；integration 文档也要求前端不得持久化 model payload。
- 日切归档 `archive/<timestamp>/session/` 拥有跨日事实；当天 active session 在 `runtime/session/`。

## 需求方案（建议二选一或组合）

### 方案 A：Session 只读投影端点（恢复会话骨架）

新增 loopback + bearer 鉴权的只读端点，例如：

- `GET /v1/session/turns?day=current` → 当天全部已提交 Turn 的列表（turn_id、输入、最终输出、状态、起止时间、action 计数）。
- `GET /v1/session/turns/{turn_id}` → 单轮细节投影：逐 cycle/stage、逐 action 的名称/参数/结果状态、failure 三通道。

前端连接/重连后调用一次即可恢复会话骨架。此方案可完整恢复主对话与 action 级 trace，但**不含** LLM message stack。

### 方案 B：LLM 调用投影落盘（恢复完整 trace）

在 Session record 或独立 projection store 中，按 turn 持久化每次 LLM Task 的 request/response 安全投影（即现有 `llm.model.request/response` observation payload，图片二进制已 digest 化），并在方案 A 的 turn 细节端点中按 task 返回。前端据此让历史轮的 message stack 子滑窗与 trace 导出同样可用。

## 前端侧将做的配合

- 连接后对 `GET /v1/session/turns` 做一次恢复拉取，与实时事件流按 turn_id 合并去重（实时事件优先）；gap 恢复路径同样重读该投影。
- 历史轮标记为只读来源（来自 Session 投影而非实时事件），UI 上以细微标识区分。
- 导出的 turn trace 对历史轮同样生效（数据来自投影而非事件缓冲）。

## 边界与非目标

- 不要求恢复进行中的 turn（重启即中断），只恢复已提交历史。
- 不要求跨 Business Day 浏览（可先只支持当天；历史日在 archive 中，后续可再议）。
- 不引入前端本地持久化 model payload（遵守现有安全约束）。
