# 20260713 Agent Home / Memory / Daily Lifecycle Execution Plan

## 状态

status: done

本文是 Agent Home、Memory、Daily Lifecycle 和 Maintenance 的唯一执行规划，统一取代此前 followup plan 与 semantic audit。规划以当前 `AGENT.md` 和 `docs/design/` 为约束，只保留已经确认的核心语义；旧的 Home daily archive、archived Home workset、Settlement root、持久 review/plan/apply 状态机、MEMORY runtime candidate、Home-owned Memory 边界和 HOW usage Session provenance 均不属于目标设计。Stage 1-8.1 已全部实施；默认 Agent Home 内容扩写与真实 Action capability 扩充分别进入独立后续计划。

后续说明：Stage 8.1 中 Agent/WHAT/WHY Top Link 携带 `.md` 的选择已由 `20260715-done-home top link identity refactor plan.md` 替代；当前 canonical 语义以 `AGENT.md`、`docs/design/agent_home.md` 与该后续计划为准。

状态统一使用：

- `done`：代码、测试和设计文档均已同步；
- `in_progress`：已有部分实现但验收未闭合；
- `pending`：尚未实施；
- `blocked`：存在必须先确认的设计或外部依赖。

## 总体设计意图

TinySoul 使用两个相互独立的持久生命周期：

```text
Business Day 生命周期
  runtime/session + runtime/workspace + active Trash
  -> 固定日界确定性归档
  -> archive/<timestamp>/{session,workspace,trash}
  -> 新日空 Session/Workspace

Home 工作副本生命周期
  actual Home fallback
  + 跨日 runtime/home overlay
  -> Agent 在普通 Turn 中透明读写 effective Home
  -> Home Maintenance 直接 review active overlay
  -> apply/discard 后清理已处理 runtime diff

Memory 生命周期
  指定日期 Session archive
  + 可选同日期旧 MEMORY
  -> Memory Maintenance 完整重写 memory/yyyy/mm/yyyy-mm-dd.md
  -> 昨日在每 Turn 自动进入可逐出 Background
  -> 其它日期通过 memory.search/recall 进入 TurnTrace
```

核心原则：

1. Session、Workspace 和 Trash 按 Business Day 强制物理归档；Home 不参与日切或 archive；
2. `runtime/home` 跨 Turn、跨日、跨重启保留，是唯一尚未提交的 Home 事实，不建立第二份 workset/store；
3. Agent 通过 `home:` Link 透明读写 effective Home，不感知 actual/runtime 分层；通过 `memory:YYYY-MM-DD.md` 访问独立日期记忆；
4. 普通 User Turn 只修改 runtime Home；actual Home 只由 Home Maintenance 修改；
5. MEMORY 在 User Turn 中只读顶层 `memory/`，不建立 runtime；MEMORY 只由 Memory Maintenance 写入；
6. Home Maintenance 与 Memory Maintenance 是可独立触发的 Program work，没有共同 plan 或共同提交边界；
7. Runtime 只提供运行位置、Trap、Signal 与 Observation，不保存 Maintenance 业务状态；
8. Background 由 Context 拥有并聚合 Home/Memory provider，不由 Home 拥有；
9. App/scheduler/terminal 只产生 typed Program event，不直接 diff、review 或读写 Home/Memory。

## 当前架构与代码进度

| 模块 | 当前状态 | 已实现能力 | 与目标设计的差距 |
| --- | --- | --- | --- |
| Infra | done | 配置、JSON、原子文件、digest、有界读、路径约束 | 复用现有能力。 |
| Runtime | done | Program/Turn/Cycle/Phase/Module frame、Trap、Signal、Observation | Maintenance 复用同级 Turn/Module frame，不新增状态系统。 |
| LLM | done for current tasks | provider-neutral Task、模型链、输出解释、JSON-only `home_search`、`memory_search`、`home_maintenance` 与 `memory_maintenance` profile | Maintenance Observation 不包含 prompt/reasoning，不新增持久状态。 |
| Action | done for current User Turn scope | 域选择、调用归一化、批次/backend/result、Home/Memory catalog 与 executor、只读 catalog identities | Memory search/recall 已是独立 native action；Maintenance 不作为普通 Action。 |
| Context | done for current User Turn | MessageStack、Context-owned 多 provider Background、Working/Trace、信号批次和压力恢复 | Home core 不可逐出，昨日 Memory 与 Phase1 动态项按 source 回收。 |
| Session | done for lifecycle and Memory projection | 不可变 Turn record、summary、orphan reconciliation、日归档、archive snapshot、递归 Summary 的 Memory facts projection | Stage 6 已通过 Loop Maintenance runner 按日期定位并调用 projection。 |
| Workspace | done for active lifecycle | 当日资源、Manifest、Trash、日归档 | 从目标日切看已基本闭合，不参与 Maintenance。 |
| Loop | done through Stage 7 | User Turn、显式 BusinessDay、可恢复 rollover 与 crash matrix、Session archive 定位、typed Maintenance work/outcome、启动 preflight/reminder、分层 Observation，以及 MemoryEngine/Background provider 协作 | 生命周期核心闭环已完成。 |
| Agent Home | done through Stage 7 | Link、动态 effective Background provider、schema v2 跨日 overlay、resource/top/prompt mount mutation、Catalog mount reconcile、SKILL_MEMORY、WHAT/WHY/HOW top search、无持久状态 Home Maintenance、crash recovery 与 verbose Observation | Home 对日期 Memory 零所有权。 |
| Memory | done through Stage 7 | 独立 Link/store/config/search/recall/Background/Maintenance/consolidator/action/failure/bridge，默认顶层 `memory/`，自由结构单日 consolidation、按日 search、有界 Link hints、原子写恢复与 verbose Observation | 生命周期核心闭环已完成。 |
| App | done through Stage 7 | Builder、CLI、输入分发、输出路由、Maintenance channel、启动提示、scheduler、共享 Observation 装配、受控 BusinessClock seam，以及独立 MemoryEngine/provider/registrar/bridge 装配 | 无网络正式装配 E2E 已覆盖；发布资产留待 Stage 8。 |
| 发布与初始化 | done | package-owned catalog、HOW 发现目录、可编辑项目模板、init CLI、README、wheel 与 fake-provider E2E | Stage 8 已闭合。 |
| Capabilities | separate follow-up | subprocess/script/LLM action backend mechanism 已有 | 真实能力按独立后续规划扩充，不属于本执行计划。 |

阶段 1 已删除 Home 日归档实现：`DailyLifecycleCoordinator` 不再接收 Home，新的 transition 不含 `HOME_ARCHIVED` 或 `settlement_status`，Home overlay schema v2 不含 Business Day，Engine/Manager 不再暴露 Home `active_day`、`initialize_day` 或 `archive_day`。读取旧 schema v1 manifest 时原地迁移；读取旧 finalized transition 时只忽略历史 `home_archived` step，不恢复旧业务语义。若未完成的 legacy pending transition 已包含 Home，coordinator 明确要求人工恢复，不能静默丢弃目录。

阶段 2 已清理 top catalog/read 的 source-first 行为和 mutation 中的 settlement/当日镜像旧语义；普通 User Turn Home 读写现在统一遵守 active cross-day overlay。

## 目标存储结构

```text
home/                                  # actual Home
  agent/
  what/
    entity/
    concept/
  why/
  how/
    <skill>/
      SKILL.md
      references/
      scripts/
  how_domain/
  how_action/

memory/                                # Memory-owned, read-only in User Turn
  yyyy/
    mm/
      yyyy-mm-dd.md

runtime/
  session/                             # current Business Day only
  workspace/                           # current Business Day only
  home/                                # cross-day active overlay
    .tinysoul/
      home_overlay.json
      operations/
    how/<skill>/SKILL_MEMORY.md

archive/
  <timezone-timestamp>/
    transition.json                    # physical rollover only
    session/
    workspace/
    trash/
```

明确禁止：

- `archive/<timestamp>/home`；
- 顶层 `settlement/` 或 `SettlementManifest`；
- Home pending archive、review plan、decision log、apply journal 或 completed status；
- `runtime/home/memory`；
- `home/memory`、`home:memory@...` 或任何旧 Link/path 兼容别名；
- Memory runtime overlay、双读、自动/人工迁移操作；
- `DOMAIN_MEMORY.md`、`ACTION_MEMORY.md` 或其它平行 skill memory；
- memory candidate store、`home.memory.append` 或 `memory.append` mutation action。

## User Turn 处理流程

