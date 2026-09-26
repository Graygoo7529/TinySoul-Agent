# Action / Model / Retrieval 完整复核与统一检索重构执行计划（r4）

日期：2026-09-26（Asia/Shanghai）

代码基线：`0ebc1f1da34b95538fa97fe49fa085f46ff6a482`，`docs: archive action retrieval planning inputs`。

状态：基线代码复核 `done`；维护者已确认操作组合设计及 r3 建议；本稿完成统一目标下的设计补全。F1–F4 修复及本稿全部重构实施均为 `pending`。

本稿取代 r3 及更早 review，作为本轮完整重构的当前执行依据。基于同一已复核代码基线继续设计，没有把设计确认当成实施完成，也没有声称重新拉取了更新提交。第 13 节保留历史验证记录；本文的新请求、配置和结果结构是本轮目标契约，需实施后使用。与归档旧计划冲突的检索设计，以本稿为准。

## 1. 总体判断与修订理由

当前重构已经建立合理基础：Action 的业务操作与执行方式分离；模型用途由代码声明、由配置绑定；LLM 使用唯一调用管线，JEV/Embedding 保留专用 typed 协议；来源归各 owner；Inspect、Search 和 Background load/evict 分工清晰。没有发现仍在运行的旧 Action backend 分类管线，或旧 Memory Embedding 客户端与新服务并行。

但尚不能认定完整收尾：真实召回证据没有贯穿模型输入与结果预览（F1）；向量缓存被局部请求覆盖（F2）；Memory 的错误引用越过局部失败边界（F3）；无消费者配置和旧设计文档仍未清理（F4）。这些影响正常功能与后续前端建设，不是针对极端故障增加治理。

用户进一步提出的单步操作与组合需求是合理的。本轮将当前“来源 mode + semantic 开关”重构为：

**一个候选来源 → 零个或多个类型化候选操作 → 一个结果视图及分页。**

query/backlinks 负责产生候选；refs/directory/result 是已有候选入口；filter/select/rerank 处理统一候选集合。业务 Action 仍由 owner 提供，模型调用仍复用现有用途绑定。这是对现有 retrieval 的职责重划，不建立第二套 Action runner、跨空间搜索中枢或通用工作流系统。

用户明确控制的是每个操作内部的模型与实现，例如 query 是否启用以及使用哪个 Embedding，select 使用 JEV 还是 LLM，rerank 使用 Embedding、JEV 还是 LLM。Agent 选择操作、顺序、范围和业务判断条件，不在 ActionCall 中挑选 provider/model。

相较已归档主计划，本稿明确修订三点：

1. 原“不开放 steps”的限制改为开放有限、线性的已登记操作组合；不开放程序语言、分支和循环。
2. 原 limit 限制最终保留结果，改为只限制单页展示；已形成结果可续接。
3. 原 select 可输出有序子集，改为只决定成员、保留输入相对顺序；排序由 rerank 独立负责。

以上修订已随 r3 建议获得维护者确认。本轮按新语义整体实施，不再把 select 排序、结果快照或 Workspace 模型操作列为待确认项。

复核依据：根目录 [AGENTS.md](../../AGENTS.md)、[归档主计划](done/20260924-done-action-model-retrieval-unification-plan.md)、当前生产代码/配置/SDK/Endpoint 投影，以及本轮对话确认。归档中的完成事实应保留；新增问题以本稿跟踪，不能反向把旧记录改成已经验证新协议。

### 1.1 本轮目标：Agent 可主动构造查询，获得此前未知的 Links

Search 是统一的资源发现和候选处理工具。Agent 从任务、当前语境和已有探索结果出发，决定在哪个 owner 的什么范围寻找内容、使用什么查询语句，以及如何组合筛选和排序；返回可打开的真实 refs、原文预览和继续探索入口。

“从无到有”指 refs 可以此前不在 Agent 的 Context 中，不是让模型生成不存在的资源身份。query 和 directory 不要求已知资源 ref；backlinks 以已有 anchor 发现未知来源；refs/result 则支持已知集合的再处理。这些路径共同组成完整工具，不把 search 缩成只能精炼已知 refs 的 selector。

“统一工具”指统一的 SearchRequest、CandidateSet、操作不变量、配置/模型用途、分页与失败语义。对外仍是各 domain 的 search Action；owner 保有来源与实际资源操作权，不增加一个覆盖所有空间的全局 search executor。

### 1.2 本次完整性检查所补齐的设计

| 检查点 | r3 中尚不够完整的地方 | r4 明确处理 |
| --- | --- | --- |
| 不依赖已知 refs 的语义发现 | directory 只为 MCP 开放，Context/Workspace 等可能仍依赖 lexical 先命中 | directory 统一为 owner 范围内的候选枚举，五个 owner 均提供真实适配；directory → select 可直接语义发现 |
| 来源与内部召回通道 | source 与 candidate_sources 容易混成同一层概念 | source 由 Agent 选；query.channels 由用户配置；lexical/embedding 只是内部通道 |
| 可实际应用的配置 | r3 的 target.profile 与现有 parser 的 task_profile 不一致；Embedding 设置入口未完全展开 | 保留 target.task_profile/use；明确 owner Embedding use 与 provider 链；统一 Memory 的 search 设置命名 |
| 管道步骤确实可组合 | 候选粒度、属性、预算和返回顺序仍有隐含假设 | 固定资源身份与内容单元关系、元数据过滤时机、完整成员评估和单页展示边界 |
| 可直接交接实施 | 部分请求变体、SDK/Endpoint 投影和移除清单过于概括 | 补齐请求约束、所有 owner 能力/来源基础设施、catalog/配置迁移及逐项验收 |

以上是已确认目标下的完整性补全。directory 扩展复用各 owner 现有 corpus/catalog/manifest/事实来源，不新增来源存储。没有发现需要重新改变所有权、执行内核或模型服务分层的架构阻碍。

## 2. Backlink select、MCP select 与 seed select 的关系

它们可以复用同一个 select 操作，但当前实现中并不都属于 seed_refinement。

| 场景 | 当前代码表达 | 本稿表达 | 候选来源与 select 的边界 |
| --- | --- | --- | --- |
| 已知 refs 中选择 | seed_refinement，必须 select | refs → select | 显式资源集合，经 owner 展开真实内容后判断 |
| 真实反链中选择 | backlink_search + semantic=select | backlinks → select | 先查真实入边，select 不能编造新的反链 |
| MCP 工具中选择 | directory SeedRefinement，必须 select | directory → select | 来源是工具目录，判断材料是实际描述及参数定义 |
| 查询后选择 | query_discovery + semantic=select | query → select | 先完成检索，再做内容判断 |
| 查询后排序再选择 | 目前不能完整表达独立多步 | query → rerank → select | 三步各有输入输出，按显式顺序执行 |

因此，不需要定义 BacklinkSelector、MCPSelector 等平行抽象。owner 提供不同的内容与关系，公共 select 复用用途解析、LLM/JEV 输入准备和结果校验。

## 3. 基线实施复核与遗留问题

### 3.1 已正确落地、应继续复用的基础

| 范围 | 当前判断及依据 |
| --- | --- |
| Action 执行 | catalog 绑定 executor；runner 管总 deadline、批次与执行事实；`kernel/action/catalog/specs.py`、`execution/runner.py` |
| 模型调用 | ActionTaskFactory 准备业务输入；LLMTaskRunner.invoke 执行唯一模型链，run 增加 Runtime bridge；`kernel/action/tasks.py`、`llm/execution/task.py` |
| 用途配置 | descriptor、binding、实际调用 Observation 分离；`kernel/action/models.py`、`retrieval/selection.py` |
| JEV / Embedding | provider 顺序、typed 协议、共享客户端及 owner 向量索引已经存在；`infra/model_services/` |
| Context / Session | 检索原始叶子事实与解释，不只搜索当前压缩后文本；`kernel/context/search.py`、`plugins/session/views/inspection.py` |
| Home | agent/skills 对外空间已检索；Skill 按 top 聚合，其它结果为 resource；反链为实际来源 resource；`plugins/home/engine.py` |
| Memory | search、确定性 inspect、文档 query 与真实关系已统一；`plugins/memory/engine.py` |
| MCP | describe/search/call 共用真实目录；`plugins/capabilities/expand/` |
| Workspace | 保留文字/正则、文件范围读取及反链能力，没有强加向量索引；`plugins/workspace/` |
| 生命周期 | SearchSession/SearchViews 绑定 Turn/profile 或 SDK lease；结果翻页不再调用模型；`kernel/retrieval/{engine,operations}.py`、`agent/services.py` |
| Reflection | 仍是同一内核下的情景扩充；通用 Action/model use 可用，持久写服务由 profile 提供 |

LLM 与专用模型无需塞进一个巨大的通用请求 union；统一的是用途、绑定、调用事实及失败边界。`llm_action` 仍是有消费者的任务 profile 名称，不等于已经删除的旧执行 backend 类型。

### F1 — P2：真实内容、命中依据、输入预算与结果分页尚未形成一致契约

状态：问题已确认；此前证据/分页/请求排除改进方向已获认可；实施 `pending`。本稿第 4–12 节将其与新增组合设计一起收敛。

主要位置：`tinysoul/kernel/retrieval/engine.py:254,308,384`，`selection.py`，Memory owner 的反链来源构造。

当前 lexical 与 Embedding 召回已经独立运行并融合。问题发生在之后：Embedding 每个 evidence 单元参与比较，但聚合只保留候选最高分，丢失实际命中单元；统一 bound_evidence 又按 lexical 分数裁剪。页面和 selector 共用这份小预算预览，selector 还没有收到 evidence_complete。

已复现：候选中前置 1,200 字符无关内容、后置另一个 ref 下的 `An automobile is available for hire.`；query 为 `car`。模拟向量服务使后者得分 1.0，但最终预览仅有无关内容。候选被召回，却没有把真正命中的实际文本交给模型或用户。

