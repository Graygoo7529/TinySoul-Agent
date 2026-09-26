
## 20260924 初始设计思路

请重新加载 AGENTS.md，结合当前实施情况进一步理解整体设计语义；之前，我们讨论了 docs\chat\20260924-visualization-backend-support-plan-r4.md 和 docs\chat\20260924-action-model-usage-architecture-proposal.md（这两份文档是本轮重构的触发点，仅作为参考，还需要进一步根据下面的最新思路要求深入分析和设计，结合对当前后端的思考：哪些模块有“检索”行为的特征？都是如何进行的？）

因此，在前端重构和后端功能支持计划之前，我觉得有必要先进行一轮新的、彻底的后端重构，本轮重构无需向后兼容、允许重新设计整体架构和细节，以达成最佳效果的后端重构，重构主要面向项目中 actions 中多类模型的配置和使用，和信息披露和检索语义的统一设计和基础设施；这不是对现有实现的调整，而是要在下述思路下具有想象力、创造力和清晰、统一设计思路下，完整地重新设计。本轮重构也不要考虑后续先做部分，再后续继续演进（需全部设计清楚并在本轮重构中落实，以实现最佳、最干净一致的架构效果）。本次重构分为两方面，如下：

（一）llm_action 的重新设计和多类模型的配置和切换。 

（1）当前，action 会标记 backend 为 native/subprocess/llm_action，可以考虑将 llm_action 表达为更抽象设计层次，使其整体设计干净一致；当前 handler 的含义是什么，是定义 action 的操作语义、还是后端可复用的处理方式，model 请求可以抽象为一种 handler 吗？Action 执行体系可以进一步分析设计，在本轮重构，使其复用、可扩展，在设计语义上清晰明确； 
（2）有些 action 需要嵌入 model 进一步操作，把 action 对于模型的请求抽象为 input->model->output，而 input、output 的语义和结构由具体 action 负责；从 model 类型上，有 llm、Jev（关于 Jev，可了解 docs\example\JevUse）、嵌入模型 Embedding、图像生成模型（后续配置，本轮不做）等；从请求语义上，有些会给与当前完整 context 和额外输入，有些仅给与局部的输入（但这个应该属于具体 action 管理而不是通用 model 请求抽象管理，model 请求抽象应只管理从输入到输出、以及具体用的模型/链）； 
（3）本轮重构还需要考虑对于模型的配置，Jev、Embedding 先做成一种抽象模型能力（类比 llm 模型链，但可简化为一对一模型实例），对应到实际模型配置，如 Embedding-3（当前使用，但类比 llm 模型配置，应允许先配置 provider，并支持多个 provider 的排序和切换）；此外，我们还需要考虑对于部分 action 中 llm 模型和 Jev 模型的可配置和切换，例如允许配置某些候选、检索行动选择使用 llm 或这 jev，但这种切换需要进一步设计是在 action 执行层做还是 model 请求层做，我更倾向于在 action 执行层做，因为输入可能需要根据所用模型改变； 
（4）当前实施情况下，reflection actions 相当于特殊情景下对 home/memory domain 的扩充，因此，如 home.top.search 这样的行为不应该固定 home_search；所有 action 内使用的模型请求（在模型的配置和使用上）通用统一，对于特定类型的任务（如，语义检索、候选项提取或排序、以及更有应用语义的任务，如语境下的文档撰写、语境下的链接提取、语境下的反链探查等等）可考虑提取为可复用的基础设置；这个问题可以结合下一个方面一起考虑。

（二）TinySoul 语境信息披露和检索语义的统一设计和基础设施。 
注：不考虑 web search，这个工具使用外部 api 接入 
（1）首先，我们将这一套体系抽象为几种方式：
- 基于 context 的迭代式、渐进式信息披露 Inspect：由于我们设计了非常良好的链接体系，由 Agent 自主决定从当前已有的语境中输出需要进一步探查的链接，可以再从输出链接的召回中获取信息或进一步探查的链接线索。
    - 模式：Context -> Agent -> Links/Refs -> Contents（先当于从 context 中给出一批需要深入的链接，以及打开 Links/Refs 实际内容）
    - 额外模式：查探反向链接 Context -> Agent -> 基于已有 Context 给出需要查询反链的 Link -> 检索该 Link 的反向链接（这里可能还涉及筛选、重排序），后半部分查询反向链接严格来说更像是 Search 的变种，原始 Link 即是 Query，模型输出给出候选链接；不过，因为这里使用了 Context，所以暂且放在这里先说明；
    - 相关模型：LLM or Jev
    - 说明：上面模式里提及的 “Agent” 不一定指 stage3 里的 action 使用模型请求，因为当前实现下可以是由 stage2 指定参数去进行 Inspect；Inspect 在这里体现的是 TinySoul 信息披露的设计理念；此外，Stage2 目前不考虑引入 Jev，Stage1 如果可行的话，可以考虑引入 Jev；
    - 另一方面，还有一个可以优化的地方是，可以考虑增加一个额外的 Search Action 从已有 links 中检索 / 给 Inspect 增加可选的语义预筛选模型步骤：目前主要模式是 Stage2 给出 Links，Stage3 直接打开内容并载回 Context；考虑可选地让 Stage2 先选出更多的潜在链接，先在直接载回 Context 前结合 Context+query+搜索范围进行语义预筛选，从而在扩大 Inspect 范围的同时展开更相关的内容；
