# 分层 Agent 架构总体重构方案与执行计划

状态：`in_progress`（方案已定稿，S0 完成；阶段进度见第 10 节，决策记录见第 9 节）

本文件同时是设计方案与执行计划。1–8 节阐述重构性质、设计意图、统一语义、架构与契约、与现有模块的联系、可行性和开放问题；9–12 节记录决策、分阶段实施、测试与验收。方案在与维护者的讨论中持续修订，修订点在第 9 节留痕。


## 0. 最初重构思路
初步思路是，对现有代码的层次进一步划分，上下层次之间提供 agent/sdk api 风格的清爽调用和依赖解耦，不同功能范畴之间提供插件式的通用注入和内聚能力可维护、可替换性。

以 agent 概念出发，将一切定义为输入、输出和 agent 状态的改变；例如，app/gateway 通过接口输入配置启动 agent /重启/查询状态，以及发起一次 turn（用户对话、记忆维护、home 维护）；将 agent 置于运行环境之中，可以看作一个事件驱动的系统（可以考虑 dds 消息的解耦），使得 agent 能够收集感知环境状态、对环境进行操作，也可以接收用户追加输入，订阅环境发生的变更，暂停 agent turn 并于用户交流对话，执行脚本或 shell 指令或派遣 sub-agent，对于后台任务以一定间隔唤醒自己的下一个 cycle，或者等待后台任务发出的事件来激活下一个 cycle。

进一步地，考虑 agent 内部封装，kernel 依然是 turn-cycle-stage-loop 和 context 语境维护；其中，background context 在 before turn 即有所准备，且允许在 turn 期间通过 异常触发（如上下文压缩）或 stage1 tool 变更，background context 呈现堆的形态（冰山理论），堆顶是线索，并可向下按需追溯； interaction trace 以栈的形态，在当前 turn 运行中的追加新的消息；workspace 呈现最新的工作状态（可用的本地资源、待办和里程碑，里程碑类似寄存器一样的备忘数据或真实值）；
在 agent 内部另一个关键架构设计是，kernel 负责利用 context 中不同的语境段，但 kernel 本身不需要知道和维护 context 不同语境段的内容和含义；依赖反转，外围插件式申明 context 语境段内容和 kernel 的使用方法（turn 前/中/后），并在外围模块内部维护属于这个段的相关内容和结构，内容的维护和管理依靠外围具体的功能模块。



## 1. 重构性质与授权范围

这是一次全面、彻底、不向后兼容的整体重设计，不是模块内重构，也不是渐进兼容迁移。

授权范围覆盖项目内一切设计：

- `AGENTS.md` 的核心定义、项目规约、运行控制、代码风格与测试约定可以改写；其中与本方案冲突的表述（如"不建立 ask/pause/awaiting 状态"、Program/App 概念、按 owner 名固定的 MessageStack 顺序、`runtime/bridge/` 集中放置业务 bridge、"需要跨 Cycle 监督的外部任务只保留 Turn-scoped job"）直接撤销或替换。
- `docs/design/` 全部按新架构重组；旧设计文档只作为理解历史意图与保留资产的材料。
- 包布局、模块名、公共门面签名、Runtime 原因标识、Session 记录 schema、Endpoint 协议、Action 域划分、测试目录与 `pyproject` 打包元数据全部可变。
- 旧测试不构成保留旧边界的理由；与新架构冲突的测试改写或删除。
- 唯一有意保持稳定的是用户项目侧的 TOML section 名与持久目录布局（`home/`、`memory/`、`runtime/`、`archive/`），因为它们属于用户数据而非代码结构（D8）。

判断标准只有一个：新架构是否在整体逻辑上干净、清晰，在空间上把现有设计与功能纳入统一语义，在时间上支撑长期迭代与扩展。不以工作量、测试兼容或"当前暂无消费者"为由拒绝合理抽象，也不以"未来可能需要"为由预留没有语义的空壳。

## 2. 设计意图与愿景对照

原始构想拆成八项，逐项给出设计回应与达成状态。`本次落地` 指在本计划阶段内完成；`本次落地·后续扩展` 指机制与首个消费者本次完成、更多消费者按独立计划追加。

| # | 原始构想 | 设计回应 | 状态 |
|---|---|---|---|
| 1 | 层次进一步划分，上下层 agent/sdk api 风格调用，依赖解耦 | 六层单向依赖；`Agent` 门面是 L5 唯一入口；插件经 `PluginRegistry` SPI 注入；三条 import 规则由测试固定 | 本次落地 |
| 2 | 不同功能范畴插件式注入，内聚、可维护、可替换 | 每个 owner/能力是一个 `Plugin`，声明段、动作、catalog 片段、Trap 处理器、profile、事件源、触发器、Job 种类、服务门面；增删插件只改插件清单 | 本次落地 |
| 3 | 以 agent 出发，一切是输入、输出与状态改变 | `Agent` API 只暴露输入（TurnRequest、追加输入、控制、配置 patch、环境事件）、输出（TurnOutput、Observation 流、服务读取）与状态（世代、活动、业务日、Job 表） | 本次落地 |
| 4 | Agent 置于环境中，事件驱动，DDS 式解耦 | 单一 asyncio `EventBus` 以 topic 组织事件；`EnvironmentEvent` 协议、静态/动态事件源、`EventRouter` 路由到收件箱或触发器；三种投递语义对应既有 Signal/Observation/Trap 三分法 | 本次落地 |
| 5 | 接收追加输入、订阅环境变更、暂停 Turn 与用户对话 | 追加输入进收件箱；段 `subscriptions()` 与 `TurnTrigger` 两级订阅；Workspace 文件监视是首个环境事件源；`core.ask` 暂停 Turn 等待回复 | 本次落地 |
| 6 | 执行脚本/shell、派遣 sub-agent、按间隔或事件唤醒下一 Cycle | Job 框架统一后台进程、外部 ACP agent 与内部嵌套 Turn；`WaitRequest(until, timeout)` 统一事件唤醒与定时唤醒；agent 级 Job 完成可触发新 Turn | 本次落地 |
| 7 | 内核仍是 turn-cycle-stage-loop 与语境维护；background 冰山、trace 栈、workspace 最新状态与寄存器式里程碑 | 段形状一等概念：Heap / Stack / State；`plan` 段 milestone 为带状态、值、来源、版本的寄存器；`jobs`、`expand.tools` 段是 State 形状的新成员 | 本次落地 |
| 8 | 依赖反转：外围声明段内容与内核使用方法，内核不知内容 | 段协议 `open`（前）/`stage·commit·on_event·reclaim·inspect`（中）/`seal·close`（后）；内核只知槽位、形状与 ref scheme | 本次落地 |
| 9 | MCP 通用工具接入（`00 doing something.md`），避免 tool schema 过大 | `expand` 域：MCP 网关服务 + `expand.search/describe/call` + `expand.tools` 钉选段；模型自己策展可见工具集 | 本次落地·后续扩展 |

## 3. 统一设计语义

### 3.1 Agent：输入、输出与状态

Agent 是进程内唯一的智能体实例。

- 输入：`TurnRequest(profile, input, metadata, source)`、`InputAppended`、`ControlRequested(stop|exit)`、`ConfigPatch`、`EnvironmentEvent`。
- 输出：`TurnOutput(kind=answer|question, text)`、Observation 流、服务门面读取。
- 状态：配置世代、活动（`idle | preflight | turn | awaiting_input`）、业务日、Job 表、注册插件与服务状态摘要。

