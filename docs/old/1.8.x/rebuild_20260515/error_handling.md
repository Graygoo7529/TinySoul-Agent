# Error Handling

Error Handling（central exception routing and error taxonomy for query-loop）

## Exception Hierarchy

所有框架异常继承自 `TinysoulError`。ErrorTrap 作为集中中断向量表（OS-style IDT），统一处理所有异常与外部信号。仅 `SystemExit` 和 `GeneratorExit` 由最底层直接透传。

三层分类体系：

```
TinysoulError
├── AbortError                              # 致命，终止 loop
│   ├── ConfigError                         # 配置/初始化错误
│   ├── SystemExhaustedError                # 所有恢复机制耗尽
│   └── LoopAbortError                      # 外部要求终止
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
- WorkspaceError 继承 ActionExecutionError：工作区操作几乎总是 Action 执行的一部分，属于执行失败的子类
- ActionError 与 StateError 是 FeedbackError 下的平行子树：前者发生在 action 执行域，后者发生在 state 操作域
- 所有 FeedbackError 统一携带 `action_name` / `action_input` 协议字段，非 action 阶段可为 null


## AbortError

（1）语义：Fatal error，query loop 必须终止，无法通过重试或反馈恢复

（2）子类：
- `ConfigError`：配置缺失或非法，系统无法启动（如 API key 缺失、workspace_location 不存在）
- `SystemExhaustedError`：所有恢复机制耗尽（如 LLM 多模型池全部失败）
- `LoopAbortError`：外部显式要求终止 loop

（3）处理策略：ErrorTrap 产生 Disposition.ABORT，直接向上传播


## RecoverableError

（1）语义：可以被系统自动处理，无需反馈给 LLM

（2）子类：
- `InterruptSignal`：预留的外部中断信号（非 KeyboardInterrupt）
- `LLMTransientError`：LLM 调用瞬态失败（网络超时、速率限制），携带 `model_name` 字段

（3）`LLMTransientError` 处理链：
- Adapter 调用失败时抛出 `LLMTransientError`
- AIClient 内部执行指数退避重试，并在多模型池间自动切换
- 若全部模型池耗尽，AIClient 抛出 `SystemExhaustedError`
- ErrorTrap 将 `SystemExhaustedError` 识别为 `AbortError`，返回 Disposition.ABORT
- 防御性兜底：若 `LLMTransientError` 绕过 AIClient 直接到达 ErrorTrap，仍会被包装为 `SystemExhaustedError` 并返回 ABORT

recoverable error semantics(additional explanation)
- auto_handled=True 的 LoopErrorItem 会被 build_feedback_errors 过滤掉，LLM 不会感知到已被系统自动处理的问题
- raw_traceback 对 auto_handled 错误会被置空，避免向 LLM 暴露无意义的堆栈


## FeedbackError

（1）语义：必须反馈给 LLM，使其能够调整策略。所有 FeedbackError 进入 loop_error_list。

（2）统一协议：
- `action_name`: Optional[str] — 异常发生时的 action 名称
- `action_input`: dict | None — 异常发生时的 action 输入（结构化字典）
- `to_loop_error_message()`: str — 标准化消息格式

（3）标准化消息格式：
```
action=<action_name> | input=<action_input> | error=<message>
```
- 若 action_name 为 null，则省略 `action=` 段
- 若 action_input 为 null，则省略 `input=` 段


### LLM Response Errors

`LLMResponseParseError`：LLM 返回的原始文本无法解析为合法的结构化数据（如 JSON 解析失败）

`LLMResponseValidationError`：LLM 返回的结构化数据能够解析但不符合语义要求（如缺失必要字段、字段类型错误）


### ActionError

（1）语义：Action 执行域中的错误。ActionError 会被**双记录**：
- 进入 `loop_error_list`（所有 FeedbackError 都进入）
- 额外生成 `action_result` 进入 `action_record_list`

（2）子类：
- `ActionNotFoundError`：请求的 action 在 QueryAction 的可用列表中不存在
- `ActionInputError`：action 输入参数解析或验证失败（如非法 JSON、缺失 required 字段）
- `ActionExecutionError`：action 执行逻辑失败
  - `WorkspaceError`：工作区操作失败（路径穿越、资源不存在、资源冲突等）

（3）双记录判定：
- **硬中断路径**（`capture()`）：ErrorTrap 通过 `isinstance(exc, ActionError)` 判定
- **软中断路径**（`route()`）：`ACTION_FAILED`、`ACTION_TIMEOUT`、`ONGOING_FAILED` 均标记 `is_action_error=True`，统一产生 `action_result`
- 两种路径的最终行为一致：动作执行失败既进入 `loop_error_list`，也进入 `action_record_list`

action error semantics(additional explanation)
- ActionNotFoundError 与 ActionInputError 的区分：前者是"调度阶段找不到 action"，后者是"找到了 action 但参数不合法"
- WorkspaceError 作为 ActionExecutionError 的子类，天然参与双记录，无需在 ErrorTrap 中做特殊场景判断


### StateError

（1）语义：State 操作域中的错误。仅进入 `loop_error_list`，不生成 `action_result`。

（2）子类：
- `TodoAmbiguityError`：todo key 匹配到多个 pending todo，无法确定操作目标


## Interrupt Handling（OS-Style）

ErrorTrap 不仅是异常路由器，更是**集中中断处理中心（Interrupt Vector Table）**。

### 中断 vs 错误

| | 中断（Interrupt） | 错误（Error） |
|---|---|---|
| 来源 | 外部信号（用户、系统） | 内部执行故障 |
| 代表 | `KeyboardInterrupt`、`InterruptSignal` | `ActionError`、`StateError` |
| 是否记录 loop_error | ❌ 不记录（不是故障） | ✅ 记录 |
| Disposition | `ABORT` / `CONTINUE` | `CONTINUE` / `RETRY` / `ABORT` |

### _run_step 统一入口

```
step_fn() 执行
    ↓
