# Maintenance 设计

## 定位

`tinysoul.maintenance` 拥有 TinySoul 的业务日、确定性日切、归档 catalog、到期计算，以及 Archive/Home/Memory 维护任务的计划和编排。Maintenance 与 User Turn 是同级 Program work，但不是另一套 Program：App 的同一个 request queue 将 MaintenanceRequest 分派给唯一 MaintenanceEngine。

Maintenance 分开处理两类工作：

- 不依赖模型的固定处理：业务日 preflight、日切恢复、Session/Workspace/Trash 归档、active roots 初始化、availability/eligibility 计算；
- 需要推理的处理：Home diff 的 accept/reject/rewrite，以及关闭日 Memory consolidation。这两类工作通过独立 Maintenance Turn 使用共用 3-stage Loop。

整个流程自治执行，不需要人工审批，不建立 decision channel，不等待人类输入。手动、Endpoint 和 scheduler 只负责构造 typed request，不能绕过 Engine 直接调用业务模块。

## 目录组织

```text
tinysoul/maintenance/
  engine.py                  # 单一门面、plan 和任务编排
  models.py                  # request/plan/availability/outcome
  config.py                  # timezone/archive/schedule 设置
  schedule.py                # due 与 missed-work 计算
  day.py                     # BusinessDay / BusinessClock
  actions.py                 # per-Turn ActionEngine view
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

Archive/Home/Memory 包不互相读取私有 store。Engine 只依赖它们公开的窄 task/catalog 协议。

## Request 与 Program

`MaintenanceRequest` 包含：

- `scope`: `daily | home | memory`；
- `trigger`: `manual | scheduled`；
- Memory 可选 `target_day` 与 `rebuild_memory`；
- request identity、source 与有界 metadata。

Program 不按 trigger 分叉业务流程。所有 MaintenanceRequest 都串行调用 `MaintenanceEngine.run()`；trigger 只用于审计。User Turn 活跃期间收到的 Maintenance 命令进入 Program queue，在当前 Turn 收束后执行，不成为 `context.input.append`。

手动语法为：

```text
/maintenance
/maintenance daily
/maintenance home
/maintenance memory [YYYY-MM-DD] [--rebuild]
```

Endpoint 使用同一参数语义。scheduler 根据 `[maintenance.schedule]` 每天投递一个 scheduled Daily request。计划时刻之后才启动的进程不追补启动前的 LLM work，只由 Program 发布 availability；计划时刻前已经运行的进程按时投递，运行中跨日休眠则合并为一个当前日 request。scheduler 不保存持久 cursor，不执行模块逻辑，也不等待结果。

## Engine 流程

每次 `run(request)` 在 Engine lock 内执行：

1. 用 BusinessClock 捕获当前 BusinessDay；
2. 调用 Archive preflight，恢复 pending journal 或把旧 active Session/Workspace/Trash 归档并建立新日 roots；
3. 从 authoritative archive catalog、Home pending 和 Memory eligibility 构造 MaintenancePlan；
4. `daily` 运行 Home，并运行所有 eligible closed Memory days；`home` 只运行 Home；`memory` 运行显式目标或所有 eligible closed days；
5. 每个 task 独立形成 completed/skipped/failed outcome；一个 task 失败不回滚已完成 task，也不阻止其它目标；
6. 聚合为 `completed | partial | skipped | failed` MaintenanceOutcome。

Archive preflight 不变量失败是 Program 边界失败，因为在日切完成前不能开始新日 work。Home/Memory task 内异常被收敛为只含稳定 error type 的 task failure，不把正文、reasoning 或绝对路径放入 outcome。

## Archive

Archive 是完全确定性的维护包，不触发 Turn。`DailyLifecycleCoordinator` 使用 `.pending-<operation-id>/transition.json` 记录步骤：Session 归档、Workspace/Trash 归档、新 active roots 初始化、final rename。进程异常后根据 journal 与 participant persisted facts 前滚。

完成目录为：

```text
archive/<timezone-timestamp>/
  transition.json
  session/
  workspace/
  trash/
```

Home 不参与日切或 archive。`ArchiveProjection` 只暴露 BusinessDay、archive root、Session root 和 Workspace root；日期必须来自 transition journal，不能从目录名或“当前日减一”猜测。开放当天不是 closed archive target。

## Home Task

Home task 先让 Home owner 确定性清理 copied/consistent 残留。若没有真实 diff，则 finalize 并移除空 `runtime/home`；否则启动 Home Maintenance Turn。

Home Turn 使用 actual Home Background，加当前 Session 与 Workspace 情景。专用 actions 逐个列出和 inspect snapshot token，然后选择：

- `accept`: runtime 版本提交到 actual；
- `reject`: 保留 actual；
- `rewrite`: 将整理后的完整正文提交到 actual。

每个成功 resolution 都清理对应 overlay record/content。`maintenance.complete` 只有在 Home owner 确认所有 diff 与 SKILL_MEMORY 均已处理时成功；Turn 后 controller 再调用 `finalize_maintenance()`，正常结果是 `runtime/home` 不存在。下次需要 Home 时重新创建 overlay 并从 actual 懒加载。

## Memory Task

Memory target 必须小于当前 BusinessDay且存在 ArchiveProjection。默认任务在目标已有有效 MEMORY 时 skipped；显式 `--rebuild` 才允许重写。

Task 让 Session owner从 archive Session root 生成 facts projection，让 Workspace owner 从 archive Workspace root 生成只读 manifest，并把二者绑定到 `ArchivedMaintenanceContext`。Memory Maintenance Turn 因而能在关闭日的 Session/Workspace 情景中继续梳理，而不是只接收脱离上下文的一段 prompt。

`maintenance.memory.consolidate` 将 Session facts 和 rebuild 时的同日旧 MEMORY 交给 Memory owner；Memory 完成 Link 校验、分层 consolidation、日期 H1 渲染和单文件原子替换。`maintenance.complete` 要求 consolidation 已产生非失败 outcome。

## Turn 与 Action 隔离

User Turn 和 Maintenance Turn 共用 `loop.turn`、`loop.cycle` 与 3-stage phases，但使用独立 Context、prompt guidance、completion detector 和 ActionEngine。

- User ActionEngine 显式排除所有 `maintenance.*`；
- Home Turn 只见通用 inspect 与 Home Maintenance actions；
- Memory Turn 只见通用 inspect 与 Memory Maintenance actions；
- `core.context.inspect`、`core.session.inspect` 是可复用的只读 common actions；
- Maintenance Turn 不见 `core.answer` 或普通 mutation/capability actions；
- Home/Memory 两种 Turn 不见对方 actions。

Maintenance Context 与 User Context 具有相同的 Background/Session/Workspace/TurnTrace/Working 结构。差异是 Background 使用 actual Home，task input/guidance 明确维护目标，Memory task 的 Session/Workspace 来自目标 archive。`maintenance.complete` 是 owner-bound 完成协议，不是普通回答。

## 核心不变量

- 新日 User Turn 只依赖确定性 Archive preflight，不依赖模型成功；
- manual/scheduled 不复制流程或结果类型；
- action catalog 的物理存在不等于对某个 Turn 可见；
- User Turn 永远不能选择或调用 maintenance domain；
- Maintenance task 不能等待审批或阻塞在外部 decision；
- ArchiveProjection 是关闭日定位的唯一跨模块事实；
- Home resolution 后清除对应 runtime diff，全部完成后移除 runtime Home；
- Memory 只由 Memory owner写入，Home/Archive 对 `memory/` 零写入；
- 不建立 settlement、approval、review plan 或 scheduler cursor 持久状态。
