# 20260713 Agent Home / Daily Lifecycle Execution Plan

## 状态

status: in_progress

本文是 Agent Home、Daily Lifecycle 和 Maintenance 的唯一执行规划，统一取代此前 followup plan 与 semantic audit。规划以当前 `AGENT.md` 和 `docs/design/` 为约束，只保留已经确认的核心语义；旧的 Home daily archive、archived Home workset、Settlement root、持久 review/plan/apply 状态机、MEMORY runtime candidate 和 HOW usage Session provenance 均不属于目标设计。

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
  -> Memory Maintenance 完整重写日期 MEMORY
```

核心原则：

1. Session、Workspace 和 Trash 按 Business Day 强制物理归档；Home 不参与日切或 archive；
2. `runtime/home` 跨 Turn、跨日、跨重启保留，是唯一尚未提交的 Home 事实，不建立第二份 workset/store；
3. Agent 只看 `home:` Link 与 effective 内容，不感知 actual/runtime 分层；
4. 普通 User Turn 只修改 runtime Home；actual 非 MEMORY 内容只由 Home Maintenance 修改；
5. MEMORY 在 User Turn 中只读 actual Home，不复制到 runtime；actual MEMORY 只由 Memory Maintenance 写入；
6. Home Maintenance 与 Memory Maintenance 是可独立触发的 Program work，没有共同 plan 或共同提交边界；
7. Runtime 只提供运行位置、Trap、Signal 与 Observation，不保存 Maintenance 业务状态；
8. App/scheduler/terminal 只产生 typed Program event，不直接 diff、review 或写 Home。

## 当前架构与代码进度

| 模块 | 当前状态 | 已实现能力 | 与目标设计的差距 |
| --- | --- | --- | --- |
| Infra | done | 配置、JSON、原子文件、digest、有界读、路径约束 | 复用现有能力。 |
| Runtime | done | Program/Turn/Cycle/Phase/Module frame、Trap、Signal、Observation | Maintenance 复用同级 Turn/Module frame，不新增状态系统。 |
| LLM | done for Maintenance tasks | provider-neutral Task、模型链、输出解释、JSON-only `home_maintenance` 与 `memory_maintenance` profile | Stage 5 search profile 在搜索语义确认后定义。 |
| Action | done for current User Turn scope | 域选择、调用归一化、批次/backend/result、top/prompt mount catalog 与 executor、只读 catalog identities | Maintenance 不作为普通 Action。 |
| Context | done for User Turn | MessageStack、Background/Working/Trace、信号批次和压力恢复 | 保持每 Turn 重建 Home Background；不持有 Maintenance 状态。 |
| Session | done for lifecycle and Memory projection | 不可变 Turn record、summary、orphan reconciliation、日归档、archive snapshot、递归 Summary 的 Memory facts projection | Program 尚未按日期定位并调用 projection。 |
| Workspace | done for active lifecycle | 当日资源、Manifest、Trash、日归档 | 从目标日切看已基本闭合，不参与 Maintenance。 |
| Loop | in_progress | User Turn、显式 BusinessDay、只含 Session/Workspace/Trash 的可恢复 rollover、Session archive 定位 | 增加两个独立 Maintenance work、scheduler 与启动提醒。 |
| Agent Home | in_progress | Link、动态 effective Background、schema v2 跨日 overlay、resource/top/prompt mount mutation、Catalog mount reconcile、SKILL_MEMORY、无持久状态 Home Maintenance、三段式 Memory Maintenance | 增加 top search，并由 Stage 6 接入两个 Maintenance Program work。 |
| App | in_progress | Builder、CLI、输入分发、输出路由 | 增加启动 rollover/reminder、typed Maintenance command 和内置 scheduler。 |
| Capabilities/发布 | pending | backend mechanism 已有，真实 capability 和项目模板不足 | 在核心生命周期闭环后补齐。 |

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
  memory/
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
- `DOMAIN_MEMORY.md`、`ACTION_MEMORY.md` 或其它平行 skill memory；
- memory candidate store 或 `home.memory.append` action。

## User Turn 处理流程

1. Program 在 work lock 内捕获唯一 aware time 与 `BusinessDay`；
2. `DailyLifecycleCoordinator.ensure_active_day` 只校验/归档 Session 与 Workspace/Trash；
3. Context `begin_turn` 清空上一 Turn 的 Home/Session Background 与 Turn 内状态；
4. Home provider 从 current effective Home 重建默认 core/catalog；
5. Session 投影当前 Business Day 历史，Workspace reconcile 并投影 Manifest；
6. Phase1/2/3 完成语境、行动选择和行动执行；
7. `core.answer` 经 TurnOutput Trap 收束；
8. Session 幂等提交不可变 Turn record；
9. 只有 completion pipeline 成功才发布 answered output。

Home Background 与 Phase1 加载项是 Turn 内状态；runtime Home 文件与 overlay record 是跨 Turn 持久事实。二者不能混为同一层。

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

日切是确定性物理过程，不调用 LLM，不检查 MEMORY，不触发 Home commit。程序运行时由内置 scheduler 在日界投递触发；程序未运行时由启动或下一项 work 前的 preflight 恢复并补做。跨午夜 User Turn 归属开始日，完成旧日 Session 提交后再在下一 work 边界日切。

## Effective Home 设计

### 读取规则

所有非 MEMORY Home Link 使用同一 effective 规则：

```text
runtime override
  -> runtime tombstone hides actual
  -> actual Home fallback