Agent 取代 Program/App。`RunLevel.PROGRAM → AGENT`，`runtime.program_end → runtime.agent_end`。

### 3.2 事件与环境协议

一条 asyncio 总线，事件以 topic 命名。三种投递语义对应既有三分法：

- Signal：命名空间队列，由拥有协议的模块在边界批次消费，参与业务提交。段 patch、收件箱事件是 Signal。
- Observation：广播、JSON 安全、只面向外部；normal / verbose / model 三级。所有环境事件以 verbose 级镜像为 Observation，供前端与 journal 回放。
- Trap：不是事件；收件箱中的控制事件在 Phase 边界转 `RuntimeException`。

`EnvironmentEvent` 是 Signal 的一个子类型，表达"环境中发生了什么"：

```python
@dataclass(frozen=True)
class EnvironmentEvent:
    topic: EventTopic          # 分级点分名，如 job.<id>.exited、fs.workspace.changed、schedule.daily.due、mcp.<server>.resource_updated
    source: SourceId           # 发布者身份
    occurred_at: datetime
    payload: JsonObject        # JSON 安全；typed 转换在消费者一侧
    turn_scope: TurnId | None  # 归属 Turn；None 表示 agent 级
```

事件源分两类，同一注册接口：

- 静态源：随 Agent 启停，插件在 `contribute` 中经 `registry.event_source` 声明（终端、调度器、Workspace 文件监视、MCP 服务器订阅流）。
- 动态源：运行期由 owner 注册/注销（每个 Job 是其 `job.<id>.*` 的源；每个 MCP 连接是其 `mcp.<server>.*` 的源）。`EventRouter.register_source(descriptor)` / `unregister_source(id)`。

`EventRouter`（agent）对每个事件按序判定：

1. `turn_scope` 指向活动 Turn → 投递该 Turn 收件箱。
2. 否则匹配 `TurnTrigger(filter, plan)` → `plan(event) -> TurnRequest...` 进入 TurnScheduler 队列。
3. 否则仅保留 Observation 镜像。

`EventFilter`：topic 通配 + 可选 `turn_scope` + 可选 payload 谓词；收件箱 `wait`、段 `subscriptions()`、`TurnTrigger` 共用。

`TurnInbox` 是活动 Turn 对其命名空间的类型化视图：`drain()`、`wait(filter, timeout)`。收件箱事件种类：`InputAppended`、`ControlRequested`、`EnvironmentEvent`。

topic 分类（当前消费者）：`input.*`（终端/Endpoint）、`control.*`、`schedule.<name>.due`（maintenance 触发器）、`fs.workspace.changed`（`workspace.resources` 段）、`job.<id>.*`（`jobs` 段、`core.job.wait`、agent 级 Job 触发器）、`mcp.<server>.*`（`expand` 网关刷新工具索引与资源订阅）。

### 3.3 Turn 与 TurnProfile

Turn 是一项完整 work；Cycle 由 Phase1/2/3 组成；骨架不变。

User Turn 与 Maintenance Turn 的差异收敛为 `TurnProfile`：guidance、Action surface、参与段集合、completion detector、completion 到 `TurnOutput` 的映射、Trap 策略追加、预算、是否接受追加输入、等待策略。内建 `user`；maintenance 注册 `home_maintenance`、`memory_maintenance`；`subagent` 插件注册 `subagent` profile（受限 surface，用于内部嵌套 Turn）。

Cycle 边界等待是一等语义：`WaitRequest(until: EventFilter, timeout, extend_budget)`，`until` 是事件唤醒，`timeout` 是定时唤醒。

### 3.4 Context：槽位、形状与段

段有槽位、槽内序号、形状、ref scheme。MessageStack 顺序由槽位决定：`identity → inputs → history → background → trace → working → task`。

三种形状定义内核对段的使用方式：

- Heap：线索在顶，条目可 `load/evict/inspect`；压力回收逐出。实例：`home.background`、`memory.background`、`session.history`。
- Stack：Turn 内追加，旧帧折叠，折叠帧可 `inspect`；压力回收折叠。实例：`trace`。
- State：最新状态整体替换或 patch；压力回收收缩渲染。实例：`identity`、`inputs`、`plan`、`workspace.resources`、`jobs`、`expand.tools`。

内核统一处理：渲染框架、回收顺序（State 收缩 → Heap 逐出 → Stack 折叠）、`context.load/evict(ref)` 对所有 Heap 有效、`core.context.inspect(ref, cursor)` 对声明 `inspect` 的段有效；ref 按 scheme（`home:`、`memory:`、`session:`、`trace:`）路由。

段每 Turn 实例：注册 `ContextSegmentProvider`，Turn 开始 `open(turn)`，结束 `seal()`/`close()`。段即 Turn 参与者，不再有独立的 `TurnParticipant`。

### 3.5 Job：Agent 监督的外部工作单元

Job 是 Agent 在环境中启动、监督、交互并回收的外部工作单元。后台 subprocess、外部 ACP agent、内部嵌套 Turn 是三种 Job 种类；未来长时 MCP 调用可成为第四种。

```python
class Job(Protocol):
    job_id: JobId
    kind: str                    # "process" | "acp_agent" | "tinysoul_turn"
    scope: JobScope              # TURN（Turn 结束即停止）| AGENT（跨 Turn 存续）
    status: JobStatus            # starting | running | waiting_input | exited | failed | stopped
    def summary(self) -> JsonObject: ...            # 有界摘要，供 jobs 段渲染
    async def send(self, message: JobMessage) -> None: ...   # stdin / ACP prompt / 嵌套 Turn 追加输入
    async def stop(self) -> None: ...
    async def collect(self) -> JobResult: ...       # 最终结果；大块输出以 workspace: Link 引用
```

- Job 事件：`job.<id>.started | output | state | message | permission_request | exited | failed`，payload 有界；Job 启动时注册为动态事件源，结束后注销。
- `JobRegistry`（kernel 定义、agent 持有一个实例）：按 id 索引；Turn 结束时停止该 Turn 的 `TURN` 级 Job；`AGENT` 级 Job 存续到 `collect` 或 `stop`；不跨进程重启持久化。
- `jobs` 段（内核 State，`working` 槽）：渲染本 Turn 可见的 Job（本 Turn 的 + 所有 agent 级），订阅 `job.*`，`on_event` 更新状态并对显著事件追加 trace note。
- agent 级 Job 完成且无活动 Turn 时，agent 内建 `TurnTrigger` 生成 `TurnRequest(profile=user, input=<Job 完成通告>, metadata={job_id})`，下一 Turn 的 `jobs` 段显示为可回收。
- 通用控制在 core 域：`core.job.wait(job_id | any, timeout)`（登记 WaitRequest）、`core.job.status(job_id)`、`core.job.stop(job_id)`。启动、发送与回收由种类所属域提供，因为它们的参数与结果语义不同。
- Job 种类由插件经 `registry.job_kind(kind, factory)` 注册；`ActionExecutionContext.turn.jobs` 提供 `start(kind, spec, scope)` 与查询。

### 3.6 Plugin 与两阶段装配

