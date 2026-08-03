# Memory 设计

## 状态

Stage 6.2 已实施。Memory 正式位于 `tinysoul.memory`，默认持久根为项目顶层 `memory/`，配置为顶层 `[memory]`；文档是自由结构的单日 Markdown，search 以日期为候选。项目不保留 `home:memory@...` 别名、`home/memory/` 双读、迁移命令或自动迁移逻辑；旧 Link 按非法 Home Link 处理，旧路径不是 Memory 数据源。

## 定位

Memory 是 TinySoul 的长期日期记忆模块。它将指定 Business Day 的 Session 事实提炼为一份单日 Markdown，并向 User Turn 提供昨日自动 Background、跨日 search 和精确 recall。

Memory 与 Agent Home 平级：

- Agent Home 拥有当前有效的身份规约、用户偏好、WHAT、WHY 和 HOW；
- Memory 拥有按日期组织的长期经历记录；
- Session 拥有当日跨 Turn 事实与已归档的不可变 Turn 图；
- Context 拥有 Turn 内 Background 和 TurnTrace；
- Loop 只提供可复用 Turn 内核和 User Turn preparation，不解析 MEMORY Markdown；Memory Maintenance 的计划、archive binding 与 task/action 编排属于 `tinysoul.maintenance.memory`。

Memory 不是 Home 顶层 space，不是 runtime overlay，不参与 Home Review/Apply，也不进入 Daily Rollover archive。

## 设计目标

1. 使用独立的存储根、Link、配置、Action 和 failure 语义，不反向依附 Home 内部结构。
2. 普通 User Turn 只读 Memory；唯一写入边界是 Memory Maintenance 对单日文件的原子完整替换。
3. 昨日记忆作为每 Turn 重建的自动 Background；其它日期只按需进入 TurnTrace。
4. Link 稳定地表达日期资源，不泄漏物理年月目录。
5. Search、recall、Background 和 Maintenance 共享同一文档解析与上限，不建立第二份索引事实。

## 存储与 Link

持久结构固定为：

```text
memory/
  yyyy/
    mm/
      yyyy-mm-dd.md
```

稳定 Link 固定为：

```text
memory:YYYY-MM-DD
```

`MemoryLink` 或等价值对象负责严格的无后缀日期身份解析，并完成 Link/物理相对路径双向映射。`memory:YYYY-MM-DD` 不暴露 Markdown 格式或物理 `yyyy/mm/` 目录；反向映射仍只接受严格 `yyyy/mm/yyyy-mm-dd.md` 路径。旧 `.md` Link、`@`、资源子路径、绝对路径、反斜杠、`.`/`..` 或非法日期均拒绝。每个日期最多对应一份文档。

项目顶层 `memory/` 是默认布局；显式绝对 root 是受信任的部署或测试覆盖，不改变 Memory 的逻辑所有权。配置的 Memory root 在尚无任何记忆时可以不存在；Background/search 将其视为空 store，recall 返回 not-found。只有 Memory Maintenance 成功写入时才可创建 root 与目标年/月父目录；模块 import、builder、search 和 recall 不得为只读请求产生目录副作用。root 已存在但不是目录、Link 映射越出配置 root、路径包含 symlink 或 Maintenance 写入时不可用，属于 Memory 边界失败。

`<memory:YYYY-MM-DD>` 是可出现在 Context 中的引用语法，包括 Home 顶层内容、Session Background、MEMORY 正文和 ActionResult。它只提示 Agent 通过 `memory.recall` 召回指定日期，不内联正文、不自动展开，也不转换为 Home Link。

Memory Maintenance 生成的正文可以引用：

- 当前 actual Home 中已存在的规范 Home 顶层 Link；
- 已存在的其它日期 `<memory:YYYY-MM-DD>` Link。

Memory 通过 Home 注入的只读顶层 Link catalog 校验 Home Link，通过自身 store 校验 Memory Link。不允许目标日期自引用或引用尚不存在的 Memory；非法引用通过有界模型反馈修正，不静默删除。

