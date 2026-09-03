# Maintenance Turn 所有权与 App 装配重构执行计划

## 状态

- `completed`：整体重构
- `completed`：Stage 1，建立执行计划与基线
- `completed`：Stage 2，提取通用 Turn kernel assembly 与 User Turn 入口
- `completed`：Stage 3，内聚 Maintenance Context、Action、Turn 与 Runtime policy
- `completed`：Stage 4，中性化 Home/Memory owner 能力并迁移配置与资源
- `completed`：Stage 5，收缩 App、更新文档并完成全量验收

## 背景

当前 App 已正确拥有 typed request queue、Program frame、输入输出和服务生命周期，也正确把 UserTurnRequest 与 MaintenanceRequest 分派到同级 work。但是 `TinySoulAppBuilder` 仍直接构造两类 Turn 的 Context、ActionEngine、Phase1/2/3、Cycle、Trap、preparation、completion 和 task 变体；`loop.maintenance`、`action/catalog/maintenance`、`runtime.bridge.maintenance`、`home.background.ActualHomeBackgroundEntryProvider` 与 `[loop.maintenance]` 又把 Maintenance 支线语义分散到通用或主线模块。

这不仅是文件过大：Maintenance Memory Turn 使用按 active Workspace 构建的 Context pressure recovery，存在历史归档梳理影响当前工作区的错误恢复路径。User ActionEngine 还要通过 Maintenance-owned view 排除 Maintenance actions，形成主线到支线的反向依赖。

本计划不保留旧导出、旧配置键、旧类型名或旧 Builder alias。迁移完成后删除旧路径，避免兼容层继续表达错误所有权。

## 已确认目标

1. App 只拥有进程 composition、Program queue/frame、请求分派、Gateway、Endpoint、scheduler、输入输出与服务生命周期。
2. `tinysoul.loop` 根只拥有 owner-neutral Turn/Cycle/Phase kernel 与通用 pipeline/protocol；`loop.user` 是清晰的 User Turn 主线入口。
3. `tinysoul.maintenance` 独立拥有 Maintenance Context、Action catalog fragment、Home/Memory Turn、Prompt、completion、Runtime policy、task 与 Engine；通用内核和 User 主线不认识 Maintenance。
4. User Turn 和 Maintenance Turn 复用同一个 Turn kernel，但分别构造完整 Context、Action、Trap、preparation、completion 和 typed entry。
5. Home/Memory owner 保留私有 store、CAS、Link 校验、overlay apply、consolidation 与原子写入不变量，但公开能力使用中性 Home Review / Memory Consolidation 语义，不以 Maintenance 命名。
6. App、Endpoint 和前端作为明确顶层分派或外部协议边界可以认识 Maintenance 公共 request/status；Action、Runtime、Loop core、User、Home、Memory、Session、Workspace、Context 不得反向依赖 `tinysoul.maintenance`。
7. Maintenance 整体仍自治执行，不增加人工 approval、decision channel、阻塞输入或第二套 Program。

## 目标依赖图

```text
tinysoul.app
  +-> loop.user.UserTurnEntry
  |     +-> loop Turn kernel
  |     +-> Context/Action/Session/Workspace/Home/Memory public facades
  +-> maintenance.MaintenanceEngine
        +-> maintenance.turn.MaintenanceTurnEntry
        |     +-> loop Turn kernel
        +-> Archive/Home/Memory Maintenance tasks
        +-> Home Review / Memory Consolidation public facades

loop core / loop.user / action / runtime / home / memory / session / workspace
  -X-> tinysoul.maintenance
```

## 目标目录

```text
tinysoul/loop/
  assembly.py
  turn.py / cycle.py / phases.py
  preparation.py / completion.py
  pressure.py                 # 中性 pressure protocol/result
  trap_handlers.py            # 中性 frame/pressure handler
  user/
    builder.py
    entry.py
    actions.py
    context.py
    pressure.py
    runtime.py
    completion.py
    prompts.py

tinysoul/maintenance/
  builder.py
  context.py
  runtime_bridge.py
  turn/
    entry.py
    completion.py
    prompts.py
    runtime.py
  catalog/maintenance/
  archive/
  home/
  memory/
```

