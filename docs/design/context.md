# Context 设计

## 定位

Context 模块负责 TinySoul 的语境状态、MessageStack 构造、语境控制工具和语境压缩服务。

Context 不调用 LLM，不执行 action，不驱动运行控制流。它依赖 `llm` 提供消息与工具的公共类型，依赖 `runtime` 提供信号与异常转移协议；`loop` 是它的主要调用方。

Context 的核心职责是把"Agent 此刻知道什么"组织成稳定的状态模型，并在每次 LLM Task 前把状态"构造"为完整的 MessageStack。状态是持续维护的语境；MessageStack 是按需生成的投影。

Stage 6.1 已将原 Home-specific Background 提升为 Context-owned 多 provider Background，并接入可逐出的昨日 Memory entry。Catalog/entry 显式携带 owner、source 和 evictable 语义，Context 在同一 Turn Business Day 下聚合 provider 并校验 Link 唯一性。

## 设计目标

1. 三段语境（BackgroundContext、TurnTraceHeap、WorkingContext）各自职责清晰，状态变更入口收敛。
2. MessageStack 采用构造式组装：每次 LLM Task 单独构造，区段顺序服务提示缓存的稳定前缀。
3. 语境变更不由模型输出直接驱动：Control Tool Calls 先归一化为信号，再由 Context 整批解析、投影验证并提交可行变更。
4. 用户轮执行中的追加输入进入语境有明确的暂存与合并语义。
5. 语境压缩作为 Runtime 恢复例程的服务方接入，流程遵循统一的陷入协议。

## 语境状态模型

语境分为三段，另有一个本轮输入列表。四者都是 Turn 内的可变持有者：内部条目使用不可变对象，变更只通过受控入口进行。变更入口只有两类：信号消费和 Turn 生命周期（开始、结束与异常放弃）。ContextEngine 不向 loop 暴露这些可变持有者，只提供背景链接、工作台快照、轨迹摘要等只读投影；状态持有者类型作为模块内部散件服务于实现与单元测试。

### BackgroundContext

用户轮开始前的背景。BackgroundContext 由 Context 所有，是可聚合多个内容模块的通用 Phase1 Background，不是 Agent Home 的内部容器。Session 在 Turn preparation 期间通过版本化全量快照注入当日跨 Turn 历史；注册的 `BackgroundEntryProvider` 分别提供自己拥有的默认条目、可加载目录和按 Link 正文。Home provider 提供 core 与 Home 顶层目录；Memory provider 只提供精确昨日的自动条目（如有），不把全部历史 Memory 加入 Phase1 目录。

`begin_turn` 清空上一 Turn 的 Session 与通用 Background；`abort_turn` 同样清空未完成 Turn 的 Background、provider catalog、Session、Working、Trace 和输入状态。preparation 先从所有 provider 原子重建默认/自动条目，再提交 Session snapshot。Phase1 动态加载项和昨日 Memory 条目都只属于本 Turn，不依赖 Context 内存跨 Turn 保留；跨 Turn 信息必须先进入 Session、Home 或 Memory 持久事实。SessionBackground 始终渲染在通用 Phase1 Background 之前。预算恢复可逐出 Phase1 动态来源和自动昨日 Memory，但不删除 `home:agent@core` 等不可逐出的默认规约。

### WorkingContext

本轮任务执行状态，即 Agent 的"工作台"。持有工作区资源描述（链接与摘要清单）、Manifest revision、里程碑与待办。普通 WorkingPatch 只管理里程碑与待办；Workspace 资源段只能由 `context.workspace.sync` 的完整 `WorkspaceSnapshot(revision, resources)` 替换，旧 revision 或同 revision 冲突快照收敛为局部结果。Context 只验证和渲染资源句柄，不读取 workspace 文件内容。

### TurnTraceHeap

本轮行为轨迹的规范存储。`TurnTraceHeap` 对 `TraceEntry` 保持 append-only 的完整记录，同时维护“热条目 + 冷节点头部”的可见投影。压缩不会删除 canonical entry，而是按完整 Cycle 边界把旧热条目移动到 leaf node；多个 leaf 可按 branch factor 合并为 branch node。模型通过 `context.trace.inspect` 从 `turn:trace@<turn_id>` 或 branch ref 逐层检查，通过 `context.trace.recall` 有界召回 leaf。recall 使用 zero-based continuation cursor；响应包含 `next_cursor` 与 `truncated`，调用额度会被配置的 `trace_recall_max_chars` 限制，因此同一不可变 leaf 可以分段继续探索。轨迹条目保持原子，不在消息 JSON 中间切断。召回结果携带 origin ref，并在下一次压缩时折叠回短指针，避免召回历史递归膨胀。

