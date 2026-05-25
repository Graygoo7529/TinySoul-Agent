# Context 模块

## 定位

Context 模块提供 Loop、Action、Prompt、Trap 之间共享的会话视图。它不做决策，也不执行动作；它负责把状态、事件、工作区、动作入口、LLM 客户端和 ongoing 控制统一包装成 `ContextProvider`。

当前实现中，`QueryContext` 位于 `tinysoul/loop/context.py`，而抽象协议位于 `tinysoul/context/protocols.py`。这是为了让 Loop 能直接组装运行态上下文，同时让 Action 和 Prompt 只依赖协议。

## 结构

主要对象：

- `QueryState`：会话状态门面，组合 action record、todo、milestone、loop error、ongoing action 等管理器。
- `QueryEvents`：用户查询、模型事件、用户追加信息的事件序列。
- `Workspace`：工作区资源索引和安全路径访问。
- `QueryContext`：运行时上下文实现。
- `ContextProvider`：Action、Prompt、Trap 面向上下文的协议。

Context 的设计目标是隔离直接状态读写。调用方读取结构化快照，写入则走明确方法或由 Trap 统一完成。

## `QueryContext`

`QueryContext` 组合以下依赖：

- 当前 `QueryState`
- 当前 `QueryEvents`
- `Workspace`
- `QueryAction`
- `AIClient`
- `SignalBus`
- loop-level system messages
- ongoing action 控制注册表

它向外提供：

- `get_current_state()`
- `get_workspace()`
- `get_loop_level_system()`
- `append_inquiry()`
- `append_response()`
- `append_append()`
- `emit_signal()`
- ongoing action 生命周期控制方法

其中 `append_append()` 是当前代码中的实际方法名，用于记录用户在循环中的追加信息。

## 状态快照

`get_current_state()` 返回面向模型和动作的结构化字典，主要字段包括：

- `action_record_list`
- `feedback_error_list`
- `todo_list`
- `milestone_list`
- `ongoing_action_list`

`current_turn` 不在该快照内部生成，而是由 `PromptBuilder` 作为独立上下文字段注入。

Action record 默认会压缩输出：当记录数量超过 `settings.compact_max_records` 时，旧记录只保留动作名、轮次、状态和 execution id 等摘要，最近记录保留完整输入输出。调试或导出时可以关闭压缩。

Feedback error 会过滤已自动处理的错误，并按 `settings.compact_max_errors` 控制暴露数量。

## `QueryState`

`QueryState` 是状态管理器的聚合门面：

- ActionRecordManager：动作执行记录。
- TodoManager：待办项。
- MilestoneManager：里程碑。
- LoopErrorManager：循环错误。
- OngoingActionManager：运行中动作记录。

各管理器维护自己的数据结构，避免 Loop 或 Action 直接修改内部列表。

### Action record

Action record 记录动作执行事实，主要字段包括：

- `action_name`
- `action_target`
- `action_input`
- `action_result`
- `turn`
- `timestamp`
- `execution_id`
- `read`
- `status`

Loop Step3 会读取未读记录生成状态更新。只有状态更新成功后，这些记录才会被 ack 为已读。终止类控制信号可能使 Loop 在进入 Step3 前返回，因此文档和调用方不应假设所有成功动作都会立刻被 ack。

### Todo

Todo 支持 `semantic_key` 和 `display_key`。当多个待办共享同一语义键时，上下文会暴露 display key，帮助模型精确引用。

完成或取消 todo 时，解析顺序是：

1. 精确匹配 display key。
2. 匹配唯一的 pending semantic key。
3. 多个 pending semantic key 命中时抛出歧义错误。
4. 没有 pending 命中时视为无操作。

### Milestone

Milestone 是追加式记录，用于保存阶段性成果或重要事实。它不是任务队列，也不会被自动删除。

## `Workspace`

`Workspace` 负责工作区内资源发现和路径安全：

- 初始化时解析工作区根目录。
- `scan()` 发现当前文件资源，并保留已有资源元数据。
- `resolve_access()` 禁止绝对路径和 `..` 逃逸。
- 读写动作只能访问工作区内路径。

工作区扫描关注实际文件系统状态。运行脚本时产生的 `.tinysoul_runtime` 目录如果存在于工作区内，也可能被扫描为普通资源；调用方不应把资源列表理解为只包含用户源文件。

## 事件

`QueryEvents` 保存会话事件：

- 用户原始 query。
- 用户对 `ask_user` 的回答。
- 用户追加信息。
- 其他 Loop 事件。

这些事件会进入 PromptBuilder，帮助模型理解当前查询的上下文变化。

## Ongoing 控制

Ongoing action 的生命周期由 Context 暴露给动作和 Loop：

- start：登记运行中动作。
- tick：记录进展信号。
- complete：移除运行中动作。
- shutdown：请求动作结束。

Context 只提供控制入口；信号如何落库由 Trap/InterruptHandler 决定。

## 当前边界

- Context 是运行态视图，不是持久化数据库。
- `get_current_state()` 是模型友好格式，不等同于完整内部状态。
- Workspace 的路径保护用于工作区边界，不等同于系统级沙箱。
- action record 的 read/ack 与 Loop Step3 强相关，终止信号会改变正常更新路径。
- `QueryContext` 当前放在 Loop 包内，外部模块应依赖 `ContextProvider` 协议而非具体路径。

## 设计不变式

- 状态只能通过管理器或明确上下文方法修改。
- 暴露给模型的上下文必须是结构化、可压缩、可选择的。
- 工作区访问必须先经过 workspace-relative 路径解析。
- Action 不直接拥有状态推进权。
- Ongoing 生命周期必须通过 context 和 signal 双通道保持一致。
