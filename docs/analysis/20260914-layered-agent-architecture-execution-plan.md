# 分层 Agent 架构总体重构执行计划

状态：`pending`

本计划是一次不向后兼容的整体重设计。它允许改动项目内一切设计，包括 `AGENTS.md` 中的核心定义、项目规约、目录约定和 `docs/design/` 下的旧规约；当前代码、设计文档与已完成执行记录只作为理解意图与保留资产的材料，不构成保留模糊边界、重复状态或过渡层的理由。

## 目标

以 Agent 概念为中心重组 TinySoul：

1. 把代码分为 infra / runtime + llm / kernel / plugins + environment / agent / gateway 六层，上下层之间只经 Agent SDK 风格的类型化 API 与 SPI 调用，依赖方向单向向下。
2. 内核（Turn-Cycle-Phase 循环与 Context 语境维护）对 owner 中立：内核利用语境段，但不知道段的内容与含义；语境段、动作、Turn 生命周期钩子、Trap 处理器、Turn profile、事件源与服务门面全部由外围插件声明并注入。
3. 把 Agent 置于运行环境之中：环境事件（用户追加输入、控制请求、后台任务事件、定时器）统一进入 Turn 收件箱，内核在 Cycle/Phase 边界消费，并可按 WaitRequest 等待事件或定时唤醒下一个 Cycle。
4. 内核与所有 I/O 边界迁移到 asyncio；持久 owner 的存储引擎保持同步领域代码，由插件适配层在阻塞 I/O 处以线程调用。
5. Endpoint 协议按 Agent SDK 风格重新设计（v2），前端随后适配。
6. 清理组合根硬编码、反向依赖、超大门面与文档漂移，使 `AGENTS.md`、`docs/design/`、代码与测试重新互相解释。

## 决策记录

已确认（2026-09-14 讨论）：

- 采用分层包布局，模块名与目录随边界重定。
- Endpoint 协议一并重设计，不保持 v1 稳定。
- 内核全面迁移到 asyncio。

工作假设（按推荐项执行，待维护者确认；确认结果回写本节）：

- D1 asyncio 边界：Agent API、事件总线、Turn/Cycle/Phase、LLM、Action 批次与进程后端、输入源、Endpoint 全部 async；持久 owner 存储引擎（workspace/home/memory/session 的文件逻辑、CAS、reconcile、事务）保持同步，插件适配层中所有触盘调用经 `asyncio.to_thread`，owner 内部锁保持 threading。
- D2 新行为范围：本次落地"事件唤醒 Cycle（WaitRequest + TurnInbox）"与"Agent 生命周期 API（start/stop/restart/status/reload_config）"。`core.ask`（Turn 内等待用户回复）、环境订阅（文件监视等 `EnvironmentChanged` 事件源）、sub-agent（嵌套 Turn）本次不落地，也不预留空接口；三者在架构上均为已落地机制的直接消费者，可作为后续独立计划。
- D3 迁移路线：原地分层迁移 + 行走骨架（S1 打底，S2 交付最小可运行 Agent，S3 起逐插件恢复能力）。主机部署继续运行最后一个绿色提交的独立 checkout，直到 S5 完成。
- D4 包命名：`infra`、`runtime`、`llm` 保留顶层；新增 `kernel`、`plugins`、`environment`、`agent`、`gateway`。`llm` 不归入 `kernel`：它是模型服务，不是推理循环。
- D5 测试依赖：引入 `pytest-asyncio`（auto 模式）。
- D6 计划段归属：milestones/todos 是 agent 内在工作状态，作为内核内建 `plan` 段放在 `working` 槽并走同一段 SPI；Workspace 资源列表是插件段，同槽相邻。
- D7 文档冲突：`docs/design/loop.md`、`context.md` 中"不建立 ask/pause/awaiting 状态"的表述随收件箱设计撤销；Turn 等待成为 WaitRequest 的一等语义。
- D8 配置键：TOML section 名（`[workspace]`、`[home]`、`[capabilities.web]`、`[llm]`、`[loop.cycle]` 等）保持稳定，包布局变化不牵动项目配置；仅新增 `[agent]` 取代 `[app]`，并把 `[maintenance.schedule]` 的调度器读取搬到 environment。
- D9 Session 记录 schema 升级为 v5（通用段快照），不迁移 v4 归档；切换前应先完成所有待处理日期的 Memory 维护。

## 现状诊断

### 保留的设计资产

以下资产在本次重构中搬迁与适配，不重写：

- Action catalog TOML 四层定义（模型侧协议 / 补充语义 / 框架运行配置 / 后端）、schema 子集校验、hook 阶段化、`available = runtime.enabled && supported`、`standard/foldable` trace 生命周期、`ActionResult`/`ActionLocalFailure`/phase-level result 三类局部结果。
- 三层失败语义；`RuntimeException` 单一入口 + 稳定 reason；`RunScope`/`RuntimeTransfer(RETRY|END)`/Trap 向量表；bridge 显式映射表与 JSON payload 约束。
- Link 模型（`home:`、`memory:`、`workspace:`、`home:skills_domain:`、`home:skills_action:`）与 `home/`、`memory/`、`runtime/`、`archive/<timestamp>/` 持久布局。
- Session Turn/Summary 记录图、Summary 堆、渐进 inspect 与 continuation；Workspace manifest/revision/digest CAS、Trash、mirror；Home actual/overlay 与 review；Memory 五类 Markdown codec、多文档事务、catalog/backlinks/embedding 派生缓存、活动 `Memory.md` CAS。
- LLM 消息模型、Tool 协议与 provider 名称可逆映射、模型链/provider 链/重试策略、上下文窗口水位、各 provider adapter 的请求/响应映射逻辑（改为 async 调用）。
- 配置 catalog、ConfigEnvironment、ConfigController 候选校验与原子激活、`RuntimeHandle` 世代切换语义；Endpoint Bearer token、连接描述发布与项目实例 lease；`tinysoul init/reset` 模板生成。
- 默认 Home 内容、Skill 目录结构、Maintenance package catalog、daily lifecycle 的 pending transition/journal 恢复算法。

### 结构性问题