Plugin：`configure(env)`、`contribute(registry)`、可选 `finalize(view)`。装配两阶段：declare → resolve（服务表、合并 catalog、按 profile 组装段与 Trap 表、执行延迟 registrar、`finalize`）。插件间只经包根公共门面依赖；当前跨插件消费者是 maintenance（编排）与 subagent/expand（经 `WorkspaceService` 落盘大块输出）。

### 3.7 asyncio 与取消

单事件循环。Agent API、总线、Turn/Cycle/Phase、LLM、Action 批次、进程后端、事件源、Job、MCP/ACP 客户端、Endpoint 全部 async。持久 owner 存储引擎保持同步，适配层触盘经 `to_thread`，同步引擎不触碰 asyncio 对象。

取消沿用现有"边界权威"模型，不依赖 asyncio 的 Task 取消传播：

- `TurnCancellation` 保留为协作式令牌（底层改为 `asyncio.Event`），stop/exit 请求先置令牌，再在 Phase/Cycle 边界由收件箱控制事件转为 Trap。控制流只在边界改变，与现 `CycleRunner._boundary` 语义一致。
- Phase 内 in-flight await 与令牌竞争：LLM 调用以 `asyncio.wait({provider_task, cancel_wait}, FIRST_COMPLETED)` 取代现有守护线程轮询，命中令牌时取消 provider task 并抛 `TaskCancelled`，Phase 返回 `cancelled`，由边界收敛；Action 批次 runner 以同样方式观察令牌与 deadline。
- `ActionExecutionControl`（deadline、cancel_event、cancel callbacks）保留：它是线程内同步 executor 与进程后端唯一能观察到的协作取消手段；批次 runner 改用 asyncio 原语等待，但对 execution 的取消仍经 `control.request_cancel`。
- asyncio 的硬取消（`Task.cancel()`）只在 `Agent.stop()/exit()` 宽限期后对活动 Turn Task 使用，属于进程收尾而非业务控制流；模块内 `except Exception` 不吞 `CancelledError`。

### 3.8 失败三层语义

不变。每个插件自带 `failures.py` 与 `runtime_bridge.py`，复用 `runtime/bridge/_payload.runtime_exception()` 构造 payload（`module` + `kind`）；`runtime/bridge/` 只保留 `_payload` 与内核模块 bridge。Trap 原因的所有权同样分层：`runtime` 只定义 `runtime.startup_failed | turn_end | cycle_end | agent_end`；`kernel/context` 定义 `context.compression_required`；`home.runtime_copy_required`、`workspace.trash_restore_required` 等由所属插件定义并经 `registry.trap_handler` 登记（现 `TrapHandlerRegistry` 已支持 exact/prefix/fallback，无需改动）。现 `runtime/exception.py` 中集中声明业务原因常量的做法取消。ACP/MCP 的协议错误在插件边界归类：工具返回 `is_error` 是局部结果；连接/握手失败是模块边界异常；不进入 Runtime。

## 4. 分层架构与包布局

```text
L5 gateway      cli · endpoint v2 (http/ws) · project init/reset
L4 agent        Agent 门面 · assembly · TurnScheduler · EventRouter · JobRegistry 实例 · generation · day · profiles/user · services · status
L3 plugins      home · memory · session · workspace · maintenance · capabilities/{resource,web,execution,subagent,expand}
L3 environment  terminal · scheduler · fswatch · console sink
L2 kernel       spi · context · loop · action · jobs · prompts
L1 runtime      scope/trap/transfer/exception · events(EventBus/Signal/Observation/EnvironmentEvent/TurnInbox/EventFilter) · generation handle · 内核 bridge
L1 llm          messages · tools · task runner · providers (async)
L0 infra        config · json · filesystem · time · async concurrency · staging · continuation · embedding
```

依赖规则（S7 用静态 import 测试固定）：只向下依赖；`kernel` 不 import `plugins/environment/agent/gateway`；`runtime`/`llm` 不 import 业务模块；`gateway` 只经 `Agent` API 与 `agent.services` 访问业务。

```text
tinysoul/
  infra/
  runtime/
    scope.py transfer.py exception.py errors.py frame_runner.py
    trap/  events/  generation/
    bridge/{_payload,context,loop,action,jobs,llm,infra}.py
  llm/
  kernel/
    spi.py
    context/
      slots.py shapes.py segments.py
      identity.py inputs.py plan.py trace.py jobs.py
      composer.py pressure.py engine.py actions.py
    loop/
      turn.py cycle.py phases.py profile.py inbox.py wait.py completion.py outcomes.py cancellation.py config.py
    action/
      engine.py core/ backends/ builtins/core/ config.py failures.py
      catalog/core/
    jobs/
      job.py registry.py events.py actions.py      # Job 协议、JobRegistry、事件 payload、core.job.*
    prompts/
  plugins/
    home/ memory/ session/ workspace/ maintenance/
    capabilities/
      resource/ web/
      execution/            # script、shell、process Job 种类；域 execution
      subagent/             # ACP 客户端与 tinysoul_turn Job 种类；域 subagent；subagent profile
      expand/               # MCP 网关、工具索引、expand.tools 段；域 expand
  environment/
    terminal.py scheduler.py fswatch.py console.py
  agent/
    agent.py assembly.py scheduler.py router.py generation.py day.py services.py status.py config.py failures.py runtime_bridge.py
    profiles/user.py
  gateway/
    cli.py
    endpoint/{auth,schemas,routes,events,host}.py
    project/{initializer,resetter,instance}.py
  assets/
```

插件包统一结构：`plugin.py`、`config.py`、`engine.py|service.py`、`segments.py`、`actions.py`、`jobs.py`（Job 种类，按需）、`catalog/<domain>/`（按需）、`participants.py`（DailyParticipant，按需）、`failures.py`、`runtime_bridge.py`、`errors.py`。

## 5. 契约设计

### 5.1 Agent SDK API

- `await Agent.create(project_root, *, overrides) -> Agent`
- `await agent.start()` / `stop()` / `restart()`
- `agent.status() -> AgentStatus`（含 Job 表摘要）
- `await agent.reload_config(patch) -> ConfigReloadResult`
- `await agent.submit_turn(TurnRequest) -> TurnHandle`
- `await agent.append_input(turn_id, text)`、`await agent.control(turn_id, kind)`、`await agent.exit()`
- `await agent.publish(EnvironmentEvent)`（供 gateway 代理外部环境事件）
- `agent.subscribe(filter) -> AsyncIterator[ObservationEvent]`
- `agent.services.get(FacadeType)`

`TurnScheduler` 串行消费 TurnRequest；每 Turn 前由 `agent/day` 取得业务日 lease；持有活动 Turn 收件箱。`EventRouter` 按 3.2 路由。嵌套 Turn（`tinysoul_turn` Job）不进队列，作为父 Turn 内的 Task 运行，共享 owner 引擎，段实例独立。

### 5.2 PluginRegistry

