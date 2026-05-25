# Dispatcher 超时与取消语义

## 背景

`ParallelDispatcher` 负责并行动作执行。旧记录中担心 dispatcher 无法真正取消已启动任务。当前源码已经实现 per-run termination token、late-result filtering、子进程终止和 timeout signal，但整体仍是协作式取消模型。

本 todo 的目标不是把 Python 线程强杀，而是把取消语义文档化、测试化，并推动各类 executor 遵守同一运行契约。

## 当前现状

- Dispatcher 为每个动作创建 `RunConfig` 和 `execution_id`。
- batch timeout 后，Dispatcher 会对 pending action 调用 `request_termination(TIMEOUT)`。
- pending future 会被 `cancel()`，并发出 `ACTION_TIMEOUT` signal。
- 子进程类执行器通过 `ManagedProcessRunner` 响应 `RunConfig`，先 terminate，再 kill。
- 临时脚本 sandbox worker 也通过 `ManagedProcessRunner` 控制。
- `OneStepAIExecutor` 会把 action 剩余时间折算到请求级 `ChatConfig.timeout`。
- native action 只能依靠自身主动调用 `run_config.raise_if_terminated()`。
- Dispatcher 过滤已超时 execution 的 late result，避免重复写入 SignalBus。

## 问题

### 1. 已启动线程不能被强杀

Python `ThreadPoolExecutor` 无法停止已经运行的线程。Dispatcher 可以发出终止意图，但如果 native action 不检查 `RunConfig`，该线程仍可能继续执行到自然返回。

### 2. 不同 executor 对取消的响应能力不同

子进程和脚本 worker 可以被终止；同步 LLM 调用只能依赖请求 timeout；native 长任务需要主动检查。

这意味着相同的 action timeout 在不同执行载体上语义并不完全一致。

### 3. Late result 被过滤，但 late side effect 仍可能发生

Dispatcher 可以避免 late result 重复进入 SignalBus，但无法撤销动作已经产生的外部副作用。

## 建议

- 保持当前协作式取消模型，不尝试在 Python 层强杀线程。
- 明确要求长任务型 native action 周期性检查 `RunConfig`。
- 对所有 executor 建立统一取消契约文档和测试。
- 对有副作用动作，在动作实现中先检查终止状态，再执行不可逆副作用。
- 在日志中区分 dispatcher timeout、executor timeout、action cancelled。

## 实施方案

### 阶段 1：补充执行契约

在 Action/Executor 文档中明确：

- action 启动前必须检查 `RunConfig`。
- 长循环必须定期检查。
- 执行不可逆副作用前应再次检查。
- 捕获 timeout/cancel 后不得伪装成成功结果。

### 阶段 2：补充测试

建议增加测试：

- pending future timeout 后只写一次 `ACTION_TIMEOUT`。
- late success 不进入 SignalBus。
- `ManagedProcessRunner` 在 timeout 后 terminate/kill 子进程。
- native action 不检查 `RunConfig` 时的行为被文档化，而不是误判为 bug。

### 阶段 3：增强可观测性

在日志和 action record 中区分：

- `dispatch_timeout`
- `executor_timeout`
- `user_cancel`
- `shutdown`

这样后续分析问题时能看清是 batch 层超时，还是执行器内部超时。

### 阶段 4：评估进程化 native action

如果未来需要真正硬中断长任务，可以为高风险 native action 提供进程化执行器，而不是依赖线程池。

## 验收标准

- 文档明确说明 dispatcher cancel 是协作式取消。
- 子进程、脚本、LLM、native action 的取消边界分别有测试或文档覆盖。
- timeout 后 late result 不会产生重复 action record。
- 有副作用动作在不可逆操作前检查 `RunConfig`。
- 日志或状态能区分 timeout/cancel/shutdown。

## 设计原则

- Dispatcher 负责发出终止意图和过滤结果，不承诺强杀线程。
- Executor 负责按自身执行载体实现停止。
- 副作用动作必须以保守方式处理 timeout 和 cancel。
