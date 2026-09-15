# Agent 架构重构：设计语义、契约与执行计划

状态：`in_progress`（设计复审，尚未实施架构重构）。
修订日期：2026-09-15。审阅代码：`e930c9c444deb0073ab3d7f016057245bad66ca6`；本轮 git ls-remote 确认远端 HEAD 相同。

本文件描述目标设计，不代表当前实现。用户本轮授权分析、修订计划与讨论，不据历史“全面授权”直接实施代码。已确认语义见第 14 节；Q 编号的细化方案为建议，不标成用户已批准。原“正文 + 替换预览”合并为单一方案，旧版由 Git 保存，不并行保留互相冲突的接口。API 均为契约草图，具体名称与类型在子计划落定。

## 1. 项目理解与重构意图

TinySoul 是长期运行的个人 Agent：在环境中感知与行动，通过多 Cycle 求解，通过 Session 保存对话经验，通过 Memory 与 Home Reflection 沉淀知识、偏好和可复用能力。项目已有资源 owner、构造式 Context、分层失败和可复用 Turn 内核；本次应围绕这些资产重整依赖与生命周期。

设计判断顺序：谁拥有事实 → 谁可以修改 → 何时可观察 → 谁处理失败 → 谁负责结束与回收。“干净”不等于删除合理抽象，也不等于让所有业务都经消息总线绕行。

| 原始意图 | 设计回应 | 边界 |
|---|---|---|
| SDK 风格分层调用 | Agent/Engine 公共门面、显式依赖注入 | gateway 不访问 owner 私有状态 |
| 可维护、可替换功能 | Plugin 可贡献段、动作、事件源、服务、profile | 无内容的能力不造假段，不建设动态发现平台 |
| Agent 处于环境中 | EnvironmentEvent、Router、TurnInbox、Trigger | 借鉴 DDS 发布订阅思想，不引入 DDS 中间件 |
| 暂停并与用户交流 | question/reply 与 INPUT 等待 | 暂停不结束 Turn，不释放根执行位置 |
| 监督后台任务 | Turn-owned Job、EVENT/TIMER 等待 | Job 不跨 Turn；等待不消耗 Cycle |
| 冰山、Trace 栈、工作台 | 三分区与 Heap/Map/Stack/State | 形状不规定领域内容或 Python 容器 |
| 外围维护语境 | Engine 拥有事实，Segment 拥有本轮视图 | Context 组合段，不理解 Home/Memory 内容 |
| 历史会话地图 | Session 事实、Map 投影与有来源注释 | 不再平行维护线性 Summary |
| 自然知识沉淀 | 两个 Reflection profile 与专属域 | User 不写持久 Memory、不提交 actual Home |
| 灵活工作区 | list/search/read/write/edit/append 等 | 去 CAS 不等于允许半写文件 |

## 2. 代码现状与复用判断

本轮读取 AGENTS.md、原计划、相关模块设计、现有讨论笔记及关键运行路径；不是逐行审计全仓，也没有宣称运行测试通过。旧 `docs/chat/00 doing something.md` 仅供参考，不自动扩大范围。

| 实现证据 | 已有资产或缺口 | 重构处理 |
|---|---|---|
| `loop/turn.py`、`loop/cycle.py` | owner-neutral TurnRunner、三 Phase、边界取消、PhaseFailure | 保留骨架，改 async，补等待恢复 |
| `loop/turn.py` 的 max_cycles/activity_controller | 已有预算边界和等待接点，二者耦合 | 内核预算检查 + typed 用户决策 |
| `runtime/transfer.py` | 只有 RETRY/END | 暂停不能伪装成结束后复活；见 Q1 |
| `runtime/bridge/action.py`、`context.py` | runtime import 上层模块 | bridge 随 owner 放置 |
| `runtime/bridge/llm.py` | LLM 失败直接映射 Context 压缩原因 | LLM 声明容量失败，Context 注册恢复策略 |
| `context/engine.py::consume_signal_batch` | 先准备后改状态，但特判 Workspace/Session | 保留批次语义，解释权交给段 |
| `loop/context_signals.py`、`runtime/frame_runner.py` | 捕获批次并定向重放 Module frame | 恢复不重新 drain、不重做 Action |
| `action/core/runner.py::_run_one` | 未知异常、非法返回对象等包装成局部失败，反馈拼接 exc | 内部/契约错误提升为模块失败 |
| `action/core/runner.py` 的 leaked timeout | 已阻断同批后续 execution | 未释放 owner 时阻止后续 Turn/日切/reload |
| `runtime/bridge/_payload.py` | 配置原值、异常文本可能进入 payload | owner 显式给出有界诊断 |
| `session/completion.py` | 从 Phase2/3 消息解析 Action 配对 | Trace 导出 typed 事实，Session 不猜消息布局 |
| `loop/completion.py` | 有序完成处理管线 | 保留有序提交，区分 finish/close |
| `workspace/engine.py` | digest/revision/read-set 深入提交逻辑 | 删除对应动作契约与测试，保留原子文件操作 |
| `home/review.py`、`home/overlay.py` | actual/overlay/review | 保留边界，简化专属域 |
| `memory/transaction.py`、`maintenance/*` | Memory 多文档流程、维护编排 | 单文档写，编排与存储分离 |
| `maintenance/archive/engine.py` | active day lease、归档恢复 journal | 保留，不随 Memory 事务删除 |
| `app/builder.py`、`app/generation.py` | 集中装配、世代与资源关闭 | 拆组合根与插件贡献 |
| `llm/task.py`、`runtime/observation.py` | 局部恢复与旁路观察 | 保留三层失败，不机械删除宽泛捕获 |

