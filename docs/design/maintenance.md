# Maintenance 设计

## 定位

`tinysoul.maintenance` 拥有业务时钟、确定性日切、归档 catalog、持久 availability，以及 Home/Memory Maintenance Turn 的编排。Maintenance 与 User Turn 是同级 Program work，共用同一个 request queue 和 Loop kernel；它不是第二套 Program，也不把维护结果写入 User Session。

工作分为两类：

- 确定性工作：preflight、pending 日切恢复、Session/活动 Memory/Workspace/Trash 归档、新日 roots 初始化、availability 计算；
- 模型工作：Home review 和关闭日 Memory 维护，通过各自的 Context、Action surface 和完成协议执行。

手动命令、Endpoint 和 scheduler 只能构造 typed request，不能直接调用 owner store。维护自治执行，不建立审批 channel 或持久 plan。

## Request 与触发

`MaintenanceRequest` 包含 scope `daily | home | memory`、trigger `manual | scheduled`、可选明确 target、request/source identity 和有界 metadata。Memory scope 必须提供 `target_day`；项目不存在 `rebuild_memory` 字段。

手动语法：

```text
/maintenance
/maintenance daily
/maintenance home
/maintenance memory YYYY-MM-DD
```

`daily` 运行 Home，并在 availability 中前一日可维护时运行该日 Memory；`home` 只运行 Home；`memory` 始终走显式目标路径，即使目标 daily 已存在也可以复查 daily 与持久知识。

`MaintenanceSchedule` 每天只产生一个 scheduled Daily request。进程在计划时刻前已经运行时会按时投递；启动晚于当日时刻不 catch up。scheduler 不保存业务 cursor、不执行 owner 逻辑、不等待任务结果。

自动与手动 Memory 在触发后调用同一个 `MemoryMaintenanceTask.run()`。差异只在 eligibility：自动路径使用 `if_absent=true`，目标 daily 已存在即不登记、不重复提示；显式路径使用 `if_absent=false`，daily 是否存在不决定能否维护。

## Engine 流程

`MaintenanceEngine.run()` 在串行 lock 中：

1. 调用 `preflight()` 恢复 Memory transaction 和日切，捕获当前 Business Day；
2. 对本次新形成或恢复的 Archive 增量更新 availability，并重算 Home pending；
3. 根据 scope 选择 Home 和至多一个 Memory target；
4. 每个 task 形成 completed/skipped/failed outcome；已知 owner/task failure 收敛为稳定 error type，未知异常和 Runtime transfer 传播；
5. 再次刷新 availability并聚合 MaintenanceOutcome。

`preflight()` 在启动时也执行，但只恢复确定性状态、保存 availability 和发提示，不运行 LLM。启动不扫描全部历史 Archive；尚未完成的旧项由已有 availability 跨重启保留，新项来自本次 Archive。

## Availability

`runtime/maintenance/availability.json` 是前端和终端提示的唯一持久投影，包含 checked day、Home 计数和去重的 Memory 日期列表。它不是提交依据，task 执行前仍向 Archive、Session 和 Memory owner 重新检查。

Memory 自动登记要求：

- 目标日有 authoritative ArchiveProjection；
- 目标 daily 不存在；
- 归档 Session 与 Session root 内的 `Memory.md` 均存在且有效；
- Session facts 或活动 Memory 正文至少一项非空。

缺失 source 或 source 全空表示 not-ready，不登记；文件存在但损坏是 invariant failure。daily 已存在时先停止自动 eligibility 检查，避免完成后因归档资料变化重新提示。显式 Memory request 不依赖 availability。

## Daily Lifecycle

`DailyLifecycleCoordinator` 通过 read/write lease 协调活动日访问和排他 rollover。参与者为 Session、活动 Memory、Workspace：

```text
initialize: Session root -> Session/Memory.md -> Workspace
archive:    validate Memory.md -> Session (including Memory.md) -> Workspace/Trash
new day:    Session root -> empty Session/Memory.md -> Workspace
```

pending transition 使用 `.pending-<operation-id>/transition.json` 记录 Session archived、Workspace archived、active initialized 三个可恢复步骤；完成后写 archive catalog 并 rename 为最终时间戳目录。恢复对归档前后的 `Memory.md` 重复执行 owner 校验，不能把缺失或错日活动记忆归档为有效 source。

