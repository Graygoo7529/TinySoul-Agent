# 需求：重启后端后保留当天会话与 Turn Trace

日期：2026-08-04 · 提出方：前端（visualization） · 状态：done

## 现象

后端重启后，前端丢失当天全部会话历史与 Turn 内部细节：

- 观察事件只存在于 Endpoint 进程内的有界 buffer（2000 条 / 32MB），进程退出即消失；
- 前端发现 instance_id 变化后会清空事件派生视图；`docs/endpoint/frontend integration.md` 明确不存在 `/v1/session/*` 查询，历史无法补拉；
- 用户因此无法在重启后回顾"当天之前聊了什么、每轮做了什么"。

## 目标体验

重启后端并重新连接后，前端仍能展示**当天（当前 Business Day）全部已完成用户轮**：

- 主对话界面恢复每轮的用户输入与最终回答（含状态）；
- 每轮的 Turn Trace 滑窗仍可打开，呈现 cycle/stage/action 输入输出，以及每次 LLM 调用的 message stack（Request+Response）。

## 落地方案（已确认并实施）

采用 **Endpoint 持久事件 Journal**（非 Session REST）：

- 路径 `runtime/endpoint/events/`，分段 NDJSON，启动续 sequence，按大小滚动淘汰；
- `/v1/events` 协议不变；内存热缓存 + journal 深读；
- 前端与后端成对重启后重新解析 lease，以 status 的最新 sequence 快照为目标从 `after=0` 分页全量重放，不设置静默页数上限；恢复轮细微标识；
- 本地对早先 `llm.model.*` payload 骨架化，详情/导出时按 sequence 深读回填；提供「加载更早」。

## 前端侧配合（已落地）

- 连接后 REST 以单调 cursor 完整消费 status sequence 快照，再挂 WebSocket 到实际恢复的最新 sequence；
- 历史轮标记 `restored`；
- 导出/详情前 hydrate skeleton sequences。

## 边界与非目标

- 不要求恢复进行中的 turn（重启即中断），只恢复已提交历史；前端将未完成历史轮收敛为 stopped。
- 不要求跨 Business Day 浏览（可先只支持当天；历史日在 archive 中，后续可再议）。
- 不引入前端本地持久化 model payload（遵守现有安全约束）。
