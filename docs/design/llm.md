# LLM 设计

## 定位

LLM 模块负责把 TinySoul 内部的模型调用请求转换为具体供应商 API 调用，并把模型输出转换为可解释的统一结果。

LLM 模块不负责从语境、状态、记忆或工作区中构造提示词。上层模块负责维护和选择语境内容，并把最终要调用模型的消息栈交给 LLM 模块。

LLM 模块可以表达 TinySoul 自己的模型侧工具语义，并负责将其映射到不同供应商的工具调用协议；工具调用结果如何被解释、提交、执行或写入语境，仍由上层模块负责。

## 边界

供应商、模型、任务调用和模型链应分开理解。

供应商表达外部 API 的接入方式，包括认证、端点、请求格式、参数差异、错误分类和响应归一化。供应商不决定某个业务任务应该使用哪个模型。

模型表达可被调用的具体模型、有效上下文窗口及其能力。上下文窗口是当前 provider endpoint、套餐与真实模型组合的部署规格，以 token 为单位显式配置；模型能力仍保持抽象但真实，例如文本输入、图像输入、JSON 对象输出、推理输出和提示缓存支持。上层选择模型时应面向模型规格与能力，而不是直接面向供应商。

任务调用表达一次模型请求。它接收上层已经构造好的消息栈、回答格式、工具作用域、调用参数和可选缓存意图，完成能力校验、模型选择、调用执行、重试切换和输出解释。

LLM 模块可以向上层暴露某个任务当前优先模型的能力和上下文窗口视图。该视图用于帮助上层决定是否构造图像内容、远程图片 URL 或其他能力相关输入。它表示下一次调用会优先尝试的模型，不承诺异常切换后的最终使用模型。

任务配置表达不同任务用途对应的调用设置、调用参数、候选模型顺序，以及失败后的重试和切换策略。链路切换的单位是模型，不是供应商。

模型侧工具表达一次 LLM Task 可以提供给模型的工具定义、工具作用域、工具选择约束、模型返回的工具调用意图，以及需要回放给模型的工具结果。模型侧工具属于模型输入输出协议，不等同于 TinySoul 的行动执行。Control Tool 的业务含义由 Loop、Context 或 WorkingContext 等上层模块解释；Action Tool 的业务含义由 Action 模块解释。

## 消息栈

TinySoul 内部使用自己的消息栈表达模型输入，而不是直接使用某个供应商的报文格式。

消息栈由有序消息组成。TinySoul 通用消息使用语义消息类型表达模型输入历史，包括系统消息、用户消息、助手消息和工具结果消息。系统消息、用户消息和助手消息表达常规对话内容；工具结果消息表达模型侧工具调用完成后的结果回放。供应商协议中的 role 只是适配层映射结果，不作为 TinySoul 内部消息模型的核心分类。语境分类应通过额外的来源或范围信息表达。

每条消息可以包含多个片段。LLM 模块表达文本和图像输入。纯文本调用只是只有一个文本片段的普通消息，不需要单独设计另一套简化结构。

消息内容可以包含由上层构造的结构化 JSON 内容。结构化内容在 TinySoul 内部保留为 JSON 语义，进入供应商请求前先渲染为模型可见文本。文本内容与结构化 JSON 内容可以合并为普通文本输入，JSON 以可读代码块呈现；包含图像内容时，再由供应商适配层映射为对应接口接受的多模态内容。这样上层动作层可以把动作结果、观察信息和结构化上下文交给 LLM 模块，而不需要手写 JSON 字符串。

助手历史消息可以携带推理内容和模型侧工具调用记录。推理内容不是可见回答，也不是动作结果；它用于上层在构造后续上下文时保留模型推理轨迹。工具调用记录表达模型曾经生成的工具调用意图，它属于助手消息的附带项。支持 Chat 形态推理回放的供应商可以把推理内容映射为对应的历史推理字段；不支持这种回放语义的供应商不应把它伪装成普通回答内容。

TinySoul 不把供应商原生工具调用结构作为通用消息语义。TinySoul 可以在 LLM 模块中定义自己的模型侧工具消息，用于表达工具调用意图和工具结果回放；供应商原生 `tool_calls`、`tool_call_id`、`tool` role 或 Responses `function_call` 只由适配层映射。工具调用记录保存在助手消息中；工具结果以独立的工具结果消息进入 MessageStack。工具、技能或外部动作的业务选择与执行属于上层模块，LLM 模块只返回归一化后的工具调用结构，不直接执行工具，也不修改语境。

TinySoul 标准图像输入是已经由上层准备好的图像字节和 MIME 类型。路径读取、文件缓存、权限和生命周期由上层模块负责。供应商适配层把标准图像输入转换为对应接口可接受的图像内容。

远程图片 URL 不是标准图像输入，而是模型额外能力。只有明确具备远程图片 URL 能力的模型，才应接收远程图片引用。这样上层可以区分“发送本地已读取图像内容”和“要求供应商访问远程资源”两种不同语义。

LLM 模块不接收文件附件。文件、PDF、网页、代码文件或其他资料应由上层工具或语境模块先读取、抽取、摘要或压缩，再以普通文本或图像形式进入消息栈。这样调用方不会混淆“原生文件理解”和“文件抽取为文本”两种完全不同的处理路径。

