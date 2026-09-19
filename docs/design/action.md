# Action 设计

## 定位

Action 模块负责 TinySoul 的行动语义、模型侧工具暴露、行动参数生成、行动执行和结果回放。

Action 不负责构造基础语境，不负责模型供应商适配，不负责运行时陷入控制。它依赖 `llm` 提供消息栈、工具消息和任务调用抽象，依赖 `runtime` 提供运行位置、信号和异常转移协议。

Action 的核心职责是把“可选择的域”和“可执行的动作”组织成稳定的 catalog，并把 Phase1 / Phase2 / Phase3 的行为切成清晰的边界。

Memory domain 通过 `register_memory_actions` 接入 `memory.memorize`、`memory.inspect`、`memory.recall`：活动记忆 patch、持久 Link 发现/探索和精确完整召回是三个不同 Action 边界。持久写使用同域内的 `memory.write_daily`、`memory.write`，只向 Memory Reflection 授权。domain 决定规划分组，不赋予服务权限。

## 设计目标

1. Phase1 只选择域，不暴露全部 action 细节。
2. Phase2 只在已选域内选择动作并生成参数。
3. Phase3 统一执行一批动作，支持并发、超时、hook 校验和结构化结果。
4. 所有 LLM 调用都基于语境模块构造的 `MessageStack`，Action 只追加临时任务提示。
5. Action 定义使用 TOML 存放，入口动态校验后尽早转换为内部类型。
6. 去掉旧设计中的冗余字段，保持模型侧可见描述和框架内运行配置分离。
7. 内置 Action Catalog 随 TinySoul 包版本发布为 init/reset 模板；运行实例只使用项目中物化的 catalog。
8. ActionResult 的 trace 生命周期由 Catalog 声明，业务 executor 只提供结果内容及必要的 compact projection 数据。

## 分层模型

### Phase1: 域选择

Phase1 面向模型暴露的是域，而不是 action 列表。

域的作用只有两个：

1. 让模型先判断当前任务应进入哪个工具选择方向。
2. 为 Phase2 限定可见 action 集合。

Phase1 暴露的工具是少量内部控制工具，例如：

- 选择一个或多个 action domain
- 请求加载某些顶层上下文
- 记录当前轮次的方向意图

Phase1 不输出二级 action 描述，也不直接提供 action 参数 schema。

### Phase2: 动作选择与参数生成

Phase2 只接收 Phase1 选中的 domain，并在这些 domain 内暴露具体 action。

Phase2 的输出不叫 draft。它就是一个规范化的 action call，已经足够进入执行阶段。

Phase2 面向模型暴露的 action 信息只保留两类内容：

1. 工具调用直接需要的结构：`name`、`description`、`schema`
2. 补充语义：`use_when`、`avoid_when`、`effects`、`examples`

Catalog 中的 action `name` 是 Action 模块的稳定 identity，并使用 dotted namespace 表达 domain 与 action 归属；它不是某个供应商请求中的原生 function name。Action scope、归一化、执行、结果回放和 prompt mount 始终使用该 identity，不在 Action 模块中清洗或重命名。供应商字符集、长度和碰撞约束由 LLM provider 适配层以请求内可逆映射处理。

`edge_cases` 不再由 action definition 承担，交给 hook 和执行结果表达。

### Phase3: 批次执行

Phase3 将 Phase2 产出的多个 action call 统一装配成一个执行批次。

Phase3 负责：

- 将框架内信息和业务参数拆开
- 对每个 action 执行输入 hook
- 按 batch 维度处理并发和超时
- 将每个 action 的执行结果结构化
- 等待 Action 收敛并整理 `ActionResult` 序列；Runtime transfer 出现时取消并收回同组工作，保留实际执行事实后原样传播。

Phase3 不保留长期运行或 ongoing Action。正常完成以成功、失败或超时结果反馈；取消、尚未执行和结果未知由独立的执行事实表达，不伪造模型工具结果。

ActionExecutor 统一提供异步执行入口。runner 拥有已启动任务直到其收敛：Action deadline 取消异步 I/O 并生成 timeout；Turn 取消保持取消身份。短本地 owner 调用通过 JoinedOperations 保留并等待 worker 结果，结果先交付 Trace，再传播取消；迟到的真实成功不改写为超时。

Home、Memory 与 Workspace Action 通过注入的 async Service 调用 owner；短文件操作由 ServiceScope 复用 Action 的 JoinedOperations，结果和通知先交付执行事实，再由 runner 传播取消。Workspace 的混合动作分为有界读取、异步 LLM、owner 提交；提交包含 Workspace snapshot 通知。Home 搜索只把文档读取放入短操作，rerank 仍为原生异步 LLM。Reflection 使用按用途授权的写服务，长进程使用受控 backend；不把含网络或长期进程工作的整个 executor 投入线程适配。

