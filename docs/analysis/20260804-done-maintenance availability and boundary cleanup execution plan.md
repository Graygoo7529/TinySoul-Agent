# Maintenance Availability 与边界收敛执行计划

## 状态

- `completed`：整体重构
- `completed`：Stage 1，同步规约、设计文档与执行计划
- `completed`：Stage 2，建立持久 Maintenance Availability 与增量 Memory 待办
- `completed`：Stage 3，删除 MaintenancePlan 并收敛 Engine 与异常边界
- `completed`：Stage 4，迁移 BusinessDay、删除兼容残留并对齐 App/Endpoint
- `completed`：Stage 5，完成测试、类型检查和文档验收

## 背景

2026-08-03 的 Maintenance Turn 与 Daily Lifecycle 重构已经建立 App-owned Program、共用 Loop 内核和 Archive/Home/Memory Maintenance 边界，但启动 availability 仍通过扫描全部关闭日临时计算，`MaintenancePlan` 没有成为真实执行协议，Endpoint 也会在读取状态时重新计算业务事实。该实现缺少一份跨重启保留的待维护事实投影，并在 Engine 中保留了宽泛异常捕获与兼容输出路径。

本计划不提供旧配置、旧持久格式、旧导出或旧调用的兼容层。

## 已确认设计

1. Program 启动先恢复或完成确定性 Archive，再由 Maintenance 刷新唯一 availability；Endpoint 必须在该步骤完成后才对前端可用。
2. 一次 Archive 完成或恢复后，只检查该归档日：Archive Session facts 非空且该日有效 MEMORY 缺失时，把日期加入持久 `memory_days`。Archive Workspace 是 Memory Turn 的情景来源，不单独创建 Memory 待办。
3. 既有 `memory_days` 跨重启保留。刷新时只校验列表内日期并删除已经存在有效 MEMORY 的项；不扫描所有历史关闭日，也不只猜测昨日。
4. Home 不进入日期列表。每次刷新都由 Home owner 计算唯一的 diff/SKILL_MEMORY 计数，并和 Memory 日期列表共同原子写入一份 availability。
5. 对前端，持久 availability 是唯一提示单；对维护执行，Archive、Memory 和 Home owner facts 仍是提交前必须复验的权威状态。Observation 只通知前端重新读取，不拥有待办事实。
6. 删除 `MaintenancePlan` 和 `MaintenanceTaskPlan`。Engine 直接根据 typed request 与一次 availability 快照选择 Home 和按日排序的 Memory tasks。
7. 手动与定时请求继续使用同一个 Engine 流程；启动只刷新并提示，不自动启动 LLM Maintenance，也不建立审批或阻塞状态。
8. `BusinessDay` 是 Session、Workspace、Loop 与 Maintenance 共用的 owner-neutral 值对象，移到 `tinysoul.infra.time`；业务时区和 BusinessClock 仍归 Maintenance。
9. Engine 只把明确的可继续 task failure 收敛为失败 outcome。Runtime transfer 和未分类的程序错误原样传播；Archive 和 availability 不变量失败阻止新日 Program work。
10. 删除本次边界内的兼容残留，包括旧 Turn output signal/trap、旧 Maintenance plan 导出和宽松的旧 journal 字段解释；数据保护检查不是兼容层，应保留。

## 目标流程

```text
Program startup / request boundary
  -> Archive preflight
  -> reconcile persisted MaintenanceAvailability
       +-> newly archived day -> Session facts / MEMORY eligibility
       +-> existing memory_days -> completed-item pruning
       +-> current Home pending counts
  -> atomic availability write
  -> publish availability observation

Maintenance request
  -> same preflight + reconciliation
  -> direct task selection from request + availability snapshot
  -> Home Turn and/or ordered Memory Turns
  -> post-task reconciliation + atomic write
  -> completed + availability-changed observations
```

## 实施事项

### Stage 1：规约与设计

1. 更新 `AGENT.md` 的每日生命周期、提示单、增量发现、前后端协同与异常语义。
2. 更新 Maintenance、App、Endpoint、Infra、Memory 设计文档。
3. 保留 2026-08-03 完成记录，新建本活跃计划表达后续变更。

### Stage 2：Availability

1. 在 Maintenance 配置中增加 module-owned runtime state root。
2. 建立严格 schema 的 `MaintenanceAvailabilityStore`，使用有界 JSON 读取和原子替换。
3. 让 preflight 返回的 Archive projection 直接驱动单日 Memory 待办登记。
4. 让成功 Memory task和启动恢复幂等清理已完成日期；Home 每次从 owner 重新计算。

### Stage 3：Engine 与失败边界

