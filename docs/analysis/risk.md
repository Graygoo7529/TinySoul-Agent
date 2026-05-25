# 当前风险分析

## 背景

旧版风险记录中有些问题已经被实现修复，有些已经从“缺失能力”变成“剩余边界”，也有少数仍然成立。本文件按当前源码重新归档，作为 `docs/todo/*` 的上层索引。

## 已解决或已过期的问题

- 真实 LLM 调用丢失 system prompt：已修复。OpenAI-compatible adapter 会把 `request.system` 拼入 messages。
- `ActionRegistry.with_allowlist()` 丢失注入环境能力：已修复。allowlist view 共享 `_env_caps`。
- action record 丢失 `action_target`：已修复。InterruptHandler 会从 signal payload 读取 target。
- README 文档索引漂移：当前 README 已移除私有设计草案入口，并指向公开模块文档、分析文档和 todo 文档。
- SubprocessExecutor 只有设想：已实现。当前已有 `ManagedProcessRunner`、`SubprocessExecutor`、`CLIExecutor`、`BashExecutor`。
- ONGOING 完全缺失：已实现基础链路。当前有 `ActionMode.ONGOING`、ongoing signal、control registry、`monitor` 示例和 `stop_ongoing_action`。

## 当前主要风险

### 1. Sandbox 是 best-effort，不是强隔离

当前脚本执行有 AST 校验、受限 builtins、import 白名单、workspace 路径包装和 worker 子进程。但它仍不是 OS 级隔离：

- 没有 syscall、network、进程权限或容器级限制。
- worker 内会 `os.chdir()` 到 workspace，这是进程级全局状态。
- `pathlib` 等标准库能力可能绕过部分 Python 层代理。
- sandbox 路径校验使用字符串前缀判断，建议改为 `Path.relative_to()`。

这不是普通测试问题，而是安全边界问题。应在文档和 allowlist 策略中持续保持明确。

### 2. Destructive action 缺少框架级确认策略

`delete_file` 的 metadata 标记了 `DESTRUCTIVE`，但当前框架不会强制用户确认。模型可以通过 allowlist 直接选择该动作。

现有 `ask_user` 可以表达“需要确认”，但这是 prompt/模型层约束，不是运行时强制。

### 3. Git action 的 path 没有绑定 workspace 边界

Git action 白名单了 read-only subcommands，也用 argv list 避免 shell injection。但 `git -C path` 的 `path` 当前来自 action input，没有通过 `Workspace.resolve_access()` 约束。

这意味着当 `git` action 可用时，它可能读取工作区外 repo 的状态、日志或 diff。虽然动作是 read-only，仍属于工作区边界风险。

### 4. 并行动作超时仍是协作式

Dispatcher 会给 pending action 发出 termination token、cancel future，并过滤 late result。对于子进程和临时脚本，`ManagedProcessRunner` 可以 terminate/kill 子进程。

剩余风险在于：

- 已启动的 Python 线程不能被强杀。
- native 长任务必须主动检查 `RunConfig`。
- 同步 LLM 调用只能设置请求 timeout，无法从 Python 侧硬中断供应商调用。
- late result 不会重复入 SignalBus，但后台代码仍可能执行到自然返回。

### 5. ONGOING 生命周期仍是内存级、示例级

当前 ONGOING 已有基础链路，但仍缺少生产级生命周期能力：

- 无持久化。
- 无健康检查。
- 无最大运行时策略。
- 无统一 heartbeat/last_tick。
- shutdown drain 时间较短，无法保证所有后台动作完成清理。
- 当前 `monitor` 更像示例动作，不代表所有长期任务的标准实现。

### 6. Step context 裁剪未接入

`PromptBuilder.include_context` 已经具备字段筛选能力，但 Loop Step 仍使用默认完整上下文。长任务下 token 成本和无关信息干扰会增加。

### 7. 类型边界仍偏动态

项目保留 JSON-like 数据是合理的，但 Step 输出、signal payload、provider content part、current state view 等高频边界缺少统一类型定义。扩展动作和 provider 时容易产生隐式字段漂移。

### 8. QueryState 线程安全依赖当前写入模型

当前主路径基本由 Loop 消费 signal 后写状态，状态管理器未设计为可被多线程直接写入。若未来让后台 ongoing action 直接写 state，或多个 Loop 共享同一 state，需要补锁或建立单写者模型。

## 建议优先级

1. 对 destructive action 增加框架级确认/策略拦截。
2. 将 git path 约束到 workspace 或显式允许的 repo root。
3. 接入 Step prompt context 裁剪，降低 token 成本。
4. 继续收紧 sandbox 边界，至少修正路径校验并记录绕过风险。
5. 完善 ONGOING 生命周期：TTL、heartbeat、健康检查、终态清理。
6. 梳理类型边界和 ActionHandler 协议。
7. 对多模态 attachment 做清晰类型化，避免静默降级。

## Todo 承接

- `docs/todo/Destructive-action-confirmation.md`
- `docs/todo/Git-workspace-boundary.md`
- `docs/todo/Prompt-context-trimming.md`
- `docs/todo/Sandbox-isolation.md`
- `docs/todo/On-going-action.md`
- `docs/todo/Dispatcher-cancel.md`
- `docs/todo/SubprocessExecutor.md`
- `docs/todo/TypedDict.md`
- `docs/todo/AITask-multimodal.md`

## 设计原则

- 风险文档描述当前事实，不把未来目标写成已实现能力。
- `docs/todo/*` 承接可执行改进项，必须包含实施方案和验收标准。
- 对安全边界保持保守表述：best-effort 就写 best-effort。
- 对已修复问题显式归档，避免旧风险重复误导后续设计。