常规消息不承载语境来源、缓存范围或附件类别。来源追踪、预算裁剪和提示词组装属于上层语境模块；LLM 模块只接收已经组装完成、可直接发送给模型的消息栈。工具结果消息只表达工具调用结果回放，不表达工具如何执行，也不承担 Action Result 的业务存储职责。工具结果消息只承载状态、短文本或结构化摘要；图片、视频、文件和长内容等资源应由上层保存为工作区或其他资源句柄，并在后续 LLM Task 前重新构造为普通文本或多模态消息输入。

## 模型侧工具

模型侧工具用于约束模型生成结构化调用意图。工具定义包含工具名称、描述、输入结构、工具类别和可选供应商映射提示。工具类别至少区分 Control Tool 和 Action Tool。工具作用域表达本次调用提供给模型的工具集合和选择约束；选择约束可以限制可用工具名称，也可以要求模型返回的工具调用中包含某一个工具。强制工具选择必须与要求工具调用的工具使用策略同时出现。这里的强制工具选择是 TinySoul 的任务结果解释语义，表示返回结果中必须包含该工具调用，不表示只能调用该工具，也不要求供应商原生协议必须支持同名的强制工具选择参数。模型返回的工具调用是助手消息的结构化附带项；工具执行完成后，上层模块可以将结果构造为工具结果消息，拼接回 MessageStack。

Control Tool 是框架内部控制工具，主要用于 Phase1。它用于表达更新 WorkingContext、更新 BackgroundContext、选择 Phase2 行动等控制意图。Control Tool Call 不直接修改状态，而是在 Phase1 中被汇聚、校验、归一化，并转化为内部操作信号，由对应上层模块消费。

Action Tool 是智能体行动工具，主要用于 Phase2。Phase2 只暴露 Phase1 已选择 domain 内的 Action Tools，并结合 action 工具结构、补充语义和自动注入的 domain skill 生成行动参数。Action Tool Call 被归一化为 ActionCall，之后由 Phase3 装配和执行。

Loop 的 Phase1/Phase2 framework task 使用 `answer_format=NONE` 与 `ToolUse.REQUIRED`：阶段完成以结构化 Control/Action Tool Call 为准，不要求自由文本 answer。Provider 同时返回的 `raw_response.answer_text` 或 reasoning 可以保留在 trace 中，供观察和诊断使用，但不能替代工具调用、改变阶段边界或宣布 Turn 完成。

LLM 模块只负责模型侧工具定义、工具调用和工具结果在 TinySoul 内部结构与供应商协议之间的映射。供应商工具调用标识只在适配层用于相关性映射，TinySoul 内部应使用自己的调用标识，避免 Context、Action 或 Loop 依赖供应商私有标识。工具调用可以作为任务结果的一等输出，而不是把工具调用伪装成普通 JSON 对象。

工具名称同样以 TinySoul 内部稳定 identity 为准，可以保留 Action Catalog 使用的 dotted namespace，不受某个供应商 function name 字符集或长度约束反向塑形。OpenAI SDK 形态适配器为每个请求从当前可见工具、assistant tool-call 历史和 tool-result 历史建立无碰撞名称表：已经满足公共安全子集的名称保持不变，其余名称映射为最长 64 字符的可读临时别名。工具定义、历史调用和需要名称的结果回放必须使用同一张表，供应商响应在构造 `ToolCallRecord` 前解码回 TinySoul identity；无法在本次映射中识别的响应名称保持原值，继续由任务解释层按 ToolScope 形成局部失败，而不猜测映射。provider 临时别名不得进入 ToolScope、ActionCall、Context 或 trace。

MessageStack 可以在 Phase3 action-internal LLM task 构造时包含当前 Phase2 decision 的 assistant tool call，而对应 ActionResult 只有外层 action 执行完成后才会产生；这是真实的 TinySoul trace 状态，但不是一个已经完成、可以回放的供应商多轮工具交换。OpenAI SDK 形态适配器按有序 assistant turn 原子判断 provider-native replay：只有同一 AssistantMessage 的全部 tool calls 都在其后的连续 ToolResultMessage 中以唯一 call_id 和匹配 tool_name 完成时，才回放整个 call/result 集合；缺少结果、名称不匹配、重复 ID 或顺序不属于该 turn 时，整个 native exchange 都不发送。Context/trace 不删除或改写这些未完成记录，嵌套任务通过自身 action prompt 接收当前执行参数。当 `tool_use=disabled` 时，适配器不发送任何 provider-native tool call/result；带 tool call 的 assistant turn 连同其 provider-native reasoning 一并跳过，ToolResultMessage 则降级为带有工具名的普通 user context，以便嵌套任务保留执行反馈而不重新打开供应商工具协议。

支持原生工具调用的供应商可以由适配层映射到对应协议。若某个任务不使用供应商原生工具调用，也可以由上层把工具意图设计为普通 JSON 对象回答；这属于任务语义设计，而不是 LLM 模块的模型侧工具主链路。不同供应商之间切换时，应以 TinySoul 内部工具调用结构作为规范历史，供应商原生工具历史只存在于适配层映射过程。

