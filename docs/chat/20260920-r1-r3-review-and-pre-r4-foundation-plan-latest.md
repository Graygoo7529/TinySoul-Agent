# 前三轮 Review 与 R4 前基础补强方案

状态：`in_progress`（复审与补强方案已整理，补强代码尚未实施）。
初审日期：2026-09-19；最新修订日期：2026-09-20。
主执行计划：[Agent 架构重构](20260920-agent-architecture-refactor-plan-latest.md)。
代码基线：2026-09-19 重新克隆并核对远端的 `be61886`，含 R3 收口；2026-09-20 未再次拉取。本次只交付两份分析文档，不实施后端补强、不更改部署数据。

## 1. 结论与当前授权语义

前三轮是可继续推进的基础。R1 的依赖反转和失败归属、R2 的 async SDK/等待/段协议、R3 的领域职责与执行资源组织都与主目标一致。没有证据支持再次推翻现有内核；下一步应补可验证的数据和协作缺口。

本文件用于在 R4 开始前完善已实施基础，**不把原定 R4–R6 的新能力提前全塞进“收口”**。环境源与订阅、Gateway v2、ACP/MCP 仍按主计划继续；Session Organize 的运行动作安排尾期，数据基础提前补。

2026-09-20 已确认：

- Organize 面向当日此前多个历史 Turn 和当日已有 map，持续梳理对话逻辑、意图、推理行动与交流分支，不限上一成功 Turn。
- 先落地所需数据基础；整理 Action 的完整设计见主计划 §8，尾期实施，不为前期加隐藏 LLM 工作流。
- 面向受信独立主机，不要求脚本/ACP 不能绕过业务写限制，不额外建设执行沙箱或审批系统。User/Reflection 的正式 API 分工保留；原子文件写、资源收尾和准确结果属于运行正确性。

最新微调确认：Map/Organize 只服务当日持续对话，日切将 turns 与 map 一起归档，新日从空地图开始。撤销上一版跨日持续地图和相应补强范围；执行强隔离议题仍已关闭。既有 Archive/Reflection 历史读取照旧。

## 2. 前三轮实施 Review

| 轮次 | 核验代码/契约 | 评价与保留内容 |
|---|---|---|
| R1 | owner runtime_bridge；runtime/infra 导入边界；LLM 容量事实与上层恢复策略 | 依赖方向合理，保留 bridge 与三层失败，不重新集中到 runtime |
| R2 及收口 | Agent SDK、RootScheduler、服务世代/日有效性、JoinedOperations | 有真正的生命周期闭环；保留 create/start 分义、单根队列、候选配置与激活分开 |
| R2 及收口 | Loop、TurnInbox、预算 SUSPEND、question/reply、JobRegistry | 暂停不是终结后复活；事件/预算不需要第二套等待器 |
| R2 | Context 三插槽、四形状、typed 段更新、prepare/install、seal/close | 外围维护领域视图已落地；不把原计划旧 Context owner 特判当现状 |
| R2/R3 | Action runner、typed Trace、TurnCompletionPipeline | 内部非法结果走模块失败；必要提交和附属清理分开；Session 最后记录 |
| R3 | Session records/views/completion/projection | 唯一不可变历史与确定性 Map 已形成；无模型 organize 是已批准的延后，不是违约 |
| R3 | Reflection profile、Memory/Home 服务、逐动作 catalog | 专属动作归本属域是合理调整；三情景共用定义，visibility 不另造授权系统 |
| R3 | Workspace storage/inspection/actions | 去 CAS、轻量 manifest、灵活文件动作；保留原子写和已提交事实 |
| R3 及收口 | execution、kernel/jobs、infra/process | 能力、监督、OS 执行资源各有 owner；后代收尾不因父进程先退出而遗漏 |
| R3 | assets/common/standard/development、ConfigDocumentSet | 配置来源统一；不需改为另一种模板/加载平台 |

异常处理代表路径审查结论：已知可修正请求由 ActionResult 反馈，owner IO/不变量经 bridge，取消/转移保持其身份。宽泛捕获需要看所在边界，不按关键字机械删除。当前 Action runner 中的 join 逻辑服务于真实完成语义，不再增设线程泄漏恢复器。