1. Program 在 work lock 内捕获唯一 aware time 与 `BusinessDay`；
2. `DailyLifecycleCoordinator.ensure_active_day` 只校验/归档 Session 与 Workspace/Trash；
3. Context `begin_turn` 清空上一 Turn 的通用 Background、Session Background 与 Turn 内状态；
4. Context 从 Home provider 重建默认 core/catalog，并从 Memory provider 加载精确昨日的完整有界正文（如有）；不回退更早日期；
5. Session 投影当前 Business Day 历史，Workspace reconcile 并投影 Manifest；
6. Phase1/2/3 完成语境、行动选择和行动执行；
7. `core.answer` 经 TurnOutput Trap 收束；
8. Session 幂等提交不可变 Turn record；
9. 只有 completion pipeline 成功才发布 answered output。

Context-owned Background、昨日 Memory entry 与 Phase1 加载项是 Turn 内状态；runtime Home 文件与 overlay record 是跨 Turn 持久事实，顶层 Memory 文件是长期只读事实。三者不能混为同一层。

## Daily Rollover 设计

### 强制参与者

只有：

- Session；
- Workspace；
- Workspace active Trash。

Home 不提供 active day 给 coordinator，也不参与 claim、move、initialize、rollback 或 archive overlap 校验。

### 顺序

1. 恢复或创建 `archive/.pending-<operation-id>/transition.json`；
2. Session reconciliation 后移动到 pending `session/`；
3. Workspace 完整 reconcile，把 active Workspace 与 Trash 分别移动到 `workspace/`、`trash/`；
4. 初始化同一新 Business Day 的 Session 与 Workspace；
5. pending 原子改名为 `archive/<timestamp>/`；
6. coordinator 返回后才允许新日 Program work。

日切是确定性物理过程，不调用 LLM，不检查或读写 MEMORY，不触发 Home commit。程序运行时由内置 scheduler 在日界投递触发；程序未运行时由启动或下一项 work 前的 preflight 恢复并补做。跨午夜 User Turn 归属开始日，完成旧日 Session 提交后再在下一 work 边界日切。

## Effective Home 设计

### 读取规则

所有 Home Link 使用同一 effective 规则：

```text
runtime override
  -> runtime tombstone hides actual
  -> actual Home fallback
```

top catalog、top read、Background loader、progressive resource read、domain/action prompt mount 和 top search 都必须复用同一 Home-owned lookup，不能各自做 source-first 判断。

Memory 不是 Home effective view 的旁路或例外；`memory:YYYY-MM-DD.md` 由独立 Memory 模块映射到顶层 `memory/`。

### Overlay 生命周期

- overlay 不以 Business Day 为身份；
- daily rollover 不修改 `runtime/home`；
- 程序启动恢复 operation 并 reconcile 同一 active overlay；
- 未触发 Home Maintenance 时，所有 runtime diff 跨日继续有效；
- actual Home 外部变化不会自动覆盖已物化 runtime，Home Maintenance 负责显式 review；
- operation journal 只保证 runtime mutation 可恢复，不表达 Maintenance 状态。

### SKILL_MEMORY

- 只存在于 `runtime/home/how/<skill>/SKILL_MEMORY.md`；
- 生命周期是“自上次 Home Maintenance 以来”，不是自然日；
- 通过既有 progressive resource action 读取、write、patch；
- 记录临时工作记忆、skill 使用反馈和待 review 变化；
- Home Maintenance 可据此修改 actual `SKILL.md`、references 或 scripts；
- 文件自身永不进入 actual Home，skill review 完成后清空。

## Home Mutation 设计

### Progressive Resource

现有 `home.resource.read/write/patch/delete` 保持 `/` Link 边界，只修改 active overlay。

### Top Content

新增独立：

```text
home.top.write
home.top.patch
home.top.delete
```

规则：

- 只接受 `agent/what/why/how` 空间的 `HomeTopLink`，`memory:` 不是 Home action 参数；
- 允许在 runtime 创建不存在的顶层内容；
- 新 WHAT Link 必须显式包含 `entity/` 或 `concept/` 及真实 `.md` 文件名，分类属于稳定身份；
- `home:agent@AGENT.md` 允许 write/patch，禁止 delete；
- write/patch/delete 都只改变 active overlay，不直接写 actual Home；
- runtime-only top 必须进入 effective catalog，并可在下一 User Turn Background 重建时被加载。

### Prompt Mount

新增：

```text
home.prompt_mount.write
home.prompt_mount.patch
```

逻辑 `HomePromptMountLink` 由 Action Catalog 中定义的 domain/action 自动维护：

- catalog 存在 domain/action，逻辑 mount 即合法；
- actual/runtime 正文都不存在时，自动注入为空；首次 write 物化 runtime 内容；
- action 临时 disabled 或 provider 暂时不可用不删除 mount；
- domain/action 从 catalog 删除时，框架在 runtime 形成删除语义；
- 模型不拥有 prompt mount create/delete action；
- prompt mount 不创建任何 memory 文件。

## Home Maintenance 设计

### 输入

只包括：

- 当前 active `runtime/home` overlay；
- 当前 actual Home；
- runtime 中的 `SKILL_MEMORY.md`。

不读取 Session、Workspace、Trash 或 archive，也不创建 Home archive/workset。

### Review 与 Apply

Home-owned reviewer 构造有界、内存态 diff/decision/outcome，不序列化：

1. `copied` 表示 Agent 未修改，直接清理，不能因为 actual 后来变化而把旧 runtime 副本写回；
2. `created/modified/deleted` 使用 baseline、runtime 和 current actual 作为 review 事实；
3. scheduler/background 模式允许 Agent 对全部合法差异自动 apply/discard；
4. 人工模式通过 App-owned decision provider 在终端逐项确认；Home reviewer 不读取 stdin；
5. apply 以单文件原子替换/删除写 actual，discard 不写 actual；
6. 决定完成后清理对应 runtime record/content，使 effective read 回退到 actual；
7. `SKILL_MEMORY.md` 在对应 skill review 后清空；
8. `home:agent@AGENT.md` delete 在进入 reviewer 前即为非法状态。

### 中断语义

- actual 写入前中断：runtime diff 保留，下次重新 review；
- actual 原子写完成、runtime 清理前中断：下次发现两者一致并清理；
- 多文件处理中断：已处理项已清理，剩余 active diff 重新 review；
- 人工终止逐项确认：已确认项保持结果，未确认项继续留在 overlay；
- 不恢复上次内存 decision，不保存未完成 operation list。

Program work lock 串行化 Home Maintenance 与 User Turn。Maintenance 期间新输入排队，不能与 runtime mutation 并发。

## Memory Maintenance 设计

### 输入与输出

任务接受明确目标 Business Day：

```text
Session archive for yyyy-mm-dd
+ optional existing memory/yyyy/mm/yyyy-mm-dd.md
-> complete replacement memory/yyyy/mm/yyyy-mm-dd.md
```

规则：

- Session 通过自己的只读 archive query 门面提供专用 Memory facts projection；该 projection 按需递归解析已提交 Summary 图，交付按 Turn 开始时间稳定排序的可达有界事实，不向 Memory 暴露 Session store 或 archive 文件结构，也不把 Summary 与其子 Turn 重复作为事实；
- Memory 校验每个 fact 的开始时间属于目标 Business Day，但不把 Turn 或最终文档强制划分为时间段；
- Session archive 不存在或 projection 不含 Turn facts 时返回 `skipped`，不创建、不覆盖也不删除同日 MEMORY；
- 目标不存在时，只使用同日 Session；
- 目标存在时，只额外读取同日期旧 MEMORY；
- 不读取其它日期 MEMORY、Workspace、active Home diff 或 `SKILL_MEMORY.md`；
- Session facts 与同日旧 MEMORY 作为统一有序 source 序列执行有界、分层 consolidation，不静默截断；超过总字符或最大调用次数硬上限时失败并保持旧文件不变；
- consolidator 使用严格 JSON object 输出单个自由结构 Markdown body；Memory renderer 只负责固定日期 H1。既有同日 MEMORY 无需满足该 renderer 格式，只要是非空、可读、上限内的 UTF-8 文本就可在人工重写时作为 source；
- 完整 Home/Memory Link catalog 只用于本地 validation，模型只接收从本次 sources 提取且受字符预算约束的有效 Link hints；
- MEMORY 中的规范 Home top Link 只允许指向当前 actual Home 中已存在的顶层内容；`<memory:YYYY-MM-DD.md>` 只允许指向已存在的其它日期 MEMORY，用于提示 Agent 通过 recall 召回；非法、不存在或目标日自引用必须作为有界模型反馈进入重新生成，重试耗尽后失败；
- 输出是完整重写，不 append；
- 目标使用单文件原子替换，失败保持旧文件不变；
- stable Link 始终是 `memory:YYYY-MM-DD.md`，不提供旧 Home Link 别名。

