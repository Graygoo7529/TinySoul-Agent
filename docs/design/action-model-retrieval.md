# Action 模型与检索基础设施

## 执行与模型用途

Action catalog 的 execution.executor 只表示业务执行器注册键。Action runner 统一负责批次、deadline、hook、取消和执行事实；executor 解释参数并调用所属 owner。模型调用是 executor 内部的一次 typed input → configured model/use → typed output，不形成另一套 Action 调度器。

代码贡献 ModelUseDescriptor，配置以 ModelUseBinding 绑定实现和逻辑用途。LLM 使用 task profile，JEV 使用结构化决策用途，Embedding 相似度引用 Home、Memory owner 已绑定的向量用途。模型服务负责 provider 顺序、协议、重试和关闭；输入、输出、候选语义与 Context 由调用 owner 决定。Stage1、Stage2 使用 LLM，Action 内部操作按其声明选择实现。

ModelServices 按 generation 共享客户端，按 provider → logical model → use 装配。Home 与 Memory 各自拥有可重建向量索引，缓存按 provider/model/use、抽取规则和实际内容身份隔离；缓存不拥有业务事实。显式 select/rerank 失败不会跨实现降级成另一个操作；query 的可选通道失败则保留已完成通道并报告缺失。

## 一个有限函数管道

Search 的公共请求使用 source + steps + page。Agent 决定已登记的候选来源、scope、业务条件、步骤顺序、criterion、Context 选项和页面；implementation/provider/model 与操作输入预算由用途配置绑定，请求不承载内部模型选择。

| 函数 | 输入与结果语义 |
| --- | --- |
| query | 在 owner 范围内从无到有发现候选；启用的 lexical 与 Embedding 独立召回后融合，任一路不能裁掉另一路的有效成员 |
| backlinks | 从真实引用边找出来源候选；来源 owner 解释边，目标 owner 解释身份 |
| directory | 枚举指定空间的真实资源、工具或事实，准备正文或明确的 metadata |
| filter | 以声明的属性/标签约束当前集合，保持相对顺序，不读盘、不调用模型 |
| select | 以 criterion 和可选 Context 选择稳定子集，可返回空集 |
| rerank | 以 criterion 和可选 Context 排列全部候选，不删除成员 |

三类来源之外，refs 是显式已知入口，result 是当前 lease 中的既有完整结果。两者不构成新的发现函数。没有 steps 合法；refs 纯读、refs → filter、refs → rerank 都不需要先 select。每一步 criterion 独立，不隐式继承 query。一次请求共用已经构造好的 Context；新请求可按新 Context 重评同一 result。辅助模型任务不解除 Inspect 结果的展示保护。

用途配置可以不开放任何约束操作。operations 省略或为空时，来源仍可独立使用；生成的 Action schema 与请求解析器均允许省略 steps 或传入空数组，并拒绝非空步骤。

source.where 定义来源资格，filter 只处理当前集合。各 owner 的 AttributeFilters 声明文本、文本集合、日期属性，共用 schema、解析和比较语义。多个属性同时满足；标量属性的列表表示允许值，集合属性要求包含所有给定值；日期 before/after 为严格早于/晚于。条件不会反向改写来源正文或重跑 query。exclude_refs 显式排除指定候选身份，seen 或低分不自动形成黑名单。

## 内容、命中和判断

ContentUnit 保存一次来源读取的真实正文、稳定资源 ref 与位置；SearchEvidence 只引用其中的范围，表示词法命中、向量贡献、真实关系或模型指认。SearchCandidate 组合身份、属性与内容；CandidateSet 表达有序集合及来源处理事实。两者均为查询生命周期内快照，不是另一套持久内容。

共享投影为模型输入与 SearchPage 生成 CandidatePreview。片段保存到 ContentUnit 的子范围映射，长行的起始列与实际匹配位置保持原文含义；匹配先在原始内容进行，不在拼接的展示摘录中查找。页面的 matches 定位本片段中的代表性命中，不保证列出全部出现位置。内部单元 ID 和模型短 ID 不成为可跨 Turn 使用的资源身份。

来源处理完整性、快照内容覆盖、实际模型输入覆盖、页面预览覆盖分别表达。全文、摘录和 metadata 使用同一有限覆盖语义；页面摘录不会改写快照，JEV/LLM 的有界输入也不会冒称读过全文。非文本资源可提供 metadata，但不能因此声明已理解正文。

LLM 同一次生成返回候选 ID 与 basis_ids。非空依据必须属于实际送入该候选的片段，框架据此引用原文，不接受模型重写正文或指向未给出的范围；空依据合法，属性判断、语境判断和低相关候选不必制造正向理由。select 按输入顺序返回选中成员；rerank 校验完整排列。依据证明的是引用合法性，不证明模型判断正确。

