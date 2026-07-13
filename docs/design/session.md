# Session 设计

## 定位

Session 是当日跨 Turn 会话历史的唯一持久化归属模块。它不维护当前 Turn 的可变执行状态，不参与 Phase 决策，也不直接调用 LLM。Context 负责当前 Turn 语境，Session 在 Turn 完成后接收不可变 `TurnCompletion`，在下一 Turn preparation 期间把有界历史头部投影为 `SessionBackground`。

Session 与 Workspace 一样具有日级生命周期，但二者保存不同事实：Workspace 保存 Agent 可操作资源；Session 保存用户 ask、Turn 内 reason/action/result 轨迹、最终 answer 和结束状态。Agent Home 仍负责经过沉淀的长期知识与记忆，Session 不是 Agent Home 的替代品。

## 持久模型

active Session 根目录包含：

```text
runtime/session/
  manifest.json
  turns/<turn_id>.json
  summaries/<summary_id>.json
```

`turns/` 中的完整 Turn record 是不可变事实，包含 TurnSummary、输出、exhausted 状态和用于恢复排序的 `recorded_at_ns`。Record schema 当前为 v2；v1 record 读取时以文件 mtime 补足排序时间。Manifest 只保存下一 Turn 可见的有界历史头部：`turn` item 或 `summary` item、背景投影、估算字符数及 child refs。近期 Turn 投影固定包含 ask、answer、结束状态和 trace digest；action 调用与结果由 Session 配置的 `background_action_names` allowlist 选择，默认只投影最多三个 `core.reason`，避免把所有工具结果复制进跨 Turn 背景。每个被投影 action 的参数与结果分别有界，完整内容仍只存在于 Turn record。summary record 保存被合并节点的完整头部和子引用，不删除原 Turn record，因此摘要是索引层压缩，不是事实层丢失。

Session 不读取 `date.today()`，也不拥有 archive root 配置。Program 在 work 边界传入唯一 `BusinessDay`；日切时 Loop coordinator 先要求 Session 完成 reconciliation，再把 active root 移到统一 pending archive 的 `session/`，最后与 Workspace 一起打开新日。Home 不参与这一 Business Day 事务。Manifest 和 record 使用稳定 JSON 与原子写入；day 不匹配、损坏或归档目标冲突显式失败，不静默重建。

## 摘要与渐进恢复

Session 的 `background_max_chars` 是跨 Turn 历史头部预算。当可见 item 估算超过 60% watermark 时，每次 Turn completion 最多执行一次确定性合并：保留至少 `min_recent_turns` 个最近 Turn，把更旧的连续前缀替换为一个 summary node。默认目标比例为 40%，为下一批 Turn 留出增长空间。若极端单条投影仍超过总预算，下一 Turn 只注入 overflow head，模型可通过 inspect action 获取完整索引。

恢复是分层、显式和有界的：

- `session.history.inspect` 返回当日 Manifest 头部及 `session:turn/...`、`session:summary/...` refs；
- `session.history.recall` 读取一个 Turn 或 summary record；summary 返回 child refs，Turn trace 使用 `cursor`、`next_cursor` 和 `truncated` 分页，允许继续向底部探索；调用方提供的 `max_chars` 不得突破 Session 配置上限；
- recall ActionResult 使用 foldable trace projection，当前 Cycle 可见完整结果，后续压缩折叠为 origin ref，避免历史召回递归放大当前 TurnTraceHeap。

## Turn 生命周期

1. `ContextEngine.begin_turn` 创建当前 Turn 状态并打开 preparation 窗口；
2. `SessionTurnPreparationHandler` 使用 Turn 开始日校验 active Manifest，产生唯一版本化 `context.session.sync`，位于 Home 默认 Background 重建之后、Workspace snapshot 之前；
3. Context 关闭 preparation 窗口后，SessionBackground 在整个 Turn 固定，Phase1 不能修改；
4. Turn 结束后 Context seal trace 并生成 TurnSummary；
5. `SessionTurnCompletionHandler` 先持久化完整 Turn record，再原子提交新 Manifest，必要时生成一个 summary node；
6. Session completion 失败经 RuntimeSessionBridge 映射，仍在原 Turn scope 进入 Trap。