### 自动提示

启动时只检查配置业务时区中的昨日：

```text
昨日 Session archive 存在且 projection 含 Turn facts
AND 昨日 MEMORY 不存在
-> 提示 Memory Maintenance
```

不扫描更早日期，不持久化 skipped 状态。因此同一业务日内重启仍可能再次提示；该日期不再是昨日后，不再自动提示。人工命令仍可指定任意存在 Session archive 的日期，也可显式重写已有同日 MEMORY。

## Memory User Turn 访问设计

Background 提升为 Context-owned 通用 Phase1 Background，通过 Link 命名空间分离的 provider 聚合内容。Home provider 继续提供不可逐出 core 与可由 Phase1 加载的 Home top catalog；Memory provider 只提供当前 Business Day 精确昨日的自动 entry。

- 每个 User Turn 都重建昨日 entry，不依赖上一 Turn 的 Context 内存；
- 昨日文件存在时加载完整但受文档上限约束的 Markdown；不存在时正常省略，不回退更早日期；
- 已存在文件不可读、为空、非 UTF-8 或超限是 Memory 模块失败，不伪装为缺失；任意 Markdown 章节结构本身不是错误；
- 昨日 entry 可在压力回收中于 Phase1 动态项之后被逐出；Home core 继续不可逐出；
- 更早日期不进入 `load_background` catalog，Context 中的 `<memory:YYYY-MM-DD.md>` 提示 Agent 调用 `memory.recall`。

`memory.search(query, top_k)` 的候选单元是完整单日 MEMORY，每个日期最多产生一个候选；只返回 Link、日期、有界摘要和必要检索元数据。完整 store 以流式方式参与确定性评分，只保留固定数量的最佳日期候选，使工作内存、模型输入和输出有界；专用 `memory_search` LLM rerank 失败时回退确定性结果，当前不引入持久索引或向量数据库。

`memory.recall(memory_link)` 只接受精确 `memory:YYYY-MM-DD.md`，返回完整但受上限约束的非空单日 Markdown，不增加章节过滤或分页。外部改动造成空文件、非 UTF-8 或超限时明确失败，不截断后伪称完整。Search/recall 都是 Memory-owned native action，ActionResult 只进入 TurnTrace，不修改 Background。

## Program、Scheduler 与输入边界

Program 增加两个独立 work kind：

```text
home_maintenance
memory_maintenance(target_day)
```

二者拥有独立 outcome，不组成共同事务。稳定 outcome：

```text
HomeMaintenanceOutcome
  completed | stopped | failed

MemoryMaintenanceOutcome
  completed | skipped | failed
```

outcome 只存在于当次运行结果与 Observation，不持久化。

Home outcome 与当前 Home-owned service 语义一致：`completed` 表示所有当次可 review change 已处理完成，无 diff 也属于完成；`stopped` 表示人工 decision provider 在某个未确认项前终止，已确认项保持结果、剩余 diff 留在 overlay；`failed` 表示 review 或模块边界失败，已完成项不回滚。`needs_confirmation` 是 App decision channel 等待输入时的瞬时交互状态，不是最终 outcome；未触发 Home Maintenance 也不由 Home service 构造 `skipped` outcome。以上 outcome 已是稳定语义，不再是待选建议。

入口规则：

- scheduler 是 App-owned InputSource，只投递 Program event；
- scheduler 在日界触发 daily rollover，并在配置夜间时点触发自动 Home/Memory Maintenance；
- 启动先补做 daily rollover，再提示 active Home diff 与昨日缺失 MEMORY；
- Home 与 Memory 可以由独立人工指令触发；
- 人工 Home 使用专用 decision channel 逐项确认，自动 Home 使用 Agent 全自动 decision；普通输入继续留在 Program queue；
- CLI/terminal 不直接遍历 archive、解析 overlay 或读写 Home/Memory；
- Maintenance 执行期间不接受 append input，新输入留在 Program queue。

## 模块所有权

### Agent Home

- effective lookup、runtime mutation 与 overlay recovery；
- top/resource/prompt mount Link 到路径的映射；
- prompt mount catalog reconciliation；
- SKILL_MEMORY lifecycle；
- Home reviewer/apply/cleanup；
- 提供 actual Home 顶层 Link 的只读 catalog 协议，不解析 Memory store。

### Memory

- `memory:YYYY-MM-DD.md` 与 `memory/yyyy/mm/yyyy-mm-dd.md` 双向映射；
- 完整有界非空日期文档读取与 store catalog，不要求既有 Markdown 章节结构；
- 昨日 Background provider；
- `memory.search` / `memory.recall` 及其 Action executor；
- Memory eligibility、consolidator、Home/Memory Link 校验与原子替换；
- 不读取 Home overlay、Session store 或 Workspace。

### Session

- active Turn/summary 不可变事实；
- daily archive；
- 按 Business Day 只读查询 archive；
- 不解释 MEMORY 文档，也不写 Agent Home 或 Memory。

### Workspace

- active Workspace/Trash 与 daily archive；
- 不参与 Home/Memory Maintenance。

### Loop

- daily rollover 只编排 Session/Workspace/Trash；
- Program work lock 和 Maintenance runner；
- typed work/outcome 与 Observation；
- 不解析 Home overlay、Session store、Memory Link/store 或 MEMORY 正文。

### App

- startup lifecycle、terminal command、scheduler 和 event dispatch；
- 注入 Home/Memory/Session/Loop 门面、Background provider 与 Action registrar；
- 不实现 diff、review、consolidation 或文件操作。

### Runtime、Context、Action、LLM

- Runtime 只提供控制边界；
- Context 每 User Turn 从多 provider 重建 Background，不读文件或持有 Maintenance 状态；
- Action 暴露普通 User Turn mutation/search/recall tools，不执行 Maintenance；
- LLM 执行 reviewer/consolidator task，不决定持久状态。

## 依赖顺序

```text
阶段 1 Daily Rollover / Home 生命周期解耦
  -> 阶段 2 Effective Home + Mutation
       -> 阶段 3 Home Maintenance
       -> 阶段 5 Home Top Search

阶段 1 Session archive query
  -> 阶段 4 Memory Maintenance

阶段 3 + 阶段 4
  -> 阶段 6 Program/App/Scheduler
       -> 阶段 6.1 Memory 模块拆分 + Context Background 提升
            -> 阶段 7 恢复、观察与 E2E
                 -> 阶段 8 HOW 发现、项目初始化与发布
```

## 执行阶段

### 阶段 1：Daily Rollover 与 Home 生命周期解耦

status: done

优先级：P0

实施项：

1. 从 `DailyLifecycleCoordinator` protocol、claim、journal、resume 和 initialize 中移除 Home；
2. 删除 `HOME_ARCHIVED` 与 `transition.json.settlement_status`；
3. archive 稳定结构改为 Session/Workspace/Trash；
4. 保证 rollover 前后 `runtime/home` 字节和 overlay revision 不变；
5. Home overlay schema 移除 Business Day 身份与 `active_day/archive_day` 业务 API，保留 operation recovery；
6. AppBuilder 不再把 Home 作为 daily participant 注入；
7. Session 增加按 Business Day 查询 archive 的只读门面；
8. 更新 daily/home/session/app 测试，删除三者同日的旧断言。

验收：连续跨日、启动补做和 crash recovery 只改变 Session/Workspace/Trash；Home runtime diff 原样跨日、跨重启可见。

实施结果：`tinysoul/loop/daily.py` 已收敛为 Session/Workspace/Trash journal，并提供只解释 transition 的 `session_archive_for(day)`；`tinysoul/session/engine.py` 通过 `archive_snapshot(day, root)` 校验 Session 自有 manifest/graph；Home overlay 已迁移为无日期的 schema v2，builder 在启动时恢复 operation、迁移 schema v1 并 reconcile，AppBuilder 不再向 daily coordinator 注入 Home。定向测试覆盖正常 rollover、失败恢复、Home 字节不变、legacy manifest 迁移和 archive snapshot 边界。

### 阶段 2：Effective Home 与 Mutation

status: done

说明：本阶段对 Home overlay、mutation、prompt mount 和 `SKILL_MEMORY.md` 的实现继续有效；第 3 项及实施结果中的 MEMORY Link/路径特判是当前旧实现，将由 Stage 6.1 从 Home 完全删除。

优先级：P0

依赖：阶段 1

实施项：

