# Context

Context 模块位于 `tinysoul/context/`，负责运行时数据的持有、序列化和状态管理。它完全独立于 Loop，通过清晰的读写边界与 QueryLoop 协作。Context 包含三个子系统：`context.protocols`（协议定义）、`context.state`（运行时状态）、`context.workspace`（文件系统上下文）。

---

## Design Principles

### 1. 独立于 QueryLoop

- State 不感知 Loop 的存在，只暴露数据结构和操作方法
- Loop 通过 `QueryContext` 读取 State 的序列化视图，State 本身不组装 prompt
- Workspace 同样独立于 Loop，可持久化、跨 Loop 复用

### 2. 对象引用优先于预序列化

- `ContextProvider` 暴露的是对象引用（`QueryState` 对象、`Workspace` 对象），而非预先生成的 JSON 字符串
- 序列化由消费者（`PromptBuilder`）在需要时触发，避免过早序列化带来的性能损耗和过期问题

### 3. Protocol 而非具体类

- `ContextProvider` 是 Protocol，不是 ABC
- Action Executor 只依赖 `ContextProvider` 协议，不依赖 `QueryContext` 具体类
- 任何实现了协议的对象都可以作为 Action 的上下文来源，便于测试和扩展

### 4. Context 不组装 Prompt

- `QueryContext` 的职责仅限于持有数据引用和提供按需序列化方法
- Prompt 字符串的组装由 `PromptBuilder` 负责
- LLM 调用由 `AITask` 负责
- 三者职责边界清晰

### 5. Facade + Manager 分离

- `QueryState` 作为统一门面（Facade），对外暴露单一入口
- 内部委托给四个独立的 Manager，每个 Manager 只负责一类状态的增删改查
- Manager 之间无交叉依赖，便于单独测试和替换

---

## ContextProvider Protocol

定义 Action 和 PromptBuilder 所需的共享上下文字段：

```python
class ContextProvider(Protocol):
    @property
    def query_events(self) -> QueryEvents: ...
    @property
    def loop_target(self) -> str: ...
    @property
    def current_state(self) -> Any: ...       # QueryState 对象
    @property
    def workspace(self) -> Any | None: ...    # Workspace 对象
    @property
    def current_turn(self) -> int: ...
    @property
    def query_action(self) -> QueryAction: ...

    def get_current_state(self) -> dict: ...
    def get_workspace(self) -> dict: ...
    def get_loop_level_system(self) -> list[dict[str, str]]: ...
    def append_inquiry(self, content: str) -> QueryEvent: ...
    def append_response(self, content: str, ask_context: str) -> QueryEvent: ...
    def append_append(self, content: str, turn: int = 0) -> QueryEvent: ...
    def emit_signal(self, signal: Signal) -> None: ...
    def register_ongoing_control(self, control: OngoingControl) -> None: ...
    def unregister_ongoing_control(self, execution_id: str) -> Any | None: ...
    def request_ongoing_termination(self, execution_id: str, reason: TerminationReason) -> bool: ...
    def request_all_ongoing_termination(self, reason: TerminationReason) -> int: ...
```

> **注意**：`get_loop_level_system()` 只提供 loop-level system messages（`basic_system` + `query_loop_system`）；内部 LLM-dependent Action 的 `ACTION EXECUTION CONTEXT` 由 `tinysoul.action.system.build_llm_action_system()` 在 action 层追加；`emit_signal()` 是 Action 层访问信号系统的唯一入口；ongoing control 方法只处理运行时终止意图，不直接写 `ongoing_action_list`；`append_append()` 委托给 `QueryEvents.append_append()`，将用户补充输入追加到 query 事件流。

Action Executor（如 `OneStepAIExecutor`）通过 `context_provider` 访问上述字段，以构造内部 LLM prompt 或读取 workspace 文件。

---

## QueryContext

`QueryContext` 是 `ContextProvider` 的具体实现，由 `QueryLoop` 在初始化时创建并持有。

### 职责

1. **持有运行时对象引用**：`query_state`, `query_action`, `workspace`, `signal_bus`
2. **按需序列化**：`get_current_state()`, `get_workspace()`, `peek_new_action_records()`
3. **维护 `current_turn`**
4. **管理 query 事件流**：`QueryEvents` 维护 `query_events` 的事件列表
5. **管理 ONGOING 控制面**：按 `execution_id` 注册、请求终止、注销 `OngoingControl`

### 序列化边界

**分层压缩**：`action_record_list` 和 `feedback_error_list` 位于 JSON 顶部
- 含义：近期记录（可配置数量）保留全量细节，早期记录压缩为摘要（action_name + turn + status），以控制 prompt 大小

