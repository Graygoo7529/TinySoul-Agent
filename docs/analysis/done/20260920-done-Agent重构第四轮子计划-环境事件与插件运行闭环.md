# Agent 重构第四轮子计划：环境事件与插件运行闭环

状态：`done`（2026-09-20，R4.1–R4.6 实现、文档、门禁与主计划 S4 已逐项核对，证据见 §10）。
日期：2026-09-20。
审查基线：`a20ec5e`，Before 4 已提交，开始本次分析时工作区干净。
主计划：[Agent 架构重构](20260915-done-agent-architecture-refactor-plan.md)。
前置：[Before 4 验收](20260920-done-Agent重构Before4子计划-数据基础与渐进披露.md)。
参考：[整体功能想法](../../chat/00%20doing%20something.md)，其中旧 domain、CAS、Session 整理范围等表述以已确认主计划为准。

## 1. 本轮目标与范围

R4 落实主计划 S4 的环境协作：Agent 在运行或等待期间持续接收环境变化，业务 owner 更新事实，本轮视图在安全边界刷新，下一次模型调用使用刷新后的 Context。插件显式提供来源、订阅适配和必要生命周期贡献，Kernel 不识别 Workspace、Home、Memory 或具体外部系统。

完整主线为：

```text
外部文件变化 → 文件变化线索 → Workspace owner 核对/提交
                                                ↓
正式 Action / SDK 写入 → 同一 Workspace 提交边界 → 领域变化事件
                                                ↓
              EventBus / Router → 匹配的 TurnInbox
                                                ↓
              捕获批次 → 插件适配 → prepare / install → ack
                                                ↓
                       Trace 变化摘要 + Workspace State
                                                ↓
                       后续决策模型使用新的 MessageStack
```

独立的触发路径为“到期事实 → 已声明 Trigger → 类型化根请求 → 现有根队列”，以每日 Reflection 为真实消费者。订阅更新当前工作，Trigger 安排新工作，两者不互相替代。

本轮纳入：

- 当前 Workspace 的真实文件监听、owner 变化发布，以及 User/Home Reflection/Memory Reflection 中的当前工作台刷新。
- 事件 topic、来源与作用域，插件订阅、范围等待、去重及可合并通知。
- 来源与 owner 适配的世代/日期生命周期；必要 preparation/completion 贡献归回插件声明，并仍进入唯一既有管线。
- 每日 Reflection 的来源/触发职责解耦，复用原调度规则、队列和授权语义。
- fake 来源、真实临时文件系统及 SDK 的完整验收。

范围外：Home/Memory 的外部文件热监听（见 Q1）、Session Organize/注释持久层、Gateway v2、ACP/MCP、内部子 Turn 并发、新 DDS 中间件、动态插件发现、OS 沙箱与持久事件日志。SDK 与协议文档同步必要字段，但不扩大为 S5 的接口重建。

## 2. 实施前的代码基线与缺口