1. 建立 Home-owned effective catalog/lookup，统一 actual、runtime override 与 tombstone；
2. `read_top`、Background provider、prompt mount、resource read 使用同一 lookup；
3. 更新 MEMORY 日期映射和扫描到年月目录；
4. 实现 `home.top.write/patch/delete` 及 WHAT 分类/core delete 校验；
5. 实现 `home.prompt_mount.write/patch`；
6. 从 Action Catalog 派生逻辑 mount，并对 catalog 删除形成 runtime deletion；
7. 支持 runtime-only top 进入 catalog；
8. 实现并记录 `SKILL_MEMORY.md` 约定；
9. 增加跨日 overlay、runtime-only top、tombstone、actual 外部变化和 prompt mount 测试。

验收：Agent 跨 Turn/跨日透明读写同一 Home；MEMORY 不产生 runtime copy；所有普通 mutation 对 actual Home 零写入。

实施结果：`AgentHomeLayout` 只负责稳定 Link 与 relative path 的双向映射，`AgentHomeEngine` 根据 overlay record 与 actual fallback 统一解析 effective top/resource/prompt mount。top catalog 已包含 runtime-only entry 并排除 tombstone；MEMORY 只接受稳定日期 top Link 并映射年月目录。Action Catalog 增加 top 与 prompt mount mutation，`ActionEngine` 只暴露只读 domain/action identities，App 将其交给 Home reconcile 逻辑 mount。WHAT create、core delete、prompt mount create/delete 所有权和 `SKILL_MEMORY.md` 路径/actual 禁止规则均已在 Home 边界实施。测试覆盖跨重启 runtime-only top、actual tombstone、actual 外部变化、WHAT 分类、core/MEMORY 保护、Catalog mount 删除/恢复、SKILL_MEMORY 和普通 mutation 对 actual 零写入。

### 阶段 3：Home Maintenance

status: done

优先级：P0

依赖：阶段 2

实施项：

1. 定义内存态 frozen diff/decision/outcome，不实现 serializer/store；
2. 枚举 active copied/created/modified/deleted 与 SKILL_MEMORY；
3. 构造 baseline/runtime/current actual 三方有界 review；
4. 定义自动 reviewer LLM Task 和人工逐项 decision 边界；
5. 实现单文件原子 apply、discard 与 overlay cleanup；
6. copied 自动清理，SKILL_MEMORY review 后清空；
7. 保证 actual 写后清理前、部分多文件处理和人工中止可重跑；
8. 输出供 Loop 发布 Observation 的有界 outcome，不写 review 文件。

验收：后台全自动和终端逐项确认共享同一 reviewer/apply 服务；中断后只需 active overlay 与 actual Home 即可继续。

实施结果：新增 Home-owned `HomeMaintenanceService` 及 frozen change/decision/item outcome/run outcome；review 输入只含有界 runtime/current actual 预览、baseline/digest 元数据和可选同 skill `SKILL_MEMORY`。自动模式通过独立 JSON-only `home_maintenance` LLM profile 返回严格 apply/discard，review 协议失败收敛为非持久 `FAILED/review_failed` outcome；人工模式通过注入 provider 逐项决策并允许在未确认项前停止。copied、runtime/actual 已一致项和 actual 写后残留 overlay 均确定性清理；apply 使用单文件原子替换/删除，discard 不写 actual，core tombstone 在 review 前失败。SKILL_MEMORY 在对应 skill 全部 change 处理后清理，人工中止前未完成的 skill memory 保留。服务不序列化 diff/decision/outcome；Program work、Observation、终端 provider 和 scheduler 装配仍归阶段 6。

### 阶段 4：Memory Maintenance

status: done

说明：本阶段记录已完成的功能基线，当时 Memory 由 Home 承载。consolidation、Session projection 和 Program outcome 语义继续有效；路径、Link、配置、renderer/validator 所有权已由 Stage 6.1 替换，未保留旧兼容层。

优先级：P0

依赖：阶段 1

实施项：

1. Session 提供专用 Memory facts projection，按需递归 Summary 图并按 Turn 开始时间输出可达叶子事实；
2. consolidator 对有序 Session facts 和可选同日旧 MEMORY 执行有界分层 consolidation；
3. 使用严格 JSON object 承载单个自由结构 Markdown body，由 Memory 确定性渲染日期 H1；
4. 目标缺失时使用 Session，目标存在时额外读取同日期旧 MEMORY；
5. 对模型输出中的顶层 Link 做 actual Home 存在性校验，以有界反馈重试非法输出；
6. Session 缺失或为空时 `skipped` 且对目标文件零写入；
7. 原子完整写入年月分层日期路径，拒绝其它日期 MEMORY、Workspace、runtime Home 输入；
8. 提供昨日 eligibility 所需的模块查询但不保存 skip，跨模块提示编排仍归阶段 6；
9. 增加递归 Summary、有序单日 facts、空/缺失/长 Session、任意格式旧 MEMORY 重写、非法输出与 Link、原子失败和显式旧日期测试。

验收：指定日期非空 Session 稳定映射唯一自由结构单日 MEMORY；空或缺失 Session 不写文件；失败不改变旧文件；自动提示不扫描更早日期。

实施结果：Session 新增 `SessionMemoryFactsProjection`，在只读 archive snapshot 校验后按需递归 Summary 图，去重并按 Turn 开始时间交付叶子事实；projection 不包含 raw trace/reasoning 或 store 路径。Memory 以配置字符/调用预算对有序 facts 和可选同日旧 MEMORY 执行分层 reduce，严格接收单个 Markdown body 并确定性渲染日期 H1。输出中的 `<home:space@name>` 只允许指向 actual Home 既存顶层 Link，空/缺失 Session 分别返回非持久 skip reason，超限/非法输出在原子写前失败，成功只原子替换顶层 `memory/yyyy/mm/yyyy-mm-dd.md`。

### 阶段 4.1：App 集成测试隔离基线

status: done

优先级：P0

Stage 5/6 开始前，App 集成测试必须同时把 actual Home、Home runtime、Session、Workspace 和 daily archive 指向同一 `tmp_path` 下互不冲突的绝对路径。测试 actual Home 使用最小 `home/agent/AGENT.md` fixture；缺失 core 等失败测试显式覆盖自己的空 Home root。不得只隔离 `home.runtime_root`，也不得依赖 `.gitignore` 隐藏测试产生的真实 runtime/archive。现有 Builder/Runtime 测试 helper 已完成五个可变 root 隔离，并以配置回归用例锁定该边界。

### 阶段 5：Home Top Search 与真实 Home 内容

status: done

说明：Home 的 WHAT/WHY/HOW 搜索继续有效；当时纳入 Home top search 的 MEMORY 条目已由 Stage 6.1 删除，并由 `memory.search` 替代。

优先级：P1

依赖：阶段 2

Stage 5 实施时的已确认语义（其中 MEMORY 部分已由 Stage 6.1 覆盖）：

1. search 只包含 WHAT、WHY、通用 HOW 与 MEMORY，不包含 `agent`、`how_domain` 或 `how_action`；
2. 标题以 Markdown 首个 H1 为权威来源，短摘要取首个有效正文段；缺失时分别回退 Link name 与有界正文前缀，不建立独立 metadata 索引；
3. 确定性候选使用 link/name/title/summary/searchable prefix，候选上限为 20，默认 `top_k=5`、最大为 10；目录不超过候选上限时不因词法零分丢弃条目；
4. LLM rerank 失败时返回稳定排序的确定性候选，validator 始终只接受候选内 Link；
5. 首批 actual Home 分别增加一个简单 WHAT、WHY、HOW 示例；示例只说明 TinySoul 自身公开设计，不虚构用户事实；
6. MEMORY 业务继续由 Home 下独立 `memory.py` 负责；search 新增 Home-owned `search.py`，只消费 Home effective catalog。Infra 只保留真正领域无关的文本/排序原语，不解释 Home Link、space、runtime overlay 或 MEMORY。

实施项：

1. 基于 effective catalog 构造 link、space、标题、短摘要、digest 和有界 searchable prefix；
2. `home.top.search` 先确定性限制候选，再用现有 LLM task rerank；
3. validator 只接受候选内 link；
4. search 不物化全部 runtime copy、不自动加载 Background、不返回完整正文；
5. MEMORY 使用稳定日期 Link，不暴露年月路径；
6. 补实际 WHAT/WHY/HOW 内容与 SKILL_MEMORY 使用规约；
7. 测试 runtime-only top、tombstone、Home Maintenance 后内容和预算。

