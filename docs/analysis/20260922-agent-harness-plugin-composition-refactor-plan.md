# Agent Harness 与 Plugin 组装重构方案

状态：`pending`（命名与所有权边界已确认，代码尚未实施）

提出日期：2026-09-22

修订日期：2026-09-22（采用 PluginGeneration / PluginProfileExtension）

关联审查：`docs/analysis/20260922-agent-refactor-completion-review-e2625da.md`

关联主计划：`docs/analysis/done/20260915-done-agent-architecture-refactor-plan.md`

## 1. 目标与范围

本方案收口 Agent SDK 的组装语义。TinySoul 的主要宿主是我们自己的 Agent 与上层应用，因此 SDK 的核心目标是让 Agent 能力以清晰、显式、可替换的 Plugin 组合形成，同时保持唯一根调度、唯一 Turn 内核、统一 Context、Job 和 owner 语义。

本方案解决以下问题：

1. 区分 Agent 的组装定义、运行 generation、执行 profile 和实际 Turn；
2. 统一 `builder`、`assembly`、`declaration`、`profile` 的职责和命名；
3. 使内置能力和后续自定义能力使用同一套 Plugin 组装路径；
4. 让 generation 级资源与 profile/Turn 级视图拥有正确生命周期；
5. 保持 Kernel owner-neutral，不新增第二套 Loop、Context、Session 或 Job 机制；
6. 为后续 coding、知识来源、环境感知和多 Agent 能力提供稳定接入面。

本方案不建设动态插件发现、安装或升级平台，也不把所有配置项机械地包装成 Plugin。LLM、时钟、观察输出、输入源等宿主基础依赖仍可以通过明确的 Host 配置注入；具有领域事实、Action、Context 段、事件来源或受约束服务的能力才作为 Plugin 参与 Agent 组成。

## 2. 当前问题判断

当前实现已经具备正确的基础协议，但几个名称同时承载了不同层次：

| 当前概念 | 实际承担的职责 | 产生的歧义 |
|---|---|---|
| `AgentBuilder` | 读取配置、创建 Engine、创建 generation、装配三种 profile 和资源 | 名称像静态构建器，实际包含运行资源创建和内置能力选择 |
| `Agent.assemble` | 接收一个 `AgentAssembly` 工厂，创建 SDK Agent | `assemble` 与 `AgentAssembly`、Builder 的关系不清楚，且当前参数实际是运行时工厂 |
| `AgentAssembly` | 进程级根调度、命令、来源、配置和 generation handle | 当前名称实际指运行容器，不是 Agent 的静态组装定义 |
| `PluginDeclaration` | 某个 profile 的服务、段、Action、事件、完成处理和运行来源 | 同一个对象同时带有 profile 贡献和 generation 来源，Plugin 与 Declaration 边界不清楚 |
| `ResolvedPlugins` | 一个 profile 的已校验贡献集合 | 名称像已解析的 Agent 插件集合，实际只服务一个 TurnProfile |
| `TurnProfile` | 当前情景的 Context、Action surface、服务、完成策略和 Trap | 与“Profile 选择能力”及实际 runtime profile 的关系没有单独命名说明 |

其中最需要修正的是 `PluginDeclaration.sources`：来源由三个 profile 汇总后再由 `GenerationSources` 去重，运行上可用，但语义上使 generation 级来源看起来像 profile 贡献。generation 资源、来源和 profile 视图应在协议上分开。

### 2.1 对 review 和当前实现的可行性判断

review 的 F1 判断是准确的：当前 Kernel 和 profile PluginDeclaration 已足以承载扩展，但标准 Agent 的组合根仍然把内置能力写死在 `AgentBuilder` 和 `CommonActionAssembly` 中。自宿主场景不需要把完整内部 Builder 原样暴露给第三方，而应把 Builder 重塑为 TinySoul 自己的 Harness 入口。

本方案与当前实现是渐进可迁移的：

- `AgentBuilder._build_generation` 已经集中承担 generation 创建，可以拆为 `AgentAssembly` 保存组装定义、内部 generation builder 创建 `AgentGeneration`；
- `CommonActionAssembly.prepare` 已经按 profile 接收 PluginDeclaration，可以改为消费各 `PluginGeneration` 提供的 `PluginProfileExtension`；
- User、Home Reflection 和 Memory Reflection 已经共用 Workspace、Subagent 和 Scheduler 等 owner 实例，现有 `GenerationSources` 去重证明资源共享关系存在，只需把来源身份从 profile 声明上移到 `PluginGeneration`；
- `PluginRegistry` 的服务、依赖和段校验可以继续复用，不需要新建第二套动态注册系统；
- review 的 F2 ACP 类型修复与本次命名重构相互独立，适合作为前置门禁。

