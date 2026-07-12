# 20260712 Agent Home / daily lifecycle followup plan

## 状态

status: pending

本文基于 `AGENT.md`、当前 `docs/design/` 和提交 `492fe06` 之后的代码重新审计，承接 `20260708-done-workspace home implementation record.md` 中未完成的工作。目标不是继续追加孤立 action，而是补齐 Agent Home 的有效运行时覆盖层、统一业务日、日终归档与沉淀、失败可见性和实际可用能力，使现有模块边界能够形成完整业务闭环。

## 总体结论

当前代码已经完成可靠的 User Turn 执行骨架：配置、Runtime、LLM、Action、Context、Loop、Session、Workspace、Agent Home 只读平面、App 输入输出和 console 入口都有明确门面与测试。设计主线是清楚的：

1. Runtime 只负责位置、陷入、转移、信号和观察事件；
2. Loop 组合 Program/Turn/Cycle/Phase，不复制业务模块语义；
3. Context 保存语境事实并构造 MessageStack；
4. LLM 负责供应商无关调用与模型链；
5. Action 把域选择、参数生成和批次执行分层；
6. Session、Workspace、Agent Home 分别拥有跨 Turn 历史、当日资源和长期知识；
7. App 只负责进程装配与外部 I/O。

距离 `AGENT.md` 的主要差距已经不在三阶段主链，而在“日级状态闭环”和“真实任务能力”：Home 还不能形成可审阅的当日修改，Workspace/Home 没有统一业务日与归档协调，Program 不能调度 Daily Turn，HOW/MEMORY 没有事实来源和沉淀过程，console 对失败 Turn 的普通模式反馈不足，安装后的项目资产也没有自举路径。

## 当前模块与主要类型

### Infra

status: done

主要类型：`ProjectConfig`、`ConfigEnvironment`、`ConfigSource`、`ConfigFileToml`、`DotenvSource`、`ConfigError`、JSON 类型与文件系统 helper。

作用：加载 main/include/dotenv/environment/override，保留配置来源，拒绝越界 include/env path，为上层提供 JSON 安全转换、原子文件写入、有界文本读取、digest 和根目录路径约束。Infra 不解释 Workspace、Home 或 Runtime 业务语义。

### Runtime

status: done

主要类型：`RunFrame`、`RunScope`、`RuntimeException`、`RuntimeTransfer`、`RuntimeTrap`、`TrapHandlerRegistry`、`RuntimeModuleRunner`、`Signal`、`SignalBus`、`ObservationEvent`、`ObservationEmitter`。

作用：以 Program/Turn/Cycle/Phase/Module 栈定位控制流；将少量稳定 Runtime reason 交给 Trap；只允许 RETRY/END 指向捕获 scope 内 frame；为可重放 Module 提供重试；区分有业务消费者的 Signal 与只供外部观察的 Observation。

### LLM

status: done

主要类型：`MessageStack` 与消息 part、`ToolSpec`/`ToolScope`/`ToolCallRecord`、`TaskCall`/`TaskResult`、`ModelSpec`/`ModelRegistry`、`ProviderSpec`/`ProviderRegistry`、`ModelChain`/`RetryPolicy`、`LLMTaskRunner`。

作用：维护 provider-neutral 输入输出、能力检查、工具协议映射、推理信息、JSON object 解释、provider adapter、同模型重试、模型切换和成功模型偏好窗口。provider 的 endpoint identity、adapter、enabled 和凭据来源已经分离。

### Action

status: done

主要类型：`ActionDomainSpec`、`ActionSpec`、`ActionCall`、`ActionExecution`、`ActionBatch`、`ActionResult`、`ActionPhaseResult`、`ActionExecutionControl`、`ActionEngine`、`ActionEngineBuilder`、各 backend executor。

作用：Phase1 只暴露非空 domain；Phase2 只暴露已选 domain 的 Action Tools 并归一化调用；Phase3 形成自包含 execution，执行 hook、并发规划、deadline、取消和结果收敛。`native`、`subprocess`、`script`、`llm_action` 后端机制已经存在，但 shell/script 目前没有实际 catalog action。

### Context

status: done

