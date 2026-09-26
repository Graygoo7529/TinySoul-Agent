# Action 模型与检索基础设施

Action catalog 的 `execution.executor` 只表示业务执行器注册键。Action runner 统一负责批次、deadline、hook、取消和执行事实；executor 解释参数并调用所属 owner。模型调用是 executor 内部的一次 typed input → configured model/use → typed output，不形成另一套 Action 调度器。

Action 的模型依赖由代码贡献的 `ModelUseDescriptor` 声明，由 `ModelUseBinding` 绑定实现和逻辑用途。LLM 使用 task profile，JEV 使用结构化决策用途，Embedding 相似度只引用 Home、Memory 等 owner 已绑定的向量用途。模型服务负责输入输出协议、provider 顺序、重试和关闭；输入、输出、候选语义和 Context 由业务 owner 决定。

模型服务按 provider → logical model → use 装配。一个用途可以配置 provider 顺序并在失败时切换。Home 与 Memory 各自拥有可重建的向量索引和缓存，缓存不是持久事实；Embedding 文档输入使用稳定的内容单元身份，按 provider/model/use 隔离。JEV 的 Score 用于逐候选评分和阈值选择，Choice 只用于明确声明单选的业务操作。Stage1、Stage2 使用 LLM；Action 内的 select、rerank 才可按用途绑定 LLM、JEV 或 Embedding。

Search 是一个有限的函数式管道。Stage2 选择已登记的六个高层操作函数、操作顺序、scope、query、where、criterion、Context 选项和 page 参数：

- `query` 在 owner 范围中从无到有发现候选；启用的 lexical 与 Embedding 独立召回并融合，任一路有效候选都不会被另一路裁掉。Workspace 的 literal/regex 是 query 语句语义。
- `backlinks` 从 owner 保存的真实入边发现候选，不能用相似文档伪造反链。
- `directory` 枚举指定空间的真实资源、工具或事实目录，保留资源属性和正文预览。
- `select` 依据 criterion 从候选集合得到稳定子集，可返回空集并保持输入顺序。
- `rerank` 依据 criterion 对完整候选集合重排，必须保留全部成员。
- `filter` 按 owner 声明的属性和标签做确定性资格判断，不调用模型、不隐式改变顺序。

操作函数内部的 implementation、provider、model 和输入预算由用户配置的 model-use binding 透明决定；Search 请求不承载这些内部实现选择。`source.where` 是来源资格条件，`filter` 是当前候选集合上的显式步骤；两者可复用比较器但不能互相改写。`refs` 不进行隐藏 lexical/Embedding 预筛；需要内容相关性时必须显式使用 `select` 或 `rerank`。允许的 context 由配置和当前实现共同计算，不支持 Context 的实现不会向 Stage2 暴露 `current`。

每个候选由稳定 ref、属性、一个或多个 `ContentUnit` 和 `SearchEvidence` 构成。来源读取、select/rerank 输入和最终 SearchPage 都使用真实正文或有界命中片段；模型看到展开后的内容预览，而不是只有链接名。一次管道先形成完整最终候选快照，再按 page 字符预算分页。`result_ref` 指向完整快照，`continuation` 只指向其中的页位置；翻页和 result 派生不会重新调用来源或模型，句柄绑定 Turn/profile 或 SDK generation/day lease。

Inspect 是已知入口的确定性渐进读取：返回有界正文、位置和 direct refs，不调用模型、不递归展开，也不查询 backlinks。Memory 的 `memory.search` 提供 query、directory、refs、backlinks 和组合步骤；`memory.inspect` 只读取已知文档和 direct refs。Home 的 `home.search` 覆盖 actual Home 加 runtime overlay 组成的 effective Home，即使资源尚未通过 Context trap 加载也可发现；Skill 的证据按 top 聚合并保留深层 ref。Context search 读取当前 Turn Trace、Session 原始事实和解释投影，不 seal trace、不提前 completion。MCP search 作用于真实 server/tool directory；Workspace 复用 manifest、正文读取、literal/regex 和 Markdown 反链能力，不建立隐式向量库。

来源 owner 负责身份、范围、内容读取、属性和真实引用边；kernel retrieval 只负责候选组合、六函数管道、模型用途调用、快照和分页。没有全局图或跨 owner 持久复制。实际来源故障、模型协议失败、视图过期和容量不足分别转换为稳定的局部 Search failure；不会静默截断候选或伪造成功覆盖。
