# Agent 架构重构：设计语义、契约与执行计划

状态：`in_progress`（R1 已完成；R2 已继续迁入核心段、Home/Memory Heap、Session 事实 Map 与统一检查路由，实施见第二轮子计划第 15 节；S1 剩余及 S2 完整内核/SDK 闭环仍在实施）。
修订日期：2026-09-15。初始复审代码：`e930c9c444deb0073ab3d7f016057245bad66ca6`（当次查询远端 HEAD 相同）；R2 分析基线为本地 `6821983`，本次未查询远端。

本文件描述目标设计，不代表当前实现。用户本轮授权分析、修订计划与讨论，不据历史“全面授权”直接实施代码。确认状态见第 14 节。用户本轮已确认上一轮架构方向，特别是受限 SUSPEND 与 Inbox 保障边界，并补充 Reflection 通用动作叠加、ACP 显式连接及 Working 呈现；新增具体签名与连接寿命仍标明建议。原“正文 + 替换预览”合并为单一方案，旧版由 Git 保存，不并行保留互相冲突的接口。API 均为契约草图，具体名称与类型在子计划落定。

## 1. 项目理解与重构意图

TinySoul 是长期运行的个人 Agent：在环境中感知与行动，通过多 Cycle 求解，通过 Session 保存对话经验，通过 Memory 与 Home Reflection 沉淀知识、偏好和可复用能力。项目已有资源 owner、构造式 Context、分层失败和可复用 Turn 内核；本次应围绕这些资产重整依赖与生命周期。

干净性首先评价架构语义、依赖方向、领域内聚和长期一致性。Action 异常、线程超时是服从这些语义的实现事项，不作为重构主线。设计判断顺序：谁拥有事实 → 谁可以修改 → 何时可观察 → 谁处理失败 → 谁负责结束与回收。“干净”不等于删除合理抽象，也不等于让所有业务都经消息总线绕行。

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
| `action/core/runner.py` 的 leaked timeout | 线程承载可超时执行，收敛较复杂 | 短 owner 操作完成后退出边界；长执行使用受控进程，共用执行控制 |
| `runtime/bridge/_payload.py` | 配置原值、异常文本可能进入 payload | owner 显式给出有界诊断 |
| `session/completion.py` | 从 Phase2/3 消息解析 Action 配对 | Trace 导出 typed 事实，Session 不猜消息布局 |
| `loop/completion.py` | 有序完成处理管线 | 保留有序提交，区分 finish/close |
| `workspace/engine.py` | digest/revision/read-set 深入提交逻辑 | 删除对应动作契约与测试，保留原子文件操作 |
| `home/review.py`、`home/overlay.py` | actual/overlay/review | 保留边界，简化专属域 |
| `memory/transaction.py`、`maintenance/*` | Memory 多文档流程、维护编排 | 单文档写，编排与存储分离 |
| `maintenance/archive/engine.py` | active day lease、归档恢复 journal | 保留，不随 Memory 事务删除 |
| `app/builder.py`、`app/generation.py` | 集中装配、世代与资源关闭 | 拆组合根与插件贡献 |
| `llm/task.py`、`runtime/observation.py` | 局部恢复与旁路观察 | 保留三层失败，不机械删除宽泛捕获 |

上一轮核验发现 AGENTS 的任务指向和过渡条款陈旧。本轮随用户确认同步修正任务指向、Job/bridge/SUSPEND 目标；其它旧实现说明保留过渡标记，随实际落地更新。

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

TurnProfile 汇总 guidance、Action surface、段 provider 集合、完成判定与输出映射、Trap 策略、预算和输入/等待策略；它不另建执行器。user、home_reflection、memory_reflection 均调用同一内核；未来内部 subagent 同样复用，不在本次预建专属调度/预算机制。内核提供 profile 协议，实际组合由 Agent/插件声明；例如 Reflection profile 选择目标日 session、只读历史 Workspace 与专属写域。

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

活动/等待 Turn 持有世代及日 lease，reload 明确 busy。候选失败保留当前世代，磁盘候选状态单独报告。shutdown/restart 复用执行资源统一收尾，短 owner 操作完成后再释放 lease，长执行由进程回收。宿主 I/O 真正卡死属于实例异常，不另建线程隔离与 owner 恢复状态机，也不承诺应用内 restart 能杀死线程。

## 5. 环境事件与 TurnInbox（Q2）

### 5.1 三种消息语义和路由

EnvironmentEvent 表达事实，Signal 表达 owner 待消费更新，Observation 表达旁路输出；Trap 表达运行位置转移。可复用 envelope/基础组件，不强制共用物理 FIFO。SDK 命令是输入意图，不必假装已发生的环境事实。

envelope 建议包含 event_id/source/source_seq/received_seq/occurred_at、可选 target_turn_id 与 typed topic/payload。实例序号用于排序、去重、等待游标，不是 Memory/Workspace revision。跨源按接收顺序，墙钟仅供展示。

路由规则：

1. 定向事件只送登记中的目标 Turn；过期目标返回 closed/stale，不转成新根请求。
2. 无目标事件按段订阅和等待过滤器投递给登记中的 Turn，同一 Turn 去重；未来内部子 Turn 可复用此路由，不预建并发调度器。
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

已确认默认：Inbox 元数据内存有界，大输出 owner 落盘，不默认独立 Inbox WAL。保证进程存活期间暂停不丢已接受关键事件，不保证崩溃后续跑 Turn。无限暂停、无限不可丢输入、有限容量不能同时成立，拒绝与背压是协议的一部分。

如果需要崩溃后恢复已接受输入，需确认持久 receipt/checkpoint 与外部执行对账；仅写 JSONL 不能恢复 Cycle/线程/外部副作用。Session、Job 输出、Observation journal 和 Inbox 各有用途，不互相冒充。

### 5.4 结束交界

正常完成先检查无活 Job/待处理关键请求，再关闭普通受理并处理已接受批次；若有新输入或必须处理事件，撤回完成候选并继续，预算不足仍先等用户。

取消/失败时停止接受外部新输入，但内部 Job 清理终态仍能进入收尾通道；回收后处理已接受终态、seal，再注销 Inbox。不得先注销后等待 Job 上报退出。cancel 不等普通缓冲腾空。

