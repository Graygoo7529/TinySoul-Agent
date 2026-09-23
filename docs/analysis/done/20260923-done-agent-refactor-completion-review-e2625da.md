# Agent 大重构完成后独立审查与后续收口建议

审查日期：2026-09-22

代码基线：`e2625da8c02309c60cd79ada3d34fad973ab089d`（独立拉取的远端 HEAD）

范围：架构、正常功能链路、扩展接口、代表性失败处理、本地验证。
状态：`done`（2026-09-23 收口复核完成；原始审查结论与后续实施证据见第 11 节）。

本文件是本次最新交付，不是前三轮 Review 或主计划的旧副本。主计划当前实际路径为 `docs/analysis/done/20260915-done-agent-architecture-refactor-plan.md`，R7 及其披露收口也已归档。本轮不修改实现、不修改历史提交、不覆盖历史验收记录。

## 1. 结论

**此次重构的核心架构目标已经基本达到，可以作为后续功能建设的基础；不建议再发起一轮推倒式重构。** 在本次检查的正常链路上，没有发现需要恢复旧实现、并行建立第二套 Loop、Session 历史或 Job 监督系统的问题。

但“核心架构完成”需要与另外两件事分开：

1. **SDK 的嵌入运行能力已经成立，宿主侧通用插件接入还不够直接。** 内核已有真实的插件 SPI，标准 Agent 装配仍集中绑定内置能力。它适合继续在仓库中开发插件，但不能无保留地宣传为宿主只传入插件声明就能扩展完整 Agent。
2. **本次全新环境的类型门禁未通过。** ACP 运行夹具通过，但 `ty 0.0.83` 对生产客户端和测试 Agent 的不完整 Protocol 实现报错。应修正类型契约后重新验收，不把历史“通过”覆盖本次结果。

真实模型的自主整理效果、真实 Codex 委派和远程 MCP 服务可用性，不由本地夹具或架构阅读证明。本轮没有使用真实账号、模型或部署数据测试这些能力。

主计划的 `done` 可以保留为其既定范围的历史完成记录；本次新增发现应独立收口，不把已经落实的设计重新列为待确认。

## 2. 审查依据与边界

重新阅读 AGENTS.md，检查主计划的分层、Context、插件、Session、Reflection、ACP/MCP 和验收约定，以及 R7 实施与后续收口记录；对照当前 Agent/Session/Context 设计和 `docs/chat/00 doing something.md`。

代码检查覆盖以下主要接点，不声称逐行审计全仓：

- SDK、组合根、服务 lease、根调度和 Endpoint 协议门面。
- PluginDeclaration、TurnProfile、段协议、事件适配、准备/完成管线。
- Context 组合、Trace 折叠及消费保护、Session 事实/注释/投影/inspect。
- Workspace 事件、文件监听、Reflection 装配与确定性日切。
- Action 执行边界、Job、ACP 连接与后台委派、MCP 发现与调用。

优先检查正常任务的所有权、可见性和结束边界。没有把受信主机上的 shell/ACP 强隔离、极端存储故障恢复或企业级治理加入验收条件。

## 3. 原始目标与实际实现