Review 为关键路径与契约审查，不声称逐行覆盖全仓。五份子计划及收口的历史完成状态保持原样；本轮新发现的延伸需求不反向将已完成轮次全部改成失败。

## 3. 问题分级：补强、已知验证不足、未来能力

| 编号 | 当前证据与影响 | 分类/处理时机 |
|---|---|---|
| F1 | SealedTurnTrace 有 entries/actions；session/completion.py 主要投影 inputs/actions/最终 State，缺少统一事实交错顺序 | 数据能力不足；R4 前 BF1，支撑后续 Organize |
| F2 | 现有当日 Map/inspect 需消费 BF1 新增的稳定事实与顺序 | 当日导航补强；R4 前 BF2，固定日视图符合范围，不新增跨日入口 |
| F3 | PluginDeclaration 仅有 services/requires/segments/actions；完成管线和环境服务在组合根装配 | 当前架构边界，非已证实运行 bug；R4 前澄清契约，R4 以 fswatch 实现所需贡献 |
| F4 | PluginRegistry 排服务依赖，TurnSegments.open 按显示 sort_key 排序 | 潜在扩展误用；明确服务先解析、段不读取别段私有状态，不预造依赖调度器 |
| F5 | BusinessClock/IanaBusinessClock/business_day 仍在 infra、Loop、Agent | 语义命名遗留；R4 前 BF3 成套修正 |
| F6 | Linux ty 6 个 msvcrt 成员诊断；Windows 目标通过 | 平台类型声明不足；R4 前 BF4 |
| F7 | 两个本地 Web discovery 测试仍使用真实 DNS，受环境影响 | 测试隔离不足；R4 前 BF4，保留生产校验 |
| F8 | fswatch/owner 事件适配未实现；非输入事件目前主要转 Trace note | 既定 S4 新能力，不算 R3 漏实现；R4 正式完成 |
| F9 | Session 解释层、organize、运行中 Map 刷新未实现 | 已确认延后；基础先做，主计划尾期实现 |
| F10 | Gateway v2、ACP/MCP 完整适配未实现 | 按 S5/S6 推进，不能用占位接口标完成 |
| F11 | Trace.compact 先 fold_overlays，现有 min_hot_entries 不等于保护新 inspect 正文；分支 inspect 当前超限会拒绝而非分页 | 渐进披露待补的契约与静态风险，不宣称已复现模型循环；BF2.2/BF2.3 验证 |
| F12 | TurnSegments.reclaim 目前按 shape 调用段；Session 当前未声明 RECLAIM | BF2 接入回收时由 Session 实现自身水位/最低投影规则，不能只加能力枚举 |

现有 Session revision 服务固定视图与分页，不是 Workspace CAS；Trace 折叠树可以承载 Stack 语义。不要按字段名或内部类名机械删除合理实现。

## 4. R4 前基础补强执行方案

以下 BF 均为 `pending`。每个切片同时更新生产消费者、真实契约测试及对应 docs/design；实施后才回填 done。具体类型/函数名可服从现有代码风格，但不能改变主计划 §8 的数据语义。

### BF1：把当前 Turn 的可追溯事实补完整

**目标：**不靠模型补记，也不把 provider 消息布局当事实 schema。跨轮能说明收到什么、何时对 Agent 可见、执行了哪些行动、重要变化是什么。

实施路径：