删除 `tinysoul/loop/maintenance/`、`tinysoul/action/catalog/maintenance/` 与 `tinysoul/runtime/bridge/maintenance.py`。

## Turn Kernel 与入口

新增通用 Turn assembly，只接受 ContextEngine、ActionEngine、LLMRunner、SignalBus、RuntimeTrap、TurnSettings、Phase retry、guidance、completion detector、pipelines、DomainHowProvider 和 activity controller。它构造共享 RuntimeModuleRunner、ContextSignalConsumer、Phase1/2/3、CycleRunner 与 TurnRunner，不接受 Maintenance kind、Home diff 或 Memory target day。

`loop.user.UserTurnBuilder` 接受 typed settings 与已构建 owner 门面，构造 effective Home/Memory Context、User ActionEngine、User pressure/trap、User preparation/completion 和 `core.answer` completion。它不读取 ConfigEnvironment、不创建 Program、Endpoint 或服务。

`maintenance.MaintenanceBuilder` 构造 Home 与 Memory 各自独立的 ContextEngine、ActionEngine、Trap、Turn entry、controller、task、Archive coordinator、availability store 和唯一 MaintenanceEngine。Home/Memory task 依赖 Maintenance-owned typed Turn entry，不直接解释通用 TurnRunner outcome。

## Runtime Policy

1. User pressure recovery 保留 Context 压缩、Background 逐出、active Workspace recoverable cleanup、Home runtime copy 与 Workspace trash restore。
2. Maintenance pressure recovery 只能修改本 Maintenance Context；不注册 Home runtime copy、Workspace cleanup 或 Workspace trash restore。
3. Home Turn 注入当前 Session/Workspace 的只读情景；Memory Turn只注入目标关闭日的 Archive Session/Workspace。
4. Memory Turn 的普通、压力、失败和 transfer 路径均不得读取或修改 active Workspace。
5. Home/Memory Maintenance Context、SignalConsumer 与 Trap 不共享，避免 task profile 或绑定状态串扰。

## Action Catalog

Action 增加通用多 catalog source 支持，例如 `ActionCatalogLoader.load_many()` 与 `ActionEngineBuilder.add_catalog_root()`；合并仍由 ActionCatalog 强制 domain/action 唯一。

User ActionEngine 只加载 `tinysoul.action` 自有 catalog，因此物理上不存在 Maintenance domain，不再按字符串排除。Maintenance catalog 作为 `tinysoul.maintenance` package data；Maintenance Engine 同时加载 Core catalog 与 Maintenance fragment，再通过 `include_actions()` 精确构造 Home 或 Memory ActionEngine。通用 `core.context.inspect`、`core.session.inspect` 仍归 Action/Core 拥有。

删除 `user_action_view()` 和构建后重复的 `maintenance_action_view()`。

## Owner 中性能力

Home 保留 overlay review 实现，但执行以下无兼容改名：

```text
home/maintenance.py           -> home/review.py
HomeMaintenanceService        -> HomeReviewService
HomeMaintenance*              -> HomeReview*
maintenance_pending()         -> review_pending()
maintenance_snapshot()        -> review_snapshot()
resolve_maintenance()         -> resolve_review()
finalize_maintenance()        -> remove_resolved_overlay()
```

Memory 保留 consolidation、Link validation 与原子写入，但执行：

```text
memory/maintenance.py         -> memory/consolidation.py
MemoryMaintenanceService      -> MemoryConsolidationService
MemoryMaintenance*            -> MemoryConsolidation*
maintenance_eligible()        -> consolidation_eligible()
run_maintenance()             -> consolidate()
[memory.maintenance]          -> [memory.consolidation]
memory_maintenance LLM profile -> memory_consolidation
```

Session facts projection、Session archive view、Workspace archive snapshot 和 Home actual read 门面保留在各 owner；Maintenance 只能通过这些公共门面访问事实。

## 配置与公共入口

