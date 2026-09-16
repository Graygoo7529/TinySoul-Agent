# Context 设计

## 定位

Context 拥有一个活动 Turn 的模型语境。内核维护 User Inputs、plan 与 TurnTraceHeap；Workspace 与 Session 通过独立注册段维护本轮资源投影和固定历史视图。Home/Memory 的目录、加载视图和刷新也属于各自的 Heap 段。Context 不拥有跨 Turn 历史、Workspace 文件、Home 内容或 Memory 文件。

## MessageStack

Composer 只接收带段描述的消息投影，按 Background → Trace → Working 槽位、段 order 和 id 排序，最后附加 TaskPrompt。当前装配顺序为：

1. system identity；
2. Session Background；
3. 当前 Turn 的有序 User Inputs；
4. Home、Memory 等通用 Background；
5. TurnTraceHeap 当前可见内容；
6. plan 的 milestones/todos，以及独立 workspace 段的资源摘要；
7. 当前 LLM Task 的 prompt overlay。

除 system identity 外，框架构造的语境使用 user role；TinySoul ToolResult 仍按内部工具消息语义表达，并由 provider adapter 决定供应商协议映射。前端在 model Observation 中看到的 MessageStack 就是实际交给 LLM 层的构造结果，不另建 Context REST snapshot。

## Background 与 Working

Session provider 在段 open 时读取历史视图，在该 Turn 内固定且不可逐出。通用 Background 每 Turn 重建；默认 Home 条目、按需加载的 Top Link 和 Memory 动态投影都属于当前 Turn。User/Home Reflection 装配不可逐出的 `memory:current + optional memory:latest`，Memory Reflection 装配不可逐出的 `memory:target + optional memory:latest`；latest 是严格早于 Context Business Day 的最近 daily，缺失时省略。Background catalog 只提供有界 Link、title 和 description，不等同于已加载正文。

WorkingContext 维护 plan，只向模型呈现 milestones 与 todos，不持有 Workspace 快照。Milestone 是少量、可复用的事实寄存器：可以记录有价值的完成、尝试、失败、阻塞、测量值、决定、来源 Link、版本/digest 或局部成果，供后续 Cycle 防止遗忘；它不是 todo 的镜像、进度徽章或对模型的自我确认。失败或仅尝试过的工作必须明确记录其状态，不能登记为完成事实。Workspace 段只呈现 resource Link/summary；revision 等 owner 一致性字段不进入模型投影。

Context 更新从 SignalBus 捕获当前 Turn 的固定批次；解析、候选校验、背景读取和注册段的 prepare 全部结束后才安装。准备入口和批次消费均为 async；短背景读取使用 joined owner 操作，取消时等待读取结束且不安装候选。默认背景的 catalog、provider 索引和正文也先完整准备，再一起安装，不在加载失败前暴露部分新目录。恢复信号以独立固定批次由内核提交，不从 Trap handler 直接修改视图。Home 顶层变更和活动 Memory 写入先提交 owner，再通知本轮段刷新；刷新只替换本轮目录与已加载内容，不自动内联新资源。

## 注册段

SegmentRegistry 在装配时校验段 id、更新路由唯一性与 ref 前缀不重叠。描述统一声明 owner、slot、order、shape、能力与可选 ref 路由；provider 每 Turn 创建实例。只读段不注册空的更新通道，声明 ref 路由的段必须提供真实 inspect 能力。已注册的更新信号在注册边界解码为 owner 的具体类型，再交给该段 prepare，异构调度不把内部候选退化为任意 JSON。identity、inputs、trace、plan、固定 journal、Home、Memory、Session 和 Workspace 都通过同一生命周期注册。Turn 内核必经 open，不要求外部装配重复添加 Context preparation handler；每个新 Turn 都创建新视图。统一 core.context.inspect 路由到声明 ref 的 Trace、Session 或只读归档 Workspace；选择能力提供当前可加载/已加载/受保护 ref，Heap 的加载/逐出和 owner 刷新使用相同 prepare/install。shape 按 State → Heap → Stack → Map 参与回收顺序，仅调用声明了 reclaim 的段，保留受保护默认内容。profile 贡献经 PluginRegistry 校验与激活；需要持久提交的 owner 使用 Turn 完成管线，不在纯段 prepare 中提交业务事实。

