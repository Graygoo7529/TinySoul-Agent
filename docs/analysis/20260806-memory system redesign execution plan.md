# Memory 系统重构执行计划

## 状态

- `planned`：整体设计与实施
- `planned`：Stage 1，更新稳定语义、Link 与文档模型
- `planned`：Stage 2，建立活动记忆与 Daily Lifecycle
- `planned`：Stage 3，建立多类型 Memory Store、Recall 与引用校验
- `planned`：Stage 4，建立图索引、Inspect、Backlinks 与语义检索
- `planned`：Stage 5，建立 Memory 多文档事务与恢复
- `planned`：Stage 6，重构 Memory Maintenance Turn
- `planned`：Stage 7，收敛 App、配置、Action Catalog 与旧实现
- `planned`：Stage 8，完成回归、全量验收与设计复核

## 背景

当前 Memory 是按 Business Day 组织的单一日期文档集合：`MemoryLink` 只接受
`memory:YYYY-MM-DD`，User Turn 只提供日期 search/recall，Memory Maintenance
把关闭日 Session facts 与可选同日旧 Memory 合并为一份 Markdown。这个模型已经
建立了正确的 owner、Background provider、Session facts projection、Maintenance
Turn 和原子单文件写入边界，但不能表达以下目标：

1. 当前业务日内跨 Turn 连续、可由 User Turn 快速修改的显式活动记忆；
2. daily、entity、concept、fact、note 五类不同生命周期的长期记忆；
3. 基于显式 Link、反向链接和 embedding 的渐进式记忆探索；
4. Memory Maintenance 对多个相关文档进行检索、复用、纠正、合并和一致提交；
5. 旧 Link 在知识合并、纠正和清除后仍然可解释。

本计划是对当前 Stage 6.2 Memory 语义的正式替换，不在旧日期 Link、旧 search
候选和旧单文件 consolidation 上叠加兼容分支。实现时同步修改根 `AGENT.md`、当前
设计文档、配置、Action Catalog、测试和默认项目资源，使代码与稳定定义保持一致。

## 已确认语义

1. User Turn 只能修改当前活动记忆 `Memory.md`；daily 情景/日志证据以及
   entity、concept、fact、note 知识图只能由 Memory Maintenance Turn 修改。
2. fact/note 使用由 Memory owner 生成的抽象稳定 cite，主要可读语义由
   `fact_summary` 或 `note_title` 提供；entity/concept cite 使用实体或概念的规范化
   名称，例如 `graygoo`、`apple`、`agent-design`。
3. 每个业务日的 `runtime/session/Memory.md` 初始为空。User Context 默认加载
   `memory:current` 与 `memory:latest`，两者都不可被 Context pressure 逐出。
4. `memory:latest` 解析为 Context BusinessDay 之前最近一个实际存在的 daily；它不是
   固定“自然日昨天”。没有任何更早 daily 时直接省略该 Context entry，不注入
   unavailable 占位，也不影响 User Turn 继续运行。
5. Memory Maintenance 维护知识图时必须先检索、后创建；持续更新和纠正现有节点，
   不直接删除已经存在的节点。
6. 合并、替代或清除节点时保留原 Link 和 frontmatter，清空正文，写入非 active
   status，并指向有效替代节点；cite 创建后不再改变。
7. `if_absent` 只控制启动 availability/reminder 和定时 Daily Maintenance：目标 daily
   缺失才登记并实际执行；scheduler 到点 request 可以照常入队，但目标 daily 已存在时
   Engine 返回 skipped/unchanged，不启动 Memory Turn，也不自动重做。
8. 显式 `/maintenance memory <date>` 对精确关闭日总是绑定目标 Archive，同时维护
   daily 与知识图；daily 缺失时 create，已存在时允许在旧 digest CAS 保护下 replace
   或 append，并与知识图放入同一 changeset。该显式目标语义已覆盖旧
   `--rebuild` 的有效用途，因此删除额外的 `--rebuild` 布尔参数。
9. 启动 preflight 只恢复 Daily Lifecycle、Memory transaction 和登记 availability，
   不直接执行模型维护。自动维护继续由 scheduler 提交 typed MaintenanceRequest。
10. User Turn 可以在没有可解析 latest daily、但今日 `Memory.md` 可用的状态下继续。

## 三层记忆模型

### 活动记忆

活动记忆是当前业务日的显式工作状态，物理文件固定为：

```text
runtime/session/Memory.md
```

它服务当前日跨 Turn 连续性，不是长期知识图节点，也不使用持久 MemoryLink。Memory
owner 负责初始化、解析、快照、CAS patch 和校验；Session 只在归档整个活动目录时
搬运该文件，不解释其正文。关闭日归档后，该文件成为 Memory Maintenance 的只读
输入之一。

### Daily 情景证据

`memory:daily/YYYY-MM-DD` 是指定 Business Day 的直接、增量式长期记录。Memory
Maintenance 的 normal/scheduled 路径对每个关闭日最多创建一次；已有 daily 是
`if_absent` 的完成标志，自动任务不得替换、追加或回写。显式精确日期 Maintenance 是
受控例外：它重新检查同日 Archive、活动 Memory、现有 daily 和知识图，允许通过 CAS
replace 或 append 修正/补充该 daily，并保留同一个 canonical Link。

Daily 保存可长期理解的输入、行动、结果、决定、上下文变化和未完成事项，但不保存
raw reasoning、provider payload、Context heap topology、绝对路径或 Maintenance 中间
状态。它是 fact 的最低证据来源，也是 entity/concept/note 更新的重要 provenance。

### 当前知识图

entity、concept、fact、note 表达当前最有效认识。它们可以被 Maintenance 重写、
补充证据、降低或提高置信度、增加关系、合并和替代。知识图文档不是事件日志；历史
变化由 daily 和旧节点状态保留，不在当前节点正文中持续追加变更记录。

## 所有权与依赖

```text
app
  +-> loop.user
  |     +-> MemoryEngine: current background / memorize / inspect / recall
  +-> maintenance
        +-> Archive coordinator: day lifecycle and opaque directory movement
        +-> maintenance.memory: target binding / draft / action workflow
              +-> MemoryEngine: document, graph and transaction owner facade
              +-> SessionEngine: typed archived Turn facts
              +-> WorkspaceEngine: typed archived resource view

memory -X-> maintenance
session -X-> memory internals
context -X-> memory store
```