当供应商原生协议提供类似强制调用某个具体工具的参数时，适配层不应直接把 TinySoul 的强制工具选择映射为该参数，除非两者语义完全一致。TinySoul 的强制工具选择允许同一次结果中同时包含其他工具调用；若供应商参数表示只能调用一个指定工具，则会错误收窄 TinySoul 工具语义。适配层应优先映射为供应商可表达的“需要工具调用”语义，并由任务解释层校验返回的工具调用是否满足 TinySoul 的工具作用域和强制工具选择约束。若框架任务因 provider 返回了其它可见工具而缺少强制工具，所属 Phase 可以把稳定的解释反馈带入一次有界重试，并临时收窄工具作用域；这属于 Loop 的局部恢复，不改变 LLM 模块的通用强制选择语义。

## 调用设置与任务结果

调用设置应区分回答格式和工具使用策略。

回答格式表达任务是否需要助手回答，以及回答应按纯文本还是 JSON 对象解释。工具使用策略表达本次调用是否禁用工具、允许工具调用，或要求模型至少生成一次工具调用。二者不是互斥关系：同一次任务结果可以同时包含助手回答和工具调用，也可以只包含回答或只包含工具调用。

供应商适配层先把模型调用结果归一化为统一模型响应。统一模型响应保留模型可见回答、模型侧工具调用、可选推理信息、用量、元数据、供应商原始响应信息和 provider-neutral `stop_reason`，但不表达某个任务如何解释这些内容。`stop_reason` 稳定区分正常完成、工具调用、输出上限、内容过滤、其它未完成与未知状态；供应商私有 finish/status 字符串只在适配层解释。

供应商响应解析应区分“模型输出不满足任务协议”和“供应商响应结构无法解释”。例如模型没有按任务要求返回必需工具调用，属于任务解释失败，可以形成局部 `TaskResult` 反馈；但供应商响应已经声明存在 function/tool call，却缺少工具名、调用 id、函数参数结构或出现 TinySoul 当前不支持的工具调用类型，则属于 provider 响应归一化失败，应以 `ProviderError(PARSE)` 表达，并由模型链切换与 Runtime bridge 按 provider 失败路径处理。

任务层再依据回答格式和工具使用策略解释统一模型响应。供应商原生 tool call 不携带 TinySoul 的 Control/Action 所有权；`ResponseInterpreter` 必须按本次可见 `ToolScope` 的同名 `ToolSpec.kind` 回填分类，并拒绝供应商或测试输入中与 scope 冲突的 kind。这样 Phase1/Phase2 的真实供应商响应与内存 FakeLLM 使用同一分类边界。任务结果同时保留统一模型响应、解释后的助手回答和解释后的工具调用，使调用方可以区分“模型返回了什么”和“该任务从返回中解释出了什么”。调用方应以任务结果中的助手回答和工具调用作为业务主入口，统一模型响应主要用于调试、追踪、重放和供应商差异分析。

任务结果需要表达成功和失败两种完成态。成功结果提供解释后的回答和工具调用；失败结果表示模型调用本身已经返回，但这次输出无法满足任务解释协议。`TaskFailure` 使用 LLM-owned `reason`、`scope` 和可选 `constraint` 表达稳定恢复事实，并以 `model_feedback` 提供简短错误反馈；`frame_data` 只承载有界诊断，不作为调用方解释 reason/scope 的协议。面向模型的反馈只描述本轮输出为什么不满足要求，不携带完整消息栈；完整消息栈仍由上层语境模块按当前状态重新构造。

任务失败结果属于 LLM 模块的局部结果，不表示运行时控制流必须改变。典型场景包括模型返回内容无法按任务要求解释、未返回必需工具调用、返回了不在工具作用域内的工具调用、JSON 对象回答无法解析，或 provider 明确声明本次生成因输出上限、内容过滤或其它未完成状态而停止。停止原因在回答解释前检查，因此截断的 JSON 或文本不能被误当作完整业务输出。调用方可以把稳定失败事实映射到自己的局部恢复协议，但 LLM 模块不自动重试一次已经成功返回却不满足输出协议的响应。

LLM 模块需要改变运行控制流的失败应通过 Runtime bridge 进入 Trap，而不是伪装成任务失败结果。典型场景包括模型链耗尽、供应商不可恢复失败、任务调用契约错误、配置错误和模块内部错误。进入 Runtime bridge 的 payload 只携带模块名、稳定失败类型和必要摘要；原始异常链只用于日志和调试，不成为上下文或 payload 协议。

因此 LLM 模块的失败边界分为两层：任务解释层的局部失败返回给调用方处理，模块边界层的不可继续失败映射为 Runtime 语义异常。两者都可以携带面向模型或框架的摘要，但只有 Runtime 语义异常会改变 Turn、Cycle 或 Program 的运行控制流。