- P1 组合根硬编码。`tinysoul/app/builder.py`（935 行）、`tinysoul/loop/user/builder.py`、`tinysoul/loop/user/actions.py`、`tinysoul/maintenance/builder.py` 逐个 import 全部 owner Engine 与 capability，并手工调用 `register_*_actions(builder, workspace=..., home=..., bus=..., staging=..., llm_action=...)`。kernel 子包 `loop.user` 实际知道所有 owner；内核 owner 中立只停留在 `TurnRunner` 与 `build_turn_kernel` 一层。
- P2 Context 硬编码 owner 段。`ContextEngine.consume_signal_batch` 按 `SIGNAL_SESSION_SYNC`/`SIGNAL_WORKSPACE_SYNC` 分支解析并调用 `apply_session_snapshot`/`apply_workspace_snapshot`；`ContextTurnCompletion` 固定携带 `working` 与 `background_links` 字段；而 Home/Memory 走 `BackgroundEntryProvider` 协议。两种投影模式并存，Context 同时知道 Session 与 Workspace 的快照类型。
- P3 反向依赖。`context/preparation.py → loop.preparation`；`session/projection.py → loop`（Turn 准备/完成 handler 放在 owner 包内却依赖内核类型）；`capabilities/supervised_process/manager.py → loop, context`（自行等待 input/control 信号）。
- P4 事件与等待碎片化。追加输入走 `context.input.append` 信号、控制走 `loop.control.request` 信号、维护走 Program 队列、后台进程唤醒走 `TurnActivityController.wait_before_cycle` + `SignalWatch` 轮询。没有统一的 Turn 收件箱，无法表达"等待事件再进入下一个 Cycle"的通用语义。
- P5 Agent 概念分散。生命周期在 `TinySoulApp.run/run_once`，命令入口在 `AppCommandGateway`，分派在 `ProgramRunner`，世代在 `RuntimeHandle[AppRuntimeGeneration]`，状态查询只有 `EndpointRuntimeEngine.status()`；无 restart，CLI 无 status；Endpoint 通过四个 Protocol 间接描述同一 App。
- P6 Runtime bridge 反向持有业务。`runtime/bridge/{home,memory,session,workspace,shell,script,supervised_process,endpoint,app}.py` import 业务模块 errors；`maintenance` 已把 bridge 放在自己包内，两种放置方式并存。
- P7 超大门面。`workspace/engine.py` 2203、`workspace/actions.py` 1318、`context/engine.py` 1107、`home/overlay.py` 966、`app/builder.py` 935、`home/engine.py` 904、`llm/task.py` 861、`maintenance/memory/actions.py` 818、`capabilities/web/service.py` 794、`capabilities/supervised_process/manager.py` 770、`maintenance/archive/engine.py` 766、`loop/phases.py` 697。
- P8 同步 + 线程混合。Phase3 `ThreadPoolExecutor`；Terminal 与 scheduler 独立线程；uvicorn 独立线程桥接同步 gateway；`SignalBus` Lock/Condition；`RuntimeHandle` 读写锁；`llm/task.py` 用守护线程 + 0.1s 轮询模拟可取消的 provider 调用；38 个文件直接使用 threading 原语。
- P9 零散漂移。`docs/design/action.md` 仍示意 `catalog/memory/`（实际在 `core`）；`AgentHomeEngine.default_background_entries()` 近乎仅测试使用；Endpoint 构造期缓存的 `workspace`/`maintenance` 引用在 Generation 切换后可能过期；`MaintenanceScheduler` 关闭时仍起线程；`InputDispatcher` 中冗余 `assert`。

## 目标架构

### 分层与依赖规则

```text
L5 gateway      cli, endpoint http/ws v2, project init/reset
L4 agent        Agent 门面 (SDK API), 装配与插件注册表, TurnScheduler, 配置世代, 内建 user profile, 服务注册表
L3 plugins      home, memory, session, workspace, capabilities/*, maintenance
L3 environment  terminal 输入源, 定时调度器, console sink
L2 kernel       context (段 SPI / composer / heap / trace / plan), loop (turn / cycle / phase / profile / inbox / wait), action (catalog / scope / normalize / batch / results / backends), prompts, spi
L1 runtime      RunScope / Trap / Transfer / RuntimeException, events (Signal / Observation / EventBus / TurnInbox), generation handle, kernel bridges
L1 llm          messages / tools / task runner / providers (async)
L0 infra        config, json, filesystem, time, async concurrency, staging, continuation
```

依赖规则：

- 只能向下依赖。`gateway → agent`；`agent → plugins, environment, kernel`；`plugins/environment → kernel, runtime, llm, infra`；`kernel → runtime, llm, infra`；`runtime/llm → infra`。
- `kernel` 不 import 任何 plugin、environment、agent 或 gateway。
- `runtime` 不 import 业务模块；插件的 Runtime bridge 放在插件内部。
- 插件之间只允许依赖对方在包根 `__init__` 声明的公共门面类型，不依赖内部实现。当前唯一跨插件消费者是 `maintenance`（编排 session/workspace/home/memory 的日切、归档与维护 profile）。
- `gateway` 只经 `Agent` API 与 `agent.services` 暴露的类型化门面访问业务；不直接持有任何 Engine。

### 包布局