主要迁移风险是当前 `AgentAssembly` 类型被多个 Gateway、测试和 SDK 入口直接引用，以及 `AgentBuilder.build()` 当前是异步并创建真实资源。计划通过一次明确的类型迁移解决，不保留同名静态组装对象和运行容器两套含义。

### 2.2 命名方案评估

已确认 Agent 的构建与使用链路如下：

```text
AgentBuilder.build() → AgentAssembly → Agent.assemble(assembly) → Agent
Agent 内部管理 AgentRuntime 与当前 AgentGeneration
AgentGeneration 内的 TurnProfile → Turn
```

`AgentAssembly` 是静态组装产物，`Agent.assemble` 是从组装定义跨入运行对象的生命周期边界，返回宿主使用的 `Agent`。宿主无需手工创建 `AgentGeneration` 或 `TurnProfile`；上述对象关系不表示一串连续的公开 API 调用。

当前代码中同名的进程级 `AgentAssembly` 必须改为内部 `AgentRuntime`。它保存 RootScheduler、AgentCommands、generation handle、InputDispatcher、Endpoint gateway 和进程资源；这些对象属于 Agent 的运行壳，不属于静态组装定义。`AgentGeneration` 管理一代插件运行实例、Profile、Source 和共享执行设施，不吸收进程级根队列；Job 仍只属于唯一 Turn。

插件层次固定为 `AgentPlugin → PluginGeneration → PluginProfileExtension`。其中 `PluginGeneration` 是插件在某个 AgentGeneration 中的运行实例，`PluginProfileExtension` 是该实例针对某个执行情景提供的局部扩展。多个插件针对同一情景的扩展与情景策略共同解析为一个 `TurnProfile`。新接口统一使用这两个名称，不保留讨论阶段候选名称的兼容别名。

`Agent.create(root, ...)` 不再是第二种组装模型。若有真实的默认入口消费者，可以保留为薄函数，但它必须内部执行 `AgentBuilder(root).build()` 和 `Agent.assemble(assembly)`；稳定文档、Gateway 和自定义宿主使用完整链路。若实施中确认没有真实消费者，应直接移除 `create`，避免保留重复入口。

## 3. 稳定术语与所有权

以后采用以下术语。新代码和设计文档使用这些含义，不再把同一个词用于多个层次。

### 3.1 AgentAssembly

`AgentAssembly` 是一个 Agent 的不可变组装定义，描述：

- 项目根和宿主基础依赖；
- 配置来源及已解析的宿主选项；
- 参与 Agent 的 `AgentPlugin` 工厂集合；
- 默认 profile 集合和 profile 策略；
- 输入源、观察 sink 等进程级宿主适配。

它描述 Agent 由哪些能力构成，不拥有已经启动的来源、LLM 客户端、Workspace watcher 或可变领域 Engine。添加、删除或替换 Plugin 是组装定义变化，需要重新创建或重新装配 Agent；普通配置 reload 只在组装仍然有效时重建 generation。

### 3.2 AgentBuilder

`AgentBuilder` 是宿主用于编写 `AgentAssembly` 的公开组装门面。它负责收集显式配置和 Plugin，检查组装级身份与依赖，然后产生 `AgentAssembly`。

`AgentBuilder` 不启动来源、不创建活动 Turn、不拥有根调度器，也不执行模型调用。它可以读取和校验配置来源，但不创建 generation Engine 或运行资源。它可以提供少量稳定的宿主注入方法，例如项目根、配置环境、模型 provider、时钟、观察 sink 和输入源；领域能力通过 `use(plugin)` 进入，不为每个内部 Engine 暴露一个平行的 `with_*` 注入入口。

建议的公开形态为：

```python
assembly = (
    AgentBuilder(project_root)
    .use(HomePlugin(...))
    .use(MemoryPlugin(...))
    .use(SessionPlugin(...))
    .use(WorkspacePlugin(...))
    .use(ExecutionPlugin(...))
    .use(SubagentPlugin(...))
    .use(MyKnowledgePlugin(...))
    .with_input_source(source)
    .build()
)
agent = await Agent.assemble(assembly)
```

`AgentBuilder.build()` 同步产生组装定义，不创建可接受请求的运行对象。`Agent.assemble(assembly)` 异步创建 SDK Agent 和初始 Generation，运行来源与根 work 在 `start` 后激活。若保留 `Agent.create(root, ...)`，它只能是项目根默认 Plugin 集合的薄便捷函数，不能再拥有另一套组装协议；默认 Gateway 和文档使用 `AgentBuilder` 加 `Agent.assemble` 的完整路径。

### 3.3 Agent

`Agent` 是宿主使用的运行 SDK 门面。`Agent.assemble(AgentAssembly)` 创建它；它拥有唯一根队列、运行世代句柄、事件路由、日协调和生命周期操作：`start`、`submit_turn`、`append_input`、`reply`、`publish`、`restart`、`reload`、`shutdown` 等。