主要类型：`BackgroundContext`、`SessionBackgroundSnapshot`、`WorkingContext`、`WorkspaceSnapshot`、`PendingInputs`、`TurnTraceHeap`、`TaskPrompt`/`PromptBlock`、`MessageStackComposer`、`ContextSignalBatch`、`TurnSummary`、`ContextEngine`/`ContextEngineBuilder`。

作用：维护本 Turn 的输入、Session/Home Background、Workspace/里程碑/待办和 canonical trace；通过事务信号批次提交状态；按固定区段构造 MessageStack；在字符或图片预算超限时向 Runtime 请求压力恢复；seal 完整 trace 交给 Session。

### Loop

status: in_progress

主要类型：`ProgramRunner`、`TurnRunner`、`CycleRunner`、`Phase1Unit`/`Phase2Unit`/`Phase3Unit`、`TurnPreparationPipeline`、`TurnCompletionPipeline`、`ContextSignalConsumer`、各 Trap handler。

作用：消费 Runtime transfer，组织 Session/Workspace preparation、三阶段 Cycle、输入追加、安全边界、Context pressure、Workspace Trash restore、Turn completion 和最终回答提交。User Turn 主链已经完成；当前 Program 只调度 User Turn 与退出事件，还没有同级维护任务。

### Session

status: done

主要类型：`SessionHistoryItem`、`SessionManifest`、`SessionRecord`、`SessionStore`、`SessionReconciler`、`SessionEngine`、preparation/completion handler、history action executor。

作用：把完整 Turn 作为不可变事实保存，以 Manifest 维护有界跨 Turn 背景头部；确定性生成 summary；分页 inspect/recall；在 record 已写而 Manifest 未提交时收养 orphan；跨日归档前验证完整图。支持级别是单进程写入、Engine 实例内串行化。

### Workspace

status: in_progress

主要类型：`WorkspaceLink`、`WorkspaceResourceRecord`、`WorkspaceManifest`、`WorkspaceReconciler`、`WorkspaceEngine`、`WorkspacePromptInput`/`WorkspaceTextSlice`、`WorkspacePromptReferenceResolver`、`WorkspaceTrashItem`、action executor 和 preparation handler。

作用：管理 active Workspace、资源分类、Manifest、description、Prompt 临时读取、write/rewrite/patch、逻辑删除、恢复、压力回收与 Context 全量投影。上述 User Turn 能力已经完成，当前一致性等级已经明确为单进程单写者、同一 Engine 实例内线性化；日终归档未实现，document 只有 `conversion_required` 诊断而没有转换 action。

### Agent Home

status: in_progress

主要类型：`HomeTopLink`、`HomeResourceLink`、`HomePromptMountLink`、`AgentHomeLayout`、`AgentHomeRuntimeCopyManager`、`AgentHomeEngine`、`HomeBackgroundContentLoader`、`HomeDomainHowProvider`、`HomeActionHowProvider`、`HomeResourceReadExecutor`。

作用：解释 `home:` 链接，提供 core/可加载背景、domain/action HOW、渐进资源有界读取和 runtime copy 缺页恢复。当前只有“原始文件 -> runtime 副本 -> 只读使用”平面；runtime-only 文件、覆盖层 Manifest、写入、patch、搜索、memory、feedback、diff、归档和 merge 均未实现。

### App 与 Capabilities

status: in_progress

主要类型：`TinySoulAppBuilder`、`TinySoulApp`、`InputEvent`/`InputDispatcher`、`TerminalInputSource`、`ObservationRouter`、`ConsoleOutputSink` 和 CLI。

作用：装配所有模块，区分 inactive/active Turn 输入，把最终回答写 stdout，把详细观察写 stderr。App 核心入口已经完成；`tinysoul/capabilities` 当前为空，默认 config/Home/catalog 也没有作为独立项目模板形成安装后自举闭环。

## 当前处理流程

### 1. 启动与装配

1. `ConfigEnvironment` 按 main、include、dotenv、process env、override 顺序合并配置并保留来源；
2. AppBuilder 校验顶层 section，各模块 parser 拒绝未知 key；
3. 构建 Observation router、provider/model/task registry、Home、Workspace、Session 和 Context；
4. 启动 recovery 只物化 `home:agent@core`，其它 Home 内容保持 lazy；
5. 构建 `LLMActionTaskRunner`，注册 Context/Session/Workspace/Home/core executor；
6. 构建 Trap registry、Module runner、Phase/Cycle/Turn/Program runner；
7. 构建 InputDispatcher、TerminalInputSource 和 console sink。

