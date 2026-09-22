# Agent Harness 与 Plugin 组装重构方案

状态：`pending`（方案预览，尚未实施）  
提出日期：2026-09-22  
关联审查：`docs/analysis/20260922-agent-refactor-completion-review-e2625da.md`  
关联主计划：`docs/analysis/done/20260915-done-agent-architecture-refactor-plan.md`

## 1. 目标与范围

本方案收口 Agent SDK 的组装语义。TinySoul 的主要宿主是我们自己的 Agent 与上层应用，因此 SDK 的核心目标是让 Agent 能力以清晰、显式、可替换的 Plugin 组合形成，同时保持唯一根调度、唯一 Turn 内核、统一 Context、Job 和 owner 语义。

本方案解决以下问题：

1. 区分 Agent 的组成定义、运行 generation、执行 profile 和实际 Turn；
2. 统一 `builder`、`assemble`、`declaration`、`profile` 的职责和命名；
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
| `Agent.assemble` | 接收一个 `AgentAssembly` 工厂，创建 SDK Agent | `assemble` 与 `AgentAssembly`、Builder 的关系不清楚，且是高级内部组合入口 |
| `AgentAssembly` | 进程级根调度、命令、来源、配置和 generation handle | 它不是 Agent 组成定义，也不是单一 generation，名称容易与组装动作混淆 |
| `PluginDeclaration` | 某个 profile 的服务、段、Action、事件、完成处理和运行来源 | 同一个对象同时带有 profile 贡献和 generation 来源，Plugin 与 Declaration 边界不清楚 |
| `ResolvedPlugins` | 一个 profile 的已校验贡献集合 | 名称像已解析的 Agent 插件集合，实际只服务一个 TurnProfile |
| `TurnProfile` | 当前情景的 Context、Action surface、服务、完成策略和 Trap | 与“Profile 选择能力”及实际 runtime profile 的关系没有单独命名说明 |

其中最需要修正的是 `PluginDeclaration.sources`：来源由三个 profile 汇总后再由 `GenerationSources` 去重，运行上可用，但语义上使 generation 级来源看起来像 profile 贡献。generation 资源、来源和 profile 视图应在协议上分开。

## 3. 稳定术语与所有权

以后采用以下术语。新代码和设计文档使用这些含义，不再把同一个词用于多个层次。

### 3.1 AgentComposition

`AgentComposition` 是一个 Agent 的不可变组成定义，描述：

- 项目根和宿主基础依赖；
- 配置来源及已解析的宿主选项；
- 参与 Agent 的 `AgentPlugin` 工厂集合；
- 默认 profile 集合和 profile 策略；
- 输入源、观察 sink 等进程级宿主适配。

它描述 Agent 由哪些能力构成，不拥有已经启动的来源、LLM 客户端、Workspace watcher 或可变领域 Engine。添加、删除或替换 Plugin 是组成定义变化，需要重新创建或重新装配 Agent；普通配置 reload 只在组成仍然有效时重建 generation。

### 3.2 AgentBuilder

`AgentBuilder` 是宿主用于编写 `AgentComposition` 的公开组装门面。它负责收集显式配置和 Plugin，检查组成级身份与依赖，然后产生 `AgentComposition`。

`AgentBuilder` 不启动来源、不创建活动 Turn、不拥有根调度器，也不执行模型调用。它可以提供少量稳定的宿主注入方法，例如项目根、配置环境、模型 provider、时钟、观察 sink 和输入源；领域能力通过 `use(plugin)` 进入，不为每个内部 Engine 暴露一个平行的 `with_*` 注入入口。

建议的公开形态为：

```python
composition = (
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
agent = await Agent.from_composition(composition)
```

`Agent.create(root, ...)` 保留为默认 Plugin 集合的便捷入口，相当于创建标准 `AgentComposition` 后建立 Agent runtime；显式组成使用 `Agent.from_composition(composition)`。`AgentBuilder.build()` 的结果是组成定义，不是可接受请求的运行对象。

### 3.3 Agent

`Agent` 是宿主使用的运行 SDK 门面。它拥有唯一根队列、运行世代句柄、事件路由、日协调和生命周期操作：`start`、`submit_turn`、`append_input`、`reply`、`publish`、`restart`、`reload`、`shutdown` 等。

