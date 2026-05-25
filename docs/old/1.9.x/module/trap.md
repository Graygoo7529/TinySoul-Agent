# Trap

Trap 模块位于 `tinysoul/trap/`，是 TinySoul 的**集中异常与信号路由中枢**。它采用 OS 风格的中断向量表（IVT）模型，统一处理 Query Loop 执行过程中的一切异常、信号和状态突变。所有状态写入——无论来源是硬中断（异常）还是软中断（Signal）——都经过同一套路由逻辑。

---

## Design Principles

### 1. OS-Style 中断路由

- 所有 step 由 `_run_step` 统一包裹，异常不再按类型分散 try/except
- `ErrorTrap.capture()` 作为中断向量表，将异常分类为 `ABORT` / `CONTINUE`
- `KeyboardInterrupt` 被路由为 `USER_INTERRUPT`，外层优雅返回当前状态
- 状态更新中的每个 todo operation 独立 `try/except`，部分失败不丢弃整轮更新

### 2. 决策与执行分离

- `ErrorTrap` 只做**决策**（`Disposition`），不做状态突变
- `InterruptHandler` 只做**执行**（`QueryState` 写入），不做决策
- 这种分离使决策逻辑集中维护，状态突变单点执行

### 3. 硬中断与软中断统一模型

| | 硬中断（Hard Interrupt） | 软中断（Soft Interrupt） |
|---|---|---|
| 来源 | `BaseException`（异常） | `Signal`（执行事件） |
| 入口 | `ErrorTrap.capture()` | `ErrorTrap.route()` |
| 场景 | Step 失败、系统错误 | Action 完成/失败/超时/取消、ONGOING tick |
| 是否记录 loop_error | FeedbackError 是；中断不是 | 数据信号否；失败信号是 |

两种中断最终都输出统一的 `TrapResult`（`Disposition` + 可选 `loop_error` + 可选 `action_result`），由 `InterruptHandler` 执行状态副作用。

### 4. SignalBus 解耦

- 所有 Action 执行结果（串行/并行/ONGOING）统一 emit 为 `Signal` 进入 `SignalBus`
- 主循环在固定时机 `consume()` 批量取出，统一路由
- 这解耦了执行现场与状态突变，支持并行和后台线程

---

## Exception Hierarchy

```
TinysoulError
├── AbortError                              # 致命，终止 loop
│   ├── ConfigError                         # 配置/初始化错误
│   ├── SystemExhaustedError                # 所有恢复机制耗尽
│   └── LoopAbortError                      # 外部要求终止 loop
│
├── RecoverableError                        # 自动恢复，不反馈 LLM
│   ├── InterruptSignal                     # 预留外部中断信号
│   └── LLMTransientError                   # LLM 调用瞬态失败
│
└── FeedbackError                           # 必须反馈给 LLM
    ├── LLMResponseParseError               # LLM 返回无法解析
    ├── LLMResponseValidationError          # LLM 返回语义不符
    ├── ActionError                         # Action 相关（双记录）
    │   ├── ActionNotFoundError             # Action 不存在/未注册
    │   ├── ActionInputError                # 参数解析/验证失败
    │   └── ActionExecutionError            # 执行逻辑失败
    │       └── WorkspaceError              # 工作区操作失败
    │           ├── PathTraversalError
    │           ├── ResourceNotFoundError
    │           └── ResourceConflictError
    └── StateError                          # State 操作错误
        └── TodoAmbiguityError
```

exception hierarchy semantics(additional explanation)
- `WorkspaceError` 继承 `ActionExecutionError`：工作区操作几乎总是 Action 执行的一部分
- `ActionError` 与 `StateError` 是 `FeedbackError` 下的平行子树：前者发生在 action 执行域，后者发生在 state 操作域
- 所有 `FeedbackError` 统一携带 `action_name` / `action_input` 协议字段
- `auto_handled=True` 的错误会被过滤出不进入 `feedback_error_list`（LLM 无需知道已被系统自动处理的问题）

---

## ErrorTrap

OS-Style Interrupt Controller。三个入口点（均返回 `TrapOutcome`）：

```python
capture(exc, context)       → TrapOutcome  # 硬中断（异常）
route(signal)               → TrapOutcome  # 软中断（单信号）
process_signal_batch(signals) → TrapOutcome  # 软中断（批量信号）
```

### Disposition