另外两处已确认：

- Memory 结构化反链可能只给出程序生成的 “source references target”，没有来源文档正文；关系事实不能代替内容预览。
- 三个匹配候选、limit=1 时，只保留一个且没有 continuation。旧主计划的总保留上限语义导致其余结果不可取回，需修改设计而非仅修一个裁剪函数。

现状不是“所有 search 都只有 ref”：Home/Memory 已有真实 evidence；MCP 有真实工具说明和 schema；Context/Session 有事实与解释投影。缺口在于这些内容在召回、聚合、模型选择和分页之间丢失重点、完整性或可续接性。

修订必须同时覆盖来源内容单元、命中记录、模型输入、候选操作与 SearchView；不能只加一段提示词，或者只让最终页面显示更多字。

### F2 — P2：一次查询的候选集合被错误当成缓存的完整来源集合

状态：方案已获维护者确认；实施 `pending`。主要涉及 A9 和持续运行性能。

位置：

- `tinysoul/infra/model_services/vectors.py:70`，读取缓存后只保留当前 `documents` 中的条目。
- 同文件 `:103`，有 pending 条目时，将这个局部集合覆盖写入同一个缓存文件。
- `tinysoul/kernel/retrieval/engine.py:322`，discovery 的 key 为候选 ref 加 evidence 序号。
- `tinysoul/kernel/retrieval/selection.py:103`，相似度 rank 使用候选 ref 和组合后的候选文本。

Home/Memory 的 discovery 与相似度 rank 正确复用了 owner 的同一 EmbeddingIndex。然而，两种操作提交的 key/文本投影不同，后一次写入会清掉前一种操作的向量。下一轮查询又要重新向量化原始证据。不同 scope 在引入新条目时也会出现类似缓存丢弃。

本次用真实 ModelServices、EmbeddingIndex 和 HTTP MockTransport 复现 A → B → A：A 使用 `ref + evidence 序号`，B 使用 `ref`；A 的内容没有修改，却被计算了两次。每次 query 自身重新向量化是正常行为，本项关注的是未变文档的重复计算。

修正方案：

- 区分 owner 的来源生命周期与一次检索请求的输入集合。查询不应隐式声明“其它缓存条目已删除”。
- 本稿采用按固定 provider/model/extraction 身份隔离、按实际嵌入文本摘要复用向量的方案；候选 ref / ContentUnit 到文本的映射由本次操作维护。新请求增量合并缺少的文本向量，不以本次候选集合替换整个 owner 缓存；discovery 与 rerank 使用相同内容单元，不能互相清空。
- 删除、重建或容量控制仍属于 owner 的派生缓存管理，不新增全局向量库、检索协调器或事务系统。
- 保持当前 provider 固定空间和失败时整次尝试切换的规则。

验收：discovery → similarity rank → 相同 discovery，不应再次提交未变原文；切换 scope 后返回原 scope 仍能复用未变内容；provider 切换仍不能混用向量空间。

### F3 — P2：Memory 的请求引用错误会被升级成 Action 内部故障

状态：方案已获维护者确认；实施 `pending`。涉及局部失败 / Runtime 控制流一致性。

位置：

- `tinysoul/plugins/memory/engine.py:190`，`canonical_reference()` 将不可解析身份转换成 `infra.references.ReferenceError`。
- 同文件 `:271`、`:277`，seed / document query 直接调用该方法，没有转换为 SearchFailure。
- `tinysoul/plugins/memory/actions/active.py:134`，executor 只接住 SearchFailure、MemoryContractError、MemoryError。
- `tinysoul/kernel/action/execution/runner.py:282`，遗漏的普通异常最终进入 Action Runtime bridge；`action/runtime_bridge.py` 将内部故障映射为结束 Turn。

本次分别使用不存在的 `memory:concept/missing` 作为 seed 和 document query，均得到裸 ReferenceError；进一步通过 MemorySearchExecutor 调用，确认它没有返回可供模型改正请求的 ActionResult，而是直接抛出该异常。

这是模型传入错误、过期或不存在的引用时的常规反馈路径，不应成为需要全局恢复的内部故障。

修正方案：在 Memory search 的 owner 请求归一化处，将这类 ReferenceError 转换为 `SearchFailure(INVALID_REQUEST)`，与当前 anchor 分支一致。SDK 和 Action 因而复用相同语义，Action 继续沿现有局部失败映射返回。不要在公共 runner 中泛化吞掉所有 ReferenceError，更不要把 I/O 故障统一伪装成空结果。

验收：不存在的 seed / document query 得到明确局部失败，能够继续同一个 Turn；真实存储错误保持原有模块失败语义。

### F4 — P2：无消费者的 Memory 日报任务配置及旧文档仍在表达另一套设计

状态：方案已获维护者确认；实施 `pending`。涉及 A14、配置可理解性和前端接入基础。

位置：

- `tinysoul/llm/protocol/requests.py:26`：仍有 `TaskProfile.MEMORY_DAILY`。
- `tinysoul/assets/standard/configs/llm/tasks.toml:50`、development 对应模板：仍生成 `llm.tasks.memory_daily`。
- `tests/llm/config/test_config.py:59`：仍要求该内置 profile 存在。
- `docs/design/llm.md:217`：仍写固定 Home `home_search` reranker，以及过于宽泛的失败降级。
- 同文件 `:219`：仍描述 Memory daily composer、分层 reduce 和 changeset preview。

搜索当前生产代码，没有发现 `memory_daily` 的真实调用消费者；`memory.write_daily` 实际上是 Reflection 中的确定性文档写入。这不是两条仍在执行的管线，但默认配置、枚举和设计文档仍承诺了不存在的功能，也会让后续设置界面继续显示没有效果的独立任务链。

修正方案：

1. 删除没有消费者的内置 MEMORY_DAILY 枚举、两份默认任务配置和固化它的测试断言。
2. 更新 LLM 设计文档，明确 Reflection 通过正常决策循环形成内容，再调用确定性 Memory 写入；Search 用途由 `action.models.bindings` 选择实现/profile。
3. 把 Home 的旧固定 reranker 描述替换为实际落地后的候选来源、显式操作及对应失败语义；本稿实施时不再固化旧三种 mode。
4. 保留实际承接多个生成和选择 consumer 的 `llm_action` profile，不通过改名制造额外迁移。

验收：新生成项目不再包含无消费者的 Memory 专属任务链；文档与实际 Reflection、Search 调用路径一致。历史 chat/done 输入稿可以保留历史表述，不必全仓机械替换旧词。

## 4. 唯一的操作模型

### 4.1 候选来源与候选操作

| 层次 | 名称 | 输入 | 输出及不变量 |
| --- | --- | --- | --- |
| 来源 | query | query、owner scope、显式属性条件 | 符合来源检索策略的候选，保留各通道实际命中内容；通道排序/融合属于 query 内部实现 |
| 来源 | backlinks | anchor_ref、owner scope、显式属性条件 | 具有真实入边的来源候选、关系依据和来源内容；anchor 可以属于其它 owner |
| 来源 | refs | 明确 refs / fragment refs | owner 规范化并读取指定范围后的候选；保持输入顺序，不做隐藏相关性预筛 |
| 来源 | directory | owner 声明的 scope、显式属性条件 | 枚举该范围的真实候选并准备内容；不做 query 匹配，不要求已知 refs，不调用模型 |
| 来源 | result | 当前 lease 内的 result_ref | 上一次完整最终集合及其内容快照；不是仅上一页可见条目 |
| 操作 | filter | 候选集合、where | 依据显式属性/标签返回稳定子集，不调用模型 |
| 操作 | select | 候选集合、criterion、context | 基于真实展开内容返回稳定子集，可为空；不改变保留成员的相对顺序 |
| 操作 | rerank | 候选集合、criterion、context | 对全部输入成员排序，允许并列且稳定打破并列；不删除成员 |
| 展示 | page | 最终结果视图、页预算/continuation | 当前页及续接入口，不改变最终集合、不重新运行模型 |

其中 query、directory 和 backlinks 是不同的发现入口；refs/result 负责从已知身份或结果建立可操作集合。它们统一进入同一条执行路径，而不是把五种不同层次概念一起塞进旧 SearchMode。

单步 search 就是一个来源加零步或一步。例如纯 query、纯 backlinks、refs → select、result → filter、result → rerank。组合调用仍是一次 Action，内部顺序复用相同操作实现。

### 4.2 CandidateSet 与真实内容

将当前 SearchCandidate 演进为候选内容与操作结果分离的 typed 对象；名称可按实际组织调整，但只有一套语义：

- Candidate：规范 ref、title、owner 声明的 attributes，以及可读取范围。
- ContentUnit：来源 ref、稳定单元身份、位置/范围、真实 text 或有来源的结构化内容、内容类型及完整性。
- Evidence：引用 ContentUnit，记录 lexical/embedding 命中、真实关系依据或当前操作判断依据。证据引用内容单元，不复制另一份正文 owner。
- CandidateSet：有序候选成员、内容单元快照、操作产生的分数/依据及 coverage。运行期不可变；每步产生新集合，可以共享不可变内容单元。

一个 Candidate 可以对应多个深层 resource 的 ContentUnit，例如 Home Skill top。结果 ref 与实际命中正文 ref 不必相同，必须都能正确解释。

来源内容是 owner 事实的有界快照，不是另一份持久化知识库。最终 SearchView 保存后续展示和重新操作所需的内容投影；不只保存最终页面的几行小字，也不要求复制整个文件系统。

### 4.3 线性组合边界