并行组按完成就绪处理任务；同一批同时失败按提交顺序选择主失败。未知 executor 异常、非法结果身份和 trace policy 错配由 Action bridge 转为模块失败；已知业务拒绝保持局部结果。RuntimeException 与 RuntimeTransferInterrupt 保持原身份，同批工作回收后传播。执行事实独立于模型视图提交，因此部分批次失败不抹去已提交结果。runner 不保留失联线程 grace 或“泄漏后继续”策略；受控进程的停止仍由进程 owner 负责。

## 定义结构

域定义保持很薄，只服务于 Phase1 的方向选择。域默认运行配置不进入模型可见语义，只作为具体 action 的运行配置合并来源。

具体 action 定义分为四个语义层次：

1. 模型侧工具协议，用于构造 Phase2 可见工具。
2. 模型侧补充语义，用于帮助模型判断何时使用或避免某个 action。
3. 可见性与框架内运行配置，分别控制情景选择和超时、并发、hook、结果 trace 生命周期。
4. 后端执行配置，用于描述真实执行落点。

模型侧补充语义不参与执行控制。环境影响语义只描述只读、新增或修改。

后端只负责执行实现，不负责模型侧解释。`llm_action` 只表示动作内部还需要一次受控 LLM 调用，不意味着 action 退化成 prompt 拼接逻辑；公共调用能力由 action 层共享服务提供，业务 executor 仍负责自身 action 语义。

### Activation 与 Runtime Support

一份 catalog 由 `assets/common/configs/action/catalog` 提供项目模板，按 domain/action 独立 TOML 维护。运行时通过 ConfigDocumentSet 加载项目定义；三个情景共用同一候选文档，不额外读取 Reflection 包资源。`visibility` 按动作当前情景、域当前情景、动作 default、域 default、true 的顺序选择首个配置值。domain 是可覆盖默认值。`runtime.enabled` 和 loop/reflection 中的平行开关表已删除。

配置 activation 与当前 Generation 的 runtime support 是两个独立事实：Capability 或其它业务
owner 负责依赖、凭据、服务和 executor，并在不支持 Action 时通过
`mark_actions_unsupported()` 明确声明；隐藏 Action 不能跳过 owner 的装配校验。最终关系为：

```text
available = granted && visibility && supported
```

Builder 因此保留 configured catalog、exact include view、supported identities 和 effective catalog。
Phase1/Phase2、执行 identity、executor 完整性校验与 Home prompt mount reconciliation 只消费
effective catalog；设置与 Endpoint 投影遍历 configured catalog，使关闭或暂不支持的 Action 仍可读。
授权来自代码中的动作身份与执行绑定注册。可编辑 handler 不能借用其它动作的执行能力，catalog 成员身份不会自动成为授权。显式启用未授权的情景动作、未知情景或未声明动作均在候选边界拒绝。配置查询按情景返回选择来源、granted、supported、available 和不可用原因，候选校验覆盖三个情景。

## 执行语义

### 输入

一次 action 执行输入分两层：

1. 框架内信息
2. 模型生成参数

框架内信息描述调用关联、批次关联、运行位置、超时边界和所属域。模型生成参数只保留 action schema 对应的业务参数。

`ActionExecution` 是 Phase3 的自包含执行输入：它同时携带已解析的 `ActionSpec`、规范化后的 `ActionCall` 和 `ActionFramework`。runner、hook 和 backend executor 不再在执行时重新查询 catalog；catalog 一致性在 builder/engine 准备阶段完成。

行动调用使用 TinySoul 归一化后的模型侧 tool call id 作为后续工具结果回放的相关性字段；执行期另有框架内部观测标识，用于 trace 和调度。

### Hook

每个 action 可以复用通用 hook，也可以定义专用 hook。hook 按 action 生命周期分为 normalize hook 和 execution hook。

normalize hook 发生在 Phase2，用于检查模型侧 action tool call 是否能成为 ActionCall。schema 参数检查属于内置 normalize hook，默认对所有 action 启用；action 也可以追加自己的 normalize hook，用于检查参数组合、链接格式或领域约束。

execution hook 发生在 Phase3，用于检查 ActionExecution 是否可以真实执行，例如工作区状态、资源存在性或运行上下文限制。

每个阶段内 hook 顺序为：

1. 全局 hook
2. domain hook
3. action hook

hook 只做输入检查、上下文约束和可执行性裁剪，不执行真实动作。

