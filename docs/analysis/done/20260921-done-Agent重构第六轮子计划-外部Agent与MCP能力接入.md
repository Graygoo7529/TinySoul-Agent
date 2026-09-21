# Agent 重构第六轮子计划：外部 Agent 与 MCP 能力接入

状态：`done`（2026-09-21 完成实现、设计同步、逐项核对与本地门禁；外部验证边界见 §12）。
日期：2026-09-21。
代码基线：`9f42976`（R5 运行可用性、重启边界与退出等待修正已提交）；开始分析时工作区干净。
设计复核基线：`2b03a61`（四动作 MCP 方案已确认）；实施基线：`f5c4a90`（四动作与实施边界已提交）。第 2 节保留实施前缺口，第 9、11、12 节记录本轮证据。
主计划：[Agent 架构重构主执行计划](20260915-done-agent-architecture-refactor-plan.md)，主要对应 §11 与 S6。
参考：[功能规划讨论](../../chat/00%20doing%20something.md)。其中的 coding、外部工具和后台协作作为能力场景参考，不据此恢复旧 Reflection domain、CAS 或扩大本轮范围。

## 1. 本轮目标与推进位置

让同一个 Agent 能够通过既有 Action 委派外部 Agent、监督其执行并回答其原生请求，同时按需发现和调用 MCP 工具。两者继续使用现有 Context、Job、Inbox、Workspace、profile、世代和日生命周期。

R6 不是重新建立 Agent 调度器。ACP connection 是可通信的服务资源，ACP session 是该连接上的对话上下文，Job 是当前 TinySoul Turn 所属的一次委派。MCP connection 是外部工具服务资源，一次 `expand.call` 是有界 Action。这几种身份不互相替代。

本轮完成后 S6 才能逐项验收；S3 的 Organize Action 与模型注释层仍在主计划尾期、S7 前完成。R5 的 `Agent.wait_for_exit` 是实例退出等待，本轮继续使用 `core.job.wait` 表达当前 Turn 对 Job 的等待，二者不合并或再次改名。

## 2. 实施前基线核对

| 当前事实 | 实现位置 | R6 处理 |
|---|---|---|
| 尚无 subagent/expand 实现和配置；capabilities 只有 resource/web | `tinysoul/plugins/capabilities/`、`pyproject.toml` | 建立两个真实插件，按主计划保留在 capabilities 子包 |
| JobBackend 的创建、停止、关闭等仍为同步接口，Registry 经 JoinedOperations 调用；组合根限定 ProcessJobBackend | `kernel/jobs/models.py`、`registry.py`、`agent/composition/actions.py` | 统一为异步 Job 资源边界，进程与 ACP 共用一个 Registry |
| Job wait 的 ready 仅判断终态；Inbox 的 Job 专用投递也只覆盖终态 | `kernel/jobs/actions.py`、`kernel/loop/interaction/inbox.py` | 补齐待答请求的可靠投递与唤醒，否则父等 Job、子等父会互相等待 |
| Job 清理后才执行 Workspace 最终 reconcile | `agent/composition/activity.py` | 保留顺序，并纳入插件本轮 session/引用释放 |
| 插件已有 services/segments/actions/events/sources/preparation/completion 贡献 | `kernel/registration.py` | 通过现有声明接入；只为真实资源关闭消费者补窄接口 |
| GenerationSources 的 pause 使用附属清理诊断语义 | `agent/lifecycle/sources.py`、`infra/concurrency.py` | 不把 ACP 必须停止的执行藏在可忽略诊断中；必要资源关闭与普通来源停止分清 |
| ManagedProcess 面向 stdout/stderr 文件捕获，不直接提供协议 SDK 所需双向异步管道 | `infra/process/managed.py` | 共用平台进程所有权，补充 stdio 会话传输所需能力；不复制进程树控制 |
| Action 自有 schema 是明确的受限子集 | `kernel/action/catalog/schema.py` | 保留外壳校验；远端完整 JSON Schema 另交标准 validator，不能削弱远端约束 |
| 配置、catalog、情景可见性和 SDK/Endpoint 门面均已集中 | `infra/config/`、`assets/`、`agent/services.py`、`gateway/endpoint/` | 复用既有入口，不建立第二套配置或外部工具调用网关 |

以上是实施前的路径核查，不代表完成后的状态；本轮新增实现与门禁单独记录，不引用旧门禁作为新实现证据。

### 2.1 主计划要求与本轮细化的区别

| 设计项 | 来源 | 当前判断 |
|---|---|---|
| 进程与 ACP 共用 Job，Turn 所有权、公共 status/stop/wait、终态与资源关闭分离 | 主计划 §11.1、S6；§6.3 已要求前台 Action 与后台 Job 共用受控 backend | 既定架构目标，R6 补齐第二个真实 backend |
| 可取消 I/O 使用 async，短同步 owner 操作经明确边界调用 | 主计划 §6.3；现有 ActionExecutor、ExecutionEngine.start/wait 已为 async | 既定执行原则，不意味着所有工作都后台化 |
| JobBackend 的具体异步方法、混合 Registry 的类型边界、待答唤醒如何接入 | 本轮 §4 | 根据现有进程专属实现作必要细化；主计划未规定所有 backend 方法必须 async |
| MCP 归 expand，提供发现、描述与调用，结果进 foldable Trace，无工具专属 Context 段 | 主计划 §11.4 | Q6 已确认四动作 `describe_servers/describe_tools/search/call`；owner 与渐进披露不变 |
| MCP schema 校验、分页/列表变化、大输出、未知写结果不重放 | 主计划 §11.4 与 S6 验收 | 既定约束，R6 落到真实 SDK |
| search 的筛选算法、是否调用 LLM、返回线索或完整工具定义 | 本轮细化，用户已确认 Q4 | 有界的一次 Action 内局部 LLM 选择，owner 补齐原始定义；超预算由父 Agent 缩小服务范围，见 §6.2 |
| SDK 版本、首个真实 adapter、stdio/HTTP 范围和目录细节 | 本轮细化 | 版本与接口仍需 R6-0 验证，不是主计划已经实现的能力 |

## 3. 协议与 SDK 核验

以下为 2026-09-21 阅读官方文档、发布信息和源码得到的设计依据。实施使用 MCP 2.2.0、ACP 0.12.1 和 jsonschema 4.26.0；独立临时目录安装已发布的 Codex ACP 1.12.0 与 Codex 0.154.0，真实握手、session close 与新 session 探针通过。发布包的 Codex 依赖为 `^0.154.0`，实施验证使用锁定版本。连续 prompt、权限、后台任务停止与取消通过真实 SDK 的本地协议 fixture 验证，未运行真实模型委派。发布包、协议测试与真实模型端到端证据分别记录。

