# Runtime 设计

## 定位

Runtime 是 TinySoul 的顶层运行控制模块。它负责描述程序运行位置、异常陷入、运行转移、运行中断、内部信号分发和非控制性观察事件协议。

Runtime 不负责执行业务动作，不构造模型消息栈，不修改语境状态，不读写 Workspace 或 Agent Home，也不解释 LLM、Action、Context 的业务结果。具体模块负责完成自身局部处理，并在模块边界通过异常或信号向 Runtime 和其他模块表达需要上层协调的运行事实。

Runtime 采用 OS 风格的陷入设计：模块内部正常执行时不依赖全局控制器；当模块局部处理失败、运行环境需要全局恢复、用户请求中断或程序需要退出时，执行流程陷入 Runtime，由 Runtime 根据当前运行位置和异常语义给出恢复或中断决策。内部信号作为可消费的软事件，用于在模块之间表达状态变更请求、动作结果和用户追加输入；只供外部观察、没有业务消费者的事件使用独立 Observation 协议。

## 运行层级

TinySoul 的运行层级从外到内分为 Program、Turn、Cycle、Phase 和 Module。

Program 是程序顶层，当前负责等待用户输入、执行退出指令和调度 User Turn。运行层级允许未来调度与用户轮同级的 Daily Turn，但该调度尚未实现；Program 不直接介入 Phase 或具体模块细节。

Turn 是 Program 下的一次顶层任务。当前实现由用户输入形成 User Turn；运行模型允许每日沉淀或维护任务形成与 User Turn 同级的 Daily Turn，但对应调度尚未落地。不同类型 Turn 的调度策略可以不同，例如 User Turn 可以接收用户追加输入，Daily Turn 执行期间不接收用户输入；但它们在运行控制层级上同属 Turn。

Cycle 是 User Turn 内的一次执行轮。User Turn 可以包含多个 Cycle，每个 Cycle 按顺序组织 Phase。

Phase 是执行轮内的执行单元。Phase1 负责更新语境与决策行动域，Phase2 负责生成行动参数，Phase3 负责采取行动。每个 Phase 都可以包含一次或多次模块级任务。Phase 的稳定标识由 Runtime 以 CyclePhase 提供，供业务模块在结果与轨迹元数据中引用同一语义。

Module 是具体模块执行边界，包括 LLM Task、Action 执行、Context 操作、Workspace 或 Agent Home 相关操作。模块优先在自身边界内完成局部恢复和错误映射；只有局部策略耗尽或需要全局协调时，才向 Runtime 上抛异常或发出信号。

Runtime 使用运行位置记录当前执行栈。运行位置应能表达 Program、Turn、Cycle、Phase 和 Module 的嵌套关系，从而定位异常发生处和恢复目标。运行位置只描述控制流位置，不承载业务参数。Action 输入、LLM profile、Context patch 等业务内容应存在模块异常详情或信号载荷中。

## 异常与陷入

异常用于表达执行失败、运行恢复需求和中断请求。异常的核心作用是进入 Trap，并由 Trap 处理器决定后续运行转移。

模块内部可以先执行局部恢复。例如 LLM 模块负责模型链重试、模型切换和响应解释；Action 执行器负责把 Action 运行失败、超时或参数错误结构化为 Action Result；Phase 可以把一次无法解析的 LLM 输出反馈到下一次同 Phase 的模型调用中。上述情况只要能在模块或 Phase 内完成，就不需要进入全局 Runtime 陷入。

模块内部可以使用普通 Python 异常或模块私有异常表达内部失败，例如参数错误、供应商错误、解析错误或局部状态错误。这些异常不应直接跨出模块边界进入 Runtime。模块边界负责捕获内部异常，先执行局部恢复、错误映射或结果结构化；只有确实需要上层运行控制介入时，才转换为 Runtime 可理解的语义异常。这样可以避免 Runtime 被供应商、解析器或具体模块内部错误类型污染。