LLM 模块内部领域对象和注册表不使用裸 `ValueError`、`TypeError` 或 `KeyError` 表达模块语义失败。调用契约问题统一使用 `LLMContractError`，注册表重复注册等内部不变量破坏使用 `LLMInvariantError`；配置和 provider 动态边界再分别转换为 `ConfigError` 或 `ProviderError`。`CallSettings`、`TaskCall`、`ModelChain`、`TaskSpec`、`ProviderRequest` 和 `PromptCache` 等核心请求对象在直接构造时校验类型、非空标识、正数限制、模型链唯一性与 JSON 安全性，使绕过配置 parser 的调用路径仍满足同一领域不变量。

LLM 领域对象自身也承担基础不变量校验。消息片段、消息栈、模型规格、供应商规格、工具定义、工具调用记录和任务结果等稳定对象，在直接构造时应拒绝空标识、错误成员类型和非 JSON 安全载荷，并以 `LLMContractError` 表达调用契约问题。配置解析器仍是配置动态边界，配置输入导致的领域对象契约错误应在 parser 边界转换为 `ConfigError`。

JSON 对象是 TinySoul 的主要回答结构化方式。供应商支持原生 JSON 输出时应使用原生参数；供应商不支持或能力未确认时，可以通过提示约束和本地解析完成兼容。本地兼容解析只规范化完整包裹响应的 Markdown JSON fence，之后直接交给标准库 `json.loads`；不扫描花括号、不从 prose 中猜测对象起点，也不忽略 JSON 后的额外文本。解析成功只表示模型回答可以被解释为对象，具体业务字段是否正确仍由调用方模块校验。解析失败属于一次 LLM Task 的失败结果，不触发模型链切换；调用方可以把失败结果中的模型反馈加入后续任务提示，或依据自身策略结束当前 Phase、Cycle 或 Turn。

模型侧工具调用是另一种结构化输出形态，适用于需要模型在有限工具集合中生成调用意图的任务。调用方模块应依据任务语义决定是否启用模型侧工具；无论使用 JSON 对象回答还是工具调用，业务字段和调用参数都需要在模块边界继续校验。

原生 JSON 输出和提示缓存属于供应商增强能力，不是默认必备能力。模型缺少这些能力时，请求仍应正常执行；适配层只是不传对应供应商参数，输出仍由统一解释逻辑处理。

JSON Schema 不属于当前核心回答格式。严格 schema 支持涉及供应商能力差异、参数映射和 schema 子集限制，不应混入 JSON 对象回答格式。

## 多模态

多模态能力以模型能力为准，而不是以供应商整体能力为准。

图像输入需要在调用前进行能力校验。支持时由供应商适配层映射为对应 API 结构；不支持时应清晰报错或要求上层转换输入形式。标准图像输入和远程图片 URL 分别对应不同能力。

一次调用的硬能力约束来自三处：任务配置中的必备能力、单次调用追加的必备能力，以及消息结构自然推导出的能力。能力本身只描述模型具备什么；某个能力是否成为硬约束，由调用设置和消息内容共同决定。

模型链执行时会基于当前调用的硬能力约束筛选尝试对象。若当前模型缺少单次调用所需能力，例如图像输入、远程图片 URL 或工具调用能力，runner 不会向供应商发起请求，而是沿模型链继续尝试后续模型；只有模型链中所有候选都无法满足能力或调用失败时，才按模型链耗尽进入 Runtime 语义陷入。上层仍可以通过当前优先模型能力视图决定是否构造特定输入，但单次调用能力校验负责兜底保护。

文本化附件和普通提示文本在模型接口层都属于文本输入。若调用方需要保留来源差异，应在上层语境或追踪结构中记录，不放入 LLM 消息模型。

## 模型上下文窗口

每个已配置模型必须声明正整数 `context_window_tokens`。LLM 在每次候选模型调用前，以完整 MessageStack、可见工具 schema、选择约束、reasoning/tool replay、图片、请求结构开销和有效 `max_output_tokens` 预留估算窗口占用。当前 provider-neutral estimator 使用序列化 UTF-8 字节作为确定性的保守 token 上界；供应商明确返回 context-limit 错误时，适配层以 `ProviderErrorKind.CONTEXT_LIMIT` 进入同一容量失败路径，作为本地估算的权威兜底。

`max_output_tokens` 始终是本次 provider 生成的 token 上限，同时参与上下文窗口输出预留；它不是 ActionResult、TurnTrace 或 Session 的字符预算。具体调用方可以显式覆盖 task profile 的该值，例如完整文档或脚本生成使用动作级 generation budget。生成成功后的业务工件大小、ActionResult 投影和 Context trace 生命周期分别由拥有该工件的 action/capability、Action Catalog 和 Context 负责，不能共用一个 `max_output_tokens` 假装表达三种边界。

Context 配置的 `compression_trigger_ratio` 是硬运行水位。占用严格超过 `context_window_tokens * compression_trigger_ratio` 时不调用 provider；占用恰好等于水位仍允许调用。容量 payload 保留 message/non-message/output 分项、消息字符投影和 provider 是否实际拒绝请求，供 Runtime 压力恢复按 `compression_target_ratio` 计算字符回收量。

## 推理输出

部分模型会返回推理或思考内容。LLM 模块应在统一响应中保留这类信息，但不应把它作为默认业务结果。