hook 失败应转为结构化 action result，而不是直接升级成 Runtime 陷入。`HookOutcome.success()` 只表示放行，不能携带 payload/frame data，也不产生独立结果；实际 action call 最终仍恰好收敛为一个执行结果。普通拒绝由 `HookOutcome.failure` 直接携带完整 `ActionLocalFailure`，可选 payload 只承载模型可见的有界业务数据，可选 frame data 只承载诊断；`failure is None` 即通过，不再维护平行 `ok` 或 `model_feedback` 状态，也不提供从 primitive feedback 猜测失败 scope/disposition 的工厂。`reject` 在运行时要求 typed failure，`HookOutcome.frame_data` 禁止携带 pipeline-owned hook identity 或 failure/reason/scope/disposition/feedback/constraint 等重复失败事实。pipeline 校验 hook 的实际返回类型，并把 failure/payload/frame data 一次性映射到最终 `ActionResult`；非 `HookOutcome` 返回与普通实现异常一样收敛为既有阶段 hook failure。pipeline 最后写入真实 hook identity，不能以通用 rejected reason 覆盖 owner failure，也不能让 owner frame data 覆盖注册身份。注册缺失和 hook 实现异常由 pipeline 自己构造 typed failure，不产生第二个反馈字段。

这里的 hook 失败只指普通拒绝、注册缺失或实现异常。hook 抛出的 `RuntimeException` 与 `RuntimeTransferInterrupt` 已经表达全局恢复或运行转移，normalize/execution hook pipeline 必须原样传播，不能降级为局部 ActionResult。

normalize hook 的未知 hook、hook 自身异常和 hook 拒绝都收敛为 normalize 阶段的 ActionResult。execution hook 的未知 hook、hook 自身异常和 hook 拒绝都收敛为 hook 阶段的 ActionResult。

### 批次执行

Phase3 使用 map-reduce 风格执行：

- map：每个 invoke 独立执行
- reduce：只负责等待收敛并整理 `ActionResult` 序列

Batch 只是执行编排容器，runner 的核心输出是 `ActionResult` 序列。

单个 action result 只收敛为三类：

- `success`
- `failed`
- `timeout`

批次内允许部分成功，但不需要额外定义 batch result。

Phase2 的模型侧 action tool call 即使无法归一化，也必须产出局部 ActionResult。因此一个 action tool call 在 Action 模块内总是对应一个局部结果：normalize failed、prepare failed、hook failed、schedule failed、execute failed、timeout 或 success。

上述局部收敛规则不包含 Runtime 控制异常。并行 worker 一旦产生 Runtime transfer，批次不再为未完成 sibling 伪造局部 ActionResult，而是先执行取消清理，再把同一个控制异常交回 Runtime 边界。

超时结果有两类来源：runner 发现 deadline 已过并给出 timeout；后端执行器在自身边界内发现 timeout 并给出 timeout。超时后的成功结果必须改判为 timeout，避免越过 deadline 的副作用被当作正常完成；超时后的失败结果可以保留 failed，因为失败信息通常比 timeout 标签更有利于下一 cycle 修正。

无法绑定到具体 action tool call 的阶段性框架问题不伪造成 ActionResult，而是产出 phase-level result，供 Context 记录为 cycle phase 执行反馈。

### 输出

Action result 需要同时表达三类信息：

1. 给模型看的反馈
2. 框架内状态
3. 执行可观测数据

结果中应保留：

- `result_id`
- `call_id`
- 成功/失败/超时
- 所处阶段
- 原始 call 顺序 `sequence`
- 可选的 `invoke_id` / `batch_id` / `domain`
- 结构化 payload
- 可选的 typed `ActionLocalFailure(reason, scope, disposition, feedback, constraint)`
- frame data

大块文件内容、隐式整文件内容和无界文本不直接塞回结果，改用资源句柄或摘要。明确 inspection action 可以返回受 owner 配置硬限制的文本片段；这类正文必须使用 foldable trace 生命周期，不能成为 Session 持久化正文。

`ActionResult` 是具体 action call 的局部事实记录，不等同于 LLM message。Action phase result 是 action 模块某个 phase 的局部执行记录，用于表达无法绑定到具体 action call 的框架性问题。

`ActionResultRenderer` 负责把 action result 渲染为：

1. 给模型看的统一 `action/status/stage/payload?/failure?` envelope；
2. 给 trace/log 使用的同一 envelope 加执行标识和 frame data；
3. 可由 Context 加入下一 Cycle MessageStack 的 visible/canonical `ToolResultMessage`。