JEV 对每个候选做 Score，select 以用途阈值选择，rerank 以评分排序；不增加 Choice 调用，不宣称 JEV 指认了某段。Embedding 使用实际参与向量计算的内容单元，保留相似度贡献及其真实覆盖。模型评估不覆盖来源命中，结果只保存本请求最近模型步骤的评估及逐步数量统计，不累积评估历史。

投影优先安排当前模型指认，再为来源各通道保留片段空间，最后补充普通原文。lexical 命中不能吞掉 Embedding 深层命中的全部展示空间。LLM/JEV 对每个成员使用有界真实摘录，操作总预算包括 criterion、Context、指导、协议/问题及序列化材料；Embedding 按实际全文输入计量。所有成员都参与，超预算反馈 scope_required，不隐藏 top-k、不自动摘要或增加内部搜索循环。

## 来源 owner

Home Search 覆盖 actual Home 加 runtime overlay 组成的 effective Home，排除局部自动挂载的 domain/action Skill。query/directory 先按 Skill top 聚合资源与 resource_types，再应用资格条件，因此要求包含 .py 不会裁掉同一 Skill 的 .md 正文。backlinks 返回实际引用源资源。refs 精确读取所指入口和 fragment：Skill top 只读其 SKILL.md，与 Inspect 一致；要继续处理已经发现的完整聚合，使用 result。

Reflection 通用 Home Search/Inspect 同样读取 effective Home，可探查未接受的 overlay。Background 基线选择和 review/diff 的 actual 语义由各自服务负责；通用检索不授予接受 overlay 的写权限，也不表示所读内容已进入 actual Home。

Memory 以五类持久 Markdown 为来源；文本 query 与 document_ref query 都显式发布。后者由 owner 解析文档正文，并排除查询文档本身。refs 保序、去重、精确读取 fragment；旧文档仍能读出迁移说明，不隐式展开 redirect 目标正文。query 文档关联和 backlink 目标匹配使用 owner 的 redirect 身份解释。普通 Inspect 只读取内容及 direct refs，不包含反链。

Context 从当前 Trace 和固定 Session 原始事实/解释中发现内容，保持其日期和来源，不 seal trace、不提前 completion、不永久展开背景。日期条件与后续 filter 使用同一属性契约。

MCP 保留真实工具定义上的 literal/regex query；自然语言发现使用 directory → select/rerank，不经过词法预筛。完整工具定义进入候选快照，模型和页面可明确摘录，进一步读取使用 describe_tools；Search 的摘录不冒充完整调用 schema。没有 MCP 向量库或第二套工具目录。指定来源服务不可用时由父 Agent 缩小范围，不把不完整服务集合伪称成功。

Workspace 的 Action 与 SDK 共用一个 search 入口。owner 以 manifest 解析文件/目录/Workspace 范围与属性，读取真实正文及 Markdown 边；原生逐行 literal/regex matcher 注入公共 query 通道，保留锚点、跨内容单元匹配、原文行列定位及全部匹配成员。没有旧 top_k/片段结果协议或隐式向量索引。非文本资源可用于 directory/refs 的 metadata，query 不把它当作正文。

所有 owner 在读取候选正文前处理资格及排除，并按指定入口顺序形成 refs。排除只需规范身份，不要求被排除文件仍存在。短来源读取走既有 joined owner 边界；共享 retrieval 不解析业务路径、不持有存储、不按 Action ID 特判插件。

## 结果、分页与观测

SearchViews 冻结完整最终集合。page 的数量与字符预算仅控制展示，result_ref 指向全部成员，continuation 定位其中一页。页面不足以容纳有意义候选时明确反馈容量问题；更深正文使用 Inspect/read/describe，不建立 Search 正文游标。视图绑定 Turn/profile 或 SDK generation/day lease，结束后失效。

翻页只读取旧快照与旧评估，不重读来源、不重调模型。result 派生复用全部成员、顺序、内容、来源通道与缺失覆盖，清除旧评估和旧分数，再执行本次步骤；无步骤时不会调用模型。新模型步骤按请求正常调用模型。原视图不受派生操作影响，result 排除只比较冻结身份。

action.retrieval 是整体 object，内部含点 Action ID 是原子 map key。加载、生成、PATCH、保存重载共用该形状；修改某 Action 时提交完整 map，不提供点路径转义或多层 wildcard 补偿。

Observation 通过 search_id 和 step_index 关联步骤，LLM 调用同时关联既有 task_id，JEV/Embedding 关联既有 call_id；query 通道标为来源阶段。沿现有 verbose/model 级别输出，不新增审计存储。SearchFailure 表达有限可修正失败，owner 契约/I/O 与不可恢复模型失败仍在所属模块边界处理，取消继续服从 Action 总期限和生命周期。