### 2. User Turn

1. 无 active Turn 的输入进入 Program queue；有 active Turn 的普通输入变成 `context.input.append`，stop/exit 变成 `loop.control.request`；
2. Context `begin_turn` 创建 UserInputs、WorkingContext 和 TurnTraceHeap；
3. preparation 先投影 Session history，再 reconcile 并投影 Workspace Manifest；两个 snapshot 在 Context preparation 窗口中事务提交；
4. Cycle 边界消费用户追加输入和控制请求；
5. Phase1 构造 MessageStack，调用 framework LLM，归一化 Context controls 并选择 action domain；
6. Phase2 注入 domain HOW，只暴露已选 domain actions，生成并归一化 `ActionCall`；
7. Phase3 形成 `ActionBatch`，执行 hook/backend/deadline/cancel，将业务副作用信号提交 Context，并把 ActionResult 写入 TurnTraceHeap；
8. 唯一成功 `core.answer` 触发 `runtime.turn_output` Trap，发布作用域化 output signal 并结束 Turn；
9. Context seal 为 `TurnSummary`，Session completion 先持久化；只有 completion 成功后才发布 `turn.output` Observation。

### 3. 恢复与失败

- LLM 模型输出不符合任务协议：局部 `TaskResult.failure`，Phase1/Phase2 在上限内反馈重试；
- Action 参数、hook、普通执行和 timeout：call 级 `ActionResult`；无法绑定 call 的 scope/batch 问题：phase-level result；
- Context signal 不合规：`ControlResult`，合法变更仍按投影验证后成批提交；
- provider 暂时性失败：同模型有限重试并进入后续 chain cycle；永久/配置/认证错误：当前调用不再打同一模型并切换；未知实现异常：立即中止；
- Context budget：Trap 先折叠 recall/trace，再逐出 Phase1 background，必要时暂存可回收 Workspace 资源；有进展才重试 replayable frame；
- Home runtime copy miss：原子建立副本后重试当前 Module；不可恢复或重复 miss 结束 Turn/Program；
- Workspace pressure resource miss：从确定 Trash ref 恢复、同步 Context 并重试 Module；显式 delete 不自动恢复；
- Session crash window：不可变 record 保留，下一次 reconciliation 收养 orphan；同 ref 不同完成事实视为 invariant failure；
- Workspace mutation：内容与 Manifest 不能形成跨文件系统事务，Manifest 失败时以操作前字节回滚；
- Output sink：从业务控制流隔离，失败 sink 被禁用，App 在业务边界结束后报告 `AppOutputError`。

## 设计与代码质量判断

### 已经形成的优势

status: done

- 门面清楚：业务模块均通过 Engine/Builder 或 registrar 接入，上层没有绕过 Workspace/Home/Session 直接读写文件；
- 状态层次清楚：磁盘事实、模块内存和模型 MessageStack 是不同对象，投影方向明确；
- 控制层次清楚：局部结果、模块异常和 Runtime 控制异常已经大体分离；
- 动态边界清楚：TOML、JSON、env、provider response 和模型参数在入口处转换，`Any` 没有扩散成内部主类型；
- 核心对象大量使用 frozen dataclass 与 StrEnum，不变量集中在构造边界；
- 并发语义诚实：Workspace/Session 没有夸大为跨进程事务，Action 对 native 泄漏风险有显式表达；
- 测试覆盖按模块组织，LLM、Action、Context、Workspace 的高风险路径有较多契约测试。

### 需要在扩展前处理的质量风险

status: pending

