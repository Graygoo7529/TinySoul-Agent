# context 与 loop 模块设计草案（2026-07-06，已按维护者决策修订）

基于最新 AGENT.md 核心定义、项目规约与四个已完成模块（infra/runtime/llm/action）的实际接口，规划 context 与 loop 两个模块。本文是讨论稿；确认后拆分为 docs/design/context.md 与 docs/design/loop.md 并实现。

## 零、已确认决策（2026-07-06 与维护者确认）

1. 推进顺序：context 先行，完成后 loop + app 一起落地。
2. Turn 结束语义：以 `core.answer` action 执行成功为准（cycle 上限仅作兜底保护）。
3. Phase1 职责：选择 domain 为**必选**输出，整理语境（working/background 控制调用）为**可选**输出；不存在"不选 domain 直接收束"的路径。
4. 语境压缩：处理**流程**走完整规范链路（模块失败 → bridge → Runtime 原因 → Trap 处理器 → 恢复例程 → retry 转移），仅处理**策略**轻量化（trace 旧条目裁剪 + 摘要占位）。
5. 持久化：本期 context 为内存态语境 + `TurnSummary`；持久化随 workspace/home 读写机制接入，不预留空接口。
6. 追加输入：支持用户轮执行中的追加输入；由输入线程采集，语境模块维护用户输入列表，通过信号在安全边界合并或追加最新输入。

## 一、模块定位与边界

**context**：语境模块。持有三段语境状态（BackgroundContext、TurnTraceContext、WorkingContext）与本轮用户输入列表，负责"构造式" MessageStack 的组装、语境类 Control Tools 的定义与归一化、语境状态信号的事务式消费，以及语境压缩服务。context 不调用 LLM，不执行 action，不驱动控制流。

**loop**：编排模块。实现 Program/Turn/Cycle/Phase 四级运行器与输入监听线程，驱动 Phase1→2→3 执行单元；每个 Phase 是"从 context 取语境 + 从 action 取工具作用域 + 调 llm task + 解释结果 + 发信号"的组合点。loop 是整个程序的装配入口，消费 Trap 返回的运行转移。

与既有模块的分工不变：llm 只管模型调用，action 只管行动语义与执行，runtime 只管控制流协议，infra 只管基础设施。

## 二、context 模块

### 2.1 目录组织

```text
tinysoul/context/
  __init__.py        # 导出公共类型与 ContextEngine
  failures.py        # 服务于 Runtime bridge 的稳定失败枚举（含 BUDGET_EXCEEDED）
  errors.py          # ContextContractError / ContextInvariantError
  background.py      # BackgroundContext：顶层内容条目、加载/逐出
  working.py         # WorkingContext：workspace 摘要、Milestone、Todo
  trace.py           # TurnTraceContext：行动轨迹 + PendingInputs（用户输入列表）
  prompts.py         # TaskPrompt（task_guide/task_input/task_output_desc）与渲染
  controls.py        # 语境 Control Tools 定义 + Control Tool Calls 归一化为信号
  composer.py        # MessageStackComposer：按区段构造 MessageStack + 预算检查
  compress.py        # ContextCompressor：轻量压缩策略（供 Trap 恢复例程调用）
  engine.py          # ContextEngine / ContextEngineBuilder 组装门面
```

（`prompts.py` 可并入 `composer.py`、`compress.py` 可并入 `trace.py`，实现时按体量取舍。）

### 2.2 状态模型（核心类）

- `BackgroundEntry`（frozen）：一条顶层内容。字段含链接标识（如 `home:what@xxx`）、渲染文本、加载来源（默认加载 / Phase1 加载）。
- `BackgroundContext`：顶层内容有序集合 + 当日会话历程摘要。方法：`load(entry)`、`evict(link)`、`entries()`、`render_messages()`。
- `Milestone` / `TodoItem`（frozen，StrEnum 状态）：WorkingContext 的寄存器与待办。
- `WorkingContext`：workspace 资源描述（链接+摘要清单）、milestones、todos。方法：`apply_patch(patch)`、`render_messages()`；patch 为明确类型（`WorkingPatch`，由信号载荷解析而来）。
- `TraceEntry`（frozen）：一条轨迹记录，直接持有 llm `Message`（AssistantMessage 含 tool_calls / ToolResultMessage / 追加输入形成的 UserMessage）加上结构化元数据（cycle_id、phase、来源）。
- `TurnTraceContext`：append-only 轨迹序列。方法：`append_decision(...)`、`append_action_results(...)`（接收 ActionFeedbackRenderer 产出的 ToolResultMessage）、`append_phase_note(...)`、`append_user_input(...)`、`render_messages()`；压缩服务可对旧条目执行裁剪与摘要占位替换（见 2.6）。
- `PendingInputs`：本轮用户输入列表（初始输入 + 轮中追加输入），条目 frozen（文本、接收时间、是否已合并）。追加输入先入列表，在安全边界由 loop 触发合并：合并时转为 `TraceEntry`（UserMessage）进入轨迹，条目标记已合并。列表本身保留全量记录，进入 `TurnSummary`。

