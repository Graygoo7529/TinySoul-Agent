# Agent Harness 与 Plugin 组装重构方案

状态：`done`（2026-09-23；实现、设计同步与完整本地门禁已逐项核对）

提出／修订日期：2026-09-22

修订标识：**自宿主显式组合确认稿，含配置、恢复处理、Turn 收尾与 Reflection 装配契约**。

代码分析基线：`e2625da8c02309c60cd79ada3d34fad973ab089d`。本文保留基线问题说明；实施状态和验证证据以本文件末尾为准。

关联审查：`docs/analysis/20260922-agent-refactor-completion-review-e2625da.md`。

关联主计划：`docs/analysis/done/20260915-done-agent-architecture-refactor-plan.md`。

本稿整体替换此前同名方案，保留已确认命名并统一后续语义。旧版的任意核心插件裁剪、Runtime 跨 restart 保留、先关闭旧 generation 再 reload，以及必须新增知识插件等表述，不再作为执行要求。

## 1. 重构目标与确认边界

TinySoul 的主要宿主是自己的 Agent 与上层应用。SDK 与 Plugin 的灵活性服务于内部代码清晰、能力增强和长期迭代，不以第三方插件平台或任意精简 Agent 为目标。

标准 TinySoul 显式组装当前完整核心能力。Plugin 统一能力的创建、依赖、情景贡献和生命周期；新能力通过同一机制加入。当前不提供核心 Plugin 裁剪、运行时增删、自动发现、安装、版本治理或缺少核心能力时的降级机制。

本次必须做到：

1. 静态组成、运行容器、generation、profile 与 Turn 各有明确职责。
2. 内置能力与后续新增能力共用装配路径，不把原 Builder 包成一个巨型 Plugin。
3. 领域配置、服务、Action、Context、事件、恢复处理及必要收尾尽量内聚到所属 owner。
4. 保留唯一根队列、Turn/Cycle/Phase 内核、Context、Job 和三层失败语义。
5. 新增能力无需修改 Kernel 的领域分支，也无需在多个专用 Builder 中分别补特例。

已确认的实施取舍：

- 标准组成固定保留核心能力；显式组合用于扩展和内部演进，不实现拔除任意核心插件的产品能力。
- reload 保留候选准备、成功切换、失败保留旧世代的现有行为。
- restart 保留当前停止受理、结清请求、关闭并重建运行装配的行为，不改为复用旧根调度器。
- ContextEngine 继续作为 profile 的串行执行设施复用；每次 Turn 的段、Trace 和加载状态独立建立、释放。
- Reflection 保留请求解释、目标来源绑定和结果归纳等业务编排；领域能力贡献统一进入插件装配。
- Session 当日范围、Organize、统一 inspect、Reflection 写边界、Workspace/Memory 存储协议和受信主机假设不变。

本次是组成与所有权重构，不是再造推理内核。LLM、时钟、观察输出和宿主输入等基础依赖可以保持显式注入，不强制全部成为 Plugin。

## 2. 基线代码与需要迁移的真实接点

| 基线位置 | 当前职责／问题 | 本次处理 |
|---|---|---|
| `agent/composition/builder.py::_build_generation` | 集中创建 Home、Session、Memory、Workspace、执行能力、三情景和来源 | 分离组成定义、配置编译、插件实例化及情景解析 |
| `agent/composition/assembly.py::AgentAssembly` | 实际是根调度、命令、配置、来源和 generation handle 的运行容器 | 改名内部 AgentRuntime，原名用于静态定义 |
| `agent/sdk.py::Agent.assemble` | 接收异步运行装配工厂 | 改为接收静态 AgentAssembly |
| `agent/dispatch/scheduler.py::AgentGeneration` | 当前是只暴露 `user_turn`、`reflection`、`day` 的窄 Protocol | 改名为 `GenerationDispatchPort`，把 `AgentGeneration` 留给实际世代聚合对象 |
| `kernel/registration.py` | PluginDeclaration 混合 profile 贡献与 generation sources | 收口为 PluginProfileExtension；sources 上移 |
| `kernel/loop/assembly.py::TurnProfile` | 当前同时保存 Profile 执行面和 `sources` 字段 | 保留 Profile 的执行能力与事件/完成管线；移除 generation 级来源字段，身份收口为 `ProfileKind` |
| `agent/composition/actions.py` | 创建共享 Jobs 和 execution/expand/subagent，集中贡献动作与连接段 | 保留共享设施；领域创建与贡献移入各插件 |
| `agent/user/runtime.py` | 手工绑定 Home runtime-copy Trap handler | Home 声明 owner 处理器，情景装配器统一安装 |
| `agent/composition/activity.py` | Jobs 收敛 → ACP close_turn → Workspace reconcile/flush | 保留执行顺序，改为消费明确的 owner 贡献 |
| `plugins/reflection/builder.py`、`actions.py` | 准备来源对象，手工追加专属写动作，再组装 Reflection 执行器 | 来源策略保留；写能力归回 Home/Memory 的扩展 |
| `plugins/reflection/memory/context.py`、`task.py` | 固定目标日来源的 bind/clear 和写会话开始／完成 | 保留业务所有权，明确先后装配顺序 |
| `agent/lifecycle/day.py` | 停来源、关闭旧日执行资源、确定性归档、恢复来源 | 保留协调者；区分日资源释放与永久 close |
| `agent/services.py::registry` | 固定四类 SDK facade 的 lease 绑定 | 消费显式 SDK export 声明，保持权限边界 |
| `_compile_config_plan_values`、`_validate_config_candidate` | 集中列 section、解析配置、校验动作及外部绑定 | owner 提供纯解析／校验，初始构建与 reload 共用 |

