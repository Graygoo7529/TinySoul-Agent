# 分层 Agent 架构总体重构方案与执行计划

状态：`in_progress`（D1–D24 与原 S0 定稿记录保留；2026-09-14 新增架构一致性复审，第 13 节提案部分待确认；D25 单根 Turn 与 D26 Segment 职责已确认；S1–S7 尚未完成，本轮不实施代码重构）。

阅读规则：1–12 节保留上一轮已记录的方案与决策，不等于当前实现。第 13 节给出基于 `e6ee6af` 代码的冲突定位、替换预览与验收补充；涉及旧条款的替换在确认后统一回写，不能同时实现两套接口。进入 S1 前先讨论影响基础协议的 P1–P6；其它实施细节在所属阶段定稿，不要求一次性批准全部远期方案。P9 仅是历史想法参考，不能自动增加本次范围或成为 S1 前置门禁。本轮请求是设计复审，不因原文的“授权范围”或“已定稿”自动进入代码实现。

本文件同时是设计方案与执行计划。1–8 节阐述重构性质、设计意图、统一语义、架构与契约、与现有模块的联系、可行性和开放问题；9–12 节记录决策、分阶段实施、测试与验收；第 13 节记录本轮待确认的进一步修订。方案在与维护者的讨论中持续修订，修订点在第 9 节留痕。


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
| 3 | 以 agent 出发，一切是输入、输出与状态改变 | `Agent` API 只暴露输入（TurnRequest、追加输入、控制、配置 patch、环境事件）、输出（TurnOutput、Observation 流、服务读取）与状态（世代、活动、日历日、Job 表） | 本次落地 |
| 4 | Agent 置于环境中，事件驱动，DDS 式解耦 | 单一 asyncio `EventBus` 以 topic 组织事件；`EnvironmentEvent` 协议、静态/动态事件源、`EventRouter` 路由到收件箱或触发器；三种投递语义对应既有 Signal/Observation/Trap 三分法 | 本次落地 |
| 5 | 接收追加输入、订阅环境变更、暂停 Turn 与用户对话 | 追加输入进收件箱；段 `subscriptions()` 与 `TurnTrigger` 两级订阅；Workspace 文件监视是首个环境事件源；`core.ask` 暂停 Turn 等待回复 | 本次落地 |
| 6 | 执行脚本/shell、派遣 sub-agent、按间隔或事件唤醒下一 Cycle | Job 框架统一后台进程、外部 ACP agent 与内部嵌套 Turn；`WaitRequest(until, timeout)` 统一事件唤醒与定时唤醒；Job 事件仅唤醒所属 Turn，不触发新根 Turn | 本次落地 |
| 7 | 内核仍是 turn-cycle-stage-loop 与语境维护；background 冰山、trace 栈、workspace 最新状态与寄存器式里程碑 | 三分区 Background → Trace → Working；四种形状 Heap / Map / Stack / State；`session.history` 为 Map；`plan` milestone 为寄存器 | 本次落地 |
| 8 | 依赖反转：外围声明段内容与内核使用方法，内核不知内容 | 段协议 `open`（前）/`prepare·install` 与按需事件/回收/检查能力（中）/`seal·finish·close`（后）；内核只知槽位、形状与 ref scheme | 本次落地 |
| 9 | MCP 通用工具接入（`00 doing something.md`），避免 tool schema 过大 | `expand` 域：MCP 网关 + `expand.search/describe/call/servers`；搜索与描述结果进入 Trace，不设钉选段 | 本次落地·后续扩展 |

## 3. 统一设计语义

### 3.1 Agent：输入、输出与状态

Agent 是进程内唯一的智能体实例。

- 输入：`TurnRequest(profile, input, metadata, source)`、`InputAppended`、`ControlRequested(stop|exit)`、`ConfigPatch`、`EnvironmentEvent`。
- 输出：`TurnOutput(kind=answer|question, text)`、Observation 流、服务门面读取。
- 状态：配置世代、活动（`idle | preflight | turn | awaiting_input`）、日历日、Job 表、注册插件与服务状态摘要。

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

topic 分类（当前消费者）：`input.*`（终端/Endpoint）、`control.*`、`schedule.<name>.due`（reflection 触发器）、`fs.workspace.changed`（`workspace.resources` 段）、`job.<id>.*`（`jobs` 段、`core.job.wait`）、`mcp.<server>.*`（`expand` 网关刷新工具索引与资源订阅）。

### 3.3 Turn 与 TurnProfile

Turn 是一项完整 work；Cycle 由 Phase1/2/3 组成；骨架不变。

根 Turn 调度遵循 D25：同一 Agent 同时至多运行一个根 Turn，等待用户回复或后台任务期间仍占据该执行位置，不启动其它独立 User Turn 或 Reflection。显式新任务与维护请求进入队列，待当前根 Turn 完成收尾后执行；属于当前 Turn 的回复/追加输入进入其收件箱。等待只暂停当前推理推进，不暂停环境 I/O、Job 监督和取消控制。此决定不确认子 Turn 的并发、作用域或世代方案，它们仍按 P5 讨论。

差异收敛为 `TurnProfile`：guidance、Action surface、参与段集合、completion detector、completion 到 `TurnOutput` 的映射、Trap 策略追加、预算、是否接受追加输入、等待策略。内建 `user`；`plugins/home` 注册 `home_reflection`，`plugins/memory` 注册 `memory_reflection`（专属域只在对应 profile 的 surface 中出现，与常规 User Turn 的 `home` / `core.memory` 域分开）；`subagent` 插件注册 `subagent` profile（受限 surface，用于内部嵌套 Turn）。

Cycle 边界等待是一等语义：类型化 WaitRequest，区分 EVENT 与 TIMER；模型不管理 Cycle 额度，预算由内核检查并由用户追加。

日历日由 `agent/day` 持有：类型名为 `CalendarDay`（取代 `BusinessDay`），时区时钟为 `CalendarClock`。提示词、Observation、CLI 与 Endpoint 使用"今天 / 某日"；代码与持久目录日期字段使用 ISO `YYYY-MM-DD`。确定性日切、归档与新根初始化语义不变，只改名。

### 3.4 Context：槽位、形状与段

已确认 D26：Segment 是领域 Engine 为当前 Turn 提供的有状态 Context 段，维护本轮加载、展开和呈现；Engine 拥有领域事实及操作。二者不要求一一对应，无语境贡献的能力插件可以不提供段。Context 组织各段，每次模型调用由 Compose 将各段当前渲染结果与本次 TaskPrompt 构造成 MessageStack，供应商适配层再映射为请求。内核的 inputs/plan/trace 也可作为段；身份内容由 Home/配置提供，内核不解释领域内容。

段有分区槽位、槽内序号、形状、ref scheme、以及是否可逐出。MessageStack 按三分区渲染：Background → Trace → Working；Working 尾部由 loop 叠加当前 LLM Task 的 TaskPrompt overlay（不是段）。

Background 槽内顺序（D19）：`identity`（system role）→ `session.history` → `inputs` → `home.background` → `memory.background`。Phase1 会 load/evict Home 与 Memory，把会变的段放在固定段之后，避免污染 identity/history/inputs 的前缀。`identity`、`history`、`inputs` 不可逐出；`home.background`、`memory.background` 可渐进 load/evict。

四种形状定义内核对段的使用方式：

- Heap：线索在顶，条目可 `load/evict/inspect`；压力回收逐出。实例：`home.background`、`memory.background`。
- Map：关系图骨架始终可见；节点可 `inspect`；压力回收只在本段超过自身水位时有限折叠节点细节，不拆骨架。实例：`session.history`。Thread 是地图上的节点种类，不是第五种形状。
- Stack：Turn 内追加，旧帧折叠，折叠帧可 `inspect`；压力回收折叠。实例：`trace`。
- State：最新状态整体替换或 patch；压力回收收缩渲染。实例：`identity`、`inputs`、`plan`、`workspace.resources`、`jobs`。

内核统一处理：渲染框架、回收顺序（State 收缩 → Heap 逐出 → Stack 折叠 → Map 仅在自身超水位时有限折叠）、`context.load/evict(ref)` 对 Heap 有效、`core.context.inspect(ref, cursor)` 对声明 `inspect` 的段有效、`core.context.organize` 路由到 Map 段；ref 按 scheme（`home:`、`memory:`、`session:`、`trace:`）路由。

Trace 除决策、Action 调用与结果、Phase 反馈外，包含**事件帧**：`trace` 段订阅收件箱（`input.appended`、显著 `job.*`、`fs.workspace.changed`），`on_event` 追加有时序的感知记录（如"收到追加输入 #2，正文见 inputs"）。正文仍由所属段承载。`jobs` 段不自行追加 trace note。

段每 Turn 实例：注册 `ContextSegmentProvider`，Turn 开始 `open(turn)`，结束依次导出快照 `seal()`、完成业务提交 `finish(completion)`、释放资源 `close()`。段即 Turn 参与者，不再有独立的 `TurnParticipant`。语境更新的 prepare/install 只处理内存候选状态，实际领域 Action 经 Engine 门面提交业务事实，不经过 Context 事务。

### 3.5 Job：Turn 内的受监督工作

按最新讨论 D27，Job 只属于启动它的 Turn，可跨 Cycle，不跨 Turn。进程、外部 ACP agent、内部子 Turn 共用这一生命周期；删除 JobScope TURN/AGENT、scope 参数和 Job 完成触发新根 Turn 的机制。

JobRegistry 可由 Agent 统一索引，但每个 Job 必须有 owner_turn_id；注册表所在位置不代表 Job 可以跨 Turn。父 Turn 的子 Turn 本身也是 Job，父收尾递归取消并回收子工作。Job 完成/失败/请求事件投递所属 TurnInbox；父 Turn 通过子 Turn Job 的公开事件与结果了解子任务，不直接消费子收件箱。

正常终结前，Job 应已完成或明确停止；用户取消/失败时框架停止并回收剩余 Job。结果文件和 Session 事实可保留，运行对象不留到下一 Turn。collect 是读取结果，不是停止进程，也不应是释放已结束执行资源的唯一入口。

动作保留种类域内 start/send/collect，以及 core.job.status/stop 和统一等待入口。具体等待工具名待子计划确定；模型可选择匹配 Job 中间/终态事件，或等待一段时间后再运行任意探测动作。

### 3.6 Plugin 与两阶段装配

Plugin：`configure(env)`、`contribute(registry)`、可选 `finalize(view)`。装配两阶段：declare → resolve（服务表、合并 catalog、按 profile 组装段与 Trap 表、执行延迟 registrar、`finalize`）。插件间只经包根公共门面依赖；当前跨插件消费者是 reflection（编排）与 subagent/expand（经 `WorkspaceService` 落盘大块输出）。

### 3.7 asyncio 与取消

单事件循环。Agent API、总线、Turn/Cycle/Phase、LLM、Action 批次、进程后端、事件源、Job、MCP/ACP 客户端、Endpoint 全部 async。持久 owner 存储引擎保持同步，适配层触盘经 `to_thread`，同步引擎不触碰 asyncio 对象。

取消沿用现有"边界权威"模型，不依赖 asyncio 的 Task 取消传播：

- `TurnCancellation` 保留为协作式令牌（底层改为 `asyncio.Event`），stop/exit 请求先置令牌，再在 Phase/Cycle 边界由收件箱控制事件转为 Trap。控制流只在边界改变，与现 `CycleRunner._boundary` 语义一致。
- Phase 内 in-flight await 与令牌竞争：LLM 调用以 `asyncio.wait({provider_task, cancel_wait}, FIRST_COMPLETED)` 取代现有守护线程轮询，命中令牌时取消 provider task 并抛 `TaskCancelled`，Phase 返回 `cancelled`，由边界收敛；Action 批次 runner 以同样方式观察令牌与 deadline。
- `ActionExecutionControl`（deadline、cancel_event、cancel callbacks）保留：它是线程内同步 executor 与进程后端唯一能观察到的协作取消手段；批次 runner 改用 asyncio 原语等待，但对 execution 的取消仍经 `control.request_cancel`。
- asyncio 的硬取消（`Task.cancel()`）只在 `Agent.stop()/exit()` 宽限期后对活动 Turn Task 使用，属于进程收尾而非业务控制流；模块内 `except Exception` 不吞 `CancelledError`。