Memory 仍以 `MemoryEngine` 作为唯一装配门面。`tinysoul.maintenance.memory` 拥有
Maintenance Turn 的 target、source binding、review token、draft 和 action 状态，但
不能自行解析 Link、frontmatter、索引或写物理 Memory 文件。Session、Workspace、
Context 只通过 typed projection/provider 与 Memory 协作。

## AGENT.md 同步清单

当前根规约仍描述已实施的 date-only Memory。Stage 1 必须在任何业务实现前同步以下
稳定定义，不能让新代码长期依赖“计划文档覆盖根规约”的隐式假设：

1. Link 列表从 `memory:YYYY-MM-DD` 改为 daily/entity/concept/fact/note 五类持久 Link，
   并把 current/latest/target 明确为 Context 动态引用而非持久 Link；
2. Memory 定位从“日期文档集合”改为活动记忆、daily 证据和当前知识图三层模型；
3. “普通 User Turn 对 Memory 只读”改为“持久 Memory graph 只读，但可通过 memorize 修改
   当日活动 Memory.md”；inspect/recall 仍只读；
4. Business Day 生命周期 participant 增加活动 Memory，明确它在 deterministic rollover
   中初始化、校验并随 Session directory 归档；
5. 持久 `memory/` 根仍不进入 archive；只有位于 `runtime/session/Memory.md` 的活动日
   artifact 随 Session 进入 archive，两者不能混称“Memory 被归档”；
6. Memory owner 职责改为活动文档、五类持久文档、图索引和 changeset commit；Memory
   Maintenance 仍只负责任务编排，不取得 store 私有所有权；
7. Context 定义明确 current/latest 是每 Turn 重建且不可逐出的 Memory Background，latest
   不存在时省略对应 entry；
8. 一致性条款从 Memory 单文件 atomic replace 扩展为 owner 校验、CAS、journal 和多文档
   幂等前滚，但不改变“每项持久事实只有一个 owner”的总原则。

## Link 与 Cite

### 持久 Link

```text
memory:daily/2026-08-06
memory:entity/apple
memory:concept/agent-design
memory:fact/f-a71c9d2e5f42
memory:note/n-9c04bda1e873
```

新增 `MemoryKind`：`daily`、`entity`、`concept`、`fact`、`note`。新的
`MemoryLink(kind, cite)` 负责严格解析、canonical rendering 和物理路径映射：

```text
memory/daily/yyyy/mm/yyyy-mm-dd.md
memory/entity/<cite>.md
memory/concept/<cite>.md
memory/fact/<cite>.md
memory/note/<cite>.md
```

Daily cite 必须是严格 ISO date。Entity/Concept cite 使用 lowercase ASCII kebab-case，
禁止路径分隔符、`.`、`..`、Windows reserved name、尾随点/空格和大小写碰撞；中文或
其它展示名称保存在 title 中，创建方显式提供稳定的罗马化或领域 cite。发生同名时先
检索复用；确属不同对象时使用有意义限定词，例如 `apple-company`，不自动用易漂移的
顺序号。

Fact/Note cite 由 Memory owner 在 stage create 时生成，分别使用 `f-`、`n-` 与足够长
的随机十六进制主体，并在 projected graph 中检查碰撞。Maintenance 模型不自行编造
opaque cite；stage result 返回 Link，后续 staged 文档和 daily 可以引用它。

`fact_cite<fact_summary>` 与 `note_cite<note_title>` 是展示投影，不是 canonical Link
grammar。结构化结果分别返回 `link + summary`、`link + title`；Markdown 中只解析
`<memory:fact/...>` 或 `<memory:note/...>`，相邻展示文本不参与身份和路径映射。
模型可见的紧凑投影可以渲染为
`memory:fact/f-a71c9d2e5f42<用户偏好简洁的中文工程回答>` 或
`memory:note/n-9c04bda1e873<注意力缩放因子的作用>`，Action 输入仍只接受其中的
canonical Link 部分。

### Context 动态引用

`memory:current`、`memory:latest` 和 Maintenance-only `memory:target` 是
`MemoryBackgroundRef`，不属于 `MemoryLink`，也不被 `memory.recall` 接受：

- `memory:current`：当前 User Turn BusinessDay 的活动 `Memory.md` 快照；
- `memory:latest`：当前 Turn BusinessDay 之前最近存在的 canonical daily，可能不存在；
- `memory:target`：Memory Maintenance 目标日归档的最终 `Memory.md`。

动态引用只在 Context provider 绑定的 BusinessDay/target 内解析，不能写入长期文档，
从而避免历史文档保存随日期变化的别名。`latest` 的实际解析结果必须在 entry
正文中标出 canonical daily Link、day、revision/digest，便于模型知道它加载的真实日期。

### Context MessageStack 装配

Memory context 是 Context owner 的语义投影，不是第二套消息状态或可被业务模块直接
拼接的路径。`ActiveMemoryBackgroundProvider`、`LatestDailyBackgroundProvider` 和
Maintenance 的 `TargetMemoryBackgroundProvider` 返回 `BackgroundEntry`，由已有
`BackgroundContext` 收集，再交给 `MessageStackComposer` 的 `ContextSection.BACKGROUND`。
因此 User Turn 的顺序仍是 `identity -> user_inputs -> session_background -> background`
（其中 memory entries 按 current、latest 顺序）`-> trace -> working -> task_prompt`；
Maintenance 复用同一构成，只替换其绑定的 source projection。current/latest/target
entry 均设置 `evictable=false`，不加入 pressure eviction 候选；latest 无解析结果时
不创建 entry。它们的 link 字符串只是 Context 内部标签，persistent Link parser 和
inspect/recall 均拒绝这些动态引用。

## 活动 Memory.md 契约

框架确定性维护 frontmatter，模型只通过 patch 修改 Markdown body：

```markdown
---
schema_version: 1
kind: active
day: 2026-08-06
revision: 0
updated_at: null
---
```

空 body 是合法初始状态。`ActiveMemoryDocument` 和 `ActiveMemorySnapshot` 至少包含
day、revision、body、完整文件 digest。Background provider 渲染 current ref、day、
revision、digest 和 body；即使 body 为空也提供明确快照。