这些接点共同决定范围。仅重命名 Builder/Declaration 或开放 `.use()`，不能算本方案完成。

## 3. 对象模型与公开使用方式

### 3.1 名称与职责

| 对象 | 含义 | 生命周期 |
|---|---|---|
| AgentBuilder | 收集组成定义，检查静态身份与依赖 | 宿主构建期间 |
| AgentAssembly | 不可变组成定义：配置来源、宿主绑定、插件定义和标准情景策略 | 可用于创建／重建 Agent |
| Agent | 宿主使用的 SDK 门面 | start/restart/shutdown 的稳定调用对象 |
| AgentRuntime | 内部运行容器：根调度器、命令／输入路由、配置控制、generation handle | reload 保留；restart 重建 |
| AgentGeneration | 一份有效配置及插件运行实例、已解析 profiles 的集合 | reload 或 restart 替换 |
| AgentPlugin | 能力定义、构建依赖和配置契约 | 随 Assembly 保存，无活动 Engine |
| PluginGeneration | 单插件在某代中的 owner、资源和扩展生产者 | 每个插件每 generation 一个 |
| PluginProfileExtension | 单插件面向一个情景的局部贡献声明 | profile 装配期间形成 |
| TurnProfile | 策略与多插件扩展汇集后的可执行情景，身份使用 `ProfileKind` | generation 内串行复用 |
| Turn | 使用一个 profile 的一次执行 | 初始输入至必要收尾完成 |

PluginGeneration 不拥有独立世代编号或重启器；AgentGeneration 不复制领域事实。静态定义可复用，不等于活动 Engine 或连接可以跨 generation 复用。

### 3.2 默认组成与 SDK

标准组成在一个可定位的函数中显式列出完整内置 Plugin。函数只形成配方，不运行旧 Builder。具体函数名在实施时落定，使用语义如下：

```python
assembly = (
    standard_agent(project_root)  # 返回含显式标准组成的 AgentBuilder
    .use(MyKnowledgePlugin(...))
    .with_input_source(source)
    .build()
)
agent = await Agent.assemble(assembly)
await agent.start()
```

- `build()` 同步产生定义，不创建 Engine、网络客户端、watcher、根队列或 Turn。
- Builder 不隐藏第二份默认插件集合；标准组成函数是默认集合的唯一声明位置。
- `Agent.assemble(assembly)` 异步创建运行容器和初始 generation，不启动来源或受理根请求。
- `start()` 完成日准备和来源激活后受理 work。
- 保留 `Agent.create(root, ...)` 供当前简单入口使用，但仅委托标准组成和 `Agent.assemble`；不维护第二套工厂协议。
- 普通 SDK 使用者无需操作 AgentRuntime、generation handle、Kernel frame 或可变注册表。
- 相同插件身份或同一服务所有者重复时装配报错，不按注册顺序覆盖。不新增替换管理 API；内部替换通过修改显式标准组成及其依赖完成。

### 3.3 状态与视图

TurnProfile 持有的 ContextEngine/ActionEngine 是可串行复用执行设施，不宣称它们都是纯不可变配置。ContextEngine 在 begin/open/end/close 边界管理本轮 Trace、段和加载集合；不得在下一轮看到上一轮的可变视图。

本次不新增“每 Turn 重建整个 Profile/ContextEngine”流程，也不支持同一个 profile 上的并发根 Turn。未来如有并发需求，应单独设计执行状态隔离。