1. `TurnOutcome` 只有 output/exhausted/transfer，没有稳定失败摘要。normal 模式只显示成功回答；模型链耗尽或 completion 失败可能结束 Turn，但 `--once` 仍返回成功且没有普通模式诊断。
2. `TurnCompletionPipeline` 只是顺序调用。Session 已幂等，但增加 Home feedback/settlement handler 后，需要明确 handler 幂等、失败后重放和已提交前序 handler 的语义，不能依赖调用顺序碰巧安全。
3. Home runtime copy 只有进程内 ready set，没有持久 overlay Manifest。它不能区分 copied/created/modified/deleted，也不能安全表达 runtime-only 文件和跨日状态。
4. Context 在 AppBuilder 构建时冻结 Home loadable links。运行期新增或沉淀产生的顶层条目无法在不重建 Context 的情况下进入 Phase1 control scope。
5. 当前 `home/` 只有 `agent/AGENT.md`；WHAT、WHY、HOW、how_domain、how_action、MEMORY 的机制有代码但没有实际内容。运行时 Agent 规约也尚未说明未来 search/write/memory 的使用方式。
6. Workspace/Home 没有共享业务日；Turn 跨午夜时，Session 按完成时日期归档，而 Workspace/Home 没有 day identity，三者可能归属不同日期。
7. `ActionHookRegistry` 私有 lookup 仍抛裸 `KeyError` 后再由 pipeline 宽捕获；虽然当前会收敛为局部结果，但与模块失败风格不完全一致，应改为 Action 私有/契约错误。
8. 部分 Settings `__post_init__` 只比较数值而未显式拒绝 `bool`；parser 已拒绝，但直接构造边界不完全一致。
9. `workspace/engine.py`、`context/engine.py`、`workspace/actions.py` 和 `app/builder.py` 已较大。现有职责仍可解释，不建议机械拆分；新出现的 overlay、archive、search、settlement 应放入独立且有真实职责的组件，避免继续扩大这些文件。
10. `docs/design/runtime.md` 的 Program 同级任务和 `docs/design/app.md` 的安装后 console 表述超前于当前实现，需要在功能落地前明确当前边界。

## 功能缺口分级

### P0：日级状态正确性

status: pending

- 统一业务日尚不存在；
- runtime Home 没有 day marker、overlay reconciliation 或 rollover；
- Workspace 没有 archive API 和 day-aware Trash；
- Program 没有 Daily Turn/maintenance work item；
- 跨午夜 Turn 的 Session/Workspace/Home 归属不一致；
- 没有 crash-resumable 的跨模块日切换 journal。

### P0：Agent Home 可写覆盖层

status: pending

- runtime-only resource 当前不可读，因为读取先要求 original source 存在；
- 没有 create/write/patch/delete/tombstone；
- 没有 baseline digest、runtime digest、revision 和 expected digest；
- 没有 effective view（runtime 优先、original fallback）和完整 reconciliation；
- runtime 内容消失或出现孤儿文件时没有持久恢复协议。

### P1：检索、记忆与 HOW 反馈

status: pending

- `home.top.search` 不存在；AGENT 要求的 top-k semantic matching 没有实现；
- Context loadable catalog 不是动态的；
- `home.memory.append` 和 `this_day_memory.md` 不存在；
- HOW 使用事实、效果反馈、`SKILL_MEMORY.md` / `DOMAIN_MEMORY.md` 不存在；
- Session 完整 Turn record 尚未作为每日沉淀的确定事实输入接入。

### P1：每日沉淀与审阅

status: pending

- 没有 Home diff、SettlementPlan、expected-digest precondition、apply journal 和审阅摘要；
- 没有独立 LLM maintenance profile；
- 没有 plan/status/apply/abort 入口；
- 没有把 Session archive、Workspace archive summary、Home overlay 和用户显式保留/删除意图组合成一次维护任务；
- 没有解决旧日 plan 延迟应用与当前日 runtime copy 的冲突。

### P1：失败可见性与真正可用入口

status: pending

- normal 模式没有 `turn.failed` / `turn.exhausted` 诊断；
- `--once` 不根据 TurnOutcome 返回失败 exit code；
- 交互模式没有维护任务命令与状态显示；
- 没有 README、项目初始化命令和安装产物的默认配置/Home/catalog 资产验证；
- 缺少不触网的完整 CLI -> Program -> Turn -> Session/Workspace smoke test。

### P2：实际行动能力

status: pending

- `shell`、`script` 只有 domain 定义，没有实际 action，因此会被 Phase1 正确过滤但不具备业务能力；
- `tinysoul/capabilities` 是空包；
- document 类型要求显式转换，但没有 document-to-text action；
- 没有经过明确安全边界的受控命令/脚本 action；
- 真实 provider 测试默认 skip，缺少可选的端到端发布 smoke gate。

## 目标设计决策

