当前实现采用 per-run termination token，而不是 Dispatcher 强杀 executor。

核心边界：

- `ParallelDispatcher` 负责判定 batch timeout，并对对应 `RunConfig` 发出 `request_termination(TerminationReason.TIMEOUT)`。
- `Executor` 负责按自身执行载体实现停止。
- `ParallelDispatcher` 仍保留 late-result filtering，避免 timeout 后后台解包出的晚到结果被重复记录。

`RunConfig` 是一次 action execution 的运行控制对象：

```python
@dataclass
class RunConfig:
    action_name: str = ""
    turn: int = 0
    execution_id: str = ""
    timeout: float | None = None
    deadline: float | None = None
    terminate_event: threading.Event = field(default_factory=threading.Event)
    termination_reason: TerminationReason | None = None
    llm_timeout: float | None = None
    api_timeout: float | None = None
```

语义：

- `timeout/deadline` 控制本次 action execution。
- `terminate_event` 表示外部已经要求这次 execution 终止。
- `termination_reason` 区分 `TIMEOUT`、`USER_CANCEL`、`SHUTDOWN`。
- `raise_if_terminated()` 将 timeout 映射为 `ActionTimeoutError`，其他终止映射为 `ActionCancelledError`。

各 executor 的当前边界：

- `SubprocessExecutor`：通过 `ManagedProcessRunner` 启动子进程，轮询 `RunConfig`，超时或终止时先 `terminate()`，再 `kill()`。
- `TemporaryScriptExecutor`：保留脚本 sandbox 的 AST 校验、IPC 和 workspace 边界；worker 子进程同样交给 `ManagedProcessRunner` 控制，避免脚本超时后后台残留。
- `OneStepAIExecutor`：同步 LLM 调用无法被强杀，只在调用前后检查 `RunConfig`，并把 action 剩余时间折算进请求级 `ChatConfig.timeout`。
- native action：短任务调用 `raise_if_terminated()` 即可；长循环型 native action 应在循环中主动检查。
- `ONGOING` action：`RunConfig.timeout` 只控制启动阶段。启动成功返回 `ONGOING_STARTED` 后，后台生命周期不再受启动 `RunConfig` 影响，后续应由独立 ongoing 管理机制控制。

timeout 默认推导：

- 显式 `ActionRuntimeConfig.timeout` 绝对优先，不根据依赖放大。
- 未显式配置时，先取 cluster 默认值：`NATIVE/action_timeout`、`CLI/cli_timeout`、`SCRIPT/script_timeout`。
- 如果 action 声明 `llm_dependency != NONE`，默认 action timeout 至少为 `llm_timeout + action_llm_overhead`。
- `api_dependency` 作为 runtime-only 配置预留，同理可用 `api_timeout + action_api_overhead` 放大默认 action timeout；暂不暴露到 LLM metadata/detail。
