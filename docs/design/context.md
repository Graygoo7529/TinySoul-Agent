# Context 设计

## 定位

Context 模块负责 TinySoul 的语境状态、MessageStack 构造、语境控制工具和语境压缩服务。

Context 不调用 LLM，不执行 action，不驱动运行控制流。它依赖 `llm` 提供消息与工具的公共类型，依赖 `runtime` 提供信号与异常转移协议；`loop` 是它的主要调用方。

Context 的核心职责是把"Agent 此刻知道什么"组织成稳定的状态模型，并在每次 LLM Task 前把状态"构造"为完整的 MessageStack。状态是持续维护的语境；MessageStack 是按需生成的投影。

## 设计目标

1. 三段语境（BackgroundContext、TurnTraceContext、WorkingContext）各自职责清晰，状态变更入口收敛。
2. MessageStack 采用构造式组装：每次 LLM Task 单独构造，区段顺序服务提示缓存的稳定前缀。
3. 语境变更不由模型输出直接驱动：Control Tool Calls 先归一化为信号，再由 Context 事务式消费。
4. 用户轮执行中的追加输入进入语境有明确的暂存与合并语义。
5. 语境压缩作为 Runtime 恢复例程的服务方接入，流程遵循统一的陷入协议。

## 语境状态模型

语境分为三段，另有一个本轮输入列表。四者都是 Turn 内的可变持有者：内部条目使用不可变对象，变更只通过受控入口进行。变更入口只有两类：信号消费和 Turn 生命周期（开始与结束）。

### BackgroundContext

用户轮开始前的背景。持有顶层内容条目（BackgroundEntry）的有序集合与当日会话历程摘要。每个条目对应一个 Agent Home 顶层内容链接（如 `home:what@xxx`）及其渲染文本，并区分默认加载与 Phase1 加载两种来源。条目可以被 Phase1 的控制意图加载或逐出。

### WorkingContext

本轮任务执行状态，即 Agent 的"工作台"。持有工作区资源描述（链接与摘要清单）、里程碑（Milestone）与待办（TodoItem）。里程碑与待办使用稳定状态枚举。变更通过明确的补丁类型（WorkingPatch）表达，补丁由信号载荷解析而来，先校验后提交。

### TurnTraceContext

本轮行为轨迹，append-only。每条轨迹记录（TraceEntry）直接持有 llm 公共消息类型——含工具调用记录的助手消息、工具结果消息、由追加输入形成的用户消息——并附带执行轮、Phase 与来源等结构化元数据。轨迹是 Phase2 行动决策与 Phase3 行动反馈的规范历史，也是语境压缩的作用对象。

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

composer 在构造时执行语境预算检查。预算超限不在 Context 内部消化，而是作为模块边界失败交给压缩流程处理（见语境压缩）。

## 语境控制工具与信号

Context 定义 Phase1 可见的语境控制工具（Control Tools）：更新工作台（里程碑与待办）、加载顶层内容、逐出顶层内容。控制工具与 action 模块的域选择工具并列进入 Phase1 的工具作用域；域选择是 Phase1 的必选输出，语境控制是可选输出。

模型返回的 Control Tool Calls 不直接修改状态。ControlCallNormalizer 负责校验与归一化：合规调用转为状态信号，不合规调用收敛为局部结果（ControlResult），供上层记录并反馈模型。这一模式与 action 模块的行动调用归一化保持同构。

Context 消费的信号协议：

- `context.working.patch`：WorkingContext 变更请求；
- `context.background.patch`：顶层内容加载与逐出请求；
- `context.trace.append`：轨迹追加请求，载荷为消息投影与元数据；
- `context.input.append`：用户追加输入。

信号消费是事务式的：先校验全部载荷，再提交状态；载荷不合规转为局部结果，不抛出异常。信号生产方包括 Phase1 归一化（前两类）、Phase2/Phase3 的结果整理（第三类）和 loop 的输入监听（第四类）。

## 语境压缩

压缩流程遵循 Runtime 统一陷入协议，Context 只承担失败表达与压缩服务两个角色：

1. composer 预算检查失败时抛出模块边界异常，由 context bridge 映射为语境压缩的 Runtime 原因；
2. Trap 按原因调用注册的压缩处理器；处理器调用 Context 提供的压缩服务（ContextCompressor）；
3. 压缩策略为对 TurnTrace 旧条目的裁剪与摘要占位替换：占位条目记录被裁剪的条目数与关键动作名，BackgroundContext 与 WorkingContext 不参与裁剪；
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

ContextEngine 是 Context 面向 loop 的装配门面，聚合状态持有者、composer、控制工具构建、归一化、信号消费、输入合并与压缩服务；ContextEngineBuilder 负责装配配置（身份 system 文本、默认背景来源、预算阈值等）。模块内部散件默认只服务于模块内部与测试。

## 设计范围

Context 的核心范围是语境状态模型、MessageStack 构造、语境控制工具语义、语境信号消费和压缩服务。

Context 不承担 LLM 调用、行动执行、运行控制流、workspace 与 Agent Home 的文件读写、终端渲染。这些能力在对应模块中设计，通过 llm 公共类型、信号与 Runtime 协议与 Context 协作。