### 1. 业务日属于 Program/Loop，不属于 Runtime scope

status: pending

Runtime frame 继续只表达控制位置，不携带日期。Program 在开始一项 work 时捕获唯一 ISO business day，并把它作为业务参数传给 User Turn 或 Daily Turn。一个跨午夜 User Turn 始终归属于开始时的 day；日切换只在 Turn 边界执行。

建议引入：

- `ProgramWorkKind.USER_TURN` / `DAILY_MAINTENANCE`；
- `ProgramWorkItem`：work kind、business day、输入和来源；
- `TurnCompletion.day`：让 Session 使用 Turn 开始日，而不是完成时重新读取系统日期；
- 可注入的 `BusinessDayClock`，生产实现读取本地日期，测试实现控制跨午夜；
- Workspace/Home active metadata 中的 `day` 与 schema version。

InputDispatcher 只观察 active User Turn。Daily Turn 执行期间的新用户输入排入 Program queue，不能作为追加输入写入维护任务。

### 2. Agent Home 使用持久 effective overlay

status: pending

现有 runtime copy manager 应演进为 Home overlay 的一部分，而不是直接在 Engine 上追加几个写方法。建议结构：

```text
runtime/home/
  .tinysoul/
    manifest.json
    operations/
  agent/
  what/
  why/
  how/
  how_domain/
  how_action/
  this_day_memory.md
```

建议核心对象：

- `HomeOverlayRecord`：relative path、baseline digest、runtime digest、state（copied/created/modified/deleted）、size、mtime；
- `HomeOverlayManifest`：schema、day、revision、records；
- `HomeOverlayStore`：原子加载/提交；
- `HomeOverlayReconciler`：扫描 runtime 文件、校验 original baseline、收养可判定 orphan、拒绝模糊损坏；
- `EffectiveHomeResource`：link、effective path、origin/runtime 状态和 digest；
- `AgentHomeEngine` 继续是唯一上层门面，并以 `RLock` 串行化同一实例公开读写。

读取规则：runtime 非 tombstone 版本优先；没有 runtime record 时 original 是候选；真正进入 Background/HOW/ActionResult 前仍通过 copy Trap 建立 runtime record。搜索可以读取 effective candidate metadata，不因候选发现而物化全部副本。

写入规则：普通 User Turn 只写 runtime；已有 original 的首次写入先物化并记录 baseline digest；runtime-only 新资源允许直接创建；删除写 tombstone，不能因 fallback 让 original 重新出现；每次变更都使用真实字节 digest 和原子替换，Manifest 提交失败时回滚文件或保留可恢复 operation record。

一致性等级与 Workspace 相同：单进程单写者、Engine 实例内线性化；不宣称跨进程 CAS。

### 3. Home 顶层目录必须是动态 provider

status: pending

Context 不应解释 Home 文件，但不能继续冻结启动时 link 清单。将静态 `dict[link, loader]` 扩展为 Context 自有的 `BackgroundEntryProvider` 协议：

- `links()` 返回当前可加载顶层链接；
- `load(link)` 返回非空文本；
- Context 每次构造 Phase1 control scope 时查询 links；
- provider 只返回 Home link 和内容，不泄漏路径；
- 同一 signal batch 仍先 prepare 全部 lazy content，再提交 Context 状态。

这使 settlement 或 runtime memory 产生的新 top entry 能在后续 Cycle/Turn 被发现，同时保持 Context 不依赖 Agent Home 类型。

### 4. `home.top.search` 采用候选发现与语义重排两段式

status: pending

不能把文件名 substring scan 标成 semantic search。建议：

1. Home 枚举 effective top records，提取 link、space、标题、显式摘要/首段、digest 和有界 searchable text；
2. 使用确定性文本分数做候选裁剪，限制送入模型的记录数和字符数；
3. Home-owned `home.top.search` executor 复用 `LLMActionTaskRunner` 或独立 maintenance/search profile，对候选做 semantic rerank；
4. 严格校验模型只能返回候选集合中的 link；
5. ActionResult 只返回 top-k link、summary、短 snippet 和 score/reason，不自动加载 Background；
6. 下一 Cycle 由 Phase1 `load_background` 选择需要的 top link。

无匹配是成功空结果；query/space/top_k 参数错误是局部 ActionResult；索引或 effective Home 不完整是 Home 模块边界失败，不能静默漏掉损坏知识。

