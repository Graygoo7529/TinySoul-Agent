# Agent 重构 R5 复审修正子计划：运行可用性与退出等待

状态：`done`（2026-09-21 实现、文档同步、逐项核对与完整门禁通过）。
日期：2026-09-21。
复审基线：`7d97f23`。
主计划：[Agent 架构重构](../20260915-agent-architecture-refactor-plan.md)。
前置：[R5 Gateway v2](20260920-done-Agent重构第五轮子计划-Gateway%20v2与SDK协议闭环.md)、[R5 Endpoint 生命周期收口](20260920-done-Agent重构第五轮收口子计划-Endpoint生命周期与重启.md)。

## 1. 目标与范围

本轮修正 R5 提交后复审发现的两个生命周期缺口，并明确 SDK 退出等待的命名。继续采用同一个 Agent、同一个根调度器、同一个 EndpointHost；不改变 Turn/Cycle/Phase、Context 段、领域 owner、Reflection 或 Job 的业务语义。

核心原则是由生命周期 owner 决定何时可以接受外部操作。Endpoint 可以持有已装配的依赖，但只有 owner 可运行时才允许业务访问。重启请求只调用 Agent 已有的共享重启操作，等待者不拥有绑定或运行状态。

优先验证正常启动、重启、业务受理和退出，再补齐已复现的启动失败与等待者取消路径。不引入自动恢复、重试队列、生命周期事件总线、额外重启任务、发布版本号或跨世代迁移。

## 2. 已复现问题

| 编号 | 触发与证据 | 原因与影响 |
|---|---|---|
| P1 `done` | 在新 Assembly 的服务激活期间提交 Turn，再令激活失败：Endpoint 曾返回 ready=true 并接受请求；Agent shutdown 后该句柄仍为 queued、未完成 | 已由统一 owner 可用性和启动失败句柄结算修正；实现与回归见 §9 R5R.1/R5R.3 |
| P2 `done` | 两个重叠重启调用都成功，但 Agent running、Endpoint ready=false；取消重启等待者也能产生同样结果 | 已删除逐请求解绑，复用唯一 SDK 重启任务；实现与回归见 §9 R5R.2 |

相关实现：`tinysoul/gateway/cli.py` 的工厂与 `_EndpointLifecycle`、`gateway/endpoint/host.py`、`engine/context.py`、`agent/sdk.py` 的启动/重启边界、`agent/dispatch/scheduler.py` 的请求结清。

复审验证为隔离项目上的真实 Agent/Endpoint lifecycle 调用；相关既有测试 122 项通过。重叠与取消实验没有通过真实 HTTP 传输，不能替代本轮的正式回归与全门禁。上轮归档中的 Full/typecheck 是历史验证，不代表本轮缺口已经关闭。

## 3. 统一设计：依赖绑定与运行可用性

### 3.1 单一可用性来源

EndpointEngineContext 增加显式注入的同步、只读可用性函数，类型为 `Callable[[], bool]`。它只读取生命周期 owner 的当前状态，不执行 I/O、等待或状态变更。无需为一个真实读取点建设通用生命周期观察 SPI。

稳定 SDK 宿主从 `Agent.state is AgentState.RUNNING` 派生可用性。首次装配、启动、停止、重启和启动失败时不可用；`Agent._start` 完成 activation 并进入 running 后才可用。运行状态继续只由 Agent 修改，Endpoint 不维护自己的 starting/running/restarting 状态或可变 ready 标志。

EngineContext 集中检查依赖是否齐备以及 owner 是否可用，其 gateway/services/config 访问遵循同一边界；各 HTTP route 不重复检查。状态查询通过同一可用性判定生成 ready，不再以 active_day 非空替代启动完成。owner 的世代/日 lease 校验继续负责已取得服务的有效性。

可用性来源必须显式装配。稳定宿主不能在未接入 Agent 时默认放行，也不能改用候选 Assembly 的局部 activated 状态来绕过 SDK 生命周期。类型检查与聚焦测试应覆盖装配入口，而不是在每层重复防御。

### 3.2 bind 的明确含义

保留工厂中的 `host.bind(assembly)`，其职责收敛为替换当前候选依赖并接入 Observation route；bind 本身不宣告业务 ready。候选引用是装配依赖，不是新增的业务状态副本。

