# Session 设计


## 内部组织

records 封装不可变记录、校验、存储与 reconcile；views 从这些事实派生背景、导航和 Memory 来源。Engine/Service 提供唯一公共访问，completion 负责 Turn 收尾记录。不另存图正文或平行线性 Summary；模型主动 organize 与推导注释尚未实现，也没有预留空动作。
## 定位

Session 拥有同一 business day 内已完成 User Turns 的不可变业务事实。固定的 prior-Turn 语境、基础事实 Map、渐进检查和 Memory evidence 都从同一组 Turn records 派生；不保存活动 Turn 的运行轨迹，不承担前端审计日志职责。

## 持久事实与恢复

Turn record 使用 schema v9，保存有序用户输入、plan 终态、Background links、owner 段快照、正式输出及来源、类型化终态、执行失败、必要 finish 失败和有序 Action 事实。输入保留稳定 input_id 与 reply_to；Action 保存结果身份，使回复能确定性连回成功的 core.ask。回复正文只保存在输入中；inputs 段快照只引用身份。取消与等待用户超时分别记为 cancelled 与 awaiting_user。Session 段自己的快照只保存来源日、revision 和 Turn refs，避免将历史正文递归复制进后续记录。不静默迁移旧 schema。

Action 事实直接来自 sealed Trace。success、failed、timeout 保存已知 canonical result 或局部失败；cancelled、not_executed、unknown 保留实际执行事实，不伪造工具结果。Action 身份配对、状态转移与发生顺序由 Trace 校验，Session 不从模型消息猜测执行状态。

Manifest schema v3 只索引该日的有序 Turn refs 与内部 revision。没有 Summary records、Summary 树、压缩阈值或平行关系日志。当前 record/manifest 均严格校验字段和版本，不读取或自动迁移旧 schema。

Store 对同 ref 的相同业务事实幂等复用，recorded time 不参与比较；同身份内容冲突属于不变量失败。Reconciliation 校验日期、缺失或重复引用，按写入时间和 ref 收养“record 已原子写入、manifest 尚未提交”的孤立 Turn。Archive 使用同一验证入口。

## Turn 视图与基础 Map

Session provider 在每个 Turn 的段 open 中，通过 joined owner 读取建立独立固定视图。Background 始终提供 `session:map`，注明来源日、总 Turn 数、当前投影数与省略数。字符预算不足时只保留可容纳的连续最近后缀，问答摘录明确标记不完整；最低地图入口仍超预算则报告容量失败。背景不展示内部 revision、digest、调用身份或完整 Action result。

基础 Map 由不可变事实确定性派生：

- Turn 节点保存来源日、终态、有界问答和 Action outcomes；
- Action 节点使用 Turn 内的 occurrence ref，区分同名重复调用；
- 输入、输出、Working 与 resource 节点使用记录内 ref；resource 复用 Background、完成输出与 Action 明确保存的 references，Workspace 引用携带来源日；
- precedes 表达 Turn 提交顺序、输入顺序与 Action 顺序，contains 表达记录包含关系，replies_to 连回明确追问，references 表达记录中的显式引用。不推测输入与 Action 之间缺乏事实依据的交错顺序。

所有关系标记为 fact，不从文本猜测语义关系，也不把推断当作执行事实。当前没有模型整理或关系编辑接口；这部分仍在后续 Session 整理范围内。

## 渐进检查

模型通过统一 `core.context.inspect` 进入段声明的 `session:` 路由：

- `session:map` 分页返回事实节点和关系；
- Turn ref 返回问答、终态、失败和 Action 集合入口；
- `#actions` 返回按发生顺序排列的有界 Action headers；
- `#action/<occurrence>` 返回一次调用的请求与已知结果或中断事实。
- `#input/<occurrence>`、`#output`、`#working` 展开对应记录内容；`#resource/<occurrence>` 返回资源身份和来源日，不读取当天同名文件。

集合和叶子身份从原始 Turn records 派生，不单独落盘。SessionView 固定 manifest 来源集合，按 ref 读取不可变记录，不复制另一份历史正文；当前日和归档日共用该只读查询实现，归档查询不会创建可写 Engine 或 reconcile 归档。超长对象使用 opaque continuation，绑定来源日、manifest revision 与过滤条件。随后完成的 Turn 不进入既有视图，也不会使该视图失效。单次检查不会改写固定 Background。

`core.context.inspect` 的完整输出只进入当前交互，压力回收后保留来源 ref 与精简 canonical payload。不存在独立的 Session inspect Action 或兼容入口。

## 完成与 Memory

Session completion 位于必要 finish 的最后，通过 joined owner 边界等待实际本地提交。执行或前置 finish 失败仍记录已知事实，但不发布回答候选为正式输出。Session 自身提交失败由 Turn 报告；后续 close 失败只追加诊断，不二次提交。

活动 `Memory.md` 位于 Session root，但始终由 Memory owner 解释和维护。确定性日切将校验后的 Session 根整体归档。Memory facts 从同一 Turn 索引投影，按输入开始时间和 ref 排序，交付完整业务事实，不交付运行时 trace 或第二份历史账本。

## 失败边界

错误 ref、未知节点或失效 continuation 是可修正的局部检查失败，由 Session 段映射为 Context 检查协议。持久化 I/O、损坏索引、固定视图版本冲突等模块失败经 RuntimeSessionBridge 转换，不能成为模型可重试的普通结果。配置拒绝未知键，字符预算由 owner 控制。

## 异步读取边界

SessionService 只暴露已完成事实的背景投影与渐进检查；读取通过 joined owner 操作，SDK 服务绑定世代和业务日。当前 Turn 的完成记录仍由 owner completion handler 提交，User 服务不提供 record_turn 或日生命周期入口。段与 SDK 使用同一只读服务，不复制另一份历史事实。内部 records 负责不可变记录、提交与 reconcile，views 负责 Map、Background、检查和 Memory 来源投影；Engine 组合它们并拥有日生命周期。