| 证据 | 已有能力 | 本轮处理 |
|---|---|---|
| `runtime/events.py` | 有界 EventBus、事件身份、发布回执；envelope 只有 kind/payload/id/target | 增加真实消费者需要的 topic/source 与过滤契约；保持传输层不理解领域 |
| `agent/commands.py`、`dispatch/router.py` | 定向路由与订阅；当前将全部无目标 EVENT/TIMER 送入活动 Turn | 改为声明订阅或等待匹配；按 Turn 身份去重，不依赖 bound method 的对象 id |
| `kernel/loop/interaction/inbox.py` | 有界受理、回复/Job 终态预留、固定 capture/ack、统一等待 | 补可合并状态通知；受理和 capture 复制记录时保留 received_at，当前重建 InboxRecord 会刷新时间 |
| `kernel/loop/turn.py::_consume_inbox` | 输入与其它事件按受理顺序进入 Context；非输入只写 Trace | 增加 owner-neutral 的事件适配，刷新信号与必要 Trace 摘要同批安装 |
| `kernel/registration.py` | 声明服务、依赖、段和动作；按 profile resolve/activate | 增加确有消费者的事件与生命周期贡献，区分世代运行资源和 Turn 视图 |
| `plugins/workspace/engine.py::_change`、`observation.py` | 单一提交边界、typed WorkspaceChange、旁路 Observation | 同一提交事实分别提供业务通知和观察投影；禁止从 Observation 反推业务事件 |
| `plugins/workspace/projection.py` | preparation 执行 reconcile；段接收完整 WorkspaceSnapshot | 刷新统一为 owner 声明的失效/刷新意图，prepare 从 owner 读最新 snapshot，避免多条路径携带过时整份状态 |
| Workspace/Execution actions | 正式操作后直接发 workspace snapshot signal；execution 操作真实目录 | 接入同一 owner 通知与段刷新路径，删除重复快照生成；保留执行后必要 reconcile |
| `environment/sources/scheduler.py` | 有线程收尾、满载重试、配置刷新，但来源直接依赖 ReflectionRequest | 拆开定时 I/O 与 Reflection 到期/根请求策略，由真实 Trigger 复用现有 queue |
| `agent/composition/assembly.py`、`lifecycle/generation.py` | 来源/服务资源作用域、世代资源、配置切换、日 lease | 接入一次性的运行资源生命周期，避免每 profile 创建 watcher 和旧日回调污染新根 |
| `agent/user/builder.py` | 在组合根指定 Workspace preparation、Session recorder | 收集插件已有处理器，保留 Session 最后记录及必要 finish 失败语义 |

以上缺口不表示 R1–R3/Before 4 整体失效。事件订阅、fswatch 和 Trigger 是既定待实施范围；接收时间复制是本次检查识别的具体修正项，不新增另一套事实协议。

## 3. 统一抽象与所有权

### 3.1 传输、领域事实、语境更新和观察

- Environment source 负责 I/O 与停止；文件系统通知只是“可能变了”的线索，不证明最终文件状态，也不证明外部操作的因果顺序。
- Workspace owner 负责解析路径、检查扫描结果、更新 manifest 和生成 WorkspaceChange。正式动作、SDK、execution 和外部编辑遵循同一事实边界。
- EnvironmentEvent 负责传递已经可以解释的变化事实；Signal/typed 更新负责请求某个段刷新；Observation 只展示事实。三者可以共享投影帮助，不合并职责。
- Segment 只拥有本轮视图。事件回调不碰 Segment，prepare 可读 owner、不得持久写；install 同步安装已准备状态。
- Session 继续保存完成事实；不持久化 OS 原始通知，也不以文件扫描日志替代 Before 4 的 Trace/Session 时间线。

文件线索先经注入的 owner 适配端口完成 reconcile，再向 EventBus 发布领域事件，不要求所有原始通知先过全局总线。这样也避免 EventBus 串行投递期间，handler 再次等待同一 EventBus 发布而发生重入死锁。来源不得持锁调用任意订阅方。

### 3.2 最小事件协议

沿用 EnvironmentEvent/EventReceipt，并补充由真实路由使用的 topic/source。topic 是 owner 声明的稳定标识，例如 `workspace.changed`、`reflection.due`；不在 runtime 枚举全部领域动作。kind 保留 EVENT/TIMER 的通用分类，不能代替 topic。

事件身份、source、topic、可选 target 与语义 payload 分开。运行期世代/日期绑定由来源注册和 Agent lease 维护，不要求模型填写 generation/revision/digest。模型只接收必要的变化摘要、Link 和来源日。

外部 SDK publish 表达宿主通知，不获得伪造 Job 终态、回复、预算决定或领域提交快照的能力。内置 owner 发布入口绑定声明来源；输入参数在各自动态边界校验，公共层不再逐层重复解码。

接收时间只在首次受理时确定；跨 Inbox 副本和重试不重写。Inbox seq 表达受理顺序；EventBus 回执序号表达发布顺序，不互换成“外部真实发生顺序”。现有 Session v10 协议可继续消费这些事实，未预设再升存储版本。

### 3.3 声明与生命周期

继续扩展现有 PluginDeclaration/ResolvedPlugins；按实际寿命区分两组贡献，不建立第二套动态插件发现系统：