`memory.memorize` 使用以下确定性协议：

```text
expected_digest: 当前 Background 中的文件 digest
operations:
  - append(text)
  - replace(old_text, new_text)
  - remove(text)
  - clear()
```

replace/remove 要求 old text 在当前 body 中唯一存在；操作按序应用，最终 body 受
`max_active_chars` 约束。Memory owner 在持有活动日 lease 时复验 day 与 digest，递增
revision，并原子完整替换 `Memory.md`。stale digest、目标片段缺失/重复、空操作或超限
形成可由模型修正的局部 Action failure；I/O、非法 frontmatter、日期冲突或 symlink
进入 Memory 模块失败。

Action 不发送 Background patch，所以成功变更只在下一 User Turn preparation 生效；
当前 Turn 只收到新 revision、digest、字符数和 changed/cleared 状态。Session 保存小型
patch request，不重复保存每次完整 `Memory.md`。

外部编辑文件后，下一 Turn 会重新读取磁盘并得到新 digest；非法外部编辑不能静默
降级为空记忆。归档前 Memory DailyLifecycle 再次验证活动文档的日期和完整性。

## 持久文档模型

使用 PyYAML safe structured parser，并在入口转换为 frozen dataclass。LLM Action 参数
是类型化字段和 Markdown body，框架负责稳定 frontmatter rendering；不接受模型提交的
任意 YAML 字符串。所有 parser 拒绝未知字段、重复 Link、非法日期、非法 status、类型
不匹配、空 active body、越界正文和指向不存在 projected node 的关系。

### 公共元数据

```yaml
schema_version: 1
kind: entity | concept | fact | note
cite: stable-cite
status: active | merged | superseded | retracted
title: current display title
created_on: 2026-08-06
updated_on: 2026-08-06
aliases: []
activity:
  last_activated_on: 2026-08-06
  activation_count: 1
relations: []
evidence: []
redirect_to: null
```

`created_on` 创建后保持不变；`updated_on` 只在正文或语义元数据变化时更新。单纯
recall/inspect 不写文档；当日 Session 中对 Link 的引用、recall 和 inspect 由下一次
Maintenance 汇总为 activation，避免只读行为直接产生持久副作用。当前 activity score
根据 last activation、count 和配置衰减读取时计算，不要求每日重写所有节点。

confidence 使用 `low`、`medium`、`high` 三档而不是伪精确小数。Fact 必须有
confidence 和 `provenance=user_statement|tool_observation|agent_inference|mixed`；其它
文档可以省略 confidence。

### DailyMemoryDocument

Daily frontmatter 包含 day、revision、created_on、updated_on、Session projection
revision 和归档活动 Memory digest。正文 H1 由框架渲染为目标日，模型只产生 body。
DailyStore 提供两个明确写入入口：

1. `create_if_absent(day, ...)`：供启动可用性和定时 Daily Maintenance 使用；存在目标时
   返回 existing/no-op，不产生 revision、updated_on 或知识图写入。
2. `write_explicit(day, mode=replace|append, expected_digest, ...)`：只供精确目标
   Maintenance 使用。replace 生成完整新正文，append 保留现有正文并追加规范化段落；
   两者均以旧完整 digest 做 CAS，成功后递增 revision、更新 updated_on，并和图变更
   进入同一 MemoryChangeSet。User Turn 没有该入口，不能直接修改 daily。

normal/scheduled 路径永远拒绝 replace/append；explicit 路径即使 daily 已存在也允许
这两种操作，且 append 必须保持唯一 frontmatter/H1，不得重复追加相同候选。

Daily 可以在正文中引用任意 active 或非 active Memory Link；反向链接由索引派生。
Daily 不要求把所有引用复制到 frontmatter。Daily Link 永远不 redirect。

### EntityMemoryDocument 与 ConceptMemoryDocument

title 是当前实体/概念名称，cite 是创建时确定的规范名称。正文保存当前简洁认识，不
累积事件流水。`relations` 不是任意 Link 数组，而是带谓词的受限知识边：
`related_to`、`broader_than`、`narrower_than` 的目标只能是 entity/concept。daily、
fact、note 不作为这些语义关系的目标；它们通过独立的 `evidence`/`about` 字段形成
provenance 和反向链接。若未来确有“派生/支持/矛盾”这类跨 kind 语义，新增显式谓词
（例如 `derived_from`、`supports`、`contradicts`）并为每个谓词声明允许的目标 kind，
禁止恢复无类型的任意跨 kind relations。诸如“某人就职于某组织”的具体可真假陈述
应建为 fact，不扩张为任意关系 ontology。entity/concept 的 `evidence` 至少包含一个
daily/fact/note Link。

初始 schema 的目标 kind 矩阵固定如下，codec 和 projected graph validator 共同校验：

| 字段/谓词 | 可出现的 source kind | 允许的 target kind | 语义 |
| --- | --- | --- | --- |
| `related_to` | entity/concept | entity/concept | 对称弱语义关联 |
| `broader_than` / `narrower_than` | concept | concept | 概念层级 |
| `evidence` | entity/concept/fact/note | daily/fact/note | 来源或支持材料，不是知识关系 |
| `about` | fact/note | entity/concept | 内容主题归属，反向边由 index 派生 |
| `redirect_to` | 非 active graph node | 按状态规则限定的 fact/note/entity/concept/daily | 身份解析与纠正 |

因此 entity/concept 不维护 `has_fact`、`has_note`、`mentioned_in_daily` 这类易漂移的双向
列表；它们由 `about`、`evidence` 和正文 Link 的 backlinks 派生。跨 kind 新谓词进入
schema 前必须有不可由这些字段表达的真实查询需求。

### FactMemoryDocument

Fact body 必须恰好是一条可独立判断真假的陈述，不包含第二条事实、章节或过程说明。
frontmatter 的 `summary` 是该陈述的规范化单行投影，由 codec 从 body 确定性生成或严格
复验，不能形成第二个不同命题。`evidence` 至少包含一条 daily Link，并可包含其它
fact/note；`about` 可以指向 entity/concept。补充证据、confidence 或不改变命题的措辞
澄清可以 rewrite 同一 fact；命题含义改变时创建新 fact，并把旧 fact 设为 superseded。

### NoteMemoryDocument

