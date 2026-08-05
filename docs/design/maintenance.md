# Maintenance 设计

## 定位

`tinysoul.maintenance` 拥有 TinySoul 的业务时钟、确定性日切、归档 catalog、持久 availability，以及 Archive/Home/Memory 维护任务的编排。Maintenance 与 User Turn 是同级 Program work，但不是另一套 Program：App 的同一个 request queue 将 MaintenanceRequest 分派给唯一 MaintenanceEngine。跨模块共用的 `BusinessDay` 值对象属于 Infra；业务时区和日切策略仍属于 Maintenance。

Maintenance 分开处理两类工作：

- 不依赖模型的固定处理：业务日 preflight、日切恢复、Session/Workspace/Trash 归档、active roots 初始化、availability/eligibility 计算；
- 需要推理的处理：Home diff 的 accept/reject/rewrite，以及关闭日 Memory consolidation。这两类工作通过独立 Maintenance Turn 使用共用 3-stage Loop。

整个流程自治执行，不需要人工审批，不建立 decision channel，不等待人类输入。手动、Endpoint 和 scheduler 只负责构造 typed request，不能绕过 Engine 直接调用业务模块。

## 目录组织

```text
tinysoul/maintenance/
  builder.py                 # 完整 Maintenance branch 装配入口
  engine.py                  # 单一门面、availability 刷新和任务编排
  models.py                  # request/availability/outcome
  availability.py            # 唯一持久提示单
  config.py                  # timezone/archive/runtime/turn/schedule 设置
  schedule.py                # due 计算
  day.py                     # BusinessClock 与时区策略
  actions.py                 # 双 catalog root 的精确 ActionEngine 装配
  context.py                 # actual Home Maintenance Context
  runtime_bridge.py          # Maintenance -> Runtime 单向映射
  resources.py               # Maintenance Action Catalog package resource
  catalog/maintenance/       # maintenance.* actions，User catalog 不包含
  turn/
    entry.py                 # typed task-facing Turn boundary
    runtime.py               # Context-only pressure/trap policy
    completion.py / prompts.py
  errors.py / failures.py
  archive/
    engine.py                # 日切 journal、恢复、archive catalog
  home/
    task.py                  # Home Maintenance Turn task
    actions.py               # list/inspect/accept/reject/rewrite/complete
  memory/
    task.py                  # closed-day projection 与 Turn task
    actions.py               # facts/workspace inspect、consolidate、complete
```

Archive/Home/Memory 包不互相读取私有 store。`MaintenanceBuilder` 独立构造 Home/Memory Context、ActionEngine、trap 和 typed Turn entry；Engine 只依赖公开的窄 task/catalog 协议。`[maintenance.turn]` 拥有 Maintenance cycle budget，`[loop]` 不再包含 maintenance 配置键。

## Request 与 Program

`MaintenanceRequest` 包含：

- `scope`: `daily | home | memory`；
- `trigger`: `manual | scheduled`；
- Memory 必须提供 `target_day`，可选 `rebuild_memory`；
- request identity、source 与有界 metadata。

Program 不按 trigger 分叉业务流程。所有 MaintenanceRequest 都串行调用 `MaintenanceEngine.run()`；trigger 只用于审计。User Turn 活跃期间收到的 Maintenance 命令进入 Program queue，在当前 Turn 收束后执行，不成为 `context.input.append`。

手动语法为：

```text
/maintenance
/maintenance daily
/maintenance home
/maintenance memory YYYY-MM-DD [--rebuild]
```

Endpoint 使用同一参数语义。scheduler 根据 `[maintenance.schedule]` 每天投递一个 scheduled Daily request。计划时刻之后才启动的进程不追补启动前的 LLM work，只由 Program 发布包含 Home 聚合任务和全部 Memory 日期的 availability；计划时刻前已经运行的进程按时投递，运行中跨日休眠则合并为一个当前日 request。scheduler 不保存持久 cursor，不执行模块逻辑，也不等待结果。

## Engine 流程

每次 `run(request)` 在 Engine lock 内执行：