这使“激活成功后才对外可用”由 Agent 的一次状态发布自然成立，无需增加 activated/deactivating 回调框架，也无需让工厂自行调用 activate 或等待 SDK 私有任务。Gateway 不读取 Agent 私有 Assembly，Agent 不导入 Gateway。

Observation 可在 activation 期间进入稳定 buffer，以保留启动和失败诊断；它仍是旁路事实，不参与可用性判定。旧 route 随下一次 bind 移除，最终 host.stop 移除当前 route；本轮不建设事件迁移或双写机制。

### 3.3 单 generation 嵌入式装配

现有 `mount_endpoint` 仍只服务单 Assembly 随启停的嵌入场景。它也使用同一个 EngineContext 可用性入口，从 Assembly 的公开只读属性取得“激活完成且仍接受工作”的投影，不能读取私有字段或默认 always-ready。

该属性从现有 `_activated`、受理/关闭事实派生，不增加一套生命周期状态。单 Assembly 运行结束或关闭时先停止受理。需要跨 restart 的嵌入方继续使用稳定 EndpointHost 与 Agent 状态来源，不把单 Assembly 挂载扩展成另一套跨世代宿主。

CLI、嵌入式装配和测试 fixture 必须一起迁移显式依赖注入。HTTP server、engine、instance、journal、cursor 的进程级生命周期保持一致。

## 4. 启动、重启与失败的主线

### 4.1 正常顺序

```text
Agent 开始启动/重启，外部业务不可用
  → 原有关闭路径结清旧 Turn/Job 并回收资源（重启时）
  → 工厂 build，host.bind 候选依赖与 Observation route
  → Agent activation：日准备、来源和服务启动
  → Agent 发布 running；Endpoint 派生 ready=true
  → 外部请求经同一 AgentCommands 受理
```

候选激活期间 status、health、replay 与显式 restart 仍可访问；业务查询和写入返回既有 `409 service.unavailable`，不返回虚假 admission receipt。重启成功后保留 instance/cursor，generation 改变，旧业务 facade 仍按既有语义失效。

### 4.2 共享重启与等待者取消

`_EndpointLifecycle.restart` 只等待 `Agent.restart()` 并投影结果，删除调用前 unbind 和 `except BaseException: unbind`；如果不再使用 host 引用，同步删除该依赖。

SDK 的 `_restart_task` 继续是唯一共享重启操作。重叠请求加入该任务；真正完成之后的新请求可发起下一次重启，不额外增加去重窗口。HTTP 层不增加锁、第二个 restart task 或串行重启队列。

保留 SDK 当前 join 语义：调用者取消不会抛弃已开始的生命周期操作；操作收敛后再向该调用者传播取消。无论等待者是否仍存在，成功进入 running 的绑定保持可用。显式 shutdown 仍拥有终止运行及回收资源的权限。

### 4.3 启动失败时结清已受理请求

修正 Endpoint 提前受理之后，来源启动期间仍可能通过受信输入入口排入请求。这是当前 activation 顺序的真实行为，不另建启动缓冲队列，也不通过大范围重排来源启动规避。

SDK 启动失败路径应停止受理和已启动来源，通过 RootScheduler 既有句柄完成入口结清剩余请求，再释放 Assembly。普通启动失败使用已有 `RequestFailure.FAILED` 和有界 error_type；启动被取消使用 `RequestFailure.CANCELLED`。扩充已有 close_requests 的结束分类即可，不新建 TurnOutcome 或另一个完成器；失败结算不额外伪造 cancel_requested。

未执行请求不调用 LLM、不伪造 Session Turn；已持有句柄最终可以取回终态。清理沿既有资源作用域和 JoinedOperations 完成，必要清理不覆盖原始启动失败。正常 shutdown 的既有分类保持不变。

### 4.4 错误与查询

- 未激活业务访问是 Endpoint 局部请求拒绝，不生成 Runtime Trap。
- 启动/激活失败仍由当前 owner/SDK 边界归类；HTTP 复用有限错误 envelope，不返回原始异常正文。
- 等待者取消保持取消身份，不转换成启动失败或触发解绑。
- 启动失败后 Agent 非 running，Endpoint 返回不可用状态；用户可显式重试，没有后台自动重建。
- Observation 或 journal 失败只形成旁路诊断，不改变生命周期成功与否。

