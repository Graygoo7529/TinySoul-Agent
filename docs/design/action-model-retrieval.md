# Action 模型与检索基础设施

Action catalog 的 `execution.executor` 只表示执行器注册键；它不表示模型类型或进程承载方式。Action runner 统一负责批次、deadline、hook、取消和执行事实，executor 负责解释参数并调用所属 owner。受控外部进程仍由 execution owner 使用 infra 的受控进程设施，模型调用不形成另一套 Action 调度器。

Action 的模型依赖由代码贡献的 `ModelUseDescriptor` 声明，由配置中的 `ModelUseBinding` 选择实现和用途。LLM 使用普通 task profile，JEV 使用结构化决策用途，Embedding 相似度只引用 Home 或 Memory 已绑定的 owner 向量用途。请求输入和输出语义由 Action/owner 构造和解释；模型服务只负责已准备输入到类型化输出的调用、provider 顺序、有限重试和关闭。

模型服务按 provider → logical model → use 装配。Embedding 的一次文档/query 尝试固定 provider；切换 provider 时重新执行完整向量阶段。Home 与 Memory 各自拥有可重建的派生索引和缓存，缓存不成为持久事实。Home 通用检索始终读取 effective overlay，Reflection 的 actual Background 和 baseline/diff 独立读取实际基线。JEV adapter 只接受 noul、choice、score 三类问题，严格校验问题身份、类型、等级、候选和概率；业务层决定阈值、排序和空选择。模型调用 Observation 记录 consumer、实现、provider、model、尝试、耗时、有限 usage 和失败类型，sink 失败不改变业务。

检索公共设施提供三种请求模式：

- `query_discovery` 在 owner 声明的范围内独立执行 lexical/Embedding 候选召回，再以明确的倒数排名融合，可选 rank 或 select。
- `seed_refinement` 在已知 seed 或目录张成的候选空间内执行必需的 LLM/JEV select。显式 scope/filter 只定义资格，不进行隐藏的 lexical 或向量相关性预筛选。
- `backlink_search` 只读取 owner 保存的真实入边。rank/select 可以重排这些入边，但不能把相似文档补成反链；没有 query 且 context 为 none 时按稳定原序返回。

Stage2 只能选择已登记 Action 的有限 mode、scope、semantic、context、limit 和 filters，不能指定 provider、模型或任意 task profile。`context=current` 是操作开始时的一次固定 Context 投影；SDK 查询没有活动 Context，只能使用 `none`。SearchPolicy 同时约束 Action schema 和运行时归一化，不能出现 schema 允许而执行层拒绝的能力分叉。

Inspect 是已知入口的确定性读取：返回有界内容、原始行号、direct refs 和 continuation，不查询 backlinks、不调用模型、不自动递归。Memory 的 `memory.search` 负责 query discovery、seed refinement 和 backlink search；`memory.inspect` 只读取文档内容和 direct refs，backlinks 不再属于 Inspect。Home 的 `home.search` 覆盖 agent/skills 全部可读资源，普通 Skill 的证据按实际所属 top 聚合，其他资源保留 resource 身份；`home.inspect` 读取 top 或 resource。MCP 的 Search 是工具目录上的 seed refinement；Workspace 保留 literal/regex 搜索并增加 Markdown 来源反链，不建立隐式向量库。Context search 搜索固定的 Trace/Session 原始事实和解释投影，不 seal trace、不提前 completion，也不以辅助模型调用解除 Inspect 展示保护。

SearchPage 在排序/选择完成后形成生命周期受限的不可变 view。continuation 只遍历已保留结果，不重复调用模型，也不扩展候选范围；view 绑定 Turn/profile 或 SDK generation/day lease，关闭后 continuation 失效。coverage 分开表达扫描、资格候选、模型评估、结果 limit 舍弃、来源不完整和降级阶段。

同一 profile 可跨多个 Turn 复用：Turn preparation 打开新的查询生命周期，cleanup 关闭旧 view；旧 continuation 不随下一轮重新启用。没有活动 Turn 的 SDK 查询由服务自身的 generation/day lease 控制。

引用解析使用 CommonMark inline/reference-style link，忽略代码和外部网页链接。引用边归 source owner，目标身份和 fragment 规范化归 target owner；没有全局图或跨 owner 存储复制。Memory 的结构化 relations/evidence 与 Markdown 连接均可成为真实出边，Home、Workspace 和 Context 保留各自来源身份。跨空间查询由 Agent 显式安排多个 owner Action。

SearchCapability 是来源 owner 的静态能力声明，与可编辑 SearchPolicy 分开：后者只能选择前者支持的模式、召回来源和语义操作。JEV selector 使用 0–3 四级相关性，默认 select 阈值为 2；rank 保留所有候选。逐候选评分和阈值可配置切换后的实际效果需要针对资料验证，通用模型配置不承诺相关性质量。