- 基于 query 的关联信息检索 Search：Search 是给定 query 在特定空间的检索，和语境的关联没有 Inspect 那么大。由于语境的有限长度，以及语境是一种运行中的状态的事实，为了使得在 Agent 能够“从无到有”地召回链接或信息，可以通过构建 query 基于关键词或语义相似度地方式找到内容加入到当前语境中。
	- 模式：Query -> Model -> Links/Refs -> Contents（可以先返回一批候选和排序的 Links/Refs 并呈现主要摘要/关联内容片段，类似 web search）
	- 相关模型：关键词匹配 / Grep or regex 检索式 / Embedding 向量相似度 / 给定 Query + 搜索范围使用 LLM or Jev 来语义检索
	- 说明：可以考虑将相关模型的使用结合起来，例如混合检索将关键词匹配和 Embedding 向量相似度检索，某些适合的情景考虑使用 LLM/Jev 检索；更灵活的方式是这些模型都支持，让 Agent 在 Stage2 生成 query 时也决定 search 所用的模型和与之对应的 query；此外，检索结果可能也涉及筛选和重排序，例如在构建 Query 时使用基于标签和属性的筛选条件（标签如“数据科学”，属性如“文件类型”、“创建时间”，这里只是举例，当前有些 plugin 可能并没有设计标签和属性，因此筛选可作为一种附加选项，我后续会做 ChatGPT 那种 Libraries 会存放各种类型的外部资料可能会用上）；Search 结果可能还需要结合 Query 或 Context 进行重排序；因此，除了 Inspect 和 Search，我们还可以考虑将结构化筛选、语义筛选（使用 llm/jev）、语义重排序（使用 llm/jev）等设计为操作原语，并在 Inspect / Search 中使用它们；
（2）对于当前的几个 Plugins，进一步分析、检查和设计：
- Context：检查当前对于当前 Turn 的执行事实和对于 Session 交互历史的 Inspect 是否是公用一个动作；此外，考虑对于 Context 实现 core.context.search，可以考虑是对既有链接进行精炼，也可以考虑使用 query 从那些 Session/Turn 里直接 “从无都有”地发掘关键信息；
- Home：首先检查当前对于 Home 中通用 Skill 的加载应当是通过 Inspect 方式进行的，即 Context 中带有 Skill-Meta 段呈现了通用 Skill 链接允许 Stage1 来渐进式加载它们；此外，当前 Home 检索范围仅仅限于 skills 是错误的，应当把 Home 空间都纳入为搜索空间，并考虑返回 top 链接、摘要/相关片段（片段可以包含 ref 链接内的内容，即 skill 可能应为其中 ref 的局部与 query 产生关联，但 home search 返回 top，再通过 Inspect 机制到局部 ref 即可）；home.top.search 可以改名为 home.search，检索方式可以重新设计，例如使用混合检索或自行决定检索策略；
- Memory：当前 Memory 方案相对齐全，但需要考虑和整体设计一致；实际上，当前 Memory 的 Recall 有点类似上述的 Inspect 语义，而 Memory 的 Inspect 实则类似 Search 语义；需进一步检查、分析和设计到整体设计的抽象原语和基础设施下；
- MCP Expand：MCP 的 search 类似给定 Query + 搜索范围来语义检索；MCP 目前还有 describe，先列举 servers，再列举 servers 下可用 tools，接近 Inspect 语义；
- Workspace：WorkSpace 可以灵活一点，不一定要完全符合上述设计；一是因为 Workspace 已有对其中资源的描述、二是对 Workspace 做 embedding 不合适、三是目前 Agent 对于本地文件的操作方式很灵活；作为建议，我觉得 Read 实际上可作为一种 Inspect，对于长文本是逐步/按需去读取的；而 Search 可以提供比较灵活的关键词、正则检索、query+范围检索筛选等等检索策略。

