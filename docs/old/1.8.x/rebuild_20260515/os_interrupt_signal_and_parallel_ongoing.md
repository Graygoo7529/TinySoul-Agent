# OS 中断、信号系统与并行 / ONGOING Action 执行架构

## 概述

本文档描述 TinySoul 在 **OS 风格中断路由**、**SignalBus 统一信号缓冲**、**异构并行 Action 执行** 以及 **ONGOING Action 后台生命周期** 四个维度的当前架构设计。这四个维度相互耦合，共同构成 Query Loop 的执行内核。

核心设计目标：
1. **所有执行事件（成功、失败、超时、后台心跳）统一建模为 Signal**
2. **SignalBus 作为唯一的信号缓冲层，解耦执行与状态突变**
3. **Step 3 统一消费 SignalBus，获得完整的本轮执行快照**
4. **并行 batch 与 ONGOING action 共享同一路径，无特殊分支**

---

## 一、OS 中断风格异常 / 信号路由

### 1.1 双入口中断向量表

`ErrorTrap` 是 Query Loop 的中央中断控制器（IVT），拥有两个对称的入口：

| 入口 | 输入类型 | 来源 | 路由目标 |
|------|----------|------|----------|
| `capture(exc, context)` | `BaseException`（硬中断） | Step 1~3 的 `_run_step` 包裹层、不可恢复的系统错误 | `_handle_abort` / `_handle_recoverable` / `_handle_feedback` |
| `route(signal)` | `Signal`（软中断） | SignalBus 消费阶段、平行/后台执行 | 控制/成功信号直接返回 `TrapResult`；失败信号走 `_handle_feedback` |

**关键区分**：
- **硬中断** = step 级失败（LLM 调用超时、JSON 解析错误、代码 bug）。`_run_step` 负责捕获，ErrorTrap 决定 `CONTINUE/RETRY/ABORT`。
- **软中断** = action 级事件（action 完成、失败、超时、ONGOING tick）。由 `SignalBus` 统一缓冲后批量路由。`route()` 将 Signal 映射为纯数据字段后调用 IVT，不再构造伪异常。

### 1.2 InterruptHandler：执行臂分离

`ErrorTrap` 只做 **决策**（Disposition），`InterruptHandler` 只做 **执行**（QueryState 突变）：

```
ErrorTrap (决策层)
    ↓ TrapResult(disposition, loop_error, action_result)
    ↓
InterruptHandler.handle(trap_result, context)
    ├── _write_action_record()   → action_record_list.append()
    ├── _write_loop_error()      → loop_error_list.append()
    ├── _update_ongoing_lifecycle() → ongoing_action_list 维护
    └── _logger.step_failed()    → 结构化日志
```

这种分离保证了：
- **决策逻辑集中**：所有异常的分类策略在 ErrorTrap 中一处维护
- **状态突变单点**：所有对 QueryState 的写入通过 InterruptHandler 一处执行
- **线程安全**：即使多个线程并发调用 `InterruptHandler.handle()`，由于操作都是 `list.append()`（CPython GIL 下原子），无需显式锁

### 1.3 Signal 类型体系

`SignalType` 枚举覆盖了全部执行事件：

```
Action 执行:     ACTION_COMPLETED, ACTION_FAILED, ACTION_TIMEOUT
ONGOING 生命周期: ONGOING_STARTED, ONGOING_TICK, ONGOING_COMPLETED, ONGOING_FAILED, ONGOING_STOPPED
控制:            TURN_TIMEOUT, INTERRUPT
```

每个 Signal 携带完整的运行时上下文（`turn`, `step`, `action_name`, `action_input`, `payload`），可无损转换为 `SignalContext` 供 ErrorTrap 路由。

---

## 二、SignalBus：统一信号缓冲层

### 2.1 为什么需要 SignalBus？

在引入并行执行之前，串行 action 可以直接调用 `ErrorTrap.route()` → `InterruptHandler.handle()` 完成状态写入。但并行化后产生两个问题：

1. **子线程无法直接抛异常到主线程**：需要一种跨线程的"结果投递"机制
2. **Step 3 需要看到完整的本轮快照**：如果子线程"当场处理"结果，Step 3 可能在某些 action 尚未完成时就消费了不完整的 `action_record_list`

