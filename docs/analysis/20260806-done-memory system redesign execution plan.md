# Memory 系统重构执行计划

## 状态

- `done`：整体设计、实现、文档同步与本地验收
- `done`：Stage 1，稳定契约并建立 Memory 文档、检索与存储基础
- `done`：Stage 2，完成活动记忆、Context、Lifecycle 与 User Memory Action
- `done`：Stage 3，完成 Memory Maintenance、统一提交、触发接入与整体验收

## 背景

重构前的 Memory 是按 Business Day 组织的单一日期文档集合：`MemoryLink` 只接受
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
3. 每个业务日的 `runtime/session/Memory.md` 初始为空。User Context 和 Home
   Maintenance Context 默认加载 `memory:current` 与可选 `memory:latest`；Memory
   Maintenance Context 默认加载 `memory:target` 与相对于 target 的可选
   `memory:latest`。进入 Context 的这些内容都不可被 Context pressure 逐出。
4. `memory:latest` 解析为 Context BusinessDay 之前最近一个实际存在的 daily；它不是
   固定“自然日昨天”。没有任何更早 daily 时直接省略该 Context entry，不注入
   unavailable 占位，也不影响 User Turn 继续运行。
5. Memory Maintenance 维护知识图时必须先检索、后创建；持续更新和纠正已有记忆文档，
   不直接删除已经存在的 Link。
6. 合并、替代或撤回记忆文档时保留原 Link 和 frontmatter，写入非 active status、
   迁移说明正文和有效 `redirect_to`；cite 创建后不再改变。除每天新建时允许为空的
   `Memory.md` 外，daily、entity、concept、fact、note 的正文都必须非空。该确认取代
   原始草案中“清空正文”的旧表述。
7. 自动触发和手动显式触发都先验证目标日归档 Session 与 `Memory.md` 可读取；触发后
   进入完全相同的 Memory Maintenance Turn，不分两套 action 或维护模式。
8. daily 是否存在只用于阻止重复自动触发以及从启动 availability/reminder 中移除已完成
   日期。显式 `/maintenance memory <date>` 不受该条件阻止：它总是重新梳理目标日会话、
   `Memory.md`、已有 daily 和相关长期记忆；daily 缺失则创建，存在则检查后按需整体更新，
   无变化则不写。该语义覆盖旧 `--rebuild` 的用途，因此删除该布尔参数。
9. 启动 preflight 只恢复 Daily Lifecycle、Memory transaction 和登记 availability，
   不直接执行模型维护。自动维护继续由 scheduler 提交 typed MaintenanceRequest。
10. User Turn 可以在没有可解析 latest daily、但今日 `Memory.md` 可用的状态下继续。

## 三层记忆模型

### 活动记忆

活动记忆是当前业务日的显式工作状态，物理文件固定为：

```text
runtime/session/Memory.md
```

它服务当前日跨 Turn 连续性，不是长期知识图文档，也不使用持久 MemoryLink。Memory
owner 负责初始化、解析、快照、CAS patch 和校验；Session 只在归档整个活动目录时
搬运该文件，不解释其正文。关闭日归档后，该文件成为 Memory Maintenance 的只读
输入之一。

### Daily 情景证据

`memory:daily/YYYY-MM-DD` 是指定 Business Day 的直接、增量式长期记录。已有 daily 是
该日期已完成自动维护的标志，因此自动触发和启动 availability 不再重复选择它。手动
显式维护仍可重新检查同日归档 Session、`Memory.md`、现有 daily 和相关长期记忆，并在
确有变化时以旧 digest CAS 保护整体更新 daily，继续保留同一个 canonical Link。

Daily 保存可长期理解的输入、行动、结果、决定、上下文变化和未完成事项，但不保存
raw reasoning、provider payload、Context heap topology、绝对路径或 Maintenance 中间
状态。它是 fact 的最低证据来源，也是 entity/concept/note 更新的重要依据。

### 当前知识图

entity、concept、fact、note 表达当前最有效认识。它们可以被 Maintenance 重写、
补充证据、降低或提高置信度、增加关系、合并和替代。这些文档不是事件日志；历史
变化由 daily 与原 Link 的状态和迁移说明保留，不在当前有效文档中持续追加变更记录。

## 所有权与依赖

```text
app
  +-> loop.user
  |     +-> MemoryEngine: current background / memorize / inspect / recall
  +-> maintenance
        +-> Archive coordinator: day lifecycle and opaque directory movement
        +-> maintenance.memory: target binding / draft / action workflow
              +-> MemoryEngine: document, catalog and transaction owner facade
              +-> SessionEngine: typed archived Turn facts
              +-> WorkspaceEngine: typed archived resource view

memory -X-> maintenance
session -X-> memory internals
context -X-> memory store
```

Memory 仍以 `MemoryEngine` 作为唯一装配门面。`tinysoul.maintenance.memory` 拥有
Maintenance Turn 的 target、source binding、inspection ref、draft 和 action 状态，但
不能自行解析 Link、frontmatter、catalog 或写物理 Memory 文件。Session、Workspace、
Context 只通过 typed projection/provider 与 Memory 协作。

## 现有实现核对与改造边界

本方案可以沿用现有整体执行模型，不需要新增第二套 Loop、Program 或 Context：

1. `ContextEngine` 已通过 `BackgroundEntryProvider.catalog/load` 在每 Turn preparation
   重建 Background，并由 `MessageStackComposer` 稳定组合 Session Background 与通用
   Background；新 Memory 只需替换 provider 投影。
2. `ContextEngine._collect_background_catalogs()` 明确拒绝同一 Context 中重复 owner，
   所以 current/latest 或 target/latest 必须由一个聚合 provider 提供，不能拆成多个
   `owner="memory"` provider。
3. `SessionEngine.memory_facts()` 已能从 archive 递归展开 Summary 并交付有序 Turn 业务
   事实，`SessionArchiveView` 已支持目标日 Session Background 与渐进 inspect；它们继续
   是 Memory Maintenance 的 Session 输入，不复制 raw TurnTrace。
4. `SessionStore.archive_to()` 原子搬运整个 Session 根，适合让其中的 `Memory.md` 一起
   归档；Session 仍不解析该文件，Memory owner 在搬运前后负责校验。
5. `ProgramRunner` 和 `MaintenanceEngine` 已串行执行 User/Maintenance work，Maintenance
   Action domain 也已使用 serial policy；多文档提交期间不会与 User Turn 并发读取。