实施结果：新增 Home-owned `search.py`，由 `AgentHomeEngine` 只负责把统一 effective catalog 解析成 bounded document，search service 负责 H1/首正文段 metadata、link/name/title/summary/prefix 确定性评分、20 个候选上限和稳定排序；actual WHAT/WHY/HOW 搜索不创建 runtime copy，runtime-only/modified 使用当前 overlay，tombstone 被排除，MEMORY 始终读取 actual。新增 `home_search` JSON-only profile 与 candidate-only `LLMHomeSearchReranker`；Task failure、非法结构、重复或候选外 Link 回退确定性候选，合法空列表表达无匹配。`home.top.search` action 只返回 metadata/digest/score，不返回完整正文或自动加载 Background。配置新增 `home.search` 预算并拒绝未知/非法组合；AppBuilder 只注入 reranker。actual Home 新增 `home:what@concept/daily-lifecycle.md`、`home:why@separate-rollover-maintenance.md`、`home:how@daily-home-review` 三个相互链接的简单示例。定向测试覆盖 effective runtime、tombstone、actual 不物化、Maintenance 后 actual、候选限制、rerank validator/fallback/no-match、action profile、配置和默认示例。

### 阶段 6：Program、App 与 Scheduler

status: done

优先级：P1

依赖：阶段 3、阶段 4

已确认语义：

1. daily rollover 使用独立 typed wake-up event；每项 Program work 仍在统一单写者边界内执行日界 preflight；
2. 自动顺序固定为 `Daily Rollover -> Home Maintenance -> Memory Maintenance(昨日)`；Home/Memory 结果独立，前一 Maintenance 失败不阻止后一任务执行；
3. 显式命令使用 `/maintenance home` 与 `/maintenance memory [YYYY-MM-DD]`；在活跃 User Turn 中进入 Program queue，不形成 append；
4. 人工 decision channel 仅在存在关联确认请求时消费精确 `apply`、`discard`、`stop`；其它输入留在 Program queue。EOF 先停止当前人工 Home Maintenance，再请求 Program 退出；
5. 启动先补做 daily rollover，再非阻塞检查并提示 active Home diff，以及昨日存在非空 Session facts 但缺少 MEMORY；普通 User 输入等同于暂不执行提示任务，不保存 skip 状态；
6. 日界由业务时区午夜决定；漏掉的 daily rollover 在启动补做。Maintenance 不自动追补更早日期，Home overlay 原样保留，Memory 自动提示只看昨日；
7. scheduler 随长运行 `TinySoulApp.run()` 启用，不随 `run_once` 启用；业务时区午夜投递 daily rollover，默认 `00:05` 投递 Home Maintenance，默认 `00:15` 投递目标为昨日的 Memory Maintenance；时刻由 `app.scheduler` 显式配置；
8. Home 启动 pending 只统计 current actual 与 runtime 仍有真实差异的 created/modified/deleted 和尚存在的通用 HOW `SKILL_MEMORY.md`，不统计纯 copied 或 actual 已一致的恢复残留；
9. 自动 Memory Maintenance 在目标 MEMORY 已存在时直接 skipped，不读取 Session、不调用模型；人工 Memory Maintenance 允许结合同日期旧 MEMORY 与 Session 重写；无日期人工命令默认昨日；
10. Stage 6 最小 normal 事件固定为 `program.maintenance.available`、`program.work.completed`、`program.work.failed`。

实施项：

1. 增加 typed Home/Memory Maintenance Program event；
2. 增加 Maintenance runner 和独立 outcome；
3. 启动时主动补做 daily rollover；
4. 启动检查 active Home diff 与昨日 Session/MEMORY，发布终端提示；
5. 输入解析支持独立 Home 与带日期 Memory 指令；
6. 实现 App-owned 人工 Home decision provider，协调终端输入但不形成 User Turn append；
7. 增加 App-owned scheduler，所有触发进入 Program queue；
8. scheduler 自动 Home 使用全自动 reviewer；
9. Maintenance 期间输入排队；
10. CLI、interactive 与 scheduler 共享同一 runner。

验收：启动、日界、后台和人工触发都不复制业务流程；Home/Memory 任一失败不影响另一项或 User Turn 历史。

实施结果：新增 `ProgramWorkKind/Mode/Status/Outcome` 与独立 `ProgramMaintenanceRunner`，Home 和 Memory work 在 Program 单写者锁内分别执行 Daily preflight、保留有界 outcome，失败只形成对应 `FAILED` work 并继续处理后续队列。Program 启动先补做 rollover，再发布 active Home pending 与昨日 Session/MEMORY eligibility 提示；Home pending 由 Home service 根据真实 diff 和 `SKILL_MEMORY.md` 计算，Memory eligibility 由 Loop 定位昨日 archive、Session 递归投影 facts、Home 判断目标文件。Input parser/dispatcher 已支持 `/maintenance home`、`/maintenance memory [YYYY-MM-DD]`，Maintenance 指令在 active Turn 中仍进入 Program queue；App-owned `TerminalHomeDecisionBroker` 只在待确认时消费 `apply/discard/stop`，EOF 或 Program exit 会停止 pending review。App scheduler 使用进程内游标，以 `daily -> Home -> Memory` 顺序只投递当前日 typed event，不补跑停机期间更早 Maintenance；`TinySoulApp.run_once()` 不启动 source。自动已有 MEMORY 在 Session/LLM 前 skipped，人工命令保留同日重写能力。配置、纯调度时序、Program 独立失败、启动 eligibility、decision channel 和真实人工 Home apply 路径均有测试覆盖。

### 阶段 6.1：Memory 模块拆分与 Context Background 提升

status: done

优先级：P0

依赖：阶段 2、阶段 4、阶段 5、阶段 6

已确认语义：

1. Memory 与 Home 平级，持久根固定为顶层 `memory/yyyy/mm/yyyy-mm-dd.md`；不建立 runtime copy、overlay 或 archive copy；
2. Memory-owned Link 固定为 `memory:YYYY-MM-DD.md`；`<memory:YYYY-MM-DD.md>` 可出现在 Context 和 MEMORY 正文中，提示 Agent 通过 recall 召回，不内联正文；
3. 不保留 `home:memory@...`、`home/memory/`、`[home.memory]` 或 Home search 中 MEMORY 条目的双读/别名；不实现自动或显式迁移操作；
4. `tinysoul.memory` 独立拥有 Link/store、配置、search/recall、Background provider、Maintenance、consolidator、failure 与 Runtime bridge；
5. Background 是 Context-owned 的通用 Phase1 容器；Home 与 Memory 只是 Link 命名空间不同的 provider，任一模块都不拥有整个 Background；
6. 每个 User Turn 使用该 Turn 的 Business Day 自动加载精确昨日 MEMORY（如有），正文完整但受 Memory 文档上限约束，不回退更早日期；
7. 昨日 entry 每 Turn 重建，在 Context 压力回收中可逐出；Home core 仍不可逐出；
8. `memory.search(query, top_k)` 以单日文档为候选并返回日期 Link、日期和有界摘要；`memory.recall(memory_link)` 返回完整但受上限约束的单日 Markdown；
9. Search/recall 结果通过 ActionResult 进入当前 TurnTrace，不修改 Background；全部历史 Memory 不进入 `load_background` catalog；
10. Memory Maintenance 仍只消费指定日期 Session facts projection 与可选同日旧 MEMORY，与 Home Maintenance 的触发、outcome 和失败独立。

代码与配置实施顺序：

1. 建立 `tinysoul/memory/` 门面与边界类型：`MemoryEngine`、严格 `MemoryLink`、store/layout、config/errors/failures 和 Runtime Memory bridge；
2. 将原有 Memory consolidation 的有效业务逻辑迁入 Memory 内部，保留分层 consolidation、skip/rewrite 和原子替换语义；
3. 把目标路径切换到 `memory/yyyy/mm/yyyy-mm-dd.md`，outcome 中的稳定 Link 切换到 `memory:YYYY-MM-DD.md`；
4. 将现有 `[home.memory]` 的 consolidation 预算移到独立 `[memory]`，增加 Memory root、完整文档上限与 search 预算；删除 Home 对 Memory 配置和 Home `max_write_chars` 的依赖；
5. 从 Home Link parser/layout/catalog/effective top search/mutation guard 中删除 `memory` space 与全部 MEMORY 特判；Home 只暴露一个只读 actual top-link catalog 协议供 Memory validator 使用；
6. Memory validator 同时校验 actual Home 顶层 Link 与已存在跨日 Memory Link；拒绝目标日自引用、不存在 Link 和非法语法，继续用有界模型反馈重生成；
7. 实现 `MemorySearchService`：以单日文档为唯一候选粒度，复用现有 LLM task 边界建立 `memory_search` rerank/fallback；
8. 实现精确 recall；为保证“完整但受限”，已存文档超限时显式失败，不分页或静默截断；
9. 新增 `tinysoul/action/catalog/memory/` 与 `register_memory_actions`，实现 search/recall native executor；Action 层只负责参数边界和 ActionResult 映射；
10. 将 Context 现有 Home-specific Background state/rendering/builder 提升为通用 provider 聚合，为 entry 保留 owner/source/evictable 语义，以 Link 唯一性保证多 provider 不冲突；
11. 实现 `MemoryBackgroundEntryProvider`，将 Business Day 传入 preparation；缺失昨日正常省略，已存却损坏/超限经 Memory bridge 结束当前 Turn；
12. 扩展 Context pressure recovery：先回收 Phase1 动态项，再回收自动昨日 Memory，不回收 Home core；
13. AppBuilder 独立构建 MemoryEngine，注册 Memory actions/provider/bridge/reranker，并将 MemoryEngine 注入现有 `ProgramMaintenanceRunner`；Loop/App 不复制 eligibility 或 consolidation 流程；
14. 删除 HomeEngine 中 Memory service/property、Home action catalog 中 MEMORY 搜索条目、旧配置、旧 tests/fixtures 假设和旧文件；不留 alias/adapter/deprecation branch；
15. 更新 App 集成测试 root 隔离，必须同时隔离 actual Home、Home runtime、Memory、Session、Workspace 和 archive；
16. 更新项目配置 include 与发布/初始化资产规划；空 Memory root 缺失是空 store，只有 Memory Maintenance 成功写入时创建 `memory/` 与年/月父目录，模块 import、builder、search/recall 不得隐式创建目录。