SignalBus 作为中间缓冲层解决了这两个问题：
- **生产者**（action 执行线程、ONGOING 后台线程）只负责 `emit(signal)`，不直接碰状态
- **消费者**（QueryLoop 主线程）在固定时机 `consume()` 批量取出，统一路由到 ErrorTrap → InterruptHandler

### 2.2 SignalBus 与 action_record_list 的关系

| 维度 | SignalBus | action_record_list |
|------|-----------|-------------------|
| **层级** | Signal（原始事件） | ActionRecord（处理后的历史记录） |
| **内容** | 含 SignalType、payload、上下文 | 含 action_name、action_target、action_input、action_result |
| **消费方式** | `consume()` 清空 | `consume_unread()` 标记已读 |
| **生命周期** | 瞬时缓冲（step 间） | 持久历史（跨 loop） |

SignalBus 是 **事件层** 的缓冲，action_record_list 是 **状态层** 的持久化。SignalBus 中的信号被 ErrorTrap 路由后，由 InterruptHandler 写入 action_record_list。两者不重叠，而是上下游关系。

### 2.3 消费时机（Drain Points）

QueryLoop 在每轮每个 step 结束后调用 `_drain_signal_bus()`：

```python
# Turn N
action_specs = self._run_step("choose_action", ...)
self._drain_signal_bus("choose_action")   # ← 消费 Step 1 期间产生的 ONGOING tick

action_specs = self._run_step("generate_parameters", ...)
self._drain_signal_bus("generate_parameters")

step2b_result = self._run_step("execute_action", ...)
self._drain_signal_bus("execute_action")  # ← 消费所有 action 结果（串行/并行）

updates = self._run_step("update_state", ...)
self._drain_signal_bus("update_state")
```

**这保证了**：无论 ONGOING 后台线程在哪个 step 期间产生 tick，都不会跨轮遗漏。Step 3 的 `consume_new_action_records()` 看到的永远是"已 drain 完毕"的完整记录集。

---

## 三、并行 Action 执行与最慢决定者算法

### 3.1 ParallelDispatcher 的阻塞语义

`ParallelDispatcher` 使用 `ThreadPoolExecutor` + `concurrent.futures.wait(ALL_COMPLETED)`：

```
Step 2b: dispatch([A, B, C])
    ├── Thread-A: execute A → emit Signal(ACTION_COMPLETED) → SignalBus
    ├── Thread-B: execute B → emit Signal(ACTION_FAILED)    → SignalBus
    ├── Thread-C: execute C → 卡住/死锁
    └── wait(ALL_COMPLETED) 阻塞直到全部结束或超时
```

**关键设计**：子线程**只 emit，不处理**。所有信号缓冲在 SignalBus 中。`dispatch()` 返回后，主线程 `_drain_signal_bus()` 统一消费。

### 3.2 最慢决定者算法（Slowest-Decider Timeout）

`ParallelDispatcher.dispatch()` 的 `timeout` 默认不再为 `None`，而是通过以下算法计算：

```
batch_timeout = max(action_timeout for each action in batch) + parallel_dispatch_buffer
```

实现路径（`parallel_dispatcher.py`）：
1. 遍历 batch 中的每个 `ActionSpec`
2. 通过 `QueryAction.get_action_timeout(spec.name)` 获取该 action 的解析后超时
   - 优先级：`ActionRuntimeConfig.timeout` → `cluster.type` 默认 → `settings.action_timeout`
3. 取最大值 `max_timeout`
4. 加上缓冲 `settings.parallel_dispatch_buffer`（默认 10.0s）

**为什么需要缓冲？**
- `ThreadPoolExecutor` 的调度开销
- 各 action 内部 timeout 的实现粒度不同（有些用 `thread.join`，有些用 `subprocess.run`）
- 给最慢的 action 一个"触发自身内部超时并被正常捕获"的机会，避免 ParallelDispatcher 提前放弃