AGENTS 的“当前任务”仍指向不存在的 20260914 计划，过渡条款夹有旧 Job/bridge 语义。本轮依据用户指定的本文件设计。S0 确认后修正规约指向及已确认目标；后续逐阶段同步已实现事实，不等到 S7 才处理文档矛盾。

## 3. 分层、所有权与代码组织

| 层 | 模块 | 职责 |
|---|---|---|
| L5 | gateway | CLI/HTTP/WS、鉴权、协议映射、项目命令入口 |
| L4 | agent | 门面、组合根、根队列、Router、实例状态、世代、日切 |
| L3 | plugins / environment | 领域事实与能力 / 外部 I/O、调度、文件观察 |
| L2 | kernel | loop/context/action/jobs/profile、插件消费协议 |
| L1 | llm / runtime | 模型任务与供应商 / 运行位置、Trap、转移与事件基础 |
| L0 | infra | 配置源、JSON、文件原语、时间值、通用并发 |

允许向下依赖，不要求逐层中转。llm 可依赖 runtime 公共协议；runtime 不 import llm/kernel/plugins，kernel 不 import agent/environment/plugins/gateway。跨插件仅依赖明确公开服务契约，实例由组合根注入。SDK 服务读取是直接门面调用，不用总线模拟 RPC。

建议布局：

- `runtime/{scope,trap,transfer,exception,events,generation,failures}`：通用协议，无业务 bridge。
- `llm/`：消息、工具、模型链、provider、自身 runtime_bridge。
- `kernel/loop/`：Turn/Cycle/Phase、profile、completion、cancellation、wait、budget。
- `kernel/context/`：段协议、composer、pressure、inputs/identity/plan/trace/jobs 段与控制动作。
- `kernel/action/`：catalog/schema/hook/批次/executor；`kernel/jobs/`：Job 协议、监督与控制。
- `kernel/spi.py`：公共协议汇出；定义跟随各 owner，不建设巨型接口文件。
- `plugins/{home,memory,session,workspace,reflection}/`。
- `plugins/capabilities/{resource,web,execution,subagent,expand}/`。
- `environment/{terminal,scheduler,fswatch,console}.py`。
- `agent/{agent,assembly,scheduler,router,generation,day,services,status,config}.py`。
- `gateway/{cli,endpoint,project}/`；继续使用项目 assets。

所有业务 bridge 随 owner；公共异常 payload 帮助放 runtime 公开模块，不跨模块 import 私有 `_payload`。infra 不依赖 runtime，由使用边界适配错误。CalendarDay 是通用日期值，CalendarClock/日切协调归 agent/day。

Plugin 是装配单元，Engine 是领域服务，Segment 是当前 Turn 视图，Action 是模型可选择能力，不相互代替。插件按需拥有 plugin/config/engine/segments/actions/failures/runtime_bridge/catalog/jobs 文件，不强制空壳。

装配：declare → resolve → activate。先声明贡献与依赖，再校验重复身份/依赖环/profile/ref 路由/服务，再启动连接与监听。失败逆序清理已激活资源。协议只公开真实消费者需要的能力，但允许合理的共同抽象，不以文件数衡量干净性。

注册面保留明确用途：`context_segment(provider)`、`actions(registrar)`、`action_catalog_fragment(...)`、`turn_profile(profile)`、`trap_handler(reason, handler)`、`day_participant(...)`、`event_source(...)`、`schedule(...)`、`turn_trigger(...)`、`job_kind(kind, factory)`、`service(FacadeType, instance)`。可见 profile/surface 在 resolve 阶段确定，运行时不从任意字符串 service key 找私有对象。core catalog 归内核，各领域 fragment 随插件；init/reset 确定性合成用户项目 catalog，运行期 fragment 和项目可编辑配置边界明确。

TurnProfile 汇总 guidance、Action surface、段 provider 集合、完成判定与输出映射、Trap 策略、预算和输入/等待策略；它不另建执行器。user、home_reflection、memory_reflection、subagent 均调用同一内核。内核提供 profile 协议，实际组合由 Agent/插件声明；例如 Reflection profile 选择目标日 history、只读历史 Workspace 与专属写域。

EventBus/envelope/过滤基础归 runtime；包含 Turn 等待、批次确认与终结语义的 TurnInbox 归 kernel/loop；其登记表与跨 Turn Router 归 agent。这样底层不必理解 profile、Job 内容或当前根任务。

## 4. Agent SDK 与生命周期（Q6）

| 契约草图 | 语义 |
|---|---|
| `await Agent.create(root, overrides=...)` | 读取、校验与装配；不启动监听 |
| `await agent.start()` | 激活服务并接受请求 |
| `await agent.submit_turn(request) -> TurnHandle` | 排入根队列，返回身份和结果句柄 |
| `await agent.append_input(turn_id, input) -> InputReceipt` | 明确接受/拒绝，不转给其它 Turn |
| `await agent.reply(turn_id, question_id, response)` | 校验并回答指定问题 |
| `await agent.cancel_turn(turn_id)` | 取消该 Turn 及子工作 |
| `await agent.grant_cycles(turn_id, request_id, count)` | typed 预算决定，重复请求不重复加额 |
| `agent.status() -> AgentStatus` | 无 I/O 的不可变内存快照 |
| `patch_config(patch)` / `reload_config()` | async 保存候选 / 空闲边界校验激活 |
| `shutdown()` / `restart()` | async 回收并停实例 / 回收后重装配启动 |
| `await agent.publish(event) -> PublishReceipt` | 校验后路由外部事件 |
| `agent.subscribe(filter)` | 只读 Observation 流 |
| `agent.services.get(FacadeType)` | 注册服务门面；其 I/O 方法为 async |