Agent 的行为由其 `AgentAssembly` 决定，但 Agent 本身不暴露可变 Plugin 注册表。运行后添加 Plugin 会破坏 generation 身份、资源边界和服务 lease，因此必须通过新的组装定义重新创建 Agent。

#### AgentRuntime：内部运行容器

`AgentRuntime` 是 `Agent` 内部的运行壳，保存唯一根调度器、请求与事件入口、生命周期协作对象、当前 Generation 句柄和进程级资源。它承接当前进程级 `AgentAssembly` 的职责，不引入另一个调度 owner 或状态机。SDK 对外以 `Agent` 为运行门面，不要求宿主创建或获取 `AgentRuntime`。

`AgentRuntime` 可以跨 restart/reload 保持存在，并协调旧 `AgentGeneration` 的收尾与新世代的激活。它不保存 Home、Memory、Session、Workspace 的领域事实，不承担 Turn 的 Context 或 Job 所有权。这里的类型属于 `agent` 层，不改变底层 `tinysoul/runtime` 只负责 Trap、Signal、运行位置和 Observation 的职责。

### 3.4 AgentGeneration

`AgentGeneration` 是一次组装定义和有效配置的运行实例。它持有该世代的：

- LLM、embedding 等共享宿主服务与执行设施；
- 每个已组装插件的 `PluginGeneration`，由其封装领域 Engine、连接和外部协议资源；
- 从插件实例汇集、由 Agent 生命周期统一协调的 RuntimeSource、day participant 和关闭资源；
- 由插件扩展与情景策略解析的 `TurnProfile`，包含 Action、Context provider 和服务绑定。

初始 Generation 在 `Agent.assemble` 中准备，在 `start` 时激活；restart 或成功 reload 按相同组装定义创建并切换到新的 Generation。旧世代失效后，其 generation/day 绑定服务必须拒绝继续使用。Generation 统一管理插件实例的生命周期，具体资源的创建与释放仍封装在各插件实例内；它不持有某个 Turn 的可变 Context 段视图。

### 3.5 AgentPlugin

`AgentPlugin` 是 Agent 的组成定义与插件组装门面，保存插件身份、依赖和配置，并负责为每个 `AgentGeneration` 创建一个 `PluginGeneration`。运行 Engine、连接、来源和关闭逻辑封装在后者中，不能存入静态 Plugin 定义后跨世代复用。

Plugin 由宿主显式加入 `AgentBuilder`，不通过 import 扫描或运行时动态发现。Plugin 身份、组成依赖和重复 owner 在组成或 generation 准备阶段确定性校验。

### 3.6 PluginGeneration

`PluginGeneration` 表示一个 Plugin 在某个 `AgentGeneration` 中的运行实例。它拥有并封装：

- Engine 或受约束服务实现；
- RuntimeSource；
- 日切参与者；
- 插件运行资源的关闭逻辑；
- 供 profile 构建使用的窄依赖 facade，以及产生 `PluginProfileExtension` 的方法。

同一个插件在同一个 AgentGeneration 中只创建一个运行实例，不能因为 User、Home Reflection 和 Memory Reflection 各自建 profile 而重复创建 Engine、连接或来源。来源的身份冲突、启动顺序与关闭仍由 Agent 生命周期统一协调。

它属于唯一 `AgentGeneration`，随该世代创建和关闭，不维护独立的世代编号、重启机制或调度器。持久事实继续由领域 owner 的存储协议维护，插件实例关闭不代表删除持久事实。

### 3.7 PluginProfileExtension

`PluginProfileExtension` 是某个 `PluginGeneration` 针对一个执行情景提供的局部扩展声明。它包含：

- profile 可用的服务 facade；
- 当前 Turn 的 Segment provider；
- Action 注册；
- 当前 profile 的事件订阅；
- preparation/completion handler；
- User profile 必要的 recorder。

它只描述当前 profile 如何使用插件 owner，不拥有 generation Engine，不直接启动来源，也不跨 Turn 保存可变视图。它不是完整的 `TurnProfile`，不拥有独立运行生命周期；声明中的 Segment provider 在具体 Turn 内创建视图，并由 Turn 的 Context 生命周期更新和释放。

现有 `PluginDeclaration` 应收口为 `PluginProfileExtension`。现有 `ResolvedPlugins` 调整为内部 `ResolvedProfileExtensions`，只表示一个 profile 的已解析扩展集合，不再暗示它包含 Agent 级插件实例。优先复用现有文件和校验实现，不建立旧声明与新扩展并行维护的协议；generation source 必须移到 `PluginGeneration`。

### 3.8 TurnProfile 与 Turn

