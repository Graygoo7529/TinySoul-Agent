# Loop

Loop 模块位于 `tinysoul/loop/`，是 TinySoul 的核心调度器。它驱动 Agent 与 LLM 的多轮交互，每轮（turn）固定为三 step：选择 Action → 生成参数并执行 → 更新状态。所有 step 的执行被 `_run_step` 统一包裹，异常与信号通过 `ErrorTrap` 集中路由。

---

## Design Principles

### 1. 三 Step 固定范式

- Step 1 `choose_action`：从可用 Action 中选择最适配的一个或多个
- Step 2 `generate_parameters` + `execute_action`：生成 JSON 参数并执行
- Step 3 `update_state`：基于执行结果更新 todo / milestone
- 三 step 的输入输出均为结构化 JSON，由 `AITask` + `Interpreter` 统一处理

### 2. OS-Style 异常路由

- 所有 step 由 `_run_step` 统一包裹，异常不再按类型分散 try/except
- `ErrorTrap.capture()` 将异常分类为 `ABORT` / `USER_INTERRUPT` / `NEXT_STEP`
- `KeyboardInterrupt` 被路由为 `USER_INTERRUPT`，外层优雅返回
- 部分失败隔离：`update_state` 中的每个 todo operation 独立 try/except

### 3. ContextProvider 驱动

- `QueryContext` 实现 `ContextProvider` 协议，持有运行时对象引用
- Prompt 组装由 `PromptBuilder` 负责，LLM 调用由 `AITask` 负责
- `QueryLoop` 只负责调度，不直接操作 prompt 字符串或 LLM 响应

### 4. Peek / Ack 语义（Step 3）

- Step 3 前先 `peek_new_action_records()`，仅读取未读记录，不改 `read` 标志
- LLM 调用 + normalize + `apply_state_updates()` 成功后，再 `ack_action_records()` 标记已读
- 若 Step 3 失败（LLM 错误或 normalize 异常），记录保持 unread，供下一轮重新消费
- 这比原来的"consume-on-read"更精确：只有真正被成功处理过的记录才被确认

### 5. 串行与并行路径统一

- 单 Action 与多 Action batch 的终点都是 **SignalBus**
- 子线程只 emit Signal，不直接修改状态
- 主循环在 Step 2b 后统一 `consume()` 并批量路由
- 这保证了并行 batch 和 ONGOING action 与串行路径无特殊分支

---

## Architecture

```
loop/
├── loop.py              QueryLoop（调度器）+ LoopOutcome
├── context.py           QueryContext（ContextProvider 实现）
├── query.py             QueryEvents + QueryEvent
├── parallel_dispatcher.py  ParallelDispatcher + ActionSpec
└── steps/
    ├── choose.py        ChooseActionTask（Step 1）
    ├── execute.py       TakeActionTask（Step 2a）
    └── update.py        UpdateStateTask（Step 3）
```

---

## QueryLoop

调度器，管理 Agent Query Loop 的完整生命周期。

### 构造参数

- `initial_query`：初始输入（str，内部包装为 QueryEvents）
- `loop_system`：外部 loop-level system 来源列表（inline / filesystem / builtin）；内置 `query_loop.system.md` 自动追加
- `loop_target`：循环目标
- `available_action_names`：可用 Action 名称列表（allowlist）
- `init_todo_list`：初始待办事项
- `workspace`：可选的 Workspace 实例
- `client`：可选的 AIClient 注入（测试用）
- `registry`：可选的 ActionRegistry 注入（测试用）
- `logger`：可选的 EventLogger 注入
- `env_caps`：可选的 EnvironmentCapabilities 注入

### 初始化行为

