# Memory 设计

## 状态与定位

本轮 Memory 系统已实施。`tinysoul.memory` 是活动记忆、五类持久 Memory Markdown、检索目录、引用关系、派生向量缓存和多文档提交的唯一 owner；`tinysoul.maintenance.memory` 只负责把一个关闭 Business Day 绑定到 Memory Maintenance Turn，并通过 Memory 门面维护这些事实。

Memory 与 Home、Session、Context 的边界如下：

- Home 保存当前有效的身份规约、用户偏好和技能；
- Session 保存同一 Business Day 已完成 User Turn，并在自己的 root 中承载当日 `Memory.md`；
- Context 只装配当前 Turn 的 `memory:current|latest|target` 投影和 ActionResult；
- 持久 `memory/` 保存 daily、entity、concept、fact、note Markdown；
- User Turn 只能修改活动 `Memory.md`，持久 Memory 只能由 Memory Maintenance Turn 修改。

Markdown 是唯一业务事实。进程内 catalog、正向引用、backlinks、lexical 单元和 `.tinysoul/embedding-cache.json` 都可以删除并从 Markdown 重建，不具有独立业务语义。

## 三层记忆

### 活动记忆

活动记忆固定为 Session root 下的 `Memory.md`。新 Business Day 在 Session root 建立后初始化 schema v1 frontmatter，正文为空；同日重启保留现有文件。User Turn 的 `core.memory.memorize` 使用当前 Background 暴露的 digest 做 CAS patch，支持 append、replace、remove、clear。变更不改写本轮已经构造的 Background，从下一 User Turn 起生效。

活动 `Memory.md` 随 Session 一起归档，是目标日 Maintenance 的直接输入；它不复制到持久 `memory/`，也不是持久 Memory Link。

### Daily 情景证据

`memory:daily/YYYY-MM-DD` 是指定日期 Session 与活动记忆的完整提炼。daily 只描述该日发生的事件、决策、行动、结果、语境变化和未完事项，不作为当前百科。显式重新维护同一目标日时，已有 daily 是复查输入；Maintenance 根据目标日资料决定保持不变或完整替换，不存在独立 append 操作。

### 持久知识

entity、concept、fact、note 保持当前最有效表达。Maintenance 先检索并复用已有内容，再做更新、纠正或必要的新建。既有 Link 一旦创建就不更名、不 hard delete；合并、替代或撤回通过非空迁移说明、非 active status 和有效 redirect 表达，使旧引用继续可精确召回。

## Link 与磁盘映射

五类 canonical Link 与路径为：

```text
memory:daily/2026-08-05       -> memory/daily/2026/08/2026-08-05.md
memory:entity/graygoo         -> memory/entity/graygoo.md
memory:concept/agent-design   -> memory/concept/agent-design.md
memory:fact/f-a71c9d2e5f42   -> memory/fact/f-a71c9d2e5f42.md
memory:note/n-a71c9d2e5f42   -> memory/note/n-a71c9d2e5f42.md
```

entity/concept cite 就是实体或概念的规范小写连字符名称，最长 120 字符。fact/note cite 是 Memory owner 生成的不透明稳定身份；模型可见语义分别来自 `summary` 和 `title`，不从 cite 猜测。旧日期 Link、`.md` Link、大小写变体、反斜杠、路径穿越和动态 Context ref 都不能按持久 Link 解析。

以下身份只在所属 Context 中动态解析：

- `memory:current`：活动 Session 的 `Memory.md`；
- `memory:latest`：严格早于 Context Business Day 的最近一份 daily；
- `memory:target`：Memory Maintenance 绑定的归档目标日 `Memory.md`。

动态 ref 不写入持久文档，也不能传给 exact recall。

## 文档契约

所有持久文档使用严格 YAML frontmatter 和非空 Markdown 正文；未知、缺失、重复或类型错误的字段均失败。daily 的框架 H1 是日期，正文不得再含 ATX 或 Setext H1。

daily 元数据包含：schema version、kind、day、revision、`created_on`、`updated_on`、Session revision 和活动 Memory digest。`created_on`、`updated_on` 始终等于目标日；显式复查替换时 revision 增加，但日期语义不改成执行日。

