# Agent 设计

## 定位与依赖

`tinysoul.agent` 是嵌入式 SDK 与进程装配层，拥有唯一根队列、环境事件路由、运行世代和日协调。它通过显式 Plugin 声明装配真实 owner，通过 TurnProfile 调用同一套异步 Turn/Cycle/Phase 内核，不实现另一套推理或 Action 状态机。

依赖方向为 `infra → runtime/llm → kernel → plugins/environment → agent → gateway`。Environment 只通过注入的输入端口提交请求；CLI、HTTP、终端输出和项目命令位于 gateway。Agent 不导入 gateway，也不自动开启终端或 HTTP 监听。

## 装配、服务与生命周期

AgentBuilder 读取明确传入的配置、构造领域 Engine 与资源作用域；AgentAssembly 保存根调度器、命令门面、配置控制器、当前世代和显式挂载的来源/服务。User、Home Reflection、Memory Reflection 分别解析真实 PluginDeclaration，先校验服务身份、依赖和段路由，再激活段与 Action 贡献。TurnProfile 绑定独立 Context、Action surface、准备/完成管线和类型化服务表。

Agent.create 从项目根装配；Agent.assemble 接受显式装配工厂，供嵌入方注入 provider、时钟或来源。create 不启动来源，start 等待确定性日切与服务激活后才返回。SDK 的 submit、append、reply、cancel、grant 与 publish 经 AgentCommands 进入唯一调度器或指定 Inbox。状态查询为内存快照，TurnHandle 是结果权威；等待者取消不取消已受理 work。

Agent.services 按 Facade 类型提供当前 User profile 服务，查找不触发 I/O；返回的 owner 门面属于当前世代，嵌入方应在 reload 后重新取得服务，并协调自身调用与生命周期。业务 SDK 请求和 Endpoint 访问由框架持有相应世代/day lease。领域短文件操作仍归 owner，同步门面通过 JoinedOperations 接入异步执行边界；模型和网络使用原生 async。

只运行一个根 Turn。等待用户、Job、定时器或预算期间仍占根位置，新 User/Reflection 请求排队。队列和已完成句柄保留有界；重复 request identity 必须内容相同。queued 阶段取消不伪造 Session Turn，开始后的取消先收尾再完成句柄。

shutdown 停止受理、取消根 work，等待 Action/Job、必要记录、段和来源回收，最后关闭世代。restart 重新装配，旧句柄保留旧结果。自建 LLM/embedding 客户端归世代关闭，注入对象保持借用。部分激活失败逆序关闭已创建资源；重复取消不抛弃清理任务，有限 cleanup diagnostics 不覆盖主失败。

## 输入、事件与容量

Environment 的 InputEvent、InputSource、AgentRequestSource 只描述输入与来源生命周期。AgentIngress 解释可信终端命令和普通用户文本；InputCommandParser 纯解析，InputDispatcher 调用 AgentCommands。终端普通文本在空闲时提交 UserTurnRequest，活跃时追加到该 TurnInbox。Reflection 始终排入根队列。

`/reply <question_id> <text>` 与 `/grant <request_id> <count>` 明确关联当前等待；普通追加不代替问题回复。取消、退出不排在普通输入后；退出停止后续根 work，取消当前 Turn 则保留后续请求。

Runtime EventBus 只校验 envelope、保存有界幂等回执并投递。Agent EventRouter 将定向事件送到指定身份，过期目标不会回退给其他 Turn；无目标事件经订阅进入当前活动 Turn。事件不隐式创建根 work，外部事件不能伪造 reply、预算决定或 Job 终态。

TurnInbox 从受理到收尾持续存在，由 Kernel 独占待消费正文。固定 capture → Context prepare/install → ack；新到记录留到后批，等待只观察就绪。SDK 可通过 InboxLimits 设置普通记录数、字节数、单条大小、回执保留与 Job 终态预留数/字节。默认普通队列为 64 条/256000 字节、单条 64000 字节，另预留一个同大小问题回复和 16 个 8192 字节 Job 终态槽；JobRegistry 在启动 backend 前核对其终态预算，容量不足先拒绝。取消和预算决定独立于进度容量，大输出留在 owner 资源。默认值是本地有界策略，不是生产吞吐承诺。

