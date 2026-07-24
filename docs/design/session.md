# Session 设计

## 定位

Session 是当日跨 Turn 会话历史的唯一持久化归属模块。它不维护当前 Turn 的可变执行状态，不参与 Phase 决策，也不直接调用 LLM。Context 负责当前 Turn 语境，Session 在 Turn 完成后接收不可变 `TurnCompletion`，在下一 Turn preparation 期间把有界历史头部投影为 `SessionBackground`。

Session 与 Workspace 一样具有日级生命周期，但二者保存不同事实：Workspace 保存 Agent 可操作资源；Session 保存用户 ask、Turn 内 reason/action/result 轨迹、最终 answer 和结束状态。Agent Home 负责经过沉淀的当前知识与技能，独立 Memory 模块负责按日期提炼长期记忆；Session 不替代二者。

## 持久模型

active Session 根目录包含：

```text
runtime/session/
  manifest.json
  turns/<turn_id>.json
  summaries/<summary_id>.json
```

`turns/` 中的完整 Turn record 是不可变事实，包含 TurnSummary、输出、exhausted 状态、确定性 `action_history` 和用于恢复排序的 `recorded_at_ns`。Record schema 直接使用 v3，不读取或迁移 v1/v2。TurnSummary 的 canonical trace 是证据事实，`trace_digest` 是该 trace 稳定 JSON 的 SHA-256 完整性事实，`action_history` 是同一 trace 的确定性物化派生，不是独立事实源。Session-owned Turn record validator 是这些关系的唯一校验入口：写入前、生命周期 reconciliation、actions/recall 证据读取与 Memory facts projection 都复用它；任一 digest、物化摘要或复制的内在 Background 事实不一致都会成为 invariant failure。Manifest 只保存下一 Turn 可见的有界历史头部：`turn` item 或 `summary` item、背景投影、估算字符数及 child refs。近期 Turn 投影固定包含 ask、answer、结束状态、trace identity 与 `action_outcome_summary`；配置 allowlist 仍只选择少量 Action detail 进入自动背景。validator 不依据当前配置重新选择旧 record 的 Background action detail，因此配置变化不会重写首次提交语义。summary record 保存被合并节点的完整头部和子引用，不合并子 Turn 的 Action counts，也不删除原 Turn record，因此摘要是索引层压缩，不是事实层丢失。

`TurnActionProjector` 只扫描 canonical trace 中 Phase2 decision 的 Action ToolCall 与 Phase3 action_result 的 canonical Action envelope，排除 Control、reasoning 和 phase note。它按 call id 分组，只有唯一 call/result 且 action name 一致才形成有效 pair；missing/orphan/duplicate/name mismatch 都显式报告。name mismatch 拆为 call action 与 result action 两个异常 occurrence，状态和 failure 始终归到实际 result action；`pairing_issue_count` 因此统计异常 occurrence 而不是 call-id group。投影包含 trace indexes、status/stage、typed failure、全 Turn counts、by-action 状态计数、failure groups、`scan_complete` 与 `pairing_complete`，不复制 raw arguments 或业务 payload。Turn completion 使用 projector 生成 Background 摘要与持久 `action_history`，validator 在后续生命周期和证据读取边界重算并比较；inspect/Turn preview 只消费已经提交的结构化导航投影，不扫描 Action。Summary 不聚合子节点 Action counts，派生摘要不是第二事实源。

Session 不读取 `date.today()`，也不拥有 archive root 配置。Program 在 work 边界传入唯一 `BusinessDay`；日切时 Loop coordinator 先要求 Session 完成 reconciliation，再把 active root 移到统一 pending archive 的 `session/`，最后与 Workspace 一起打开新日。Home 不参与这一 Business Day 事务。Manifest 和 record 使用稳定 JSON 与原子写入；day 不匹配、损坏或归档目标冲突显式失败，不静默重建。

## 摘要与渐进恢复

Session 的 `background_max_chars` 是跨 Turn 历史头部预算。当可见 item 估算超过 60% watermark 时，每次 Turn completion 最多执行一次确定性合并：保留至少 `min_recent_turns` 个最近 Turn，把更旧的连续前缀替换为一个 immutable Summary node。Summary 可递归包含 Summary，原 Turn/Summary record 不删除。默认目标比例为 40%，为下一批 Turn 留出增长空间。若极端单条投影仍超过总预算，下一 Turn 只注入 `session_overflow_head` 与可容纳的最近节点，模型通过无 ref inspect 恢复 authoritative Manifest root。