entity/concept/fact/note 共同包含：cite、status、`created_on`、`updated_on`、activity、relations、evidence、redirect 和可选 confidence。正文始终非空，包括已经迁移的旧文档。

- `status`: `active | merged | superseded | retracted`；
- `activity`: `last_activated_on` 与持久 `activation_count`；
- `relations`: 只允许指向 entity/concept，用于稳定实体和概念关系；
- `evidence`: 只允许指向 daily/fact/note，用于情景来源、事实支持和笔记依据；
- `redirect_to`: active 时为空；非 active 时必须存在且不能指向 daily；merged/superseded 必须指向同类文档；
- fact: `summary` 是最长 480 字符的一条陈述，active 正文与该原子陈述一致，必须有 confidence 和至少一条 daily evidence；
- note: `title` 最长 240 字符，正文完整发展一个卢曼卡片式主题，active 时至少关联一个 entity 或 concept。

这种 relations/evidence 分工避免把所有引用混成一个字段：entity/concept 负责“与什么有关”，daily/fact/note 负责“依据是什么”。正文中的 canonical Memory Link 也进入正向引用和 backlinks，但必须指向实际存在的文档。

## Context 装配

User Turn 和 Home Maintenance 使用同一活动 provider：

```text
memory:current + optional memory:latest
```

Memory Maintenance 使用 target-bound provider：

```text
memory:target + optional memory:latest
```

所有成功装配的 Memory 默认条目都不可被 Context pressure 逐出。latest 缺失是正常状态：不创建占位、不在 Context 解释缺失，也不阻止 Turn。provider 每 Turn 重新解析 latest；latest 永远严格早于 current/target 的 Business Day。

`memory:current` 额外公开 memorize 所需 digest。`memory:latest` 公开 resolved daily Link。`memory:target` 来自归档 Session root，不能误读当前活动 Session。

## User Action

### `core.memory.memorize`

只 patch `memory:current`。模型应保留 Context 中已经确认且对后续有用的 canonical Memory Link；不知道 Link 时先 inspect，不能为持久知识编造 Link。memorize 不创建或更新 daily/entity/concept/fact/note。

### `core.memory.inspect`

inspect 是有界发现和一跳探索，不返回完整 Markdown：

- query 模式综合 exact identity、lexical term、正文 grep、中文 bigram 和可选 embedding 相似度；
- link 模式返回该 Link 的正向引用、backlinks，以及优先使用 semantic related、无 embedding 时回退 lexical related 的有界候选，另返回各类关系计数；
- kinds 可限制五类候选，continuation 绑定当前 catalog generation 与完整请求身份；
- 只返回 active query candidate；已知非 active Link 仍可用 link 模式检查；
- 结果同时受 top-k、candidate count、单摘要和整页字符预算约束；Maintenance 追加
  `inspection_ref` 时由 Memory owner 预留对应 page overhead，完整 ActionResult 仍不超限。

模型自行决定多跳路径：query 找候选，inspect 候选 Link 查看引用/backlinks，再 inspect 下一 Link；需要完整证据时切换 recall。inspect 结果以 foldable Trace 投影进入当前 Turn，不改变 Background。

### `core.memory.recall`

recall 只接受一个精确持久 Link，返回 owner 校验后的完整 Markdown、kind、cite、digest、metadata 和 redirect resolution chain。它不自动内联 redirect 终点正文，旧 Link 与新 Link 的内容保持可区分；模型可根据 chain 再 recall 目标。

## 派生检索与 Embedding

Memory 启动和提交后从所有 Markdown 重建进程内 catalog。catalog 验证缺失引用、redirect cycle/hop、所有 active 知识文档的 relation 最终目标，并生成正向引用和 backlinks。Lexical/grep 检索始终可用，不依赖外部模型。Maintenance 可以让 Memory owner 在不改变全局 catalog 的情况下，从当前 Markdown 与暂存文档集合构造临时 snapshot，供同一 Turn 的 inspect/recall 使用。

