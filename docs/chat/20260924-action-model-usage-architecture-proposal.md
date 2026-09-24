# Action 模型用途、Reflection 写入与检索调用统一设计提案

> 日期：2026-09-24。
> 状态：pending；设计提案，等待讨论确认，未修改生产代码。
> 检查基线：10b43c9e1b9d245da9029fd713510317b754e662；实际业务代码与 f496508 一致。
> 关联：[后端支持计划 r4](20260924-visualization-backend-support-plan-r4.md)、[前端计划 r4](../../visualization/docs/analysis/20260924-visualization-refactor-plan-r4.md)。
> 本提案进一步审视 r4 §5.7：从仅提供模型依赖描述，推进到 Action 内部模型调用结构的整理。当前确认的是开展设计讨论，不表示用户已经批准全部新动作或配置迁移。

## 1. 判断与目标

建议调整后端。当前 native/llm_action 分类混合了动作执行方式与内部是否使用模型；LLMActionTaskRunner 又把路由、Context 组装、Skill 挂载、LLM 调用和 ActionResult 转换聚在一起。前端若只增加更丰富的下拉框，会继续受这些语义限制。

目标不是增加 llm/jev/image/embedding 四种 Action 执行器，而是明确三件事：

1. Action 由同一执行框架调用 handler，拥有业务意图、输入来源、输出解释、副作用和 ActionResult。
2. Action 或服务声明自己需要的具名模型用途，绑定到满足该用途契约的实现。
3. 模型协议层接收已构造的类型化输入，执行模型/Provider 路由并返回结果；不访问 Context、业务文件或持久化 owner。

采用组合来表达能力，保留现有 ActionBatchRunner、Turn/Cycle/Phase、Signal、Trap、Job 和 PluginGeneration 的职责。

## 2. 当前代码证据

| 位置 | 当前事实 | 对设计的影响 |
|---|---|---|
| kernel/action/catalog/specs.py | ActionBackendKind 为 native/subprocess/llm_action | 把执行入口与模型依赖混为同一维度 |
| kernel/action/execution/executor.py、runner.py | ExecutorRegistry 按 backend.handler 找 executor，所有动作经过相同批次执行骨架 | 模型辅助动作不需要新 Loop 或独立 ActionRunner |
| kernel/action/config.py | LLM 路由只允许 backend.kind=llm_action，按 action_id 选择一个 task profile | 不能描述 native 内的模型用途或一个 Action 的多个用途 |
| kernel/action/catalog/loader.py | llm_action 分类决定特有默认超时和 options 校验 | 去掉分类时必须迁移实际策略，不能只删枚举 |
| kernel/action/backends/llm_action.py | _run 固定 context.compose(prompt)，自动挂 Skill，返回 TaskResult 或带 Action 身份的失败结果 | 无法自然复用为纯局部输入调用，模型层与动作结果耦合 |
| plugins/workspace/actions/operations.py | workspace.write 精确写文本；workspace.compose 解析资源、生成完整正文，再由 Workspace owner 写入 | 生成和精确提交已有合理的业务区分 |
| plugins/memory/actions/write.py | write_daily/write 接收完整 Markdown，校验后原子写单文档 | 不代表没有 LLM 思考：正文已由外层模型提供，但长正文占 Phase2 输出 |
| plugins/home/actions/review.py | diff 与 review 由 Reflection 专属服务提供；review 接收 paths 和明确 decision | 模型判断已经发生在 Reflection Loop，不必每次提交再判断一次 |
| plugins/home/review/service.py | owner 的 resolve 可接收 rewrite_text，拥有 review token/实际提交 | 若后续增加模型重写，仍应复用这个 owner，而非另造审核存储 |
| plugins/home/content/search.py | HomeSearchReranker 已是局部输入接口；LLM 实现固定 TaskProfile.HOME_SEARCH | 有可复用的业务接口，应该移除固定路由，不重写检索 owner |
| plugins/home/plugin.py | generation/profile 装配时构建并注入 Home 检索实现 | 可在同一显式装配点选择用途实现 |
| plugins/memory/retrieval/embeddings.py | EmbeddingClient 输出 EmbeddingBatch，Memory 拥有向量缓存与检索语义 | 服务消费无需伪装成 Action，不应把向量数据塞进通用文本结果 |

