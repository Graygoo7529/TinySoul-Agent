# Loop 设计

## 边界与装配

`kernel/loop` 只拥有 Turn/Cycle/Phase 的异步执行、预算、等待与运行转移消费。Agent 管根队列、日期和世代；plugins 管领域事实及 profile 贡献。内核不 import Home、Memory、Session、Workspace 或 Reflection，也不访问它们的私有存储。

冻结的 TurnProfile 绑定 Context、Action、完成策略、准备/完成管线与类型化服务表。User 装配位于 agent/user，Reflection 装配位于 plugins/reflection；两者调用 build_turn_kernel，共用唯一 TurnRunner/CycleRunner/Phase 实现。

局部 phases 包保留共享 PhaseFailure/协议与三个 Phase 实现；lifecycle 聚合准备/完成，interaction 聚合 Inbox 与取消。TurnRunner 仍是唯一生命周期协调者，拆包不引入并行内核。

## Turn 生命周期

Agent 在进入 Turn 前捕获 CalendarDay 并持有 day/generation lease。Turn 内不重读系统日期，跨午夜等待仍属于原执行日。Context 每轮打开独立段视图，准备操作通过 owner 门面读取，所有候选成功后安装。

执行链统一 async：provider、LLMTask、Phase、内部 LLM Action、Cycle 与 Turn。网络等待可直接取消；短 owner 操作开始后等待完成并交付真实结果，再传播取消；脚本和 Shell 由受控进程执行。取消不变成 Action timeout，执行中断也不伪造工具结果。

收尾顺序为关闭普通受理、Action/Job 收敛、消费已接受终态、seal、必要 finish、Session recorder、全部 close，随后释放外层 lease 并完成句柄。prepare/open 部分失败同样回收已取得资源。重复取消等待既有收尾任务，不能让未结束的 owner 写入遗留到下一 Turn。

TurnCompletion 保存执行状态、typed Trace、输入和段快照。必要 finish 失败阻止正式回答，recorder 仍尝试保存已有失败事实；Session 自身失败明确报告。close diagnostics 不改写已提交结果。TurnExecutionCancelled 携带封存 TurnOutcome，并保持 asyncio 取消语义。Observation 输出晚于必要记录与关闭。

## Cycle 与 Phase

每个 Cycle 顺序执行：

1. Phase1 构造 MessageStack，只暴露 Control Tools 和域级语义，消费语境控制并选择行动域。
2. Phase2 只暴露所选域的 Action Tools，挂载相应领域 Skill，生成并归一化 ActionCall。
3. Phase3 执行 ActionBatch，把 typed 执行事实交给 Trace，并解释完成、问题和等待意图。

Phase1/Phase2 的可修正协议失败是 PhaseFailure，当前 Cycle 在失败 Phase 结束，有限反馈交给下一完整 Cycle；不在 Phase 内重复同一协议调用，不以空 ActionBatch 进入 Phase3。供应商/模型链重试归 LLM，模块契约失败经 owner bridge 进入 Runtime。

Phase task profile 由 loop.cycle 配置，三 profile 共用模型链选择；TaskPrompt 只叠加当前引导和 Skill。背景、Trace、Working 均由 Context 按段描述组合，Phase 不解释领域内容。

## 输入、问题与预算

TurnInbox 从请求受理到收尾持续接收。固定批次经 Context prepare/install 成功后 ack；准备期间到达的记录留在后批。inputs 保存正文，Trace 只引用输入身份与顺序。等待只观察就绪，不能抢走消费者记录。

core.ask、core.wait、core.job.wait 都先以 ActionResult 收敛，再由 Loop 在 Cycle 边界等待。ask、wait、answer 等互斥意图在批次执行前检查，冲突形成 PhaseFailure，不先执行部分副作用。ask 无默认超时，显式超时以 awaiting_user 结束；普通追加作为新指示恢复并记录原问题未答，过期问题拒绝迟到回复。

带 Inbox 的 Turn 在下一 Cycle 开始前检查预算；不足时经 Loop-owned reason 和 Trap SUSPEND 当前 Turn frame。next_cycle_index 保留，事件就绪不能越过预算，grant 绑定请求身份且幂等。模型不见剩余 Cycle，不得自动补额。不带 Inbox 的单次内核调用以有限预算终态收敛。

INPUT、EVENT、TIMER 和 BUDGET 共用 TurnInbox.wait_for_cycle。事件使用类型、显式身份与当前 Cycle 已消费 cursor 过滤，Job 使用权威终态；定时器使用单次 monotonic deadline。普通条件满足但预算不足时保留有限就绪凭据，先 grant 则继续等条件；计时不重启，事件与输入不自动补额。等待只观察，不删除 Inbox 正文；Job 在登记前或登记期间结束均能恢复。问题超时直接结束 Turn，不需要为不存在的下一 Cycle 补预算。恢复原因进入现有 Trace，不补造工具结果。

正常完成前复查 Inbox 与活 Job。已接受输入使候选失效并继续推理；活 Job 由模型等待或停止。取消独立于队列容量，停止普通受理后仍接收内部清理终态，消费并 seal 后才注销目标。

## Job 与完成策略

Kernel JobRegistry 管身份、配额、监督、终态预留和 Turn 收尾；具体 backend 管进程及输出资源。Job 可跨 Cycle，不跨所属 Turn。通用 core.job.status/stop/wait 查询、停止或构造等待条件，进程 manager 不管理下一 Cycle 节拍。后台 monitor 在 Turn 等待期间仍更新 owner 状态和终态，段视图在正常边界刷新，不由 monitor 并发修改 Context。

User 的 core.answer 经 profile 映射为正式用户输出，由 Session 保存 schema v9 完成事实。Home/Memory Reflection 复用同一完成检测和内核，core.answer 表示维护总结，不写 User Session；各自专属 Action 权限由装配决定，内核不按 profile 字符串分支解释业务。

Job 终态单调、只交付一次。停止确认与附属清理分开：日志/临时文件清理失败保留诊断，不改写已停止的执行结果；明确活进程无法停止或监督依赖失败经 Jobs bridge 转换，Turn 的 activity cleanup 不吞掉必要运行转移。stop 对仍保留的终态幂等，成功 release 后查询拒绝；执行关闭失败不提前删除条目。日志与资源由 backend/Workspace 拥有，完整正文不进入 JobSnapshot。

## Trap 与失败

可反馈 Action/Phase 失败留在本轮语境。模块失败在自身 bridge 映射为有限 Runtime 原因；Trap 只决定合法 frame 的重试、结束或受限 SUSPEND。已解析的 RuntimeTransferInterrupt 原样展开，不重复捕获。

Context/LLM 容量恢复使用同一压力协议，段按能力和形状回收；有进展才重试，无进展结束恢复。Home owner 恢复策略由外围注册，handler 发 Signal，内核在重试前消费；Workspace 不参与压力删除或 Trash 恢复，不直接安装 Context，也不因投影失败撤销已完成 owner 提交。

Agent queue、环境触发、外部协议、Archive journal 与领域存储均留在 Turn 内核之外。