Embedding 是 `tinysoul.infra` 的 provider-neutral 基础设施，通过 `[infra.embedding]` 配置。当前项目模板默认关闭，启用示例：

```toml
[infra.embedding]
enabled = true
base_url = "https://open.bigmodel.cn/api/paas/v4"
model = "embedding-3"
api_key_env = "GLM_EMBEDDING_API_KEY"
dimensions = 1024
batch_size = 64
timeout_seconds = 30.0

[memory.semantic_search]
embedding_cache_max_chars = 16000000
```

密钥只从专用的 `GLM_EMBEDDING_API_KEY` 环境变量读取，不能复用 `GLM_API_KEY`，也不能写入 TOML 或缓存。Maintenance commit 后为 active 文档批量刷新派生向量；User inspect 只对 query 临时请求向量，不写业务 Markdown或派生缓存。缓存按 provider/model/dimensions identity 和文档 digest 复用；缺失、损坏、不匹配、请求失败或维度异常时回退 lexical/relations/backlinks，不影响 exact recall。Embedding-3 的当前端点、批量和维度限制以智谱官方文档为准：<https://docs.bigmodel.cn/api-reference/模型-api/文本嵌入>。

## Memory Maintenance

### 目标输入

一个目标日必须小于当前 Business Day，并且有 authoritative ArchiveProjection。维护前要求归档 Session 和其中的 `Memory.md` 均存在且可读，且 Session facts 或活动 Memory 正文至少一项非空。缺失资料或两者都为空表示 not-ready/skipped；文件存在但 schema、日期、UTF-8 或大小不合法是 owner invariant failure。

Memory Maintenance Context 精确绑定：

```text
target-day Session turn facts
+ target-day archived Memory.md
+ optional latest daily strictly before target
+ optional existing target daily
+ read-only target-day Workspace archive view
```

Workspace 只通过 owner 生成的 manifest 和 digest-bound bounded text read 暴露，不提供任意归档路径访问。existing target daily 通过 exact recall 检查；`memory:target` 和 latest 已由 Background 提供，`inspect_sources` 不复制这些完整正文。

### Action 工作流

Controller 在一个 Maintenance Turn 内拥有 draft、inspection refs 和提交状态：

1. `inspect_sources` 以 `source=session|workspace` 分页理解 Session facts 或 Workspace resource 摘要，必要时 `read_workspace`；
2. `inspect` 搜索已有持久 Memory，`recall` 读取精确 Markdown 并绑定 digest；
3. `stage_create` 必须持有 query inspection ref；`stage_rewrite` 和 `stage_redirect` 必须持有 exact recall ref 与 digest；
4. `compose_daily` 对目标资料做有界分块、分层 reduce 和完整 daily composition；
5. `stage_daily` 选择 create、replace 或 unchanged，不存在 append；
6. `preview` 将知识变更、activity 更新和 daily 组成一个 owner changeset并验证所有引用；
7. `commit` 只接受未过期 preview revision；
8. `maintenance.complete` 只在 commit 后成功。

暂存文档可以互相引用，preview 对“现有 Markdown + 全部暂存文档”的最终视图统一验证。无关 stage 不使 inspection ref 失效；外部 catalog generation 或 source digest 变化会使它失效。User Turn 没有这些 mutation actions。

Maintenance 中真正被来源、inspect、recall、rewrite 或 redirect 使用的非 daily Link 更新 activity；同一任务内用集合去重，每个 Link 至多增加一次。activation 不在 User inspect/recall 中持久变化，也不为显式重复或乱序维护增加额外账本。

### 触发路径

自动和手动只有触发检查不同，进入同一个 Memory Maintenance Turn 后行为完全一致：

- 自动路径由每天的 scheduled Daily request 选择前一日；availability 只在目标 daily 缺失且目标 source ready 时登记，daily 已存在用于防止重复触发和启动重复提示；
- 手动路径为 `/maintenance memory YYYY-MM-DD`，明确目标日后即使 daily 已存在也复查 daily 与持久知识；
- 项目没有 `--rebuild` 或 `rebuild_memory`；
- 启动 preflight 只恢复日切、刷新 availability 和发提示，不运行 LLM；scheduler 在进程已经运行并越过配置时刻时投递 request，启动晚于时刻不 catch up。