### 5. Memory/HOW 使用事实先进入 Session，再生成 Home 投影

status: pending

不要在 HOW provider 读取时做不可审计的旁路追加。建议把使用事实写入 canonical Turn trace，再由 Session 不可变 record 保存：

- domain HOW provider 返回内容及实际 link；
- action HOW provider 返回 domain/action 内容及实际 links；
- Phase2 和 action-internal LLM task 记录 compact `how_usage` phase/action metadata；
- `home.memory.append` 产生带稳定 id、Turn id、links 和候选文本的局部事实；
- Session record 成为日终 feedback/memory reconstruction 的事实源；
- Home feedback projector 按 day/turn/ref 幂等生成 `this_day_memory.md`、`SKILL_MEMORY.md`、`DOMAIN_MEMORY.md` 等 runtime 投影。

这样进程在“使用 HOW”后崩溃时，已完成 Turn 的事实仍可从 Session reconciliation 恢复；未完成 Turn 不会留下被误认为成功经验的长期反馈。

### 6. Daily Turn 使用可恢复 journal，不伪装跨模块事务

status: pending

Workspace、Session、Home 不可能通过普通文件系统形成一个原子事务。Daily coordinator 应记录 operation journal，并要求每个模块操作幂等：

1. 冻结目标 day，拒绝新 User Turn 写入该 day；
2. Session reconciliation 完成并归档；
3. Workspace 完整 reconcile，生成 archive summary，归档 active root；
4. Home 完整 overlay reconcile，冻结 runtime diff；
5. 生成 SettlementPlan 与人类可读 diff；
6. 按 policy 等待 review 或应用计划；
7. 初始化新 day 的 active Workspace/Home 元数据；
8. journal 标记每个已提交步骤，崩溃后从未完成步骤继续。

跨模块 partial completion 是可恢复中间态，不写成“全部原子”。archive destination 冲突、day marker 不匹配、Manifest/overlay 损坏属于模块不变量失败；计划 precondition 冲突进入 `needs_review`，不是自动覆盖。

### 7. Settlement 分离 plan 与 apply

status: pending

建议输出：

```text
runtime/settlement/<day>/
  inputs.json
  plan.json
  review.md
  apply-journal.json
```

`SettlementPlan` 中每个 operation 明确 target Home link、operation kind、baseline/expected digest、候选内容或 patch、来源 Session/Workspace refs 和理由。LLM 只生成候选计划；Home settlement validator 重新检查 link、schema、digest、内容上限和相互冲突。

apply 默认需要显式确认。已应用 operation 通过稳定 operation id 幂等跳过；部分应用后重启继续；original Home 被外部修改时停止并生成 conflict，不覆盖。旧日计划延迟应用到当前日时，若当前 runtime copy 仍等于旧 baseline，可显式 rebase；若当前日已有修改，则保持冲突等待审阅。

原始 Home 只在 settlement apply 边界可写。普通 User Turn、search、HOW provider 和 Home action 均不能绕过 overlay 写 original。

### 8. Turn 失败必须成为普通模式可见事实

status: pending

建议增加稳定 `TurnOutcomeStatus` 与有界 `TurnFailure` 摘要。Trap 捕获时保留 reason、module、kind 和安全 message；不保留 traceback、大 payload 或 provider 原始数据。

观察与 CLI 语义：

- answered：`turn.output` 写 stdout，`--once` 返回 0；
- exhausted：`turn.exhausted` 写 stderr，`--once` 返回非 0；
- failed：`turn.failed` 写 stderr，包含稳定 reason/module/kind，`--once` 返回 1；
- user stop：明确记录 stopped，不伪装内部失败；
- interactive Program 在单个 Turn 失败后继续等待下一输入，除非 transfer 指向 Program。

normal 仍不输出模型/动作细节，但不能保持无声失败。

## 实施阶段

### 阶段 0：契约与可见性清理

status: pending

实施项：

- 增加 `TurnOutcomeStatus` / `TurnFailure`，发布 normal 级 failure/exhausted/stopped Observation；
- CLI `--once` 消费 outcome 并返回稳定 exit code；
- 为 Turn completion handler 明确幂等契约和后续重放边界；
- `ActionHookRegistry` 未命中改用 Action 私有/契约错误；
- Settings 直接构造统一拒绝 bool/错误类型；
- 增加失败 Turn、completion 失败、exhausted 和 CLI exit code 测试。