当局部处理失败，或发生需要全局协调的情况时，模块边界抛出 Runtime 可理解的语义异常，异常进入 Runtime 陷入流程。Runtime 语义异常使用少量稳定原因标识表达陷入后的运行意图，例如启动失败、结束 Turn、结束 Cycle、结束 Program、语境压缩或 Agent Home 运行时副本准备。Trap 将异常和当前运行位置转换为 TrapSnap，并按照原因标识查找处理器。

Runtime 的异常入口应保持单一。模块外交给 Runtime 的异常使用统一异常类型承载原因标识、错误消息和结构化载荷。Runtime 不通过庞大的异常继承树区分恢复、中断和退出，也不直接接收各模块的细粒度失败原因；模块失败原因由模块内部维护，并通过 bridge 映射到 Runtime 的通用原因。这样可以保持异常入口稳定，并避免 LLM、Infra、Action 或 Context 的内部错误分类污染 Runtime 控制协议。

Runtime 自身仍然有模块内部的契约和不变量错误。`RuntimeException` 只表示需要进入 Trap 的控制流语义，不用于表达 `RunScope`、`Signal`、`TrapResult` 或 Trap registry 的构造错误。Runtime 公共对象、SignalBus/Trap 注册表和 JSON payload 边界使用 Runtime 自有错误层表达：调用方违反 Runtime API 约定时抛出 `RuntimeContractError`，已装配 Runtime 状态无法满足自身运行不变量时抛出 `RuntimeInvariantError`。这些错误表示代码或装配边界失败，不作为普通业务恢复原因进入 Trap，也不新增 Runtime reason。

TrapSnap 是 Trap 捕获异常后形成的陷入上下文快照。它包含原因标识、错误消息、结构化载荷和运行位置。结构化载荷是模块 bridge 显式构造的 JSON 对象；原始异常链可以供日志和调试使用，但不应成为 payload 协议。TrapSnap 不再被抛出；它只在 Trap 处理器、日志、TurnTrace 和可观测流程中流动。

常见原因包括：程序启动失败、结束 Turn、结束 Cycle、结束 Program、需要语境压缩、需要 Agent Home 运行时副本准备。具体 Runtime 原因名称属于模块间协议，应稳定、可记录、可测试；具体模块失败类型应放在 payload 的模块命名空间字段中。

## 模块接入约定

其他模块接入 Runtime 时应遵循与 LLM 和 Infra 一致的桥接模式。

模块内部先定义服务于 Runtime bridge 的稳定失败语义。稳定失败语义属于模块，而不是 Runtime；它用于表达该模块跨出边界后需要 Runtime 协调控制流的失败类别。模块内部可自行处理或结构化返回给调用方的失败不必纳入 bridge failure 枚举；这类失败应使用模块结果、模型反馈或专门的局部结果协议表达。模块内部临时异常、实现细节异常和第三方库异常不应直接成为跨模块协议。

模块边界负责决定失败的去向。可以在模块内部修复的失败，应由模块内部重试、切换、降级或转换为模块结果；需要反馈给模型或上层业务流程继续处理的失败，应返回结构化模块结果，例如 LLM 的任务失败结果通过模型反馈说明输出为何不满足任务解释协议，Action 的 action result 和 phase-level result 表达具体 action call 或 action phase 的局部执行事实；需要改变运行控制流的失败，才通过 Runtime bridge 转换为 Runtime 语义异常。默认跨模块失败映射为结束当前 Turn；启动装配阶段的失败映射为启动失败；只有需要独立全局恢复例程时，才新增 Runtime 原因。

Runtime bridge 是模块失败语义和 Runtime 通用原因之间的唯一翻译层。bridge 应通过显式映射表把模块失败类型映射为 Runtime 原因，并显式构造错误消息和 JSON payload。payload 至少应表达模块名和模块失败类型，并可包含 `error_type`、配置 key、任务 profile、资源句柄等稳定摘要字段。traceback 和原始异常对象不属于 payload 协议；实现上可以通过异常链保留调试信息。