`TurnProfile` 是将一个执行情景的策略、内置内核组件和各插件针对该情景的 `PluginProfileExtension` 解析后得到的完整可执行配置。它属于当前 AgentGeneration，绑定：

- ContextEngine；
- ActionEngine 和可见 Action surface；
- profile 服务 registry；
- preparation/completion pipeline；
- domain skill、完成输出、预算、Trap 和等待策略。

User、Home Reflection、Memory Reflection 是当前固定的 profile identity。它们共享 Kernel Turn/Cycle/Phase 实现，但拥有不同的 Context、Action surface、服务权限、写边界和完成输出。

`Turn` 是一次具体执行。Turn 只使用已经装配好的一个 `TurnProfile`，通过请求类型选择 profile；Turn 不改变 AgentAssembly，也不安装新的 Plugin。Profile 决定能力是否可用，Plugin 决定能力是否属于 Agent 的组装。

例如，同一个 Memory `PluginGeneration` 持有一个 Memory Engine，针对 User 提供活动记忆操作和持久记忆读取，针对 Memory Reflection 提供受约束的持久写入。两个 `PluginProfileExtension` 引用同一个领域 owner，但暴露不同的服务权限与 Action；它们分别参与不同 `TurnProfile` 的构建。每次 Turn 的可变 Context 仍独立创建。

## 4. 目标对象关系

组装与资源所有权关系如下：

```text
AgentBuilder
    │ build()
    ▼
AgentAssembly  ── contains ── AgentPlugin factories
    │ Agent.assemble(assembly) returns Agent
    ▼
Agent
    └─ AgentRuntime（内部运行容器）
         ├─ 唯一根调度器、输入/事件路由、生命周期与进程资源
         └─ current-generation handle
              └─ AgentGeneration
                   ├─ 共享宿主服务与执行设施
                   ├─ PluginGeneration（每个插件一个）
                   │    └─ Engine / connection / source / day resource
                   └─ TurnProfile（按执行情景解析）
```

插件扩展与执行关系如下：

```text
AgentPlugin
    │ 在每个 AgentGeneration 中创建一次
    ▼
PluginGeneration
    ├─ PluginProfileExtension(user)
    ├─ PluginProfileExtension(home_reflection)
    └─ PluginProfileExtension(memory_reflection)
       （仅为插件参与的情景提供扩展）

多个插件针对同一情景的 PluginProfileExtension
    + 该情景的服务授权、Action 策略、完成策略和内核组件
    ▼
TurnProfile → Turn → Cycle → Phase
```

这条关系表达三个边界：

1. Agent 的组装在 `AgentAssembly` 中定义；
2. AgentGeneration 管理整个世代，PluginGeneration 封装单个插件在该世代内的运行资源；
3. PluginProfileExtension 是局部声明，TurnProfile 是汇集与校验后的完整执行情景，Turn 使用它执行。

## 5. AgentPlugin 接口设计

类型名称按已确认方案固定。方法预览采用 `build_generation` 和 `extend_profile`，分别表达创建插件运行实例与提供情景扩展；具体参数沿现有受约束端口整理，不新增无消费者接口：

```python
class AgentPlugin(Protocol):
    id: str

    async def build_generation(
        self,
        context: GenerationBuildContext,
    ) -> PluginGeneration: ...
```

`PluginGeneration` 提供一个窄的 profile 扩展方法；不参与某个情景时返回 `None`：

```python
class PluginGeneration(Protocol):
    def extend_profile(
        self,
        profile: ProfileKind,
        context: ProfileBuildContext,
    ) -> PluginProfileExtension | None: ...

    async def close(self) -> tuple[CleanupDiagnostic, ...]: ...
```

这里的 `ProfileBuildContext` 不能暴露完整可变 `Agent` 或所有 Engine。它只提供：

- 当前 generation 的受约束服务解析；
- 当前 profile 的策略和权限；
- Context、Action、观察和 Signal 的组装端口；
- 当前 profile 允许使用的宿主资源。

Plugin 通过 `PluginProfileExtension.requires` 表达所需 facade，由 profile resolver 进行校验。插件不能通过闭包捕获完整组合根绕过依赖声明，也不能自行向其它 profile 注入服务。

Plugin 的以下内容分别归属不同阶段：

| 内容 | 所属阶段 | 所有者 |
|---|---|---|
| Plugin id、依赖和适用 profile | Assembly | AgentBuilder/Plugin registry |
| Engine、连接、缓存、RuntimeSource | Generation | PluginGeneration |
| Segment provider、Action 注册、事件与完成处理声明 | Profile | PluginProfileExtension |
| Context 视图和 Action 批次 | Turn | Kernel 与 profile provider |
| 持久事实 | Domain owner | Home/Memory/Session/Workspace 或具体 capability |