| 决策 | 语义 | 消费方 |
|------|------|--------|
| `ABORT` | 致命，停止执行并向上传播 | `_run_step` |
| `USER_INTERRUPT` | 用户按下 Ctrl+C | `_run_step` → Loop 返回 `interrupted` |
| `COMPLETE_LOOP` | Loop 正常结束（answer action） | `process_signal_batch` → Loop 返回 `completed` |
| `SUSPEND_LOOP` | Loop 挂起等待用户输入（ask_user） | `process_signal_batch` → Loop 返回 `suspended` |
| `NEXT_TURN` | 跳过 Step 3，直接进入下一轮 | `process_signal_batch` |
| `NEXT_STEP` | 正常继续 | 通用默认值 |

### TrapResult

ErrorTrap → InterruptHandler 的内部传输协议：
```python
@dataclass
class TrapResult:
    disposition: Disposition
    loop_error: LoopErrorItem | None = None
    action_result: dict | None = None
```

Loop 不应消费其 `loop_error` 和 `action_result` 字段——这些已由 `InterruptHandler` 处理完毕。

### ErrorContext

异常发生时的运行时上下文：
- `turn`: int — 异常发生的 turn 编号（1-based）
- `step`: str — `"choose_action" | "generate_parameters" | "execute_action" | "update_state"`
- `action_name`: Optional[str]
- `action_input`: dict | None

### capture() — 硬中断入口

```python
def capture(exc: BaseException, context: ErrorContext) -> TrapOutcome:
    # SystemExit / GeneratorExit 直接透传
    # KeyboardInterrupt → Disposition.USER_INTERRUPT
    # AbortError → Disposition.ABORT
    # RecoverableError (LLMTransientError) → 包装为 SystemExhaustedError → ABORT
    # FeedbackError → Disposition.NEXT_STEP + loop_error (+ action_result if ActionError)
    # 未知异常 → 包装为 FeedbackError → NEXT_STEP
```

### route() — 软中断入口

```python
def route(signal: Signal) -> TrapOutcome:
    # 控制流信号（LOOP_COMPLETE / LOOP_SUSPEND / LOOP_NEXT_TURN）→ 直接映射 Disposition
    # 成功信号（ACTION_COMPLETED / ONGOING_STARTED / ONGOING_TICK / ONGOING_COMPLETED）→ NEXT_STEP
    # 失败信号（ACTION_FAILED / ACTION_TIMEOUT / ACTION_CANCELLED）→ NEXT_STEP + loop_error + action_result
    # USER_APPEND → NEXT_STEP（用户补充输入，追加到 QueryEvents）
```

### process_signal_batch() — 批量软中断

批量处理信号：先执行所有数据副作用，再聚合控制流决策。

优先级：
1. `LOOP_COMPLETE` → `COMPLETE_LOOP`（最高控制）
2. `LOOP_SUSPEND` → `SUSPEND_LOOP`
3. `LOOP_NEXT_TURN` → `NEXT_TURN`（跳过 Step 3，直接进入下一轮）
4. （默认）→ `NEXT_STEP`

---

## Signal & SignalBus

### SignalType

```python
class SignalType(StrEnum):
    # Action execution signals
    ACTION_COMPLETED = "action_completed"
    ACTION_FAILED = "action_failed"
    ACTION_TIMEOUT = "action_timeout"
    ACTION_CANCELLED = "action_cancelled"

    # ONGOING lifecycle signals
    ONGOING_STARTED = "ongoing_started"
    ONGOING_TICK = "ongoing_tick"
    ONGOING_COMPLETED = "ongoing_completed"

    # Loop control flow signals
    LOOP_COMPLETE = "loop_complete"
    LOOP_NEXT_TURN = "loop_next_turn"
    LOOP_SUSPEND = "loop_suspend"

    # User dialogue signals
    USER_APPEND = "user_append"
```

### Signal

统一的执行事件格式：
```python
@dataclass
class Signal:
    type: SignalType
    turn: int
    step: str | None = None
    action_name: str | None = None
    action_input: dict | None = None
    execution_id: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)
```

### SignalBus

线程安全的信号缓冲层：
```python
class SignalBus:
    def emit(signal: Signal) -> None
    def consume() -> list[Signal]       # 取出并清空
    def peek() -> list[Signal]          # 仅查看不清空
```

SignalBus 是**事件层**的缓冲，action_record_list 和 QueryEvents 是**状态层**的持久化目标。Action 执行类信号被 ErrorTrap 路由后，由 InterruptHandler 写入 action_record_list；USER_APPEND 信号则追加到 QueryEvents，不写 action_record_list。

---

## InterruptHandler

状态突变的唯一执行点。接收 `TrapResult` + `SignalContext`，执行：

