# Agent SDK / Plugin 收口强化执行计划

状态：`done`（2026-09-23 已完成实施、文档同步与本地门禁核对）

提出日期：2026-09-23

审查依据：`docs/analysis/done/20260923-done-agent-sdk-plugin-complete-review-and-test-performance-6e06e07.md`

相关已完成计划：`docs/analysis/done/20260923-done-agent-harness-plugin-composition-refactor-plan.md`

代码基线：`6e06e077bb79b120c34451b2cd7e63a0f1b7bb1d`

本文是上一轮 Agent SDK / Plugin 重构完成后的收口强化计划。它不重新设计 Agent、Turn、Context、PluginGeneration 或 PluginProfileExtension，也不引入动态插件平台、任意核心能力裁剪、第二套调度器或新的配置治理框架。

## 1. 对最新 review 的判断

最新 review 的主结论准确：当前架构主线已经落地，剩余问题是组合契约、命名表达、直接验收和一个已定位的配置查询热点。四项补强的性质如下：

| 项目 | 判断 | 依据与影响 | 处理决定 |
|---|---|---|---|
| R1 配置范围 owner | 属实 | `PluginDefinitions` 只排除插件之间的 section 重叠；`AgentBuilder` 另行解释 `agent/action/loop/llm/context/infra/reflection`，因此插件可以声明 `loop` 并被接受 | 增加静态的 Harness 保留配置范围输入，与插件配置一起做相等及父子重叠检查 |
| R2 新插件验收证据 | 属实 | 当前宿主插件测试只验证一次 generation 的服务绑定和关闭，没有第二代、段、动作、事件及 Turn 收尾的直接证据 | 增加一个测试专用小插件的纵向路径，并补最小 generation/profile/resource 契约测试 |
| R3 SDK 命名与宿主边界 | 属实但不影响运行 | SDK 私有字段仍称 `_assembly`，运行对象有 `profile_services`，`AgentRuntime.services` 实际是宿主 EnvironmentService；`Agent.runtime` 和 Endpoint 访问运行对象是现有真实宿主接口 | 整理名称和说明，保留真实宿主访问，不用删除导出或万能代理制造新的边界 |
| R4 配置状态性能 | 属实 | `status()` 的每个 source 都重新计算 credential names，`_effective_fields()` 也再次计算；catalog match 对字段逐项匹配 | 在一次 `status()` 请求内共享 effective values 和 credential names；不做跨请求缓存，是否建立 catalog 索引留待复测 |

Review 中关于 Linux/Python 3.13 样本、JUnit 口径和 Full 慢点的描述可作为定位证据，但不能外推为所有机器的性能结论。测试分层、异步客户端和并行化建议应作为后续测量方向，不能替代已定位的正常逻辑优化，也不应为了缩短数字删除真实生命周期验收。

真实 provider、远程 MCP、真实 ACP 委派、Windows 实机和 Defuddle CLI 仍是独立环境验收，不由本计划伪装为本地门禁已完成。

## 2. 保持不变的整体语义

1. `AgentBuilder` 只收集静态组成定义；`AgentAssembly` 只保存可重建定义；`Agent.assemble` 物化 `AgentRuntime`；`AgentRuntime` 仍是当前根调度、输入/命令路由、配置控制和 generation handle 的运行容器。
2. Plugin 仍按 generation 持有 owner、来源、SDK export 和永久 close；profile 只贡献情景内服务、段、动作、事件、准备/完成和 Turn 资源。
3. User、Home Reflection、Memory Reflection 继续由固定宿主业务编排选择 `ProfileKind`；不把三种情景拆成并行调度器。
4. `Agent.services` 继续是宿主读取显式 SDK export 的公开门面；内部 profile registry 与 SDK service registry 继续分开。
5. 配置 reload 仍重新读取来源、构造候选、成功后切换 generation；不把 Assembly 首次解析结果当作跨 reload 的永久快照。
6. R4 只改变一次状态查询内的中间值复用；不引入 revision、全局失效缓存、CAS 或新的配置 owner。

## 3. R1：收口 Harness 配置范围

### 3.1 目标

把“哪些配置由 Harness 解释、哪些配置由 Plugin 拥有”变成组合定义的静态契约。插件不得声明 Harness 已拥有的 section，也不得声明其父级或子级；插件之间现有的重叠检查继续保留。`capabilities` 作为插件拥有的公共容器，继续由各 `capabilities.<domain>` 配置贡献分派，不把整个容器保留给 Harness。

### 3.2 设计

在 `PluginDefinitions` 增加显式的 `reserved_configuration_sections`（或确认后的等价名称）输入。Kernel 只执行通用路径重叠校验，不知道 Agent Harness 的具体 section；组合根传入当前实际由 Harness 解析的：