**动态部分**：`current_turn`, `todo_list`, `milestone_list`, `ongoing_action_list`

`ongoing_action_list` 是 LLM 可见的运行状态视图，包含 `{execution_id, action_name, turn, status, started_at}`。`OngoingControlRegistry` 是运行时控制面，只保存在 `QueryContext` 内部，不直接暴露给 LLM。

**`new_action_records` 的独立块**：在 Step 3 中，未读记录不作为 `current_state` 的子字段，而是作为单独的 InputSpec data 传入。含义：明确告诉 LLM "这是本轮新发生的事件，请重点评估"。

### Peek / Ack 语义

Step 3 采用"先 peek，成功后 ack"的两阶段消费模式，替代原来的 consume-on-read：

```python
# Step 3 update state
new_action_records = self.query_context.peek_new_action_records()  # 只读，不改 read 标志
# ... LLM call + normalize + apply_state_updates ...
self.query_context.ack_action_records()  # 成功后标记已读
```

- `peek_new_action_records()`: 仅返回 `read=False` 的记录的序列化视图，不修改 `read` 标志
- `ack_action_records()`: 调用 `query_state.ack_action_records()`（即 `mark_all_read()`），将所有未读记录标记为已读
- 若 Step 3 失败（LLM 调用或 normalize 异常），记录保持 `read=False`，供下一轮重新消费

### Todo Key 冲突处理

`_build_todo_list_for_context()` 根据当前 `todo_list` 中相同 `semantic_key` 的数量决定暴露 `semantic_key` 还是 `display_key`：
- 若存在 2+ 个相同 `semantic_key`，该 key 下的所有 todo 对外暴露 `display_key`
- 否则暴露 `semantic_key`
- 该逻辑与 `TodoManager` 的解析规则对称，确保 LLM 看到的 key 与它能操作的 key 一致

---

## QueryState

State 是 Query Loop 的运行时状态容器，完全独立于 Loop 本身。`QueryState` 作为 Facade，聚合四个独立 Manager：

```
QueryState（Facade）
├── TodoManager          → todo_list
├── MilestoneManager     → milestone_list
├── ActionRecordManager  → action_record_list + ongoing_action_list
└── LoopErrorManager     → loop_error_list
```

### TodoManager

管理待办事项，核心设计是解决 LLM 对 todo key 的操作歧义：

**双 key 体系**：
- `semantic_key`：LLM 输入的规范化 key（小写 snake_case）
- `display_key`：系统生成的带序号 key（如 `verify-1`, `verify-2`）

**key 暴露规则**：
- 若当前 `todo_list` 中存在 2 个及以上相同 `semantic_key` 的 todo（无论状态），该 key 下的所有 todo 对外暴露 `display_key`
- 否则暴露 `semantic_key`

**complete / cancel 解析顺序**：
1. 精确匹配 `display_key` 且状态为 `PENDING`
2. 精确匹配 `semantic_key` —— 仅当恰好存在一个 PENDING 的匹配项时
3. 若存在多个 PENDING 匹配项，抛出 `TodoAmbiguityError`，由 Loop 记录到 `loop_error_list` 并反馈给 LLM

**部分失败隔离**：`apply_state_updates()` 对每个 todo operation 单独 try/except，一个 todo 操作失败不会导致同轮的其他 todo 操作或 milestone 操作被丢弃。

### MilestoneManager

极简的里程碑列表，只支持追加：
- `add(description)`：追加一条已完成的重要进展描述
- 不提供删除或编辑，保证里程碑是只增的历史记录

### ActionRecordManager

管理 Action 执行记录：

**ActionRecord 字段**：`action_name`, `action_target`, `action_input`, `action_result`, `timestamp`, `turn`, `read`

**Ongoing Action 支持**：
- `add_ongoing(execution_id, action_name, turn)` 将 execution 加入 `ongoing_action_list`
- `remove_ongoing(execution_id)` 按 execution 移除，而不是按 action_name 移除
- 同一 `action_name` 可以有多个并发 ONGOING execution；去重键是 `execution_id`
- 同一 ONGOING execution 的多次 tick/result 产生多条 ActionRecord，并共享同一个 `execution_id`

**Peek / Ack 语义**：
- `peek_unread()`: 只返回 `read=False` 的记录，不改状态
- `mark_all_read()`: 批量确认已读
- 被确认后的记录仍保留在 `action_record_list` 中，LLM 在 Step 3 通过 `new_action_records` 看到增量，通过 `action_record_list` 看到完整历史

### LoopErrorManager