```python
class PluginRegistry(Protocol):
    def context_segment(self, provider: ContextSegmentProvider, *, profiles: frozenset[str] | None = None) -> None: ...
    def actions(self, registrar: ActionRegistrar) -> None: ...
    def action_catalog_fragment(self, root: Path, *, package_only: bool = False) -> None: ...
    def trap_handler(self, reason: str, handler: TrapHandler, *, profiles: frozenset[str] | None = None) -> None: ...
    def turn_profile(self, profile: TurnProfile) -> None: ...
    def daily_participant(self, participant: DailyParticipant) -> None: ...
    def event_source(self, source: EventSource) -> None: ...
    def schedule(self, name: str, spec: ScheduleSpec) -> None: ...
    def turn_trigger(self, trigger: TurnTrigger) -> None: ...
    def job_kind(self, kind: str, factory: JobFactory) -> None: ...
    def service(self, facade_type: type[T], facade: T) -> None: ...
```

覆盖规则、resolve 阶段的 `ActionRegistrationContext`（bus、observations、llm_action、staging、resolvers、skill providers、`services`、`jobs`）、catalog 所有权（core 归内核，其它域随插件；`package_only` 域只运行时合并；`init/reset` 合成项目 catalog）同前。

### 5.3 段协议

```python
class ContextSegmentProvider(Protocol):
    segment_id: str; slot: SegmentSlot; order: int; shape: SegmentShape; ref_schemes: frozenset[str]
    async def open(self, turn: TurnInfo) -> ContextSegment: ...

class ContextSegment(Protocol):
    def render(self) -> tuple[Message, ...]: ...
    def stage(self, patch: SegmentPatch) -> StagedChange: ...
    def commit(self, staged: Sequence[StagedChange]) -> None: ...
    def seal(self) -> JsonObject: ...
    async def close(self, completion: TurnCompletion) -> None: ...
    def load(self, ref) ; def evict(self, ref) ; def inspect(self, ref, cursor)      # 形状能力
    def reclaim(self, required_chars: int) -> int: ...
    def control_tools(self) ; def apply_control(self, call)                         # 段专属控制工具
    def subscriptions(self) -> EventFilter | None: ...
    async def on_event(self, event: TurnEvent) -> SegmentPatch | None: ...
```

`ContextEngine`：按 profile 选段并并行 `open`；`compose` 依槽位渲染并叠加 TaskPrompt；边界批次消费段 Signal、Phase1 控制调用与收件箱事件产生的 patch。批次语义沿用现 `consume_signal_batch`：先对全部 patch 做 `stage`（校验 + 投影到批次状态 + 完成惰性加载），单个 patch 校验失败转为该调用的局部 `ControlResult` 并从批次剔除，其余 patch 依序 `commit`；`stage` 阶段不改变任何段状态，因此 Trap 重试同一批次不会观察到半提交。压力 Trap 按形状顺序 `reclaim`；`end_turn` 汇总 `seal()` 为 `TurnCompletion.segments`，再依序 `close`（`history` 最后）。

`TurnInfo`（`open` 的输入）：`turn_id`、`profile`、`business_day`、`request.metadata`（如 `memory_maintenance` 的 `target_day`、Job 完成通告的 `job_id`）、`parent_turn_id`；段据此决定打开当日还是归档日、读写还是只读。

内核段：`identity`、`inputs`、`plan`（控制工具 `plan.patch`；milestone 字段 status、value、source link、revision/digest、note）、`trace`、`jobs`。插件段：`home.background`、`memory.background`、`session.history`、`workspace.resources`（订阅 `fs.workspace.changed`）、`expand.tools`。

`trace.seal()` 除折叠后的语义节点外，直接给出 `actions` 投影（Phase2 调用与 Phase3 结果按 call_id 配对、含 outcome/failure/references），供 `session.history.close` 原样记录；现由 `session/completion.py` 解析 sealed trace 的做法取消。

压力回收顺序为 State 收缩 → Heap 逐出 → Stack 折叠：State 段收缩（`workspace.resources` trash 临时资源、`expand.tools` 按最近使用 unpin、`jobs` 折叠已结束项）几乎不损失决策信息；Heap 条目是可经 `context.load` 重新加载的线索；Stack 折叠丢失的是模型正在依据的本轮细节，虽可 `inspect` 追溯但代价最高。这与现 `UserContextPressureRecovery` 先折叠 trace 再逐出 background 的顺序不同，属有意调整。每轮回收逐段询问 `reclaim(required_chars)` 直到满足目标或全部段返回 0，无进展则按现有 `ContextPressureTrapHandler` 语义结束 Turn。

### 5.4 TurnProfile 与等待

```python
@dataclass(frozen=True)
class TurnProfile:
    name: str
    guidance: tuple[str, ...]
    action_surface: ActionSurface
    completion: TurnCompletionDetector
    completion_to_output: Callable[[JsonObject | None], TurnOutput | None]
    turn_settings: TurnSettings
    cycle_settings: CycleSettings
    accepts_appended_input: bool
    wait_policy: WaitPolicy        # 单次最长等待、extend_budget 上限、ask_timeout
```

`core.ask(question)`：发出 `TurnOutput(kind=question)`，登记 `WaitRequest(until=InputAppended, timeout=wait_policy.ask_timeout, extend_budget=True)`，Agent 活动进入 `awaiting_input`；回复到达则下一 Cycle 在 inputs 段看到；超时则 Turn 以 `TurnOutcomeStatus.AWAITING_USER` 结束（现有枚举 `ANSWERED | COMPLETED | EXHAUSTED | FAILED | STOPPED` 新增一项，`TurnOutcome.__post_init__` 一致性校验同步扩展），Session 记录问题。`core.answer` 仍是终结性回答。`ask_timeout` 默认 30 分钟。

Turn 内核骨架（`TurnRunner.run` 的准备 → Cycle 循环 → completion → 收尾 → outcome 归类，`CycleRunner` 的三 Phase 与 `_run_phase` 重试/结束转移消费，`PhaseFailure` 反馈进入下一 Cycle）整体保留；改变的是三个接缝：准备管线的 Signal 提交改为段 `open`，`_boundary` 的"控制信号 + Context 信号 + 合并追加输入"改为"收件箱 drain + 段 patch 批次"，`TurnActivityController.allow_additional_cycle/wait_before_cycle/cleanup_turn` 改为 `WaitRequest` 与 Job 的 Turn 级清理。

### 5.5 Action 框架

`ActionEngine` 门面不变，`run_batch` async。`ActionBatchRunner` 每 execution 一个 Task，`asyncio.wait(FIRST_COMPLETED)` 同时观察 deadline 与 Turn 取消令牌，超时或取消时对 execution `control.request_cancel` 并等待宽限期，仍未收敛者标记 `executor_leaked` 并阻断同批后续 execution（现有 `leaked_timeout` 语义保留）；首个 `RuntimeException`/`RuntimeTransferInterrupt` 出现时取消同组后原样上抛，不用 `TaskGroup`。`ActionExecutor.execute` 为 async；native 同步 executor 经 `to_thread` 承载并继续以 `control.check_cancelled()` 协作；subprocess 后端 `create_subprocess_exec`；`llm_action` async。`ActionExecutionContext` 保留 `control`、`module_runner`（async 版 `RuntimeModuleRunner`），新增 `turn`：`turn_id`、`business_day`、`request_wait`、`jobs`、`publish(EnvironmentEvent)`；`signal_bus` 改为 `bus`（EventBus）。

Schema 子集已支持自由形态 `object`（`action/core/schema.py` 中 `type: object` 允许省略 `properties`，`additionalProperties` 默认 `true`），`expand.call.arguments` 可直接声明为 `{ "type": "object" }`，无需扩展校验器。

### 5.6 `execution` 域（进程 Job 种类）