1. 若未提供 `registry`，自动创建并 `bootstrap()` 内置 Action
2. 若提供 `available_action_names`，对 registry 应用 allowlist 过滤
3. 创建 `QueryState`、`QueryAction`、`QueryContext`、`PromptBuilder`
4. 创建三个 Step Task 实例（复用 across turns）
5. 若 `workspace` 非空且 `resources` 为空，自动触发 `scan()`
6. `resource_desc` 仅含持久化字段 `summary`；`relevance` 由 `read_file` action 通过 `action_result` 临时反馈给当前 loop，不跨 loop 保留
7. 构建 loop-level system（外部 `loop_system` sources + 内置 `tinysoul.prompt.loop/markdown/query_loop.system.md`）

### Main Loop

```python
def query_loop(self, max_turns: int | None = None) -> LoopOutcome:
    for turn in range(self._turn_offset, self._max_turns_limit):
        self.query_context.current_turn = turn + 1

        # Step 1: Choose action(s)
        action_specs = self._run_step("choose_action", self._step1_choose_action)
        if action_specs is _INTERRUPT_SENTINEL: ...
        if action_specs is _ABORT_SENTINEL: ...
        if action_specs is None: continue  # error occurred, loop continues

        # Step 2a: Generate parameters（并行，max_workers=3）
        action_specs = self._run_step("generate_parameters", ...)
        if action_specs is None: continue

        # Step 2b: Execute action(s)（ParallelDispatcher → SignalBus）
        step2b_result = self._run_step("execute_action", ...)
        if step2b_result is None: continue

        # Batch-process all signals
        signals = self._signal_bus.consume()
        batch_outcome = self._error_trap.process_signal_batch(signals)
        if batch_outcome.decision == COMPLETE_LOOP: return completed
        if batch_outcome.decision == SUSPEND_LOOP: return suspended
        if batch_outcome.decision == NEXT_TURN: continue

        # Step 3: Update state
        updates = self._run_step("update_state", self._step3_update_state)
        if updates is None: continue
        # _step3_update_state 内部已调用 apply_state_updates + ack

    # max_turns exhausted
    return LoopOutcome(status=EXHAUSTED, ...)
```

### LoopOutcome

统一返回值：
```python
@dataclass
class LoopOutcome:
    class Status(Enum):
        COMPLETED = "completed"      # LOOP_COMPLETE received
        SUSPENDED = "suspended"      # LOOP_SUSPEND received
        EXHAUSTED = "exhausted"      # max_turns reached
        INTERRUPTED = "interrupted"  # KeyboardInterrupt
        ABORTED = "aborted"          # Unrecoverable error

    status: Status
    completed_turns: int
    final_state: dict[str, Any]
    answer: str = ""
    pending_question: dict | None = None
    error_type: str | None = None
    error_message: str | None = None
```

---

## Steps

### Step 1: Choose Action

`ChooseActionTask` 通过 `AITask` 调用 LLM，输入：
- 可用 actions 的 meta 列表（不含 detail）
- `action_schema`（定义 action 结构的标准 schema）

期望输出：
```json
{"action_name": "<name>", "selection_reason": "<reason>"}
```
或并行 batch 格式：
```json
{"actions": [{"action_name": "<name>", "selection_reason": "<reason>"}, ...]}
```

### Step 2a: Generate Parameters

`TakeActionTask` 通过 `AITask` 调用 LLM，输入：
- 选中 action 的 detail（parameter_schema, examples, edge_case_handling）
- 可选的 `selection_reason`（用于对齐参数生成与选择意图）

期望输出：符合 parameter_schema 的 JSON 对象。

参数生成支持**并行化**：当 Step 1 选择了多个独立 Action 时，`ThreadPoolExecutor(max_workers=min(len(specs), 3))` 并发为每个 Action 生成参数。

### Step 2b: Execute Action

`QueryAction.execute()` 调用对应 Handler 的 `execute()`，传入 `action_input` 和 `context_provider`。

执行前通过 `_build_action_spec()` 构建 `ActionSpec`：
```python
def _build_action_spec(self, name: str, target: str) -> ActionSpec:
    mode = self.query_action.get_action_mode(name)  # 从 handler meta 读取 action_mode
    return ActionSpec(name=name, target=target, args={}, mode=mode)
```

