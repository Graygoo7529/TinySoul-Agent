# 20260713 Daily lifecycle semantic audit

## 状态

status: done

审查对象：提交 `5130dac feat(app): add recoverable daily lifecycle and writable home overlay`，以及提交后的 `AGENT.md`、`docs/design/`、配置、实现和测试。

本次审查区分三类事实：代码已经实施的能力、文档表达的目标语义、仍需设计实现的 settlement 能力。不能因为 archive journal 写有 `settlement_status = pending`，就把 settlement 调度或 apply 误判为已经存在。

## 总体设计意图

当前架构的主线是“控制、语境、行动、持久事实分离”：

1. Runtime 只表达运行位置、Trap、运行转移、信号和 Observation；
2. Loop 在 Program/Turn/Cycle/Phase 边界组合模块，并拥有跨模块 business day 与 daily rollover；
3. Context 只保存当前 Turn 的模型可见语境并构造 MessageStack；
4. Session、Workspace、Agent Home 分别拥有当日会话事实、当日任务资源、长期知识及其当日 overlay；
5. Action 统一域选择、参数归一化和批次执行，LLM 只负责 provider-neutral 模型任务；
6. App 只做进程装配和外部 I/O，不读取业务资源；
7. 确定性 rollover 先冻结旧日事实，语义 settlement 后消费不可变归档，两者不共享一个提交动作。

这个方向是清楚的。最近提交补上了此前最危险的状态缺口：旧日 active roots 不会继续被新日复用，Home 修改不会直接污染 original，Home Background 不再错误依赖 Context 内存跨 Turn 保留。

## 当前模块与主要类型

| 模块 | 主要类型 | 作用与边界 |
| --- | --- | --- |
| Infra | `ConfigEnvironment`、配置 source、JSON/Filesystem helper | 加载和校验动态边界，提供原子写、digest、有界读和根路径约束；不解释业务日与链接语义。 |
| Runtime | `RunScope`、`RuntimeException`、`RuntimeTransfer`、`RuntimeTrap`、`RuntimeModuleRunner`、`SignalBus`、`ObservationEvent` | 定位和改变控制流；不执行 archive、Home copy 或 Context patch。 |
| LLM | `MessageStack`、`TaskCall`/`TaskResult`、`ModelRegistry`、`ProviderRegistry`、`LLMTaskRunner` | 供应商无关模型调用、重试切换和输出解释；不执行模型侧工具。 |
| Action | `ActionEngine`、`ActionCall`、`ActionExecution`、`ActionResult`、`ActionBatchRunner` | Phase1 域作用域、Phase2 action 归一化、Phase3 执行与局部结果收敛。 |
| Context | `ContextEngine`、`BackgroundContext`、`WorkingContext`、`TurnTraceHeap`、`MessageStackComposer` | 当前 Turn 语境、动态 Background、信号批量提交、MessageStack 和压力回收服务。 |
| Loop | `ProgramRunner`、`TurnRunner`、`CycleRunner`、Phase units、`BusinessDay`、`DailyLifecycleCoordinator` | 运行编排、Turn preparation/completion、业务日捕获和跨模块确定性换日。 |
| Session | `SessionEngine`、`SessionStore`、`SessionManifest`、`SessionRecord`、`SessionReconciler` | 当日跨 Turn 不可变历史、确定性 summary、orphan reconciliation 和日归档。 |
| Workspace | `WorkspaceEngine`、`WorkspaceManifest`、`WorkspaceReconciler`、`WorkspaceTrashStore` | 当日资源事实、Manifest 投影、action、可恢复 active Trash 和 workspace/trash 归档。 |
| Agent Home | `AgentHomeEngine`、`AgentHomeLayout`、`HomeOverlayManager`、`HomeOverlayManifest`、Home providers | `home:` 链接、动态顶层目录、HOW、非 MEMORY 当日 effective overlay、runtime-copy Trap 和 Home 归档。 |
| App | `TinySoulAppBuilder`、`TinySoulApp`、`InputCommandParser`、`InputDispatcher`、`ObservationRouter` | 组装上述门面，接入终端/嵌入输入输出；不拥有 daily 或 settlement 业务状态。 |