`plugins/capabilities/execution/` 合并现 script、shell、supervised_process：一个域一个插件。`execution.run_script`、`execution.run_shell` 保留前台有界执行；`execution.start(kind=script|shell, source, args, scope=turn|agent) -> job_id` 启动 `process` Job；`execution.stdin(job_id, text)`；`execution.collect(job_id)` 返回 stdout/stderr 摘要与 `workspace:` 落盘 Link。等待/状态/停止用 `core.job.*`。进程树终止逻辑保留。

### 5.7 `subagent` 域（ACP 与嵌套 Turn）

依赖：ACP Python SDK（在子计划中核实包名与版本）。协议要点（ACP v2）：JSON-RPC 2.0 over stdio NDJSON；`initialize → session/new(cwd, mcpServers?) → session/prompt` 立即返回，随后 `session/update` 通知流（`user_message`、`agent_message(_chunk)`、`agent_thought`、`tool_call(_update)`、`plan`、`state_update: running|idle(stopReason)`）；`session/cancel`；agent 反向请求 `session/request_permission`。

- 配置：`[capabilities.subagent.agents.<name>]`：`command`、`args`、`cwd_policy = workspace | project | path`、`permission_policy`（`auto_allow` 列表 + 默认 `ask_model` | `deny`）、`env`。
- `acp_agent` Job 种类：spawn → initialize → session/new（cwd 按策略解析到 Workspace 目录）→ prompt。`session/update` 映射为 `job.<id>.message | state | output`（tool_call 摘要）；`request_permission` 映射为 `job.<id>.permission_request` 并置 `waiting_input`，按策略自动应答或等待模型；`idle(stopReason)` → `exited`。`send` = 追加 `session/prompt`；`stop` = `session/cancel` + `session/close` + 进程终止。
- `tinysoul_turn` Job 种类：以 `subagent` profile 在父 Turn 内运行嵌套 Turn；子 Turn 输出映射为 `job.<id>.message`；`send` = 子收件箱追加输入；父 stop 传播为子 stop；Session 记录子 Turn 带 `parent_turn_id`。
- 动作：`subagent.start(agent, brief, references, scope) -> job_id`、`subagent.prompt(job_id, message)`、`subagent.respond(job_id, request_id, option)`、`subagent.collect(job_id)`（最终消息、stopReason、变更文件摘要）。等待/状态/停止用 `core.job.*`。
- Workspace 联动：sub-agent 在 Workspace 目录内改动文件，由 `fs.workspace.changed` 事件驱动 `workspace.resources` 段刷新与 manifest reconcile。
- 不在范围：TinySoul 作为 ACP server 被外部客户端驱动（可作为 gateway 的后续选项）。

### 5.8 `expand` 域（MCP 通用工具）

依赖：MCP Python SDK v2（`mcp`，async；`Client` 支持 stdio 与 Streamable HTTP；`list_tools/call_tool`；`listen(tools_list_changed, resource_subscriptions)` 订阅流）。

- 配置：`[capabilities.expand.servers.<name>]`：`transport = stdio | http`、`command/args` 或 `url/headers`、`enabled`、`tool_allowlist`、`connect = eager | lazy`。
- `McpGateway` 服务（agent 级）：连接、工具索引（server、name、title、description、input_schema）、`listen` 任务把 `ToolsListChanged/ResourceUpdated` 发布为 `mcp.<server>.tools_changed | resource_updated` 环境事件并刷新索引；每个连接是动态事件源。
- `expand.tools` 段（State，`working` 槽）：模型钉选的工具集及完整 input schema，有界（默认 ≤ 12）；`reclaim` 按最近使用逐出；Turn 结束 `seal` 记录钉选列表以便 Session 承接。
- 动作：`expand.search(query, limit)` 在索引上做词法 + 可选语义检索（复用 `infra/embedding`），返回候选并自动钉选前 N；`expand.describe(tool_ids)` 返回完整 schema 并钉选；`expand.call(tool_id, arguments)` 先按钉选 schema 校验参数（未钉选或不合法为局部失败），再 `call_tool`，结果归一化为文本摘要 + `structured_content`，超限内容经 `WorkspaceService` 落盘为 `workspace:` Link；`expand.unpin(tool_ids)`。
- tool-search 的设计意图：Phase2 只看到 `expand.*` 五个稳定动作与钉选段里的少量 schema，而不是所有 MCP 工具的 schema；搜索是线索、钉选是加载，与冰山语义一致。
- 后续扩展：`expand.read_resource`、prompts、长时调用作为 `mcp_call` Job 种类。

### 5.9 Endpoint v2

- `GET /v2/health`；其余 Bearer。
- `GET /v2/agent`、`POST /v2/agent/restart`、`POST /v2/agent/reload`（显式激活配置）。
- `POST /v2/turns`、`GET /v2/turns/{id}`（状态含 `awaiting_input`）、`POST /v2/turns/{id}/inputs`、`POST /v2/turns/{id}/control`。
- `GET /v2/jobs`、`GET /v2/jobs/{id}`、`POST /v2/jobs/{id}/stop`。
- `POST /v2/events`（外部环境事件代理）、`GET /v2/events`（replay）、`WS /v2/events`（流）。
- `GET /v2/config`、`GET /v2/config/catalog`、`GET /v2/config/actions`、`PATCH /v2/config`（只写文件事务，可多次批量修改后统一 reload）。
- `GET /v2/maintenance`、`POST /v2/maintenance/daily`（经 `MaintenanceService.plan_daily()`）。
- `/v2/workspace/*` 经 `WorkspaceService`。
- 连接描述、实例 lease、事件缓冲与 journal 保留。

### 5.10 Prompts

`kernel/prompts/` 集中框架提示词与 `PromptBlock` 构造器；插件动作内部提示词留在插件。

## 6. 与现有模块的联系与迁移映射

