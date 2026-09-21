# Session 设计

## 定位与内部组织

Session 拥有同一 CalendarDay 内已完成 User Turns 的不可变业务事实，以及有来源、可修订的会话理解。records 封装事实与恢复，annotations 封装语义节点、关系和原子变更，views 从两者派生地图、线性交互和渐进读取。Engine 是唯一 owner，Service 提供按权限划分的异步门面；不另存森林、交互副本或平行摘要日志。

Session Map 的事实列表、语义解释和话题森林是同一组内容的不同职责。森林是有界导航投影，底层关系可共享或形成回路；一个 Turn 可属于多个话题，不设置唯一主要话题。Session 不承担通用运行日志、前端审计库或跨日语义地图职责。

## 不可变事实与完成

唯一 Turn completion 管线从 typed Trace 保存原始输入、追加与回复、plan 终态、来源 Link、段快照、正式输出、执行状态和必要反馈。时间线记录输入安装/可见、Action 请求/开始/结算及交付事件的 owner 观察顺序；受理顺序单独保留，不把并行结算顺序当作请求顺序或外部因果时间。

输入身份与 reply_to 可精确连回成功的 core.ask；行动使用请求登记次序的 occurrence ref。success/failed/timeout 保存 canonical result，cancelled/not_executed/unknown 保留实际执行事实，不伪造结果。正文只存一处，时间线只引用输入、行动和必要 note；Session 段 seal 只保存历史来源，不递归复制 prior-Turn 正文。

Session completion 位于必要 finish 的最后，通过 joined owner 等待本地提交。前置 finish 失败仍保存已知事实，不把回答候选发布为正式 output；后续 close 失败只追加诊断，不二次提交。

Turn record v10 与 manifest v3 保持原协议。record 相同身份/业务事实幂等复用；冲突失败。reconcile 只恢复事实索引，收养已写入但未进入 manifest 的孤立记录，不改写注释。更旧格式不静默迁移或 reset。

## 语义解释与 Organize

`core.session.organize` 是 User Turn 内唯一的模型整理动作，属于 core 规划域、由 Session 插件执行。Phase2 给出完整小批变更，Action 不调用额外 LLM，不建立新 Reflection 情景或后台整理任务。SDK 和 Reflection 只有 Session 只读服务。

语义节点表达 thread/note，关系表达成员、顺接、分支、澄清、修正、支持、否定、解决或转向。所有解释须有原始事实 source refs，程序只校验来源可用，不声称证明判断正确。事实 contains/precedes/replies_to/references 确定性派生，不由模型改写，也不自动推断话题或因果。

同批新对象以局部 key 互相引用，owner 分配稳定 ref；修订使用原 ref 和完整语义字段，来源可以纠正。撤回保留原身份和状态，必须同时处理该节点仍活动的关系。合流建立新解释入口，旧分支与历史 ref 保持可读；不移动事实以制造唯一父节点。变更历史沿原有 Action 记录追溯，不再保存对象版本链。

整批候选经来源、对象与关系校验后，在 Session 锁内一次原子替换 map.json，再发布内存快照。缺少该文件表示尚无注释，合法 R6 Session 可直接打开；损坏文件不能降为空图。没有 CAS、图数据库或跨文件事务。

### 当前轮证据

Context 提供只读 ContextTurnFacts，Action 在事件循环取得快照后交给 joined owner 操作。Session 共用完成时的引用映射，把当前已接受输入、已结算 Action 转成最终 Session occurrence；不 seal 活动 Trace、不对已结算子集重新编号。

当前证据只可解释已有历史，不进入 prior-Turn 目录、话题成员或线性交互正文。段更新时绑定本轮证据快照，精确读取标注 active_turn；完成后相同 ref 读取不可变 record。未接受输入、未来结果和未结算 Action 被局部拒绝；若完成记录未能保存，来源报告不可用，不伪造证据或回滚已提交 map。

## 同一 Session 段的两个投影

Background 先展示语义地图，再展示按历史顺序排列的线性交互。地图只包含解释、关系和 refs；正文从同一 Turn records 投影，每个 Turn 只出现一次，未归类 Turn 也在候选中。

