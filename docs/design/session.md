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

`turns/` 中的完整 Turn record 是不可变事实，包含 TurnSummary、输出和 exhausted 状态。Manifest 只保存下一 Turn 可见的有界历史头部：`turn` item 或 `summary` item、背景投影、估算字符数及 child refs。summary record 保存被合并节点的完整头部和子引用，不删除原 Turn record，因此摘要是索引层压缩，不是事实层丢失。

进程跨日时，active 根目录原子移动到 `archive_root/<yyyy-mm-dd>`，然后创建新日 Manifest。Manifest 和 record 使用稳定 JSON 与原子写入；损坏或归档目标冲突显式失败，不静默重建。

## 摘要与渐进恢复

Session 的 `background_max_chars` 是跨 Turn 历史头部预算。当可见 item 估算超过 60% watermark 时，每次 Turn completion 最多执行一次确定性合并：保留至少 `min_recent_turns` 个最近 Turn，把更旧的连续前缀替换为一个 summary node。默认目标比例为 40%，为下一批 Turn 留出增长空间。若极端单条投影仍超过总预算，下一 Turn 只注入 overflow head，模型可通过 inspect action 获取完整索引。

恢复是分层、显式和有界的：

- `session.history.inspect` 返回当日 Manifest 头部及 `session:turn/...`、`session:summary/...` refs；
- `session.history.recall` 读取一个 Turn 或 summary record；summary 返回 child refs，允许继续向底部探索；
- recall ActionResult 使用 foldable trace projection，当前 Cycle 可见完整结果，后续压缩折叠为 origin ref，避免历史召回递归放大当前 TurnTraceHeap。

## Turn 生命周期

1. `ContextEngine.begin_turn` 创建当前 Turn 状态并打开 preparation 窗口；
2. `SessionTurnPreparationHandler` 产生唯一版本化 `context.session.sync`，先于 Workspace snapshot 提交；
3. Context 关闭 preparation 窗口后，SessionBackground 在整个 Turn 固定，Phase1 不能修改；
4. Turn 结束后 Context seal trace 并生成 TurnSummary；
5. `SessionTurnCompletionHandler` 先持久化完整 Turn record，再原子提交新 Manifest，必要时生成一个 summary node；
6. Session completion 失败经 RuntimeSessionBridge 映射，仍在原 Turn scope 进入 Trap。

## 失败边界

Session 参数和 ref 不合规使用 `SessionContractError`，持久化与归档失败使用 `SessionIOError`，内部状态破坏使用 `SessionInvariantError`。跨模块边界统一经 `SessionFailureKind` 和 `RuntimeSessionBridge` 转为少量 Runtime 原因：启动配置/初始化失败结束 Program，Turn preparation/completion 期间失败结束当前 Turn。AppBuilder 只负责构建 Session、注册 action 和安装 preparation/completion adapters，不读取或修改 Session 文件。