| 现模块 | 新位置 | 保留（搬迁） | 改变（重写） |
|---|---|---|---|
| `infra` | `infra` | 全部 | asyncio 并发原语；线程 RW lock 保留给同步引擎 |
| `runtime` | `runtime` | scope/trap/transfer/exception/generation 语义；`TrapHandlerRegistry` exact/prefix/fallback；`RuntimeModuleRunner` 重放语义；`_payload` | `signals/` → `events/`；`RuntimeHandle` 由 `Condition(RLock)` 改为 asyncio 读写/活动 lease；`RunLevel.PROGRAM→AGENT`、`runtime.program_end→agent_end`；`exception.py` 只保留四个 runtime 原因，业务原因常量迁回 owner；bridge 收敛 |
| `llm` | `llm` | 协议、映射、模型链、重试、水位 | provider/task runner async；删除线程轮询 |
| `loop` | `kernel/loop` + `agent/profiles/user` + plugins | Turn/Cycle/Phase 骨架、cancellation、outcomes、PhaseFailure | async；收件箱与 WaitRequest 取代 `TurnActivityController`；`loop/user/*` 拆到 user profile 与各插件 |
| `context` | `kernel/context` | trace 堆、Working plan、background 堆算法、compressor、composer、控制工具归一化 | 段协议与三形状；删除 owner 特判；`ContextTurnCompletion` 泛化为 `segments` |
| `action` | `kernel/action` | catalog 四层、loader、schema、hooks、result、rendering、scope | runner asyncio；catalog 模板拆到插件；`ActionExecutionContext.turn` |
| `app` | `agent` + `environment` + `gateway/project` | initializer/resetter/instance、调度计时、终端解析；`ProgramRunner.run` 的串行请求循环、preflight、世代活动 lease、Program 级转移消费 | `ProgramRunner` → `TurnScheduler`（`Queue.get(timeout=0.5)` 轮询改为 `asyncio.Queue`）；`ProgramGeneration` → `AgentGeneration`（按 profile 装配的段 provider、Action surface、Trap 表）；`RuntimeActivity` 扩展 `preflight | awaiting_input`；builder（935 行）→ assembly + 各插件 `contribute`；gateway/inputs → EventRouter/Agent API；outputs → Observation 订阅 |
| `endpoint` | `gateway/endpoint` | auth、lease、事件缓冲、journal、host | v2 路由与 schema |
| `maintenance` | `agent/day` + `plugins/maintenance` | `day.py` 的 `BusinessClock/IanaBusinessClock`；`archive/engine.py` 的 `DailyLifecycleCoordinator`、`DailyTransitionJournal`（SESSION_ARCHIVED → WORKSPACE_ARCHIVED → ACTIVE_INITIALIZED）、`ActiveDayLease`；`availability.py`、`schedule.py`；Home/Memory 维护任务 | `BusinessClock` 与 `DailyLifecycleCoordinator` 迁 `agent/day`，三个分立的 `SessionDailyLifecycle / WorkspaceDailyLifecycle / ActiveMemoryDailyLifecycle` 协议合并为一个 `DailyParticipant`（`initialize_day / archive_day / reconcile_active`，按注册顺序执行，journal 步骤按参与者名记录）；`MaintenanceEngine.preflight` 拆为 `agent/day.ensure_active_day`（确定性）与 maintenance 插件的 availability reconcile；builder → plugin；两个 profile 与专属段；`MaintenanceSchedule.due` → `registry.schedule` + `TurnTrigger` |
| `session` | `plugins/session` | 记录图、Summary 堆、inspect、continuation、`memory_facts` | `history` Heap 段（`open` 读 prior turns，`close` 记录；`memory_maintenance` profile 下按 `TurnInfo.metadata.target_day` 打开归档日）；schema v4 → v5：`working` + `background_links` 由通用 `segments`（segment_id → seal JSON）取代，`actions` 改由内核 `trace` 段 `seal()` 直接给出的 `actions` 投影承接（Phase2 调用与 Phase3 结果的配对是 trace 内部知识，不再由 `session/completion.py::project_turn_record` 解析 sealed trace），新增可空 `parent_turn_id`；`SessionMemoryFact` 同步以 `segments` 取代 `working`/`background_links`；inspect 走统一机制 |
| `workspace` | `plugins/workspace` | engine 存储逻辑 | engine 拆分；`resources` State 段带 `reclaim` 与 `fs` 订阅；`WorkspaceService`；Trash Trap 随插件 |
| `home` | `plugins/home` | actual/overlay/review/skills | `home.background` Heap 段；prompt mount reconcile 移入 `finalize`；runtime copy Trap 随插件 |
| `memory` | `plugins/memory` | codec、事务、catalog、backlinks、embedding、Memory.md CAS | `memory.background` Heap 段；动作 registrar 化 |
| `capabilities/{script,shell,supervised_process}` | `plugins/capabilities/execution` | handler、进程管理、进程树终止 | 合并为一个域一个插件；supervised 重写为 `process` Job 种类；删除对 loop/context 的 import |
| `capabilities/{resource,web}` | `plugins/capabilities/{resource,web}` | worker 与协议 | registrar 化 |
| （新） | `plugins/capabilities/subagent` | — | ACP 客户端、`acp_agent`/`tinysoul_turn` Job 种类、`subagent` profile |
| （新） | `plugins/capabilities/expand` | — | MCP 网关、工具索引、`expand.tools` 段、五个动作 |
| （新） | `environment/fswatch.py` | — | Workspace 文件监视事件源（`watchfiles`） |

## 7. 可行性与风险

规模与分层评估同前一版（内核 13.5k、llm 6.5k、owner 17k、capabilities 8.4k、外层 9.5k；测试 885 例；38 文件用 threading）。新增部分的可行性：

- Job 框架：现 `supervised_process/manager.py`（770 行）已有进程注册表、输出缓冲、等待、清理的全部算法，改写为 `process` Job 种类是结构内重排；`jobs` 段与 `core.job.*` 是新增但边界清晰。
- ACP：协议为 stdio NDJSON JSON-RPC，与进程后端同一基础；SDK 为 async。风险在权限请求的策略设计与外部 agent 行为差异；先以一个 agent（如 Codex/Claude Code CLI 的 ACP adapter）验证。
- MCP：SDK v2 async，`Client` 一行连接；自由形态 object 参数已被现有 schema 子集接受（见 5.5）；剩余风险是远程服务器 300s 读超时与 Action 超时的协调，以及 MCP 工具自身 `inputSchema` 超出本项目 schema 子集时的钉选校验策略（子计划中决定：超出子集的键只透传不校验）。
- 文件监视：`watchfiles` 跨平台成熟；Windows 事件噪声用去抖 + manifest digest 比对过滤。

### 7.1 对照现有代码的复审结论（2026-09-14）

逐文件核对 `runtime`、`loop/turn.py`、`loop/cycle.py`、`action/core/{runner,executor}.py`、`context/engine.py`、`app/program.py`、`llm` 公共面后，方案与现有实现的关系归为三类：

保留并直接迁移（结构内重排）：

- `RunScope/RunFrame/RunLevel`、`RuntimeException(reason, message, payload)`、`RuntimeTransfer(RETRY|END, target)`、`TrapHandlerRegistry`（exact/prefix/fallback）、`RuntimeModuleRunner` 重放语义、`bridge/_payload.runtime_exception()`：全部保留，只改 `PROGRAM→AGENT` 与 async 化。
- `TurnRunner.run` 骨架（准备 → Cycle 循环含 `phase_feedback` → completion → `_finish_turn` → `_outcome_status`）、`CycleRunner.run` 的三 Phase 与 `_run_phase` 的 RETRY/END 转移消费、`PhaseFailure` 进入下一 Cycle：保留。
- `ActionBatchRunner` 的分组、deadline、宽限期、`executor_leaked` 阻断与 `RuntimeException` 传播语义：保留，等待原语换为 asyncio。
- `ContextEngine.consume_signal_batch` 的"校验 → 投影 → 惰性加载 → 依序应用"两阶段与"单条失败为局部结果"语义：升格为段协议 `stage/commit` 的通用语义。
- `ProgramRunner.run` 的串行请求循环、preflight、活动 lease、Program 级转移消费：改名为 `TurnScheduler`，语义不变。

需要修正的方案表述（已回写至对应小节）：

- 3.7：取消模型改为沿用"协作令牌 + 边界权威"，不以 asyncio Task 取消作为业务控制流（现 `CycleRunner._run_phase` 捕获 `TaskCancelled` 后返回 `cancelled` 交边界收敛的设计是正确的，应保留）。
- 3.8：Trap 原因常量按 owner 分层，`runtime/exception.py` 不再集中声明 `context.*`、`home.*`、`workspace.*` 原因。
- 5.3：段批次不是"任一失败丢弃全部"，而是"单条失败局部化、其余提交、stage 不触状态"。
- 5.4：`TurnOutcomeStatus` 新增 `AWAITING_USER`。
- 5.5：`ActionExecutionControl` 与 `module_runner` 保留。

