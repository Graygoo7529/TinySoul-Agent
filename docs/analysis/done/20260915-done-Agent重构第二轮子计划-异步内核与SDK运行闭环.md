# Agent 重构第二轮子计划：异步内核与 SDK 运行闭环

状态：`done`（R2.1–R2.8 的实现、文档与必要验证已逐项核对，第 24 节为完成证据；历史切片状态仅表示记录时点，不代表当前缺口）。
日期：2026-09-15。
主执行计划：[Agent 架构重构](../20260915-agent-architecture-refactor-plan.md)。
前置成果：[R1 底层依赖与失败协议](20260915-done-Agent重构第一轮子计划-底层依赖与失败协议.md)。
初次审阅基线：本地 `6821983`，当时工作区干净；本次继续实施基线为 `7fe426a` 及已有未提交改动。未查询远端。

第 12 节继续实施基线为已提交的 `f616fdb`，开始时工作区干净；第 11 节保留前次核验记录，不作为当前门禁结果。

## 1. 推进结论与范围提案

建议第二轮交付一个可实际嵌入运行的 Agent：通过 SDK 提交 User 或 Reflection work，经同一异步 Turn/Cycle/Phase 内核执行；可以提问、追加输入、等待事件或定时器、预算暂停、补额和取消；使用真实领域段与进程 Job，最终保留可解释的完成事实并回收资源。

主要覆盖 S1 剩余 async/事件/取消与 S2 的内核、SDK、段、Job、CLI 和全部旧消费者迁移。这是一次基础架构迁移，规模明显大于 R1，需要分成依赖明确的实施切片；不能用新增 Agent 门面包裹旧 Program/Loop，就将其视为 SDK 化完成。

主计划依然可行，但 S2/S3 的交界需要在本轮明确。Session 的新完成记录和基础 Map、Reflection 的统一终结意图与专属写域，直接影响新内核的完成协议和插件服务权限。建议把这些必要契约项纳入 R2，按原主计划目标实施；它们属于 S3 的部分前置落实，不表示整个 S3 提前完成。具体范围与替代方案见第 8 节，等待本轮确认。

保留 S3 的 Workspace 全量动作/存储简化、Session 整理能力深化、execution 完整领域合并；保留 S4 的真实文件监听与调度深化、S5 的完整 Endpoint v2 路由、S6 的 ACP/MCP adapter。R2 不宣称 SDK 全部长期能力已经建成。

## 2. 当前代码证据与迁移约束

| 当前实现 | 已有设计与实际缺口 | R2 的处理 |
|---|---|---|
| `llm/provider/base.py`、`provider/openai_sdk/clients.py` | provider 和两种 client 均为同步调用协议 | 在原接口上统一改 async，所有 provider/fake/真实测试调用方同步迁移 |
| `llm/provider/openai_sdk/adapters.py` | adapter 只持 SDK 的 responses/completions 子对象，缺少显式父客户端关闭责任 | 明确 owned/borrowed client，世代只关闭自己拥有的客户端 |
| `llm/task.py::_invoke_provider` | 用 daemon thread 等待供应商；取消后丢弃等待，工作线程仍可能运行 | 原生 async I/O、取消与 deadline 收敛；保留模型链/输出解释/容量度量 |
| `loop/turn.py::TurnActivityController` | 进程监督同时决定额外 Cycle 和下一 Cycle 等待 | 预算归 Loop，Job 只提供事实与就绪条件，取消自动补额 |
| `capabilities/supervised_process/manager.py` | 按 Turn 索引任务，同时拥有进程、等待、监督额度与结果释放 | Kernel Job 监督与执行 backend 分工，统一 Turn 收尾，终态不等 collect 才释放执行句柄 |
| `context/engine.py::consume_signal_batch` | 能捕获/准备批次，但固定解释 Session/Workspace snapshot | 保留批次一致性，由段 owner 准备候选，Context 只协调安装 |
| `context/engine.py::compose` | 固定 inputs/background/working/trace 参数与领域状态 | 段按 slot/order 渲染；Engine 事实与本轮加载视图分离 |
| `action/core/runner.py::_run_one` | 未知异常、非法结果/身份、trace policy 错配均包装成局部 ActionResult；迟返成功可能改成 timeout | 修正模块失败分类，同时记录实际执行事实并收敛同批其它调用 |
| `session/completion.py` | 从 Phase2 AssistantMessage 与 Phase3 ToolResultMessage 反推配对，缺一项就拒绝整个记录 | 直接消费 typed TurnCompletion；未执行/取消/结果未知不伪造 ToolResult |
| `session/engine.py::record_turn`、`loop/completion.py` | 已有幂等记录与有序完成 pipeline | 保留唯一事实 owner，扩展失败/取消收尾，分开必要提交和资源 close |
| `maintenance/actions.py`、`maintenance/turn/entry.py` | 独立精确动作集、controller 与 maintenance.complete 解释 | 三 profile 共用动作/完成管线；不能仅给旧完成器换名字 |
| `app/generation.py::close` | 逆序关闭但吞掉清理错误 | 继续全部清理，同时保留有限 cleanup diagnostics，不覆盖主失败 |
| `maintenance/archive/engine.py` | 已有 active day lease 与确定性日切 journal | 归 Agent 日协调；保留 owner 存储边界，不随 Memory 事务删除 |
| `endpoint/engine/contracts.py` | 直接依赖旧 App gateway、Turn、Maintenance、Workspace/Generation | 当前 HTTP 消费者必须接入 SDK/公开服务，不能等 S5 才修失效 imports |
| `app/sources/terminal.py` | daemon readline，stop 只置标志，阻塞读取不一定退出 | 终端由 environment 管输入寿命，不能在 restart 中不断遗留 reader |
| `pyproject.toml` | console script 与 catalog package data 固定旧包 | 包迁移必须连同 CLI、init/reset、资源定位与 wheel 验收完成 |

当前 `tinysoul` 中有 78 个文件匹配旧 loop/context/action 的直接 import 文本；这是迁移入口集合，不是完整工作量估计。方法调用、配置、catalog、测试和动态资源定位还需在各切片逐项清点。

R1 已解决 Runtime 向上依赖及主要 bridge 诊断。R2 保留这些成果，不重建集中 bridge；失败 owner 随包迁移，稳定 failure kind 不因机械移动任意改名。旧实现证据只用于找责任边界，不作为保留兼容管线的理由。

## 3. 目标结构与真实消费者

```text
gateway CLI / 当前 HTTP 协议
             ↓ SDK 与公开服务
Agent：装配、根队列、Router、世代、日 lease
             ↓ TurnProfile
Kernel：Turn/Cycle/Phase + Context 段协调 + Action + Job
             ↓ 公共协议
LLM / Runtime / Infra

Plugins：Engine 事实 → Segment 视图、Action、profile/Job 贡献
Environment：输入/事件源 → 注入的 InputPort / PublishPort
```

依赖按主计划的 `infra → runtime/llm → kernel → plugins/environment → agent → gateway` 收敛。真实调用可以向下跨层；SDK 查询服务直接调用公开门面，不通过事件总线模拟 RPC。

- Agent 一个异步事件循环负责受理、根调度与路由。只运行一个根 Turn；等待中的根仍占执行位置。
- Plugin 负责装配贡献，Engine 负责领域事实，Segment 负责一个 Turn 的加载/展开/投影。插件没有语境内容时不注册空段。
- 注册按 declare → resolve → activate：元数据只声明一次，先校验身份/依赖/ref 路由/profile/服务，再激活资源。
- 类型化服务按明确 Facade 类型注入；不让 provider 获取整个 Agent，不在运行期使用任意字符串查询私有对象。
- 注册面按本轮消费者落地。没有真实 ACP/MCP 实现时不注册假连接、假工具或空的 connections 段；Job 由真实受控进程验证。

目录迁移沿用主计划；旧 `app/loop/context/action/endpoint` 等包在消费者切换后删除，不留 import alias。已有领域存储算法直接移动/改造，不复制新旧 Engine。

## 4. SDK 与 Turn 生命周期预览

以下是待确认的职责与签名方向，不是已发布 API；具体类型应复用或替换现有 request/result 对象，不为同一事实建立多套 DTO。

| 入口 | 建议契约 |
|---|---|
| `await Agent.create(...)` / `await agent.start()` | create 读取/校验/装配，start 激活并接受工作；部分激活失败逆序关闭 |
| `await agent.submit_turn(request)` | 明确接受后返回 TurnHandle；有界队列满、profile 不可用等返回 typed rejection |
| `await handle.wait()` / `handle.status()` | wait 返回权威终态，status 是无 I/O 内存投影；等待者自己超时/取消不隐式取消 Agent 持有的 Turn |
| `append_input(turn_id, input)` / `reply(turn_id, question_id, response)` | 返回明确 receipt；严格目标身份，不能把迟到回复偷偷变成新根输入 |
| `cancel_turn(turn_id)` | 幂等请求取消，随后通过 handle 等待实际资源收尾；受理取消不等于已经停完 |
| `grant_cycles(turn_id, request_id, count)` | request_id 绑定 Loop 发出的预算请求；同一决定重试不重复加额，冲突 count 拒绝 |
| `status()` / `subscribe(filter)` | 权威活动快照与旁路 Observation 分开；慢订阅可 gap，不阻塞业务 |
| `patch_config(...)` / `reload_config()` | 保存候选与激活分离；活跃/等待 Turn 持世代 lease，激活返回 busy |
| `shutdown()` / `restart()` | 停受理、取消/回收工作、关闭服务；restart 后重装配，旧句柄保持原结果，不复活旧 Turn |
| `publish(event)` / `services.get(FacadeType)` | 外部事实入口与领域服务入口分开；外部 source 无权伪造 Job 终态 |