每个已组装 Plugin 提供自己的 PluginGeneration，但不要求它拥有 I/O 资源、来源或日切处理。插件只为实际参与的情景提供 PluginProfileExtension，其余情景返回 `None`，不为缺失能力制造空扩展或重复 Engine。

## 6. Profile 选择与权限

Profile 不是 Plugin 的别名，也不是用户临时传入的字符串配置。它是 Agent 内核支持的一组稳定执行情景。

请求进入根队列时由请求类型选择 profile：

- `UserTurnRequest` 选择 `user`；
- Home Reflection 请求选择 `home_reflection`；
- Memory Reflection 请求选择 `memory_reflection`。

Profile 构建时，Agent 汇集当前 generation 中各 `PluginGeneration` 提供的 `PluginProfileExtension`，依据该情景的 grant、visibility、服务权限和完成策略建立 `TurnProfile`。因此：

- Agent 没有 Memory Plugin 时，Memory Reflection profile 无法构建；
- Memory Plugin 属于 Agent，并不意味着 User profile 自动获得 Memory 持久写权限；
- Home/Memory Reflection 的专属写服务由 profile 显式授予；
- Action catalog visibility 只筛选已声明且已授予的能力，不能补足缺失的 owner 或 service。

Plugin 可以声明只参加某个 profile，也可以为多个 profile 提供不同的 `PluginProfileExtension`。同一个 generation Engine 可以被多个 profile 以只读或窄 facade 方式使用；Action surface 按情景解析，每个 Turn 的可变 Segment 视图和执行状态独立创建。

## 7. Context 与领域 owner 的关系

插件组合定义 Agent 的语境能力，但不让 Plugin 直接拥有一份平行 Context 内容。

- Domain Engine 持有 Home、Memory、Session、Workspace 或 capability 的领域事实；
- PluginProfileExtension 提供用于创建当前 Turn 视图的 Segment provider；
- Segment 读取 Engine 当前状态，构造 Background、Trace 或 Working 的受限投影；
- ContextEngine 只负责组合、批次 prepare/install、render、inspect 路由和压力回收；
- Kernel 不解释 Segment 的业务内容。

Background、Trace、Working 的位置由 Context 组合协议决定，State/Heap/Stack/Map 是内容形状，INSPECT/QUERY/SELECT/RECLAIM 是访问能力。Plugin 只声明自身 segment 的稳定身份、引用前缀和能力，不改变这些公共语义。

Plugin 的 Action 结果必须通过现有 Action/Trace/Session 事实链；不另建 Plugin 日志或隐式后台模型任务。持久事实仍由 owner 先提交，再发送 Signal 刷新当前 profile 的视图。

## 8. 生命周期与资源边界

目标生命周期为：

```text
AgentBuilder.build
  → AgentAssembly（无运行副作用）
Agent.assemble
  → 创建 AgentRuntime → 创建初始 AgentGeneration / PluginGeneration
  → 汇集 PluginProfileExtension → 解析 TurnProfile → 返回 Agent
Agent.start
  → day prepare → activate sources → 受理根 work
根请求
  → 选择 profile → 创建 Turn → 运行 shared Kernel
restart/reload
  → 收敛旧 generation → 从同一 AgentAssembly 创建新 generation 并激活
shutdown
  → 停止来源 → 收敛 Turn/Job → 关闭 PluginGeneration / AgentGeneration → 关闭 AgentRuntime
```

必须遵守：

1. AgentPlugin 定义可以复用，但每个 AgentGeneration 必须创建新的 PluginGeneration，不跨世代复用可变 Engine，也不引入插件独立世代；
2. RuntimeSource、ACP/MCP 连接、watcher 和模型客户端按 generation 或 owner 资源关闭；
3. Segment provider 只创建当前 Turn/profile 的视图；
4. Job 只属于唯一 Turn，不因 Plugin 或连接复用而跨 Turn；
5. Profile 服务通过 generation/day lease 绑定，旧世代或旧日调用返回现有 stale/unavailable SDK 错误；
6. 组合失败、generation 构建失败和 profile 注册失败都在模型执行前收束，不伪造局部 ActionResult；
7. Turn 内的 Action、Phase 和 Context 失败继续沿现有三层失败语义处理。

## 9. 公开 API 与内部 API

### 9.1 公开 SDK

公开且稳定的核心入口：

```text
AgentBuilder       编写 AgentAssembly
AgentAssembly      描述 Agent 由哪些插件和宿主选项构成
Agent.assemble     从 AgentAssembly 创建运行 Agent
Agent              使用已创建的运行 Agent
Agent.services     显式导出的 SDK facade
Agent.commands     Turn、事件和控制入口
```

`Agent.assemble(assembly)` 是显式组装的主要入口。若保留 `Agent.create(root, ...)`，它只负责构造默认 `AgentAssembly` 后调用 `Agent.assemble`，不再提供独立的 factory 或资源组装语义。公开 SDK 不要求宿主知道 `RuntimeHandle`、`AgentGeneration`、内部 `AgentRuntime` 或 Kernel frame。