| 目标 | 当前落点与判断 | 主要代码证据 |
|---|---|---|
| Agent SDK 封装 | create/assemble、start、submit、append/reply、grant、cancel、publish、status、restart/shutdown 已形成统一门面 | `tinysoul/agent/sdk.py`、`commands.py`、`handles.py` |
| 唯一根调度 | User 与两类 Reflection 共用根队列；等待仍占根位置，不另开推理循环 | `agent/dispatch/scheduler.py`、`kernel/loop/assembly.py` |
| Kernel 不理解领域内容 | kernel 依赖通用段、服务与执行协议；Home/Memory/Session 语义由插件维护 | `kernel/registration.py`、`kernel/context/segments/` |
| 环境驱动 | 定向/订阅路由进入 Inbox，owner 适配为 Signal，再由既有 Context 批次更新 | `agent/dispatch/router.py`、`kernel/loop/interaction/events.py`、`plugins/workspace/plugin.py` |
| 渐进式 Context | 三插槽、四形状、能力声明；Trace 和 Session 共用披露页与分页 | `kernel/context/segments/protocol.py`、`kernel/context/disclosure.py` |
| 当日 Session 理解 | 不可变 Turn 事实加独立可修改注释；Organize 是普通 core Action | `plugins/session/actions.py`、`annotations/`、`views/` |
| 灵活工作区 | 真实文件内容加索引/标签，事件后刷新；不把 digest/CAS 变成日常写入协议 | `plugins/workspace/`、`plugins/execution/` |
| 自主 Reflection | 两个 profile 复用同一 kernel，通用域叠加专属写服务；不是固定八步控制器 | `plugins/reflection/builder.py`、`home/services.py`、`memory/services.py` |
| ACP 与后台任务 | 显式连接、每次委派一个 Turn-owned Job；连接视图属于 Working | `capabilities/subagent/engine.py`、`jobs/backend.py`、`segments/connections.py` |
| MCP 扩展 | 四个动作共用目录、schema 校验和连接；检索结果进入工具反馈，不新建 tools 段 | `capabilities/expand/engine.py`、`actions.py`、`mcp/client.py` |
| Gateway 解耦 | Endpoint 通过明确协议门面和服务调用 Agent，不维护另一张业务 Turn 状态表 | `gateway/endpoint/engine/contracts.py`、`context.py`、`agent/services.py` |

这些不是只有命名上的拆分：`tests/test_architecture.py` 检查了导入方向；SDK 集成测试检查了同轮等待恢复、Session 记录、重启与日切；协议夹具实际经过 ACP/MCP SDK。

### 3.1 分层为什么是合理的

infra 提供文件、进程、配置、并发和时钟；runtime 提供运行转移与消息 envelope；llm 承担模型调用；kernel 组合 Turn/Cycle/Phase、Action、Context 和 Jobs；plugins 持有领域事实和外部能力；agent 是组合根及根调度；gateway 是宿主和协议适配。

组合根知道具体 Home/Memory/Workspace 并不违反依赖反转。关键是业务规则不能倒灌 kernel，且新增普通能力不应要求修改 kernel 的 owner 分支。本次检查中，这条主边界成立。仍待改进的是组合根对宿主开放的扩展接口，而不是删除组合根。

### 3.2 运行链路

宿主提交 typed request → Agent 根队列 → 日准备及 profile → Turn → Cycle 三 Phase → Action/Job/领域 owner → Signal 或环境事件 → 固定批次更新 Context → 下一次模型决策。

等待用户、事件、定时器和预算由既有 Turn 处理。Job 与来源在等待期间仍能运行；等待不会变成“结束后重建一个 Turn”。完成时先收敛工作和必要事实，再记录 Session、释放视图和日资源。这个设计足以承载持续任务，不需要再引入 DDS 中间件或第二套通用工作流引擎。

## 4. Context 与 Session：渐进式理念是否真正落地

### 4.1 插槽、形状和能力不是同一个维度

| 维度 | 当前定义 | 用途 |
|---|---|---|
| 插槽 | Background / Trace / Working | 决定模型语境的组合位置 |
| 形状 | State / Heap / Stack / Map | 描述内容组织，不强迫统一容器 |
| 能力 | INSPECT / QUERY / SELECT / RECLAIM | 声明可读取、定位、加载逐出和回收的操作 |
| 段身份 | lower_snake_case id、owner、order、ref_prefixes | 稳定注册、排序和引用路由 |

当前三段主语义清楚：Background 保存身份和来源背景，包括 session、inputs、home、memory；Trace 保存当前轮按观察顺序记录的交互事实；Working 保存 plan、Workspace、jobs、connections 的现态。TaskPrompt 是每次模型任务的临时层，不应演化成第四个长期事实 owner。

`session` 段名已落实。`session:history` 是同一 Session 的事实导航入口，不是恢复了一套名为 history 的独立存储。Action 名和引用仍可含点号、冒号或路径；删除这些标点不是“段命名简化”的要求。

### 4.2 外围插件怎样维护语义