| 贡献寿命 | 内容 | 真实消费者 |
|---|---|---|
| 世代/Agent 运行期 | 显式来源实例、owner 事件适配、Trigger、资源 start/stop | Workspace 文件来源；Reflection 定时触发；Agent 装配与资源作用域 |
| 当前 Turn/profile | 段订阅与 typed 更新适配、preparation、completion | Workspace 当前 State；Session recorder；TurnProfile 与现有管线 |

Workspace 运行贡献由 owner 组合根构造一次，各 profile 只引用同一实例；三种情景的受约束 Service/Action surface 仍各自 resolve。不能按相同字符串 id 随意选取三份 watcher 中的一份：同一运行贡献必须是同一实例，冲突声明在激活前拒绝。

公共贡献协议置于现有 kernel 注册/生命周期协议或 runtime 的无领域事件接口；environment 实现来源，plugins 实现 owner 处理器，agent 负责激活。kernel 不 import environment/agent/plugins；plugins 不 import Agent SDK。Trigger 通过注入的类型化请求端口提交其 owner 请求，不引入万能根请求 JSON 或任意 service-key 查找。

贡献只声明这些真实消费者需要的启动、停止、订阅与处理能力；日切和配置切换仍由 Agent 现有协调器组织，不把每个 owner 都改造成带空回调的通用生命周期框架。

preparation/completion 收集后进入现有 TurnPreparationPipeline/TurnCompletionPipeline。Workspace reconcile 仍在 preparation 的 owner 操作阶段；随后提交刷新意图，段 prepare 读取当前已提交快照。Session recorder 仍最后执行，普通 User profile 才注册；Reflection 不因此开始写 User Session。段 order 不用于排列持久提交依赖。

## 4. Workspace 事件闭环

### 4.1 文件来源与刷新