6. `MaintenanceScheduler` 已在 `TinySoulApp.run()` 中按时提交 typed DAILY request，
   不直接执行 LLM；`run_once()` 不启动 scheduler，进程晚启动也不追赶错过的定时点。
7. Home 已有严格 PyYAML frontmatter、owner-bound snapshot 和原子写入模式，可借鉴实现
   方式，但 Memory 仍拥有自己的 schema、codec 和持久边界，不跨模块复用业务类型。

需要替换的旧实现边界也很明确：

- date-only `MemoryLink/MemoryStore/MemorySearchService` 改为五类文档与派生目录；
- 精确昨日且可逐出的 `MemoryBackgroundEntryProvider` 改为按 Context 语义聚合、不可逐出；
- 单文件 `MemoryConsolidationService` 改为无副作用 daily candidate 与统一 changeset；
- `rebuild_memory`、existing-daily skip 和仅 Session facts eligibility 从 request、Engine、
  task、controller、CLI/Endpoint 全链路删除；
- `DailyLifecycleCoordinator`、`ActiveDayLease` 和恢复窗口显式纳入 Session 根内的
  `Memory.md`，但不新增 Memory archive root 或独立 archive step；
- `AppBuilder` 先装配 Session runtime root，再装配依赖该 root 的 MemoryEngine。

## AGENT.md 同步清单

根规约已在 Stage 1 同步以下稳定定义，代码不依赖“计划文档覆盖根规约”的隐式假设：

1. Link 列表从 `memory:YYYY-MM-DD` 改为 daily/entity/concept/fact/note 五类持久 Link，
   并把 current/latest/target 明确为 Context 动态引用而非持久 Link；
2. Memory 定位从“日期文档集合”改为活动记忆、daily 证据和当前知识图三层模型；
3. “普通 User Turn 对 Memory 只读”改为“持久 Memory 文档只读，但可通过 memorize 修改
   当日活动 Memory.md”；inspect/recall 仍只读；
4. Business Day 生命周期 participant 增加活动 Memory，明确它在 deterministic rollover
   中初始化、校验并随 Session directory 归档；
5. 持久 `memory/` 根仍不进入 archive；只有位于 `runtime/session/Memory.md` 的活动日
   artifact 随 Session 进入 archive，两者不能混称“Memory 被归档”；
6. Memory owner 职责改为活动文档、五类持久文档、派生 catalog 和 changeset commit；Memory
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

Daily cite 必须是严格 ISO date。Entity/Concept cite 就是实体或概念的规范名称，使用
lowercase ASCII kebab-case，例如 `graygoo`、`apple`、`agent-design`；禁止路径分隔符、
`.`、`..`、Windows reserved name、尾随点/空格和大小写碰撞。发生同名时先检索复用；
确属不同对象时使用名称本身所需的有意义限定词，例如 `apple-company`，不再增加一套
旧兼容身份或与 cite 并行的身份语义。

Fact/Note cite 由 Memory owner 在 stage create 时生成，分别使用 `f-`、`n-` 与足够长
的随机十六进制主体，并在暂存记忆视图中检查碰撞。Maintenance 模型不自行编造
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
从而避免历史文档保存会随日期变化的动态引用。`latest` entry 只需标出实际解析出的
canonical daily Link、day 和正文；完整性 digest 留在 owner 内部。`current` 额外公开
`expected_digest`，因为它是 `memory.memorize` CAS 的真实模型输入；revision 不因内部
存在就暴露给模型。

### Context MessageStack 装配

Memory context 是 Context owner 的语义投影，不是第二套消息状态或可被业务模块直接
拼接的路径。现有 `ContextEngine` 要求每个 owner 在一个 Context 中只有一个 provider，
并由 provider 返回 `BackgroundCatalog`；因此每个 Context 只装配一个聚合 provider，
而不是为 current/latest/target 分别注册同 owner provider：

- `ActiveMemoryBackgroundEntryProvider` 用于 User Context 与 Home Maintenance Context，
  提供 `memory:current + optional memory:latest`，latest 严格早于当前 BusinessDay；
- `TargetMemoryBackgroundEntryProvider` 用于 Memory Maintenance Context，从
  `ArchivedMemoryMaintenanceContext` 的目标日绑定读取快照，提供
  `memory:target + optional memory:latest`；latest 严格早于 target day，与执行日无关。

Provider 通过 catalog/default entries 接入已有 `BackgroundContext`，再由
`MessageStackComposer` 放入 `ContextSection.BACKGROUND`。User Turn 的顺序仍是
`identity -> user_inputs -> session_background -> background`（Memory entries 按
current、latest 顺序）`-> trace -> working -> task_prompt`；Maintenance 复用相同消息
构成。两种 provider 的 owner 都是 `memory`，但不会出现在同一 Context。current、
latest、target entry 均设置 `evictable=false`；latest 无解析结果时不创建
entry。它们只是 Context 动态引用，persistent Link parser 与 inspect/recall 均拒绝。
`MaintenanceBuilder` 必须显式区分两种装配：Home Context 绑定活动日，Memory Context
绑定 `target_day`；不能继续用同一个日期 provider 隐式推断两种语境。

## 活动 Memory.md 契约

框架确定性维护 frontmatter，模型只通过 patch 修改 Markdown 正文：

```markdown
---
schema_version: 1
kind: active
day: 2026-08-06
revision: 0
updated_at: null
---
```

空正文是 `Memory.md` 的合法初始状态。`ActiveMemoryDocument` 和
`ActiveMemorySnapshot` 至少包含 day、revision、content、完整文件 digest。Background
provider 渲染 current ref、day、expected digest 和正文；即使正文为空也提供明确快照。

`memory.memorize` 使用以下确定性协议：

```text
expected_digest: 当前 Background 中的文件 digest
operations:
  - append(text)
  - replace(old_text, new_text)
  - remove(text)
  - clear()
```

replace/remove 要求 old text 在当前正文中唯一存在；操作按序应用，最终正文受
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
是类型化字段和 Markdown 正文，框架负责稳定 frontmatter rendering；不接受模型提交的
任意 YAML 字符串。所有 parser 拒绝未知字段、重复 Link、非法日期、非法 status、类型
不匹配、daily/entity/concept/fact/note 空正文、越界正文和指向不存在记忆文档的关系；
只有活动 `Memory.md` 可以为空。

### 公共元数据