失败语义：

- 昨日文件缺失是正常 preparation 结果；存在却不可读/超限是 Memory 模块边界失败；
- search 无匹配与 recall 目标不存在是局部 ActionResult；已发现 Memory 文档损坏时 search 整体失败，不返回不完整结果；
- Maintenance 的 Session 缺失/为空、自动目标已存在和模型输出不合规仍用结构化 outcome；原子写、配置、store 或不变量失败经 Memory bridge 进入 Runtime；
- 任何失败不创建半写文件，不改变旧目标，不回滚 Home 或其它 Program work。

验收：

- `tinysoul.home` 对 Memory Link/path/config/search/maintenance 零所有权，`tinysoul.memory` 成为唯一门面；
- 代码、catalog、配置、文档和 tests 中不存在可执行的 `home:memory@...`、`home/memory` 或 `[home.memory]` 兼容路径；
- 每 Turn 的昨日 Background 重建、缺失、损坏、上限与压力逐出均有测试；
- search 的按日候选、候选限制、rerank validator/fallback 与有界 ActionResult 均有测试；
- recall 的精确 Link、完整文档、not-found、超限与 TurnTrace-only 语义均有测试；
- Memory Maintenance 的原 Stage 4/6 行为在新 root/Link/module 上全部回归，并新增 Home/Memory 交叉 Link 校验；
- App 启动提示、scheduler 和人工 Memory 命令继续共享同一 runner，无网络 fake-provider 流程可产生 Memory 并在后续 Turn 通过昨日 Background 或 search/recall 可见。

实施结果：新增 `tinysoul.memory` 单一门面及严格 `MemoryLink`、无只读副作用的 bounded store、独立 `[memory]` 配置、自由结构单日 Maintenance/consolidator、按日 search、完整 recall、昨日 Background provider、Memory Action domain、`memory_search` LLM profile、failure kind 与 Runtime bridge。Memory Maintenance 输出与 Program outcome 使用 `memory:YYYY-MM-DD.md` 和默认顶层 `memory/yyyy/mm/yyyy-mm-dd.md`，同时校验 actual Home top Link、其它日期 Memory Link、缺失引用与自引用。Home parser/layout/search/config/Engine 已删除日期 Memory space、旧路径和 Maintenance service，只通过窄 `actual_top_links()` catalog 协作。

Context 已改为按 Turn Business Day 聚合多 provider 的通用 Background，catalog/entry 显式携带 owner/source/evictable；精确昨日存在时自动加载完整有界非空正文，缺失不回退，空文件/非 UTF-8/超限经 Memory bridge 结束当前 Turn。压力恢复先回收 Phase1 动态项，再回收自动昨日 Memory，Home core 保持不可逐出。AppBuilder 独立装配 MemoryEngine、actions、reranker、provider、bridge 和 ProgramMaintenanceRunner；测试 root 同时隔离 Home、Memory、Session、Workspace 与 archive。单元/集成测试覆盖 Link/path、无副作用空 store、recall、任意 Markdown 结构、空文件/非 UTF-8/超限、按日 search、rerank fallback、昨日重建/缺失/压力、交叉 Link validation、Maintenance/Program 行为和旧 Home Link/path 拒绝。

### 阶段 6.2：自由结构单日 Memory 与边界收口

status: done

优先级：P0

依赖：阶段 6.1

本阶段以 2026-07-14 的最新确认替换 Stage 4/6.1 中“三时间段文档与 period search”实现基线，不改变 Memory 独立 root/Link、昨日 Background、其它日期 TurnTrace、Maintenance 独立性或自动已有目标 skip 语义。

已确认语义：

1. MEMORY 是自由结构的单日 Markdown，不要求上午、下午、晚上或其它固定章节；旧文件只要非空、可读、未超限且是 UTF-8，即可直接读取并在人工重写时作为同日 source；
2. 新 MEMORY 由 LLM 返回单个 Markdown body，框架只确定性增加日期 H1；正文可使用 H2 及以下结构但不得生成第二个 H1；
3. `memory.search` 以日期文档为唯一候选粒度，item 不再携带 period；完整 store 参与流式确定性评分，内存中只保留 `candidate_limit` 个日期候选；
4. Session facts 保持按 Turn 开始时间的稳定顺序并校验属于目标 Business Day，但 Memory 不再对 facts 分段；
5. 自动目标已存在时先验证文件非空、可读、未超限，再于 Session/LLM 前 skipped；人工 Maintenance 将任意既有同日 Markdown 与 Session facts 重新整理并完整覆盖；
6. 完整 actual Home 与其它日期 Memory Link catalog 只用于本地验证；模型只看到从本次 sources 提取、实际存在且受总字符预算限制的 Link hints；
7. 顶层 `memory/` 是默认项目布局；显式绝对 root 是受信任部署/测试覆盖，所有 Link 映射仍严格受配置 root 约束。

实施项：

1. 删除 `MemoryPeriod`、`MemorySections`、固定章节 parser/renderer 和 period search contract；
2. 将 consolidation request/result 改为统一 sources 与单个 body，保留分层 reduce、调用预算、Link validation 和原子替换；
3. 增加 Link hints 总字符预算，禁止完整 catalog 进入模型 message；
4. 将 search candidate/id/item/reranker 改为唯一日期，并以固定候选集合流式扫描完整 store；
5. 让 Background、recall、search 接受任意结构的有界非空 UTF-8 Markdown；
6. 补自由格式旧 Memory 重写、自动可读性 skip、单日 search、真实 ActionResult/TurnTrace 与配置 root 隔离测试；
7. 同步 AGENT、Memory/LLM 设计文档、Action 描述和当前进度。

验收：项目可执行代码与当前设计文档中不再把 period 作为 MEMORY 文档、search 或 LLM 输出契约；模型 message 中 Link hints 有明确硬上限，完整 catalog 仅在进程内用于验证。

实施结果：删除 `MemoryPeriod`、`MemorySections`、固定章节 parser 和 period candidate，Memory store 现将任意结构但非空、可读、上限内的 UTF-8 Markdown 作为合法旧文档。Maintenance 以按时间稳定的 Session facts 和可选同日旧正文构造统一 sources，分层 reduce 后只接收 `content`，框架确定性增加日期 H1；新输出继续校验 H1 所有权、Home/Memory Link、长度和非空。配置新增 `memory.maintenance.link_hints_max_chars`，完整 Link catalog 只保留给本地 validator，模型只接收 source-derived 有效 hints 和有界 feedback。

Search 改为完整 store 流式扫描、每日期一个 candidate，并只在内存保留 `candidate_limit` 个最佳日期；reranker candidate id 直接使用 `memory:YYYY-MM-DD.md`，ActionResult 不再包含 period。自动 Program work 通过 `MemoryEngine.read_day` 验证已有目标后才在 Session 前 skipped；模块自身的 `maintenance_eligible()` 也会读取验证已存在目标，不能把空文件、非 UTF-8 或超限误判为“无需处理”。人工重写接受任意旧 Markdown。新正文 validator 同时拒绝普通或最多三个前导空格的 ATX H1，以及 Setext H1，保持日期 H1 只由框架拥有。真实 search/recall executor 已通过 Phase3/TurnTrace 集成测试，App root 隔离增加 Memory 断言；Context abort 同时清理 Background/provider catalog/session，未使用的 empty provider 已删除。全量 pytest 与 ty 均通过。