Agent 的行为由其 `AgentComposition` 决定，但 Agent 本身不暴露可变 Plugin 注册表。运行后添加 Plugin 会破坏 generation 身份、资源边界和服务 lease，因此必须通过新的组成定义重新创建 Agent。

### 3.4 AgentGeneration

`AgentGeneration` 是一次组成定义和有效配置的运行实例。它持有该世代的：

- LLM、embedding、Workspace、Home、Memory、Session 等 Engine；
- capability 连接和外部协议资源；
- generation 级 RuntimeSource、day participant 和关闭资源；
- 为各 profile 建立的 Action、Context provider 和服务绑定。

Generation 随 start、restart 或成功 reload 创建和激活，失效后所有 generation/day 绑定的服务对象必须拒绝继续使用。Generation 负责拥有实际领域 Engine；它不持有某个 Turn 的可变 Context 段视图。

### 3.5 AgentPlugin

`AgentPlugin` 是 Agent 的组成单元。它不是单个 Action，也不是一个 TurnProfile。一个 Plugin 可以拥有自己的配置、generation Engine、服务、RuntimeSource、profile 贡献和关闭逻辑。

Plugin 由宿主显式加入 `AgentBuilder`，不通过 import 扫描或运行时动态发现。Plugin 身份、组成依赖和重复 owner 在组成或 generation 准备阶段确定性校验。

### 3.6 GenerationContribution

`GenerationContribution` 表示一个 Plugin 在某个 `AgentGeneration` 中创建的运行资源和 generation 级事实：

- Engine 或受约束服务实现；
- RuntimeSource；
- 日切参与者；
- generation 资源关闭回调；
- 供 profile 构建使用的窄依赖 facade。

这些内容只创建一次，不能因为 User、Home Reflection 和 Memory Reflection 各自建 profile 而重复创建。GenerationSource 的身份冲突、来源启动和关闭仍由 Agent 生命周期协调。

### 3.7 ProfileContribution

`ProfileContribution` 是 Plugin 针对一个执行 profile 提供的声明。它包含：

- profile 可用的服务 facade；
- 当前 Turn 的 Segment provider；
- Action 注册；
- 当前 profile 的事件订阅；
- preparation/completion handler；
- User profile 必要的 recorder。

它只描述当前 profile 如何使用 generation owner，不拥有 generation Engine，不直接启动来源，也不跨 Turn 保存可变视图。

现有 `PluginDeclaration` 应重命名为 `ProfileContribution`。现有 `ResolvedPlugins` 应重命名为 `ResolvedProfileContributions` 或等价的单一 profile 解析结果。若实现阶段证明重命名会产生不必要的重复文件，可以保留文件位置，但类型语义必须按本节收口，不能继续把 generation source 放在其中。

### 3.8 TurnProfile 与 Turn

`TurnProfile` 是将一个 profile 策略、一个 generation 和一组 `ProfileContribution` 解析后得到的可执行 runtime surface。它绑定：

- ContextEngine；
- ActionEngine 和可见 Action surface；
- profile 服务 registry；
- preparation/completion pipeline；
- domain skill、完成输出、预算、Trap 和等待策略。

User、Home Reflection、Memory Reflection 是当前固定的 profile identity。它们共享 Kernel Turn/Cycle/Phase 实现，但拥有不同的 Context、Action surface、服务权限、写边界和完成输出。

`Turn` 是一次具体执行。Turn 只使用已经装配好的一个 `TurnProfile`，通过请求类型选择 profile；Turn 不改变 AgentComposition，也不安装新的 Plugin。Profile 决定能力是否可用，Plugin 决定能力是否属于 Agent 的组成。

## 4. 目标对象关系

目标关系如下：

```text
AgentBuilder
    │ build()
    ▼
AgentComposition  ── contains ── AgentPlugin factories
    │ Agent.create(root) / Agent.from_composition
    ▼
Agent
    │ owns one root scheduler and one current AgentGeneration
    ▼
AgentGeneration
    ├─ GenerationContribution / Engine / source / day resource
    └─ profile builders
         ├─ User TurnProfile
         ├─ Home Reflection TurnProfile
         └─ Memory Reflection TurnProfile
                │
                └─ ProfileContribution → Context / Action / Service / pipeline
                                      │
                                      └─ Turn → Cycle → Phase
```