```yaml
schema_version: 1
kind: entity | concept | fact | note
cite: stable-cite
status: active | merged | superseded | retracted
created_on: 2026-08-06
updated_on: 2026-08-06
activity:
  last_activated_on: 2026-08-06
  activation_count: 1
relations: []
evidence: []
redirect_to: null
```

Entity/concept 的 cite 就是名称；fact 使用 `summary`，note 使用 `title`，二者的
opaque cite 只承担稳定身份。`created_on` 和 `updated_on` 都使用本次维护的目标日：
新建时相同，目标日复查有变化时更新为目标日。单纯 recall/inspect 不写文档；持久
`activation_count` 与 `last_activated_on` 由 Maintenance 依据目标日会话汇总更新，
不为显式重复维护或乱序维护增加额外去重语义。当前 activity score 根据 last activation、
count 和配置衰减读取时计算，不要求每日重写所有文档。

一次 activation 表示某个 entity/concept/fact/note 在目标日的可维护来源中被实际使用：
包括 Session answer/reference、精确 recall、link-mode inspect、活动 `Memory.md` 引用，或
Maintenance 对该文档进行 create/rewrite/redirect。对同一目标日的一次 Maintenance Turn，
同一 Link 最多增加一次 `activation_count`，并把 `last_activated_on` 设为 target day；
query-mode inspect 只返回候选，不把所有候选计为 activation。显式重复或乱序维护仍按
用户确认不额外建立跨任务去重账本。

confidence 使用 `low`、`medium`、`high` 三档而不是伪精确小数。Fact 必须有
confidence；其它文档可以省略 confidence。证据来源只由 `evidence` Link 和正文表达，
不再增加其它来源分类字段。

### DailyMemoryDocument

Daily frontmatter 包含 day、revision、created_on、updated_on、Session projection
revision 和归档活动 Memory digest。正文 H1 由框架渲染为目标日，模型只产生正文。
Daily 没有独立的 append action：每次 Memory Maintenance 都根据目标日 Session、归档
`Memory.md`、相对于 target 的 latest 和已有 target daily 梳理出一份完整候选；已有 daily
只作为本次检查和整体更新的输入。提交时用 expected-absent 或旧完整 digest CAS，候选
无变化则 unchanged，不制造 revision。User Turn 没有该入口，不能直接修改 daily。

Daily 可以在正文中引用任意 active 或非 active Memory Link；反向链接由索引派生。
Daily 不要求把所有引用复制到 frontmatter。Daily Link 永远不 redirect。

### EntityMemoryDocument 与 ConceptMemoryDocument

cite 是当前实体/概念的规范名称。正文保存当前简洁认识，不累积事件流水。初始 schema
只保留两类链接字段：

- `relations` 只允许指向 entity/concept。entity/concept 用它连接其它实体或概念；
  fact/note 用它标明涉及的实体或概念。具体可判断陈述写成 fact，不在 relations 中预设
  `broader_than`、`supports` 等关系 ontology。
- `evidence` 只允许指向 daily/fact/note，表达来源或支持材料，不属于 relations。

因此 relations 不指向 daily/fact/note。daily、fact、note 的发现由 evidence、正文中的
canonical Memory Link 和派生 backlinks 完成，不维护 `has_fact`、`has_note`、
`mentioned_in_daily` 等反向列表，也不增加其它主题字段或未来谓词矩阵。redirect
只服务非 active entity/concept/fact/note，并按下文状态规则校验目标。Active 文档中的
relations 可以保留一个后来被合并或替代的旧 Link，但该 Link 必须能沿 redirect 解析到
active entity/concept；文档下次被维护时优先改写为最终 Link，不要求一次合并级联重写
全部 backlinks。

### FactMemoryDocument

Active Fact 正文必须恰好是一条可独立判断真假的单行陈述，不包含第二条事实、章节或
过程说明；frontmatter 的 `summary` 与规范化后的正文保持一致，直接作为紧凑展示语义，
避免摘要和事实形成两个命题。`evidence` 至少包含一条 daily Link，并可包含其它
fact/note；`relations` 可以指向 entity/concept。补充证据、confidence 或不改变命题的
措辞澄清可以 rewrite 同一 fact；命题含义改变时创建新 fact，并把旧 fact 设为
superseded。Fact 变为非 active 后保留原 summary，正文改为迁移说明。

### NoteMemoryDocument

Note 使用卢曼卡片语义：一个清晰主题、一份可以脱离原 Session 理解的正文、明确的
连接和来源。frontmatter 的 `title` 提供主要展示语义；`relations` 至少包含一个能够
解析到 active entity/concept 的 Link，`evidence` 可以包含 daily/fact/note。学习论文时应以自己的理解记录
核心论点、推理或可复用洞察，不复制整篇材料，也不为相同主题重复建卡。

### 非 Active 记忆文档

普通 Maintenance 不提供 hard delete。状态转换规则如下：

- `merged`：同类重复文档合并，正文改为迁移说明，`redirect_to` 指向保留的同类文档；
- `superseded`：原文档的语义被同类新文档替代，正文改为迁移说明并指向替代文档；
- `retracted`：原内容无效，正文改为撤回说明，保留 evidence，`redirect_to` 必须指向
  能解释该撤回或纠正的 active entity/concept/fact/note。

非 active 文档必须拥有有效 `redirect_to`，并保留 cite、summary/title、创建日期、状态、
证据和迁移说明正文。Recall 始终精确返回请求 Link 对应的文档；若它不是 active，结果
额外返回有界 resolution chain 和最终 active Link，但不静默替换或同时内联最终文档，
模型需要时再对最终 Link 执行 recall。Merged/superseded redirect 必须同类；retracted
可以指向解释撤回的 active entity/concept/fact/note，但不指向 daily。全部 redirect 必须无环并受最大 hop
限制；Inspect 默认排除非 active 候选，但 backlinks 和 exact recall 仍能看到它们。

## Background 语义

User Context 和 Home Maintenance Context 使用聚合的 Memory background provider：

1. `memory:current` 始终是 default、loadable、non-evictable；
2. `memory:latest` 是 default、loadable、non-evictable，按当前 BusinessDay 严格向前
   选择最近实际存在的 daily，而不是简单减一天；
3. latest daily 存在时，entry 包含解析出的 canonical daily Link、day 和正文；
4. 没有更早 daily 时不创建 latest entry，Context 中忽视该项，不搜索或内联其它日期；
5. 全部其它 Memory Link 不进入 Background catalog，通过 inspect/recall 渐进加载；
6. memorize 不更新本 Turn 已加载的 current entry；成功 patch 在下一 Turn preparation
   重新投影。

