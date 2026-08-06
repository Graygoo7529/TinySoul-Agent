
## 记忆和知识
每天维护会话显式记忆 Memory.md，可与 磁盘 runtime session 目录下文件同步，引入 Memory 空间进行加载（background 段），跨 turn 连续，每日随 session 归档，作为 Memory maintenance 的参考依据；

可用于 user turn 的动作：memorize action：快速变更 Memory.md（下一轮 turn 生效）

各类记忆内容通过 memory links 体现，每个 memory link 对应到 memory 空间的一份 markdown 文档；可以有创建日期、更新日期、置信度、活跃度等属性，可以通过 yaml/front-meta 支持；memory link 的建立和维护通过 memory maintenance，user turn 只使用简单的 memorize action

memory:daily/yyyy-mm-dd
yyyymmdd 仍然作为持久化记忆的 daily 日志；启动时加载昨日 daily 日志并维护今日 Memory.md

memory:entity/entity_name
memory:concept/concept_name
使用 entity 实体（如，人、物、地点或组织）、concept（如，主题、抽象概念、领域或长期兴趣）作为 memory link；entity/concept 维护（新增、合并、修改）交给 memory maintenance；entity/concept 有活跃度记录，也可以通过 front-meta 说明彼此联系（指向其它 entity/concept）

memory:fact/fact_summary
可以由 memory:fact/fact_cite<fact_summary> 构成；可通过 fact_cite 加载完整 fact，fact_summary 是一句摘要的陈述句
新增一种 memory link，原子事实，事实应有一条条的陈述语句组成，有创建日期、更新日期、置信度、活跃度；原子事实至少应包含 daily link（证据来源），也可以包含 entity/concept link；

memory:note/note_title
可以由 memory:note/note_cite<note_title> 构成；可通过 note_title 加载完整 note，note_title 能够基本说明笔记内容
新增一种 memory link，卢曼卡片式笔记，笔记应有完整的笔记主题和笔记内容，符合卢曼卡片式笔记的特点，例如学习一篇论文，至少应包含 entity 或 concept link；尽量不要对相同内容建立两份笔记，应即时更新旧笔记/合并笔记；


可用于 user turn 的动作：action：memory inspect 通过 context 中出现的 memory link 逐步/多跳探索记忆，如何探索交给模型；
也可以通过语义检索（embedding） memory links、可以由 links 进一步派生 links，如查看 entity/concept 的反向链接（可结合相关性和其它排序方法）

可用于 user turn 的动作：action：memory recall 作为指定 memory link 的精确召回，可以精准召回 daily 日志、fact 原子事实、entity 实体、concept 概念、note 笔记

整体看来，在运行期间（user turn），记忆 action 主要进行 inspect 和 recall，以及轻量的 memorize 用于维持临时记忆 Memory.md；而相关其它 memory links 的整理下沉到 memory maintenance，maintenance 应基于当日会话和 Memory.md，以及尽量先检索、先复用的原则去修改和维护已有的原子事实/实体/概念/笔记，必要时新增；而 daily 日志针对目标日进行维护时完整重组、必要时替换；即 原子事实/实体/概念/笔记 保持最新最有效，而 daily 是基于指定日期的会话进行维护的。

User Turn 只修改活动记忆；
情景/日志证据、知识图的修改维护由 Memory Maintenance Turn 进行；

fact、note 的 city 可以抽象一些，语义主要由 <fact_summary>、<note_title> 提供；而 entity、concept 的 city 应该就是实体或者概念的名字，如 graygoo、apple、agent-design；


今日 `Memory.md` 初始为空并加载昨日/近日 daily：Background 默认加载不可逐出的 `memory:current` 和昨日 daily `memory:latest`，这两者都不要被压力逐出；允许 User Turn latest daily 缺失情况下继续，也无需在 context 说明缺失 latest；

Maintenance 知识图维护时，尽量先检索已有内容再新建，持续更新、纠正，但不要直接删除节点（避免旧链接失效，即 cite 创建后不改），删除或合并语义应通过清除节点正文内容，声明节点状态并在指向有效的新节点链接；

Memory Maintenance Turn 输入精确目标日上下文（包括 session turn trace、目标日 Memory.md、目标日前一天 daily），然后对目标日 daily 和知识图进行维护；如果目标日 daily 已经存在，相当于重新维护检查一遍；

当前启动时登记 Maintenance availability 清单并发出提示，如果目标日 daily 已经存在，则说明已经维护过了，所以在无需提醒需要显示手动维护；自动维护应该是通过定时触发而非启动时检查；自动触发和（受到提示后）手动触发的 Maintenance Turn 在触发后处理逻辑是一致的，都是对 daily 和知识图进行维护）；

此外，memory memorize、inspect、recall 以及 daily/entity/concept/fact/note 五类 link 你可在现有语义的基础上进一步设计，使 memory links 更可用、更能够有效检索和召回关键记忆；例如，memorize 时可以让模型尽量产生 memory link；能够合理有效通过 inspect 多步探索和 recall 精确召回的多步配合，在 Markdown 是唯一业务事实的语义上，充分结合正向引用、backlinks、语义检索、grep、lexical catalog 等方式启发和探索到相关的 memory links；

embedding 模型可选用 embedding-3（embedding 可作为基础设施 infra，并通过 config toml 配置）：
https://docs.bigmodel.cn/cn/guide/models/embedding/embedding-3