1. `LoopSettings` 删除 Maintenance Turn budget，保留共享 Phase retry 与 User Turn budget。
2. `[loop.maintenance]` 移为 `[maintenance.turn]`，由 MaintenanceSettings 持有通用 TurnSettings。
3. Memory owner 的算法预算从 `[memory.maintenance]` 改为 `[memory.consolidation]`。
4. `RuntimeMaintenanceBridge` 移到 Maintenance，形成 `maintenance -> runtime` 单向依赖。
5. App 的 `with_action_engine`、`with_context_engine`、`with_domain_how`、`with_turn_completion_handler` 改为显式 `with_user_*`；不保留旧 alias。

## App 收缩

从 AppBuilder 删除 User/Maintenance Context、Action、Phase、Cycle、Turn、Trap 与 task/controller 的内部构造方法。App 只构建 LLM、Home、Memory、Session、Workspace 等进程级 owner，然后调用 UserTurnBuilder 与 MaintenanceBuilder，最后装配 Program、Gateway、Endpoint、scheduler 和 TinySoulApp。

Program 的 Archive preflight、active day lease 与 MaintenanceRequest 分派继续保留，因为它们是新日 User Turn 的顶层一致性门禁，不属于 Turn 内核。

## 实施阶段

### Stage 1：基线与通用能力

- 写入本计划并确认工作区基线。
- 新增通用 Turn kernel assembly。
- 抽象 pressure recovery protocol，迁移 User Workspace recovery。
- 增加 Action 多 catalog root 合并。

### Stage 2：User Turn 主线

- 建立完整 `loop.user` Builder/Entry/Context/Action/Runtime。
- 迁入 App 中 User Context、Action、Trap、Phase/Cycle/Turn 装配。
- 收紧 User override API 并验证 catalog 不包含 Maintenance。

### Stage 3：Maintenance 内聚

- 把 Maintenance prompt/completion/outcome 从 Loop 移入 Maintenance。
- 迁移 actual Home Background provider、Maintenance runtime bridge 与 catalog。
- 建立 Home/Memory 独立 Context/Trap/Turn entry 与 MaintenanceBuilder。
- 修复 Memory Turn active Workspace pressure 路径。

### Stage 4：Owner 中性化与 App 收缩

- 完成 Home Review、Memory Consolidation、LLM profile 与配置改名。
- 删除 App 内 Turn 细节与 Maintenance 内部 imports。
- 删除所有旧文件、旧导出、旧配置键和 alias。

### Stage 5：文档与验收

- 更新 AGENT.md、Loop、Maintenance、Action、Home、Memory、LLM 设计文档和默认配置。
- 增加架构依赖测试、Action 精确可见性、Context 隔离与 active Workspace 不变测试。
- 运行定向测试、全量 pytest、ty、wheel 构建、隔离安装和资源读取验证。
- 重新加载 AGENT.md 与本计划逐项审计；完成后将本文件改名为 `20260804-done-maintenance turn ownership and app assembly refactor execution plan.md`。

## 完成判据

1. AppBuilder 不再导入 Phase1/2/3、CycleRunner、Maintenance controller/task 或 Maintenance action constants。
2. `tinysoul.loop` 通用路径不包含 Maintenance import、类型、配置字段、Prompt 或 completion。
3. User 默认 catalog 中物理上不存在 Maintenance domain；Home/Memory Maintenance catalog 精确且互相隔离。
4. Maintenance Context 与 User Context 同结构；Home 使用 actual Home + 当前情景，Memory 使用 actual Home + 目标归档情景。
5. Memory Maintenance 在 Context pressure 下不修改 active Workspace。
6. Home/Memory/Session/Workspace/Action/Runtime 不导入 `tinysoul.maintenance`；owner API 不再以 Maintenance 命名。
7. 手动、定时、Endpoint 请求仍进入同一 MaintenanceEngine；启动 preflight/availability、Daily 仅昨日、显式 Memory 日期语义不变。
8. Home 全部 review 完成后 runtime Home 为空；Memory 仍只由 Memory owner原子写入。
9. 全量测试、类型检查、wheel 和隔离安装通过，设计文档与 AGENT.md 同步。

## 实施结果

### Turn 与 App 所有权