Memory Maintenance Context 不读取真实 active `memory:current`。它绑定目标关闭日并默认
加载 non-evictable `memory:target` 与严格早于 target day 的可选 `memory:latest`；Session
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

Query mode 返回有界候选 Link、kind、名称或摘要、关系原因、相关性和 activity；不
返回完整正文。Link mode 返回文档有界摘要、一跳 outgoing、backlinks 和 semantic
related。Action 本身不接受 depth；多跳由模型根据每次结果继续选择 Link，避免一次
调用无界遍历图。

当前 `memory.search` 公共 action 被删除，其候选生成和 rerank 能力并入 inspect query
mode，不保留旧兼容身份。无匹配是成功空结果；非法 query/link/continuation 是局部失败。

### memory.recall

只接受 canonical persistent MemoryLink，返回解析后的 frontmatter、完整受限 Markdown、
digest 和 redirect resolution。`memory:current`、`memory:latest`、`memory:target` 均
不是精确 recall 输入。Daily、entity、concept、fact、note 使用各自字符上限，不提供
任意文件路径或未验证片段。

Inspect/recall 使用 foldable Action trace projection。当前 Turn 可以看到完整结果；
Session canonical record 只保存 query/link、选中引用、状态和有界摘要，通过
`origin_refs` 保存真实 Memory Link，供以后 Maintenance 计算 activity 和关联性。Recall
与 link-mode inspect 记录请求 Link；query-mode inspect 只记录 query、kind filter 和结果
数量，不把返回的全部候选写入 origin refs，只有模型后续真正 inspect/recall 的 Link 才
计为使用。

## 派生目录与语义检索

Markdown 文档是唯一持久业务事实。个人项目规模下不需要新增 SQLite 状态库；
`MemoryCatalogSnapshot` 在 `memory.recover()` 后扫描五个固定 kind root，通过
`MemoryDocumentCodec` 严格校验文档，并在内存中建立：

- Link -> kind/cite/display/status/digest/activity 的文档目录；
- relations、evidence、redirect 和正文 canonical Link 的正向引用；
- 由正向引用反推的 backlinks；
- 用于 query-mode inspect 的规范化词法单元。

Store 只允许五个 kind root 和 `.tinysoul` 内部目录，拒绝未知文件、symlink、大小写
身份冲突、缺失引用、非法 redirect 和损坏文档。changeset commit 成功后直接重建内存
snapshot；进程重启同样从 Markdown 重建，因此目录没有 schema migration、恢复 journal
或第二份存在性事实。

候选检索顺序为 exact cite、fact summary/note title、lexical units、显式 relations/
backlinks、可选 embedding 近邻，再进行稳定融合和可选 LLM rerank。相关性是主排序，
关系距离次之，activity、recency 和 fact confidence 只作为有限 tie-break，不能让高频但
不相关文档压过语义匹配。

Embedding 是可选增强，不是检索正确性依赖。通用 typed embedding adapter 位于 Infra，
App 根据独立 `[embedding]` 配置装配并注入 Memory；Memory 只拥有派生索引语义，不解释
API key、HTTP 或 provider payload。
缓存使用可删除的 `memory/.tinysoul/embedding-cache.json`，每项绑定 Link、document
digest、model identity 和 vector dimensions；损坏或不匹配时丢弃并回退 lexical/关系
检索。query inspect 可以为当前查询临时生成向量，但不把查询向量写入磁盘；文档向量
缓存只在显式 refresh 或 Memory Maintenance commit 后更新，失败不回滚 Markdown 提交。
Exact recall 永远不依赖派生目录或 embedding。

## Memory Maintenance 输入

Memory Maintenance Turn 接受精确 `target_day`，且该日必须小于当前 BusinessDay 并
存在可读取的 ArchiveProjection。自动触发和手动显式触发都必须具备目标日 Session 与
归档 `Memory.md`；二者只是进入队列的路径不同，进入 Turn 后行为一致。输入事实固定为：

```text
SessionMemoryFactsProjection(target_day)
+ Archived ActiveMemorySnapshot(target_day)
+ Latest DailyMemoryDocument(day < target_day), optional
+ Existing DailyMemoryDocument(target_day), optional source for review and update
+ WorkspaceArchiveView(target_day), optional progressive reads
+ Current persistent Memory through inspect/recall
```

这里的 Session Turn trace 指 Session 已提交的 Turn 业务事实、Action request/result、
references、Working 终态和输出，不恢复 Context raw TurnTrace、模型 reasoning 或 provider
消息。Session Summary 必须递归展开为去重、有序的 Turn facts；活动 Memory 即使来自
未正常回答的 Turn，仍通过关闭日最终 `Memory.md` 被维护看到。

触发检查保持简单：目标日 ArchiveProjection、Session 投影和归档 `Memory.md` 必须存在
且可解析，并且 Session facts 或 `Memory.md` 正文至少一项非空；两份目标日 source 都要
具备，不能用其中一份缺失来降级维护。目标日前没有 latest daily 是正常输入状态；目标
source 缺失或两者都为空表示 not-ready，自动不登记、手动返回 typed skipped；已经存在
但损坏的 Session、`Memory.md` 或 target daily 是明确模块失败。自动路径随后只额外检查
“目标 daily 不存在”以抑制重复触发；手动显式路径忽略 daily 是否存在，直接进入同一
Turn。daily 的存在判断必须读取并校验文档，不能把空文件或损坏文件当作已完成标志。

`MemoryMaintenanceTask` 在每次实际运行前重新构造一份 frozen source projection，并把
Archived ActiveMemorySnapshot 一同绑定到 `ArchivedMemoryMaintenanceContext`。Context
preparation 因而可以由 target provider 读取同一份快照，不需要 Memory provider 反向依赖
Archive catalog，也不会在 eligibility 与 Turn 之间偷偷切换 target。

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
resource；`inspect/recall` 委托 MemoryEngine，并由 controller 为结果签发 Turn-scoped
`inspection_ref`。该 ref 只绑定 task id、target day、catalog generation、query 或 Link
以及涉及文档 digest，不形成第二份持久 review 状态。

创建 entity/concept/fact/note 前必须提供同 kind 或适当 kind 集合的 query inspection ref；本地
只强制“先检索”事实，是否确属新文档由 Maintenance 模型根据候选 recall 判断。Rewrite
必须提供目标 recall inspection ref 和 expected digest；redirect 必须提供源、目标 recall ref，
且源目标满足状态、kind 和无环规则。stale inspection ref 返回局部反馈并要求重新 inspect。