1. 在 kernel/context 的 Trace 事实协议中增加稳定有序引用，沿用已有 Action 身份。typed Input/Action/Event/Job 事实为正文来源，时间线只存 ref/kind/seq/必要 cycle 与关联，避免复制同一输出。
2. 输入保留受理身份与接收顺序；在 Inbox 批次成功安装时记录对 Context 的可见位置。动作按请求/开始/结算实际回调记录；并行完成不靠 ActionBatch 最终排序反推。时间线 seq 只表达 owner 观察顺序，不宣称外部物理时刻或因果。
3. 外部事件和 Job 记录以当前已有消费者为范围：已交付的环境事实、待答请求、终态/结果引用；进度按已存在合并规则记录有界摘要。未来 fswatch/ACP 使用同一 typed 通路，不预造其专属字段。
4. Session completion 接收这些 typed 事实，序列化进同一不可变 TurnRecord。Trace 折叠不改变事实；取消前已接受的重要记录在既有收尾中消费，保留未执行/取消/未知状态。
5. plan 的最终快照继续保存，已有动作事实记录显式修改；如存在无 Action 的重要变更，用同一 typed 记录入口，不保存每个无意义状态快照。
6. 原子记录提交及 manifest reconcile 沿用；必要 schema 变化显式记录，不静默迁移、丢弃或 reset 已部署数据。模型投影不显示 schema/revision 等实现字段。

**现有落点：**kernel/context/builtin/trace.py、context/engine.py、loop/turn.py、action/execution/runner.py、plugins/session/completion.py、records/models.py、views/navigation.py。可按现有职责拆小文件，不再新设顶层日志模块。

**验证：**串行行动间追加输入、并行行动反序完成、ask/reply、等待时事件/Job 终态、Trace 折叠、失败/取消保存；重开 Session 后仍能从事实引用解释顺序。聚焦正反路径即可，不为每个 dataclass 写镜像测试。

### BF2：数据基础立即有用——当日 Map 导航与事实读取

**目标：**让 BF1 当下就由 session Map/inspect 消费；以 Trace 与当日 Session 共用渐进披露构件，形成顶层线索 → 下层 ref → 事实详情的完整可用路径。Stack 的顺序与 Map 的关系保持不变。

实施路径：

1. 按主计划 §7.2.1–7.2.2 从现有 Trace 中提取有真实消费者的线索/披露页、显示折叠与分页构件；Trace 和 Session 分别提供分组、线索、保护策略与事实读取，不共用巨型基类。扩展现有确定性 Map：输入、行动、重要事件及其稳定引用可导航；contains/precedes/replies_to/references 与明确请求/结果关系由事实构建，不做意图推断。
2. 按主计划 §7.7 扩展同一 `core.context.inspect(ref, query?, continuation?)`：无 query 导航/读详情，有 query 在该 ref 范围定位证据，结果含摘录和稳定引用；Trace 与当日 Session 为真实消费者。复用路由与分页，补 typed 请求和可选 QUERY 能力，同步现有 inspector，不另建搜索工具。当前阶段搜索事实，尾期再接语义注释。近期 Background 含真实问答/结果和 Map 入口，不因无 Organize 而隐藏新事实。
3. 导航覆盖当日已结束 Turns；稳定来源保留所属 day/Turn/事实身份，以便随日归档后仍可解释。不新增跨日 Session 导航路由或历史图聚合服务。
4. session 段固定当日、本轮开始前的已结束事实集合；当日较早 Turn 按需读取。新日无历史是正常状态；损坏记录仍走 owner 失败，不装作没有历史。
5. 地图根保留当日近期内容与较早 Turn 分组线索；每次 inspect 披露下一层和必要横向关系，不只返回一个总入口。未有 Organize 时确定性分组，尾期接入话题线索；Session 自身超水位时复用折叠构件收缩可见层级，保留最低导航投影。现有字符水位与 continuation 继续使用，不在每 Cycle 扫描全部事实。

**现有落点：**kernel/context/actions.py、engine.py、segments/{protocol,collection}.py、builtin/core.py/trace.py，core/actions/context_inspect.toml；session/projection.py、services.py、engine.py、views/{inspection,navigation,background}.py。日切复用现有 Session 目录归档，不扩展 Archive 读取契约。

**验证：**不使用 query，仅沿顶层线索连续 inspect 即可到达被折叠的 Trace/Session 事实；多次折叠仍保留可判断的线索；同一事实的跨分支关联和 Action 顺序不变；无 Organize 也能导航；Trace/Session 压缩前后按正文 query 找到相同证据；从根入口定位并读全文；inspect 结果再折叠后可重读；不支持 query 的段明确反馈；当日多 Turn 的同一事实导航入口；空历史/损坏历史；多页查询不重复或漏项；大历史投影仍有入口；日切归档旧记录、新日视图为空。完成后，删除未来 Organize 不会使这些数据基础失去用途。