1. 用 BusinessClock 捕获当前 BusinessDay；
2. 调用 Archive preflight，恢复 pending journal 或把旧 active Session/Workspace/Trash 归档并建立新日 roots；
3. 若本次形成或恢复 Archive，只校验该关闭日的 Session facts 与 MEMORY，并增量登记 Memory 待办；随后校验既有日期、重算 Home 计数并原子写入 availability；
4. `daily` 运行 Home，并且只在昨日位于 availability 时运行该日一个 Memory task；更早的待办保持不变；`home` 只运行 Home；`memory` 只运行请求中的明确目标；
5. 每个 task 独立形成 completed/skipped/failed outcome；明确的 task failure 不回滚已完成 task，也不阻止其它目标，未知异常和 Runtime transfer 传播；
6. 完成后再次刷新 availability，并聚合为 `completed | partial | skipped | failed` MaintenanceOutcome。

Archive preflight 不变量失败是 Program 边界失败，因为在日切完成前不能开始新日 work。Home/Memory task 内异常被收敛为只含稳定 error type 的 task failure，不把正文、reasoning 或绝对路径放入 outcome。

## Availability

Maintenance 在 module-owned runtime root 原子保存唯一 `availability.json`。它包含本次检查的 Business Day、去重排序的全部 Memory 待办日期和当前 Home diff/SKILL_MEMORY 计数。Memory 列表只在 Archive 完成或恢复时增量加入日期，在有效 MEMORY 已存在时删除；Home 状态每次从 owner 重算，不建立 Home task journal。展示层把 Home pending 计为至多一个聚合任务，把每个 Memory 日期计为一个独立任务。

该投影是前端提示的唯一事实来源，但不是业务提交依据。Memory task 执行前仍解析对应 ArchiveProjection 并调用 Memory owner eligibility；Home task 仍由 Home owner重新检查 diff。文件缺失表示尚未完成启动刷新，文件损坏或与 Archive 不变量冲突必须失败，不能解释为空提示单。

这种增量列表同时覆盖多日停机和失败重试：历史欠账由列表保留，新增欠账来自本次 Archive，已完成项由有效 MEMORY 幂等清理。因此正常路径既不扫描所有 Archive，也不把“昨日”当作唯一可能目标。

## Archive

Archive 是完全确定性的维护包，不触发 Turn。`DailyLifecycleCoordinator` 使用 `.pending-<operation-id>/transition.json` 记录步骤：Session 归档、Workspace/Trash 归档、新 active roots 初始化、catalog entry 写入和 final rename。`archive/catalog.json` 是按 BusinessDay 定位归档目录的严格索引，归档完成时原子更新；进程异常后根据 journal 与 participant persisted facts 前滚，不通过扫描全部已关闭日恢复索引。

完成目录为：

```text
archive/catalog.json        # BusinessDay -> finalized archive name
archive/<timezone-timestamp>/
  transition.json
  session/
  workspace/
  trash/
```

Home 不参与日切或 archive。`ArchiveProjection` 只暴露 BusinessDay、archive root、Session root 和 Workspace root；日期必须来自 transition journal，不能从目录名或“当前日减一”猜测。开放当天不是 closed archive target。

## Home Task

Home task 先通过 Home owner 的中性 `review_pending()` / `review_snapshot()` 能力确定性清理 copied/consistent 残留。若没有真实 diff 或 skill review，则调用 `remove_resolved_overlay()` 移除空 `runtime/home`；否则启动 Home Maintenance Turn。

Home Turn 使用 actual Home Background，加当前 Session 与 Workspace 情景。专用 actions 逐个列出和 inspect snapshot token，然后选择：

- `accept`: runtime 版本提交到 actual；
- `reject`: 保留 actual；
- `rewrite`: 将整理后的完整正文提交到 actual。