这条关系表达三个边界：

1. Agent 的组成在 `AgentComposition` 中定义；
2. generation 是组成定义的一次可运行资源实例；
3. profile 是运行时情景，Turn 只在某个 profile 上执行。

## 5. AgentPlugin 接口设计

最终接口名称可以在实现阶段按现有类型布局确定，但语义应遵循以下形态：

```python
class AgentPlugin(Protocol):
    id: str

    def build_generation(
        self,
        context: GenerationBuildContext,
    ) -> Awaitable[GenerationContribution]: ...
```

`GenerationContribution` 提供一个窄的 profile 贡献方法：

```python
class GenerationContribution(Protocol):
    def contribute(
        self,
        profile: ProfileKind,
        context: ProfileBuildContext,
    ) -> ProfileContribution | None: ...

    async def close(self) -> tuple[CleanupDiagnostic, ...]: ...
```

这里的 `ProfileBuildContext` 不能暴露完整可变 `Agent` 或所有 Engine。它只提供：

- 当前 generation 的受约束服务解析；
- 当前 profile 的策略和权限；
- Context、Action、观察和 Signal 的组装端口；
- 当前 profile 允许使用的宿主资源。

Plugin 通过 `ProfileContribution.requires` 表达所需 facade，由 profile resolver 进行校验。插件不能通过闭包捕获完整组合根绕过依赖声明，也不能自行向其它 profile 注入服务。

Plugin 的以下内容分别归属不同阶段：

| 内容 | 所属阶段 | 所有者 |
|---|---|---|
| Plugin id、依赖和适用 profile | Composition | AgentBuilder/Plugin registry |
| Engine、连接、缓存、RuntimeSource | Generation | Plugin generation contribution |
| Segment、Action、事件处理、完成处理 | Profile | ProfileContribution |
| Context 视图和 Action 批次 | Turn | Kernel 与 profile provider |
| 持久事实 | Domain owner | Home/Memory/Session/Workspace 或具体 capability |

不要求每个 Plugin 都实现所有阶段。只有真实消费者需要的贡献才提供；无内容的阶段不创建空对象。

## 6. Profile 选择与权限

Profile 不是 Plugin 的别名，也不是用户临时传入的字符串配置。它是 Agent 内核支持的一组稳定执行情景。

请求进入根队列时由请求类型选择 profile：

- `UserTurnRequest` 选择 `user`；
- Home Reflection 请求选择 `home_reflection`；
- Memory Reflection 请求选择 `memory_reflection`。

Profile 构建时，Agent 将当前 generation 中参与该 profile 的 Plugin contributions 合并，依据 profile 的 grant、visibility、服务权限和完成策略建立 `TurnProfile`。因此：

- Agent 没有 Memory Plugin 时，Memory Reflection profile 无法构建；
- Memory Plugin 属于 Agent，并不意味着 User profile 自动获得 Memory 持久写权限；
- Home/Memory Reflection 的专属写服务由 profile 显式授予；
- Action catalog visibility 只筛选已声明且已授予的能力，不能补足缺失的 owner 或 service。

Plugin 可以声明只参加某个 profile，也可以为多个 profile 提供不同的 `ProfileContribution`。同一个 generation Engine 可以被多个 profile 以只读或窄 facade 方式使用，但每个 Turn 的 Segment 和 Action surface 必须独立构建。

## 7. Context 与领域 owner 的关系

插件组合定义 Agent 的语境能力，但不让 Plugin 直接拥有一份平行 Context 内容。

- Domain Engine 持有 Home、Memory、Session、Workspace 或 capability 的领域事实；
- Plugin 的 profile contribution 提供当前 Turn 的 Segment provider；
- Segment 读取 Engine 当前状态，构造 Background、Trace 或 Working 的受限投影；
- ContextEngine 只负责组合、批次 prepare/install、render、inspect 路由和压力回收；
- Kernel 不解释 Segment 的业务内容。

