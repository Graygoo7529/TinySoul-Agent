# Loop 模块

## 定位

Loop 模块是 TinySoul 的顶层编排器。它把用户查询拆成多轮动作选择、参数生成、动作执行和状态更新，并根据信号决定继续、挂起、完成或中止。

Loop 不直接实现业务动作，也不直接调用具体模型供应商。它只依赖：

- `QueryAction` 执行动作。
- `AITask` 完成 LLM 子任务。
- `QueryContext` 暴露运行态上下文。
- `ParallelDispatcher` 并发执行动作。
- `ErrorTrap` 统一处理异常和信号。

## 核心对象

### `QueryLoop`

`QueryLoop` 是主入口。初始化时会：

- 创建或接收 `ActionRegistry`。
- 应用动作 allowlist。
- 初始化 `QueryEvents`、`QueryState`、`Workspace`、`QueryAction`。
- 构建 `SignalBus`、`QueryContext`、PromptBuilder 和各 Step Task。
- 构建 loop-level system messages。
- 若工作区资源为空，执行一次 workspace scan。

`run()` 返回 `LoopOutcome`，而不是直接返回裸字符串或异常。

### `LoopOutcome`

当前状态包括：

- `COMPLETED`：已得到最终答案。
- `SUSPENDED`：等待用户回答。
- `EXHAUSTED`：达到最大轮次。
- `INTERRUPTED`：用户中断。
- `ABORTED`：不可恢复错误。

业务异常通常不会逃出 Loop。`_run_step()` 会捕获除 `SystemExit`、`GeneratorExit` 外的异常，并交给 Trap 转成结构化结果。

### `ParallelDispatcher`

Dispatcher 负责动作并发执行和信号发射：

- 使用线程池执行本批动作。
- 为每个动作绑定 `execution_id` 和 `RunConfig`。
- 将成功、失败、超时、取消转换为 signal。
- 多动作批次会抑制普通 `LOOP_NEXT_TURN`，但保留完成和挂起控制信号。
- 批次超时时请求 pending 动作终止，并关闭线程池。

批次总超时是动作超时上限加 `settings.parallel_dispatch_buffer`，当前默认 buffer 为 `20.0` 秒。

## 主流程

每一轮分为三步：

### Step1：动作选择

模型读取 query events、当前状态、工作区和动作列表，选择一组动作规格。动作规格会带上动作名、目标、选择理由和执行模式。

Loop 会查询 `QueryAction.get_action_mode()`，把动作模式写回 spec。未知动作默认按 single-run 处理，并在执行阶段失败。

### Step2a：参数生成

Loop 为每个动作并发生成参数。当前使用 `ThreadPoolExecutor`，最大并发为 `min(action_count, 3)`。

参数生成失败会进入 Trap。可恢复错误会作为反馈进入下一轮，不可恢复错误会中止 Loop。

### Step2b：动作执行

Loop 把动作 spec 和参数交给 Dispatcher。Dispatcher 执行动作后把结果写入 `SignalBus`。

随后 Loop 从 SignalBus 消费信号，并调用 `process_signal_batch()`：

- data signal 先交给 Trap/InterruptHandler 落库。
- control signal 按优先级聚合。
- 聚合结果决定本轮是否进入 Step3 或直接返回。

若收到 `COMPLETE_LOOP` 或 `SUSPEND_LOOP`，Loop 会在 Step3 前返回对应 outcome。因此，终止动作产生的 action record 可能已经写入状态，但未必已经被 Step3 读取和 ack。

### Step3：状态更新

当控制结果允许继续时，Loop 读取未读 action records，让 LLM 总结状态更新：

- 新增或完成 todo。
- 记录 milestone。
- 整理反馈错误。
- 更新可供下一轮使用的状态快照。

状态更新成功后，Loop 才 ack 本批已读取 action records。若 Step3 失败，未读记录会保留，后续可重新处理或暴露给错误恢复逻辑。

## 控制流

Loop 对 batch control 的处理结果：

- `COMPLETE`：返回 completed。
- `SUSPEND`：记录挂起点并返回 suspended。
- `NEXT_TURN`：进入下一轮。
- `NEXT_STEP`：进入 Step3。
- `ABORT`：返回 aborted。
- `INTERRUPT`：返回 interrupted。

`resume(user_response)` 只在已有挂起点和待回答 inquiry 时有效。恢复时会追加用户 response，并从下一轮继续执行。没有挂起上下文时会返回 aborted，并带有 `ResumeStateError`。

## Ongoing 处理

Ongoing 动作通过信号报告生命周期：

- `ONGOING_STARTED`
- `ONGOING_TICK`
- `ONGOING_COMPLETED`

Loop 在 completed、exhausted、interrupted、aborted 等终态会请求关闭运行中的 ongoing 动作，并短暂 drain 信号；在 suspended 状态不会主动关闭，以便恢复后继续观察。

## 错误处理

Loop 的错误策略是“动作错误结构化、系统错误可中止”：

- 动作失败由 Dispatcher 转成 `ACTION_FAILED`。
- 超时转成 `ACTION_TIMEOUT`。
- 取消转成 `ACTION_CANCELLED`。
- LLM transient 类错误交给 Trap 判断是否反馈或中止。
- `KeyboardInterrupt` 转为 interrupted。

Trap 负责把错误写入 loop error 或反馈错误，Loop 只消费 TrapResult。

## 当前边界

- Step2a 参数生成最多并发 3 个。
- Dispatcher 基于线程池，无法强制杀死已经进入不可中断代码的线程；超时通过 `RunConfig` 和 future cancel 协作完成。
- 多动作批次会过滤普通 next-turn 控制，避免某个动作提前跳过同批其他动作结果。
- 完成或挂起控制会跳过 Step3，这是当前实现特性。
- Loop 不持久化状态；会话恢复依赖同一运行态对象。

## 设计不变式

- Loop 只编排，不实现具体动作业务。
- 每轮先执行动作，再由状态更新统一吸收动作结果。
- 所有跨模块控制都通过 signal 或 TrapResult 表达。
- 用户交互通过 suspend/resume 表达，不在动作里阻塞等待输入。
- 终态必须清理或请求清理 ongoing 动作，挂起态除外。