三段语境与输入列表均为 turn 内可变持有者（内部 frozen 条目 + 受控变更方法），变更入口只有两类：信号消费与 turn 生命周期方法（`begin_turn`/`end_turn`）。

### 2.3 MessageStack 构造（composer）

`MessageStackComposer.compose(phase, task_prompt) -> MessageStack`，区段顺序服务提示缓存稳定前缀：

1. system：Agent 身份与规约（最稳定）；
2. BackgroundContext 渲染段（turn 内基本稳定）；
3. WorkingContext 渲染段（低频变化）；
4. TurnTraceContext 渲染段（turn 内 append-only：用户输入、Phase2 的 assistant tool_calls、Phase3 的 ToolResultMessage 按序回放）；
5. task prompt overlay（每次 LLM Task 不同，含 `TaskPrompt(guide, input, output_desc)` 渲染 + Phase2/Phase3 的 domain HOW 引导文本）。

composer 在 compose 时执行预算检查（按字符量估算，阈值可配置）；超限时抛 `ContextBudgetError`（模块边界异常），由 context bridge 映射为 `CONTEXT_COMPRESSION_REQUIRED` 的 Runtime 语义异常（见 2.6）。

`TaskPrompt` 是 frozen dataclass；Phase2 overlay 的构造接受 `domain_guidance: tuple[str, ...]`（真实功能：拼入 overlay），内容来源在 Agent Home 机制落地前为空，落地后由 home 模块按已选 domain 提供（对应 how_action/domain_name/DOMAIN.md）。

### 2.4 语境 Control Tools 与信号（controls）

context 提供 Phase1 语境控制工具（可选输出，与 action 的必选域选择工具并列进入 Phase1 tool scope）：

- `update_working`：更新 milestone/todo（结构化参数）；
- `load_background` / `evict_background`：按链接加载或逐出顶层内容。

`ContextControlScopeBuilder.build() -> ToolScope`（tools 标记 `ToolKind.CONTROL`）。
`ControlCallNormalizer.normalize(tool_calls) -> ControlNormalization`：把模型返回的 Control Tool Calls 校验、归一化为**信号**（不直接改状态），无法归一化的产出局部结果（模式对齐 action 的 `ActionCallNormalizer`）。

信号协议（名称按消费方 context 命名空间组织）：

- `context.working.patch`：WorkingContext 变更请求（生产：Phase1 归一化）；
- `context.background.patch`：Background 加载/逐出请求（生产：Phase1 归一化）；
- `context.trace.append`：轨迹追加请求（生产：Phase2/Phase3，载荷为渲染后的消息投影与元数据）；
- `context.input.append`：用户追加输入（生产：loop 输入监听线程，载荷为输入文本与时间戳）。

`ContextEngine.consume_signals(bus)` 事务式消费：先校验全部载荷、再提交状态；载荷不合规转局部结果（`ControlResult`）反馈模型或记录 trace，不抛异常。

### 2.5 组装门面与失败语义

`ContextEngine`（组装门面）：`begin_turn(user_input)`、`compose(phase, task_prompt)`、`control_scope()`、`normalize_controls(tool_calls)`、`consume_signals(bus)`、`merge_pending_inputs()`（安全边界合并追加输入，返回本次合并条数供 loop 观测）、`compressor()`（供 Trap 恢复例程使用）、`end_turn() -> TurnSummary`。`ContextEngineBuilder` 负责装配（身份 system 文本、默认 background 来源、预算阈值等配置）。

失败三层：模型控制调用不合规 → 局部结果（`ControlResult`，模式同 ActionResult）；契约/不变量/预算超限 → `ContextContractError`/`ContextInvariantError`/`ContextBudgetError`；跨边界 → `failures.py` 枚举（含 `BUDGET_EXCEEDED`）+ `runtime/bridge/context.py` 映射（配置失败→启动失败，`BUDGET_EXCEEDED`→`CONTEXT_COMPRESSION_REQUIRED`，其余默认结束 Turn）。

### 2.6 语境压缩（规范流程 + 轻量策略）

流程完全走规范链路，与其他 Runtime 恢复例程同构：