## 3. 抽象层次：执行、用途和模型协议

### 3.1 Action 执行层

保留 ActionSpec、ActionExecutor、ActionExecutionContext 与 ActionBatchRunner。backend 表达 handler 及真正需要的执行配置；native/subprocess 可以继续描述执行机制。移除把 llm_action 当作互斥执行机制的做法，当前 LLM 动作仍由自己的正常 handler 执行。

一个动作能够读文件、调用模型、解释输出、提交 owner；其中任何一步不单独决定它是哪种 Action 类型。不要增加 JevAction、EmbeddingAction、ImageAction 继承树，也不把进程调用能力一并重构。

### 3.2 具名模型用途

动作可以声明零个、一个或多个用途。例如：

| 消费者 | 用途 | 业务输入 | 业务输出 |
|---|---|---|---|
| workspace.compose | compose | 指令、目标旧内容、参考资源及选定语境 | 完整文本产物 |
| memory.compose（建议） | compose | 目标、整理指令、已有文档、可追溯来源 | 可由 Memory 校验的完整文档 |
| home.top.search | rerank | query、有界候选与 top_k | 候选范围内的有序 Link 子集 |
| expand.search | select_tools | 需求、限定工具目录、实际所需语境 | 目录内工具选择 |
| Memory 检索服务 | embedding | 固定的一组文档/查询文本 | 与输入对应、同一向量空间的向量 |

用途表示业务依赖；LLM/JEV 表示可能的实现。两者不能混成一个枚举：LLM 既可生成也可做判断，“生成”也可能指文本或图像。基础协议类别可沿既定 llm、decision、embedding、image_generation 区分，JEV 是 decision 的具体模型/adapter。

用途声明提供身份、可读说明、支持的已实现策略、默认绑定规则、调用选项 schema 和配置引用。前端 catalog 从同一声明派生；不再另维护一份仅供 UI 的猜测名单。声明本身不读取文件或发起网络调用。

用途的 Input/Output 类型由消费 owner 定义。已有 HomeSearchReranker 可以直接演进；Workspace、Memory 各自保留资源解析与文档语义。多个功能出现相同契约时再抽公共接口，不为同名 compose 强行建立万能文档模型。

### 3.3 类型化模型协议与实际调用

底层模型调用接受完全准备好的请求，按具体协议返回结果：

- LLM 继续使用 TaskCall/MessageStack/CallSettings/TaskResult。
- Embedding 继续使用文本批次与 EmbeddingBatch。
- JEV 接入后使用其结构化问题和决策结果类型。
- 图像调用接入后有独立请求和图像产物结果。

可以有共同的绑定解析、调用身份、计时和 Observation 支持；不要求一个 run(dict)->dict 执行全部协议。不同 Provider 的适配、重试由相应协议实现承担，不在新层再包装一套重试循环。

共享的调用信息限于真实所需的 scope、可选父 Action 身份、取消/剩余时间和观察端口。复用已有对象；只有实际重复代码需要时才合成小型调用上下文，不引入第二个运行上下文容器。

### 3.4 配置选择在装配时完成

generation 使用候选配置验证引用与受支持实现，构造选定的用途实现并注入 Action/服务。模型/Provider 连接属于 generation；任务消息属于调用；Reflection 写服务仍由 profile 授予。

业务代码调用其明确类型的接口，例如 composer.compose(request) 或 reranker.rerank(request)。可选的泛型 Protocol 只表达类型化 input/output，不承担动态插件发现、任意类型转换和运行调度。

所有实现仍显式组合。模型辅助动作只是现有插件的 handler 与依赖，不应为每个动作新增一个 PluginGeneration。Memory 共享 Embedding 继续由 Memory 业务生命周期管理其缓存，模型调用设施不接管它。

## 4. Context 是输入来源，不是模型类别

赞同将正常调用理解为 input → model → output，但 input 应为类型化的已准备数据。Action 负责语义和选择，公共构造器负责重复的拼装。

现 LLMActionTaskRunner 建议拆清两项职责，具体文件数量服从实际实现：

1. 输入构造：生成 TaskPrompt、解析本地参考资源、挂载适用 Skill，选择使用当前已安装 Context 或仅局部消息。
2. 调用支持：使用解析好的 task profile 和已构造 MessageStack 调用 LLM，携带父 Action 的期限/取消与调用身份，返回模型结果。