UserRequest 与 ReflectionRequest 采用明确类型，后者携带 target/source day；活动日由 Agent 决定。profile id、来源、输入结构在入口校验，不用万能 metadata 控制权限和日期。

生命周期状态与执行结果分离：created/running/stopping/stopped/faulted 属 Agent；queued/preparing/running/waiting/finalizing/finished 属 Turn；INPUT/EVENT/TIMER/BUDGET 是等待原因。TurnResult 分别报告执行 outcome、必要提交失败和 close 诊断；执行回答候选不等于正式回答已发布。

建议默认 ask 无超时；profile 可设置等待上限。达到上限则以 awaiting_user 等明确终态记录事实并回收 Job，后续回复须显式提交新 work。Handle 的活动记录/已完成结果保留数量有界；活动句柄不逐出，长期业务事实归 Session，不靠 Observation journal 补状态。

## 5. 统一等待、事件与预算

Runtime 提供事件 envelope、过滤与异步分发基础；Agent Router 管目标与注册；Kernel TurnInbox 管接收批次/确认/等待就绪。Signal 仍表示 owner 更新，Observation 仍是旁路，各自不冒充彼此的事实或控制权。

Inbox 从 Turn 受理身份登记后持续存在。排队请求与活动 Turn 的输入保留由调度层明确负责，不能返回 accepted 却在开始前丢掉追加。初始/追加输入正文归 inputs，Trace 只引用输入身份和发生顺序，不复制第二份正文。

批次流程：捕获固定批次 → 路由 typed 段更新 → 全部 prepare → install → ack。prepare 等待期间到达的新记录留在后续批次；不把新进度合并覆盖正在处理的批次。prepare 失败重试同批，已提交 Action 不重做。内部非法更新是契约失败，模型可修正控制才是局部结果。

等待只观察就绪，不能抢走更新消费者的数据。登记前检查、登记与复查位于同一事件循环；EVENT 使用接收游标 after_seq，终态通过 owner 状态立即可见。取消为独立控制状态，不排在进度队列后。

Cycle 完成后先消费结果/输入，再评估完成或等待意图；下一 Cycle 尚未启动时检查预算。不足时由 Loop-owned reason 经 Trap 返回只指向合法 Turn frame 的 SUSPEND，Loop 保留 next_cycle_index 与未满足条件。普通等待与预算暂停复用同一等待流程；事件就绪不能绕过未解决预算。删除进程监督的 allow_additional_cycle，不给模型自动补额能力。

容量按总条数、总字节、单条大小、活 Job/问题数配置：输入/回复/预算决定接受前拒绝或背压；Job 终态与待答身份按活任务配额预留；进度只合并未捕获记录；大输出由 owner 落盘。具体默认值在假源压力测试后确定，不作为已验证生产参数。本轮不增加 Inbox WAL 或崩溃 continuation。

正常完成在一个受理边界上复查关键输入与活 Job；新输入使完成候选失效并继续。活 Job 阻止正常回答，模型选择 wait/stop。取消/失败停止普通受理，但保留内部清理终态通道，直到回收、消费与 seal 完成才注销 Inbox。最终 seal/提交之后到达的请求明确返回 too_late/closed，不反向改写完成事实。

## 6. 执行、取消与完成事实

### 6.1 一条异步调用链

Provider → LLMTaskRunner/模型链 → Phase 与内部 LLM Action → Cycle → Turn 全链统一 async。消息、工具映射、schema、模型路由与解释算法继续复用；provider/模型链等待改为可取消异步等待，不新增同步 runner 或每次调用 asyncio.run。

供应商客户端创建与关闭归世代内的 LLM 服务；注入 client 默认借用，只有明确 owned 的对象才随世代关闭。现有配置描述的 provider 能力必须保留，不能仅跑通 fake 就删除某个已支持 adapter。第三方 async client 的准确调用/关闭接口在 R2.1 以安装版本、官方资料和 fake client 核验，本文不声称已完成外部协议验证。

混合 owner 方法必须拆出真正的 I/O 边界：Home search、Memory daily composition、Workspace/Script 的 LLM 辅助操作分别完成局部读取、await LLM、owner 提交。不能把包含网络/模型调用的整个业务 executor 丢进 to_thread。

短 owner 调用采用同一通用异步适配：开始前检查取消；已开始则保留 future，等待该调用完成并记录实际提交结果，再传播取消。单独 shield 或丢弃 await 不算收尾。长计算/脚本/shell 使用受控进程，可取消网络使用原生 async；删除失联线程仍继续写入而 Turn 已终结的路径。

终端输入是独立环境 I/O，不属于短 owner 调用；必须有可停止的平台读取方式或可回收的受控输入资源。Windows console、重定向 stdin 与测试 stream 分别验证退出；不以多起 daemon reader 实现 restart。

### 6.2 三层失败与部分批次

| 情况 | 结果与传播 |
|---|---|
| 模型协议/Action 参数不合法、已知业务拒绝 | typed 局部结果，下一完整 Cycle 反馈 |
| 未知 executor 异常、非法返回/身份、catalog 或 trace 契约破坏 | Action 模块失败，经自身 bridge 退出；不是普通 executor_raised |
| RuntimeException / 已解析 TransferInterrupt | 保持身份，收敛同批工作后传播，不重入 Trap |
| 所属 Action deadline | 归 Action 超时；仍记录超时前已经提交的已知事实 |
| Turn 取消 / asyncio 取消 | 保持取消来源与传播，停止安排后续工作，收回已启动工作；不全部包装为工具超时 |
| owner 短操作结束后发现取消 | 保留已经提交的真实结果，Turn 可以 cancelled；不能把已成功写入伪装成未执行 |
| close 失败 | 继续其余 close，附有限诊断；不覆盖执行或必要提交失败 |

Action 框架继续只有一套批次/调度生命周期。ActionResult 表达一次已归一化调用的局部结果；执行事实另外表达 cancelled/not_executed/unknown 等中断状态，不能为补齐模型 tool 配对伪造结果。

typed Trace 是当前 Turn 执行事实的唯一 canonical owner。Phase2 归一化后登记调用身份，执行边界登记启动与实际结果；部分批次异常也要在传播前交付已收敛事实。同一 Trace 的折叠只改模型投影；Session 不再解析 AssistantMessage/ToolResultMessage 猜执行情况。调度器可持活动 future/引用，但不另写一套持久 execution ledger。

实现时必须在 Trace owner 内明确 canonical 事实写入与 Segment 安装投影的边界：执行事实不能因 Context prepare 失败而丢失，也不能让外部监听任务任意修改段视图。注册的 typed 事实入口由 Trace 消费，视图在 Context 边界刷新；两者引用同一组事实身份。

### 6.3 收尾和记录

统一顺序：关闭普通受理 → Action/Job 收敛 → 消费已接受关键终态 → seal → TurnCompletion → 按依赖 finish（Session 最后记录）→ 全部 close → 释放 day/世代 lease → 完成 TurnHandle 并发布观察输出。

User 的 answered、cancelled、failed、awaiting_user 都保存可解释事实；queued 阶段未开始执行的取消只作为请求结果，不伪造空 User Turn。必要 finish 失败阻止成功发布；可写 Session 时记录既有失败事实，Session 自身写失败则通过 handle 明确报告，不能保证不存在的持久记录。

Session record 按 turn_id 幂等提交，确定性 Map 可补建；模型注释独立保存但始终指向原事实，不可当派生缓存删除。close 失败不再次提交 Session，不把已经持久完成的记录改写为另一个失败 Turn。

## 7. 段 SPI 与插件接入预览

注册对象唯一声明 id/owner/slot/order/shape/profile/ref 路由及可选能力；provider 负责 open 本轮实例，不再维护第二份可分歧 descriptor。Engine 可以跨 Turn，Segment 不复用到下一 Turn。

- 基线：provider.open、segment.render/seal/close；部分 open 失败由分配资源的一方收回尚未交出的对象。
- 更新：带具体更新类型的 prepare/install 配对；prepare 不改持久事实或活动视图，install 不 await/I/O/调用外部代码。全段准备成功才安装；安装程序错误结束 Turn，不虚构跨段回滚。
- 能力：load/evict/inspect/organize/reclaim 按实际用途组合；不使用包含大量空方法的基类。
- 泛型更新入口在注册时绑定 owner 的更新类型与 handler；公共 API 不退化为任意 dict/object。异构调度必要的类型封装局限在已校验的 registry 边界。
- render/seal 是纯内存投影，TaskPrompt 是临时 overlay。shape 参与通用检查/回收，内容算法仍属 owner。