`capabilities/` 当前没有形成独立业务能力，不应为了目录对称提前引入空抽象。

## 整体处理流程

### Program 与日切

1. `ProgramRunner.run_once` 在 work lock 内从 IANA clock 捕获一次 aware `now`，据此构造唯一 `BusinessDay`；
2. `DailyLifecycleCoordinator.ensure_active_day` 先检查 archive/active/original roots 不重叠，并优先恢复 `.pending-*`；
3. 若 active day 落后，Session 先 reconcile 并移动到 pending `session/`；
4. Workspace 完整 reconcile，先移动 active Trash 到 `trash/`，再移动 Workspace root 到 `workspace/`；
5. Home 恢复未完成 overlay operation、reconcile effective records，再移动到 `home/`；
6. 三个模块建立同一新日空 active roots；pending 原子改名为 `archive/<timezone-timestamp>/`；
7. 只有 coordinator 返回后，Program 才启动新日 User Turn。

这不是跨目录原子事务，而是 journal 驱动的可恢复前滚。新日 roots 可能在最终 rename 前已经建立，但此时调用尚未返回，不能开始 Turn；重启后会先完成 pending rename。

### User Turn

1. Context `begin_turn` 创建 UserInputs/Working/Trace，并清空上一 Turn 的 Home 与 Session Background；
2. preparation 先调用动态 Home provider 重建默认 core；若非 MEMORY 文件尚无 runtime copy，抛出专用 RuntimeException，Trap 物化后重试同一 preparation；
3. Session 按当前 `BusinessDay` 投影有界历史，Workspace 校验相同 day、reconcile 并投影同 revision Manifest；
4. Cycle 按 Phase1 更新语境与选域、Phase2 生成 ActionCall、Phase3 执行 Action；
5. `core.answer` 成功通过 TurnOutput Trap 收束 Turn；Context 生成 TurnSummary；
6. completion pipeline 先幂等写入 Session，再运行外部后处理；只有提交成功才输出 answered。

### Home effective view

1. MEMORY top/resource 始终读取 `home/` original，不创建 runtime record；
2. 其它 top/resource/HOW 首次读先查 overlay；缺页时通过 `home.runtime_copy_required` Trap 复制 original，并重试可重放 frame；
3. write/patch/delete 只提交 `runtime/home` operation 与 Manifest，delete 使用 tombstone，不删除 original；
4. 日切只把 runtime overlay 冻结到 archive；未来 settlement 才能修改 original。

## 五项语义核对

### 1. 先确定性归档，再异步或人工 settlement

结论：`部分实现`。

已实现：新 User Turn 开始前先完成不调用 LLM 的可恢复归档；archive 写入 pending settlement 标记；归档不写 original Home。

未实现：夜间后台 Agent、程序空闲启动检测、人工 Daily maintenance 命令、pending archive claim、settlement plan/review/apply/abort、状态推进与失败重试。当前只在 `run_once` 前检查日切，程序启动后若一直空闲不会主动归档。

### 2. runtime 只放当日 session/workspace/home，archive 按时间戳保存旧日四类内容

结论：`已实现核心语义`。

默认配置分别使用 `runtime/session`、`runtime/workspace`、`runtime/home`，日切移动旧 roots 并创建空新日 roots。归档结构为 `archive/<timestamp>/{transition.json,session,workspace,home,trash}`。

边界：各 active root 和 archive root 可配置；coordinator 只管理三个参与者，不会递归清空 runtime 下其它模块或用户自建目录。因此“清空 runtime”应理解为“替换三个 active roots”，不应实现为删除整个 runtime。

### 3. 旧日 Trash 进入归档，不再提供语义追踪

结论：`已实现`。

active Trash 位于 Workspace 内部 `.tinysoul/trash`，日切后独立移动到 archive `trash/`。新日 WorkspaceTrashStore 指向新 active root；list/restore 和自动恢复都不能访问旧日 Trash。归档仍保留旧 record 文件作为审计事实，但没有 active API 语义。

### 4. Home Background 每个 User Turn 重建，Phase1 临时项不跨 Turn