使用单一 `watchfiles` 后端，由 `environment/sources/fswatch.py` 封装异步监听、批次及停止。官方 API 提供变化批次、合并窗口和停止事件；它内部使用线程等待通知，必须显式停止并等待退出，不能取消 await 后遗弃工作。见 [watchfiles watch/awatch](https://watchfiles.helpmanual.io/api/watch/)。引入依赖只承载文件通知，不接管 owner、任务执行或恢复。

过滤规则来自 Workspace owner：包含实际工作区资源，排除其内部 manifest/Trash/临时原子写路径及既有 ignore_dirs；不直接采用库默认过滤器替代业务规则。库允许注入过滤器，见 [watchfiles filters](https://watchfiles.helpmanual.io/api/filters/)。具体依赖范围、合并窗口与平台停止时间在实现时以 wheel 和实机测试落定，不新建 native/polling 双实现。

Watcher 批次只保留有界路径线索；过量时合并为该绑定根的 dirty 标记，由 owner 做一次完整 reconcile，不任意截掉末尾路径并声称扫描完整。实际扫描仍受现有 owner 容量约束，不能把 incomplete 当作完整 snapshot 发布。

重命名不凭通知猜操作配对；实际状态由扫描确定。经 Workspace.move 操作可保留人工元数据；外部 rename 没有可靠身份时按旧路径消失/新路径出现处理，已有路径的 description/tags 保留，不新增内容 hash/CAS 来猜身份。

### 4.2 正式写入与外部变化的汇合

WorkspaceChange 从现有提交边界产生，同时服务业务通知和 Observation。业务通知独立于观察配置或 sink 成败。同步 owner 的锁内只产生事实/轻量待通知标记，发布与订阅处理在锁外完成；跨线程交接必须有界，不为每行输出创建一个无限排队 task。

已提交写入不能因为通知队列满载被报告成“未执行”。保留有限的待刷新标记直至接受，后续读取以 owner 现态为准。通知摘要描述合并范围，不承诺还原每次 OS 改写。普通模型 Action 的完成结果仍独立保留，不能被状态通知合并掉。

Action、SDK、execution 与 watcher 共用此路径。段接收的是刷新意图，读取同一 owner snapshot；不同时维持“Action 发整份快照”和“事件再发整份快照”两套竞争状态。正式 Action 批次返回前需要保证它产生的通知已受理，现有运行边界负责安装，因此本轮直接写入仍能及时进入下一次决策。

外部写入后，暂停期间可以刷新 owner manifest；Segment 不并发变更。SDK 读服务能看到 owner 现态；活动 Turn 在后续合法边界取得最新投影。Workspace 与 plan 分段，文件变化不直接修改 milestones/todos，不内联文件正文。

### 4.3 自身写入、无变化与无活动 Turn

引擎写入引发的文件通知再次扫描若无 manifest 变化，不再发布新的领域变化，避免模型的写入引出无限自激循环。不能仅凭时间窗口把所有同路径变化当成自身写入并丢掉。

空闲时来源仍能更新 owner，无活动 Turn 就不制造 Trace/Session 或自动提交 UserTurnRequest。下一个 Turn 的 preparation 读取最新事实；来源通知不是等待未来 Turn 消费的长期历史。

## 5. 订阅、批次与等待

### 5.1 路由与范围

定向事件只去目标身份，过期目标返回 closed/stale，不回退活动 Turn。无目标事件只投给声明订阅或当前等待匹配的 Turn；相同 Turn 同时匹配多条件只受理一次，所需多个段更新在本 Turn 的事件适配阶段展开。

`core.wait`/WaitRequest/WaitCondition 增加通用 topic 条件，使模型能等待 `workspace.changed` 等可描述事件；需要限定外部监听等具体来源时可同时使用 source 条件。保留现有 event_id、Job 状态谓词和 after_seq 语义。事件源的可等待 topic/source 通过已有 Action/domain 指导或有消费者的描述投影提供，不让模型猜内部字符串，也不新建常驻“全部事件目录”段。

### 5.2 批次与失败位置

TurnInbox 保留规范事件。消费固定批次时，由声明的适配器将已校验领域事件转成自身更新意图及有界 Trace note，与同批输入一起进入现有 ContextSignalConsumer。所有 prepare 成功才 install，成功后 ack；重试原批次，不重新 drain，也不重做文件操作或模型 Action。

事件适配只做类型转换和视图刷新请求；需要写 manifest 的 reconcile 在 owner 操作阶段完成，不能塞进段 prepare。程序性契约错误或 owner 读取失败沿所属 bridge 进入现有 Module/Turn Trap；全局 Loop 不捕获具体 Workspace 异常。

Before 4 的事实顺序和取回保护保持有效。文件变化摘要进入 Trace 时说明 created/updated/removed 或合并后的 changed 范围；大路径集合给计数、少量 Link 与现态入口，不复制完整文件正文、manifest 或新的并列日志。

### 5.3 合并与等待行为

文件状态通知可以按 owner/资源绑定合并，关键输入、reply、Job 终态不可因此被覆盖。合并只作用于尚未 capture 的记录；已捕获批次固定，期间新变化留在下一批。若跨输入合并会改变事实顺序，保留原有边界或明确先后区间，不能把较新的变更伪装成发生在早先输入之前。

| Turn 当前状态 | 文件变化的效果 |
|---|---|
| 正在运行 | 更新 owner、受理通知；不取消正在进行的模型调用或 Action，在安全边界安装 |
| EVENT 等待且 topic 匹配 | 唤醒同一个 Turn，在下一 Cycle 前安装 |
| 等待用户回答 | 保留通知，不伪造回答；用户回复/追加到达后继续 |
| TIMER 等待 | 默认继续等定时器；显式组合事件条件才提前恢复 |
| BUDGET 暂停 | 更新 owner、合并通知，但不启动模型；补额后按同一边界继续 |
| finalizing/已完成 | 不跨给别的 Turn；已受理必要事实按原收尾协议保存，普通后续变化保留在 owner 现态 |

文件变化不是活 Job 或必须由模型解释完才能结束的用户请求。应区分“投影需要同步”与“必须再决策”的记录，避免持续改文件让回答永远撤回；正常结束仍处理已接受事实，但不能为每个状态通知强制新增一轮 LLM。新增用户输入、明确事件等待及 Job/待答请求沿既有语义处理。

## 6. 世代、日期、来源与 Trigger

### 6.1 来源生命周期

创建/resolve 不启动监听。Agent.start 完成确定性日准备后才启动来源；候选构建或失败 reload 不提前让候选来源向活动 Turn 发布。来源是运行资源，不是 Turn-owned Job，也不靠空 Segment 持有生命周期。

共享原有资源作用域、世代与日边界。来源等待不持日锁；日切或切换前先停止来源并 join 已进入的 owner 操作，随后进入独占边界。实际文件操作继续在 owner 锁内提交，不额外给 watcher 增加一层日读 lease，避免“持独占锁等待一个正等待读锁的 watcher”死锁。SDK 服务仍使用原有世代/日 lease。

- 活动 Turn 跨午夜仍绑定旧 active_day；其 watcher 继续服务旧工作区。Turn/Job 收尾后才切日。
- 日切前停止旧绑定；完成归档和新根初始化后，再绑定新根并建立基线。归档搬移和新根创建不伪装为用户批量删除/创建。
- reload 失败保留旧运行贡献；成功切换后旧绑定失效，来源按新配置重新绑定。旧回调不能对新日同名文件或新世代 owner 执行操作。
- shutdown 先停止外部来源受理，再收敛运行中的 owner 操作、Action/Job 和必要记录，最后关闭来源/段/世代；内部 Job 清理终态通道保留到收尾结束。

每次绑定须衔接监听就绪与 owner 初始扫描：监听建立后完成一次基线 reconcile，其间变化继续合并受理，再进入正常服务。不能先扫描、隔一段未监听的窗口再注册来源。这里只保证从当前事实起步，不补造离线期间的文件历史。

监听是可关闭的外部感知能力。建议由 Workspace 配置的 `watch` 子项承载启用开关和必要合并参数，默认开启；Workspace owner 解释配置后向通用文件来源传入明确设置，environment 不重复读取业务配置。`--once`/嵌入宿主可以通过相同设置关闭后台来源；关闭后仍保留 Action/SDK 的领域事件和原有 Turn preparation 的确定性扫描。

### 6.2 Reflection Trigger 的真实接入

保留 ReflectionSchedule 的到期计算、启动过晚不补跑、满载保留并重试、按日/情景去重等已确认行为。环境定时器只负责等到下一到期点并交付事实；Reflection 插件把到期事实转成 ReflectionRequest，Agent 提供类型化提交端口，经原 `request_reflection`/RootScheduler 受理。

同一来源标识、同一到期日形成稳定请求身份；待重试事件固定其到期日和 Memory target，不能因为队列满而拖到午夜后被重新解释成另一天。Home/Memory 请求仍按现有整批受理规则进入唯一根队列。

Trigger 不依赖当前是否有活动 Turn，也不因事件同时投到订阅而重复生成根工作。仅已声明的 Trigger 可提交请求；文件来源和 Job 终态没有默认 Trigger。手动 Reflection 仍是明确的一次授权命令，无需伪装成环境事件，不产生持续许可。

## 7. 失败语义与简洁性约束

| 情况 | 处理边界 |
|---|---|
| 外部非法事件、未知目标、超容量 | 明确类型化拒绝/回执；不伪造已受理或跨 Turn 转投 |
| 可合并变化达到容量 | 合并有界 dirty 通知/最新现态，固定已捕获批次；不侵占 reply/Job 预留 |
| owner 扫描不完整、存储/契约失败 | owner 归类；不能发布成功快照。需要当前 Turn 读取时经其 bridge 停在合法 frame |
| 原生文件监听失败 | 建议停止该监听、暴露有限 source failure/status；普通执行与已有显式 reconcile 继续，见 Q2 |
| 来源或 handler 程序缺陷、错误注册 | 模块边界失败；运行资源捕获到所属 Agent 边界，不从无 frame 的后台任务随意抛 RuntimeTransfer |
| Observation sink 失败 | 旁路诊断，不改变业务通知或 owner 提交 |
| 取消/关闭中附属清理失败 | 保留主结果及有限 cleanup diagnostic，不伪回滚已提交文件 |

来源状态由运行资源自身维护，SDK/Observation 投影，不落盘另一份健康状态库。原生监听故障与 owner 数据损坏分开，不用“可用性降级”吞掉 owner 失败，也不新增自动恢复编排、无限重试或逐操作审批。

## 8. 顺序执行切片与验收

所有切片均为 `done`。真实调用者、测试和文档已同步迁移；逐项证据见 §10，不保留旧接口兼容路径。

| 切片 | 交付 | 验收 |
|---|---|---|
| R4.1 事件与受理协议 | topic/source、过滤、按 Turn 去重、保留接收时间、可合并通知 | 目标过期不转投；重复多匹配只受理一次；capture/ack 固定；输入/终态不丢；时间不随副本改变 |
| R4.2 插件贡献与边界消费 | 声明订阅、事件适配、运行贡献及既有 preparation/completion 收集 | 两种无领域假设的测试插件；Kernel/Agent 无按 owner 名称特判；Session 仍最后记录且 Reflection 不记录 User Session |
| R4.3 Workspace owner 闭环 | 同一提交发布、刷新意图、Action/SDK/execution 汇合 | 写入/改名/标签/外部创建修改删除均刷新 State；Observation 关闭也成立；失败不发布假快照；无重复整份状态路径 |
| R4.4 真实 fswatch 与运行资源 | 文件来源、过滤/合并、日切与世代绑定、停止/状态 | 真实临时目录；内部文件不自激；外部直接写可发现；切日不污染；reload 失败保留旧绑定，成功不留旧回调 |
| R4.5 等待与 Trigger | topic 等待、Reflection 来源与请求策略分离 | EVENT 恢复同 Turn；INPUT/TIMER/BUDGET 规则不变；到期满载跨午夜仍为原目标；文件/Job 不生成根 Turn |
| R4.6 集成、文档与核对 | SDK 场景、配置/catalog、设计/协议同步、全门禁 | fake LLM 验证 MessageStack 实际含新状态；关闭/restart/午夜真实进程回归；逐项核对主计划 S4 |

代表性端到端场景：

1. User Turn 写入工作台并等待 `workspace.changed`；外部编辑器改文件，owner 更新 manifest，当前 Turn 收到变化并在下一 Phase1 看到新摘要，文件正文仍通过 Action 读取。
2. 同一场景改为预算暂停：期间多次修改、回复与取消仍可受理；没有未经授权的新模型调用，补额后按原 Turn 继续。
3. SDK 在活动 Turn 期间写/标注资源，走同一 owner 变化入口；无需等下一 Turn 才更新当前 State，也不要求前端再发一个“刷新”命令。
4. Reflection 等待期间当日 Workspace 变化可更新；历史 Session/Workspace 来源仍固定目标日，只读归档段不订阅今日变化。
5. 连续文件写入期间 Agent 可以正常结束回答；已完成 Action、已接受输入与必要事实保留。下一个 Turn 从现态开始，不重放上一个 Turn 的普通通知。
6. 跨午夜 Job 仍在旧日工作；Job/Turn 结束后停止旧来源、日切并绑定新根。旧 event_id/source binding 不能作用于新日同名文件。

测试按协议 owner 覆盖一次，跨层仅验证代表路径。fake watcher 使用可控事件而非真实 sleep 猜时序；真实文件通知做有限临时目录验收，不把具体 OS 通知次数/顺序当业务契约。现有 Job 后代进程、ask/reply、Session 完成失败及 Before 4 披露保护必须继续通过。

实施门禁：聚焦 → Fast → `scripts/test.ps1 -Suite Full` → `scripts/typecheck.ps1`；Windows/Linux 目标类型检查及实机验证分别记录。新依赖纳入 wheel 隔离安装；不需要真实 LLM/network/ACP/MCP 来证明本轮闭环。

受影响设计文档为 agent/context/runtime/loop/workspace/reflection/infra；根据新增环境职责考虑独立 `docs/design/environment.md`，仅在代码落地时写当前事实。Action catalog 仍在 assets/common；配置走既有 ConfigDocumentSet/reload，不另造配置目录或热加载旁路。必要 SDK/Observation 变化同步 endpoint 文档，前端代码不在本轮范围。

## 9. 已确认的产品语义

### Q1：外部文件监听的范围

建议 R4 只监听当前 Workspace，覆盖三种情景的当前工作台；Home actual/overlay、持久 Memory、活动 Memory.md、Session records、Archive 和配置文件不启用外部热监听。它们的正式 Action/SDK 仍按各 owner 当前协议工作；后续需要外部编辑时复用同一来源/适配机制，再明确 overlay 冲突、活动/历史视图和缓存失效语义。此划分不把通用事件协议写成 Workspace 专属，也不把协议验证推给未来。

### Q2：文件监听不可用时的行为

建议监听配置错误/已启用但依赖缺失在装配入口明确失败；运行中原生监听故障则关闭该来源、通过 SDK 状态和 Observation 明确报告，允许正常对话及既有确定性 reconcile 继续。重新激活通过明确 reload/restart，不增加后台自动修复循环。

来源不可用是类型化运行事实，由相同订阅/等待路径消费。正在等待该来源的 Turn 得到有界反馈，明确这次等待未因文件变化满足，再由后续决策选择其它动作；不伪造 `workspace.changed`、Action 结果或 Runtime 全局失败。仅按 topic 等待时，外部监听失效也应提示该感知能力已中断，但不能声称 Action/SDK 的同 topic 发布入口一并失效。此反馈不唤醒 INPUT/TIMER，不绕过 BUDGET；已关闭来源的新等待在登记时得到相同不可用语义，避免永久挂起。关闭监听不回滚已写文件。

2026-09-20 用户确认以上两点，并要求主要关注正常路径，避免因极端故障引入复杂架构或编码逻辑。实现只保留明确停止、有限诊断和等待反馈，不建设自动修复状态机。单根 Turn、普通文件变化不新建根请求、事件不绕预算、日切后旧对象失效、Reflection 一次授权语义、受信宿主执行以及 Organize 尾期实施均沿用已确认主计划。

## 10. 实施与验收记录

### 10.1 切片核对

| 切片 | 状态 | 实现与验证位置 |
|---|---|---|
| R4.1 | `done` | `runtime/events.py` 的 topic/source/EventFilter，`agent/dispatch/router.py` 按目标身份去重，`kernel/loop/interaction/inbox.py` 保留 received_at、固定 capture/ack、按声明状态来源合并；router/Inbox 测试覆盖定向、过滤、容量与固定批次 |
| R4.2 | `done` | `kernel/registration.py` 收集 events/sources/preparation/completion/recorder，`TurnProfile` 传入既有 TurnRunner；Workspace 与 Session 声明自身贡献。`tests/kernel/test_registration.py` 用两种无领域假设的插件验证共同管线和 recorder 最后执行 |
| R4.3 | `done` | `plugins/workspace/events.py` 从 owner 提交事实发布；ServiceScope 的 after 回调在既有 joined/lease 边界 flush；Workspace、Web、Resource、Execution 和 Endpoint 删除直接同步快照路径。`tests/plugins/workspace/test_events.py` 验证正式写入、说明、外部修改/删除、自身回声、关闭监听后正式操作仍可用；既有移动/标签/恢复测试全部通过 |
| R4.4 | `done` | `environment/sources/fswatch.py` 实际监听、过滤及 join；`agent/lifecycle/sources.py` 统一世代来源，day/reload/shutdown 先停止再切换。真实临时目录验证外部文件感知；SDK 验证失败 reload、来源启动失败后旧绑定恢复、成功关闭监听与旧服务失效 |
| R4.5 | `done` | `core.wait` 支持 topic/source，Inbox 在同一等待判定内处理来源不可用及预算；ReflectionScheduler 持有固定到期日，通过注入端口提交请求，DeadlineTimer 仅处理定时 I/O。测试覆盖跨午夜满载重试、及时停止及既有 INPUT/TIMER/BUDGET、ask/reply 行为 |
| R4.6 | `done` | `tests/agent/test_sdk.py` 的 external/sdk 两条路径均让原 Turn 恢复，并在真实交给 fake LLM 的下一 MessageStack 中看到新 Link、不内联正文；Full 包含 restart、真实进程跨午夜、Reflection、Session、生成及 wheel；设计和 Endpoint 文档已同步 |

### 10.2 保持简洁的实现选择

- 一个 WorkspaceRuntime 同时供三种情景引用；GenerationSources 只按同一实例合并，冲突身份在激活前拒绝。运行来源不借用 Job、空 Segment 或平行监督器。
- Watcher 将通知批次立即收敛为一次 owner 扫描，不额外保存路径队列。owner 待发布状态按两个声明来源有界合并；Inbox 为每个精确 topic/source 保留捕获中与下一批状态槽，独立于输入、reply、Job 终态额度。合并通知表示现态刷新，不承诺枚举全部中间文件操作。
- Segment 只接收刷新意图，在 prepare 读取 owner。普通状态更新不撤销已完成回答；用户输入、Job、显式等待仍遵循现有决策语义。
- 日切通过“停止并 join → 独占切换 → 重新绑定”保证回调边界，未增加 watcher 读锁、世代 token 校验链或自动恢复状态机。
- 原生监听故障报告 source status；owner 扫描失败保留 owner bridge。来源激活失败在 Agent 边界转为有限启动失败，候选关闭后恢复旧世代。成功提交后的附属清理只产生诊断。
- Reflection Trigger 由真实插件策略和类型化提交端口实现，没有新增无消费者的通用 Trigger 注册平台。满载请求保持原 request identity、scheduled_day 和 Memory target。
- 删除仅供旧测试使用的同步式 `run_once` 旁路；CLI 与组合测试经现有请求队列执行，预算不足等待明确决定。`--once` 显式关闭文件监听与每日定时来源。

### 10.3 文档、配置与验证

同步 `docs/design/agent.md`、`context.md`、`runtime.md`、`loop.md`、`workspace.md`、`reflection.md`、`infra.md`，新增 `environment.md`；Endpoint runtime/events/workspace 文档同步来源状态与自动刷新。`AGENTS.md` 当前任务与过渡语义、主计划 §13 同步实际完成范围。

`workspace.watch` 进入 standard/development 配置与配置 catalog，默认开启、合并窗口 200 ms；沿现有候选和 reload 生效。依赖范围为 `watchfiles>=1.1,<2`，本机使用 1.2.0；职责仅为文件通知。Session/Workspace 持久格式未变，没有迁移、reset 或清理部署数据。

2026-09-20 验证：

- 聚焦测试与 Fast 已通过；最终 `scripts/test.ps1 -Suite Full`：**1100 passed、23 deselected**，含 generation/wheel、fake-provider CLI、真实 Windows 文件监听与进程/日切路径。
- `scripts/typecheck.ps1` 通过；额外 `ty check --python-platform linux` 通过。
- `git diff --check` 通过；旧同步快照入口与旧线程 RequestScheduler 已无调用，runtime/kernel 无新增上层领域依赖。
- 未运行 Linux 实机、真实 provider/network、ACP/MCP；类型检查不代替实机验证。Full 中一条 Starlette/httpx 弃用警告来自现有依赖，与本轮结果无关。

### 10.4 与 AGENTS 和主计划的结论

- [x] 事实 owner、来源 I/O、事件传输、段视图与 Observation 各自保持边界；没有第二份 Workspace 状态或模型必须理解的 CAS/schema/reconcile 操作协议。
- [x] User/Reflection 复用同一 Kernel、Inbox、等待与完成管线；Session 只记录 User Turn，历史目标日视图不订阅今日 Workspace。
- [x] 正常提交、等待、停止、日切和重载已闭合，必要失败只在所属边界处理；没有为假设极端情况增加恢复编排。
- [x] 主计划 S4 标记 `done`；S3 Organize 动作/注释层与 S5–S7 保留，未提前宣称完成。
- [x] 本子计划标记 `done` 并归档；原设计基线与 Q1/Q2 确认保留为审阅依据。