### 阶段 7：恢复、观察与端到端加固

status: done

优先级：P1

依赖：阶段 6.2

已确认语义：恢复范围限定为 Python 进程异常和文件操作失败，不承诺 power-loss/fsync durability。Daily started 为 verbose，completed/recovered/failed 为 normal；Home/Memory 的 started、item（仅 Home）与 terminal 为 verbose，Program 继续为每项 Maintenance 保留唯一 normal outcome。“后续 Turn 可见 MEMORY”走两条路径：精确昨日 MEMORY 在每 Turn preparation 自动进入可逐出 Background；其它日期通过 `memory.search`/`memory.recall` 结果进入 TurnTrace。无网络 E2E 使用受控时钟和 typed Program event，不启动真实 scheduler 线程。

实施项：

1. 补 Session move 后、Trash move、active init 后、journal 写失败、final rename 失败和连续跨日恢复；
2. 断言所有 daily crash window 都不移动 Home；
3. 补 Home actual write 后清理前、部分 apply/discard、SKILL_MEMORY 清理失败；
4. 补顶层 Memory 原子写前后中断，并断言 Home 不参与恢复；
5. 发布 `daily.transition.*`、`home.maintenance.*`、`memory.maintenance.*` Observation；
6. payload 只含 day、计数、link/digest 摘要和 outcome，不含正文/reasoning；
7. 建立无网络 E2E：旧日 Turn -> daily archive -> 新日继续使用旧 Home overlay -> Home commit -> Memory 生成 -> 后续 Turn 自动获得昨日 MEMORY -> 更早日期可经 search/recall 召回。

实施结果：Daily 恢复矩阵覆盖初始 journal 写失败、Session move 后 step journal 失败、Trash/Workspace move 中断、active init 后 step journal 失败、final archive rename 失败与恢复后继续下一次跨日；每个窗口都断言 `runtime/home` manifest 与顶层 `memory/` 标记不变。journal 持有的 persisted facts 允许 participant 已移动或 active roots 已初始化但 step 未提交时前滚；空且无 journal 的 pending 可丢弃，已有 participant data 却缺 journal 仍显式失败。该实现保持单进程单写者和跨目录 partial completion 边界，不新增 fsync 或断电事务承诺。

Home 恢复矩阵覆盖 actual apply 后 overlay 清理前中断、部分 review/apply 后失败，以及 `SKILL_MEMORY.md` 清理失败；已处理项通过 runtime/actual 一致性确定性清理，未处理项仍由 active diff 重新 review，不保存 decision。Memory 覆盖原子替换前失败保留旧文件，以及替换完成后调用方观察异常的场景；后者重试时按已存在目标自动 skipped，不重复 consolidation。两项恢复均断言不读写另一所有者的持久根。

Observation 由各业务所有者发布并共享 App 注入的 emitter：Loop Daily 发布 `daily.transition.started/completed/recovered/failed`，Home 发布 `home.maintenance.started/item.resolved/completed/stopped/failed`，Memory 发布 `memory.maintenance.started/skipped/completed/failed`。载荷只含 operation/day/mode/status/link/digest/计数和稳定错误类型，不含正文、diff、reasoning 或绝对路径；emit/enabled 失败继续由 Runtime observation helper 隔离。Program 的 `program.work.completed/failed` 仍是用户 normal 层唯一 Maintenance 结果。

新增无网络 App E2E，以 AppBuilder 注入受控 BusinessClock、关闭 scheduler 并直接投递 typed Home/Memory/Turn/Exit event，贯通旧日 Home mutation Turn、启动 Daily preflight、Session/Workspace/Trash archive、Home commit、Memory consolidation、新日昨日 Background、较早日期 Memory search/recall 和后续回答。测试使用 fake LLM，不访问供应商或网络；Context UserInput 墙钟在测试内绑定同一受控时间源，Memory 的 facts 日期校验保持严格。模块恢复/事件测试、App/Loop/Home/Memory 集成测试与全量 `pytest tests -q` 均通过（仅保留 10 个环境/真实供应商显式 skip），`ty check` 无诊断。

### 阶段 8：HOW 发现、项目初始化与发布闭环

status: done

优先级：P2

依赖：阶段 7

已确认语义：

1. Action Catalog 是框架版本化的只读 package resource，App 直接从已安装的 `tinysoul.action` 包加载；项目配置不暴露 catalog path override，也不把 catalog 复制到新项目；
2. 配置、默认 Home、`.env.example`、`.gitignore` 和项目说明是可编辑项目模板，随 wheel 发布，并由 `tinysoul init [DIRECTORY]` 复制到不存在或为空的目标目录；目标非空时失败，不覆盖现有项目；
3. `init` 不接收 `--provider`。模板中的 provider 全部默认 disabled，用户通过 TOML 与环境变量启用；未配置时 App 启动必须返回清晰配置错误；
4. CLI 保持“无子命令即运行 App”的兼容入口，只新增显式 `init` 命令；
5. Phase1 继续通过 Context-owned `load_background` control tool 按需把选定顶层正文加载到 Background；全部 effective 通用 HOW 的 Link、title、description 在每个 User Turn 自动形成不可逐出的有界 Background catalog，使 Phase1 知道可加载哪些 skill；
6. 通用 `how/<skill>/SKILL.md` 使用 YAML `---` frontmatter 严格保存且只保存非空单行 `title`、`description`。Home 在 actual/runtime effective view、mutation 和启动 reconcile 边界统一校验；单项及总 catalog 都有界，总量超限时显式失败，不静默截断或丢弃 skill；
7. HOW 的 `home.top.search` 复用相同 frontmatter metadata；WHAT/WHY 继续使用 Markdown H1 与首个正文段；`how_domain`/`how_action` 不进入此自动目录；
8. 当前没有真实 shell/script capability，因此删除空 domain 和空 `tinysoul.capabilities` 包。受控 backend mechanism 保留，真实能力和 document conversion 由独立后续计划推进；
9. 完整默认 Home 的业务内容不在本阶段扩写，由独立后续计划统一说明 AGENT、Link、WHAT/WHY/HOW 与示例内容。

实施项：

1. 将内置 Action Catalog 改为 package resource，删除 project catalog path 配置和空 shell/script domain；
2. 为通用 HOW 增加 YAML frontmatter 类型、解析、effective catalog 校验、search 复用与 Context Background metadata projection；
3. 建立 package-owned 可编辑项目模板，默认 provider 全部 disabled；
4. 增加无 provider 参数、拒绝覆盖非空目录的 `tinysoul init [DIRECTORY]`；
5. 补项目 README、package metadata、wheel 内容校验、初始化/未配置失败测试和 fake-provider CLI E2E；
6. 保留真实 provider smoke 为显式 opt-in，并补 App/CLI 装配层 smoke，不能只测试 provider adapter。

实施结果：Action Catalog 已改为 `tinysoul.action` 的只读 package resource，App 在资源上下文内加载并构建不可变 catalog；项目级 `configs/action.toml`、`ActionSettings/catalog_root`、空 shell/script domain 和空 capabilities 包均已删除。subprocess/script backend mechanism 继续保留，但没有对应真实 action 时不进入 Phase1 domain。wheel 测试会检查 catalog 资源存在且空域、旧配置 parser 不进入安装包。

Home 新增严格的 `HomeSkillMetadata` 与 YAML frontmatter parser，使用 PyYAML safe loader，只接受精确 `title`/`description`。启动/reconcile、runtime 恢复、top write/patch、自动 HOW 目录与 Home search 共享该语义；单项和总 catalog 有界，总量溢出在写入前或启动时显式失败。`BackgroundCatalogItem` 允许 provider 投影目录 metadata，Context 每 Turn 自动渲染 `background:catalog:home`，同时保留 `load_background` 对具体顶层正文的按需加载。runtime-only create/modify/tombstone 会进入后续 Turn 的 effective 目录，搜索 HOW 时复用 frontmatter 而非正文 H1。

新增 `tinysoul.assets` 可编辑项目模板与 `ProjectInitializer`。`tinysoul init [DIRECTORY]` 使用同级 staging 安装到不存在或空目标，拒绝文件、symlink 与非空目录；它复制 `tinysoul.toml`、configs、Home、README、`.env.example`、`.gitignore`，并创建空顶层 `memory/`，但不复制 Action Catalog。模板 provider 全部 disabled，且不接收 `--provider`；未配置启动会给出 task 没有 enabled provider model 的清晰错误。CLI 仍保持无子命令即运行 App。