不同 bridge 可以复用私有 helper 完成机械性的 payload 拼装、异常类型摘要和 `ConfigError` 投影，但模块名、模块 failure enum、Runtime reason 映射表和专用恢复入口仍保留在各自 bridge 文件中。公共 helper 不承担模块失败分类，也不决定控制流语义。

模块事件和状态变更请求不应通过 Runtime 异常表达。模块完成一次动作、产生状态 patch、需要追加 TurnTrace 或需要通知其他模块消费数据时，应发出信号；只需要向外部报告运行边界时应发布 ObservationEvent。只有结束 Turn、结束 Cycle、结束 Program、触发全局恢复或启动失败这类控制流变化，才进入 Runtime Trap。

## 运行转移

Runtime 的陷入结果是运行转移。运行转移应指向运行位置栈中的 frame，使运行器能够明确知道 Trap 处理结束后应重试或结束哪个运行边界。

运行转移只包含重试某个 frame 和结束某个 frame。重试表示恢复例程完成后重新执行目标 frame，使原本被陷入打断的工作继续完成；结束表示结束目标 frame。结束 Program frame 表示退出程序；结束 Turn frame 表示结束当前 User Turn 或 Daily Turn；结束 Cycle frame 表示结束当前执行轮，后续是否进入下一 Cycle 由 Turn 运行器基于当前 Turn 状态决定。程序退出、Turn 中断、Cycle 收束和恢复失败都不需要单独的动作枚举，而是通过结束对应 frame 表达。

重试目标 frame 必须具备可重放语义。模块级重试只有在模块边界保存了可重放调用时才成立，例如资源操作、Action Invoke 或明确的 LLM Task 调用。否则处理器应选择重试 Phase、Cycle，或结束 Turn。Runtime 不提供从异常抛出点下一行继续执行的语义；若某个问题可以在模块内部继续调度，它不应进入 Trap，而应由模块内部流程或信号系统处理。

运行器负责消费运行转移。Program、Turn、Cycle 和 Phase 运行器只消费指向自身 frame 的转移；`RuntimeModuleRunner` 为 action invoke、Context signal batch 等可重放调用建立 Module frame，捕获一次 RuntimeException、发出 Trap 信号并在 RETRY 指向自身时重放同一调用。指向上层 frame 的转移通过 `RuntimeTransferInterrupt` 展开传播，不会在每层重复进入 Trap。Runtime 本身不直接提交业务状态。

Trap 只接受指向本次捕获 `RunScope` 内 frame 的运行转移。处理器若返回外部 scope、已经失效或从未属于该运行栈的 target，Trap 以 `RuntimeInvariantError` 拒绝结果；运行器不能消费一个没有栈归属的跳转目标。这个校验位于 Trap 边界，而不是分散到每级运行器。

## 异常处理

Runtime 将异常处理统一为 Trap 处理器调度。

Runtime 使用 Trap 处理器表处理不同陷入原因。处理器表类似 OS 中断向量表：原因标识和运行位置共同决定处理器，处理器返回运行转移。

Trap 处理器负责解释 Runtime 原因标识。它可以直接返回结束 Turn、结束 Program 等转移，也可以执行全局恢复例程后返回重试某个 frame 的转移。新增模块失败类型通常不应新增 Runtime 原因，而应在模块 bridge 的映射表中映射到既有通用原因；只有需要独立恢复例程或独立全局控制语义时，才新增 Runtime 原因并注册处理器。处理器可以读取 TrapSnap，但不应反向依赖具体业务模块内部状态。

Trap registry 支持精确 reason、命名空间前缀和一个显式 fallback。应用装配为未识别的 RuntimeException 注册 fallback：运行期结束最近 Turn，启动期结束 Program。这样无法由业务处理器恢复的 RuntimeException 不会泄漏为普通 Python 异常。registry 重复注册、非法 key、错误 Signal/TrapResult 等 Runtime 自身契约和装配错误仍使用 `RuntimeContractError`/`RuntimeInvariantError`，不进入 fallback。