Inspection ref 不绑定 draft revision，否则同一 serial ActionBatch 中对不同文档的第二个
stage 会无意义地过期。所有 stage action 都在执行时针对当前 draft 重新校验重复 Link、
关系、digest 和 redirect；只有 `preview` 返回的 preview revision 绑定完整 draft，任何后续
stage 都使它失效，`commit` 必须携带最新 preview revision。

`MemoryMaintenanceDraft` 是 Maintenance Turn 内存状态，不持久化。它在现有记忆文档上
叠加 create/rewrite/redirect 和一份 daily candidate；后续 inspect/recall 必须看到这份
本轮暂存结果，从而允许新建 fact/note 引用同一 Turn 刚暂存的 entity/concept。

`compose_daily` 由现有 hierarchical consolidator 重构而来：它总是接收有界 Session、
归档活动 Memory、相对于 target 的 latest daily、已有 target daily（若存在）和当前记忆
文档摘要，生成一份完整 daily candidate，不写文件。已有 daily 只是 source；候选可以
保持不变，也可以整体修正或补充。`stage_daily` 只接受 `create|replace|unchanged`：
create 使用 expected-absent，replace 使用旧完整 digest，unchanged 证明本次已经检查且
无需写入。不存在 daily 时必须 stage 合法非空正文；已有 daily 不要求单独 append 操作。

`preview` 同时验证 daily candidate 与长期记忆文档暂存结果。自动路径不会到达已有
daily 的 Turn；手动路径在已有 daily 下照常走同一套
compose、stage、preview、commit。
`maintenance.complete` 要求 commit completed/unchanged，不能以 action 调用顺序代替 owner
postcondition。

## Maintenance 推理原则

Maintenance prompt 和 action semantic 必须共同表达：

1. Daily 优先保留目标日发生过什么，不把它改造成当前知识百科；
2. 只有跨 Turn/跨日仍有价值、可复用或需要持续追踪的内容才提升到知识图；
3. 对每个候选主题先 query inspect，再 recall 最相近文档；
4. 相同实体、概念、事实命题或笔记主题优先 rewrite/merge，不新建近义副本；
5. 必须根据 Session 与 evidence 区分用户陈述、工具观察和 Agent 推断，不把 Agent 输出
   自动当成事实；
6. 新 fact 至少引用目标或其它确切 daily evidence；
7. 新 note 至少关联 entity/concept，并符合一主题、一正文、可独立理解、显式连接；
8. 纠正事实时保留旧文档并使用 superseded/retracted；显式 daily 修改只能修正或补充
   目标日记录，必须保留事件归属和证据，不能把后来获得的新知识伪装成当日事件；
9. entity/concept 正文保持当前有效摘要，具体关系尽量下沉为 fact；
10. 没有长期价值的临时工作细节只保留在 daily，不污染知识图。

## 多文档事务与恢复

当前单文件 atomic replace 不足以提交 daily 和多个互相引用的记忆文档。新增 Memory-owned
`MemoryChangeSet`、`MemoryTransactionService` 和持久 journal：

```text
memory/.tinysoul/transactions/<transaction-id>/
  manifest.json
  staged/<operation-id>.md
```

Prepare 阶段完成：

1. 固化 target day、source revisions/digests、base catalog generation；
2. 为每个记忆文档 replace 记录 expected old digest，为 create 记录 expected absent；daily
   缺失时记录 expected absent，已有 daily 更新时记录 expected old digest，候选不变时
   记录 unchanged。自动与手动使用同一种 changeset，不增加 daily 写入模式；
3. 确定性渲染全部新文件并记录 new digest；
4. 在暂存结果中校验 Link、状态、redirect、fact evidence、note relations 和字符上限；
5. 将 staged files 和 manifest 原子写入同一 Memory filesystem。

Commit 在 Program 单写者和 Memory write lock 内按稳定顺序逐文件 atomic replace。daily
写入始终在同一 changeset 的长期记忆文档操作之后执行：缺失目标最后 create，已有目标
最后 replace；unchanged 不写入。每一步复验目标是 old digest 或 new digest，支持崩溃后幂等
roll-forward；不做跨文件回滚，也不建立第二份业务事实。

全部 Markdown operation 完成后即可标记 transaction complete 并清理 staging，再从文件
重建内存 catalog snapshot。Catalog 重建不属于持久事务步骤；embedding cache 更新也不
进入 changeset，失败只使 semantic candidate 暂时回退。只要存在未恢复 transaction，
MemoryEngine 拒绝向新 Turn 暴露可能的半提交记忆文档。

Program 使用的 Maintenance preflight 按固定顺序执行：先 `memory.recover()` 并重建
catalog，再恢复/执行 Daily Lifecycle，最后刷新 availability。这样 Context provider、
daily completion marker 与 source readiness 始终看到恢复后的同一持久状态。恢复仍失败属于
Maintenance/Memory invariant failure，不能把半提交状态当成可降级只读状态。测试
覆盖每个 operation 写入前后、daily 写入前后和 journal 清理前后的中断。

## Daily Lifecycle 与 Archive

`MemoryEngine` 通过窄 `ActiveMemoryLifecycle` 接口成为 coordinator 的显式协作者，但不
成为独立 archive participant，也不增加 journal step：

1. 新 active day 初始化时，Session 先建立 `runtime/session` 和 manifest；
2. Memory 在该 root 创建当天空正文的 `Memory.md`，day 与 revision 为 0；同日进程重启
   只校验并保留既有文件，不重新清空；
3. Workspace 初始化完成后，coordinator 提交 ACTIVE_INITIALIZED；
4. rollover 前 Memory 校验 active day 与 `Memory.md`；
5. Session 的 directory move 将 `Memory.md` 一起移入 `archive/.../session/`；
6. 新 active root 初始化新的空 `Memory.md`，不复制昨日活动正文；
7. `ArchiveProjection` 仍只暴露 owner-neutral root，MemoryEngine 通过固定文件名读取自己
   的归档文档，Maintenance 不拼接该路径。

`ActiveDayLease` 同时核对 Session、Workspace 和 active Memory day。Daily journal 的
SESSION_ARCHIVED step 包含活动 Memory 的物理移动；恢复逻辑显式验证 pending archive
中的 `Memory.md`，不依赖“目录里碰巧有额外文件”的隐式行为。