## 文档契约

每份 MEMORY 是一个 Business Day 的自由结构 Markdown，不要求上午、下午、晚上或其它固定章节。Memory Link 与物理路径拥有日期身份；旧文件只要是非空、可读、受上限约束的 UTF-8 文本，即可被 Background、search、recall 读取，也可在人工 Maintenance 时作为同日 source，无需先迁移或满足当前 renderer 格式。

新生成 MEMORY 由框架确定性渲染日期 H1，LLM 只返回单个 Markdown body：

```markdown
# YYYY-MM-DD

自由结构的单日记忆正文
```

正文可以按主题、时间顺序、事项或自然段组织，可以使用 H2 及以下标题，但不得再生成普通或带 Markdown 合法前导空格的 ATX H1，也不得生成 Setext H1。新正文必须非空，最终文档必须在 Memory 配置的总长度上限内；超限不以静默截断伪装成完整记忆。

Memory 文档是日期事实的长期提炼，不保存 raw trace、reasoning、provider payload、Session store 路径或 Maintenance 中间候选。

## User Turn 读取

### 昨日自动 Background

Turn preparation 使用 Program 已捕获的 `BusinessDay` 与 `maintenance.timezone` 计算精确的昨日，不自行读取系统日期。`MemoryBackgroundEntryProvider` 只查询该日期：

- 文件不存在时不产生 entry，不搜索更早日期；
- 文件存在时返回 Link 和完整、受上限约束的非空 Markdown，不要求固定章节；
- 文件无法读取、为空、不是 UTF-8 或超过完整文档上限时，preparation 以 Memory 模块失败结束，不伪装为“昨日无记忆”。

该 entry 属于每 Turn 重建的自动 Background source，不跨 Turn 保留在 Context 内存中。它不是身份规约，因此可在 Context 压力回收中被逐出；`home:agent@AGENT` 仍不可逐出。Memory provider 不向 Phase1 目录暴露全部历史日期。

### Search

`memory.search(query, top_k)` 对 Memory-owned 日期文档执行有界检索。候选语义单元就是单日文档，每个日期最多产生一个 candidate 和一个结果。每个 item 只包含：

- `memory:YYYY-MM-DD` Link；
- 日期；
- 受配置上限约束的摘要与检索元数据。

Memory 流式扫描完整日期 store，对每份有界文档评分并只保留固定数量的最佳日期 candidate，因此工作内存、模型输入和输出有界；当前不引入持久索引或向量数据库。Memory 负责确定性候选、候选上限、稳定排序和 candidate-only validator；可使用专用 `memory_search` LLM Task 重排候选。Task 失败或返回候选外 Link 时回退确定性结果，不把只读检索变成不可用。Search 是 Agent 在不知道精确日期时使用的候选日期发现 Action，不返回正文片段或完整 MEMORY，也不修改 Background；找到候选日后，Agent 可继续调用 recall。

### Recall

`memory.recall(memory_link)` 只接受精确 `memory:YYYY-MM-DD`，返回该日期的完整 Markdown 和稳定元数据。它用于 Context 已出现精确 Memory Link，或者 search 已发现目标日期的情况。Recall 不提供章节过滤或分页；Maintenance 产生的文档已被总长度上限束缚。若外部修改使文档为空、非 UTF-8 或超限，recall 显式失败而不返回不完整正文。

Search 和 recall 都是 Memory-owned native action。Action executor 只解析参数、调用 Memory 门面并将局部成功/失败映射为 `ActionResult`；Context 将结果记入当前 TurnTraceHeap。

## Memory Maintenance

Memory Maintenance 是 MaintenanceEngine 编排的独立 task。它接受明确目标 Business Day，并把目标关闭日的 ArchiveProjection 绑定为 Maintenance Turn 的 Session/Workspace 情景；真正写入 Memory owner 的 consolidation source 仍是：