TurnRequest 包含 profile、输入、来源与该 profile 的 typed 参数；target_day 不能成为任意请求均可篡改的万能 metadata 开关。外部 JSON 在 gateway 转类型，SDK 同样验证契约。外部发布不能伪造内部 Job 身份/终态。

单根 Turn：等待用户/Job/预算仍占根位置；新任务与 Reflection 排队，当前回复/追加输入进入 Inbox。根队列有界；重复到期 Reflection 按 profile+target_day 合并，用户任务不合并丢弃。

状态分开建模：Agent 生命周期 created/running/stopping/stopped/faulted；Turn 活动 queued/preparing/running/waiting/finalizing/finished；等待原因 input/event/timer/budget。outcome 表示最终 answered/completed/cancelled/failed 等，不让 awaiting_input 同时表示活动和终态。

TurnHandle 最终结果是完成权威；Observation 是可断档旁路。最终回答先是候选，必要持久记录和收尾成功后再发布完成；问题是中间输出，不结束 Turn。

活动/等待 Turn 持有世代及日 lease，reload 明确 busy。候选失败保留当前世代，磁盘候选状态单独报告。restart 不能杀死 Python 线程：存在不可回收 worker 时保持 faulted，需要实际宿主进程重启，不能谎报成功。

## 5. 环境事件与 TurnInbox（Q2）

### 5.1 三种消息语义和路由

EnvironmentEvent 表达事实，Signal 表达 owner 待消费更新，Observation 表达旁路输出；Trap 表达运行位置转移。可复用 envelope/基础组件，不强制共用物理 FIFO。SDK 命令是输入意图，不必假装已发生的环境事实。

envelope 建议包含 event_id/source/source_seq/received_seq/occurred_at、可选 target_turn_id 与 typed topic/payload。实例序号用于排序、去重、等待游标，不是 Memory/Workspace revision。跨源按接收顺序，墙钟仅供展示。

路由规则：

1. 定向事件只送登记中的目标 Turn；过期目标返回 closed/stale，不转成新根请求。
2. 无目标事件按段订阅和等待过滤器投递，可送根/子 Turn，同一 Turn 去重。
3. Trigger 独立决定是否创建根请求，与订阅投递不互斥；Job 事件不生成新根 Turn。
4. owner 先提交事实再发布变化。fswatch 只是变化线索，Workspace reconcile 后给出状态。
5. Observation 异步镜像，失败不撤销已接受事件，也不阻塞业务。

environment 使用注入 PublishPort/InputPort，不 import Agent。JobRegistry 管监督与状态，Router 管目的地，Inbox 管待消费记录，三者不互相接管状态机。

### 5.2 接收、消费和唤醒

Inbox 从 Turn 注册持续到收尾，与 Cycle 是否运行无关。推荐暂停期间更新 owner 状态、Inbox 与就绪条件，不并发修改 Segment；恢复边界批次同步段。前端直接取 Job/Agent 状态，仍实时可见。

take_batch 捕获有序批次，prepare/install 成功后 ack；准备失败重试同一批次，不重新 drain、不重新执行 Action。inputs 保存正文，Trace 记录 input id 和收到的时序，避免重复全文。

wait 只观察就绪，不与边界消费者竞争删除事件。登记和入队由同一事件循环协调：先查待处理事件/Job 状态 → 登记过滤器与游标 → 原子复查。禁止 drain 清空后才开始等待。EVENT 使用 after_seq，防止同一旧进度反复唤醒；已终结 Job 通过状态谓词立即满足。

### 5.3 容量与落盘

同时限制总条数、总字节、单条大小和活 Job/请求数。精确默认值通过假源压力验证后写配置，不虚构生产依据。

| 类别 | 保存策略 | 满载处理 |
|---|---|---|
| cancel/shutdown | 独立幂等控制状态，立即置令牌 | 不排在进度 FIFO 后，不静默丢弃 |
| 输入/reply/预算决定 | 不可丢记录 + 明确 receipt | 接受前背压/拒绝；接受后保留至消费 |
| Job 终态、权限/问题 | owner 权威现态 + Inbox 唯一 pending 身份 | 按活 Job/请求预留容量；拒绝新建或明确源失败 |
| 进度、文件变化 | 按 Job/资源合并最新值，保留区间/合并计数 | 可折叠，不让每行日志变成 Trace |
| stdout/stderr/大输出 | owner 落盘，事件只传 link/cursor/摘要 | 配额或写失败变成 Job 失败并收敛生产者 |
| Observation | 独立订阅缓冲 | gap/断开/重新取状态，不背压业务 |

推荐默认：Inbox 元数据内存有界，大输出 owner 落盘，不默认独立 Inbox WAL。保证进程存活期间暂停不丢已接受关键事件，不保证崩溃后续跑 Turn。无限暂停、无限不可丢输入、有限容量不能同时成立，拒绝与背压是协议的一部分。

如果需要崩溃后恢复已接受输入，需确认持久 receipt/checkpoint 与外部执行对账；仅写 JSONL 不能恢复 Cycle/线程/外部副作用。Session、Job 输出、Observation journal 和 Inbox 各有用途，不互相冒充。

### 5.4 结束交界