每个成功 resolution 都通过 `resolve_review()` 清理对应 overlay record/content。`SKILL_MEMORY.md` 是独立的 `skill_review`：`list/inspect` 暴露 actual skill 与临时记忆，只有 inspect 后才能 `reject` 或 `rewrite`；`accept` 对该 review 明确失败。skill rewrite 在写 actual 前重新校验 frontmatter。`maintenance.complete` 只有在 Home owner 确认所有 review 均已处理时成功；Turn 后 controller 再调用 `remove_resolved_overlay()`，正常结果是 `runtime/home` 不存在。

## Memory Task

Memory target 必须小于当前 BusinessDay且存在 ArchiveProjection。默认任务在目标已有有效 MEMORY 时 skipped；显式 `--rebuild` 才允许重写。

Task 让 Session owner从 archive Session root 生成 facts projection，让 Workspace owner 从 archive Workspace root 生成只读 manifest，并把二者绑定到 `ArchivedMemoryMaintenanceContext`。绑定同时校验 `session.day == target_day`、`workspace.day == str(target_day)`（若存在）和 preparation request 的 `business_day == target_day`。Memory Maintenance Turn 因而能在关闭日的 Session/Workspace 情景中继续梳理，而不是只接收脱离上下文的一段 prompt。

`maintenance.memory.consolidate` 将 Session facts 和 rebuild 时的同日旧 MEMORY 交给 Memory owner 的 `consolidate()`；Memory 以 `[memory.consolidation]` 预算完成 Link 校验、分层 consolidation、日期 H1 渲染和单文件原子替换，但不知道 Maintenance request、scheduler 或 Turn。`maintenance.complete` 要求 consolidation 已产生非失败 outcome。

## Turn 与 Action 隔离

User Turn 和 Maintenance Turn 共用 owner-neutral `loop` kernel，但 profile 分别归 `loop.user` 与 `maintenance.turn`。Maintenance 的 Home/Memory profile 又分别使用独立 Context、trap、prompt guidance、completion detector 和 ActionEngine。

- User ActionEngine 只加载 `tinysoul.action` catalog，物理上不存在 `maintenance.*`；
- Home Turn 只见通用 inspect 与 Home Maintenance actions；
- Memory Turn 只见通用 inspect 与 Memory Maintenance actions；
- `core.context.inspect`、`core.session.inspect` 是可复用的只读 common actions；
- Maintenance Turn 不见 `core.answer` 或普通 mutation/capability actions；
- Home/Memory 两种 Turn 不见对方 actions。

Maintenance Context 与 User Context 具有相同的 Background/Session/Workspace/TurnTrace/Working 结构。差异是 Background 使用 actual Home，task input/guidance 明确维护目标，Memory task 的 Session/Workspace 来自目标 archive。`maintenance.complete` 是 owner-bound 完成协议，不是普通回答。

## 核心不变量

- 新日 User Turn 只依赖确定性 Archive preflight，不依赖模型成功；
- manual/scheduled 不复制流程或结果类型；
- manual/scheduled Daily 都只选择当前 Maintenance BusinessDay 的昨日 Memory，不自动消费更早欠账；
- Memory scope 必须携带明确 target day，一个 request 至多运行一个 Memory Turn；
- `MaintenancePlan` 不是领域协议；Engine 直接从 typed request 与 availability 快照选择任务；
- MaintenanceEngine 不伪造没有 RuntimeModuleRunner owner 的 `MODULE` frame；Program scope 由 App 传入，真正的 Module frame 只由可重放的 RuntimeModuleRunner 建立；
- Event 只通知 availability 失效，Endpoint GET 才交付持久提示单；
- Maintenance catalog 只属于 `tinysoul.maintenance` package data，通用 Action/User catalog 不认识它；
- Maintenance Context pressure 不得调用 active Workspace cleanup、trash restore 或 Home runtime copy；
- User Turn 永远不能选择或调用 maintenance domain；
- Maintenance task 不能等待审批或阻塞在外部 decision；
- ArchiveProjection 是关闭日定位的唯一跨模块事实；
- Home resolution 后清除对应 runtime diff，全部完成后移除 runtime Home；
- Memory 只由 Memory owner写入，Home/Archive 对 `memory/` 零写入；
- 不建立 settlement、approval、review plan 或 scheduler cursor 持久状态。