**顺序与完成条件：**BF2 已超过单纯“补一个导航方法”的范围，按四个小切片执行；它们属于同一补强方案，不另建并行总计划。

| 切片 | 具体落地 | 可审阅完成条件 |
|---|---|---|
| BF2.1 事实导航 | 消费 BF1 身份/时间线，完善当日 Map 与精确事实 ref | 无 Organize 即可查看当日问答、行动和重要事件 |
| BF2.2 共用披露 | Trace/Session 共用线索、分层显示候选、全层分页；owner 保留分组规则 | 只用根线索与 ref 能逐层找到事实；折叠/加父节点后旧 ref 可用；分支和超长叶子都能继续读取 |
| BF2.3 inspect 取回闭环 | typed inspect/page、同一 ref 路由和 ActionResult；可见结果保护及 owner 回收资格 | 结果进入实际决策模型请求后才折叠；Session 未超自身水位返回零；不改消息角色和工具关联 |
| BF2.4 辅助 query | 沿同一 inspector 增加 QUERY 与确定性匹配 | 查询命中与精确 ref 读取指向同一证据；未完成扫描正确分页；无需新搜索执行器 |

首要验收是无需 query 的渐进追溯；query 仍按已定范围实施，但不能用搜索通过来替代 BF2.2。每个切片同步现有消费者，不先合入破损签名；Session 事实图/投影是前期交付，map.json 语义注释和 Organize Action 仍留尾期。

公共披露只存引用/线索/视图；事实和正文归原 owner，不新建平行持久库。短暂保护复用 Task/Trace 覆盖层生命周期，不建额外恢复控制器。静态/分页来源继续使用既有 continuation；具体规则以主计划 §7.2.3 为唯一设计定义。

**本切片明确不做：**注释写存储、空 organize schema/handler、隐藏 LLM、自动总结调度、thread 空类型。事实地图独立工作；语义节点/边与写入契约已在主计划设计，尾期再落地。

### BF3：对齐所有权表述与日期命名

**目标：**防止后续开发因旧文档误用已有生命周期，清理仍可见的 Business Day 表述。

- 将 BusinessClock/IanaBusinessClock 改为 CalendarClock/IanaCalendarClock；Turn 活动日期字段用 active_day，Reflection 保留 source_day/target_day。类型、调用者、Observation/SDK 相关字段、配置描述、测试与文档同步，不保留旧别名；外部字段变更写明。
- 框架只解释通用事实/段能力，领域内容由 owner 解释；完成贡献接入唯一 TurnCompletionPipeline。无需把 Session recorder 搬入一个空 Segment，也不创建独立完成事件总线。
- 说明段显示顺序与服务依赖不是同一概念。现有 provider 依赖已解析服务，不读取另一段未提交视图；未来确有 open 依赖再由真实消费者带出契约。
- 当前 PluginDeclaration 不承诺覆盖全部异步资源生命周期；文档如实说明现有组合根作用。R4 再新增必要贡献，不为每个主计划注册名称写一个空方法。
- 去除“cwd/Service 能阻止受信代码任意写”的暗示。User/Reflection 正式动作分工保留；脚本直接写的实际副作用仍经 owner reconcile 反映，不因不是正式动作就伪称没有发生。

**验证：**导入与配置/SDK 相关契约，日切/Reflection 来源回归；搜索旧语义名时历史分析记录不作为运行代码失败。修改过的公开协议同步文档，测试不固定无意义文件数或文本全文。

### BF4：让本地门禁可复现

- Windows 控制台实现以平台条件定义或现有适配边界隔离，使 Linux ty 不解析不可用 msvcrt 成员；保留 Windows 功能，不全局忽略错误。
- Web URL 检查的解析器按现有可注入风格传入 discovery 测试，fake 页面/robots/解析器共同组成确定性本地用例。真实 DNS/网络验收仍属 external，不关闭生产 URL 校验。
- 测试 httpx/OpenAI 本地 fake 服务时不依赖宿主代理。前次清除测试进程代理已定位问题；生产是否使用宿主代理不被测试修复顺手改变，不为此强加新的依赖或配置平台。
- Linux 真实进程/后代收尾与 SDK 跨日已有聚焦通过，保留并回归；Windows 实机测试仍需 Windows 环境，目标类型检查不冒充实机验证。