这解决了 ONGOING action 被误当 SINGLE_RUN 的问题：`mode` 正确传递到 `ParallelDispatcher`，后者据此发射 `ONGOING_STARTED` 而非 `ACTION_COMPLETED`。

执行结果统一 emit 为 `Signal` 进入 `SignalBus`：
- 成功 → `Signal(ACTION_COMPLETED)`，payload 含 `result`
- 失败 → `Signal(ACTION_FAILED)`，payload 含 `error`、`error_type`
- 超时 → `Signal(ACTION_TIMEOUT)`，payload 含 `error`
- 被终止 → `Signal(ACTION_CANCELLED)`，payload 含 `error`

所有执行类信号都携带 `execution_id`，用于关联 action_record、ONGOING 生命周期和 late-result filtering。

**控制流信号**：部分 Action（如 `reasoning`）可在执行后额外发射 `LOOP_NEXT_TURN`，请求跳过 Step 3 直接进入下一轮。该信号在 `process_signal_batch` 中聚合，优先级低于 `LOOP_COMPLETE` 和 `LOOP_SUSPEND`。

**串行与并行路径终点一致**：无论单 action 还是多 action batch，结果都进入 SignalBus，不在执行现场直接写 state。

### Step 3: Update State

`UpdateStateTask` 通过 `AITask` 调用 LLM，输入：
- `new_action_records`：本轮 peek 到的未读 action records（peek, not consume）
- `state_schema`：state 结构的标准 schema

期望输出：
```json
{
  "todo_operations": [
    {"operation": "add", "key": "<key>", "description": "<desc>"},
    {"operation": "complete", "key": "<key>"},
    {"operation": "cancel", "key": "<key>"}
  ],
  "milestone_operation": "add" | "no-change",
  "milestone_param": "<desc>" | null
}
```

`_normalize_state_updates()` 做防御性校验：
- `todo_operations` 必须是数组
- 每个 operation 必须是含 `operation` + `key` 的字典

`_step3_update_state()` 内部调用 `apply_state_updates()`（`tinysoul/context/state/update.py` 中的纯函数）逐个应用 todo operation，单个失败不影响同轮其他操作。成功后调用 `ack_action_records()`。

> `apply_state_updates()` 已提取为独立纯函数，不依赖完整 QueryLoop，可直接单元测试。

---

## Parallel Dispatcher

`ParallelDispatcher` 使用 `ThreadPoolExecutor` + `concurrent.futures.wait(ALL_COMPLETED)` 实现异构并行 Action 执行。它负责创建 execution 级 `RunConfig`，为每个 Action 分配 `execution_id` 和 `terminate_event`。

### 最慢决定者算法（Slowest-Decider Timeout）

```
batch_timeout = max(action_timeout for each action) + parallel_dispatch_buffer
```

- 遍历 batch 中的每个 `ActionSpec`
- 通过 `QueryAction.get_action_timeout(spec.name)` 获取解析后超时
- 取最大值 `max_timeout`
- 加上缓冲 `settings.parallel_dispatch_buffer`（默认 10.0s）

缓冲的意义：给最慢的 action 一个按自身载体收口的机会，避免 ParallelDispatcher 过早放弃。若 batch 边界仍超时，Dispatcher 会对 pending execution 调用 `RunConfig.request_termination(TIMEOUT)`，补发 `ACTION_TIMEOUT`，并过滤后续晚到的 completed/failed/cancelled 结果，避免同一次 execution 被重复记录。

### 并行 batch 的 Signal 抑制

当 batch 大小 > 1 时，消费 SignalBus 后会**抑制 `LOOP_NEXT_TURN`**：
- 多个 action 并行执行时，它们的数据结果需要 Step 3 来更新 state
- 跳过 Step 3 会丢失这些结果
- `LOOP_COMPLETE` 和 `LOOP_SUSPEND` 不受抑制

### 串行 vs 并行路径统一

