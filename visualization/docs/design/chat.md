# 对话与执行轨迹设计

## 对话优先

- 主界面是一条连续的聊天历史：右侧为用户气泡，左侧为 Agent 气泡。
- Agent 气泡默认只展示最终回答；执行细节通过“execution trace”入口渐进展开。
- Turn 运行时，Agent 气泡显示当前 Phase 与最新 Action，告诉用户“正在做什么”。

## 运行时语义层次

展开后遵循 AGENT.md 的 `Turn → Cycle → Phase → Action/Result → LLM Context` 层次：

### Turn

- 包含用户输入、最终回答、终止状态（answered / failed / stopped / exhausted）。
- `turn.completed` 事件决定最终状态；运行期间显示 live activity。

### Cycle

- 每个 Cycle 头部展示：序号、完成状态、选中的 action domains、action 数量。
- Cycle 展开后显示横向 Phase stepper（Context / Plan / Act）和 Phase 卡片时间线。

### Phase

- **Phase1：更新语境与决策行动域**
  - 展示 context changes（loaded / evicted background links）。
  - 展示选中的 action domains（从 `select_action_domains` tool call 提取）。
  - LLM 任务折叠在“Reasoning”下。
- **Phase2：生成行动参数**
  - 展示 planned actions，状态为 `planned`。
  - LLM 任务折叠在“Planning model calls”下。
- **Phase3：采取行动**
  - 展示 executed actions 与结果（成功 / 失败 / 超时）。
  - 展示 workspace effects（`workspace.changed` 等副作用）。
  - LLM 任务折叠在“Execution model calls”下。

### Action

- 每个 Action 以 Mock Computer 卡片呈现：
  - 文档编辑：文件预览、行数、保存状态。
  - 脚本执行：语言、参数、stdout/stderr、exit code。
  - Shell 命令：终端样式、工作目录、输出、退出码。
  - 长时 Process：job state、elapsed、execution id、stdout/stderr、candidate changes。
- 卡片仍可展开查看原始 JSON payload/result。

### LLM Context

- 嵌在 Phase 内部的 Model Call 中。
- 按语义分组：System Identity、User Inputs、Background Context、Working Context、Turn Trace、Task Prompt、Assistant Decision、Action Results。

## 派生数据

`src/hooks/useDerivedChat.ts` 消费原始 `EndpointEvent[]`，构建：

- `ChatTurn[]`：用户输入、助手回答、状态、Cycle 列表、live activity。
- `Cycle[]`：按 `cycle` scope 分组，包含 Phase 列表。
- `PhaseStep[]`：按 `loop.phase.*` 事件映射，包含 tasks 与 actions。
- `ActionRecord[]`：`action.call` 生成 planned record；`action.result` 在 Phase3 生成 executed record，避免计划与执行状态混淆。
- `ModelTask[]`：按 `llm.*` 事件分组，包含 request/response。

## 状态显示

- `success`、`completed`、`failed`、`timeout`、`planned`、`running` 统一归一化显示，避免成功被渲染为失败。
- 运行中的 Turn 显示 spinner + 当前 Phase/Action；Turn 结束后自动移除 running 提示。