- 每次请求恰有一个 source；steps 按顺序处理同一 owner 的 CandidateSet。
- steps 仅允许注册的 filter/select/rerank，不接受 Python、表达式字符串或用户自定义函数名。
- 不在 steps 中再次 query/backlinks，不引入分支、循环、跨 owner join、隐式递归 Inspect。
- 不自动重排步骤。`query → filter → rerank` 与 `query → rerank → filter` 可有不同成本与排序事实，由 Agent 决定。
- 标准模板最大步数设为 8，可通过 policy 调整；它是有界调用预算，不是固定业务流程。
- 空候选集继续经过操作得到空集，不调用无意义的模型；记录该步骤输入为零。
- 一次 Action 共享已有总 deadline、取消和模型 Observation；不添加每步独立执行状态机。

有限线性组合足以满足本次需求。每个操作都有真实消费者和独立不变量，抽象的收益来自可解释数据流，而非可编程能力的数量。

### 4.4 directory 作为不依赖词面命中的发现入口

directory 的含义是“枚举 owner 声明范围内的候选集合”，不局限于文件系统目录，也不局限于 MCP。它不接受自然语言 query；自然语言问题由后续 select/rerank 的 criterion 表达。

- Home 枚举公开可检索的 agent/skills，普通 Skill 按 top 聚合；Memory 枚举指定 kind 的文档。
- Context 枚举 trace/session 的原始可检索事实与解释；Workspace 枚举指定工作区/目录/文件范围的资源。
- MCP 枚举 all 或 server 范围的工具定义。
- 显式 where/exclude_refs 限定候选资格；内容模型判断由后续步骤负责，不能暗加 lexical/Embedding top-k。
- source 只枚举成员与准备真实内容；select/rerank 的 JEV/LLM 由各自 binding 选取，directory 不新增一个模型用途。

因此，当不知道词面表达时可以 `directory → select`；需要排序则 `directory → rerank → select`。已配置 Embedding 的空间也可用 query 混合召回。Agent 通过选择这些业务路径构造不同查询方式，始终不临时指定 provider/model。

范围过大时返回 scope_required 及该 owner 支持的收紧方式，不将全空间伪装成前 N 个对象。directory 可以 steps=[] 用于有界浏览，但不能用它替代需要完整展开内容的 Inspect。

### 4.5 候选身份、内容范围与默认顺序

query/directory 的候选粒度由 owner 固定：Home Skill 是 top、其它 Home 是 resource；Memory 是文档；Context 是既有事实/解释入口；MCP 是工具；Workspace 是资源文件。同一资源多个命中单元合并进该候选，不能把重复片段当成多个文件结果。

backlinks 按实际来源身份聚合真实入边；特别是 Home 不把具体引用来源悄悄改成 Skill top。refs 来源保持显式读取范围，有意义的 fragment/range 参与规范身份，不能为了复用 query 聚合而扩大范围；相同规范 ref 只出现一次，稳定保留首次输入顺序。

query 使用配置的召回排序及融合；refs 使用输入顺序；directory/backlinks 使用 owner 声明的稳定规范顺序；result 使用原视图顺序。没有相关性判断的顺序不能标成“最相关”。select/filter 稳定保序，rerank 的并列使用输入顺序。

owner 将文件行/段范围、结构化事实位置、工具定义字段转换为自己的 ContentUnit。共享 retrieval 只保存、投影和传递这些范围，不解析各 owner 的路径或 fragment 语法。

## 5. Action / SDK 请求协议与调用例子

继续使用 `home.search`、`memory.search`、`core.context.search`、`expand.search`、`workspace.search`。不为每个 owner 再派生一组 query/select/rerank Action 名称。SDK 复用同一 typed request 与 owner 服务；请求是一次新 Search 或一次 continuation，二者互斥。

新请求顶层为 source、exclude_refs、steps、page。query 的文字与文档形式在解析边界转换为 TextQuery / DocumentQuery；JSON 的 source.query 接受非空文本或 {"document_ref": "..."}，在内部成为互斥的 TextQuery / DocumentQuery；只有声明 DocumentQuery 能力的 owner 接受文档形式。context 默认 none，criterion 是 select/rerank 的明确业务判断目标。

### 5.1 纯 query：不隐式追加 select

```json
{
  "source": {
    "kind": "query",
    "scope": "all",
    "query": "配置文件在不同操作系统之间共享"
  },
  "steps": [],
  "page": {"limit": 5}
}
```

query 是否使用 lexical、Embedding 或二者融合，由该 owner 操作配置决定。Agent 没有在参数里选择模型。query 的自然匹配语义仍存在；纯 lexical 没有匹配的资源不属于召回结果，但不能用 lexical 无命中否定 Embedding 产生的候选。

### 5.2 query → rerank → select

```json
{
  "source": {
    "kind": "query",
    "scope": "skills",
    "query": "跨平台配置文件管理"
  },
  "exclude_refs": ["home:skills@windows-only"],
  "steps": [
    {
      "op": "rerank",
      "criterion": "优先适合当前 Linux 和 Windows 项目共用的方案",
      "context": "current"
    },
    {
      "op": "select",
      "criterion": "保留有实际配置或操作说明、可用于当前项目的资料",
      "context": "current"
    }
  ],
  "page": {"limit": 5}
}
```

最后的 select 保留 rerank 得到的相对顺序；它不会再次隐式排序。不同步骤可以具有不同 criterion，不把 source.query 当成所有后续操作的隐藏输入。

### 5.3 对已知 refs 单独 select

```json
{
  "source": {
    "kind": "refs",
    "refs": ["memory:concept/configuration", "memory:note/platforms"]
  },
  "steps": [
    {
      "op": "select",
      "criterion": "保留包含实际踩坑经验的资料",
      "context": "none"
    }
  ],
  "page": {"limit": 5}
}
```

owner 读取指定 refs 的实际内容。fragment 不能先被剥掉再当成全文 seed。对于 refs 来源，规范身份保留有意义的 fragment/range；query 的 Skill top 聚合不意味着所有 refs 请求都必须扩大成整个 top。

### 5.4 对完整已有结果重新 rerank

```json
{
  "source": {
    "kind": "result",
    "result_ref": "search-result:example"
  },
  "steps": [
    {
      "op": "rerank",
      "criterion": "先处理对当前故障最有解释力的内容",
      "context": "current"
    }
  ],
  "page": {"limit": 5}
}
```

result_ref 是结果视图句柄，不是持久资源 Link。输入包含该视图全部最终成员，不受上一页 limit 限制；新操作创建新结果视图，原视图与 continuation 不变。

### 5.5 确定性 filter

```json
{
  "source": {"kind": "result", "result_ref": "search-result:example"},
  "steps": [
    {"op": "filter", "where": {"kind": ["concept", "entity"]}}
  ],
  "page": {"limit": 10}
}
```

where 只能使用该 owner 在 catalog 声明的属性。上例用于 Memory，不能假定所有 owner 都有 kind、标签、创建时间等字段。

### 5.6 backlinks → select

```json
{
  "source": {
    "kind": "backlinks",
    "scope": "all",
    "anchor_ref": "workspace:design.md"
  },
  "steps": [
    {
      "op": "select",
      "criterion": "保留解释该设计取舍的来源，而非仅列出链接的目录",
      "context": "current"
    }
  ],
  "page": {"limit": 5}
}
```

例如通过 home.search 调用时只查 Home 的真实来源边；目标身份可由 Workspace owner 解析。返回的是 Home 来源候选，不能让 select 将目标或其它空间的相似资源补进反链集合。

### 5.7 MCP directory → select

```json
{
  "source": {"kind": "directory", "scope": "server:research"},
  "steps": [
    {
      "op": "select",
      "criterion": "能够读取网页正文并返回来源链接的工具",
      "context": "none"
    }
  ],
  "page": {"limit": 5}
}
```

目录范围由实际 server/catalog 声明；示例值是设计示意。模型看到真实工具描述和参数定义。普通目录导航仍可直接调用 describe；search 不承担执行工具的职责。

翻页请求仅携带 continuation，沿用建立视图时的页预算；不能同时携带 source、criterion、context、steps 或新 page。若只需改变页预算，可使用 result 来源加空 steps 建立新展示视图，不重新调用模型。翻页不等于重新判断。

### 5.8 统一输出示例

以下内容与计数仅示意协议，不是本次项目实际检索结果。query/select/rerank 的输出都通过相同 SearchPage 呈现；步骤内部传递 CandidateSet，不先分页再传给下一步。

```json
{
  "result_ref": "search-result:example",
  "items": [
    {
      "ref": "home:skills@config-management",
      "title": "配置管理",
      "attributes": {"space": "skills"},
      "evidence": [
        {
          "ref": "home:skills/config-management/references/platforms.md",
          "range": {"start_line": 12, "end_line": 13},
          "text": "共享配置保存在项目目录中。平台差异通过独立覆盖文件处理。",
          "kind": "content",
          "basis": ["embedding", "select"]
        }
      ],
      "content_coverage": "excerpt",
      "evaluation": {"step_index": 1, "op": "select", "input_coverage": "excerpt"}
    }
  ],
  "coverage": {
    "source_complete": true,
    "completed_channels": ["lexical", "embedding"],
    "missing_channels": [],
    "source_candidates": 18,
    "steps": [
      {"op": "rerank", "input": 18, "evaluated": 18, "output": 18},
      {"op": "select", "input": 18, "evaluated": 18, "output": 6}
    ],
    "final_count": 6
  },
  "page": {
    "offset": 0,
    "count": 1,
    "total": 6,
    "continuation": "search-page:example"
  }
}
```

`source_complete` 表达来源范围已处理，不表示每份长资源都以全文给了模型；后者由内容覆盖表达。示例中所有 18 个成员参与模型步骤，最终保留 6 个，本页只展示 1 个，其余 5 个仍可续接。filter 不调用模型，其步骤无需 evaluated 字段；纯 query 没有 steps 记录。step_index 从 0 开始；evaluation 说明最后一次模型判断实际读了多少内容，不把 snapshot 或页面覆盖冒充模型输入。

