# Agent SDK / Plugin 完整实施 Review 与测试提速建议 — 6e06e07

审查日期：2026-09-23。本稿整合上一版实施审查、SDK 专项核查与本次测试耗时分析，作为新的完整交付稿；替代 `20260922-agent-plugin-implementation-review-6e06e07.md` 的阅读入口，旧稿保留作记录。代码基线不变，本次未重新拉取远端。

代码基线：`6e06e077bb79b120c34451b2cd7e63a0f1b7bb1d`，提交说明：`refactor(agent): compose generations and profiles through plugins`。

主要对照：`AGENTS.md`、`docs/analysis/done/20260923-done-agent-harness-plugin-composition-refactor-plan.md`；同时核对原架构主计划及当前 Context、Session 设计的关键延续边界。

本文状态：审查 `done`；以下补强项仍为 `pending`。仅新增审查文档，没有修改实现、测试或原计划的完成标记，没有提交或推送。

## 1. 判断

**架构主线已经落地，设计方向合理，可以作为后续能力扩展的基础；但“所有执行与验收条目均已完成”仍应保留条件。**

这次不是只开放 `.use()` 或把旧 Builder 包装成巨型 Plugin。Home、Memory、Session、Workspace、execution、ACP、MCP 等能力的 owner 创建、配置和 profile 贡献确实进入统一路径；SDK 服务导出、Home Trap 和 Turn 收尾也有真实消费者。未发现需要再次推翻整体架构的问题。

还需收口配置所有权、SDK 命名与宿主边界，并补足新增组合契约的直接验证。本次另定位到配置状态查询的重复扫描热点，可用请求内复用直接改善性能。两者都应沿现有设计完成，无需引入插件平台、任意核心裁剪、第二套调度器或复杂防御机制。

## 2. 已完成的关键设计

| 设计目标 | 实施证据与判断 |
|---|---|
| 自宿主显式组合 | `standard_agent()` 给出标准配方，`AgentBuilder.use()` 加入扩展；`PluginDefinitions` 检查并排序构建依赖。标准核心能力仍为必需，符合已确认边界。 |
| 静态组成与运行实例分离 | `build()` 同步返回 `AgentAssembly`，运行实例由异步 materialize 创建；旧运行容器已改名 `AgentRuntime`。Assembly 使用工厂闭包保存已捕获的组成，不是第二套运行容器。 |
| 两阶段依赖 | generation 构建期按 `provides/requires` 选择服务；profile 阶段汇集 `PluginProfileExtension`，统一校验服务、段和贡献后安装。 |
| owner 内聚 | 各 `plugins/*/plugin.py` 创建领域 owner、贡献配置、动作和语境；`CommonActionAssembly` 已移除，`ProfileAssembly` 保留统一装配职责。 |
| 来源归 generation | sources 从 `PluginGeneration` 汇集到 `GenerationSources`，不再从 profile 推导、去重或重复持有。 |
| SDK 显式导出 | `PluginServiceExport` 绑定 `ServiceScope`；Home 使用 generation 生命周期，Memory/Session/Workspace 使用 day 生命周期；没有自动公开内部写服务。 |
| Reflection 无环装配 | 先准备未绑定的来源接口，再构造扩展与 profile，最后创建 task；目标日、bind/clear、写会话和结果归纳仍由 Reflection 业务编排负责。 |
| Turn 收尾 | 共享 Jobs 收敛后执行插件资源释放，再由 `SYNCHRONIZE` 阶段同步 Workspace；其后仍沿原 Turn 完成边界提交事实，Session recorder 最后执行。 |
| 日切与永久关闭 | ACP/MCP 提供 `release_day`；日协调者直接调用贡献，仍使用既有确定性归档流程。没有引入通用事务式 DayParticipant 系统。 |
| reload/restart | reload 先构造候选，再切换并退役旧代；restart 重建 runtime。原服务失效、失败 reload 保留旧服务等已有 SDK 测试继续通过。 |
| Context/Session 延续 | profile 复用 ContextEngine，各 Turn 建立独立视图；统一 inspect、Session 当日语义地图、Organize 和分层披露设计继续存在，没有新增平行历史或第二套 Context。 |
| 依赖与异常边界 | SPI 位于 Kernel 可依赖层，领域插件不反向依赖 Agent；owner 保留自己的 bridge，Action 局部失败与 Runtime 控制异常未因插件装配合并。 |