| 段 | owner 与真实输入 | R2 要完成的作用 |
|---|---|---|
| identity / inputs | 内核；Home identity provider / 已接受输入 | State，必要内容保护、单一输入正文事实 |
| trace / plan | 内核；typed 执行事实 / todo 与 milestone | Stack 与 State，折叠不破坏事实，milestone 不等同完成 todo |
| home | Home Engine | Heap，目录、加载/逐出、overlay 刷新与 Skill 局部挂载 |
| memory | Memory Engine | Heap，current/target/latest 保护与 inspect/recall 刷新 |
| session | Session Engine | Map，基础问答/Action/资源关联与有界 inspect，不混入当前 Turn |
| workspace | Workspace Engine | State，资源 Link/summary；正文留在显式 Action 读取 |
| jobs | Kernel JobRegistry | State，真实进程 Job、待处理请求、终态摘要 |

统一 core.context.inspect 路由到声明的 ref handler；ordinary Workspace read 与 Home Skill mount 不变成通用 Context 读取。后续 organize 算法落地时由 Session 注册，不在 R2 注册空动作，也不能放到纯 prepare 中偷偷写磁盘。回收保持 State/Heap/Stack/Map 策略和最低语义保护，无实际进展结束恢复。

需显式迁移所有能力 Actions 的 Context/TaskPrompt/Workspace 通知依赖；旧 ContextEngine 不能作为黑盒塞到一个“领域段”里。新增普通领域只注册贡献，不修改 composer/Loop 的 owner 分支。

## 8. S2/S3 交界：建议一起批准的必要前置项

| 项目 | 建议纳入 R2 | 后续仍保留 |
|---|---|---|
| Session | 新 typed record/schema，失败/取消/ask/reply 记录；基础确定性 Map、统一 inspect；删除并行线性 Summary | organize 的 thread/gist/推导关系完整操作与大图聚合策略深化；默认待整理标记指向上一成功 User Turn |
| Reflection | 三 profile 共用内核与 core.answer 完成意图，模型 prompt/schema 同步；通用域 + 各自最小专属域 | 手动重整/自动触发策略、完整知识沉淀行为与提示验证继续按主计划深化 |
| Memory 写契约 | 为 write_daily/write 直接形成单文档 owner 写入边界，移除被替代的 stage/preview/commit 控制器、对应多文档事务与无消费者版本字段；同步活动记忆写入口 | 检索/注释/沉淀体验等领域深化；任何已无消费者旧字段当轮删除，不延期清垃圾 |
| Home | diff/review 复用既有 overlay/review 服务；统一选择项与逐项结果，不复制专属 done | Home 语义细化与使用体验；actual/overlay 的 owner 一致性校验继续保留 |
| 进程 | Job backend 接入、Turn 生命周期、公共 status/stop/wait 和既有执行能力迁移；移除自动监督补额 | script/shell 的完整动作命名合并与领域目录清理按 S3；迁移后的活动实现仍唯一 |
| Workspace | 段与公开服务迁移、短 owner 操作取消、真实资源通知 | 全量 write/edit/list/tag 等动作调整、删除 CAS/read-set/压力 Trash 等存储语义按 S3 |

R2 的 Memory 前置项是实际范围增加，不能在实现时悄悄纳入：仅把旧 8 步控制器搬进插件再重命名为 Reflection，会让新 profile 继续依赖旧完成步骤；仅加 write 外壳、内部仍拼旧事务，会留下两套写语义。建议本轮按已确定目标直接替换这组契约。

如果希望第二轮严格不包含这些 S3 项，可以先做 S1 剩余及 S2 的部分迁移，并明确把“完整三 profile SDK 闭环”作为下一轮交付；不能一面缩小范围，一面宣称 S2 整体完成。本文推荐完整闭环方案，但这项范围选择须由维护者确认。主计划无需重排 S0–S7，只在实际落实后标记对应子项。

Reflection 的 source_day/active_day 分离：历史 Session/Workspace 是只读参考，当前 Workspace 仍为工作台。User 不获得持久 Memory/actual Home 的写服务；Reflection 不是只能调用专属工具，也不默认等待人工审批。core.ask 可用于确有信息缺口；core.answer 在 Reflection profile 表达总结完成，不发用户回答、不写 User Session。

CalendarDay 与日切组合根归 Agent，保留 Archive journal、owner 原子替换和 lease。新 Session schema 不静默读取/转换 v4，不自动 reset 真实数据；开发验收使用独立初始化目录，部署与数据迁移不属于本轮实施授权。

## 9. 实施切片与验收

R2.1–R2.8 为 `done`，逐项完成证据见第 24 节。切片用于审阅和验证顺序；中间状态不宣称可部署，不长期保留旧管线作为转发器。

| 切片 | 可审阅产物与删除项 | 验证重点 |
|---|---|---|
| R2.1 | 原生 async LLM/模型链/client 生命周期，通用短 owner 适配；同步迁移 LLM 调用者与 fake | 取消 during I/O/backoff、迟返、客户端借用/关闭、容量重建、无 orphan provider thread |
| R2.2 | typed 调用/执行/TurnCompletion；Action 分类与并发收敛；取消统一边界 | 先前成功保留、未启动/未知事实、兄弟任务收回、控制身份、迟返已提交写入 |
| R2.3 | Kernel 段注册、组合、typed 更新与 prepare/install；核心段 | 后段准备失败不安装、同批 retry/new event 隔离、install 缺陷不重放、纯 render |
| R2.4 | 真实 Home/Memory/Session/Workspace/能力插件接入；第 8 节确认的相邻契约 | 无领域特判、User 写权限、三 profile 同管线、Session 失败/取消记录与基础 Map |
| R2.5 | EventBus/Router/TurnInbox、进程 Job；统一 INPUT/EVENT/TIMER/BUDGET 与 SUSPEND | 登记/到达竞态、终态预留、重复 grant、满载取消、Job 不跨 Turn、已接受输入不丢 |
| R2.6 | Agent SDK、根队列、世代与日 lease、创建/激活/停止/重启、服务门面 | create 不监听、单根等待排队、等待者取消不取消 Turn、跨午夜与 reload busy、清理错误保留 |
| R2.7 | CLI/terminal 与当前 Endpoint 全部消费迁移；项目命令/catalog 资源与打包 | 当前 HTTP 协议经 SDK 可用、无旧 App/Loop imports、终端停止、wheel/init/reset |
| R2.8 | 全仓边界与死抽象审计，文档/测试/计划逐项核对 | 聚焦 → Fast → Full → typecheck，三 profile 协作路径与包外 SDK 使用 |

R2.1 的公共异步边界会迫使调用链同时调整，R2.2–R2.6 的类型设计须先形成共同契约预览，再分切片落地；不在第一步留下一个没有业务消费者的 AsyncLLMRunner。每个切片在涉及的全部消费者切换后删除旧实现。

这些切片是验收拆分，不是互相独立的串行包迁移：typed completion、段更新与取消的骨架先共同确定；真实进程/段的首个注册贡献随消费内核一起落地，再扩展剩余 owner。若某个切片必须依赖后一个才能运行，应合并为同一可验证提交，不用假实现填满接口。S1 只有 async、事件、取消的真实消费链均验收后才完成，S2 只有全消费者、SDK/CLI/打包均验收后才完成。

完成基线场景：

1. SDK 提交 User Turn → 真实 Plugin 段与 fake async provider → 执行 Workspace Action → 正式回答 → Session 记录。
2. core.ask → 暂停仍接收环境/追加输入 → 指定 reply → 同一 Turn 继续；新根与 Reflection 保持排队。
3. 真实进程 start → Job 输出落 owner 资源 → EVENT/TIMER 等待 → collect/stop → 资源收回；无 Job 事件隐式创建新根。
4. Budget 不足 → 合法 Turn SUSPEND → 事件积累但不启动模型 → 幂等 grant → 下一未启动 Cycle；cancel 可打断任何等待。
5. 相邻 Action 一个写入完成，另一个内部失败/超时/取消 → 已提交事实保留、其余执行收敛、Session 不因消息缺配对全量丢失。
6. 分别在 LLM I/O、短 owner 写、受控进程、prepare、finish、close 注入失败；必要记录失败不发布成功，close 不覆盖主失败。
7. Home/Memory Reflection 各运行一次完整 work，通用域可用、长期写服务受 profile 限制、完成不进入 User Session。
8. 跨午夜等待、reload busy、shutdown/restart、旧 reply/旧 Job 事件、Observation gap 与慢订阅均符合主计划边界。

测试按 owner 覆盖稳定契约，跨模块只保留代表性协作风险；引入已确认的 pytest-asyncio 作为测试依赖。fake clock/provider/source 用于确定性竞态测试，真实本地进程验证退出；外部供应商/ACP/MCP 不在本轮通过声明中。依赖升级必须先说明真实用途，不顺手更新全部库。

## 10. 文档与本轮分析交付

首次分析只新增 pending 子计划，并修正 R1 的文档状态与交叉引用，未修改生产代码或运行代码门禁。继续实施的变更和验证记录见第 11 节；R1 的门禁结果不冒充 R2 验证。

