# Context 设计

## 定位

Context 拥有一个活动 Turn 的模型语境。它持有 User Inputs、固定 Session Background、通用 Background、WorkingContext 与 TurnTraceHeap，并按稳定顺序构造 MessageStack。Context 不拥有跨 Turn 历史、Workspace 文件、Home 内容或 Memory 文件；这些模块只通过明确的 provider、snapshot 或 signal 协议向 Context 投影。

## MessageStack

MessageStack 顺序固定为：

1. system identity；
2. 当前 Turn 的有序 User Inputs；
3. Session Background；
4. Home、Memory 等通用 Background；
5. TurnTraceHeap 当前可见内容；
6. WorkingContext 当前快照；
7. 当前 LLM Task 的 prompt overlay。

除 system identity 外，框架构造的语境使用 user role；TinySoul ToolResult 仍按内部工具消息语义表达，并由 provider adapter 决定供应商协议映射。前端在 model Observation 中看到的 MessageStack 就是实际交给 LLM 层的构造结果，不另建 Context REST snapshot。

## Background 与 Working

Session Background 只在 Turn preparation 期间通过版本化全量 signal 注入，在该 Turn 内固定且不可逐出。通用 Background 每 Turn 重建；默认 Home 条目、按需加载的 Top Link 和 Memory 动态投影都属于当前 Turn。User/Home Maintenance 装配不可逐出的 `memory:current + optional memory:latest`，Memory Maintenance 装配不可逐出的 `memory:target + optional memory:latest`；latest 是严格早于 Context Business Day 的最近 daily，缺失时省略。Background catalog 只提供有界 Link、title 和 description，不等同于已加载正文。

WorkingContext 是原位替换的当前快照，只向模型呈现 milestones、todos 与 Workspace resource Link/summary。Milestone 是少量、可复用的事实寄存器：可以记录有价值的完成、尝试、失败、阻塞、测量值、决定、来源 Link、版本/digest 或局部成果，供后续 Cycle 防止遗忘；它不是 todo 的镜像、进度徽章或对模型的自我确认。失败或仅尝试过的工作必须明确记录其状态，不能登记为完成事实。典型事实包括已计算的平均值、正在编辑的文档 Link/当前范围/digest、权威网址，或某次写入在已知边界失败。只有事实发生变化时才更新。Workspace revision、digest 和 Context 内部同步标识不进入模型投影。

所有 Context 变更先从 SignalBus 捕获当前 Turn 的作用域化批次，再完成解析、资源准备和整体校验，最后一次提交。失败不得留下半提交状态。

## TurnTraceHeap

TurnTraceHeap 是当前 Turn 的 append-only 运行事实：

- hot entries 直接进入 MessageStack；
- 压力回收先折叠 foldable ActionResult 的完整 visible overlay；
- 再按完整 Cycle 把较旧 hot entries 移入 immutable leaf；
- leaf 按 branch factor 合并为多层 branch；
- MessageStack 只保留 heap head 与剩余 hot entries。

压缩不删除 canonical entry，也不把已展开内容复制为第二份热历史。heap topology、node id 和压缩布局只在当前 Context 生命周期内存在，不写入 Session。

### 渐进检查

模型只通过 `core.context.inspect` 检查当前 Turn 的冷轨迹：

- head ref 返回直接 root headers；
- branch ref 返回直接 child headers；
- leaf ref 返回按原顺序投影的语义 interactions；
- leaf 内容超出 owner 字符上限时，响应携带 `next_continuation`。

公开 header 只保留 ref、kind、直接 child/interaction count、interaction kinds 与 Action names。leaf 只呈现 decision、Action request、Action outcome/result/failure、references 和必要 phase note，不呈现 entry/call id、cycle、phase、trace index、digest、revision 或 pager 实现字段。

`ref` 选择节点；`continuation` 只继续同一节点尚未交付完的直接内容。continuation 是 owner/action/ref-bound 的 opaque token，模型只能原样回传。无效或过期 token 反馈重新检查当前 ref，不解释其内部位置、digest 或 revision。

`core.context.inspect` 是 foldable Action：完整结果和 continuation 只在当前 Interaction 可见，后续压力回收只保留已检查的 origin ref。需要继续时从该 ref 重新检查。Context 不提供独立 recall 或显式 fold Action。

## Turn Completion

`end_turn()` 产生 typed immutable `ContextTurnCompletion`，包含 Turn identity、有序输入文本与接收时间、Working 终态、Background links 和 `SealedTurnTrace`。Sealed trace 只含 turn id 与有序 canonical entries，不携带 heap topology。

该对象只在 Loop completion pipeline 中传递。Session 在自己的提交边界验证 Action call/result 一一配对并投影 v4 业务记录；Context 不生成持久 `TurnSummary`、trace digest 或 JSON canonical trace。Session 提交后也不保留当前 Turn trace。

## 失败边界

无效 ref/continuation 是可修正的 `context.inspect` 局部 Action failure。Context 配置、资源准备或内部不变量失败经 RuntimeContextBridge 改变当前 Turn 控制流。LLM 上下文超硬水位触发既有压力恢复与完整 Task 重建，不为不同模型生成不同 MessageStack。
