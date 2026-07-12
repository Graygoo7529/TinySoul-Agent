# Loop 设计

## 定位

Loop 模块负责 TinySoul 的运行编排：Program/Turn/Cycle/Phase 各级运行器，以及 Runtime 运行转移的消费。

Loop 不维护语境状态，不定义行动语义，不做模型供应商适配，也不直接处理外部输入源或进程装配。它把 context、action、llm 三个模块在每个 Phase 组合起来，并消费 runtime 的信号与运行转移协议。进程装配、输入源、输入命令解析和外部接口适配由 app 模块负责。

## 设计目标

1. 运行层级与 Runtime 的运行位置模型一一对应：Program、Turn、Cycle、Phase 各有运行器或执行单元，各自消费指向本级 frame 的运行转移。
2. Phase 执行单元只做组合：取语境、取工具作用域、调 LLM Task、解释结果、发信号；不复制任何模块的内部逻辑。
3. 控制流变化统一经 Runtime 语义异常进入 Trap；外部输入与模块事件统一经信号，在明确边界消费。
4. 用户轮执行中可以接收由 app 层分发而来的追加输入与控制指令，两者路径分离。
5. Turn 结束语义唯一：以 `core.answer` 行动执行成功为准。

## 目录组织

Loop 模块按运行职责拆分：

```text
tinysoul/loop/
  config.py          # LoopSettings 与配置解析
  errors.py          # loop 契约与不变量错误
  failures.py        # loop Runtime bridge 失败枚举
  signals.py         # loop.control.request 信号协议
  prompts.py         # Phase 任务提示构造与 domain HOW provider
  preparation.py     # 首个 Cycle 前的 Turn preparation pipeline
  completion.py      # Turn 完成后的持久化/后处理 pipeline
  pressure.py        # Context 与 Workspace 的压力恢复协调
  phases.py          # Phase1/Phase2/Phase3 执行单元
  cycle.py           # CycleRunner
  turn.py            # TurnRunner
  program.py         # ProgramRunner
  trap_handlers.py   # 通用结束与语境压缩 Trap handler
```

Runtime bridge 独立放在 `tinysoul/runtime/bridge/loop.py`，使 loop 自身的跨边界失败仍通过统一 Runtime 原因进入 Trap。`tinysoul/loop/__init__.py` 使用轻量导出与延迟加载，避免运行器、Phase 单元和 runtime bridge 之间形成导入环。

## 运行层级与运行器

ProgramRunner 是顶层运行循环：等待已经由 app 层解析完成的 `ProgramInputEvent`，把 `start_turn` 事件派发为 User Turn，把 `exit_program` 事件转换为 Runtime Program end。ProgramRunner 不解析原始字符串命令，也不直接接入终端、HTTP 或其他外部输入源。ProgramOutcome 只按 `app.retained_turn_outcomes` 保留最近若干 TurnOutcome，同时单独累计总 Turn 数；这只限制进程返回对象的内存，不影响 Session 对全部已提交 Turn 的持久化。

TurnRunner 驱动一次 User Turn：开始时初始化语境并以锁保护唯一 active Turn scope，循环执行 Cycle，结束时收取 TurnSummary。`core.answer` 成功不会直接设置 answered 布尔，而是由 Phase3 抛出 `runtime.turn_output`；TurnOutput Trap 校验输出、发出 `loop.turn.output` 并返回结束当前 Turn。TurnRunner 只接受本 Turn 的唯一输出信号，并把对应 END 识别为正常完成。Context 结束后，`TurnCompletionPipeline` 按注册顺序接收包含完整 JSON trace/heap 元数据的 TurnSummary 与最终 TurnOutput。默认首个处理器把 Turn 持久化到 Session，之后才运行应用追加的 completion handlers；处理器 RuntimeException 仍在原 Turn scope 内进入 Trap。只有 completion pipeline 全部成功后才发布 normal 级 `turn.output` ObservationEvent，确保外部看到的最终回答已经通过提交边界。执行轮数上限只作为无输出时的兜底保护。