1. composer 预算检查失败 → `ContextBudgetError` → context bridge → `RuntimeException(CONTEXT_COMPRESSION_REQUIRED)`；
2. loop 的 Phase 边界捕获并交 `RuntimeTrap.handle`，按原因查到压缩处理器；
3. 压缩处理器（app 装配时注册）调用 `ContextCompressor.compress()`：**策略轻量化**——按预算裁剪 TurnTrace 旧条目，以摘要占位条目替换（占位记录被裁剪的条目数与关键动作名），Background/Working 不动；
4. 处理器发出 trace 记录信号（压缩事件可观测），返回 `RuntimeTransfer.retry(当前 Phase frame)`；
5. Phase 重放，composer 在压缩后的语境上重新构造。

压缩失败（裁剪后仍超限）由处理器返回结束 Turn 转移。后续迭代可将策略升级为 LLM 归纳压缩，流程不变。

### 2.7 持久化边界（本期取舍）

本期 context 为内存态语境 + 渲染；`end_turn()` 产出可 JSON 化的 `TurnSummary`（含 PendingInputs 全量记录、milestone/todo 终态、trace 摘要）作为未来持久化与当日会话历程的数据源。持久化同步在 workspace/home 机制落地时接入。

## 三、loop 模块

### 3.1 目录组织

```text
tinysoul/loop/
  __init__.py        # 导出 TinySoulApp / 运行器
  failures.py        # loop 稳定失败枚举
  errors.py          # LoopContractError / LoopInvariantError
  inputs.py          # InputListener：输入监听线程 + 输入分类
  phases.py          # Phase1Unit / Phase2Unit / Phase3Unit 执行单元
  cycle.py           # CycleRunner：一次执行轮
  turn.py            # TurnRunner：User Turn（追加输入合并、turn 结束判定）
  program.py         # ProgramRunner：顶层循环（输入等待、指令分发）
  app.py             # TinySoulApp / TinySoulAppBuilder：全局装配入口
```

### 3.2 输入监听（inputs）

`InputListener` 是常驻 daemon 线程，持续读取 stdin 行输入并分类：

- **控制指令**（如 `exit`，词表可配置）：发出 `loop.control.request` 信号（载荷：`stop_turn` / `exit_program`）。信号不直接改变控制流；TurnRunner/ProgramRunner 在 Phase/Cycle 边界检查该信号，由运行器构造对应 Runtime 语义异常进入 Trap（`RUNTIME_TURN_END` / `RUNTIME_PROGRAM_END`），符合"控制流变化统一经 Trap"的规约；
- **普通内容**：Turn 执行中发出 `context.input.append` 信号（追加输入）；无 Turn 运行时投递给 ProgramRunner 作为新 Turn 的初始输入。

线程安全依赖 SignalBus 的线程安全发出/消费能力（runtime 既有设计）。InputListener 不解析业务语义，只做分类与投递。

### 3.3 Phase 执行单元（phases）

每个 Phase Unit 输入统一为 `(context: ContextEngine, action: ActionEngine, llm: LLMTaskRunner, bus: SignalBus, scope: RunScope)`，输出为明确的 Phase 产物类型。

**Phase1Unit** → `Phase1Outcome(selected_domains, local_results)`

1. `tool_scope = merge(context.control_scope(), action.phase1_scope())`（ToolScope 合并函数建议放 llm.tools）；域选择必选、语境整理可选，通过 TinySoul 强制工具选择语义表达：`ToolUse.REQUIRED` + `forced_name="select_action_domains"`（llm 任务解释层已支持：结果必须包含该工具调用，允许同时包含其他工具调用）；
2. `stack = context.compose(PHASE1, phase1_task_prompt(action.phase1_domain_prompt()))`；
3. `llm.run(TaskCall(profile=FRAMEWORK, messages=stack, tool_scope, settings))`；
4. TaskFailure（含缺失必选域选择调用）→ 局部结果反馈进下一次尝试（有限次），耗尽后按 llm/loop 失败边界处理；
5. 汇聚 Control Tool Calls：语境类交 `context.normalize_controls` 产信号；域选择调用解析为 `selected_domains`（校验 domain 存在性，非法值转局部反馈重试）；Phase1 结束统一 `context.consume_signals(bus)`。

**Phase2Unit** → `Phase2Outcome(calls, results)`

1. `preparation = action.phase2_scope(selected_domains)`；scope 失败 → phase result 记入 trace，结束本 cycle；
2. `stack = context.compose(PHASE2, phase2_task_prompt(domain_guidance))`；
3. LLM 调用（tool_use=REQUIRED）→ `action.normalize(tool_calls)`；
4. assistant tool_calls 与归一化失败的局部结果记入 trace（`context.trace.append` 信号，Phase2 末消费）。

**Phase3Unit** → `Phase3Outcome(results, answered)`