推理内容主要用于调试、日志、分析和上层构造后续上下文。TinySoul 将推理内容理解为与助手消息相关的推理轨迹：它可以是文本形式的推理内容，也可以是供应商返回的结构化推理项，还可以包含给人或框架观察的摘要。调用方应以正式回答和工具调用作为业务判断依据，不应把推理摘要当作正式输出。

模型可以在额外选项中声明推理轨迹保留方式。该声明表达 TinySoul 对历史推理内容的上层保留意图，例如不保留、保留文本推理内容，或保留供应商返回的加密推理项。具体供应商是否支持、如何映射和何时传回，由供应商适配层按各自协议处理。

Reasoning 的三个字段语义不同：`content` 是可传给支持 Chat 历史思考字段供应商的文本推理内容；`summary` 是给框架或人观察的摘要，不等同于可回放内容；`encrypted_items` 是 Responses 等供应商返回的结构化加密推理状态。OpenAI-compatible Chat 适配器只有在声明 `reasoning_keep=content` 时才把 `content` 映射为历史推理字段；OpenAI Responses 适配器只有在声明 `reasoning_keep=encrypted` 时才把 `encrypted_items` 放回 Responses input，未声明时跳过历史 reasoning，声明 `content` 时按配置错误处理。这样 Context 可以保留 provider-neutral Reasoning，而不需要理解供应商私有回放协议。

## 提示缓存

提示缓存应表达为一次请求的缓存意图、路由提示或稳定前缀身份，而不是由 LLM 模块维护完整缓存生命周期。

缓存意图包含稳定上下文身份。供应商支持显式缓存键、缓存路由提示或缓存保留参数时，适配层可以映射为对应请求字段；不支持时可以忽略。对于自动前缀缓存的供应商，缓存意图可用于帮助上层保持稳定消息前缀。具体是否发送请求侧缓存字段由供应商适配层决定，不由通用 OpenAI-compatible 调用层决定。

缓存范围由上层语境模块决定。角色只用于供应商对话结构，LLM 模块不在消息内维护缓存范围。

## 重试与切换

任务可以配置候选模型顺序、重试次数和等待时间。失败后切换的单位是模型。

任务配置描述任务用途、调用设置、调用参数、候选模型顺序和异常恢复策略；异常恢复逻辑负责根据策略执行重试、等待、切换和链路状态更新；任务调用本身只负责单次模型请求的能力校验、供应商调用和输出解释。三者应保持分离，避免一次调用流程被异常恢复细节淹没。

模型链采用显式异常分类后的顺序尝试策略。一次调用从当前起点开始沿模型链向后尝试：暂时性 ProviderError 先在同一模型按配置重试，仍失败时允许进入后续 chain cycle；非暂时性 ProviderError 和本次调用的模型能力缺失会把该模型标记为本次调用不可再尝试，并继续其余模型；RuntimeException 和未归类的实现异常立即中止模型链，不能伪装成供应商切换。这样认证/配置类错误不会按 `max_cycles` 重复轰击同一端点，程序缺陷也不会被其它模型掩盖。只有至少存在暂时性错误时才循环可重试模型；所有候选均永久失败后立即耗尽。模型链耗尽后进入 Runtime 语义陷入，由运行层决定结束当前 Turn 或执行其他上层处理。

每次候选模型尝试在 provider 调用前执行上下文硬水位预检，但一个 LLM Task 内所有候选始终共享上层已经构造的同一个 MessageStack。预检不会为不同模型维护平行 MessageStack，也不修改 ModelChainRunner 的位置状态；若当前 Task 允许 Context 重建，则容量压力立即中止整个 LLM Task，经 Runtime Trap 压缩 Context 后由上层重新构造一个新的 LLM Task。重放仍从既有 preferred model 开始，可能再次调用先前失败的大窗口模型，这是无容量 checkpoint 设计的明确成本。

`ModelContextOverflowPolicy` 区分两类调用恢复契约：Framework 和 `llm_action` 使用 `RECOMPOSE_CONTEXT`，把硬水位压力映射为当前 Turn Context 压缩；User policy 可以继续清理 active Workspace，Maintenance policy 只回收自己的 Context。Home Search 与 Memory owner 的 daily composition 使用 `END_TURN`，不以模块内部 MessageStack 的容量问题清理 active User Context；Memory inspect 本身是确定性目录检索，不创建独立 LLM task。

个人项目场景下，模型链默认进行有限但较充分的循环尝试，以容忍暂时网络故障，同时避免错误配置导致调用永久卡住。需要持续等待暂时性故障时，可以显式把 `max_cycles` 配置为无限；永久错误仍只尝试每个候选一次。每次模型尝试、重试、切换和失败通过 ObservationEvent 暴露，并遵守配置的等待间隔。

应提供重置链路状态的能力，使用户或上层流程可以让模型链回到初始尝试顺序。

模型链可以配置成功模型的偏好时间窗口。某个非链头模型在失败恢复中调用成功后，后续调用可以在一段时间内从该模型继续向后尝试；窗口过期后应重新回到链头模型尝试。这样既能避免频繁打到暂时不可用的链头模型，也能在窗口结束后自动回到优先模型。

