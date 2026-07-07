# Context 设计

## 定位

Context 模块负责 TinySoul 的语境状态、MessageStack 构造、语境控制工具和语境压缩服务。

Context 不调用 LLM，不执行 action，不驱动运行控制流。它依赖 `llm` 提供消息与工具的公共类型，依赖 `runtime` 提供信号与异常转移协议；`loop` 是它的主要调用方。

Context 的核心职责是把"Agent 此刻知道什么"组织成稳定的状态模型，并在每次 LLM Task 前把状态"构造"为完整的 MessageStack。状态是持续维护的语境；MessageStack 是按需生成的投影。

## 设计目标

1. 三段语境（BackgroundContext、TurnTraceContext、WorkingContext）各自职责清晰，状态变更入口收敛。
2. MessageStack 采用构造式组装：每次 LLM Task 单独构造，区段顺序服务提示缓存的稳定前缀。
3. 语境变更不由模型输出直接驱动：Control Tool Calls 先归一化为信号，再由 Context 整批解析、投影验证并提交可行变更。
4. 用户轮执行中的追加输入进入语境有明确的暂存与合并语义。
5. 语境压缩作为 Runtime 恢复例程的服务方接入，流程遵循统一的陷入协议。

## 语境状态模型

语境分为三段，另有一个本轮输入列表。四者都是 Turn 内的可变持有者：内部条目使用不可变对象，变更只通过受控入口进行。变更入口只有两类：信号消费和 Turn 生命周期（开始与结束）。ContextEngine 不向 loop 暴露这些可变持有者，只提供背景链接、工作台快照、轨迹摘要等只读投影；状态持有者类型作为模块内部散件服务于实现与单元测试。

### BackgroundContext

用户轮开始前的背景。持有顶层内容条目（BackgroundEntry）的有序集合与当日会话历程摘要。每个条目对应一个 Agent Home 顶层内容链接（如 `home:what@xxx`）及其渲染文本，并区分默认加载与 Phase1 加载两种来源。条目可以被 Phase1 的控制意图加载或逐出。批量消费背景变更时，Context 会在投影状态上顺序验证同批 load/evict：未知链接、逐出未加载链接、同一信号同时加载和逐出同一链接都会收敛为局部结果；加载已经存在的链接是幂等 no-op，不改变已有条目的内容和来源；可行变更再统一提交。

### WorkingContext

本轮任务执行状态，即 Agent 的"工作台"。持有工作区资源描述（链接与摘要清单）、里程碑（Milestone）与待办（TodoItem）。里程碑与待办使用稳定状态枚举。变更通过明确的补丁类型（WorkingPatch）表达，补丁由信号载荷解析而来。Phase1 的语境控制工具只暴露里程碑与待办更新；工作区资源描述由 workspace 或装配层同步工作区摘要时通过 `context.working.patch` 信号提交。Context 只接收、验证和渲染资源句柄，不读取 workspace 文件内容。批量消费工作台变更时，Context 会在投影状态上顺序验证同批 patch，因此后一条 patch 能看到前一条有效 patch 的结果；无效 patch 收敛为局部结果，不阻止同批其他可行 patch 提交。

### TurnTraceContext

本轮行为轨迹，append-only。每条轨迹记录（TraceEntry）直接持有 llm 公共消息类型——含工具调用记录的助手消息、工具结果消息、由追加输入形成的用户消息——并附带执行轮、Phase 与来源等结构化元数据。轨迹是 Phase2 行动决策与 Phase3 行动反馈的规范历史，也是语境压缩的作用对象。trace append 信号使用 llm 消息能力的稳定投影表达：文本与 JSON 内容以多片段 `content` 载荷保留，assistant decision 可携带 provider-neutral `Reasoning`；Context 只保存该结构，不判断供应商能否回放。图片、文件等非文本资源仍应通过链接进入上下文，而不是塞入 trace 信号。

### PendingInputs

本轮用户输入列表，包含初始输入与轮中追加输入。追加输入先进入列表暂存，由 loop 在安全边界触发合并：合并时转为轨迹中的用户消息，条目标记已合并。列表保留全量记录并进入 TurnSummary。

## MessageStack 构造

MessageStackComposer 按区段构造 MessageStack，顺序从稳定到易变：

1. system 段：Agent 身份与规约；
2. BackgroundContext 段：Turn 内基本稳定；
3. WorkingContext 段：低频变化；
4. TurnTraceContext 段：Turn 内只追加，按序回放用户输入、行动决策与行动反馈；
5. task prompt overlay：每次 LLM Task 不同。

这个顺序保证跨 LLM Task 的消息前缀尽量稳定，服务供应商提示缓存。

task prompt 由 TaskPrompt 表达，包含任务引导、任务输入与期望输出描述三部分语义。Phase2 的 overlay 可以携带按已选 action domain 组织的 HOW 引导内容（domain guidance）；引导内容由上层装配提供，Context 只负责拼装，没有内容提供方时该部分为空。

composer 在构造时执行语境预算检查。预算估算覆盖消息可见文本、JSON 片段，以及 Assistant reasoning 的文本内容、摘要和加密推理项，避免不可见推理轨迹绕过上下文预算。预算超限不在 Context 内部消化，而是作为模块边界失败交给压缩流程处理（见语境压缩）。