实施时同步 `docs/design/` 已落地职责、`docs/endpoint/` 当前协议与 SDK 映射、资源与测试。当前 Endpoint 路由继续提供现有功能，删除私有依赖；完整 v2 路由与新增远程 wait/reply/budget 产品协议归 S5，不为迁移保留旧 App 实例。R2 的新等待入口至少通过 SDK 与 CLI 可使用。

重点审计：单一事实 owner、三层失败、无遗留执行、无无效别名、无空 SPI、无 Segment/Engine 双状态、无第二个等待器、无部分提交伪回滚、所有新 py 文件有独立职责。第一轮公开 failure helper 和 owner bridge 继续使用。

维护者已授权按完整闭环继续实施，包括第 8 节必要前置项；不重复申请上述范围确认。只有出现与已确认边界的实质冲突时才重新讨论。

## 11. 2026-09-15 继续实施核验

本节更新当前进度；第 2 节仍是初次审阅时的迁移证据，不能将其中同步 provider 等旧状态当作当前实现。

方案的依赖方向和总体范围可行，无需重排主计划。当前实现仍处于基础迁移，不能把 async 函数、SDK 门面或段注册器单独存在视为闭环成立。

| 检查项 | 当前实现与证据 | 状态与下一步 |
|---|---|---|
| 原生 async LLM | `7fe426a` 已迁移 provider/model chain/task 与调用入口；本次补迁移 App、Home、Memory、Maintenance、Workspace、能力测试的调用与 fake | `in_progress`；重试等待的取消、真实 owner I/O 和客户端世代寿命仍需核验 |
| Action 收敛 | runner 可取消异步执行任务并等待收尾；短 owner 结果在取消传播前记录，兄弟失败保留原控制异常；移除无消费者的 grace 参数及同步 executor 兼容分支 | `in_progress`；多数生产 owner I/O 仍直接同步调用，不能用测试 helper 的 JoinedOperations 覆盖冒充全量接入 |
| 类型化事实 | Trace 以 Cycle/sequence 维护唯一 Action 现态；Phase2 登记意图和归一化失败，Phase3 登记准备失败、启动及终态；Session 直接消费 sealed facts，删除消息配对回退 | 已实现该子项；R2.2 的完整 Turn 结果/必要提交/close 协议仍未完成 |
| Session schema | v5 增加 cancelled/not_executed/unknown；这些状态不伪造 ActionResult 或重试建议；保存 canonical payload 与来源 links，跨 Cycle 重用 call_id 不串记录 | 已实现该子项；尚未实现基础 Map、ask/reply 和 Turn outcome 新 schema 全部内容 |
| Turn task 取消 | 外层 asyncio 取消先结束 Context、运行完成记录、清除活动 scope，再传播取消；已有 failure 优先于回答候选 | 已实现该子项；多 owner finish/close 诊断与失败记录顺序仍须统一 |
| 段注册器 | 工作区 `context/segments.py` 仍是无生产消费者的 JsonObject prepare/render 草稿，没有 slot/shape/open/install/seal 与真实 owner 接入 | `pending`；不得标为 R2.3 完成，也不得把旧 ContextEngine 塞入一个段 |
| 调度与 SDK | Program 仍用同步 Queue/RLock，等待仍含进程监督的额外 Cycle；尚无 Agent SDK、Inbox、Router、统一等待或 SUSPEND | R2.5–R2.7 `pending` |
| 世代关闭 | `LLMTaskRunner.close` 已是 async，但 `AppRuntimeGeneration.close`/配置激活与 CLI 退出没有完整接入；Fast 暴露真实 HTTP 客户端在所属 loop 关闭后回收的错误 | `in_progress`；应把此生命周期链与 R2.6/R2.7 对应消费者合并验收，不能用测试 GC 或每次 invoke 新建客户端规避 |

推进顺序：先把异步世代资源所有权、候选激活与退休、CLI/Endpoint 调用边界作为一个切片闭合；同步拆分生产 owner 的读取/模型调用/提交。随后按 R2.3–R2.7 将真实段、profile、Job、Inbox 和 Agent 装配接入同一运行链，再删除旧包。R2.8 最后检查整个依赖图、业务状态及打包；主计划 S1/S2 此时仍不能标 done。

本次验证：

- 起始 Action 聚焦：9 failed / 126 passed；起始 typecheck：231 diagnostics。
- Action/Context/Session/Loop 最后一次聚焦：271 passed，覆盖异步 I/O deadline、取消及重复取消收尾、并行写提交保留、跨 Cycle 身份和不配对消息的 Session 投影。
- Home/Memory/Maintenance/Workspace/能力聚焦曾发现两处残留同步测试，已修正；后续由全仓门禁核验。
- Fast：985 passed / 1 failed / 2 skipped / 28 deselected；失败为 async HTTP client 跨事件循环关闭，不能声明通过。
- typecheck：通过。
- Full：993 passed / 1 failed / 2 skipped / 23 deselected；wheel/init 验收通过，失败仍是 async HTTP client 在所属 event loop 关闭后回收。失败工件：`.local-test/runs/7859ffad977f4c7ba0472481e25f715a/`。随后只对新增的重复取消竞态进行了上述聚焦验证。本计划保持 `in_progress`，不归档。

没有运行 external provider/ACP/MCP 测试，没有迁移或 reset 用户实际数据，也没有创建提交。

本次修改文件按职责归纳：

- 执行与失败边界：`tinysoul/action/core/call.py`、`core/runner.py`、`tinysoul/action/engine.py`；`tinysoul/runtime/frame_runner.py`。
- 当前 Turn 事实及收尾：`tinysoul/context/engine.py`、`trace.py`；`tinysoul/loop/context_signals.py`、`cycle.py`、`phases.py`、`turn.py`。
- Session 投影与 schema：`tinysoul/session/completion.py`、`models.py`。
- 回归与异步消费者：`tests/action/test_backends_engine.py`、`test_hooks_runner.py`；`tests/context/test_actions.py`、`test_state.py`；`tests/loop/test_pressure.py`、`test_turn.py`；`tests/session/synthetic.py`、`test_completion.py`、`test_session_engine.py`、`test_validation.py`。
- 其余同步迁移的测试：`tests/app/test_builder.py`、`test_cli.py`、`test_program.py`、`test_runtime.py`；`tests/home/test_home_engine.py`、`test_home_metadata.py`、`test_home_search.py`；`tests/maintenance/test_home_actions.py`、`test_maintenance_engine.py`、`test_memory_actions.py`、`test_turn_boundaries.py`；`tests/memory/test_memory_consolidation.py`；`tests/workspace/test_workspace_engine.py`；`tests/capabilities/resource/test_resource.py`、`shell/test_shell.py`、`web/test_discovery.py`、`web/test_web.py`。
- 规约与文档：`AGENTS.md`、`docs/design/action.md`、`loop.md`、`runtime.md`、`session.md`、本子计划；主计划只更新开头进度状态。

工作区原有的 `tinysoul/context/__init__.py` 段导出与未跟踪的 `tinysoul/context/segments.py` 草稿保留，没有冒充本次完成的段实现。

建议 commit 文本：`refactor: stabilize async action facts and cancellation for agent R2`。该文本只描述已实现改动，不表示 R2 完成或可部署。

## 12. 2026-09-15 异步资源生命周期与本地 owner 切片

本切片沿第 11 节的依赖顺序实施，没有变更主计划结构或扩大领域功能范围。

| 子项 | 实现与验证证据 | 当前判断 |
|---|---|---|
| Generation 资源所有权 | AppBuilder 异步构造；注册自建 LLM/embedding 的关闭责任，注入服务保持借用；部分构造失败回收已创建资源 | 本子项已落实；不代表完整 Agent create/start/restart |
| 统一资源关闭 | Infra AsyncResourceScope 逆序关闭、嵌套诊断、幂等关闭；取消和重复取消等待清理任务完成 | 已验证继续全部关闭、同一资源只关一次、诊断不包含异常正文 |
| 配置激活与退休 | ConfigController 与全部 PATCH 消费者改 async；候选 abort 与已提交世代 retire 分离；退休失败保留新配置并返回 cleanup diagnostics | 已验证提交失败回滚、abort 失败不覆盖主失败、退休失败不伪回滚；保存候选/显式 reload 分离仍归 R2.6 |
| HTTP/CLI 与队列 | Uvicorn task 与 App 共用事件循环，宿主保留信号权；CLI 在 loop 退出前关闭资源；Program 改异步 mailbox/执行锁，取消空闲等待不遗留读队列线程 | 已验证真实端口 HTTP、假供应商 CLI、线程投递和取消等待；旧 App 仍未迁移为目标 Agent 包 |
| LLM 取消 | Task 统一监督供应商调用和全部 backoff，移除 provider 局部轮询收尾；重复取消不打断 provider finalizer | 已验证 provider retry/model switch 等待取消与原生 task 重复取消 |
| Home/Workspace 本地操作 | LocalActionExecutor 明确承载纯本地 owner 动作；Home 文档读取与 rerank 分离；Workspace 读取、await LLM、提交分离，提交包含 snapshot 通知 | 已验证真实 Workspace 文件提交期间取消仍返回成功事实与通知，runner 再传播取消；不是同步 executor 兼容层 |