按 AGENTS 聚焦 → Fast → Full → typecheck；Full 包括非 external 的 generation/wheel，平台分别记录。若环境不能完成某项，准确列出缺口，不改 skip 伪造全绿。

### BF5：验收与主计划回填

BF1/BF2 数据基础应先完成，再宣布可以在此基础上开展环境能力；BF3/BF4 可按修改关联组织，最终一起验收。

- 一条完整 fake-provider SDK 流程：提问 → 行动 → 追加输入 → 事件/Job → 完成 → 同日下一 Turn inspect 先前事实，并验证日切后不继续旧日视图。
- typed 完成事实不依赖 Observation 是否成功，必要写失败不宣称成功；不新增通用恢复框架。
- 更新受影响 docs/design、协议说明与主计划的“数据基础”进度，Organize Action/注释仍保持未实施。
- 所有补强待实施项关闭或有明确留存理由；验证记录包含版本/平台/命令/结果与未执行项。
- 只在代码、文档、必要验证齐备后把本补强实施状态改为 done，并按仓库规则归档；不改写前三轮历史记录的当时验收数字。

## 5. R4 及后续推进边界

| 阶段 | 负责内容 | 不重复建设 |
|---|---|---|
| R4 前本补强 | typed 事实顺序、历史导航、命名、可复现门禁 | 不提前实现全部环境 SPI 和 Organize |
| R4 / S4 | fswatch、插件事件适配/订阅、必要资源/完成贡献；暂停时更新 owner、恢复时安装段 | 复用 SDK、Inbox、prepare/install、等待、资源关闭 |
| S5 | Gateway v2 状态/请求/回复/Job/重连/配置语义 | 不绕开 SDK 建第二套状态 |
| S6 | ACP connect/delegate 与 MCP search/describe/call | 复用 Job、Trace、State 段，不建设强隔离平台 |
| 尾期 S3 补完 | core.session.organize、语义节点/边存储、当日跨 Turn 持续地图、段刷新与日切归档 | 复用 BF1/BF2 的事实来源和 inspect；没有额外隐藏 LLM |
| S7 | 最终文档、旧名称/入口、打包与完整协作验收 | 不能用全仓清理掩盖尚未实现的业务能力 |

R4 以“外部文件变化 → owner reconcile → 段批次更新 → 后续模型看到”为完整切片；定向过期事件不能路由到别的 Turn，普通文件变化默认不触发新根请求。此处保留有界资源与正确时序，是为了系统可靠、性能稳定，不升级为复杂防御设计。

ACP 的 Connection/协议 session/Job 三分仍有效；简单跨 Turn 复用空闲连接，否则关闭，无需再询问。MCP 搜索/描述结果在 Trace，不新建工具列表段。锁定协议版本与真实 adapter 时再核实具体方法，不在本文件假定外部 SDK 行为。

## 6. Organize 设计摘要与前后期接口衔接

完整定义只在主计划 §8 维护，本节说明补强交付如何被使用：

1. 自动层给出稳定 Fact refs、有序事实与确定性 Map。
2. 尾期模型读取当日事实和已有地图，调用 `core.session.organize` 应用 upsert/retract；命名对齐现有 `core.context.inspect`、`core.job.*`，domain 仍是 core，文件为 core/actions/session_organize.toml。
3. Session 保存语义状态，发出更新；Map 段下个边界刷新。Node/Edge 可以跨多个 Turn 关联，可修订既有话题，不改原始问答和结果。
4. 整理对象是历史 Turn/已有 map；当前已接受输入和已结算行动可作为新的证据，立即修订旧理解。其稳定引用随当前完成记录落盘；必要记录失败时明确来源不可用，不新增预提交系统或跨文件事务。
5. 当日语义状态在尾期以活动 Session 目录内的 map.json 实施；turns/map 随现有目录一起归档，新日空地图，不建长期跨日文件。BF2 先完善当日事实导航，尾期再验证地图归档及同日重启恢复。