SessionBackground 只在 Turn preparation 期间以唯一版本化 `context.session.sync` 进入 Context，在该 Turn 内固定且不可逐出。`session.history.*` 是普通 Phase2 Action；其 ActionResult 进入当前 Interaction/TurnTrace，不发出 Session sync 或 Background patch，不会将展开后的节点写回自动 Background。

恢复是分层、显式和有界的：

- `session.history.inspect(ref?)` 无 ref 时分页返回 authoritative Manifest root，Summary ref 时返回直接 children，Turn ref 时返回单节点 overview。每个节点只携带 Session-owned 有界 `preview`、`child_count` 与 ref/kind；它不返回 raw trace 或重新统计 Action。root continuation cursor 绑定 Manifest revision，revision 变化时显式要求从 root 重新开始；revision 作为 Session-owned opaque cursor binding 交给 Infra pager，current/next cursor 的最终形态都参与 hard character budget，Infra 不解释 revision；Summary/Turn record immutable，不使用 revision cursor；
- `session.history.actions(ref)` 只接受具体 Turn ref，始终从完整 canonical trace 投影全 Turn summary、by-action 计数、failure groups 和 trace indexes；details 按 occurrence 分页，不返回 raw arguments 或 raw result payload；
- `session.history.recall(ref)` 只接受具体 Turn ref，只分页返回 canonical `trace_entry`、source、coverage 与 digest-bound oversized continuation。inspect/recall 共享 immutable JSON sequence hard pager 和 `history_page_max_chars/entries`，但各自拥有 ref/kind/source 语义；`max_entries=1` 可根据 actions 返回的 trace index 精确恢复；recall 不返回 Background、preview 或 Action summary，Summary ref 必须由 inspect 展开；
- actions/recall ActionResult 使用 foldable trace projection，当前 Cycle 可见完整结果，后续压缩折叠为 origin ref，避免历史恢复递归放大当前 TurnTraceHeap。

inspect/actions/recall 都读取 Engine 最近一次已提交的 Manifest 与 immutable record，不触发 orphan reconciliation，也不修改 Manifest revision。已知 orphan ref 在下一次生命周期 reconciliation 前不属于 authoritative root；恢复 record 与改变可见头部只发生在 Session 生命周期边界，不由用户查询产生副作用。

## Turn 生命周期

1. `ContextEngine.begin_turn` 创建当前 Turn 状态并打开 preparation 窗口；
2. `SessionTurnPreparationHandler` 使用 Turn 开始日校验 active Manifest，产生唯一版本化 `context.session.sync`，位于 Home 默认 Background 重建之后、Workspace snapshot 之前；
3. Context 关闭 preparation 窗口后，SessionBackground 在整个 Turn 固定，Phase1 不能修改；
4. Turn 结束后 Context seal trace 并生成 TurnSummary；
5. `SessionTurnCompletionHandler` 先持久化完整 Turn record，再原子提交新 Manifest，必要时生成一个 summary node；
6. Session completion 失败经 RuntimeSessionBridge 映射，仍在原 Turn scope 进入 Trap。

## 幂等提交与 orphan reconciliation

Turn completion 使用“不可变 record 先行、Manifest 后提交”的顺序。Turn record 的幂等语义由 v3 completion、output、exhausted 和 day 共同决定；background 是首次提交时按 Session 配置生成的派生投影，不参与重放身份，因此重启后调整投影配置不会把同一完成事实误判为冲突。相同 `session:turn/<turn_id>` 与相同语义内容重复提交时直接复用已有 record；若同一 ref 对应不同完成事实，则抛出 `SessionInvariantError`，不会覆盖先前事实。summary record 以 day、schema 和有序 child refs 判断幂等。Manifest revision 只对新接入的 Turn 递增，完全相同的重放不改变 revision。

