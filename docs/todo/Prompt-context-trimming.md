# Step Prompt Context 裁剪

## 背景

`PromptBuilder` 已经支持 `include_context`，可以选择注入顶层或嵌套上下文字段。当前 Step1/2/3 仍使用默认完整上下文。随着 action record、workspace resources、todo 和错误列表增长，token 成本和无关信息干扰都会增加。

## 当前现状

- 默认上下文字段包括 query events、loop target、current turn、current state、workspace。
- `include_context` 支持顶层字段和嵌套字段。
- choose/generate/update 三个 Step 当前没有传入 `include_context`。
- current state 和 workspace 已经有压缩逻辑，但仍是通用压缩，不是按 Step 精确裁剪。

## 问题

### 1. Step 目标不同，但上下文相同

Step1 需要选择动作，Step2 需要生成某个动作参数，Step3 需要吸收未读 action records。三者需要的上下文重叠但不相同。

### 2. Token 成本会随历史增长

即使 current state 有压缩，完整注入仍会在长任务中累积成本。

### 3. 无关上下文可能干扰模型

参数生成时暴露过多无关 action record 或 workspace 信息，可能让模型偏离当前 action schema。

## 建议

- 为每个 Step 定义默认 `include_context`。
- 用测试锁定每个 Step 的 prompt context 字段。
- 保留 debug 模式或配置开关，可临时注入完整上下文。
- 对 workspace 使用摘要优先，需要文件内容时由 action 引用读取。

## 实施方案

### 阶段 1：定义 Step context profile

建议初始划分：

- Step1：`query_events`、`loop_target`、`current_turn`、`current_state.todo_list`、`current_state.milestone_list`、`current_state.feedback_error_list`、`current_state.ongoing_action_list`、workspace 摘要。
- Step2：`query_events`、`loop_target`、`current_turn`、selected action detail、必要 workspace 摘要、相关 feedback error。
- Step3：`query_events`、`loop_target`、`current_turn`、`current_state.action_record_list`、`current_state.feedback_error_list`、`current_state.todo_list`、`current_state.milestone_list`。

具体字段需要结合 prompt guide 再收敛。

### 阶段 2：接入 Step task

在 choose/execute/update task 构建 prompt 时传入 `include_context`。

避免在 Step2 中注入全部 action list；Step2 已经有 selected action detail。

### 阶段 3：增加上下文快照测试

测试每个 Step 的 prompt context 包含和不包含哪些字段。字段变化应显式更新测试。

### 阶段 4：增加配置开关

建议支持：

- default trimmed context。
- debug full context。
- per-step override。

## 验收标准

- Step1/2/3 使用不同 context profile。
- prompt context 字段有测试覆盖。
- 长 action history 下 prompt 大小明显下降。
- 状态更新仍能正确看到未读 action records。
- debug 模式可以恢复完整上下文用于排查。

## 设计原则

- Prompt context 应按任务需要注入，不默认暴露一切。
- 文件内容通过 workspace reference 按需读取，不混入通用上下文。
- 裁剪不能破坏状态更新的 action record ack 语义。