验收：任何没有 final answer 的 `--once` 调用都不会静默返回 0；normal 模式不泄漏 MODEL payload。

### 阶段 1：统一业务日

status: pending

实施项：

- Program work item 捕获 business day；
- TurnRunner/TurnCompletion 传递开始日；
- Session preparation/completion 改用显式 day，保留现有幂等和 orphan 语义；
- Workspace/Home active metadata 加 day；
- fake clock 覆盖跨午夜 Turn、Turn 间 rollover 和重启测试；
- day mismatch 在修改任何 active state 前显式失败或调度维护。

验收：跨午夜 Turn 的 Session record、Workspace owner metadata 和 Home memory fact 使用同一开始日。

### 阶段 2：Agent Home overlay 与写入

status: pending

实施项：

- 增加 Home overlay manifest/store/reconciler；
- 将原子 runtime copy 纳入 overlay record；
- 支持 effective read、runtime-only create 和 tombstone；
- 增加 `home.resource.write` / `home.resource.patch`，必要时补充明确 delete action；
- 使用 `expected_digest`、RLock、文件回滚和 operation recovery；
- action 成功只返回元数据，普通冲突收敛为局部 ActionResult；
- 增加 crash window、orphan runtime file、源文件变化、symlink 和跨进程非保证测试。

验收：original Home 在 User Turn 中零写入；runtime-only resource 可立即读取；重启后 diff 状态不丢失。

### 阶段 3：动态顶层目录与搜索

status: pending

实施项：

- Context 接入动态 `BackgroundEntryProvider`；
- Home 建立 effective top catalog 与有界摘要；
- 增加 `home.top.search` action、候选限制和语义 rerank；
- 新增/沉淀 top entry 无需重建 App 即可进入后续 Phase1 scope；
- 搜索结果不自动复制、不自动加载 Background、不返回长正文；
- 增加中英文查询、损坏候选、runtime override、新 entry 和 budget 测试。

验收：搜索返回的 link 在下一 Cycle 可被 `load_background` 接受，Context 仍不读取 Home path。

### 阶段 4：Memory 与 HOW feedback

status: pending

实施项：

- HOW provider 返回实际使用 links；
- Phase2/action-internal task 把 HOW usage 写入 canonical trace；
- 增加 `home.memory.append` 的稳定候选事实；
- 从 Session record 幂等投影当日 memory/HOW 文件；
- 提供 bounded inspect/recall，避免反馈文件整份进入 Context；
- 增加 Turn 成功/失败、重复 completion、orphan Session、同一 HOW 多次使用和截断测试；
- 补充真实 `home/how_domain`、`home/how_action` 和至少一个通用 HOW 内容。

验收：只完成并持久化的 Turn 参与自动 feedback；重复 reconciliation 不产生重复条目。

### 阶段 5：Workspace archive 与 Daily Turn

status: pending

实施项：

- Workspace Manifest schema 加 day，配置增加 archive root；
- Trash record 加 day，并明确跨日 list/restore 语义；
- Workspace archive 前强制完整 reconcile，生成无正文 archive summary；
- ProgramRunner 支持与 User Turn 同级的 Daily maintenance work；
- Daily 执行期间不设置 active User Turn，新输入只排队；
- 增加跨模块 journal、幂等 resume、archive collision 和 partial completion 测试；
- 发布 verbose `session.reconciled`、`workspace.archived`、`home.overlay.frozen`、`daily.*` Observation。

验收：旧日 active roots 不会被新日继续复用；任一 crash point重启后都能继续或明确进入 review，不静默删除资料。

### 阶段 6：Settlement plan/review/apply

status: pending

实施项：

- 定义 settlement LLM profile 和 provider-neutral Prompt；
- 汇集 Session records、Workspace archive summary、Home diff、memory candidates 和 HOW feedback；
- 生成并严格校验 `SettlementPlan`；
- 实现 plan/status/apply/abort CLI 或等价明确入口；
- apply 使用 expected digest、stable operation id 和 journal；
- 生成 `review.md` 与机器可读结果，不把原始消息栈或大文件嵌入 plan；
- 增加冲突、延迟 apply、部分 apply、重复 apply、LLM 非法输出和人工拒绝测试。