1. Engine/Service 持有事实；PluginDeclaration 注册段、动作、服务、事件和必要生命周期贡献。
2. `provider.open(TurnInfo)` 读取来源，创建本 Turn 的视图。
3. Action 先提交 owner 事实，再发刷新 Signal；外部事件通过订阅适配进入相同通道。
4. 各段 `prepare` 读取并构造候选；全部准备完成后统一同步 `install`。
5. 每次模型任务的 composer 调 `render`，只读取已安装内容，不临时扫磁盘。
6. 完成管线保存必要事实；`close` 只回收视图。Session 的 recorder 位于必要完成处理之后，不重复写两次。

无上下文内容的插件无需伪造一个空段。准备、完成和运行来源已有真实消费者，不需要再建设另一套 Participant 总线。

### 4.3 折叠与 inspect

`DisclosureHint(ref, title, clue)` 和 `DisclosurePage` 把逐层读取统一起来，但不把 Trace 的顺序和 Session 的图改成一种数据结构。

- Trace 保留原始事实与折叠投影，inspect 沿根、分支、叶子取回。
- Session 保留事实和注释，地图入口通向话题、注释、未归类和历史 Turn，再下探输入、Action、输出及资源来源。
- 分页用于读完当前范围；inspect 子 ref 用于继续下探，二者不是两套检索系统。
- query 是 ref 范围内的确定性定位，不启动额外模型，不沿任意图关系无限遍历。
- inspect 返回作为当前工具反馈进入 Trace；它不等于永久展开 Background。Home/Memory 的持续加载仍由 load/evict 承担。
- Trace 对尚未进入实际返回的 Phase1/Phase2 模型请求的 overlay 保持保护；容量恢复不能仅因尝试调用模型就解除保护。

证据：`context/disclosure.py`、`context/builtin/trace.py::mark_consumed/fold_overlays`、`loop/phases/phase1.py`、`phase2.py`、`session/views/inspection.py`。相关 Context/Session 聚焦测试通过。

### 4.4 Session 并没有重新维护“两套历史”

自动事实记录与模型解释分层正确：事实由完成管线确定性保存，解释由 `core.session.organize` 原子修改 map；Organize 本身不额外调用 LLM，模型决定已经发生在正常 Phase2。

当前背景展示是“地图引用 + 按时间顺序一次呈现的交互正文”。它们从同一组 records/annotations 派生，不能仅因出现线性交互就判断为双轨设计。反而这避免模型只有话题摘要，却看不到用户原话、完整选项和对应回复。

整理可以面向多个历史 Turn 和既有解释；已接受的当前输入/已结算 Action 可以作为解释证据，但当前 Turn 不提前成为历史成员。活动与完成 Action 的披露复用同一投影，最新 `e2625da` 已补齐相应查询范围和下探入口。

压缩使用同一背景预算：优先保留近期交互及相关来源，超限才明确摘录/折叠；问题和选项不截断。Session 仅在自身高水位回收，刷新沿用缩减后的预算。日切归档 turns 与 map，新日不继承语义图，同日重启可恢复。

这满足已确认的“当日持续理解 + 冰山式追溯”，无需增加持久摘要副本、图数据库或隐藏整理任务。

## 5. 需要收口的两项

### F1：标准 SDK 缺少完整、明确的宿主插件接入路径

历史状态：`proposed`；优先级：P2（扩展性收口，不是现有正常业务故障）。

收口状态：`done`（2026-09-23）。

证据：

- `agent/sdk.py:82–121`：create 只接项目配置、队列和 Inbox 参数；assemble 接收整个 AgentAssembly 工厂。
- `agent/composition/builder.py:143–213`：已有模型、时钟、输入源和少数 owner 的注入方法，没有通用 plugin/profile contribution 入口。
- `agent/composition/builder.py:516–543`：内置 runtime_plugins 在组合根内直接构造。
- `agent/composition/actions.py:213` 附近：内置 Workspace、execution、expand、subagent 等声明由 CommonActionAssembly 集中组织；部分能力没有像 Session/Home/Memory/Workspace 那样的独立声明门面。
- `agent/services.py:51–76`：公开 ServiceRegistry 显式导出四类核心服务，不会自动导出新增插件服务。