1. 删除 plan 类型、`plan()` 和 `missed_memory_days()`。
2. `run()` 使用 availability 快照直接选择任务并在结束后刷新提示单。
3. 用明确的 task failure 协议替代 `_run_task()` 的 `except Exception`；未知异常与 Runtime transfer 不得降级。
4. 增加 crash window、失败保留和多日期稳定顺序测试。

### Stage 4：共享类型与协议

1. 将 `BusinessDay` 移到 `tinysoul.infra.time`，更新全部引用，不从 Maintenance 兼容重导出。
2. Program 启动先刷新 availability；Endpoint GET 只读取该投影。
3. 删除旧 Turn output signal/trap 与测试，completion detector 成为唯一 Turn 输出路径。
4. 收紧 Archive journal 的字段集合并拒绝旧字段。

### Stage 5：验收

1. 聚焦 Maintenance/App/Endpoint/Loop/Infra 测试。
2. 运行 Fast、Full 与 `ty` 类型检查。
3. 将设计文档和本计划更新为实际实现；全部通过后将计划改名为 `-done-`。

## 实际结果

- `MaintenanceAvailabilityStore` 已成为唯一前端提示单，Program 在 ProgramRequestSource、AppService 和 Endpoint 启动前完成 Archive preflight、增量 Memory 日期登记与 Home 计数重算；Endpoint GET 只读取该投影，前端连接后读取 GET，事件只触发重新读取。
- Archive 已增加严格 `archive/catalog.json` 日期索引。Archive projection 由本次 transition 直接交付，按日期查询只读取索引指向的目标 journal，不再扫描全部关闭日。
- Engine 已删除 `MaintenancePlan`、`MaintenanceTaskPlan`、`plan()` 与 `missed_memory_days()`；manual/scheduled request 进入同一路径，Memory 失败日期保留到下一次启动，Home 完成后按 owner 事实清除 runtime Home。
- `BusinessDay` 已移动到 `tinysoul.infra.time`；旧 Maintenance 重导出、旧 journal 字段解释、Turn output signal/trap 及相关 Runtime reason 已删除。Task failure 只收敛明确 owner 异常，未知异常和 Runtime transfer 继续传播。
- 本轮边界复核已完成：Home `SKILL_MEMORY.md` 被建模为独立 `skill_how_review`，`list/inspect` 与 `reject/rewrite` 由 Home owner 绑定 token，只有 inspect 后才能解决；HOW rewrite 在 actual 写入前复用严格 frontmatter parser，非法内容不会覆盖 actual 或清理临时记忆。
- Maintenance task 新增统一外层 transfer 展开 helper；指向 Turn 之外的 transfer 原样抛出给 Program，不降级为普通 task failure。MaintenanceEngine 不再伪造没有 `RuntimeModuleRunner` owner 的 `MODULE` frame，调用方 Program scope 直接贯穿 Archive/Home/Memory task。
- Memory 归档情景适配器已从 `loop.maintenance` 移入 `tinysoul.maintenance.memory.ArchivedMemoryMaintenanceContext`，绑定时校验目标日、Session day、Workspace day，prepare 时校验 Memory Turn business day；Memory Turn 使用目标关闭日，MaintenanceOutcome 仍记录执行日。
- Program 运行期 availability、User preflight 与 Maintenance request 的 `MaintenanceError` 统一经过 RuntimeMaintenanceBridge 收束为 `runtime.program_end`；启动 prepare 仍使用 `runtime.startup_failed`，未知 Python 异常保持传播。

## 验证

- 聚焦 Maintenance/App/Endpoint/Loop：通过。
- Fast：`839 passed, 2 skipped, 22 deselected`。
- Full：`840 passed, 2 skipped, 21 deselected`。
- `ty check`：通过。
- `visualization`：`pnpm test` 通过（3 tests），`pnpm build` 通过。
- 边界回归：`33 passed`，覆盖 Home HOW review/非法 rewrite、Program maintenance failure、外层 Runtime transfer、无伪 Module frame 与归档情景日期不变量。

## 验收条件

- 启动和每次维护后都只有一份持久 availability；前端不依赖事件历史恢复提示。
- 新归档日被增量登记，失败日期跨重启保留，正常路径不扫描所有 Archive days。
- Memory 成功后日期消失，Home 完成后计数归零且正常情况下 `runtime/home` 被移除。
- `MaintenancePlan`、旧 missed-work 扫描和旧 Turn output 协议不存在。
- User/Maintenance Action view 隔离及共用只读 inspect 语义保持不变。
- Runtime transfer 和未知程序错误不被转成普通 Maintenance task failure。
- 完整本地门禁和类型检查通过。