LLM 模块与 Runtime 的语义桥接通过独立桥接层完成。LLM 内部维护服务于 Runtime bridge 的稳定失败类型，表达模型链耗尽、配置失败、调用契约错误和内部失败。Provider 错误是模型链恢复策略的输入：runner 在同模型重试或切换候选模型后，只有所有尝试耗尽才形成 `MODEL_CHAIN_EXHAUSTED`，不再维护一个脱离真实控制路径的独立 provider Runtime failure。跨出模块边界并需要改变运行控制流时，桥接层通过映射表把这些失败转换为少量 Runtime 通用原因；当前模型链耗尽和调用契约错误默认映射为结束当前 Turn，配置失败映射为启动失败。Runtime payload 只携带模块名、模块失败类型和必要摘要；原始异常链用于日志和调试，不作为 payload 协议。

LLM 的桥接方式应作为其他业务模块接入 Runtime 的参考：模块内 bridge failure 类型描述需要 Runtime 协调控制流的模块失败，bridge 映射表描述运行控制语义，任务失败结果描述可以由调用方继续处理或反馈给模型的局部失败。不要把第三方供应商异常、解析器异常或临时实现异常直接暴露为 Runtime 原因；也不要为了局部失败强行扩展 Runtime bridge failure 枚举。

## 配置

LLM 配置属于 LLM 模块。Infra 只负责读取和合并配置文件，LLM 模块负责解释供应商、模型和任务配置的语义。

`LLMConfigParser` 是配置解析公共门面，保持上层输入边界稳定；内部按 provider、model、task 三类 section parser 拆分。provider parser 只解释供应商接入形态，model parser 负责模型能力与供应商引用，task parser 负责任务模型链、调用设置和 retry policy。共享的动态值读取与 enum/list/number 校验由配置 helper 承担，所有配置问题都收敛为 `ConfigError`。

供应商配置把端点/凭据身份和行为适配类型分开描述：provider id 表示一个可独立启停的端点与凭据集合，`adapter` 表示复用哪种供应商协议行为，`api_style` 表示底层接口形态。代理端点因此可以使用独立 provider id 和密钥，同时显式选择 `openai` adapter；Kimi 开放平台和 Kimi Coding Plan 也使用不同 provider id、端点与凭据，但共同选择 `kimi` adapter。模型只引用实际提供它的 provider id，而不假定 provider 名称等于适配器名称。同一模型在不同平台具有不同供应商模型名时，配置必须使用目标端点公开的模型 id，不把一个平台的具体模型名发送给另一个端点。`enabled = false` 的 provider 不构建 adapter、不解析凭据，任务模型链会过滤其模型；过滤后为空在加载期报错。密钥本身不写入项目配置文件，应放在本地环境文件或系统环境变量中。

同一模型系列中的性能与成本档位仍是独立 `ModelSpec`，而不是 provider 或 adapter 的子类型。任务 profile 按自身用途静态选择优先档位，模型链继续表达有序失败恢复，不承担运行时复杂度分类或动态成本路由。配置应使用端点公开的具体模型 id；当供应商同时提供会重定向到某个档位的浮动别名时，初始化模板不为该别名复制第二个 TinySoul 模型身份，也不让隐式重定向替代明确档位选择。

OpenAI 供应商使用 Responses API。Kimi 以及其他兼容 OpenAI Chat Completions 形态的供应商使用 Chat Completions API。供应商适配层负责把已经渲染的 TinySoul 消息内容、回答格式、工具使用策略、模型侧工具、通用调用参数和模型专属选项映射为对应接口参数，并把响应文本、推理内容、工具调用、用量和元数据归一化。

OpenAI 的推理设置可以通过模型配置中的推理强度和推理摘要选项表达，由 OpenAI 适配层映射到底层 Responses 的推理结构。OpenAI 的历史推理回放使用 Responses 返回的加密推理项；模型声明保留加密推理项时，适配层请求供应商返回对应加密内容，并在后续调用中把这些结构化推理项作为 Responses 输入的一部分传回。OpenAI Responses 的文本 reasoning content 不作为输入回放；历史消息中只有文本 reasoning 且未声明回放时会被跳过，显式声明 `reasoning_keep=content` 则作为不支持的供应商配置报错。OpenAI 的模型侧工具调用可以映射为 Responses 的 function call item，工具结果可以映射为 function call output item。Responses 的 call_id 属于供应商相关性标识，适配层应将其映射到 TinySoul 内部工具调用结构，并避免上层模块直接依赖该标识。OpenAI 的推理摘要只作为可观察摘要保留，不作为可回放推理内容。输出详细度、提示缓存保留时间和服务层级等选项也属于供应商专属配置，由对应适配层映射到底层请求结构。这样可以保持 TinySoul 通用调用设置只表达跨模型通用意图，同时允许不同供应商模型保留各自可解释的 option 字段。