Turn scope 建立后、首个 Cycle 开始前，TurnRunner 运行 `TurnPreparationPipeline` 并批量提交处理器产生的 Context signals。默认顺序是 Session 先投影当日跨 Turn 历史，Workspace 再完成磁盘 reconciliation 和 Manifest 摘要投影；Context 只在这个窗口接受 `context.session.sync`。属于本次 preparation 的信号若被拒绝，按 Loop 装配不变量失败结束当前流程，不能在缺失初始状态时进入 Phase1。

CycleRunner 驱动一次执行轮，顺序执行 Phase1、Phase2、Phase3 三个执行单元。每个 Phase 边界执行两项检查：控制请求信号存在时构造 Runtime 语义异常进入 Trap；追加输入信号存在时触发语境的输入合并，使追加输入在下一次 MessageStack 构造中可见。

各级运行器在自己的 frame 边界捕获 Runtime 语义异常，交 Trap 处理并消费运行转移：转移目标是本级 frame 时，结束转移正常收束本级、重试转移重放本级（语境保持已提交状态）；目标是上级 frame 时以运行结果向上传播。重试语义要求各级边界可重放，这由"语境变更只在信号消费点提交"保证。

## 输入边界

外部输入源、输入命令解析和输入分发由 app 模块负责。Loop 只消费两类已经进入内部边界的输入结果：

- Program 级 `ProgramInputEvent`：进入 ProgramRunner 的输入队列，用于启动 Turn 或结束 Program；
- Turn 执行中的内部信号：`loop.control.request` 表示结束 Turn 或结束 Program 的控制请求，`context.input.append` 表示追加用户输入。

控制请求信号本身不改变控制流；运行器在 Phase 或 Cycle 边界只接受 Turn frame 与当前 Turn 完全相同的请求，再构造对应 Runtime 语义异常进入 Trap。无 Turn scope 或旧 Turn 请求会被拒绝，不能中断后续 Turn。普通追加输入同样携带 active Turn scope，由 ContextEngine 校验后在明确边界合并。

Loop 只消费精确的 `loop.control.request` 信号，不按 `loop.` namespace 批量消费。未来若增加 `loop.observation`、`loop.metrics` 或其他 loop 命名空间信号，应由各自消费者处理；控制请求消费者不得因为命名空间相同而移除未知信号。

## Phase 执行单元

三个 Phase 执行单元的输入统一为 context 门面、action 门面、LLM 任务运行器、信号总线与当前运行位置；输出为各自的明确产物类型（Phase1Outcome、Phase2Outcome、Phase3Outcome）。

### Phase1：更新语境与决策行动域

Phase1 的工具作用域由 context 的语境控制工具与 action 的域选择工具合并而成。域选择是必选输出，语境整理是可选输出；这通过 TinySoul 的强制工具选择语义表达——工具使用策略要求工具调用，且结果必须包含域选择调用，同时允许包含其他控制调用。

Phase1 的 LLM Task 使用 `framework` profile，并在单次 TaskCall 中显式覆盖为工具必选调用。模型返回后：语境类控制调用交 context 归一化为状态信号；域选择调用解析为已选 domain 集合，非法域名转为局部反馈。Phase1 结束时统一触发 context 的批量可行信号消费。模型输出不满足任务协议时（含缺失必选域选择），以局部结果反馈进入有限次重试；局部策略耗尽后按失败边界处理。

### Phase2：生成行动参数

Phase2 从 action 门面取已选 domain 的行动工具作用域；作用域准备失败收敛为 phase 级结果记入轨迹并结束本执行轮。MessageStack 由 context 构造，overlay 可携带 domain 级 HOW 引导内容。模型返回的 Action Tool Calls 交 action 归一化；行动决策（助手消息与工具调用记录）与归一化失败的局部结果通过轨迹信号记入语境。

Domain 级 HOW 的来源由 `DomainHowProvider` 注入。Agent Home 未接入时默认 provider 返回空内容；接入后同一注入点指向 `home:how_domain:<domain>`，由 Agent Home 映射到 `how_domain/<domain>/DOMAIN.md`，不需要改变 Phase2 执行单元。Phase3 自身不构造 LLM prompt；带内部 LLM task 的 action 通过 action 层共享 `LLMActionTaskRunner` 自动追加 domain HOW 与 action HOW。