BaseException 发生（除 SystemExit / GeneratorExit）
    ↓
ErrorTrap.capture()  —— 中断向量表查询
    ↓
_handle_interrupt()  /  _handle_recoverable()  /  _handle_feedback()
    ↓
返回 TrapResult（Disposition + 可选 loop_error + 可选 action_result）
    ↓
_run_step 根据 Disposition 执行恢复策略
```

### KeyboardInterrupt 处理链

```
用户按下 Ctrl+C → KeyboardInterrupt
    ↓
_run_step 捕获（不再硬编码透传）
    ↓
ErrorTrap._handle_interrupt()
    ↓
返回 Disposition.ABORT, loop_error=None（不记录错误）
    ↓
_run_step 重新 raise KeyboardInterrupt
    ↓
query_loop() 外层捕获 → 优雅返回当前状态
```

### InterruptSignal 处理链

```
外部系统发送 InterruptSignal
    ↓
ErrorTrap._handle_interrupt()
    ↓
返回 Disposition.CONTINUE, loop_error=auto_handled（静默记录）
    ↓
loop 继续下一 turn
```


## ErrorTrap

ErrorTrap（central exception router / interrupt handler for query-loop）

### Disposition

ErrorTrap 对异常/中断的处置决策：
- `CONTINUE`：记录错误（如有）后继续下一 turn
- `RETRY`：自动恢复后重试当前 step（如 LLM 模型切换）
- `ABORT`：终止当前 step，向上传播异常（致命错误或用户中断）

### ErrorContext

异常发生时的运行时上下文：
- `turn`: int — 异常发生的 turn 编号（1-based）
- `step`: str — `"choose_action" | "generate_parameters" | "execute_action" | "update_state"`
- `action_name`: Optional[str] — 若 step 为 execute_action，则为执行的 action 名称
- `action_input`: dict | None — 若 step 为 execute_action，则为 action 的结构化输入

### TrapResult

ErrorTrap.capture() 与 ErrorTrap.route() 的统一返回结果：
- `disposition`: Disposition — 处置决策
- `loop_error`: Optional[LoopErrorItem] — 统一的错误记录。对于中断信号（KeyboardInterrupt）为 None——中断不是错误，不污染 loop_error_list
- `action_result`: dict | None — 当 disposition=CONTINUE 且需要双记录时生成的结构化结果，用于写入 action_record_list。格式：`{"error": "...", "error_type": "..."}`


## LoopErrorItem

LoopErrorItem（定义于 `tinysoul.trap.loop_error`，loop_error_list 中的统一错误记录，审计用途）

（1）字段：
- `timestamp`: datetime — 异常发生时间
- `turn`: int — 异常发生的 turn 编号
- `step`: str — 异常发生的 step
- `error_type`: str — 异常类型链（如 `"ActionExecutionError/ValueError"`、`"ActionInputError"`）
- `message`: str — 标准化错误消息
- `action_name`: Optional[str]
- `action_input`: dict | None
- `auto_handled`: bool — 是否被系统自动处理
- `recovered`: bool — 是否已成功恢复
- `raw_traceback`: Optional[str] — 原始堆栈（auto_handled 时为 null）

（2）`to_feedback_view()`: 提取 LLM-facing 视图，用于构建 feedback_error_list


## feedback_error_list

feedback_error_list 来源于 loop_error_list 的派生视图，专用于向 LLM 提供错误反馈。

feedback_error_list semantics(additional explanation)
- 不是独立存储，而是 loop_error_list 的投影
- auto_handled=True 的错误会被过滤（LLM 无需知道已被系统自动处理的问题）
- 在 current_state 中，feedback_error_list 位于 action_record_list 之后，作为静态边界的一部分


## ErrorTrap_Query_Loop_Integration

ErrorTrap 在 Agent Query Loop 各阶段中的作用。

### Step_Integration

- Step 1: choose action
  - 异常类型：LLMResponseParseError / LLMResponseValidationError
  - Disposition: CONTINUE
  - 记录：仅 loop_error_list（非 ActionError，无 action_result）

- Step 2a: generate parameters
  - 异常类型：LLMResponseParseError / LLMResponseValidationError
  - Disposition: CONTINUE
  - 记录：仅 loop_error_list（参数生成失败不是 action 执行失败）

- Step 2b: execute action
  - 异常类型：ActionInputError / ActionExecutionError / WorkspaceError
  - Disposition: CONTINUE
  - 记录：loop_error_list + action_record_list（双记录）
  - action_result 格式：`{"error": "...", "error_type": "..."}`

- Step 3: update state
  - 异常类型：LLMResponseParseError / LLMResponseValidationError / StateError
  - Disposition: CONTINUE
  - 记录：仅 loop_error_list
  - 若异常发生，updates 回退为安全默认值（finished=false）

### Error_Context_Binding

`_run_step` 统一包裹所有 step 的执行（OS 式中断模型）：
- `except BaseException` 捕获所有异常与中断（`SystemExit`/`GeneratorExit` 直接透传）
- 所有捕获的异常/中断被路由到 ErrorTrap.capture()（中断向量表）
- ErrorContext 的 `step` 字段精确标识发生位置（choose_action / generate_parameters / execute_action / update_state）
- ErrorContext 的 `action_name` / `action_input` 在 execute_action 阶段由 QueryLoop 传入
- `_run_step` 根据 TrapResult.disposition 执行统一恢复策略，不再按异常类型特殊分支


## ErrorTrap_Action_Integration

Action 执行边界处的异常处理由 `ActionBase.execute()` 统一负责。

### Boundary_Wrapper

ActionBase.execute() 的行为：
1. 调用 `self._executor.execute(action_input, context_provider)`
2. 若抛出 `TinysoulError` 子类 → **原样透传**
3. 若抛出其他未知异常 → **包装为 `ActionExecutionError`**，自动附加 `action_name` 和 `action_input`

boundary wrapper semantics(additional explanation)
- Executor 开发者只需在能精确识别错误类型时主动抛出 ActionInputError / WorkspaceError 等
- 未知异常（如 ZeroDivisionError、KeyError）由边界包装器自动捕获并升级，确保 ErrorTrap 能正确分类
- TinysoulError 子类（如 LLMResponseParseError）会被边界包装器原样透传，不会被二次包装；只有非框架异常（如 ZeroDivisionError、KeyError）才会被升级为 ActionExecutionError


## ErrorTrap_LLMClient_Integration

ErrorTrap 与 LLMClient 的协作关系。

### Failover_Chain

```
AIClient.chat()
├── 内部指数退避重试（max_retries，由 ModelConfig 配置）
├── 单模型失败 → 捕获 LLMTransientError，自动重试 / 切换模型
└── 全部模型池耗尽 → 抛出 SystemExhaustedError
    └── ErrorTrap.capture()
        ├── 识别为 AbortError
        └── 返回 Disposition.ABORT