```

top catalog、top read、Background loader、progressive resource read、domain/action prompt mount 和 top search 都必须复用同一 Home-owned lookup，不能各自做 source-first 判断。

MEMORY 是唯一旁路：只读 actual `home/memory/yyyy/mm/yyyy-mm-dd.md`，不建立 overlay record。

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

- 只接受非 MEMORY `HomeTopLink`；
- 允许在 runtime 创建不存在的顶层内容；
- 新 WHAT 必须显式指定 `entity` 或 `concept`，分类决定物理路径但不泄漏到稳定 Link；
- `home:agent@core` 允许 write/patch，禁止 delete；
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
8. `home:agent@core` delete 在进入 reviewer 前即为非法状态。

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
+ optional existing home/memory/yyyy/mm/yyyy-mm-dd.md
-> complete replacement home/memory/yyyy/mm/yyyy-mm-dd.md
```

规则：

- Session 通过自己的只读 archive query 门面提供专用 Memory facts projection；该 projection 按需递归解析已提交 Summary 图，交付可达 Turn 的有界事实，不向 Home 暴露 Session store 或 archive 文件结构，也不把 Summary 与其子 Turn 重复作为事实；
- Turn 以配置业务时区中的开始时间归入固定时间段：上午 `[00:00, 12:00)`、下午 `[12:00, 18:00)`、晚上 `[18:00, 24:00)`；跨时间段 Turn 整体归入开始时所在段；
- Session archive 不存在或 projection 不含 Turn facts 时返回 `skipped`，不创建、不覆盖也不删除同日 MEMORY；
- 目标不存在时，只使用同日 Session；
- 目标存在时，只额外读取同日期旧 MEMORY；
- 不读取其它日期 MEMORY、Workspace、active Home diff 或 `SKILL_MEMORY.md`；
- Session facts 与同日旧 MEMORY 按时间段执行有界、分层 consolidation，不静默截断；超过总事实、总字符或最大调用次数硬上限时失败并保持旧文件不变；
- consolidator 使用严格 JSON object 输出上午、下午、晚上三个 Markdown body；Home renderer 负责固定日期标题、三个中文时间段标题和最终 Markdown；
- MEMORY 中只允许指向当前 actual Home 中既存顶层内容的稳定 `HomeTopLink`；不存在、非顶层或语法非法的 Link 必须作为有界模型反馈进入重新生成，重试耗尽后失败；
- 输出是完整重写，不 append；
- 目标使用单文件原子替换，失败保持旧文件不变；
- stable Link 始终是 `home:memory@yyyy-mm-dd`。

