# Memory 设计


## 内部组织

Engine 组合 documents 的类型/Markdown codec、storage 的活动与持久存储、retrieval 的派生 catalog 与文档关系，向量索引复用 infra/model_services。Service 不穿透 store，检索不回调 Engine 私有方法。普通与持久写 actions 分别消费被授予的服务；拆分没有增加第二份 Markdown、活动记忆或提交日志。
## 所有权与事实

`plugins/memory` 是活动 Memory.md、五类持久 Markdown、Link、codec、检索 catalog、backlinks 与 embedding cache 的唯一 owner。`plugins/reflection/memory` 绑定目标日来源并运行维护 Turn，不直接操作 Memory 私有路径。普通动作与持久写分别在 Memory actions 内部封装，持久写会话只持有本次被授予的目标日。

User Turn 通过 memory.memorize 修改当日 Session root 中的活动 Memory.md，通过 memory.search 发现候选、memory.inspect 读取已知持久知识。Inspect 只返回内容和 direct refs；反链通过 memory.search 的 backlink_search 模式查询。只有 Memory Reflection profile 注册持久写 Action。Home 负责身份与技能，Session 负责已完成 User Turn，Memory 不复制二者的历史日志。

Markdown 是业务事实；catalog、lexical 单元、正向引用、backlinks 与 embedding cache 可删除并重建。schema v2 使用严格 YAML frontmatter，拒绝未知字段和旧文档 schema；部署数据转换不隐含在启动中。

## 活动记忆与五类文档

新 CalendarDay 由 owner 初始化正文为空的 Memory.md，同日重启保留。memorize 在 owner 锁内执行 append/replace/remove/clear 并原子替换，不要求模型传 CAS digest。成功后发刷新 Signal，在下一 Context 边界更新当前 Memory 段。活动记忆随 Session 归档，不是持久 memory: Link。

daily 保存目标日的情景证据；entity/concept 保存稳定实体与概念，fact 保存有来源的原子陈述，note 保存完整发展的知识主题。持久文档具有非空正文，已有 Link 不 hard delete。非 active 文档保留迁移说明与有效非 daily redirect；merged/superseded 指向同类目标。

relations 只表达 entity/concept 关联，evidence 指向 daily/fact/note。fact 必须具有 daily evidence 和 confidence；active fact 正文与陈述一致，active note 至少关联一个 entity/concept。daily 的日期元数据属于目标日，不改成执行日。没有 revision、activation_count、session_revision 或 active_memory_digest 持久字段。

## Link 与 Context

canonical Link 分别是 memory:daily/YYYY-MM-DD、memory:entity/name、memory:concept/name、memory:fact/cite、memory:note/cite。owner 解析并映射到 Markdown；动态 ref、扩展名、路径穿越和非规范身份不作为持久 Link。

memory:current 指向活动 Memory，memory:target 指向准备时绑定的目标日活动 Memory 快照（当前日或归档来源），memory:latest 指向严格早于来源日的最近 daily。latest 缺失时静默省略。User/Home Reflection 使用 current/latest，Memory Reflection 使用 target/latest；这些默认内容受保护，不可因压力逐出。仅有历史 daily 而无归档时，目标活动 Memory 明确为空，daily 仍通过 memory.inspect 渐进读取。

Memory provider 每 Turn 打开 Heap 段，维护本轮加载视图、目录与渐进检查；Context 只按 descriptor、ref 路由和通用能力调用。加载视图与持久事实分开，catalog 与正文更新由 owner 负责，TaskPrompt 中局部资源不自动进入通用背景。

## 检索与召回

memory.search 提供 query discovery、seed refinement 和 backlink search。lexical 与 Embedding 独立召回后融合，seed 的相关性只由必需的 LLM/JEV selector 判断；backlink 只返回真实入边。memory.inspect 只检查已知文档内容和 direct refs，不查询 backlinks 或相似文档。continuation 绑定有限 Search view 与请求身份，结果受条数、证据与整页字符预算约束。

memory.inspect 接受精确持久 Link，返回有界 Markdown 内容、direct refs、类型 metadata 与 redirect chain；不会自动内联目标正文。模型根据搜索结果渐进读取，Trace 保留有限投影和来源 Link，检索本身不改变 Background 或知识文档。

Embedding 使用 generation 共享的 `infra.model_services` provider-neutral 服务。Memory owner 保存自己的可重建向量索引；一次文档/query 阶段固定 provider，切换时完整重算，缓存身份包含 provider、模型、维度和证据抽取规则。损坏缓存重建；可恢复 provider 失败可回到 lexical 候选，认证、契约和取消保持原语义。Markdown 写入不调用网络，凭据不进入缓存。

## Reflection 与单文档提交

Memory Reflection 的执行日是 Agent 当前日，source/target 独立绑定明确日期。当前日使用已完成 Session 固定视图和活动 Memory 快照；历史日读取已有归档，既有 daily 也可独立成为整理来源。全部来源缺失或为空为 skipped，损坏为模块失败。历史 Workspace 由只读段提供，当前 Workspace 仍为工作台。

模型先 search/inspect 已有知识，再选择 memory.write_daily 或 memory.write。write_daily 写目标日完整 daily；write 写一份非 daily Markdown。MemoryEngine 在 owner 锁内构造候选 catalog，校验文档、全部引用和 redirect，然后原子替换目标文件并安装新 catalog。

每次 Action 都是独立已收敛提交。引用与迁移目标须先写入，后续无效写入不会回滚此前成功文档。没有 draft、inspection receipt、preview、changeset、多文档 journal 或专用 complete 状态机。检索 digest 是读取摘要，不是持久写 CAS。core.answer 在共享 Reflection 完成管线中保存总结。

自动与手动请求均可更新已有 daily；模型读取后可重新组织既有内容并补充新证据。没有严格冻结或封账状态，触发去重不由 daily 存在决定。日切和归档由 Agent/Archive 协调，不依赖维护模型成功。历史资料只作为来源，持久 memory/ 与 Home 不随日切归档。

## 失败边界

模型参数、Markdown schema、引用或 redirect 使当前写入无效时返回简短局部 Action failure，供模型修正。损坏既有文档、目录不变量、I/O 和配置失败在 Memory owner 边界归类，由 runtime_bridge 转为 Runtime 可理解的原因；不把原始异常正文传给模型。

短本地读取、提交与缓存写通过 JoinedOperations 接入异步执行，已开始写入完成并记录真实结果后才传播取消。可选 embedding 失败只影响派生检索，不改变已提交 Markdown 或 确定性 Inspect。

## 服务与情景权限

MemoryReadService 提供活动背景与持久 Search/Inspect；MemoryService 增加当前活动记忆 patch，供 User 与 Home Reflection 使用。Memory Reflection 只取得只读 Memory 服务和独立 MemoryKnowledgeService，后者才提供目标文档提交。Action 与背景段使用实际注入的 async 门面；不注册完整 MemoryEngine。SDK 的 MemoryService 绑定世代和业务日，旧对象不自动转向新日 Memory.md。