```text
SessionMemoryFactsProjection(target day)
+ optional existing memory/yyyy/mm/yyyy-mm-dd.md
-> complete replacement memory/yyyy/mm/yyyy-mm-dd.md
```

Session 负责归档图校验、按需递归 Summary、去重可达 Turn 事实并按 Turn 开始时间稳定排序；Workspace 负责交付同日只读 Manifest；Memory/Maintenance 都不读取 Session 或 Workspace 的私有 store。Maintenance Turn 可以 inspect 归档 Session 和 Workspace 以理解一天的情景，再由 `maintenance.memory.consolidate` 把有序 Session facts 与可选同日期旧 MEMORY 交给 Memory owner 执行有界分块和分层 reduce。Memory owner 不读取其它日期 MEMORY 正文、active Home diff 或 `SKILL_MEMORY.md`。

正常 Daily task 面向 archive catalog 中所有尚无有效 MEMORY 的关闭日；目标 MEMORY 已存在且是非空、可读、未超限 UTF-8 文本时，在读取 Session 或调用模型前 skipped。显式 `--rebuild` request 可以读取任意既有 Markdown 格式的同日期旧 MEMORY，将其与 Session facts 重新整理为一份新的规范文档。旧正文中的 Link 只作为 source；新输出中的 Link 必须重新通过所有者存在性校验。

完整 actual Home Link catalog 和其它日期 Memory Link catalog 只用于本地验证，不完整进入模型输入。模型只接收从本次 Session/旧 Memory source 中提取、实际存在且受总字符预算约束的 Link hints；模型仍可生成未列入 hints 但实际存在的 Link，本地 validator 负责接受或以有界错误反馈要求重试。

目标 archive 缺失或 Session projection 无 Turn facts时返回非持久 `skipped`，对目标 Memory 零写入。默认 work 在目标已存在时于 Session/LLM 之前 `skipped`；rebuild work 可结合同日期旧 MEMORY 与 Session 重写。成功时只原子替换单个目标文件，不 append，不保存 candidate、plan、review result 或中间状态。原子替换前的写失败保留旧文件；若替换已经完成但调用方随后观察到进程异常，目标文件就是新的 persisted fact，下一次默认 work 按“目标已存在” skipped。该保证覆盖进程异常和文件操作失败，不扩展为断电/fsync 承诺。

Memory service 只发布 verbose `memory.maintenance.started` 与 `completed/skipped/failed` Observation。事件只含目标日期、rewrite mode、Memory Link、fact/model-call 计数、成功 digest、skip/failure kind 或稳定异常类型，不含 Session facts、旧/新 MEMORY 正文、模型 prompt/reasoning 或绝对路径。Program 在 normal 层另行发布该 work 的唯一结果；Observation emitter 失败不能改变原子写、outcome 或后续 Program work。

启动 availability 从权威 archive catalog 计算所有 eligible closed days，不只猜测昨日，也不保存平行 skip 状态。手动 Memory request 可以指定其中任意关闭日；`--rebuild` 允许显式重建已有日期。

## Context 协作

Background 是 Context-owned 的通用 Phase1 语境容器。Context 定义通用 Background provider/entry 协议、Link 唯一性、source 类别和逐出策略；Home 和 Memory 只实现各自 provider，不拥有 BackgroundContext。

- Home provider 提供不可逐出的 core 和可由 Phase1 加载的 Home 顶层目录；
- Memory provider 只提供可逐出的昨日自动 entry；
- Session 继续以版本化全量 snapshot 提供当日跨 Turn 历史。

`load_background`/`evict_background` 仍属于 Context Control Tool。全部历史 Memory 不进入该目录，因此模型看到 `<memory:...>` 后应使用 `memory.recall`，不使用 `load_background`。

## 模块边界

目标代码组织：