通用处理策略包括：启动失败结束 Program；结束 Turn 原因结束当前 Turn；结束 Cycle 原因结束当前执行轮；结束 Program 原因退出程序；`runtime.turn_output` 校验并发布最终输出后结束 Turn；语境压缩或 Agent Home 运行时副本准备等原因由对应处理器执行恢复后返回运行转移；未处理 RuntimeException 由 fallback 结束 Turn 或 Program。

Trap 处理器可以发出信号，例如请求记录 TurnTrace 或通知某个恢复任务已完成。Trap 处理器不应直接修改业务状态；实际状态修改仍由对应信号消费者完成。运行器可在捕获 Trap 后另行发布观察事件，但输出适配器不参与 Trap 决策。

## 恢复例程

部分陷入原因会触发恢复例程。恢复例程是 Trap 处理器执行的全局恢复任务，类似 OS 的异常服务例程。它用于执行那些不能由单个模块局部完成、但完成后可以恢复运行的任务，例如 MessageStack 压缩、Agent Home 运行时副本准备、用户追加输入合并或需要全局协调的资源状态修复。

恢复例程通过 Trap 处理器注册表接入 Runtime。Trap 捕获 Runtime 语义异常后，记录陷入位置，按照原因标识查找处理器，执行必要的恢复任务，并依据处理结果生成运行转移。

Trap 处理器的结果应表达运行转移和需要发出的信号。恢复成功后可以建议重试陷入模块、当前 Phase 或当前 Cycle。恢复失败时可以建议结束当前 Turn；用户或程序级中断时可以建议结束 Program。

例如，Agent Home 运行时副本缺失时，处理器可以创建所需副本，并建议重试陷入模块；MessageStack 超出预算时，处理器可以压缩语境，并建议重试当前 Phase；压缩失败时，处理器可以建议结束当前 Turn，并发出故障记录信号供 TurnTrace 或可观测模块消费。

Trap 处理器不应直接驱动运行器跳转。Trap 只返回运行转移，具体的重试或结束由对应运行器消费。这样可以保留陷入点和恢复目标之间的清晰边界，也避免 Runtime 直接依赖 Phase、Action 或 Context 的内部执行方式。

## 信号

信号用于表达内部模块行为和模块间消费意图。信号不等同于异常；信号不表示 Python 调用失败，也不默认改变恢复位置。

信号由统一信封承载。信封至少表达信号名称、来源、运行位置和结构化载荷。信号名称使用命名空间形式，区分 Runtime 保留信号和模块信号。运行位置说明信号产生处；结构化载荷使用 JSON 对象，保证跨模块边界可校验、可记录、可渲染。

Runtime 只定义信号信封和分发机制，不定义所有业务载荷字段。具体信号协议由生产模块和消费模块共同维护。例如 Phase1 可以把 Control Tool Calls 汇聚、校验并归一化为 WorkingContext 或 BackgroundContext 的状态信号；Phase3 可以把并行动作结果汇聚为 TurnTrace 追加信号。外部渲染不消费这些业务信号，而由运行器在已经确定的边界发布 ObservationEvent。

信号载荷应保持为结构化摘要和资源句柄，不应携带大量文件内容。Workspace 文件、Agent Home 渐进式内容、图片或长文本应通过链接或资源句柄表达，由需要的模块在具体执行边界读取。

## 信号分发与消费

信号通过 SignalBus 发出和暂存。SignalBus 提供线程安全的发出、查看、批量消费和按命名空间前缀选择性消费的能力，以支持 Phase3 的并行动作执行、用户追加输入和后台事件；命名空间消费使某个模块可以只取走属于自己的信号，而不影响其他消费者的队列。

信号消费由拥有业务协议的模块在明确边界负责。消费者通过 SignalBus 的精确名称或命名空间批量选择能力取得信号，再按自身类型解析、投影和提交；Runtime 不维护一个脱离业务所有权的通用 SignalHandlerRegistry。Phase1 产生的状态信号应在 Phase1 结束后按消费模块协议批量处理；Phase3 的 Action 结果信号应在并行执行完成后批量消费；用户追加输入信号应在 User Turn 可接收输入的位置合并进当前 Turn。