```

### Injection_Pattern

ErrorTrap 不内部创建 AIClient，必须由外部注入：
- QueryLoop 在初始化时通过 `get_ai_client()` 获取实例并传入 ErrorTrap
- 测试场景可注入 mock AIClient，控制 failover 行为


## Error_Handling_Invariants

All framework errors inherit from TinysoulError
SystemExit bypasses ErrorTrap immediately; GeneratorExit is handled outside ErrorTrap by _run_step; all other exceptions/interrupts route through ErrorTrap
KeyboardInterrupt is handled by ErrorTrap._handle_interrupt() — not hard-coded propagation
InterruptSignal is handled by ErrorTrap._handle_interrupt() — not RecoverableError auto-continue
ActionError (hard interrupt) and ACTION_FAILED / ACTION_TIMEOUT / ONGOING_FAILED (soft interrupt) are all recorded to both loop_error_list and action_record_list
FeedbackError always enters loop_error_list; ActionError subclasses and action-level failure signals additionally generate action_result
Interrupts (KeyboardInterrupt) intentionally produce `loop_error=None` — they are signals, not errors
auto_handled=True errors are suppressed from feedback_error_list
ErrorTrap must receive AIClient from outside; no hidden global dependency
raw_traceback is null for auto_handled errors
action_name and action_input are set at raise time, not assembled later