交互流保留初始输入、追加、reason 的行动标记/状态/ref、问题及完整有序选项、带 reply_to 的回复、正式 output。reason 的任意 JSON 不是统一结论，不自动内联推理全文或供应商隐藏 reasoning；core.answer 的行动结果不再复制一次正式回答。普通 Action 只给状态/来源线索，完整请求与结果按 ref 读取。

Segment 在 open 时固定 prior-Turn manifest 和注释快照。Organize 提交后发 Signal，prepare 读取最新注释并共用已缓存的不可变记录，install 同步替换视图；不扩大本轮历史集合，不每 Cycle 重扫文件。SDK 新读取可见最新提交，已取得的固定视图保持快照语义。render 与 reclaim 无 I/O。

### 预算和压力

地图导航和线性正文共用 background_max_chars，inspect 使用独立容量。导航按近期来源排列，先展示可容纳的解释与直接关系，超限折为标题/ref；其余内容由话题、注释、未归类与完整历史目录覆盖，不要求枚举全部节点。

线性候选去重后，优先最近三轮、解释直接引用的较早 Turn、未归类 Turn，再考虑其余历史；最终仍按稳定历史次序呈现。正常容量内完整展开多轮。超限时省去普通 Action 详情，对长输入/输出明确标记摘录；问题和选项不截断，连同回复仍放不下则整 Turn 折为线索/ref，不留下孤立的“第二项”。

Session 仅在自身超过 80% 水位时回收到半预算，最低保留目录入口；不因其他段变大任意逐出。回收只缩小已准备、已披露的内容，不补选新分支、不改写事实和注释。Organize 更新沿用已收紧预算，下一 Turn 才按初始容量重建。

## 渐进读取与分页

`core.context.inspect` 通过 session: 路由访问：

- 地图入口通向话题、全部注释（含撤回）、未归类 Turn 与完整历史；较多历史分成稳定的 Turn 组。
- 语义节点返回解释、直接关系、关联入口与事实来源，不递归复制成员正文。
- Turn 返回与 Background 相同的完整交互流，另给 Action、timeline、输入、输出、Working、note 和资源入口。
- 行动集合按请求顺序列 occurrence，事实叶子返回原始请求、已知结果或中断事实。资源引用保留来源日，不读取今日同名文件。

所有层级复用 DisclosureHint/Page 和 opaque continuation。query 在地图范围搜索事实与解释，在 Turn 范围搜索其事实，在语义节点范围搜索自身与直接事实来源；不沿任意横向关系递归检索。精确 ref 读取不依赖 query。

分页绑定日、固定来源集合、过滤条件和实际读取内容。解释正文、关系或该范围查询结果变化使旧 token 局部失效；无关注释变化和背景折叠不使未变页面失效。事实正文页不混入可变话题标签。inspect 不修改 Background，不常驻展开集合；完整反馈先进入一次实际决策模型请求，之后才按 Trace 规则折叠。

## 日生命周期与服务

Session root 包含 Memory owner 维护的活动 Memory.md；map 与 turns 一起归档，新日为空图。同日重启保留注释，归档与 Reflection 共用只读 SessionView，不创建可写归档 Engine。Memory facts 从原有记录派生，不把模型解释升级为 Memory 的原始证据。

SessionService 暴露读取；SessionOrganizeService 只注入 User profile 的 Action 和可更新段，两者共享同一 Engine。SDK 保持只读并绑定世代/日 lease；没有外部 Session 编辑 HTTP API。visibility 筛选不能授予缺失写服务。

## 失败边界

无历史、无效来源、未知 ref、冲突变更与不完整撤回返回有限 OrganizeResult，整批不提交；inspect 的未知 ref/token 失效映射为 Context 局部失败。损坏存储、I/O 与内部不变量属于 Session 模块边界，经 RuntimeSessionBridge 处理。

提交成功而后续 prepare 失败时保留真实持久变更，不重放 Action；已开始的本地提交在取消前完整 join。附属清理诊断不覆盖已记录主结果，必要记录失败如实报告。没有围绕假设故障建立补偿事务或第二套恢复状态机。