位置可以由 owner 表达为行、段、事实范围或工具定义字段，不强制所有来源都变成文件行号。该 range 是真实内容定位，深层读取仍走对应 owner 的 Inspect/describe/read。

### 5.9 不知道任何目标 ref 的语义发现

例如在 core.context.search 中，Agent 尚不知道哪个历史事实提到了用户的取舍，且用词可能不同：

```json
{
  "source": {"kind": "directory", "scope": "session"},
  "steps": [
    {
      "op": "select",
      "criterion": "找出用户此前解释为何优先保持实现简洁，而不增加复杂恢复机制的交流",
      "context": "current"
    }
  ],
  "page": {"limit": 5}
}
```

该路径直接向配置的 LLM/JEV 提供合格候选的真实事实/解释内容，再得到实际 session refs；没有 lexical 前置门槛。Context 容量很大时可用 owner 声明的属性条件或更小范围收紧请求，而非静默取最前面的历史条目。

Workspace 同样可以从明确目录进行内容筛选，不先要求 Agent 猜中关键词：

```json
{
  "source": {
    "kind": "directory",
    "scope": {"kind": "directory", "locator": "workspace:notes/"},
    "where": {"kind": "text"}
  },
  "steps": [
    {"op": "select", "criterion": "包含跨平台路径处理经验的笔记", "context": "none"}
  ],
  "page": {"limit": 5}
}
```

Workspace scope 延用其工作区/目录/文件的 typed 语义；它不必为统一入口把合法的结构化范围扁平为任意字符串。

### 5.10 必须统一的请求约束

| 变体 | 允许输入 | 约束 |
| --- | --- | --- |
| query 来源 | kind、scope、query、where；Workspace 支持 case_sensitive/use_regex | query 非空；Memory 可用文档形式；literal/regex 是业务匹配语句，不是 provider/model 选择 |
| backlinks 来源 | kind、scope、anchor_ref、where | anchor_ref 必填；若需自然语言判断，明确增加 select/rerank，而不保留旧隐藏 semantic 字段 |
| directory 来源 | kind、scope、where | 不接收 query/refs；枚举与自然语言判断分层 |
| refs 来源 | kind、refs | 至少一个明确 ref；不接收 scope/where，后续属性筛选使用 filter |
| result 来源 | kind、result_ref | 当前 owner 的有效句柄；不重新访问 owner 文件或改变原集合 |
| filter 步骤 | op、where | 非空明确条件，无 criterion/context/model |
| select/rerank 步骤 | op、criterion、context | criterion 非空；context 默认 none；不得携带 provider/model/implementation |
| 新 Search 顶层 | source、exclude_refs、steps、page | source 必填，steps 默认 []，exclude_refs 默认 []；不存在默认追加的模型步骤 |
| continuation 请求 | continuation | 必须单独使用，不触发来源读取与语义模型 |

scope 的默认值是该 owner 的标准公开范围；声明规则来自 owner capability，不从字符串前缀猜测。page.limit 默认 min(20, policy.page.max_items)，仅允许正整数。未知或跨变体字段在入口转为有限请求反馈。

Memory 的文档 query 使用 `{ "source": { "kind": "query", "scope": "all", "query": { "document_ref": "memory:concept/example" } } }`。owner 读取文档确定 query 内容，并按其文档相似检索语义排除查询文档本身；这一规则在 schema/帮助中披露，不当成额外 lexical 筛选。内容过大按输入容量反馈，不默默取标题代替全文。

先完成整个请求的结构、能力、用途和预算形态校验，再访问来源或调用模型。运行期规模校验仍按实际 CandidateSet 进行。纯 refs / result 的空结果可以正常返回，refs 列表为空则是缺少来源的请求错误。

## 6. 用户配置与 Agent 决策的明确分工

### 6.1 配置的是内部实现

| 用户配置 | 允许选择 | Agent 调用时表达 |
| --- | --- | --- |
| query 召回策略 | lexical、Embedding、混合；具体 Embedding use/model/provider 顺序 | query、业务 scope、显式 where |
| select 实现 | llm_task 或 structured_decision；对应 LLM profile 或 JEV use；必要的评分阈值 | refs/目录/结果来源及筛选 criterion、context |
| rerank 实现 | embedding_similarity、structured_decision、llm_task | 排序 criterion、context |
| filter | owner 支持的有限字段与比较语义，不需要模型绑定 | 明确属性/标签条件 |
| 预算 | 操作输入容量、页面大小、视图容量和最大步骤数 | 在已开放范围内申请展示数量 |

Embedding 的具体模型、provider 链继续通过 model/use 配置解析；不能给每个步骤再复制一份 provider 配置。`source` 表达候选来源，`query.channels` 表达来源内部召回通道，删除旧 `candidate_sources` 命名以免两层概念混淆。Home/Memory 的 query 与 Embedding rerank 复用同一 owner 的 Embedding use、索引和内容表示。rerank 绑定指定 Embedding 实现时消费该已声明用途；本轮同一 owner 固定一个内容向量用途，query 与 Embedding rerank 都通过它取得具体模型及 provider 链，不引入重复配置入口。

JEV 与 LLM 可以有不同输入构造，但这发生在公共操作实现层：select/rerank 已知道候选内容和业务目标，再选择适配实现；infra ModelServices 不猜测检索意图。多次步骤也不允许改变已解析的用户绑定。

Embedding rerank 支持显式 criterion；不擅自把完整 Context 拼接成向量 query。若当前绑定不支持 context=current，catalog/schema 不开放它；SDK 输入也得到明确参数反馈。LLM/JEV 支持 current 时读取一次调用开始时的 Context 快照，不因中间候选变化而修改父 Context。

### 6.2 一套 policy、一套 model-use

将按 mode 重复的 SearchPolicy 改为每个 Action 的 retrieval capability/policy：sources、operations、各操作可用参数/Context、预算、owner 属性。Stage2 schema、SDK 校验、catalog 投影、设置界面的能力显示都从这套声明与已绑定配置生成。

保留 `action.models.bindings`。操作用途统一为 `.select`、`.rerank`；将现有 `.rank` consumer 和 ModelOperation.RANK 一次迁移为 `.rerank` / RERANK，不保留兼容 alias。结果页的 rank 序号不属于旧操作名，无需机械删除。配置中的旧 action.models.search_policies 移至 action.retrieval，每个 Action 只有一份 policy。

以下为本轮目标配置形状，typed parser、catalog 与模板必须一起实现。新增 action.retrieval 不属于基线现有配置；保留已有 target.task_profile/use 的准确拼写：

```toml
[action.retrieval."home.search"]
sources = ["query", "backlinks", "directory", "refs", "result"]
operations = ["filter", "select", "rerank"]
max_steps = 8

[action.retrieval."home.search".query]
channels = ["lexical", "embedding"]

[action.retrieval."home.search".select]
allowed_context = ["none", "current"]
input_max_chars = 64000

[action.retrieval."home.search".rerank]
allowed_context = ["none", "current"]
input_max_chars = 64000

[action.retrieval."home.search".page]
max_items = 50
max_chars = 8000

[[action.models.bindings]]
consumer = "home.search.select"
implementation = "structured_decision"
target = { use = "decision_main" }
options = { relevance_threshold = 2 }

[[action.models.bindings]]
consumer = "home.search.rerank"
implementation = "llm_task"
target = { task_profile = "llm_action" }
```

配置预算数值为示意。select 阈值应与当前 JEV Score levels 一起校验，不能将一个裸阈值跨任意评分尺度解释。默认配置为每个开放的模型操作提供有效 binding；隐藏或不开放的操作不产生无消费者必填任务链。

不以配置暴露任意处理器脚本、动态 plugin 发现或自定义执行图。这里的扩展性面向仓库内显式组合与迭代。

### 6.3 模型配置链路与生效能力

| 操作内部实现 | binding / owner 配置 | 具体调用链 |
| --- | --- | --- |
| query 的 lexical 通道 | query.channels 包含 lexical | owner 内容/范围 → 确定性匹配，不需要模型用途 |
| query 的 Embedding 通道 | query.channels 包含 embedding；owner search.embedding_use | use → 专用 model → 有序 provider_bindings → 同一向量空间的内容/查询向量 |
| select / rerank 的 LLM | implementation=llm_task；target.task_profile | 既有 LLM task profile → 模型链/调用分配 → provider 链；输入由检索操作准备 |
| select / rerank 的 JEV | implementation=structured_decision；target.use | 专用 use → JEV model → provider 链；操作准备 Score/Choice 请求 |
| rerank 的 Embedding | implementation=embedding_similarity；target={} | descriptor 声明 embedding_owner，读取该 owner 的 embedding_use 与索引 |
| filter / backlinks / directory / refs / result | 不声明模型用途 | 各自确定性逻辑；只有显式后续模型步骤才调用模型 |

统一配置位置：`home.search.embedding_use` 与 `memory.search.embedding_use`。将基线 `memory.semantic_search` 及 MemorySemanticSearchSettings 更名为 `memory.search` / MemorySearchSettings，同步 parser、装配、catalog、标准/开发模板和文档，不保留 alias。缓存大小继续属于各 owner；source/steps/page 策略归 action.retrieval。

专用模型继续使用 `infra.model_services.providers/models/uses`；provider 负责 endpoint、adapter、凭据引用、代理/客户端设置及传输参数，model 的 provider_bindings 数组决定切换顺序，use 绑定一个实际 model。沿用现有真实字段，不新增与其并行的 retrieval.providers 或每步 provider 配置。

配置的 sources/operations/allowed_context 是开放范围上限；生效能力由代码声明、情景服务、用户 policy 和当前 binding 的实现能力共同解析。尤其 rerank 切换成 Embedding 后，effective_context 只包含 none；保留配置中的允许上限不会让 Stage2 获得 current。无效默认值、缺少必需用途或不支持的实现应在配置应用/装配校验时明确反馈。