验收：每一项 original Home 变更都能追溯到 operation、来源 ref、precondition 和 apply 状态；普通 User Turn 无法直接修改 original Home。

### 阶段 7：真实行动能力与发布闭环

status: pending

实施项：

- 明确本地个人 Agent 的命令执行信任边界；
- 增加至少一个受控 script action，固定 workspace cwd、无 `shell=True`、有 deadline/cancel 和 bounded stdout/stderr；
- 增加 document conversion capability，将结果写成新的 `workspace:` text resource；
- 只在有具体业务后扩展 `tinysoul/capabilities/<capability>`；
- 使用 package data 或 `importlib.resources` 提供 built-in catalog；
- 增加 `tinysoul init` 或等价项目模板入口，生成 config、Home core 和 env example；
- 补充 README、wheel 安装 smoke、无网络 fake-provider E2E 和显式开启的真实 provider smoke。

验收：在不依赖源码仓库目录布局的干净环境中，可以初始化项目、配置一个 enabled provider、运行一次 `tinysoul --once`，并得到成功回答或明确失败诊断。

## 失败语义约束

后续实现继续遵守三层失败语义：

- 局部结果：search 参数、无匹配、write digest conflict、patch 不适用、memory candidate 不合规、settlement plan operation conflict；
- 模块边界异常：Home overlay/Workspace archive/Session graph 损坏、路径不变量破坏、原子 I/O 失败、动态 catalog 无法完整解释；
- Runtime 控制异常：启动失败、结束 User/Daily Turn、结束 Program，以及确有可重放恢复语义的 runtime copy/context pressure/workspace restore。

不要为普通 daily step 新增大量 Runtime reason。Daily pipeline 自身可以用结构化 step result 和 journal 表达可继续、needs_review、failed；只有需要改变 frame 控制流时才进入 Trap。

## 组织与编码约束

- `AgentHomeEngine`、`WorkspaceEngine`、`SessionEngine` 继续是上层门面；
- `actions.py` 只做参数适配、调用门面、结果/Signal 映射；
- Home overlay、search、settlement和 Workspace archive 是新增真实职责，可使用独立模块，避免继续扩大现有 engine/actions 文件；
- AppBuilder 只注入 coordinator/provider/registrar，不读取 Home diff 或执行 archive；
- Daily cross-module 编排属于 Loop/Program 层，不下沉 Runtime，也不放进 AppBuilder；
- 磁盘结构、TOML、JSON、LLM 输出先校验为明确对象；
- 所有 persisted schema 带版本并提供显式迁移或明确拒绝；
- 不引入兼容 alias、空接口、未消费字段或“以后可能需要”的 registry；
- normal/verbose/model payload 必须有界且不包含 API key、原始 reasoning、provider payload 或文件正文。

## 接受的边界与非目标

- Active Session、Workspace、Home 继续只保证单进程单写者；不增加分布式锁或数据库事务；
- 跨模块日切换采用 journal 和幂等 resume，不宣称原子事务；
- 流式 LLM 输出、HTTP/WebSocket 输入、多用户隔离和企业级调度不属于本计划；
- semantic Home search 可以复用现有 LLM 做候选重排，不在没有真实需求时提前建设向量数据库；
- 原始 Home 的自动无审阅覆盖不是默认目标；默认保留 plan/review/apply 边界；
- 现有大文件不因行数单独拆分，只在新增职责确实独立时建立模块。

## 全局验收

每个阶段完成时均需：

```powershell
python -m pytest tests -q
$env:TINYSOUL_PYTHON='当前设备的 TinySoul python.exe'; .\scripts\typecheck.ps1
```

最终还需要：

- 跨午夜和每个 archive/apply crash point 的恢复测试；
- original Home 普通 Turn 零写入测试；
- Workspace/Home/Session day 一致性测试；
- normal 模式失败可见且 MODEL 数据不泄漏测试；
- console `--once` exit code 测试；
- wheel/project init/CLI smoke；
- `docs/design/agent_home.md`、`workspace.md`、`session.md`、`loop.md`、`runtime.md`、`app.md` 与 `AGENT.md` 当前进度同步。