```text
tinysoul/
  infra/                      # L0；新增 asyncio 并发原语，其余保留
  runtime/                    # L1 控制协议 + 事件
    scope.py transfer.py exception.py errors.py frame_runner.py
    trap/                     # RuntimeTrap, registry, snap, handler（保留）
    events/                   # EventBus, Signal, Observation, TurnInbox, TurnEvent, EventFilter, topics
    generation/               # RuntimeHandle（改 asyncio lease）
    bridge/                   # _payload.py + context.py loop.py action.py llm.py infra.py
  llm/                        # L1 模型服务；provider/task runner 全 async
  kernel/                     # L2 owner 中立内核
    spi.py                    # Plugin, PluginRegistry, ContextSegmentProvider, TurnParticipant, TurnPreflight, TurnProfile, DailyParticipant, ServiceFacade 协议汇出
    context/
      slots.py                # SegmentSlot 与槽内排序
      segments.py             # ContextSegmentProvider 协议、SegmentPatch、SegmentSnapshot、SegmentControlTool
      shapes/                 # SnapshotSegment, HeapSegment, TraceSegment 基类
      inputs.py               # inputs 段（内核）
      plan.py                 # plan 段（内核；milestones/todos 与其控制工具）
      trace.py                # trace 段（内核；热尾 + 折叠 + inspect）
      composer.py             # MessageStack 构造
      pressure.py             # 压力回收编排（调用各段 reclaim）
      engine.py               # ContextEngine：段生命周期协调 + 批次两阶段提交
      actions.py              # core.context.inspect
    loop/
      turn.py cycle.py phases.py
      profile.py              # TurnProfile 数据与 ActionSurface 选择器
      inbox.py                # 收件箱消费、WaitRequest 处理
      completion.py outcomes.py cancellation.py config.py
    action/
      engine.py core/ backends/ builtins/core/ config.py failures.py
      catalog/core/           # 仅 core 域模板；其它域模板随各插件包发布
    prompts/                  # 框架内提示词文本与 PromptBlock 构造器
  plugins/                    # L3 业务 owner 与能力
    home/ memory/ session/ workspace/
    capabilities/{resource,web,script,shell,supervised_process}/
    maintenance/              # daily lifecycle / archive / availability / clock / home & memory maintenance profiles / package catalog
  environment/                # L3 感知与输出适配
    terminal.py               # stdin 输入源（async）
    scheduler.py              # 定时 TurnRequest 源（通用；日程由 maintenance 插件配置）
    console.py                # console Observation sink
  agent/                      # L4
    agent.py                  # Agent 门面
    assembly.py               # 显式插件清单、PluginRegistry 实现、世代构建
    scheduler.py              # TurnScheduler：串行 Turn 队列、preflight、活动 Turn 与收件箱路由
    profiles/user.py          # 内建 user TurnProfile 与 guidance
    services.py status.py config.py failures.py runtime_bridge.py
  gateway/                    # L5
    cli.py
    endpoint/                 # http/ws v2：auth, schemas, routes, events replay/journal, host
    project/                  # initializer, resetter, instance lease
  assets/
```

每个插件包内部结构统一为：`plugin.py`（`Plugin` 实现，`configure` + `contribute` + 可选 `finalize`）、`config.py`、`engine.py` 或 `service.py`（同步领域逻辑）、`segments.py`（段与 background 条目 provider）、`actions.py`（executor 与 registrar）、`participants.py`（TurnParticipant / DailyParticipant / TurnPreflight，按需）、`catalog/<domain>/`（该插件拥有的 Action TOML 模板，按需）、`failures.py`、`runtime_bridge.py`、`errors.py`。

### 核心概念修订

以下修订将写入 `AGENTS.md` 核心定义（S6）：

- Agent：进程内唯一的智能体实例，拥有配置世代、插件装配、Turn 调度与状态。对外表现为输入（TurnRequest、追加输入、控制、配置 patch）、输出（回答、Observation 流、服务门面读取）与状态变化（世代、活动、活动日）。取代原 Program/App 概念；`RunLevel.PROGRAM` 更名为 `AGENT`，`runtime.program_end` 更名为 `runtime.agent_end`。
- Environment：Agent 之外的事件来源与输出去向：终端、定时器、Endpoint 客户端、后台任务。环境经 EventBus 向 Agent 投递事件，Agent 经 Observation 与服务门面向环境输出。
- TurnProfile：一类 Turn 的完整定义：guidance、Action surface、参与的语境段 provider、completion detector、completion 到输出的映射、trap 策略追加、cycle 预算与 phase task profile。内建 `user`；`maintenance` 插件注册 `home_maintenance` 与 `memory_maintenance`。User Turn 与 Maintenance Turn 的区别只在 profile。
- 语境段/ContextSegment：Context 的组成单元，由内核或插件声明。段有槽位（`identity, inputs, history, background, trace, working, task`）、槽内序号、可选控制工具、可选压力回收。内核自有 `identity`（配置文本）、`inputs`、`trace`、`task` 与 `working` 槽内的 `plan` 段，并创建 `background` 槽的堆段；其它段由插件提供。MessageStack 顺序由槽位决定，不再由 owner 名决定。
- Background 堆：堆顶是有界线索（目录、标题、摘要），可按需向下加载或逐出。`background` 槽是内核创建的唯一堆段，条目由 Home、Memory 的 `BackgroundEntryProvider` 填充，加载/逐出经 Phase1 控制工具。`history` 槽由 Session 以 Turn 内固定的快照填充，向下追溯经 `core.session.inspect` 动作；Session 与 Trace 的渐进检查是动作而非段能力。
- TurnInbox 与 TurnEvent：活动 Turn 的收件箱。事件种类为 `InputAppended`、`ControlRequested`、`JobEvent`、`TimerFired`。内核在 Cycle/Phase 边界 drain：追加输入并入 inputs 段并写 trace note；控制请求进入 Trap；job/timer 事件路由到声明了 `on_event` 的段或参与者。
- WaitRequest：Action executor 或参与者登记的"在下一个 Cycle 前等待"意图：`until: EventFilter`、`timeout`、`extend_budget`。TurnRunner 在 Cycle 边界据此等待。`execution.wait`、`core.idle` 是消费者；`core.ask` 是 `until=InputAppended, timeout=None` 的特例。原"不建立 ask/pause/awaiting 状态"表述撤销。
- Plugin：向 Agent 注册表贡献段、background 条目、动作、Action catalog 片段、参与者、Trap 处理器、profile、事件源与服务门面的显式对象。插件清单在 `agent/assembly.py` 中静态列出，不做动态发现。装配分两阶段：declare（全部插件 `contribute`）→ resolve（注册表按依赖解析动作 registrar、服务门面与 profile，再调用可选 `finalize`）。
- Signal / Observation / Trap 三分法保留，全部落在 asyncio 原生 EventBus 上：Signal 是命名空间队列、可消费、参与业务提交；Observation 是广播、只面向外部；Trap 只处理控制流。

### 契约设计

#### Agent SDK API

`tinysoul/agent/agent.py`：