## 6. Kernel、暂停、预算与取消（Q1、Q3）

保留 Phase1 语境控制/选域 → Phase2 生成 ActionCall → Phase3 执行有界批次。Phase1/2 协议失败为 PhaseFailure，进入下一完整 Cycle，Phase2 失败不以空批次继续。

启动 Job、ask、wait 都先返回已收敛 ActionResult；等待在 Cycle 边界。互斥 ask/answer/wait 不同批并行。模型看不见剩余 Cycle，不提供模型扩额工具。

已确认 RuntimeTransferAction 增加受限 SUSPEND（Q1），只允许合法 Turn 调度边界；不序列化任意 Python 栈，不从 Action 副作用中途暂停后重跑整个 Phase：

1. Cycle 完成，消费待处理输入与结果，检查完成/等待意图。
2. 正常 INPUT/EVENT/TIMER 等待由 TurnRunner 处理，不强制抛异常。
3. 下一 Cycle 启动前预算不足，Loop 原因经 Trap 返回 SUSPEND(BUDGET)。
4. TurnRunner 保存 next_cycle_index、预算请求身份和尚未满足的等待条件，维持原 Context；所有等待进入同一个 Loop 等待处理流程。
5. I/O、Job、Router 继续；事件就绪不绕过预算。
6. 有效 grant 后检查其它等待条件，从尚未启动的 Cycle 继续；cancel 进入收尾。

恢复是在同一 coroutine 安全边界继续，不是 RETRY 已完成 Cycle。Runtime 只负责转移合法性，loop 负责等待/预算内容。SUSPEND 的通用转移只带目标 frame，不携带需要 runtime import kernel 才能解释的 WaitRequest；Loop 在发起暂停前持有 typed 等待条件。不扩展任意 continuation 框架。实施时以预算暂停切片验证，不再将是否支持 SUSPEND 列为待决。

| 等待 | 满足条件 | 普通 Job 进度 | 用户输入/控制 |
|---|---|---|---|
| INPUT | 对应 question_id 的 reply | 缓存，不当作回答 | 普通追加可作为新指示恢复，并标明原问题未答；cancel 中断 |
| EVENT | after_seq 后匹配事件或目标状态 | 匹配才唤醒 | 追加输入可恢复，cancel 中断 |
| TIMER | monotonic deadline | 推荐不提前唤醒 | 输入/cancel 可打断；终态提前唤醒须显式组合条件 |
| BUDGET | grant_cycles/cancel | 缓存，不启动模型 | 普通文本不等同额度授权 |

推荐 ask 无默认超时，profile 可配上限（Q3）。配置超时则以 awaiting_user 等明确终态收尾并回收 Job；旧 question 的迟到 reply 返回 closed，由 gateway 明确转新 Turn，不自动复活。等待不耗 Cycle，但零延时空转需拒绝或节流。计时区分 active execution、等待上限与总 wall-time，不默认用一个期限混算。

取消保持“边界权威”，并统一为一条生命周期规则：执行方持有资源，执行方完成/取消并回收，Turn 在执行收敛后离开边界。复用 ActionExecutionControl 和 backend 清理，不新增泄漏注册表、owner 隔离队列或自动修复状态机。

| 执行类别 | 承载与取消 | 收敛语义 |
|---|---|---|
| 短 owner 操作 | 同步 Engine，经 to_thread 避免阻塞事件循环 | 开始前检查取消；已进入的读取/原子写完成后退出，再处理 Turn 取消 |
| 可取消 I/O | 原生 async，适配器处理 deadline/取消 | 等待本次执行退出，不遗留脱管 task |
| 脚本/shell/长计算/需硬停止代码 | 受控 subprocess；前台 Action 与后台 Job 复用同一 backend | 先请求停止，宽限后终止进程树并 wait 回收 |

短 owner 操作不包含 LLM/网络等待/任意用户代码。“短”是承载约束，不声称文件系统永不阻塞。deadline 到期后停止安排后续步骤，当前原子操作完成并记录真实提交结果；不能抛弃 to_thread await 后宣称取消成功。适配层保留 future 并等待完成，单独 shield 不等于完成清理。

罕见宿主阻塞由现有实例失败边界报告并停止接受新工作，交宿主退出/重启处理，不建设恢复框架。正常取消无需额外 owner 污染集合。清理失败仍不覆盖主失败。

## 7. Context：领域事实、Turn 视图、模型投影

### 7.1 插槽、形状、段与能力

通用段重构已从 Workspace 接入：composer.py 按注册投影的 slot/order 组合，Workspace 视图已脱离内核 Working；engine.py 仍持有 Session 与通用 Background，trace.py 的 TurnTraceHeap 仍是折叠实现。当前并非完整的 shape/slot/能力 SPI；下文继续描述重构目标。

四个正交概念：

| 概念 | 回答的问题 | 内容 |
|---|---|---|
| Slot / 插槽 | 段放在哪里 | BACKGROUND、TRACE、WORKING，确定大顺序 |
| Shape / 形状 | 段如何组织和呈现信息 | Heap、Map、Stack、State，提供共同使用与回收约定 |
| Segment / 段 | 这一块语境是谁、服务什么 | 稳定 id、显示名称、领域 owner、本 Turn 实例 |
| Capability / 能力 | 内核可以请求它做什么 | load/evict/inspect/organize/reclaim/事件更新，显式按需声明 |

一个插槽容纳多个段，段选择一个主插槽和一种主形状；同一个插件可提供多个段，没有 Context 内容的插件可以不提供段。同一 owner 的不同内容确需不同形状/生命周期时分段，不为每个字段单独造段。TRACE 插槽与 trace 段重名无歧义，二者是不同字段。

Slot 固定整体构造顺序；段在槽内按显式 order 排列，同序按稳定 id 排序，保证确定性。新增普通领域只注册段，不改 Slot 枚举。order 只管渲染顺序，不隐含 open/finish 依赖；生命周期依赖由装配声明单独处理。TaskPrompt 继续是当前任务 overlay，不新增第四个持久插槽。

### 7.2 形状的公共语义与复用

