# SubprocessExecutor 进程执行模型

## 背景

旧记录只写了 “cli and bash / 进程模型”。当前源码已经实现 `ManagedProcessRunner`、`SubprocessExecutor`、`CLIExecutor` 和 `BashExecutor`。因此本 todo 不再描述“需要创建基础执行器”，而是整理当前模型的剩余改进方向。

## 当前现状

- `ManagedProcessRunner` 使用 `subprocess.Popen` 启动进程。
- `RunConfig` 控制 timeout、cancel 和 shutdown。
- timeout/cancel 时先 `terminate()`，再 `kill()`。
- stdout/stderr 会被收集。
- 非零 exit code 转为 `ActionExecutionError`。
- stdout 若是 JSON object，直接作为 dict 返回；非 object JSON 包装为 `{"result": ...}`；非 JSON 文本包装为 `{"output": ...}`。
- `CLIExecutor` 通过固定命令模板和 `_build_cmd()` 映射 action input。
- `BashExecutor` 支持任意 bash 脚本，但没有注册为默认 action。

## 问题

### 1. BashExecutor 风险高

`BashExecutor` 是任意 shell 执行能力。虽然有基础黑名单，但这不是安全沙箱。当前未注册默认 bash action 是合理选择。

### 2. CLI context 传递较粗

`CLIExecutor` 通过环境变量传递 query events、loop target、current turn。复杂上下文没有结构化传入，适合普通 CLI，不适合需要完整 TinySoul 上下文的子进程任务。

### 3. 输出协议需要更稳定

当前 stdout 自动 JSON 解析足够灵活，但对长期维护来说，需要明确哪些 action 应返回 JSON object，哪些可以返回纯文本。

### 4. 与 ONGOING 的关系尚未标准化

SubprocessExecutor 当前主要是 bounded run。若要支持长期 CLI/daemon 类任务，需要与 ONGOING control、heartbeat 和 shutdown 协议结合。

## 建议

- 继续保持 BashExecutor 不进入默认 action registry。
- CLI 类 action 优先使用固定命令和 argv list，不通过 shell。
- 明确 stdout JSON object 是推荐协议。
- 为需要完整上下文的子进程任务，使用 stdin JSON 或临时 payload，而不是塞环境变量。
- 将长期子进程任务纳入 ONGOING executor 设计，而不是复用 bounded CLIExecutor。

## 实施方案

### 阶段 1：文档化子进程协议

说明：

- stdin 输入协议。
- stdout 输出协议。
- stderr 和 exit code 语义。
- timeout/cancel/shutdown 行为。
- 不同 executor 的适用场景。

### 阶段 2：增强测试

建议测试：

- JSON object 输出。
- JSON list/string 输出包装。
- 非 JSON 输出包装。
- 非零 exit code。
- timeout terminate/kill。
- cancel 转成 `ActionCancelledError`。

### 阶段 3：收紧 Bash 使用策略

如果未来注册 bash action，需要同时实现：

- 明确 allowlist。
- destructive confirmation。
- workspace cwd 限制。
- 更强沙箱或低权限进程。
- 用户确认策略。

### 阶段 4：设计 ongoing subprocess executor

为长期子进程任务增加：

- process handle control。
- stdout/stderr streaming to tick。
- heartbeat。
- shutdown callback。
- completed signal。

## 验收标准

- 子进程输出协议有文档和测试覆盖。
- BashExecutor 不会被默认注册为可选动作。
- CLI action 不通过 shell 拼接命令。
- timeout/cancel 行为与 Dispatcher 文档一致。
- 长期子进程任务有独立 ONGOING 方案，不混入 bounded executor。

## 设计原则

- CLI 执行默认走 argv list，不走 shell。
- 子进程是强于线程的取消边界，但不是安全沙箱。
- Bash 能力必须显式启用，并受更严格策略约束。