Renderer 不是失败事实源，不从业务 payload 或 frame data 推断失败。`ActionResult.failure` 是 failed/timeout 的唯一通用失败事实；success 禁止 failure，failed/timeout 必须携带 failure。payload 只承载业务数据，frame data 只承载诊断，因此不存在 `payload.failure`。`ActionResult`、`ActionResultEnvelope` 和 foldable `ActionTraceProjection` 在构造边界拒绝业务 payload 顶层 `failure`；`HookOutcome` 在更早的 hook owner 边界执行同一检查，避免重复失败事实进入 pipeline。

Context 模块决定渲染结果如何进入 TurnTraceHeap；Action 模块不直接维护 MessageStack。Catalog 的 `[runtime.result] trace_mode` 只支持 `standard` 和 `foldable`：standard 的 visible/canonical message 相同；foldable 只允许成功结果提供非空 `canonical_payload` 和有界、去重的 `origin_refs`。Renderer 构造的 canonical message 保留完整 Action envelope，只替换 envelope 内的业务 payload；完整 payload 作为当前 Turn visible overlay。Context 压缩统一移除 visible overlay，不修改 canonical message。Turn 结束时 Session 从已验证 call/result 投影不可变业务事实，不保存 ToolResultMessage 或完整 Context trace。standard action 返回 projection、foldable action 缺少 projection或 failed/timeout 携带 projection，均由 runner 收敛为局部 trace-policy mismatch。

Catalog 只声明生命周期策略，不能从任意 JSON 自动推断 canonical 字段。业务 payload 的投影选择属于 executor；Loop 只把已验证的完整 visible/canonical message 转成 Context signal。`core.context.inspect`、`workspace.read` 和 `workspace.search` 共用该框架生命周期；各 owner 只在 executor 边界形成自己的紧凑 canonical payload。

Phase-level result 没有模型侧 tool call id，因此不渲染为 ToolResultMessage，只渲染为普通模型反馈 payload 或 trace payload，由 Context 写入对应 phase 的执行记录。

### 失败与异常边界

Action 模块的正常执行流不应把可反馈失败暴露为普通异常。能够绑定到具体 action tool call 的问题应收敛为 action result，例如参数无法归一化、normalize hook 拒绝、batch prepare 阶段某个 call 无法装配、execution hook 拒绝、executor 失败、executor 返回错配结果和超时。

无法绑定到具体 action tool call、但仍属于当前 Action phase 局部流程的问题，应收敛为 phase-level result，例如 Phase2 无法准备可用 action scope，或 Phase3 的批次准备出现无法归因到单个 call 的问题。Context 模块可以把这类结果记录为当前 cycle phase 的执行反馈，并在后续 message stack 中按需呈现给模型。

防御性不变量异常和模块调用契约错误不属于可继续的 action flow。它们表示 Action 模块内部对象关系、catalog、执行输入或公共边界被破坏，应在模块公共边界通过 Runtime bridge 映射为 Runtime 语义异常，由 Trap 决定结束当前 Turn 或采取其他运行转移。Action bridge 位于自身 runtime_bridge.py，区分调用契约与内部不变量。Runtime payload 只携带模块名、稳定失败类型和必要摘要，不携带原始异常文本、大块上下文或完整消息栈。

因此 Action 失败处理分为三层：action call 级局部结果、phase 级局部结果、Runtime 语义异常。前两者服务于 Context 记录和模型反馈，后者服务于运行控制流。

## 后端执行

### native

`native` 后端表示 owner-specific executor 在宿主中执行，handler 精确绑定显式注册的 ActionExecutor。执行统一 async；网络/模型等待原生取消，短本地 owner 操作通过 JoinedOperations 完整 join 后交付真实结果。长工作必须使用受控进程，不能用不可停止线程越过 Action/Turn 生命周期。Runtime 控制异常原样传播，普通请求失败由 owner 返回结构化 ActionResult。

### subprocess

`subprocess` 后端表示 Action 内必须同步收敛的受控进程生命周期，不提供从 Catalog options 直接执行命令的通用 executor。Capability-owned executor 或 service 只能为固定 worker 构造显式 `ProcessRequest`，禁止 `shell=True`，也不能把模型参数直接拼为 argv。结构化请求可以由 owner 编码为 stdin，worker 的响应协议、失败映射和后续业务提交仍由 owner 校验。

进程启动、stdin、stdout/stderr 字符投影上限、deadline 和取消回调由内部 `ControlledProcessRunner` 统一实现；真正的进程树终止、fallback kill 和短暂回收等待属于 `ManagedProcess`，由 `ManagedProcessOptions.termination_wait_seconds` 集中配置，默认 1 秒。stdout/stderr 直接捕获到临时文件，进程结束后只读取有界 UTF-8 前缀与 truncated 标记，避免宿主内存聚合完整输出；这不是子进程硬输出配额。Windows 使用 `taskkill /T /F`，POSIX 使用新 session/process group。Resource 与 Web 等需要在进程前后执行协议校验、staging 或 commit 的 executor 复用同一 runner，并各自把 outcome 映射为所属业务的 ActionResult。