AGENTS 核对：没有添加 Runtime 对上层业务依赖；Infra 仍只提供通用并发、资源和配置原语。Module 仍解释自身失败，取消不转为普通模型反馈。没有第二份业务日志、世代兼容 alias 或假 Plugin。新增生产抽象都在同次变更接入真实消费者，唯一新增 Python 文件为 `tests/infra/test_concurrency.py`，保护通用并发契约。现有 Home serial 策略与 overlay 锁、Workspace owner 一致性边界继续使用。本切片没有改用户数据、reset 项目、迁移 Session 历史或创建提交。

验证结果：

- App/Endpoint/Infra/LLM 首轮聚焦：363 passed。
- 取消、资源作用域与配置失败聚焦：63 passed。
- Home/Workspace/Action/Loop 聚焦：336 passed。
- 增加真实 Workspace 提交取消及客户端借用/关闭验证后的聚焦：191 passed。
- Fast 曾出现新增测试重复初始化目录的问题：998 passed / 1 failed；已修正并通过上述聚焦及最终 Full，不将这次 Fast 记为通过。
- 最终 `scripts/test.ps1 -Suite Full`：1006 passed / 2 skipped / 23 deselected；包括 wheel/init。上轮的 HTTP client 跨已关闭事件循环回收错误未再出现。
- 最终 `scripts/typecheck.ps1`：通过；`git diff --check`：通过。未运行 external provider/network 验证。

仍未完成的范围：Memory/部分 Maintenance 的同步混合操作、embedding 网络异步迁移、Turn 必要 finish/close 与权威结果协议、真实段 SPI 和 Plugin/profile、Session Map、Job/Inbox/统一等待/SUSPEND、完整 Agent SDK、终端可停止读取、包与全部消费者迁移。AsyncMailbox 只是已有 Program 的非阻塞队列，不冒充具备容量/确认/路由协议的 TurnInbox；关闭服务也不等于实现 shutdown/restart。R2.1/R2.2 保持 `in_progress`，R2.3–R2.8 保持 `pending`；主计划 S1/S2 不标 done，本计划不归档。

本切片修改文件：

- 通用设施与配置：`tinysoul/infra/concurrency.py`、`config/controller.py`、`embedding.py`。
- LLM：`tinysoul/llm/provider/factory.py`、`provider/registry.py`、`task.py`。
- App：`tinysoul/app/builder.py`、`cli.py`、`generation.py`、`inputs.py`、`program.py`、`runtime.py`、`services.py`。
- Endpoint：`tinysoul/endpoint/engine/configuration.py`、`engine/contracts.py`、`host.py`、`http/routes/configuration.py`、`http/server.py`。
- 本地 owner 动作：`tinysoul/action/__init__.py`、`core/executor.py`；`tinysoul/home/actions.py`、`engine.py`；`tinysoul/workspace/actions.py`。
- 测试：`tests/infra/test_concurrency.py`、`test_config_controller.py`；`tests/app/test_builder.py`、`test_cli.py`、`test_inputs.py`、`test_program.py`、`test_runtime.py`；`tests/endpoint/test_endpoint_api.py`；`tests/llm/test_config.py`、`test_provider_openai_sdk.py`、`test_real_provider_api.py`、`test_task_runner.py`；`tests/maintenance/test_turn_boundaries.py`；`tests/workspace/test_workspace_engine.py`。
- 文档：`docs/design/action.md`、`agent_home.md`、`app.md`、`endpoint.md`、`infra.md`、`llm.md`、`workspace.md`；本子计划及主计划开头进度。

建议 commit 文本：`refactor: close async generation resources and join local owner operations`。

## 13. 2026-09-15 异步检索、准备与必要收尾切片

继续实施基线为 `c8aad26`，开始时工作区干净。主计划的方向和第 9 节切片顺序保持不变。本切片继续 R2.1/R2.2，并消除 R2.3 接入前的同步准备和恢复处理器直接提交 Context 的路径。

| 子项 | 当前实现与核验 | 状态 |
|---|---|---|
| Memory 网络与事实边界 | EmbeddingClient 和 OpenAI-compatible adapter 原生 async；自建客户端由 generation 关闭，注入 transport 借用；Markdown commit 不再请求 embedding | 已落实；取消进入网络任务，失败只影响可选语义检索 |
| 派生缓存 | inspect 捕获固定 catalog 视图；按 embedding 输入文本摘要刷新候选向量，整批生成后原子写缓存并安装内存视图；缓存 schema v2 | 已验证取消保留旧缓存和已提交 Markdown、失败回退 lexical、后续可重建缓存 |
| 本地动作 | Memory memorize/recall 与 Session inspect 使用 LocalActionExecutor；Memory inspect 和 Maintenance inspect 调用者统一 await | 已落实本组；旧 Maintenance controller 的其余混合操作和锁仍待整体替换 |
| Turn 必要 finish | 完成 pipeline 统一 async；依赖 handler 失败后停止其后续依赖，最终 recorder 仍记录既有事实；失败通过原 Trap 或已解析转移处理；Session 写失败显式返回，不重放前置 finish | 已验证必要提交失败不发布回答、Session 自身失败不宣称已记录 |
| Session 完成事实 | schema v6 区分终态、执行失败、必要 finish 失败；Background/inspect/Memory facts 从同一记录投影；失败 Turn 不保存回答候选为正式输出 | 已落实该子项；Summary heap 仍在，基础 Map/ask/reply/profile 迁移未完成 |
| 取消与外层退出 | finalizer 由 Turn 持有，连续取消等待已开始 Session 提交完成；Task 取消、已解析转移和意外契约异常均先封存本轮再返回或传播；activity close 诊断单独返回 | 已验证连续取消只提交一次、外层异常不遗留活动 Context；完整 Job/段 close/lease 释放仍待接入 |
| 异步准备与批次 | Turn preparation、Context 批次消费统一 async；默认 catalog/provider 索引/正文全部读取后再安装；Session 历史、Workspace reconcile 与归档 Session 读取使用 joined owner 操作 | 已验证准备失败/取消无部分安装、原批次重试不吞入新输入；未冒充通用 Segment SPI |
| 恢复信号 | Workspace pressure/Trash restore 返回 Signal，删除直接消费 Context 与投影拒绝时的伪回滚；ModuleRunner 通过内核注入入口先消费恢复批次再重试，Phase 重试先消费更新 | 已验证真实 Workspace restore、重试前视图更新、待处理新输入仍保留；Runtime 不解释业务 payload |

AGENTS 核对：领域存储仍由原 owner 提交；没有新增持久日志或新旧并行执行器。Infra 只提供异步 embedding 与通用 joined 操作，Runtime 新增的恢复信号消费入口由 Kernel 装配，不增加上层 import。局部 embedding 失败可降级，取消不伪装为模型结果；必要 finish 失败和资源释放诊断不混用。新增协议均已连接生产消费者，本切片未新增 Python 文件。未修改实际用户数据、reset 项目或创建提交。

当前验证记录：

- Memory/Infra/Maintenance 初次聚焦：69 passed；取消与词法回退已补充验证。
- Turn/Session/Memory/Maintenance/App 聚焦：135 passed。
- 检索、收尾和 Session schema 切片：Fast 1005 passed / 2 skipped / 28 deselected；补充验证后 Full 1014 passed / 2 skipped / 23 deselected，typecheck 通过。此结果早于后续异步准备修改，不作为最终门禁。
- 异步准备迁移曾暴露 3 处旧 Trap 直接调用同步 Context 的路径，已改为恢复信号消费；Context/Loop/Workspace/Maintenance/Runtime 聚焦 273 passed。
- 加入外层异常退出、背景取消及恢复信号隔离后的聚焦：168 passed；补充固定批次重试测试后 Context 聚焦 26 passed。
- 最终 Fast：1014 passed / 2 skipped / 28 deselected。
- 最终 Full：1019 passed / 2 skipped / 23 deselected，包含 wheel/init；typecheck 与 `git diff --check` 通过。未运行 external provider/network 测试。

剩余项：真实 Segment 注册/open/typed prepare-install/render/seal/close、Home/Memory/Session/Workspace 插件与三 profile、Session Map、精简 Reflection、Job/Inbox/Router/等待/SUSPEND、SDK 根调度及世代/日 lease、可停止终端输入、包与全部消费者迁移。现有同步恢复处理器和部分 Maintenance/能力操作仍需梳理；当前恢复 Signal 消费入口不是目标 EventRouter。R2.1/R2.2 仍为 `in_progress`，R2.3–R2.8 仍为 `pending`；S1/S2 不标 done，本计划不归档。

本切片修改文件按职责归纳：