```text
config, agent, action, loop, llm, context, infra, reflection
```

校验规则：

- reserved 与插件 section 相等时拒绝；任一方是另一方的点号父级时也拒绝，例如 `loop` 与 `loop.extra`、`loop.extra` 与 `loop.extra.detail`。
- 插件之间现有的相等/父子重叠检查不改变。
- `capabilities.expand`、`capabilities.resource` 等插件 section 可以共存；插件声明 `capabilities` 整段时按父子重叠规则拒绝已有子配置 owner。
- 所有 section 先转换为非空 dotted identifier；错误在创建 generation 或解析配置前返回 `RegistrationError`。

`PluginConfiguration` 的 settings 类型同时作为 `ServiceRegistry` 身份使用。为避免两个配置 owner 在解析后才产生重复 facade，SPI 增加可读的 settings/facade 类型声明，并在 `PluginDefinitions` 中做唯一性检查。若实现确认现有 `PluginConfiguration` 的扩展形态不需要这一项，则至少保留 `ServiceRegistry(plugin_settings)` 的单一失败点和对应测试，不另建第二种配置身份。

`AgentBuilder._definitions` 集中提供 Harness 保留范围；`_compile_config_plan_values()` 的既有配置解析、候选验证、错误 bridge 和 reload 路径保持不变。配置错误仍由实际 owner 映射，不能因为注册顺序改变错误归属。

### 3.3 验收

- 一个声明 `loop` 的宿主插件在 `build()` 阶段被拒绝，且其 `build_generation` 未被调用。
- 声明 `loop.extra`、`reflection.extra`、`capabilities` 与现有 owner 的父子冲突均被拒绝。
- 声明独立 `probe` section 的插件可以正常 parse、build、reload；错误配置仍进入该插件自己的 failure bridge。
- 候选 generation 已创建但后续声明校验失败时，已注册的 `close` 会在资源 scope 关闭时执行。
- 重复 settings/facade 类型在静态组合阶段得到稳定 `RegistrationError`。

## 4. R2：补齐新增 Plugin SPI 的直接验收

### 4.1 测试专用 Probe Plugin

在现有 Agent composition 测试中建立一个最小测试专用插件，不将其变成生产能力或新的通用测试框架。它拥有：

- 一个独立配置 section 和 generation owner，记录每次 generation 创建、关闭及配置值；
- 一个 generation/day 约束的 SDK facade，调用时经过已有 `ServiceScope`；
- 一个只向 User profile 贡献的 Context segment；
- 一个使用现有 Action catalog 的 action executor 或 action hook；测试目录提供最小 action 描述，不在 Plugin SPI 里动态拼第二套 catalog；
- 一个订阅既有 `EnvironmentEvent` 的 profile event handler，把收到的事件写入 owner 的可观察状态；
- 一个可记录的 Turn resource，分别覆盖 `RELEASE` 和 `SYNCHRONIZE` 阶段。

插件只验证现有贡献协议，不实现知识库、文件系统或新的业务 owner。

### 4.2 公开宿主纵向路径

通过 `standard_agent(root).use(probe).build()` 和 `Agent.assemble()` 创建真实 Agent，验证：

1. `build()` 不创建 owner、source 或客户端；首次 materialize 创建一次 generation。
2. User profile 的 action catalog、segment 和 event subscription 都来自 Probe Plugin；发布环境事件后，下一次 Cycle/LLM view 能观察到 owner 更新的有限投影。
3. 一个真实 Turn 执行 probe action 并保留结构化结果；不直接调用 profile 私有 registry 代替公开路径。
4. 成功 reload 创建新的 probe owner；旧 SDK facade 在旧 generation lease 上返回既有 stale/unavailable 语义，新 facade 可用。
5. restart 关闭旧 runtime/generation、重建新 owner；旧命令、旧 service 和旧 profile 不被重新绑定。

Action 测试应复用现有 catalog/LLM fake 设施，只补一条代表性 action 数据流，不复制所有内置 action 的正常测试。

### 4.3 构建与资源契约

在现有 kernel registration 或 composition 测试中补最小矩阵：

- 缺失 build service、依赖环、重复 plugin identity、generation declaration 与 `provides` 不匹配；
- 失败发生在 generation 已返回之后时，候选 owner 的 close 被执行；
- profile service、segment、trap 的身份冲突、服务依赖缺失和多个 completion recorder 在 activate 前拒绝；event、preparation/completion handlers 与 Turn resources 是有序贡献集合，没有额外身份或排他所有权，同一事件允许多个订阅共同处理；
- `PluginTurnResource` 的顺序可观察为 Jobs → `RELEASE` 资源 → `SYNCHRONIZE`/Workspace；必要完成失败影响主结果，附属 close 诊断不覆盖已提交事实。