默认全部 select/rerank 绑定 llm_action，JEV 与 Embedding 保留可选配置；配置模板不因默认填入 JEV 就强制用户准备 Typesafe 凭据。本文 TOML 中 JEV/混合通道用于展示选配，实际启用时要求对应 provider/use 就绪。query 默认 lexical，不代表运行时擅自把用户明确配置的混合检索降成 lexical。

解析后的 binding 在同一次请求内固定。provider 切换仍属于同一模型实现的调用链，不跨 LLM/JEV/Embedding 类型隐式 fallback；Embedding provider 切换必须重做同一尝试的查询/内容向量空间匹配。

### 6.4 操作预算、内容投影和视图预算

本轮预算按真实职责设置，不沿用一个 candidate_limit 同时表示扫描、模型输入和展示数量：

| 预算 | 唯一 owner / 配置位置 | 超额行为 |
| --- | --- | --- |
| 来源扫描/读取 | 各资源 owner 的 search 设置 | 无法完成请求范围时 scope_required；不得静默给前缀加“完整”标记 |
| 候选内容快照总量 | action.retrieval 的 snapshot 预算 | 无法形成所需有界输入时 scope_required；成员不因它被偷偷删除 |
| 每步模型输入总字符/成员数 | action.retrieval 的 select/rerank 预算 | 对实际步骤输入检查；filter/select 先缩小集合可减少后续成本 |
| 模型内容投影 | 各操作预算与 owner 内容单元共同决定 | 短内容完整，长内容明确摘录；保留真实来源/命中依据及覆盖说明 |
| 单页条目/字符 | action.retrieval 的 page | 仅减少本页展示，产生 continuation |
| 活动视图数量/总占用 | SearchViews 的 session 预算 | 对旧视图进行有界回收；过期句柄明确反馈，不截掉新视图成员 |
| 步数/总执行时间 | retrieval.max_steps / 既有 Action deadline | 参数超限或调用超时按所属局部失败/控制流处理 |

这些是本轮 parser 要实现的预算类别；沿用现有合理默认值时记录其实际职责，不简单复制旧 result_limit/candidate_limit。先执行已声明的元数据 where/exclude，已读取元数据足够时可避免为被排除成员加载正文。steps 中 filter 可先于模型运行；不过不能自动下推穿过 query/rerank，改变 Agent 声明的顺序。

模型输入准备应在每个语义步骤基于当前集合进行，不因后面存在模型步骤就先对整个来源套用 selector 容量。快照预算仍约束本次已读取内容，不增加隐式多轮摘要或超大数据集全局排序。

snapshot、模型输入、页面三者的覆盖分别记录。页面只显示几行不意味着模型只读了几行；反之 owner 保存完整文档也不意味着模型看过全文。结果中的 content_coverage 表示候选快照覆盖；语义步骤另记录实际 input_coverage，并送入模型。最后一次判断的依据与覆盖可在该候选的 evaluation 投影中披露，未经过模型的候选没有 evaluation。

## 7. 内容展开、命中证据与模型输出

### 7.1 召回与资格不能混用

query 在显式 scope/where/exclude_refs 确定的范围内召回。lexical 与 Embedding 各自处理完整合格来源，独立产生候选和命中单元，之后合并去重、融合排序；无词面重合不能否定向量候选，向量低分也不能否定 lexical 候选。

禁止合并后再做隐藏 lexical 门槛、按 lexical 只保留前 N 个候选、或在 semantic selector 前先做未声明的语义排除。原有 candidate_limit 和 limit 不得承担这种静默删除职责。用户要求属性/标签过滤时使用明确 where/filter；要求语义排除时必须出现 select。

不要求无匹配资源都成为候选；要求检索策略已经产生的有效候选不会因展示预算或另一通道的否决消失。RRF 等融合仍可排序，但必须保留各通道的真实命中单元，不能仅剩总分。

### 7.2 同一内容来源，分别准备模型输入与页面

模型输入预算与页面预览预算必须分开。两者都取自 ContentUnit，不能先把页面缩成 1,200 字符再声称模型已经检查资源。

| 场景 | 内容展开重点 |
| --- | --- |
| query | 实际 lexical/Embedding 命中单元及连贯邻近内容，聚合结果同时披露 top 和实际命中 resource |
| refs / directory → select/rerank | 指定 refs/ranges 或枚举对象的正文；短内容完整，长内容有范围、标题、真实片段与覆盖说明；不以 criterion 的词面匹配删掉候选 |
| backlinks → select/rerank | 真实边或引用位置，加来源正文；结构化关系与正文分别标注 |
| MCP directory/refs | 工具真实描述、参数 schema 和必要 definition；超范围可 describe，不用工具名替代定义 |
| Context/Session | owner 提供的事实、解释、关联内容及 ref；不伪装成文件，不只读折叠后的提示 |
| result → select/rerank | 原结果视图保留的内容快照；使用新 criterion，不能只拿上一页展示的小片段 |

短内容尽量完整；长内容提供连贯原文片段和覆盖范围。完整性必须送入 LLM/JEV，明确 full、excerpt 或 metadata。目录对象的 schema 本身可以是实际内容；有正文资源却只剩标题时，不能当作已完成正文评估。

超过总模型输入容量时返回 scope_required，引导收紧 source、refs 范围或减少 current Context。不能悄悄漏掉候选后声称对全体做了 select/rerank。有限片段不等于全文：模型判断只能声称基于给定内容，不能把未入选解释为证明全文无用。

不自动递归 Inspect，不偷偷多轮检索、摘要和模型讨论。需要更深内容时仍由父 Agent 沿 ref 调用确定性 Inspect/describe/read，然后决定下一步。

### 7.3 选择与排序也应留下可验证内容依据

单有模型解释 reason 不能替代原文预览。为每个 ContentUnit 提供本次输入内的 unit id，操作输出关联实际依据：

- LLM select/rerank：输出候选 ids，以及所评估候选的已知 basis unit ids；操作层校验身份、成员与数量，正文由原单元取回，不接受模型改写为“原文”。
- JEV select：复用原生 Score 判定；保留达到明确阈值者，按输入顺序输出。多个内容单元时，可在同次请求附 Choice 选择最有判断依据的已知单元；单单元不增加问题。
- JEV rerank：同样取得 Score 和必要的依据 Choice；按分数降序、原序稳定打破并列，保留所有成员。
- Embedding rerank：criterion 与实际内容单元比较，记录贡献分数的单元；复用 owner 内容向量，不再用裁剪后标题+片段生成一套互相覆盖的缓存键。

JEV 的实现方案基于仓库当前 `infra/model_services/protocol.py` 中 Score / Choice 及 DecisionRequest 结构，不要求 JEV 生成自由 JSON 或文本。真实多问题组合的效果与成本须在实施验收做代表性调用；当前 review 没有验证新的 Score+依据 Choice 请求。候选过多或 Choice 超出协议选项上限，属于输入容量问题，不拆成隐式全局排序流程。

basis 表示本次判断采用的实际内容；低分或纯反证片段不应标成“正向语义命中”。页面按最后一个语义操作的依据优先呈现，同时保留 query 命中/关系出处供展开；filter 不改写证据，rerank/select 不抹除来源依据。步骤级记录有界保留，不创建另一份事实历史。

## 8. filter、资格条件与检索排除性

### 8.1 同一个 FilterSpec，两个明确应用时机

query/backlinks/directory 的 source.where 在相关性召回/候选输出前限定资格；refs/result 来源需要过滤时显式使用 filter。steps 中 filter 对已有集合做确定性过滤。两处复用同一属性比较器，但不能擅自下推或重排：改变参与 query 排序/融合的集合，可能改变结果顺序。聚合候选的 where 必须基于完整聚合元数据求值；读取元数据可以早于读取正文，不能只凭第一份子资源属性过滤整个 Skill。

本轮支持 owner 已声明字段的相等、列表成员匹配与字段间 AND；不预建通用表达式语言。未知字段、错误值类型得到明确参数反馈，不能默默忽略。对候选明确缺失的合法字段，普通匹配为 false；无“自动猜测”属性。

属性归 owner 定义。尤其 Home Skill 的 file_type 等聚合属性不能沿用第一份文件的偶然值：需要字段则明确为集合成员语义，例如 resource_types；没有可靠来源就不开放该字段。Memory kind、MCP server 等也由各自实际 catalog 提供。

filter 是结构化资格筛选；自然语言“保留有操作说明的文档”属于 select。两者输入语义不同，不再另加一个重复的 semantic_filter。

### 8.2 exclude_refs 只在本次请求生效

已确认的边界保持：Agent 根据真实查阅和当前任务，显式给出 exclude_refs；owner 在候选准备/模型操作前按规范结果身份处理。默认空，不持久化负面索引，不自动把 seen、unselected 或低分对象加入黑名单。

查询 Skill top 的排除与 fragment 排除不能混淆。仅一段不适用不代表整个 Skill 无用；owner 不支持所请求的排除范围时明确反馈，不能剥掉 fragment 后静默排除整个对象。

result 来源后的 filter.where 与请求级 exclude_refs 使用快照属性与规范身份，不为排除校验重新检查磁盘现态。语法或 owner 不支持的排除身份是请求错误；规范且属于本 owner、但不在当前集合的身份视为无匹配，不要求它仍存在于磁盘。

结果视图已排除的对象不会在该视图的派生步骤中自动恢复；若需要重新考虑，创建新 query/refs/directory 来源即可，不必删除持久记录。

### 8.3 情境相关判断

相同资源在不同 criterion/current Context 下可以得到不同 select/rerank 结果。context=none 不知道先前查阅结论；rerank 也不保证排除重复内容。需要此次确定不再检索时使用 exclude_refs，需要结合当前任务判断时使用 criterion/current。