### 自动提示

启动时只检查配置业务时区中的昨日：

```text
昨日 Session archive 存在且 projection 含 Turn facts
AND 昨日 MEMORY 不存在
-> 提示 Memory Maintenance
```

不扫描更早日期，不持久化 skipped 状态。因此同一业务日内重启仍可能再次提示；该日期不再是昨日后，不再自动提示。人工命令仍可指定任意存在 Session archive 的日期，也可显式重写已有同日 MEMORY。

## Program、Scheduler 与输入边界

Program 增加两个独立 work kind：

```text
home_maintenance
memory_maintenance(target_day)
```

二者拥有独立 outcome，不组成共同事务。建议稳定 outcome：

```text
HomeMaintenanceOutcome
  completed | stopped | failed

MemoryMaintenanceOutcome
  completed | skipped | failed
```

outcome 只存在于当次运行结果与 Observation，不持久化。

Home outcome 与当前 Home-owned service 语义一致：`completed` 表示所有当次可 review change 已处理完成，无 diff 也属于完成；`stopped` 表示人工 decision provider 在某个未确认项前终止，已确认项保持结果、剩余 diff 留在 overlay；`failed` 表示 review 或模块边界失败，已完成项不回滚。`needs_confirmation` 是 App decision channel 等待输入时的瞬时交互状态，不是最终 outcome；未触发 Home Maintenance 也不由 Home service 构造 `skipped` outcome。

入口规则：

- scheduler 是 App-owned InputSource，只投递 Program event；
- scheduler 在日界触发 daily rollover，并在配置夜间时点触发自动 Home/Memory Maintenance；
- 启动先补做 daily rollover，再提示 active Home diff 与昨日缺失 MEMORY；
- Home 与 Memory 可以由独立人工指令触发；
- 人工 Home 使用专用 decision channel 逐项确认，自动 Home 使用 Agent 全自动 decision；普通输入继续留在 Program queue；
- CLI/terminal 不直接遍历 archive、解析 overlay 或写 Home；
- Maintenance 执行期间不接受 append input，新输入留在 Program queue。

## 模块所有权

### Agent Home

- effective lookup、runtime mutation 与 overlay recovery；
- top/resource/prompt mount Link 到路径的映射；
- prompt mount catalog reconciliation；
- SKILL_MEMORY lifecycle；
- Home reviewer/apply/cleanup；
- MEMORY 日期映射与 Memory consolidator。

### Session

- active Turn/summary 不可变事实；
- daily archive；
- 按 Business Day 只读查询 archive；
- 不解释 MEMORY 文档，也不写 Agent Home。

### Workspace

- active Workspace/Trash 与 daily archive；
- 不参与 Home/Memory Maintenance。

### Loop

- daily rollover 只编排 Session/Workspace/Trash；
- Program work lock 和 Maintenance runner；
- typed work/outcome 与 Observation；
- 不解析 Home overlay、Session store 或 MEMORY 正文。

### App

- startup lifecycle、terminal command、scheduler 和 event dispatch；
- 注入 Home/Session/Loop 门面；
- 不实现 diff、review、consolidation 或文件操作。

### Runtime、Context、Action、LLM

- Runtime 只提供控制边界；
- Context 每 User Turn 重建 Background，不持有 Maintenance 状态；
- Action 暴露普通 User Turn mutation tools，不执行 Maintenance；
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
       -> 阶段 7 恢复、观察与 E2E
            -> 阶段 8 实际能力与发布
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

优先级：P0

依赖：阶段 1

实施项：