进程可能在 record 原子落盘后、Manifest 原子提交前退出，因此 record 存在而未从 Manifest 图可达是合法的可恢复中间态。Session 在加载现有 active root、Turn preparation/completion、显式 `reconcile_active` 和归档前执行 reconciliation：先通过唯一 Turn validator 校验全部 Turn record，再递归校验 Manifest/summary 图的引用存在性、kind、background、char count、child refs、重复子节点和环，最后按 `recorded_at_ns, ref` 的稳定顺序接入 orphan Turn。普通 inspect/actions/recall 不执行这一流程。构造 Engine 不会隐式创建新日或隐式跨日搬迁；这些状态改变只能由 `initialize_day`/`archive_day` 触发。损坏的已提交图或 orphan record 属于内部不变量失败，不静默重建。

summary id 由 day、schema 和有序 child refs 的 digest 确定。若生成 summary record 后 Manifest 提交失败，重试会复用同一 summary，而不会产生重复摘要。不可达 summary 不独立接入可见头部，因为它是派生索引而不是新的 Turn 事实；reconciliation 会报告这些 refs，并在后续确定性汇总需要时复用。`record_turn` 必须显式携带 Turn 开始日；同 ref、同 completion/output/exhausted 是幂等成功，同 ref 不同事实是 invariant conflict。跨日时必须先完成旧日 reconciliation，再把完整旧日目录归档。

SessionEngine 使用进程内可重入锁串行化同一实例的 preparation、completion、history 读取和 reconciliation。history 读取只观察最近一次提交状态；当前不提供跨进程锁，active Session 的支持运行模型是单进程写入，多进程同时提交同一 active 根不属于一致性保证范围。

归档后的 Session 还是同一组不可变 Turn/summary 事实。`SessionEngine.memory_facts(day, root)` 先复用 `archive_snapshot` 校验 manifest/graph，再按需递归可达 Summary 节点，并对每个叶子 Turn 复用同一 validator，只输出唯一叶子 Turn 的 `SessionMemoryFactsProjection`。每个 fact 使用首个 UserInput `received_at` 作为 Turn 开始时间，缺失时回退 record `recorded_at_ns`，并投影全部 UserInput 文本、最终 Working、Background 顶层 Links、最终 answer/references、已校验的有界 action 摘要、exhausted 和 trace digest；不输出 raw trace、trace heap、reasoning 或 provider payload。Projection 按开始时间和 ref 稳定排序，不同时交付 Summary 与其子 Turn。

Memory Maintenance 只消费上述 typed projection；Session 不解释 MEMORY 文档格式，不读取或写入 Agent Home/Memory，也不参与 Home runtime diff。目标 `memory/yyyy/mm/yyyy-mm-dd.md` 不存在时，Memory consolidator 只使用同日期 Session；目标已存在时，同时使用同日期旧 MEMORY 完整重写。任务中断后重新构造同一 projection 即可，不建立 memory candidate store。

启动自动提示只查询配置业务时区中的昨日，不扫描更早日期。Loop 通过 `DailyLifecycleCoordinator.session_archive_for(day)` 解释 transition 并定位 Session 根；Session 通过 `memory_facts(day, root)` 判断 projection 是否含事实，Memory 模块判断同日期目标是否存在。只有 archive 存在且 projection 非空才满足 Session 一侧 eligibility；App 不遍历 `transition.json`，Loop 不理解 Session store，“目录存在”不替代“存在可供提炼的已提交 Session 事实”的模块判断。

## 失败边界

Session 历史 owner/ref/kind/limit/cursor 可修正请求使用带稳定 reason/scope/constraint 的 `SessionHistoryRequestError`，Action executor 与 Endpoint 分别把它映射为局部 failure 和安全 `422`。其它公共契约仍使用 `SessionContractError`，持久化与归档失败使用 `SessionIOError`，内部状态破坏使用 `SessionInvariantError`；后三类不得被 history action 压平为普通 recall/actions failure。bridge 分别映射为 contract、I/O 和 internal failure，不把持久图损坏误报为调用方请求。跨模块边界统一经 `SessionFailureKind` 和 `RuntimeSessionBridge` 转为少量 Runtime 原因：启动配置/初始化失败结束 Program，Turn preparation/completion 及 action 期间的非局部失败结束当前 Turn。AppBuilder 只负责构建 Session、注入同一 Runtime bridge、注册 action 和安装 preparation/completion adapters，不读取或修改 Session 文件。