保留固定的 User/Home Reflection/Memory Reflection 情景、日协调者和 Reflection 专门策略是合理的。它们是宿主业务编排，不要求为了“插件化”全部拆成可拔除模块。当前 `ProfileKind` 也不构成第二套调度逻辑。

## 3. R1：配置范围校验尚未覆盖 Harness 自有配置

状态：`pending`。优先级：中；属于组合契约的清晰性问题，未发现标准配方因此出现运行故障。

位置：

- `kernel/registration.py:259–263`：只检查插件之间的 section 重叠。
- `agent/composition/builder.py:689–725`：Harness 另外解释 `agent/action/loop/llm/context/infra/reflection` 等配置。
- `agent/composition/builder.py::_map_owned_config_error`：按插件 section 优先寻找错误归属。

**实际复现：**在完整标准配方上 `.use()` 一个声明 `PluginConfig("loop", int, lambda tree, root: 7, ...)` 的插件，配合有效项目配置和 FakeLLM，调用 `.build()` 成功；输出 `Accepted plugin claiming harness-owned loop: True`。

这说明同一份 `loop` 输入可以既归 Harness 又归新增插件解释。若发生配置错误，错误 owner 的选择也可能受新增插件影响。现有插件间排重并不能表达完整的“配置范围单一 owner”契约。

建议：把 Harness 已拥有的配置范围作为现有 `PluginDefinitions` 校验的显式输入，与插件范围一起检查相等、父子重叠。共享容器 `capabilities` 仍按已实现的子范围分派，不需要整段保留给 Harness。配置 settings 类型若也用于服务注册身份，可在同一装配检查中明确其唯一性。

不需要增加权限系统、配置治理框架或运行时恢复链；这是一次静态组成检查。验收应证明：`loop` 和 `loop.*` 冲突在插件构建前拒绝；独立扩展 section 正常加载，保存候选与 reload 仍使用同一解析器。

## 4. R2：新增插件契约的验收证据不足

状态：`pending`。优先级：中；这是验证缺口，不等于已证明存在生命周期运行错误。

`tests/agent/composition/test_builder.py:198–217` 的新增宿主插件测试只创建一次 runtime，读取 profile/SDK 中的同一个服务对象，然后关闭。虽然测试名包含 `built_per_generation`，但没有第二代；测试插件也没有贡献段、动作、事件、配置或真实的 scoped SDK 操作。

计划 P6 仍要求通过公开入口验证额外段、动作和事件，当前 A15 则写为 generation owner + profile extension，验收口径比 P6 窄。现有 `tests/kernel/test_registration.py` 的声明测试覆盖旧 profile 注册层，不能单独代替 generation 构建和公开 SDK 组合验证。

此外，当前测试源码没有直接使用新增的 `PluginDefinitions`、`PluginConfig`、`PluginTrapHandler`、`TurnResourceStage` 或 `release_day`。已有标准 Agent、SDK 重载和日切测试提供了广泛间接覆盖，但没有直接证明新贡献协议的关键顺序和扩展行为。

建议只补三个有实际区分能力的切片：

1. **构建契约**：覆盖缺失依赖、依赖环、配置归属冲突，以及声明不匹配时已返回候选资源被回收。不要重复全部旧 profile 注册测试。
2. **公开宿主纵向路径**：通过 `standard_agent().use()` 和 `Agent.assemble()`，让一个小插件的段、动作和事件进入真实 Turn；动作仍使用现有 catalog。reload 后验证 owner 是新实例、旧代关闭且旧 scoped facade 失效。可复用同一个小插件继续验证 restart，不新增知识库产品。
3. **资源顺序**：用可记录调用的 owner 或既有本地协议 fixture，证明 Jobs → 插件释放 → Workspace 同步 → 必要完成，以及日切 release 后同代能力仍能重新使用。至少对 MCP 已发现目录在 release 后重新发现、ACP 旧连接释放和新连接建立给出可观察证据。

这是验证正常功能主线与结束边界，不是增加罕见故障矩阵。完成后再逐项把 P5/P6/A15 的证据写回计划，避免仅用全量测试数字代替新契约验收。