1. Session 提供专用 Memory facts projection，按需递归 Summary 图并按 Turn 开始时间输出可达叶子事实；
2. Home consolidator 按上午、下午、晚上分组并执行有界分层 consolidation；
3. 使用严格 JSON object 承载三个时间段 Markdown body，由 Home 确定性渲染完整日期文档；
4. 目标缺失时使用 Session，目标存在时额外读取同日期旧 MEMORY；
5. 对模型输出中的顶层 Link 做 actual Home 存在性校验，以有界反馈重试非法输出；
6. Session 缺失或为空时 `skipped` 且对目标文件零写入；
7. 原子完整写入年月分层日期路径，拒绝其它日期 MEMORY、Workspace、runtime Home 输入；
8. 提供昨日 eligibility 所需的模块查询但不保存 skip，跨模块提示编排仍归阶段 6；
9. 增加递归 Summary、三个时间段、空/缺失/长 Session、旧 MEMORY 重写、非法输出与 Link、原子失败和显式旧日期测试。

验收：指定日期非空 Session 稳定映射唯一三段式 MEMORY；空或缺失 Session 不写文件；失败不改变旧文件；自动提示不扫描更早日期。

实施结果：Session 新增 `SessionMemoryFactsProjection`，在只读 archive snapshot 校验后按需递归 Summary 图，去重并按 Turn 开始时间交付叶子事实；projection 不包含 raw trace/reasoning 或 store 路径。Home 新增 `MemoryMaintenanceService` 与独立 `LLMMemoryConsolidator`，按业务时区把 facts 和同日旧 MEMORY 分入上午、下午、晚上，以配置字符/调用预算执行分层 reduce，再严格接收三个 Markdown body 并确定性渲染日期文档。输出中的 `<home:space@name>` 只允许指向 actual Home 既存顶层 Link，非法 Link 进入有界最终生成反馈；空/缺失 Session 分别返回非持久 skip reason，超限/非法输出在原子写前失败，成功只原子替换 `home/memory/yyyy/mm/yyyy-mm-dd.md`。新增 `memory_maintenance` JSON-only profile、嵌套 Home Memory 配置、eligibility 查询和定向测试；Program event、昨日启动提示和 scheduler 装配仍归阶段 6。

### 阶段 5：Home Top Search 与真实 Home 内容

status: pending

优先级：P1

依赖：阶段 2

实施前必须向用户确认：search 是否包含 `agent` space；标题与短摘要的权威来源；确定性候选评分、候选上限与 `top_k`；LLM rerank 失败时的回退结果；首批实际 WHAT/WHY/HOW 文件清单与内容验收。未确认前不得在实现中自行选择。

实施项：

1. 基于 effective catalog 构造 link、space、标题、短摘要、digest 和有界 searchable prefix；
2. `home.top.search` 先确定性限制候选，再用现有 LLM task rerank；
3. validator 只接受候选内 link；
4. search 不物化全部 runtime copy、不自动加载 Background、不返回完整正文；
5. MEMORY 使用稳定日期 Link，不暴露年月路径；
6. 补实际 WHAT/WHY/HOW 内容与 SKILL_MEMORY 使用规约；
7. 测试 runtime-only top、tombstone、Home Maintenance 后内容和预算。

### 阶段 6：Program、App 与 Scheduler

status: pending

优先级：P1

依赖：阶段 3、阶段 4

实施前必须向用户确认：daily rollover 是否使用独立 typed wake-up event；scheduler 的日界/维护时点、Memory 目标日期、同刻事件顺序与漏调度行为；Maintenance 指令在活跃 User Turn 中排队还是 append；人工 apply/discard/stop/EOF 与普通终端输入的 decision channel 分流；启动提示是非阻塞提示还是显式选择流程。未确认前不得在实现中自行选择。

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

### 阶段 7：恢复、观察与端到端加固

status: pending

优先级：P1

依赖：阶段 5、阶段 6