### Turn Job

execution 的 native Action 调用同一 ProcessJobBackend：run 等待当前 Job 收敛，start 返回身份供后续 Cycle 监督。JobRegistry 拥有受理、终态、容量与 Turn 回收；kernel/action 不另设 supervised_process backend kind，也不保存 capability manager、mirror 或候选提交状态。等待、状态和停止复用 core.wait/core.job.*，collect 只读结果。Action worker 与 Job backend 都使用 infra/process 的受控进程原语，进程行为的业务解释仍在各自 owner 边界。

### llm_action

`llm_action` 表示 action 内部还需要一次受控 LLM task。它仍处于 `ActionExecutor` 语义内：Phase3 执行具体 executor，executor 在自身业务边界构造 `TaskPrompt`，再调用 action 层共享的 `LLMActionTaskRunner`。共享服务位于 `tinysoul/kernel/action/backends/llm_action.py`，负责集中处理 Phase3 自动 skill、Context message stack 构造、`LLM_ACTION` task 调用、回答形态解释和局部失败归一化；业务 executor 不直接拼供应商请求，也不直接读取 Agent Home 文件。

`llm_action` 的业务参数使用 `TaskPrompt` 的 PromptBlock-only 协议。`guide_blocks`、`input_blocks` 与 `output_blocks` 都由 `{label?, text}` 块组成，并可分别渲染为多条 `PromptBlock`。通用 LLM action 只接受 `reference_links` 作为 Phase2/Phase3 边界上的只读资源链接，由注入的 `PromptReferenceResolver.resolve_reference(link)` 解析为临时 `PromptBlock`。Workspace-owned LLM action 由 Workspace 模块提供 executor：修改类 action 接收 `target_link` 和 `reference_links`；分析类 action 可以只接收 Phase2 已选择的明确 `reference_links` 与意图。二者都在 action 内部加载正文并调用共享 LLM action 服务，不把正文作为 Phase2 参数。新增动作必须直接使用 block/link 协议。

`home.top.search` 是 Home-owned native action，其 executor 调用 Home search service，并使用注入的专用 `LLMHomeSearchReranker` 完成候选重排；它不使用通用 `llm_action` backend，因为确定性候选、candidate-only validator 和 fallback 都属于 Home 搜索业务语义。Action 层仍只负责执行 catalog 中的 handler 和承载结构化结果。

Memory 的三个 native action 都只调用 `MemoryEngine`：memorize 在 Memory owner 边界 patch Session root 内的活动 `Memory.md`；inspect 以 query 或已知五类持久 Link 执行 lexical/grep/正向引用/backlinks/可选 semantic 的有界发现；recall 只按精确 `memory:daily|entity|concept|fact|note/<cite>` 返回完整 Markdown 和 redirect chain。inspect/recall 使用 foldable trace projection 记录 origin Link 与有界 canonical facts，不修改 Background；memorize 提交后发 Signal，在下一 Context 边界刷新本轮 current 视图。Action 模块不解释 Memory 物理路径、文档关系或 Reflection mutation。

Phase3 action-internal LLM task 会自动追加 domain skill 与 action skill guide blocks。Action 层只依赖 `ActionSkillProvider` 协议；Agent Home 可提供 `HomeActionSkillProvider`，但 action executor 不感知 Home 目录结构。`skills_domain` 与 `skills_action` 属于局部自动 prompt 挂载机制，不进入普通渐进式加载，也不由 `home.resource.read` 按需读取。

嵌套 LLM task 禁用模型侧工具调用，但回答协议由 action 语义决定。`run_json` 服务结构化业务结果，例如 `core.reason`、`core.answer` 和 `workspace.analyze`；`run_text` 服务将完整模型文本作为暂态工件交给 owner 的 write/commit 边界。文本工件只在 Phase3 executor 内存中存在，不能先包装成 ActionResult 再从 Context 取回；owner 成功提交后只返回资源 Link、大小、摘要等元数据，具体完整性字段由有消费者的 owner 协议决定。LLM task failure 或回答形态不匹配收敛为 execute 阶段局部 `ActionResult`；Context 模块边界错误通过 Context bridge 转换，Runtime 控制异常继续传播，未完成文本不会提交。内部 Task 使用 `REQUEST_RECOVERY`；Context 预算与 LLM 容量原因原样交给恢复协议，恢复只重放当前未提交调用，不重复之前已完成的 Action。没有 Workspace 压力删除或无消费者的资源保护字段。