关于 Jev 是什么，可见 docs\example\JevUse，如有需要，你可试用 key（允许该 key 出现在当前会话中）

请进一步深入分析以上方案是否合理可行？请根据以上思路分析和设计完整的后端重构方案，然后撰写完整的执行计划；根据你撰写的执行计划向我呈现重构方案预览，与我进一步讨论确认，深入修订执行计划。


## 20260925 search strategy

search strategy 可以这样考虑和设计吗：Stage2 Search 所用的 strategy 应和 strategy 中本身所用的模型、如何用模型区分，strategy 语义有三种模式：（a) query discovery，此时适合先使用[可选地] lexical+embedding 产生 generation，并支持输入 scope/filter （约束检索空间的范围/检索结果的属性和标签），然后还[可选地] 通过 embedding/llm/jev 来重排序；注意这里的 [可选地] 指用户配置，stage2 agent 可选性应当为 strategy 模式和参数；（b）seed_refs 上的候选精炼，这里 query 的 scope 可以是 seed_refs 所张成的内容空间，可能需要通过互斥的 llm/jev 来实现；例如，MCP search 以全局/server 下的 tools 名称和描述为 scope，由 llm/jev 决策与 query 关联的工具；（c）反链检索，如果可以，我们最好还能支持通用意义上的反链，即我在 markdown-A 中用标准 md 链接链接了 markdown-B，那么 markdown-B 的反链会包含 markdown-A；反链检索可考虑进一步结合 embedding/llm/jev 重排序；此外，局部步骤 embedding/llm/jev 虽然都是重排序，但实际上输入形式可能是不同的，但最终又是可以配置、使用和替换的环节；此外，可以考虑使用 llm/jev 时是否（agent stage2 可选）带有完整 context 语境，我觉得重排序可以默认没有，候选精炼默认有，但 MCP 候选精炼默认没有；



## 20260926 函数组合支持重构

目是把 search 做出能够让 agent 主动构建不同查询方式并得到“从无到有” links 结果的统一工具，查询方式能支持候选来源（以及查询语句）和候选操作的灵活组合，并为每一种函数操作实现好更底层的模型配置使用和具体插件中使用的检索基础设施。

考虑一下几个方面：
（1）search：query、select、backlinks 当前输出结果是否给出返回 refs 指向资源的实际内容预览，特别是 query （语义）匹配的部分实际内容预览
（2）lexical、Embedding 应当是相互补充的，至少不应该用 lexical 来否定 Embedding；query search 结果也不应当被 lexical 裁剪，裁剪只能是因为基于显示 query 的“属性或标签” 而执行的“过滤”操作，或者是返回数量过多而有界展示（可续接）
（3）在原始的设计思路里，基于 llm/jev select 的输入，模型不应该仅仅看到 ref 和零碎的信息，而应该看到 refs 实际内容的展开，至少也应该是真实片段内容预览
（4）此外，让我们考虑一下：“语境下的检索排除性/顺序性”，避免总是检索已经证实无用的内容，即能够在不同的语境/state下给出的重排/select结果是不同的，也许用 llm/jev 来重排序或 select 已经相当于这个能力？


在设计和实施上，我们之前为 search 总体设计为 query、（seed）select 和 backlink 三种模式；现在请进一步权衡和设计：我们当前实施实际上还有 rerank 操作和过滤 filter 操作，是嵌入在 query、backlink 的给出的候选 refs 步骤之后的，但是现在看来它们和 select 又是同一层次的函数，你觉得是否可以扩展 search 模式，使 agent 能够决策的函数操作粒度更细、更灵活，例如纯 query、backlink、directory、select、rerank、filter（前三者是发掘候选，后三者是约束候选）？即允许单步操作，也允许在 search 以函数式管道的方式直接组合操作例如 query->rerank->select？每一个操作函数都有比较清晰的输入（例如 select 输入候选 refs 以及候选链接所展开真实内容预览）和输出定义（例如 refs 和语义命中的部分实际内容预览，输出返回给 agent），同时有比较明确的边界和续接机制。请结合当前 review 里的几个问题和现有实施情况，进一步分析和设计可行的方案，如果有必要可以进一步重构当前设计和实现。