Note 使用卢曼卡片语义：一个清晰主题、一份可以脱离原 Session 理解的正文、明确的
连接和来源。frontmatter 的 `title` 提供主要展示语义；`about` 至少包含一个 active
entity/concept，`evidence` 可以包含 daily/fact/note。学习论文时应以自己的理解记录
核心论点、推理或可复用洞察，不复制整篇材料，也不为相同主题重复建卡。

### 非 Active 节点

普通 Maintenance 不提供 hard delete。状态转换规则如下：

- `merged`：同类重复节点合并，正文清空，`redirect_to` 指向保留的同类节点；
- `superseded`：fact/note 的语义被新节点替代，正文清空并指向替代节点；
- `retracted`：原陈述无效，正文清空，保留 evidence，`redirect_to` 必须指向解释该
  撤回或纠正的 active fact/note/daily。

非 active 节点必须拥有有效 `redirect_to`，并保留 cite、title/summary、创建日期、状态、
证据和目标，不保留正文。Recall 返回原 Link、状态和解析目标，并默认继续加载最终
active 节点，同时返回完整 resolution chain。Merged/superseded redirect 必须同类；
retracted 可以指向解释撤回的 fact/note/daily。全部 redirect 必须无环并受最大 hop
限制；Inspect 默认排除非 active 候选，但 backlinks 和 exact recall 仍能看到它们。

## Background 语义

User Context 使用新的 `ActiveMemoryBackgroundProvider` 和
`LatestDailyBackgroundProvider`：

1. `memory:current` 始终是 default、loadable、non-evictable；
2. `memory:latest` 是 default、loadable、non-evictable，按当前 BusinessDay 严格向前
   选择最近实际存在的 daily，而不是简单减一天；
3. latest daily 存在时，entry 包含解析出的 canonical daily Link、day、revision/digest
   和正文；
4. 没有更早 daily 时不创建 latest entry，Context 中忽视该项，不搜索或内联其它日期；
5. 全部其它 Memory Link 不进入 Background catalog，通过 inspect/recall 渐进加载；
6. memorize 不更新本 Turn 已加载的 current entry；成功 patch 在下一 Turn preparation
   重新投影。

Memory Maintenance Context 不读取真实 active `memory:current`。它绑定目标关闭日并默认
加载 non-evictable `memory:target` 与按 target day 计算的 `memory:latest`；Session
Background 仍是固定 projection。Context pressure 只能压缩 Maintenance TurnTrace，
不能逐出 target/latest，也不能访问或清理 active Workspace。

## User Memory Actions

User Memory domain 最终只公开三个 action：

### memory.memorize

只修改活动 `Memory.md`，不创建或改写 daily/entity/concept/fact/note。Action serial
执行并使用 expected digest；同一 ActionBatch 中基于同一旧 digest 生成的后续 memorize
会稳定返回 stale，而不会覆盖先成功的修改。

### memory.inspect

请求严格使用 query mode 或 link mode 二选一：

```text
query mode: query + optional kinds + limit + continuation
link mode: memory_link + optional relations + limit + continuation
```

Query mode 返回有界候选 Link、kind、title/summary、关系原因、相关性和 activity；不
返回完整正文。Link mode 返回节点有界摘要、一跳 outgoing、backlinks 和 semantic
related。Action 本身不接受 depth；多跳由模型根据每次结果继续选择 Link，避免一次
调用无界遍历图。

当前 `memory.search` 公共 action 被删除，其候选生成和 rerank 能力并入 inspect query
mode，不保留 alias。无匹配是成功空结果；非法 query/link/continuation 是局部失败。

### memory.recall

只接受 canonical persistent MemoryLink，返回解析后的 frontmatter、完整受限 Markdown、
digest 和 redirect resolution。`memory:current`、`memory:latest`、`memory:target` 均
不是精确 recall 输入。Daily、entity、concept、fact、note 使用各自字符上限，不提供
任意文件路径或未验证片段。

Inspect/recall 使用 foldable Action trace projection。当前 Turn 可以看到完整结果；
Session canonical record 只保存 query/link、选中引用、状态和有界摘要，通过
`origin_refs` 保存真实 Memory Link，供以后 Maintenance 计算 activity 和关联性。

## 图索引与语义检索

Markdown 文档是唯一持久业务事实。`memory/.tinysoul/index.sqlite3` 是可删除、可重建
的派生索引，不作为存在性、状态、关系或事务完成依据。建议包含：

```text
documents(link, kind, cite, title, summary, status, digest,
          created_on, updated_on, last_activated_on, activation_count)
edges(source_link, target_link, relation, source_digest)
embeddings(link, model, dimensions, source_digest, vector)
metadata(schema_version, document_revision, embedding_revision)
```

Index reconcile 扫描五个固定 kind root，使用 MemoryDocumentCodec 校验全部文档，拒绝
未知文件、symlink、大小写身份冲突和损坏文档。Backlinks 从 structured relations、
evidence/about 和正文中的 canonical angle links 派生，不反写文档。

候选检索顺序为 exact cite/title/alias、lexical units、显式边/backlinks、可选 embedding
近邻，再进行稳定融合和可选 LLM rerank。相关性是主排序，关系距离次之，activity、
recency 和 fact confidence 只能作为有限 tie-break，不能让高频但不相关节点压过语义
匹配。

新增 provider-neutral `EmbeddingRunner` 窄协议，具体供应商适配仍归 LLM 模块；Memory
只接收 text -> typed vector 能力。Embedding 配置默认关闭；启用后按 document digest、
model 和 dimensions 增量生成。Embedding 调用失败不回滚业务文档，索引将该节点标为
pending 并继续使用 lexical/graph 检索；exact recall 永远不依赖 index 或 embedding。

## Memory Maintenance 输入

Memory Maintenance Turn 接受精确 `target_day`，且该日必须小于当前 BusinessDay 并
存在 ArchiveProjection。输入事实固定为：

```text
SessionMemoryFactsProjection(target_day)
+ Archived ActiveMemorySnapshot(target_day)
+ Latest DailyMemoryDocument(day < target_day), optional
+ Existing DailyMemoryDocument(target_day), optional mutable base in explicit mode
+ WorkspaceArchiveView(target_day), optional progressive reads
+ Current Memory graph through inspect/recall
```