## 5. 退出等待接口

`Agent.wait()` 已直接重命名为 `Agent.wait_for_exit()`，删除旧名称，不保留兼容转发。这个方法等待调用方所观察的 Agent 运行最终退出，跨越 generation restart；不是让 Agent 暂停，也不是 Signal/EventBus 的消费接口。

`TurnHandle.wait()` 保持原名，其对象已经明确表示一个 Turn 的完成结果；Kernel 的 INPUT/EVENT/TIMER/BUDGET 等待仍由 Loop 唯一维护。此次命名不涉及内核等待动作、进程 wait、Condition 或 Future 的通用等待方法。

本轮按 §8 Q1 确认，仅重命名、同步调用者和明确已有契约。接口行为如下：

| 情况 | wait_for_exit 行为 |
|---|---|
| 首次成功启动之前 | AgentClosedError |
| 根调度正常退出 | 返回现有 AgentRunResult |
| 根调度异常退出 | 传播已有运行失败 |
| generation restart | 保持等待；重启失败由重启调用方接收，宿主等待仍可跨显式重试 |
| 取消一个等待者 | 只解除该等待者，不停止 Agent 或取消其他等待者 |
| 显式 shutdown，退出 Future 尚未完成 | 保留现有 CancelledError；若退出结果已完成，不撤销该结果 |

wait_for_exit 不替代 shutdown，也不承诺世代和全部宿主资源已经释放；宿主继续在 finally 中关闭 Endpoint 与 Agent。AgentRunResult 保持现有根调度运行范围，不新增跨重启累计结果或退出历史。

当前生产调用点主要为 CLI，直接 SDK 回归在 `tests/agent/test_sdk.py`。实施时搜索代码、当前设计文档与协议说明完成迁移。已归档计划中的 Agent.wait 是历史事实，保留并用本计划说明命名变化，不批量重写旧执行记录。

## 6. 实施切片与验收

| 切片 | 状态 | 改动与验收 |
|---|---|---|
| R5R.1 可用性边界 | done | EngineContext 的统一可用性读取；CLI/Host/单 Assembly 挂载显式装配；activation 完成前业务拒绝，完成后正常受理，status 与业务一致 |
| R5R.2 重启适配收敛 | done | 删除逐请求解绑，复用唯一 SDK 重启任务；并发调用共享结果，取消一个等待者不破坏新绑定；失败后查询和显式重试保持可用 |
| R5R.3 部分启动收尾 | done | 复用 scheduler 完成入口结清来源已受理请求；失败/取消身份准确，句柄完成，无虚构 Turn/Session |
| R5R.4 退出等待命名 | done | 已确认重命名为 wait_for_exit，同步 CLI、SDK 测试与当前文档；不留旧别名 |
| R5R.5 文档与门禁 | done | 同步 AGENTS、design/agent、design/endpoint、endpoint/runtime 及相关协议说明；Full/typecheck、文档链接与 diff-check；主计划 S5 重新验收 |

最小回归集合按 owner 分工：

1. Endpoint 边界用受控 activation 暂停点验证未激活时 status=false、业务拒绝，成功后可用；包含保留 mount_endpoint 的单 Assembly 路径。
2. Agent owner 验证来源在 activation 中已经受理请求、后续失败/取消时句柄终结；不通过伪造 HTTP 状态代替 owner 收尾验证。
3. 真实 CLI/HTTP 宿主覆盖正常重启，以及候选已绑定但尚未激活期间的第二个重启请求，结果成功且新 Turn 可受理。使用明确的同步点，不靠 sleep 或随机压力碰撞。
4. lifecycle 适配层直接取消一个等待任务，验证底层重启完成且绑定可用；不假设 HTTP 客户端断开一定会取消 ASGI handler。
5. SDK 退出等待测试覆盖跨重启、单等待者取消隔离与 Q1 确认的关闭语义。继续复用已有旧对象失效、instance/cursor、启动失败后重试和 Ctrl-C 验证。

局部验证后运行 Fast，声明实施完成前运行 `scripts/test.ps1 -Suite Full`（包含 Generation/wheel）与 `scripts/typecheck.ps1`。真实 provider/network 和 Linux 实机不作为本轮默认验证，执行与否如实记录。仅编写本计划不运行代码门禁，不沿用历史通过数作为新实施证据。