现有 `RootScheduler` 中名为 `AgentGeneration` 的窄 Protocol 不是世代 owner。迁移时必须将其收口为 `GenerationDispatchPort`（或同等明确的窄名称），并让 `RuntimeHandle` 的实际泛型对象使用 `AgentGeneration`。不得保留两个同名类型或用兼容别名掩盖两种职责。

## 4. 契约归属与依赖方向

保持 `infra → runtime/llm → kernel → plugins/environment → agent → gateway` 的依赖方向。

`AgentPlugin` 的名称不决定它必须位于 `agent` 包。Plugin 实现不能为了实现 SPI 反向导入 AgentBuilder、AgentRuntime 或 agent 内部构建类。

本次落点原则：

- profile 贡献、解析和共享构建协议优先整理在现有 `kernel/registration.py`；实际解析器只消费通用协议，不解释 Home/Memory/Reflection 内容。
- 如该文件因职责确需拆分，只按“generation 契约／profile 贡献解析”分开，不平行保留旧注册系统。
- AgentBuilder、AgentAssembly、AgentRuntime、generation 构建器和具体 build-context 实现属于 agent。
- Plugin 实现、领域配置解析、owner facade、声明门面属于 plugins 的各 owner 包。
- 日历、配置来源、资源 scope、ServiceScope 等继续属于原有基础设施，不私有化到新插件。
- 通用 SPI 传递中性的 `ProfileKind`；它在 kernel 可依赖的中性位置使用 `StrEnum` 声明稳定的 `USER`、`HOME_REFLECTION` 和 `MEMORY_REFLECTION` 身份。固定身份的策略和领域语义由上层组合与插件共享约定维护，Kernel 不按情景名称分支，不形成 plugins→agent 导入。

第一批架构测试必须覆盖这些新协议的导入方向，而不仅检查旧包。

## 5. 两阶段装配与依赖解析

### 5.1 Generation 构建依赖

Plugin 定义声明稳定身份、所提供的构建期服务类型和所需的构建期服务类型。构建器在创建资源前检查重复 owner、缺失依赖与依赖环，并按依赖顺序创建实例。

构建期 facade 表达真实需要：Memory 所需的活动存储位置、执行能力所需的 Workspace 操作、共享 Job 监督等。若消费者目前需要 Engine 的多个内部能力，先整理窄协议；不要直接向所有插件提供整张 Engine 字典。

可复用现有排序和服务校验算法。此阶段的依赖用于创建 owner，不能被 profile 扩展上的 `requires` 替代。

### 5.2 Profile 使用依赖

创建完 owner 后，情景策略准备必要的来源接口，再让各 PluginGeneration 生成该情景的扩展。扩展中的 `requires` 检查情景最终是否获得必要服务。

`extend_profile` 不应依赖“另一个插件已先安装扩展”。跨插件的构建依赖已在 generation 阶段解决；profile 内部绑定若需要最终服务表，则通过声明的窄绑定入口在解析后取得，不提前访问未完成 registry。`ProfileBuildContext` 可以提供 Reflection 的请求来源绑定端口，但不直接承载或启动 `RuntimeSource`；来源实例和来源生命周期只属于 `PluginGeneration` 与 `GenerationSources`。

先收集声明，再完成服务、段路由、动作与 Trap 原因等校验，最后统一安装。注册回调只修改本次局部构建器，不能执行文件提交、启动来源或调用模型。若回调契约失败，丢弃该次候选装配，不建立复杂回滚系统。

### 5.3 方法语义预览

以下是职责预览，不是已经落地的字段清单。配置贡献、服务导出和可选生命周期贡献在后文定义：

```python
class AgentPlugin(Protocol):
    # 静态身份、构建期提供/依赖以及配置契约
    async def build_generation(self, context: GenerationBuildContext) -> PluginGeneration: ...

class PluginGeneration(Protocol):
    def extend_profile(
        self, profile: ProfileKind, context: ProfileBuildContext
    ) -> PluginProfileExtension | None: ...

    async def close(self) -> tuple[CleanupDiagnostic, ...]: ...
```

GenerationBuildContext 只提供已解析配置、已声明依赖及实际所需宿主端口。ProfileBuildContext 只提供由 `ProfileKind` 标识的情景允许的来源、策略和组装读取端口，不暴露完整 Agent，也不让插件自行向其它 profile 写入。

`PluginGeneration` 的来源、日边界资源、SDK export 和永久 close 必须通过明确的代级资源端口归属给它；Profile 的事件、Trap handler、Turn 收尾和其他局部能力通过 `PluginProfileExtension` 归属。实现可以复用 `GenerationSources`、现有 day coordinator 和 `ServiceScope`，但不能只保留一个 `close()` 方法而把这些资源重新散落回 Builder。具体 SPI 仅加入当前有真实消费者的资源端口。