恢复窗口固定为：SESSION_ARCHIVED 前校验 active 文件；Session 目录已经移动但 step 尚未
落盘时校验 pending/session/Memory.md；ACTIVE_INITIALIZED 后校验新 Session root 中的空
文件。新语义实施后的既有 active Session 若缺少 `Memory.md` 是不变量失败，不静默重建
并丢失可能的外部同步内容；开发期旧 runtime 通过清理/迁移步骤处理。

当前 `AppBuilder` 先构建 Memory、后构建 Session，无法把活动文件位置作为明确依赖传给
Memory owner。实施时调整为先构建 Session runtime root，再把该 typed root 交给
MemoryEngine；Memory 只拥有固定子文件 `Memory.md`，Session 仍只负责初始化和整体搬运
目录，不解析其内容。该改动不建立独立的 active Memory root。App 装配同时拒绝持久
`memory/` root 与 Session、Workspace、archive roots 重叠；活动文件位于 Session root 是
唯一被允许的交叉位置。注入预构建 Session/Memory facade 的测试路径也必须验证相同布局。

## Availability、启动与 Scheduler

Maintenance availability 的 `memory_days` 继续是 Maintenance-owned 待办投影，不是
Memory 的第二状态源：

1. 新 archive 完成或恢复后，仅当目标日 Session 与归档 `Memory.md` 均存在且可解析、
   二者至少一项包含可维护内容、且 target daily 缺失时增量登记 target day；
2. 已登记日期跨重启保留；有效 daily 已存在时幂等移除，避免自动重复触发和启动重复提示；
3. 启动不扫描全部 archive catalog，不把已有 daily 的日期重新登记；
4. startup/User preflight 只恢复 transaction、rollover 和 availability，不运行 LLM；
5. scheduler 继续提交 `MaintenanceScope.DAILY` 的 typed request；该请求使用
   `if_absent` 选择语义，只处理“当前 BusinessDay 前一日且仍在 availability 中”的目标；
   更早 backlog 保留为启动/availability 提醒，等待显式 target，不被一次 DAILY request
   批量消费；
6. 手动/Endpoint `MaintenanceScope.MEMORY + target_day` 绕过 pending 要求，只要目标日
   Session 与归档 `Memory.md` 都可读且至少一项有内容，就进入同一 Maintenance Turn；
   daily 缺失时 create，已存在时检查并按需整体 replace；
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
   `if_absent` 选择器只选择当前 BusinessDay 的前一日，且仅当该日仍 pending、Session
   与归档 `Memory.md` 可读时才启动 Memory Turn；否则返回 typed skipped outcome。更早
   backlog 原样保留，已有 daily 不会因为 scheduler 到点而再次触发或启动提示。显式
   target request 不经过该重复触发门槛，但仍要求同样的目标 source readiness，并进入
   相同的 Memory Maintenance Turn。
6. 这里的两条路径按 scope 区分，而不是按 trigger 复制业务：`scope=DAILY` 无论来自
   scheduled 还是手动 `/maintenance daily`，都使用 previous-day + availability 的
   `if_absent` 选择；`scope=MEMORY + target_day` 是显式目标路径。`trigger` 继续只作审计。
7. 组合 DAILY request 保留当前 Home-first、Memory-second 顺序。Home Context 的
   `memory:latest` 表示 Turn preparation 时已经存在的最近 daily，不承诺读取同一 DAILY
   request 稍后才生成的目标 daily；该顺序让 Memory Maintenance 看到 Home Turn 已接受的
   current actual Home。两项 task 仍独立收敛，Home 失败不阻止 Memory 尝试运行。

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

[embedding]
enabled = false
base_url = "https://open.bigmodel.cn/api/paas/v4"
model = "embedding-3"
api_key_env = "GLM_EMBEDDING_API_KEY"
dimensions = 1024
batch_size = 64
timeout_seconds = 30.0
cache_max_chars = 16000000

[memory.daily_composition]
chunk_max_chars = 12000
source_max_chars = 240000
max_calls = 48
validation_retries = 2
```

实际默认数值在实施时结合 Context/LLM budget 测试确认，但字段所有权保持以上结构。
当前 `[memory.search]` 迁为 `[memory.inspect]`；`[memory.consolidation]` 迁为
`[memory.daily_composition]`。Embedding 由 Infra 的顶层 `[embedding]` 配置拥有，默认关闭；
启用时 API key 只从专用的 `GLM_EMBEDDING_API_KEY` 环境变量解析，不复用模型使用的
`GLM_API_KEY`，也不进入 TOML、日志或缓存。`embedding-3` 的维度与
批量上限在配置入口严格校验。活动文件位置来自 Session root 注入，不增加
`memory.active_root` 配置。配置是开发期严格切换，不保留旧键兼容字段。

## 目标代码结构

```text
tinysoul/memory/
  __init__.py
  engine.py                 # 唯一业务门面
  config.py
  links.py                  # MemoryKind / MemoryLink / BackgroundRef
  documents.py              # frozen documents + YAML codec + inline refs
  active.py                 # runtime/session/Memory.md owner
  store.py                  # persistent document store
  catalog.py                # in-memory catalog/backlinks/query + optional vector cache
  transaction.py
  daily.py                  # candidate types/validation/hierarchical composer
  background.py
  actions.py
  errors.py / failures.py

tinysoul/maintenance/memory/
  task.py
  context.py
  actions.py                 # controller, draft, inspection refs and executors
