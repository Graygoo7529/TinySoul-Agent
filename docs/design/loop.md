# Loop 设计

## 定位

Loop 模块负责 TinySoul 的运行编排：Program/Turn/Cycle/Phase 各级运行器、外部输入监听，以及整个程序的装配入口。

Loop 不维护语境状态，不定义行动语义，不做模型供应商适配。它把 context、action、llm 三个模块在每个 Phase 组合起来，并消费 runtime 的信号与运行转移协议。Loop 是 Runtime 运行转移的主要消费者，也是全局装配（Trap 处理器、信号处理器、executor 注册）的落点。

## 设计目标

1. 运行层级与 Runtime 的运行位置模型一一对应：Program、Turn、Cycle、Phase 各有运行器或执行单元，各自消费指向本级 frame 的运行转移。
2. Phase 执行单元只做组合：取语境、取工具作用域、调 LLM Task、解释结果、发信号；不复制任何模块的内部逻辑。
3. 控制流变化统一经 Runtime 语义异常进入 Trap；外部输入与模块事件统一经信号，在明确边界消费。
4. 用户轮执行中可以接收追加输入与控制指令，两者路径分离。
5. Turn 结束语义唯一：以 `core.answer` 行动执行成功为准。

## 目录组织

Loop 模块按运行职责拆分：

```text
tinysoul/loop/
  config.py          # LoopSettings 与配置解析
  errors.py          # loop 契约与不变量错误
  failures.py        # loop Runtime bridge 失败枚举
  signals.py         # loop.control.request 信号协议
  inputs.py          # 输入监听与输入分类
  prompts.py         # Phase 任务提示构造与 domain guidance provider
  phases.py          # Phase1/Phase2/Phase3 执行单元
  cycle.py           # CycleRunner
  turn.py            # TurnRunner
  program.py         # ProgramRunner
  trap_handlers.py   # 通用结束与语境压缩 Trap handler
  app.py             # TinySoulApp 与 TinySoulAppBuilder
```

Runtime bridge 独立放在 `tinysoul/runtime/bridge/loop.py`，使 loop 自身的跨边界失败仍通过统一 Runtime 原因进入 Trap。`tinysoul/loop/__init__.py` 使用轻量导出与延迟加载，避免 loop 装配入口和 runtime bridge 之间形成导入环。

## 运行层级与运行器

ProgramRunner 是顶层循环：等待用户输入或指令，把普通输入派发为 User Turn，处理退出指令；与用户轮同级的其他任务（如每日沉淀）在其分发范围内，随对应模块接入。

TurnRunner 驱动一次 User Turn：开始时初始化语境，循环执行 Cycle 直到 Turn 结束条件满足，结束时收取 TurnSummary。Turn 结束条件为：`core.answer` 行动执行成功；执行轮数达到配置上限（兜底保护，收束前记录警告轨迹）；或 Trap 返回结束 Turn 的运行转移。

CycleRunner 驱动一次执行轮，顺序执行 Phase1、Phase2、Phase3 三个执行单元。每个 Phase 边界执行两项检查：控制请求信号存在时构造 Runtime 语义异常进入 Trap；追加输入信号存在时触发语境的输入合并，使追加输入在下一次 MessageStack 构造中可见。

各级运行器在自己的 frame 边界捕获 Runtime 语义异常，交 Trap 处理并消费运行转移：转移目标是本级 frame 时，结束转移正常收束本级、重试转移重放本级（语境保持已提交状态）；目标是上级 frame 时以运行结果向上传播。重试语义要求各级边界可重放，这由"语境变更只在信号消费点提交"保证。

## 外部输入

InputListener 是常驻输入监听线程，持续读取终端输入并分类投递；它不解析业务语义。

控制指令（如退出程序、中断当前 Turn，词表可配置）发出 `loop.control.request` 信号。信号本身不改变控制流；运行器在 Phase 或 Cycle 边界检查到控制请求后，构造对应的 Runtime 语义异常进入 Trap，由 Trap 返回结束 Turn 或结束 Program 的运行转移。

普通内容在 Turn 执行中发出 `context.input.append` 信号，进入语境的输入列表并在安全边界合并；没有 Turn 运行时，作为下一个 Turn 的初始输入交给 ProgramRunner。

线程安全依赖 SignalBus 的线程安全发出与批量消费能力。

## Phase 执行单元

三个 Phase 执行单元的输入统一为 context 门面、action 门面、LLM 任务运行器、信号总线与当前运行位置；输出为各自的明确产物类型（Phase1Outcome、Phase2Outcome、Phase3Outcome）。