## CalendarDay 与 Reflection 触发

AgentDayCoordinator 使用注入时钟，协调 Memory catalog 与 Archive owner。短日切操作在 JoinedOperations 内完成，取消等待已开始操作结束才释放世代活动边界。日切不调用 LLM，也不依赖 Reflection 成功。

每项根 work 前完成日切与 availability 刷新，再持 active-day lease 执行；跨午夜等待仍属于开始日。Archive 的可恢复 journal、Session/Memory/Workspace 的初始化与归档由各自 owner 实施。Reflection 只取得只读 ArchiveReader，不拥有推进日期的权限。

daily 触发在 Agent 边界拆为 Home 与触发日前一日 Memory 两个独立请求，整批容量受理；执行前的日切使新关闭日资料可见。scheduled 请求按日期/profile 稳定身份去重，已有 daily 跳过自动 Memory；明确日期的手动请求允许复查。更早 backlog 由 availability 保留并由明确日期请求处理。定时来源遇到满载保留请求并重试；启动晚于当日计划时刻不追补模型任务。

## 配置候选与世代激活

SDK patch_config 与 HTTP PATCH 统一只校验并原子保存候选，返回 saved/pending_reload。当前运行世代继续服务；reload 在 idle 边界读取候选、校验并构造新世代后切换 RuntimeHandle。活动/等待 Turn、日切或既有激活会拒绝 reload。

候选失败关闭候选并保留活动世代；已经保存的磁盘候选仍明确报告。切换成功后的退休只回收旧资源，失败返回诊断，不伪回滚可见新世代。EndpointHost、来源、实例锁与事件缓冲独立于业务世代，保持稳定。

## Observation 与 Gateway

ObservationRouter 按 normal/verbose/model 扇出到显式 sink，并提供有界 SDK 订阅。慢订阅得到 gap，不阻塞业务；单一 sink 或订阅编码失败关闭对应观察路径，记录有限错误类型。Observation 不参与提交、Trap 或控制流。

CLI 在 gateway 显式挂载 Console、Terminal 与 EndpointHost。终端读取支持停止与线程回收；来源等待实际受理回执，不维持平行业务队列。HTTP 与 Agent 共用事件循环，宿主保留信号处理权。start --once 关闭定时来源、交互输入和 HTTP，执行一个 User Turn；只有正式回答返回成功退出码。

normal 输出正式回答与重要运行边界；verbose 增加执行过程；model 展示真实模型输入和归一化输出。Console 有字符上限，Endpoint MODEL replay 面向可信客户端；图片字节和供应商私有推理不作为原始诊断输出。

## 项目资源与发布

gateway 的 ProjectInitializer/ProjectResetter 使用 package-owned 模板。通用模板和唯一默认 Home 位于 assets/project；standard/development 是完整配置快照，只表达初始取值差异，不进入运行时配置来源。

Action catalog 文档随所属 owner 发布：Kernel 提供通用 core，Home/Memory/Workspace/Capabilities 提供自己的 fragments。Agent 的显式 catalog 合成拒绝重复文档，initializer/resetter 物化成项目 configs/action/catalog；运行实例使用项目 catalog。Reflection 专属 fragment 只由相应 profile 装配，不进入 User Action 设置页。

init 只安装到不存在或空目录；reset 是显式开发命令，持项目排他 lease，在同级 staging 生成并只保留普通 .env，再以可回滚替换安装。reset 不由 SDK 启动或重构自动执行。start 在创建业务 Engine 前持有 ProjectInstanceLease；HTTP 就绪后发布本机连接描述，退出时清理。

发布验证覆盖 wheel package data、隔离安装和 init，以及本地 fake-provider CLI 的真实配置/provider/Phase/Action 链。真实供应商测试通过独立 external 开关运行。