正常完成先检查无活 Job/待处理关键请求，再关闭普通受理并处理已接受批次；若有新输入或必须处理事件，撤回完成候选并继续，预算不足仍先等用户。

取消/失败时停止接受外部新输入，但内部 Job 清理终态仍能进入收尾通道；回收后处理已接受终态、seal，再注销 Inbox。不得先注销后等待 Job 上报退出。cancel 不等普通缓冲腾空。

## 6. Kernel、暂停、预算与取消（Q1、Q3）

保留 Phase1 语境控制/选域 → Phase2 生成 ActionCall → Phase3 执行有界批次。Phase1/2 协议失败为 PhaseFailure，进入下一完整 Cycle，Phase2 失败不以空批次继续。

启动 Job、ask、wait 都先返回已收敛 ActionResult；等待在 Cycle 边界。互斥 ask/answer/wait 不同批并行。模型看不见剩余 Cycle，不提供模型扩额工具。

建议 RuntimeTransferAction 增加 SUSPEND（Q1），只允许合法 Turn 调度边界；不序列化任意 Python 栈，不从 Action 副作用中途暂停后重跑整个 Phase：

1. Cycle 完成，消费待处理输入与结果，检查完成/等待意图。
2. 正常 INPUT/EVENT/TIMER 等待由 TurnRunner 处理，不强制抛异常。
3. 下一 Cycle 启动前预算不足，Loop 原因经 Trap 返回 SUSPEND(BUDGET)。
4. TurnRunner 保存 next_cycle_index、预算请求身份和尚未满足的等待条件，维持原 Context。
5. I/O、Job、Router 继续；事件就绪不绕过预算。
6. 有效 grant 后检查其它等待条件，从尚未启动的 Cycle 继续；cancel 进入收尾。

恢复是在同一 coroutine 安全边界继续，不是 RETRY 已完成 Cycle。Runtime 只负责转移合法性，loop 负责等待/预算内容。不扩展任意 continuation 框架。实施前以预算暂停切片核验 Q1。

| 等待 | 满足条件 | 普通 Job 进度 | 用户输入/控制 |
|---|---|---|---|
| INPUT | 对应 question_id 的 reply | 缓存，不当作回答 | 普通追加可作为新指示恢复，并标明原问题未答；cancel 中断 |
| EVENT | after_seq 后匹配事件或目标状态 | 匹配才唤醒 | 追加输入可恢复，cancel 中断 |
| TIMER | monotonic deadline | 推荐不提前唤醒 | 输入/cancel 可打断；终态提前唤醒须显式组合条件 |
| BUDGET | grant_cycles/cancel | 缓存，不启动模型 | 普通文本不等同额度授权 |

推荐 ask 无默认超时，profile 可配上限（Q3）。配置超时则以 awaiting_user 等明确终态收尾并回收 Job；旧 question 的迟到 reply 返回 closed，由 gateway 明确转新 Turn，不自动复活。等待不耗 Cycle，但零延时空转需拒绝或节流。计时区分 active execution、等待上限与总 wall-time，不默认用一个期限混算。

取消保留现有“边界权威”：入口置令牌，运行边界进 Trap；in-flight await 与令牌/deadline 竞争。同步 owner 经 to_thread，线程用线程安全控制对象，不操作 asyncio.Event。取消 await 不等于停止线程。

清理有宽限期；进程树可硬停止，线程不可假杀。未释放工作令 Agent blocked/faulted，阻止下一 Turn、归档、世代切换复用 owner。清理失败不覆盖主失败。

## 7. Context：领域事实、Turn 视图、模型投影

### 7.1 内容与顺序

Engine 拥有领域事实与动作；Segment 维护当前 Turn 的加载/展开/呈现；Context 组合公共协议。领域段不反向拥有整个 Context。每次 LLM Task 重新构造 MessageStack，不维护另一份任意追加的完整 prompt。

| 分区/顺序 | 段 | 形状和语义 |
|---|---|---|
| Background 1 | identity | State，system role，内容来自 Home/配置 |
| Background 2 | session.history | Map，prior-turn 关系骨架 |
| Background 3 | inputs | State，初始和已接受追加输入，不逐出 |
| Background 4 | home.background | Heap，目录/线索及渐进内容 |
| Background 5 | memory.background | Heap，必要根与召回知识；保护由 profile 声明 |
| Trace | trace | Stack，决策/请求/结果/问答/环境感知 |
| Working 1 | plan | State，todo 与 milestone 寄存器 |
| Working 2 | workspace.resources | State，资源链接/摘要，不自动内联正文 |
| Working 3 | jobs | State，活任务、待答请求、有界终态 |
| Task overlay | TaskPrompt | 当前 LLM Task 临时层，非段 |

history 准备时读取 prior-turn 集合，不把本 Turn 提前写入；organize 可明确修改注释并刷新视图。inputs 追加会改变前缀，因此只能说“尽量稳定”，不能保证全 Turn 字节不变或必然缓存命中。

milestone 表达 status/value/note/source links，可记失败、阻塞、尝试、决定，不等同 todo 完成。不强制 revision/digest；真实任务需要的版本信息可作为具体事实。

形状是访问/回收约定，不强迫容器实现。能力独立声明 load/evict/inspect/organize/reclaim/订阅。ref scheme/namespace 路由装配时校验无歧义；kernel 不写 owner 特判。ToolResult 保留内部调用关联，环境通知不是伪造 tool result；provider 映射归 llm。

### 7.2 段生命周期与批次