prepare 不改变活动视图或持久事实；全部候选准备成功才同步 install。候选只属于准备它的 Turn 且只能安装一次。安装缺陷使段集合停止接受后续更新和渲染，不回滚业务副作用或重放已安装候选。渲染只读已安装视图；seal 返回以 segment id 标识的 JSON 快照，不解释领域 owner 内容。核心 inputs/plan/trace 通过类型化 ContextTurnCompletion 交付业务事实，持久段快照不再重复保存同一核心事实。

部分 open 失败关闭已经交出的视图；尚未交出的资源由 provider 自行回收。Turn 在必要 finish 后逆序 close 段，连续取消仍等待清理完成。close 不关闭跨 Turn Engine，不再次提交 Session；失败成为独立有限诊断。

## TurnTraceHeap

TurnTraceHeap 是当前 Turn 的 append-only 运行事实：

- hot entries 直接进入 MessageStack；
- 压力回收先折叠 foldable ActionResult 的完整 visible overlay；
- 再按完整 Cycle 把较旧 hot entries 移入 immutable leaf；
- leaf 按 branch factor 合并为多层 branch；
- MessageStack 只保留 heap head 与剩余 hot entries。

压缩不删除 canonical entry，也不把已展开内容复制为第二份热历史。heap topology、node id 和压缩布局只在当前 Context 生命周期内存在，不写入 Session。

### 渐进检查

模型通过 `core.context.inspect` 检查段声明的 ref。Trace 段负责当前 Turn 冷轨迹：

- head ref 返回直接 root headers；
- branch ref 返回直接 child headers；
- leaf ref 返回按原顺序投影的语义 interactions；
- leaf 内容超出 owner 字符上限时，响应携带 `next_continuation`。

公开 header 只保留 ref、kind、直接 child/interaction count、interaction kinds 与 Action names。leaf 只呈现 decision、Action request、Action outcome/result/failure、references 和必要 phase note，不呈现 entry/call id、cycle、phase、trace index、digest、revision 或 pager 实现字段。

`ref` 选择节点；`continuation` 只继续同一节点尚未交付完的直接内容。continuation 是 owner/action/ref-bound 的 opaque token，模型只能原样回传。无效或过期 token 反馈重新检查当前 ref，不解释其内部位置、digest 或 revision。

`core.context.inspect` 是 foldable Action：完整结果和 continuation 只在当前 Interaction 可见，后续压力回收只保留已检查的 origin ref。需要继续时从该 ref 重新检查。Context 不提供独立 recall 或显式 fold Action。

## Turn Completion

`end_turn()` 产生 typed immutable `ContextTurnCompletion`，包含 Turn identity、有序输入文本与接收时间、plan 终态、Background links、按 id 标识的段快照和 `SealedTurnTrace`。Sealed trace 保存 turn id、有序 canonical entries 及类型化 Action 执行事实，不携带 heap topology。

该对象只在 Loop completion pipeline 中传递。Session 在自己的提交边界直接投影类型化 Action 事实及 Turn 终态为 v8 业务记录，保留段快照，不从模型消息猜测 call/result 配对；Context 不生成持久 `TurnSummary`、trace digest 或 JSON canonical trace。Session 提交后也不保留当前 Turn trace。

## 失败边界

无效 ref/continuation 是可修正的 `context.inspect` 局部 Action failure。Context 配置、资源准备或内部不变量失败经 RuntimeContextBridge 改变当前 Turn 控制流。Context 自身预算不足使用 Context-owned 恢复原因，LLM 容量不足使用独立 LLM 原因；User/Reflection 装配将两者接入各自压力策略。恢复有进展才重放可重建的 Task，否则结束 Turn，不为不同模型生成不同 MessageStack。Context bridge 位于自身 runtime_bridge.py，捕获的 Context signal batch 在 Module 重试中保持同一批次，不重新取队列。

## 插件装配

Turn Context 先由内核根据 `ContextSettings` 构造核心段。Home、Memory、Session、Workspace 和 Job 以显式 `PluginDeclaration` 提供服务、段和动作贡献；`PluginRegistry` 在安装前校验服务唯一性、依赖顺序以及段 id、ref 和 signal 路由。解析失败不会部分安装，激活只发生一次。段 provider 仍只创建当前 Turn 的视图，Engine 服务跨 Turn 持有领域事实。