### 3.8 失败三层语义

不变。每个插件自带 `failures.py` 与 `runtime_bridge.py`，复用 `runtime/bridge/_payload.runtime_exception()` 构造 payload（`module` + `kind`）；`runtime/bridge/` 只保留 `_payload` 与内核模块 bridge。Trap 原因的所有权同样分层：`runtime` 只定义 `runtime.startup_failed | turn_end | cycle_end | agent_end`；`kernel/context` 定义 `context.compression_required`；`home.runtime_copy_required` 由 home 插件定义并经 `registry.trap_handler` 登记（现 `TrapHandlerRegistry` 已支持 exact/prefix/fallback，无需改动）。现 `runtime/exception.py` 中集中声明业务原因常量的做法取消。`workspace.trash_restore_required` 随 D24 删除。ACP/MCP 的协议错误在插件边界归类：工具返回 `is_error` 是局部结果；连接/握手失败是模块边界异常；不进入 Runtime。

## 4. 分层架构与包布局

```text
L5 gateway      cli · endpoint v2 (http/ws) · project init/reset
L4 agent        Agent 门面 · assembly · TurnScheduler · EventRouter · JobRegistry 实例 · generation · day · profiles/user · services · status
L3 plugins      home · memory · session · workspace · reflection · capabilities/{resource,web,execution,subagent,expand}
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
    home/ memory/ session/ workspace/ reflection/
    capabilities/
      resource/ web/
      execution/            # script、shell、process Job 种类；域 execution
      subagent/             # ACP 客户端与 tinysoul_turn Job 种类；域 subagent；subagent profile
      expand/               # MCP 网关、工具索引；域 expand
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

插件包统一结构：`plugin.py`、`config.py`、`engine.py|service.py`、`segments.py`、`actions.py`、`jobs.py`（Job 种类，按需）、`catalog/<domain>/`（按需）、`participants.py`（DayParticipant，按需）、`failures.py`、`runtime_bridge.py`、`errors.py`。

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

`TurnScheduler` 串行消费 TurnRequest；每 Turn 前由 `agent/day` 取得日历日 lease；持有活动 Turn 收件箱。`EventRouter` 按 3.2 路由。嵌套 Turn（`tinysoul_turn` Job）不进队列，作为父 Turn 内的 Task 运行，共享 owner 引擎，段实例独立。

### 5.2 PluginRegistry

```python
class PluginRegistry(Protocol):
    def context_segment(self, provider: ContextSegmentProvider, *, profiles: frozenset[str] | None = None) -> None: ...
    def actions(self, registrar: ActionRegistrar) -> None: ...
    def action_catalog_fragment(self, root: Path, *, package_only: bool = False) -> None: ...
    def trap_handler(self, reason: str, handler: TrapHandler, *, profiles: frozenset[str] | None = None) -> None: ...
    def turn_profile(self, profile: TurnProfile) -> None: ...
    def daily_participant(self, participant: DayParticipant) -> None: ...
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
    async def prepare(self, updates: tuple[SegmentUpdate, ...]) -> PreparedSegment: ...
    def install(self, prepared: PreparedSegment) -> None: ...
    def seal(self) -> SegmentSnapshot: ...
    async def finish(self, completion: TurnCompletion) -> None: ...
    async def close(self) -> None: ...