| 对象 | 已查证依据 | 本轮建议 |
|---|---|---|
| ACP | v1 的 prompt 请求在本次执行结束后返回 StopReason；流更新不等于完成 | 以 ACP v1 为基础，不采用未经核验的 v2 假设 |
| ACP Python SDK | PyPI 稳定版 `agent-client-protocol 0.12.1`；另有 1.0.0rc1 | 先以 0.12.1 做发布包探针；不因 rc 存在自动选预发布 |
| Codex ACP adapter | 旧 zed-industries 仓库已指向 agentclientprotocol/codex-acp；新仓库主分支 package 标为 1.12.0 | 首个目标建议选新仓库的已发布版本，安装前核对发布制品及绑定的 Codex 版本；不使用漂移的 npx latest/preview |
| MCP | 当前规范入口指向 2026-07-28；Python SDK 发布版为 2.2.0 | 采用 SDK 2.2.0 为集成基线，以 SDK 公共 Client 统一协议差异 |
| JSON Schema | MCP 默认 dialect 为 2020-12；jsonschema 文档提供 dialect 选择、schema 检查和实例校验 | 使用标准 validator，限定明确支持的 dialect 与引用解析范围 |

来源：[ACP prompt/取消](https://agentclientprotocol.com/protocol/v1/prompt-turn)、[ACP SDK 发布](https://pypi.org/project/agent-client-protocol/0.12.1/)、[旧 adapter 迁移说明](https://github.com/zed-industries/codex-acp)、[新 adapter](https://github.com/agentclientprotocol/codex-acp)、[主分支 package](https://github.com/agentclientprotocol/codex-acp/blob/main/package.json)、[MCP SDK 发布](https://pypi.org/project/mcp/2.2.0/)、[MCP 规范](https://modelcontextprotocol.io/specification/2026-07-28)、[JSON Schema 校验](https://python-jsonschema.readthedocs.io/en/stable/validate/)。

四个需要落实到 adapter 的具体事实：

1. ACP `session/close` 是有能力声明条件的接口，不能无条件调用。SDK 发布包是否暴露所需方法，必须与目标 adapter 一并验证。支持且成功释放旧 session 时可保留空闲连接，新根创建新 session；否则按主计划 Q8 在 Turn 收尾断连。[Session setup](https://agentclientprotocol.com/protocol/v1/session-setup)
2. 候选 Codex adapter 的 `_session/steering` 示例允许返回 `startedNewTurn`，所以它不能直接满足“只向当前 Job 追加”的契约。R6 建议不开放此扩展，见 Q2；以后只有具备可确认的“当前工作已结束则拒绝”语义才注册 `send`。[Steering 示例](https://github.com/agentclientprotocol/codex-acp/blob/main/examples/steering.ts)
3. 候选 adapter 支持 prompt 结束后仍运行的后台终端任务，故 prompt 返回不能单独证明执行资源已关闭。首个 adapter 的收尾必须验证这些资源确已结束/收回；不能仅靠 idle 或关闭客户端 future 推断。使用其真实能力做必要收尾，不另建 TinySoul 子 Job 树。[后台终端说明](https://github.com/agentclientprotocol/codex-acp/blob/main/docs/async-tasks.md)
4. MCP SDK 2 的 Client 可处理现代 discover 与旧 initialize 协议；现代工具列表变更需要订阅流，不能照抄旧 message callback。TinySoul adapter 统一成“连接信息、列举、调用、目录失效线索”，不在业务层保留两套 MCP 实现。[协议版本](https://py.sdk.modelcontextprotocol.io/protocol-versions/)、[Client](https://py.sdk.modelcontextprotocol.io/client/)、[订阅](https://py.sdk.modelcontextprotocol.io/client/subscriptions/)

R6-0 是实现前的技术验证切片，不是要求用户判断 SDK 细节。只有探针暴露与本计划已确认语义冲突时，才带着具体证据重新讨论，不以临时补丁绕过。

## 4. 统一所有权与异步执行边界

### 4.1 模块分工

| Owner | 职责 |
|---|---|
| `plugins/capabilities/subagent` | 显式目标配置、ACP 连接/session、委派 backend、待答协议请求、输出归一化、connections 段 |
| `plugins/capabilities/expand` | MCP 服务连接、远端工具索引、schema/参数校验、调用结果归一化 |
| `kernel/jobs` | 唯一 Job 受理、Turn 隔离、容量、监督、快照、待答/终态通知和 stop/wait |
| `kernel/loop` | 现有 INPUT/EVENT/BUDGET 等待、Inbox 捕获与 Context 批次安装 |
| `infra/process` | stdio 受控进程及其后代、异步管道和有界关闭；不认识 ACP/MCP/Job |
| `plugins/workspace` | cwd、引用和输出 Link 的解析，资源写入与最终同步 |
| `agent` | 创建共享服务、profile 绑定、唯一根队列、事件路由、Turn/日/世代收尾 |

capabilities 可以拥有被 Agent 生命周期管理的 I/O 资源和服务缓存；禁止的是另建运行调度器或与核心 owner 平行的持久事实。这是主计划已有 subagent/expand 布局的落实。实现时同步澄清 `docs/design/capabilities.md` 的职责表述，不能机械解释为所有 capability 都必须无内存状态或无法持有连接。

### 4.2 异步生命周期、同步快照与前台执行

统一的是可以等待 I/O 的资源操作：创建、启动、请求停止、执行关闭和含 I/O 的清理使用异步契约。当前 poll 包含文件大小检查、超时判定及必要进程停止，describe 也读取输出文件大小；保留这些职责时，它们同样应在可 await 的边界执行，不直接阻塞事件循环。若只读取已维护的内存状态，则保留同步 snapshot/property；参数校验、内存投影和底层短同步原语也不需要机械改成 async。

ProcessJobBackend 在自己的边界通过现有 JoinedOperations 调用短同步进程操作，ACP backend 直接 await 可取消的协议操作。Registry 不识别具体 backend 类型，也不判定“返回值是否 awaitable”。同一公共方法的契约固定，不为进程与 ACP 分别保留同步/异步两套入口。

一次返回最终结果与异步执行是两个维度：`execution.run_shell/run_script` 仍在当前 Action 内等待命令完成后返回结果，模型无需再发 wait/collect；`execution.start` 则在受理后返回 job_id，供后续 Cycle 监督。二者已经共用同一 backend，R6 保持这个行为。await 仅允许等待期间继续接收输入、取消、事件或协议反向请求，不让父 Cycle 提前当作命令完成，也不要求模型管理一个原本只需一次调用的短命令。

组合根从 `JobRegistry[ProcessJobBackend]` 收敛为容纳不同 JobBackend 的一个 Registry。能力 owner 取回自己的 backend 时，在公开的类型化边界一次校验种类/类型；不在每个插件建立第二张 Job 生命周期表。Registry 继续拥有监督快照，backend 仅拥有执行资源及协议局部状态。

保留现有受理前容量检查、终态投递、终态与 execution_closed 分离、停止幂等、取消时 join、附属诊断等语义。进程型与 ACP 型 Job 共享 live/retained 限额，不能各拿一套独立额度后绕过总量限制。普通回答仍由公共 answer guard 检查未关闭的执行；空闲连接不属于活 Job。

不重写现有进程执行主线，不把 ACP prompt 放到线程里长等，不用轮询文本推断模型结束，也不引入跨 Turn Job 数据库。

### 4.3 待答请求与等待闭环

Job 公共投影增加有界待答请求摘要与结果 Link。待答摘要表达 request_id、请求种类、简短问题和可选项；ACP 的 session、RPC id、callback/future 留在 adapter 内。request_id 由 owner 稳定关联到真实未决请求，不假设 ACP 回调参数本身必有同名字段。

待答请求使用现有 Job/Inbox 路径可靠投递：扩展 Job 通知语义，区别 input_required 与 terminal，复用已有保留容量的办法提供有界控制通知位置。必要请求元数据先受理，随后才承诺等待父回复；大详情写入 Workspace。超出声明容量时完成协议层拒绝/取消，不静默丢掉已接受的请求。进度通知可以合并，未回复请求身份和终态不能被普通进度覆盖。

`core.job.wait` 的正常含义细化为等待该 Job 出现可处理的状态：终态或需要父回应。已经处于 waiting_input 时立即返回可处理状态；新待答请求也唤醒正在等待该 Job 的 Turn。只收到输出片段不强迫新增 Cycle。恢复仍服从当前预算；父处于 INPUT/BUDGET 暂停时仅积累事实，不启动隐藏 LLM 代答。

父通过 `subagent.respond` 选取真实 option_id；如果确需人的判断，先用现有 `core.ask`，用户回复回到同一父 Turn，再执行 respond。普通子 Agent 最终文本里的问句不自动转为权限请求：它是已完成 Job 的结果，父可用下一次 delegate 继续对话。

## 5. ACP 动作与语境

### 5.1 动作面

以下为已确认并落实的 TinySoul 动作语义，不是 ACP 协议方法清单。

| Action | 输入与行为 | 收敛输出 |
|---|---|---|
| `subagent.agents` | 列出显式配置且当前情景可用的目标；不自动启动 | agent_id、用途、支持边界与连接线索 |
| `subagent.connect` | agent_id、可选 cwd_link；启动、初始化，并准备当前 Turn 的可用 session | connection_id、实际就绪状态、cwd Link |
| `subagent.delegate` | connection_id、brief、可选 Workspace reference_links | 当前 Turn 的新 job_id；长 prompt 由 backend 托管 |
| `subagent.respond` | job_id、request_id、option_id | 原生请求已答/已过期/无此选项；不启动新委派 |
| `subagent.collect` | job_id、有界分页位置 | 输出片段、结果摘要及 Workspace Links；重复读取不再次执行 |
| `subagent.disconnect` | connection_id | 关闭空闲连接；有活 Job 返回 busy，先 core.job.stop |

`core.job.status/wait/stop` 仍是共用监督入口。R6 不保留绕过 connect 的 start，不给同一行为另建 SDK/Endpoint 私有执行路径。`subagent.agents` 是模型发现可连接目标的真实入口，避免要求模型猜配置 id。

`send` 暂不进入 R6 默认动作面，见 Q2。没有能力支持时不注册空壳动作。后续同 Turn 的追加任务可使用同 connection/session 发起新 delegate，但必须产生新 Job。

### 5.2 Connection、session 与 Job

一个 connection 同时最多一个 prompt Job；并行使用不同连接，仍受统一 Job 容量约束。同 Turn 内后续 delegate 可延续该 session 的对话；新根 Turn 必须使用新 session，不能自动加载历史协议会话。

默认 cwd 是 Workspace 中独立连接目录；显式 cwd_link 可以选择当前 Workspace 的已有目录。每次 Job 的输出材料另外归入 `workspace:jobs/<job_id>`。reference_links 由 Workspace owner 有界读取并转换为 adapter 所支持的输入；不向子 Agent 自动复制父 Context、Home、Memory 或 Session。要传递相关知识，由父在 brief 中明确给出必要内容。

模型只看到 cwd Link，协议所需绝对路径由 owner 解析后在 adapter 内传递。操作的是实际当天 Workspace，失败/取消不回滚。并行任务默认分目录协作；明确共写同一路径时承认覆盖风险，不加全局 CAS、文件租约或自动合并平台。

`connections` 是装配时注册一次、每 Turn 打开的 State 段。它按当前 profile 投影 connection_id、agent_id、ready/busy/unavailable、cwd_link、active_job_id；不复制 Job 输出或权限列表。连接变化通过插件声明的事件/Signal，在固定 Inbox 批次刷新段。协议回调不直接修改 Context。

### 5.3 权限、能力与关闭

建议默认把原生权限请求交给父 Agent 决定；可通过明确配置使用 adapter 自身支持的自动许可。没有逐 shell 操作分类器，不因出现权限请求就一律询问人。回应只回传本次请求提供的真实 option_id，不从展示标签拼接决定，也不把“自动许可”理解为自动选择修改永久规则的选项。[权限契约](https://github.com/agentclientprotocol/codex-acp/blob/main/docs/permission-extension.md)

目标 adapter 自己负责其本地文件和 terminal 能力；首个接入不声明 TinySoul 尚未实现的 ACP client fs/terminal 回调，也不自动向子 Agent 透传 TinySoul 的 MCP 服务或凭据。必要认证使用目标自身已有登录或显式配置的凭据方式，不在 Agent Turn 中安装 CLI、打开网页登录或建立认证工作流。

以 prompt 的明确终结响应解释此次委派结果：end_turn 表示委派执行正常结束，refusal/限额原因作为有限失败摘要，cancelled 保留取消。委派执行正常结束不等于已经证明父任务成功。传输断开且结果不明时保留失败原因与已获得材料，不自动重发。

资源关闭继续服从现有执行框架：先结清本 Job 未决反向请求和协议任务，回收它仍拥有的外部执行，再报告 execution_closed。若目标支持后台终端，adapter 必须完成有界收尾或确认它们已结束；不把这些任务提升为跨 Turn 工作。若只能靠 session/进程关闭证明停止，就关闭并呈现相应连接不可用，不能假装 session 仍可继续。是否能保留同 Turn session，是 R6-0 必须给出结论的 adapter 资格检查，不能在实施末尾才发现。如果选定发布版连正常路径的连续委派都无法支持，应更换满足契约的 adapter，或明确讨论范围调整，不能把每次委派后必然断连当成已完成同连接多次委派验收。

Turn 收尾先清理全部 Job，再释放本轮 session/连接引用，最后同步 Workspace。可低成本明确释放旧 session 的连接允许同日、同世代空闲复用；不能证明者直接断连。日切、reload/restart/shutdown 关闭相关连接，不迁移旧 cwd，不自动续跑旧委派。Q8 的取舍原则已经确认，无需再要求用户在两种寿命机制之间预选。

## 6. MCP 工具接入

### 6.1 四个动作与单一目录

Q6 已确认 expand 的四个动作：`describe_servers/describe_tools/search/call`。它们只面对当前已配置、启用且情景允许的 MCP 服务/工具，不搜索内置 Action、Home Skill 或互联网 MCP 市场；core 继续拥有通用运行控制与 Job 监督。四个动作是同一目录 owner 的不同投影，不构成强制串行工作流。

| Action | 单一职责 | 模型调用 |
|---|---|---|
| `expand.describe_servers(server_ids?)` | 浏览允许服务的用途和工具目录；每个工具只给可复用身份、名称及简短用途，不给 schema；可限定服务 | 无 |
| `expand.describe_tools(tools=[...])` | 精确批量取得工具定义，允许同批跨服务 | 无 |
| `expand.search(query, server_ids?)` | 根据需求选择工具并返回原始定义；query 必填，server_ids 可选 | 有候选且预算允许时一次 |
| `expand.call(server_id, tool_name, arguments)` | 执行一次指定工具调用 | 不额外调用 TinySoul 搜索模型 |

tools 数组中的每项为结构化身份，例如 `{"server_id":"docs","tool_name":"read"}`，不只传一个可能重名的裸工具名。describe_servers 和 search 返回同一身份结构，可直接用于 describe_tools/call。跨服务批量描述仍是 expand owner 的一次目录读取；内部按服务取得目录并取回条目，不新增批次状态机；多个真正工具执行仍复用 ActionBatch。

保留直接取得整服务定义的需求：`describe_tools(server_ids=[...])` 作为完整服务范围选择，与 tools 二选一；两种输入都只做精确读取，沿用同一有界分页与原始定义投影。批量读取不要求先 search；search 已返回所需完整定义时也不要求再 describe_tools。

describe_servers 若要报告可用工具名称，必须按需取得允许服务的工具目录；仅靠本地服务配置无法得知这些名称。因此它不再承诺“完全无 I/O 的本地服务列表”：命中有效目录时直接投影，否则按需连接/列举，可选 server_ids 限定范围。结果使用有界目录页，不能因为浏览就一次向模型填入所有工具描述；某个服务未能读取时仍可返回其配置用途与有限状态，明确目录未取得，不把它说成没有工具。它报告本次目录可见的工具，不承诺后续调用必然成功。

服务列表不自动挂载为常驻 Background/Working。Agent 可以走 `describe_servers → describe_tools → call` 的目录浏览路径，也可以直接 `search → call`；这两条路径共用同一目录，不形成两套能力发现系统。search 必须携带非空 query，空查询由 describe_servers 表达；search 已返回完整定义时不要求再次 describe_tools。

### 6.2 搜索策略权衡与选择

调研支持“按需发现，再披露少量定义”的方向，未证明某一种排序方法对 TinySoul 一定最好。Anthropic 的工具搜索给出 regex、BM25 和自定义 embedding 等路线；其另一篇 MCP 实践也区分目录浏览、搜索和不同粒度的定义加载。这里借鉴渐进披露，不引入供应商专属 tool-search API 或代码执行网关。[工具搜索实践](https://www.anthropic.com/engineering/advanced-tool-use)、[MCP 渐进披露实践](https://www.anthropic.com/engineering/code-execution-with-mcp)

| 策略 | 收益 | 代价与本轮判断 |
|---|---|---|
| 精确身份/服务范围过滤 | 确定、便宜，已知工具无需推理 | 作为公共目录操作；describe 承担精确读取 |
| lexical/BM25/regex 排序 | 不增加 LLM 调用，适合名称和关键词 | 中文需求与英文工具描述、同义需求可能缺少词面重合；不作为当前自然语言搜索的唯一筛选器 |
| 全候选紧凑目录 + 一次 LLM 选择 | 按用途理解、比较候选，复用 llm_action | 增加一次调用与输入成本，排序质量需验证；建议作为正常规模的搜索主线 |
| lexical 召回 + LLM 重排 | 大目录时减少模型输入 | 初筛漏掉的工具无法由重排找回；有真实规模证据后再替换候选选择内部实现 |
| embedding/混合检索 | 可支持大规模语义召回 | 增加嵌入生成、缓存更新和质量评估；本轮不建立向量索引 |

Q4 已确认一条明确实现路径；服务目录浏览由已确认的 `describe_servers` 负责，search 始终只接受语义 query：

1. 有 query 才取得所选服务目录。owner 先应用服务/工具配置与 profile 约束，剔除不可调用项；正常规模下，全部允许候选参与选择。候选为空时直接返回目录事实，不调用 LLM。输入保留 server_id、tool_name、服务用途、工具描述和有用参数摘要；这是检索投影，完整 schema 保存在同一 owner 中。
2. query 与候选投影仅挂载到本 Action 的 TaskPrompt，经既有 `LLMActionTaskRunner.run_json` 进行一次相关性选择。模型返回候选身份和简短理由；使用该 Action 已配置的模型链、Skill、超时和失败处理。describe_servers/describe_tools 的目录读取不调用模型。
3. owner 校验选择来自本次候选，再附加原始调用定义。模型不生成 schema、不生成替代工具名，也不在 search 中生成并执行远端 arguments。父 Agent 根据真实定义决定后续 call。
4. 按匹配上限和反馈容量返回少量完整定义。超过反馈容量的已选项只返回身份/摘要并标明需要 describe_tools，不把半个 schema 标为完整。全部候选只存在于局部任务输入，返回项进入 foldable Trace，不写 Background/Working 或另一套动态 Action Catalog。
5. 无匹配是正常空结果；目录不可用、未覆盖服务、容量限制与 LLM 协议失败分别说明。不能把不可用服务等同于已搜索且无匹配，也不在 LLM 失败后静默换算法。

完整候选投影超过当前任务可用输入预算时，返回可浏览的服务摘要及缩小 server_ids 范围的提示，由父 Agent 选择范围后继续；单服务仍过大时，可先通过 describe_servers 分页了解工具，再用 describe_tools 读取定义。本轮不藏入递归 LLM 搜索或无声明的前 N 项截断。该选择意味着 R6 的全域语义检索有明确规模上限，不宣称支持任意规模；后续若真实目录需要召回层，可在同一目录与选择边界内引入，不改变四个 Action 或新增持久业务事实。

预算按完整 Task 的可用输入和反馈大小计算，不只按工具个数猜测容量。测试覆盖选择协议和数据流；检索质量用中英文需求、相似工具和无匹配的少量人工标注样例另行评估，不用 fake LLM 的固定排序证明真实搜索质量。

### 6.3 单一目录、批量描述与按需刷新

expand Engine 拥有服务绑定、SDK 连接与一份运行期目录；工具身份为配置的 `(server_id, tool_name)`。远端自报 server name 只作说明，不能替代本地稳定身份。目录中保存原始定义及校验结论，候选摘要、精确描述与调用校验均从这里派生。它不是新的持久知识库、Job Registry 或 Context 段。

describe_tools 的批量选择按结构化 `(server_id, tool_name)` 精确解析并去重；返回成功定义与未找到/不可用项的有限说明，个别无效项不遮蔽其它定义。也可以用 `server_ids` 指定一个或多个完整服务范围；`tools` 与 `server_ids` 二选一，不越过配置限制。响应按完整工具定义分组分页，同时有数量与总大小上限，单个 schema 不跨页拆开。需要续页时使用 owner 的有界分页入口；分页事实允许投影，模型无需维护 revision/digest。工具列表变化后过期续页可要求重新 describe_tools，不建设历史目录版本库。

上游 MCP 分页与面向模型的 describe 分页职责不同：owner 完成一次 tools/list 遍历后发布本地目录，模型再按需读取定义页。完整遍历表示没有把中途失败的半份列表提交为完成；协议不保证遍历期间远端目录不变，TinySoul 不宣称跨页事务一致性，也不为此增加 CAS。目录容量不足时明确反馈；不能静默丢掉尾部后声称整服务工具均已载入。

目录新鲜度收敛为“命中可用目录，或下一次访问时刷新”：

- 现代协议的 TTL 与 list_changed 都作为 owner 内部失效依据；保守使用已读取各页的到期边界，通知可以提前失效。无 TTL 的旧服务优先沿用可靠通知，否则下一次访问重新列举；不把 TTL 当后台轮询周期。
- 每个服务绑定的凭据、generation 和服务策略共同限定复用范围；配置激活更换绑定时同时丢弃旧目录，不跨不同认证身份复用。原始 TTL/cacheScope 等不进入模型反馈。
- 一次 Action 使用取得的目录完成本次局部工作；不因 TTL 为零在同一次操作中循环刷新。变更/过期使后续访问重新读取，call 按当时取得的定义校验；远端仍可能随后变化，由实际调用结果说明。
- SDK adapter 把现代订阅与旧通知归一为失效线索。监听失败只停止监听并使目录失效，后续显式操作按需读取，不创建后台重连/重放循环。

这些是轻量派生缓存规则，既不回写历史 Trace，也不自动扩展 Context。缓存新鲜度、授权范围和无跨页一致性保证来自当前协议；实现按锁定 SDK 的公共能力适配。[MCP 缓存协议](https://modelcontextprotocol.io/specification/2026-07-28/server/utilities/caching)

Phase1 只见 expand 域，Phase2 只见四个本地 Action。远端工具不转换成上千个本地 Action/domain。四个 Action 的反馈继续使用现有 Trace 消费保护和折叠，不新建 expand.tools 或连接状态常驻段。

### 6.4 Schema、结果与副作用

本地 `expand.call` schema 只校验外壳，arguments 保留 JSON 对象。远端 schema 在装入时用标准 validator 检查，在调用前校验输入；有 outputSchema 时也按协议核验结构化输出。默认 2020-12，显式支持的其它 dialect 按 validator 选择；未支持的必需 vocabulary、未解析引用或非法 schema 标为不可调用，不删除约束后继续。

JSON Schema 的共用封装放在 infra 的动态数据边界，MCP owner 解释其失败；不把有限 Action schema 扩张成手写全规范实现。引用解析限于已提供 schema/本地注册资源，不隐式联网获取任意 `$ref`。自定义注释不当成校验约束；`format` 等按所声明 dialect 的断言/注释语义处理。单工具 schema 超过描述/校验上限时，该工具明确不可调用，不返回半个 schema 却声称完整。现代 HTTP 的 `x-mcp-header` 等协议字段由 SDK/adapter 按协商版本解释，不当成普通注释静默忽略，也不复制到通用 Action schema。[MCP 工具 schema 与结果](https://modelcontextprotocol.io/specification/2026-07-28/server/tools)

短文本与结构化结果有界归一；重复表达相同内容时避免向模型重复投影。长文本、图片/音频字节及嵌入资源写入 Workspace，返回可继续处理的 Link/摘要；远端 resource URI 不能伪装成 `workspace:` Link，也不自动读取。stdio 原始日志和协议诊断不进入通用 Context。

远端 isError、无此工具、参数不满足和服务不可用属于局部结果；TinySoul 内部不变量、配置和 Workspace 持久化失败由对应 owner bridge 处理。远端返回的原始异常文本不直接充当 TinySoul failure payload。

一次 call 的运行、超时和取消都归现有 Action 边界。超时/断流只能说明本次未取得可用结果，不能声称远端写入未发生。反馈明确结果未知、可能已有副作用，不自动 retry；外层取消保留已有类型化 ExecutionFact，不伪造工具响应。MCP 声明的幂等/read-only 提示不自行授予框架重放权。

### 6.5 本地、远程服务与用户扩展

两种传输进入同一个 MCP adapter 和 Engine：

| 传输 | 用户提供 | TinySoul 拥有 |
|---|---|---|
| stdio | 本机已安装的可执行程序、参数、可选 cwd 和环境变量引用 | 按需启动的本地进程、双向管道、SDK client 和关闭责任；复用 infra/process |
| Streamable HTTP | MCP endpoint URL、可选静态 headers/凭据引用 | HTTP client 与协议资源；外部服务器本身由用户或供应方运行 |

HTTP 可以访问 localhost，也可以访问远程服务；“本地/远程”不是两套工具目录或调用语义。连接关闭表示释放本地资源，不承诺撤销远端副作用或停掉远端服务器。旧 HTTP+SSE 不额外作为本轮传输选项，避免把它与 Streamable HTTP 的流式响应混同。[官方 Python SDK 传输](https://py.sdk.modelcontextprotocol.io/client/transports/)

配置放在既有合并配置树 `configs/capabilities/expand.toml`，服务为具名集合 `capabilities.expand.servers.<server_id>`，无需独立文档集或新注册中心。以下字段已实现；路径和 URL 仅为示例：

```toml
[capabilities.expand.servers.local_notes]
enabled = true
description = "检索和管理本机笔记库"
transport = "stdio"
command = 'C:\Tools\notes-mcp\python.exe'
args = ["-m", "notes_mcp"]
cwd = 'D:\Notes'
env_refs = { NOTES_API_KEY = "NOTES_MCP_API_KEY" }
tools_default = true
tools = { delete_note = false }

[capabilities.expand.servers.team_docs]
enabled = true
description = "检索团队文档和读取正文"
transport = "streamable_http"
url = "https://mcp.example.com/mcp"
header_refs = { Authorization = "TEAM_DOCS_AUTHORIZATION" }
tools_default = false
tools = { search_documents = true, read_document = true }
```

`description` 是用户给 Agent 的稳定服务用途说明；远端描述按协议取得。传输字段在 owner 入口转为明确 stdio/HTTP 配置类型，不用一个任意 kwargs 对象穿透多层。stdio command/args 直接交进程接口，不拼接为 shell 命令；cwd 是显式稳定服务目录，省略时按项目根解析。R6 不增加 cwd 模板语言或自动把所有 MCP 服务绑定为 Workspace 文件服务。

非敏感固定值可用 `env`/`headers`；`env_refs`/`header_refs` 的 value 为 ConfigEnvironment 环境变量名，装配时解析，引用值覆盖同名固定值。Authorization 引用读取完整 header value（如含 Bearer 前缀），不猜认证方式或再造密钥插值语法。凭据不作为模型参数；既有 secret 脱敏规则覆盖配置和诊断。SDK 的 HTTP 参数与 stdio 环境要求留在 adapter，不泄漏进 Action 外壳。

服务 enabled 是硬边界；启用服务内 `tools_default` 给出默认选择，`tools.<原始工具名>` 覆盖默认，和已有 domain/action 的“默认选择 + 单项覆盖”思想一致。工具名保留大小写和原始身份；含点的 TOML key 必须作为完整 key 引用。配置编辑以整个 tools 映射为值提交，避免把远端名称中的点解释为配置层级。缺省允许启用服务的全部工具；需要固定集合时设置 tools_default=false 再逐项开启，新发现工具因此保持关闭。预配的尚未发布名称不要求在配置保存时联网证明存在。

实际允许集合由服务启用、工具选择、profile 服务约束共同确定；本地 expand Action 的 domain/action visibility 仍沿用原机制。过滤结果同时用于搜索、描述和调用，已知隐藏工具名不能绕过调用检查；本轮不增加第二套远端工具情景策略矩阵。

用户扩展步骤：

1. 准备服务：安装本地 MCP 服务及其运行环境，或取得远程 MCP URL；自定义工具通过用户自己的 MCP 服务发布。TinySoul 的 expand Action 不负责安装包、启动网页登录或从互联网注册中心自动接入服务。
2. 在 expand.toml 新增 server_id、传输、用途与选择；按需在既有 `.env`/进程环境中提供凭据。生成模板纳入正常 config.include，不另读一份私有 JSON 配置；用户拆分多个 TOML 时仍使用项目原有 include 机制。
3. 使用现有配置候选保存和空闲时 reload。补充 MCP 服务 collection/field descriptors，使 SDK 和 `/v2/config` 可编辑这些条目；不新增 `/mcp/register`。候选校验只检查本地配置、必要依赖和引用就绪，不联网枚举工具或启动服务。服务启用后连接失败是该服务的局部 unavailable，不阻断其它正常工具。
4. 首次 `describe_servers`、`describe_tools`、`search(query)` 或 `call` 按需连接/列举。服务通过 tools/list 暴露的新工具自动进入 owner 目录，再应用配置选择；无需为每个远端工具写 Action TOML、Python executor 或修改 TinySoul PluginDeclaration。服务增加/删改工具由同一刷新规则处理。

上述流程已通过具名配置、候选校验、重载解析和本地协议测试核对。外部工具依赖由 `.[external-tools]` 安装，开发 extra 包含它；默认模板不启用目标或服务。

### 6.6 支持范围

R6 聚焦工具能力。resources/prompts 的主动浏览、sampling、交互式 elicitation、现代多往返请求的自动续交、长任务/Tasks、OAuth 登录流程和 MCP Apps 均不进入本轮主线。客户端不声明未实现能力；遇到需额外输入/认证/功能的结果，局部明确说明，不能伪装普通成功或启动隐藏子 Turn。

HTTP 支持无认证服务和显式配置凭据的服务；凭据沿用 ConfigEnvironment，模型与 Observation 不获得其原值。服务要完成额外 OAuth 或交互流程时，记录为当前接入边界，后续以独立计划设计。

## 7. 装配、资源生命周期与目录组织

服务在 generation 组合根创建，每个 profile 获得自己的动作视图和服务约束。user、home_reflection、memory_reflection 均可使用已配置的通用 subagent/expand 能力，专属 Home/Memory 写权限不因此扩大。旧 facade 在世代/日切失效后由调用者重新获取。

ACP 与 MCP 的连接生命周期分别留在对应 Engine；协议差异不需要抽象成万能 ConnectionManager。只有受控进程、异步关闭、JSON 校验等真实共用机制进入 infra。MCP 连接允许跨 Turn 复用，但不代表 call 跨 Turn；为保持日工作区绑定明确，本轮日切时统一关闭涉及旧日资源的连接，后续按需重建。

现有 `PluginDeclaration.sources` 继续接收事件来源；generation resource scope 接收附属资源释放。对日切前/Turn 收尾必须完成的资源停止，补充窄的 owner 生命周期参与点，消费顺序由 Agent 组合，不把这一职责塞进 Segment.close 或 completion recorder。只有真实未停止执行才阻止切换；普通断连后的句柄诊断不增加恢复状态机。

stdio 使用 SDK 的协议编解码，结合 `infra/process` 的单一平台进程所有权提供双向管道。SDK 已有公共传输入口优先复用，避免读取文件尾充当流或把同步 spawn helper 外包给线程。进程组/Windows Job Object 的创建和后代回收只留在 infra，协议插件不复制平台代码。SDK 自带只关闭根进程的 helper 不能直接当成整个执行单元已回收的证明。

建议内部组织如下；真实文件按职责创建，不把目录树当必须创建全部文件的模板：

```text
plugins/capabilities/subagent/
  engine.py / config.py / actions.py / failures.py / runtime_bridge.py
  acp/          # SDK 适配、会话、反向请求；目标差异留在此处
  jobs/         # ACP backend 与输出收集
  segments/     # connections provider 与 State 视图
plugins/capabilities/expand/
  engine.py / config.py / actions.py / failures.py / runtime_bridge.py
  mcp/          # SDK client、传输接入与类型归一
  # 目录与结果归一内聚于 engine；共用 JSON Schema validator 位于 infra/json
```

配置继续是 `configs/capabilities/subagent.toml`、`expand.toml` 中的对应 `[capabilities.*]` 子树；每个 owner 自己解析。Action 定义放在 `assets/common/configs/action/catalog/{subagent,expand}/`，领域 Skill 放在既有 skills_domain 目录。standard/development 提供环境预设，不复制一份 catalog。

本地 domain/action 开关沿用“domain 提供默认选择，单动作覆盖”与情景可见性。远端服务启用、目标筛选与可选工具限制属于 expand 配置，不为每个发现工具生成第二份 TOML Action。新增配置描述、候选校验、生成资源及必要前端协议说明一并同步；不编辑 visualization。

SDK Job 投影与现有 `/v2` Job 查询同步增加有界待答/结果字段；Agent 与 Endpoint 都读取同一 owner 投影。ACP 原生回应由父通过 subagent Action 完成，不新增通用 `/jobs/respond` 或远端任意工具执行 HTTP API。人的参与复用现有 ask/reply；其它没有真实客户端消费者的 ACP 专用路由不预建。

## 8. 失败处理约束

| 情况 | 归属与处理 |
|---|---|
| 模型给出未知目标、busy connection、旧请求 id、参数/schema 不满足 | 当前 Action 局部结果，提供有限可修正说明 |
| 外部服务拒绝/不可用/协议任务失败 | ACP Job 或 MCP Action 的有限失败，保留已取得材料 |
| 配置非法、启用能力缺少依赖、注册矛盾 | owner 装配失败，经既有 Runtime bridge；不降级成正常成功 |
| Workspace 读写失败、Job 监督不变量破坏 | 相应 owner bridge；不统一捕获包装成 external unavailable |
| 用户取消/Turn 结束 | 现有取消与收尾协议；未决反向请求结清，执行停止并 join |
| 已断开的传输附属释放诊断 | 有界诊断，不撤销已经获得的业务结果 |
| 执行仍无法停止、会继续访问旧 Workspace | 保留必要失败并阻止错误地越过生命周期边界 |

只增加能解释上述实际路径的有限失败标识。取消不能被 catch Exception 吞掉；原始 traceback/异常链只用于调试，模型反馈不承担 session token、RPC id、schema version 或恢复算法。

## 9. 实施顺序与验收

| 编号 | 状态 | 实施范围 | 验收证据 |
|---|---|---|---|
| R6-0 | done | 锁发布包与首个 adapter；验证 stdio 公共入口、权限、prompt 终态、取消、session 释放、后台资源关闭和新 session 隔离 | ACP 0.12.1、Codex ACP 1.12.0/Codex 0.154.0；真实握手/session 探针；发布源码与 SDK fixture 验证后台执行扩展；实际模型委派单列未运行 |
| R6-1 | done | 统一异步 JobBackend、混合 Registry、待答投影与 Inbox/Job wait 唤醒 | Process 与 ACP backend 共用 Registry；待答、停止、终态、容量及类型边界测试通过 |
| R6-2 | done | stdio 受控传输与必要插件资源关闭接点 | Windows 实进程后代回收、双向管道及根退出后后代停止；ACP Turn 收尾；既有进程日切/重载回归；组合根核对必要关闭先于归档 |
| R6-3 | done | subagent 全链路、connections 段、权限与结果材料 | 本地 ACP SDK fixture 完成 connect→delegate→待答/respond→collect→同 session 新 delegate→新 Turn 新 session→停止；包含后台任务扩展、无响应取消和段 prepare/install |
| R6-4 | done | expand 两种传输、统一目录、发现/批量描述/调用、schema 与结果；采用 Q4 与 Q6 已确认策略和四动作入口 | MCP SDK 2.2.0 stdio/Streamable HTTP fixture；schema、长文本/图片 Workspace、isError、工具选择、上游分页/TTL/通知失效、写后断流不重放及一次 LLM 选择/容量返回 |
| R6-5 | done | 三种情景、配置/资源生成、SDK/Endpoint 投影、文档与门禁 | 配置映射/凭据脱敏、候选拒绝不落盘、三情景可见性、公共 Job 投影、设计与 Endpoint 文档已核对；Full 1130 passed、23 deselected，Windows/Linux 目标类型检查与生成/wheel 通过 |

R6-1 的必要公共接口先完成，再分别接入 ACP 与 MCP。单项已通过即记录，不以重复全矩阵验证代替实现推进；只有新的代码或证据才扩展测试。

代表性稳定契约测试：

- ProcessJobBackend 与 ACP backend 共享受理和生命周期；错误种类访问不可绕过 Turn 所有权；终态与关闭不互相伪造。
- 父正在 core.job.wait 时，权限请求进入 jobs/Trace 并唤醒；父暂停预算时请求保留；回复后子继续，停止时取消待答，事件不另起根 Turn。
- 同连接连续两个 Job、空闲连接不阻挡 answer、新根不继承旧协议上下文；跨午夜活 Job 仍用旧日，清理后才能切日。
- 真正的 ACP prompt 响应决定执行结果；流中的 idle/文本不能构成替代终态；后台资源与不响应取消分别验证有界收尾。
- MCP 工具同名不同 server 不冲突；多页目录、TTL/通知失效刷新、撤销工具和有限 schema 组合/ref 校验，不能把远端复杂 schema 当本地子集通过；不把完整本地遍历误报为远端跨页事务快照。
- describe_servers 覆盖服务筛选、目录按需读取、部分服务不可用和工具摘要分页；不调用 LLM，未取得的目录不伪装成空集合。
- describe_tools 覆盖单工具、跨服务工具列表与整服务范围分页，部分身份无效时其余定义仍可用；定义不截断，过期续页有明确反馈。
- search 使用现有 LLM Action 路径，query 与候选目录只在局部 TaskPrompt 挂载；候选身份校验、完整定义由 owner 返回，search→call 无强制 describe_tools 中间步骤，输入容量不足时给出真实范围与缩小提示；测试不固化模型排序措辞。
- 服务具名集合通过原配置候选/reload 生效，凭据引用只在装配解析；tools 默认选择与单项覆盖在发现/描述/调用上一致，含点原始名称通过完整映射编辑，不绕过约束。
- MCP 正常结果、isError、结构化输出、图片/长内容落 Workspace；超时或断流不重放写调用；传输诊断不污染模型语境。
- 现有 User/Home Reflection/Memory Reflection 主线及 R5 restart/readiness/wait_for_exit 回归；测试针对协作边界，不复制各 owner 的全部用例。

日常先聚焦路径，再 Fast；实施完成前必须运行：

```powershell
.\scripts\test.ps1 -Suite Full
.\scripts\typecheck.ps1
```

真实 adapter/provider smoke 属 external，显式开关、实际环境与结果单列；离线 fake +真实 SDK 通过不等于真实 Codex 端到端已验证。若未跑真实外部 smoke，不据此声称所有真实 adapter 已可用。Linux 目标 typecheck 与 Linux 实机验证分别记录。

实施同步：更新 `docs/design/execution.md`、`capabilities.md`，补充 subagent/expand 设计；按实际接口影响更新 agent/environment/action/infra 与 `docs/endpoint/`。AGENTS 只补当轮已落实事实，整体旧术语重写仍归 S7。逐项确认实现、文档和门禁后，本子计划标 done、文件名加 `-done-` 并移到 done/，主计划 S6 才更新完成状态。

## 10. 待讨论点与已确定边界

| 编号 | 状态 | 建议与影响 |
|---|---|---|
| Q1 | decided（2026-09-21） | 首个真实目标选择 `agentclientprotocol/codex-acp` 的已发布版本，ACP Python SDK 先验证 0.12.1；其它 agent 后续按同一 adapter 边界接入 |
| Q2 | decided（2026-09-21） | R6 暂不开放运行中 send/steering；原生权限通过 respond，普通追加工作在当前 Job 结束后使用同 session 新 delegate。候选 steering 可隐式 startedNewTurn，不满足当前 Job 追加契约；已同步主计划动作草图 |
| Q3 | decided（2026-09-21） | 原生权限请求默认交父 Agent 决定，需要人时复用 core.ask；显式配置可使用 adapter 自动许可，不自动批准持久规则修改 |
| Q4 | decided（2026-09-21） | 自然语言搜索采用有界的一次 Action 内 LLM 选择，owner 返回原始定义；超预算由父 Agent 缩小服务范围。不静默初筛或新增向量索引，见 §6.2 |
| Q5 | decided（2026-09-21） | 已确认 servers 的职责需要独立、清晰的目录入口；不保留旧 `servers` 名称作为兼容别名 |
| Q6 | decided（2026-09-21） | 四动作定稿：`describe_servers/describe_tools/search/call`。服务目录与定义按需读取，工具身份结构化且可跨服务批量，search 只接受语义 query；不保留三动作旧接口，搜索算法不变 |

MCP 的 tools-only、stdio + Streamable HTTP、具名服务配置与工具选择、显式凭据而无 OAuth 工作流是本轮已确认并实现的范围；后续服务需要其它能力时另行明确范围。配置字段不增加逐字段审批，继续服从上述所有权与调用语义。

以下不再作为待确认点：单根 Turn；Job 不跨 Turn；同日/同世代轻量复用与不可复用即关闭的 Q8 原则；新根新 ACP session；实际 Workspace 与受信主机；Reflection 通用能力叠加；配置/domain/action 的现有归属与覆盖选择；无内部子 Turn 预算树。

## 11. 设计预览核对记录

- `done`：重新阅读 AGENTS.md，包括过渡期条款；核对主计划 S6、已提交 R5 修正和功能规划相关意图。
- `done`：定位 Job 同步 backend、进程专属装配、待答唤醒、stdio 与完整 schema 的真实接入缺口。
- `done`：查验上述官方协议/SDK/adapter 文档；发现 steering 隐式新工作和后台执行的具体语义，写入资格验证及讨论点。
- `done`：Q1–Q3 已确认；同步主计划的 send 范围，记录首个目标与权限默认语义。
- `done`：区分主计划要求与本轮实现细化；明确前台结果返回、异步等待和同步快照的不同语义。
- `done`：基于已提交 `4501546` 再次核对目录、LLM Action、配置集合/候选/reload；补充官方工具发现实践、传输与缓存协议的研究，写入四动作、批量描述和用户扩展预览。
- `done`：配置预览经 TinySoul 环境的 TOML parser 检查，两种传输与工具选择示例可解析；本次仅作计划文档验证，不作为新能力的运行证据。
- `done`：Q4/Q5 已确认并同步主计划；进一步说明服务目录按需读取、工具身份与语义搜索的关系。
- `done`：Q6 四动作接口已确认并同步主计划；旧三动作和无 query search 表述已清理。
- `done`：R6-0–R6-5 实施、设计文档同步、必要验证与主计划验收。最终标准 Full 1130 passed、23 deselected（含 5 项 Generation/wheel），Windows/Linux 目标 typecheck、diff-check 通过；命令使用 TinySoul Python。早期 Fast 1118 passed、28 deselected，之后新增测试由最终 Full 覆盖。MCP stdio/HTTP、JSON Schema、Windows stdio 后代、ACP SDK fixture 和 Codex ACP 1.12.0 handshake/session 探针分别记录；真实模型 provider/network 与 Linux 实机未运行。

本轮实现已接入：异步 Job、ACP/MCP owner、配置与 catalog、Workspace 结果投影、Action/Segment/Endpoint 文档均已同步；没有建立第二套调度器、远端工具 Action 集合或模型可见的内部 schema/revision 协议。真实 Codex 只完成握手/session 生命周期探针，未运行真实模型委派；未宣称 provider/network/Linux 实机已验证。本轮归档，主计划 S6 标 done，S3 的 Organize/注释层与 S7 保留原范围。

## 12. 实施核对与边界

| 稳定契约 | 实现与核对位置 |
|---|---|
| 同一 Job 生命周期与容量，前台命令仍等待结果 | `kernel/jobs/{models,registry,actions}.py`、`plugins/execution/{engine,backend}.py`；`tests/kernel/jobs/test_registry.py` 与真实 execution 回归 |
| 待答元数据可靠保留，父等待可唤醒 | `kernel/loop/interaction/inbox.py`、JobInputRequest/JobSnapshot；普通 Inbox 满载下的待答与终态测试、ACP permission fixture |
| Connection/session/Job 分工；段只投影 | `plugins/capabilities/subagent/{engine,acp/connection,jobs/backend,segments/connections}.py`；真实 SDK fixture 验证连续委派、session 释放/隔离、后台停止、无响应取消与段刷新 |
| stdio 只有一个平台进程 owner | `infra/process/stdio.py` 共用 Windows Job Object/POSIX process group；`tests/infra/process/test_stdio.py` 在 Windows 验证双向协议、活根及根退出后后代回收 |
| 四动作同一目录、完整定义与标准 schema | `plugins/capabilities/expand/{engine,actions,mcp/client}.py`、`infra/json/schema.py`；stdio/HTTP 本地 SDK server、目录分页/TTL/通知、非法 schema、工具选择与结果归一测试 |
| 一次有界搜索，由父 Agent 缩小范围 | `LLMActionTaskRunner` 与 `ModelContextOverflowPolicy.RETURN_FAILURE`；Action 数据流/候选身份/反馈大小及真实 LLMTaskRunner 输入容量预检测试，未用 fake 排序宣称真实检索质量 |
| 配置统一加载、候选不触发服务、凭据不投影 | `infra/config` 的 object 字段边界及 credential reference；capability owner 的依赖/引用校验；`tests/plugins/capabilities/test_external_config.py` 验证含点/数字工具名与失败候选不落盘 |
| 三情景通用能力与专属权限分开 | `agent/composition/actions.py` 的显式 PluginDeclaration；`tests/agent/composition/test_builder.py` 覆盖三种情景，不增加 Reflection domain 或动态远端 Action 注册 |
| Turn/日/世代关闭顺序 | `AgentTurnActivity`、`AgentDayCoordinator`、`RuntimeGeneration`；必要执行关闭先于 Workspace 最终同步/归档/旧世代释放，附属诊断不冒充执行未结束 |
| SDK/Endpoint 无平行执行入口 | JobSnapshot 的 pending_inputs/result_links 直接进入原有 Turn 查询；父通过 respond，人的参与复用 ask/reply；无 ACP/MCP 任意执行路由 |

设计文档：`docs/design/capabilities/{subagent,expand}.md` 说明实际 owner、数据流、配置与结束边界；execution、agent、action、infra、llm 与 Endpoint configuration/runtime 同步实际协作。AGENTS 只追加 R6 落地事实，S7 的整体术语整理不提前扩大。

实现细化：不创建没有真实消费者的 expand/tools 空包，目录与投影目前由 Engine 内聚；Codex 扩展只在 ACP adapter 内解析，未扩展 kernel Job 树；MCP 本地分页保存有限临时引用，不引入模型侧 revision/CAS。配置目录每次项目加载只读取一次并显式传给各 TOML source，没有导入期全局缓存。

回归收口：修复无响应 ACP 取消时 prompt 错误收尾被打断后残留 running 状态；WebSocket 验收按时间等待事件，不以心跳帧数量限制合法重载时长。首轮 Full 出现过 execution 启动后的 Workspace 同步失败，保留工件，13 次独立复测和随后 Full 未复现其具体 IO 原因；检查同时发现活动 Job 期间强制完整扫描的过强约束，已按既有 owner 的“不完整扫描保留索引”语义处理，并在跨日真实进程测试中确定性注入不完整扫描保护这一正常路径。最终 Turn 同步仍要求执行已停止且扫描完整，不吞真实 IO 异常。

外部验证边界：选定 Codex 发布包真实启动、初始化、close_session/new_session 探针通过；实际 prompt 行为通过公开 ACP SDK 的本地 fixture 验证。未运行真实模型委派、远程 MCP 服务或中英文语义检索质量评估，未运行 Linux 实机。Windows/Linux 目标 typecheck 与 Linux 实机能力分开记录。