| 形状 | 公共结构与使用方式 | 通用能力及压力行为 |
|---|---|---|
| Heap | 线索/目录为入口，按 ref 展开细节；不是优先队列的 heap | 显式加载、逐出已加载细节，保留重新发现入口 |
| Map | 有稳定节点身份与关系的历史视图 | 检查节点；按 owner 规则聚合详情，保留关系和追溯入口 |
| Stack | 按序追加的本 Turn 交互帧，顺序和调用关联稳定 | 追加、折叠旧帧、追溯原事实；不是简单 LIFO pop |
| State | 当前时刻的工作现态，替换或 patch | 刷新快照、压缩显示；不把过往快照堆成另一份历史 |

形状不能只是四个没有消费者的标签。Context 使用 shape 选择默认回收优先级和检查契约，段使用公共的加载集合、ref 分页、帧折叠等构件；领域 owner 决定哪些细节重要、如何概括、哪些事实必须保护。复用现有 background/trace/working 算法，移出领域特判；无需为 Map 额外建立通用知识图谱数据库。

统一基线是 descriptor、render、seal、close；按需组合更新、渐进加载、检查、整理与回收协议。采用 Protocol + 小型可复用实现组合，不使用一个包含所有空方法的巨大基类。shape 不自动授予所有能力：State 可声明完全不可回收，Map 的 organize 只有 Session 这样的实际 owner 提供；descriptor 声明和实际 handler 必须在 resolve 时一致。

通用回收请求表达目标容量和原因，返回实际减少量/是否还能回收；具体候选生成与安装仍走同一 prepare/install 边界。纯 render 不改状态。计量接口可以统一，但不能要求 owner 用统一算法解释 Home、Memory 或 Session 的语义。

### 7.3 段结构、顺序与命名

命名建议基于语义而非包路径：段 id 全部去点号，采用简短名；owner、slot、shape 已是独立元数据，不再重复编码在 id 中。id 使用 lower_snake_case，按当前装配集合唯一；冲突时在装配时报错，必要时选更具体名称，不静默覆盖。不保留旧点号 id 的兼容别名。

这只调整 Context 段命名；Action 的 domain.action、事件 topic 和资源 Link 的命名协议不因段改名而全仓删除标点。显示标题与稳定 id 分离，前端显示“会话历史”等自然语言。

Engine 拥有领域事实与动作；Segment 维护当前 Turn 的加载/展开/呈现；Context 组合公共协议。领域段不反向拥有整个 Context。每次 LLM Task 重新构造 MessageStack，不维护另一份任意追加的完整 prompt。

| 分区/顺序 | 段 | 形状和语义 |
|---|---|---|
| Background 1 | identity | State，system role，内容来自 Home/配置 |
| Background 2 | session | Map，对话事实、发展关系与有来源的推导线索 |
| Background 3 | inputs | State，初始和已接受追加输入，不逐出 |
| Background 4 | home | Heap，目录/线索及渐进内容 |
| Background 5 | memory | Heap，必要根与召回知识；保护由 profile 声明 |
| Trace | trace | Stack，决策/请求/结果/问答/环境感知 |
| Working 1 | plan | State，todo 与 milestone 寄存器 |
| Working 2 | workspace | State，资源链接/摘要，不自动内联正文 |
| Working 3 | jobs | State，活任务、待答请求、有界终态 |
| Working 4 | connections | 插件 State 段，可委派 ACP 连接的当前状态 |
| Task overlay | TaskPrompt | 当前 LLM Task 临时层，非段 |


命名映射：`history → session`、`home.background → home`、`memory.background → memory`、`workspace.resources → workspace`、`subagent.connections → connections`。`identity/inputs/trace/plan/jobs` 保留。`plan` 明确包含待办与事实寄存器，不改成容易和 TaskPrompt 混淆的 task；`session` 表达会话事实、发展关系与推导线索，Session 模块是其 owner；`connections` 当前表示 ACP 端点，不等于正在执行的 sub-agent Job。若未来 MCP 也有独立连接段，使用 `mcp_connections` 等具体 id，或另行设计有真实需求的共同 owner，不能让两个插件各自注册同名段。

session 准备时读取已结束 prior-turn 的事实与语义地图，不把当前 Turn 的运行轨迹复制进去；当前运行中的发展记录仍由 trace/plan 承载，结束时再归入 Session。organize 可明确修改已有注释并刷新视图。inputs 追加会改变前缀，因此只能说“尽量稳定”，不能保证全 Turn 字节不变或必然缓存命中。

milestone 表达 status/value/note/source links，可记失败、阻塞、尝试、决定，不等同 todo 完成。不强制 revision/digest；真实任务需要的版本信息可作为具体事实。

形状是访问/回收约定，不强迫容器实现。能力独立声明 load/evict/inspect/organize/reclaim/订阅。ref scheme/namespace 路由装配时校验无歧义；kernel 不写 owner 特判。ToolResult 保留内部调用关联，环境通知不是伪造 tool result；provider 映射归 llm。

### 7.4 段生命周期与批次

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

### 7.5 插件声明与前、中、后交互

插件显式声明：id/owner/title、slot/order、shape、启用 profile、ref 路由、可选能力 handler、订阅过滤器及保护/水位策略；provider 通过已注入的 Engine/公开服务创建每 Turn 段。段不自行读取全局配置，不获取整个 Agent 或其它段私有状态。

声明示意（协议草图，不是新增已实现代码）：

```python
registry.context_segment(
    HomeSegmentProvider(engine=home_engine),
    descriptor=SegmentDescriptor(
        id="home",
        owner="home",
        slot=SegmentSlot.BACKGROUND,
        order=40,
        shape=SegmentShape.HEAP,
    ),
)
```

能力和订阅通过 provider 的类型化贡献表达，注册时验证；示意省略这些字段，不能理解为内核按 id == home 自动补规则。profile 选择参与段并提供该 Turn 参数。ref resolver 唯一地路由到 handler；声明模型可用控制时复用现有 control/action 注册与结果协议，不增加第二套工具执行通道。