模块信号的主链路是 SignalBus 和业务模块消费者，不是 Trap。这样可以保持异常控制流和模块事件流分离。Trap 不识别控制信号；请求结束当前 Turn、请求结束 Program 或请求进入全局恢复流程等控制流变化，应由运行器构造 Runtime 语义异常进入 Trap。其他信号由对应模块在自身安全边界消费。

信号消费者不应依赖发送方的内部对象。发送方负责在边界处把动态数据转换为清晰的 JSON 对象；接收方负责把 JSON 载荷解析为自身模块的明确类型，并执行校验和状态提交。这样可以避免宽泛动态对象在模块内部扩散。

控制流变化不通过普通信号表达。需要结束 Turn、结束 Program、触发全局恢复或处理无法继续的错误时，应构造 Runtime 语义异常进入 Trap。信号用于模块事件和状态变更请求，例如追加 TurnTrace、提交 WorkingContext patch、记录 trace 或传递用户追加内容。

外部输入也遵循这个边界。用户追加普通内容时，可以先形成用户追加信号，由 Turn 运行器在安全边界合并；如果外部输入请求停止当前 Turn 或结束 Program，则由对应运行器构造 Runtime 语义异常进入 Trap，并由 Trap 返回结束 Turn 或结束 Program 的运行转移。

## 观察事件

`ObservationEvent` 是不可用于控制流的结构化旁路事件。它包含稳定事件名、`normal` / `verbose` / `model` 详细度、来源、RunScope、可读消息、JSON payload 和产生时间。Runtime 只定义事件与 `ObservationEmitter` 协议；Loop、LLM、Action 和 RuntimeModuleRunner 在各自拥有事实的边界发布，App 负责过滤和连接 `OutputSink`。

Runtime transfer 本身只表达恢复位置，不等于业务失败。Loop 在消费 transfer 时可从原始 `RuntimeException` 异常链提取 bridge 已提供的 reason/module/kind，形成有界 Turn failure；`runtime.turn_output`、用户 stop/exit 和无模块失败字段的控制 END 不得被归类为失败。该分类属于 Loop 的 Turn outcome 语义，不扩展 RuntimeTransfer 字段，也不把 traceback 或大 payload 带入 Observation。

Observation 与 Signal 的区别由消费语义决定：SignalBus 中的事件等待业务模块消费并可能形成状态提交；Observation 只面向人机界面、日志适配或嵌入方，不排队等待业务确认。Observation 与 Trap 的区别由控制语义决定：emitter/sink 失败不能触发恢复、重试或结束 frame。发布 helper 吞掉 emitter 异常，App router 隔离失败 sink，并在业务边界结束后由 App 语义报告输出故障。

详细 observation payload 必须 provider-neutral、JSON 安全且有界表达二进制和敏感结构。MODEL 级可以表达文本消息、工具协议和归一化回答以支持诊断，但图片只携带摘要，推理原文、加密项原文与 provider 原始响应不进入事件。是否渲染及文本裁剪属于 App/OutputSink 责任，不属于 Runtime 控制协议。

## Trap

Trap 是 Runtime 的 OS 风格陷入控制器。它处理 Runtime 语义异常并返回运行转移，但不拥有业务状态。

Trap 的异常入口接收 Runtime 语义异常和运行位置，转换为 TrapSnap，按照原因标识查找处理器，验证处理器给出的 target 属于捕获 scope，再返回运行转移。Trap 不处理普通信号或 ObservationEvent；模块状态信号和动作结果信号由各业务模块从 SignalBus 消费，观察事件直接进入已注入 emitter。

Trap 不执行 LLM 调用，不重跑 Phase，不修改 Context，不写 Action Record，也不直接写 Workspace。它只负责把 Runtime 语义异常转换为运行转移，并把必要的副作用意图表达为信号。具体恢复任务由注册的 Trap 处理器执行；具体运行跳转由 Program、Turn、Phase 或 Module 运行器执行。

