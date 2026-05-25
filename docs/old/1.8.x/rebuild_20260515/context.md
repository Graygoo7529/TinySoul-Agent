# Context

Context（runtime data provider for Query Loop and Actions）

`ContextProvider` 定义于 `tinysoul.context.protocols`，`QueryContext` 实现于 `tinysoul.loop.context`。

Context 解决的核心问题：Query Loop、LLM Prompt Builder 和 Action Executor 之间如何传递运行时数据，同时避免相互耦合。

## Design_Principles

（1）对象引用优先于预序列化
- ContextProvider 暴露的是对象引用（如 `QueryState` 对象、`Workspace` 对象），而非预先生成的 JSON 字符串
- 序列化由消费者（`PromptBuilder`，位于 `tinysoul.llm.tasks.prompt`）在需要时触发，避免过早序列化带来的性能损耗和过期问题

（2）Protocol 而非具体类
- `ContextProvider` 是 Protocol，不是 ABC
- Action Executor 只依赖 `ContextProvider` 协议，不依赖 `QueryContext` 具体类
- 任何实现了协议的对象都可以作为 Action 的上下文来源，便于测试和扩展

（3）Context 不组装 Prompt
- `QueryContext` 的职责仅限于持有数据引用和提供按需序列化方法
- Prompt 字符串的组装由 `PromptBuilder` 负责
- LLM 调用由 `AITask`（位于 `tinysoul.llm.tasks.task`）负责
- 三者职责边界清晰

## ContextProvider（Protocol）

定义 Action 和 PromptBuilder 所需的共享上下文字段：

```
user_query: str
loop_target: str
current_state: Any        # QueryState 对象
workspace: Optional[Any]  # Workspace 对象，可为 None
current_turn: int
query_action: QueryAction

get_current_state() -> dict
get_workspace() -> dict
```

Action Executor（如 `OneStepAIExecutor`）通过 `context_provider` 访问上述字段，以构造内部 LLM prompt 或读取 workspace 文件。

## QueryContext（Implementation）

`QueryContext` 是 `ContextProvider` 的具体实现，由 `QueryLoop` 在初始化时创建并持有。

### 职责

（1）持有运行时对象引用
- `query_state`: `QueryState`
- `query_action`: `QueryAction`
- `workspace`: `Workspace | None`
- `user_query`, `loop_target`, `current_turn`

（2）按需序列化
- `get_current_state()`：将 `QueryState` 序列化为 LLM 可读的字典
  - 字段顺序有语义：`action_record_list` 和 `feedback_error_list` 在前（静态边界），随后是 `current_turn`, `todo_list`, `milestone_list`, `ongoing_action_list`
- `get_workspace()`：将 `Workspace` 序列化为字典，无 workspace 时返回 `{}`
- `consume_new_action_records()`：消费未读的 ActionRecord，返回序列化后的字典列表

（3）Todo key 冲突处理
- `_build_todo_list_for_context()` 根据当前 `todo_list` 中相同 `semantic_key` 的数量决定暴露 `semantic_key` 还是 `display_key`
- 该逻辑与 `TodoManager` 的解析规则对称，确保 LLM 看到的 key 与它能操作的 key 一致

### 与 PromptBuilder 的关系

```
QueryContext（数据持有者）
    ↓ 对象引用
PromptBuilder（prompt 组装者）
    ↓ LLMPrompt
AITask（LLM 调用者）
```

`PromptBuilder` 在构造 prompt 时调用 `context_provider.get_current_state()` 和 `context_provider.get_workspace()`，将共享上下文注入到每个 task 的 prompt 中。

**按需注入与字段选择**

默认情况下，PromptBuilder 注入全部共享字段（user_query, loop_target, current_state, workspace, current_turn）。调用方可通过 `include_context` 参数按需选择：

- `include_context=None`（默认）：注入全部字段
- `include_context=["user_query", "current_state"]`：仅注入指定的顶层字段
- `include_context=["current_state.todo_list", "workspace.resources"]`：仅注入嵌套子字段

该机制使不同 step（choose action / take action / update state）和 Action 可以根据自身需求裁剪上下文，避免无关信息占用 prompt token。例如，OneStepAIExecutor 中的内容生成 Action 可以选择只暴露 `user_query`、`current_state.todo_list` 和 `workspace`，而不携带完整的 action history。

## 序列化边界

（1）`current_state` 的静态边界
- `action_record_list` 和 `feedback_error_list` 位于 JSON 顶部，作为"静态边界"
- 含义：这部分内容单调增长，LLM 可以将其视为只读历史

（2）`new_action_records` 的独立块
- 在 Step 3 中，`new_action_records` 不作为 `current_state` 的子字段，而是作为单独的 InputSpec data 传入
- 含义：明确告诉 LLM "这是本轮新发生的事件，请重点评估"