OpenAI SDK 形态的适配分为通用接口形态和具体供应商差异两层。通用层位于 `tinysoul.llm.provider.openai_sdk` 包内：client protocol 表达最小 SDK 面，payload mapper 负责消息、图片和 tool payload 映射，response parser 负责文本、tool call 和 reasoning 抽取，request-local tool name mapper 负责内部 identity 与供应商临时名称的双向映射，common helper 负责通用请求字段、错误归类和 metadata 提取，adapter 类只组合这些能力完成调用。供应商层负责自身支持的扩展参数、推理内容位置、缓存选项和接口风格约束。这样可以复用 OpenAI 兼容接口的共同结构，同时避免把不同供应商的专属参数混在同一个通用映射中。

Kimi 采用兼容 OpenAI Chat Completions 的接口形态。K2.x 的思考开关由模型额外选项表达并映射为 `thinking`；声明保留文本推理内容时，K2.x 同时使用 preserved thinking 设置并把助手历史消息中的 `reasoning_content` 传回供应商。K3 始终思考，不接受 K2.x `thinking` 参数，而是使用顶层 `reasoning_effort`；声明保留文本推理内容时仍回放 `reasoning_content`，但不得因此生成 `thinking.keep`。供应商 option 映射因此可以读取完整 `ProviderRequest`，依据供应商模型身份解释同名上层保留意图。模型侧工具调用映射为 Chat Completions 的 tools、assistant tool_calls 和 tool role 消息；K3 支持原生 required tool choice，K2.x 只发送 auto 并继续由任务解释层校验 required 和 forced_name 语义。Kimi function name 的字符约束由公共 request-local tool name mapper 吸收，Kimi behavior 继续校验工具数量、schema 根类型和模型参数等无法通过名称映射消除的真实能力差异。Kimi 的预填续写能力属于供应商对最后一条助手消息的专属扩展，不进入当前 TinySoul 通用消息语义。

DeepSeek 采用兼容 OpenAI Chat Completions 的接口形态。其推理开关和推理强度属于供应商扩展参数，服务端缓存采用前缀缓存语义，而不是请求侧显式缓存键。模型侧工具调用可以映射为 Chat Completions 的 tools、assistant tool_calls 和 tool role 消息。DeepSeek 的 strict 模式和 schema 支持范围属于供应商能力差异，应由适配层解释和校验。DeepSeek 可以返回文本推理内容，适配层会把它保留为统一推理信息；只有声明保留文本推理内容时，适配层才把助手历史消息中的文本推理内容传入供应商请求。模型能力配置应反映这些差异，避免把请求侧缓存键或不支持的多模态能力误标为通用能力。

GLM 采用兼容 OpenAI Chat Completions 的接口形态，但输出长度、思考模式和推理强度参数需要按智谱接口语义映射。GLM 的思考开关属于模型 option，推理轨迹保留方式映射为是否清除历史思考内容；只有声明保留文本推理内容时，适配层才把助手历史消息中的文本推理内容传入供应商请求。模型侧工具调用可以映射为 Chat Completions 的 tools、assistant tool_calls 和 tool role 消息。GLM 的工具选择参数当前只表达自动选择，因此适配层应把 TinySoul 的工具启用和要求调用语义映射为供应商允许的自动工具选择，并由任务解释层校验 required 和 forced_name 等 TinySoul 语义。GLM 的工具 schema 约束属于供应商能力差异，应由适配层解释和校验。结构化输出可使用 Chat Completions 的 JSON 对象输出参数。GLM 的上下文缓存是服务端自动前缀缓存，不使用请求侧缓存键，因此不应把提示缓存意图映射为显式缓存参数。

MiniMax 采用兼容 OpenAI Chat Completions 的接口形态。其思考模式和推理拆分属于供应商扩展参数，由模型额外选项映射到底层请求；启用推理拆分时，适配层把供应商返回的推理内容保留为统一推理信息，并把可见回答作为正式模型回答。模型侧工具调用可以映射为 Chat Completions 的 tools、assistant tool_calls 和 tool role 消息。MiniMax 当前适配不发送工具选择参数；当 TinySoul 要求工具调用或指定 forced_name 时，适配层只暴露工具定义，具体 required 和 forced_name 语义由任务解释层校验。只有声明保留文本推理内容时，适配层才把助手历史消息中的文本推理内容传入供应商请求；MiniMax 的 reasoning_details 会被提取为 TinySoul 的文本推理内容，但这只是供应商结构化推理细节的文本投影，不等同于完整结构回放。MiniMax 的 JSON 对象原生输出能力未作为当前模型能力声明；需要 JSON 对象时，由回答格式和本地解释逻辑处理模型可见回答。

供应商密钥按配置中的环境变量顺序读取第一个非空值。若同一供应商配置了多个可选环境变量，靠前名称具有更高优先级。

模型配置描述 TinySoul 内部模型标识、所属供应商、供应商真实模型名、必填的 `context_window_tokens` 和模型能力。任务配置只引用 TinySoul 内部模型标识，不直接引用供应商模型名。内部模型标识应使用小写和下划线，避免点号等容易与配置路径混淆的字符。