面向 Action 可提供两个明确的构造入口：

- `from_turn(prompt)`：当前已安装 Context + TaskPrompt；“当前 Context”不意味着读取 Session 全部档案或 Home/Memory 全库。
- `from_local(messages_or_prompt)`：只使用动作准备的局部输入；需要 domain/action Skill 时显式挂载。复用现有消息类型，不建设第二套 Prompt DSL。

这些名字是接口设计示意，确认实现时按现有 Context API 收敛。LLM 调用服务本身不持有 ContextEngine，也不暗中决定加载范围。用户不需要在设置里为每个动作选择 full/local；这属于动作正常语义。

| 用途 | 推荐输入方式 | 说明 |
|---|---|---|
| core.reason / core.answer | 当前 Context + 任务输入 | 保持既有语境感知行为 |
| workspace.compose / analyze | 首先保留现有 Context + 局部参考方式 | 抽象迁移不顺便削弱动作能力 |
| memory.compose | Reflection Context + 所选来源、目标文档 | 仅在本轮模型调用中使用来源，不永久加载全部文档 |
| home.top.search 重排 | query + 有界候选 | 当前已有清楚局部语义，无需整轮上下文 |
| Memory Embedding | 文档/查询文本 | 不附带对话或 Skill，避免改变向量语义 |
| 未来 JEV 决策 | owner 构造的 state + 结构化问题 | 不由底层自动把聊天消息摊平成 state |

Context 容量异常只有输入实际依赖当前 Context、缩减它能解决问题时才请求已有恢复。纯局部候选过大则由该用途反馈缩小输入，不压缩无关的整轮 Context。render 仍纯读；参考资源由 owner 的读取服务在构造输入时解析。

## 5. Memory 写入是否增加 LLM

### 5.1 推荐保留精确写入，增加一个生成写入动作

write/write_daily 的原子提交与校验仍有价值；精确写入不应对已给定的正文再随机改写一次。专门生成模型的价值在于处理较长内容、按明确来源整理和使用独立输出预算，减少 Phase2 同时承担调度和整篇文档写作。

建议新增一个 `memory.compose`，参照 workspace.compose：

- 参数是目标、instruction、source_refs；source_refs 区分资源 Link 与 Session/Trace ref，归档来源携带日期，不把二者都当文件路径。
- daily 目标固定为当前 Reflection 的 target_day；非 daily 使用明确的持久 Memory Link。一个动作覆盖所有文档类型，不按 entity/concept/fact/note 增加动作。
- 已有文档通过 Memory owner 读取；整理既有文档时把必要完整旧内容作为输入，无法容纳时明确反馈，不能把截断内容当全文覆盖。
- Source resolution 复用 profile 已有 Memory/Session/Workspace 读取服务；对 Home/其他来源只使用已授予的正式读服务，不建设任意文件 API。
- 动作根据目标类型生成正文或现有文档 schema 所需内容；日期、身份和已知固定字段由 owner/构造器提供。模型产生的关系、证据与 redirect 交给现有 Memory 校验。
- 输出先在内存中解析/校验，再调用现有 write_document/write_markdown 单文档提交。模型失败或文档校验失败不写入，返回正常局部反馈供下一 Cycle 修正。
- 成功返回 Link、写入状态与简短说明，不把整篇生成文档常驻 Trace；详细正文由 owner 读取，UI 从旁路展示实际变化。

仅 Memory Reflection 注入持久写服务并授予该动作。普通 User Turn 的 memorize、inspect、recall 行为不变。没有 preview/commit 工作流、跨文档事务、CAS 或额外 Reflection 控制器。

实际维护时，精确写入和生成写入共用同一内部提交方法；动作语义不同，但不维护两条文档持久化路径。

### 5.2 两种备选与取舍

| 选择 | 优点 | 代价/判断 |
|---|---|---|
| 推荐：保留 write/write_daily，新增一个 compose | 与 Workspace 语义一致；明确哪些操作需要额外模型；保留精确写入 | 增加一个有独立语义的动作 |
| 保持两个动作，使用 literal/generated 判别输入 | 动作数量不变，仍可显式选择正文或生成指令 | write 同时承担两类操作；需要在 Workspace/Home 同类动作上解释不同习惯 |
| 将 write/write_daily 全改成 instruction 驱动 | Phase2 输出小，配置简单 | 失去精确正文提交，已有完整内容也多一次模型调用，不推荐 |