必需能力为 descriptor/open/render/seal/close；更新能力 prepare/install、完成提交 finish 按需提供，避免纯只读段写空方法。段实例就是 Turn 参与者，不新增平行 TurnParticipant；DayParticipant 处理独立日生命周期，可以保留。

- open：依 profile/day/parent 创建视图，必要依赖确定性按序打开。
- render/seal：纯内存投影，不 I/O、不改事实。
- prepare：处理本段完整有序批次，异步读取和候选计算，不改当前状态、不持久写。
- install：同步替换已校验候选，无 await/I/O/外部回调。
- finish：owner 的完成副作用。
- close：只释放资源，部分 open 失败也关闭已打开对象。

全部 prepare 成功后才 install。无效模型控制为局部结果，非法内部 typed 更新是契约缺陷。install 程序失败结束 Turn，不承诺跨段回滚；已安装批次不盲目重放。

协议草图为 `provider.open(TurnInfo) -> Segment`；`segment.prepare(tuple[SegmentUpdate, ...]) -> PreparedSegment`；`install(PreparedSegment) -> None`；`seal() -> SegmentSnapshot`；`finish(TurnCompletion)` 与 `close()` 为异步边界。TurnInfo 携带 turn/profile/day/parent 的明确身份；TurnCompletion 显式携带输入、问题、输出、执行 outcome 和 typed Action 事实，插件快照按 segment id 标识，内核不解析其内容。插件内部专用更新类型由自己的 handler 消费，公共路由不把 payload 全部退化成任意 JSON。

跨段通过同一边界批次及事实引用协作，不读取另一段未提交私有候选。Action 先经 Engine 提交业务事实再通知，Context 失败不撤销已完成 shell/文件副作用。

收尾：关闭新业务受理 → 收敛 Action/Job → 消费已接受终态 → seal → typed TurnCompletion → finish → close → 释放 lease → 发布终态。提交顺序显式声明，Session 最后记录；必要 finish 失败不发布成功。总会 close，持久结果与资源清理状态分别报告。

### 7.3 压力与追溯

默认 State 收缩 → Heap 逐出 → Stack 折叠 → Map 有限折叠。保护 identity/inputs 必需语义、待处理问题、活 Job、关键 milestone；每段声明最低可用投影。

history 仅自身超水位时有限折叠旧已整理节点；其它段过大不优先牺牲历史。完整图无限增长不能保证永久整图入模：推荐完整持久图 + 稳定 thread 聚合节点和有界详情（Q4）。仍超容量则明确失败，不静默截断问答事实。

容量结合当前模型估计，字符数只是近似，不当硬 token 保证。无回收进展即结束恢复，不无限 RETRY。LLM 声明容量失败，Context handler 回收并重建当前任务消息，已执行 Action 不重放。

core.context.inspect(ref,cursor) 统一追溯；load/evict 仅有 Heap 能力的段；organize 由 Session 提供实现，以 core 名称注册，kernel 不实现图业务。inspect 不取代 workspace.read 或一切资源 API。

## 8. Session：唯一历史体系（Q4）

SessionTurnRecord 保存不可变问答/行动事实；Map 是确定性图投影和有来源语义注释。删除平行 SessionSummaryRecord 线性历史，history 就是 Session 地图视图。

无模型抽取：初始问题、追加输入、ask/reply、最终回答、outcome、显式 core.reason 摘要、Action 请求/结果、milestone、资源引用/URL。“推理”指可保存显式 Action 或摘要，不指供应商私有推理原文。

Trace 执行时维护 typed Action 事实，折叠只改变模型渲染，不从压缩文本重新猜调用配对。中断时每个已产生调用有结果或明确 cancelled/not_executed/unknown，不能伪造成功，也不能因一对缺失导致全部问答无法保存。

地图可有 turn/thread/resource/decision 节点及 follows/continues/touches/decides 边；resource 已承载链接时不强制再建重复 link 节点。跨日引用附 owner/day，旧 workspace:path 不得解析成今日同名文件。

finish 先按 turn_id 幂等写 record，再补确定性图。organize 修改 gist/thread/关系并引用原 Turn，不改原话；注释是需持久保存的知识，不宣称都能从原事实无损重建。地图更新失败可补投影且保留注释；record 写失败是必要持久化失败。

新 User Turn 提供上一成功用户 Turn 待整理标记；失败/取消也保留事实，但不称成功。AWAITING_USER 代表仍待后续回复，不自动等同成功回答；是否允许一起整理见 Q4。

User 根 Turn 进入用户 Session，Reflection 不进入。推荐子 Turn 作为可追溯子记录并关联 parent_turn_id，不重复成为根历史条目；由同一个 Session owner 保存，不另造日志。

## 9. Home、Memory、Reflection 与 CalendarDay

两个独立 profile 和专属 domain：home_reflection、memory_reflection。共用内核、动作配置、模型链、TaskPrompt/Skill 挂载，不保留维护专用第二套 Loop。

| 工作类型 | 可写事实 | 动作与完成 |
|---|---|---|
| User Turn | 活动 Memory.md、Workspace、Home overlay | 正常回答或其它终态 |
| Home Reflection | 审核后 actual Home | diff_list/detail/accept/reject/rewrite/done |
| Memory Reflection | target daily、entity/concept/fact/note | write_daily/write/retire/done |

User 的实际 Action surface 不含专属域，注入的服务也限制写权限，不只靠提示词。子 profile 不继承超出父 profile 的长期写能力。