返回 `None` 仅表示某能力不参与某个情景，不表示标准 Agent 可以缺少核心 owner。`ProfileKind` 的转换在请求入口完成，插件 SPI 内不传播未经校验的场景字符串。无 I/O 的能力仍可产生轻量 PluginGeneration，但不为其制造空来源、空段或日切对象。

## 6. 配置、Action catalog 与宿主依赖

### 6.1 配置定义与有效快照

Assembly 保存配置来源、固定 overrides 和组成；generation 保存该次重新读取、校验后形成的有效配置。不得将初次 ConfigEnvironment 快照固定后用于所有 reload。

插件贡献自身配置范围和纯解析／校验函数，结果尽早转成 owner 的类型化 settings。组装层收集合法范围并执行校验；现有 ConfigController、TOML、候选保存和显式 reload 保持统一。

共享容器 section（例如 capabilities）由明确的公共解析入口分派各子配置，不允许多个插件重复认领整个 section。嵌入宿主可显式提供自有插件的类型化配置；只有需要项目配置管理时才贡献对应 section，不建设任意配置 UI 生成器。

初始装配、保存候选和 reload 使用同一配置契约；保存候选不创建运行资源。需要从运行实例导出的实际能力状态仍由实例报告，不把纯配置校验变成外部握手。

### 6.2 Action 定义与实现

沿用公共 Action catalog 与配置规则。PluginProfileExtension 注册执行实现、真实 grant 和情景内语义覆盖；visibility 只筛选已授予能力。

新增 Action 必须在现有 catalog 管线中有明确来源，校验参数 schema、执行器标识和情景支持。当前不增设动态拼接 schema 的第二套工具目录。新增仓库内置能力同步 package-owned assets、生成测试和使用文档；宿主额外能力使用同一 catalog 规则。

保留当前未知动作检查、候选 catalog 校验与 Home Skill mount 核对。Reflection 对 `core.answer` 的指导语覆盖由情景策略贡献，不复制另一套完成动作。

### 6.3 Owned 与 borrowed

静态 Assembly 可以保存宿主绑定定义，但必须区分：

- 框架工厂创建的客户端或服务归对应运行作用域关闭；generation 切换重新创建。
- 宿主明确借用的 LLM/clock/sink 等对象不被框架误关，复用责任属于宿主。
- 输入源按其进程级生命周期 start/stop；若不能重新启动，应使用明确工厂重建。
- 可变领域 Engine 通过 Plugin 工厂每代创建，不继续保留 `with_session_engine` 等平行注入旁路。

不可变 Assembly 表示组成关系不变，不保证其中借用对象本身不可变。避免为了所有对象建立复杂 scope 容器，复用已有资源管理设施。

## 7. Profile 贡献与恢复处理

PluginProfileExtension 承接当前声明中的 services、segments、actions、events、preparation/completion 和 recorder，并补齐已有真实消费者需要的恢复与 Turn 收尾贡献。

| 贡献 | 语义 | 禁止混淆 |
|---|---|---|
| 服务 | 情景实际可用的窄 facade | 不等于 SDK 自动公开 |
| Segment provider | 创建本 Turn 的视图 | 不存储第二份领域事实 |
| Action 注册 | 绑定现有 catalog 的执行实现 | 不启动执行或 Job |
| 事件订阅 | envelope 适配为 owner 更新 | 不直接修改已安装段 |
| preparation | Turn 准备时必要的确定性处理 | 不调用隐藏整理模型 |
| completion / recorder | 事实封存后的必要提交，Session recorder 最后 | 不代替 Job/协议资源收敛 |
| owner Trap handler | 对明确原因注册恢复处理器 | 不覆盖整个 Trap 或通用 fallback |
| Turn 资源收尾贡献 | Jobs 收敛后、事实封存前的 owner 处理 | 不等于 generation.close |

Trap 的预算、容量、结束和 fallback 规则由内核／情景策略提供；Home 插件贡献 `HOME_RUNTIME_COPY_REQUIRED` 等自身 handler。冲突原因在装配时拒绝，复用现有 TrapHandlerRegistry，不建设插件优先级覆盖链。

段继续采用 Background/Trace/Working、State/Heap/Stack/Map 及 INSPECT/QUERY/SELECT/RECLAIM。owner 提交事实后发 Signal，段 prepare/install 更新投影；render/seal 不 I/O。统一披露、inspect 消费保护和 Session 水位策略不改。

## 8. Reflection 的专门策略与无环装配

User、Home Reflection、Memory Reflection 仍是固定情景，由请求类型选择。Agent 不临时切换插件组成；普通 User 不获得持久 Memory 或 actual Home 的专属写服务。