## 5. R3：SDK 主体一致，命名和宿主公开边界需收口

状态：`pending`。优先级：中低。不是运行故障，也不需要重新设计 SDK。

### 5.1 名称与架构逐项核对

| 对象 | 已确认含义 | 当前情况 |
|---|---|---|
| AgentBuilder | 收集组成，静态检查，显式扩展 | 已实现 `.use()` 和同步 `.build()`，标准配方只在一个函数声明 |
| AgentAssembly | 静态组成，可用于创建/重建 | frozen dataclass 保存 root、plugin_ids、runtime_factory；闭包捕获配置来源和组成，未持有已创建 runtime |
| Agent | 稳定的 SDK 门面 | `create → standard_agent/build → assemble` 为同一路径 |
| AgentRuntime | 当前运行容器 | 根调度器、配置控制、来源、generation handle；restart 重建 |
| AgentGeneration | 当前配置下的领域实例与 profiles | reload 替换；不与调度窄协议混用 |
| GenerationDispatchPort | 根调度器所需的窄接口 | 原重名协议已改名 |
| AgentPlugin / PluginGeneration / PluginProfileExtension | 定义、代级 owner、情景贡献 | 已区分；三情景不分别创建领域 owner |
| TurnProfile / Turn | 可复用情景设施、单次执行 | Context 视图仍按 Turn 创建和释放 |

SDK 功能已经包括：start/restart/shutdown/wait_for_exit；User/Reflection 请求和 TurnHandle；追加输入、reply、cancel、grant_cycles；环境事件 publish；状态、Job 查询与停止；Observation 订阅；配置查看、patch/reload；显式导出的领域服务。暂停与回复仍走既有 Inbox 和内核运行语义，SDK 未再造暂停状态机。

不要求把所有 Plugin SPI 从 `tinysoul.agent` 顶层重新导出。SPI 定义保留在 Kernel 可依赖层符合依赖方向；宿主文档提供清晰导入示例即可。

### 5.2 旧 assembly 命名仍指运行对象

证据：`agent/sdk.py` 的 `_assembly: AgentRuntime`、`_running_assembly()`，以及 `gateway/endpoint/host.py` 的 `assembly: AgentRuntime` 参数和字段。

建议一次性改为 `_runtime`、`_running_runtime()`、`runtime`；静态 `AgentAssembly` 对象继续使用 assembly。更新同一对象的测试变量和注释，不进行整个仓库盲目字符串替换，也不改 ReflectionAssembly 等另有明确意义的类型。无需保留旧私有名称的兼容 alias。

### 5.3 SDK 服务仍被描述成 profile 服务

证据：`Agent.services` 的注释仍写“Current User profile's typed services”，它委托 `AgentRuntime.profile_services`；实际返回的是 `AgentRuntimeServices.registry` 汇集的 scoped SDK exports。

建议保留公开 `Agent.services`，将 runtime 的 `profile_services` 改为 `sdk_services`，同步说明其为插件显式导出、受 generation/day lease 约束的 facade 集合。不要修改真正的 `TurnProfile.services`，也不要把两个 registry 合并。

另外，`AgentRuntime.services` 目前表示 mounted EnvironmentService，和 SDK services 不是一回事。可将内部字段改为 `host_services`（保持 `mount_service` 的意图清楚），避免这次改名后仍出现三个不同含义的 services。该项只整理已有职责，不增加第三套服务框架。

### 5.4 AgentRuntime 的内部宿主访问约定

计划称其“内部运行容器”，实现却在 `agent/__init__.py` 导出该类型，并通过 `Agent.runtime` 暴露；CLI/Endpoint 当前确有绑定消费者。

推荐保留当前直接访问方式，明确它属于**内部宿主集成接口**：用于准备阶段的 Endpoint 挂载及 runtime 重建后的重新绑定；常规业务通过 Agent、请求/句柄、SDK services 和 Observation。持有 runtime 的宿主必须在 restart 后重新获取，不能假定旧对象随 Agent 自动更新。

不必为“隐藏内部”再造万能代理或强迫所有宿主连接成为 Plugin。若维护者希望严格缩减公开 surface，应另行迁移现有消费者再去掉导出，不能仅删除 `__all__` 名称就宣称已解耦。本 review 推荐的直接宿主访问约定属于待采用建议，不将其写为用户已确认的新规则。