| 时点 | 谁调用谁 | 允许的工作 |
|---|---|---|
| 装配 | Plugin → Registry | 注册 provider、描述与可选能力；校验依赖，不提前启动 Turn |
| Turn 开始 | Context → provider.open(TurnInfo) | 从 Engine 取得背景/现态，建立本轮加载集合和初始视图 |
| 运行边界 | Inbox/内部更新 → Segment.prepare → install | owner 解释事件/更新、读取新事实；内核统一批次安装 |
| 模型控制 | Context 路由 → 已声明 handler | load/evict/inspect；按原控制/Action 结果方式反馈 |
| 领域操作 | Action → Engine → 更新通知 | 先改领域事实，再通知段刷新；不由 Context 提交文件事务 |
| 每次模型调用 | Composer → segment.render | 依 slot/order 构造 MessageStack，叠加 TaskPrompt |
| Turn 结束 | seal → finish → close | 导出快照、owner 完成提交、释放本 Turn 视图资源 |

事件适配 handler 将已校验事件转为该段 typed 更新，再在 prepare 做读取；监听任务不直接写 Segment。插件内部提交使用注册时绑定的段更新入口，只能提交已声明更新类型，不能凭字符串任意改其它段。对跨 Turn 的公共事实变更，经订阅分别刷新各自视图。

Home 示例：open 加载目录与必要条目；Phase1 load 通过 Home Engine 读取内容并安装本 Turn 加载视图；home 动作改 overlay 后刷新相应条目；压力时逐出细节；seal 导出加载事实，close 清理本轮视图。普通 Turn 的 finish 不把 overlay 自动提交 actual。

Session 示例：open 读取 prior-turn 地图；inspect 为有界只读；organize 经 Session Engine 写语义注释后刷新 session，不能塞进“只读 prepare”；finish 保存本 Turn typed 事实并更新地图；close 不负责持久提交。

Connections 示例：open 读取连接服务现态；连接变化在边界刷新 State；seal 只导出摘要。close 释放段订阅/本轮引用，不等于关闭 Agent 级服务中的所有可复用连接。连接是否保留由 subagent owner 的资源策略决定，Kernel 不识别 ACP。

领域 Engine 可以跨 Turn 存活，Segment 必须每 Turn 新建；旧段不能被下一个 Turn 复用。共同协议把生命周期和更新方式统一，事实维护仍内聚在插件内部。

### 7.6 压力与追溯

默认 State 收缩 → Heap 逐出 → Stack 折叠 → Map 有限折叠。保护 identity/inputs 必需语义、待处理问题、活 Job、关键 milestone；每段声明最低可用投影。

session 仅自身超水位时有限折叠旧已整理节点；其它段过大不优先牺牲历史。完整图无限增长不能保证永久整图入模：推荐完整持久图 + 稳定 thread 聚合节点和有界详情（Q4）。仍超容量则明确失败，不静默截断问答事实。

容量结合当前模型估计，字符数只是近似，不当硬 token 保证。无回收进展即结束恢复，不无限 RETRY。LLM 声明容量失败，Context handler 回收并重建当前任务消息，已执行 Action 不重放。

core.context.inspect(ref,cursor) 统一追溯；load/evict 仅有 Heap 能力的段；organize 由 Session 提供实现，以 core 名称注册，kernel 不实现图业务。inspect 不取代 workspace.read 或一切资源 API。

## 8. Session：唯一历史体系（Q4）

SessionTurnRecord 保存不可变问答/行动事实；session 段以 Map 呈现会话事实、基于事实的发展关系，以及模型进一步提炼的线索。名字不再暗示仅为过去对话列表。删除平行 SessionSummaryRecord 线性历史；session 是同一 Session 事实体系的语境视图。

三类内容明确区分：

| 内容 | 产生方式 | 修改边界 |
|---|---|---|
| 对话/行动事实 | 无模型记录输入、问答、动作和结果 | 原记录不可变，不因整理改写 |
| 发展关系 | 时间次序、显式 reply-to、资源关联等确定性构建；语义连续性可经模型补充 | 确定性投影可重建；模型补充的边标明推导来源 |
| 推导线索 | 模型提出问题关联、假设、下一步方向、thread/gist | 可修订/撤回，保留来源 refs 和推导性质，不自动升级为已验证事实 |

来源与性质使用最少必要标记，不引入版本链或审计数据库。图压缩、inspect 和后续 Memory Reflection 都保留事实/推导的区别；未验证线索可以帮助继续思考，但不能仅因写入 session 就成为可靠知识。

无模型抽取：初始问题、追加输入、ask/reply、最终回答、outcome、显式 core.reason 摘要、Action 请求/结果、milestone、资源引用/URL。“推理”指可保存显式 Action 或摘要，不指供应商私有推理原文。

Trace 执行时维护 typed Action 事实，折叠只改变模型渲染，不从压缩文本重新猜调用配对。中断时每个已产生调用有结果或明确 cancelled/not_executed/unknown，不能伪造成功，也不能因一对缺失导致全部问答无法保存。

地图可有 turn/thread/resource/decision 节点及 follows/continues/touches/decides 边；resource 已承载链接时不强制再建重复 link 节点。跨日引用附 owner/day，旧 workspace:path 不得解析成今日同名文件。

finish 先按 turn_id 幂等写 record，再补确定性图。organize 修改 gist/thread/关系并引用原 Turn，不改原话；注释是需持久保存的知识，不宣称都能从原事实无损重建。地图更新失败可补投影且保留注释；record 写失败是必要持久化失败。

新 User Turn 提供上一成功用户 Turn 待整理标记；失败/取消也保留事实，但不称成功。AWAITING_USER 代表仍待后续回复，不自动等同成功回答；是否允许一起整理见 Q4。

User 根 Turn 进入用户 Session，Reflection 不进入。当前 ACP 委派通过本 Turn 的 Action/Job 摘要记录关联；未来内部子 Turn 可由同一 Session owner 保存可追溯子记录并关联 parent_turn_id，不在本次预建子记录管线，也不重复成为根历史条目。

## 9. Home、Memory、Reflection 与 CalendarDay

两个独立 profile 和专属 domain：home_reflection、memory_reflection。共用内核、动作配置、模型链、TaskPrompt/Skill 挂载，不保留维护专用第二套 Loop。

已确认 Reflection = 通用 action domains + 当前 Reflection 专属域。通用推理、检索、Context、Workspace、home 副本操作、execution/subagent/expand 等已配置能力仍可使用；home_reflection/memory_reflection 不互相自动附加。profile 改目标、视图与输出解释，不重写执行器，也不把 Reflection 关进只有几个命令的工作流。