这里的 Session Turn trace 指 Session 已提交的 Turn 业务事实、Action request/result、
references、Working 终态和输出，不恢复 Context raw TurnTrace、模型 reasoning 或 provider
消息。Session Summary 必须递归展开为去重、有序的 Turn facts；活动 Memory 即使来自
未正常回答的 Turn，仍通过关闭日最终 `Memory.md` 被维护看到。

Eligibility 从“Session facts 非空”改为“Session facts 非空或归档活动 Memory body 非空”。
Workspace 单独存在不创建 daily。目标日前没有任何 latest daily 是正常输入状态；目标
归档 Memory.md 损坏、Session 图损坏或已有目标 daily 损坏是明确模块失败。explicit
模式把已有目标 daily 的 revision/digest 纳入 source binding；scheduled/if_absent 在任务
选择阶段发现它存在时不建立 Maintenance Turn。

Workspace owner 提供只读、受限的 archive resource inspect/read 门面，使论文笔记等
Maintenance 可以读取真实来源；Memory/Maintenance 不直接拼接 Workspace 私有路径。

## Maintenance Action 与 Draft

Memory Maintenance ActionEngine 保持独立 action view，提供：

```text
maintenance.memory.inspect_sources
maintenance.memory.inspect
maintenance.memory.recall
maintenance.memory.stage_create
maintenance.memory.stage_rewrite
maintenance.memory.stage_redirect
maintenance.memory.compose_daily
maintenance.memory.stage_daily
maintenance.memory.preview
maintenance.memory.commit
maintenance.complete
```

`inspect_sources` 分页读取 Session facts、target Memory、现有 target daily 和 Workspace
resource；`inspect/recall` 委托 MemoryEngine，但把结果绑定为 Maintenance-owned review
token。Token 至少绑定 task id、target day、index revision、query 或 Link、document digest
和 staged draft revision。

创建 entity/concept/fact/note 前必须提供同 kind 或适当 kind 集合的 search token；本地
只强制“先检索”事实，是否确属新节点由 Maintenance 模型根据候选 recall 判断。Rewrite
必须提供目标 recall token 和 expected digest；redirect 必须提供源、目标 recall token，
且源目标满足状态、kind 和无环规则。stale token 返回局部反馈并要求重新 inspect。

`MemoryMaintenanceDraft` 是 Maintenance Turn 内存状态，不持久化。它在 base graph 上
叠加 create/rewrite/redirect 和一个按 mode 标注的 daily candidate；后续
inspect/recall 必须看到 projected graph，从而允许新建 fact/note 引用同一 Turn 刚 stage
的 entity/concept。

`compose_daily` 由现有 hierarchical consolidator 重构而来：scheduled/if_absent 模式只在
目标 daily 缺失时生成 candidate；explicit 模式总是读取已有 daily（若存在）作为 source，
可生成完整 replacement 或规范化 append candidate，不写文件。两者都接收有界
Session/活动 Memory/latest daily source 和 projected graph 的 Link/title/summary hints，
并保持 Session chronology。candidate 存在 controller 中并返回 token、digest 与正文；
`stage_daily(mode=create|replace|append|unchanged)` 要求：create 使用 expected-absent，
replace/append 仅允许 explicit target 并携带 expected old digest；explicit 复核后无需
改动时以 unchanged + expected old digest 证明 daily 已被检查，不制造空 revision。

Missing daily 的 normal/scheduled 或 explicit 任务都必须 stage 一份合法 daily。显式目标
的 existing daily 是可修改的 base source；`preview` 需同时验证 daily create/replace/
append 和 projected graph，确认 append 不重复 frontmatter/H1、replace/append 的 old
digest 未过期。scheduled existing daily 必须在任务选择阶段直接 no-op，不生成 graph 或
daily draft；`commit` 只接受当前 preview revision。
`maintenance.complete` 要求 commit completed/unchanged，不能以 action 调用顺序代替 owner
postcondition。

## Maintenance 推理原则

Maintenance prompt 和 action semantic 必须共同表达：

1. Daily 优先保留目标日发生过什么，不把它改造成当前知识百科；
2. 只有跨 Turn/跨日仍有价值、可复用或需要持续追踪的内容才提升到知识图；
3. 对每个候选主题先 query inspect，再 recall 最相近节点；
4. 相同实体、概念、事实命题或笔记主题优先 rewrite/merge，不新建近义副本；
5. 用户陈述、工具观察和 Agent 推断必须区分 provenance，不把 Agent 输出自动当成事实；
6. 新 fact 至少引用目标或其它确切 daily evidence；
7. 新 note 至少关联 entity/concept，并符合一主题、一正文、可独立理解、显式连接；
8. 纠正事实时保留旧节点并使用 superseded/retracted；显式 daily 修改只能修正或补充
   目标日记录，必须保留事件归属和 provenance，不能把后来获得的新知识伪装成当日事件；
9. entity/concept 正文保持当前有效摘要，具体关系尽量下沉为 fact；
10. 没有长期价值的临时工作细节只保留在 daily，不污染知识图。

## 多文档事务与恢复

当前单文件 atomic replace 不足以提交 daily 和多个互相引用的图节点。新增 Memory-owned
`MemoryChangeSet`、`MemoryTransactionService` 和持久 journal：

```text
memory/.tinysoul/transactions/<transaction-id>/
  manifest.json
  staged/<operation-id>.md
```

Prepare 阶段完成：

1. 固化 target day、mode、source revisions/digests、base index revision；
2. 为每个知识节点 replace 记录 expected old digest，为 create 记录 expected absent；daily
   create 记录 expected absent，explicit replace/append 记录 expected old digest 和
   `daily_write_mode`；normal/scheduled changeset 不得出现后两种 mode；
3. 确定性渲染全部新文件并记录 new digest；
4. 在 projected post-state 校验 Link、状态、redirect、fact evidence、note about 和字符上限；
5. 将 staged files 和 manifest 原子写入同一 Memory filesystem。

Commit 在 Program 单写者和 Memory write lock 内按稳定顺序逐文件 atomic replace。daily
写入始终在同一 changeset 的知识图操作之后执行：缺失目标最后 create，显式目标最后
replace/append。每一步复验目标是 old digest 或 new digest，支持崩溃后幂等
roll-forward；不做跨文件回滚，也不建立第二份业务事实。scheduled existing daily 在
进入 commit 前已成为 unchanged/no-op，不产生任何 daily 或 graph operation。