**影响：** 对一个新增“专属知识来源 + Working 状态 + Action + 事件源”的插件，内核协议够用，但使用标准 Agent 的宿主还需要深入组合根装配。`Agent.assemble` 是有效高级逃生口，不等于简单的通用插件注入 API。服务白名单本身是合理权限设计，不应为方便直接导出 SessionOrganizeService 等内部服务。

建议以一个真实新增插件为消费者，补齐薄的一层组合契约：

1. 在 AgentBuilder 接受按世代创建的插件工厂；create 可以转交同一配置，不建设动态扫描/安装平台。
2. 工厂显式声明参与哪些现有 profile；生成每个 profile 的贡献时取得窄依赖，不取得整个可变 Agent。
3. 复用 PluginDeclaration、ServiceRegistry、TurnProfile 与既有资源作用域。I/O Engine 每世代创建、关闭；Segment 每 Turn 创建；不要把同一个可变段跨 profile/Turn 复用。
4. 若真实插件需要 SDK 读取，增加显式的可公开服务绑定贡献，复用 generation/day lease；内部动作权限与对外导出分开。没有消费者时不预建万能导出协议。
5. 将新增能力的声明和资源所有权收拢到所属插件门面，组合根只负责选择与连接。不要为了文件对称而拆现有无状态函数。

验收以“宿主通过公开入口挂载一个实际小插件，不改 kernel、不复制默认 Agent 装配；同轮事件更新下一次模型视图；restart 后重建且旧对象失效”为准。不以增加注册接口的数量为完成标准。

这是一项建议，不将其追认为已批准的具体 API。若项目刻意只支持仓库内静态插件，应明确文档定位，并可暂缓对外入口；按用户强调 SDK 化的目标，本报告推荐补齐薄入口。

### F2：全新合法依赖环境下 ACP 类型契约未通过门禁

历史状态：`pending`；优先级：P2（验证与适配器类型契约）。

收口状态：`done`（2026-09-23）。

复现环境：Python 3.13.15，ACP 0.12.1，MCP 2.2.0，ty 0.0.83，按仓库 `.[dev]` 安装。Linux 和 win32 类型检查目标都报告两处 `call-non-callable`：

- `tinysoul/plugins/capabilities/subagent/acp/connection.py:103` 实例化 `_Client`；它继承 ACP Client Protocol，但缺少包括文件/终端回调在内的 12 个方法实现。
- `tests/plugins/capabilities/subagent/fixture_agent.py:158` 实例化 LocalAgent；它继承 ACP Agent Protocol，但缺少 8 个方法实现。

当前 `_Client` 仅实现 permission 和 session_update；初始化没有声称支持通用文件/终端能力。真实本地协议夹具已通过，因此不能把静态报错写成“连接必然无法建立”。也不能在未取得之前具体工具版本的情况下断言一定由 ty 升级造成。

建议：依锁定 ACP 包的实际扩展契约，为未支持的可选方法建立明确、最小的适配处理；优先复用该依赖已有适配入口，必要时在 ACP owner 边界显式拒绝未支持调用，不假返回成功，也不为了凑齐接口实现第二套文件/终端系统。测试 Agent 同步表达自身支持范围。避免全局忽略类型错误、宽泛 cast 或只固定旧检查器来遮住问题。

修正后重跑 ACP 聚焦、Fast、Full 和两平台目标类型检查。工具版本可以记录以便重现，但无需因此设计复杂依赖治理。

## 6. 编码与异常处理的干净性判断

总体风格遵循 typed dataclass、StrEnum、显式配置与 owner 门面。以下抽样处理是合理的，应保留：

- Action 无效参数或 Organize 无效来源返回有限局部结果；存储损坏、契约错误经 owner bridge 进入 Runtime。
- ActionRunner 不把任意内部异常伪装为模型可以修复的成功/失败工具正文；真实结算与取消事实分开。
- 短本地 owner 操作 join 后再传播取消；长进程由受控执行后端收敛。当前不再依靠抛弃超时线程来宣称完成。
- 必要完成失败影响主结果，附属 close 诊断不覆盖已提交事实；Session recorder 不另起平行日志。
- ACP/MCP 外部边界的宽泛捕获用于封装第三方失败，不能仅凭 `except Exception` 就要求机械删除；内部 JSON/契约缺陷仍应保持可诊断。