## 7. 与主计划及 AGENTS 的核对

- Agent 仍唯一拥有运行状态、根请求及 start/shutdown/restart 任务；Endpoint 只读取可用性并映射协议。
- Candidate facade 与 Observation route 的绑定没有被误用为业务激活；Context、领域 owner、请求队列和 Job 不复制状态。
- 本轮只给既有关闭入口补齐未启动请求的结算，保持局部拒绝、模块失败、Runtime 控制和取消的区别。
- 可用性检查集中在协议依赖入口，底层继续使用已有 lease，不添加逐层状态重验、发布序号、CAS 或自动恢复。
- 原 R5 两批次的归档与验证记录保留。本计划覆盖提交后复审修正；S5 在修正完成后重新核对为 done，S1/S2/S4 完成状态与 S3、S6–S7 范围不变。
- 当前 design 文档在实施时更新，不提前描述本计划为已实现。完成后逐项写入实现与验证位置，将本文件加入 `-done-` 并移至 `docs/analysis/done/`，更新主计划链接及 S5 状态。

## 8. 待确认点

Q1 `decided`（2026-09-21 用户确认）：本轮仅重命名，保持 `AgentRunResult` 返回类型和显式 shutdown 对未完成退出等待的取消语义，把含义准确写入 SDK 文档。不新增退出结果类型或跨重启累计结果。

P1/P2 的可用性投影、共享重启与请求收尾方案及 Q1 均已确认并落实，没有遗留待确认语义。

## 9. 实施记录

2026-09-21：用户确认 Q1 并授权实施，代码实施起点为计划提交 `996b35d`。以下实现、文档与必要验证均已逐项核对完成：

- R5R.1：`gateway/endpoint/engine/context.py` 集中读取显式可用性函数；`host.py` 在未接入来源时关闭业务访问，CLI 从 Agent.state 派生，mount_endpoint 从 Assembly.is_available 派生；status 复用同一判定。四项既有配置协作测试改为真实 activate/close，不保留未激活即可服务的假设。
- R5R.2：`gateway/cli.py` 的 `_EndpointLifecycle` 删除 host 依赖和逐请求解绑，只调用 Agent.restart。既有真实 CLI/HTTP 回归加入候选已绑定的 activation 同步点，验证两个请求只建立一个新 Assembly；单独取消 lifecycle 调用者后继续从真实 HTTP 查询并受理 Turn。
- R5R.3：Assembly 激活失败先停止受理并回收来源；SDK 通过 JoinedOperations 完整 join 失败启动的请求结算和资源关闭；scheduler.close_requests 使用已有 RequestFailure 区分失败与取消。两项参数化 owner 回归验证句柄终态、cancel_requested、错误摘要、未调用模型与资源回收。
- R5R.4：SDK 与 CLI、测试替身均已迁移 wait_for_exit；保留原返回/取消协议。回归覆盖跨 restart、单等待者取消、首次启动前拒绝、正常退出结果及 shutdown 后保留已完成结果。
- R5R.5：已同步 design/agent、design/endpoint 和 endpoint/runtime、index、frontend-integration；AGENTS 与主计划 S5 完成状态同步。历史执行记录保留旧名，当前代码无 Agent.wait 兼容别名。

验证：Windows Fast `1107 passed, 28 deselected`；Full `1112 passed, 23 deselected`，含全部 5 项 Generation/wheel；`typecheck.ps1` 与 diff-check 通过，归档链接已核对。本轮真实 HTTP server 验证并发 restart、ready/受理边界、失败后重试和 Ctrl-C；等待者取消直接在 lifecycle 适配层验证，不把 HTTP 断开等同于任务取消。未运行真实 provider/network 或 Linux 实机。

依据 AGENTS 最终核对：Endpoint 只有候选依赖和 owner 状态投影，未增加平行生命周期/重启任务；请求结算复用 RootScheduler 完成管线，失败与取消分类没有混用；wait_for_exit 沿用已确认的结果与取消契约。代码、当前设计和 Endpoint 协议一致，P1/P2 已关闭。本计划标记 done 并归档，主计划只更新 S5 状态与本轮完成记录。
