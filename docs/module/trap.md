# Trap 模块

## 定位

Trap 模块是 TinySoul 的错误与信号收敛层。它把异常、动作结果和控制信号统一转成 Loop 能理解的 `TrapResult`，并把需要落库的事实交给 `InterruptHandler` 写入上下文状态。

Trap 不选择动作，不调用 LLM，也不直接推进 Loop 轮次。它只回答两个问题：

1. 这件事是否需要写入状态或事件？
2. Loop 下一步应该继续、换轮、挂起、完成、中止还是中断？

## 核心对象

### `Signal`

Signal 是动作执行和 Loop 控制之间的消息格式，包含：

- signal type
- source
- turn
- execution id
- action result
- loop error
- control reason

Signal 分为 data signal 和 control signal。data signal 描述动作事实，control signal 描述流程意图。

### `ErrorTrap`

`ErrorTrap` 处理两类输入：

- `capture(exc)`：捕获异常并生成 `TrapResult`。
- `route(signal)`：路由单个 signal。

它会把已知 `TinysoulError` 映射到明确策略；未知异常通常进入 aborted 路径。`SystemExit` 不被吞掉，`KeyboardInterrupt` 会转成用户中断。

### `InterruptHandler`

`InterruptHandler` 负责副作用：

- 写入 action record。
- 写入 loop error。
- 追加用户 inquiry/append 事件。
- 更新 ongoing action 生命周期。

Trap 决定语义，InterruptHandler 执行落库。这样 Loop 不需要知道每种信号如何写入内部状态。

## 异常分层

异常体系以 `TinysoulError` 为根，核心分组包括：

- LLM：配置、鉴权、瞬时错误、解析错误、系统耗尽。
- Action：动作未找到、输入错误、执行错误、取消、超时。
- State：状态更新、恢复状态、todo 歧义。
- Workspace：路径逃逸、资源不存在、文件访问错误。
- Script/Sandbox：脚本安全、执行失败、沙箱违规。
- FeedbackError：可反馈给下一轮模型的错误。

`FeedbackError` 会尽量绑定 action name 和 input，便于下一轮 Prompt 给模型具体修正信息。

## Signal 路由

单个 signal 的处理方式：

- `ACTION_SUCCEEDED`：写入成功 action record。
- `ACTION_FAILED`：写入失败 action record 和 loop error。
- `ACTION_TIMEOUT`：写入 timeout action record 和 loop error。
- `ACTION_CANCELLED`：写入 cancelled action record 和 loop error。
- `USER_APPEND`：追加到 query events。
- `ONGOING_STARTED`：写入 action record，并登记 ongoing。
- `ONGOING_TICK`：写入 action record。
- `ONGOING_COMPLETED`：写入 action record，并移除 ongoing。
- `LOOP_NEXT_STEP`、`LOOP_NEXT_TURN`、`SUSPEND_LOOP`、`COMPLETE_LOOP`：返回控制结果。

控制信号本身通常不写状态；若它同时携带 action result 或 loop error，InterruptHandler 会处理这些数据部分。

## Batch 处理

`process_signal_batch()` 是 Loop 消费一批信号后的聚合入口。

当前顺序是：

1. 分离 data signal 和 control signal。
2. data signal 逐个 route，确保动作事实先落库。
3. control signal 按优先级聚合。
4. 返回一个 batch 级 `TrapResult`。

控制优先级为：

1. `COMPLETE_LOOP`
2. `SUSPEND_LOOP`
3. `LOOP_NEXT_TURN`
4. `LOOP_NEXT_STEP`

因此，只要批次中存在 `LOOP_NEXT_TURN`，且没有更高优先级控制，batch 结果就是 next-turn。多动作批次中的普通 next-turn 过滤由 `ParallelDispatcher` 完成，不在 Trap 中完成。

## TrapResult

`TrapResult` 是 Loop 消费的统一结果，包含：

- status
- message
- data
- error
- should_continue
- should_abort

Loop 根据 status 决定 outcome 或下一步，而不是检查原始异常类型。

## 与 Loop 的协作

Loop 使用 Trap 的位置：

- `_run_step()` 捕获 Step 异常。
- Step2b 执行动作后处理 signal batch。
- 参数生成或状态更新失败时决定反馈、重试或中止。
- 用户中断时生成 interrupted outcome。

Trap 不主动重跑步骤。重试、下一轮和终止都由 Loop 根据 `TrapResult` 执行。

## 当前边界

- Trap 不保证动作线程停止；停止请求由 Dispatcher 和 `RunConfig` 协作完成。
- control signal 的副作用有限，主要是返回控制状态。
- batch 聚合不会合并多个错误的详细语义；详细错误已作为 data signal 落库。
- LLM transient 错误通常已经由 AIClient 重试和 failover；到达 Trap 时可能直接导致中止。
- `SystemExit` 保持进程级语义，不进入普通错误恢复。

## 设计不变式

- 异常不能直接穿透主循环成为未结构化失败。
- 动作事实先落库，控制决策后聚合。
- Trap 只解释错误和信号，不执行业务动作。
- Loop 只消费 `TrapResult`，不分散处理每种异常细节。
- Ongoing 生命周期必须由 signal 驱动并落到上下文。