普通 User 写 Session 解释层符合对话职责，与写持久 Memory/提交 actual Home 是不同业务。Reflection 继续把会话事实作为知识整理证据，不替代 Session organize。

## 7. 整体一致性复查与交付

| 已确认理念 | 主计划落点 | 本补强落点 |
|---|---|---|
| Stack/Map 语义不变，共享堆式渐进披露 | §7.2.1–7.2.3 | BF2.2，两个真实 owner 共用构件 |
| 顶层有线索，逐层 ref 可到达事实 | §7.7 | BF2.1/BF2.2，无 query 路径验收 |
| inspect 让取回内容重新进入模型视野 | §7.2.3/§7.7 | BF2.3，保护实际可见结果再折叠 |
| 模块维护事实，Kernel 不理解业务 | §3/§7.4/§8.2 | BF1、BF2、BF3 的 owner/管线边界 |
| Session 当日持续整理并日切归档 | §8.1/§8.3/§8.6 | BF2/BF5 的当日数据；Organize 与 map.json 尾期 |
| 功能灵活，避免重复防御机制 | §9/§11/§14 的受信单机约定 | 保留必要正确性，不加沙箱/审批/新执行器 |

复查判断：方案合理可行，但结论基于当前代码骨架和已记录验证；BF 状态仍为 pending，不以设计复查替代实现门禁。此前 Review 中的缺口已分清“实际验证不足”“新增数据契约”“既定后续能力”，未把所有后续任务混称前三轮回归。新增披露细节是闭合已确认理念的实现契约，当前无须另增用户决策点。



两份文档分别是主执行计划与本 Review/基础补强方案；不另外生成平行主计划或替换预览。用户确认的方向已同步，具体接口/存储设计作为可实施方案记载，代码实施仍为 pending。

本次未更改后端、AGENTS 或 docs/design 的当前事实，没有新增测试通过声明。建议文档提交：`docs: finalize progressive context disclosure and pre-R4 foundation plan`。

## 8. 已有复审验证证据（2026-09-19）

环境：Linux，独立 checkout，新建 Python 3.13.15 环境并安装项目 dev 依赖；没有项目 Conda 环境或 PowerShell，使用与脚本相同 marker 的 pytest 入口，临时目录由 tests/conftest.py 隔离。

- 聚焦：架构依赖、infra/process、Context segments、Jobs、Agent SDK，74 passed、1 skipped。包括真实后代进程和 SDK 跨日收尾测试；跳过项为 Windows 平台验证。
- 首次 Fast：1057 passed、13 failed、6 skipped、28 deselected。多数失败由宿主 SOCKS 代理缺少 socksio 引起，并触发 SDK 客户端清理连带错误；另有 Web discovery 的真实 DNS 失败。不能把这些合计当作 13 个架构缺陷。
- 清除当前测试进程的代理环境后，Fast：1068 passed、2 failed、6 skipped、28 deselected。剩余两项均为 tests/plugins/capabilities/web/backends/test_discovery.py 的 DNS 解析失败；它们注入了页面/robots fetcher，但入口 URL 校验仍走真实解析器。建议本地测试注入确定性 resolver，真实 DNS 留 external；不要改生产校验或用全局 skip 消除失败。
- ty 0.0.82：Windows 目标检查通过；Linux 默认检查有 6 处 terminal.py 中 msvcrt 成员诊断。该方法运行入口有平台分流，但定义未让 Linux 类型检查器排除 Windows 专属调用；需要平台条件定义或明确平台适配边界，不应全局忽略类型错误。
- Fast 尚有上述环境耦合失败，本次未扩大运行 Full/generation/wheel；未执行真实 provider/ACP/MCP/network 验证。本次不沿用历史 Full 数字冒充本机通过。
- git diff --check 通过；只修改主计划和本复审文档。

上述是 2026-09-19 对 be61886 的实际检查，不是本方案补强已完成的证据。2026-09-20 仅修订文档，未重复运行业务测试；文档链接、状态和差异另行核验。