- 新增 `loop.assembly.build_turn_kernel()`，集中构造 RuntimeModuleRunner、ContextSignalConsumer、Phase1/2/3、CycleRunner 与 TurnRunner；该入口只接收通用 typed facade 和 policy，不含 Maintenance kind、Home diff 或 Memory target。
- `loop.user.UserTurnBuilder/UserTurnEntry` 现完整拥有 effective Home/Memory Context、User ActionEngine、User pressure/trap、preparation、Session completion、HOW 和 `core.answer` completion。App 的 override API 已无兼容改名为 `with_user_*`。
- `maintenance.MaintenanceBuilder` 现完整拥有 Archive coordinator、availability、Home/Memory controller/task，以及 Home/Memory 各自独立的 Context、ActionEngine、trap 和 typed `MaintenanceTurnEntry`。Task 不再导入 TurnRunner 或解释 TurnOutcomeStatus；外层 Program transfer 由 typed entry 原样展开。
- `TinySoulAppBuilder` 删除两类 Context/Action/Phase/Cycle/Turn/trap/controller/task 私有装配方法，只构建进程级配置、LLM、Home、Memory、Session、Workspace、SignalBus 与服务，再调用两个 builder。Program 使用 `app.runtime_policy.build_program_trap()`。

### Maintenance 内聚与主线隔离

- Maintenance prompt/completion/runtime policy 从 `loop.maintenance` 迁入 `maintenance.turn`，旧包删除。Loop 根与 `loop.user` 不导入 Maintenance。
- Maintenance catalog 从 `action/catalog/maintenance` 物理迁入 `maintenance/catalog/maintenance` 并作为独立 package data 发布。Action core 新增多 catalog root 合并；User 只加载 Action 自有 catalog，Home/Memory Maintenance 组合 core + Maintenance fragment 后以 `include_actions()` 构造精确 surface，旧 action view/filter 删除。
- `ActualHomeBackgroundEntryProvider` 从 Home 移入 `maintenance.context`；`RuntimeMaintenanceBridge` 移入 `maintenance.runtime_bridge` 并改名 `MaintenanceRuntimeBridge`。通用 Runtime 不再认识 Maintenance。
- Maintenance pressure recovery 只调用当前 Maintenance Context 的 reclaim；没有 active Workspace reclaimer、Workspace trash restore 或 Home runtime copy。Home 与 Memory profile 不共享 Context/SignalConsumer/trap，Memory preparation 只注入目标关闭日的归档情景。

### Owner 中性化与配置

- Home owner 从 `home.maintenance`/`HomeMaintenance*` 迁为 `home.review`/`HomeReview*`，公开 `review_pending()`、`review_snapshot()`、`resolve_review()` 与 `remove_resolved_overlay()`。Home 目录和公开 API 不含 Maintenance 业务语义。
- Memory owner 从 `memory.maintenance`/`MemoryMaintenance*` 迁为 `memory.consolidation`/`MemoryConsolidation*`，公开 `consolidation_eligible()` 与 `consolidate()`；LLM profile 改为 `memory_consolidation`。
- `[loop.maintenance]` 删除，Maintenance Turn budget 迁到 `[maintenance.turn]`；`[memory.maintenance]` 迁为 `[memory.consolidation]`。旧配置键、旧类型、旧文件、旧 builder alias 均未保留。
- 架构扫描与测试确认 `action/context/home/loop/memory/runtime/session/workspace` 不导入 `tinysoul.maintenance`，这些主线/内核目录也不再出现 Maintenance 业务命名。

### 验收结果

- 新增/更新架构依赖、App 无 Turn 细节、User catalog 物理隔离、Maintenance 精确 action、typed transfer、配置无兼容、Home Review、Memory Consolidation 与 Maintenance pressure 不修改 active Workspace 等回归测试。
- 正式 `scripts/test.ps1 -Suite Full -Durations 0` 通过：851 passed、1 skipped、21 deselected；仅保留既有 FastAPI TestClient 的 Starlette deprecation warning。
- 全项目 `scripts/typecheck.ps1` 通过，`python -m compileall -q tinysoul` 通过，`git diff --check` 通过。
- release wheel 测试通过 clean-source build、Maintenance package-data 断言、隔离安装及 standard/development 项目初始化。
- `AGENT.md` 与 Action、App、Loop、Maintenance、Agent Home、Memory、LLM 设计文档已同步到新所有权与配置语义。