| 路径 | 信号发射方式 | 信号类型 |
|------|-------------|----------|
| 串行 SINGLE_RUN | `self._signal_bus.emit(Signal(ACTION_COMPLETED))` | `ACTION_COMPLETED` |
| 串行 ONGOING | `self._signal_bus.emit(Signal(ONGOING_STARTED))` | `ONGOING_STARTED` |
| 并行 SINGLE_RUN | 子线程 `emit(Signal(ACTION_COMPLETED))` | `ACTION_COMPLETED` |
| 并行 ONGOING | 子线程 `emit(Signal(ONGOING_STARTED))` | `ONGOING_STARTED` |

逻辑上所有 Step 2b 执行都经 `ParallelDispatcher`，单 Action 只是 batch size = 1。

---

## ONGOING Action Lifecycle

ONGOING action 遵循**启动即返回、后台持续运行**的模型。`RunConfig.timeout` 只约束启动阶段；启动成功后，后台生命周期由 ongoing control 管理。

```
Turn N, Step 2b:
    LLM 选择 monitor action
    ParallelDispatcher 分配 execution_id
    execute() 启动后台 daemon thread
    action 注册 OngoingControl(execution_id)
    立即返回 {"status": "ongoing_started"}
    emit ONGOING_STARTED(execution_id) → SignalBus
    drain → InterruptHandler → action_record_list + ongoing_action_list

Turn N+1, Step 1~2a 期间:
    后台线程 wait(interval) → emit ONGOING_TICK(execution_id) → SignalBus

Turn N+1, Step 2b drain:
    ONGOING_TICK 被消费 → InterruptHandler → action_record_list

Step 3:
    peek_new_action_records() 看到 ONGOING_TICK 记录
    LLM 根据 tick 内容决定是否继续等待或调用 stop action

显式停止：
    LLM 选择 stop_ongoing_action(execution_id)
    ContextProvider.request_ongoing_termination(execution_id, USER_CANCEL)
    后台执行体观察 control.terminate_event
    emit ONGOING_COMPLETED(execution_id, status=terminated)
    drain → ongoing_action_list.remove(execution_id)

自然完成：
    后台执行体 emit ONGOING_COMPLETED(execution_id, status=completed)
    drain → ongoing_action_list.remove(execution_id)
```

**终态清理**
- `COMPLETED`、`EXHAUSTED`、`ABORTED`、`INTERRUPTED` 返回前，QueryLoop 会对已注册的 ongoing controls 发出 `SHUTDOWN`，并短暂 drain 完成信号
- `SUSPENDED` 是可恢复状态，不默认停止 ongoing；外部可 resume，或通过 stop action 显式结束指定 execution

**ContextProvider.emit_signal()** 是 action 层访问信号系统的唯一入口：
```python
def emit_signal(self, signal: Signal) -> None:
    if self._signal_bus is not None:
        self._signal_bus.emit(signal)
```

这提供了恰到好处的抽象：action 层知道"我在发一个信号"，但不知道信号如何被缓冲、何时被消费、由谁处理。

---

## Suspend & Resume

### Suspend

`ask_user` action 执行时发射 `LOOP_SUSPEND` 信号 → `ErrorTrap` 路由为 `SUSPEND_LOOP` → `QueryLoop` 返回 `LoopOutcome(status=SUSPENDED)`。

返回值包含 `pending_question`，供外部代码向用户展示问题。

### Resume

```python
def resume(self, user_response: str) -> LoopOutcome:
    # 找到最后一个 INQUIRY
    # append_response(user_response, last_inquiry)
    # 重置 suspension flag
    # 继续 query_loop()
```

Preconditions：
- `query_loop()` 先前返回了 `status=SUSPENDED`
- `user_response` 是对 `pending_question` 的回答

若 loop 未处于 suspended 状态，`resume()` 返回 `LoopOutcome(status=ABORTED, error_type="ResumeStateError")`，而非抛出异常。

### User Append

`QueryContext.append_append(content, turn)` 委托给 `QueryEvents.append_append()`，将用户的补充输入追加到 query 事件流。这是 `resume()` 之外另一种向 loop 注入外部输入的方式。

