# Session 设计

## 定位

Session 拥有同一 business day 内已完成 User Turns 的不可变业务事实。固定的 prior-Turn 语境、基础事实 Map、渐进检查和 Memory evidence 都从同一组 Turn records 派生；不保存活动 Turn 的运行轨迹，不承担前端审计日志职责。

## 持久事实与恢复

Turn record 使用 schema v8，保存有序用户输入、plan 终态、Background links、owner 段快照、正式输出及来源、类型化终态、执行失败、必要 finish 失败和有序 Action 事实。输入保留稳定 input_id 与 reply_to，问题来自同一 core.ask Action 事实，回复正文只保存在输入中；inputs 段快照只引用身份。取消与等待用户超时分别记为 cancelled 与 awaiting_user。Session 段自己的快照只保存来源日、revision 和 Turn refs，避免将历史正文递归复制进后续记录。不静默迁移旧 schema。

Action 事实直接来自 sealed Trace。success、failed、timeout 保存已知 canonical result 或局部失败；cancelled、not_executed、unknown 保留实际执行事实，不伪造工具结果。Action 身份配对、状态转移与发生顺序由 Trace 校验，Session 不从模型消息猜测执行状态。

Manifest schema v3 只索引该日的有序 Turn refs 与内部 revision。没有 Summary records、Summary 树、压缩阈值或平行关系日志。当前 record/manifest 均严格校验字段和版本，不读取或自动迁移旧 schema。

Store 对同 ref 的相同业务事实幂等复用，recorded time 不参与比较；同身份内容冲突属于不变量失败。Reconciliation 校验日期、缺失或重复引用，按写入时间和 ref 收养“record 已原子写入、manifest 尚未提交”的孤立 Turn。Archive 使用同一验证入口。

## Turn 视图与基础 Map

Session provider 在每个 Turn 的段 open 中，通过 joined owner 读取建立独立固定视图。Background 显示有界的最近问答、执行终态、失败摘要和 Action 集合入口；字符预算不足时保留可容纳的连续最近后缀，并提供 `session:map`。背景不展示内部 revision、digest、调用身份或完整 Action result。

基础 Map 由不可变事实确定性派生：

- Turn 节点保存有界问答和 Action outcomes；
- Action 节点使用 Turn 内的 occurrence ref，区分同名重复调用；
- resource 节点复用完成输出和 Action 明确保存的 references；
- precedes 表达 Turn 提交顺序，contains 表达 Turn 所含 Action，references 表达记录中的显式引用。

所有关系标记为 fact，不从文本猜测语义关系，也不把推断当作执行事实。当前没有模型整理或关系编辑接口；这部分仍在后续 Session 整理范围内。

## 渐进检查

模型通过统一 `core.context.inspect` 进入段声明的 `session:` 路由：

- `session:map` 分页返回事实节点和关系；
- Turn ref 返回问答、终态、失败和 Action 集合入口；
- `#actions` 返回按发生顺序排列的有界 Action headers；
- `#action/<occurrence>` 返回一次调用的请求与已知结果或中断事实。

集合和叶子身份从原始 Turn records 派生，不单独落盘。超长对象使用 opaque continuation；Map 分页绑定 manifest revision，Action 集合分页绑定过滤条件。来源版本在固定 Turn 视图期间发生变化属于契约失败，不能静默混入后来完成的 Turn。单次检查不会改写固定 Background。

`core.context.inspect` 的完整输出只进入当前交互，压力回收后保留来源 ref 与精简 canonical payload。不存在独立的 Session inspect Action 或兼容入口。

## 完成与 Memory

Session completion 位于必要 finish 的最后，通过 joined owner 边界等待实际本地提交。执行或前置 finish 失败仍记录已知事实，但不发布回答候选为正式输出。Session 自身提交失败由 Turn 报告；后续 close 失败只追加诊断，不二次提交。

活动 `Memory.md` 位于 Session root，但始终由 Memory owner 解释和维护。确定性日切将校验后的 Session 根整体归档。Memory facts 从同一 Turn 索引投影，按输入开始时间和 ref 排序，交付完整业务事实，不交付运行时 trace 或第二份历史账本。

## 失败边界

错误 ref、未知节点或失效 continuation 是可修正的局部检查失败，由 Session 段映射为 Context 检查协议。持久化 I/O、损坏索引、固定视图版本冲突等模块失败经 RuntimeSessionBridge 转换，不能成为模型可重试的普通结果。配置拒绝未知键，字符预算由 owner 控制。