历史 Session/Workspace 用作只读参考，当日 Workspace 仍作为可操作工作台；source_day 与 active_day 分开，不能为读取历史而禁用通用 workspace 写能力。通用工具可用不等于获得绕过 owner 写持久 Memory/actual Home 的业务权限；execution/subagent 的工作目录和服务能力仍遵循对应 owner 边界，不把 shell 作为长期写入捷径。

| 工作类型 | 可写事实 | 动作与完成 |
|---|---|---|
| User Turn | 活动 Memory.md、Workspace、Home overlay | 正常回答或其它终态 |
| Home Reflection | 审核后 actual Home | 通用域 + home_reflection.diff/review |
| Memory Reflection | target daily、entity/concept/fact/note | 通用域 + memory_reflection.write_daily/write |

User 的实际 Action surface 不含专属域，注入的服务也限制写权限，不只靠提示词。子 profile 不继承超出父 profile 的长期写能力。

精简专属动作草图（本轮新增签名建议）：

| 动作 | 参数与语义 |
|---|---|
| memory_reflection.write_daily | target_day + markdown；目标日默认来自 profile，一次写一份 daily |
| memory_reflection.write | kind + cite + markdown；kind 为 entity/concept/fact/note，一次写一个文档 |
| home_reflection.diff | 可选 paths + detail + cursor；无路径列差异，指定路径查看有界详情 |
| home_reflection.review | paths + decision(accept/reject)；处理明确选择的待审项，返回逐项结果 |

Home 副本读取与改写复用常规 home 域，不另加 reflection.rewrite；Memory 的合并/退休状态通过 write 的文档状态与 codec 校验表达，不为每种知识和状态增加动作。write 返回 link 与精简结果，供进一步 inspect；review 批量执行不宣称多文件原子事务。

Memory 典型过程：通用 inspect/search → recall/证据读取 → 写一个文档 → 检查 → 决定下一步。Home 典型过程：diff 目录 → 详情 → 按需常规 home 动作改副本 → 再看 diff → review。模型自主少量多步，不增加固定控制器、阶段 token 或必须凑齐的操作序列；review 只提交当前明确选择的待审项，领域规则由 Home owner 校验。

不为两个域各设 done。建议复用通用 core.answer 的终结意图，由 profile 映射为 ReflectionCompletion(summary)，不发布用户回答、不写 User Session。core.ask 仍可在需要时暂停交流；正常 Reflection 不默认要求人工审批。若统一 core 终结动作在实现时调整名称，也只改同一核心契约，不复制专属完成器。

不引入 Git。Skill top 线索进 Background，domain/action Skill 挂对应 Task，正文局部读取。

Memory 删除 8 步控制器、preview、多文档 CAS/journal、revision/activation_count/session_revision/active_memory_digest。活动 Memory.md 同样使用轻量 owner 操作，不暗留 CAS。保留类型、身份、来源、关系、摘要和必要状态；具体字段由 codec 统一，不在计划增设关系同义字段。

单文档原子替换；catalog/backlinks/embedding 为可重建派生数据。通过 write 更新退休/合并状态时保留迁移说明，redirect 存在、类型合法且不成环；先写目标再改旧项。Reflection 失败不撤销已完成单文档写入，准确报告进度。

Reflection 插件编排触发/去重/完成，Home/Memory 管存储，日切归 agent/day。有 Session 无 daily 可触发补记；已有 daily 仍允许手动重整今天/历史日。失败调度有界，不即时无限重入。不保留 availability.json 平行事实。

CalendarDay 取代 BusinessDay；面向用户说“今天、总结、整理”。根开始锁定 day/世代，跨午夜继续原日；根及子工作完全收尾后归档再开新根。Reflection target/source_day 与运行 active_day 分开，历史 Workspace 只读参考，当日 Workspace 仍可操作。

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

### 11.2 内部子 Turn：后续能力，不作为本次前置

用户已明确：当前子智能体以 ACP 外部 Codex 等 agent 为主，不设计内部子 Turn 额度协调，也不建设全树预算、子额度 UI 或向用户逐子申请机制。保留统一 Job 与可复用 TurnRunner 边界，不为未来消费者预建空的 subagent profile、嵌套调度器或预算桥接。

未来调用 TinySoul 子 agent 时，子 Turn 使用独立配额，由发起调用的 agent 在启动时给定；子 Turn 自身不能无限扩额。额度耗尽作为明确子任务结果交回调用 agent，由其决定后续动作。无需共享根计数，也无需把每个子 Turn 的额度决定直接升级到人。

这不改变当前用户根 Turn 的约定：根 Turn 预算不足仍暂停，由用户中断或补充。也不将 TinySoul Cycle 计数强加给 ACP 外部 agent；外部执行按 adapter 提供的控制能力和 Job 生命周期管理。具体内部调用签名、并发/递归与扩额动作留到真实需求出现，不是本次 S0/S6 门禁。

如果未来以内嵌方式调用，仍使用同一 TurnRunner、独立 Context/Inbox，并经 Job 结果隔离运行转移；如果经 ACP 调用另一个 TinySoul 实例，复用 ACP 适配器，不新增第二套通用协议。

### 11.3 ACP

ACP 客户端归 subagent 插件；TinySoul ACP server 不在本次范围。先锁真实 agent adapter、SDK 和协议版本，再映射初始化/session/prompt/流更新/权限/取消/退出。

旧草图“ACP v2”“prompt 立即返回”“idle 就是完成”“session/close 必存在”未验证，本版删除这些实现假设。本轮未完成目标 adapter 连通验证，S6 先以官方文档和 fake adapter 核验。

已确认先建立 ACP 连接，再委派 Job，连接现态进入 Working。Connection 是可通信端点，协议 session 是适配器维护的对话上下文，Job 是一次有终点的委派。Job 完成不等于断连，后续委派也不复活旧 Job。

动作草图：

- subagent.connect(agent, cwd?) → connection_id：启动/握手，准备可用端点，限时返回；未准备完成不宣称 ready。
- subagent.delegate(connection_id, brief, references) → job_id：创建一次 acp_agent 委派。
- subagent.disconnect(connection_id)：关闭空闲连接；有活 Job 返回 busy，先经 core.job.stop 收敛。
- send/respond/collect 仍针对 job_id；ACP 不再保留绕过显式连接的第二套 start 入口。

