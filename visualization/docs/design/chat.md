# 对话与执行轨迹设计

## 对话优先

- 主界面是一条连续的聊天历史：右侧为用户气泡，左侧为 Agent 行（渐变头像 + 内容区）。
- Agent 行在完成态展示 Markdown 渲染的最终回答；页脚给出状态徽标、耗时、概要（cycles/actions/domains/成败数）、token 用量与 Details 入口。
- 用户输入通过本地回声即时上屏；非本端输入从首个 message stack 的 `user_input` 段恢复。

## 运行状态动态披露（LiveStatus）

进行中的用户轮在 Agent 行内展示实时状态卡，全部从观察事件流派生：

- **浮动最新状态**：只突出当前最新的一条语义活动（加载背景、设置 todo、选择 domain、正在思考、执行 action…；不暴露具体模型名，模型细节归细节滑窗），新活动以动画上浮替换旧条目，旧条目以渐淡轨迹残留在下方——不同时陈列三个阶段；状态卡右上角有停止按钮可中断当前轮。
- **独立工作态区域**：todo 列表（状态图标、进行中高亮、完成划线）与 milestone 胶囊在状态卡下部常驻，由 Phase1 control tools 与 message stack 的 `working` 段共同推导。

## Turn 内部细节滑窗

每个用户轮可从右侧拉出细节滑窗（运行中实时更新，标注 live）：

- **Overview**：cycles / LLM calls / tokens / actions 统计与最终回答摘要。
- **Working Context**：该轮最终 todo/milestone 状态。
- **Cycle 卡片（可折叠）**：折叠时显示状态徽标、选中的 action domain 胶囊标签、动作/LLM 调用/耗时统计；展开后呈现三个默认折叠的 stage 行。
- **Stage 行（折叠即语义）**：不再解释"stage 是什么"，而是直接陈述"stage 做了什么"——
  - Stage1：折叠直接展示选中的 domain 胶囊（如 `home` `core`），文案为 "Selected N domains" / 运行中 "Maintaining context and selecting domains…"。
  - Stage2/3：折叠直接展示动作名胶囊（planned 灰 / 成功绿 / 失败红 / 执行中 accent），文案为 "Planned 1 action: core.answer" / "Executing workspace.write (2/3)" / "3 actions executed · 1 failed"。
  - Stage 展开后呈现完整语义：推理思考（reasoning summary，Markdown 渲染）、control operations（domain 选择与 intent、todo/milestone 设置/移除、背景加载/逐出）、action 输入输出、工作区变更。
- **LLM 子滑窗**：stage 折叠行右侧的 accent 胶囊按钮（Brain 图标 + "context"/"N calls"）是唯一入口，不展开 stage 即可直接唤出最近一次调用；子滑窗从主滑窗**左侧**拉出，展示该次调用的 Request message stack（Identity / User Inputs / Background / Turn Trace / Working Context / Task Prompt 分区，分区与逐条 message 均可折叠）、Tools offered（胶囊标签样式，点击标签在下方展开该工具的完整信息：description、kind/strict 徽标与 parameters schema）与 Response（reasoning / answer / tool calls / usage）。
- **Trace 导出**：选择目录后由 Rust 侧写入文件夹——`tinysoul-turn-<id>-<时间戳>/` 下 `turn.json`（完整结构投影）、`trace.md`（可读文档），以及 `cycle-N/phaseM-llm-K-<profile>.json` 每次 LLM 调用（Request+Response）的独立文件。浏览器 dev 模式回退为单 JSON 下载。

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
