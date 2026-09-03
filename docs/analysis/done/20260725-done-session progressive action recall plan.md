# Session 渐进式 Action 召回执行计划

## 意图

Session Background 应提供足以延续对话的 prior-Turn ask、answer、references 和 Action outcome，但不应让模型理解 canonical trace 的物理位置、call/result 配对索引或执行框架字段。模型需要历史 Action 细节时，应从 Background 已暴露的 Session ref 开始，沿 Session-owned 导航节点逐层 inspect，并用 owner 签发的 leaf ref recall 一次语义化 Action request/result。

本轮不改变 schema v3 Turn/Summary record、canonical trace、完整性 validator、Memory facts 或 Endpoint Session Explorer 的详细 history/actions/trace 协议。内部 `TurnActionProjection` 继续是 call/result 配对和所有派生视图的唯一来源。

## 已确认语义

- 模型侧 Session Domain 只保留 `session.history.inspect` 与 `session.history.recall`，删除 `session.history.actions`；
- 自动 Turn Background 使用一个 `session:turn/<turn_id>#actions` 虚拟集合 ref 包装按 Action 聚合且只保留非零项的 outcome counts；
- inspect 从 head、Summary、Turn 渐进展开到 Action 集合，再签发 `session:turn/<turn_id>#action/<occurrence>` leaf ref；Action 集合允许用 Background 已出现的 Action 名称过滤；
- 虚拟 ref 从已校验 immutable Turn 确定性派生，不落盘、不进入 Manifest、不建立新 SessionRecord；模型只能复制 ref 和 continuation，不能解释或构造后缀；
- recall 只接受 Action leaf ref，返回 Action schema request、outcome、canonical result/references 或简化 failure；entry index、call/result trace index、call id、cycle id、历史 stage 和 pairing 实现细节保持内部透明；
- inspect/recall 成功结果均为 foldable；当前 Turn 的历史查询进入 Interaction，后续只持久紧凑 origin ref/continuation；
- 当前 active Turn 仍由 Context trace heap 管理，Session 只读取已完成 prior Turn；Endpoint 继续提供详细 actions/trace 供前端诊断，不把其结构回灌模型。

## 执行项

- [x] 增加 Session Action collection/occurrence 虚拟 ref 解析和语义投影；
- [x] 增加模型专用 inspect/recall 查询，同时保留 Endpoint 详细查询；
- [x] 清理自动 Background outcome 结构，移除零计数和默认空字段；
- [x] 删除模型侧 `session.history.actions`，更新 Catalog 和 Session Domain HOW；
- [x] 覆盖 ref 稳定性、Action 过滤、成功/失败 recall、foldable 生命周期和 Endpoint 无回归测试；
- [x] 同步 AGENT、Session/Action/Endpoint 设计文档并完成全量测试、类型检查与 wheel 验收。

## 完成结果

Session 已以已校验 Turn record 为唯一事实源，确定性派生 Action collection/occurrence 虚拟 ref；模型侧只保留 compact inspect 与 semantic recall，自动 Background 不再暴露 trace 位置和配对实现细节。Endpoint 详细 actions/trace 协议及持久 schema v3 均未改变。

全量测试、Session/Endpoint/Action/Loop 定向测试、类型检查、compileall 与 clean-source wheel 验收均已通过；仅保留测试依赖 Starlette/httpx 组合产生的既有弃用警告。