`llm_action` backend options 由 backend kind validator 在 Catalog 构建边界统一校验：`max_output_tokens` 覆盖 `LLM_ACTION` profile 的 provider 生成上限，`max_output_chars` 限制 `run_text` 接受的完整工件字符数。前者属于 LLM 调用与上下文窗口预留，后者属于 action 工件边界；两者都不控制 ActionResult 进入 Context 的大小。结构化业务输出仍由 executor 校验自己的字段和结果预算，ActionResult trace 继续服从 Catalog 的 standard/foldable 生命周期。

LLM task failure 由共享服务映射为 `ActionLocalFailure`，再由 renderer 作为 envelope 顶层 `failure` 投影。`retry_same` 可以在 disposition 允许的瞬态或可恢复条件下重复同一参数；运行时不把重复参数判为错误。`change_request` 要求改变 `scope` 指出的限制条件；`use_fallback` 要求改变真实生成/执行路径；`stop` 表示当前配置不可继续。该协议不自动调度重试，也不把 provider 或诊断异常暴露给模型。内置 `core.reason` 由 `tinysoul/kernel/action/builtins/core/actions.py` 提供，作为通用推理动作，只接受 `reference_links`；内置 `core.answer` 同样由 Action builtins core actions 提供，作为 User Turn 正常完成动作，要求内部 LLM task 返回包含字符串 `text` 的 JSON object，并可把使用过的 `reference_links` 一并返回为来源链接。它既可以交付当前成果，也可以在后续工作依赖用户时提出问题、请求确认、申请进一步指示或请求路线选择；成功只表示当前 User Turn 已产生正式响应，不表示整体多轮目标或 WorkingContext todos 已完成。Workspace 的 write/edit/append 表达明确内容写入、精确编辑和追加，compose 负责模型生成新建或替换；`workspace.analyze` 仍返回经过 executor 验证的结构化结论。Phase3 在外层 ActionResult 产生前就可能启动嵌套 task，因此 LLM provider 适配器不能把当前未完成的 Phase2 tool call 当作完整 provider-native history 回放；当嵌套 task 禁用工具时，已完成的 ToolResultMessage 也只作为普通上下文文本传入。

`llm_action` 后端只表达“动作内部需要一次模型推理”，不拥有独立语境，也不绕开 Context/LLM 模块的调用协议。外层 Action control 通过 LLM task cancellation contract 传入；`LLMActionTaskRunner` 从 owner 剩余时间中固定预留 5 秒，让内部 Task 在 owner deadline 前完成取消、失败归一化和 executor 返回，再把扣除后的剩余时间交给 LLM runner/provider request timeout。Task 成功返回后，runner 在把结果交给领域 executor 前重新检查同一 cancellation，从而阻止迟返工件进入 Workspace mutation；迟返失败仍保留原 Task failure。预留窗口到期映射为普通 `execution_timeout/action.timeout`，不向模型暴露 backend、provider 或线程事实。

项目配置 `[action.llm_action]` 包含 `timeout_seconds`、`default_task_profile` 和 inline-table
`overrides`。timeout（默认 600）只填充未声明专用超时的 `llm_action`；具体 Action 的 runtime
值仍可覆盖通用默认。`LLMActionProfileResolver` 先按完整 Action ID 查 override，再回退 default
profile，并把字符串 profile 交给现有 LLM task runner。候选 AgentConfigPlan 构建时，Action
模块会把 override Action ID 对照当前候选 project catalog，要求 backend kind 为 `llm_action`；App 再用
LLM `TaskSpecTable.profiles()` 协调 profile 引用。unknown Action、非 LLM Action、unknown
profile 和重复 override 都在文件提交前形成 Action-owned `ConfigError`，不会推迟到执行期。

`max_output_tokens` 是具体 action 或 owner 选择的 provider generation budget；最终 artifact boundary 由拥有提交语义的 owner 决定。Workspace compose 不在 Catalog backend options 中重复声明字符或 token 上限，而是统一使用 `workspace.max_write_chars=12000`，并在 task 与 commit 两侧共同校验。超过上限应按任务状态选择自然片段、`workspace.append` 或 精确 `workspace.edit`，而不是重复同一路径的无界重试。其它 Action 继续使用所属 Catalog runtime 边界；该机制不是对供应商不可中断网络请求的硬停止保证——Turn 取消令牌可放弃本地等待并丢弃迟到结果。

## 组装入口

`ActionEngine` 是 action 模块面向 Loop/Context 的唯一调用门面，位于 `tinysoul/kernel/action/engine.py`。它以私有字段持有 catalog、scope builder、normalizer、execution builder、runner 和 result renderer，不把内部组件作为公共状态暴露，不改变结果模型，也不引入 batch result。