### 9.2 插件 SPI 与内部装配

自定义插件作者通过 `AgentPlugin`、`PluginGeneration`、`PluginProfileExtension` 和受约束的构建 context 接入；这些是插件 SPI，普通 SDK 调用者无需操作它们。运行门面不公开可变插件注册表或 PluginGeneration 资源管理权。

以下对象只属于内部组装实现：

- generation builder/factory；
- profile builder；
- 插件依赖校验、profile resolver 和 `ResolvedProfileExtensions`；
- AgentRuntime resource scope；
- Runtime bridge 和 Plugin registry 的内部校验细节。

当前 `Agent.assemble(assembly_factory)` 应改为 `Agent.assemble(assembly: AgentAssembly)`。它负责从不可变组装定义创建 AgentRuntime，异步准备初始 AgentGeneration 及其 PluginGeneration 和 TurnProfile，返回 Agent，但不启动来源、不接受根 work。当前进程级 `AgentAssembly` 运行容器应改名为内部 `AgentRuntime`，避免与静态组装定义重名。低层测试若需要直接提供 generation factory，应使用内部 `AgentRuntimeFactory`，不能再把 factory 形式作为第二种公开 Agent 创建方式。

### 9.3 服务导出

内部 `ServiceRegistry` 仍按 facade 类型解析。每个 Plugin 可以声明内部服务和可公开 SDK facade，但二者必须分开：

- 内部 service 供 profile Action、Segment、completion 使用；
- SDK facade 通过 Agent 的 generation/day lease 绑定后显式导出；
- 未被真实上层消费者使用的内部服务不自动公开；
- restart/reload 后旧 facade 必须失效，由宿主重新获取。

## 10. 与现有代码的目标映射

| 当前位置 | 目标调整 |
|---|---|
| `tinysoul/agent/composition/builder.py` | 保留 Agent 组装根职责，拆出无运行副作用的 `AgentAssembly` 构建和 generation 构建两层 |
| `tinysoul/agent/composition/assembly.py` | 保存静态 `AgentAssembly`；当前进程级运行容器迁移为内部 `AgentRuntime` |
| `tinysoul/agent/sdk.py` | 以 `Agent.assemble(AgentAssembly)` 创建 Agent；`Agent.create` 仅可作为默认组装的薄便捷入口 |
| `tinysoul/agent/lifecycle/generation.py` | 将 `AgentRuntimeGeneration` 收口为 `AgentGeneration`，统一管理 PluginGeneration 生命周期 |
| `tinysoul/kernel/registration.py` | 将当前 profile 级 PluginDeclaration 收口为 PluginProfileExtension，ResolvedPlugins 收口为内部 ResolvedProfileExtensions；保留通用依赖和段校验 |
| `tinysoul/agent/composition/actions.py` | 将 execution、expand、subagent 等内置能力逐步纳入标准 Plugin suite，保留统一 Job/Action 装配 |
| `tinysoul/agent/user/builder.py` | 仅负责 user profile 的 Context/TurnProfile，消费各 PluginGeneration 为 user 提供的 PluginProfileExtension |
| `tinysoul/plugins/reflection/builder.py` | 仅负责 home/memory reflection profile，消费同一 PluginGeneration 针对不同情景的 PluginProfileExtension |
| `tinysoul/agent/lifecycle/sources.py` | 直接接收 generation 级来源集合，不再从 profile declaration 汇总来源 |
| `tinysoul/agent/services.py` | 从当前 generation 的明确 SDK export 表构造服务 facade |
| `docs/design/agent.md` | 重写组装、generation、profile、Turn 和 SDK 入口语义 |
| `docs/design/context.md` / `loop.md` | 明确 PluginProfileExtension 与 Context/Turn kernel 的边界 |
| `docs/design/capabilities.md` | 说明 capability Plugin 与 Action/Job/Workspace owner 的关系 |

实现时优先复用现有 `PluginRegistry`、`TurnProfile`、`GenerationSources`、`ServiceRegistry` 和资源 scope；只有当前类型无法表达 generation/profile 分离时才新增类型，避免建设第二套注册框架。

## 11. 异常处理与失败边界

组合模型不改变现有三层失败语义，只明确失败发生的位置：

