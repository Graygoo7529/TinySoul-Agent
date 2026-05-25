# Signal & ErrorTrap 重构方案

## 目标

1. 统一所有 Executor 返回值为纯净 dict，消除 `{"result": ...}` 嵌套污染
2. 统一 ErrorTrap 的 OS 中断式异常和信号处理架构
3. 移除所有僵尸信号、僵尸 Disposition、遗留解包逻辑
4. Loop 只消费聚合后的控制决策，不直接解析 TrapResult

---

## 一、Executor 层：统一返回值

### 原则
- 所有 Executor.execute() 返回 `dict[str, Any]`，不再包装 `{"result": ...}`
- OneStepAIExecutor 去掉 `return {"result": result}`，直接 `return result`
- 当前返回 `str` 的 `_apply_result` 全部改为返回 dict

### 改动清单

| Executor/Action | 当前返回值 | 新返回值 |
|---|---|---|
| `OneStepAIExecutor` | `{"result": <any>}` | `<dict>` (由 _apply_result 决定) |
| `AnswerAction._apply_result` | `{"answer": ..., "confidence": ..., "references": [...]}` | 不变 (已经是 dict) |
| `ReasoningAction._apply_result` | `{"content": ..., "conclusions": [...], ...}` | 不变 (已经是 dict) |
| `ReadMarkdownFileAction._apply_result` | `"Read markdown file 'xxx'"` (str) | `{"message": "Read markdown file 'xxx'", "file_path": "..."}` |
| `CreateMarkdownFileAction._apply_result` | `"Created markdown file 'xxx'"` (str) | `{"message": "Created...", "file_path": "..."}` |
| `EditMarkdownFileAction._apply_result` | `"Edited markdown file 'xxx'"` (str) | `{"message": "Edited...", "file_path": "..."}` |
| `CreateTemporaryScriptAction._apply_result` | `"Created script file 'xxx'"` (str) | `{"message": "Created...", "file_path": "..."}` |
| `EditTemporaryScriptAction._apply_result` | `"Edited script file 'xxx'"` (str) | `{"message": "Edited...", "file_path": "..."}` |
| `AverageDogWeightExecutor` | `{"result": "37 lbs", "breed": "..."}` | `{"average_weight": "37 lbs", "breed": "..."}` |
| `ScanWorkspaceExecutor` | `{"result": "Scanned...", "resource_count": N}` | `{"message": "Scanned...", "resource_count": N}` |
| `DeleteFileExecutor` | `{"result": "Deleted...", "file_existed": true}` | `{"message": "Deleted...", "file_existed": true}` |
| `CalculateExecutor` | `{"result": 42, "expression": "..."}` | `{"value": 42, "expression": "..."}` |
| `RegisterTemporaryScriptExecutor` | `{"result": "Registered...", "script_path": "..."}` | `{"message": "Registered...", "script_path": "..."}` |
| `SubprocessExecutor` | JSON 直接返回 / `{"result": stdout}` | JSON 直接返回 / `{"output": stdout}` |
| `TemporaryScriptExecutor` | dict 直接返回 / `{"result": raw}` | dict 直接返回 / `{"output": raw}` |
| `MonitorExecutor` | `{"status": "...", "message": "..."}` | 不变 |
| `AskUserExecutor` | `{"question": ..., "context": ...}` | 不变 |

### 影响
- `QueryLoop._unwrap_executor_result` 可以删除
- `Signal.payload["result"]` 直接存纯净 dict
- `action_record.action_result` 直接存纯净 dict
- LLM 在 Step 3 看到的 action_record 是干净结构

---

## 二、Signal 层：移除僵尸

### 移除的信号类型

| 信号 | 状态 | 原因 |
|---|---|---|
| `TURN_TIMEOUT` | 僵尸 | 无任何 emitter |
| `INTERRUPT` | 僵尸 | 无任何 emitter |
| `ONGOING_FAILED` | 僵尸 | 无任何 emitter（失败走 ACTION_FAILED） |
| `ONGOING_STOPPED` | 僵尸 | 无任何 emitter |
| `USER_QUERY_INJECTED` | 僵尸 | 无任何 emitter |

### 保留的信号类型

```python
class SignalType(StrEnum):
    ACTION_COMPLETED = "action_completed"
    ACTION_FAILED = "action_failed"
    ACTION_TIMEOUT = "action_timeout"

    ONGOING_STARTED = "ongoing_started"
    ONGOING_TICK = "ongoing_tick"
    ONGOING_COMPLETED = "ongoing_completed"

    LOOP_COMPLETE = "loop_terminate"
    LOOP_NEXT_TURN = "loop_skip_step3"
    LOOP_SUSPEND = "loop_suspend"
```

---

## 三、ErrorTrap 层：统一架构

### Disposition 重命名

```python
class Disposition(Enum):
    """统一的执行控制决策。

    ErrorTrap 的输出。消费方：
    - _run_step() except 块：ABORT, STEP_FAILED
    - process_signal_batch() → SignalBatchResult：COMPLETE_LOOP, SUSPEND_LOOP, NEXT_TURN
    - 通用：NEXT_STEP
    """
    ABORT = "abort"                    # 步骤级：中止并抛异常
    STEP_FAILED = "step_failed"        # 步骤级：步骤失败但 Loop 继续

    COMPLETE_LOOP = "complete_loop"    # Loop 级：完成整个 Loop
    SUSPEND_LOOP = "suspend_loop"      # Loop 级：挂起 Loop
    NEXT_TURN = "next_turn"            # Loop 级：跳过 Step 3，进入下一轮

    NEXT_STEP = "next_step"            # 通用：正常继续
```