上层模块应通过 `ActionEngine` 获取 action scope、执行批次和结果渲染，不直接调用 action 内部 builder、runner 或 renderer。`ActionEngine` 提供 action result、phase result 与 tool result replay 的渲染门面；renderer 仍是模块内部组件，用于保持结果模型和模型回放格式集中。

Action 顶层包同时暴露业务模块实现 executor 所需的公共 SPI：`ActionExecution`、`ActionExecutionContext`、`ActionExecutor`、Action 结果类型和模块错误基类。Workspace、Home、Memory 与 Loop 只从顶层包引用这些协作类型；catalog 负责定义与 schema，planning 负责作用域/参数归一化/渲染，execution 负责批次准备、hook 与调度；call/result 保持跨子系统公共协议，内部散件只服务 Action 与对应测试。公共 SPI 不取代 `ActionEngine` 的调用门面，上层仍不直接调用 runner、hook pipeline 或 execution builder。

`ActionEngine.domain_names()` 与 `action_identifiers()` 提供只读 catalog identity snapshot，供 App 在装配期把 domain/action 逻辑 prompt mount 交给 Agent Home reconciliation。该接口不暴露可变 `ActionCatalog`、tool schema 或 executor registry；Action 不解释 Home 路径，Home 不读取 catalog TOML。

`ActionEngine.catalog_json()` 提供当前 Generation 的完整配置展示投影：Domain/Action 模型可见
语义、effective runtime、backend contract、availability，以及指向项目 document source/local path
的编辑绑定。投影以 configured catalog 为基准，分别返回 effective `runtime.enabled`、
`enabled_source`、owner `supported` 和最终 `available`；配置关闭或 owner 暂不支持的 Action 仍可读。
Domain 同样返回默认 enabled 及其 provenance，`available` 仍表示至少存在一个 effective 子 Action。
投影不暴露 executor 或 prompt，也不重新读取文件。

`ActionCatalogLoader.load_documents()` 负责从 Infra 提供的候选 `ConfigDocumentSet` 解析
`LoadedActionCatalog`，并复用 package template 测试所用的同一个 `ActionTomlParser`。加载结果同时
保留 Domain 默认 runtime、Domain/Action enabled 来源、Action timeout 来源与稳定 document binding。backend kind validator 在
加载边界校验 options。`ActionEngineBuilder` 只接收已经校验的 `ActionCatalog` 或
`LoadedActionCatalog`，负责注册 executor/hook、support 与 activation 求交，并在 build 阶段校验
effective catalog 中所有 handler 都有 executor；它不再隐式打开 package 或项目路径。registrar 不修改 tool
schema，项目 Action TOML 是模型参数 contract 的唯一事实。

## 情景动作策略

ActionPolicy 从同一 domain/action TOML 的 visibility 读取选择，按动作情景→域情景→动作 default→域 default→true 取首个已配置值。domain 是可覆盖默认值；TurnProfile 不维护平行选择表。最终集合为 grants、visibility 与 backend support 的交集；显式越权启用在候选配置阶段拒绝。每个情景生成独立 immutable catalog 视图；Phase1、Phase2、normalize、prepare_batch 与 run_batch 使用同一有效集合。执行入口复验 ActionSpec，伪造 handler 或借自其他情景的批次在副作用前拒绝。

## Action Schema

Action tool schema 使用 TinySoul 支持的 JSON Schema 子集。加载 TOML 时必须检查 schema 自身，运行时再校验模型生成参数。

当前支持的 keyword：

- `type`
- `description`
- `properties`
- `required`
- `additionalProperties`
- `items`
- `enum`
- `minimum`
- `maximum`
- `default`

`minimum` 与 `maximum` 只用于 `integer`/`number`，schema 定义边界和运行时参数都必须满足数值关系。`default` 是模型可见的 JSON Schema 注解，其值必须通过所在 schema；通用参数校验器不负责向缺失参数注入值，需要默认行为的 Action owner 从同一有效 `ActionSpec` 编译 typed policy 并由 executor 消费。等待 Action 校验正数时限并返回意图，实际计时与恢复由 Loop 负责，不在 executor 内阻塞。

当前支持的 type：

- `object`
- `array`
- `string`
- `number`
- `integer`
- `boolean`
- `null`

不支持的 keyword 必须在加载期抛出配置错误，避免 action TOML 写了 schema 但运行时静默忽略。

## LLM 调用原则

所有 LLM 调用都从语境模块已经构造好的 `MessageStack` 出发。

Action 只负责追加临时 task prompt overlay，不重新发明消息栈。