文档提交后更新/重建派生 index，再标记 transaction complete 并清理 staging。Index 或
embedding 失败不撤销已提交文档；journal 记录 documents committed、index pending，后续
preflight 可重建。只要存在未恢复 transaction，MemoryEngine 拒绝向新 Turn 暴露可能的
partial graph。

Maintenance preflight 在 availability 之前调用 `memory.recover()`。恢复仍失败属于
Maintenance/Memory invariant failure，不能把 partial graph 当成可降级只读状态。测试
覆盖每个 operation 写入前后、daily 写入前后、index 更新前后和 journal 清理前后的中断。

## Daily Lifecycle 与 Archive

新增窄 `MemoryDailyLifecycle` participant，并显式接入 `DailyLifecycleCoordinator`：

1. active day 初始化时，Session 先建立 `runtime/session` 和 manifest；
2. Memory 在该 root 创建当天空 `Memory.md`，day 与 revision 为 0；
3. Workspace 初始化完成后，coordinator 提交 ACTIVE_INITIALIZED；
4. rollover 前 Memory 校验 active day 与 `Memory.md`；
5. Session 的 directory move 将 `Memory.md` 一起移入 `archive/.../session/`；
6. 新 active root 初始化新的空 `Memory.md`，不复制昨日活动正文；
7. `ArchiveProjection` 仍只暴露 owner-neutral root，MemoryEngine 通过固定文件名读取自己
   的归档文档，Maintenance 不拼接该路径。

`ActiveDayLease` 同时核对 Session、Workspace 和 active Memory day。Daily journal 的
SESSION_ARCHIVED step 包含活动 Memory 的物理移动；恢复逻辑显式验证 pending archive
中的 `Memory.md`，不依赖“目录里碰巧有额外文件”的隐式行为。

## Availability、启动与 Scheduler

Maintenance availability 的 `memory_days` 继续是 Maintenance-owned 待办投影，不是
Memory 的第二状态源：

1. 新 archive 完成或恢复后，仅当目标 daily 缺失且 Session facts/活动 Memory 至少一项
   非空时增量登记 target day；
2. 已登记日期跨重启保留；daily 已存在时幂等移除；
3. 启动不扫描全部 archive catalog，不把已有 daily 的日期重新登记；
4. startup/User preflight 只恢复 transaction、rollover 和 availability，不运行 LLM；
5. scheduler 继续提交 `MaintenanceScope.DAILY` 的 typed request；该请求使用
   `if_absent` 选择语义，只处理“当前 BusinessDay 前一日且仍在 availability 中”的目标；
   更早 backlog 保留为启动/availability 提醒，等待显式 target，不被一次 DAILY request
   批量消费；
6. 手动/Endpoint `MaintenanceScope.MEMORY + target_day` 绕过 pending 要求，对存在 archive
   的精确关闭日同时维护 daily 与知识图：daily 缺失时 create，已存在时显式 CAS
   replace/append；
7. 删除 `MaintenanceRequest.rebuild_memory`、CLI `--rebuild`、Endpoint 字段和相关分支；
8. User Background 使用 `memory:latest`；没有更早 daily 时省略该 entry，User Turn
   正常继续。

### Scheduler 实现核对

当前实现已经具备定时自动触发链路，但触发边界必须在重构后保持清晰：

1. `MaintenanceScheduler` 只在 `TinySoulApp.run()` 启动其 `ProgramRequestSource` 时建立
   daemon thread；`run_once()` 不启动 scheduler。
2. 线程到点调用 `MaintenanceSchedule.due()`，把 typed
   `MaintenanceRequest(scope=DAILY, trigger=SCHEDULED, source="scheduler")` 入 Program
   queue；scheduler 自身不执行 LLM 或写 Memory。
3. standard/development 配置默认 `maintenance.schedule.enabled=true`、`daily_time=00:15`；
   disabled 时 builder 不装配 source。
4. schedule cursor 在 start 时初始化为当前日期/前一日，因此启动晚于 daily_time 不追赶
   错过的任务；长时间睡眠最多折叠为一个 request。该行为与“启动只提醒、自动维护由
   定时触发”一致。
5. Program 串行消费队列并调用 `MaintenanceEngine.run()`；Daily request 的
   `if_absent` 选择器只选择当前 BusinessDay 的前一日，且仅当该日仍 pending 才启动
   Memory Turn；否则返回 `previous_day_not_pending`。更早 backlog 原样保留，已有 daily
   不会因为 scheduler 到点而重写 daily 或知识图。显式 target request 不经过 scheduler，
   使用显式 daily write mode。

## 配置

目标配置按 owner 拆分，拒绝未知旧键：

```toml
[memory]
root = "memory"
max_active_chars = 12000

[memory.documents]
daily_max_chars = 32000
entity_max_chars = 16000
concept_max_chars = 16000
fact_max_chars = 4000
note_max_chars = 24000
redirect_max_hops = 8

[memory.inspect]
candidate_limit = 40
default_top_k = 8
max_top_k = 20
summary_max_chars = 480
page_max_chars = 8000

[memory.embedding]
enabled = false
model = ""
dimensions = 0

[memory.daily_composition]
chunk_max_chars = 12000
source_max_chars = 240000
max_calls = 48
validation_retries = 2
```

实际默认数值在实施时结合 Context/LLM budget 测试确认，但字段所有权保持以上结构。
当前 `[memory.search]` 迁为 `[memory.inspect]`；`[memory.consolidation]` 迁为
`[memory.daily_composition]`。配置是开发期严格切换，不保留旧键 alias。

## 目标代码结构

```text
tinysoul/memory/
  __init__.py
  engine.py                 # 唯一业务门面
  config.py
  links.py                  # MemoryKind / MemoryLink / BackgroundRef
  models.py                 # frozen document/activity/relation/change types
  documents.py              # YAML frontmatter codec and renderers
  active.py                 # runtime/session/Memory.md owner
  store.py                  # persistent document store
  references.py             # canonical inline Link extraction
  index.py                  # derived catalog/edges/backlinks
  embeddings.py             # narrow embedding service
  inspect.py
  recall.py
  transaction.py
  daily.py                  # candidate request/result/validation
  daily_composer.py         # hierarchical LLM candidate generation
  background.py
  actions.py
  errors.py / failures.py

tinysoul/maintenance/memory/
  task.py
  context.py
  draft.py
  tokens.py
  actions.py
```