如果选择第二种，应使用明确互斥的类型化输入，不能用“有 instruction 就生成，否则猜 markdown”这类隐式分支。本提案不预先决定新增动作已经获准。

## 6. Home review 是否再调用模型

推荐保留 `home.diff → Reflection 判断/必要的内容修改 → home.review` 的多步协作。Reflection 的正常 LLM 已承担判断，review 接收明确 accept/reject，再调 Home owner 提交；这条正常主线简单且自主。

不建议默认给每次 review 内嵌第二次 LLM：当调用参数已经明确 decision，额外判断会让意图和执行不一致，也增加延迟。rewrite 应先修改 effective 内容或调用 owner 明确的 rewrite 能力，再完成审核。

如果实际使用证明需要一次评估很多变化，可增加模型辅助评估用途，输入限定 diff/说明，输出逐项建议；或者设计明确 instruction 驱动的 review 变体。但应把它作为新语义单独确认。它必须依据送给模型的同一 review snapshot/token 提交，复用现有 owner，不能把模型看过的 diff 与提交的版本脱钩。

本轮不增加 home.assess/home.auto_review 等多个预备动作。未来若 Home 内容生成也有真实需求，应按 compose 语义设计，而非把生成能力塞进 accept/reject 提交。

## 7. Home 搜索：解除固定 task profile

保留 Home 的确定性候选构建、限量和结果校验。将 HomeSearchReranker 的实现改为从 `home.top.search` 的 `rerank` 用途绑定注入，LLM 分支接受可配置 task profile；删除对 TaskProfile.HOME_SEARCH 的代码硬绑定。

初始默认可以继续引用名为 home_search 的已有链，以保留当前调优；名称只是普通配置对象，用户可换成任何满足本任务能力/输出需求的 LLM 链。配置可以选择不启用可选重排，但这不同于运行中异常后偷偷切换另一类模型。

输出契约保持候选内、有界、可为空的有序 Link 子集。修改配置不改变 Link 校验与 Home 内容语义。模型输出不合格时保留目前有证据的确定性候选结果回退，并明确实际使用方式；不增加多层自修复流程。

### 7.1 后续 LLM/JEV 两种实现

同一个 rerank 请求可以由 LLM 或 JEV 的业务适配器处理，前提是输出满足上面的 Home 结果契约。两者输入协议不同，由对应适配器构造，调用处不受影响。

2026-09-24 核对 TypeSafe 官方资料：Choice 是从给定集合选一个选项；Score 是按有序等级评分。这不是现成的“返回任意多个 Link 的排序列表”协议。

若以后接 JEV，可研究对每个候选批量给出相关度 Score，再由 Home 策略按分值、稳定的原候选顺序和有效性规则取 top_k/空集。需要确定阈值和相同分数的处理；不能把 Choice 的选项概率直接宣称为独立相关度，亦不能要求每次必须命中一个候选。此处是设计推导，尚未实现或验证效果。

Embedding 是候选召回/相似度用途；JEV 可用于后续选择/重排。它们不必相互替代，也不应混成一个“搜索模型类型”的随意切换列表。

本轮既有确认仍是 JEV 预配置。接入 JEV 重排需要后续明确扩大功能范围；通用结构先用 Home 可配置 LLM 路由、Workspace 模型调用与真实 Embedding 消费证明可行，不为展示选择器注册空实现。