发布验收覆盖 wheel 构建、资源条目、隔离 `--target` 安装和从安装包执行 init；fake-provider E2E 从生成项目启动本地 OpenAI-compatible HTTP server，贯通真实配置、adapter、Phase1、Phase2、Phase3 与 `core.answer`。该测试同时发现并修复供应商 tool call 缺少 TinySoul kind 的问题：`ResponseInterpreter` 现在按当前 `ToolScope` 回填 Control/Action 分类并拒绝冲突。真实 provider App/CLI smoke 已作为显式 opt-in 测试保留。全量 577 项测试通过，其中 11 项真实环境/供应商测试默认 skip；`ty check` 无诊断。

### 阶段 8.1：Canonical Link 与完成态语义加固

status: done

优先级：P1

依赖：阶段 8

已确认语义：

1. Agent、WHAT 和 WHY 顶层 Link 使用相对于各自 Home space 的真实 Markdown 文件路径并保留 `.md`；core 为 `home:agent@AGENT.md`，WHAT 为 `home:what@entity|concept/<path>.md`，WHY 为 `home:why@<path>.md`；
2. WHAT 分类属于 Link 身份，`home.top.write` 不再接收重复的 `what_kind` 参数；entity 与 concept 同名文件是两个不同顶层对象；
3. `memory:YYYY-MM-DD.md` 保留真实叶文件名但继续隐藏物理 `yyyy/mm/` 目录；不提供旧 Link 别名；
4. 通用 `home:how@<skill>` 与 `home:how_domain:`/`home:how_action:` 保留框架 identity；HOW 渐进资源和 Workspace 资源继续保留真实相对路径与扩展名；
5. `memory.search` 保持日粒度候选发现 Action，`memory.recall` 保持精确单日读取 Action；片段级语义检索进入独立能力扩展计划；
6. Maintenance Program failure 只暴露稳定 failure facts，不透传可能包含绝对路径或敏感实现细节的原始异常 message。

实施项：

1. 修改 Home/Memory Link parser、filesystem mapping、Action schema、Memory Link validation 和所有运行时结果；
2. 同步 AGENT、模块设计文档、默认 Home 示例、package template 与测试；
3. 增加 Phase1 自动 HOW metadata catalog、`load_background`、Phase2 正文可见和下一 Turn 清理的集成测试；
4. 为 Program Maintenance failure 增加稳定 `failure_kind`，仅白名单保留 Runtime cause kind，并补路径不泄漏测试；
5. 在默认 Home 计划记录 canonical Link 内容要求，在能力扩展计划记录 Home Backlink 与 Memory 片段检索边界；
6. 运行全量测试、类型检查和 wheel 内容验证；完成后将本计划标记 done，并按分析文档规则增加 `20260713-done-` 文件名前缀。

实施结果：Home 顶层映射已由多候选名称解析收敛为单一确定文件映射。Agent/WHAT/WHY Link 直接携带真实 Markdown 相对路径，WHAT 分类进入 Link 并删除 `what_kind` Action 参数；通用 HOW 与 prompt mount 保留框架 identity。Memory Link 改为 `memory:YYYY-MM-DD.md`，store 路径、Background、search/recall、consolidation Link validation、Action schema 和 Program outcome 已统一，旧 Link 直接拒绝且无兼容别名。源码 Home、package template 中现有示例 Link 与设计文档已同步。

新增 Phase1/Phase2 集成测试，验证全部 HOW 的 Link/title/description 自动进入 metadata catalog、正文不在初始 Phase1 暴露、`load_background` 后正文进入 Phase2，并在下一 User Turn 清除。Program Maintenance failure 不再透传原始异常 message，改为 `ProgramWorkFailureKind`、`error_type` 和白名单 Runtime cause facts；路径泄漏回归测试覆盖 outcome/normal Observation 共用 payload。默认 Home 计划新增 canonical Link 与物理文件表，能力扩展计划新增 Home-owned Backlink 边界、当前 Memory 日候选 search/精确 recall 行为及未来片段检索方案。全量测试 `569 passed, 11 skipped`，其中包含 wheel 内容与隔离安装验证；`ty check` 无诊断。

## 失败语义

继续遵守三层失败模型：

1. 局部结果：无 Home diff、非法 reviewer decision、人工未确认、discard、Memory 输出不合规、目标 Session 不存在、Home/Memory search 无匹配、Memory recall 目标不存在；
2. 模块边界异常：Home overlay/Session archive/Memory 文档损坏、路径不变量破坏、actual Home/MEMORY 无法原子写、effective catalog 或 Memory store 无法解释；
3. Runtime 语义异常：启动失败、结束 User/Maintenance Turn、结束 Program，以及已有 runtime copy/context pressure/workspace restore 恢复原因。

Daily rollover failure 阻止新日 Program work。Home/Memory Maintenance failure 只结束对应 Maintenance work，不新增普通步骤 Runtime reason，不伪装为 User Turn answer，也不回滚另一项任务。

## 代码组织约束

- `AgentHomeEngine` 是 Home 单一门面，只拥有 Home reviewer；`MemoryEngine` 是 Memory 单一门面，拥有 store/search/recall/consolidator；
- `HomeOverlayManager` 只管理 active overlay 与 operation recovery；
- 各模块 `actions.py` 只适配普通 User Turn mutation/search/recall，不执行 Maintenance；
- Loop runner 只调用门面，不解析 overlay/Session JSON；
- AppBuilder 只装配，terminal/scheduler 只发送 event；
- 所有 LLM output、TOML/JSON、日期和外部输入在边界转成明确类型；
- 不引入 Home archive、Settlement alias、空 registry、Memory 旧路径兼容/双读、双写或第二套 apply 流程；
- 文本、diff、Observation、failure 和输出必须有界；
- 仅在职责和生命周期真实独立时新增模块，不因文件行数机械拆分。

## 接受的边界与非目标

- Session/Workspace/Home 继续是单进程单写者，不实现分布式锁或数据库事务；
- Daily rollover 使用 journal 前滚；Home/Memory Maintenance 不持久化执行过程；
- Home 不保留决策审计历史，已处理 diff 从 active overlay 消失；
- archive 的 Session/Workspace/Trash 是历史事实，Home 没有 archive；
- Memory 自动提示与自动 Background 都只看精确昨日，跳过/缺失不保存状态，不回退更早日期；
- 首个 semantic search 不引入向量数据库；
- 不实现多用户、HTTP/WebSocket、企业调度、流式输出或跨设备同步；
- Background Agent 必须通过 Program Maintenance work，不是绕过 Loop 的独立脚本。

## 验收纪律

每个阶段必须同步完成代码、测试、`docs/design/`、`AGENT.md` 当前进度和本文状态。声明完成前运行：

```powershell
python -m pytest tests -q
$env:TINYSOUL_PYTHON='当前设备的 TinySoul python.exe'; .\scripts\typecheck.ps1
```

最终全局验收必须覆盖：

- 跨午夜、连续跨日、程序离线后启动补做和 daily crash windows；
- daily rollover 对 runtime Home 与 actual Home 零写入；
- Home overlay 跨 Turn、跨日、跨重启持续；
- effective top/resource/prompt mount 一致；
- top create/modify/delete、WHAT 分类和 core delete 禁止；
- prompt mount catalog 自动生命周期；
- 所有 effective 通用 HOW 都有合法 YAML frontmatter，其 Link/title/description 每 Turn 自动进入 Background catalog，runtime create/modify/delete 会在后续 Turn 反映；
- HOW metadata 总预算溢出显式失败，不能截断或遗漏 skill；
- SKILL_MEMORY 仅通用 HOW 存在，并在 Home Maintenance 后清空；
- Home apply/discard/部分中断通过 active diff 重算；
- Home 不再接受 `memory` space，Memory 独立 root/config/Link/module 不存在旧路径别名；
- Context-owned Background 可聚合 Home core 与可逐出昨日 Memory，每 Turn 重建且不回退更早日期；
- `memory.search` 只返回日期 Link/有界摘要，`memory.recall` 返回完整有界非空单日 Markdown，两者只进入 TurnTrace；
- `<memory:YYYY-MM-DD.md>` 可提示跨日 recall，Memory Maintenance 验证所有引用的 Home/Memory Link 存在性；
- Memory 只读取指定日期 Session 与可选同日旧 MEMORY；
- 昨日提示不扫描更早日期；
- Home/Memory Maintenance 独立失败；
- normal failure 可见且 MODEL/敏感数据不泄漏；
- scheduler、启动和人工入口共享同一 Program 流程；
- wheel 内含内置 Action Catalog 与可编辑项目模板，不含空 shell/script domain；
- project init 不覆盖非空目录、不要求 provider 参数，未配置 provider 时给出清晰配置错误；
- fake-provider CLI E2E 和显式 opt-in 的真实 provider App/CLI smoke。
