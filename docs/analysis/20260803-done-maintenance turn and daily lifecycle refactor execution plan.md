# Maintenance Turn 与每日生命周期重构执行计划

## 状态

- `completed`：整体重构
- `completed`：Stage 1，建立 Maintenance 领域与 App-owned Program 边界
- `completed`：Stage 2，抽取可复用 Turn/Cycle 内核并建立 Maintenance Turn
- `completed`：Stage 3，接入 Archive/Home/Memory Maintenance 任务与专用 Action view
- `completed`：Stage 4，统一手动、定时和启动提示链路，删除人工 decision 协议
- `completed`：Stage 5，更新设计规约、Endpoint 和前端协议并完成全量验证

## 背景与问题

当前实现已经把 Home/Memory Maintenance 表达为与 User Turn 平级的 Program work，但真实执行由 `loop.ProgramMaintenanceRunner` 直接调用 Home reviewer 和 Memory consolidator，未进入 Cycle 与 Phase1/2/3。与此同时，`loop.ProgramRunner`、Daily Lifecycle、Program request/outcome、App scheduler 和人工 Home decision broker 分散拥有顶层维护语义，使 App、Loop、Home、Memory 与 Endpoint 之间形成交叉边界。

本次重构不保留旧调用、旧配置或旧 Endpoint 的兼容层。目标是建立以下单向关系：

```text
external sources -> App Program dispatcher
                         |
                         +-> User Turn -> Loop Turn/Cycle/Phase
                         |
                         +-> MaintenanceEngine
                               +-> deterministic Archive preflight
                               +-> Maintenance Turn -> Loop Turn/Cycle/Phase
                                      +-> Home maintenance actions
                                      +-> Memory maintenance actions
```

## 已确认设计决策

1. Archive 不开放独立人工命令，只作为 App 启动 preflight 和 Daily Maintenance 的强制第一步。
2. 启动时必须自动恢复并完成确定性日切；漏跑的 LLM Maintenance 只发出非阻塞提示，不自动调用模型。
3. 手动、定时、启动提示后的触发统一形成 `MaintenanceRequest`；trigger 只用于审计，不改变执行策略。
4. 所有 Home 决策均由 Maintenance Turn 自动完成，不存在人工 apply/discard/stop、pending decision 或输入阻塞。
5. User Turn 与 Maintenance Turn 复用 Cycle 和三阶段 Phase 内核，但分别拥有 preparation、prompt、Action view、完成条件和 completion。
6. Archive 是确定性生命周期操作，不为形式统一而调用 LLM。Home/Memory 只有在存在 eligible work 时才启动 Maintenance Turn。
7. App 顶层队列保持单写者串行执行。非阻塞表示请求立即获得 accepted receipt、后续输入可排队且没有人类审批等待，不表示并发修改 Session/Workspace/Home/Memory。
8. 白天手动 Daily Maintenance 不归档当前开放 Business Day；Home 仍可处理，Memory 只接受已关闭日期。
9. Daily Maintenance 顺序固定为 Archive、Home、Memory。Archive 失败停止本次流程；Home 失败不阻止 Memory，聚合结果标记 partial/failed。
10. Maintenance 使用 actual Home 的核心规约；runtime Home 只作为待审查 diff 输入，不能用尚未接受的 runtime AGENT 规则授权自身提交。

## 目标模块边界

### App

App 拥有进程级 Program、typed request queue、外部命令解析、输入分派、scheduler source 和 Observation 路由。App 不解释 Home diff、Memory Markdown、Session archive graph 或 Workspace manifest。

### Loop

Loop 只拥有一次 Turn 内的运行语义：Turn、Cycle、Phase、Runtime transfer 消费和通用 Context/Action/LLM 组合。Loop 不拥有 Program、scheduler、Daily Lifecycle 或 Maintenance 业务。

Loop 通过明确的 Turn definition/profile 支持 User 与 Maintenance：

- User：用户输入、允许 append、active Session/Workspace preparation、`core.answer` completion、Session commit；
- Maintenance：框架 task input、禁止 append、maintenance Background/Working projection、专用 Action view、`maintenance.complete` completion、Maintenance outcome。

### Maintenance

Maintenance 是每日维护领域门面，拥有：