Reflection 保留：请求解释、目标日与来源日选择、活动／归档资料准备、来源 bind/clear、写入会话的业务开始／结束和结果归纳。它们属于业务语义，不能改成无序通用钩子。

各 owner 的职责如下：

- HomePlugin 对相应情景贡献 review 服务和动作，普通情景只操作 effective overlay。
- MemoryPlugin 对 Memory Reflection 贡献受约束持久写服务和动作；User 仍只有活动记忆操作及持久读取。
- SessionPlugin 提供 User recorder/Organize 与 Reflection 只读视图，不反向导入 Reflection。
- WorkspacePlugin 提供当前工作区能力，以及明确来源的只读归档视图。
- Reflection 策略提供目标来源接口、指导语、完成输出解释和独立根请求编排。

装配顺序固定为：

1. 创建基础 owner 和归档读取协作对象。
2. Reflection 策略创建尚未绑定具体请求的窄来源接口；这些接口不需要已经构建好的 Turn。
3. 情景构建端口将来源接口传给相关插件，各自生成扩展。
4. 解析扩展，构建 TurnProfile 和共享内核 runner。
5. 将已构建的执行入口交给 Reflection task/engine；scheduler 只持类型化提交端口。
6. 执行一次请求时准备并绑定来源，再运行 Turn；必要收尾后解除绑定。

这避免 ReflectionGeneration 与 TurnProfile 相互要求对方先构建。来源接口在代内可复用，但每次请求绑定独立，不能泄漏上一目标日内容。现有 MemoryReflectionContext 可以作为迁移基础，不新建平行来源存储。

## 9. 资源生命周期和正常收尾顺序

### 9.1 Generation 资源与来源

每个插件每代创建一个 PluginGeneration，三个 profile 不重复创建 Engine、连接和来源。来源从插件实例汇集到 GenerationSources，不再从 TurnProfile 去重推导。

GenerationSources 负责统一启动、暂停与 join 来源；插件负责自身资源最终释放。资源具有唯一所有者：外层注册插件的 close，不同时重复注册同一底层连接的 close。构建未成功返回前，插件负责回收其已创建资源；成功返回后，generation 将插件纳入已有 scope。

外部 ACP/MCP 连接仍按实际使用惰性建立，不因 build_generation 而强制连接所有服务。创建运行实例与启动来源是不同步骤。

### 9.2 Turn 收尾

保留当前 AgentTurnActivity 的执行位置和顺序：

1. 关闭本 Turn 新业务受理，收敛当前 Action。
2. 共享 JobRegistry 收敛本 Turn 的所有 Job。
3. 执行插件必要的 Turn 资源收尾，例如 ACP 释放该轮协议 session，按既定策略保留空闲传输连接。
4. Workspace reconcile／flush，消费必要终态与刷新，取得真实结束事实。
5. seal Context，执行必要 completion，Session recorder 最后保存。
6. 关闭 Segment 并释放 Turn/day lease，发布终态。

Turn 收尾贡献由 profile 装配器交给既有活动控制器，不新增另一套完成事件总线。Job 监督仍是一个共享设施；ACP、进程执行均不自建 Job 表。插件实例可跨 Turn，Job 不可跨所属 Turn。

必要资源未收敛与附属清理诊断必须区分。不能将进程仍在写旧工作区等情况一律降为无害 close warning。

### 9.3 日切

保留 AgentDayCoordinator 和 Archive 的确定性协调。Session／Workspace／活动 Memory 的归档顺序继续由现有 owner 协议保证，不变成任意插件自行归档。

来源 pause/join → 释放绑定旧日的执行／连接资源 → owner 归档并建立新日 → 恢复来源绑定。

仅为已有真实消费者提供日边界资源释放贡献，不要求每个插件都有空 DayParticipant。该操作释放旧日绑定，插件实例仍可用于新日；它必须与永久 `close()` 分义。当前 `CommonActionAssembly.close` 同时服务日切和代关闭的用法需在迁移中消除。

### 9.4 reload

继续使用现有候选语义：空闲边界取得激活权 → 重新解析配置 → 创建候选 generation → 暂停旧来源并完成切换准备 → 激活候选并切换 handle → 回收旧代。

准备失败关闭候选并保留旧世代；激活失败沿现有 abort/resume 规则处理。不承诺构建阶段所有 owner 文件操作跨模块事务回滚，也不引入新补偿框架。重点是不提前永久关闭可继续服务的旧实例。

### 9.5 restart 与 shutdown

restart 保留现有 SDK 行为：停止受理 → 结清活动和排队请求 → 关闭旧运行装配 → 按相同 Assembly、重新读取配置创建新 AgentRuntime／AgentGeneration → start。