- `await Agent.create(project_root, *, overrides) -> Agent`：加载 ConfigEnvironment，运行插件 `configure`，编译 `AgentConfigPlan`，构建首个世代。
- `await agent.start()` / `await agent.stop()` / `await agent.restart()`：start 依次运行注册的 preflight（日切恢复等）、启动事件源、启动 TurnScheduler；stop 取消活动 Turn、逆序停止事件源、关闭世代；restart 为 stop + 重新 create 世代 + start。
- `agent.status() -> AgentStatus`：世代 id、活动（idle / turn / preflight）、活动 Turn 摘要、活动日、注册插件、各服务门面状态摘要。
- `await agent.reload_config(patch) -> ConfigReloadResult`：idle 时编译候选 Plan、构建候选世代、提交配置事务、原子切换 `RuntimeHandle`；沿用现 ConfigController 流程。
- `await agent.submit_turn(TurnRequest(profile, input, metadata, source)) -> TurnHandle`：进入 TurnScheduler 串行队列；`TurnHandle` 提供 `turn_id`、`await handle.outcome()`。
- `await agent.append_input(turn_id, text)`、`await agent.control(turn_id, ControlKind.STOP)`、`await agent.exit()`。
- `agent.subscribe(filter) -> AsyncIterator[ObservationEvent]`。
- `agent.services.get(ServiceType) -> ServiceType`：返回插件注册的类型化门面（Workspace 浏览/编辑、Maintenance availability、配置投影）。

TurnScheduler：单一 asyncio 任务串行消费 `TurnRequest`；每个 Turn 前运行 `TurnPreflight` 参与者取得权威 `BusinessDay` lease；活动 Turn 的收件箱由 scheduler 持有并接收 `append_input/control/JobEvent/TimerFired`；非活动期到达的追加输入按 profile 策略拒绝或转为新 TurnRequest（user profile 默认转为新 Turn）。

#### Plugin 契约

`tinysoul/kernel/spi.py`：

```python
class Plugin(Protocol):
    name: str
    def configure(self, environment: ConfigEnvironment) -> None: ...
    def contribute(self, registry: PluginRegistry) -> None: ...
    def finalize(self, assembled: AssemblyView) -> None: ...        # 可选；查看最终 domain/action identity 与服务

class PluginRegistry(Protocol):
    def context_segment(self, provider: ContextSegmentProvider, *, profiles: frozenset[str] | None = None) -> None: ...
    def background_entries(self, provider: BackgroundEntryProvider, *, profiles: frozenset[str] | None = None) -> None: ...
    def actions(self, registrar: ActionRegistrar) -> None: ...        # 延迟到 resolve 阶段执行
    def action_catalog_fragment(self, root: Path) -> None: ...        # 插件自有 domain 的 TOML 模板
    def turn_participant(self, participant: TurnParticipant, *, profiles: frozenset[str] | None = None) -> None: ...
    def turn_preflight(self, preflight: TurnPreflight) -> None: ...
    def trap_handler(self, reason: str, handler: TrapHandler, *, profiles: frozenset[str] | None = None) -> None: ...
    def turn_profile(self, profile: TurnProfile) -> None: ...
    def daily_participant(self, participant: DailyParticipant) -> None: ...
    def event_source(self, source: EventSource) -> None: ...
    def scheduled_requests(self, source: ScheduledRequestSource) -> None: ...
    def service(self, facade_type: type[T], facade: T) -> None: ...
```

- 适用性与覆盖规则：`profiles=None` 表示默认，对所有 profile 生效；同一 `segment_id`、同一 background owner 或同一 Trap reason 的 profile 专属注册覆盖默认注册。profile 专属 provider（actual Home、`memory:target`、归档 Session/Workspace 视图）由拥有该 profile 的 `maintenance` 插件使用 owner 公共门面注册，Home/Memory/Session/Workspace 插件不知道维护 profile 名。
- 两阶段装配：`contribute` 只声明；注册表在全部插件声明完成后进入 resolve，先建立服务门面表与合并 catalog（项目 catalog + 各插件 fragment），再以 `ActionRegistrationContext`（bus、observations、llm_action runner、staging、reference resolvers、skill providers、`services`）依次调用各 `ActionRegistrar`，最后调用各插件可选 `finalize(AssemblyView)`。插件清单顺序因此不构成依赖。`finalize` 的现有消费者：Home 的 prompt mount reconcile、supervised_process 的"是否仍有 run 动作"判定。
- 每个插件自带 `failures.py` 与 `runtime_bridge.py`，在自身边界 raise 时使用；Trap 与 outcome 归类只读取异常 payload，不需要注册 bridge。`runtime/bridge/` 只保留 `_payload` 与内核模块 bridge。
- 线程规则：同步 owner 引擎不触碰 EventBus、TurnInbox 或任何 asyncio 对象；Signal 与 Observation 只在 async 适配层于 `to_thread` 返回后发出。
- Action catalog 模板所有权：`kernel/action/catalog/core/` 只含 core 域；`workspace/home/memory/web/execution/maintenance` 域 TOML 随各插件包发布并经 `action_catalog_fragment` 声明。`tinysoul init/reset` 从内核 core + 已装配插件 fragment 合成项目 `configs/action/catalog`；运行时仍以项目 catalog 为唯一事实，插件 fragment 中标记为 package-only 的域（当前只有 `maintenance`）不物化到项目、只在运行时合并。

#### Context 段 SPI

`tinysoul/kernel/context/segments.py`：

```python
class ContextSegmentProvider(Protocol):
    segment_id: str                 # 如 "session.history", "workspace.resources", "plan"
    slot: SegmentSlot
    order: int
    async def prepare(self, turn: TurnInfo) -> None: ...            # Turn 前建立初始状态
    def stage(self, patch: SegmentPatch) -> StagedChange: ...       # 解析并校验，不改状态
    def commit(self, staged: Sequence[StagedChange]) -> None: ...
    def render(self) -> tuple[Message, ...]: ...
    def seal(self) -> JsonObject: ...                               # Turn 结束快照
    # 可选能力
    def control_tools(self) -> tuple[SegmentControlTool, ...]: ...  # 现有消费者：plan、background 堆
    def apply_control(self, call: ToolCallRecord) -> StagedChange | ControlResult: ...
    def reclaim(self, required_chars: int) -> int: ...              # 现有消费者：trace、background 堆、workspace.resources
    async def complete(self, completion: TurnCompletion) -> None: ...  # 现有消费者：session.history
```