- BusinessDay/BusinessClock 与 `[maintenance]` 配置；
- 可恢复 Archive lifecycle coordinator；
- Maintenance request/plan/outcome；
- Home/Memory task eligibility、顺序、失败隔离和 Maintenance Turn 构建；
- scheduler due/missed 计算与启动 availability；
- Archive Workspace/Session 的只读维护投影。

Maintenance 不复制 Home、Memory、Session 或 Workspace 的 owner 内部逻辑。

### Home、Memory、Session、Workspace

- Home 提供绑定 baseline/runtime/actual digest 的 diff snapshot 和原子 `accept/reject/rewrite` resolve；成功 resolve 清理对应 overlay。
- Memory 提供指定关闭日期的完整替换提交、文档与 Link 校验；普通 User Turn 继续只读。
- Session 提供归档 facts projection，不暴露 store 结构。
- Workspace 提供 active archive participant 以及归档后的只读资源投影。

## 目标请求与结果

`AppRequest` 是 App queue 的 tagged union：

- `UserTurnRequest`
- `MaintenanceRequest`
- `ExitRequest`

`MaintenanceRequest` 至少表达：scope `daily|home|memory`、trigger `manual|scheduled`、可选 target day、显式 `rebuild_memory`、request/source identity。启动 availability 本身不创建 request；用户确认提示或 scheduler 到期后才投递 request。

`MaintenanceOutcome` 聚合 task results，不形成 User answer，不写入 Session。Memory 是否重写已有文件只由 `rebuild_memory` 决定，不能由 trigger 推断。

## Maintenance Turn 与 Action

Maintenance Turn 使用独立、不可变 Action Catalog view，只暴露当前任务所需 action。至少包含：

- `maintenance.home.list`
- `maintenance.home.inspect`
- `maintenance.home.accept`
- `maintenance.home.reject`
- `maintenance.home.rewrite`
- `maintenance.memory.inspect_facts`
- `maintenance.memory.inspect_workspace`
- `maintenance.memory.consolidate`
- `maintenance.complete`

Home 每项 resolve 必须携带 change token/digests；stale 作为局部 ActionResult 返回，由后续 Cycle 重新 inspect。`maintenance.complete` 在 owner 后置条件未满足时返回局部失败，不能仅相信模型声明。

Memory consolidation 可以继续在 action 内使用有界分层 LLM Task，但任务选择、来源检查、Workspace/Session 渐进读取和最终提交由 Maintenance Turn 驱动。

## Archive 与启动语义

Archive 保留当前 journal 前滚保证，但从 Loop 移入 Maintenance。每次 App 启动和每个顶层 request 前执行 active-day preflight。只有 Archive 成功后才允许新日 User/Maintenance work。

启动完成 Archive 后计算 availability：

- active Home 是否存在真实 diff 或 SKILL_MEMORY；
- 已关闭 Archive 日期是否存在非空 Session facts但缺少 Memory。

availability 只发布提示，不自动创建 Maintenance Turn。为避免扫描范围不明，Archive transition 是关闭日期的权威 catalog；不从任意目录猜测日期。

## 配置与接口

目标配置：

```toml
[loop.user]
max_cycles = 20

[loop.maintenance]
max_cycles = 20

[maintenance]
timezone = "Asia/Shanghai"
archive_root = "archive"

[maintenance.schedule]
enabled = true
daily_time = "00:15"
```

删除旧 `[loop.daily]`、`[app.scheduler]` 和 Home/Memory 双时刻。命令收敛为 `/maintenance`、`/maintenance home`、`/maintenance memory [YYYY-MM-DD] [--rebuild]`。Archive 无命令。

Endpoint 删除 decision GET/POST 和相关 schema，只保留 Maintenance status/request。前端删除 decision dialog 和 maintenance-decision input blocking；这属于同一次无兼容协议变更。

## 实施阶段

### Stage 1：领域与 Program 所有权

1. 建立 `tinysoul.maintenance` 的 day、request/outcome、config、archive、engine 门面。
2. 将 Daily Lifecycle 从 Loop 移到 Maintenance，并让其继续只通过 Session/Workspace owner 门面工作。
3. 在 App 建立 Program dispatcher 和 request queue；把现有 User Turn 分派迁出 Loop。
4. 删除 Loop Program work/maintenance 对外所有权，迁移对应测试。

### Stage 2：Turn 内核