捕获一次当前 Context 给本请求所有声明 current 的步骤使用；候选输出在本次 Action 内是局部数据，不偷偷加入父 Context。最终结果按正常 Action 反馈进入 Trace；辅助模型调用不解除 Inspect 的“必须实际进入决策模型请求”保护。

内容向量可以跨语境复用；语义判断不能只按 query/ref 缓存后跨语境复用。本稿不新增语义结果缓存。Session/Trace 已有真实查阅与判断事实足够作为后续推理基础。

## 9. 结果视图、分页与重新操作

### 9.1 三种入口不能混为一谈

| 入口 | 含义 | 是否新检索/新模型判断 |
| --- | --- | --- |
| 内容 ref | owner 持有资源/事实的可打开身份 | Inspect/read 取内容；refs 来源按当时内容建立新集合 |
| result_ref | 一个搜索最终集合的运行期句柄 | 可作为新操作输入，显式 select/rerank 会重新判断 |
| continuation | 一个既有视图的分页位置 | 只读取原集合下一页；不重新召回、不重新判断 |

result_ref 复用现有 SearchViews 条目身份；不建立新持久表、会话语义图或新的注册服务。它不是任意 owner 可解析的资源 Link。

### 9.2 视图保留完整最终成员

limit 是每页最多展示的候选数量，页面字符预算控制预览和实际页大小；配置须容得下至少一个最小候选入口，不能产生有剩余结果却零进展的分页。SearchView 保存本次已完成来源范围的全部最终成员、顺序及有界内容单元；不能再用 prepared[:limit] 永久裁掉尾部。

coverage 至少区分来源是否完成/哪些通道缺失、来源候选数、每步输入输出与实际评估范围、最终结果数、当前页及剩余数量。select 排除、filter 排除与未展示分别披露。

模型容量、来源扫描容量与视图容量仍有限：

- 纯 query 不受 selector 的候选输入预算限制。
- 模型操作须覆盖输入集合的全部成员；内容可以有明确 excerpt 范围，成员不能静默漏评。
- 无法完成指定范围或容纳最终结果时返回 scope_required。不能创建“可翻页”但实际上未扫描/已丢弃尾部的伪完整视图。
- 本稿不新增全 owner 的来源游标。已经存在的内容级分页保留；搜索结果 continuation 只覆盖已形成的结果，不能假称续接还没搜索的来源。

通过有界范围、容量反馈、完整结果分页实现轻量设计，不靠隐藏 top-k 模拟完整性，也不承诺无限集合全局模型排序。

query/backlinks 的完整扫描要求针对请求所规定的正文范围，不得只扫长文件前缀而声称完整；directory 的来源完成则表示合格成员已经完整枚举，其正文可以是明确的有界摘录。二者不能把“已枚举成员”与“已检索全部正文”混用。二进制资源只按 owner 声明的元数据能力参与，不假称已全文检索；正常文本读取故障按 owner 错误分类处理。

多通道部分可恢复缺失时，来源范围和 missing_channels 分别披露。由 result 派生时保留原来源覆盖事实，不能因为重新排序成功就把原缺失通道改成已完成。

### 9.3 result 来源使用冻结内容投影

source=result 使用旧视图的成员、属性与内容单元快照。可以在新 current Context 下重新选择/排序，但不在背后重新读取 owner 最新文件并混合旧证据。若需要更新数据，发起新的 query/refs 请求。

由于旧视图内容可能是 excerpt，新的 criterion 不一定在这些片段中获得充分依据；结果应继续显示该覆盖事实，Agent 可主动选择新 refs 来源或 Inspect。不能把旧的显示片段扩充成未读取内容，也不能把 result 重排称为全文重新检索。

新视图中的 evaluation.step_index 只引用本次请求的 steps。result 输入保留来源内容与历史证据出处，但不能将旧视图的模型评估冒充本次新执行的步骤；本次没有语义模型步骤时省略新 evaluation。旧视图的翻页继续保留其原评估事实。

由 result 派生的新视图共享不可变内容单元，保存自己的成员与顺序；不逐步复制全部正文。只注册请求最终视图，不默认保存管道每一步的可恢复 checkpoint。若 Agent 需要保留中间集合，使用多次独立调用即可。

Turn/profile 关闭清理相应视图；SDK 继续受 generation/day lease 约束。沿用有界视图缓存及明确过期反馈；不承诺跨 Turn 的 result_ref，不让 SearchView 承担持久任务状态。

## 10. 失败、时限与观测

显式步骤意味着实际执行承诺：请求了 rerank/select，若该步骤没有完成，不能静默返回上一步结果并把整条管道标成成功。删除当前“可选 semantic 阶段失败后当作成功返回”的歧义；用户想要纯 query 可不写 steps。

这不改变 AGENTS.md 的三层失败：

| 情形 | 边界 |
| --- | --- |
| 无效 ref、错误 where、当前 binding 不支持该 Context、来源/模型输入超容量、可修正的选择输出协议错误，以及现有分类认定可恢复的暂时不可用 | owner/retrieval 的有限局部反馈，由 Action/SDK 转换；允许父 Agent 修正或重试下一次调用 |
| 不可恢复的模型链失败、provider/存储故障、配置或内部不变量失败 | 保持所属模块的失败类型与既有 Runtime bridge，不泛化吞掉异常或伪造空集 |
| 取消、总时限及 Runtime 转移 | 复用 Action/Turn 现有机制，不给每步增加独立线程/恢复循环 |

当前 `LLMInvocationFailure.recoverable` 已区分因 transient provider 错误导致的链耗尽。此类失败可由操作层转为有限失败；本稿不把所有链耗尽升级成结束 Turn，也不把所有链耗尽降为普通空结果。

query 的内部多通道与显式 steps 不是同一层：若某个通道按既有分类属于可恢复缺失，而另一通道已正常完成，可返回有明确 coverage 的部分召回；不能标成完整混合检索。没有可用来源则失败；真正的模块异常仍按原分类传播，不因“有 lexical”一概掩盖。

局部失败反馈包含失败步骤、有限原因和可修正建议，不带全 Context、正文或原始异常。请求不会因为中途失败自动发布一串中间视图；这避免增加恢复状态机。已有可复用 result_ref 不受派生失败影响。

Observation 复用现有体系披露 source、操作顺序、每步输入/输出数量、模型用途、实际模型尝试、内容覆盖及耗时。为前端提供事实，不另建同步业务状态或独立审计日志。

## 11. 各 owner 的本轮落地范围

下表是本轮确定实施范围，不代表所有能力已经在基线存在。只开放真实支持的组合，由 capability/schema 约束。

| owner / Action | 来源 | 操作 | owner 的必要改动 |
| --- | --- | --- | --- |
| Home / home.search | query、backlinks、directory、refs、result | filter；LLM/JEV select；LLM/JEV/Embedding rerank | 保留全公开空间检索；Skill query 按 top 聚合并保存深层命中内容；其它资源直接返回 resource；精确 refs 范围；统一向量内容键 |
| Memory / memory.search | query（文字/文档）、backlinks、directory、refs、result | filter；LLM/JEV select；LLM/JEV/Embedding rerank | 结构化反链补来源正文；错误 seed/document 引用局部归类；保留五类文档与真实边语义 |
| Context / core.context.search | query、backlinks、directory、refs、result | filter；LLM/JEV select/rerank | segment/session owner 提供事实/解释内容；无 Embedding；inspect 仍确定性披露 |
| MCP / expand.search | directory、refs、result | filter；LLM/JEV select/rerank | 在已有 select 上补 rerank 声明；真实工具定义为内容；describe 不变；不伪造词法 query/backlinks 能力 |
| Workspace / workspace.search | query（文字/正则）、backlinks、directory、refs、result | filter；LLM/JEV select/rerank | 本轮增加真实内容选择/排序用途；适配现有逐行匹配、文件范围与属性；不引入 Embedding |

Workspace 新增 select/rerank 已获确认；当前基线主要是原生 text/regex query 与无模型反链，不能把新增支持计为已实现。其原生匹配器、行号、列号和上下文行保留，作为候选来源适配到同一 SearchPage；read/write/edit 的文件操作语义不变。

Workspace 仍允许 literal/regex 这类业务匹配参数，由 owner query schema 表达。它们不是任意模型选择；不得为了统一而删掉实用的本地文件能力。现有外部 search/search_backlinks 分叉迁移到一个 SDK 检索入口，内部 matcher 可以继续保留明确实现。

Home 普通 Skill 的默认入口仍由 Context 中 Skill meta 线索和 Stage1 渐进加载构成；search 是补充发现能力。Reflection 按自身 profile 提供有效来源视图，通用查询不固定 home_search 模型；actual/diff/review 保留 Home 业务职责。

跨空间 anchor 继续由目标 owner 解释身份，来源 owner 只扫描自身。refs/result 输入也属于当前 owner；不在单条管道接受混合 owner 候选。跨 owner 查询由父 Agent 分别发起，再沿各 ref 读取。

Stage1/Stage2 JEV、图像生成、Web Search 统一、全局向量库均不在本轮范围，不以占位类型或空 runner 预留。

### 11.1 各插件必须真正提供的检索基础设施