Background、Trace、Working 的位置由 Context 组合协议决定，State/Heap/Stack/Map 是内容形状，INSPECT/QUERY/SELECT/RECLAIM 是访问能力。Plugin 只声明自身 segment 的稳定身份、引用前缀和能力，不改变这些公共语义。

Plugin 的 Action 结果必须通过现有 Action/Trace/Session 事实链；不另建 Plugin 日志或隐式后台模型任务。持久事实仍由 owner 先提交，再发送 Signal 刷新当前 profile 的视图。

## 8. 生命周期与资源边界

目标生命周期为：

```text
AgentBuilder.build
  → AgentComposition（无运行副作用）
Agent.from_composition
  → Agent runtime 壳和 generation factory
Agent.start
  → build generation → build profiles → day prepare → activate sources
根请求
  → 选择 profile → 创建 Turn → 运行 shared Kernel
restart/reload
  → 停止旧 generation → 从同一 composition 创建新 generation
shutdown
  → 停止来源 → 收敛 Turn/Job → 关闭 generation → 关闭 Agent runtime
```

必须遵守：

1. Plugin 工厂不能只创建一次并复用内部可变 Engine；每个 generation 都要产生新的 generation contribution；
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
AgentBuilder       编写 AgentComposition
AgentComposition   描述 Agent 由哪些插件和宿主选项构成
Agent               使用已创建的运行 Agent
Agent.services      显式导出的 SDK facade
Agent.commands      Turn、事件和控制入口
```

`Agent.create(root, ...)` 是默认组成的便捷构造；显式组成使用 `Agent.from_composition(composition)`。公开 SDK 不要求宿主知道 `RuntimeHandle`、`AgentGeneration`、`AgentAssembly` 或 Kernel frame。

### 9.2 内部装配

以下对象只属于 Agent/插件组合实现：

- generation builder/factory；
- profile builder；
- `GenerationContribution` 和 `ProfileContribution` resolver；
- Agent runtime resource scope；
- Runtime bridge 和 Plugin registry 的内部校验细节。

当前 `Agent.assemble(assembly_factory)` 不再作为主要 SDK 概念。实现阶段应将其迁移为内部 runtime factory 或测试专用装配入口，并删除会让用户同时面对 `assemble`、`AgentAssembly` 和 `AgentBuilder` 的平行公开路径。若确有低层测试需要，必须使用明确的内部命名，不能继续把它描述为另一种 Agent 创建方式。

### 9.3 服务导出

内部 `ServiceRegistry` 仍按 facade 类型解析。每个 Plugin 可以声明内部服务和可公开 SDK facade，但二者必须分开：

- 内部 service 供 profile Action、Segment、completion 使用；
- SDK facade 通过 Agent 的 generation/day lease 绑定后显式导出；
- 未被真实上层消费者使用的内部服务不自动公开；
- restart/reload 后旧 facade 必须失效，由宿主重新获取。

## 10. 与现有代码的目标映射

| 当前位置 | 目标调整 |
|---|---|
| `tinysoul/agent/composition/builder.py` | 保留 Agent 组合根职责，拆出无副作用的 Composition 构建和 generation 构建两层 |
| `tinysoul/agent/composition/assembly.py` | 将当前进程级容器改为内部 Agent runtime 容器，避免继续作为公开组成概念 |
| `tinysoul/agent/sdk.py` | 以 `AgentComposition` 创建 Agent；降低或移除 `Agent.assemble` 的公开地位 |
| `tinysoul/agent/lifecycle/generation.py` | 明确 `AgentGeneration` 与 generation Plugin contributions 的所有权 |
| `tinysoul/kernel/registration.py` | 将当前 profile 级 PluginDeclaration 语义收口为 ProfileContribution/等价类型；保留通用依赖和段校验 |
| `tinysoul/agent/composition/actions.py` | 将 execution、expand、subagent 等内置能力逐步纳入标准 Plugin suite，保留统一 Job/Action 装配 |
| `tinysoul/agent/user/builder.py` | 仅负责 user profile 的 Context/TurnProfile，消费 generation contributions |
| `tinysoul/plugins/reflection/builder.py` | 仅负责 home/memory reflection profile，消费同一 generation owner 的不同 profile contribution |
| `tinysoul/agent/lifecycle/sources.py` | 直接接收 generation 级来源集合，不再从 profile declaration 汇总来源 |
| `tinysoul/agent/services.py` | 从当前 generation 的明确 SDK export 表构造服务 facade |
| `docs/design/agent.md` | 重写组装、generation、profile、Turn 和 SDK 入口语义 |
| `docs/design/context.md` / `loop.md` | 明确 Plugin contribution 与 Context/Turn kernel 的边界 |
| `docs/design/capabilities.md` | 说明 capability Plugin 与 Action/Job/Workspace owner 的关系 |

实现时优先复用现有 `PluginRegistry`、`TurnProfile`、`GenerationSources`、`ServiceRegistry` 和资源 scope；只有当前类型无法表达 generation/profile 分离时才新增类型，避免建设第二套注册框架。

## 11. 异常处理与失败边界

组合模型不改变现有三层失败语义，只明确失败发生的位置：

| 位置 | 失败示例 | 处理 |
|---|---|---|
| Composition build | 重复 Plugin id、静态依赖环、宿主配置类型错误 | `AgentCompositionError` 或既有配置错误，未创建运行资源 |
| Generation build | Plugin Engine 配置错误、缺少依赖、连接或资源初始化失败 | 所属 owner runtime bridge；逆序关闭已创建资源，Agent 保留有限启动失败 |
| Profile resolve | 服务 facade 冲突、Segment 路由冲突、Action catalog 不一致 | profile/generation 装配失败，不开始 Turn |
| Turn Phase/Action | 参数无效、工具失败、模型协议失败 | 现有 typed 局部结果和下一 Cycle 反馈 |
| Runtime/lease | 日切、取消、预算、世代切换 | 现有 Trap/Transfer/SDK stale 语义 |
| close/observation | 资源关闭或 sink 失败 | 有界 cleanup diagnostic，不覆盖已提交主结果 |

Plugin 不得用宽泛 `except Exception` 把 generation 构建错误伪装成模型可修正的 ActionResult，也不得吞掉取消和 RuntimeException。第三方 ACP/MCP 边界仍可封装供应商异常，但要在 capability owner 内转换为稳定失败或 runtime bridge。

## 12. 执行阶段

### P0：确认术语和边界

状态：`pending`。

核对本方案与 `AGENTS.md`、主计划、`docs/design/agent.md`、`context.md`、`loop.md`、`reflection.md` 和 `capabilities.md`。维护者确认以下决策：

- `AgentBuilder.build()` 产生 `AgentComposition`；
- `Agent.create(root, ...)` 创建默认运行 Agent，`Agent.from_composition` 创建显式组成的运行 Agent；
- Agent-level Plugin 与 profile-level ProfileContribution 分开；
- generation source/resource 不再由 profile declaration 承担；
- `Agent.assemble` 不作为主要公开 SDK 入口；
- Profile 仍由 User/Reflection 请求类型选择，而不是由 Plugin 临时切换。

### P1：先修复独立的 ACP 类型门禁

修复 review F2：

- `_Client` 对 ACP `Client` Protocol 的未支持文件、终端和 elicitation 方法提供明确的 method-not-found/拒绝处理；
- 测试 `LocalAgent` 对未支持 Agent Protocol 方法表达相同语义；
- 不添加第二套文件或终端能力，不用宽泛 cast 或 type ignore；
- 运行 ACP 聚焦、Fast、Full 和干净环境 typecheck。

F2 不依赖本方案的 Plugin API，但必须先恢复干净的类型门禁。

### P2：建立 Composition 模型

新增或整理最小的组合类型和测试：

- `AgentComposition`；
- `AgentPlugin` 及 generation build context；
- profile kind 和 profile contribution context；
- Plugin identity/dependency/重复 owner 校验；
- Builder 无运行副作用的构建测试。

这一阶段不迁移所有内置能力，只让现有默认装配可以被包装为一个明确的标准 Plugin suite。

### P3：分离 generation 与 profile 贡献

调整注册协议：

1. 将 RuntimeSource、day participant 和 generation close 责任移到 generation contribution；
2. 将 profile 的 services、segments、actions、events、preparation/completion 和 recorder 保留在 profile contribution；
3. 将 `ResolvedPlugins` 收口为单一 profile 的解析结果；
4. 让 User 与两类 Reflection 由同一 generation contributions 建立不同 profile surface；
5. 保证来源只启动一次，日切/reload/restart 只由 generation lifecycle 关闭和重建。

### P4：内置能力接入标准 Plugin suite

按真实所有权逐步迁移 Home、Memory、Session、Workspace、Execution、ACP、MCP、Reflection schedule 和 Workspace watcher。迁移顺序以减少并行实现为准：

1. 先迁移已有 `declare_home/declare_memory/declare_session/declare_workspace`；
2. 再迁移 execution、subagent、expand 的 Action/Job/connection contributions；
3. 最后迁移 Reflection 的 profile 专属写服务和 scheduler source。

每一步删除旧的特殊装配旁路，不保留同一能力的旧声明和新 Plugin 两套路径。

### P5：接入一个真实自定义 Plugin

实现一个最小但真实的宿主能力作为验收插件，例如“知识来源”：

- generation Engine 持有来源状态；
- User profile 提供一个 Background 或 Working Segment；
- 提供一个 Action；
- 环境事件更新 owner，下一批 Context 刷新；
- restart 关闭旧 Engine 并创建新实例；
- 旧 generation service 明确失效；
- 不修改 Kernel，不创建新调度器。

该插件的测试比抽象接口测试更重要，用来证明 Plugin 组合能够承载真实能力。

### P6：收口公开 SDK 和删除歧义入口

更新 SDK、CLI、Endpoint 和测试：

- 默认 `Agent.create` 使用标准 Plugin suite；
- 自定义宿主通过 `AgentBuilder.use` 组合；
- 现有 `Agent.assemble` 调用迁移到 Composition/内部 runtime factory；
- `AgentAssembly` 改为内部 runtime 命名或删除；
- SDK 只导出明确 facade，不导出完整可变 Plugin registry。

同步更新 Endpoint 文档；Endpoint 继续调用 Agent，不维护自己的 Plugin、profile 或 generation 状态。

### P7：文档、验证与归档

同步设计文档和 README 示例，至少包含：

- AgentComposition 与 Agent runtime 的区别；
- Plugin、GenerationContribution、ProfileContribution、TurnProfile 的关系；
- User/Reflection profile 选择和权限边界；
- 一个自定义 Plugin 的组装示例；
- restart/reload/stale service 行为。

验证顺序：

1. Plugin registry、Composition 和 profile resolver 聚焦测试；
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

1. 代码中可以清楚指出组成定义、generation、profile 和 Turn 的唯一 owner；
2. `AgentBuilder` 只构造 `AgentComposition`，不启动运行资源；
3. Agent runtime 从 composition 创建 generation，并在 restart/reload 时重新创建 Plugin generation 实例；
4. `PluginDeclaration`/`ProfileContribution` 不再承载 generation 级 source 生命周期；
5. User、Home Reflection、Memory Reflection 复用同一 generation owner，但使用独立 profile surface；
6. 一个自定义 Plugin 可以提供 Engine、Segment、Action 和事件刷新，不修改 Kernel；
7. 旧服务、旧 Segment 和旧 generation 资源在切换后失效或关闭；
8. 失败处理符合 Composition、Generation、Profile、Turn 四个边界和现有三层失败语义；
9. 不存在旧 Builder、assemble、PluginDeclaration 旁路与新 Plugin 体系并行维护的重复实现；
10. Full 测试和 typecheck 通过，且设计文档准确描述已落地能力。

## 15. 当前请求的确认点

本文件是新的执行计划和完整设计预览，当前保持 `pending`。实施前需要确认的核心产品取舍只有一项：是否采用“`AgentBuilder.build()` 产生不可变 `AgentComposition`，`Agent.create(root, ...)` 或 `Agent.from_composition()` 创建运行 Agent，Plugin 通过 generation/profile 两层贡献接入”的命名和生命周期模型。

确认后按 P1 → P7 顺序实施；若不同意某个名称，可以只调整公开名称，但不能重新合并 generation 与 profile 的所有权边界。