这些是 TinySoul 动作，不声称 ACP 有同名协议方法。逻辑 session 默认同时一个 prompt Job，忙时返回 busy；并行任务使用独立 session/连接，按实际 adapter 能力落实。同连接后续 Job 可沿用 session 上下文，但具有新 job_id。活 Job 追加只使用 adapter 支持的机制，无能力则局部失败，不强发并行 prompt。

subagent 插件在装配时注册 connections State provider，每 Turn 打开段；connect/disconnect/故障更新 Engine 事实并发布连接变化，段在边界刷新。不是每次 connect 都重新注册 Segment。呈现 connection_id、agent、ready/busy/unavailable、工作目录引用、active_job_id；任务输出/权限详情归 jobs/Trace，不重复保存。kernel 只知 State 协议，不认识 ACP。

Q8 已获条件授权：能简单复用就跨 Turn 保留，复杂则 Turn 收尾关闭，不再要求用户预先选择两套机制。具体采用 subagent Engine 内的轻量连接表，不新增通用连接池平台。

- 先收敛当前 Turn 的全部 Job、权限请求和协议任务，再判断连接能否成为空闲资源；活 Job 永不跨 Turn。
- 在同一 Agent 世代与工作日内，配置/目标/cwd 和能力策略仍匹配，且 adapter 支持清晰结束当前 session/请求时，可以保留空闲传输连接。
- 新根 Turn 默认使用新的协议 session，连接复用不暗中继承上轮对话语境；同 Turn 内多个 Job 仍可延续本 Turn session。若 adapter 无法低成本分离 session 与连接，则 Turn 结束直接断连。
- 日切归档前、reload/restart/shutdown 或显式 disconnect 时关闭相关空闲连接；不保留旧工作区 session，不做跨世代迁移、旧 cwd 重绑定、自动恢复或委派重放。
- 空闲连接不阻止 Turn 完成，不延长 Turn/日 lease；新 Turn 的 connections 段展示与当前 profile 匹配的可用端点。不同 profile 的能力/工作目录不匹配则不用旧连接，按需新建。
- 连接数使用有限配置；达到上限返回已有可用端点或明确资源满，不额外引入复杂驱逐策略。S6 若不能通过简洁的 adapter 契约和代表测试证明可复用，关闭连接就是已授权回退。

这保留资源与工作的区别：Agent 可以持有空闲 I/O 服务，Job 仍严格由 Turn 拥有。回退只改变资源释放时机，不新增第二套 Job 语义。

连接断开时 adapter 将活 Job 收束为失败/结果未知并投 Inbox，再更新连接现态；空闲断开仅改连接状态。不自动重连后重发可能有副作用的委派。

权限问题以 request_id 进入 Job 待答，父经 subagent.respond 回应。历史“读 auto_allow、写 ask_model”须映射真实选项；任意 shell 不能凭模糊描述可靠分类，未知请求待答/拒绝。父 INPUT/BUDGET 暂停时不启动隐藏模型代答，可由明确用户控制入口处理。

取消 Job 先收敛未决反向请求与当前协议任务；正常取消后连接可以回到 ready，供新的 Job 使用。不响应而必须终止受控进程时，同时把连接标为不可用，不能留下虚假 ready 端点。Turn 收尾在 Job 收敛后按 Q8 保留符合条件的空闲连接，其余关闭。最终结果信号按选定协议确定，不从流文本猜测终态。

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

Action runner 仅做一次统一分类：已知业务问题由 executor 返回 ActionResult；未知异常/无效结果由 runner 转模块失败；Runtime 与取消原样传播。不增加每个 executor 的恢复器或庞大异常树。宽泛捕获限有说明的动态边界、观察、清理；未知异常不能全部变 executor_raised 普通反馈。BaseException 必要转交时保留取消/退出。payload 保留 module/kind/error_type/必要身份与有界说明，不直传 str(exc)、配置原值、完整资源。

### 12.2 Gateway

Endpoint v2 经 SDK 提供 agent 状态/restart/reload、turn submit/status/inputs/reply/cancel/budget、Job 查询/停止/回应、Reflection、配置候选、Workspace、replay/WS。精确路由/schema/错误码在 S5 固定，避免本计划维护另一套易漂移协议表。

WS 断开不取消 Turn；问题可由状态查询恢复，Observation gap 不等于业务丢失。配置保存成功不等于激活成功。gateway/project 复用 init/reset/lease；删 app 时同步 pyproject console script/package data。后端仅更新前端对接文档，不擅改 visualization。

### 12.3 可行性

既有 TurnRunner/ActionEngine/Context 批次/Session 图/overlay/day lease 是可复用基础，主要工作不是改函数 async，而是生命周期、事实接口与失败归属。最高风险为暂停位置、背压、线程取消、收尾事实、午夜资源和外部终态，必须用完整协作切片验证。

### 12.4 本轮架构复审：统一入口、职责与实施闭环

结论：方案方向合理，具备可复用实现基础；经过下列收敛后，没有发现必须推翻分层、段协议或 Job 语义的架构障碍。可行性是静态代码/依赖审阅判断，仍需实际迁移和测试验证。

| 检查项 | 易产生的重复/冲突 | 收敛设计 |
|---|---|---|
| Plugin/Engine/Segment | 插件拥有一份事实、Context 再拥有一份领域状态 | Engine 唯一领域 owner；Segment 只维护本轮选择、加载与投影 |
| Slot/Shape/Capability | enum 标签无消费者，或万能基类强迫空方法 | shape 有共同访问/回收语义；协议按能力组合；段元数据只声明一次，由 Registry 保存并校验 |
| SDK/事件/Signal | 同一命令经多条路径修改同一状态 | SDK 统一接受入口；owner 方法提交事实；Signal 同步视图；Observation 不回写 |
| 普通 wait/预算 SUSPEND | 两个暂停控制器、两个收件箱或两套恢复位置 | 唯一 Turn 等待状态与处理流程；进入来源不同，收件箱/取消/恢复共用 |
| Runtime bridge | bridge 移名后仍从底层 import kernel | bridge 随 owner；SUSPEND 只表达合法目标，Loop 持有等待语义 |
| Reflection/普通 Turn | 专属完成器和固定步骤重新形成第二套维护内核 | common domains + 专属写域；同一完成意图，profile 解释输出 |
| Session/Trace | 当前 Turn 一边写 trace 一边复制进会话 Map | trace 保存当前过程；Session 记录已结束事实，整理只改有来源语义层 |
| ACP Connection/Job | 连接存活被误判任务未完成，或结束 Job 被复活 | Connection 为服务资源；Job 为一次工作；保留空闲连接不保留活任务 |
| 阶段计划 | S2 删除旧包，S3 才补依赖 | S2 同步全部消费者接入；S3 深化领域语义 |