不为每个字段建立一条测试；只保护 SPI 的失败边界和真实正常数据流。

### 4.4 日资源验证

复用已有本地 MCP/ACP fixtures 增加一个明确的 day release 切片：

- MCP `release_day()` 后旧连接/派生页被清除，下一次 discovery 能按配置身份惰性重建；
- ACP day release 后旧协议连接不可继续使用，新的 Turn 能建立新的协议 session；
- 既有跨 Turn ACP session 复用和同一 Turn Job 收尾测试继续保留，不与 day release 语义混淆。

## 5. R3：统一 SDK、Runtime 和宿主命名

### 5.1 推荐命名调整

只清理同一职责的内部名称，不做盲目全仓字符串替换，也不改 `ReflectionAssembly` 等已有明确含义的对象：

| 当前 | 调整后 | 语义 |
|---|---|---|
| `Agent._assembly` | `Agent._runtime` | 当前物化运行对象 |
| `_running_assembly()` | `_running_runtime()` | 获取当前运行对象的内部 helper |
| SDK/Endpoint 局部 `assembly`（类型为 `AgentRuntime`） | `runtime` | 运行对象变量/参数 |
| `AgentRuntime.profile_services` | `AgentRuntime.sdk_services` | generation/day lease 下的显式 SDK facade registry |
| `AgentRuntime.services` | `AgentRuntime.host_services` | Endpoint、Console 等 EnvironmentService 挂载集合 |

`Agent.services` 公开名称保留，文档改为“当前运行世代显式导出的 SDK services”，不再称为 User profile services。`TurnProfile.services` 保留原名，因为它确实是单个情景的 profile registry。

`Agent.runtime`、`AgentRuntime` 顶层导出和 Endpoint 的 runtime 绑定保留：它们有现有 CLI/Endpoint 消费者，属于内部宿主集成接口。文档明确持有者必须在 restart 后重新绑定/获取；常规业务通过 Agent、句柄、SDK services 和 Observation 协作。此次不删除 `__all__` 名称，不增加万能代理，也不保留旧私有名称 alias。

`mount_service()` 是否改为 `mount_host_service()`是低价值命名选择。默认只将字段改为 `host_services`，保留方法名以减少非必要 API 扩散；若实现时发现调用语义仍有歧义，再单独确认。

### 5.2 同步范围

- `tinysoul/agent/sdk.py`、`tinysoul/agent/composition/assembly.py`、`tinysoul/gateway/endpoint/host.py`、`tinysoul/gateway/cli.py` 及对应测试变量/注释；
- `docs/design/agent.md`、`docs/design/runtime.md` 和必要的 `AGENTS.md` 术语；
- 在已完成计划末尾增加收口说明，说明原计划实现已完成，本计划只补命名和直接验收证据，不改写历史范围。

验证不改变 Endpoint HTTP schema、Agent 状态机、restart/reload 时序或服务 lease 语义。

## 6. R4：优化配置 status 的请求内重复扫描

### 6.1 实施

修改 `tinysoul/infra/config/editing/controller.py`：

1. `status()` 只取得一次 `effective_values()`。
2. 基于这份值只计算一次 credential names。
3. 将 effective values 与 credential names 显式传给 `_effective_fields()`、`_source_json()` 和 `_source_values()`；这些 helper 不再隐式重新扫描整个环境。
4. 单次请求结束即丢弃中间值；`patch()`、`reload()`、环境变量别名、dotenv spelling 和多 descriptor 命中错误语义保持不变。

先不修改 `ConfigCatalog.match()` 的匹配算法。只有同机复测证明请求内共享仍不足，才另行评估不可变 catalog 的预拆 pattern；不得改成首个匹配成功，不能引入跨请求失效缓存。

### 6.2 验收

- status 返回的 sources、脱敏 fields、source id、writable 和 credential alias 与修改前结构一致；
- patch 或 reload 后下一次 status 立即反映新的 credential 引用和 effective source；
- dotenv、environment、override 三类 source 的脱敏和别名测试通过；
- 在相同 Python、依赖和测试选择集下，记录原实现与优化后的 status 中位耗时；性能记录只作为证据，不把任意毫秒数写成稳定协议。

## 7. 测试分层与执行顺序

测试组织遵循 AGENTS.md：