- Embedding 与 Memory：`tinysoul/infra/embedding.py`；`tinysoul/memory/actions.py`、`catalog.py`、`embeddings.py`、`engine.py`；`tinysoul/maintenance/memory/actions.py`。
- 语境准备与运行：`tinysoul/context/engine.py`、`preparation.py`；`tinysoul/loop/assembly.py`、`completion.py`、`context_signals.py`、`cycle.py`、`outcomes.py`、`preparation.py`、`pressure.py`、`trap_handlers.py`、`turn.py`；`tinysoul/loop/user/builder.py`、`pressure.py`、`runtime.py`、`trap_handlers.py`；`tinysoul/runtime/frame_runner.py`。
- Session 与其余准备入口：`tinysoul/session/actions.py`、`background.py`、`completion.py`、`engine.py`、`memory.py`、`models.py`、`navigation.py`、`projection.py`；`tinysoul/workspace/projection.py`、`tinysoul/maintenance/memory/context.py`。
- 测试：现有 Infra、Context、Loop、Session、Memory、Maintenance、Workspace 和 App 测试中的对应调用迁移与真实边界验证。
- 文档：`docs/design/infra.md`、`memory.md`、`session.md`、`loop.md`、`context.md`、`runtime.md`；本子计划和主计划进度行。

建议 commit 文本：`refactor: await owner preparation and preserve turn finalization failures`。

## 14. 2026-09-16 注册段与 Workspace 视图切片

继续实施基线为 `cc37e5d`，开始时工作区干净。重新核对 AGENTS.md、主计划第 7 节及本计划第 6/7/9 节，沿已确认的段依赖反转方向实施；没有变更主计划范围。

| 子项 | 实现与核验 | 当前判断 |
|---|---|---|
| 通用组合 | 删除固定 ContextSection 枚举；composer 只消费带 descriptor 的消息投影，按 Background/Trace/Working、order、id 排序，TaskPrompt 独立叠加；预算诊断按段 id 归属 | 已接入实际模型调用；Session 顺序已移至 inputs 前 |
| 注册与生命周期 | 替换原无生产消费者的 segments 草稿；注册校验 id/更新路由唯一，provider 每 Turn open；部分 open 失败回收已交出视图，render/seal 只读内存，逆序 close | Workspace 已作为真实 owner 消费；尚不代表全部核心/领域段迁移 |
| typed 更新 | 在注册边界绑定具体更新类型与 codec；Context 捕获固定批次，所有背景/核心校验与段 prepare 成功后才 install；候选属于单一 Turn 且只能安装一次 | 已验证后段失败无前段安装、固定批次重试与新更新隔离、取消准备无安装、安装缺陷禁止重放 |
| Workspace 所有权 | 资源快照类型、codec、revision 判断及本轮投影移入 workspace/projection.py；WorkingContext 只保留 plan；User 与两种 Maintenance 装配同一段注册 | 删除 Context 的 Workspace 分支及旧导出，没有兼容别名；初始 reconcile 仍由既有 owner preparation handler 提供 |
| 内核解耦 | Phase3 不再按 Workspace 动作名筛选更新失败；全部内部 Action 更新拒绝均作为契约/不变量失败 | 注册段的非法更新经对应 owner/Context bridge 退出，不伪装为普通工具结果 |
| seal/finish/close | TurnCompletion 与 Session schema v7 保存以 id 标识的段快照，Memory facts 来自同一记录；Turn 在 finish 的 finally 边界关闭段，关闭结束后才发布输出 | 已验证 close 错误不覆盖正式结果、重复取消等待 close、清理前不得复用 Context、关闭不再次提交记录 |

AGENTS 核对：Workspace Engine 仍是磁盘/manifest 的唯一 owner，段只维护本轮视图；不存在第二份 Workspace 持久状态。Context 不 import Workspace，不解释资源快照，composer 不增加领域分支。未知段实现错误停在 Context 契约边界；owner 已映射的运行异常保留，安装阶段缺陷不进入重试。没有新增生产 Python 文件；新增 `tests/context/test_segments.py` 与 `tests/workspace/test_projection.py` 分别保护通用 SPI 和 Workspace 投影契约，原 Context 中的 Workspace 私有状态测试已移除/迁移。同步 Context、Workspace、Session、Loop 设计及项目生成的 Context 使用说明；未修改用户运行数据，未迁移旧 Session，未创建提交。

核验记录：Context/Loop/Workspace/Session 聚焦最终 231 passed；Fast 1019 passed / 2 skipped / 28 deselected。审计补充核心更新路由冲突校验后，注册段聚焦 6 passed；最终 Full 1024 passed / 2 skipped / 23 deselected（含 wheel/init），`scripts/typecheck.ps1` 与 `git diff --check` 通过。未运行 external provider/network 测试。

边界与剩余项：当前 descriptor 只声明已有消费者的 id/owner/slot/order，更新路由绑定具体 Signal codec；shape 的检查/回收、profile/ref 路由、只读段注册及可选 finish 仍需与真实 owner 一同接入。Home/Memory/Session 与核心段仍需迁至统一实例生命周期；当前通用 Background 和 Session preparation 分支未冒充已拆分领域段。Session Map、Reflection 写契约、Job/Inbox/Router/SUSPEND、Agent SDK/lease、终端回收与包迁移继续按第 9 节推进。R2.3/R2.4 标记 `in_progress`，R2 和主计划 S1/S2 均不标 done，也不移动至 done 目录。

修改文件按职责归纳：

- Context：`segments.py`、`composer.py`、`engine.py`、`working.py`、`signals.py`、`__init__.py`。
- owner 与装配：`workspace/projection.py`；`loop/phases.py`、`loop/turn.py`、`loop/user/builder.py`、`maintenance/builder.py`；`session/completion.py`、`session/models.py`、`session/memory.py`。
- 验证：Context、Loop、Workspace、Session 对应测试，含段生命周期、真实 Workspace preparation、Session 快照 round-trip。
- 文档/资源：四份模块设计、本子计划、主计划进度；项目 Home 的 AGENT.md 与 Context/Link 使用说明。

建议 commit 文本：`refactor: register turn context segments and separate workspace projection`。

## 15. 持续实施：统一核心/领域段与 Session 事实 Map

状态：`in_progress`。继续实施基线为 `12450b7`，初始工作区干净。维护者已要求完整推进 R2，允许清理或重构旧测试；本节不是 R2 完成记录。

- Context 的 identity、inputs、trace、plan、固定 journal 与 Home/Memory/Session/Workspace 同用注册、open、render、prepare/install、seal、close。Turn 内核必经 open，删除重复的 Context preparation adapter。核心段实现集中于 `context/core.py`，不把旧 ContextEngine 封成领域黑盒。
- descriptor 明确声明 slot/order/shape、ref 路由和实际能力。只读段无需虚构更新通道；注册拒绝重叠 ref，open 校验声明的能力有真实实现。统一 `core.context.inspect` 路由到 Trace 与 Session，删除 `core.session.inspect` catalog、executor 和装配。
- Home/Memory 的本轮加载状态归各自 Heap 段，共用纯内存视图和准备算法。Context 不保存 provider-by-link 或领域内容；通用选择校验后分发给段，全部候选完成才安装。Home 顶层写入与活动 Memory 写入提交后发刷新通知；刷新目录和已加载正文，不自动展开新资源。回收遵循 shape 顺序和受保护默认项。
- Session 保留 v7 不可变 Turn record，manifest 更新为 v3 平面 Turn 索引。删除 Summary records/递归压缩/配置阈值/多态存储与旧测试；Map 从同一事实派生 Turn、Action occurrence、resource 节点及标记为 fact 的 precedes/contains/references。保留原子提交、幂等、孤立 Turn 恢复和有界 continuation。
- Session provider 每 Turn 打开固定视图；seal 只存来源日、revision、refs，不递归复制 prior-Turn 正文。inspect 校验固定视图版本。Memory evidence 直接投影同一 Turn 索引。中断 Action 的历史统计覆盖 cancelled/not_executed/unknown。

已完成的中间验证：Session/Context/Loop/Memory/Home/Action 聚焦 375 passed；Fast 1022 passed / 2 skipped / 28 deselected；随后能力声明调整通过 ty。后续改动后仍须重新完成 Full 与标准 typecheck，不能用本记录代替最终门禁。

尚待本轮收口：profile 贡献与权限、真实 finish 接入、Memory 单文档写与 Reflection 替换、Job/Inbox/Router/统一等待与预算、Agent SDK/lease、终端与 HTTP 消费者、目标包迁移及全仓最终审计。Session ask/reply 等事实随等待协议继续补齐。R2 与主计划仍不标 done，不迁移到 done 目录。

## 16. Reflection 与 Memory 单文档写入

状态：`in_progress`。Reflection 已接入通用 action 装配，分别提供 `home_reflection.diff/review` 与 `memory_reflection.write_daily/write`；完成意图统一使用 `core.answer`，不再依赖独立 `maintenance.complete`。

- Memory codec 与 owner 使用 schema v2，移除持久文档的 activation_count、daily session_revision、active_memory_digest 及活动 Memory 的 CAS revision。
- `MemoryEngine.write_document` 先构造并校验新目录快照，再原子替换单一 Markdown；catalog、backlinks、embedding 仍是可重建派生数据。重定向目标不存在、类型不符或成环时拒绝当前写入，已提交的此前文档保持不变。
- Home review 按稳定 Home Link 选择，owner 仍负责 token/version 校验和实际提交；批量 review 逐项处理并以结构化结果报告部分成功。
- 旧 Memory Maintenance 的 staging/preview/changeset 控制器、daily 专用 composer 与相关旧测试已删除。聚焦验证 114 passed，Full 1017 passed / 2 skipped / 23 deselected，typecheck 通过。