**超时后的行为**：
- `wait(timeout)` 返回后，pending futures 被 `cancel()`
- 对于已启动但未完成的 futures，`cancel()` 无效，但会补发 `ACTION_TIMEOUT` signal
- 该 action 后续若突然完成，其完成 signal 仍在 SignalBus 中，会在 drain 时被消费

### 3.3 串行 vs 并行的路径统一

无论是单 action（串行）还是多 action（并行），`_step2b_execute_actions()` 的终点都是 **SignalBus**：

| 路径 | 信号发射方式 | 信号类型 |
|------|-------------|----------|
| 串行 SINGLE_RUN | `self._signal_bus.emit(Signal(ACTION_COMPLETED))` | `ACTION_COMPLETED` |
| 串行 ONGOING | `self._signal_bus.emit(Signal(ONGOING_STARTED))` | `ONGOING_STARTED` |
| 并行 SINGLE_RUN | 子线程 `self._signal_bus.emit(Signal(ACTION_COMPLETED))` | `ACTION_COMPLETED` |
| 并行 ONGOING | 子线程 `self._signal_bus.emit(Signal(ONGOING_STARTED))` | `ONGOING_STARTED` |

**没有捷径代码**。串行路径不再直接调用 `ErrorTrap.route()`，而是和并行路径一样 emit 到 SignalBus，由主线程统一 drain。

#### ACTION_FAILED 的 error_type 保留

动作执行失败时，`ACTION_FAILED` 信号的 payload 携带原始异常的完整类型信息（包括 `__cause__` 链）：

```python
except BaseException as exc:
    error_type = type(exc).__name__
    if exc.__cause__:
        error_type = f"{error_type}/{type(exc.__cause__).__name__}"
    self._signal_bus.emit(
        Signal(
            type=SignalType.ACTION_FAILED,
            payload={
                "target": spec.target,
                "error": str(exc),
                "error_type": error_type,   # ← 如 "ActionExecutionError/ZeroDivisionError"
            },
        )
    )
```

`ErrorTrap.route()` 读取 `payload["error_type"]` 而非硬编码 `"FeedbackError"`，确保 LLM 在 `action_result` 中看到真实的异常类型。`ACTION_TIMEOUT` 与 `ONGOING_FAILED` 因来源类型确定，仍使用硬编码的 `error_type`。

---

## 四、ONGOING Action 集成

### 4.1 生命周期模型

ONGOING action 遵循**启动即返回、后台持续运行**的模型：

```
Turn N, Step 2b:
    LLM 选择 monitor action
    execute() 启动后台 daemon thread
    立即返回 {"status": "ongoing_started"}
    emit ONGOING_STARTED → SignalBus
    drain → InterruptHandler → action_record_list + ongoing_action_list

Step 3:
    consume_new_action_records() 看到 ONGOING_STARTED 记录
    LLM 可能添加 "wait for monitor" todo

Turn N+1, Step 1~2a 期间:
    后台线程 sleep(interval) → emit ONGOING_TICK → SignalBus

Turn N+1, Step 2b drain:
    ONGOING_TICK 被消费 → InterruptHandler → action_record_list

Step 3:
    consume_new_action_records() 看到 ONGOING_TICK 记录
    LLM 根据 tick 内容决定是否继续等待或停止

... 最终：
    后台线程 emit ONGOING_COMPLETED → SignalBus
    drain → ongoing_action_list.remove("monitor")
```

### 4.2 启动与运行的分离

`ParallelDispatcher` 对 ONGOING action 的"完成"定义是**启动完成**（`ONGOING_STARTED`），而不是运行结束。后台运行由 action 的 executor 自行管理：

```python
class MonitorExecutor(ActionExecutor):
    def execute(self, action_input, context_provider, run_config):
        # 1. 读取参数
        interval = action_input.get("interval", 2.0)
        max_ticks = action_input.get("max_ticks", 3)

        # 2. 启动后台 daemon thread（独立于 ThreadPoolExecutor）
        def _background():
            for tick in range(1, max_ticks + 1):
                time.sleep(interval)
                context_provider.emit_signal(Signal(ONGOING_TICK, ...))
            context_provider.emit_signal(Signal(ONGOING_COMPLETED, ...))

        threading.Thread(target=_background, daemon=True).start()

        # 3. 立即返回启动结果
        return {"status": "ongoing_started", ...}
```