Home rewrite 默认改待审副本，accept 明确提交 actual，reject 清待审项；批量返回逐项结果，不假称多文档原子事务。review 是 Agent Reflection 审阅，不默认逐项向人审批；不引入 Git。Skill top 线索进 Background，domain/action Skill 只挂对应 Task，正文局部读取。

Memory 删除 8 步控制器、preview、多文档 CAS/journal、revision/activation_count/session_revision/active_memory_digest。活动 Memory.md 同样使用轻量 owner 操作，不暗留 CAS。保留类型、身份、来源、关系、摘要和必要状态；具体字段由 codec 统一，不在计划增设关系同义字段。

单文档原子替换；catalog/backlinks/embedding 为可重建派生数据。retire 保留迁移说明，redirect 存在、类型合法且不成环；先写目标再退休旧项。Reflection 失败不撤销已完成单文档写入，准确报告进度。

Reflection 插件编排触发/去重/完成，Home/Memory 管存储，日切归 agent/day。有 Session 无 daily 可触发补记；已有 daily 仍允许手动重整今天/历史日。失败调度有界，不即时无限重入。不保留 availability.json 平行事实。

CalendarDay 取代 BusinessDay；面向用户说“今天、总结、整理”。根开始锁定 day/世代，跨午夜继续原日；根及子工作完全收尾后归档再开新根。Reflection target/source_day 与运行 active_day 分开，历史 Workspace 只读。

保留 home/memory/runtime/archive 布局、确定性日切恢复 journal；删除 Memory 事务不等于删除归档恢复。TOML 原则稳定，仅已确认 app→agent、maintenance→reflection 及新增能力配置。新 Session schema 不隐式兼容 v4，不自动 reset 用户数据。

## 10. Workspace 与 execution

磁盘是内容事实，manifest 是轻量索引，State 段是投影。动作提供 list/search(literal|regex)/read/write/edit/append/move/mkdir/delete/restore/trash_list/tag/describe/compose/analyze；小文件整读、大结果有界分页。

删除 expected_digest/revision、read-set 复验、described_digest、retention、压力 trash、Trash marker 和恢复 Trap。保留路径解析、owner 锁、原子文件替换、简单 Trash。单文件 edit 全部匹配后一次提交，无匹配/歧义局部失败，不能改半份文件。

tag 可支持 pinned/tmp/library；library 标记不代表实现了独立长期 Library。scan/reconcile 用于 Turn 准备/文件事件/必要查询，不把 manifest 当比磁盘更权威的内容。

Engine 锁只能协调 Engine 调用，锁不住 ACP/shell 直接写。推荐并发子工作独立输出目录，交接后合并；显式共写则承认覆盖风险，不宣称 fswatch 防止 lost update，不因此恢复全局 CAS（Q5）。

execution 合并 script/shell/supervised_process：有界 run_script/run_shell；后台 start/stdin/collect。collect 是读结果，不是释放资源唯一入口；进程结束即回收执行句柄，结果按 Turn 保留。

## 11. Job、ACP 与 MCP（Q5、Q7）

### 11.1 Job

Job 属启动 Turn，可跨 Cycle，不跨 Turn；Registry 在 Agent 索引不改变所有权。公共 status/stop/wait，种类域 start/send/collect。状态区分 starting/running/waiting_input/stopping/succeeded/failed/cancelled，适配器私有状态不直接充当公共状态。

必要事实为 owner_turn_id/job_id/kind/state/result refs/pending requests。backend 拥有执行资源，Registry 监督生命周期。终态单调且发布一次，stop/collect 幂等；执行完成与资源释放分开。

正常 answer 时有活 Job：推荐局部 completion_blocked，模型选择 wait/stop，框架不静默杀任务后给成功回答。取消/失败才自动递归回收。输出归 Workspace，不另建跨 Turn Job 数据库。

### 11.2 内部子 Turn

tinysoul_turn Job 使用同一 TurnRunner，独立 Context/Inbox/Action scope，不进根队列。父取消传播，子 RuntimeTransfer 不能指向父 frame；子失败成为父 Job 结果。

建议有限并发/递归、profile 能力不超委派集合、独立 plan/trace，共享 Engine 而不共享 Segment。只接父显式 brief/references，不隐式复制父全部语境。

子预算不足不得自动扩额。推荐经同一用户控制入口呈现 root/child 路径，父见 budget_blocked，可继续其它允许工作。全树预算还是每子独立预算待 Q5，不能先实现两套。

当前倾向每个内部子 Turn 使用独立 Cycle 预算，并由根树的并发/递归上限约束总体规模；这样子任务不会因另一个子任务消耗共享计数而突然停止。所有额外 Cycle 仍由用户授予，父模型不能代批。ACP 外部 agent 的内部 Cycle 通常不受 TinySoul kernel 计数控制，需用 Job 的时间/输出/资源上限表达，不能宣称本地 Cycle 预算覆盖外部推理费用。

### 11.3 ACP

ACP 客户端归 subagent 插件；TinySoul ACP server 不在本次范围。先锁真实 agent adapter、SDK 和协议版本，再映射初始化/session/prompt/流更新/权限/取消/退出。

旧草图“ACP v2”“prompt 立即返回”“idle 就是完成”“session/close 必存在”未验证，本版删除这些实现假设。本轮未完成目标 adapter 连通验证，S6 先以官方文档和 fake adapter 核验。

Job 表示一次有终点的委派，连接/session 是可复用资源；终结 Job 不回 running。推荐 send 只在适配器支持的活任务追加机制中使用；最终任务结束后新委派建新 Job，可以复用 session。无中途追加能力则明确局部失败，不强发第二个 prompt。