本轮没有提出另一套 ActionRunner、事务协调器或自动恢复状态机。继续维护时值得关注的是“大类里新能力的装配增长”，而不是文件行数本身；F1 的门面收拢应随真实插件消费推进。

## 7. 后续功能规划如何纳入现有语义

| 规划方向 | 推荐接入方式 | 不应做的事 |
|---|---|---|
| Coding / 多 Agent 协作 | Workspace + execution + ACP Job，Skill 组合行为 | 为 coding 另建 Loop 或给每种任务一套监督器 |
| 邮件、检索、图像生成等工具 | 优先 MCP；需要领域状态时采用能力插件 | 搜索一次就把所有工具 schema 常驻 Working |
| 外部环境感知 | 来源发布事件，订阅适配刷新 owner 段；独立 Trigger 才提交根 work | 观察日志反向驱动业务，普通 Job 事件隐式新建根 Turn |
| 连续问答和意图理解 | Inputs/Trace + Session Organize + 既有 ask/reply | 隐藏模型后台编辑历史事实，跨日默认延续 Session 图 |
| PDF/图片等资源处理 | Workspace 资源 + 按需读取/转换 Action；模型适配处理消息能力 | 把全部二进制或历史图片载荷永久塞入 Context |
| 长期收藏 Library | 若明确跨日保留需求，新增资源 owner、服务和来源 Link | 将当日 Workspace 的 library 标签冒充长期持久库 |
| 前端语义图和过程展示 | Session 只读视图和 Observation/Endpoint 投影 | 前端建立第二张权威会话事实表或绕过 owner 编辑 map |
| 自身扩展与能力沉淀 | Home overlay、Skill、独立 Home Reflection 审核 | 普通 User API 直接提交 actual Home 或持久 Memory |

上述是接续设计，不代表这些产品能力全部已经实现。尤其 MCP resources/prompts、ACP 运行中 steering、TinySoul 自调用子 Turn 和完整长期 Library，不能从“底层可扩展”推导为已交付。

## 8. 本次验证

环境没有 Conda TinySoul 或 PowerShell，使用新建 Python 3.13 venv，安装当前 checkout 的 editable `.[dev]`。未使用旧 checkout 的已安装包。未设置 external 开关，未调用真实外部模型。pytest 通过仓库 conftest 生成独立 `.local-test` 运行目录。

执行 pytest 时仅对该子进程移除了 HTTP(S)/ALL_PROXY 环境变量，避免宿主代理改变本地夹具环境；没有输出或修改凭据。

| 验证 | 本次结果 |
|---|---|
| 聚焦：导入边界、注册、Context、Session、SDK、ACP/MCP | 184 passed |
| Fast：`pytest -m 'not external and not generation and not release'` | 1138 passed，6 skipped，28 deselected |
| Full：`pytest -m 'not external' -rs` | 1143 passed，6 skipped，23 deselected；包含生成与 wheel 验收 |
| `ty check --python .venv/bin/python --platform linux` | 2 diagnostics，见 F2 |
| `ty check --python .venv/bin/python --platform win32` | 同样 2 diagnostics；这是目标类型检查，不是 Windows 实机测试 |

本次 Fast 有一条 Starlette 关于 AnyIO BlockingPortal 的弃用警告，不是测试失败，不建议为此调整架构。

Full 首次运行因本次 uv 创建的 venv 缺少 pip，在调用 `python -m pip wheel` 时失败；确认 `No module named pip` 后仅补装 pip 26.2.1，再完整复跑，得到上表通过结果。没有修改测试、跳过发布验收或修改业务代码。

6 个跳过项分别是 1 个 Windows 挂起启动测试、4 个 Windows 大小写路径测试、1 个缺少 Defuddle CLI 的测试。23 个 external 测试未纳入运行。Linux Full 的通过不等于 Windows 实机、Defuddle 或真实供应商验证完成。最终新增文档通过独立 whitespace 检查；交付前重新查询远端 HEAD，仍为上述基线。