Agent SDK 对象与已有 wait_for_exit 契约继续有效；旧请求句柄保存旧结果，旧 commands/services 不重新绑定。Gateway 的进程宿主和观察缓冲按现有边界维护，不把 HTTP server 塞进插件 generation。

shutdown 不重建，完成既有必要收尾后关闭运行资源。reload 与 restart 不能共用“先关闭旧代再创建”的错误简图。

## 10. SDK 服务导出

插件的内部构建服务、profile 服务和 SDK facade 是用途不同的接口，可能引用同一 owner，但不自动互相公开。

插件实例显式贡献实际有上层消费者的 SDK facade 绑定。Agent 的 ServiceScope 继续提供 generation/day lease；插件使用该 scope 创建自身 facade，Agent 不通过类型分支访问每个 owner 的私有 `_bind`。

首批必须迁移现有四个 SDK 服务：Home 绑定 generation；Memory、Session、Workspace 绑定 generation/day。成功 reload、restart 或日切使相应旧 facade 失效；失败 reload 保留旧 facade。SDK Session 仍只读，不导出 SessionOrganizeService 或 Reflection 专属写服务。

新服务复用现有 registry、lease 和错误类型，不增加万能代理、任意方法转发或按反射导出全部服务。Endpoint 仅消费 Agent 的正式接口；内部类型改名不意味着必须修改 HTTP 协议，只有实际协议变化才同步对应 endpoint 文档。

## 11. 失败语义

| 阶段 | 分类与处理 |
|---|---|
| 静态 Assembly | 重复身份、缺失依赖、依赖环属于有限装配错误；未创建运行资源 |
| 配置编译 | owner 类型化配置错误沿现有 ConfigError 路径；候选保存不执行能力 |
| Generation／profile 构建 | owner 经现有 bridge 或装配边界报告启动失败，回收候选资源；不伪造 ActionResult |
| Turn 内模型／Action 协议 | 可修正问题为局部结果，反馈下一 Cycle |
| owner 不变量／存储失败 | 所属 bridge 映射 Runtime 语义；不混同用户参数错误 |
| 控制转移 | 既有 Trap、SUSPEND、取消和 frame 语义 |
| 必要收尾 | 失败影响主结果或阻止不安全日切，保留真实事实 |
| 附属 close／Observation | 有界诊断，不覆盖已提交主结果 |

先检查现有 AgentError、RegistrationError 与 owner failures 能否表达，不为 Assembly/Plugin/Profile 每层机械增加异常树。第三方 ACP/MCP 异常仍在适配边界封装，不把宽泛捕获蔓延到通用业务层。

## 12. 代码迁移边界

| 位置 | 目标 |
|---|---|
| `agent/composition/builder.py` | 公开 Builder 收集定义；内部 generation 构建消费插件与配置契约 |
| `agent/composition/assembly.py` | 静态 AgentAssembly；现运行容器改为内部 AgentRuntime 并放入职责相符位置 |
| `agent/sdk.py` | assemble 接静态定义，create 仅委托；保留生命周期可观察行为 |
| `agent/lifecycle/generation.py` | AgentGeneration 管理插件实例、profiles、来源及资源作用域；与 `GenerationDispatchPort` 分离 |
| `agent/dispatch/scheduler.py` | 将窄的 AgentGeneration Protocol 改名为 `GenerationDispatchPort`，保持 RootScheduler 只依赖 user/reflection/day |
| `kernel/registration.py` | 复用声明校验，收口 PluginProfileExtension／ResolvedProfileExtensions；提供必要下层 SPI |
| `kernel/loop/assembly.py` | 从 TurnProfile 移除 generation 级 `sources`，保留 Profile 的执行 surface 与 `ProfileKind` 身份 |
| `plugins/*/plugin.py` 或已有 owner 门面 | 配置、实例创建、依赖、情景贡献、资源释放与 SDK export 的单一入口 |
| `agent/composition/actions.py` | 剥离领域特例，只保留必要共享内核装配；没有剩余职责时删除 |
| `agent/user/builder.py`、`plugins/reflection/builder.py` | 保留各情景策略和必要业务来源协作，消费统一扩展；不手工重复追加 owner 能力 |
| `agent/user/runtime.py`、Reflection Trap 构建 | 通用规则与 owner handler 分开汇集 |
| `agent/composition/activity.py` | 原位置执行共享 Job 和插件 Turn 收尾，无第二套状态机 |
| `agent/lifecycle/day.py`、`sources.py` | 直接消费代级来源和明确的日资源贡献 |
| `agent/services.py` | 消费显式 facade export，统一 lease，无全量自动导出 |