- `ContextEngine` 收缩为：按槽位与序号排列段；`begin_turn` 时按 profile 选出参与段并并行 `prepare`；`compose` 时依序 `render` 并叠加 TaskPrompt；边界批次消费 `context.<segment_id>` 命名空间 Signal 与 Phase1 控制调用，先对全部段 `stage`，全部成功后依序 `commit`，任一失败则丢弃全部 staged 并返回局部 ControlResult，Trap 重放同一批次时不留半提交；`control_scope` 聚合声明了控制工具的段；`reclaim_pressure` 按段声明的可回收性调用 `reclaim`；`end_turn` 汇总 `seal()` 为 `TurnCompletion.segments: {segment_id: json}`。
- 内核段：`identity`（`[agent]` 配置的身份文本）、`inputs`（初始输入 + 收件箱追加）、`plan`（milestones/todos，控制工具 `plan.patch`）、`background`（唯一堆段：目录条目 + 可加载/可逐出内容 + `load/evict` 控制工具，条目来自注册的 `BackgroundEntryProvider`）、`trace`（TurnTraceHeap，热尾/折叠；`core.context.inspect` 是内核动作）、`task`（每次 LLM Task 的 overlay，不是持久段）。
- 内核提供 `SnapshotSegment` 基类（整体替换；`stage` 解析完整快照）供插件段复用；堆与 trace 是内核实现，不作为可复用基类暴露。
- 插件段：`session.history`（Snapshot，`history` 槽，Turn 内固定）、`workspace.resources`（Snapshot，`working` 槽 order 在 `plan` 之后）；Home 与 Memory 以 `BackgroundEntryProvider` 向 `background` 堆提供条目（默认加载、不可逐出、可逐出、可加载四类沿用现有 catalog 语义）。
- 段 Signal：插件在 Action 成功后发出 `SegmentPatch` Signal（如 Workspace 提交后发出 `context.workspace.resources` 快照）；内核只按 `segment_id` 路由，不解析 payload。

#### TurnProfile

```python
@dataclass(frozen=True)
class TurnProfile:
    name: str
    guidance: tuple[str, ...]
    action_surface: ActionSurface               # include/exclude domain 与 action identity 的谓词
    completion: TurnCompletionDetector
    completion_to_output: Callable[[JsonObject | None], TurnOutput | None]
    turn_settings: TurnSettings                 # max_cycles 等
    cycle_settings: CycleSettings               # phase1/phase2 task profile
    accepts_appended_input: bool
```

- Action surface 在合并 catalog（项目 catalog + 插件 `action_catalog_fragment`）上求值，再与 activation/support 求交，形成该 profile 的 effective catalog；Phase1/Phase2 只看该视图。
- `user`：全部非 `maintenance.*` 动作，`core.answer` 完成，输出用户回答。
- `home_maintenance`/`memory_maintenance`：精确 include 列表，`maintenance.complete` 完成，无用户输出。
- 每个 profile 的 Context 由该 profile 适用的段 provider 装配；每次 Turn 重建。

#### 事件、收件箱与等待

`tinysoul/runtime/events/`：

- `EventBus`：asyncio 原生，单事件循环。提供 `publish_signal(Signal)`、`consume_namespace(ns) -> tuple[Signal, ...]`、`publish_observation(ObservationEvent)`、`subscribe_observations(filter) -> AsyncIterator`。删除线程版 `SignalBus`、`SignalWatch`。
- `TurnInbox`：每个活动 Turn 一个；`put(TurnEvent)`、`drain() -> tuple[TurnEvent, ...]`、`await wait(filter, timeout) -> TurnEvent | None`。
- `TurnEvent` 联合：`InputAppended(text, source, received_at)`、`ControlRequested(kind)`、`JobEvent(job_id, kind, payload)`、`TimerFired(timer_id)`。
- 内核边界处理：Phase 边界与 Cycle 边界各 drain 一次；`InputAppended` 并入 inputs 段并追加 trace note `input_received`；`ControlRequested(stop|exit)` 构造 `RuntimeException(runtime.turn_end | runtime.agent_end)` 进 Trap；`JobEvent`/`TimerFired` 分发到该 profile 登记的 `TurnParticipant.on_event`，参与者返回的 `SegmentPatch`（通常是 trace note）进入同一批次。段本身不接收事件。
- `TurnParticipant`：`on_turn_start(turn)`、`on_event(event) -> SegmentPatch | None`、`after_cycle(turn) -> WaitRequest | None`、`on_cycle_budget_exhausted(turn) -> bool`、`on_turn_end(turn)`，全部可选。现有消费者：supervised_process（事件、等待、额外 Cycle、清理）、session（Turn 记录经段 `complete`，不用参与者）。
- `WaitRequest(until, timeout, extend_budget)`：由 `ActionExecutionContext.turn.request_wait(...)` 或 `TurnParticipant.after_cycle` 登记；TurnRunner 在 Cycle 边界若存在未满足的 WaitRequest，`await inbox.wait(until, timeout)`；`extend_budget=True` 时在参与者声明的上限内允许超出 `max_cycles`。取代 `TurnActivityController`。
- `supervised_process` 插件：进程输出/退出经 `ActionExecutionContext.turn.inbox_put(JobEvent)` 投递到活动 Turn 收件箱；`execution.wait` 登记 `WaitRequest(until=JobEvent(job_id), timeout=wait_seconds)`；Turn 结束由 `TurnParticipant.on_turn_end` 清理；删除其对 loop/context 的 import。
- `EventSource`：随 Agent 启停、向 TurnScheduler 投递 `TurnRequest` 或控制的长运行源。现有消费者：terminal、定时调度器。`ScheduledRequestSource`：由 `environment/scheduler.py` 的通用定时器按插件声明的日程触发，到期时返回零到多个 `TurnRequest`；现有消费者：`maintenance` 的每日维护（先 `home_maintenance`，再按 availability 决定是否追加昨日 `memory_maintenance`）。人工 `/maintenance daily` 与 Endpoint 的等价请求经 `MaintenanceService.plan_daily()` 得到同一组 `TurnRequest` 再提交，gateway 不解释 eligibility。