这种边界避免将旧实现中的 trap、interrupt handler、QueryState 和 Action Record 绑定在一起。Runtime 提供控制协议；Loop、Context、Action、LLM 和 Infra 在各自边界内接入。

## 与 LLM 的关系

LLM 模块保持现有边界：它负责模型调用输入输出的统一表达、供应商适配、能力校验、模型选择、重试切换和输出解释。LLM 不执行 Action，不修改 Context，不消费 Control Tool 或 Action Tool 的业务语义。

LLM 内部的 provider 错误、模型链切换和有限重试属于局部恢复，不进入 Runtime。暂时性供应商错误可以在同一模型上重试；其他供应商错误默认跳过同模型重试并切换到下一个模型。模型链耗尽、调用设置不满足、调用契约错误等跨出 LLM 边界的失败，由 LLM bridge 根据模块失败类型映射为 Runtime 通用原因，默认结束当前 Turn。Phase 可以先进行局部反馈和重试；局部策略耗尽后，再交给 Runtime 陷入处理。

LLM 输出解释失败不默认进入 Runtime。若模型调用已经成功返回，但回答无法解析或工具调用不满足任务解释协议，LLM Task 可以返回失败任务结果，其中 `model_feedback` 提供给模型看的简短错误反馈，框架内部数据只作为上层参考。调用方模块据此决定是否把反馈加入下一次任务提示、结束当前 Cycle，或在局部策略耗尽后再通过 Runtime 语义异常进入 Trap。模型链耗尽、调用契约错误、无法在模块内继续处理的供应商错误等需要改变运行控制流的情况，才通过专门桥接层转换为 Runtime 语义异常。

模型侧工具调用仍属于 LLM 输出协议。Control Tool Calls 和 Action Tool Calls 的业务含义由上层模块解释，并通过信号或 Action Invoke 进入后续流程。Provider 原生 tool calling 结构不进入 Runtime。

LLM 是模块接入 Runtime 的参考实现之一。供应商错误先由 LLM 模型链按策略重试或切换，不单独作为 Runtime bridge failure 暴露；模型链耗尽、配置失败和调用契约错误等需要改变控制流的模块失败，再由 LLM bridge 映射到 Runtime 通用原因。模型输出解释失败则作为任务失败结果返回调用方，通过 `model_feedback` 供上层参考，不默认进入 Runtime，也不纳入 LLM bridge failure 枚举。

## 与 Infra 的关系

Infra 继续提供配置、JSON 边界和受控文件系统能力。Runtime 可以使用 Infra 的 JSON 基础能力约束信号载荷和异常详情，但 Runtime 不属于 Infra。

配置加载错误可以在配置模块边界转换为表示启动失败的 Runtime 语义异常。观察事件由 Runtime 或业务运行器通过 ObservationEmitter 发布，并由 App 输出边界渲染；Infra 不拥有终端输出语义。资源读写、Workspace 边界检查和 Agent Home 运行时副本机制应由对应资源模块实现；当这些机制需要全局恢复流程时，再通过 Runtime 语义异常或 Runtime 保留信号进入 Trap。

Infra 自身不表达 Runtime 控制流。当前 Infra bridge 只映射配置加载失败为启动失败；JSON 与文件系统边界错误由实际拥有该调用流程的业务模块局部处理或归入自身 bridge，不维持没有真实调用路径的通用失败分类。

## 设计范围

Runtime 的核心范围是运行位置、异常陷入、运行转移、Trap 处理器、信号分发、信号消费协议和非控制性 Observation 信封。

Runtime 不承担 Loop 业务策略、Context 状态模型、Action 执行、LLM 任务构造、Workspace 文件内容管理、Agent Home 知识合并和终端渲染细节。这些能力应在对应模块中设计，并通过 Runtime 的异常和信号协议与整体运行控制协作。