## 提交与恢复

Memory changeset 为每份文档记录 expected digest 或 expected absent，绑定 catalog generation 和目标日。事务目录使用三种可恢复状态：`.preparing-<id>` 是尚未发布的临时目录，`<id>` 是已发布、可执行的 ready journal，`.completed-<id>` 表示所有目标已写入、只待清理。提交先在 preparing 目录中写入所有新 Markdown 和 manifest，完成校验后原子改名为 ready，再执行以下步骤：

1. 校验整份 manifest、顺序、staged digest、Markdown schema、目标日字段和全部 CAS；
2. 确认所有知识文档在前、daily 在最后；
3. 在首个目标写入前验证完整暂存文档集合与最终引用；
4. 按稳定顺序逐份原子替换，daily 最后写入；
5. 所有目标达到新 digest 后把 ready journal 原子改名为 completed，再清理 journal、重建 catalog，并 best-effort 刷新 embedding cache。

任何 staged 文档、引用或 CAS 在预检阶段失败时一份目标都不写。进程在 preparing 阶段中断时只清理临时目录；在 ready 的部分替换阶段中断时，下一次 Memory recovery 根据每个目标的 new digest 幂等前滚剩余操作；在 completed 清理阶段中断时只重试清理，不重复业务写入。因此 User Turn 不会在正常 Program 串行边界观察到 Maintenance 的半提交状态。事务只承诺项目现有的进程/文件操作恢复语义，不夸大为 fsync/power-loss durability。

## 日切与归档

`DailyLifecycleCoordinator` 的参与者为 Session、活动 Memory、Workspace。初始化顺序是 Session root、空 `Memory.md`、Workspace；归档前校验活动 Memory 日期，Session archive 完成后再次从归档 root 校验 `Memory.md`。pending transition 恢复也执行相同校验。持久 `memory/` 与 Home 不进入 archive。

活动日 lease 同时核对 Session、Workspace 和 Memory 的 Business Day；任一不一致都阻止 User/Endpoint 工作，避免把当前活动记忆写入错误日期。

## 模块与失败边界

```text
tinysoul/memory/
  engine.py            # 唯一业务门面
  links.py             # 五类持久 Link 与三类 Context ref
  documents.py         # strict frontmatter/Markdown
  active.py            # Session/Memory.md CAS
  store.py             # 持久文档读写
  catalog.py           # lexical/grep/references/backlinks/semantic fusion
  embeddings.py        # 可删除的 Memory 向量缓存
  transaction.py       # 多文档 journal/前滚
  daily.py             # daily 分层 composition
  background.py / actions.py / config.py

tinysoul/maintenance/memory/
  context.py           # target archive binding
  task.py              # readiness 与 Maintenance Turn
  actions.py           # draft/inspection refs/commit controller
```

可修正的参数、stale digest/ref、not-found 和 draft 顺序错误返回局部 Action failure。持久文档损坏、缺失引用、redirect cycle、事务 journal 损坏和原子写失败停在 Memory/Maintenance owner 边界并通过 Runtime bridge 处理。Embedding 失败是派生能力降级，不改变 Markdown 事实或 recall 可用性。

## 核心不变量

- User Turn 只修改活动 `Memory.md`；
- current/latest/target 是 Context ref，不是持久 Link；
- five-kind Markdown 是唯一业务事实；
- relations 只指向 entity/concept，evidence 只指向 daily/fact/note；
- fact 至少有 daily evidence，active note 至少有关联 entity/concept；
- 先 inspect/recall 再新增或更新，已有 Link 不 hard delete；
- explicit target 可复查已有 daily，自动路径用 daily existence 去重；
- daily 与知识通过一个 changeset提交，daily 最后写入并可恢复；
- embedding cache 可删除、可降级且不含 API key；
- Home、Archive 和 User action 不绕过 Memory owner 写持久 `memory/`。