验收：正常 SDK 示例无需操作 runtime；内部 Endpoint 示例清楚展示绑定与 restart 后重绑；旧 assembly/profile_services 误名清除；生命周期与 HTTP 行为不变。相关变化只影响 Python 命名/说明时，不需要变更 HTTP 协议。

## 6. 其他非阻塞清理

状态：`pending`，可与上述补强一起完成。

- `GenerationBuildContext` 的注释称只包含选中插件的配置，实际所有插件拿到完整 settings registry；构建服务则确实按 requires 筛选。建议先准确描述为“generation 的已解析 settings、插件声明的构建服务”，不为内部可信插件另造配置访问控制。
- Builder 和若干插件迁移后仍有不再使用的导入及较密集的长行，适当清理即可；不因文件较长机械拆分职责。
- `AgentAssembly` 的工厂闭包方案能完成当前固定组成的运行重建；只要没有真实的组成检查/序列化消费者，不必为了形式上的数据化再引入一层 DI 框架。

## 7. 独立验证

环境：Linux、Python 3.13.15，项目新建虚拟环境安装 `.[dev]` 与 pip；`ty 0.0.83`、ACP SDK `0.12.1`、MCP SDK `2.2.0`。使用仓库测试隔离机制，未使用真实模型或远端 ACP/MCP 服务。

- Full 对应本地选择集：`python -m pytest -q -m 'not external'`，退出码 0，**1144 passed、6 skipped**。包括项目生成与 wheel 验收；本环境以 Python 直接运行，未执行 Windows PowerShell/Conda 入口。
- 类型检查：`python -m ty check --python .venv/bin/python`，**All checks passed**。此前 ACP Protocol 不完整问题本次未再出现。
- 配置范围冲突：独立最小脚本复现标准 Builder 接受插件认领 `loop`，未修改仓库源码。
- 全量结果有一条 Starlette/AnyIO 弃用提示，没有测试失败。跳过项及外部服务验证不能计为已通过；仓库记录的 Windows 1150 passed 不由本次 Linux 运行代为认证。

以上为上一轮独立验证；本轮为定位用户反馈的耗时问题，重新运行一次带 durations/JUnit 的 Full，数据见第 8 节。未因文档修改再重复类型检查。所有测试通过证明当前已覆盖行为没有回归，不消除 R2 指出的缺少直接验收证据。

## 8. R4：测试耗时分析与改进方案

状态：`pending`。本轮已完成测量和热点定位，尚未实施优化。优先处理正常配置查询的重复计算，再调整测试覆盖层次。

### 8.1 本次实测

在同一代码、Linux/Python 3.13.15 环境，执行完整本地选择集，未并行运行其他测试：

```bash
python -m pytest -m 'not external' --durations=35 --durations-min=0.5 \
  -o 'addopts=--strict-markers --import-mode=importlib' -q \
  --junitxml=/tmp/tinysoul-review-timing.xml
```

结果：**1144 passed、6 skipped、23 deselected，110.82 秒**，一条 Starlette/AnyIO 弃用提示。命令保留项目要求的 importlib 模式；这里覆写 addopts 只为避免双重 quiet 隐藏汇总。

JUnit 的 testcase 时间包含 setup/call/teardown，合计约 106.70 秒，和 pytest 总时间口径不同：

| 范围 | 收集的本地用例数（含 skip） | 累计 testcase 时间 |
|---|---:|---:|
| tests/agent | 110 | 58.53 秒 |
| tests/plugins | 323 | 18.51 秒 |
| tests/release | 1 | 13.94 秒 |
| tests/gateway | 48 | 7.26 秒 |
| tests/test_architecture.py | 25 | 3.94 秒 |
| tests/infra | 105 | 2.14 秒 |
| tests/kernel | 305 | 1.63 秒 |
| tests/llm | 194 | 0.70 秒 |
| environment + runtime | 39 | 0.05 秒 |

最慢的十个 testcase 合计约 43.00 秒；大部分纯 Kernel/LLM 测试不是瓶颈。主要慢点的 call 时间如下：

