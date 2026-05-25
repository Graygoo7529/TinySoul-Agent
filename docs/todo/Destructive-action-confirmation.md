# Destructive Action 确认策略

## 背景

Action metadata 已经通过 `action_environment_effect` 描述动作对环境的影响，其中 `delete_file` 标记为 `DESTRUCTIVE`。当前框架不会因为该标记自动要求用户确认，是否确认主要依赖 prompt 和模型选择 `ask_user`。

对破坏性动作来说，模型层约束不应是唯一保护。

## 当前现状

- `delete_file` 会删除 workspace 文件并更新资源列表。
- metadata 中的 `DESTRUCTIVE` 目前是描述性字段。
- `ask_user` 的描述提示模型在破坏性操作前询问用户。
- ActionRegistry allowlist 可以从入口层面禁止破坏性动作。
- 没有统一的运行时 confirmation policy。

## 问题

### 1. Destructive 标记没有执行语义

框架不会在执行前检查 `action_environment_effect=DESTRUCTIVE` 并强制确认。

### 2. 确认依赖模型自觉

模型可能因为 prompt 遗漏、上下文过长或错误判断而直接选择 `delete_file`。

### 3. 不同 destructive action 未来会重复实现确认逻辑

如果未来增加删除目录、覆盖文件、运行 shell 等动作，缺少统一策略会导致确认逻辑散落。

## 建议

- 将 destructive confirmation 作为 Action 执行前的框架策略。
- 默认对 `DESTRUCTIVE` 动作要求用户确认。
- 提供配置开关或 allowlist，使测试和受控自动化可以显式跳过确认。
- 确认状态应绑定 action name、input 和 execution id，避免确认 A 后执行 B。

## 实施方案

### 阶段 1：定义策略对象

新增 action policy，例如：

- `ActionPolicy`
- `ConfirmationPolicy`
- `requires_confirmation(meta, action_input)`

策略应读取 action metadata，不要求每个 handler 自己判断。

### 阶段 2：接入 QueryAction 或 Dispatcher

建议在执行前拦截：

- 解析 handler meta。
- 若 destructive 且无有效确认，返回需要确认的结构化错误或触发 suspend。
- 确认通过后继续执行原 action。

需要权衡是自动转为 `ask_user`，还是返回 Trap feedback 让下一轮模型选择 `ask_user`。更稳妥的做法是框架直接 suspend，并明确询问用户。

### 阶段 3：确认绑定

确认记录至少包含：

- action name
- action input hash
- turn
- execution id 或 pending confirmation id

用户确认后只能执行同一份 action input。

### 阶段 4：测试

覆盖：

- destructive action 未确认时不执行。
- 用户确认后执行。
- 修改参数后旧确认失效。
- non-destructive action 不受影响。
- 配置关闭确认时测试路径可执行。

## 验收标准

- `DESTRUCTIVE` 动作默认不能在未确认状态下执行。
- 确认过程会 suspend Loop 或产生明确可恢复状态。
- 确认绑定 action input，不能被复用到不同操作。
- allowlist 和 policy 的关系清晰：allowlist 控制是否可见，confirmation 控制是否可执行。

## 设计原则

- 破坏性动作的安全边界不能只依赖 prompt。
- 确认策略属于框架层，不属于单个 handler 的自由实现。
- 自动化场景可以显式放开，但默认应保守。