每条轨迹记录直接持有 llm 公共消息类型，并附带 Cycle、Phase、来源和可选 origin ref。用户输入由 PendingInputs 单独渲染，不作为普通 trace 条目保存。Turn 结束时 `seal()` 产生包含完整 entries、节点和 roots 的不可变投影，供 TurnSummary 与 Session 持久化使用。

### PendingInputs

本轮用户输入列表，包含初始输入与轮中追加输入。追加输入先进入列表暂存，由 loop 在安全边界触发合并：合并时只标记为已合并，不写入 TurnTrace。已合并输入作为独立的 UserInputs section 渲染为 user role messages，位置紧随 system identity。列表保留全量记录并进入 TurnSummary。当前不维护跨 Turn 的原始输入历史；后续若需要跨 Turn 回放，应先归纳为 BackgroundContext 或 memory，而不是把历史输入追加到当前 TurnTrace。

## MessageStack 构造

MessageStackComposer 按区段构造 MessageStack，顺序从稳定到易变：

1. system 段：Agent 身份与规约；
2. UserInputs 段：本 Turn 的已合并用户输入，通常在整个 Turn 内稳定，除非用户追加输入；
3. SessionBackground 段：Turn preparation 后固定；
4. 通用 Phase1 Background 段：每 Turn 从 Home、Memory 等 provider 重建，Phase1 可调整本 Turn 动态条目；
5. WorkingContext 段：低频变化；
6. TurnTraceHeap 段：冷节点头部在前，随后是热轨迹；
7. task prompt overlay：每次 LLM Task 不同。

这个顺序保证跨 LLM Task 的消息前缀尽量稳定，服务供应商提示缓存。

BackgroundContext、WorkingContext、UserInputs 与 task prompt overlay 均渲染为 user role messages；只有 identity 使用 system role。这样 system role 专注于最高层身份与框架规约，其他由 TinySoul 构造的状态段都作为本次模型任务的显式输入提供给模型。Provider 若对后置 system message 支持不同，不需要影响 Context 的语义顺序。

task prompt 由 TaskPrompt 表达，包含任务引导、任务输入与期望输出描述三部分语义。TaskPrompt 渲染为多条可切分 user messages：guide、domain HOW、task input、额外 task input blocks 和 expected output 分别可以成为独立 message。Phase2 的 overlay 可以携带按已选 action domain 组织的 HOW 引导内容（domain HOW）；引导内容由上层装配提供，Context 只负责拼装，没有内容提供方时该部分为空。

composer 在构造时执行语境预算检查。文本预算覆盖消息可见文本、JSON 片段、Assistant tool call 的名称/标识/参数、ToolResult 的调用关联与元数据，以及 Assistant reasoning 的文本内容、摘要和加密推理项，避免不可见协议数据绕过上下文预算；内联 `ImagePart` 使用独立的总字节预算，避免多资源 Prompt 绕过字符预算。任一预算超限都不在 Context 内部消化，而是作为模块边界失败交给压缩流程处理（见语境压缩）。

## 语境控制工具与信号

Context 定义 Phase1 可见的语境控制工具（Control Tools）：更新工作台（里程碑与待办）、加载 provider catalog 中的顶层内容、逐出可逐出条目。全部历史 Memory 不进入可加载 catalog；Context 中的 `<memory:YYYY-MM-DD>` 只提示模型使用 `memory.recall`。控制工具与 action 模块的域选择工具并列进入 Phase1 的工具作用域；域选择是 Phase1 的必选输出，语境控制是可选输出。

模型返回的 Control Tool Calls 不直接修改状态。ControlCallNormalizer 负责校验与归一化：合规调用转为状态信号，不合规调用收敛为局部结果（ControlResult），供上层记录并反馈模型。这一模式与 action 模块的行动调用归一化保持同构。

Context 的协议对象在构造边界维持自身不变量：`ControlResult` 校验标识、状态、阶段、序号和 JSON 载荷，`ControlNormalization` 与 `ContextSignalBatch` 只接受对应成员类型并冻结顺序，`TurnSummary` 校验 Turn 标识、唯一背景链接及所有快照/trace 的 JSON 安全性。配置 parser、signal codec 与直接 Python 调用因此共享同一组底层约束。

Context 消费的信号协议：

- `context.working.patch`：WorkingContext 变更请求；
- `context.workspace.sync`：Workspace 独占的版本化 Manifest 全量投影；
- `context.session.sync`：Session 独占、仅 preparation 可提交的版本化历史头部；
- `context.background.patch`：顶层内容加载与逐出请求；
- `context.trace.append`：轨迹追加请求，载荷为消息投影与元数据；decision/action result 的消息内容使用 `content` 多片段投影，支持 text/json，并可为 assistant decision 保留 provider-neutral Reasoning；
- `context.input.append`：用户追加输入。