现有实现中将被消除的耦合（本方案的直接目标）：

- `context/engine.py` 以 `signal.name` 分派到 owner 专用 parser（`parse_workspace_sync_signal`、`parse_session_sync_signal` 等）并持有 `WorkspaceSnapshot`、`SessionBackgroundSnapshot` 类型 → 段 `stage(SegmentPatch)` 由段自身解释 payload。
- `runtime/exception.py` 声明业务 Trap 原因；`runtime/bridge/` 下 12 个业务模块 bridge → owner 自带。
- `loop/turn.py` 的 `TurnPreparationPipeline`/`TurnCompletionPipeline`/`TurnActivityController` 三条 owner 参与通道 → 段 `open/close` 与 `WaitRequest`/Job 一条通道。
- `app/builder.py` 935 行硬编码组合根 → 插件 `contribute` + 两阶段 assembly。
- `ActionExecutionContext` 不携带 Turn 身份，executor 只能从 `execution.framework.scope` 反推 → 显式 `turn` 视图。
- 默认 Background 不经 Signal，而由 `ContextTurnPreparationHandler` 直接调用 `ContextEngine.prepare_default_background(business_day)`，Home/Memory 内容经 Context 持有的 loader/provider 反向注入 → `home.background`/`memory.background` 段在 `open` 内自行准备。
- 维护日切以三个 owner 专用协议（`SessionDailyLifecycle`、`WorkspaceDailyLifecycle`、`ActiveMemoryDailyLifecycle`）由 `DailyLifecycleCoordinator` 分别调用 → 一个 `DailyParticipant` 协议，参与者按注册顺序执行。
- `SupervisedProcessManager.wait_before_cycle` 用 `SignalWatch.wait_for_matching` 等待同 Turn 的 `input.append` 或 `control.request` → `WaitRequest(until=EventFilter(job.<id>.* | input.* | control.*))`，等待条件由发起方声明而非硬编码在 owner 中。
- 压力恢复分 `UserContextPressureRecovery` 与 `MaintenanceContextPressureRecovery` 两个 owner 特判实现，`loop/user/pressure.py` 直接 import Workspace 类型 → 内核按形状顺序调用各段 `reclaim`，Workspace trash 逻辑留在 `workspace.resources` 段内部。

风险与对策（R1–R9 同前），新增：

- R10 Job 框架跨 Turn 存续与 Turn 生命周期的交互（agent 级 Job 在日切、reload、restart 时的处置）→ 设计为：日切不影响 Job；reload 保留 JobRegistry 实例（不属世代）；restart/exit 停止全部 Job 并记录 Observation。
- R11 ACP 权限与安全 → 主机硬隔离前提下默认 `auto_allow` 读操作、写操作 `ask_model`；策略可配置。
- R12 外部依赖增加（`mcp`、ACP SDK、`watchfiles`）→ 均为轻量、async、基础性依赖，符合规约；在子计划中锁版本。

## 8. 开放设计问题

### 8.1 D11：追溯动作合并的权衡

维护者指出：Session inspect 面向当日更早 Turn 的内容，Context inspect 面向本轮被压缩的内容，语义指向不同。

分析：

- 机制层面两者已经同构：都是"持有一个 ref → 请求有界展开 → 结果进入 trace → 可用 cursor 继续"。段协议的 `inspect` + `InspectResult` + ref scheme 路由把它们统一为一个内核机制，这一点无争议。
- 模型层面的差异在意图："回看我这轮做过什么"与"查看今天早些时候发生过什么"。但模型持有的 ref（来自 history 堆头的 `session:turn/3` 或 trace 折叠标记的 `trace:node/12`）已经编码了位置，模型无需先判断"该用哪个工具"再找 ref；一个动作降低 Phase2 工具数与选择负担。
- 两个动作的好处是 guidance 文案可以分别写明使用场景与返回形态；这在单动作里也能通过描述中枚举 ref scheme 做到。
- 关键点：这是 catalog 层面的可调项而非架构决策。同一 executor 可以在 TOML 中暴露为一个或两个动作，不改代码。

决策（D11）：一个内核机制（段 `inspect` + `InspectResult` + ref scheme 路由 + cursor），从一开始暴露两个模型侧动作，共用同一 executor：`core.context.inspect(ref, cursor)` 面向本轮 `trace:` 折叠过程与 `home:`/`memory:` 背景条目；`core.session.inspect(ref, cursor)` 面向今日更早 Turn 的 `session:` 条目。两者的 guidance 分别写明意图与返回形态；executor 对 ref scheme 与动作的匹配做校验，错配为局部失败并提示应使用的动作。

### 8.2 环境订阅（已决，D13）

两级机制与首个事件源 Workspace 文件监视并入 S4；完整协议见 3.2。

### 8.3 sub-agent（已决，D15）

作为 `subagent` 域与 Job 框架的一部分，见 5.7。嵌套 Turn 不再是"在 Phase3 内联运行"，而是 `tinysoul_turn` Job 种类，与外部 ACP agent 同一监督界面。

### 8.4 配置激活（已决，D12）

`PATCH /v2/config` 只写文件，`POST /v2/agent/reload` 显式激活；允许多次修改后统一 reload。

### 8.5 MCP `expand` 域（已决，D16）

见 5.8。待子计划确认：钉选上限默认值、语义检索是否默认开启、大结果落盘阈值。

## 9. 决策记录

已确认（2026-09-14）：

- 分层包布局；Endpoint 重设计；内核全面 asyncio。
- D1 owner 存储引擎保持同步，适配层 `to_thread`。
- D2 事件唤醒、环境事件协议、Job 框架、Agent 生命周期 API 本次落地。
- D3 原地迁移 + 行走骨架；主机部署在 gateway 阶段前继续运行旧 checkout。
- D4 `llm` 保留顶层包。
- D5 引入 `pytest-asyncio`。
- D6 milestones/todos 为内核 `plan` 段；Workspace 资源为插件 State 段。
- D7 撤销"不建立 ask/pause/awaiting 状态"规约。
- D8 TOML section 名稳定，仅 `[app]→[agent]`；新增 `[capabilities.subagent]`、`[capabilities.expand]`、`[environment.fswatch]`。
- D9 Session 记录 schema v5（`segments` 通用快照取代 `working`/`background_links`，`actions` 来自 `trace` 段 seal，可空 `parent_turn_id`），不迁移 v4 归档。
- D10 `core.ask` 纳入，S4 实现。
- D12 配置显式 reload。
- D13 环境事件完整协议 + Workspace 文件监视并入 S4。
- D14 Home/Memory 分立 Heap 段；日切归 `agent/day`；Session 在 `history.close` 记录。
- D15 sub-agent 作为 `subagent` 域，经 ACP 接入外部 agent，经 `tinysoul_turn` Job 接入内部嵌套 Turn。
- D16 `expand` 域经 MCP 接入通用工具，`expand.search` 为 tool-search，`expand.tools` 段承载钉选。
- D11 追溯：一个内核机制，两个模型侧动作 `core.context.inspect` 与 `core.session.inspect`（见 8.1）。
- D17 `execution` 域合并 script/shell/supervised_process 为一个插件。
- D18 `subagent` 首个验证目标为成熟的 ACP agent（Codex 或 Claude Code 的 ACP adapter，子计划中确定）；默认权限策略：读操作 `auto_allow`，写操作 `ask_model`。
- Job 框架作为内核概念（三种种类、两种作用域、`jobs` 段、`core.job.*` 通用控制 + 域内 start/send/collect）。