依据：[Quick start](https://docs.typesafe.ai/introduction/quickstart)、[Choice](https://docs.typesafe.ai/primitives/choice)、[Score](https://docs.typesafe.ai/primitives/score)。

## 8. 配置路由、前端和运行方案

### 8.1 从 action_id 单绑定走向 action_id + use

建议迁移到一份 Action 模型用途绑定表，配置命名可采用 `action.models`。示意：

```toml
[action.models]
default_llm_task_profile = "llm_action"

[[action.models.bindings]]
action_id = "workspace.compose"
use = "compose"
implementation = "llm"
task_profile = "writing"

[[action.models.bindings]]
action_id = "home.top.search"
use = "rerank"
implementation = "llm"
task_profile = "fast_search"
```

以上是目标配置草案，不是当前 parser 接受的字段。implementation 表示该用途已注册实现，而不是任意 Provider 名。未来 decision 分支选择一个 model_use，不携带无意义的 task_profile；正式类型应是判别联合，不是所有字段皆可空的配置对象。

默认解析保持短链：该用途显式绑定 → 声明的默认规则。通用 LLM 用途可以采用 default_llm_task_profile；不增加 scenario/domain/用户/运行时多层覆盖。支持方式和可编辑参数由 owner 的真实实现声明，不能靠修改 TOML 把不存在的 JEV 实现变出来。

现有 `action.llm_action` 默认与 override 一次迁入新来源；每个旧 Action 指向它唯一的现有用途。Home 的固定绑定变成显式初始配置。迁移后旧字段不参与运行，不维护新旧两套 precedence。没有实际调用的 memory_daily 不自动当成 Reflection 绑定。

LLM 特有 max_output_tokens 等从 backend.options 移到对应模型用途调用选项；资源 max_output_chars 仍由业务 owner 的产物限制参与约束。原 llm_action 默认超时必须显式迁移为 Action/domain 的运行策略，确保已有动作不会因移除分类意外失去时限；模型种类不再决定动作超时。

Memory 的 embedding_use 仍由 Memory 配置拥有，专用 model use/model/provider 目录沿已确认方案。Action 关联共享服务时只展示和跳转，不克隆绑定。本提案不同时迁移 LLM 与专用 Provider 的全部目录所有权。

### 8.2 前端行为

Action 页“模型使用”取真实用途声明：

- 无用途：不显示空模型选择器。
- 一个或多个用途：逐项显示当前实现、默认/覆盖、所用链或 model use，以及相关模型/Provider 摘要。
- 有两个已实现且相容的方式：在该用途上显示方式选择，然后显示相应绑定控件。
- 共享服务：链接到其 owner 设置；固定绑定迁移后才显示可编辑路由。

API-06 描述来源与候选配置；API-07 继续整批应用，无新远程 Action 执行接口。UI 观察中嵌套模型调用关联原 Action，用途名、实际模型/Provider、结果类型供人理解；大向量/图像不作为普通 JSON 全量展开。

### 8.3 运行方案必须同时迁移

如果采纳本提案，r4 的 routing 快照引用需要从 action.llm_action 改为正式 action.models 来源。当前仅实现 LLM 绑定时范围与原确认等价，仍加可选预算；不遗留两个读取来源。

未来允许 LLM/JEV 切换时，推荐运行方案包含 Action 的实现选择与其绑定引用，才能完整表达运行行为；专用模型目录、Provider、凭据及 Memory 的 embedding_use 继续为项目共享配置。恢复方案按完整 Action 绑定范围替换，不将旧 LLM override 叠加到仍生效的 JEV 选择上。此未来范围变化在真正接入跨类型执行时确认，不由本提案隐含扩大已确认交付。

## 9. 生命周期与错误处理

遵循 AGENTS 三层失败语义：

- 参数/模型输出不满足本用途、生成文档不合法：owner/Action 返回稳定的局部反馈，由现有下一 Cycle 继续处理。
- 模型链耗尽、配置引用错误、owner I/O 等无法继续的模块失败：沿当前模块边界/Runtime bridge 分类，不为了“统一接口”全部变成空结果。
- Context 恢复、结束执行等全局转移：仍通过现有 Trap；模型用途不自行重启 Turn。

模型层返回自己的类型化结果/失败，不制造带 call_id 的 ActionResult。Action 公共辅助层可以复用映射逻辑，但只有 Action 执行边界装配最终结果；服务级 Embedding/检索不依赖 ActionResult。

取消与超时使用所属 Action/请求的期限，所有内层调用共享剩余时间，不重置一份完整时限。生成阶段可取消，单文件实际提交按现有 JoinedOperations 完成并记录；不引入超时线程或新的提交事务。模型返回成功不意味着文件已写，owner 提交成功后才返回写入成功及刷新 Signal。

Input preparation 不写持久事实；模型调用不拥有存储；提交后刷新段投影。当前 Context 模式保持 Skill/控制工具作用域语义，局部输入模式不增加持久背景段。

## 10. 代码组织建议

| 位置 | 调整 |
|---|---|
| kernel/action/catalog、config、engine | 移除 llm_action 执行类型依赖；登记具名用途和统一配置引用；保留同一 handler 执行 |
| kernel/action/backends/llm_action.py | 迁移输入构造与模型调用支持到清楚职责；不保留旧 runner 的重复活跃入口 |
| kernel/context 的现有 prompt/message 构造位置 | 复用消息与 TaskPrompt，提供明确的当前语境/局部构造能力 |
| kernel/action 下模型调用支持 | 接 Action scope/期限/观测，构建声明与路由的公共部分；名称可用 models，不承载 Home/Memory 业务 |
| llm | 保持现有 Task/adapter/重试协议，不读取 Action 或 Context |
| infra.model_services（既定 B1b） | 专用模型 typed 协议、Provider 连接与选择；无业务候选排名/文档提交 |
| plugins/home | 保留候选与 HomeSearchReranker 契约，依用途注入选定实现 |
| plugins/memory | 若确认新增 compose，拥有来源整理、文档生成结果解释和唯一提交；共享向量缓存不迁出 |
| agent/composition、kernel/registration | 通过既有显式组装注入用途依赖，替换硬编码的 llm_action 专属入口；不建立第二个插件装配平台 |
| gateway/endpoint、visualization | 同源 catalog、配置变更和调用展示，不另维护业务绑定 |

这是职责分配，不要求每一行新增一个文件或类。优先重用/拆清现有实现，接口必须有本轮真实消费者。

## 11. 建议实施切分与正常主线验收

| 切片 | 内容 | 可审查结果 |
|---|---|---|
| A1 | 用途声明、绑定配置、去执行类型耦合 | 原 LLM 动作行为不变，默认/override 只走新来源；原超时/产物限制仍成立 |
| A2 | 分离输入构造和模型调用 | core/workspace 保持当前 Context；Home 局部输入不夹带整轮历史；底层无 ContextEngine 依赖 |
| A3 | Home 检索改可配置路由 | 修改该用途 task profile 后实际使用对应链；结果仍限于已给候选 |
| A4（需确认） | 一个 Memory compose 动作 | 来源 → 生成 → 文档校验 → 单文档提交 → 结果；失败不提交；精确 write 仍精确 |
| A5 | 前端 Actions/任务链/运行方案/API 文档同步 | 不同入口编辑同一绑定；不再按 backend.kind 推断模型使用 |

与 B1b 的真实 Embedding 迁移配合，不阻塞已确认的 Context/资源页面建设。JEV 仅预配置继续独立成立，真正接入重排另开具体功能切片，不列为空完成项。

必要验证聚焦真实契约：同一输入在当前/局部两种构造路径的区别、默认与用途覆盖、Home 候选约束、Memory 生成校验与原子提交、取消不重复提交、前端显示的绑定确实被调用。按 owner 覆盖，避免为每个动作复制一整套模型 runner 测试。

## 12. 需要讨论确认的设计决定

| ID | 推荐 | 影响 |
|---|---|---|
| Q-03a | 采用“执行方式 + 具名模型用途”的组合，替代 llm_action 作为 Action 类型；模型调用消费已准备输入 | 后端结构/配置迁移，需同步原 r4 §5.7 和 routing 快照定义 |
| Q-03b | Home search 接入可配置 rerank 用途；先落 LLM 通用路由，JEV 保持预配置范围 | 解除 hard-coded home_search，局部输入语义不变 |
| Q-03c | 精确 Memory write/write_daily 保留，新增一个 compose；Home review 保持明确提交 | 获得长文档自主生成能力，不增加二次自动审核或多个小动作 |

上述是本轮新增方案，不能标为用户已确认。若选择合并 write/compose 的输入变体，应同步调整整个文档及动作 schema 后再实施；不能在执行阶段临时同时保留两种不清楚的写法。

确认后将 A1～A5 合入下一版前后端执行计划；这份提案保留设计依据。正式 AGENTS/docs/design 只在相应实现落地时更新为当前事实，不预先把目标接口写成现有能力。