记录循环执行中的错误：
- `turn`：错误发生的轮次（1-based）
- `step`：`choose_action` | `generate_parameters` | `execute_action` | `update_state`
- `error_type`：异常类型链（如 `"ActionExecutionError/ValueError"`）
- `message`：标准化错误消息
- `auto_handled`：被自动处理的错误，会被过滤出 `feedback_error_list`

错误记录作为 `current_state` 的一部分，供 LLM 在后续轮次调整策略。

---

## Workspace

Workspace 是外部文件系统上下文模块，独立于 State。

### Core Structures

```python
@dataclass
class ResourceItem:
    resource_name: str          # 文件显示名
    resource_type: ResourceType # MARKDOWN | PY | PDF | DOCX | TXT | JSON | CSV | UNKNOWN
    resource_access: str        # workspace-relative path
    resource_desc: ResourceDesc # {summary}
    change_log: list[ChangeLogItem]

@dataclass
class ChangeLogItem:
    turn: int
    operation: ChangeOperation  # READ | CREATED | EDITED | DELETED
    summary: str
    timestamp: datetime = field(default_factory=datetime.now)
```

### Key Behaviors

- `scan()`：同步 workspace.resources 与实际目录结构，保留现有资源的 `resource_desc` 和 `change_log`
- `resolve_access(path)`：将相对路径解析为绝对路径，校验不超出 workspace 边界；禁止绝对路径输入
- `read_reference_files(accesses)`：读取引用资源内容，失败立即抛出（由 Action 的异常边界处理）
- `add_resource()` / `remove_resource()`：维护 resources 列表

### Workspace vs State

| | State (`QueryState`) | Workspace |
|--|----------------------|-----------|
| **职责** | 运行时状态（todo、milestone、action_record、loop_error） | 文件系统上下文（resources、change_log） |
| **生命周期** | 随 Query Loop 创建和销毁 | 可持久化，跨 Loop 复用 |
| **Prompt 位置** | `=== CURRENT STATE ===` | `=== WORKSPACE ===`（并列在其后） |
| **变更控制** | Step 3 的 LLM 输出控制 | Action 执行器直接控制 |

---

## PromptBuilder Integration

```
QueryContext（数据持有者）
    ↓ 对象引用
PromptBuilder（prompt 组装者）
    ↓ LLMPrompt
AITask（LLM 调用者）
```

`PromptBuilder` 在构造 prompt 时调用 `context_provider.get_current_state()` 和 `context_provider.get_workspace()`，将共享上下文注入到每个 task 的 prompt 中。

**按需注入与字段选择**：
- `include_context=None`（默认）：注入全部字段（query_events, loop_target, current_state, workspace, current_turn）
- `include_context=["query_events", "current_state"]`：仅注入指定的顶层字段
- `include_context=["current_state.todo_list", "workspace.resources"]`：仅注入嵌套子字段

该机制使不同 step 和 Action 可以根据自身需求裁剪上下文，避免无关信息占用 prompt token。

> **当前状态**：`compact_max_records` 和 `compact_max_errors` 等压缩基础设施已就位，`include_context` 字段选择机制也已实现，但 `ChooseActionTask`、`TakeActionTask`、`UpdateStateTask` 尚未显式传入 `include_context` 做裁剪（当前默认注入全部上下文）。这是已知待完善项。

---

## Invariants

- `QueryState` 不感知 Loop 的存在，只暴露数据结构和操作方法
- `QueryContext` 不组装 prompt 字符串，只提供对象引用和按需序列化
- `QueryContext.get_loop_level_system()` 只暴露已解析的 loop-level system messages，不加载 prompt source，不拼接 action execution context
- `ContextProvider` 是 Protocol，不是 ABC；Action Executor 只依赖协议
- `action_record_list` 和 `feedback_error_list` 在 `current_state` 中位于顶部
- `new_action_records` 不作为 `current_state` 的子字段，而是作为独立块传入 Step 3
- `peek_new_action_records()` 只读；`ack_action_records()` 在更新成功后确认
- 若 Step 3 失败，未读记录保持 unread，供下一轮重新消费
- `workspace_location` 必须是绝对路径
- 所有 `resource_access` 必须解析在 `workspace_location` 边界内
- `change_log` 仅追加，不删除不编辑
- `resource_access` 在 workspace 内必须唯一（以 resource_access 为 canonical identifier）
- `milestone_list` 只支持追加，不支持删除或编辑
- `todo_list` 的 complete/cancel 解析优先匹配 `display_key`，其次精确匹配唯一的 `semantic_key`
- 所有 Manager 之间无交叉依赖
- `ongoing_action_list` 以 `execution_id` 为唯一键，不以 `action_name` 去重
- `OngoingControlRegistry` 是运行时控制层；状态层只记录 LLM 可见的 ongoing execution 视图