| owner | 来源基础设施与本轮适配 | 合法范围/属性基础 |
| --- | --- | --- |
| Home | 复用 effective Home 路径集、Skill metadata、正文分块、Markdown 边、owner EmbeddingIndex；query/directory 先建立 top/resource 聚合元数据再应用 where；refs 用现有读取器精确定位；实际 Home review 视图保持独立 | scope 为 all/agent/skills；space；resource_types 明确集合成员语义，取代聚合场景含糊的 file_type |
| Memory | 复用 catalog、五类文档存储、结构化及 Markdown 边、owner EmbeddingIndex；文档 query 与 refs 复用引用归一化；directory 按 catalog 枚举并准备正文 | scope 为 all 或五类 kind；kind/status/updated_on/confidence，类型按既有文档字段定义 |
| Context | 复用 SearchableSegment / DisclosureSearchEntry 及 Session 的 facts/interpretations 入口；directory 与 query 共享来源，refs 保持现有按种子分派到 segment/当前事实的边界，仅展开所请求身份；不 seal trace，不新建持久副本 | all/trace/session；source/basis/kind/day 使用 owner 事实属性；不存在时不推测 |
| MCP | 复用现有 server/tool 目录及定义缓存；directory 得到真实工具对象；refs 定位同一目录内的工具并取得其完整/有界定义；result 保留当次定义快照 | all 或 server:<id>；server_id/tool_name；名称不被误拆成路径 |
| Workspace | 复用 reconcile/manifest 的当前资源集、真实文件读取、literal/regex matcher 和 Markdown 边；拆开旧 matcher 的匹配与 top_k 展示截断，输出完整合格资源成员及匹配行/列/邻近内容；directory 不按关键词裁剪 | 复用 WorkspaceSearchScope 的 workspace/directory/file；kind/suffix/tags 等实际 manifest 字段，文本和非文本内容能力如实声明 |

Workspace query 仍以支持的文本内容进行匹配；directory/refs 可以返回非文本资源的真实 metadata 并标为 metadata。对后者的 select 只能声称按说明/元数据选择，不能声称理解了图片或 PDF 正文；使用现有转换/读取动作后可再检索得到的文本资源。本轮不附带新建多模态解析管线。

source adapter 负责资源身份、范围、内容读取和实际边；公共 query 操作负责调用已配置 channels、融合与命中依据。普通正文 lexical scorer 可复用，Workspace 注入有 literal/regex 语义的 matcher；matcher 返回带内容位置的 ChannelHit，不返回已经按页面 top_k 裁掉的结果。共享引擎不使用 action_id 字符串分支来调用第二条 Workspace 查询管线。

来源公开边界只有一条：解析与能力校验 → owner 来源准备 → 配置通道（query 时）→ CandidateSet → 显式 steps → SearchViews。result 在 SearchSession 内取既有视图，不回 owner 重新建 corpus。所有来源准备、匹配、内容提取共用本次取消和 Action deadline。

### 11.2 SDK、Action catalog 与 Endpoint 对接

- Action executor 和 SDK 服务调用同一个 SearchSession；一个来源 adapter 不复制出“SDK 搜索”和“模型搜索”两套逻辑。Workspace 的旧 search/search_backlinks 外部入口合并，原生 matcher 留作内部实现。
- SDK 不因为存在 source/result 就拥有某个活动 Turn 的 Context；独立服务缺少 Context 时 current 得到明确请求反馈。MCP 目录可由其来源服务获取，SDK 不伪造 core.context.search 的活跃事实来源。
- `GET /v2/config/actions?scenario=...` 保留现有路径；将旧 search_modes 投影替换为 retrieval：sources、operations、owner 范围/属性、query 语法能力、每步 effective_context、页上限及 model_uses。情景可用服务参与计算，不能只看静态配置。
- `GET /v2/config/catalog` 描述 action.retrieval 及现有 action.models.bindings、infra.model_services；Home/Memory 的 embedding_use 引用相同模型用途目录。`GET /v2/config` 仍披露已保存配置与当前生效 generation，不能把候选配置显示成正在运行的绑定。
- `PATCH /v2/config`、`POST /v2/config/reload` 继续复用现有批量保存/重载协议。含点的 Action ID 是 map key；将 `action.retrieval` 注册为 object 值整体编辑，PATCH 不把 `home.search` 或 `core.context.search` 拆成嵌套路径。前端若编辑一个条目，应提交基于当前配置构造的完整对象。
- 更新 `docs/endpoint/configuration.md`、`docs/endpoint/frontend-integration.md`、受影响的 `docs/endpoint/events.md`，说明旧字段替换和实际结果/Observation 结构。当前没有声明一个新的 HTTP search 执行端点；不能把配置 catalog 当聊天 Action 调用 API，也不为未来页面虚构现成接口。

每步 Observation 带 search 调用身份、step_index/op、输入输出计数、模型 consumer、实际 provider/model、覆盖与耗时；模型相关明细继续使用既有 normal/verbose/model 分级。业务结果仅保留必要候选及依据，前端不靠 replay 重建资源 owner 状态。

## 12. 代码组织、实施顺序与验收

### 12.1 沿现有模块重构，不并行保留旧协议

| 位置 | 目标职责 |
| --- | --- |
| `kernel/retrieval/contracts.py` | source 请求 union、step 请求 union、Candidate/ContentUnit/Evidence/CandidateSet、页面和有限失败类型；frozen dataclass + StrEnum |
| `kernel/retrieval/requests.py`、`policy.py` | 动态 JSON/TOML 转 typed 对象；统一能力与预算；生成 source/step oneOf schema |
| `kernel/retrieval/engine.py` | 来源结果组织、通道融合、确定性 filter、内容/页面投影及 SearchViews；避免继续承载裁剪后才判断的旧路径 |
| `kernel/retrieval/selection.py` | select/rerank 的实际内容准备、用途绑定、LLM/JEV/Embedding 调用及结果不变量；不成为通用模型 runner |
| `kernel/retrieval/operations.py` | SearchSession 门面、source/步骤组合、一次 Context 快照、lease 和调用 Observation |
| `kernel/action/models.py` 与 catalog 投影 | `.rerank` 等 model-use 声明、绑定校验、可用 Context 与实现能力；复用已有调用路径 |
| 各插件 engine/actions/services | 单一 owner 来源协议、范围与属性、内容单元、真实关系、局部失败映射；Action/SDK 调同一服务 |
| `infra/model_services/vectors.py` | 修正局部请求覆盖缓存；保持 provider 空间一致，不拥有业务检索流程 |
| 默认配置、AGENTS、design、endpoint | 同步实际落地语义及接口字段；移除旧 mode/semantic 运行协议与无消费者配置 |

配置/资源文件同轮同步：标准和开发的 `configs/action/routing.toml` 继续保存 model bindings，新增 `configs/action/retrieval.toml` 保存 action.retrieval，删掉 routing 中旧 search_policies；两份 Home/Memory 配置与模型目录同时验证。源代码对应 `assets/standard`、`assets/development` 及 common catalog 模板，不只修改一个生成后的项目。

`tinysoul/assets/common/configs/action/catalog/` 下 Home/Memory/Workspace/Expand 的 search、Core 的 context_search schema 与说明，以及 `assets/common/home/skills/tinysoul-docs/` 的实际用法一并更新。模型必须从工具说明理解何时使用 query、directory、backlinks 和各步骤；不能仅 parser 已支持新参数、给 Agent 的提示仍教旧 mode。

删除清单至少包括旧 SearchMode / SearchSemantic、SeedRefinement 强制 selector 规则、旧 mode policy parser/schema 分支、`.rank` 操作用途、result_limit_omitted、静默 candidate_limit/top_k 截断、无消费者 MEMORY_DAILY 和旧 Memory semantic_search 设置名。历史归档文本和合法的结果排序序号无需机械替换。保留原生匹配器及 provider/model 服务的真实复用逻辑。

优先在现有文件重新划分职责；文件确实过大时按内容投影或视图管理拆分，不为每个操作生成一层无行为 wrapper。依赖方向继续是 infra → runtime/llm → kernel → plugins → agent → gateway。

### 12.2 本轮完整交付顺序

以下是实施依赖顺序，不是先做部分、把语义缺口推到下一轮的演进安排；本稿范围需在同一轮完成。

1. **固定契约与配置**：source/steps/page、select 稳定子集、rerank 全排列、result 生命周期、操作能力矩阵及异常分类；替换旧 mode/semantic parser 与用途名。
2. **内容与向量基础**：ContentUnit、命中依据、真实反链正文、owner 属性/范围规范、F2 缓存；模型输入和显示投影分离。
3. **公共组合与视图**：来源、filter/select/rerank、basis 输出、完整结果分页、result 派生；总时限和 Observation 复用。
4. **所有 owner 接入**：Home/Memory/Context/MCP/Workspace 同一链路；补新增用途，修 F3；SDK、Action schema 和 Endpoint catalog 同步。
5. **清理与文档**：F4、`.rank` 配置迁移、旧 mode/semantic/result_limit 语义删除、AGENTS 与 design 更新、默认标准/开发模板一致；已归档文档保留历史事实。
6. **必要验证与最终门禁**：少量行为用例覆盖真实风险；代表性 LLM/JEV 请求；按项目 Full/typecheck 运行并记录实际工具版本和结果。

不为旧 JSON/TOML 协议保留 alias、双解析器或隐藏转换分支。前端对接应以新的 capability/model-use 投影为准；本轮只实施后端及契约文档，不据此声称前端已迁移。

### 12.3 行为验收