1. 把现有 User-only TurnRunner 拆成通用执行骨架与 `loop.user` policy。
2. 移除 Phase3 对 `core.answer` 的硬编码，改为 Turn completion detector。
3. 为 ActionEngine 增加不可变 Catalog view。
4. 建立 `loop.maintenance` preparation/prompt/completion/outcome。

### Stage 3：Maintenance 任务

1. Home owner 增加 snapshot/token/resolve 门面，删除 reviewer 与 decision provider。
2. 注册 Home maintenance actions，逐项自动处理并验证 runtime Home 最终为空。
3. Memory owner 接入 Maintenance Turn，保留有界 consolidation 和原子替换。
4. 提供归档 Session facts 与 Workspace 的只读 Maintenance 投影。
5. 完成 Archive -> Home -> Memory 聚合执行和失败隔离。

### Stage 4：触发与协议收敛

1. scheduler 改为单一 Daily Maintenance request。
2. 启动 preflight 自动 Archive，missed LLM work 只提示。
3. parser/gateway/Endpoint 统一 typed Maintenance request。
4. 删除 App HomeDecisionBroker、decision Endpoint、终端决策路由和前端 decision UI。
5. 更新项目模板配置，不保留旧键。

### Stage 5：规约与验证

1. 更新 `AGENT.md`、`docs/design/app.md`、`loop.md`、`runtime.md`、`agent_home.md`、`memory.md`、`session.md`、`workspace.md` 和 Endpoint 文档。
2. 删除或重写旧 Program/Home decision 测试，增加 User/Maintenance Turn 共用三阶段、Action view 隔离、Home 后置条件、Archive preflight、missed prompt 和 trigger 等价性测试。
3. 运行聚焦测试、Fast、Full 和类型检查。
4. 完成后将本文件改名为 `20260803-done-maintenance turn and daily lifecycle refactor execution plan.md`。

## 验收条件

- `tinysoul.loop` 不含 Program、Daily、scheduler 或 Home/Memory Maintenance 编排。
- User Turn 与 Maintenance Turn 都真实经过 Phase1/2/3。
- Maintenance action 无法调用普通 User-only mutation，User Turn 无法调用 Maintenance-only action。
- 手动和定时同一请求参数产生同一 plan 和业务结果。
- 启动自动完成 Archive，但不会自动发起任何 LLM Maintenance。
- 当前开放日期不会被人工 Daily Maintenance 归档。
- Home Maintenance 正常完成后 runtime Home 无真实 diff、无 SKILL_MEMORY，空 overlay 目录被移除。
- Memory 只为关闭日期写入，默认不覆盖已有有效文件，`--rebuild` 显式覆盖。
- 不存在人工 decision channel、兼容配置键、旧 Endpoint 或旧调用 alias。
- 完整本地门禁与类型检查通过。

## 实施结果

2026-08-03 已完成本计划。App 现在以 typed request queue 和 Program frame 统一分派 User Turn、Maintenance 与退出请求；Loop 只保留中性的 Turn/Cycle/Phase 内核，User 与 Maintenance profile 显式注入各自 completion、prompt、preparation 和 outcome 语义。Maintenance 形成 Archive/Home/Memory 独立包及唯一 Engine 门面，Home/Memory 都经真实 3-stage Maintenance Turn 和精确 ActionEngine view 执行，Archive 保持确定性 preflight 与权威关闭日投影。

User Turn 在装配期排除全部 `maintenance.*`，Home/Memory Maintenance 只复用 `core.context.inspect`、`core.session.inspect` 和本任务 actions。Maintenance Context 使用 actual Home，并按任务注入当前或归档的 Session/Workspace；Home 完成后 owner 校验无 diff/SKILL_MEMORY 并移除空 runtime Home，Memory 只针对关闭日写入，已有有效文档仅在 `--rebuild` 时覆盖。Terminal、Endpoint 与 scheduler 都只构造相同 MaintenanceRequest；启动只自动恢复 Archive 并发布 availability，不追补启动前错过的模型维护。

人工 decision/approval、旧配置键、旧 Program/Daily Loop owner、旧 Endpoint/UI decision 协议和兼容 alias 已删除。全量 `pytest -q`、全项目 `ty check`、前端 `pnpm test` 与 `pnpm build` 均通过；仅保留第三方 Starlette TestClient deprecation warning。