```
_write_action_record()   → action_record_list.append()
_write_loop_error()      → loop_error_list.append()
_update_ongoing_lifecycle() → ongoing_action_list 按 execution_id 维护
_append_query_events()   → QueryEvents.append_append()（仅 USER_APPEND）
_logger.step_failed()    → 结构化日志
```

即使多个线程并发调用 `InterruptHandler.handle()`，由于操作都是 `list.append()`（CPython GIL 下原子），无需显式锁。

---

## Dual-Recording（双记录）

`ActionError` 及其子类（包括 `WorkspaceError`）会被**双记录**：
- 进入 `loop_error_list`（所有 FeedbackError 都进入）
- 额外生成 `action_result` 进入 `action_record_list`

**硬中断路径**（`capture()`）：ErrorTrap 通过 `isinstance(exc, ActionError)` 判定
**软中断路径**（`route()`）：`ACTION_FAILED`、`ACTION_TIMEOUT`、`ACTION_CANCELLED` 均标记 `is_action_error=True`

两种路径的最终行为一致：动作执行失败既进入 `loop_error_list`，也进入 `action_record_list`。
其中 `ACTION_TIMEOUT` 的 action record status 为 `timeout`，`ACTION_CANCELLED` 的 status 为 `cancelled`，普通失败为 `failed`。

---

## KeyboardInterrupt 处理链

```
用户按下 Ctrl+C → KeyboardInterrupt
    ↓
_run_step 捕获（不再硬编码透传）
    ↓
ErrorTrap._handle_interrupt()
    ↓
返回 Disposition.USER_INTERRUPT, loop_error=None（中断不是错误）
    ↓
_run_step 返回 _INTERRUPT_SENTINEL
    ↓
query_loop() 映射为 LoopOutcome.Status.INTERRUPTED → 优雅返回
```

---

## Integration

### 与 QueryLoop 的关系

- `_run_step` 是硬中断的单一入口
- `_signal_bus.consume()` + `process_signal_batch()` 是软中断的单一入口
- `ErrorTrap` 的 `capture()` 和 `route()` 共享同一套 IVT
- `InterruptHandler.handle()` 是**执行事件触发**的状态突变（action_record、loop_error、ongoing_action）的唯一执行点

### 与 Action 的关系

- `ActionBase.execute()` 边界包装：未知异常 → `ActionExecutionError`，`TinysoulError` 子类原样透传
- 执行器失败抛出的异常被 `_run_step` 捕获，经 ErrorTrap 路由后双记录

### 与 LLMClient 的关系

- `AIClient.chat()` 内部指数退避重试
- 单模型失败 → 捕获 `LLMTransientError`，自动重试/切换模型
- 全部模型池耗尽 → 抛出 `SystemExhaustedError`
- `SystemExhaustedError` 被 ErrorTrap 识别为 `AbortError` → `Disposition.ABORT`

---

## Invariants

- 所有框架错误继承自 `TinysoulError`
- `SystemExit` 绕过 ErrorTrap 立即透传；`GeneratorExit` 由 `_run_step` 处理
- `KeyboardInterrupt` 经 ErrorTrap 路由后重新抛出，外层优雅处理
- 中断（KeyboardInterrupt）不是错误，intentionally 产生 `loop_error=None`
- `ActionError`（硬中断）和 `ACTION_FAILED` / `ACTION_TIMEOUT` / `ACTION_CANCELLED`（软中断）均双记录到 `loop_error_list` + `action_record_list`
- `FeedbackError` 总是进入 `loop_error_list`；`ActionError` 子类额外生成 `action_result`
- `auto_handled=True` 的错误被抑制在 `feedback_error_list` 之外
- `raw_traceback` 对 `auto_handled` 错误为 null
- `action_name` 和 `action_input` 在 raise 时设置，不在捕获时组装
- **执行事件触发**的状态突变（action_record、loop_error、ongoing_action）通过 `InterruptHandler.handle()` 执行
- **LLM 语义更新**触发的状态突变（todo、milestone）由 `apply_state_updates()` 直接应用
- 两者共享 `QueryState` 作为统一门面，但由不同组件驱动
- SignalBus 中的信号必须在 Step 3 前被消费（每 step 后 drain）
- 并行 batch 中超时的 future 会收到 `RunConfig.request_termination(TIMEOUT)`，并由 Dispatcher 补发 `ACTION_TIMEOUT` signal
- 所有执行类 signal 可携带 `execution_id`；ONGOING lifecycle 必须携带 `execution_id`
- `USER_APPEND` 信号作为用户补充输入路由为 `NEXT_STEP`，由 `InterruptHandler` 追加到 `QueryEvents`，不写入 `action_record_list`