完成布局：

```text
archive/catalog.json
archive/<timestamp>/
  transition.json
  session/
    Memory.md
    manifest.json
    turns/...
  workspace/
  trash/
```

Home 和持久 `memory/` 不参与 rollover 或 archive。`ArchiveProjection` 只公开目标 Business Day、archive root、Session root 和 Workspace root。

## Home Task

Home task 使用 actual Home Background 和当前 `memory:current + optional latest`，并装配当前 Session/Workspace 情景。专用 actions 先 list/inspect snapshot token，再 accept、reject 或 rewrite。`SKILL_MEMORY.md` review 必须 inspect 后 reject/rewrite，不能直接 accept。`maintenance.complete` 只有 Home owner 确认所有 review 解决后成功，完成后移除已经清空的 runtime Home overlay。

## Memory Task

Memory target 必须是关闭日并具有 ArchiveProjection。Task 通过 owner API检查 Session archive 和归档 `Memory.md`；缺失或两份 source 都为空返回 typed skipped，存在但损坏则失败。

`ArchivedMemoryMaintenanceContext` 精确绑定：

- target-day Session archive view；
- target-day read-only Workspace archive view；
- target-day archived active Memory snapshot；
- Context Background 的 `memory:target + optional latest`。

`MemoryMaintenanceActionController` 保存 Turn-scoped source、draft、inspection refs、activated links、preview revision 和 commit outcome。它提供 source/Workspace inspect、持久 Memory inspect/recall、create/rewrite/redirect staging、daily composition/staging、preview、commit 和 complete。新建必须先 query inspect；修改与迁移必须先 exact recall 并复验 digest。existing daily 是复查输入，daily 只能 create、replace 或 unchanged。

Controller 把所有知识变化、activity 更新和 daily 组成一个 Memory changeset。Memory owner 统一校验引用、status、redirect、日期和 CAS，以可恢复事务提交，daily 最后写入。Maintenance task 不读取或拼接 Memory 私有路径。

## Context 与 Action 隔离

User、Home Maintenance、Memory Maintenance 共用 Context/Loop 构造，但拥有不同 provider 和 Action surface：

- User ActionEngine 物理上不包含 `maintenance.*`；
- Home Turn 只见 common inspect 和 Home actions；
- Memory Turn 只见 common inspect 和 Memory actions；
- Home 使用 actual Home、current/latest 与当前 Session/Workspace；
- Memory 使用 actual Home、target/latest 与目标 Archive Session/Workspace；
- Maintenance 不见 `core.answer` 或普通 capability mutation；
- `maintenance.complete` 是 owner-bound 完成协议，不是用户回答。

精确 Action surface 先从 configured catalog 选择 Turn 所需 identity，再与 Action activation 和 runtime
support 求交。复用的 `core.context.inspect`、`core.session.inspect` 遵守项目 Action policy；Maintenance
package 自有 Action 使用 package Domain default，并且不进入 User Action 设置页。

## 失败与观察

Archive preflight 失败阻止新日 work。可修正 Action 参数和 stale source 返回局部 failure；Home/Memory owner 的已知执行失败形成 typed task outcome；未知异常与 Runtime transfer 保持原语义。Observation 只发布 scope、target、status、count、digest 和 error type，不包含 Home/Memory 正文、Session facts、prompt、API key 或绝对路径。

## 核心不变量

- 新日工作只依赖确定性 rollover，不依赖模型维护成功；
- manual/scheduled 不复制 Memory 执行流程；
- daily existence 只用于自动去重和启动提示，不阻止显式维护；
- daily scheduled 每次只考虑当前 Business Day 的前一日，更早 backlog 保留；
- Memory source 必须有目标 Session 与归档 `Memory.md`；
- startup 只刷新 availability，scheduler 不 catch up；
- User Turn 永远不能选择 maintenance domain；
- Archive、Home 和 Maintenance orchestration 不绕过各 owner 的写入边界；
- 不建立 rebuild flag、settlement、approval、decision broker 或持久 Maintenance plan。