### Phase1：更新语境与决策行动域

Phase1 的工具作用域由 context 的语境控制工具与 action 的域选择工具合并而成。域选择是必选输出，语境整理是可选输出；这通过 TinySoul 的强制工具选择语义表达——工具使用策略要求工具调用，且结果必须包含域选择调用，同时允许包含其他控制调用。

Phase1 的 LLM Task 使用 `framework` profile，并在单次 TaskCall 中显式覆盖为工具必选调用。模型返回后：语境类控制调用交 context 归一化为状态信号；域选择调用解析为已选 domain 集合，非法域名转为局部反馈。Phase1 结束时统一触发 context 的批量可行信号消费。模型输出不满足任务协议时（含缺失必选域选择），以局部结果反馈进入有限次重试；局部策略耗尽后按失败边界处理。

### Phase2：生成行动参数

Phase2 从 action 门面取已选 domain 的行动工具作用域；作用域准备失败收敛为 phase 级结果记入轨迹并结束本执行轮。MessageStack 由 context 构造，overlay 可携带 domain 级 HOW 引导内容。模型返回的 Action Tool Calls 交 action 归一化；行动决策（助手消息与工具调用记录）与归一化失败的局部结果通过轨迹信号记入语境。

Domain 级 HOW 的来源由 `DomainGuidanceProvider` 注入。Agent Home 未接入时默认 provider 返回空内容；接入后同一注入点指向 how_action/domain 文档，不需要改变 Phase2 执行单元。

### Phase3：采取行动

Phase3 将归一化行动调用经 action 门面装配为批次并执行，归一化失败结果与执行结果按原始顺序合并，经反馈渲染整理为工具结果消息与轨迹载荷，通过轨迹信号记入语境。`core.answer` 存在成功结果时，产物标记本 Turn 已回答，作为 Turn 结束条件的数据源。

Phase3 构造 `ActionExecutionContext` 时注入 SignalBus，使 native action 或后端 executor 可以通过既有信号协议向 context 提交状态变更。当前内置 `workspace.scan` 使用这一通道提交 workspace 资源摘要。

## Trap 处理器注册

Trap 处理器在装配阶段注册：结束 Turn、结束 Cycle、结束 Program、启动失败使用通用处理器；语境压缩原因注册压缩处理器，处理器调用 context 的压缩服务并返回重试当前 Phase 的转移；Agent Home 运行时副本原因随对应机制接入。处理器不直接修改业务状态，状态变更经信号交对应模块消费。

## 装配入口

TinySoulApp 是进程入口；TinySoulAppBuilder 负责全局装配：加载配置环境，构建 LLM 任务运行器、ActionEngine（注册 native 执行函数）与 ContextEngine，注册 Trap 处理器与信号处理器，组装输入监听与各级运行器。

装配层当前负责以下跨模块接入：

- action 执行上下文的信号总线由装配层注入；
- `core.answer` native action 返回最终回答 payload，并作为 Turn 正常结束条件；
- `workspace.scan` native action 扫描项目工作区中的文件摘要，生成 `workspace:` 链接，并通过 `context.working.patch` 同步 WorkingContext；
- `llm_step.context_task` 后端执行器持有装配层的 LLM 任务运行器与 ContextEngine，使用 Context 构造 MessageStack 后发起受控嵌套 LLM Task；
- Phase2 overlay 的 domain 级 HOW 引导内容由装配层 provider 提供，默认为空，Agent Home 接入后替换为 how_action 来源。

## 与其他模块的关系

- 对 llm：构造 TaskCall，处理任务成功与任务失败两态结果；任务失败走局部反馈重试，模型链耗尽等边界失败由 llm bridge 进入 Trap。
- 对 action：只经 ActionEngine 门面使用域作用域、行动作用域、归一化、批次装配与执行。
- 对 context：只经 ContextEngine 门面使用语境构造、控制工具、信号消费、输入合并与 Turn 生命周期。
- 对 runtime：信号经 SignalBus，控制流经 Runtime 语义异常与 Trap；loop 自身跨边界失败由 `failures.py` 稳定失败枚举经专门 bridge 映射为 Runtime 通用原因。

## 设计范围

Loop 的核心范围是运行编排、Phase 组合、外部输入分发、Trap 处理器注册和全局装配。

Loop 不承担语境状态模型、行动执行、模型调用细节、workspace 与 Agent Home 读写、终端渲染。运行层级的控制协议由 runtime 定义，Loop 只是其消费者。