| 位置 | 失败示例 | 处理 |
|---|---|---|
| Assembly build | 重复 Plugin id、静态依赖环、宿主配置类型错误 | `AgentAssemblyError` 或既有配置错误，未创建运行资源 |
| Generation build | Plugin Engine 配置错误、缺少依赖、连接或资源初始化失败 | 所属 owner runtime bridge；逆序关闭已创建资源，Agent 保留有限启动失败 |
| Profile resolve | 服务 facade 冲突、Segment 路由冲突、Action catalog 不一致 | profile/generation 装配失败，不开始 Turn |
| Turn Phase/Action | 参数无效、工具失败、模型协议失败 | 现有 typed 局部结果和下一 Cycle 反馈 |
| Runtime/lease | 日切、取消、预算、世代切换 | 现有 Trap/Transfer/SDK stale 语义 |
| close/observation | 资源关闭或 sink 失败 | 有界 cleanup diagnostic，不覆盖已提交主结果 |

Plugin 不得用宽泛 `except Exception` 把 generation 构建错误伪装成模型可修正的 ActionResult，也不得吞掉取消和 RuntimeException。第三方 ACP/MCP 边界仍可封装供应商异常，但要在 capability owner 内转换为稳定失败或 runtime bridge。

## 12. 执行阶段

### P0：确认术语和边界

状态：`done`（仅设计确认，代码实现未开始）。

本方案已对照 `AGENTS.md`、主计划、review 和现有设计语义分析。维护者于 2026-09-22 确认采用以下命名和所有权边界；具体设计位于第 2～9 节，后续 P1～P7 均为 `pending`：

- `AgentBuilder.build()` 产生 `AgentAssembly`；
- `Agent.assemble(AgentAssembly)` 创建运行 Agent；`Agent.create(root, ...)` 如保留，只是默认组装的薄便捷入口；
- 当前进程级运行容器改名为内部 `AgentRuntime`，整个运行世代命名为 `AgentGeneration`；
- 插件组成定义为 `AgentPlugin`，插件在某个世代中的运行实例为 `PluginGeneration`，面向情景的局部声明为 `PluginProfileExtension`；
- 多个插件针对同一情景的扩展与情景策略共同解析为 `TurnProfile`；
- generation source/resource 由 PluginGeneration 封装并经 Agent 生命周期协调，不再由 profile 声明承担；
- Profile 仍由 User/Reflection 请求类型选择，而不是由 Plugin 临时切换。

### P1：先修复独立的 ACP 类型门禁

修复 review F2：

- `_Client` 对 ACP `Client` Protocol 的未支持文件、终端和 elicitation 方法提供明确的 method-not-found/拒绝处理；
- 测试 `LocalAgent` 对未支持 Agent Protocol 方法表达相同语义；
- 不添加第二套文件或终端能力，不用宽泛 cast 或 type ignore；
- 运行 ACP 聚焦、Fast、Full 和干净环境 typecheck。

F2 不依赖本方案的 Plugin API，但必须先恢复干净的类型门禁。

### P2：建立 Assembly 模型

新增或整理最小的组合类型和测试：

- `AgentAssembly`；
- `AgentPlugin`、`PluginGeneration` 及 generation build context；
- `PluginProfileExtension`、profile kind 和 profile build context；
- Plugin identity/dependency/重复 owner 校验；
- Builder 无运行副作用的构建测试。

这一阶段不迁移所有内置能力，只让现有默认装配可以被包装为一个明确的标准 Plugin suite。

### P3：分离插件运行实例与情景扩展

调整注册协议：

1. 将 RuntimeSource、day participant 和插件资源 close 责任移到 PluginGeneration；
2. 将 profile 的 services、Segment provider、actions、events、preparation/completion 和 recorder 保留在 PluginProfileExtension；
3. 将 `ResolvedPlugins` 收口为内部 `ResolvedProfileExtensions`，仅保存单一 profile 的解析结果；
4. 让 User 与两类 Reflection 使用同一批 PluginGeneration 提供的不同情景扩展建立 TurnProfile；
5. 保证来源只启动一次，日切的来源停启和绑定切换、reload/restart 的世代关闭与重建均由 Agent 生命周期协调，插件不维护独立调度。

### P4：内置能力接入标准 Plugin suite

按真实所有权逐步迁移 Home、Memory、Session、Workspace、Execution、ACP、MCP、Reflection schedule 和 Workspace watcher。迁移顺序以减少并行实现为准：

1. 先迁移已有 `declare_home/declare_memory/declare_session/declare_workspace`；
2. 再迁移 execution、subagent、expand 的连接资源与 Action 扩展，Job 监督继续复用 kernel/jobs；
3. 最后迁移 Reflection 的 profile 专属写服务和 scheduler source。

每一步删除旧的特殊装配旁路，不保留同一能力的旧声明和新 Plugin 两套路径。

### P5：接入一个真实自定义 Plugin

实现一个最小但真实的宿主能力作为验收插件，例如“知识来源”：

- PluginGeneration 内的 Engine 持有来源状态；
- User 的 PluginProfileExtension 提供一个 Background 或 Working Segment provider；
- 提供一个 Action；
- 环境事件更新 owner，下一批 Context 刷新；
- restart 关闭旧 PluginGeneration 及其 Engine，并创建新实例；
- 旧 generation service 明确失效；
- 不修改 Kernel，不创建新调度器。