```text
tinysoul/memory/
  __init__.py
  engine.py
  config.py
  links.py
  store.py
  search.py
  maintenance.py
  consolidator.py
  actions.py
  errors.py
  failures.py

tinysoul/maintenance/memory/
  task.py             # archive projection 与 Maintenance Turn 编排
  actions.py          # owner-bound inspect/consolidate/complete actions

tinysoul/action/catalog/memory/
  domain.toml
  actions/search.toml
  actions/recall.toml

configs/memory.toml
memory/
```

`MemoryEngine` 是唯一 Memory 业务门面，对上层提供 Link/store 查询、Background provider、search/recall、eligibility 和原子 consolidation。`tinysoul.maintenance.memory` 拥有目标 archive 绑定、Maintenance Turn 与专用 actions，不复制 Link/store/renderer 规则。配置、普通 Action executor、Background provider 与 consolidator 是装配 SPI；store、renderer 和 validator 是模块内部实现。

Memory 配置位于顶层 `[memory]`，拥有根目录、完整文档上限、search 预算和 consolidation 预算；`memory.maintenance.link_hints_max_chars` 单独限制模型可见 Link hint 值的总字符数。旧 `[home.memory]` 整体删除；Memory 不继承 Home `max_write_chars` 或 Home root。配置加载时不接受旧键别名。

Memory 只依赖：

- Infra 的受控路径、有界 UTF-8 读取、digest 与原子替换；
- LLM 的 provider-neutral task runner；
- Session 的 typed facts projection；
- Home 提供的只读顶层 Link catalog 协议；
- Context/Action 的 provider 与 executor SPI。

Memory 不导入 Home layout/overlay/search 实现，Home 也不导入 Memory store 或 consolidator。AppBuilder 在组装边界注入窄协议并注册 Memory action、Background provider 和 Runtime bridge。

## 失败与 Runtime 桥接

Memory 遵守三层失败语义：

1. 局部 Action/Maintenance 结果：search 无匹配、recall 目标不存在、Session 缺失/为空、模型输出不合规、Link 校验失败或自动目标已存在；
2. 模块边界异常：配置无法解释、Memory root 不可用、已存文档为空/非 UTF-8/超限、路径不变量破坏或原子写失败；既有 Markdown 不采用当前日期 H1 或章节结构本身不是损坏；
3. Runtime 语义异常：通过 `MemoryFailureKind` 与专用 Runtime bridge 映射为启动失败、结束当前 User Turn 或结束当前 Maintenance Turn；Maintenance task 再把失败收敛为 typed task outcome。

昨日文件缺失是正常状态；文件存在却不可读不得降级为缺失。Search 遇到无法解释的已发现 Memory 文档时整个 action 失败，不返回无法声明完整性的部分结果。Maintenance 任何原子写前失败都保留旧目标不变；原子替换完成后不再把旧目标视为事实，也不建立额外事务日志回滚新文件。

## 验收要点

- Home parser/catalog 不再接受 `memory` space，项目中不存在 `home:memory@...` 兼容路径；
- Memory Link 与年月路径双向映射且拒绝非法日期/越界；
- 每 Turn 只自动加载精确昨日，缺失不回退，Context 压力可逐出该 entry；
- `memory.search` 以单日文档为候选并返回日期 Link 和有界摘要，不返回完整正文；
- `memory.recall` 仅接受精确 Link，返回完整且受上限约束的单日 Markdown；
- search/recall 结果只进入 TurnTrace，不修改 Background；
- Memory 正文中的 Home/Memory Link 都做所有者存在性校验；
- Memory Maintenance Turn 使用指定关闭日的 Session/Workspace projection；consolidation 只读取有序 Session facts 和 rebuild 时的可选同日任意格式旧 Memory，成功时只增加日期 H1 并原子完整重写；
- 空/缺失 Session 不创建文件；原子替换前失败不改变旧文件，替换后异常通过目标存在性幂等收束；
- Home Maintenance、Daily Rollover 和普通 Home mutation 对 `memory/` 零写入。