旧名称一次迁移消费者，不保留兼容 alias。分批开发可以尚未完成，但每个可验收切片应有一条可运行主线；不能把默认装配包装成超级 Plugin 后宣布迁移完成。

## 13. 执行阶段

### P0：设计确认与基线核对

状态：`done`（仅设计确认）。

命名、固定核心组成、显式扩展、restart/reload 区分、ContextEngine 复用和 Reflection 业务策略均已确认。实施启动时核对实际 HEAD 与本文基线差异；若相关修复已存在，记录证据并跳过重复修改。

### P1：ACP 独立类型门禁

状态：`done`。

核对 `_Client` 和测试 LocalAgent 对锁定 ACP Protocol 的实现。沿依赖实际方法契约为未支持能力提供最小明确处理；不能将所有通知和请求统一抛错，也不能假返回成功。保持已声明能力与实际支持一致，不实现第二套文件／终端系统，不以宽泛 cast/type ignore 遮蔽类型问题。

运行 ACP 聚焦、必要业务测试及类型检查，记录 Python／ACP／ty 版本。该项独立于 Plugin API，不将类型修复混入架构效果声明。

### P2：静态组成、配置与运行入口

状态：`done`。

同步迁移 AgentAssembly／AgentRuntime、AgentBuilder.build 和 Agent.assemble 的调用方；建立显式标准配方及下层共享 SPI。配置来源和有效快照分离，宿主 owned/borrowed 边界明确。保持 create 为薄入口。

校验依赖与身份；建立 generation 构建与 profile 解析两个阶段。迁移必要 SDK/Gateway 消费者，不能留下同名两义的 Assembly 或 `AgentGeneration`。现有能力迁移期间只保留唯一有效注册路径，包装旧 Builder 的 suite 不作为本阶段验收产物。与此同时确定标准核心 owner 的基线校验位置，并将 `TurnProfile` 的字符串身份收口为 `ProfileKind`，字符串只在 Gateway/Observation 等边界转换；User/Reflection builder 不再从 Profile declaration 汇总 `sources`。

### P3：Workspace 完整纵向接入

状态：`done`。

以 Workspace 验证真实配置、owner 创建、SDK facade、段、动作、preparation、事件源、日绑定及关闭。来源从代级直接汇集；profile 不再声明 sources。验证标准 Agent 通过新入口运行，SDK 写入和 watcher 变化能刷新同一 Turn 的实际模型视图。

### P4：Home／Memory／Session 与 Reflection

状态：`done`。

迁移现有声明门面，落实 generation 依赖、Home Trap handler、Session recorder 和 Organize。Home/Memory 专属写动作归各自扩展；按第 8 节先来源接口、再 profile、后执行入口完成 Reflection 装配。

验证 User 写边界、目标日来源、来源解除绑定、三情景共享 owner，以及连续两次不同目标的 Reflection 不串来源。沿用 Session/Context 现有事实和披露测试，不复制平行测试或改写已确认业务规则。

### P5：execution／ACP／MCP 与统一资源边界

状态：`done`。

迁移能力实例、动作、连接段和配置校验，共用 JobRegistry。将 ACP close_turn 接入原活动控制器；区分日资源释放和永久 close。Reflection scheduler 作为代级来源，只通过请求提交端口工作，不持有第二根调度器。

删除 CommonActionAssembly 中对应特殊装配与重复释放路径。验证同连接多 Job、跨 Turn 新协议 session、日切关闭旧日连接、reload 候选和 restart 重建。

### P6：宿主组合、SDK 导出及剩余旁路清理

状态：`done`。

以小型宿主集成测试证明额外贡献能经公开 Builder 接入段、动作和事件；不为验收新增完整知识库产品。迁移四类正式 SDK facade 到 export 绑定，证明旧对象失效且内部写服务未泄露。

检查新增能力的配置/catalog/Skill mount 接入是否仍需要中央 owner 特判，清除重复工厂、旧声明、兼容 alias 和无消费者字段。保留标准组成的显式业务选择，不将它误判为应消除的领域依赖。

### P7：文档、门禁与归档

状态：`done`（AGENTS、agent/context/runtime 设计文档已同步；Full 与 typecheck 已通过；本文件随后归档）。

同步 AGENTS、README 及 agent/context/loop/capabilities/reflection 等受影响设计，提供标准构建和一个额外贡献示例。设计文档只描述实际落地能力；HTTP 协议有实际变化才更新 Endpoint 契约。