该插件的测试比抽象接口测试更重要，用来证明 Plugin 组合能够承载真实能力。

### P6：收口公开 SDK 和删除歧义入口

更新 SDK、CLI、Endpoint 和测试：

- 默认 Gateway 使用标准 Plugin suite 和显式 Assembly 入口；若保留 `Agent.create`，它只委托同一组装路径；
- 自定义宿主通过 `AgentBuilder.use` 组合；
- 现有 `Agent.assemble` 调用迁移到静态 Assembly/内部 runtime factory；
- 当前进程级 `AgentAssembly` 改为内部 `AgentRuntime`；
- 导出自定义插件必需的 AgentPlugin、PluginGeneration、PluginProfileExtension SPI；SDK 服务只导出明确 facade，不导出完整可变 Plugin registry。

同步更新 Endpoint 文档；Endpoint 继续调用 Agent，不维护自己的 Plugin、profile 或 generation 状态。

### P7：文档、验证与归档

同步设计文档和 README 示例，至少包含：

- AgentAssembly、AgentRuntime 与 AgentGeneration 的区别；
- AgentPlugin、PluginGeneration、PluginProfileExtension、TurnProfile 的关系；
- User/Reflection profile 选择和权限边界；
- 一个自定义 Plugin 的组装示例；
- restart/reload/stale service 行为。

实现阶段同步 AGENTS.md 中现有 PluginDeclaration 条款，使其准确表达 PluginGeneration 的来源/资源责任与 PluginProfileExtension 的情景扩展责任。当前文档修订不把尚未落地的命名写成现有代码事实。

验证顺序：

1. Plugin registry、Assembly 和 profile resolver 聚焦测试；
2. ACP 聚焦测试；
3. Fast suite；
4. Full suite；
5. `scripts/typecheck.ps1`；
6. wheel/generation 验收和自定义 Plugin 集成测试。

只有实现、设计文档、测试和门禁逐项完成后，才将本文件移动到 `docs/analysis/done/` 并加入 `-done-` 文件名。

## 13. 不纳入本次方案的内容

- 不引入 DDS 或通用消息中间件；
- 不创建动态插件发现、安装和版本管理平台；
- 不为每个 profile 建立独立 Loop、Action runner 或 Job registry；
- 不把所有内部服务自动公开给 SDK；
- 不把 Context 内容复制到 Plugin 自己的平行历史；
- 不提前实现 `do something` 中所有产品能力；
- 不因 Plugin API 而重做 Session Map、Reflection 写边界、Workspace 原子文件协议或 Memory 持久化模型。

## 14. 验收标准

方案完成必须同时满足：

1. 代码中可以清楚指出组装定义、generation、profile 和 Turn 的唯一 owner；
2. `AgentBuilder` 只构造 `AgentAssembly`，不启动运行资源；
3. AgentRuntime 按 AgentAssembly 管理 AgentGeneration，并在 restart/reload 时重新创建各 PluginGeneration；插件不维护独立世代或重启机制；
4. PluginProfileExtension 不承载 generation 级 source 生命周期，Segment provider 只在具体 Turn 内创建可变视图；
5. User、Home Reflection、Memory Reflection 复用同一批 PluginGeneration，各插件按情景提供 PluginProfileExtension，并解析为不同 TurnProfile；
6. 一个自定义 Plugin 可以提供 Engine、Segment、Action 和事件刷新，不修改 Kernel；
7. 旧服务、旧 Segment 和旧 generation 资源在切换后失效或关闭；
8. 失败处理符合 Assembly、Generation、Profile、Turn 四个边界和现有三层失败语义；
9. 不存在旧 Builder、assemble、PluginDeclaration 旁路与新 Plugin 体系并行维护的重复实现，不为讨论阶段候选名称保留兼容别名；
10. Full 测试和 typecheck 通过，且设计文档准确描述已落地能力。

## 15. 确认记录与当前进展

2026-09-22，维护者确认采用 `PluginGeneration` 与 `PluginProfileExtension`，并要求按讨论修订方案。本轮已统一术语、接口预览、两条对象关系、迁移映射、执行阶段与验收标准；命名和所有权边界不再作为待确认项。

本次交付范围为执行计划修订，没有修改生产代码、测试、Endpoint 协议或描述现有实现的设计文档。P0 设计确认完成，完整重构计划保持 `pending`，P1～P7 尚未实施，不归档为完成。

后续实施按 P1 → P7 推进，并按第 12 节同步设计文档、AGENTS.md 与必要验证。只有实际实现、文档和门禁逐项核对完成后，才能将整个计划标为 `done`。