Context 先从 SignalBus 取出一个绑定当前 Turn id 的 `ContextSignalBatch`。消费时逐条校验 signal 的 Turn frame，解析全部载荷，在投影状态上验证 Working/Workspace/Background 序列，并在任何状态修改前调用 lazy background loader 准备全部所需内容；准备阶段若触发 Home copy 或其它 Runtime 恢复，`ContextSignalConsumer` 在 Module frame 下重试同一批次，因此信号不会丢失且状态不会半提交。可行变更随后统一提交，局部失败按原始信号顺序返回。

Reasoning 的后续回放由 LLM 模块依据模型配置中的 `reasoning_keep` 和供应商能力决定：OpenAI Responses 只能把加密 reasoning item 作为可回放输入，summary 只是可观察摘要；OpenAI-compatible Chat 供应商若支持历史思考字段，则可在声明保留文本推理内容时回放 `reasoning.content`。Context 不在信号层把这些差异编码为分支。

## 语境压缩

压缩流程遵循 Runtime 统一陷入协议，并由 Loop 的压力恢复协调器按所有权边界执行：

1. composer 预算检查失败时抛出模块边界异常，由 context bridge 映射为语境压缩的 Runtime 原因；
2. `ContextPressureRecovery` 依据预算 payload 与目标比例计算带滞回的回收量；字符预算和图片预算分开处理，图片单独超限不会触发 Workspace 文件删除；
3. 首先折叠已召回 overlay，再按完整 Cycle 把旧热轨迹移入可恢复 heap node；其次逐出 Phase1 动态 Background，仍不足时逐出自动昨日 Memory；
4. 仍不足时，Workspace 只把显式标记为 `ephemeral` 或 `turn`、且未被当前 action `target_link`/`reference_links` 保护的资源移动到可恢复 Trash，并立即用新 Manifest 全量同步 WorkingContext；批次中途失败回滚已移动项，同步失败也尝试 restore；
5. 只有确实回收了可见字符才重试当前 Module/Phase；没有进展或恢复失败则结束 Turn，避免无效重试循环。

Composer 的预算异常携带各 section 的字符数和图片字节数，为恢复决策和诊断提供稳定依据。UserInputs、不可逐出的 Home core 和 WorkingContext 业务状态不会被无条件裁剪；自动昨日 Memory 属于可回收 Background。

## 失败与异常边界

Context 失败处理分三层：

1. 局部结果：模型控制调用不合规、信号载荷不合规，收敛为 ControlResult，由上层决定记录与反馈方式；
2. 模块边界异常：调用契约错误（ContextContractError）、内部不变量破坏（ContextInvariantError）、语境预算超限（ContextBudgetError）；
3. Runtime 语义异常：跨出模块边界的失败由 `failures.py` 的稳定失败枚举经 `tinysoul/runtime/bridge/` 下的 context bridge 映射——配置失败映射为启动失败，预算超限映射为语境压缩原因，其余默认结束当前 Turn。payload 只携带模块名、失败类型与摘要字段。

## 持久化边界

Context 维护 Turn 内内存态语境。Turn 结束时产出可 JSON 化的 TurnSummary，包含输入全量记录、工作台终态、Background 链接、轨迹摘要、provider-neutral 完整 JSON trace 和 heap 元数据。Context 不执行持久化；Loop 的 TurnCompletionPipeline 把 summary 与最终 output 交给 Session 持久化。

持久化读写不属于 Context 职责：workspace、Agent Home 与 Memory 的 Link、文件和运行机制由对应资源模块承担；Context 只通过注入的 provider、ActionResult 和已有投影模型消费内容。

## 组装入口

ContextEngine 是 Context 面向 loop 的装配门面，聚合状态持有者、composer、控制工具构建、归一化、信号消费、输入合并与压力回收服务；它只向上层暴露 compose、control scope、信号消费、trace inspect/recall/fold、TurnSummary、异常放弃 Turn 与只读快照/摘要，不暴露可变状态持有者。ContextEngineBuilder 在装配边界校验背景链接冲突、预算、heap chunk、branch factor、热条目下限、召回上限和压缩目标比例。Context action registrar 采用惰性公共导出，避免 Context 核心包反向 eager import Action 装配层。

## 设计范围

Context 的核心范围是语境状态模型、MessageStack 构造、语境控制工具语义、语境信号消费和压缩服务。

Context 不承担 LLM 调用、行动执行、运行控制流、workspace/Agent Home/Memory 文件读写或终端渲染。这些能力在对应模块中设计，通过 llm 公共类型、信号与 Runtime 协议与 Context 协作。