结论：`已实现`。

`ContextEngine.begin_turn` 同时 reset Home/Session；`ContextTurnPreparationHandler` 每 Turn 从 `HomeBackgroundEntryProvider` 重建默认 core；Phase1 条目标记为 `BackgroundSource.PHASE1`，只存在于当前 Turn。跨 Turn 信息只能来自 Session snapshot、original Home 或当日已持久化 Home overlay，而不是 Context 对象残留。

### 5. MEMORY original-read，其它 Home 通过 Trap 进入 runtime，最终写回 original

结论：`前半已实现，写回未实现`。

MEMORY bypass、非 MEMORY runtime-copy Trap、透明 effective read、overlay write/patch/delete 均已实现。确定性 archive 不应写 original；“每日归档写回”必须拆成“归档冻结 + settlement apply”。当前没有 settlement apply，所以归档 Home diff 尚不会回写 original。

## 失败与异常情况

### Daily rollover

- roots 重叠、active day 分歧、时钟倒退、多 pending、journal 损坏：`LoopContractError`/`LoopInvariantError`，经 Loop bridge 转为 startup failure，不能启动 Turn；
- participant 已移动但 journal step 未落盘：根据 pending target 与 active day 前滚；
- Workspace Trash 已移动而 Workspace root 未移动：`archive_day` 根据 source/target 继续；
- active roots 已初始化而最终 rename 未完成：重启恢复同一 pending，校验 day 后完成 rename；
- archive timestamp 冲突或目标/source 同时存在：显式失败，不覆盖目录。

### Home overlay

- operation 文件已准备或 runtime target 已替换但 Manifest 未提交：按 operation intent 和 digest 前滚；
- Manifest 已提交但 operation 未清理：幂等清理；
- copied 文件丢失且 original 仍等于 baseline：可确定性重建；
- modified/created 丢失、tombstone 路径重现、original baseline 变化导致 copied 无法恢复、operation/Manifest 状态歧义：Home invariant failure，结束当前 Turn；
- runtime-copy handler 没有真实物化进展：不重复 RETRY，结束最近 Turn，避免无限陷入。

### Turn preparation/completion

- Home default load 可重试；Session/Workspace day 不匹配或 reconciliation 不完整则结束 Turn；
- preparation signals 在全部 handlers 成功后才批量提交，避免只注入 Session 或 Workspace 的半初始化语境；
- completion 先写不可变 Session record，再写 Manifest；崩溃留下的 orphan record 在下次 preparation/archive 前接回；
- completion 未提交时即使已有模型回答，也不会报告 answered。

### Settlement

当前不存在可执行失败模型。后续至少需要区分：模型 plan 不合规的局部结果、digest/目标冲突的 needs-review、archive/plan journal 损坏的模块不变量失败、apply I/O 中断后的可恢复 operation。不能为每个 step 扩展 Runtime reason。

## 代码质量与组织评价

### 做得较好的部分

- `BusinessDay`、journal step、overlay state、Turn outcome 使用 frozen dataclass/`StrEnum`，持久状态和稳定标识明确；
- Loop 只依赖 daily lifecycle Protocol，Session/Workspace/Home 各自拥有 reconcile/archive 实现，跨模块与模块内职责基本分离；
- Home operation journal 和 Daily transition journal 都使用“先持久意图、再副作用、最后提交状态”的前滚模型；
- Turn preparation 把动态 Home、Session、Workspace 组织成明确顺序，并避免 Background 内存跨 Turn 泄漏；
- action failure、模块异常、Runtime 控制异常基本遵守三层失败语义；
- 最近提交新增了覆盖 rollover、partial move、Home operation recovery、MEMORY bypass 和逐 Turn Background 重建的针对性测试。

### 需要继续收敛的部分