因此一个 action 相关的 LLM task 由两部分组成：

1. 上层语境提供的 base message stack
2. Action 追加的 phase-specific task prompt

Phase1 和 Phase2 只是在这个基础上选择不同的工具作用域和不同的 prompt overlay。

## 目录组织

`tinysoul/kernel/action` 保存通用执行机制、契约与 core executor。catalog/planning/execution 分别负责声明编译、意图准备与批次执行；共有 call/result 协议不归某一个执行实现私有。领域 executor 仍随 owner 发布。

所有 domain/action 文档集中于 assets/common/configs/action/catalog，初始化按普通模板复制。运行实例从项目 ConfigDocumentSet 加载，重复身份、域不匹配和未知配置拒绝。三情景共用定义、候选编辑与 reload，没有 Reflection loader 或专属 domain；home.diff/review 与 memory.write_daily/write 通过情景 grants 和受约束服务开放。配置查询显式选择情景。

### TOML catalog

每个 domain 一个目录，目录下放：

- `domain.toml`
- `actions/*.toml`

`domain.toml` 放域描述和域级默认运行配置。

`actions/*.toml` 放具体 action 定义。

TOML 描述模型侧工具协议、补充语义、visibility、执行配置和后端绑定，不放 Python 业务实现。backend.kind 为 native/subprocess/llm_action；handler 是显式 executor 注册键，例如 core.answer 或 workspace.list。

### Python executor 与业务归属

`tinysoul/kernel/action/backends` 只放通用执行机制，不放具体业务动作。`tinysoul/kernel/action/builtins` 只放 Action 模块自己拥有的内置动作实现，例如 `core.reason` 与 `core.answer`。Workspace、Agent Home、Memory 等有独立业务模型、链接语义、持久化或 runtime/trap 生命周期的模块，Action 集成保留在所属模块的 `actions.py` 中，并通过 registrar 注册到 `ActionEngineBuilder`。

`actions.py` 是模块与 ActionEngine 的集成边界，不等同于业务逻辑容器。它可以包含 `ActionExecutor` 实现类、模型参数解析、局部失败到 `ActionResult` 的映射、信号发送和 `register_<domain>_actions` registrar。executor 类名仍使用 `*ActionExecutor` 后缀，以明确它们实现 `ActionExecutor` 协议；registrar 使用 `register_<domain>_actions` 命名，例如 `register_core_actions`、`register_workspace_actions`、`register_home_actions`、`register_memory_actions`。真实业务规则应继续下沉到 engine/service/client/evaluator 等文件，避免 `actions.py` 变成业务大杂烩。

轻量业务能力不应全部堆入 Action executor 目录，也不必升级为 Workspace 级顶层模块。数学计算、网页搜索等能力在真实 action、边界和测试都明确后放入 `tinysoul/plugins/capabilities/<capability>`：业务逻辑放在该能力包的 service/evaluator/client 中，action-facing 代码位于该能力包的 `actions.py`，只负责参数解析、调用业务服务和映射 `ActionResult`，再由 registrar 接入 ActionBuilder。没有真实 capability 时不保留空包或空 action。Action Domain 服务于 Stage1 的大致方向选择，可以覆盖多个 Capability，也不要求与 handler owner 正交或一一对应；Resource conversion 因操作对象并入 Workspace，Script/Shell 因任务方向合并为 Execution。进程 backend 作为执行机制存在，不意味着向模型提供未受限的任意 shell 或 inline script action。

### 继承规则

加载器按以下顺序合并：

1. 内置默认值
2. domain 默认值
3. action 定义
4. loader 明确定义的专用继承规则

项目 Action TOML 保存完整参数 contract；需要把 schema 解释为业务策略的 owner 必须在 Generation
编译阶段转换为窄的内部类型，不把宽泛映射留到执行路径，也不由 registrar 动态改写 catalog。

运行配置中的 hook 使用阶段化配置，分别声明 normalize 阶段和 execution 阶段的 hook 名称。domain 默认 hook 与 action 自身 hook 按阶段合并。

## 设计边界总结

1. Phase1 只选 domain。
2. Phase2 只在 domain 内选 action。
3. Phase3 统一执行批次。
4. Action 定义保持模型侧语义、框架运行配置和后端执行配置分离。
5. 正常执行收敛为 ActionResult；取消、未执行和未知结果由 typed 执行事实表达，不伪造工具结果。
6. 无法绑定到具体 action call 的 action phase 问题收敛为 phase-level result。
7. 防御性不变量异常通过 Runtime bridge 映射为运行时语义异常。
8. 所有 LLM 调用都基于上下文模块构造的 base `MessageStack`，Action 只追加临时 prompt。