权限问题以 request_id 进入 Job 待答，父经 subagent.respond 回应。历史“读 auto_allow、写 ask_model”须映射真实选项；任意 shell 不能凭模糊描述可靠分类，未知请求待答/拒绝。父 INPUT/BUDGET 暂停时不启动隐藏模型代答，可由明确用户控制入口处理。

取消须收敛未决反向请求与协议任务，不响应则终止受控进程树。最终结果信号按选定协议确定，不从流文本猜测终态。

### 11.4 MCP expand

expand 持连接、工具索引、能力协商；Phase2 只见 search/describe/call/servers。搜索和完整 schema 描述进 foldable Trace，无 expand.tools 段。

TinySoul schema 只校验外壳；远端 inputSchema 由选定 JSON Schema validator/SDK 校验，不能忽略未知约束后宣称通过。支持 tools 分页/列表变更/能力声明、错误和结构化结果归一化；旧工具失效返回明确局部说明。

大输出落 Workspace，Trace 留摘要/link。工具业务错误局部反馈，连接不可用可由 Action 返回 unavailable；内部错误仍模块失败。远端写超时可能已有副作用，不自动重试无法证明可重放调用。

MCP 连接可常驻 Agent，不代表调用 Job 跨 Turn；首批 call 有界执行。取消不保证远端系统撤销副作用。长任务、resource/prompts 按后续明确范围扩展。