1. `settlement_status` 目前只是 `DailyTransitionJournal.to_json()` 的固定字符串，读取时也不建模；它只能表示“未来有工作”，不能作为未来状态机直接扩写。Settlement 应拥有独立、版本化 manifest，并以 archive id 关联 transition。
2. 当前 daily 检查绑定 `run_once`，还没有 Program 级 maintenance work。后台 Agent、启动检测和人工命令应汇聚到同一个内部 work kind，不能分别实现三套 apply 路径。
3. `HomeOverlayManager` 已接近千行，但仍保持单一的 current-day overlay 状态机职责。Settlement 应新增独立门面/模块，不应继续扩大 overlay 或 `AgentHomeEngine` 的普通 Turn API。
4. Daily 的恢复测试集中在 Workspace move 后、journal 前。还应覆盖 Session/Home move 后、active initialization 后、final rename 失败、损坏/多个 pending 和连续跨多日恢复。
5. 缺少 settlement 与新日 active overlay 并行时的明确测试。设计应固定为 original 的 digest-CAS apply，不反向修改当前日已物化 runtime 文件。
6. 当前 `read_top`、prompt mount 和 `loadable_background_links` 仍以 original 文件存在性/目录扫描为入口。Settlement 尚未实现，因此当前不会出现并发删除；启用后台 apply 前必须把 effective top catalog 定义为 original 与 active overlay 的一致视图，否则 original 删除会让当前日已经物化的 top/HOW 提前消失，违反日内快照边界。
7. `docs/design/workspace.md` 曾把 archive 画在 `runtime/archive`，与配置和代码不一致；本次已改为顶层 `archive/`。

未发现需要在本次文档任务中立即修改的已实现代码缺陷。完整测试通过；当前主要风险是能力边界尚未闭环，而不是 rollover/overlay 已有路径与五项设计相反。

## 后续设计与实施顺序

### P0：Settlement 事实与状态模型

1. 定义独立 `SettlementManifest`、`SettlementStatus`、`SettlementOperation`，由 archive id 唯一定位；
2. 扫描最终 archive 中 pending 项，使用原子 claim 避免后台与人工重复处理；
3. 从 Session records、Home overlay Manifest、Workspace 有界摘要构造 provider-neutral settlement input；
4. plan 只保存 refs、目标、operation、precondition 和有界理由，不嵌入完整文件或消息栈。

### P1：Review 与可恢复 apply

1. Home settlement 门面负责 original link/path、baseline/current digest 和 operation journal；
2. created/modified/deleted 分别执行不存在、digest 相等、digest 相等前置条件；
3. apply 前写 intent，原子替换 original 后写 result；重复 operation 幂等；
4. 冲突、高影响删除和顶层规约进入 review，不自动覆盖；
5. 调整 Home effective top/prompt lookup，使当前日已物化 overlay 不因 original 的 settlement 变更而失效；
6. 生成机器可读状态和有界 `review.md`。

### P2：统一调度入口

1. Program 增加与 User Turn 同级的 Daily maintenance work kind；
2. App 将夜间 scheduler、启动 pending 检测和用户命令统一映射到该 work kind；
3. maintenance 执行期间不建立 active User Turn，新输入只排队；
4. 发布 `daily.*`、`settlement.*` verbose Observation，normal 只报告用户明确请求的维护结果。

### P3：记忆与 HOW 事实来源

1. 实现 `home.memory.append` 候选与 HOW usage/feedback 的幂等持久化；
2. 只有已完成并成功提交 Session 的 Turn 参与自动沉淀；
3. 补 `home.top.search`，使 settlement 结果和新 top entry 能在后续 Turn 被发现；
4. 用 end-to-end 测试覆盖“旧日冻结 -> 新日继续工作 -> 后台 plan -> 人工 review -> apply -> 后续日可见”。

## 文档同步结果

- `AGENT.md`：补充两阶段日生命周期、目录边界、MEMORY/effective overlay 和当前未实现范围；
- `docs/design/loop.md`：明确 rollover 与 settlement、当前触发时机和 archive 结构；
- `docs/design/agent_home.md`：明确 archive 不写 original，并规划 digest-CAS settlement apply；
- `docs/design/runtime.md`：区分 Program 前置 rollover 与未来 Daily maintenance Turn；
- `docs/design/app.md`：明确当前没有 scheduler/命令/pending 扫描，以及未来装配所有权；
- `docs/design/workspace.md`：修正顶层 archive 目录并明确旧 Trash 退出 active API。
