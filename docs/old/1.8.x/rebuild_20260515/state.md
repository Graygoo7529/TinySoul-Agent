# State

State（defined in `runtime/state/` module, independent from loop, runtime state for action tracking）

State 是 Query Loop 的运行时状态容器，完全独立于 Loop 本身。其设计目标是：Loop 负责决策与调度，State 负责记录与提供历史上下文。二者通过清晰的读写边界协作。

## Design_Principles

（1）独立于 QueryLoop
- State 不感知 Loop 的存在，只暴露数据结构和操作方法
- Loop 通过 `QueryContext` 读取 State 的序列化视图，State 本身不组装 prompt

（2）Facade + Manager 分离
- `QueryState` 作为统一门面（Facade），对外暴露单一入口
- 内部委托给四个独立的 Manager，每个 Manager 只负责一类状态的增删改查
- Manager 之间无交叉依赖，便于单独测试和替换

（3）读取即消费（Consume-on-Read）
- `action_record_list` 中的记录带有 `read: bool` 标志
- `consume_new_action_records()` 返回所有未读记录，并将它们标记为已读
- 该语义支撑 Step 3 的 `new_action_records` 机制：LLM 只聚焦最新变化

## Core_Components

### QueryState（Facade）

聚合四个 Manager，提供向后兼容的属性访问和委派方法：
- `todo_list` → `TodoManager`
- `milestone_list` → `MilestoneManager`
- `action_record_list / ongoing_action_list` → `ActionRecordManager`
- `loop_error_list` → `LoopErrorManager`

`LoopErrorItem` 与 `LoopErrorManager` 定义于 `tinysoul.trap.loop_error`，由 `QueryState` 组合引用。此设计打破了早期 `state ↔ error_handling` 的循环依赖。

### TodoManager

管理待办事项，核心设计是解决 LLM 对 todo key 的操作歧义：

（1）双 key 体系
- `semantic_key`：LLM 输入的规范化 key（小写 snake_case）
- `display_key`：系统生成的带序号 key（如 `verify-1`, `verify-2`）

（2）key 暴露规则
- 若当前 `todo_list` 中存在 2 个及以上相同 `semantic_key` 的 todo（无论状态），该 key 下的所有 todo 对外暴露 `display_key`
- 否则暴露 `semantic_key`
- 该规则让 LLM 在简单场景下使用短 key，在复杂场景下被迫使用精确 key

（3）complete / cancel 解析顺序
1. 精确匹配 `display_key` 且状态为 `PENDING`
2. 精确匹配 `semantic_key` —— 仅当恰好存在一个 PENDING 的匹配项时
3. 若存在多个 PENDING 匹配项，抛出 `TodoAmbiguityError`，由 Loop 记录到 `loop_error_list` 并反馈给 LLM

（4）部分失败隔离
- `QueryLoop._apply_state_updates` 对每个 todo operation 单独 try/except
- 一个 todo 操作失败（如歧义 key）不会导致同轮的其他 todo 操作或 milestone 操作被丢弃

### MilestoneManager

极简的里程碑列表，只支持追加：
- `add(description)`：追加一条已完成的重要进展描述
- 不提供删除或编辑，保证里程碑是只增的历史记录

### ActionRecordManager

管理 Action 执行记录：

（1）ActionRecord 字段
- `action_name`, `action_target`, `action_input`（dict）, `action_result`（dict）
- `timestamp`, `turn`（int）, `read`

（2）Ongoing Action 支持
- `add_ongoing()` 将 action_name 加入 `ongoing_action_list`（去重）
- 同一 ongoing action 的多次结果产生多条 ActionRecord，但 `ongoing_action_list` 中去重

（3）Unread 语义
- `consume_unread()` 返回所有 `read=False` 的记录，并原地置 `read=True`
- 被消费后的记录仍保留在 `action_record_list` 中，LLM 在 Step 3 通过 `new_action_records` 看到增量，通过 `action_record_list` 看到完整历史

### LoopErrorManager

记录循环执行中的错误：
- `turn`：错误发生的轮次（1-based）
- `step`：`choose_action` | `generate_parameters` | `execute_action` | `update_state`
- `error_type`：str — 异常类型链（如 `"ActionExecutionError/ValueError"`、`"ActionInputError"`）
- `message`：标准化错误消息

错误记录作为 `current_state` 的静态边界的一部分，供 LLM 在后续轮次调整策略。