S6 核验入口：[ACP 官方文档](https://agentclientprotocol.com/)、[MCP 规范](https://modelcontextprotocol.io/specification)、[MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)。它们是后续入口，不是本轮已验证版本证据。

## 12. 失败语义与 Gateway

### 12.1 三层失败

| 情况 | 归类 | 外层行为 |
|---|---|---|
| 模型协议失败、参数无效、已知工具失败 | typed 局部结果 | 有界反馈，下一完整 Cycle |
| executor 非法对象/身份、owner 损坏、catalog 契约错误 | 模块边界异常 | owner bridge → Runtime 收束 |
| provider 短暂失败 | LLM 局部恢复 | 耗尽后才跨模块 |
| 模型容量不足 | LLM 原因、Context 策略 | 仅重试可重放 frame |
| 预算不足 | Loop 原因 | Trap → SUSPEND，用户决定 |
| RuntimeException/TransferInterrupt | 已归类控制 | 原样传播至合法 frame |
| cancel | 独立取消身份 | 回收后边界决定 outcome |
| Observation 失败 | 旁路失败 | 隔离，不影响业务 |
| close 失败 | 清理诊断 | 继续其它清理，保留主失败 |
| SDK 对已结束 Turn 回复 | typed rejection | 不伪造 Runtime frame |

宽泛捕获限有说明的动态边界、观察、清理；未知异常不能全部变 executor_raised 普通反馈。BaseException 必要转交时保留取消/退出。payload 保留 module/kind/error_type/必要身份与有界说明，不直传 str(exc)、配置原值、完整资源。

### 12.2 Gateway

Endpoint v2 经 SDK 提供 agent 状态/restart/reload、turn submit/status/inputs/reply/cancel/budget、Job 查询/停止/回应、Reflection、配置候选、Workspace、replay/WS。精确路由/schema/错误码在 S5 固定，避免本计划维护另一套易漂移协议表。

WS 断开不取消 Turn；问题可由状态查询恢复，Observation gap 不等于业务丢失。配置保存成功不等于激活成功。gateway/project 复用 init/reset/lease；删 app 时同步 pyproject console script/package data。后端仅更新前端对接文档，不擅改 visualization。

### 12.3 可行性

既有 TurnRunner/ActionEngine/Context 批次/Session 图/overlay/day lease 是可复用基础，主要工作不是改函数 async，而是生命周期、事实接口与失败归属。最高风险为暂停位置、背压、线程取消、收尾事实、午夜资源和外部终态，必须用完整协作切片验证。

## 13. 执行计划与验收

所有实施阶段未完成。历史 S0 定稿不代表本轮复审关闭。子计划只有实现/文档/必要验证全部通过才 done 并归档；docs/design 只写已落地部分。

| 阶段 | 范围 | 必需证据 |
|---|---|---|
| S0 | 确认 Q1/Q2/Q6 和子任务边界，修 AGENTS 指向，冻结单一契约 | 无冲突目标、待决有状态 |
| S1 | bridge 归 owner、async LLM、事件/取消原语、import 检查 | frame 重放、取消身份、旁路隔离 |
| S2 | 三 Phase、段批次、最小 SDK/CLI、fake Job、Inbox/wait/budget、打包入口 | submit→wait→resume→finish；预算/取消/竞态 E2E |
| S3 | Session→Workspace→Home→Memory→Reflection→execution/resource/web | 各 owner 正反路径；完整日切；删旧 CAS 契约 |
| S4 | fswatch/scheduler、ask/reply、容量、reload/restart、完整监督 | 暂停收事件、午夜、泄漏阻断 |
| S5 | Gateway v2、项目命令、HTTP/WS/replay、协议文档 | SDK 映射、重连、wheel/init |
| S6 | 锁 ACP/MCP adapter/协议/SDK，内部子 Turn | fake 故障矩阵，真实 external smoke 单独声明 |
| S7 | 全仓文档/AGENTS/测试/打包一致，删旧入口/死抽象 | Full/typecheck/import 图/完整 E2E |

S1–S2 为相邻基础迁移单元，不宣称迁移中间提交可部署。S2 删除 app/loop/context/action 时同步所有入口依赖；未迁 owner 若仍依赖旧内核，扩大该原子切片，不能用 alias 掩盖。现部署继续旧 checkout，不 reset 用户数据。

核心验收：

1. 全局 Workspace 事件送匹配根/子，过期定向事件不激活其它 Turn。
2. wait 前/登记期间/超时同时完成 Job，不丢唤醒、不重复消费。
3. 高频进度不阻塞 cancel/reply；容量不足接受前明确拒绝，已接受输入保留。
4. 等待不耗 Cycle，事件不绕预算，重复 grant 不重复加额。
5. 后段 prepare 失败不部分安装；重试不做 Action；install 缺陷不虚假回滚。
6. 部分 open/finish/close 失败清理，主失败保留，Session 幂等、Map 可补。
7. ask/reply/追加/reason/answer 可追溯，Trace 折叠不破坏事实配对。
8. User/子 profile 无越权持久写，Reflection 准确保留单文档已提交事实。
9. 跨午夜同 Turn 保持旧日，收尾前不归档，旧资源不指向今日同名文件。
10. 泄漏阻断下一 Turn/reload，async 取消不伪称撤销远端副作用。
11. 父取消递归回收，子失败只成 Job 结果，默认并发目录不覆盖。
12. ACP final/权限/取消/断流；MCP schema/分页/错误/未知写结果有明确映射。
13. runtime 不 import 上层，kernel 不识别领域内容，每个 SPI 有真实消费者。
14. SDK 结果与 Observation 分离，重连能查询待答问题及终态。

验证遵循 AGENTS：聚焦 → Fast → Full → typecheck，generation/wheel/external 分别执行；不全局 skip 掩盖损坏。测试保护协议和失败，不固定提示词全文/文件数/私有实现。本轮仅文档修改，核验 diff、路径、状态与交叉引用，没有运行代码门禁或外部能力测试。

## 14. 决策状态与修订记录

### 14.1 沿用已确认语义

保留历史 D1–D29 有效决定，不因重组重新申请批准：

- D1/D4/D5：同步 owner + async 适配；llm 顶层；pytest-asyncio。
- D2/D3/D7/D10/D12/D13：Agent/环境/Job/ask、行走骨架、显式 reload、文件监视。
- D6/D14/D19/D20/D21/D22/D26：plan 内核段、独立领域段、三分区、统一 inspect、Session Map、MCP 结果进 Trace；Engine/Segment/Context 及 prepare/install、finish/close 分离。D11 旧拆分撤销。
- D8/D9：配置 section 例外改名范围、Session 新 schema，不隐式迁移 v4。
- D15/D16/D17/D18：subagent、expand、execution 合并，adapter/权限需真实协议核验。
- D23/D24：两个 Reflection 域、User 持久写边界、CalendarDay、Memory 轻量化、Workspace 去 CAS。
- D25：单根 Turn，等待不并发独立 User/Reflection。
- D27：Job 跨 Cycle 不跨 Turn，撤销 AGENT scope。
- D28：EVENT/TIMER，预算确定性检查，由用户决定，模型不见额度。
- D29：TurnInbox 持续接收相关环境事件，不是 Job 专属缓存。

确认语义不等于 API 已批准或已实现。新建议统一收敛为 Q；旧 P1–P9 和悬空 13.13 引用不再是另一套目标。

### 14.2 待讨论

| 编号/状态 | 推荐 | 需要确定的行为 |
|---|---|---|
| Q1 pending | Turn 边界 SUSPEND；正常 wait 由 TurnRunner，预算经 Trap | 不用 END/RETRY 模拟暂停 |
| Q2 pending | Inbox 内存有界、大输出 owner 落盘、关键事件预留/背压 | 只保进程存活暂停，还是要求崩溃后恢复已接受输入 |
| Q3 pending | ask 默认无超时；TIMER 默认不被普通 Job 终态打断 | 自动超时及提前唤醒默认策略 |
| Q4 pending | 不可变事实+可改注释，大图 thread 有界投影 | 是否整理未回答/失败 Turn，不把它们称成功 |
| Q5 pending | 子任务独立目录、有限并发/递归、回答前显式收敛 Job | 子预算独立还是全树共享；同文件并写默认 |
| Q6 pending | SDK 生命周期分义、候选与激活分离、bridge 归 owner | 确认依赖和生命周期契约 |
| Q7 pending | Job 为一次有终点委派，ACP session 可复用 | 是否要求延续同 session；首个 adapter |

优先 Q1/Q2/Q5/Q6，决定基础协议；其它在所属阶段细化，不要求现在批准全部远期细节。数字容量、SDK 版本、精确路由通过测量/协议验证确定。

### 14.3 本轮修订

- 核验当前 checkout 与远端 HEAD；重新检查关键运行、异常、Context 和 owner 边界。
- 合并旧正文/替换预览，保留确认状态，建议不伪装为已决。
- 删除旧 AGENT-scope Job、冲突 API、未经验证 SDK 假定、悬空引用。
- 补暂停恢复、Inbox 容量/消费/唤醒/落盘、收尾交界、线程泄漏。
- 明确 Session 事实/投影/注释、压力边界、Reflection 部分提交、跨日身份。
- 明确 ACP 会话与 Job 区别、MCP 验证、子任务共享写限制。
- 重排完整切片和验证门禁；未改后端或前端实现。

建议 commit：`docs: consolidate agent refactor semantics and execution plan`。