#### Action 框架（async）

- `ActionEngine` 门面 API 保持：`phase1_scope`、`phase2_scope`、`normalize`、`prepare_batch`、`run_batch`、渲染门面。`run_batch` 改 async。
- `ActionBatchRunner`：每个 execution 一个 `asyncio.Task`，并行组用 `asyncio.wait(FIRST_COMPLETED)` 观察；单调用超时用 `asyncio.timeout`；首个 `RuntimeException`/`RuntimeTransferInterrupt` 出现时取消同组其余任务、等待其取消收敛、原样上抛；不使用 `TaskGroup`（避免 `ExceptionGroup` 包裹破坏 Trap 单一异常入口）。
- `ActionExecutor.execute` 改 `async`。native executor 内触盘的 owner 引擎调用经 `to_thread`；无法中途取消的线程任务在超时后按现有语义标记泄漏风险并阻断后续执行组。
- `subprocess` 后端改 `asyncio.create_subprocess_exec`；`ManagedProcess` 的进程树终止逻辑保留（Windows `taskkill /T /F`，POSIX process group）。
- `llm_action` 共享服务改 async；deadline 预留与迟返复检语义保留。
- `ActionExecutionContext` 增加 `turn: TurnFacet`（`request_wait`、`inbox_put(JobEvent)`、`turn_id`、`business_day`），删除 `cancelled` 回调（由 asyncio 取消承担）。

#### asyncio 与取消模型

- 单事件循环运行于主线程：`asyncio.run(agent_main())`；uvicorn 以 `Server.serve()` 任务运行在同一循环；stdin 读取经 `run_in_executor`；scheduler 用 `asyncio.sleep`。
- LLM provider adapter 使用 `AsyncOpenAI` 与 `httpx.AsyncClient`；`_invoke_provider` 的守护线程轮询删除，改为 `asyncio.wait_for(provider.invoke(...), remaining)`。
- Turn stop：收件箱控制事件在 Phase 边界检查；Phase 内 in-flight await 运行于 Turn 级 `asyncio.Task`，stop/exit 时 cancel 该任务，`CancelledError` 在 Phase frame 边界转换为 `RuntimeException(runtime.turn_end)` 进 Trap；Agent stop 先取消活动 Turn 任务，再逆序停止事件源与服务。
- `except Exception` 不捕获 `CancelledError`（BaseException）；模块内不得 `except BaseException` 吞取消，除非立即 re-raise。
- `RuntimeHandle` 读写 lease 改为 asyncio 原语（读者计数 + `asyncio.Condition`）；owner 引擎内部锁保持 threading（其方法在 `to_thread` 线程中执行）。
- `RuntimeModuleRunner`（可重放 Module frame）改 async。

#### 失败语义

三层失败语义不变：局部结果 → 模块边界异常 → Runtime 语义异常。变化只有：

- 插件 bridge 移入插件并经注册表登记；Trap 向量表由 agent 装配时按 profile 合并内核处理器与插件处理器。
- `runtime.program_end` 更名 `runtime.agent_end`；`RunLevel.PROGRAM` 更名 `AGENT`。
- 新增的 asyncio 取消在 Phase frame 边界归类为 `runtime.turn_end`（用户 stop）或 `runtime.agent_end`（exit），不是失败；超时归类为局部结果。

#### Endpoint v2

`tinysoul/gateway/endpoint/`，重写 `docs/endpoint/`：

- `GET /v2/health`（匿名）；其余 Bearer token。
- `GET /v2/agent`（AgentStatus）；`POST /v2/agent/restart`；`POST /v2/agent/reload`（配置 patch，取代 `PATCH /v1/config` 的激活语义，配置读取仍在 `/v2/config`）。
- `POST /v2/turns {profile, input, metadata}` → `{turn_id}`；`GET /v2/turns/{id}`（状态、outcome 摘要）；`POST /v2/turns/{id}/inputs`；`POST /v2/turns/{id}/control {kind}`。维护经 `profile=home_maintenance|memory_maintenance` 提交；`GET /v2/maintenance` 只读 availability。
- `GET /v2/events?after=&topics=&levels=`（replay）；`WS /v2/events`（流，首帧鉴权 + 过滤参数）。
- `GET /v2/config`、`GET /v2/config/catalog`、`GET /v2/config/actions`、`PATCH /v2/config`（写文件事务；激活由 `/v2/agent/reload` 或自动 idle 激活完成，二选一在 S5 定稿并写入文档）。
- `/v2/workspace/*` 经 `agent.services.get(WorkspaceService)`；写操作后由 Workspace 服务自行发出段 Signal。
- 连接描述发布、实例 lease、事件缓冲与 NDJSON journal 保留并搬入 gateway。

#### Prompts

`tinysoul/kernel/prompts/`：集中框架内提示词文本（Phase1/Phase2 task prompt、控制工具描述、profile guidance 模板、PhaseFailure 反馈模板）与 `PromptBlock` 构造器。插件动作内部提示词留在插件，但使用同一构造器。

## 可行性分析

基于当前实现逐层评估：