聚焦 → Fast → Full → typecheck。Full 已包含 generation/wheel，不机械重复；Linux/Windows 目标类型检查按已有门禁核验，不把目标检查当作另一平台实机测试。真实 provider/ACP 模型委派／远程 MCP 与本地夹具分开记录，未执行不得宣称通过。

只有实现、文档和必要验证逐项完成，才将本计划标为 done、文件加入 `-done-` 并移至 `docs/analysis/done/`。

## 14. 验收清单

以下条目按最终实现逐项核验；旧切片验证不作为完整计划的完成证据：

| 编号 | 完成条件 |
|---|---|
| A1 | `done`：标准核心组成唯一、显式；无核心插件裁剪与缺省空 owner 路径 |
| A2 | `done`：Builder.build 不创建 Engine/来源/客户端；assemble 准备、start 激活 |
| A3 | `done`：通用插件契约不导致 plugins→agent 或 kernel→plugins 导入；RootScheduler 依赖 `GenerationDispatchPort`，实际 `AgentGeneration` 只有一个 owner |
| A4 | `done`：generation 插件按 requires 拓扑构建并校验 identity/dependency；Profile 扩展仍在解析后统一安装且不拥有 RuntimeSource 生命周期 |
| A5 | `done`：每个插件每代一个 owner；三个 profile 不重复创建资源或来源 |
| A6 | `done`：配置通过统一解析／候选路径，reload 重新读取；宿主插件拥有独立配置贡献 SPI |
| A7 | `done`：Home 恢复 handler 经声明接入；预算/容量/结束仍由公共策略控制 |
| A8 | `done`：Jobs→插件 Turn 收尾→Workspace 同步→事实封存/completion 的顺序保持 |
| A9 | `done`：日资源释放与永久 close 分义；确定性归档仍由原协调者执行 |
| A10 | `done`：Reflection 来源准备保留业务语义，装配无环，连续目标无状态残留 |
| A11 | `done`：User 与 Reflection 权限正确；SessionOrganize 和持久写服务不自动暴露 SDK |
| A12 | `done`：ContextEngine 串行复用且视图每 Turn 独立；统一 inspect/Session 语义不回退 |
| A13 | `done`：reload 候选失败旧服务有效；restart 重建、旧句柄结果和 wait_for_exit 契约保持 |
| A14 | `done`：来源统一启动/停止一次；底层资源只有一个关闭 owner；借用宿主对象不误关 |
| A15 | `done`：宿主通过 `AgentBuilder.use()` 贡献一个 generation owner 和 User profile extension，不改 Kernel、不复制默认 Builder |
| A16 | `done`：代码无旧声明和兼容 alias，文档与最终 Full 门禁已收口 |

测试围绕真实数据流和可观察行为，不固定文件数、完整提示词文本或内部类数量。复用现有 SDK、Session、Reflection、ACP/MCP 与架构测试，只补新装配边界和已证明的缺口。

## 15. 本次修订与后续记录

2026-09-22 已确认：Plugin 用于内部清晰与迭代，不考虑移除核心能力；保留现有运行设施复用方式和 Reflection 专门策略。本文据此整体修订目标、协议、配置、生命周期、代码归属、执行顺序和验收，未保留相互冲突的旧建议。同步到当前分析计划时补充了 `ProfileKind` 的稳定类型约束，以及标准核心组成不得绕过基线校验的实现要求。

2026-09-23 复核与实施完成：此前 P1–P4 与部分验收项的完成标记偏早，旧切片仍保留中央能力装配、四类 SDK 服务特判及缺失的日资源释放。本轮已将内置 owner、配置贡献、SDK 导出、Reflection 专属能力、Trap/Turn 收尾与资源生命周期接入同一插件路径；`CommonActionAssembly` 已移除。宿主可通过 `standard_agent(...).use(plugin)` 接入 generation/profile/config/SDK export。ACP 未支持 request 以明确协议错误返回，通知不伪造响应。Expand 日切保留配置身份并清除旧日连接与派生目录，下一日按需重连。

最终验证（Conda `TinySoul` Python 3.13）：标准 `scripts/test.ps1 -Suite Full` 通过，`1150 passed, 23 deselected`；`scripts/typecheck.ps1` 通过；额外架构、注册、压力和插件聚焦测试通过。未运行真实 provider/network，因此不对外部服务可用性作结论。

基础设计方向没有新的阻塞确认项。P2 需要在实现前落实标准核心组成的基线校验位置，方法具体拼写、文件拆分和小型参数结构由实施按本文职责落定；如实际协议迫使改变所有权、可观察生命周期或业务写边界，应提出具体冲突再讨论，不用兼容旁路掩盖。

建议本次文档提交说明：

`docs: refine self-hosted plugin composition and lifecycle refactor plan`