## 语境控制工具与信号

Context 定义 Phase1 可见的语境控制工具（Control Tools）：更新工作台（里程碑与待办）、加载顶层内容、逐出顶层内容。控制工具与 action 模块的域选择工具并列进入 Phase1 的工具作用域；域选择是 Phase1 的必选输出，语境控制是可选输出。

模型返回的 Control Tool Calls 不直接修改状态。ControlCallNormalizer 负责校验与归一化：合规调用转为状态信号，不合规调用收敛为局部结果（ControlResult），供上层记录并反馈模型。这一模式与 action 模块的行动调用归一化保持同构。

Context 消费的信号协议：

- `context.working.patch`：WorkingContext 变更请求；
- `context.background.patch`：顶层内容加载与逐出请求；
- `context.trace.append`：轨迹追加请求，载荷为消息投影与元数据；decision/action result 的消息内容使用 `content` 多片段投影，支持 text/json，并可为 assistant decision 保留 provider-neutral Reasoning；
- `context.input.append`：用户追加输入。

信号消费采用批量可行提交语义：先解析同批 `context.*` 信号；解析失败或载荷不合规的信号转为局部结果；Working 与 Background 变更在投影状态上按信号顺序验证，验证通过的变更统一提交，验证失败的变更不提交且不抛异常；返回的局部结果按原始信号顺序排序。该语义不是 all-or-nothing，而是保证可行变更不会因为同批其他失败信号而丢失，同时避免提交前后状态不一致。信号生产方包括 Phase1 归一化（前两类）、Phase2/Phase3 的结果整理（第三类）和 loop 的输入监听（第四类）。

Reasoning 的后续回放由 LLM 模块依据模型配置中的 `reasoning_keep` 和供应商能力决定：OpenAI Responses 只能把加密 reasoning item 作为可回放输入，summary 只是可观察摘要；OpenAI-compatible Chat 供应商若支持历史思考字段，则可在声明保留文本推理内容时回放 `reasoning.content`。Context 不在信号层把这些差异编码为分支。

## 语境压缩

压缩流程遵循 Runtime 统一陷入协议，Context 只承担失败表达与压缩服务两个角色：

1. composer 预算检查失败时抛出模块边界异常，由 context bridge 映射为语境压缩的 Runtime 原因；
2. Trap 按原因调用注册的压缩处理器；处理器调用 Context 提供的压缩服务（ContextCompressor）；
3. 压缩策略为对 TurnTrace 旧条目的裁剪与摘要占位替换：占位条目记录被裁剪的条目数与条目类型，BackgroundContext 与 WorkingContext 不参与裁剪；多次压缩会合并已有摘要占位，压缩报告会标明本次是否实际改变了 trace；
4. 压缩完成后由处理器返回重试当前 Phase 的运行转移；压缩后仍超限则返回结束 Turn。

压缩策略可以替换（例如升级为 LLM 归纳压缩），流程与接入方式不变。

## 失败与异常边界

Context 失败处理分三层：

1. 局部结果：模型控制调用不合规、信号载荷不合规，收敛为 ControlResult，由上层决定记录与反馈方式；
2. 模块边界异常：调用契约错误（ContextContractError）、内部不变量破坏（ContextInvariantError）、语境预算超限（ContextBudgetError）；
3. Runtime 语义异常：跨出模块边界的失败由 `failures.py` 的稳定失败枚举经 `tinysoul/runtime/bridge/` 下的 context bridge 映射——配置失败映射为启动失败，预算超限映射为语境压缩原因，其余默认结束当前 Turn。payload 只携带模块名、失败类型与摘要字段。

## 持久化边界

Context 维护内存态语境。Turn 结束时产出可 JSON 化的 TurnSummary，包含输入全量记录、工作台终态与轨迹摘要，作为当日会话历程与持久化的数据源。

持久化读写不属于 Context 职责：workspace 与 Agent Home 的链接读写、运行时副本机制由对应资源模块承担；Context 在这些机制接入后通过既有的条目与摘要模型消费其内容。

## 组装入口

ContextEngine 是 Context 面向 loop 的装配门面，聚合状态持有者、composer、控制工具构建、归一化、信号消费、输入合并与压缩服务；它只向上层暴露 compose、control scope、信号消费、输入合并、压缩、TurnSummary 与只读快照/摘要，不暴露可变状态持有者。ContextEngineBuilder 负责装配配置（身份 system 文本、默认背景来源、预算阈值等），并在装配边界校验背景链接冲突、非正预算、负数压缩保留数等配置问题。包级公共导出只保留上层装配和协作需要的门面、结果类型、信号 helper、错误和常量；状态持有者、patch 类型和 codec 细节从子模块显式导入，默认服务于模块内部与测试。

## 设计范围

Context 的核心范围是语境状态模型、MessageStack 构造、语境控制工具语义、语境信号消费和压缩服务。

Context 不承担 LLM 调用、行动执行、运行控制流、workspace 与 Agent Home 的文件读写、终端渲染。这些能力在对应模块中设计，通过 llm 公共类型、信号与 Runtime 协议与 Context 协作。