Model 以四项边界清晰的事实参与调用：Provider 引用选择 endpoint、凭据、API style 与 adapter；`provider_model` 表达该 endpoint 的真实模型名；capabilities 表达路由可依赖的能力；`adapter_options` 与 `request_overrides` 是两个同级对象。`AdapterOptions` 只承载由所选 adapter 解释的模型级选项，例如推理协议、缓存和供应商扩展参数。`RequestOverrides` 只承载模型对通用调用参数的固定覆盖，当前包括 `temperature` 与 `max_output_tokens`，由 TaskRunner 在构造 `ProviderRequest` 前覆盖任务和单次调用设置，Provider adapter 不解析该配置容器。

推理轨迹保留方式属于 `adapter_options`，它描述模型历史推理内容可由 adapter 以何种形态回放；具体供应商参数仍由 adapter 根据该语义和自身协议解释。设置页把既有 Model 的 Provider 更换解释为同 adapter endpoint 之间的轻量重绑定：展示全部 Provider 及 adapter，但只允许选择与当前 Provider adapter 名称相同的项，提交时只修改 Provider 引用，不比较、改写或删除 `adapter_options`、`request_overrides`、capabilities 与 `provider_model`。该交互不是后端的新旧配置转换约束；Provider 自身的 adapter 仍可编辑，可信配置者也可直接使用 Endpoint batch PATCH 完成更广泛调整。LLM parser 只校验最终候选配置能否由当前 Provider adapter 解释，失败时整个 PATCH 不持久化且当前 Runtime Generation 保持原样。目标 endpoint 是否实际提供配置的 `provider_model` 无法静态确认，由配置者负责。

配置文件属于动态边界。provider 的 `enabled`、`adapter`、API 形态，模型能力、任务回答格式、工具使用策略、adapter options、request overrides 和 retry policy 都必须在配置解析阶段转换为明确内部类型或 `ConfigError`。provider/model/task 及 adapter 专属 options 都拒绝未知键，避免拼写错误、裸 `ValueError`、`TypeError` 或未知字符串进入运行期。

任务配置描述不同任务用途对应的调用设置、候选模型顺序和重试策略。调用设置包含回答格式、工具使用策略、通用调用参数和必备模型能力。配置文件中的键名应使用适合 TOML 的安全写法，并与运行时使用的任务用途名称一致。

`TaskSpecTable` 提供稳定的 profile 查询门面，供装配边界校验其它模块声明的 task profile 引用；它不解释 Action ID，也不拥有 Action routing。Action-owned `[action.llm_action]` 可以声明默认 profile 和按完整 Action ID 的 override，最终由 App 装配边界把 Action catalog、Action route 与 LLM task profiles 交叉校验。LLM 模块仍只拥有 provider、model、task 的解析与运行语义，不提供设置页标题、说明或展示 descriptor；这些展示元数据统一属于 `infra.config` 的 package catalog。

内置 `home_search` profile 服务于 Home-owned top candidate reranker：禁用工具、要求 JSON object、使用低 temperature 和有界输出。模型只看到确定性候选 metadata，只能返回候选内唯一 Link；Task failure 或任何结构/业务校验失败都由 Home search service 回退到稳定的确定性顺序，不影响只读搜索可用性。

内置 `memory_daily_composition` profile 只服务于 Memory-owned daily composer：禁用工具、要求 JSON object、使用较低 temperature，并为目标日 source 的分层 reduce 和最终完整 daily 正文保留明确输出预算。每次输出只接受精确 `content` 字段；validator 负责非空、文档大小和 H1 约束，最终 Link/status/reference 校验仍在 Memory changeset preview。entity/concept/fact/note 的判断与维护发生在 Memory Maintenance Turn 的普通 Phase/Action 循环，不另建专用 task profile。Memory inspect 的 lexical/grep/references/backlinks 是确定性能力，可选 embedding 通过 Infra adapter 调用，不使用 LLM task。

单次调用可以显式覆盖任务配置中的调用设置。模型配置不承担回答格式和工具使用策略，因为输出形态表达的是任务意图，而不是模型身份。通用调用参数通常来自任务或单次调用；当某个具体模型有固定要求时，模型级 `request_overrides` 在最终请求阶段具有更高优先级。

任务配置中的必备能力会在配置加载时检查链上所有模型。单次调用可以追加必备能力，但不应放松任务配置已经要求的能力。

项目配置可以按主题和目录拆分到多个文件，例如供应商、任务和不同供应商的模型配置分别维护。拆分只影响文件组织，不改变 LLM 模块看到的统一配置树。

## 设计范围

每个 `TaskCall` 具有稳定 task identity。LLMTaskRunner 在 verbose 层发布 task started/completed/failed，并把同一 identity 写入模型尝试和 model request/response Observation；MODEL request 使用 provider-neutral 完整 MessageStack 与 ToolScope 投影，供桌面调试界面关联一次任务的上下文构造，不暴露 provider 原始 payload。

LLM 模块聚焦文本输入、图像输入、JSON 对象输出、模型侧工具语义、推理输出保留、提示缓存意图、模型链重试切换。

LLM 模块承担模型侧工具语义与供应商工具协议的映射，但不承担工具执行、动作调度、状态提交、严格 JSON Schema、文件附件输入、长期文件资源管理、跨供应商文件复用和复杂企业级可靠性机制。流式输出不属于当前核心范围；这些能力若进入项目，应在清楚的模块边界内设计。