删除旧 `memory/consolidation.py` 的直接单日持久化职责；可复用的 validation、source
fragment/pack 和 LLM reduce 逻辑迁入 daily/daily_composer。`MemoryEngine` 不接受
MaintenanceRequest、scheduler 或 Turn 类型。

## 目标类型与门面方法

核心 frozen 类型：

```text
MemoryKind / MemoryStatus / MemoryConfidence / MemoryProvenance
MemoryLink / MemoryBackgroundRef
MemoryActivity / MemoryRelation / MemoryEvidence
ActiveMemoryDocument / ActiveMemorySnapshot / MemoryPatchOperation
DailyMemoryDocument / EntityMemoryDocument / ConceptMemoryDocument
FactMemoryDocument / NoteMemoryDocument
MemoryInspectRequest / MemoryInspectResult / MemoryRecallResult
MemoryDocumentChange / MemoryChangeSet / MemoryCommitOutcome
MemoryDailySourceProjection / DailyCompositionRequest / DailyCompositionResult
MemoryMaintenanceDraft / MemoryReviewToken
```

`MemoryEngine` 目标门面：

```text
initialize_active_day(day)
active_day()
read_active(day)
patch_active(day, expected_digest, operations)
validate_active_day(day)
read_archived_active(day, session_archive_root)
links(kinds=None, statuses=None)
inspect(request, scope=None)
recall(link)
daily_exists(day)
latest_daily_before(day)
maintenance_eligible(source_projection)
prepare_changeset(draft_projection)
commit(changeset)
recover()
reconcile_index()
```

上层不得取得 MemoryStore、MemoryIndex 或 transaction journal 后自行组合写入。

## 失败与 Runtime 语义

局部 Action failure：invalid/stale memorize patch、inspect query/link/continuation 非法、
recall not-found、Maintenance review token stale、create 未先 search、rewrite digest stale、
projected relation/status 不合法、candidate validation 失败。

Memory 模块失败：active/persistent 文档为空或损坏、frontmatter 不可解释、store 中存在
未知路径/symlink/case collision、redirect cycle、index schema 无法恢复、transaction CAS
冲突、原子写失败或 archive active day 不一致。

Runtime bridge 保持三层语义：User action 的可修正请求返回 ActionResult；User Context
默认 Memory 无法读取时结束 User Turn；Maintenance source/commit/recovery 失败结束当前
Maintenance work，并形成 typed task outcome。Observation 只发布 Link、kind、target day、
count、digest、status、failure kind 和模型调用计数，不包含活动正文、daily、知识正文、
Session facts、prompt 或绝对路径。

## 旧实现与迁移原则

这是开发阶段的严格语义切换：

1. 删除 `memory:YYYY-MM-DD` parser、`.md` Link、旧 date-only search 和公开 search action；
2. 删除旧单文件 consolidation outcome/request 以及 `rewrite_existing` 参数；
3. 删除 `--rebuild` 和 `rebuild_memory` 全链路字段；
4. 不保留旧 Link alias、双读、双写或按路径自动猜测；
5. 仓库测试 fixture 直接生成新格式；
6. 实施前检查实际项目 `memory/` 数据。若存在需要保留的真实旧日期文档，使用独立、
   显式、离线的一次性迁移步骤转为 `memory:daily/...`，迁移能力不进入运行时门面。

## 实施阶段

### Stage 1：稳定契约与文档模型

- 更新根 `AGENT.md` 的 Memory、Link、User/Maintenance 和持久目录定义。
- 重写 `docs/design/memory.md`，同步 Context、Session、Maintenance、App、Action、LLM、
  Runtime 相关设计段落。
- 实现 MemoryKind、MemoryLink、MemoryBackgroundRef、cite 规则和五类 frozen document。
- 实现严格 YAML codec、renderer、inline reference parser 和类型级不变量测试。
- 删除旧日期 Link 测试假设，不引入兼容 parser。

### Stage 2：活动记忆与日生命周期

- 实现 ActiveMemoryStore/Document/Snapshot 和 digest-bound patch。
- 将 MemoryDailyLifecycle 接入 coordinator、lease、rollover journal 和 archive recovery。
- 新增 current/latest/target Background provider，按 User/Maintenance Context 精确装配，
  latest 缺失时省略 entry。
- 增加 `memory.memorize` action，验证下一 Turn 生效、同 Turn stale CAS 和 Session 小型记录。
- 覆盖空初始文件、外部合法/非法编辑、跨 Turn、跨日归档和恢复窗口。

### Stage 3：持久 Store 与 Recall

- 改写 MemoryStore，只扫描五个固定 kind root 与 `.tinysoul` 内部状态。
- 实现每类 read/create/replace、status transition、redirect resolution 和字符上限。
- 扩展 MemoryEngine facade 与 RuntimeMemoryBridge failure mapping。
- 改写 `memory.recall` 为多类型 exact recall，并使用 foldable trace projection。
- 覆盖 case-insensitive filesystem、非法文件、Link 越界、redirect cycle/hop 和旧 Link 拒绝。

### Stage 4：图索引与 Inspect

- 实现 SQLite derived index、document reconcile、edges/backlinks 和 lexical candidate。
- 新增可选 EmbeddingRunner 与 digest/model-bound vector cache。
- 实现 query/link 两种 MemoryInspectService、continuation、稳定融合和 bounded output。
- 删除公开 `memory.search`，更新 domain/action catalog、prompts 和 Session references。
- 覆盖 embedding disabled/failure/model change、stale index rebuild、多跳模型工作流和排序边界。

### Stage 5：事务与恢复

- 实现 MemoryDocumentChange、MemoryChangeSet、projected graph validator。
- 实现 staging manifest、CAS atomic writes、stable operation order 和 roll-forward recovery。
- 将 index 更新建模为可重建派生步骤，不让 embedding 失败回滚业务文档。
- 在 Maintenance/User preflight 前强制恢复未完成 transaction。
- 建立逐窗口 fault-injection matrix，并断言任何 User Turn 都看不到 partial graph。