1. 先运行 R1 配置注册、R3 命名影响范围和 R4 ConfigController 聚焦测试。
2. 再运行 Probe Plugin composition、PluginDefinitions、Turn resource、MCP/ACP day release 聚焦测试。
3. 根据同一机器的 `--durations` 结果判断是否需要拆分少量重复的跨层测试；不为了耗时删除 Endpoint、reload、restart、日切、wheel 或真实本地协议验收。
4. 不共享可变 AgentRuntime、Context、Session 或活动目录来省时；不直接启用 xdist，除非另有隔离实验和稳定收益证据。
5. 最终运行：

```powershell
.\scripts\test.ps1 -Suite Full
.\scripts\typecheck.ps1
```

Full 包含 Fast、generation 和 release 本地验收；不在同一代码状态下机械重复整套 Fast。External 仍需显式开关和凭据，不能作为本地完成条件。

## 8. 文档、完成条件与交付

实施完成前逐项核对：

- R1 的 Harness/plugin 配置范围、settings owner 和失败回收已有代码与测试证据；
- R2 的 Probe Plugin 经过公开 `AgentBuilder`/`Agent.assemble` 真实 Turn、reload/restart、事件、动作和资源顺序验证；
- R3 的名称、宿主边界和设计文档一致，无旧私有命名或含义模糊的兼容 alias；
- R4 的 status 请求内复用已保持行为等价，并有同机基准前后数据；
- 设计文档、测试和本计划已同步；Full/typecheck 通过；没有把 external 能力写成已验证。

本计划已在实现、文档和验证逐项完成后标记为 `done`，文件已加入 `-done-` 并移至 `docs/analysis/done/`。未完成或需要产品决策的条目应继续保留在 `docs/analysis/`。

## 9. 已确认的决策

2026-09-23 维护者确认按此实施，采用以下选择：

1. 使用 `reserved_configuration_sections` 作为 Kernel 通用 SPI 参数名，由 AgentBuilder 传入 Harness sections；`capabilities.<domain>` 仍由插件拥有。
2. 将 `AgentRuntime.profile_services` 改为 `sdk_services`，运行对象的 `services` 字段改为 `host_services`；保留 `Agent.services`、`Agent.runtime` 和 `mount_service()`。
3. 用一个测试专用 Probe Plugin 覆盖 segment/action/event/config/SDK/resource 的纵向路径，不把它升级为生产插件或新的测试框架。
4. R4 只实施请求内共享计算；catalog 索引、xdist 和大范围测试重排均以复测证据为前提。

这些选择已按原有 Agent/Plugin 所有权和生命周期落地，没有新增设计语义决策。第 4.3 节的验收措辞按真实协议明确区分身份排重与有序贡献，未为事件或 handler 增加不存在的排重约束。

## 10. 实施核对记录

2026-09-23 完成以下核对：

- R1 已在 `kernel/registration.py` 与 `agent/composition/builder.py` 实现 Harness 保留配置范围、插件范围父子冲突和 settings facade 唯一性校验；`tests/kernel/test_registration.py` 与 `tests/agent/composition/test_builder.py` 覆盖冲突拒绝、独立配置解析、候选声明失败回收和 owner bridge。
- R2 已由 `tests/agent/composition/test_builder.py` 的 Probe Plugin 通过公开 `standard_agent().use().build()`、`Agent.assemble()` 验证配置、generation owner、User segment、action hook、事件、SDK facade、reload/restart 与 Turn 收尾；`test_assembly.py` 覆盖 Jobs → RELEASE → SYNCHRONIZE 顺序；Expand/ACP 测试覆盖日资源释放后的重新发现与重建。
- R3 已同步 `agent/sdk.py`、`agent/composition/assembly.py`、Endpoint host 及 `docs/design/agent.md`、`runtime.md`；旧运行对象私有名称和 `profile_services` 残留已清理，`Agent.services`、`Agent.runtime` 与 `mount_service()` 的既有宿主接口保持不变。
- R4 已将 `ConfigController.status()` 改为请求内共享 effective values 与 credential names，行为等价测试和 patch/reload 后即时生效测试通过。此前同机实验显示 status 中位耗时由约 1.05 秒降至约 0.045 秒；该数据仅作为性能证据，不构成协议阈值。
- `powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\\scripts\\test.ps1 -Suite Full -Durations 30` 通过：`1170 passed, 23 deselected`，耗时 179.19 秒；`TINYSOUL_PYTHON=C:\\Anaconda3\\envs\\TinySoul\\python.exe` 下运行 `typecheck.ps1` 通过。未运行真实 provider/network，因此不对 External 能力作本地完成声明。

本计划已按规约移至 `docs/analysis/done/`；后续若有新问题，应建立新的分析项，不在本计划上追加未相关的架构范围。