```

删除旧 `memory/consolidation.py` 的直接单日持久化职责；可复用的 validation、source
fragment/pack 和 LLM reduce 逻辑迁入 `daily.py`。先保持这些边界，只有单文件职责实际
膨胀后再拆分，不预先创建一批薄 wrapper。`MemoryEngine` 不接受
MaintenanceRequest、scheduler 或 Turn 类型。

## 目标类型与门面方法

核心 frozen 类型：

```text
MemoryKind / MemoryStatus / MemoryConfidence
MemoryLink / MemoryBackgroundRef
MemoryActivity
ActiveMemoryDocument / ActiveMemorySnapshot / MemoryPatchOperation
DailyMemoryDocument / EntityMemoryDocument / ConceptMemoryDocument
FactMemoryDocument / NoteMemoryDocument
MemoryInspectRequest / MemoryInspectResult / MemoryRecallResult
MemoryDocumentChange / MemoryChangeSet / MemoryCommitOutcome
MemoryMaintenanceSourceProjection / DailyCompositionRequest / DailyCompositionResult
MemoryMaintenanceDraft / MemoryInspectionRef
```

`MemoryEngine` 目标门面：

```text
initialize_active_day(day)
active_day()
read_active(day)
patch_active(day, expected_digest, operations)
validate_active_day(day)
read_archived_active(day, session_archive_root)
validate_archived_active(day, session_archive_root)
links(kinds=None, statuses=None)
inspect(request, scope=None)
recall(link)
read_daily(day)
latest_daily_before(day)
prepare_changeset(draft_projection)
commit(changeset)
recover()
refresh_embeddings(changed_links, scope)
```

`read_daily(day)` 返回可选的已校验 DailyMemoryDocument；不存在与损坏严格区分，调用方
不再用裸 filesystem exists 判断完成状态。`recover()` 前滚 transaction 后重建内存 catalog。
上层不得取得 MemoryStore、MemoryCatalogSnapshot 或 transaction journal 后自行组合写入。

## 失败与 Runtime 语义

局部 Action failure：invalid/stale memorize patch、inspect query/link/continuation 非法、
recall not-found、Maintenance inspection ref stale、create 未先 inspect、rewrite digest stale、
暂存 relation/status 不合法、candidate validation 失败。

Memory 模块失败：活动文档损坏、持久文档为空或损坏、frontmatter 不可解释、store 中存在
未知路径/symlink/case collision、缺失引用、redirect cycle、transaction CAS
冲突、原子写失败或 archive active day 不一致。

目标 archive/Session/`Memory.md` 不存在或两份 source 都为空是 trigger not-ready，手动任务
返回 typed skipped，不伪装成模块损坏；已经存在但无法解析才是 invariant failure。Embedding
adapter/cache 失败只禁用本次语义候选并回退 lexical/relations，不改变 recall 或持久文档。

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
4. 不保留旧 Link 兼容身份、双读、双写或按路径自动猜测；
5. 仓库测试 fixture 直接生成新格式；
6. 实施前检查实际项目 `memory/` 数据。若存在需要保留的真实旧日期文档，使用独立、
   显式、离线的一次性迁移步骤转为 `memory:daily/...`，迁移能力不进入运行时门面。
7. 同时检查旧 active/archive Session roots。旧 active Session 没有 `Memory.md` 时在切换前
   显式创建对应日空文件或清理 runtime；旧 archive 缺失该文件时不进入新 availability，
   如需维护则由一次性迁移补齐。运行时不保留“有文件/无文件”双语义。

## 实施阶段

### Stage 1：契约、文档与检索基础（done）

- 更新根 `AGENT.md`、`docs/design/memory.md` 及相关 Context/Session/Maintenance 设计，
  固化三层记忆、五类持久 Link、动态 current/latest/target 和两条触发路径。
- 实现 `MemoryKind`、`MemoryLink`、`MemoryBackgroundRef`、五类 frozen 文档、严格 YAML
  codec、正文/状态/证据/关系/redirect 校验；除活动 `Memory.md` 外正文不得为空，
  `created_on/updated_on` 使用目标日。
- 改写 MemoryStore 与 MemoryEngine 的持久文档、latest 查询、exact recall 和
  `activation_count`；从 Markdown 构建内存 catalog、正向引用和 backlinks，删除旧
  date-only Link 与旧配置身份。

### Stage 2：活动记忆、Context、Lifecycle 与 User Action（done）

- 实现活动 `runtime/session/Memory.md` 的初始化、快照、digest CAS patch、跨日归档和
  新日空文件初始化，接入现有 lifecycle coordinator；调整 AppBuilder 为先装配 Session、
  再把活动 root 交给 Memory，且不建立第二个独立归档根。
- 为 User Context、Home Maintenance Context 各装配一个聚合 Memory provider，加载
  `current + optional latest`；为 Memory Maintenance 预留 `target + optional latest`
  的 target-bound provider，所有已加载 entry 不可逐出。
- 实现 `memory.memorize`、`memory.inspect`、`memory.recall` 及 trace origin refs，
  验证 memorize 下一轮生效、inspect 多跳和五类 exact recall；为 Maintenance 提供
  Workspace owner 的受限 archive resource inspect/read view。

### Stage 3：Maintenance、事务、应用接入与验收（done）

- 扩展 Memory Maintenance Context，精确绑定 target 日 ArchiveProjection、Session、
  归档 `Memory.md`、target-relative latest、可选已有 daily 和 Workspace archive view。
- 实现先 inspect/recall 后复用的 draft、Turn-scoped inspection ref、实体/概念/事实/笔记维护，以及
  daily 单一完整候选的 compose；已有 daily 只作为输入，按需整体 replace 或 unchanged，
  不引入独立 append 操作。
- 实现 Memory-owned changeset、CAS 原子多文档提交、catalog 重建与 crash roll-forward；
  知识文档的合并/替代/撤回保留原 Link、非空迁移说明和同类有效 redirect，retracted 不
  指向 daily。
- 收敛自动与手动触发：两者都要求目标日 Session 与 `Memory.md` 可读并执行同一
  Maintenance Turn；自动路径额外以 daily 缺失作为去重/availability 条件，手动路径
  不因 daily 已存在而跳过；删除 `--rebuild`/`rebuild_memory`。
- 接入 startup availability、scheduler、Program queue、App/Endpoint/CLI 配置，并核对
  scheduler 仅提交 request、启动不运行 LLM 的现有行为。
- 删除旧 consolidation/search 公开路径及无消费者的兼容字段，更新 catalog、prompt、
  项目模板、wheel package data 和 architecture tests。
- 通过 Infra typed adapter 接入可选 embedding-3 与可删除的文档向量缓存；未启用或调用
  失败时保持 lexical/grep/relations/backlinks 的完整可用版本。
- 运行 Memory、Context、Session、Maintenance、App、Endpoint、Runtime 定向测试，再运行
  Fast/Full pytest、typecheck、compileall、wheel 和隔离项目初始化。
- 用真实 User Turn 验证活动记忆下一轮生效、current/latest 装配和省略；用真实自动/手动
  Maintenance Turn 验证 source readiness、daily 去重、已有 daily 复查、知识文档更新、
  redirect 与事务恢复。
- 重新加载 `AGENT.md`、本计划和当前设计文档，审计所有权、失败归属、Context message
  stack 和数据流；全部完成后再将本文件改名为
  `20260806-done-memory system redesign execution plan.md`。

## 测试矩阵

### Link 与文档

- 五类 Link 正反映射、严格 canonical、Windows 路径与 case collision；
- entity/concept name cite 与 fact/note owner-generated cite；
- YAML unknown/missing/type/duplicate 字段、date/status/confidence；
- fact 单陈述/daily evidence、note relations、关系目标、正文上限；
- merge/supersede/retract、非空迁移说明、redirect chain/cycle/hop。

### 活动记忆与 Background

- 每日初始化空 Memory.md、合法外部同步、invalid UTF-8/frontmatter；
- memorize append/replace/remove/clear、digest stale、原子写失败；
- 当前 Turn Background 不变、下一 Turn 更新；
- current 始终存在且不可逐出；latest 存在时不可逐出、无历史 daily 时省略 entry；
- latest 选择严格早于 Context BusinessDay 的最大日期，并在 entry 中公开 resolved Link；
- Maintenance target 不读取 active current，User 不读取 archived target。

### Inspect、Recall 与 Catalog

- query/link XOR、kind filter、continuation 和 bounded result；
- outgoing/backlinks/semantic related、一跳结果与模型多跳；
- active 默认、非 active exact，以及非 active recall 返回 resolution chain 但不自动内联
  最终文档；
- Markdown 启动扫描、正向引用/backlinks/lexical catalog 重建、缺失引用与 redirect cycle；
- query inspect 候选本身不计 activation，recall/link inspect/实际维护才计入；同一 Turn
  同一 Link 最多增加一次，重复或乱序显式维护不引入跨任务去重账本；
- 可选 embedding/rerank 稳定融合及降级；缓存删除、损坏、digest/model 不匹配时可重建，
  query inspect 的临时向量不落盘，文档向量只由 refresh/commit 更新，均不改变业务 Markdown。

### Maintenance

- 目标日 Session 与归档 Memory.md 都必须可读、至少一项有内容；任一 source 缺失或两者
  都为空时 typed skipped，已有但损坏的 source 或 daily 是 invariant failure；
- target-relative latest 缺失、existing target daily 作为本次复查输入；
- create 无匹配 query inspection ref、rewrite/redirect 的 recall ref 或 digest stale；
- 暂存记忆文档互相引用、暂存 inspect/recall、duplicate reuse；
- fact confidence/evidence 与 note Luhmann contract；
- daily 完整 candidate 分块、source chronology、自动 expected-absent create，不存在独立
  append 操作；
- 手动 existing daily unchanged/replace、old digest stale 与 revision 递增；
- inspection ref 不因无关 stage 失效、preview revision 在后续 stage 后失效；
- complete before commit、commit failure、retry 与 task outcome。

### Lifecycle、事务与应用

- Session root 建立后初始化空 Memory.md、同日重启保留内容、archive 前校验、Session move
  后 pending archive 校验、新 active init 各恢复窗口；
- AppBuilder 的 Session -> Memory 装配顺序、root overlap 和注入 facade 布局校验；
- 每个 changeset operation、daily 最后写入、transaction complete/cleanup、catalog 重建
  前后的中断；
- startup 只登记 availability、不运行 LLM；
- scheduler enabled + `app.run()` 到点自动入队，disabled/`run_once()` 不启动；
- scheduler 只处理前一日 pending，existing daily 不提示、不启动重复 Turn，启动后不
  catch-up，更早 backlog 保留；
- explicit target 在 existing daily 下仍联合维护 daily 与知识图，无 rebuild flag；
- `scope=DAILY`（定时或手动 daily）使用 previous-day + availability，`scope=MEMORY + day`
  是显式目标路径，trigger 只用于审计；
- 组合 DAILY 保持 Home-first、Memory-second；Home 的 latest 只表示其 Context 构造时已存在
  的 daily，Home 失败不阻止 Memory task；
- CLI、Endpoint、Program queue、Observation 和 wheel package data。

## 完成判据

1. 根 `AGENT.md` 和当前设计文档只描述三层新 Memory 语义。
2. User ActionEngine 只能通过 memorize 修改活动记忆，不能修改持久 Memory 文档。
3. User/Home Maintenance Context 默认加载 `current + optional latest`；Memory Maintenance
   Context 默认加载 `target + optional latest`，后者严格早于 target；已加载内容不可逐出。
4. 五类持久 Link、文档、status、redirect、证据和关系均由 Memory owner 严格校验。
5. Inspect 支持 query、一跳图探索、backlinks 和可选 embedding；Recall 精确返回任意类型。
6. Memory Maintenance 输入精确绑定目标 Archive、Session、归档 `Memory.md`、target-relative
   latest 和可选现有目标 daily。
7. Maintenance controller 对新建文档强制先 inspect；rewrite/redirect 使用 Turn-scoped
   inspection ref 和 owner digest 防止陈旧提交，preview revision 绑定最终 draft。
8. 自动与手动触发进入同一 Maintenance Turn；daily 只作为自动重复触发和启动提醒的
   `if_absent` 标志，手动可在已有 daily 下复查并整体 replace；项目中不再存在
   `rebuild_memory` 或 `--rebuild`。
9. 多文档 commit 在崩溃后可幂等前滚，User Turn 不会观察半提交记忆文档。
10. 已有 Link 不 hard delete；合并、替代和撤回后仍可 exact recall，正文保留迁移说明并
    解释 redirect 去向，retracted 不指向 daily。
11. Markdown 是唯一业务事实，内存 catalog 和可选 embedding cache 均可从 Markdown
    删除重建且不影响 exact recall；User inspect 不写持久派生数据。
12. 全量测试、类型检查、wheel 和隔离初始化通过；provider adapter 通过伪客户端契约测试，
    真实 provider 调用继续作为显式凭据和环境开关控制的 external 验证，工作区无旧身份残留。

## 验证结果

- Memory/Maintenance/Infra/App/Endpoint 聚焦回归：71 passed；最终边界加固聚焦回归：
  13 passed。
- `scripts/test.ps1 -Suite Full`：859 passed、2 skipped、21 deselected；包含 wheel 与隔离
  项目初始化验收。skip/deselect 均属于显式 external 或环境控制用例。
- `scripts/typecheck.ps1`：通过。
- embedding provider 使用伪客户端验证请求顺序、响应重排、配置校验和失败降级；未把真实
  API key 写入源码、TOML、测试、文档或派生缓存，也未在默认门禁中发起真实计费请求。
