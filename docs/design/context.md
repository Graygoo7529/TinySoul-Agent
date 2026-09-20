# Context 设计

内部 segments 区分段协议、注册声明与活动集合；builtin 提供内核自有 Inputs/Trace/Working，projection 负责组合与引用路由，control 负责模型侧控制意图。外部段由所属插件维护，目录分层不改变 ContextEngine 的单一消费入口。

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

Session provider 在段 open 时读取固定的历史事实集合；模型投影只在 Session 自身超过水位时折叠，保留地图入口与全部事实引用，Context 不能任意削减它。通用 Background 每 Turn 重建；默认 Home 条目、按需加载的 Top Link 和 Memory 动态投影都属于当前 Turn。User/Home Reflection 装配不可逐出的 `memory:current + optional memory:latest`，Memory Reflection 装配不可逐出的 `memory:target + optional memory:latest`；latest 是严格早于 Context 活动日期的最近 daily，缺失时省略。Background catalog 只提供有界 Link、title 和 description，不等同于已加载正文。

WorkingContext 维护 plan，只向模型呈现 milestones 与 todos，不持有 Workspace 快照。Milestone 是少量、可复用的事实寄存器：可以记录有价值的完成、尝试、失败、阻塞、测量值、决定、来源 Link、版本/digest 或局部成果，供后续 Cycle 防止遗忘；它不是 todo 的镜像、进度徽章或对模型的自我确认。失败或仅尝试过的工作必须明确记录其状态，不能登记为完成事实。Workspace 段只呈现 resource Link/summary；Workspace 不保存 revision 或内容 CAS；Session 的 continuation 等有消费者的独立协议仍由各自 owner 解释。

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

模型通过 `core.context.inspect` 检查段声明的 ref。Stack、Map、State 表达不同内容语义；渐进披露是访问方式，不把它们强行改成同一种数据形状。Trace 与 Session 共用 `DisclosureHint`、`DisclosurePage` 和既有 continuation 基础设施；owner 决定分组、关系和事实内容，公共构件只负责有界投影与分页。

Trace 的根同时提供冷节点与热记录线索，分支给出直接子节点，叶组给出稳定 entry ref，再沿 entry ref 读取语义详情。折叠和父节点合并不改变已返回引用。根、分支、关系和长叶子均分页；正文不会被静默裁掉。公开内容只表达决策、行动、结果、必要反馈和来源，不要求模型理解内部序号、存储版本或完整性校验。

可选 query 只搜索给定 ref 下的原始语义内容，按 owner 事实顺序返回有界摘录与精确 ref。Trace 排除 inspect 自身的重复请求和返回；查询不展开整段、不隐式加载正文，也不调用 LLM。QUERY 是独立声明的能力；只读归档 Workspace 等未声明该能力的 owner 返回局部不支持结果。

统一披露页以有序 items 交付详情、child 线索、关系或来源。continuation 绑定 owner、ref、query 和当前读取视图；视图变化使旧 token 明确失效，不静默混页。内部绑定信息只在 opaque token 中由基础设施解释。

inspect 的完整可见结果必须先进入一次实际返回的 Phase1/Phase2 模型请求，之后才允许压力回收其 overlay。compose 纯渲染、Action 内部模型调用以及容量拒绝都不能解除保护；受保护结果所在区间也不能被折入冷节点。折叠后保留 origin ref，可重新读取，不提供独立 recall 或 fold Action。

## Turn Completion

`end_turn()` 产生 typed immutable `ContextTurnCompletion`，包含 Turn identity、有序输入文本与原始接收时间、plan 终态、Background links、按 id 标识的段快照和 `SealedTurnTrace`。Sealed trace 保存 canonical entries、类型化 Action 执行事实和只存引用的时间线，不携带 heap topology。输入保留 Inbox 的受理顺序，时间线另记安装和合并可见位置；Action 请求、开始和结算按实际回调记录，不能从批次结果排序反推。环境/Job 交付、必要 phase note 与已安装 plan patch 通过现有 Signal 批次记录。

该对象只在唯一 Loop completion pipeline 中传递。Session 在自身边界投影为 v10 业务记录：输入与行动正文各存一处，时间线引用它们，必要语义 note 单独保存；不从消息布局猜测 call/result 配对。时间线表达 owner 观察与提交顺序，不声称外部因果时间。Context 不生成持久 Summary、平行日志或崩溃续跑协议。

## 失败边界

无效 ref/continuation 是可修正的 `context.inspect` 局部 Action failure。Context 配置、资源准备或内部不变量失败经 RuntimeContextBridge 改变当前 Turn 控制流。Context 自身预算不足使用 Context-owned 恢复原因，LLM 容量不足使用独立 LLM 原因；User/Reflection 装配将两者接入各自压力策略。恢复有进展才重放可重建的 Task，否则结束 Turn，不为不同模型生成不同 MessageStack。Context bridge 位于自身 runtime_bridge.py，捕获的 Context signal batch 在 Module 重试中保持同一批次，不重新取队列。

## 插件装配

Turn Context 先由内核根据 `ContextSettings` 构造核心段。Home、Memory、Session、Workspace 和 Job 以显式 `PluginDeclaration` 提供服务、段和动作贡献；`PluginRegistry` 在安装前校验服务唯一性、依赖顺序以及段 id、ref 和 signal 路由。解析失败不会部分安装，激活只发生一次。实际注入的是 owner 定义的受约束 async Service，Action、背景 provider 与 Skill provider 使用同一实例；不在注册窄接口后闭包捕获完整 Engine。纯渲染只读已安装视图，文件读取和网络检索分别使用 joined 本地操作与原生 async。段 provider 仍只创建当前 Turn 的视图，Engine 服务跨 Turn 持有领域事实。