| 测试 | 秒 |
|---|---:|
| release/test_wheel：构建、安装、资源与初始化验收 | 13.94 |
| composition/test_builder：config reload + event buffer | 5.07 |
| composition/test_builder：action activation policy | 4.83 |
| composition/test_builder：无凭据启动、配置与启用校验 | 4.16 |
| gateway/test_cli_fake_provider：HTTP restart failure | 3.14 |
| test_architecture：新进程导入全部包 | 2.86 |
| agent/test_sdk：Session Organize、restart、day switch | 2.25 |
| composition/test_builder：provider switch/rollback | 2.20 |
| composition/test_builder：Endpoint 挂载与激活 | 2.04 |
| subagent/test_engine：本地真实 ACP 权限与跨 Turn 隔离 | 1.75 |

这是一次本地样本，不代表 Windows 耗时或性能分位数，也不能解释所有“偶尔很慢”。若用户环境明显更慢，应在相同提交和已安装依赖条件下采集脚本 durations，并分别计时 pytest 与脚本最终目录清理；不要直接归因于磁盘、杀毒软件或网络。

### 8.2 已定位的正常功能热点：配置状态重复扫描

对最慢的配置重载测试进行一次独立 cProfile，记录约 38334 次 `ConfigCatalog.match` 和 8433480 次 `_matches_pattern`。剖析会显著放大 Python 高频调用成本，异步/线程累计时间也不宜直接相加，故不把剖析后的 29 秒当作实际测试基准。

代码能够直接解释重复来源：

- `infra/config/editing/controller.py::status` 遍历 sources，并计算 effective fields。
- 每个 `_source_values` 都重新调用 `_credential_names`；`_effective_fields` 又计算一次。
- `_credential_names` 每次遍历全部 effective values，逐键调用 catalog.match。
- `descriptors/models.py::match` 对全部 field descriptor 线性匹配；每次匹配又重新 split pattern/path。

为排除仅由 profiler 引起的错觉，另用初始化后的标准项目、`env={}`，对同一 ConfigController 做独立同步实验，各执行三次取中位数：

| 实验 | 单次 status 中位耗时 | 行为 |
|---|---:|---|
| 当前实现 | 1.0514 秒 | 每次 status 计算 credential names 28 次 |
| 临时实验：本次 status 共享一次计算结果 | 0.0446 秒 | 返回完整 status 与原结果相等 |

实验只在临时进程替换该对象的方法，没有改源码；优化计时包含首次计算 credential names。它证明重复扫描确有成本和简单改善空间，不证明所有配置状态都等价，也不承诺整个 Full 按同一比例加速。

**首选实施：**在一次 `status()` 调用内计算 effective values/credential names，显式传给已有投影辅助方法。请求结束即丢弃，不缓存跨 patch/reload 的状态，不增加 revision、失效管理或新的配置 owner。这样既改善测试，也直接改善真实配置接口。

必要验证：同一响应不同 sources 与 effective fields 的脱敏一致；patch/reload 改变凭据引用后新查询立即生效；环境变量别名规范化和公开字段输出保持原语义。绝不能靠跳过脱敏提速。

只有这一修改之后仍有显著匹配热点，才考虑在不可变 catalog 内预拆 pattern、按路径长度/首段缩小候选。必须保持“多 descriptor 命中即报错”的语义，不能改成首个匹配成功就返回。先不引入全局路径缓存。

### 8.3 测试组织：把语义组合留在 owner，把跨层验收留在少数代表用例

当前最慢几条测试把完整项目、三情景构建、Endpoint、配置编辑、reload 和多次状态查询组合起来；这些用例有实际价值，不应全部 mock 或删除。

建议逐项梳理：

1. 配置解析、覆盖优先级、catalog visibility 和非法值组合，在 Config/Action owner 层覆盖完整；Endpoint 保留 HTTP 映射和一条真实 reload/event 路径，不再次穷举相同语义。
2. SDK 保留 restart、旧 facade 失效、排队/Inbox、日切和 Reflection 来源等代表性真实路径。新增 R2 的插件纵向测试尽量复用同一个小插件验证相关边界，不给每种声明都创建完整 Agent。
3. 只有准备/关闭需要协作顺序的用例才启动 watcher/进程；纯规则测试直接使用 owner，避免为一个字段断言启动整个宿主。
4. 不跨用例共享可变 AgentRuntime、ContextEngine、Session 或活动目录来省时间。现有 `tests/support/project.py` 已经“每轮每 profile 初始化模板一次，再复制独立项目”，应保留，不再次提出同一优化。
5. 配置重载测试本来就应重新读文件；不能把 Assembly 首次解析快照永久缓存来提速，否则破坏已确认 reload/restart 语义。