- 内核层（`loop` 3.6k + `context` 4.0k + `action` 5.9k 行）：`TurnRunner`/`CycleRunner`/`Phase*Unit` 已 owner 中立，async 化与收件箱接入是结构内改写；`ContextEngine` 需按段 SPI 重写（1107 行拆为 engine/composer/pressure/shapes），`TurnTraceHeap`、`WorkingContext`、`BackgroundContext`、controls、compressor 的算法保留；Action core 中 catalog/loader/schema/hooks/result/rendering 保留，runner 重写为 asyncio，backends 改 async。风险集中在批次并发取消语义与 Trap 单一异常入口的兼容。
- LLM（6.5k 行）：openai SDK 提供 `AsyncOpenAI`，各 adapter 的请求/响应映射函数不变，只改调用链；`task.py` 删除线程轮询后体量下降；模型链/重试算法不变。风险低。
- 持久 owner（`workspace` 6.7k + `home` 4.6k + `memory` 3.7k + `session` 2.3k 行）：存储引擎按 D1 保持同步，整体搬迁；需要重写的是集成边界：`actions.py`（registrar 改为 `ActionRegistrar` 回调并 `to_thread`）、`background.py`/`projection.py`（改为段 provider）、`session/projection.py` 与 `context/preparation.py` 的 handler（改为 `prepare/complete`）。`workspace/engine.py` 借搬迁拆为 read/write/bundle/trash/archive 服务 + 门面。风险在 Session schema v5 与 `TurnCompletion.segments` 的字段映射。
- 能力层（8.4k 行）：Resource/Web 的进程 worker 与协议不变；Script/Shell 的 handler 保留；`supervised_process/manager.py` 需重写等待与生命周期（JobEvent + WaitRequest），是能力层最大改动。Web 的 crawlee worker 在子进程内自行 `asyncio.run`，不受影响。
- 外层（`app` 3.5k + `endpoint` 2.1k + `maintenance` 3.9k 行）：`app` 被更小的 `agent` + `environment` 取代（builder 的装配逻辑转为插件 `contribute`；program/gateway/inputs 转为 TurnScheduler 与 Agent API）；`endpoint` 路由与 schema 重写，auth/lease/buffer/journal 搬迁；`maintenance` 的 archive/availability/clock/task/controller 搬迁为插件，`builder.py` 替换为 `plugin.py`，两个 profile 注册到内核 profile 表。
- 测试（885 个用例）：infra/llm/runtime/持久 owner 的存储与算法测试在 import 路径与 async 标记调整后保留；loop/context/action runner/app/endpoint/maintenance builder 测试重写；新增 spi、inbox、wait、profile、agent api、endpoint v2 契约测试；fake-provider CLI E2E 从 S2 起作为门禁。
- 配置：section 名保持稳定（D8），`infra/config/catalog/*.toml` 中的 UI 描述只需增删 `[agent]`/`[app]`；`pyproject` package-data 路径随包布局更新。

主要风险与对策：

- R1 asyncio 传染与 `to_thread` 纪律。对策：插件适配层统一规则"触盘即 `to_thread`"，在 `kernel/spi.py` 文档与插件模板中固定；typecheck 对 `async def` 内直接调用 owner 引擎的写法无自动检测，S3 每个插件评审时作为专项检查项。
- R2 取消与超时语义回归（deadline 预留、迟返复检、泄漏标记、并行组阻断）。对策：先把现有 `tests/action/test_runner*` 的行为契约整理为 async 版本再改 runner；批次 runner 不用 `TaskGroup`。
- R3 Windows 事件循环。对策：使用默认 `ProactorEventLoop`，`asyncio.create_subprocess_exec` 与 `taskkill` 已验证可用；stdin 经 executor 读取。
- R4 Session v5 与旧归档。对策：D9；切换前完成待处理 Memory 维护；新代码对 v4 归档报告"归档存在但 schema 不支持"，不静默跳过。
- R5 前端在 v2 完成前不可用。对策：S5 一次性交付 v2 与 `docs/endpoint/`，并在 `docs/endpoint/frontend-integration.md` 给出 v1→v2 对照。
- R6 范围蔓延。对策：D2 之外的新行为不进入本计划；每个阶段的子计划在开始前写入 `docs/analysis/`。
- R7 `RuntimeTransferInterrupt` 跨任务传播。对策：只在 Phase3 并行 worker 内捕获并回传原异常对象，由 runner 在主任务 re-raise。
- R8 profile 名作为跨模块字符串。对策：profile 名仅由拥有它的插件定义并导出常量；`maintenance` 使用 owner 公共门面注册 profile 专属 provider，owner 插件不引用维护 profile 名。

## 分阶段实施

每阶段在开始前写入独立子计划 `docs/analysis/2026MMDD-<stage>-execution-plan.md`，完成后按文档规则标记 done 并归档；本主计划只勾选阶段。每阶段门禁：聚焦测试 → `.\scripts\test.ps1` → `.\scripts\test.ps1 -Suite Full` → `.\scripts\typecheck.ps1`；S2 起 fake-provider CLI E2E 必须通过。