历史 R7 记录的 `1149 passed, 23 deselected` 属于此前 Windows 环境。本次 Linux 跳过项与工具版本应单独记录，不直接复写该历史数字。

## 9. 原始审查时的推进顺序与产品取舍（历史记录）

以下编号保留原始审查时的判断；F1/F2 的当前收口状态以第 11 节为准，真实外部环境验收仍按实际授权和环境另行进行。

1. `pending`：先修 F2，使干净安装下类型门禁成立；不牵连 Session/Context 重设计。
2. `proposed`：确认 SDK 扩展面定位。推荐选择“宿主可通过薄插件工厂扩展现有 Agent”，然后用一个真实功能插件完成 F1 和文档示例；不建插件平台。
3. `pending`：在实际主机做小规模真实业务验收：多轮 Session 整理及 inspect；ACP 完成一次真正委派；一个已配置 MCP 服务的发现和调用；一次 Home/Memory Reflection。涉及外部服务、账号和实际写入时另行授权，不能由本次纯审查自动执行。
4. `proposed`：随后按功能价值推进 `do something` 中的能力。Context 峰值大小、长 Session 的投影成本和实际检索效果先用真实任务测量，再决定是否优化；不预先增加索引平台或恢复框架。

已有 Session 当日范围、Organize 命名及职责、Reflection 写边界、受信主机假设、ACP 条件复用和统一 inspect 均不需要重新确认。新讨论只涉及 F1 的对外扩展面，且不阻塞已有功能继续使用。

## 10. 文档与提交建议（原始审查时记录）

本轮只新增本文件；没有修改 Python、配置、前端、历史主计划或实际部署数据，也没有提交或推送。

建议提交说明：`docs: review completed agent refactor at e2625da and identify SDK integration gaps`

该说明只适用于原始审查记录；F1/F2 的后续收口状态记录在第 11 节。

## 11. 2026-09-23 收口复核

本节记录原始审查之后的实施与复核结果，保留前文作为 2026-09-22 的独立审查历史。

### F1：宿主插件接入

已满足原建议的薄组合契约：

- `AgentBuilder.use(plugin)` 是公开的宿主接入入口；插件按 generation 构建，并通过 `PluginGeneration` 提供 profile extension、来源、配置、Turn 资源、生命周期和 SDK export。
- `GenerationBuildContext`、`ProfileBuildContext` 和 `PluginServiceExport` 保持窄依赖；服务导出由插件声明，`AgentRuntimeServices` 不再按 Home/Memory/Session/Workspace 硬编码分支。
- `tests/agent/composition/test_builder.py::test_host_plugin_is_built_per_generation_and_extends_user_profile` 验证宿主插件可以经 `standard_agent(...).use(plugin)` 接入，扩展 User profile、绑定 SDK 服务，并在 generation 关闭时释放。
- 内置能力已经迁移到同一插件路径；没有新增第二套 kernel、Loop、Action 或调度器。

### F2：ACP 类型契约

已满足原建议：`_Client` 和 ACP 测试 `LocalAgent` 实现锁定依赖要求的协议方法；未支持的 request 明确返回 `RequestError.method_not_found`，通知不伪造成功响应。未引入第二套文件／终端系统，也没有使用宽泛类型忽略遮蔽协议错误。

### 最终验证与边界

- `powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\\scripts\\test.ps1 -Suite Full`：`1150 passed, 23 deselected`。
- `powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\\scripts\\typecheck.ps1`：通过，`All checks passed!`。
- 额外架构、注册、压力、Agent、Gateway、插件能力与 ACP 聚焦测试均通过。
- `AGENTS.md`、`docs/design/agent.md`、`docs/design/context.md`、`docs/design/runtime.md` 和对应执行计划已同步；执行计划已归档为 `docs/analysis/done/20260923-done-agent-harness-plugin-composition-refactor-plan.md`。

本地门禁未包含真实 provider、远程 MCP、真实 ACP 委派、Windows 实机或 Defuddle CLI；这些仍属于需要实际环境和授权的独立验收，不影响本 review 对 F1/F2 的收口结论。原始 review 现已满足归档条件。