R2.5–R2.8 的 Job/Inbox/Router、Reflection 的真实运行 profile、可停止输入、包迁移和最终文档审计仍未完成；本计划和主计划保持 `in_progress`。

## 18. Environment EventBus 与 SDK 目标事件

状态：`in_progress`。此处记录初始草稿；第 21 节已替换：EventBus 移至 Runtime，仅投递 EVENT/TIMER；INPUT/reply/grant 由明确受理入口拥有，不接受外部事件伪造授权，也不保留平行事件正文队列。

此切片先落地可复用的事件协议与 SDK 目标路由；将事件纳入正在运行 Turn 的统一等待、预算 SUSPEND、Router 注册和 ack 仍属于 R2.5/R2.6，当前不宣称已完成完整 Inbox。

## 19. TurnInbox 固定批次与确认

状态：`in_progress`。初始 Inbox 草稿已在第 21 节迁入 Loop 并连接内核：固定批次安装后 ack，普通输入/事件受容量约束，问题回复有独立预留，预算决定与取消不排在进度记录之后。

当前仍未把 Kernel 的 cycle wait、SUSPEND 恢复点、Job 终态 reservation 和 Agent Router 注册接入 Inbox；这些保留在 R2.5/R2.6，避免新 Inbox 与旧 Program 队列形成第二套运行控制。

## 20. Agent EventRouter 接入

状态：`in_progress`。新增显式 `EventRouter`，按目标 identity 或 `EventKind` subscription 路由事件；同一 callback 在目标与订阅同时命中时只投递一次。Agent 已注册活动 Handle 为目标，`publish` 经 EventBus 幂等受理后交给 Router。

Router 仍只负责事件送达，不消费 owner Signal、不伪造 Job 终态，也不启动隐藏 Turn。Kernel wait/SUSPEND 与生产环境输入源的完整接线继续按 R2.5/R2.6 实施。

## 17. Agent SDK 生命周期门面

状态：`in_progress`。初始 SDK 草稿已由第 21 节单根调度替换；删除重复的 TurnRequest 和 SDK 执行队列，复用明确 UserTurnRequest/MaintenanceRequest。Handle 引用唯一 Inbox 与完成结果，不维护第二份输入/事件正文。

- 队列满和关闭状态使用 SDK 边界异常；等待者取消通过 shield 与实际 Turn 生命周期分离；shutdown 会取消排队及活动 Turn 后关闭 App 资源。
- SDK 目前已由真实 TinySoul App 入口适配 request_id/source；Reflection profile 的专属执行装配已落地，但 SDK profile 到 Reflection Request 的完整 Agent 调度仍待 R2.5/R2.6 的 Inbox/Router 完成。
- SDK 聚焦测试覆盖有界受理、等待取消隔离、活动/排队取消及终态；类型检查通过。

## 21. 2026-09-16 单根 SDK、Inbox、预算暂停与问答闭环

状态：`in_progress`。以 `370cf6e` 和第 17–20 节未提交草稿继续，复核发现第二执行队列、活动取消未绑定、重复事件正文和 profile 字符串未分派等缺口；直接清理草稿，不保留兼容层。

- `agent/scheduler.py` 替换原 app/program.py，SDK 和旧进程入口共用唯一根队列、generation/day lease 与请求分派。User 请求定义迁至 agent/requests.py；SDK create 装配与 start 激活分开，完成结果保留有界，取消活动请求不停止后续根任务。shutdown/restart 等待取消和资源回收，旧 handle 不复活。
- Runtime EventBus 只校验、投递和保存有界幂等回执；失败可重试。Router 只送达登记目标/订阅，不启动隐藏 Turn。Loop TurnInbox 单独持有待处理正文、固定 capture/ack、记录/总字节/单条容量；关闭唤醒等待者，已捕获批次不会混入后到记录。
- SDK User Turn 的追加输入与事件由内核 prepare/install 后 ack；回答前复查并关闭受理。取消关闭普通入口并消费已接受记录，再执行 seal/finish/close；TurnExecutionCancelled 携带真实封存结果，使 SDK 可报告必要 finish 失败及清理诊断。
- Runtime SUSPEND 只允许当前 Turn 栈顶，Loop-owned 预算 reason 经 Trap 决议。预算不足不启动下一 Cycle，事件/输入不绕过预算，grant 校验 request identity/count 并幂等。删除 supervised_process 的 allow_additional_cycle、计数和 max_supervision_cycles 全部配置/资源/测试；进程 pacing 改为可取消 async，尚未冒充通用 JobRegistry。
- 新 core.ask 为立即收敛的 Action 意图，由 Turn 登记问题、发布中间输出并等待指定回复；默认无超时，显式超时为 awaiting_user。普通追加/环境事件不答复问题，满载进度不占回复预留槽，旧 reply 不新建根。多个 ask/answer 为可反馈 PhaseFailure。Session schema v8 保存 input_id/reply_to，输入正文只在输入事实中，inputs 段 seal 只引用身份；取消保存 cancelled。

中间验证：SDK 真实 App/Action/Context/Session 装配、Inbox/Loop/Context/Session 聚焦 162 passed；此前 Fast 1022 passed / 2 skipped / 28 deselected。首次 Full 为 1028 passed / 1 failed / 2 skipped / 23 deselected，失败为旧 Action 测试未登记新增 ask，已修正；这些记录不能代替后续最终门禁。标准 typecheck 已通过。未运行 external provider/network。

本节是当时切片记录；后续实际进度以第 22 节为准。主计划只更新进度，不勾选 S1/S2，不归档本计划。

## 22. 2026-09-16 继续实施：Job、Reflection 与统一命令入口

状态：`in_progress`。在既有未提交修改上继续，没有 reset 用户工作区或用户数据。

- 包依赖已迁入 `kernel/{action,context,loop,jobs}`、`plugins/{home,memory,session,workspace,reflection,capabilities}` 与 `gateway/endpoint`；更新生产/test imports、进程 worker 字符串和 package resources。旧 App 组合根尚待拆分，不以目录移动冒充完整架构完成。
- Kernel JobRegistry 成为受控进程唯一 Job 索引；后台 monitor 在 Turn 暂停时仍读取终态并关闭执行句柄，终态槽独立预留。Working jobs 段呈现同一索引；Turn 收尾先关闭普通受理，回收 Job，再消费已接受终态、seal/finish/close。已修正 poll 失败跳过 cleanup、关闭流后无法读取输出、无界最终 wait 和静默 close 失败。
- Home/Memory 请求传递 Inbox 到同一个 TurnRunner，返回保留完整 TurnOutcome 的 owner outcome，等待/耗尽/停止不降格为普通失败。修正 Reflection Trap 缺少 Home runtime copy handler。三 profile 有效动作收齐后统一 reconcile Home Skill 挂载，避免专属 Reflection 域缺失。
- Memory Reflection 的执行日绑定当前活动日，Session 和 Memory 目标独立绑定历史日；当前 Workspace 是可操作工作台。归档 Workspace 由 owner 注册只读 `workspace_archive` 段，有日期的 Context ref 经统一 inspect 分页/有界读取，不把旧资源呈现为今日可写 Link。此段是第 8 节只读历史 Workspace 要求的具体实现。
- AgentCommands 统一 SDK/Terminal/Endpoint/定时入口；移除根队列公开写口。输入到 Inbox，reply/grant 关联当前请求；daily trigger 以独立 profile 请求整批受理。线程源等待真实回执，定时源满载重试；取消与退出绕过普通输入容量，前者保留后续根工作，后者停止受理并取消全部工作。
- CLI 已调用 Agent 生命周期；当前 Endpoint input/control/maintenance 路由异步进入同一门面，协议文档同步。Agent.create 支持项目根与 overrides，assemble 支持显式装配依赖；start 等待来源激活，status 返回不可变快照，SDK 与内核共享 Turn identity。观察输出失败只保存有限诊断，不补抛业务异常。
- Terminal 使用可停止的 console/pipe/file reader；停止等待线程，Windows console 不依赖无法打断的 readline。已有真实空闲 pipe、分片 UTF-8/EOF、停止/重启验证。

验证记录：入口迁移聚焦与 typecheck 已通过。一次 Fast 为 1038 passed / 2 failed / 2 skipped，两个失败来自扩展收尾路径碰到旧测试替身；已修正收尾触发条件与异步异常捕获，相关 Loop 聚焦已通过。新增 SDK 跨日 Memory Reflection 协作验证保护当前执行日、历史来源、持久 daily 写入与不写 User Session；最终完整门禁仍需在全部改动后重跑。

已完成本轮：显式 `PluginDeclaration` 的 declare/resolve/activate 已接入 User 与两个 Reflection profile；`TurnProfile` 绑定 Context、Action、服务注册表和完成管线，重复 Context/Action 替换入口已删除。解析阶段会先校验服务、依赖和段路由，激活阶段批量安装段并取得唯一 Job 服务。Context 与 Loop 设计文档已同步。