进一步明确以下统一规则：

1. **等待只有一个事实 owner。** Loop 的 Turn 等待状态持有原因/条件/恢复点；AgentStatus、Working jobs 和前端都从各自 owner 事实投影，不各建等待状态机。Runtime Trap 只把预算异常转换为受限 SUSPEND，普通等待直接进入同一处理入口。若预算与事件条件同时存在，由该入口共同判断，不嵌套两个阻塞循环。
2. **公共贡献元数据只声明一次。** 段 id/slot/shape/profile/capability 由注册对象确定，provider 负责创建实例；不允许 descriptor 和 provider 各维护一套可分歧声明。通用框架负责路由和校验，插件负责语义，不以 service locator 回避依赖声明。
3. **完成语义只定义一次。** core 终结动作产生 typed 完成意图；User profile 映射为回答，Reflection profile 映射为总结结果。提示与 schema 在装配时匹配 profile，不能只修改输出接收端却仍告诉 Reflection 模型“正在回答用户”。移除现有按 maintenance.complete 名称单独解析的完成管线，不再复制两个专属 done。
4. **Context 安装是视图一致性，不是业务事务。** 全段 prepare/install 使一次 MessageStack 使用同一批已安装视图，但不承诺多个 owner 在同一物理时刻原子取快照。运行中外部变更留到下一批刷新；来源事实由 owner 解释，不恢复跨文件 CAS。
5. **完成记录与清理诊断分开。** Session 持久保存执行事实/完成意图，必要提交失败阻止成功发布；记录提交后的连接 close 失败属于清理诊断，不重写已提交对话事实，也不触发第二次 Session 提交。TurnHandle 区分执行结果、提交失败和清理错误，不用一个成功布尔值遮蔽差别。

保留有限抽象，避免为长期扩展增加没有消费者的机制：本次不建内部子预算、通用连接池平台、跨 Turn Job 接管、Inbox WAL/崩溃续跑、线程隔离恢复、通用持久事务或动态发现插件系统。实现细节应服务现有 owner 与用户已确认能力。

## 13. 执行计划与验收

子计划进度：[R1 底层依赖与失败协议](done/20260915-done-Agent重构第一轮子计划-底层依赖与失败协议.md) 已完成；[R2 异步内核与 SDK 运行闭环](<20260915 Agent重构第二轮子计划-异步内核与SDK运行闭环.md>) 为 `in_progress`，维护者已确认纳入 S2/S3 必要契约项并授权实施。

所有实施阶段未完成。历史 S0 定稿不代表本轮复审关闭。子计划只有实现/文档/必要验证全部通过才 done 并归档；docs/design 只写已落地部分。

| 阶段 | 范围 | 必需证据 |
|---|---|---|
| S0 | 已记录架构/SUSPEND/Inbox 确认；同步 AGENTS，细化动作组合与连接契约 | 无冲突目标、待决有状态 |
| S1 | R1 已完成：bridge 归 owner、失败协议、LLM 容量恢复、import/重放检查；async LLM、事件/取消原语仍待实施 | R1：Fast/Full/typecheck 与依赖审计通过；剩余项沿原验收继续 |
| S2 | 新内核/SDK/CLI/段/Job/等待；同步迁移所有旧内核消费者至新公共入口、插件接入与打包 | 完整导入图可用，submit→wait→resume→finish；既有 owner 可通过新架构运行 |
| S3 | 在 S2 可运行架构上深化 Session Map、Workspace 去 CAS、精简 Reflection、execution 合并等领域语义 | 各 owner 正反路径、完整日切；无旧业务契约残余 |
| S4 | fswatch/scheduler、ask/reply、容量、reload/restart、完整监督 | 暂停收事件、午夜、短操作取消与进程回收 |
| S5 | Gateway v2、项目命令、HTTP/WS/replay、协议文档 | SDK 映射、重连、wheel/init |
| S6 | 锁 ACP/MCP adapter/协议/SDK，connect/delegate、连接段；内部子调用留后续 | 建连→多次委派→收尾，fake 故障矩阵，真实 smoke 单独声明 |
| S7 | 全仓文档/AGENTS/测试/打包一致，删旧入口/死抽象 | Full/typecheck/import 图/完整 E2E |

S1–S2 为相邻基础迁移单元，不宣称中间提交可部署。S2 工作量必须如实包含所有现有消费者的接口迁移：当前 maintenance/builder.py、session/engine.py、workspace/projection.py 和能力 actions 等都依赖旧 loop/context/action，不能删除旧内核后留到 S3 修 imports。采用一套新运行路径、注册真实 owner 段与动作，保留可复用领域算法；不增加兼容 alias、旧管线转发器或临时伪插件。

S3 是领域语义变更，不负责补齐 S2 留下的损坏依赖。S2 子计划按真实依赖拆成可审阅提交，但阶段完成必须具备完整可运行路径。现部署继续旧 checkout，不 reset 用户数据。

核心验收：