待决：无。方案进入 S0 定稿，后续阶段的细节在各子计划中展开并回写本文件。

修订留痕：

- 2026-09-14 初稿曾以"当前无消费者"删除段 `shape`、段级 `inspect`/`on_event`；复审后恢复并升格为统一语义，同时删除 `BackgroundEntryProvider`、`TurnParticipant`、`TurnPreflight`。
- 2026-09-14 依维护者补充，把后台进程、外部 sub-agent、嵌套 Turn 统一为 Job 框架，环境事件升格为完整协议（`EnvironmentEvent`、静态/动态源、`EventRouter`），新增 `subagent` 与 `expand` 两个域；嵌套 Turn 由"Phase3 内联"改为 Job 种类。
- 2026-09-14 对照现有代码复审（见 7.1）：修正 3.7 取消模型、3.8 Trap 原因所有权、5.3 批次语义、5.4 outcome 枚举、5.5 执行控制保留；同步微调 `AGENTS.md`（Action/Job 定义、运行层级 Agent 命名、`core.ask`、插件契约与 bridge 放置条款、"当前任务"改为本重构并列出过渡期被替代条款），其余条款保留至 S7 整体重写。

## 10. 分阶段实施

每阶段开始前写入子计划 `docs/analysis/2026MMDD-<stage>-execution-plan.md`，完成后归档；本文件只勾选阶段。门禁：聚焦测试 → Fast → Full → typecheck；S2 起 fake-provider CLI E2E 必过。

- [x] S0 方案定稿：全部决策关闭（2026-09-14）；不改代码。`docs/design/architecture.md` 推迟到 S2 内核落地时建立，以遵守设计文档与代码一致的规则；在此之前本文件是唯一设计来源。
- [ ] S1 基础层：`infra` async 原语；`runtime/events/`（EventBus、Signal、Observation、EnvironmentEvent、TurnInbox、EventFilter）；`RuntimeHandle` asyncio lease；`PROGRAM→AGENT`；bridge 收敛；`llm` 全面 async；`pytest-asyncio`；重写 `tests/{infra,runtime,llm}`。
- [ ] S2 内核与最小 Agent：`kernel/*`（三形状、段协议、inbox/wait、profile、async action runner、Job 协议与 JobRegistry、`jobs` 段、`core.job.*`、prompts）；`agent/*`（门面、assembly、scheduler、router、generation、day 最小时钟、user profile）；`environment/{terminal,console}`；`gateway/cli`；插件清单只含内核 builtins；删除 `loop/`、`context/`、`action/`、`app/`；新建 `docs/design/architecture.md` 与 `docs/design/kernel/*.md` 描述已落地部分；fake-provider E2E 恢复。
- [ ] S3 插件迁移（每插件一个子计划）：session → workspace → home → memory → maintenance（含 `agent/day` 完整日切、DailyParticipant、archive、availability、两个 profile、schedule 与 TurnTrigger）→ capabilities（resource、web、`execution` 合并与 `process` Job 种类）。每步删除旧路径与旧 bridge。
- [ ] S4 Agent 与环境完整化：`services`、`status`、`reload_config`、`restart`；`environment/scheduler`、`environment/fswatch` 与 `workspace.resources` 订阅；agent 级 Job 完成触发器；Observation 路由与 console sink；`[agent]` 取代 `[app]`；`core.ask`。
- [ ] S5 Gateway v2：路由（含 jobs 与外部事件代理）、schema、事件 replay/流、host、auth；`gateway/project`；重写 `docs/endpoint/*` 并附 v1→v2 对照；删除 `endpoint/`。
- [ ] S6 新能力域：`subagent` 插件（ACP 客户端、`acp_agent` 与 `tinysoul_turn` Job 种类、`subagent` profile、权限策略）；`expand` 插件（MCP 网关、索引、`expand.tools` 段、五个动作）；各一份子计划。
- [ ] S7 收尾：`docs/design/` 重组（`architecture.md`、`runtime.md`、`llm.md`、`infra.md`、`kernel/{context,loop,action,jobs,prompts}.md`、`plugins/*.md`、`agent.md`、`environment.md`、`gateway.md`）；`AGENTS.md` 重写核心定义（Agent、Environment、EnvironmentEvent、TurnProfile、语境段与形状、Job、WaitRequest、Plugin）、项目规约、运行控制、测试约定与当前任务；`tests/` 镜像新布局；静态 import 规则测试；`pyproject` 依赖与 package-data；本文件标记 `done` 并归档。

## 11. 测试策略与验收

测试策略：

- 目录 `tests/<layer>/<module>/test_<切面>.py`；`tests/support/` 提供 fake provider、总线观察器、最小插件与 profile fixture、fake ACP agent 进程、内存 MCP server。
- 契约优先：段协议两阶段提交与重放、三形状回收与追溯路由、收件箱 drain/wait 与控制进 Trap、`EventRouter` 三步路由与动态源注册注销、Job 生命周期（turn/agent 级、事件、collect、Turn 结束清理）、profile 的 surface 与段装配、批次并发取消与超时、Trap 转移与失败归类、Agent API 生命周期与世代切换、Endpoint v2 请求/响应/事件流、ACP 会话状态机映射、MCP 索引刷新与 `expand.call` 校验。
- owner 存储与算法测试保留；不固化提示词文案、默认 Home 内容与 catalog 清单。
- E2E：fake-provider CLI（S2 起）；旧日 Turn → 日切 → 维护 → 新日 background（S3 后）；wheel 隔离安装与 `init`（S5 后）；fake ACP agent 与内存 MCP server 的能力 E2E（S6）；真实 provider/agent/server smoke 保持 external。

验收：

- `tinysoul start` 在单事件循环内同时运行 Terminal、Endpoint v2、调度器、文件监视与 Job 监督；`start --once`、`status`、`init`、`reset` 可用。
- 三条 import 规则由测试固定；增删插件只改插件清单与该插件包。
- `kernel/context` 中不出现任何 owner 类型；MessageStack 顺序由槽位决定。
- 追加输入、stop/exit、Job 事件、定时唤醒、定时维护、文件变更全部经总线与 `EventRouter`；不存在 `TurnActivityController`、`SignalWatch`、线程版 `SignalBus`。
- 后台脚本、外部 ACP agent、嵌套 Turn 在 `jobs` 段中以同一形态可见，用同一组 `core.job.*` 等待/查询/停止。
- `expand.search → expand.call` 在不暴露全部 MCP 工具 schema 的前提下可调用任一已连接服务器的工具。
- 三层失败语义、Trap 转移、bridge payload 约束的既有测试语义保留并通过。
- `kernel/spi.py` 每个协议方法与注册表方法在仓库内至少有一个真实消费者。
- Full 门禁与 typecheck 通过；`docs/design/`、`docs/endpoint/`、`AGENTS.md` 与代码一致。

## 12. 实施结果

待填写。