**为什么 daemon thread？**
- 实验性实现中，monitor 是短生命周期的（固定 tick 次数后自动停止）
- daemon 保证主进程退出时后台线程不会挂住
- 生产级 ONGOING action 未来需要显式的 stop 机制（由 LLM 选择 stop action）

### 4.3 ContextProvider 的 emit_signal 接口

后台线程需要访问 SignalBus。为了避免直接暴露 SignalBus 给 action 层，`ContextProvider` 协议扩展了 `emit_signal()`：

```python
class ContextProvider(Protocol):
    # ... 现有属性 ...
    def emit_signal(self, signal: Signal) -> None: ...
```

`QueryContext` 实现：
```python
def emit_signal(self, signal: Signal) -> None:
    if self._signal_bus is not None:
        self._signal_bus.emit(signal)
```

这提供了恰到好处的抽象：action 层知道"我在发一个信号"，但不知道信号如何被缓冲、何时被消费、由谁处理。

### 4.4 Step 3 的视角：无差别消费

从 Step 3 的 LLM 视角看，`ActionRecord` 的结构是完全统一的：

```json
{
  "action_name": "monitor",
  "action_target": "...",
  "action_input": {"interval": 2.0, "max_ticks": 3},
  "action_result": {"tick": 2, "max_ticks": 3, "elapsed": 4.0}
}
```

Step 3 **不需要区分**这是 SINGLE_RUN 的结果还是 ONGOING 的 tick。它只需要：
1. 读取 `action_record_list` 中的结果内容
2. 查看 `ongoing_action_list` 中是否还有 `"monitor"`

如果 `ongoing_action_list` 包含 `"monitor"`，且本轮看到了新的 monitor 记录，LLM 自然可以推断出"这是正在运行的 monitor 的新 tick"。

---

## 五、关键不变式（Invariants）

重构后严格遵守以下不变式：

1. **所有 action 执行结果必须进入 SignalBus**
   - 串行、并行、ONGOING 的发射路径统一，不允许直接调用 InterruptHandler

2. **所有 SignalBus 信号必须在 Step 3 前被消费**
   - 每轮每个 step 后调用 `_drain_signal_bus()`，确保 Step 3 的 `consume_new_action_records()` 看到完整快照

3. **所有状态突变必须通过 InterruptHandler.handle()**
   - 即使是 `_run_step` 捕获的硬中断，最终也是通过 `InterruptHandler.handle()` 写入 state

4. **ONGOING action 的 execute() 立即返回**
   - `ParallelDispatcher.wait(ALL_COMPLETED)` 对 ONGOING action 的语义是"启动完成"，不是"运行结束"

5. **Action 内部 timeout 是硬约束，ParallelDispatcher timeout 是防死锁保险**
   - 最慢决定者算法确保 ParallelDispatcher 不会比最慢的 action 的内部 timeout 更早放弃

6. **ContextProvider.emit_signal() 是 action 层访问信号系统的唯一入口**
   - action 不持有 ErrorTrap、InterruptHandler 或 SignalBus 的直接引用

---

## 六、扩展点

当前架构预留了以下演进方向：

| 扩展方向 | 当前状态 | 未来路径 |
|----------|----------|----------|
| **跨进程 ONGOING** | Daemon thread 在同进程内 | 将 `ContextProvider.emit_signal()` 改为 IPC / 网络调用，SignalBus 成为跨进程接收缓冲区 |
| **LLM 停止 ONGOING** | Monitor 自动停止（固定 tick 数） | 新增 `stop_ongoing_action` action，LLM 主动选择停止某个 ongoing_action_list 中的 action |
| **Step 2a 并发** | 串行生成参数 | 在 `TakeActionTask` 层面引入信号量控制的并发 LLM 调用 |
| **ONGOING 混排 batch** | ParallelDispatcher 已支持 `ActionSpec.mode` | 允许 batch 中同时包含 SINGLE_RUN 和 ONGOING action，各自按自己的语义完成 |
| **SignalBus 持久化** | 内存 list | 未来可将 SignalBus 扩展为磁盘/Redis 队列，支持跨会话恢复 |