1. 全局 Workspace 事件送订阅的活动 Turn，过期定向事件不激活其它 Turn；不为未来内部子并发预建调度。
2. wait 前/登记期间/超时同时完成 Job，不丢唤醒、不重复消费。
3. 高频进度不阻塞 cancel/reply；容量不足接受前明确拒绝，已接受输入保留。
4. 等待不耗 Cycle，事件不绕预算，重复 grant 不重复加额。
5. 后段 prepare 失败不部分安装；重试不做 Action；install 缺陷不虚假回滚。
6. 部分 open/finish/close 失败清理，主失败保留，Session 幂等、Map 可补。
7. ask/reply/追加/reason/answer 可追溯，Trace 折叠不破坏事实配对。
8. User profile 无专属持久写入口，Reflection 准确保留单文档已提交事实；外部工具权限不冒充领域完成提交。
9. 跨午夜同 Turn 保持旧日，收尾前不归档，旧资源不指向今日同名文件。
10. 短 owner 操作取消不遗留写线程，长执行复用进程回收，async 取消不伪称撤销远端副作用。
11. 当前 Turn 取消回收所属 ACP/进程 Job，外部委派失败以 Job 结果反馈，并发输出目录策略明确。
12. ACP final/权限/取消/断流；MCP schema/分页/错误/未知写结果有明确映射。
13. runtime 不 import 上层，kernel 不识别领域内容，每个 SPI 有真实消费者。
14. SDK 结果与 Observation 分离，重连能查询待答问题及终态。
15. Reflection 通用域与各自专属域组合；inspect→write、diff→改副本→review 跨 Cycle 自主执行，共用完成意图。
16. connect 后 Working 可见；同连接两次委派 Job 身份不同；空闲连接不阻止回答；Job 先收尾，再按 Q8 保留/关闭连接。新根的 ACP session 不隐式继承旧上下文，日切前旧连接已关闭。
17. 插件仅注册描述和 handler 即能提供段；新段无需修改 composer 的 owner 分支。slot/order 决定顺序，shape/能力一致性可验证，关闭 Segment 不误关跨 Turn Engine 服务。

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

### 14.2 确认与剩余细化

用户本轮认可上一轮分析和架构方向，特别点名受限 SUSPEND、Inbox 保障边界；不重复询问这些选择。未明确覆盖的机械默认值与新增连接寿命分别记录。

| 编号/状态 | 当前结论 | 剩余工作 |
|---|---|---|
| Q1 confirmed | Turn 边界 SUSPEND，预算经 Trap | 合法目标与恢复点验证 |
| Q2 confirmed | 有界内存 Inbox、大输出落盘；存活进程暂停不丢已接受关键事件 | 容量/背压，不做崩溃续跑 |
| Q3 accepted_direction | 沿用无默认 ask 超时、TIMER 显式条件方案 | 配置细化 |
| Q4 accepted_direction | 事实/注释分离、大图有界投影 | 未回答/失败 Turn 可追溯；主动 organize 对象范围在子计划确定 |
| Q5 decided_deferred | 本次不设计内部子额度；未来独立配额由调用 agent 给定 | 移除全树预算与逐子用户授权，不阻塞重构 |
| Q6 confirmed | SDK 生命周期分义、候选/激活分离，bridge 随 owner | 实现及文档同步 |
| Q7 confirmed_direction | ACP 显式 connect→delegate，连接呈现 Working | 本轮动作签名为草图，首个 adapter 待锁 |
| Q8 decided | 用户授权简单可复用则跨 Turn，复杂则收尾关闭 | 同日/同世代保留空闲连接，新根新 session；S6 核验，不构成设计阻塞 |

新增记录：

- D30：受限 SUSPEND、Inbox 存活进程保障边界、架构依赖与 SDK 方向已确认。
- D31：Reflection 保留通用 action domains，附加各自精简专属域，自主少量多步，不设计固定维护流程。
- D32：ACP 建连与委派分开，已连接端点由插件 Working State 段呈现。
- D33：干净性优先架构一致性；异常/取消以统一边界与生命周期轻量落实，不增加平行治理机制。
- D34：ACP 空闲连接允许简单跨 Turn 复用；若需复杂迁移/恢复则直接在 Turn 收尾关闭。具体策略见 Q8。
- D35：Context 段命名采用无点号语义 id；用户进一步明确会话段为 session，承载对话事实、发展关系与模型推导线索。slot/shape/owner 分开声明。
- D36：当前以 ACP 外部子智能体为主，内部子配额本次不设计；未来由调用 agent 设置独立子 Turn 配额，不建共享树预算。

D31/D32 确认用户提出的语义；具体动作签名与统一完成动作映射仍按子计划细化。Q8 的取舍原则本轮已授权，adapter 可行性以协议和测试核验，不为连接寿命再次阻塞讨论。

当前没有必须由用户补充才能继续设计的基础架构决策。session 命名、内部子额度、SUSPEND、Inbox、Reflection 叠加及 ACP 连接原则均已明确。本轮第 12.4 节补充的是按既定方向收敛实现边界，不另设总批准关卡；具体 SDK 版本、容量和签名在对应子计划核验。

### 14.3 本轮修订

- 核验当前 checkout 与远端 HEAD；重新检查关键运行、异常、Context 和 owner 边界。
- 合并旧正文/替换预览，保留确认状态，建议不伪装为已决。
- 删除旧 AGENT-scope Job、冲突 API、未经验证 SDK 假定、悬空引用。
- 补暂停恢复、Inbox 容量/消费/唤醒/落盘、收尾交界、线程泄漏。
- 明确 Session 事实/投影/注释、压力边界、Reflection 部分提交、跨日身份。
- 明确 ACP 会话与 Job 区别、MCP 验证、子任务共享写限制。
- 重排完整切片和验证门禁；未改后端或前端实现。

本轮确认后的追加修订：

- 记录 SUSPEND/Inbox 确认，同步 AGENTS 指向及过渡目标。
- Reflection 通用域叠加，拟用两个 Memory 写动作、两个 Home 审核动作，复用通用读取/改写/完成。
- ACP 显式 connect/delegate 与连接 State 段，连接作用域按 Q8 的轻量复用/关闭策略落实。
- 以短 owner 操作、async I/O、长进程三类承载收敛取消，替代复杂线程隔离恢复方向。

本轮 Context 深化：

- 区分现有固定 ContextSection 与目标 slot/shape/segment/capability 协议，不把目标描述为已经实现。
- Context 段统一无点号语义命名，补全插槽顺序、四形状复用与能力声明。
- 细化插件从注册到 open/更新/render/seal/finish/close 的完整接入。
- 记录 ACP 条件复用授权及简洁回退，减少待确认事项。

本轮整体复审：

- history 正式改名 session，明确事实/发展关系/推导线索及其来源性质。
- 关闭内部子预算议题，本次聚焦 ACP；未来独立额度由调用 agent 指定。
- 统一普通等待与预算暂停、元数据声明、完成意图与 Context 视图更新边界。
- 修正 S2/S3 依赖迁移顺序，补充静态代码证据；没有执行代码重构。