### 8.4 保留已有 suite，减少无意义的重复运行

现有 `scripts/test.ps1` 已支持 Fast/Full/Generation/External、TestPath、Filter 和 Durations；Fast 已排除 generation/release/external。因此“Fast 仍慢”不能仅归咎于 wheel。

日常建议沿项目规约：先相关模块的聚焦测试，再 Fast；完成前执行 Full 和 typecheck。Full 已包含 Fast，不必在同一代码状态下紧接着再跑一次相同 Fast。为调查一个已定位热点，先复测原慢用例，不反复跑全部 1150 个本地用例。

可直接使用已有入口：

```powershell
.\scripts\test.ps1 -Suite Fast -TestPath tests/agent/composition/test_builder.py -Filter endpoint_config_reload -Durations 20
.\scripts\test.ps1 -Suite Fast -Durations 20
.\scripts\test.ps1 -Suite Full -Durations 30
.\scripts\typecheck.ps1
```

wheel 发布验收继续留在 Full/Generation，保留真实打包、隔离导入和项目初始化验证。该测试已使用 --no-deps 和 --no-build-isolation，不宜在没有证据时归咎于依赖下载。

### 8.5 等待、阻塞与并行

本次未观察到 teardown 成为主热点，不建议统一缩短 timeout。大部分 `asyncio.sleep(0)` 是调度让步，不能当作浪费等待删除；进程树测试里的子进程长 sleep 用来证明进程被终止，也不等于测试必然等满该时长。

部分异步测试使用同步 TestClient，内部 WebSocket 接收是阻塞调用。比如 `receive_event_names` 虽然在外层检查 deadline，`receive_json()` 本身阻塞时却不能靠这条检查退出。当前配置了 heartbeat 且正常运行通过，不能据此认定已发生挂死；但这是“偶尔过长”时值得针对性检查的等待点。HTTP-only 的异步宿主测试可用同事件循环的异步 ASGI client；WebSocket 场景保留真实协议，采用确实可取消、可 join 的有限接收方式。不要包一个遗留阻塞线程的假超时。

如需再并行加速，先试纯 owner 测试的小规模进程并行；现有依赖没有要求用 xdist，本次也未安装或测量它。不直接全套 `-n auto`：当前模板路径来自共享 PYTEST_TINYSOUL_RUN_ROOT，并行 worker 可能同时初始化同一模板，需要预建或按 worker 隔离；真实 CLI/协议/进程测试还需验证端口、资源竞争和启动成本。并行是后续选择，不替代先消除已证实的重复扫描。

### 8.6 验收口径

先在同机同配置下记录原慢用例与 status 微基准，再优化、复测；报告中位数、实际选择集和功能断言，而非未经验证的全量加速预估。Full/typecheck 应继续通过，R2 的新契约验证不能为了数字好看移出门禁。优化后的持续耗时目标应由实测结果确定，本 review 不规定任意毫秒阈值。

## 9. 后续推进与验收顺序

认可本次架构成果，不重新启动“大重构”。建议按以下顺序推进：

1. R1：补齐配置范围单一归属，保持静态校验简单。
2. R3：清理 SDK/runtime 命名，明确 SDK 服务与内部宿主访问说明。
3. R4：先消除 status 请求内重复扫描，再根据复测决定是否需要 catalog 索引和测试分层调整。
4. R2：补齐少量插件纵向/生命周期契约验证，复用已有基础测试。
5. 运行 Full/typecheck，同步设计说明及原计划的逐项验收证据。

R4 是本次新增性能改进，不应反过来扩张原重构计划的架构范围；R1/R2/R3 才是本轮实施收口的直接补强。

后续能力继续通过显式 Plugin composition 增加：创建 owner、提供窄服务、贡献 profile 的动作/语境/事件、声明实际拥有的生命周期。只有出现新的真实业务编排时才调整宿主，不为了假设的任意插件裁剪增加抽象。

建议本审查文档的提交说明：`docs: consolidate SDK plugin review and test performance findings`。