1. `action.prepare_batch(calls, scope=scope)` → `action.run_batch(batch)`；
2. `merged = normalization.merged_results(execution_results)`；
3. renderer 产出 ToolResultMessage / trace payload → 发 `context.trace.append` 信号，Phase3 末统一消费；
4. `answered`：`core.answer` 存在成功结果时为真（Turn 结束条件的数据源）。

### 3.4 Turn 与 Cycle 运行器

- `CycleRunner.run(cycle_id) -> CycleOutcome`：顺序执行三个 Phase Unit；每个 Phase 边界执行两项检查：（a）`loop.control.request` 信号 → 构造 Runtime 异常进 Trap；（b）`context.input.append` 信号存在 → `context.merge_pending_inputs()`（追加输入即刻可见于下一次 compose）。
- `TurnRunner.run(user_input) -> TurnOutcome`：`context.begin_turn` → 循环 cycle 直到（a）`Phase3Outcome.answered` 为真；（b）cycle 数达配置上限（兜底保护，结束前记录警告 trace）；（c）Trap 返回结束 Turn 转移。结束时 `context.end_turn()` 并返回 `TurnOutcome(summary)`。
- `ProgramRunner.run()`：启动 InputListener → 循环取初始输入派发 TurnRunner；`exit_program` 控制请求或 Trap 结束 Program 转移时退出；预留每日沉淀等同层指令的分发位（实现随每日任务模块）。

### 3.5 Trap 与运行转移消费

各级运行器在自己的 frame 边界捕获 `RuntimeException` → `trap.handle(exc, scope)` → `RuntimeTransfer`：

- transfer 目标是本级 frame：`END` 正常收束本级并返回；`RETRY` 重放本级（语境保持已提交状态）；
- 目标是上级 frame：向上传播。

Trap 处理器注册在 app 装配阶段完成：`RUNTIME_TURN_END` / `RUNTIME_CYCLE_END` / `RUNTIME_PROGRAM_END` / `RUNTIME_STARTUP_FAILED` 用通用处理器；`CONTEXT_COMPRESSION_REQUIRED` 注册压缩处理器（见 2.6）；`HOME_RUNTIME_COPY_REQUIRED` 留待 home 机制。

### 3.6 装配入口（app）

`TinySoulAppBuilder`：加载配置（infra ConfigEnvironment）→ 构建 `LLMTaskRunner`、`ActionEngineBuilder`（注册 native handlers：`core.answer`、`workspace.scan`）、`ContextEngineBuilder` → 注册 Trap 处理器与信号处理器 → 组装 InputListener 与各级运行器 → `TinySoulApp(program_runner)`。`TinySoulApp.run()` 是进程入口。

挂起接口在此定型：

- **hook/executor 服务上下文**：`ActionExecutionContext.signal_bus` 由 app 注入；业务服务（workspace 句柄等）等 workspace 机制落地后作为明确类型加入，不先放宽泛 services；
- **llm_step 后端**：app 持有 `LLMTaskRunner`，实现 `LLMStepActionExecutor(llm_runner)` 注册为 executor（可与 loop 同期或紧随其后实现）；
- **how_action（domain 级 HOW）**：注入点在 Phase2 task prompt overlay 的 `domain_guidance` 参数（见 2.3），内容来源等 Agent Home 机制。

## 四、与现有模块协同总览

- context → llm：只产出/消费 `MessageStack`、`Message`、`ToolScope`、`ToolCallRecord` 等 llm 公共类型，不触碰 provider 层；
- loop → llm：构造 `TaskCall` 并处理 `TaskResult`/`TaskFailure` 两态，TaskFailure 走局部反馈重试；
- loop → action：只经 `ActionEngine` 门面五个方法；
- context/loop → runtime：信号经 `SignalBus`，控制流经 `RuntimeException` + `RuntimeTrap`，两模块各自新增 `runtime/bridge/context.py`、`runtime/bridge/loop.py`（映射表模式同现有 bridge）；
- 观测：本期沿用信号（trace 类信号可被未来可观测性模块消费），不实现三级终端渲染。

## 五、实现顺序与遗留小项

实现顺序（决策 1）：

1. context 模块（状态模型 → controls/composer → engine → 压缩 → bridge → 测试）；
2. docs/design/context.md 定稿；
3. loop 模块（inputs → phases → cycle/turn/program → app → bridge → 测试）+ docs/design/loop.md；
4. llm_step executor 接入（依赖 app 持有的 LLMTaskRunner）。

遗留小项（实现期决定，不阻塞设计）：

- cycle 上限、语境预算阈值的默认值与配置键；
- 控制指令词表（`exit` 之外是否需要 `stop` 中断当前 Turn 而不退出程序）；
- Phase1 局部反馈重试次数的默认值（与 llm 任务配置的关系）。