- [ ] S0 文档与冻结：本计划定稿；新建 `docs/design/architecture.md`（分层、依赖规则、插件契约、段 SPI、事件与等待、asyncio 与取消、profile、Endpoint v2 概览）；回写 D1–D9 确认结果。不改代码。
- [ ] S1 基础层 async 化：`infra/concurrency.py` 改为 asyncio 原语并保留线程 RW lock 供 owner 引擎；`runtime/events/` 新建 EventBus/Signal/Observation/TurnInbox/TurnEvent/EventFilter，删除 `runtime/signals/`；`RuntimeHandle` 改 asyncio lease；`RunLevel.PROGRAM→AGENT`、`runtime.program_end→runtime.agent_end`；`runtime/bridge/` 只保留 `_payload` 与 context/loop/action/llm/infra；`llm` provider/task runner 全 async 并删除 `_invoke_provider` 线程轮询；引入 `pytest-asyncio`；重写 `tests/{infra,runtime,llm}`。
- [ ] S2 内核与最小 Agent（行走骨架）：新建 `kernel/{spi,context,loop,action,prompts}`；新建 `agent/{agent,assembly,scheduler,profiles/user,status,config,failures,runtime_bridge}`、`environment/{terminal,console}`、`gateway/cli.py`（`start`、`start --once`、`status`）；最小插件清单只含内核 builtins core（`core.answer`、`core.reason`、`core.context.inspect`）；删除 `loop/`、`context/`、`action/`、`app/`；fake-provider CLI E2E 恢复。
- [ ] S3 插件迁移（按依赖序，每插件一个子计划）：`session`（history 段、`complete` 记录 v5、`core.session.inspect`）→ `workspace`（拆分 engine、resources 段与 `reclaim`、动作与 `catalog/workspace/`、Trash 恢复 Trap 处理器、WorkspaceService 门面）→ `home`（background 条目、skill providers、动作与 `catalog/home/`、runtime copy Trap、prompt mount reconcile 移入 `finalize`）→ `memory`（current/latest 条目、三个动作、embedding 装配）→ `maintenance`（clock、daily lifecycle 与 DailyParticipant、TurnPreflight、MaintenanceService 与 `plan_daily`、两个 profile 及其覆盖默认的专属 provider、package-only `catalog/maintenance/`、`ScheduledRequestSource`、动作）→ `capabilities/*`（resource、web 与 `catalog/web/`、script、shell 与 `catalog/execution/`、supervised_process 的 JobEvent + WaitRequest + `finalize` 重写）。每步删除对应旧路径与 `runtime/bridge` 旧文件；`init/reset` 的 catalog 合成随插件 fragment 增加逐步完整。
- [ ] S4 环境与 Agent 完整化：`environment/scheduler.py`（通用定时 TurnRequest 源，`maintenance` 插件提供日程与 profile）；`agent.services`、`agent.status`、`reload_config`、`restart`；Observation 路由与 console sink 迁入 environment；`[agent]` 取代 `[app]`；删除 `app/` 残余。
- [ ] S5 Gateway v2：`gateway/endpoint` 路由、schema、事件 replay/流、host、auth；`gateway/project`（initializer、resetter、instance lease）；重写 `docs/endpoint/*` 并给出 v1→v2 对照；删除 `endpoint/`。
- [ ] S6 收尾：`docs/design/` 重组为 `architecture.md`、`runtime.md`、`llm.md`、`infra.md`、`kernel/{context,loop,action,prompts}.md`、`plugins/{home,memory,session,workspace,maintenance,capabilities}.md`、`agent.md`、`environment.md`、`gateway.md`；`AGENTS.md` 重写"核心定义"（Agent、Environment、TurnProfile、语境段、Heap、TurnInbox、WaitRequest、Plugin）、"项目规约"（六层与依赖规则、插件包结构）、"运行控制"（Agent/TurnScheduler 取代 Program）、"测试约定"（`tests/<layer>/<module>/test_<切面>.py`）与"当前任务"；`tests/` 镜像新布局；`pyproject` package-data；本计划标记 `done`、加入 `-done-` 并移动至 `docs/analysis/done/`。

## 预期改动

新增：

- `docs/design/architecture.md`；`tinysoul/kernel/**`；`tinysoul/agent/**`；`tinysoul/environment/**`；`tinysoul/gateway/**`；`tinysoul/plugins/**`；`tinysoul/runtime/events/**`；`docs/design/kernel/`、`docs/design/plugins/`、`docs/design/{agent,environment,gateway}.md`；`tests/{kernel,agent,environment,gateway,plugins}/**`。

搬迁并适配：

- `tinysoul/{home,memory,session,workspace}/` → `tinysoul/plugins/<name>/`；`tinysoul/capabilities/` → `tinysoul/plugins/capabilities/`；`tinysoul/maintenance/` → `tinysoul/plugins/maintenance/`；`tinysoul/action/{core,backends,builtins,catalog}` → `tinysoul/kernel/action/`；`tinysoul/context/{trace,working,background,controls,compress,composer}` 算法 → `tinysoul/kernel/context/`；`tinysoul/endpoint/{http/auth,events/*,host}` → `tinysoul/gateway/endpoint/`；`tinysoul/app/{initializer,instance}` → `tinysoul/gateway/project/`；`tinysoul/app/sources/*`、`outputs.py` → `tinysoul/environment/`。

删除：

- `tinysoul/app/`、`tinysoul/loop/`、`tinysoul/context/`（旧）、`tinysoul/action/`（旧）、`tinysoul/endpoint/`、`tinysoul/runtime/signals/`、`tinysoul/runtime/bridge/{home,memory,session,workspace,shell,script,supervised_process,endpoint,app}.py`、旧顶层 owner 包；对应旧测试。

文档：

- `AGENTS.md`（核心定义、项目规约、运行控制、测试约定、当前任务）；`docs/design/*`（全部重组）；`docs/endpoint/*`（v2）。

## 测试策略

- 目录镜像新布局：`tests/<layer>/<module>/test_<切面>.py`；`tests/support/` 提供 fake provider、内存 EventBus 观察器、最小插件与 profile fixture。
- 契约优先：段 SPI 两阶段提交与重放、收件箱 drain/wait 与控制进 Trap、profile 的 Action surface 与 Context 装配、批次并发取消与超时、Trap 转移与失败归类、Agent API 生命周期与世代切换、Endpoint v2 请求/响应/事件流。
- owner 存储与算法测试保留并改 import；不固化提示词文案、默认 Home 内容与 catalog 清单。
- E2E：无网络 fake-provider CLI（S2 起）、旧日 Turn → 日切 → 维护 → 新日 Background 的 App E2E（S3 maintenance 后恢复）、wheel 隔离安装与 `tinysoul init`（S5 后恢复）、真实 provider smoke 保持 external。

## 验收

- `tinysoul start` 在 asyncio 单事件循环内同时运行 Terminal、Endpoint v2 与定时调度，`start --once`、`status`、`init`、`reset` 可用。
- 任一 `kernel` 模块不 import `plugins/environment/agent/gateway`；`runtime` 不 import 业务模块；`gateway` 不直接持有 Engine。用静态 import 检查测试固定这三条规则。
- 新增或移除一个插件只改 `agent/assembly.py` 的插件清单与该插件包；内核与其它插件不变。
- Context MessageStack 顺序由槽位决定；Session、Workspace、Home、Memory 的投影均通过段 SPI 或 background 条目 provider 进入，`kernel/context` 中不出现任何 owner 类型。
- 追加输入、stop/exit、后台进程事件、定时唤醒全部经 TurnInbox；`execution.wait` 经 WaitRequest 实现，不存在 `TurnActivityController`。
- 三层失败语义、Trap 转移、bridge payload 约束的既有测试语义全部保留并通过。
- `kernel/spi.py` 中每个协议方法与注册表方法在仓库内至少有一个真实消费者；本计划已据此删除 `shape`、段级 `inspect`/`on_event`、`registry.runtime_bridge` 与 Home identity provider。
- Full 门禁与 typecheck 通过；`docs/design/`、`docs/endpoint/`、`AGENTS.md` 与代码一致。

## 实施结果

待填写。