```

以上是生命周期协议草图，具体类型定义在实施子计划中收敛。load/evict/inspect/organize/reclaim、控制工具与事件订阅按能力声明，不强制每个段实现空方法。

`ContextEngine`：按 profile 选段并打开；`compose` 依分区与槽内序号渲染，保留消息角色和 ToolResult 语义，再叠加 TaskPrompt。边界捕获更新批次，各段 prepare 校验完整有序批次、计算候选状态并完成必要读取；无效模型更新返回局部结果。全部准备完成后，在无 await、无 I/O 的提交边界安装候选内存状态。准备可重放，安装后的批次不可盲目重放；这不提供跨 owner 持久事务。结束时所有段 seal，再完成业务 finish（Session 最后），最后逆序 close 释放资源；细化约束见 13.4。并行 open 的必要性与依赖次序待实施子计划确认，不作为通用保证。

`TurnInfo`（`open` 的输入）：`turn_id`、`profile`、`calendar_day`、`request.metadata`（如 `memory_reflection` 的 `target_day`、Job 完成通告的 `job_id`）、`parent_turn_id`；段据此决定打开当日还是归档日、读写还是只读。

内核段：`identity`、`inputs`、`plan`（控制工具 `plan.patch`；milestone 字段 status、value、source link、revision/digest、note）、`trace`、`jobs`。插件段：`home.background`（Heap）、`memory.background`（Heap）、`session.history`（Map）、`workspace.resources`（State，订阅 `fs.workspace.changed`）。不设 `expand.tools` 段。

`trace.seal()` 除折叠后的语义节点与事件帧外，直接给出 `actions` 投影（Phase2 调用与 Phase3 结果按 call_id 配对、含 outcome/failure/references）以及供 Session 抽取的结构化材料：问答、追加输入、`core.reason` 结果摘要、动作引用的 links。现由 `session/completion.py` 解析 sealed trace 的做法取消。

`session.history`（Map）在 `finish` 时无模型固定构建：从 completion 写入不可变 `SessionTurnRecord`，并更新当日 `SessionMap`（`runtime/session/map.json`，随 Session 归档）。抽取字段：初始提问、追加/追问输入、回答或 `core.ask` 问题、outcome、`core.reason` 与其它动作摘要、动作与回答中的 `workspace:` / `memory:` / `home:` / 外部 URL / MCP 工具 id、`plan` 中的 milestone。节点 `turn` / `thread` / `resource` / `link` / `decision`；边 `follows` / `continues` / `touches` / `decides`。Turn 结束时 thread 可暂缺，`organized=false`。新 User Turn 开始时 history 渲染地图骨架，并对上一个成功 Turn（`ANSWERED | COMPLETED | AWAITING_USER`）给出待整理标记。`core.context.organize` 由当前 Turn 的模型调用，把 gist、thread 归属与补全关系写回地图；不在 `close` 里跑 LLM。`SessionSummaryRecord` 删除。压力回收：history 不参与 Heap 式逐出；仅当本段渲染超过自身水位时，把较早已整理 thread 的逐 Turn 行折成 gist 一行，骨架与未整理 Turn 不折。

`core.context.inspect(ref, cursor)` 是唯一追溯动作（D20）：`trace:` 折叠帧、`session:` 地图节点或完整 Turn 记录分页、`home:` / `memory:` 背景条目。`context.load/evict` 只面向 Heap。错配 scheme 为局部失败。

压力回收顺序为 State 收缩 → Heap 逐出 → Stack 折叠 → Map 有限折叠：State 收缩（`workspace.resources` 按目录折计数、`jobs` 折叠已结束项）几乎不损失决策信息且不触盘；Heap 条目可经 `context.load` 重新加载；Stack 折叠丢失本轮细节但可 `inspect`；Map 最后动、且只在自身过大时折叠。每轮逐段询问 `reclaim(required_chars)` 直到满足目标或全部返回 0，无进展则按现有 `ContextPressureTrapHandler` 语义结束 Turn。

### 5.4 TurnProfile、等待与用户预算决策

TurnProfile 声明 guidance、Action surface、段集合、完成规则、预算配置和等待策略；不把运行时剩余 Cycle 数放进模型语境，不提供模型申请额度工具，不保留 extend_budget。

模型可请求两种等待：EVENT（匹配环境/Job 事件）与 TIMER（指定时间后进入下一 Cycle）。core.ask 产生 INPUT 等待。等待意图由 Action 正常返回后在 Cycle 边界执行，不占用长时 Phase3 executor；等待不消耗 Cycle。定时等待可被哪些终态事件提前打断、输入等待超时策略，见 13.13 待确认项，不把原 30 分钟当成已确认默认值。

Cycle 启动前由确定性代码检查预算；不足触发预算 Runtime 异常，当前 Turn 进入 BUDGET 暂停，用户选择中断或增加 Cycle 后继续。已完成的 Cycle 不重放；新的额度只由 typed 用户控制入口写入。预算提示属于运行时控制交互，不是模型 core.ask，也不把授权文本当作普通用户追加输入。

TurnInbox 在所有等待期间持续接收事件；恢复时先处理控制和待消费事件，再构造下一次 MessageStack。Job 继续受监督，预算暂停不自动暂停外部进程；事件就绪不绕过预算。暂停转移与精确恢复点为 13.13 提案，尚未实现。

### 5.5 Action 框架

`ActionEngine` 门面不变，`run_batch` async。`ActionBatchRunner` 每 execution 一个 Task，`asyncio.wait(FIRST_COMPLETED)` 同时观察 deadline 与 Turn 取消令牌，超时或取消时对 execution `control.request_cancel` 并等待宽限期，仍未收敛者标记 `executor_leaked` 并阻断同批后续 execution（现有 `leaked_timeout` 语义保留）；首个 `RuntimeException`/`RuntimeTransferInterrupt` 出现时取消同组后原样上抛，不用 `TaskGroup`。`ActionExecutor.execute` 为 async；native 同步 executor 经 `to_thread` 承载并继续以 `control.check_cancelled()` 协作；subprocess 后端 `create_subprocess_exec`；`llm_action` async。`ActionExecutionContext` 保留 `control`、`module_runner`（async 版 `RuntimeModuleRunner`），新增 `turn`：`turn_id`、`calendar_day`、`request_wait`、`jobs`、`publish(EnvironmentEvent)`；`signal_bus` 改为 `bus`（EventBus）。

Schema 子集已支持自由形态 `object`（`action/core/schema.py` 中 `type: object` 允许省略 `properties`，`additionalProperties` 默认 `true`），`expand.call.arguments` 可直接声明为 `{ "type": "object" }`，无需扩展校验器。

### 5.6 `execution` 域（进程 Job 种类）

`plugins/capabilities/execution/` 合并现 script、shell、supervised_process：一个域一个插件。`execution.run_script`、`execution.run_shell` 保留前台有界执行；`execution.start(kind=script|shell, source, args) -> job_id` 启动 `process` Job；`execution.stdin(job_id, text)`；`execution.collect(job_id)` 返回 stdout/stderr 摘要与 `workspace:` 落盘 Link。等待/状态/停止用 `core.job.*`。进程树终止逻辑保留。

### 5.7 `subagent` 域（ACP 与嵌套 Turn）

依赖：ACP Python SDK（在子计划中核实包名与版本）。协议要点（ACP v2）：JSON-RPC 2.0 over stdio NDJSON；`initialize → session/new(cwd, mcpServers?) → session/prompt` 立即返回，随后 `session/update` 通知流（`user_message`、`agent_message(_chunk)`、`agent_thought`、`tool_call(_update)`、`plan`、`state_update: running|idle(stopReason)`）；`session/cancel`；agent 反向请求 `session/request_permission`。

- 配置：`[capabilities.subagent.agents.<name>]`：`command`、`args`、`cwd_policy = workspace | project | path`、`permission_policy`（`auto_allow` 列表 + 默认 `ask_model` | `deny`）、`env`。
- `acp_agent` Job 种类：spawn → initialize → session/new（cwd 按策略解析到 Workspace 目录）→ prompt。`session/update` 映射为 `job.<id>.message | state | output`（tool_call 摘要）；`request_permission` 映射为 `job.<id>.permission_request` 并置 `waiting_input`，按策略自动应答或等待模型；`idle(stopReason)` → `exited`。`send` = 追加 `session/prompt`；`stop` = `session/cancel` + `session/close` + 进程终止。
- `tinysoul_turn` Job 种类：以 `subagent` profile 在父 Turn 内运行嵌套 Turn；子 Turn 输出映射为 `job.<id>.message`；`send` = 子收件箱追加输入；父 stop 传播为子 stop；Session 记录子 Turn 带 `parent_turn_id`。
- 动作：`subagent.start(agent, brief, references) -> job_id`、`subagent.prompt(job_id, message)`、`subagent.respond(job_id, request_id, option)`、`subagent.collect(job_id)`（最终消息、stopReason、变更文件摘要）。等待/状态/停止用 `core.job.*`。
- Workspace 联动：sub-agent 在 Workspace 目录内改动文件，由 `fs.workspace.changed` 事件驱动 `workspace.resources` 段刷新与 manifest reconcile。
- 不在范围：TinySoul 作为 ACP server 被外部客户端驱动（可作为 gateway 的后续选项）。

### 5.8 `expand` 域（MCP 通用工具）

依赖：MCP Python SDK v2（`mcp`，async；`Client` 支持 stdio 与 Streamable HTTP；`list_tools/call_tool`；`listen(tools_list_changed, resource_subscriptions)` 订阅流）。

- 配置：`[capabilities.expand.servers.<name>]`：`transport = stdio | http`、`command/args` 或 `url/headers`、`enabled`、`tool_allowlist`、`connect = eager | lazy`。
- `McpGateway` 服务（agent 级）：连接、工具索引（server、name、title、description、input_schema）、`listen` 任务把 `ToolsListChanged/ResourceUpdated` 发布为 `mcp.<server>.tools_changed | resource_updated` 环境事件并刷新索引；每个连接是动态事件源。
- 不设 `expand.tools` 段。`expand.search` 与 `expand.describe` 的结果（候选 / 完整 schema）作为 foldable Action 结果进入 Trace；schema 被折叠后可 `core.context.inspect` 或重新 `describe`。跨 Turn 用过的工具由 Session 地图的 `link` 节点承接。
- 动作：`expand.search(query, limit)` 在索引上做词法 + 可选语义检索；`expand.describe(tool_ids)` 返回完整 schema；`expand.call(tool_id, arguments)` 按网关索引中的 schema 校验（不在索引或不合法为局部失败，反馈附 schema 摘要），再 `call_tool`，结果归一化为文本摘要 + `structured_content`，超限内容经 `WorkspaceService` 落盘为 `workspace:` Link；`expand.servers()` 列出已连接服务器与工具计数。
- tool-search 的设计意图：Phase2 只看到 `expand.*` 四个稳定动作；搜索是线索、描述是加载，调用不依赖钉选。MCP 工具 `inputSchema` 超出本项目 schema 子集时，超出键只透传不校验（S6 子计划锁策略）。
- 后续扩展：`expand.read_resource`、prompts、长时调用作为 `mcp_call` Job 种类。

### 5.9 Endpoint v2

- `GET /v2/health`；其余 Bearer。
- `GET /v2/agent`、`POST /v2/agent/restart`、`POST /v2/agent/reload`（显式激活配置）。
- `POST /v2/turns`、`GET /v2/turns/{id}`（状态含 `awaiting_input`）、`POST /v2/turns/{id}/inputs`、`POST /v2/turns/{id}/control`。
- `GET /v2/jobs`、`GET /v2/jobs/{id}`、`POST /v2/jobs/{id}/stop`。
- `POST /v2/events`（外部环境事件代理）、`GET /v2/events`（replay）、`WS /v2/events`（流）。
- `GET /v2/config`、`GET /v2/config/catalog`、`GET /v2/config/actions`、`PATCH /v2/config`（只写文件事务，可多次批量修改后统一 reload）。
- `GET /v2/reflection`、`POST /v2/reflection/home`、`POST /v2/reflection/memory`（经 `ReflectionService`；取代 `/v2/maintenance`）。
- `/v2/workspace/*` 经 `WorkspaceService`。
- 连接描述、实例 lease、事件缓冲与 journal 保留。

### 5.10 Prompts

`kernel/prompts/` 集中框架提示词与 `PromptBlock` 构造器；插件动作内部提示词留在插件。

### 5.11 Reflection（Home / Memory 专属域）

`plugins/maintenance` 改为 `plugins/reflection`：只编排触发与完成，不拥有 Home/Memory 存储，也不合并成单一 reflection 域。

- 两个 TurnProfile：`home_reflection`、`memory_reflection`。各自 Action surface 含通用 `core.context.inspect` / `core.memory.inspect|recall`（只读）加上专属域；User Turn 的 catalog 物理上不含这两个域。
- 关键边界：User Turn 不写持久 Memory、不提交 actual Home。白天 `home.*` 只改 runtime overlay（副本）；`core.memory.memorize` 只 patch 当日 `Memory.md`。持久 `memory/` 与 actual Home 只由对应 Reflection Turn 更新。
- `home_reflection`：`diff_list`、`diff(path)`、`accept(path|all)`、`reject(path|all)`、`rewrite(path, instruction)`、`done(summary)`。对照 overlay 与 actual；接受后才写入 actual。保留 overlay 与 `home.runtime_copy_required` Trap。不引入 git。
- `memory_reflection`：轻量单文档写。`write_daily(day, markdown)`、`write(kind, cite, markdown)`、`retire(link, redirect_to, note)`、`done(summary)`。删除 8 步控制器、preview、多文档 journal、CAS digest，以及 frontmatter 中的 `revision` / `activation_count` / `session_revision` / `active_memory_digest`。frontmatter 保留 `kind, cite, status, created_on, updated_on, related, sources, redirect_to, summary|title, confidence?`。目标日可以是今天或任一有 Session 的过去日。
- 触发：`registry.schedule` + `TurnTrigger`（有 overlay 待审 → home_reflection；有 Session 而无 daily → memory_reflection）；手动 `/reflect home`、`/reflect memory YYYY-MM-DD`。删除 `availability.json`，待办由门面即时计算并经 `agent.status()` 暴露。
- Context 与 User Turn 同构；history 打开目标日地图；workspace 在 memory_reflection 下为目标日只读视图。

### 5.12 Workspace 动作面

域 `workspace` 去防御化（D24），细节在 S3 子计划锁默认预算：

- 保留：`workspace:` 链接与路径沙箱、轻量 manifest（path、kind、size、mtime、summary、description、tags）、Engine 锁、简单 Trash（原子移动到 `.tinysoul/trash/<ts>/` 并可 restore）、日切归档、read/search 的 foldable trace。
- 删除：`expected_digest` / `expected_revision` CAS、`WorkspaceEditReadSet` 复验、`described_digest`、`retention` / `owner_turn_id`、压力驱动 trash、Trash prepare/commit marker、`workspace.trash_restore_required` Trap。外部改写由 `fswatch` → manifest 刷新 → trace 事件帧告知模型。
- 动作：`list`、`search(literal|regex)`、`read`（小文件可整读）、`write`、`edit`（多处精确替换，全部命中才提交）、`append`、`move`、`mkdir`、`delete` / `restore` / `trash_list`、`tag`（`pinned` | `tmp` | `library`）、`describe`、`compose`（合并原 create/rewrite）、`analyze`（预算放宽）。`scan` 改为 Turn 开始与 fswatch 触发的内部操作。
- `workspace.resources.reclaim` 只按目录折叠渲染，不触盘。

## 6. 与现有模块的联系与迁移映射

| 现模块 | 新位置 | 保留（搬迁） | 改变（重写） |
|---|---|---|---|
| `infra` | `infra` | 全部 | asyncio 并发原语；`BusinessDay` → `CalendarDay`；线程 RW lock 保留给同步引擎 |
| `runtime` | `runtime` | scope/trap/transfer/exception/generation 语义；`TrapHandlerRegistry` exact/prefix/fallback；`RuntimeModuleRunner` 重放语义；`_payload` | `signals/` → `events/`；`RuntimeHandle` 由 `Condition(RLock)` 改为 asyncio 读写/活动 lease；`RunLevel.PROGRAM→AGENT`、`runtime.program_end→agent_end`；`exception.py` 只保留四个 runtime 原因，业务原因常量迁回 owner；bridge 收敛 |
| `llm` | `llm` | 协议、映射、模型链、重试、水位 | provider/task runner async；删除线程轮询 |
| `loop` | `kernel/loop` + `agent/profiles/user` + plugins | Turn/Cycle/Phase 骨架、cancellation、outcomes、PhaseFailure | async；收件箱与 WaitRequest 取代 `TurnActivityController`；`loop/user/*` 拆到 user profile 与各插件 |
| `context` | `kernel/context` | trace 堆、Working plan、background 堆算法、compressor、composer、控制工具归一化 | 三分区与四形状；删除 owner 特判；`ContextTurnCompletion` 泛化为 `segments` |
| `action` | `kernel/action` | catalog 四层、loader、schema、hooks、result、rendering、scope | runner asyncio；catalog 模板拆到插件；`ActionExecutionContext.turn` |
| `app` | `agent` + `environment` + `gateway/project` | initializer/resetter/instance、调度计时、终端解析；`ProgramRunner.run` 的串行请求循环、preflight、世代活动 lease、Program 级转移消费 | `ProgramRunner` → `TurnScheduler`（`Queue.get(timeout=0.5)` 轮询改为 `asyncio.Queue`）；`ProgramGeneration` → `AgentGeneration`（按 profile 装配的段 provider、Action surface、Trap 表）；`RuntimeActivity` 扩展 `preflight | awaiting_input`；builder（935 行）→ assembly + 各插件 `contribute`；gateway/inputs → EventRouter/Agent API；outputs → Observation 订阅 |
| `endpoint` | `gateway/endpoint` | auth、lease、事件缓冲、journal、host | v2 路由与 schema |
| `maintenance` | `agent/day` + `plugins/reflection` | `day.py` 时钟与日切；`archive/engine.py` 的 coordinator、journal（SESSION_ARCHIVED → WORKSPACE_ARCHIVED → ACTIVE_INITIALIZED）、lease；`schedule.py`；Home/Memory 任务编排 | `BusinessClock` → `CalendarClock` 并迁 `agent/day`；三个 owner 日切协议合并为 `DayParticipant`；删除 `availability.json`；builder → plugin；两个 profile `home_reflection` / `memory_reflection` 与专属域；`MaintenanceSchedule.due` → `registry.schedule` + `TurnTrigger` |
| `session` | `plugins/session` | 记录图、inspect、continuation、`memory_facts` | `history` Map 段：`finish` 无模型抽取问答/追问/推理/links 并更新 `SessionMap`；`core.context.organize` 在新 Turn 整理上一成功 Turn；schema v5；删除 `SessionSummaryRecord` 与线性 background；inspect 走 `core.context.inspect` |
| `workspace` | `plugins/workspace` | 链接沙箱、扫描/分类、Engine 锁、简单 Trash、归档 | 删除 CAS/复验/retention/压力 trash/Trash marker 与 restore Trap；动作面改为 list/search/read/write/edit/append/move/mkdir/tag/compose/analyze；`resources` State 段只收缩渲染；`WorkspaceService` |
| `home` | `plugins/home` | actual/overlay/review/skills | `home.background` Heap 段；User Turn 只写 overlay；`home_reflection` 域做 diff 审阅；prompt mount reconcile 移入 `finalize`；runtime copy Trap 保留 |
| `memory` | `plugins/memory` | codec、catalog、backlinks、embedding、Memory.md | `memory.background` Heap 段；User Turn 只 `memorize`；`memory_reflection` 轻量单文档写；删除 8 步控制器、preview、多文档事务与 CAS/revision/activation_count |
| `capabilities/{script,shell,supervised_process}` | `plugins/capabilities/execution` | handler、进程管理、进程树终止 | 合并为一个域一个插件；supervised 重写为 `process` Job 种类；删除对 loop/context 的 import |
| `capabilities/{resource,web}` | `plugins/capabilities/{resource,web}` | worker 与协议 | registrar 化 |
| （新） | `plugins/capabilities/subagent` | — | ACP 客户端、`acp_agent`/`tinysoul_turn` Job 种类、`subagent` profile |
| （新） | `plugins/capabilities/expand` | — | MCP 网关、工具索引、四个动作；不设钉选段 |
| （新） | `environment/fswatch.py` | — | Workspace 文件监视事件源（`watchfiles`） |

## 7. 可行性与风险

规模与分层评估同前一版（内核 13.5k、llm 6.5k、owner 17k、capabilities 8.4k、外层 9.5k；测试 885 例；38 文件用 threading）。新增部分的可行性：

- Job 框架：现 `supervised_process/manager.py`（770 行）已有进程注册表、输出缓冲、等待、清理的全部算法，改写为 `process` Job 种类是结构内重排；`jobs` 段与 `core.job.*` 是新增但边界清晰。
- ACP：协议为 stdio NDJSON JSON-RPC，与进程后端同一基础；SDK 为 async。风险在权限请求的策略设计与外部 agent 行为差异；先以一个 agent（如 Codex/Claude Code CLI 的 ACP adapter）验证。
- MCP：SDK v2 async，`Client` 一行连接；自由形态 object 参数已被现有 schema 子集接受（见 5.5）；剩余风险是远程服务器 300s 读超时与 Action 超时的协调，以及 MCP 工具自身 `inputSchema` 超出本项目 schema 子集时的透传策略（S6 子计划：超出键只透传不校验）。
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
- 默认 Background 不经 Signal，而由 `ContextTurnPreparationHandler` 直接调用 `ContextEngine.prepare_default_background`，Home/Memory 内容经 Context 持有的 loader/provider 反向注入 → `home.background`/`memory.background` 段在 `open` 内自行准备。
- 维护日切以三个 owner 专用协议（`SessionDailyLifecycle`、`WorkspaceDailyLifecycle`、`ActiveMemoryDailyLifecycle`）由 `DailyLifecycleCoordinator` 分别调用 → 一个 `DayParticipant` 协议，参与者按注册顺序执行。
- `SupervisedProcessManager.wait_before_cycle` 用 `SignalWatch.wait_for_matching` 等待同 Turn 的 `input.append` 或 `control.request` → `WaitRequest(until=EventFilter(job.<id>.* | input.* | control.*))`，等待条件由发起方声明而非硬编码在 owner 中。
- 压力恢复分 `UserContextPressureRecovery` 与 `MaintenanceContextPressureRecovery` 两个 owner 特判实现，`loop/user/pressure.py` 直接 import Workspace 类型 → 内核按形状顺序调用各段 `reclaim`；Workspace 不再因压力 trash 磁盘。

风险与对策（R1–R9 同前），新增：

- R10 已按 D27 简化：Job 不跨 Turn；风险集中在取消是否真正回收、最后事件是否记录。未完成收尾不能释放日/世代 lease。
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

决策（D11，已被 D20 撤销）：曾暴露两个模型侧动作。现行方案只保留 `core.context.inspect`，见 8.7。

### 8.2 环境订阅（已决，D13）

两级机制与首个事件源 Workspace 文件监视并入 S4；完整协议见 3.2。

### 8.3 sub-agent（已决，D15）

作为 `subagent` 域与 Job 框架的一部分，见 5.7。嵌套 Turn 不再是"在 Phase3 内联运行"，而是 `tinysoul_turn` Job 种类，与外部 ACP agent 同一监督界面。

### 8.4 配置激活（已决，D12）

`PATCH /v2/config` 只写文件，`POST /v2/agent/reload` 显式激活；允许多次修改后统一 reload。

### 8.5 MCP `expand` 域（已决，D16；钉选段由 D22 修订）

见 5.8。待 S6 子计划确认：语义检索是否默认开启、大结果落盘阈值。

### 8.6 D19 Context 三分区（已决）

`SegmentSlot = BACKGROUND | TRACE | WORKING`；槽内 `order`；`evictable` 为段属性。Background 顺序为 `identity → history → inputs → home → memory`（Phase1 会变更 home/memory，固定段在前）。Trace 含事件帧。Working 为 `plan → workspace.resources → jobs`，TaskPrompt overlay 接在尾部。不设 `expand.tools` 段。完整语义见 3.4。

### 8.7 D20 统一追溯动作（已决，撤销 D11）

只保留 `core.context.inspect(ref, cursor)`，按 scheme 路由。另增 `core.context.organize` 供 Map 段整理上一成功 Turn。`context.load/evict` 仍只面向 Heap。

### 8.8 D21 Session 语义地图（已决）

引入第四形状 **Map**（Thread 是节点种类，不是形状）。Turn 结束用无模型结构化抽取写入 `SessionTurnRecord` 与 `SessionMap`；新 Turn 用 `core.context.organize` 整理上一成功 Turn（gist、thread、补全关系）。压缩时 history 最后动，且仅当本段超过自身水位才有限折叠已整理 thread。不在 `close` 中跑 LLM。详见 5.3。

### 8.9 D22 `expand` 不设钉选段（已决，修订 D16）

取消 `expand.tools`。搜索/描述进入 Trace；`call` 按网关索引校验。动作四个：`search` / `describe` / `call` / `servers`。见 5.8。

### 8.10 D23 Reflection 取代 Maintenance（已决）

`plugins/maintenance` → `plugins/reflection`。**不合并**单一 reflection 域：`home_reflection` 与 `memory_reflection` 两个 profile + 两个专属域，仅在对应 Turn 出现。`BusinessDay` 更名为 `CalendarDay`，内部也不保留 Business Day 一词。User Turn 不写持久 Memory、不提交 actual Home。Home 保留 overlay：白天 `home.*` 改副本，`home_reflection` 做 diff 审阅（list/detail/accept/reject/rewrite），不引入 git。Memory Reflection 删除 8 步控制器、preview、多文档事务与 CAS/revision/activation_count。见 5.11。

### 8.11 D24 Workspace 去防御化（已决）

删除 CAS/复验/retention/压力 trash 及相关 Trap；扩充 list/search(regex)/read/write/edit/move/tag 等动作。见 5.12。

## 9. 决策记录

最近讨论的有效修订（优先于下方历史条款）：

- D27：Job 归属于 Turn，可跨 Cycle，不跨 Turn；运行工作在 Turn 收尾中回收。依据用户提出限制并继续认可后续统一等待设计，替换旧 AGENT scope。
- D28：模型可选择事件等待或定时等待；预算不向模型公开，由确定性代码检查，不足触发异常，用户决定中断或补充 Cycle。取消模型申请额度与 extend_budget。
- D29：TurnInbox 是暂停期间环境事件的接收与待处理记录，覆盖所有相关环境事件，不是独立 Job 缓存；接收生命周期独立于 Cycle 推进。具体容量与暂停转移仍见 13.13 待确认设计。

已确认（2026-09-14）：

- 分层包布局；Endpoint 重设计；内核全面 asyncio。
- D1 owner 存储引擎保持同步，适配层 `to_thread`。
- D2 事件唤醒、环境事件协议、Job 框架、Agent 生命周期 API 本次落地。
- D3 原地迁移 + 行走骨架；主机部署在 gateway 阶段前继续运行旧 checkout。
- D4 `llm` 保留顶层包。
- D5 引入 `pytest-asyncio`。
- D6 milestones/todos 为内核 `plan` 段；Workspace 资源为插件 State 段。
- D7 撤销"不建立 ask/pause/awaiting 状态"规约。
- D8 TOML section 名稳定，仅 `[app]→[agent]`、`[maintenance]→[reflection]`；新增 `[capabilities.subagent]`、`[capabilities.expand]`、`[environment.fswatch]`。
- D9 Session 记录 schema v5（`segments` 通用快照取代 `working`/`background_links`，`actions` 来自 `trace` 段 seal，可空 `parent_turn_id`），不迁移 v4 归档；另增 `SessionMap`。
- D10 `core.ask` 纳入，S4 实现。
- D12 配置显式 reload。
- D13 环境事件完整协议 + Workspace 文件监视并入 S4。
- D14 Home/Memory 分立 Heap 段；日切归 `agent/day`；Session 原定在 `history.close` 记录，现按 D26 改为 `history.finish`，close 只释放资源。
- D15 sub-agent 作为 `subagent` 域，经 ACP 接入外部 agent，经 `tinysoul_turn` Job 接入内部嵌套 Turn。
- D16 `expand` 域经 MCP 接入通用工具；D22 取消钉选段，动作改为 `search/describe/call/servers`。
- D11 撤销；D20 只保留 `core.context.inspect`，并增 `core.context.organize`。
- D17 `execution` 域合并 script/shell/supervised_process 为一个插件。
- D18 `subagent` 首个验证目标为成熟的 ACP agent（Codex 或 Claude Code 的 ACP adapter，子计划中确定）；默认权限策略：读操作 `auto_allow`，写操作 `ask_model`。
- Job 框架作为内核概念（三种种类、`jobs` 段、通用控制 + 域内 start/send/collect）；原两种作用域按 D27 撤销，统一 owner_turn_id。
- D19 Context 三分区 Background → Trace → Working；Background 顺序 `identity → history → inputs → home → memory`；trace 事件帧。
- D21 Session history 为 Map 形状；Turn 结束无模型结构化抽取；新 Turn 用 `core.context.organize` 整理上一成功 Turn；压缩时仅自身超水位才有限折叠。
- D23 `plugins/maintenance` → `plugins/reflection`；`BusinessDay` → `CalendarDay`；两个专属 profile/域 `home_reflection` / `memory_reflection` 不合并；User Turn 不写持久 Memory、不提交 actual Home；Home 保留 overlay + review，不引入 git；Memory Reflection 轻量化。
- D24 Workspace 去防御化与动作面扩充。
- D25 单根 Turn 调度（维护者本轮明确确认）：等待用户回复或后台任务期间，不启动其它独立用户任务或 Reflection；新根请求排队，当前 Turn 的回复/追加输入仍进入当前 Turn。环境事件、Job 监督与取消控制继续运行，不另建多根 Turn 并发调度器。
- D26 Segment/Engine/Context 关系（维护者讨论认可）：Engine 拥有领域事实与操作，Segment 提供当前 Turn 的有状态语境视图；Context 组织各段并为每次调用构造 MessageStack。实际 Action 走 Engine 门面；内存语境准备/安装分开，结束业务提交/资源清理分开，不建设通用持久事务框架。确认的是这些语义，不是 P3/P5 所有接口、顺序与资源策略。

待决：本轮新增 P1–P9，见第 13 节；其中 P4 的单根 Turn 调度为 D25，P3 的 Segment 职责和生命周期分离为 D26；其余细节仍待讨论。D1–D24 的历史确认状态不变；存在冲突的具体条款按第 13 节列出的替换范围讨论，确认后整体回写。

修订留痕：

- 维护者本轮确认 D25：等待期间无需并发另一项独立用户任务或 Reflection；已回写 3.3 与 P4，子 Turn/Job 生命周期等其它提案不随此决定自动确认。

- 2026-09-14 初稿曾以"当前无消费者"删除段 `shape`、段级 `inspect`/`on_event`；复审后恢复并升格为统一语义，同时删除 `BackgroundEntryProvider`、`TurnParticipant`、`TurnPreflight`。
- 2026-09-14 依维护者补充，把后台进程、外部 sub-agent、嵌套 Turn 统一为 Job 框架，环境事件升格为完整协议（`EnvironmentEvent`、静态/动态源、`EventRouter`），新增 `subagent` 与 `expand` 两个域；嵌套 Turn 由"Phase3 内联"改为 Job 种类。
- 2026-09-14 对照现有代码复审（见 7.1）：修正 3.7 取消模型、3.8 Trap 原因所有权、5.3 批次语义、5.4 outcome 枚举、5.5 执行控制保留；同步微调 `AGENTS.md`。
- 2026-09-14 维护者确认 D19–D24：Background 固定段在前；Session Map 无模型抽取 + organize 动作；第四形状 Map；Reflection 分两个专属域且保留 Home overlay review；Workspace 去防御化；`CalendarDay` 取代 Business Day。
- 2026-09-14 再次通读 AGENTS 与关键实现：新增第 13 节，明确 bridge 反向依赖、全局事件投递、段提交与收尾、等待竞态、Job 跨日和世代、SDK 生命周期、异常边界及阶段门禁。新增提案均为 pending，未把复审意见登记为维护者已确认。当前 checkout 未包含被 `.gitignore` 忽略的 `docs/chat/00 doing something.md`，不声称已读其内容。
- 2026-09-14 维护者随后上传 `00 doing something.md`，已全文阅读并追加 P9 需求映射；上条资料缺口已补齐。附件作为未来想法与范围依据，内部互相冲突的旧条目不自动覆盖已确认 D19–D24。
- 2026-09-14 维护者进一步澄清：`doing something` 有些陈旧，仅供参考，关键是继续讨论架构与执行计划细节。P9 降为候选议题索引，不构成新需求确认；Observation 两级化、多模态协议、Library、引用字段改名等均不据附件直接实施。后续以当前讨论确认的语义为准。

## 10. 分阶段实施

每阶段开始前写入子计划 `docs/analysis/2026MMDD-<stage>-execution-plan.md`，完成后归档；本文件只勾选阶段。门禁：聚焦测试 → Fast → Full → typecheck；S2 起 fake-provider CLI E2E 必过。

- [x] S0 方案定稿：全部决策关闭（2026-09-14，含 D19–D24）；不改代码。`docs/design/architecture.md` 推迟到 S2 内核落地时建立，以遵守设计文档与代码一致的规则；在此之前本文件是唯一设计来源。
- [ ] S0 复审补充：讨论第 13 节 P1–P9，确认后回写正文、目录与协议预览，移除互相冲突的旧条款；此项不撤销前一条历史完成记录。
- [ ] S1 基础层：`infra` async 原语；`BusinessDay` → `CalendarDay`；`runtime/events/`（EventBus、Signal、Observation、EnvironmentEvent、TurnInbox、EventFilter）；`RuntimeHandle` asyncio lease；`PROGRAM→AGENT`；bridge 收敛；`llm` 全面 async；`pytest-asyncio`；重写 `tests/{infra,runtime,llm}`。
- [ ] S2 内核与最小 Agent：`kernel/*`（三分区、四形状含 Map、段协议、inbox/wait、profile、async action runner、Job 协议与 JobRegistry、`jobs` 段、`core.job.*`、`core.context.inspect/organize`、prompts）；`agent/*`（门面、assembly、scheduler、router、generation、day 最小时钟、user profile）；`environment/{terminal,console}`；`gateway/cli`；插件清单只含内核 builtins；删除 `loop/`、`context/`、`action/`、`app/`；新建 `docs/design/architecture.md` 与 `docs/design/kernel/*.md` 描述已落地部分；fake-provider E2E 恢复。
- [ ] S3 插件迁移（每插件一个子计划）：session（Map + 无模型抽取）→ workspace（去防御化动作面）→ home（overlay + `home_reflection` 域）→ memory（轻量 `memory_reflection`）→ reflection（`agent/day` 完整日切、`DayParticipant`、archive、两个 profile、schedule 与 TurnTrigger）→ capabilities（resource、web、`execution` 合并与 `process` Job 种类）。每步删除旧路径与旧 bridge。
- [ ] S4 Agent 与环境完整化：`services`、`status`、`reload_config`、`restart`；`environment/scheduler`、`environment/fswatch` 与 `workspace.resources` 订阅；TurnInbox 暂停接收与预算决策入口；Observation 路由与 console sink；`[agent]` 取代 `[app]`；`core.ask`。
- [ ] S5 Gateway v2：路由（含 jobs、reflection 与外部事件代理）、schema、事件 replay/流、host、auth；`gateway/project`；重写 `docs/endpoint/*` 并附 v1→v2 对照；删除 `endpoint/`。
- [ ] S6 新能力域：`subagent` 插件（ACP 客户端、`acp_agent` 与 `tinysoul_turn` Job 种类、`subagent` profile、权限策略）；`expand` 插件（MCP 网关、索引、四个动作，无钉选段）；各一份子计划。
- [ ] S7 收尾：`docs/design/` 重组（`architecture.md`、`runtime.md`、`llm.md`、`infra.md`、`kernel/{context,loop,action,jobs,prompts}.md`、`plugins/*.md`、`agent.md`、`environment.md`、`gateway.md`）；`AGENTS.md` 重写核心定义（Agent、Environment、EnvironmentEvent、TurnProfile、语境段与形状含 Map、Job、WaitRequest、Plugin、CalendarDay、Reflection）；`tests/` 镜像新布局；静态 import 规则测试；`pyproject` 依赖与 package-data；本文件标记 `done` 并归档。

## 11. 测试策略与验收

测试策略：

- 目录 `tests/<layer>/<module>/test_<切面>.py`；`tests/support/` 提供 fake provider、总线观察器、最小插件与 profile fixture、fake ACP agent 进程、内存 MCP server。
- 契约优先：段协议两阶段提交与重放、四形状回收（含 Map 有限折叠）与追溯路由、`core.context.organize`、收件箱 drain/wait 与控制进 Trap、`EventRouter` 三步路由与动态源注册注销、Job 生命周期（Turn 归属、事件、collect、Turn 结束清理）、profile 的 surface 与段装配、批次并发取消与超时、Trap 转移与失败归类、Agent API 生命周期与世代切换、Endpoint v2 请求/响应/事件流、ACP 会话状态机映射、MCP 索引刷新与 `expand.call` 校验。
- owner 存储与算法测试保留；不固化提示词文案、默认 Home 内容与 catalog 清单。
- E2E：fake-provider CLI（S2 起）；旧日 Turn → 日切 → reflection → 新日 background（S3 后）；wheel 隔离安装与 `init`（S5 后）；fake ACP agent 与内存 MCP server 的能力 E2E（S6）；真实 provider/agent/server smoke 保持 external。

验收：

- `tinysoul start` 在单事件循环内同时运行 Terminal、Endpoint v2、调度器、文件监视与 Job 监督；`start --once`、`status`、`init`、`reset` 可用。
- 三条 import 规则由测试固定；增删插件只改插件清单与该插件包。
- `kernel/context` 中不出现任何 owner 类型；MessageStack 顺序由 Background → Trace → Working 分区与槽内序号决定。
- User Turn 不能调用 `home_reflection.*` / `memory_reflection.*`；持久 Memory 与 actual Home 只在对应 Reflection Turn 更新。
- `session.history` 为 Map：`finish` 无模型抽取；`core.context.organize` 整理上一成功 Turn；压缩仅在本段超水位时有限折叠。
- 追加输入、stop/exit、Job 事件、定时唤醒、定时 reflection、文件变更全部经总线与 `EventRouter`；不存在 `TurnActivityController`、`SignalWatch`、线程版 `SignalBus`。
- 后台脚本、外部 ACP agent、嵌套 Turn 在 `jobs` 段中以同一形态可见，用同一组 `core.job.*` 等待/查询/停止。
- `expand.search → expand.call` 在不暴露全部 MCP 工具 schema 的前提下可调用任一已连接服务器的工具。
- 三层失败语义、Trap 转移、bridge payload 约束的既有测试语义保留并通过。
- `kernel/spi.py` 每个协议方法与注册表方法在仓库内至少有一个真实消费者。
- Full 门禁与 typecheck 通过；`docs/design/`、`docs/endpoint/`、`AGENTS.md` 与代码一致。

## 12. 实施结果

待填写。

## 13. 架构一致性复审与替换预览（2026-09-14）

状态：`pending`。本节是待讨论方案，不代表代码已经具备这些能力。审阅基线：`e6ee6af`。本轮修改仅限本计划；不修改后端、前端、测试或 AGENTS。

### 13.1 判断、证据与范围

总体方向合理可行。应保留 Turn/Cycle/Phase 的语义骨架、构造式 Context、资源 owner、三层失败与显式装配；重构集中解决依赖方向、生命周期和扩展边界。asyncio 是统一 I/O 与等待的执行机制，DDS 只借鉴发布/订阅解耦思想，本次无需引入 DDS 中间件或分布式投递保障。

`docs/chat/00 doing something.md` 不在当前 checkout，且 `docs/chat/` 被 `.gitignore` 忽略；维护者已在本轮上传同名附件，现已全文阅读。P9 按附件核对未来需求与本次范围，不修改附件，也不把整份未来清单自动纳入本次实现。

本次是静态代码与设计审阅，没有运行真实供应商，也没有宣称完整测试通过。第 7 节原有行数、测试数和“风险同前”不能用作当前验收证据；实施子计划需用当时 checkout 的实际结果替换。

| 代码位置 | 观察到的实现 | 重构含义 |
|---|---|---|
| `runtime/bridge/action.py`、`runtime/bridge/context.py` | runtime 内的 bridge import Action/Context 类型 | 原计划保留内核 bridge 于 runtime，仍违反底层不得 import kernel 的规则 |
| `runtime/bridge/llm.py` | LLM 压力失败映射到 Context 原因 | 把常量移到 kernel 后必须同步解除 LLM 对 Context 的隐含依赖 |
| `context/engine.py::consume_signal_batch` | 特判 Workspace、Session 等 payload；惰性加载在状态修改之前完成 | 内容解释应归段；可重放准备与已提交状态必须严格分界 |
| `loop/context_signals.py`、`runtime/frame_runner.py` | 捕获批次后以 Module frame 重放；RuntimeTransferInterrupt 传递已解析转移 | 保留 frame 定向转移，不重跑已发生副作用的 Action |
| `action/core/runner.py::_run_one/_future_result` | 未分类 Exception 被转为局部失败；反馈拼接原始异常文本 | 有可能掩盖 executor 契约/内部错误；需要重新分类与有界反馈 |
| `llm/task.py::run/_run_task` | 外层观察后 re-raise；内部归类后 bridge；取消单独传播 | 宽泛捕获并非一律错误，要按边界与传播行为判断 |
| `runtime/observation.py` | sink 失败被隔离 | 保留；观察失败不得影响业务提交 |
| `app/generation.py::close`、`loop/turn.py` | 逆序关闭资源；清理失败继续；部分已有清理失败观察 | 保留尽力清理，补充可诊断结果，不能误报资源已全部关闭 |
| `loop/assembly.py` | 已有 owner-neutral 的内核装配入口 | 扩展既有门面语义，删除 owner 专用管线，不再加平行 Turn runner |
| `tests/test_architecture.py` | 目前只保护少数依赖边界和源码字符串 | 新依赖规则应在迁移开始时以 import 图检查建立，不能拖到 S7 |

### 13.2 P1：依赖方向、SDK 与 Plugin 边界

替换范围：第 3.8、4、5.1、5.2 节及 AGENTS 未来重写中的 bridge 放置规则。

**建议采用的依赖关系**：gateway → agent → plugins/environment → kernel → llm/runtime → infra。这里箭头表示允许依赖方向，不要求每层必须经过相邻层。允许 `llm → runtime`（通用运行协议）；禁止反向依赖。plugins 与 environment 位于同层，跨插件只 import 对方包根公开的服务契约；运行时对象由组合根注入，不访问私有存储。

- `runtime` 只保留通用 scope、Trap、transfer、事件基础和公开异常构造帮助；不包含 import kernel/llm/plugins 的 bridge。`runtime.failures` 等公开模块承载通用构造器，不要求外围 import `_payload` 私有文件。
- `kernel/context/runtime_bridge.py`、`kernel/action/runtime_bridge.py`、`kernel/loop/runtime_bridge.py`、`kernel/jobs/runtime_bridge.py` 分别解释本模块失败；`llm/runtime_bridge.py` 解释模型模块失败；插件 bridge 随插件。infra 自身不 import runtime，由使用方的启动/模块边界适配其失败。
- LLM 为模型容量问题声明自己的 typed failure/reason；Context 的 Trap handler 按该公开原因登记恢复策略，决定回收和重建。LLM 不 import Context，也不声明 Context 如何压缩。
- `kernel/spi.py` 只汇出具体协议的公开入口，协议定义跟随拥有该语义的模块；不演变为包含所有服务的巨型接口文件。跨模块使用公开门面，不能以 `Any`、字符串服务键或 `getattr` 绕过 import 规则。
- Plugin 是显式安装的装配单元。注册时声明 id、必要依赖与贡献；resolve 检查缺失依赖、循环依赖、重复段/动作/profile/ref scheme/服务。可替换表示满足相同公开契约后替换清单条目，不承诺两个插件同时抢占同一身份。
- `configure/contribute/resolve` 只准备配置、对象及注册关系，不启动监听、任务或改写业务文件；Agent 激活阶段才启动资源。启动失败逆序关闭已经启动的部分。
- `environment` 通过注入的输入/发布端口向 Agent 交付事件；端口协议定义于 runtime/kernel，不能向上 import Agent。文件监视器接收 Workspace 公开提供的监视描述，不自行解释其私有目录。gateway 的 FastAPI/Tauri 协议不进入 Agent SDK。

不是每个 helper 都必须成为类：Engine/Runner/Registry 表达有状态职责与生命周期；解析、格式化和构造可使用纯函数。稳定状态用 StrEnum；内部数据优先 frozen dataclass；JSON 只在外部协议、持久化与段不透明快照边界出现。

### 13.3 P2：事件路由、提交顺序与背压

替换范围：第 3.2 节三步路由、第 5.1 节“持有活动 Turn 收件箱”及第 11 节路由验收。

原路由只把显式 `turn_scope` 的事件交给活动 Turn，导致 `fs.workspace.changed` 与 agent 级 Job 事件无法触达段订阅。建议将定向投递、订阅投递与触发新 Turn 明确区分：

1. owner 先提交自己的事实，再发布事件；文件通知是“可能有变化”的线索，由 Workspace reconcile 后发布资源状态变化。事件本身不替代 owner 状态。
2. 显式指定 `turn_scope`：只投递该已登记 Turn；未知或已结束 Turn 返回/记录过期事实，不转投当前根 Turn。
3. 未指定 Turn 的环境事件：匹配所有运行中 Turn 的段订阅与等待过滤器，按 Turn 去重投递。Agent 维护根 Turn 与子 Turn 的 inbox 索引，不只保留一个 active inbox。
4. `TurnTrigger` 根据自身策略另行产生根 Turn 请求；观察投递与请求入队不是互斥分支。Job 完成只投递所属 Turn，不生成新根请求；独立调度事件仍可排队生成 Reflection 请求。Turn 结束交界处由 Router 串行完成登记/注销与触发判断，避免遗漏或重复通知。
5. 业务提交与路由之后产生 Observation 镜像；replay 仅用于观察，不重放业务副作用。

总线为内存内、有界的进程协议，不承诺断电可靠投递或 exactly-once。Event envelope 带实例内单调序号，用于 drain/wait 竞态和观察关联，不是第二份业务日志。源内有序；跨源以总线接收顺序为准，不按墙钟时间重排。

控制与用户输入不能被高频日志淹没：stop/exit 入口即时置取消令牌，并保证边界可读取控制意图；用户输入以入队结果明确接受或拒绝。文件变化可按资源合并，Job output 正文由 Job owner 缓冲或落盘，事件只传有界增量/线索；终态、问题和权限请求不得按普通进度事件丢弃。观察订阅者使用独立有界缓冲，慢客户端不会阻塞业务发布。

注册回调不能同步嵌套触发 Cycle；事件只进收件箱/请求队列，业务解释在内核边界执行。先用 typed filters 和显式注册完成需求，不引入任意可执行谓词的远程配置。

### 13.4 P3：段协议的最小公共面与提交生命周期

状态：核心职责与生命周期分离已按 D26 确认；本节具体类型、关闭排序、Session Map 恢复细节仍为实现设计提案。

替换范围：第 3.4、5.3 节。四种形状与三分区保留，但形状是访问/回收约定，不强迫使用某种 Python 数据结构。

**公共面预览**（协议草图；确认后以具体类型落地）：

```python
class ContextSegmentProvider(Protocol):
    descriptor: SegmentDescriptor  # id、slot、order、shape、能力、ref scheme
    async def open(self, turn: TurnInfo) -> ContextSegment: ...

class ContextSegment(Protocol):
    def render(self) -> tuple[Message, ...]: ...
    async def prepare(self, updates: tuple[SegmentUpdate, ...]) -> PreparedSegment: ...
    def install(self, prepared: PreparedSegment) -> None: ...
    def seal(self) -> SegmentSnapshot: ...
    async def finish(self, completion: TurnCompletion) -> None: ...
    async def close(self) -> None: ...
```

- `render/seal` 为无 I/O、无状态变更的内存投影；纯渲染不能触发背景加载或写文件。
- `prepare` 接收本段整个有序批次，在候选状态上处理后续更新对先前更新的依赖，完成必要异步读取；返回每条局部结果与候选状态，不变更当前活动段，也不写业务事实。
- 所有段 prepare 完成后，Context 在不含 await 的临界段依序 install。install 仅替换已校验内存状态，禁止 I/O、外部回调和模型调用。install 若因程序不变量失败，结束该 Turn，禁止声称整体回滚或重放已 install 的批次。
- 单条模型 patch 无效仍返回局部结果；由内部事件产生的非法 typed patch 是契约缺陷，不能伪装成模型错误。prepare 中发生压力恢复时，只重放捕获的准备批次，不重新 drain 也不重跑 Action。
- Action/owner 的持久写入在自己的门面完成；成功后段更新是该事实的投影。跨段 install 不提供跨文件分布式事务，不试图撤销已完成的工具副作用。
- `load/evict/inspect/organize/reclaim` 作为明确声明的可选能力，由 descriptor + typed handler 注册。State 段无需写假的 load/evict；非法能力请求给局部反馈，重复 ref scheme 在装配时拒绝。
- `on_event` 只解释事件并生成更新，实际读取放在 prepare；多个段看到同一个事件，inputs/jobs/resources 维护正文和现态，trace 仅记录有序感知摘要。
- `shape` 不自动授予可逐出权限。identity 与 inputs 保留完整语义；Memory 的必要根条目是否可逐出由 owner/profile 声明。State 收缩不能抹去待处理问题、控制意图与未完成 Job。

**收尾顺序**：停止接收新的定向业务更新 → 收敛本 Turn 的 Action 与 TURN Job → 接收并处理已接受的终态事件 → 所有段 seal → 汇总 typed TurnCompletion → 按显式 finish 顺序提交（Session 最后）→ 所有段逆序 close → 释放日/世代 lease → 发布终态。必要的最后控制请求仍由取消通道处理。

finish 是业务提交，close 仅释放资源；close 即使 open 部分失败也必须执行，且不负责 Session 持久写。这样部分 open 失败不会制造不存在的完整 Turn，清理失败也不会触发第二次会话提交。替换原 `history.close` 写记录的说法。

Session 不从任意 JsonObject 猜字段。TurnCompletion 显式携带输入、问题、最终输出、outcome 与 trace 导出的 typed Action 事实；插件快照是按 segment id 标识的不透明内容，内核不解析 Home/Memory 细节。trace 记录所有中途问题，不能只保存最终 answer。

Session Map 必须明确事实性质：不可变 Turn record 是对话事实；自动生成的节点/边是投影；organize 产生的 gist/thread/关系是可修改的语义注释，引用来源 Turn，不能改写原记录。语义注释由 Session 持久保存，不能宣称所有地图内容都可从原记录无损重建。finish 先提交幂等 Turn record，再更新地图；若地图更新失败，下一次由 Session 补齐缺失投影，已有语义注释保留。

### 13.5 P4：等待、提问、取消与预算

替换范围：第 3.3、3.7、5.4 节。

- `core.ask` 与 `core.job.wait` 都先产生正常 ActionResult，然后请求在 Cycle 边界等待。它们不长期占住 Phase3 executor。
- 等待分为 `input` 与 `event` 原因；Turn 活动为 running/awaiting_input/awaiting_event/finalizing，最终 outcome 是另一组枚举。**已确认 D25**：Agent 在根 Turn 等待时继续处理 I/O、状态查询和 Job 事件，但不得启动第二个根 User/Reflection Turn。独立请求排队至当前 Turn 完成收尾，调度器不因 wait 释放根执行位置；此确认不包含本节其它预算、超时与接口提案。
- 登记等待时保存收件箱序号，并先检查目标 Job 现态及尚未消费的匹配事件；wait 使用“检查 → 登记 → 再检查”或等价原子机制。Job 在 Action 完成和 wait 建立之间退出，不会错过唤醒。
- 用户追加输入和 stop/exit 总能打断 Job wait；ask 等待期间后台事件正常更新段，但仅有普通进度事件不自动当成用户回答。问题有 request id，明确回复绑定目标 Turn/问题；未带问题 id 的普通追加输入在边界作为该 Turn 的新指示处理。
- 同批 Action 出现相互冲突的等待/终结意图时，先由 Action concurrency policy 拒绝不合法组合；`ask`、终结性 `answer` 与互斥 wait 不并行执行，避免已经发问又立即终结。
- 等待本身不消耗 Cycle 次数；唤醒执行新的 Cycle 才消耗。计时用 monotonic，区分 active execution budget、等待上限与总 wall-time 上限；模型不得通过 `extend_budget=True` 无限续期。移除模型可直接无限增加预算的含糊入口。
- root stop 取消当前 Turn 及其全部子工作，不保留运行中的 Job。ask 超时以 AWAITING_USER 收束，迟到回复产生新的 Turn，不复活已经释放的旧 Context。
- Turn 的 asyncio 取消令牌与线程内 `ActionExecutionControl` 分开；to_thread worker 不直接操作 asyncio.Event。协作取消先请求，宽限期后才取消 await 并回收进程。取消 to_thread 的 await 不等于停止线程。
- 未收敛 executor 必须真实标记 leaked，并阻止共享 owner 被下一工作继续使用直至回收或重启；不能只结束本批次后让后台线程继续写状态。持久写操作应短小且受 owner 锁保护；任意长时可硬停止工作走 subprocess/Job。

### 13.6 P5：Job 与日切、配置（由 D27 收敛）

旧提案中的 AGENT scope、跨 Turn Job 目录、旧世代结果接管和“无活动 Turn 但 Job 仍运行”的重载流程已撤销。

当前方案：Job 全部在所属 Turn 收尾中回收；根 Turn 保持日与世代 lease，等待期间也不释放。跨午夜的同一 Turn 使用开始日的工作区，完成收尾后才做日切并启动下一根请求。不存在活 Job 继续写已经归档的旧日 Workspace 的正常路径。

reload 只在根 Turn 完成收尾且所有执行资源释放后激活；暂停也属于活动 Turn。若 Job/线程未收敛，不能谎报 idle 或启动新世代，需显式记录收尾失败并保持阻塞。结果持久化归 Workspace/Session，不另建跨 Turn Job 业务库。

父子取消、共享 owner 的写入顺序、递归/并发预算和最终输出前 Job 检查仍需细化；这些不因 D27 自动批准。

### 13.7 P6：异常分类与 SDK 生命周期

替换范围：第 3.8、5.1、5.5、5.9 节；确认后同时修订 AGENTS 中桥接位置和失败规则的相关句子。

| 情况 | 拥有者处理 | 外层行为 |
|---|---|---|
| 模型未输出必需工具、Action 参数无效 | TaskFailure/ActionResult/PhaseFailure | 写有界反馈，下一完整 Cycle 修正 |
| 已知工具业务失败、shell 非零退出、已收敛超时 | capability 返回 typed 局部结果 | 模型决定是否尝试其它路线 |
| executor 类型错误、catalog 不变量破坏、返回非法结果类型 | Action 边界异常 | bridge 结束所属 Turn，不能一律包装 executor_raised |
| owner 文件损坏、无法继续的持久写失败 | owner 边界异常 | 活动 Turn 经 bridge/Trap 收束；SDK 查询直接返回 typed 服务失败 |
| 可恢复 provider 失败 | LLM 内部 retry/provider/model chain | 耗尽后才边界失败；模型输出协议错误不混入供应商重试 |
| 用户选择的 MCP/ACP 连接不可达 | adapter 先归为连接错误；有界恢复后由启动/调用 Action 显式映射结果 | 服务可用性问题可返回局部 unavailable；装配契约/内部错误仍 bridge，不能笼统“协议异常不进入 Runtime” |
| Context 容量不足且当前 frame 可重放 | Context handler 回收后定向 RETRY | 无进展则结束 Turn；不重放已执行外部写入 |
| RuntimeException / RuntimeTransferInterrupt | 不重包装、不转 ActionResult | 原样向合法目标 frame 展开 |
| TaskCancelled / asyncio.CancelledError | 协作取消或收尾 | 保留取消身份；业务 outcome 由 Turn 边界确定 |
| Observation sink 失败 | 隔离、必要时本地诊断 | 不回滚或终止业务 |
| close/cancel callback 失败 | 继续其它清理并汇总诊断 | 不覆盖原始主失败，也不报告完全释放 |

宽泛 `except Exception` 只允许存在于有说明的动态执行边界、观察隔离与最终清理。Action 自定义 executor 不可预知的异常可在隔离边界捕获，但必须归为内部失败并传播，不能让模型以为只是参数不对。`except BaseException` 仅用于必要的任务/线程异常转交，必须原样保留取消和退出，不把它转换为业务失败。

模型反馈采用稳定的简短说明，`error_type`、owner、失败 kind 放入有界诊断；原始异常通过 exception chaining 留在本地。清理现有 `feedback=f"...{exc}"`、通用 bridge `message=str(error)` 和配置 payload 原值直传的入口，按 owner 白名单输出必要字段；不建设泛化的日志清洗框架。

SDK 生命周期采用一组无歧义动词：

- `Agent.create(...)` 只装配；`start()` 启动服务；`shutdown()` 结束实例的运行；`restart()` 完整 shutdown 后重建并启动；活动 Turn 用 `cancel_turn(turn_id)`，避免 `stop()` 同时表示停 Turn 与停 Agent。
- `submit_turn` 返回 TurnHandle（id、status、await result）；`append_input`、`reply`、`cancel_turn` 都显式指定目标。调用不合法是 SDK typed rejection，不伪造一个 Runtime frame。
- `patch_config(patch)` 校验并写候选配置文件；`reload_config()` 无 patch 参数，构建候选世代、完整校验、成功才切换；失败保留当前活动世代，磁盘仍是待修正/待激活配置。status 分别报告活动世代和待激活配置状态。
- `status()` 为内存快照；I/O 查询由明确 async 服务门面提供。配置、实例锁、项目根解析由 Agent/owner 管理，gateway 不直接写配置文件再调用 SDK。
- `/v2/turns/{id}/control` 映射 Turn 取消；后端 shutdown 属显式 Agent 生命周期接口，不把断开前端连接当成 shutdown。现有 stop/exit 命令可在 CLI 映射，但内核不保留两套生命周期 API。

### 13.8 P7：外部能力的验证边界

替换范围：第 5.7、5.8、7 节有关 SDK 精确接口与可行性判断。

ACP/MCP 接入方向保留，但协议主版本、Python SDK 版本、外部 agent adapter 版本是三个不同对象。不能仅凭协议文档把具体 adapter 的 prompt 结束、取消、close、权限请求语义视作已验证。

本轮查询了 [ACP 官方入口](https://agentclientprotocol.com/) 和 [MCP Python SDK 官方入口](https://py.sdk.modelcontextprotocol.io/)；返回资料涉及版本迁移，尚未完成目标 adapter 与具体包版本验证。因此原文 ACP v2 的消息顺序、MCP `Client/listen` 调用与依赖“轻量”的断言均视为待 S6 核验的候选，不作为实现验收事实。

S6 子计划先记录实际包/版本、协议版本与目标 adapter，运行最小连通与取消验证，再落实能力实现。验证 prompt 从开始到最终结果、流通知、取消、进程异常退出、权限请求；MCP 验证 tools 分页、列表变更、能力声明、超时、structured content 与错误结果。不要求引入 v1/v2 兼容层，只支持选定目标。

TinySoul 的 Action schema 子集只校验 `expand.call` 外壳。外部工具 schema 使用明确选定的 JSON Schema validator/SDK 支持；不支持的 schema 返回“本地无法验证”或依据明确策略交服务器验证，不能声称忽略未知约束后已完整校验。远端写工具超时可能已经产生副作用，不自动重试无法证明可重放的调用。

### 13.9 P8：执行顺序、文档清理与验收补充

替换范围：第 10、11 节。继续分阶段交付，但每阶段必须有可验证的完整路径；不因 S7 才收尾而允许 S1–S6 长期保留错误依赖。

| 阶段 | 补充的实施范围与必要证据 |
|---|---|
| S0 复审 | 讨论并关闭影响基础架构的 P1–P6，回写已确认条款；P7/P8 按所属阶段细化，P9 仅保留参考，不要求预先批准全部未来功能 |
| S1 基础 | bridge 随 owner 的目标布局、typed 失败、async I/O、总线/取消基础；建立 import 方向检查；验证信号顺序、等待竞态、观察隔离与取消身份 |
| S2 内核与 Agent | 最小 SDK + fake provider 从 submit 到 outcome；段 prepare/install/finish/close；假 Job 验证取消与收尾；替换 CLI/打包入口同步进行，不能删除 app 后仍引用 `tinysoul.app.cli` |
| S3 owner 插件 | 每次迁移一个 owner；显式依赖次序；Session 事实与语义注释、Workspace 写入、Home overlay、Memory 单文档写、日切均有代表性路径；日切恢复 journal 与删除 Memory 多文档 journal 区分 |
| S4 环境与生命周期 | ask/reply、全局文件事件投递、进度背压、Job 完成交界、shutdown/restart/reload busy；跨日 Job 执行目录与导入结果验证 |
| S5 gateway | 全部经 SDK 与服务；HTTP/WS 鉴权、replay、重连和终态；协议文档同步；wheel/init 验收。前端仅形成对接说明，后端任务不擅自改 visualization 实现 |
| S6 新能力 | 先锁定协议与 adapter 后验证 ACP/MCP；内部子 Turn 使用相同内核、父子取消与预算；process/ACP 与 Job 通用控制一致 |
| S7 清理 | 全仓依赖与 public facade 审查，移除兼容 alias、私有跨模块调用、废弃入口、重复状态和无消费者接口；AGENTS/设计/端点/测试/打包全部一致 |

迁移应在开发 checkout/分支进行，当前可用部署继续使用原 checkout；用户数据不自动 reset。不向后兼容意味着旧 schema 明确拒绝或需要用户另建项目，不意味着代码重构可以删除用户数据。S1/S2 删除旧模块时同时删除或迁移依赖它的旧入口/测试，不加入临时 alias 支撑旧测试。

新增的关键验收场景：

1. 全局 Workspace 变化同时触达根/子 Turn，定向输入不串到另一个 Turn；旧 Turn 迟到事件不激活无关工作。
2. Job 已结束再调用 wait、注册 wait 的瞬间结束、超时与完成同时到达：不丢唤醒、不重复启动根 Turn。
3. 第一段 prepare 成功、第二段 prepare 失败：当前活动状态未部分修改；重复消费不重新执行外部 Action。install 失败不进行不安全重试。
4. open 部分失败、finish 写入失败、close 失败：已开资源都清理，原失败保留，Session 不重复记录；地图可补齐派生节点且不丢语义注释。
5. ask 后追加输入恢复同 Turn；ask 超时后回复进入新 Turn；stop 打断两种等待；多次 wait 不无限扩大执行预算。
6. runtime 不 import llm/kernel/plugins；LLM 压力经注册 handler 引起 Context 恢复，没有逆向 import 或重复桥接。
7. Job 持有资源时 reload 明确 busy；午夜归档不被活进程继续改写；collect 幂等且链接不会错误指向新日同名文件。
8. 编程错误不变成可修正工具失败；普通非零退出保持局部结果；未知异常消息不直接进入模型反馈；Observation 失败不改变结果。
9. 父子 Turn 共享 owner 时各有独立状态；根取消传播正确，子 Turn 失败以 Job 结果反馈父 Turn，不直接结束父 frame。
10. 根 Turn 处于 awaiting_input 或 awaiting_event 时，提交独立用户任务和 Reflection 请求：它们仅排队；当前回复、Job 事件与取消仍可处理；只有当前根 Turn 完成收尾后才启动下一个根请求。

测试以行为与契约为主，不固定提示词全文、默认 catalog 列表、文件精确数量或纯实现私有方法。每个阶段开始时明确当阶段有效的本地 Full/类型检查范围与已删除旧契约；不能通过全局 skip 掩盖新架构损坏。最终恢复完整 Full、typecheck、wheel 与端点验收。纯设计文档修改只验证 diff、引用、决策状态与方案一致性，不声称跑过代码门禁。

待讨论的核心取舍：P1 bridge 下沉到各 owner；P3 将业务 finish 与资源 close 分开；P5 跨日 Job 使用独立执行目录、内部子 Turn 限 TURN scope、存在未释放 Job 时 reload 返回 busy；P6 SDK 动词与显式候选配置激活。其余条目是这些选择对应的实现与验收约束，仍需随确认整体回写。

### 13.10 P9：未来清单的覆盖、边界与冲突处理

来源：维护者本轮上传的 `00 doing something.md`（全文）。维护者已明确该文件有些陈旧、仅供参考。本节所有“建议落实”均是供讨论的候选，不是本次范围承诺，不覆盖当前讨论，不作为开始核心重构的前置门禁；没有单独确认的条目不得转成实施任务。

| 未来需求 | 本次重构建议落实 | 后续独立工作 |
|---|---|---|
| Agent/SDK、事件、三阶段、段依赖反转 | P1–P6；统一调用与生命周期 | 根据真实轨迹继续优化模型决策 |
| Session Map、追问/补充/推理/links | typed completion 保存问答与 Action 事实；Map 注释可整理；有限折叠 | 前端地图布局与交互 |
| Home/Memory Reflection | 保留两个专属域；User 不直接写长期基线；Home overlay review；Memory 轻量单文档写；支持今天与过去日 | 调整主动积累与 review 提示词的效果 |
| Reflection Action 的配置与模型链 | 与普通 Action 使用同一配置解析、任务 profile 和模型路由机制；只按 TurnProfile 改可见 surface，不再硬编码 home_search/memory_daily 调用链 | 设置页的任务分类交互 |
| milestones 如寄存器 | plan 保存有状态的事实、值、来源和失败尝试，不等同 todo 完成 | 对行为提示词进行轨迹评估 |
| 输入图片、文件夹及 PDF/PPT/Word/Excel/二进制 | 输入协议用 typed 文本/资源引用，不能固定为 text-only；持久 owner 与局部读取边界明确；模型能力适配见下文 | 各格式抽取、渲染与编辑能力；拖拽上传 UI |
| Workspace 宽松写入、references | 去 CAS；资源链接校验与文件操作归 owner；区分成果引用与证据链接 | 更丰富的项目类型与操作体验 |
| pinned/tmp/to-library 标记 | manifest 保留有类型的标记扩展入口；本次不默认基于 tmp 自动删除 | 标记 UI、清理策略和长期收藏工作流 |
| Library 独立于 Home | 明确未来 Library 是长期文件 owner，非 Home prompt、非 Memory 知识文档、非当日 Workspace；通过 Workspace 导入/导出服务集成 | 独立 `plugins/library`、索引、收藏、检索与 `library:` 身份；本次不造空实现 |
| ask 选项 + 自由输入 | TurnOutput question 支持 question_id、可选 choices；reply 保留选项身份与自由文本；trace/completion 保存 ask→reply→reason→answer | 前端选择控件与丰富交互 |
| core idle | 在统一 WaitRequest 上表达有界定时/事件等待；无完成语义的循环不得零延时空转 | 是否单独暴露 `core.idle` 动作及命名，按轨迹需要决定 |
| coding 组合能力 | execution/workspace/subagent 与 Skill 挂载，不新建第二套 coding loop | 元能力、项目权限模型与专项 coding Skills |
| prompts 管理与行为风格 | kernel 集中框架提示构造；插件拥有自己的领域提示，公共构造器复用 | 意图标签、创造性、主动提问等文案优化；不作为代码协议硬编码 |
| MCP、图像生成、数学、搜索、邮件、字体图标 | 统一 expand 或显式能力插件入口与结果引用 | 分项选服务和真实任务验证，不在重构中一次性接完 |
| Markdown 代码块插件、字体、本地配置、侧栏/桌面机器人 | gateway 提供 typed 输出与资源服务；后端不依赖前端渲染插件 | 独立前端实现计划 |
| 备份 zip、reset 保留备份、部署更新 | SDK 生命周期和项目 owner 边界不阻碍扩展；不把重构等同 reset | 备份导出、版本更新与部署回滚计划；执行更新须有具体授权 |
| 远程笔记本直连主机 | gateway 主机/端口显式配置、鉴权、重连与只读状态；SDK 不依赖 loopback | 选定私人网络接入方式后验证，默认不自行开放公网 |

**需要在本次协议中明确的补充**：

1. **两级 Observation 与模型轨迹分开建模。** 建议按附件简化 level 为 `normal | verbose`；原 `model` 表示内容类别，改为 `category=model` 的 verbose 事件，可选订阅模型输入/输出内容，避免为 level 增加第三档。完整模型消息是观察投影，不进入 Session 事实。此项需同步 runtime、CLI、Endpoint 与前端协议；不保留 level=model 兼容别名。
2. **资源链接按字段语义校验。** 附件要求 Workspace references（包括回答的成果 references）只含 `workspace:`；Session Map 的相关 links 又需要外部 URL/Home/Memory。建议区分 `artifact_references: WorkspaceLink[]` 与 `evidence_links: ResourceLink[]`，由所属字段验证；原 `references` 含混字段清理。回答文本可含网页链接，不能把网页 URL 塞进 Workspace 成果列表。未来 Library 的引用经专门引用字段或显式导入 Workspace，不偷换已有字段含义。
3. **图片按当前模型能力构造消息。** 输入文件先由 Workspace 物化，inputs 保存文字与资源身份；当前 task 模型支持图片时可发送有界图像内容，不支持时使用链接/已有文本抽取，不回放 base64，也不伪装模型看过图片。若必须识图，通过显式图像理解能力调用可用模型；无可用能力返回明确局部失败。模型切换后重新构造匹配能力的 MessageStack，此适配由 kernel 的模型调用协调入口结合 owner 提供的内容完成，LLM provider 不读取文件。
4. **跨日历史的资源身份。** 不把当日 `workspace:path` 裸字符串用作永久资源唯一身份；Session/Job 的来源记录绑定 day 与 owner 身份，归档解析由 owner 完成。后续 Library 收藏生成自己的长期 Link，不能靠保留旧 Workspace 路径模拟持久收藏。
5. **技能信息的作用域。** Home 的 Skill 元信息/可发现线索可以进入 Background；DOMAIN/action Skill 在所属 TaskPrompt 挂载；reference 正文在实际使用时局部读取。S3 用一条 top→reference→局部任务路径验证，不以重复粘贴所有 Skill 内容实现“可用”。

**附件中的旧条目冲突，建议处理如下**：

- “主体 Home 通过 git 维护”与前文“可以不引入 git”、D23 冲突：沿用已确认的 overlay + review，不把 Git 作为运行时依赖。
- “不要并行调用相同的行为”“多个脚本只能有一个后台跨 cycle”与多 Job 监督目标不一致：建议用明确的 concurrency key、owner 写锁和可配置 Job 上限控制冲突；不按 action 名一律禁止并行，不保留单后台槽位。相互独立的任务允许并发。
- “memory 段专门放 Session 中的 memory links”可能复制 Session Map：Map 保存出现事实；Memory 只从 Session 公开投影获得有界召回线索，不新建第二份会话记录或强制加载全部 memory 正文。
- “所有内部提示词集中管理”与插件可替换性存在张力：集中公共 PromptBlock 机制与框架提示，插件提示随 owner；便于查找不等于把所有领域文案移进 kernel。

上述 P9 条目为参考议题。两级 Observation、typed 多模态输入/输出、引用字段以及并发策略均涉及接口变化，若后续讨论决定纳入，才形成独立决策并回写，不要求本轮逐项确认。

### 13.11 下一轮讨论顺序

优先讨论以下真正改变核心契约的选择，每次确认一组，再修改对应正文；P1–P8 当前仍是提案，尤其 P5 的范围限制不是已经确定的产品要求。

1. **内核与插件的职责**：内核拥有 Turn/Cycle/Phase、Context 组装与容量协调、Action 调度、等待和 Job 监督协议；插件拥有身份/记忆/历史/资源等领域内容和维护。内核可以拥有通用 plan/trace/input 状态，但不能硬编码 Home/Memory/Session 的内容格式。identity 的内容由 Home/配置提供，内核只保证 system 消息约束。
2. **段与 owner 的两种生命周期**：段是每 Turn 的语境参与者，owner 跨 Turn 存在。不要求每个插件一定有段，也不要求 owner 所有行为都通过段接口；段负责模型视图与本 Turn 参与，领域 Action 通过 owner 门面做实际工作。prepare/install 只保证内存投影的批次边界，不把 owner 持久化升级为通用事务平台。业务 finish 与资源 close 分开。
3. **并发与等待（部分已确认）**：D25 已确定顶层只跑一个根 Turn，等待期间不启动另一项独立 User/Reflection；环境事件、Job 监督和取消继续运行。无需重复讨论多根 Turn 并发；子 Turn 的执行与生命周期仍属 P5 待讨论项。
4. **长期 Job 与重载**：P5 的“内部子 Turn 只允许 TURN、未释放 Job 阻止 reload”是降低生命周期复杂度的候选，若妨碍长期助手目标，应改为明确的 Job 服务生命周期与世代租约方案，而非把限制当成最终语义。先确认需要保留哪些运行中工作，再定目录和 API。

优先维护语义与所有权，具体方法名、文件数量、默认等待分钟数和外部 SDK 版本放在相关契约清楚后决定。允许推翻本节提案；不以既有文字已写入计划作为继续保留某项设计的理由。

### 13.12 配置生命周期复审结论

现有 runtime/generation/handle.py 是单活动世代与 idle 激活，app/generation.py 关闭整组 Engine/服务。D27 的 Turn-owned Job 使此结构可以保留：无需引入跨 Turn Job 或多世代退休机制。13.12 旧提案已被本节取代。候选配置可保存，活动 Turn（含等待/预算暂停/收尾）不能 reload；完整收尾后再激活。此处仍不授权执行代码重构。

### 13.13 暂停、收件箱与恢复的完整契约（细节待确认）

基础方向已按 D27–D29 回写；本节是具体实现提案，不能把方法名、容量策略和 SUSPEND 当成已确认实现。

**A. 一个收件箱，两种处理职责**

EventRouter 持续把定向输入和匹配订阅的环境事件投递 TurnInbox。暂停的是模型推进，不是总线、Router 或控制接收。Turn runner 的单一协调循环是 inbox 消费者；不要另起一个会并发修改 Segment 的暂停消费者。

控制入口优先处理 cancel/exit 与预算决定；环境事件保持有序待处理。可以在一个 TurnInbox 中提供独立控制队列与事件队列，不为此建立第二套总线。预算授权只由 typed 用户入口提交，不能由环境 payload 或模型工具伪造。普通输入不自动当成预算继续指令。

**B. 捕获批次与确认**

原 drain() 清空语义改为 take_batch()/ack(batch_id) 的显式契约：只有一个在途事件批次，取出后仍受 inbox 持有；新的到达进入后续批次。prepare 失败保留在途批次，install 成功后同步 ack；不能让 await/取消插入 install 与 ack 之间。install 发生内部错误时终止 Turn，不重放部分安装批次。

这保证进程内恢复边界，不承诺崩溃后 exactly-once。消息序号由总线/收件箱统一提供；事件发生时间用于展示，不用它排序并发源。控制消息的优先处理不改变环境事实的相对次序。

**C. 接收、等待就绪与预算是三个条件**

EVENT 等待声明过滤器；TIMER 等待保存 monotonic deadline；INPUT 等待绑定问题。已有在途/待处理事件和 Job 现态先参与匹配，再登记等待，登记后复查，防止事件在等待建立间隙丢失。等待只检查事件，不为了匹配而把事件从队列移除。

建议 TIMER 遇 Job 完成/失败可提前返回，EVENT 可有可配置超时；用户追加输入可打断普通任务等待，取消始终有效。高频 stdout 不默认唤醒模型；事件类别和等待过滤器决定是否需要推理。

普通等待就绪后，再检查 Cycle 预算；预算足够才消费下一模型 Cycle。预算不足时保留已就绪原因、剩余待处理事件和所有段，进入 BUDGET 暂停；Job 完成不能绕过预算。若普通等待尚未就绪，不因为额度为零就提前要求用户续费式确认。

**D. 预算异常与暂停转移**

当前 runtime/transfer.py 只有 RETRY/END，loop/turn.py 预算不足直接 exhausted + break；不能直接沿用。建议增加 SUSPEND，但只允许目标为当前 Turn 的 Cycle 准入边界，原因是 typed BudgetDecisionRequest；不得作为任意 Module continuation。Trap 只返回控制决定，不阻塞、不写 UI、不做网络交互。Turn runner 保存局部执行状态并 await 控制；不是退出 runner 再重建 Turn。

用户通过 request_id + turn_id 提交 stop 或 grant(additional_cycles)。同一请求重复提交幂等，旧请求不重复加额度；仅校验正整数及明确配置约束。补充后重检尚未开始的 Cycle，启动时扣减一次；Phase 内恢复不重复扣 Cycle，模型可修正 PhaseFailure 开始新 Cycle 才扣。预算数和授权原因只在运行时状态/观察中可见，不放入模型 TaskPrompt。

待用户决定期间保留 Turn 日/世代 lease，Job 继续运行、事件持续接收；断开前端不等于中断，重连可读取待决请求。是否设置用户决定超时暂不强加；若以后配置超时，必须明确终止语义。

**E. 缓冲策略与保证边界**

不丢语义事件不等于无限保存全部 stdout。完成、失败、问题、预算决定和用户输入按条保留；进度按 Job 合并，文件变化仅合并可表达为“这些路径需要刷新”的通知，保留序号范围/变更次数；插件自定义事件默认不可合并，必须声明合并语义。

正文由资源/Job owner 存储，事件传引用。建议 TurnInbox 使用有界内存，超过阈值的不可合并事件转存 Turn 临时 spool，由 inbox 独占管理并在收尾后删除；它是传输缓存，不是 Session 或业务恢复日志。spool 写失败不得静默丢事件：标记接收失败，控制通道仍可取消，Turn 进入失败收尾。磁盘耗尽情况下不承诺继续无损运行。spool 只在内存阈值触发，不为每个事件做同步落盘。

**F. 收尾与新事件的分界**

进入 finalizing 时停止启动新 Action/Job；停止接收新的普通任务追加，入口明确返回 Turn 正在收尾。对通用环境源撤销该 Turn 的订阅并保存接收截止序号；源本身继续运行，下一 Turn 由 owner 最新状态重新准备背景。Job 终态路由继续保留，直到本 Turn 全部 Job 已收敛、适配器确认最终事件已入箱。

随后处理截止前事件及最终 Job 事件，seal → finish → close，最后注销 inbox。不能为了等待全局文件事件流“变空”而无限推迟收尾。无法回收的执行资源阻止 idle/reload，已发生失败与残留 Job 状态必须可观察。

**G. 必要测试与阶段安排**

- S1 建立收件箱捕获/ack、控制优先、等待注册竞态与候选 SUSPEND 的 frame 校验测试。
- S2 在 fake provider 下走通预算不足→事件到达→用户追加额度→更新段→下一 Cycle，确认未重放 Action、未向模型泄露额度。不能等 S4 才验证基本暂停语义。
- S3 验证暂停跨午夜仍保持旧日，收尾后才归档；Session 保存业务问答/行动，不复制 transport spool。
- S4 加入端点预算请求/决定、断线重连、事件容量与终态收尾的集成验证；不等新 ACP/MCP 才验证收件箱。
- 关键竞态：事件早于 wait、到达于 prepare 中、重复 budget grant、cancel 与 grant 同时到达（cancel 优先）、持续 fswatch 不阻塞 finalizing、Job 最终事件在停止过程中到达、spool 失败不静默漏事件。

待讨论的两个核心实现取舍：SUSPEND 是否作为受限的 Turn 边界转移；不可合并事件超出内存阈值是否允许 inbox 临时落盘。其余机制以 D27–D29 为基础细化，不重新引入跨 Turn Job 或模型预算工具。