---

## State Update Semantics

### Todo Operation 隔离

- 每个 todo operation 独立 try/except
- 一个 operation 失败（如歧义 key）不会丢弃同轮的其他 operation 或 milestone
- 失败记录为 `loop_error`；非 `TinysoulError` 子类的异常 error_type 前缀 `state/`

### Milestone 只增

- 仅支持 `add` 操作，不支持删除或编辑
- 保证里程碑是单调增长的历史记录

### 独立 `apply_state_updates()`

`tinysoul/context/state/update.py` 中的 `apply_state_updates()` 是纯函数，接收 `query_state`、`updates`、`turn`、`logger`，逐个应用操作。它不依赖完整 `QueryLoop`，可直接单元测试。

---

## Query Context

`QueryContext` 实现 `ContextProvider` 协议，职责：
- 持有运行时对象引用：`query_state`, `query_action`, `workspace`, `signal_bus`
- 按需序列化：`get_current_state()`, `get_workspace()`, `peek_new_action_records()`
- 维护 `current_turn`
- 管理 query 事件流（`QueryEvents`）：`append_inquiry()`, `append_response()`, `append_append()`
- 提供 `get_loop_level_system()` 供内部 LLM Action 获取 loop-level system messages；action execution context 由 action 层统一追加

`get_current_state()` 的字段顺序有语义：
1. `action_record_list` — 近期全量，早期压缩为摘要（action_name + turn + status）
2. `feedback_error_list` — 派生自 `loop_error_list`，过滤 `auto_handled`
3. `current_turn` — 动态部分
4. `todo_list`, `milestone_list`, `ongoing_action_list`

`ongoing_action_list` 暴露的是 execution 视图：
`{execution_id, action_name, turn, status, started_at}`。LLM 停止后台任务时必须使用 `execution_id`，不能只用 `action_name`。

---

## Invariants

- 所有步骤由 `_run_step` 包裹；业务代码中无分散的 `try/except`
- Action schema 和 State schema 通过 `InputSpec.data` 传入，不在 system context 中
- `new_action_records` 在 Step 3 前被 peek（不消费），成功后 ack
- 若 Step 3 失败，未读记录保持 unread，供下一轮重新消费
- 每个 todo operation 独立失败隔离；单条失败不丢弃整轮更新
- `KeyboardInterrupt` 经 ErrorTrap 路由为 `USER_INTERRUPT`，外层优雅返回
- `max_turns` 从 `settings.max_turns` 读取，非硬编码
- 并行 batch 中 `LOOP_NEXT_TURN` 被抑制，但 `LOOP_COMPLETE` 和 `LOOP_SUSPEND` 保留
- ONGOING action 的 `execute()` 立即返回；`ParallelDispatcher.wait(ALL_COMPLETED)` 的语义是"启动完成"
- `ContextProvider.emit_signal()` 是 action 层访问信号系统的唯一入口
- SignalBus 中的信号必须在 Step 3 前被消费（每 step 后 drain）
- **执行事件触发**的状态突变（action_record、loop_error、ongoing_action）通过 `InterruptHandler.handle()` 执行
- **LLM 语义更新**触发的状态突变（todo、milestone）由 `apply_state_updates()` 应用
- `RunConfig.timeout` 是本次 execution 的生命周期预算；对 ONGOING action 只约束启动阶段
- ParallelDispatcher timeout 是批量边界和终止意图来源；Executor 负责按自身载体实际停止
- late-result filtering 保证超时后的同一 `execution_id` 不会被重复记录
- `LoopOutcome` 是 `query_loop()` 和 `resume()` 的唯一返回类型，QueryLoop 永不抛异常
- `_build_action_spec()` 从 `query_action.get_action_mode()` 读取 mode，确保 ONGOING action 不被误当 SINGLE_RUN
- ONGOING tracking 以 `execution_id` 为准，同一 action_name 可以有多个并发 execution