### Stage 6：Memory Maintenance Turn

- 扩展 ArchivedMemoryMaintenanceContext，绑定 target Memory、latest/target daily、Session
  facts 和 WorkspaceArchiveView。
- 实现 draft/review token 和全部 owner-bound Maintenance actions。
- 将 LLMMemoryConsolidator 重构为无持久副作用的 LLMMemoryDailyComposer。
- 更新 Maintenance prompt，落实 source provenance、先检索、复用、fact/note 约束和状态转换。
- 修改 eligibility，使 Session facts 或活动 Memory 任一非空即可维护。
- 实现 scheduled/if_absent 的首次 daily create，以及显式目标对既有 daily 的 CAS
  replace/append 与知识图联合维护、unchanged、失败重试和 commit postcondition。

### Stage 7：App、配置与旧路径收缩

- 删除 MaintenanceRequest/App intent/Endpoint/CLI 的 rebuild_memory/--rebuild。
- 明确 scheduled `if_absent` 与 explicit target 两种任务选择和 daily write 语义。
- 更新 Memory、LLM task、Action catalog、标准/开发配置和项目模板。
- 删除旧 consolidation/search 文件或迁移其中仍有真实消费者的通用逻辑。
- 更新 availability、startup、scheduler、wheel package data 和 architecture tests。
- 全仓搜索并清除当前设计文档与源代码中的旧 Memory Link/配置/action 身份。

### Stage 8：验收与复核

- 运行 Memory、Context、Session、Maintenance、App、Endpoint、Runtime 定向测试。
- 运行 Fast/Full pytest、typecheck、compileall、wheel 和隔离项目初始化。
- 使用真实 User Turn 验证 memorize 下一轮生效、latest 存在/省略、inspect 多跳和 recall。
- 使用真实 Maintenance Turn 验证先搜索后复用、scheduled daily 只创建一次、显式目标对
  既有 daily 的 replace/append 与知识图联合维护、节点 redirect 和事务恢复。
- 重新加载 `AGENT.md`、本计划和当前设计文档，逐项审计所有权、失败和数据流。
- 全部完成后将本文件改名为 `20260806-done-memory system redesign execution plan.md`，
  更新状态和实际验收结果，不提前填写完成声明。

## 测试矩阵

### Link 与文档

- 五类 Link 正反映射、严格 canonical、Windows 路径与 case collision；
- entity/concept name cite 与 fact/note owner-generated cite；
- YAML unknown/missing/type/duplicate 字段、date/status/confidence/provenance；
- fact 单陈述/daily evidence、note about、关系目标、正文上限；
- merge/supersede/retract、body cleared、redirect chain/cycle/hop。

### 活动记忆与 Background

- 每日初始化空 Memory.md、合法外部同步、invalid UTF-8/frontmatter；
- memorize append/replace/remove/clear、digest stale、原子写失败；
- 当前 Turn Background 不变、下一 Turn 更新；
- current 始终存在且不可逐出；latest 存在时不可逐出、无历史 daily 时省略 entry；
- latest 选择严格早于 Context BusinessDay 的最大日期，并在 entry 中公开 resolved Link；
- Maintenance target 不读取 active current，User 不读取 archived target。

### Inspect、Recall 与 Index

- query/link XOR、kind filter、continuation 和 bounded result；
- outgoing/backlinks/semantic related、一跳结果与模型多跳；
- active 默认、非 active exact、redirect resolution；
- lexical/embedding/rerank 稳定融合及 embedding 降级；
- index 删除/损坏/stale/model change 后可重建且不改变业务文档。

### Maintenance

- Session only、Memory.md only、两者皆空的 eligibility；
- target latest daily missing、existing target daily 作为 explicit mutable base；
- create 无 search token、rewrite/redirect stale token；
- staged node 互相引用、projected inspect/recall、duplicate reuse；
- fact provenance/confidence/evidence 与 note Luhmann contract；
- daily candidate 分块、source chronology、scheduled expected-absent create；
- explicit existing daily unchanged/replace/append、old digest stale、append 去重与 revision
  递增；
- complete before commit、commit failure、retry 与 task outcome。

### Lifecycle、事务与应用

- archive 前/后 Memory.md、active init 各恢复窗口；
- 每个 changeset operation、daily write、index update、journal cleanup 中断；
- startup 只登记 availability、不运行 LLM；
- scheduler enabled + `app.run()` 到点自动入队，disabled/`run_once()` 不启动；
- scheduler 只处理前一日 pending，existing daily 不提示、不写 daily 或知识图，启动后不
  catch-up，更早 backlog 保留；
- explicit target 在 existing daily 下联合维护 daily 与知识图，无 rebuild flag；
- CLI、Endpoint、Program queue、Observation 和 wheel package data。

## 完成判据

1. 根 `AGENT.md` 和当前设计文档只描述三层新 Memory 语义。
2. User ActionEngine 只能通过 memorize 修改活动记忆，不能修改持久 Memory graph。
3. `memory:current` 在每个 User Turn 默认加载；`memory:latest` 解析为严格早于当前日的
   最近 daily，有结果时加载、无结果时省略；两者一旦进入 Context 都不可逐出。
4. 五类持久 Link、文档、status、redirect、证据和关系均由 Memory owner 严格校验。
5. Inspect 支持 query、一跳图探索、backlinks 和可选 embedding；Recall 精确返回任意类型。
6. Memory Maintenance 输入精确绑定目标 Archive、活动 Memory、latest prior daily 和可选
   现有目标 daily。
7. 新建节点在 owner 层强制先 search；rewrite/redirect 使用 token 和 digest 防止陈旧提交。
8. Scheduled `if_absent` 与 explicit target 无歧义：前者只创建缺失 daily，后者可对既有
   daily 做 CAS replace/append 并联合维护知识图；项目中不再存在 rebuild_memory 或
   `--rebuild`。
9. 多文档 commit 在崩溃后可幂等前滚，User Turn 不会观察 partial graph。
10. 已有 Link 不 hard delete；合并、替代和撤回后仍可 exact recall 并解释去向。
11. Markdown 是唯一业务事实，index/embedding 可删除重建且不影响 exact recall。
12. 全量测试、类型检查、wheel、隔离初始化和真实 provider 验证通过，工作区无旧身份残留。