待完成：Endpoint 领域服务继续收紧 generation lease 的公开边界；拆分剩余 App/日切归属、CalendarDay/Agent/Reflection 命名；catalog owner fragments、测试目录和全仓文档；容量/生命周期剩余风险审计与最终 Full/typecheck。R2 与主计划 S1/S2 均未完成。

本次继续验证：App/Agent SDK 聚焦通过；插件/Context/SDK 聚焦通过。Fast `1047 passed, 2 skipped, 28 deselected`；Full `1052 passed, 2 skipped, 23 deselected`，包括 wheel/init；typecheck 与 diff 空白检查通过。这些结果覆盖当前插件/profile 切片，不代表 R2 完成；未运行 external provider/network 测试。

## 23. 2026-09-16：服务、配置与观察边界

状态：`in_progress`。本节记录第 22 节之后的继续实施。

- `kernel/registration.py` 的服务表已由三个真实 profile 消费。`TurnProfile.services` 和 `Agent.services` 提供按 Facade 类型查询的当前服务；不提供任意字符串查找。Endpoint 的 generation 约束改为 `AgentRuntimeServices` 只读投影，仍保留 RuntimeHandle lease，后续继续收紧具体 owner API。
- `agent/observations.py` 提供有界、单读者 Observation subscription：按 level/name/turn 过滤，固定记录与字节容量，慢订阅收到 `ObservationGap`，线程来源只安排一次唤醒回调；订阅关闭不会取消 Agent，Agent 停止会结束旧流。观察仍是旁路事实，sink 失败不改变业务结果。
- `ConfigController.patch` 只校验并原子保存候选，`reload` 在 idle 且有 activator 时才装配、提交和退休世代；SDK 暴露 `patch_config`/`reload_config`，Endpoint 保留有运行世代时的原子 PATCH 便利语义，并提供 `/v1/config/reload`。进程环境变量不再被误判为项目配置顶层 section。
- `BusinessDay` 已统一更名为 `CalendarDay`，运行栈的顶层 frame 与结束原因分别使用 `RunLevel.AGENT` 和 `runtime.agent_end`；外部 `/exit`、`EXIT_PROGRAM` 仍是协议层控制意图名称。

验证：配置、Endpoint、Observation、SDK 聚焦通过；typecheck 通过。随后完整门禁需在本节变更最终稳定后再运行。

## 24. 2026-09-16：完整迁移与最终核对

本节为当前权威进度。第 11–23 节保留实施过程和当时发现的问题；其待完成描述已由本节逐项核验替代。维护者已经授权完整 R2，不新增未讨论的领域方向，不扩大主计划 S3–S6 范围。

### 实现与规约核对

| 切片 | 当前实现、文档与验证证据 | 核对结论 |
|---|---|---|
| R2.1 | llm 原生 async provider/模型链；infra JoinedOperations/AsyncResourceScope；Action、领域准备、日切与 Reflection 文件边界使用同一收尾机制；docs/design/llm、infra、action | 已落实；本地 provider fake、取消/backoff、借用/关闭、短 owner 已提交事实由 owner 测试覆盖 |
| R2.2 | kernel/action typed execution facts、kernel/context canonical Trace、kernel/loop completion；Session v8；docs/design/loop、session | 已落实；部分批次、取消、必要 finish、Session 写失败与 close 诊断分开验证，不伪造缺失 ToolResult |
| R2.3 | kernel/context 段注册、slot/order/shape/ref、固定 prepare/install/ack；核心与真实领域段统一生命周期；docs/design/context | 已落实；后段失败、安装缺陷、部分 open、重复取消 close 和纯投影契约有 owner 测试 |
| R2.4 | PluginRegistry declare/resolve/activate 与 TurnProfile；agent/user、plugins/reflection 共用内核；Session Map、Home diff/review、Memory 单文档写；docs/design/agent、reflection、memory、agent_home | 已落实；User 不注册专属持久写 Action，Home/Memory Reflection 协作路径不写 User Session，历史 Workspace 为只读段 |
| R2.5 | Runtime EventBus、Agent Router、Kernel Inbox/JobRegistry、ask/reply、预算 SUSPEND；docs/design/runtime、loop、agent | 已落实；定向失效不回退、全局事件到当前根、满载取消/回复、终态预留、重复 grant、真实进程退出与清理均有验证 |
| R2.6 | Agent create/start/submit/status/services/config/shutdown/restart；唯一根队列、世代/day lease；AgentDayCoordinator 与 Archive owner bridge；docs/design/agent、reflection | 已落实；保存候选/显式 reload、等待时 busy、跨午夜等待、旧句柄、资源生命周期和观察 gap 均有验证 |
| R2.7 | 删除旧 app 包，输入源迁至 environment，CLI/initializer/instance/HTTP 迁至 gateway；owner catalog fragments；测试镜像新结构；docs/endpoint 与 README | 已落实；CLI --once 明确关闭 scheduler；wheel 隔离安装核验 SDK 和项目命令，无旧包 alias |
| R2.8 | 依赖图、失败 owner、死抽象和文档审计；执行完整本地门禁 | 已落实；Fast/Full/typecheck 与 diff 检查通过，按规约归档 |

本次收口修正的真实边界：

- 配置 PATCH 在 SDK 和 HTTP 中统一只保存候选；reload 才激活。Endpoint 通过 AgentRuntimeServices 只读投影和 read lease 取得当前门面，移除散落的具体 generation 访问；业务世代切换后 SDK 重新查询服务取得当前对象。
- 日切从 Reflection 移至 AgentDayCoordinator，Archive 有自己的错误类型和 runtime bridge。Reflection 只读历史来源；日切与 Reflection 的短文件操作让出事件循环，取消等待已开始操作结束。Archive Runtime 异常在根调度边界进入合法 Agent Trap。
- daily 触发不能从旧 availability 推算新关闭日；现按触发日拆为 Home/前一日 Memory，执行前完成日切，scheduled 按日期/profile 去重并跳过已存在 daily，旧 backlog 仍需明确目标请求。
- InboxLimits 从 SDK 注入：普通条数/字节/单条大小、回执及终态槽数/字节有界。Job 启动前验证终态预留；即使普通队列满或已关闭，清理终态仍可消费。问题回复独立预留，外部事件没有授权能力。
- 进程 stop 和后台 monitor 的终态判定在同一 owner 锁中，避免主动停止被退出码覆盖为失败；真实 Shell 生命周期回归通过。
- Observation sink/订阅编码失败只停用对应旁路并记录有限诊断，不改变业务结果；关闭事件循环时的订阅唤醒竞态已处理。
- User/Reflection 装配、测试目录、catalog package data 与 console entry 一并迁移。pytest 使用 importlib mode，允许按 owner 镜像组织同名切面测试，不以旧文件名限制新结构。旧 app 目录仅余的生成缓存已清理。
- 最终死依赖核对移除 Home task 未消费的 controller 参数及通用能力装配未消费的 Memory 引用/依赖声明；专属写服务仍由 Reflection action 装配实际持有。

按 AGENTS 核对：持久事实仍各归一个 owner；Signal、Observation、EnvironmentEvent、Trap 职责分离；Runtime 无向上依赖，Kernel 无领域 import；Plugin 与段没有空能力或第二套执行器；局部结果、模块失败、控制转移分层。已保留的 Workspace CAS/压力 Trash 和 Script/Shell 私有领域细节属于明确留给 S3 的功能变更，当前只有一套活动实现，不是兼容管线。

现有配置 section（app、maintenance、loop 等）和 HTTP /v1、稳定 failure kind 保持明确的外部标识；物理 owner 与 Python 核心身份使用 Agent/CalendarDay/Reflection。全面配置/协议产品化及 AGENTS 核心定义重写仍按主计划后续阶段处理，不凭机械更名改变已发布含义。

### 最终验证记录

- 迁移后首次 Fast 曾暴露 helper import 与进程停止竞态；已修正。后续 Fast 唯一失败是 --once 新配置对应的旧断言，已修正；不把失败记录当作通过。
- 收口聚焦：142 passed；此前 SDK/Reflection/Job/Shell 聚焦 132 passed、2 skipped。
- Fast：1060 passed、2 skipped、28 deselected。随后补强同一 ask/reply 测试的跨午夜日 lease 断言与 wheel 的包外 SDK 验证，最终以 Full 覆盖。
- 最终 Full：1065 passed、2 skipped、23 deselected（含 wheel 隔离安装、项目 init/reset、本地 fake-provider CLI、包外 SDK 生命周期与模块失败结果）；typecheck：通过；git diff --check：通过。现有 Starlette TestClient/httpx 弃用提醒不影响通过结果，未为本轮无关提示扩展依赖变更。

未运行 external provider/network、ACP/MCP 真实联调；没有 reset、迁移或修改用户实际运行数据，没有创建提交。S3 的 Session organize、Workspace 简化和 execution 深化，S4 的 fswatch/调度深化，S5 的完整 Endpoint v2 和 S6 的 ACP/MCP 保留在主计划中，不以 R2 完成替代后续阶段。

完成结论：R2 已完成并归档，主计划仅更新 S1/S2 状态与已落实前置项提示，不改动后续阶段的设计范围。建议 commit：`refactor: complete R2 async agent SDK and plugin runtime lifecycle`。