### Phase3：采取行动

Phase3 将归一化行动调用经 action 门面装配为批次并执行，归一化失败结果与执行结果按原始顺序合并，经反馈渲染整理为工具结果消息与轨迹载荷，通过轨迹信号记入语境。唯一成功的 `core.answer` 在结果已进入 TurnTrace 后构造 `runtime.turn_output`；多个成功 answer 表示违反 Loop 的唯一输出规则，记录为 Loop 自有 phase note，不伪造成 Action phase result，也不产生 Turn 输出。

Phase3 构造 `ActionExecutionContext` 时注入 SignalBus，使 native action 或后端 executor 可以通过既有信号协议向 context 提交状态变更。当前 app 装配层注册的 `workspace.scan` 使用这一通道提交 workspace 资源摘要。

`ContextSignalConsumer.emit_and_consume` 用于把同一逻辑步骤产生的 Context signals 成组发送并作为一个可重放批次提交。Phase decision、成组 action results 和成组 phase notes 不逐条提交；这既保持信号顺序，也使 Home 缺页发生时能够重放完整批次。Loop 自有 trace note 的稳定 `kind` 由 `LoopTraceNoteKind` 表达。

## Trap 处理器注册

Trap 处理器在装配阶段注册：结束 Turn/Cycle/Program、启动失败、Turn 输出使用精确处理器；Context pressure handler 依次协调 trace fold/heap compaction、Phase1 Background eviction 和可恢复 Workspace Trash，跳过 action-internal LLM task 在异常 payload 中声明的活动资源，确实回收字符后优先重试当前 Module、否则重试 Phase；Workspace Trash restore handler 恢复压力暂存资源、同步新的 Manifest snapshot 并重试原 Module；Agent Home runtime copy handler 准备副本后重试当前 Module；无进展或未处理 RuntimeException 使用结束 Turn/Program fallback。处理器产生的业务事件通过作用域化信号交对应模块消费。

## 与 app 装配层

TinySoulApp 与 TinySoulAppBuilder 属于 app 模块。App 装配层负责加载配置环境，构建 LLM、Action、Context、SignalBus 与 RuntimeTrap，注册 native action 和 executor，组装输入源、输入分发器与各级 loop runner。

Loop 与 app 的接口保持明确：

- app 创建 ProgramRunner、TurnRunner、CycleRunner 和 Phase 单元；
- app 将 ProgramInputEvent 投递给 ProgramRunner；
- app 在 Turn 活跃期间把控制请求转换为 `loop.control.request` 信号；
- loop 通过 RuntimeTransfer 把结束 Turn 或结束 Program 的控制结果返回给 app 层。

## 与其他模块的关系

- 对 llm：构造 TaskCall，处理任务成功与任务失败两态结果；任务失败走局部反馈重试，模型链耗尽等边界失败由 llm bridge 进入 Trap。
- 对 action：只经 ActionEngine 门面使用域作用域、行动作用域、归一化、批次装配与执行；实现 executor 所需的 `ActionExecution`、`ActionExecutionContext`、`ActionExecutor` 与结果类型由 Action 顶层包作为公共 SPI 暴露，上层不导入 `action.core`。
- 对 context：只经 ContextEngine 门面使用语境构造、控制工具、信号消费、输入合并与 Turn 生命周期。
- 对 runtime：信号经 SignalBus，控制流经 Runtime 语义异常与 Trap；loop 自身跨边界失败由 `failures.py` 稳定失败枚举经专门 bridge 映射为 Runtime 通用原因。
- 对 app：接收 app 已解析的 ProgramInputEvent 与 Turn 内部控制/追加输入信号，不关心外部输入源类型。

## 设计范围

Loop 的核心范围是运行编排、Phase 组合、Runtime 运行转移消费和 Turn/Cycle/Phase 边界信号消费。

Loop 不承担语境状态模型、行动执行、模型调用细节、workspace 与 Agent Home 读写、外部输入源、终端渲染或进程装配。运行层级的控制协议由 runtime 定义，Loop 只是其消费者。