1. 无词面重合但深层资源向量命中：候选、真实命中单元、selector 输入和页面都保留语义依据。
2. lexical/Embedding 任一产生的有效候选均不会被另一路否决；where/exclude/select 的排除可以追溯到显式请求。
3. refs/select 无隐藏词法或向量预筛；fragment 只读取指定范围；完整性进入 LLM/JEV 输入。
4. Markdown 和结构化 backlinks 同时返回真实关系与正文；select 不加入没有入边的新对象。
5. select 返回稳定子集或空集；rerank 保留全部成员；`query → rerank → select` 保留排序效果。
6. filter 无模型调用；source.where 与 filter 复用比较语义但不被自动换序；Home 聚合属性真实。
7. 小 page.limit 可续接所有最终成员；翻页不调用模型，不改变 Context 快照；内容级 Inspect 与结果分页不混淆。
8. result 再操作使用整个旧集合的内容快照，不只上一页；新的 current 可改变判断；原结果和 continuation 不变。
9. 当前请求超模型/来源/视图容量时明确 scope_required，不静默截候选，也不伪称全局完成。
10. 用户 binding 切换 select JEV/LLM、rerank 三种实现及 query Embedding；Agent 请求无 provider/model 参数；不支持 Context 的实现不开放 current。
11. LLM basis ids 与 JEV Score/Choice 对应真实输入单元；错误协议沿局部反馈处理；依据预览不引用模型臆造原文。
12. discovery → similarity rerank → 相同 discovery、不同 scope 往返复用未变内容向量，provider 空间仍隔离。
13. Memory 不存在的 refs / document query 得到局部失败；实际存储故障没有被错误转换成空结果。
14. exclude_refs 不持久化；seen/unselected 不自动入黑名单；同内容在不同 Context 中可以重新考虑。
15. MCP 真实目录和 Workspace 正则/行范围能力经同一结果协议工作；没有新旧检索入口并行承诺不同语义。
16. 显式操作失败不报告整条成功；总 deadline/取消仍只有既有 Action 机制；辅助模型调用不解除 Inspect 展示保护。
17. 默认项目不存在 MEMORY_DAILY 等无消费者配置；当前设计文档、AGENTS、catalog 和 Endpoint 与新实现一致。

18. 不给任何目标 refs、也无词面重合时，Context/Workspace/Home/Memory 的 directory → select 能依据实际内容返回真实链接；MCP 继续从真实工具目录选择。每个 owner 只验证自身有差异的来源部分。
19. 同一资源多个匹配单元保持一个资源候选；Skill top 与深层 evidence ref 同时正确；refs fragment 不被全量 corpus 或 top 覆盖。
20. where 聚合属性、source 排序、filter 保序、result 复用语义一致；给 result 的排除条件不触发磁盘重读。
21. 每一步实际输入预算与 candidate snapshot/page 预算分开；配置实现切换时 effective_context/schema/SDK 同步改变，不出现允许 current 但运行时只支持 none 的投影。
22. 配置保存/重载、含点 Action ID 的 object 编辑、标准/开发生成、catalog 和实际默认 binding 一致；可不配置专用模型而使用默认 LLM/lexical 路径，显式启用专用模型则必须解析到有效用途。
23. 工具 schema、内置 Skill 帮助与新的 JSON 示例一致；独立 SDK 和 Action 共享语义，但没有凭空注入 current Context。
24. 空结果正常结束、超小页预算不会零进展循环、候选正文覆盖与模型实际输入覆盖不互相冒充。

无需大量排列组合快照测试。公共步骤不变量在 retrieval 覆盖一次，各 owner 测真正不同的范围、内容和失败边界；联合链选择代表路径即可。

## 13. 已有验证记录与本稿验证边界

本次在独立检出中检查，没有覆盖先前工作目录的未提交文档。运行环境为 Linux、Python 3.13.15；没有 PowerShell/Conda，使用与脚本 Full 相同的 pytest 选择条件 `-m 'not external'`。测试均使用临时/隔离路径。

| 验证 | 实际结果 | 解释 |
| --- | --- | --- |
| 非 external 全套 | 1,150 passed、12 failed、6 skipped、25 deselected，108.75 秒 | 失败集中于审查环境缺少 SOCKS 支持/打包工具，以及本地 HTTP 代理影响；包含失败 client 析构引出的诊断 |
| 修正环境后，只重跑上述失败项 | 12 passed，21.95 秒 | 安装环境所需 socksio、pip、wheel，对 loopback 设置 NO_PROXY；未修改生产代码或测试断言 |
| 合并上述两次覆盖 | 1,162 个不同用例通过，6 个跳过、25 个 external 排除 | 这是全套加失败项复跑的覆盖统计，不声称获得了新的“单次完整 Full 全绿”记录 |
| `ty==0.0.57` | All checks passed | 项目声明的最低开发版本 |
| 新安装的 `ty==0.0.84` | 4 个类型诊断 | 见下文，不将其等同于运行时架构失败 |
| F1/F2 复现 | 确定性通过复现 | 使用真实 SearchEngine/EmbeddingIndex 逻辑和模拟向量/HTTP，未调用付费模型 |
| F3 复现 | 确定性通过复现 | owner 两类请求和 MemorySearchExecutor 边界均确认裸 ReferenceError |
| 本轮真实 JEV/LLM 调用 | 未运行 | 仓库第 16 节已记录两类各 9 次代表性请求；本次没有将这些历史记录写成本次实测 |

最初另一次运行因审查命令未创建 basetemp 父目录产生大量 setup error，已纠正，不作为产品问题，也不计入上述有效覆盖。

新版 ty 的四处诊断是：

- `infra/model_services/protocol.py:96`：`dict[str, str]` 写入递归 JsonValue 的类型推断。
- `kernel/action/engine.py:743`：visibility 字典返回 JsonObject 的类型推断。
- `kernel/retrieval/policy.py:222`：未约束泛型 `E` 的构造调用。
- `plugins/session/actions.py:78`：payload 中 created_refs 的递归 JSON 类型推断。

这不是 F1–F4 的行为原因，但 `pyproject.toml` 允许 `ty>=0.0.57`，所以新开发环境会遇到门禁不一致。建议在补强时用明确 JSON 边界转换/类型和 enum 泛型约束修正，记录验证工具版本；不建议用批量 ignore 或扩大 Any 压制诊断。此项状态：`pending`，不需要架构决策。

现有测试已经覆盖很多重要契约，仍遗漏 F1 的“召回到披露”、F2 的“同一 owner 不同操作连续执行”和 F3 的“来源引用失败到 Action 局部结果”这几个协作边界。补这几个实际行为，比继续扩大单函数快照数量更有价值。


上述测试数字属于先前对基线的实际验证，本次 r4 仅整理设计文档，未重新运行生产测试，不能把这些数字当作新 source/steps 协议或 JEV 依据选择已通过验证。

## 14. 确认状态与执行跟踪

### 14.1 已确认且不再阻塞实施的设计

- 统一 source + steps + page，支持单步与有限线性组合，保留各 domain 的 search 入口。
- 用户配置操作内部实现/模型/provider 链；Agent 自主构造来源、查询语句、业务条件和操作顺序。
- select 稳定子集、rerank 全排列、filter 确定性属性判断；显式步骤失败不静默跳过。
- result_ref 复用完整结果集合及冻结内容投影；continuation 只翻页；更新来源内容时重新读取。
- 真实内容预览、lexical/Embedding 互补、内容覆盖披露、全部最终结果可分页。
- 请求级 exclude_refs；不新增跨语境永久负面索引。
- Home 的聚合规则、跨空间 anchor 与单一来源 owner、确定性 Inspect 和 Background load/evict。
- MCP 补 rerank，Workspace 补 LLM/JEV select/rerank 且不做 Embedding。
- F2 缓存、F3 引用失败和 F4 配置/文档清理。

r4 将 directory 的 owner 枚举能力、配置准确性、预算/身份/请求变体和交付验收补齐，落实已确认的“主动构造查询、从无到有发现 Links”目标。没有新增需要先由维护者选择才能继续实施的架构分歧。

### 14.2 完成清单

| 工作项 | 当前状态 | 完成证据 |
| --- | --- | --- |
| C1 来源/步骤/分页契约与类型化 parser | pending | 单一 schema、请求变体、能力约束及单步/组合行为 |
| C2 F1 内容单元/命中证据/模型投影/分页 | pending | 真实命中片段贯穿模型与返回结果；全部最终成员可续接 |
| C3 F2 owner 向量缓存 | pending | A → B → A、跨 scope、provider 空间的代表性验证 |
| C4 操作实现与用途配置 | pending | select/rerank 三类实现能力、同源配置投影、JEV/LLM 实际调用 |
| C5 五个 owner 的来源基础设施 | pending | query/directory/refs/backlinks/result 支持与明确不支持项；资源身份/范围验证 |
| C6 SearchViews/result/SDK lease | pending | 冻结内容复用、不同 Context 再判断、过期与分页行为 |
| C7 F3 与管道失败语义 | pending | 请求引用错误局部反馈、显式步骤不跳过、真实模块故障保持归类 |
| C8 F4、旧协议/配置清理、catalog/Endpoint 文档 | pending | 无旧运行协议/无消费者配置；标准与开发模板、接口文档一致 |
| C9 验收与 Full/typecheck | pending | 聚焦行为用例、工具版本、最终实际门禁记录，无历史结果替代 |

实施者逐项填写位置、证据和状态。全部完成前保留在 docs/analysis；只有代码、配置、当前设计/Endpoint 文档及必要验证全部核对完成，才加 -done- 并归档。

### 14.3 实施中需要验证而非重新选择架构的事项

输入/快照/页面预算的实际默认数值、JEV Score+Choice 的代表性效果及成本、Workspace 长文本和 Home 多资源 Skill 的内容投影质量，需要通过实际样例与性能反馈确定。它们属于本轮验收，不以“后续演进”代替。

若真实模型协议无法承接已确定的输入/输出，或性能证据要求改变“全体成员评估、单次模型步骤”的承诺，应明确记录冲突再讨论。不要在实现中偷偷加入分批多轮排序、跨实现 fallback 或静默截断来让测试通过。

## 15. 本次交付与提交说明

本次新增 `docs/analysis/20260926-action-model-retrieval-review-and-refactor-plan-r4.md`，作为已确认方案的完整执行稿。保留 r3 及旧 review 供核对历史；未修改生产代码、AGENTS.md、归档主计划或测试，尚未实施本稿方案。

本次检查范围为设计完整性、现有代码对接可行性、协议/配置示例和文档一致性；未重复运行生产测试或付费模型。当前代码事实与新目标契约在文中分别标明。

建议提交说明：

```text
docs: finalize unified retrieval composition and implementation review
```