实施前必须向用户确认：Observation 的精确事件名、level、触发点和 payload schema；E2E 中“后续 Turn 可见 MEMORY”是指通过 search/read 可发现，还是默认自动进入 Background。未确认前不得在实现中自行选择。

实施项：

1. 补 Session move 后、Trash move、active init 后、journal 写失败、final rename 失败和连续跨日恢复；
2. 断言所有 daily crash window 都不移动 Home；
3. 补 Home actual write 后清理前、部分 apply/discard、SKILL_MEMORY 清理失败；
4. 补 Memory 原子写前后中断；
5. 发布 `daily.transition.*`、`home.maintenance.*`、`memory.maintenance.*` Observation；
6. payload 只含 day、计数、link/digest 摘要和 outcome，不含正文/reasoning；
7. 建立无网络 E2E：旧日 Turn -> daily archive -> 新日继续使用旧 Home overlay -> Home commit -> Memory 生成 -> 后续 Turn 可见。

### 阶段 8：实际能力与发布闭环

status: pending

优先级：P2

依赖：核心生命周期完成

实施项：

1. 增加受控 subprocess/script action；
2. 增加 document conversion capability；
3. 只在存在真实 action 时保留 shell/script domain；
4. 将 catalog、默认 Home 和配置模板作为 package data；
5. 增加项目初始化入口；
6. 补 README、wheel、初始化、fake-provider CLI E2E 和真实 provider smoke。

## 失败语义

继续遵守三层失败模型：

1. 局部结果：无 Home diff、非法 reviewer decision、人工未确认、discard、Memory 输出不合规、目标 Session 不存在、search 无匹配；
2. 模块边界异常：Home overlay/Session archive 损坏、路径不变量破坏、actual/MEMORY 无法原子写、effective catalog 无法解释；
3. Runtime 语义异常：启动失败、结束 User/Maintenance Turn、结束 Program，以及已有 runtime copy/context pressure/workspace restore 恢复原因。

Daily rollover failure 阻止新日 Program work。Home/Memory Maintenance failure 只结束对应 Maintenance work，不新增普通步骤 Runtime reason，不伪装为 User Turn answer，也不回滚另一项任务。

## 代码组织约束

- `AgentHomeEngine` 是 Home 单一门面；reviewer/consolidator 是 Home-owned 服务；
- `HomeOverlayManager` 只管理 active overlay 与 operation recovery；
- `actions.py` 只适配普通 User Turn mutation，不执行 Maintenance；
- Loop runner 只调用门面，不解析 overlay/Session JSON；
- AppBuilder 只装配，terminal/scheduler 只发送 event；
- 所有 LLM output、TOML/JSON、日期和外部输入在边界转成明确类型；
- 不引入 Home archive、Settlement alias、空 registry、双写或第二套 apply 流程；
- 文本、diff、Observation、failure 和输出必须有界；
- 仅在职责和生命周期真实独立时新增模块，不因文件行数机械拆分。

## 接受的边界与非目标

- Session/Workspace/Home 继续是单进程单写者，不实现分布式锁或数据库事务；
- Daily rollover 使用 journal 前滚；Home/Memory Maintenance 不持久化执行过程；
- Home 不保留决策审计历史，已处理 diff 从 active overlay 消失；
- archive 的 Session/Workspace/Trash 是历史事实，Home 没有 archive；
- Memory 自动提示只看昨日，跳过不保存状态；
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
- SKILL_MEMORY 仅通用 HOW 存在，并在 Home Maintenance 后清空；
- Home apply/discard/部分中断通过 active diff 重算；
- Memory 只读取指定日期 Session 与可选同日旧 MEMORY；
- 昨日提示不扫描更早日期；
- Home/Memory Maintenance 独立失败；
- normal failure 可见且 MODEL/敏感数据不泄漏；
- scheduler、启动和人工入口共享同一 Program 流程；
- wheel/project init/fake-provider E2E 和真实 provider smoke。