## 幂等提交与 orphan reconciliation

Turn completion 使用“不可变 record 先行、Manifest 后提交”的顺序。Turn record 的幂等语义由 completion、output、exhausted 和兼容旧 schema 的 day 共同决定；background 是首次提交时按 Session 配置生成的派生投影，不参与重放身份，因此重启后调整投影配置不会把同一完成事实误判为冲突。相同 `session:turn/<turn_id>` 与相同语义内容重复提交时直接复用已有 record；若同一 ref 对应不同完成事实，则抛出 `SessionInvariantError`，不会覆盖先前事实。summary record 以 day 和有序 child refs 判断幂等。Manifest revision 只对新接入的 Turn 递增，完全相同的重放不改变 revision。

进程可能在 record 原子落盘后、Manifest 原子提交前退出，因此 record 存在而未从 Manifest 图可达是合法的可恢复中间态。Session 在加载现有 active root、preparation/completion 和显式归档前执行 reconciliation：递归校验 Manifest/summary 图的引用存在性、kind、background、char count、child refs、重复子节点和环；再按 `recorded_at_ns, ref` 的稳定顺序接入 orphan Turn。构造 Engine 不会隐式创建新日或隐式跨日搬迁；这些状态改变只能由 `initialize_day`/`archive_day` 触发。损坏的已提交图属于内部不变量失败，不静默重建。

summary id 由 day、schema 和有序 child refs 的 digest 确定。若生成 summary record 后 Manifest 提交失败，重试会复用同一 summary，而不会产生重复摘要。不可达 summary 不独立接入可见头部，因为它是派生索引而不是新的 Turn 事实；reconciliation 会报告这些 refs，并在后续确定性汇总需要时复用。`record_turn` 必须显式携带 Turn 开始日；同 ref、同 completion/output/exhausted 是幂等成功，同 ref 不同事实是 invariant conflict。跨日时必须先完成旧日 reconciliation，再把完整旧日目录归档。

SessionEngine 使用进程内可重入锁串行化同一实例的 preparation、completion、recall 和 reconciliation。当前不提供跨进程锁；active Session 的支持运行模型是单进程写入，多进程同时提交同一 active 根不属于一致性保证范围。

归档后的 Session 还是同一组不可变 Turn/summary 事实。Memory Maintenance 通过 Session 所有的只读归档入口按明确 Business Day 定位 records，并把它们交给 Agent Home consolidator；Session 不解释 MEMORY 文档格式、不读取或写入 Agent Home，也不参与 Home runtime diff。目标 MEMORY 不存在时，consolidator 只使用同日期 Session；目标已存在时，同时使用同日期旧 MEMORY 完整重写。任务中断后重新读取同一归档 Session 即可，不建立 memory candidate store。

启动自动提示只查询配置业务时区中的昨日 Session archive 是否存在，不扫描更早日期。Loop 当前通过 `DailyLifecycleCoordinator.session_archive_for(day)` 解释 transition 并定位 Session 根；Session 通过 `archive_snapshot(day, root)` 只读校验 manifest/graph 并返回有界 history head。App 不遍历 `transition.json`，Loop 不理解 Session store；“目录存在”不替代“存在可供提炼的已提交 Session 事实”的模块判断。

## 失败边界

Session 参数和 ref 不合规使用 `SessionContractError`，持久化与归档失败使用 `SessionIOError`，内部状态破坏使用 `SessionInvariantError`。bridge 分别映射为 contract、I/O 和 internal failure，不把持久图损坏误报为调用方契约错误。跨模块边界统一经 `SessionFailureKind` 和 `RuntimeSessionBridge` 转为少量 Runtime 原因：启动配置/初始化失败结束 Program，Turn preparation/completion 期间失败结束当前 Turn。AppBuilder 只负责构建 Session、注册 action 和安装 preparation/completion adapters，不读取或修改 Session 文件。