### 移除的 Disposition
- `RETRY`：当前无任何代码返回它，属于僵尸

### 保留的接口
- `capture(exc, context) → TrapResult`：硬中断入口，不变
- `route(signal) → TrapResult`：软中断入口，移除僵尸信号处理

### 新增接口

```python
@dataclass
class SignalBatchResult:
    """ErrorTrap 批量处理信号后的统一输出。Loop 唯一消费的软中断结果。"""
    class Decision(Enum):
        NEXT_STEP = "next_step"          # 正常进入 Step 3
        NEXT_TURN = "next_turn"          # 跳过 Step 3
        COMPLETE_LOOP = "complete_loop"  # 结束 Loop
        SUSPEND_LOOP = "suspend_loop"    # 挂起 Loop

    decision: Decision
    action_data: dict | None = None   # 与控制流关联的主 action result
    has_conflict: bool = False        # 多个矛盾控制流信号


class ErrorTrap:
    def process_signal_batch(
        self,
        signals: list[Signal],
        interrupt_handler: InterruptHandler,
    ) -> SignalBatchResult:
        """
        批量处理信号：先执行所有数据副作用，再汇总控制流决策。

        1. 分离控制流信号 vs 数据信号
        2. 数据信号 → route() → InterruptHandler.handle() → 写入 QueryState
        3. 匹配控制流信号与对应的 ACTION_COMPLETED，提取 action_data
        4. 按优先级决策：COMPLETE_LOOP > SUSPEND_LOOP > NEXT_TURN
        5. 检测冲突（多个不同类型控制流信号）
        """
```

### TrapResult 定位

TrapResult 是 **ErrorTrap → InterruptHandler 的内部传输协议**。Loop 不应消费其 `loop_error` 和 `action_result` 字段。

```python
@dataclass
class TrapResult:
    """ErrorTrap → InterruptHandler 的内部传输协议。

    Loop 只应消费 disposition。
    """
    disposition: Disposition
    loop_error: LoopErrorItem | None = None      # InterruptHandler 输入
    action_result: dict | None = None             # InterruptHandler 输入
```

---

## 四、QueryLoop 层：简化控制流

### 删除
- `_unwrap_executor_result`：Executor 已返回纯净 dict
- `_drain_signal_bus_and_collect`：替换为 `process_signal_batch`

### 改造 Step 2b 后处理

```python
# 旧：
trap_results = self._drain_signal_bus_and_collect("execute_action")
control_dispositions = {tr.disposition for tr in trap_results}
action_completed_results = [...]
raw_action_result = action_completed_results[0].action_result
action_result = self._unwrap_executor_result(raw_action_result)

# 新：
signals = self._signal_bus.consume()
batch_result = self._error_trap.process_signal_batch(
    signals, self._interrupt_handler
)
```

### 改造控制流分支

```python
if batch_result.decision == SignalBatchResult.Decision.COMPLETE_LOOP:
    return {
        "completed_turns": completed_turns,
        "finished": True,
        "answer": (batch_result.action_data or {}).get("answer", ""),
    }

if batch_result.decision == SignalBatchResult.Decision.SUSPEND_LOOP:
    return {
        "completed_turns": completed_turns,
        "suspended": True,
        "pending_question": batch_result.action_data or {},
    }

if batch_result.decision == SignalBatchResult.Decision.NEXT_TURN:
    continue

# NEXT_STEP → 进入 Step 3
```

### Step 1/2a/3 后的 drain

- Step 1/2a 后：移除 drain（无信号来源）
- Step 3 后：保留轻量 drain，只处理 ONGOING tick（数据信号）

---

## 五、Prompt / Logger / 测试同步

### Prompt 层
- UpdateStateTask 的 few-shot 示例中 `"action_result": {"result": "..."}` → 改为新格式

### Logger 层
- `_fmt_action_result`：不再读取 `"result"` 键，改为读取常见业务键（`answer`, `question`, `message`, `value`, `output`, `status`）

### 测试层
- 所有 mock `{"result": "..."}` 更新为新格式
- 所有 Disposition 断言更新（TERMINATE→COMPLETE_LOOP 等）
- 所有信号类型断言更新（移除僵尸信号）

---

## 六、文件改动清单

| 文件 | 改动类型 |
|---|---|
| `tinysoul/error/signal.py` | 移除 5 个僵尸信号 |
| `tinysoul/error/trap.py` | 重命名 Disposition；移除僵尸信号处理；新增 SignalBatchResult/process_signal_batch |
| `tinysoul/error/interrupt_handler.py` | 移除 ONGOING_FAILED/ONGOING_STOPPED 处理 |
| `tinysoul/query/loop.py` | 删除 _unwrap_executor_result；替换 drain 逻辑；简化控制流 |
| `tinysoul/query/parallel_dispatcher.py` | emit 时无需解包 |
| `tinysoul/action/executors/llm/one_step.py` | 去掉 result 包装 |
| `tinysoul/action/executors/subprocess/base.py` | result→output |
| `tinysoul/action/executors/script/temporary.py` | result→output |
| `tinysoul/action/handlers/internal/*` | 多个 Executor 去掉 result 包装或改为返回 dict |
| `tinysoul/infra/logger.py` | _fmt_action_result 更新 |
| `tinysoul/query/steps/update.py` | few-shot 示例更新 |
| `tests/*` | 大量 mock 数据更新 |
