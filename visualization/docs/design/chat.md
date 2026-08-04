# 对话与执行轨迹设计

## 对话优先

- 主界面是一条连续的聊天历史：右侧为用户气泡，左侧为 Agent 行（渐变头像 + 内容区）。
- Agent 行在完成态展示 Markdown 渲染的最终回答；页脚给出状态徽标、耗时、概要（cycles/actions/domains/成败数）、token 用量与 Details 入口。
- 用户输入通过本地回声即时上屏；非本端输入从首个 message stack 的 `user_input` 段恢复。

## 运行状态动态披露（LiveStatus）

进行中的用户轮在 Agent 行内展示实时状态卡，全部从观察事件流派生：

- **当前活动**：当前 Phase 标题、正在调用的模型或正在执行的 action 及关键参数、已进行时长。
- **Phase stepper**：当前 cycle 内三段执行单元（Context & Domains / Action Planning / Action Execution）的 idle/running/completed 状态。
- **工作态快照**：由 Phase1 control tools（`set_todo`/`set_milestone` 等）与 message stack 的 `working` 段共同推导的 todo 列表（状态图标）与 milestone  chips。
- **Activity feed**：滚动语义事件流——背景加载/逐出、todo/milestone 变更、domain 选择、模型调用、action 执行与结果、工作区变更、最终回答。

## Turn 内部细节滑窗

每个用户轮可从右侧拉出细节滑窗（运行中亦可，标注 live）：

- **Overview**：cycles / LLM calls / tokens / actions 统计与最终回答摘要。
- **Working Context**：该轮最终 todo/milestone 状态。
- **Activity**：该轮完整语义事件列表。
- **Cycle → Phase 卡片**：
  - **Phase1（更新语境与决策行动域）**：control operations 语义行（domain 选择 chips、todo/milestone 设置/移除、背景加载/逐出 links）+ 背景变更 + LLM 调用。
  - **Phase2（生成行动参数）**：planned action 卡片（参数语义预览 + 原始 JSON）。
  - **Phase3（采取行动）**：executed action 卡片（状态、失败 failure 三通道、domain 感知输出渲染）+ 工作区变更。
- **LLM 调用卡片**：profile、model/provider、attempt、状态、token 用量；展开后呈现完整 message stack（按 Identity / User Inputs / Background / Turn Trace / Working Context / Task Prompt 分区，逐条 role/label/parts/tool_calls/reasoning）、offered tools 与响应。
- **Trace 导出**：导出该轮完整发生的每一次 LLM 调用的 message stack 及全部 action 输入输出，Markdown（可读文档）或 JSON（结构投影）。

## Action 输入输出渲染

按 domain 感知渲染，未知形状回退到可折叠 JSON 树（不隐藏任何信息）：

- `core.answer`：Markdown 渲染的回答文本。
- `workspace.*`：link chip + 内容预览；结果中的 link/revision。
- `execution.*`（脚本/命令）：命令行、exit code、stdout/stderr 终端块。
- `web.*`：查询/URL、结果列表（标题/域名/摘要）。
- 其余：参数与结果 JSON 树；失败展示 `ActionLocalFailure` 的 reason/scope/feedback。

## 派生数据

`src/derive/chat.ts` 消费原始 `EndpointEvent[]`（+ 本地输入回声），构建：

- `ChatTurn[]`：用户输入、助手回答、状态、Cycle 列表、working 投影、activity feed、usage、currentActivity。
- `Cycle[]` / `PhaseStep[]`：按 `cycle`/`phase` scope 帧归组。
- `ControlOp[]`：从 Phase1 模型响应的 control tool calls 解析（`select_action_domains`、`set/remove_todo`、`set/remove_milestone`、`load/evict_background`）。
- `ActionRecord[]`：`action.call` 生成 planned record；`action.result` 镜像为 Phase3 executed record，计划与执行不混淆。
- `ModelTask[]`：按 `llm.*` 事件归组，含 request（完整 message stack）/response。
