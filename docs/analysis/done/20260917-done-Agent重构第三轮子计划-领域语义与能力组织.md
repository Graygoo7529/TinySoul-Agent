# Agent 重构第三轮子计划：领域语义与能力组织

状态：`done`（R3.0–R3.7 实现、消费者、文档与必要验证已逐项核对）。
建立日期：2026-09-17；修订日期：2026-09-19。
分析基线：首次为本地 `43f1616`；最近复核为已提交方案的 `2ccefab`，开始分析时工作区干净；未查询远端。
上位计划：[Agent 架构重构主计划](../20260915-agent-architecture-refactor-plan.md)。
前置成果：[R2 收口](20260916-done-Agent重构R2收口子计划.md) 已归档，作为运行机制与验证的历史基线。

## 1. 目标、确认和主计划关系

R3 在已可运行的 Agent SDK、TurnProfile、段协议、Action 和 Job 基础上完成领域语义重构，同时整理内部代码层次和静态资源来源。判断顺序保持为：事实 owner → 服务与权限 → 数据流 → 提交和失败 → 生命周期 → 目录组织。

本轮讨论已确认：

- **D1 `confirmed`**：本轮 Session Map 自动构建只使用对话与行动事实及确定性关系。后续可由 Agent 自发选择 core domain 的整理 Action，梳理对话历史与逻辑；不把模型推导混成自动记录的事实。
- **D2 `confirmed`**：Reflection 动作本轮归回 Home/Memory 并改名，不保留新旧别名。情景仍由同一 Agent 的 TurnProfile 表达，普通 User 不获得专属持久写权限。
- **D3 `confirmed`**：保留 `plugins/capabilities`，承载 web、资源转换等外围工具能力；删除平行编排和状态。execution 已确认独立为 `plugins/execution`，以 `kernel/jobs` 为统一运行依据，共用进程设施归 `infra/process`，见 Q4。
- **D4 `confirmed`**：保持各后端一级 owner，全面审阅其内部局部子系统与封装。assets 直接分为 common/standard/development，每个 domain/action 独立 TOML，并由统一 ConfigDocumentSet 生命周期加载。
- **D5 `confirmed`**：Memory 采用独立规划域，普通与 Reflection 动作统一使用 `memory.*`，按情景授予操作能力。
- **D6 `confirmed`**：execution 直接操作真实当日 Workspace；已产生的文件副作用不因取消回滚，collect 只读结果。
- **D7 `confirmed`**：无 daily 时整理完整 daily；已有 daily 时读取既有内容，结合可用证据修订、重组并补充。daily 无严格冻结/封账语义，不增加 open/closed 来源状态。
- **D8 `confirmed`**：domain 提供可覆盖的默认选择，单动作可以覆盖域选择；沿用第 8.2 节的情景与默认值优先级，不改为域级强制总闸。

前一次预览的两处表述在此修正：Workspace 不能只做门面封装，主计划还要求去 CAS、去压力 Trash 与动作重整；execution 不能只做零散审计，主计划要求合并 script/shell/supervised_process，并服从同一 Job 生命周期。其目录落点与状态 owner 需要分别确定，移动文件本身不构成运行统一。

主计划第 8 节包含持久推导注释与 organize 的长期目标。本轮按 D1 先完成事实地图，后续整理仍由 Session owner 提供 core Action，不被改判为“只能由 Memory Reflection 实现”。自动事实图可以重建；未来由模型产生的注释不能宣称可从事实无损重建。本轮不预建注释表、空 organize 接口或没有消费者的 thread 类型。

| 主计划依据 | 本轮交付 | 范围状态 |
|---|---|---|
| §7–8 Session Map、统一 inspect、typed Trace 事实 | 确定性地图、有界投影、完整追溯、跨日身份、必要持久化 | `done` |
| §8/Q4 模型 organize、thread/gist/推导关系 | 保留方向，按 D1 后续细化 | `deferred`，不能算作本轮已实现 |
| §9 Reflection、日来源、Memory 轻量化 | 动作归并、同源 catalog、今天/历史来源、移除 availability 文件 | `done` |
| §10 Workspace | 去 CAS/压力删除、完整文件动作、轻量索引与简单 Trash | `done` |
| §10–11 execution/Job | 统一 execution，复用 Job 和受控进程生命周期 | `done` |
| §3/12 模块组织与依赖反转 | 有消费者的内部子包、装配归 Agent、catalog 集中 | `done` |
| S4/S5/S6/S7 | 仅同步本轮受影响消费者和文档 | 不扩展为 fswatch 全实现、Gateway v2、ACP/MCP 或全仓重写 |

主计划 S1/S2 保持 done，S3 为 in_progress。本轮完成项已回填；organize/模型推导注释按 D1 延后，R3 的完成不等同原主计划全部 Session 目标完成。

## 2. 代码依据与复用判断

以下保留实施前基线检查，用于解释重构依据；实施后的落点与验证见第 13 节，不宣称已逐行审计全仓。

| 现有位置 | 核验事实 | 本轮处理 |
|---|---|---|
| `plugins/session/engine.py`、`store.py`、`completion.py` | 已有不可变 Turn record、幂等写入、reconcile、typed Action 事实 | 复用必要提交与恢复，补地图边界 |
| `plugins/session/navigation.py`、`background.py`、`projection.py` | 已派生 turn/action/resource 与 precedes/contains/references；Background 仍偏向裁剪后的最近问答；无 organize | 形成明确事实地图投影，统一 `core.context.inspect`；不新建 `session.inspect` 模型动作 |
| `plugins/workspace/engine.py`、`mirror.py`、`pressure.py`、`trash.py` | digest/revision/read-set、mirror、压力删除和 Trash marker 仍存在 | 按主计划删除旧契约；保留有用资源算法与 owner 边界 |
| `gateway/endpoint/engine/workspace.py` 与 HTTP routes | mutation 仍要求 expected_digest/expected_revision/retention | 与 Service、模型动作、配置、文档同批迁移 |
| `plugins/reflection/actions.py`、`resources.py` | 通用 catalog 与包内专属 catalog 分别加载再拼接 | 所有情景使用同一配置来源和统一 ActionPolicy |
| `plugins/reflection/memory/task.py` | 只接受归档日；当天被跳过；自动请求按 daily 存在跳过 | 支持两类来源，并解决当天快照与关闭日整理的衔接 |
| `plugins/reflection/availability.py`、`engine.py` | availability.json 保存 backlog；刷新依赖旧文件和本次 transition | 从 Archive/Session/Memory/Home 门面重算，不只是删 save 调用 |
| `plugins/memory/active.py`、`engine.py` | 活动记忆已无 CAS，持久知识已是单文档写 | 作为已有成果核验，不重复宣布待重写；审计无消费者 digest 和旧字段 |
| `plugins/capabilities/{script,shell,supervised_process}` | 共用 JobRegistry，但保留 READY_TO_APPLY、mirror/apply/discard 与专属 answer guard | 合并 execution，终态和回答阻塞归通用 Job 事实 |
| `plugins/capabilities/assembly.py` | CommonActionAssembly 实际装配 Home/Workspace、Context/core、Job 和所有能力 | 跨 owner 的组合根归 Agent；capabilities 仅贡献自身能力 |
| `agent/catalog.py`、`gateway/initializer.py`、`pyproject.toml` | 从多个代码包拼 catalog，再复制到项目；Reflection 另行加载 | 集中包资源和统一生成入口，不再维护两份定义 |
| `assets/project/tinysoul.toml`、`infra/config/{project,environment,controller}.py`、`agent/builder.py` | 通用 Action catalog 已是统一配置中的 document set，支持候选编辑/reload；文件保存完整定义 | 区分独立文件与独立对象语义，推荐复用文档读取/编辑协议，清理初始化与 Reflection 的额外装载旁路 |
| `kernel/action/config.py`、`core/loader.py`、`agent/services.py` | 当前 runtime.enabled 默认值与情景 ActionPolicy 两处选择；配置查询主要投影 User 情景 | 统一 domain 内可见性配置，按指定情景查询有效动作与关闭原因 |
| `agent/day.py`、`agent/scheduler.py`、`kernel/loop/turn.py` | 每项根工作前 preflight，Turn 持 day lease 直到收尾；暂停不释放执行位置 | 保留次序，按真实结果区分局部清理诊断与收尾契约失败 |
| `kernel/jobs/registry.py::release`、`kernel/action/backends/process.py::close` | 停止/清理失败仍可能变成诊断，registry 移除条目；底层 close 报错后仍设置 closed | 先区分实际进程停止与附属清理；不能把每个 close 异常等同仍有活任务 |
| `agent/`、`kernel/`、`environment/` | 顶层边界合理；Agent 内部职责混排，Kernel 已有一级分包，environment 文件较少 | 有选择地分层，不按文件数或对称性制造子包 |

### 2.1 2026-09-18 完整方案复审的补充证据

总体分层和已确认语义相容；可行性判断来自静态源码与依赖核对，不代替实施验证。以下不是新增业务范围，而是已有条目需要补齐的实际调用闭环：

| 实际路径 | 发现的缺口 | 实施约束 |
|---|---|---|
| `kernel/loop/turn.py` 的 activity cleanup | `cleanup_turn` 抛出的 Exception 被统一降为 CleanupDiagnostic | R3.3 同步迁移 Turn 收尾，必要 owner/Runtime 失败不能被吞掉；只改 process/registry 不足以完成闭环 |
| `kernel/jobs/actions.py`、`registry.py` | JobError 同时承担未知 Job、容量、backend 不变量等语义；Action 全部转为 unknown_job | 可修正请求返回局部结果；监督/依赖契约失败走 Jobs owner 的 bridge；不把 backend 异常伪装为身份不存在 |
| `kernel/action/engine.py::ActionEngineBuilder.build` | 未指定 include 时以整个 catalog 为 granted | 合并 Reflection 定义后，不能把全 catalog 当作 User 授权；装配必须明确授予能力并校验 handler 与所需服务 |
| `plugins/home/actions.py`、`plugins/workspace/actions.py` | 若干宽泛 owner 异常捕获直接把异常文本放入模型反馈 | 随所属 R3.1/R3.2 迁移按三层失败语义收敛；模块 IO/不变量失败不得伪装成普通输入错误，反馈不直接插入 str(exc) |
| `plugins/reflection/memory/task.py`、`context.py` | 目标、归档来源与可用性绑定在仅关闭日的路径中 | 日期在受理时固定，来源在实际 Turn preparation 时绑定；排队期间已完成的目标日事实应能进入本次来源 |

主计划内“Reflection 专属域”的旧名称按已确认 D2/Q1 改称“本属域内的情景专属动作”；这不改变 TurnProfile、独立根请求、授权或完成语义。主计划 Session 推导注释仍属后续目标，不因本轮只做事实地图而删除。

## 3. 不变的架构与失败边界

### 3.1 三种入口各司其职

- AgentBuilder/owner Builder 为装配入口，可以持有完整 Engine 并注册关闭与日切职责；不要求组合根也伪装成普通 SDK 调用者。
- Action、SDK、Endpoint 通过绑定 generation/day 的受约束 Service 访问能力。Service 不复制 owner 状态，旧对象失效后由调用者重新获取。
- Segment 管理本 Turn 的视图、渲染和 inspect；kernel 只消费 slot、shape、能力与类型化信号，不理解 Memory 文档或 Session 图内容。

持久化、运行内存、模型反馈、Observation 分开。已提交事实不能因随后取消或观察失败被称为“已撤销”；短 owner 操作使用既有 joined 边界，长任务使用可停止进程。

### 3.2 失败归属

| 情况 | 处理位置与语义 |
|---|---|
| inspect ref/cursor 不合法、edit 无匹配或歧义、regex 不合法、模型生成内容无效 | 所属 owner 的局部失败，经 ActionResult 反馈；不结束整个 Agent |
| 模型输入来源超预算、进程非零退出/超时、review 条目拒绝 | 有界结果与真实执行事实；已提交部分准确保留 |
| 配置引用未知动作、重复 catalog 身份、注册服务缺失 | 装配失败，在 owner/Action/Agent 边界转换启动失败 |
| Session record 损坏、Memory codec 不变量破坏、owner 根不可用、索引无法继续解释 | 模块异常经自己的 runtime_bridge，不能伪装成空记录/无资源 |
| 取消、结束 Turn、容量恢复 | 沿用现有 Runtime/Trap；不能被 broad except 降为工具失败 |
| 进程已退出，但索引刷新或输出保存失败 | 分开保留进程终态与 owner 失败，不把进程改成仍在运行，也不抹掉文件副作用 |
| stdout/临时文件等附属清理失败 | 有界诊断，已收敛执行事实保持原值，不默认阻断下一根或日切 |
| 有界停止与复查后仍明确存在受控活进程 | execution/Job owner 当前收尾无法完成，沿既有模块 bridge 协调；不是所有清理失败的统一结果 |

本轮修改的 raise/except 逐项核验。局部错误不得携带原始异常、绝对路径、正文、traceback；bridge payload 保留稳定 module/kind 与必要摘要。文件操作失败是否可局部继续取决于 owner 是否仍能解释当前事实，不按 Python 异常类机械分类。

具体迁移不能只替换异常类名：Home/Workspace 的参数、资源缺失、冲突等可修正失败提供稳定短反馈；根目录不可用、损坏或内部不变量错误经 owner bridge。Jobs 区分请求错误与监督失败，统一由自己的边界解释 backend 结果；Infra process 不知道 Runtime。终态、已提交事实、必要失败与附属清理诊断分别保留，最外层不能再把它们全部包成一个工具失败或 cleanup 字符串。

## 4. Session：确定性事实地图

### 4.1 记录、地图和模型视图

1. Turn finish 先按 turn_id 幂等保存不可变业务记录，再更新可重建索引。记录提交是必要完成步骤；索引修复不能重复生成一轮历史。
2. 自动事实包含初始/追加输入、ask/reply、最终回答与终态、显式 reason、typed Action 请求/结果/取消/未执行/未知、milestone 和资源引用。事实只保存一次，地图以 ref 指向对应记录或记录内 occurrence。
3. 只建立确定性顺序、包含、显式 reply-to、资源引用关系。`basis=fact` 仅表示“发生过此输入/行动/引用”，不意味着用户陈述或模型回答的内容已被验证。
4. 以现有 turn/action/resource 为基础；输入和回答需要独立定位时使用记录内 ref，不为每种文本预建重复节点。显式相同资源可去重，但要包含 owner/day 解析语境。
5. Reflection 不写 User Session；失败、取消、等待用户结束的 User Turn 均可追溯，并保留各自终态，不归入成功回答。

### 4.2 有界投影与追溯

- SessionSegment 固定本 Turn 的 prior-turn 来源集合；自动事实图从相同记录派生，不增第二份线性 Summary 或业务图数据库。
- Background 显示地图入口、有界 turn 节点与关键问答/状态投影；大集合有明确覆盖范围、数量和下一页引用。资源正文与全部 Action 参数不常驻 Background。
- 只通过 `core.context.inspect` 路由到 Session 的 map/turn/action/输入等详情；SDK 的 `SessionService.inspect` 是服务方法，不再注册同义模型动作。
- 分页绑定来源视图；cursor 不得漂移到另一天/另一组记录。跨日 `workspace:` 引用表示旧日资源，不解析为当前同名文件。
- 限额、摘录和省略必须可识别并可继续追溯，不能把截断片段当完整历史。压力只调整本轮投影，不删除持久事实；Session 自身未超水位时不因其它段压力折叠历史。最低地图投影仍无法容纳时明确报告容量失败。

未来 organize 使用 Session owner 的带来源推导注释，不改原始问答。具体可整理终态、注释修订和 thread 聚合在后续子计划讨论；本轮不生成“已整理”伪状态，也不发布一个没有实现的待整理 Action 提示。

## 5. Workspace：直接资源操作与轻量索引

### 5.1 事实与元数据

磁盘文件是内容事实；manifest 保留 Link、分类、大小等可重建索引，以及用户设置的标签/说明等 owner 元数据。不能因为内容索引可重建就丢弃人工标签；扫描重建只替换派生部分。

删除 expected_digest、expected_revision、WorkspaceEditReadSet、提交前来源复验、described_digest、retention 与压力删除。不限于 Action 参数，还包括 Service/SDK、Endpoint、Context signal、配置、生成资源、Skill 和测试。Session 的视图 revision、Home review token 等有真实消费者的独立协议不在全局删除范围。

保留 owner 锁、路径解析、原子单文件替换、显式创建/覆盖策略、文本/图片/文档类型和预算检查。LLM 输入在 action 内局部读取，提交时不做内容 CAS；调用者选择共写就接受覆盖可能。不能用 mtime/size 重新包装一套提交前乐观锁。

Turn 准备、受控进程结束及必要查询进行 reconcile；文件事件接点复用现有协议，真实 fswatch 来源仍属 S4。Observation 为旁路，业务 State 更新走 Workspace signal，不通过观察事件倒灌。

### 5.2 动作与可替代关系

| 目标动作 | 语义 | 旧入口处理 |
|---|---|---|
| `workspace.list` | 列目录、资源与标签；有界分页 | 吸收模型侧 scan，内部 reconcile 保留 |
| `workspace.search` | literal/regex、明确范围与覆盖说明 | 替代 search_text；regex 有执行预算，不能阻塞事件循环 |
| `workspace.read` | 小文本可完整读取；大文本显式范围/分页 | 去 digest 前置条件，保留有界结果 |
| `workspace.write` | 写入明确内容，区分创建/替换意图 | 不调用 LLM；替代脚本能力中的普通文件创建 |
| `workspace.edit` / `append` | 精确片段或有序编辑；全部验证后一次写入 | 替代 patch，不保留 alias；多处替换不允许半提交 |
| `workspace.move` / `mkdir` | 文件/目录操作，明确目标已存在处理 | 不自动改写历史 Session Link |
| `workspace.delete` / `restore` / `trash_list` | 简单可恢复删除与查询 | 删除压力策略、retention 与 marker 恢复 Trap |
| `workspace.tag` / `describe` | pinned/tmp/library 标签；局部生成或维护说明 | 标签不赋予跨日保留能力，library 不等于 Library 模块 |
| `workspace.compose` / `analyze` | Action 内 LLM 生成工件/分析显式 references | compose 合并 create/rewrite 的模型生成职责 |

读取/搜索输出继续区分当前 Turn 的有界正文 overlay 与持久化的 compact locator；不把正文灌入 Working 或 Session。`reference_links` 仅由 Workspace owner 解析为工作区输入。

简单 Trash 保留原路径、标签与必要身份，恢复遇到目标冲突返回局部失败。删除/恢复可用临时目录和原子移动组织单项操作，但不重建多阶段 marker/Runtime 恢复状态机；发生中断时保留可解释的文件和元数据，不能静默清理用户内容。Archive 的确定性日切 journal 原样保留。

## 6. Reflection：同一情景机制、领域动作归位

### 6.1 动作身份与能力

profile 继续为 `user`、`home_reflection`、`memory_reflection`；profile 名称表达情景，不随专属 domain 删除而消失。

| 现有动作 | 目标身份 | owner/默认可用情景 |
|---|---|---|
| `home_reflection.diff` | `home.diff` | Home / Home Reflection |
| `home_reflection.review` | `home.review` | Home / Home Reflection |
| `memory_reflection.write_daily` | `memory.write_daily` | Memory / Memory Reflection |
| `memory_reflection.write` | `memory.write` | Memory / Memory Reflection |
| `core.memory.inspect` / `recall` | `memory.inspect` / `recall` | Memory / 三情景通用 |
| `core.memory.memorize` | `memory.memorize` | Memory / User 与 Home Reflection；Memory Reflection 的目标来源只读 |

**Q1 已确认**：普通 Memory 与 Reflection 写动作一并归入独立 memory domain。同步迁移 Phase1 域选择、Action 身份、Skill 挂载、配置与测试，不保留 core.memory 别名。后续 Session organize 仍属于 core，不能因本次 Memory 归域把 Session 业务一并迁走。

HomeReviewService/MemoryKnowledgeService 继续限制专属提交，普通 Service 不增加长期写入口。对应 executor 和局部结果转为 Home/Memory owner 实现；Reflection 留下目标绑定、来源选择、TurnProfile 组合、请求与结果编排。目标日绑定通过类型化服务/任务输入传入，不由 Memory 回调 Reflection 私有 controller。

相同 domain 内按 action 策略启用专属能力。有效集合为 **装配授予 ∩ 当前情景可见性 ∩ backend 可用性**；可见性配置集中在 domain/action 定义处，由同一解析规则提供给各 TurnProfile，不再在 loop/reflection 设置里保留第二份开关表。编辑 catalog 不能授予 User 长期写权限。Phase1、Phase2、调用归一化和批次执行一致，移除空 domain。服务权限还要防止改 handler 映射绕开可见性过滤。

Home review 的差异身份/版本校验继续保留，它是接受明确待审修改的 owner 协议，不属于 Workspace 去 CAS。Home 改副本→diff→review 与 Memory inspect/recall→单文档 write 均由 Agent 自主选择；继续用 core.answer 结束 Reflection，不新增完成动作或固定流水线。

### 6.2 今天和历史日来源

当 `target_day == active_day`，从 Session/Memory 门面取得准备时的 prior-turn 事实与活动 Memory 只读视图；当前 Workspace 可操作。不将未结束 User Turn 或当前 Reflection trace 伪装为已完成来源。SDK 后续改动不会悄悄改变已绑定的输入，明确需要的新资料留待后续整理。

请求受理只固定目标日期、指示与一次触发身份，不提前读取来源全文。实际运行前先做日切 preflight，再在 Turn preparation 选择当天或归档来源；请求排队期间可能跨日，但目标不变。例如受理时是当天的目标，执行时已归档，就使用同一目标日的归档来源，不继续持有过期的当天 Service，也不改成新的今天。

历史目标通过 Archive 提供的 owner 投影读取；Session/Memory/Workspace 各校验自己的归档，不由 Reflection 拼物理路径。未来日是参数错误；既无可用来源也无已有 daily 可以 skipped；已存在但损坏的来源必须失败。已有 daily 本身可以作为重新整理的输入，缺少其它证据时不得虚构新增经历。

**Q3 已按用户补充确认**：daily 是持续可整理的当日情景记忆，不设置冻结状态。

1. 无 daily：读取当次可获得的目标日证据，形成完整 daily；“完整”相对于当前材料，不声称覆盖尚未发生的晚上或未来对话。
2. 有 daily：先读取既有 daily，再结合目标日证据修订、重组和补充；可以调整上午/下午原有记录，并补入晚上内容，不限制为仅追加。
3. `memory:target` 仍表示目标日活动 Memory 来源；已有 daily 通过它自己的 `memory:daily/YYYY-MM-DD` Link 提供并按需召回，两者不混为同一文档。已有 daily 的读取是写入前的实际输入，不只是在提示中声称已看过。
4. 每次 `memory.write_daily` 提交一份完整候选文档，由 Memory owner 原子替换；本轮局部改进可分多次写入，失败不撤销此前成功文档。显式来源与预算不允许完整读取时先渐进检查，不能用被裁剪的旧文档直接覆盖而丢失未知内容。
5. 手动与自动请求都不以 daily 已存在为跳过理由；请求层去重针对一次触发身份，不把“某日期已有文件”当作永久完成。

撤回上一稿的 source_state/open/closed 字段建议；不增加来源冻结、覆盖游标、session_revision、digest 或平行完成日志。历史证据目录仍按日归档，但持久 daily 可以在之后继续修订，这两种生命周期互不替代。

### 6.3 availability 与调度

移除 `runtime/maintenance/availability.json` 的读写、store 和专属配置。availability 保留为可查询的内存投影：Home 待审事实 + Archive 日期目录 + 当前/历史 Session 与活动 Memory 来源可用性 + 已有 daily，由各 owner 门面组合。Memory 投影分别说明“可整理”与“尚无 daily”；已有 daily 不表示不再可整理，也不被无依据地标为必须重做。

Archive 需要有界列举已归档日期的公共能力，作为重启后重建可整理日期与缺失 daily 提示的真实消费者；Memory 提供自己的 daily 目录投影，不扫描其它 owner 私有目录。大历史分页检查，不把“查询可整理内容”实现成每次加载所有全文。缓存可以丢弃，不能成为完成事实。

每日策略仍只提交类型化请求，手动授权仍只针对本次；沿用 R2 单根队列与去重。定时触发的目标日固定在请求受理时，延后执行不重算为另一天。已有 daily 允许本次继续整理；不因重新计算候选日期而自动补跑全部历史、启动时追补所有错过时刻或无限即时重试。缺失 daily 的历史日可在投影中发现并明确提交；失败事实与已提交事实分别报告。用户所说“整理已写的上午/下午并补晚上”属于同一更新语义，不隐含新增一天多次的自动调度。

## 7. execution 与 Job：执行资源和监督统一

### 7.1 所有权

**Q4 已确认**：以 `plugins/execution` 取代 `plugins/capabilities/{script,shell,supervised_process}`，公共监督在 `kernel/jobs`，通用受控进程设施在 `infra/process`。不在 tinysoul 顶层新增一个与 kernel 并列的通用执行层，也不把 shell 业务放入 kernel/jobs。

| 所有者 | 唯一职责 | 不承担的职责 |
|---|---|---|
| `kernel/jobs` | job_id/owner_turn_id、运行状态、监督、等待通知、终态、活任务容量、必要回收 | 不解释脚本、shell、Workspace 路径或未来 ACP 内容 |
| `plugins/execution` | 脚本/shell 请求解释、ProcessJobBackend、stdin、输出投影与 collect、Workspace 输入/输出协作 | 不再持有平行 manager 状态表或 READY_TO_APPLY 状态机 |
| 通用受控进程设施 | 进程/进程组句柄、输出捕获、硬停止和可确认的关闭 | 不拥有 Job id/Turn/业务完成含义 |
| `plugins/capabilities` | web/resource 等外围工具实现 | 不装配其它 owner、不持有第二套通用 Job 生命周期 |

当前受控进程原语在 `kernel/action/backends/process.py`。本轮将其纯进程部分移入 `infra/process`，异常与参数校验同时去 Action 业务依赖，由 Action backend 和 ProcessJobBackend 各自在边界解释。已有 web/resource Action backend 是真实复用消费者；不同时保留两个 Popen/kill 实现。`kernel/action/backends` 仍拥有 Action 到进程的适配，不把它连同框架语义下沉 infra。

Agent 组合根注入共享的 Job 服务；execution 只注册后端能力，不在自己内部另建一个 registry 再暴露它。所有 job 以所属 Turn 隔离；Registry 在 Agent 可索引，不意味任务获得跨 Turn 寿命。未来 ACP 后端接同一真实协议，不现在创建虚假的 ACP 实现。

execution 的 bounded run 与 background start 使用同一 ProcessJobBackend 和 Job 监督路径：run 在当前 Action 的有限 deadline 内等待该 Job 收敛；start 提交后立即返回 job id，后续 Cycle 再监督。两者区别是当前 Action 是否等待，不是两种取消/终态/回收状态机。Action 超时或取消结束前停止其 bounded Job；不把未停止的写进程遗留给后续 Cycle。

公共 JobState 按主计划表达 starting/running/waiting_input/stopping/succeeded/failed/cancelled；超时是失败原因，不能再与另一组 execution state 交叉推断。starting/stopping 由真实启动/停止消费者驱动，普通进程不能因暂时无输出来推测 waiting_input，只有 backend 有明确证据时才投影。动作超时结果、进程退出码与 Job 终态分别表达其所属事实。

通用 answer guard 根据 JobRegistry 判断活 Job，放在 kernel/jobs；已终止且受控执行已停止的 Job 不因尚未 collect 或附属清理诊断阻止正常回答。进程终态、执行句柄释放、附属清理与结果保留分别表达；“FAILED”不自动证明后台已停止，临时文件尚未删除也不意味着存在活 Job。

进程结束即释放执行句柄；有限结果与 Workspace 输出在本 Turn 内仍可读取，终态单调且一次发布、stop 幂等。活任务容量与结果保留容量分别计量；终态结果不能长期占着唯一活任务槽，也不能被无声删除后仍承诺可 collect。有限保留不足时在新执行受理前给出明确结果。Turn 收尾先停止/回收进程，再同步文件与终态、关闭输出资源和释放 day lease；不跨 Turn 保留活 Job。

### 7.2 动作集合

- `execution.run_script`：显式 interpreter、script Link、参数和工作目录，一次有界执行。
- `execution.run_shell`：显式 shell、命令与工作目录，一次有界执行。
- `execution.start`：启动跨 Cycle 监督的 script/shell Job，返回稳定 job id。
- `execution.stdin`：向仍可写的进程输入，局部处理已退出/已关 stdin。
- `execution.collect`：有界读取输出/退出事实及资源 Link；不提交 Workspace 变更，不是唯一资源释放入口。
- 等待、停止、状态复用 `core.wait` 与 `core.job.*`，不重建 execution.wait/stop/status。

普通脚本创建/编辑由 Workspace write/edit/compose 完成；Home skill 资源读写由 Home owner 完成。删除专门的 create_script/rewrite_script/patch_script/promote_script 状态与重复编辑器，保留通过 Home 门面保存可复用脚本的实际能力，检查当前可用动作是否足以替代后再删入口。

### 7.3 工作目录与副作用（Q2 已确认）

执行工作目录位于真实当日 Workspace，默认给每个 Job 独立输出子目录；需要协作时显式选择已有目录。脚本解析可以保留必要的临时文件，停止使用全 Workspace mirror 及 apply/discard/read_candidate 流程。

这会改变可观察语义：进程产生文件即是实际副作用，取消只停止后续执行，不回滚已写文件；collect 不控制提交。进程期间必要查询和结束时由 Workspace reconcile 发现变化，写同一文件可能覆盖，owner 锁不能锁住外部程序。

进程工作目录通过 Workspace 的窄内部授权接口取得，不新增对 SDK/Endpoint 开放的任意路径 API。cwd 约束不是 OS 沙箱，也不能被描述为可防止任意 shell 写入 Home/Memory；正常能力流程仍经 owner 提交，不能把 shell 修改冒称 Reflection 审核完成。若需要强隔离，是独立设计需求，不恢复 mirror+CAS 来虚构保障。

### 7.4 日切、根 Turn 与 Job 的实际编排

本次沿 `agent/commands.py → agent/scheduler.py → agent/day.py → kernel/loop/turn.py → kernel/jobs/registry.py` 核验正常路径：

1. User、Home Reflection、Memory Reflection 是同一个根请求队列里的工作；只运行一个根 Turn。等待输入/Job/预算时仍占该位置并持有 day lease，不运行另一个独立根。
2. Agent 启动及每项根请求执行前调用 day preflight。日切是不用 LLM 的存储准备，不是 Reflection Turn，不在午夜打断当前工作。
3. 当前根 Turn 完成时先关闭入口、回收 Job、消费最后执行事实，再完成必要持久化和段关闭；这些动作在同一个 day lease 内完成。随后释放 lease，下一根执行前才能归档旧 Session/Workspace/Trash，建立新日 Session、空 Memory.md 和 Workspace。
4. User 写自己的 Session；Home Reflection 审核跨日保留的 overlay；Memory Reflection 读目标日来源，写跨日保留的 Memory。两 Reflection 不写 User Session，都可以使用执行日 Workspace。
5. 当前每日定时输入通过 AgentCommands 拆成 Home 和上一日 Memory 两个独立请求，按此顺序连续入队，各自有 handle/Inbox/结果。已有排队 User 工作不会被它们抢占。Home 的局部失败不使 Memory 变成同一事务；若是终止 Agent 的故障，后续根自然不能继续。
6. 当前 preflight 本身只做日切及 availability 刷新，**不会因为日切自动同步运行两个 Reflection**。定时源在所设时刻提交请求，当前默认当地时间 00:15；启动晚于时刻不自动补跑。用户明确允许时也可单独提交 Home 或指定日期 Memory。R3 保留这条调度边界，不额外添加日切与定时双重触发。

例如 9 月 17 日 23:50 的 User Turn 启动 Job，18 日 00:10 才完成，那么整个 Turn/Job 仍属于 17 日工作区；收尾后、下一项工作前才归档 17 日并初始化 18 日。Memory Reflection 的 target_day 若是 17 日，执行时可以在 18 日甚至更晚，不能因此重绑定目标日期或把旧 Workspace Link 指到新根。

代价明确：一个无限等待的 Turn 会延后日切和所有其它根工作。用户可回复、补额或取消；要在旧 Job 运行时另开新日工作区，就需要跨 Turn Job 与多活动 Workspace 的新设计，不属于已确认的主计划。

### 7.5 收尾失败：局部恢复与诊断优先

上一稿将“无法确认已停止”直接扩大为阻断下一根和日切，过于严格。本轮不引入 cleanup_failure 全局开关、持久不安全状态、孤儿进程数据库或日切的第二套 Job 检查器。

当前 `ManagedProcess.close` 把终止、stdout/stderr 关闭和临时目录删除混为一个错误；`JobRegistry.release` 与 Turn 又将它们统一记诊断。因此要修的是失败归类，而不是给所有清理错误增加一条 Agent 终止规则：

| 真实结果 | owner 处理 | 对下一根和日切的影响 |
|---|---|---|
| 已正常退出、已被停止，或检查时进程已不存在 | 完成执行资源收尾；退出/取消/超时按真实原因记录 | 按正常流程继续 |
| 日志流关闭、临时文件清理失败 | 有限诊断；尽可能完成其它清理，不改变已形成的执行结果 | 不因此阻断 |
| 轮询/停止操作暂时失败 | infra/process 在有限关闭预算内复查并执行已有硬停止；上层不再套重试循环 | 局部恢复后继续，不因一次异常升级 |
| 有界处理后有明确证据表明受控进程仍活着且无法停止 | 当前执行 owner 的收尾契约无法完成，保留真实原因并经现有 bridge 处理 | 仅此真实契约失败需要 Runtime 协调；不能宣称 Turn 已无活 Job |

Runtime 转移依已有捕获作用域和失败归属确定，不在代码路径之外增加“任何不确定性都停止 Agent”的策略。若持续运行的受控进程使单根/日切事实确实无法成立，停止接续工作是最后的模块失败结果；这不是一般 cleanup 异常的默认行为。资源查询本身持续不可用时按实际依赖失败报告，也不伪造成功或宣称掌握了进程状态。

进程句柄是否已停止与附属资源是否已清理分开；`_closed` 不得让真实的未完成停止在下一次关闭中被跳过。Job 层只消费必要执行结果和清理诊断，不复制进程状态检测。支持受控进程组/进程树的有界停止，不把整个主机不存在任何孤儿进程当作日切前置条件；主动脱离监管的守护进程不作为受支持 Job 模式。

此闭环必须覆盖 Turn 收尾消费者：附属清理继续返回 CleanupDiagnostic；execution backend 的必要失败经 Jobs 公共边界交给所属 bridge，Turn 按已有 RuntimeException/RuntimeTransferInterrupt 捕获规则保留合法转移并完成其它收尾，不能落入当前 activity cleanup 的宽泛诊断分支。Job 的失败执行结果、实际停止确认与结果保留不可互相替代，release 不能先写 STOPPED、无条件移除条目，再尝试停止。真实活进程无法收敛且不允许继续根工作时，经既有 Agent 结束 frame 处理，不新增一个日切闸门；同时保留原执行失败与必要收尾失败，不能被“主失败优先”抹掉停止接续工作的要求。

跨午夜仍沿 7.4 的正常 Turn 收尾顺序，Archive 只承担自己存储操作的真实失败。进程崩溃后的宿主级恢复不作为 R3 前置能力。

## 8. 按 domain 组织配置，统一 assets 与加载路径

### 8.1 实施前来源和 Action 开关

当前 Action catalog 已纳入配置管理，但使用独立文档集：`config.include` 合并普通配置，`config.document_sets` 声明 `action.catalog`；ProjectConfig/ConfigEnvironment 同时保存两者，ConfigController 也已支持文档集的候选校验、源文件编辑和持久化事务。AgentBuilder 通过 `load_documents(config.document_set("action.catalog"))` 编译定义。此外，init 从各代码包另行收集 catalog，Reflection 装配还单独读取包内专属定义。

现有用户开关实际分布如下，路径均相对于生成项目：

| 配置位置 | 当前含义 |
|---|---|
| `configs/action/catalog/<domain>/domain.toml` 的 `[runtime] enabled` | 域内动作的默认 enabled 值 |
| `configs/action/catalog/<domain>/actions/<action>.toml` 的 `[runtime] enabled` | 单动作默认值，未写时继承域默认值 |
| `configs/loop.toml` 的 `[loop.user.actions.domains]` / `[loop.user.actions.actions]` | User 情景的域/单动作选择 |
| `configs/maintenance.toml` 的 `[maintenance.home.actions.*]` / `[maintenance.memory.actions.*]` | 两个 Reflection 情景的域/单动作选择 |

当前优先级为：情景 Action 选择 → 情景 domain 选择 → catalog Action 默认 → catalog domain 默认 → true。domain 选择是可由单动作覆盖的默认值，不是不可覆盖的总闸。最终还受装配 grants 和 backend 可用性约束；例如 capabilities/script、shell、web 的后端 enabled 配置决定服务是否可用，并非同一份 Action 可见性。Reflection 专属定义未统一成为项目可编辑来源，AgentServices.action_catalog 当前只查询 User 有效视图，这两点需要一并收敛。

需要区分三个互相独立的问题：文件如何拆分、读取后如何表示数据、运行时如何按情景选择能力。每个 domain/action 独立 TOML 只回答第一个问题；它既可以作为完整定义文档，也可以使用命名空间后参加普通配置合并。两种方式都不需要 Reflection 专属 domain。

| 方式 | 每个 Action 文件的形态 | 读取/校验语义 | 取舍 |
|---|---|---|---|
| A：独立定义对象（已确认采用） | `name = "memory.recall"`，局部 `[tool]`、`[runtime]`、`[visibility]` | ConfigDocumentSet 携带逐文件内容与来源，Action owner 编译完整对象、拒绝重复身份 | 字段短，schema 保持整体；继续共用配置入口、编辑事务和 reload，保留真实有用的文档协议 |
| B：命名空间配置（前稿方案，备选） | `[action.domains.memory.actions.recall.tool]` 等完整表路径 | 普通 include 合并配置树，Action owner 编译合并后的定义 | 来源模型单一，但跨文件同键覆盖/深合并也作用于动作和 schema；需扩展通用配置键与空对象等往返语义 |

前稿从“统一配置”推到“必须删除 ConfigDocumentSet”过强。当前文件本来表达具名完整定义，已有文档集又有读取/编辑/候选校验的真实消费者；在一动作一文件的维护目标下，A 更自然。它不是 Reflection 的另一套配置系统。真正需要消除的是分散包资源拼接、Reflection 另读 catalog，以及三情景不共用候选配置的路径。

按用户确认采用 A，Q5 为 `confirmed`。若选择 B，也保持相同逐动作文件布局、情景规则和 owner 边界；不同时实现两套可切换 catalog 加载机制。

### 8.2 一份能力定义，按情景计算有效视图

TurnProfile 表达同一 Agent 的执行情景；domain 表达能力分组；standard/development 表达项目初始化预设，三者不是同一维度。任何一个初始化预设都应支持 User、Home Reflection、Memory Reflection，不能分别打包成三套动作定义。

domain 的语义和默认策略放在自己的 `domain.toml`，Action 的模型描述、schema、执行绑定和可见性放在自己的 TOML。Action 身份与所属 domain 由 Action owner 校验；配置来源路径只定位文件，不成为由任意模块拼接的业务资源身份。现有 dotted action id 不需要改名或拆成配置路径段。

可见性统一由对应文件内的 visibility 配置表达。以 `memory/actions/write.toml` 为例，以下只演示身份与选择策略，省略 tool/backend 等完整定义：

```toml
name = "memory.write"
domain = "memory"

[visibility]
default = false

[visibility.scenarios]
memory_reflection = true
```

domain.toml 也使用相同 visibility 结构。**D8 已确认**：按“动作当前情景 → 域当前情景 → 动作 default → 域 default → true”取第一个已配置值；domain 提供默认策略，单动作可显式覆盖。移除 runtime.enabled 与 loop/reflection 内的平行开关表。超时、并发和 hook 等执行参数仍由 Action runtime 解释，不与可见性混用。

TurnProfile 绑定自身情景标识、准备/完成语义与受约束服务；Action owner 从同一配置编译该情景视图，profile 不再持有另一套用户可编辑选择表。有效集合仍为 grants ∩ visibility ∩ backend available。专属服务只向被授予的情景装配；配置不能为普通 User 授予 Home review/Memory 持久写权限，显式在某情景启用无授权动作时应在候选校验阶段说明原因。未知情景/动作/handler 在装配边界失败，不能静默忽略。Phase1、Phase2 和批次执行消费同一有效集合。

grants 来自显式插件贡献与组合根的情景授权，不从 catalog 全部名称、可编辑 handler 字符串或 runtime.enabled 推导。候选校验遍历三个实际装配情景；未授予的动作不会因共享文件出现就要求所有情景安装它的写服务，也不能借换一个普通 action id 调用已注册的特权 handler。domain 的 true 只选择该情景已授予的集合；对未授予动作的显式 action 情景启用则拒绝并解释原因。这样保留 domain 默认可覆盖语义，同时不把共享 catalog 变成权限来源。

情景配置如 cycle budget、来源选择仍在 loop/reflection 所属设置；“按 domain 配置”指能力定义、动作参数和可见性，不把 Agent/LLM/Job 等不同 owner 的全部设置搬进 domain。Reflection 的 core.answer 提示继续由 profile 局部覆盖语义，不复制整个 core catalog。

### 8.3 建议 assets 结构与初始化

**Q5 建议**：移除 project/config_profiles 两层容器，assets 下直接区分公共资源与两种初始化预设；Action 配置放入公共项目配置模板，不单设 assets/action_catalog，也不复制到两个预设中。明确恢复逐 domain/action 文件的维护粒度，不再建议将整域所有动作先合并成一个 TOML。

```text
tinysoul/assets/
  __init__.py
  common/
    tinysoul.toml
    README.md
    .gitignore
    home/...
    configs/action/catalog/
      core/
        domain.toml
        actions/...
      home/
        domain.toml
        actions/
          diff.toml
          review.toml
          ...
      memory/
        domain.toml
        actions/
          inspect.toml
          recall.toml
          memorize.toml
          write_daily.toml
          write.toml
      workspace/domain.toml + actions/*.toml
      execution/domain.toml + actions/*.toml
      web/domain.toml + actions/*.toml
  standard/
    .env.example
    configs/...                 # 此预设的 Agent/LLM/执行等配置
    home/agent/user/user.md
  development/
    .env.example
    configs/...
    home/agent/user/user.md
```

一个 domain 一个 domain.toml，一个 Action 一个动作 TOML。没有 reflection、home_reflection 或 memory_reflection 行动域目录；home.diff/home.review 与 memory.write_daily/memory.write 分别位于本属域。情景名仍可以出现在 visibility.scenarios，代码中的 plugins/reflection 继续承担情景准备与编排，两者不是同一层次。

共享 catalog 包含全部情景定义与选择策略，只维护一份；两个预设保留各自需要的 Agent/LLM/backend 配置与 Home 内容。init 仅枚举 common 与显式选中的预设，映射为项目相对路径，拒绝重复目标后 staging/安装；共同文件与预设文件不重复提供同一目标。不建设模板继承平台，当前也不引入按预设深合并 Action 定义的路径。

推荐方案 A 在 tinysoul.toml 中仅声明一个 `action.catalog` 文档集，匹配 `configs/action/catalog/*/domain.toml` 与 `configs/action/catalog/*/actions/*.toml`；普通 config.include 不再次命中这些文件。用户直接修改生成项目中的目标动作文件，候选校验后按现有 reload 激活；不另建普通配置覆盖文档集字段的影子表。若选择方案 B，上述两个 pattern 改为普通 include，文件使用完整命名空间，不能仅把现有短字段文件直接放进合并树。

生成项目仍是 `tinysoul.toml + configs/ + home/ + .env.example`，不复制 common/standard/development 外壳、包代码或未选预设。使用 importlib.resources，保留隐藏模板文件，init 与 wheel 验证使用同一枚举。assets 只有静态资源，不 import Agent/Plugin，不决定执行器注册，也不从 TOML 动态 import handler。`infra/config/catalog` 的配置展示描述职责独立，本轮同步字段描述，不与模型动作定义混成一种资源协议。

### 8.4 读取、校验、编辑、reload 的同一闭环

推荐流程为：**assets 项目模板 → init → ProjectConfig 按统一声明读取 → ConfigEnvironment 携带普通设置与 catalog 文档 → Action owner 编译 → 各情景有效视图**。ProjectConfig 是文件入口，Action owner 解释定义，TurnProfile 消费有效能力；普通设置合并与独立对象校验使用各自数据语义，共用来源、修改事务、候选配置和 reload。运行时只读项目来源；缺失必要定义明确失败，不隐式从包资源补齐。

实施必须同时处理以下真实边界：

1. **独立对象身份与编辑。** 一份完整定义绑定一个源文件；重复 domain/action id、所属域不匹配、缺失必要定义由 Action loader 明确拒绝。`core.context.inspect` 是文件内字符串身份，schema 是原样携带的对象，均不被展平成普通配置路径。现有配置描述已以 `tool.schema` 整体编辑 schema；保留这条真实边界，覆盖含点号/数字属性、空对象和数组的往返验证。不为本轮 catalog 改成命名空间而先扩展全局路径语言；若将来确需编辑任意嵌套属性，再明确其公共路径契约。
2. **来源与候选一致性。** domain 默认、action 覆盖、情景选择均返回可解释来源；三个 profile 使用同一批候选文档。普通设置仍按已有优先级合并，文档定义不做同名深合并。include 或 document-set 声明允许变更时，候选校验必须使用对应的新文件集合；需要重启的进程级声明应明确拒绝热编辑并在重启重读，不能保存后悄悄使用旧集合。
3. **单次编译与三情景校验。** Action owner 接收同一 ConfigEnvironment 中的声明文档与自身普通设置，编译通用定义并校验各已装配 profile；不再自行扫描另一组包资源，也不让 Infra 知道 Home/Memory 授权。候选失败不替换活动 generation；持久化、显式 reload、旧服务失效仍使用已有 Agent/ConfigController 机制。
4. **统一编辑与查询。** 复用 ConfigDocumentSet/document_fields 的真实读取与编辑协议，更新 visibility 字段描述，不复制一个 Reflection 配置控制器。SDK/Endpoint 可按情景查询配置选择、实际可用动作及不可用原因，不能只返回 User 结果供 Reflection 配置页面误用；本轮同步后端协议和文档，不修改 visualization。三个情景的动作修改均经过同一 ConfigController、候选校验、文件事务和显式 reload。
5. **成套迁移。** 全部内置 domain/action（含 Reflection）移入公共模板，删除代码包旧 catalog 与 initializer 特殊拼接；同步 routing、Skill、配置描述、命令帮助、示例、测试和 package-data。历史 action id 不重写，新入口不保留旧名转发。

配置沿主计划允许的 `app → agent`、`maintenance → reflection` 改名。execution 的具体 shell/interpreter/输出设置合并为项目 `configs/execution.toml` 的 execution section；Job 通用容量与监督配置由 kernel/jobs 解释，web/resource 仍属 capabilities，不让 Plugin 重复维护全局 Job 预算。provider/model/tasks 的无关语义保持，必要路径基础设施变化须回归其真实读取与编辑契约。

本次设计不修改现有部署，不 reset 数据或覆盖自定义 catalog/Home Skill。实施需提供配置格式、开关位置、动作身份和生成资源变更清单与显式升级步骤；未知旧字段或不兼容存储 schema 明确失败，不暗中忽略或清空。

## 9. 各模块内部的层次与局部封装

### 9.1 本次复核与调整范围

这里的目标涵盖各后端一级模块及其已有子模块的内部组织，不止给 agent/kernel/environment 增加几个外层目录。保持现有顶层 owner，进一步识别同一 owner 内的协议、局部子系统、算法与适配边界。查看目录只是起点，还要拆开实际混合职责的大文件，收敛跨目录私有访问。

本次检查文件清单、代表性类/方法及调用依赖，得到以下具体依据；行数只用于定位阅读对象，不作为拆包或验收指标：

| 位置 | 现状与需要封装的职责 |
|---|---|
| `agent`、`llm` | 根目录各有 22 个 Python 文件；Agent 混放装配、调度、世代和观察；LLM 混放消息契约、任务执行与四份配置实现 |
| `kernel/context/segments.py` | 段描述/能力协议、注册对象、prepare/install 批次和活动实例管理在同一文件，适合区分 SPI 与运行集合 |
| `kernel/loop/phases.py` | 三个已有 PhaseUnit 与各自模型/执行适配同文件；可分成局部 phase 实现，但 PhaseFailure 与顺序执行仍共用 |
| `plugins/workspace/engine.py`、`actions.py` | 约 2376/1432 行，混合资源结果、归档读取、文件操作、索引一致性与多类 Action；删除 CAS/mirror 后按保留职责重组 |
| `plugins/home/overlay.py`、`review.py` | 状态/快照类型、codec/store、overlay 操作与审核提交混排；应按 overlay 与 review 子系统内聚 |
| `plugins/memory/documents.py`、`catalog.py` | 文档模型/codec，检索请求/结果/索引/排序/redirect 各混在单文件；需要文档、存储、检索的局部边界 |
| `plugins/archive/engine.py` | 一个约 848 行文件同时保存 journal/结果/owner 协议、日切流程与归档目录索引；文件少也可能需要封装 |
| `infra/config` | 来源、键路径、合并/文档快照、字段描述、候选修改与事务平铺；可按加载、描述、编辑职责组织 |
| `gateway/endpoint`、`llm/provider`、`runtime/{trap,signals,generation}` | 已有实际分层；复用已有边界并检查内部依赖，不为目录对称性重复包一层 |

Q7 建议把此项扩展为 R3 的完整后端内部组织核对，覆盖 infra/runtime/llm/kernel/plugins/environment/agent/gateway；仅处理职责封装、真实依赖和本轮必要消费者，不借此增加 S4–S7 的新业务功能。已合理的局部结构可以保留，新增 py 文件必须有明确职责。

### 9.2 封装规则

1. **owner 门面和局部实现分开。** 对外仍由已有 Engine/Builder、受约束 Service、插件入口和必要协议类型组成。子系统处理自己的具体工作；跨 owner 调用者不拿到 store/manager 的私有对象，也不自行拼装模块内部散件。
2. **子包以真实职责命名。** 如 overlay、review、retrieval、records、inspection、composition。只有实际存在多份相互协作实现时才成包，不给每个文件套同名目录，不机械套用 api/core/utils/services/models 五层模板。
3. **拆开聚合类的混合职责。** Engine 保留装配、一致性和服务协调，将文档 codec、检索算法、文件操作等交给内聚实现。采用明确组合依赖，不拆成读取 `self._engine._state` 的外部 helper，也不用多继承 mixin 把原大类摊开。
4. **状态只归属一次。** 一个子系统拥有其内部事实，Engine 通过明确方法协调；其它子系统消费引用、窄协议或不可变快照。不能让每个新目录各复制一份 manifest、overlay、catalog 或等待状态。锁与提交边界随事实 owner 保留，不因拆类分裂为几次半提交。
5. **共享契约位于实际依赖的低层。** 例如段协议独立于内置段、LLM 消息协议独立于 provider 与任务 runner。只为真实多方消费者抽出契约，不新建全仓 types/common/contracts 包。业务领域协议仍属于业务 owner。
6. **明确公共入口。** SDK 消费者使用包门面，插件可使用明确公布的 SPI 子包；其余子包默认模块私有。包根导出正式 API 是契约，不是旧路径兼容。内部实现直接依赖低层兄弟契约，不通过重新 import 顶层 SDK/Engine 或巨型 `__init__` 聚合器造成循环与重依赖加载。
7. **失败归属保持可见。** `errors.py`、稳定 failure 与 `runtime_bridge.py` 在所属 owner 边界；局部 parser/算法按该 owner 的结果或异常约定工作，不给每个新目录增加 Runtime bridge。Infra 不设置 bridge。

### 9.3 非领域模块的组织落点

| owner | 内部分组及迁移内容 | 局部边界 |
|---|---|---|
| `agent` | `composition/`：builder/assembly/跨插件动作与 profile 组合；`dispatch/`：scheduler/ingress/router/输入分派；`lifecycle/`：generation/day/runtime policy；`observation/`：输出路由/订阅；保留 `user/` | SDK、requests、handles、受约束 services 有清楚公共入口；三个业务分组协作持有同一 Agent，observation 只投影 |
| `kernel/action` | `catalog/`：spec/schema/parser/编译与情景策略；`planning/`：scope/rendering/ActionCall 归一化；`execution/`：batch/runner/hooks/executor/result；保留 `backends/`、`builtins/` | 先移走旧静态 catalog 再建立同名代码子包；必要 call/result 契约供 planning/execution 共用，不能让 planning 导入执行器 |
| `kernel/context` | `segments/`：协议/注册/prepare-install 集合；`builtin/`：identity/inputs/trace/plan 等内核段；`projection/`：composer/references/通用渲染；`control/`：控制工具/patch 解释 | ContextEngine 管本 Turn 的集合与组合；段 SPI 不依赖 builtin；Home/Memory 的内容语义仍在插件 |
| `kernel/loop` | `phases/`：已有 Phase1/2/3 实现与局部结果；`lifecycle/`：preparation/completion；`interaction/`：inbox/cancellation/已有等待处理；turn/cycle 保留单一执行骨架 | 抽取等待协作代码只引用同一 Turn 状态，不新增 TurnRunner/暂停控制器；协议失败边界和重放语义不变 |
| `kernel/jobs` | 从 registry 提取被 backend/segment/action 实际共用的模型与 backend 契约；registry/segment/actions 按当前职责保留，补通用回答约束与收尾边界 | 不为了增加目录层数细分每个类；只有一份 registry/终态/容量/回收 |
| `llm` | `protocol/`：消息/工具/请求/响应/模型描述；`config/`：类型与 section 解析；`execution/`：任务 runner/能力校验/模型与 provider 链调用；保留已有 `provider/` 层次 | ModelRegistry/路由现态归运行侧；协议不依赖 runner 或 SDK provider；不增一个与 LLMTaskRunner 平行的服务生命周期 |
| `runtime` | `control/` 聚合 scope/transfer/exception/frame_runner；复用已有 `trap/`、`signals/`、`generation/`；events/observation 保持各自事实协议 | 低层 frame/transfer 契约不反向依赖 runner；保留通用事件与 Signal 的语义差别，不建万能总线 |
| `infra/config` | `sources/`：project/TOML/dotenv/来源读取；`editing/`：候选修改与文件事务；`descriptors/`：字段描述模型/加载；ConfigEnvironment、公共路径/校验契约保持明确入口 | 所有业务配置共用读写基础，业务 parser 不下沉到 Infra；配置展示 TOML 仍为该 owner 的静态资源 |
| `infra` 其它 | 新增已确认 `process/`；如拆分 concurrency，则按 joined/resource scope/mailbox/lock 的实际职责归组；json 等已有边界保持 | 文件/时间等小而内聚的模块可以保留；不把全仓公共设施搬到某个 Plugin 内 |
| `environment` | `sources/`：terminal/scheduler 适配；inputs/services/error 契约留明确入口 | 向注入端口投递，无 Agent 私有依赖；真实新增 watcher 属 S4 |
| `gateway` | 复用已有 endpoint/{engine,http/routes,http/schemas,events}；initializer/instance 等项目工具可内聚为 `project/`，CLI/console 保持入口职责 | 只映射 SDK；不把 Endpoint 的 engine 命名误判为另一个业务 Engine；不扩任意文件 API |

Action 的 call/result 若是跨局部子系统的公共类型，应放 action 自身的公共契约位置，不因其最先服务 runner 就被迫依赖 execution 实现。LLM 配置也只依赖协议与 provider 的静态描述，不在解析配置时创建客户端。

迁移 CommonActionAssembly 时，User 与 Reflection 从 Agent composition 得到共享装配结果或类型化构造输入。Reflection 不反向 import Agent helper；不同 owner 的领域执行器不继续聚集在一个大装配类中，按插件声明由组合根组合。

### 9.4 领域 owner 内部细分

| owner | 建议内部组织 | 状态与提交约束 |
|---|---|---|
| `plugins/session` | `records/`：不可变记录类型/校验/存储/reconcile；`views/`：background/navigation/渐进投影/Memory 来源投影；completion 与 Service 保持 owner 边界 | 地图由同一 records 派生，不再保存另一份线性历史；外部只能经 Session 门面取视图 |
| `plugins/workspace` | `storage/`：manifest/文件提交/reconcile/Trash；`inspection/`：有界文本/图像读取、搜索与归档读取；`actions/`：资源查询、显式文件操作、LLM compose/analyze；projection 属 owner 视图 | 先删 CAS/mirror/压力 Trash，再拆保留操作；一个资源一致性边界，不把磁盘与 manifest 改为两个服务各自提交 |
| `plugins/home` | `content/`：布局/effective 内容读写；`overlay/`：模型/store/操作；`review/`：快照与审核提交；`skills/`：metadata/guidance/局部挂载；`actions/`：普通与审核动作 | overlay 与 actual 仍各只有一份事实；review 使用明确 overlay 协议，保留来源校验；Background 与技能挂载不混合 |
| `plugins/memory` | `documents/`：类型/Markdown codec；`storage/`：活动 Memory 与持久文档 store；`retrieval/`：catalog/词法与引用查询/redirect/embedding 派生缓存；`actions/`：inspect/recall、memorize、Reflection 写 | Active/Persistent store 的业务边界清楚；retrieval 可重建，不反向拥有 Markdown；Background 仍经 MemoryEngine 取投影 |
| `plugins/archive` | `transition/`：确定性日切协调/journal/恢复；catalog 与 projection 按其本来事实分离；保留现有公开生命周期门面 | 日切 journal 不因目录重构删除或转为通用事务平台；各 owner 仍解释自己归档内容 |
| `plugins/reflection` | 保留已有 `home/`、`memory/`、`turn/` 的情景准备与编排；根入口负责目标与候选来源 | 移除领域写执行器及专属 catalog；保留 Reflection 插件本身，情景目录不是行动域目录 |
| `plugins/execution` | `actions/`：run/start/stdin/collect；`process/`：唯一 ProcessJobBackend、输入输出协议；脚本/shell 来源准备作为局部实现 | `process/` 是 Job 到 infra/process 的适配，不重建 OS 进程管理；不恢复 script/shell 各自的 manager |
| `plugins/capabilities/web` | `operations/`：search/fetch/discover 各自流程；`backends/`：网络/抽取/发现算法与 worker 适配；已有 Service 和 Action 入口协调 | 真实受控 worker 入口同步迁移，底层算法不访问 Agent；结果经 Workspace 门面保存 |
| `plugins/capabilities/resource` | Service/Action/worker 契约已经有边界，按必要格式转换实现局部归组 | 文件少且职责集中时保留现有结构，不创建无消费者格式插件平台 |

以下以 Memory 为具体预览，展示职责细分与对外封装；不规定每个 owner 都复制同样目录：

```text
plugins/memory/
  __init__.py                  # 正式门面与协议导出
  engine.py                    # 装配、日绑定、存储与检索协调
  services.py                  # 普通服务与受约束知识写服务
  plugin.py
  config.py
  links.py
  background.py
  errors.py / failures.py / runtime_bridge.py
  documents/
    models.py
    codec.py
  storage/
    active.py
    persistent.py
  retrieval/
    catalog.py
    query.py
    embeddings.py
  actions/
    recall.py                  # inspect/recall 共用的只读任务
    memorize.py
    write.py                   # write/write_daily 的专属写能力
```

这里的 Service 不直接穿透 storage 私有对象，检索也不回调 Engine 私有方法；实例依赖由 Engine 组合。retrieval 中公开给 Service 的请求/结果通过正式协议导出，codec 的内部对象不自动变成 SDK 数据。每个动作一个 TOML 是配置维护粒度，不要求 Python 执行器也严格一动作一文件。

### 9.5 迁移及验收

随所属功能一次迁移实现、真实调用者、注册、worker 模块入口、测试和包资源；删除旧路径，保留正式公共导出，不增加旧路径转发文件。目录变化不得改变持久 Link/运行事实身份；需要变化的 Action id 只按第 6 节已确认清单处理。

每个调整模块交付简明的“原位置 → 新职责/位置 → 对外入口 → 状态/关闭 owner”核对记录。验收关注跨 owner 无私有访问、低层不反向依赖高层、一个事实只保存一次、原异常/取消/提交边界可解释，不能只列文件移动清单。

测试镜像最终职责组织；owner 契约覆盖一次，内部算法保留有区分度的用例，跨模块仅验证公共协作与代表路径。进行公开入口导入、wheel 后 worker 启动和边界依赖检查，不用固定文件数量或目录字符串快照代替行为验证。R3.6 收敛未随功能完成的 llm/runtime/infra/gateway 等内部整理；全轮仍以 Full/typecheck 与代表性 E2E 验收。

## 10. 实施切片与核对证据

R3.0–R3.7 已完成设计、实现、文档与验证；实际落点和核对证据见第 13 节。具体提交按内聚性拆分，每个切片必须同步调用者，不能借阶段划分留下损坏依赖。

| 切片 | 任务 | 完成所需证据 |
|---|---|---|
| R3.0 | 按已确认 Q1–Q4/Q8 细化，审阅 Q5/Q6/Q7；梳理各 owner 公共入口/内部子系统/失败流与基线 | 文件粒度与数据模型分别定稿；记录实际状态 owner 与允许依赖；把 §2.1 的调用闭环纳入所属切片 |
| R3.1 `done` | 移动跨 owner 装配；统一逐文件 Action 配置与情景可见性；迁移 assets 与 Reflection 动作 | User/Home/Memory 共用一套声明文档、编辑/校验/reload；重复身份拒绝；init/wheel 可加载，无 Reflection 装载旁路 |
| R3.2 `done` | Workspace 轻量化与动作收敛；同步 Service、Endpoint、资源转换 | 无 CAS/retention/压力删除；编辑全或无、分页/regex 预算、Trash/目录/标签/归档正反路径 |
| R3.3 `done` | 独立 execution、移除 mirror/apply 状态、统一 Job/受控进程生命周期及 Turn 收尾消费 | bounded/background 同后端；回收不依赖 collect；跨午夜归属正确；附属清理失败不阻断，真实存活失败不伪造收敛、不被 Turn 吞掉 |
| R3.4 `done` | Session 事实地图与有界投影 | 问答/追加/追问/行动/终态均可追溯；无平行历史；图可重建、跨日 ref 不串根 |
| R3.5 `done` | 今天/历史 Memory Reflection，删除持久 availability | 无 daily 完整整理、有 daily 修订补充；无冻结标记；自动请求不因已有 daily 跳过；重启重建候选 |
| R3.6 `done` | 按 §9 完成所有后端一级 owner 的内部组织核对，收敛剩余 llm/runtime/infra/gateway 等局部封装与配置改名 | 原位置→职责/位置→公共入口→状态/关闭 owner 可核对；无循环依赖、私有捷径或旧入口；SDK/三 profile/worker 可运行 |
| R3.7 `done` | 文档、测试、打包、主计划逐项核对 | Full/typecheck、代表性离线 E2E、删改清单及延后项记录完整 |

R3.1 按选定 Q5 数据模型统一项目 catalog 与三情景消费，同步 visibility、字段描述、编辑、生成和资源枚举，再删除旧旁路；按本稿推荐方案保留独立文档协议，不再以全局配置路径改造作为前置条件。R3.2 是 R3.3 的资源语义前提；R3.4 与来源投影完成后再做 R3.5。内部职责拆分随所属功能推进，R3.6 核对全部一级模块并收敛剩余项，不预先做一次覆盖全仓的大搬家。

切片编号是职责与核对顺序，不表示可以留下暂时损坏的消费者。R3.1 先统一已可执行定义的来源，并完成 Home/Memory 动作归位；Workspace/execution 的新动作名随各自执行器与测试一起切换，不在模板中提前发布无法装配的定义。旧 execution 依赖 Workspace mirror/CAS，因此 R3.2/R3.3 的相关删除必须作为联动迁移单元：同步调用者后再删旧接口，必要时合为一个可验证提交，不添加临时兼容 Service 或旧名转发来维持中间状态。

### 10.1 必须清理的活跃遗留

- 分散 Action catalog、Reflection 包内专属 loader、重复 Action 定义/旧 id alias。
- script/shell/supervised_process 三套上层状态与配置、mirror/apply/discard/read_candidate、脚本专用重复编辑流程；仅改名未取消的 registry/manager 平行状态。
- Workspace expected_digest/revision/read-set/described_digest/retention、pressure reclaimer、Trash marker 和恢复 Trap。
- availability 文件作为 backlog 真相、只支持归档日的单一来源假设、已有 daily 就跳过请求的判断。
- `assets/project` 与 config_profiles 层、Action catalog 特殊初始化拼接、Reflection 运行时直接读包资源及 home_reflection/memory_reflection 专属 domain 目录；独立配置文档协议保留。
- runtime.enabled 与 loop/reflection 平行可见性表；仅显示 User 作用域的跨情景配置查询假设。
- 纯受控进程设施的 Action 业务依赖；已知进程仍存活却被 closed/移除 Job 掩盖的路径。附属清理诊断继续保留，不改成全局阻断。
- capabilities 的跨 owner 组合根、上层绕过门面访问私有存储、无消费者类型与返回字段。

历史分析文档与已保存 Turn 中的旧名不属于需擦除的代码残余。Home review、Archive journal、Session view cursor 等独立协议须按消费者保留，不能用全仓关键词替换误删。

### 10.2 测试契约

| owner/边界 | 代表性验证 |
|---|---|
| Session | record 幂等与冲突、索引修复；ask/reply/append/reason/answer；cancelled/not_executed/unknown；分页与最低投影；旧日同名资源；Reflection 不入 User Session |
| Workspace | write/create/replace 语义；edit 歧义/后项失败不半写；目录 move/restore 冲突；标签保留；读取/search 覆盖与 regex 超时；Context 压力不移动文件；磁盘成功后索引失败不虚报无副作用 |
| Reflection/Home/Memory | 同 domain action 权限；伪造 handler/id 与直接批次拒绝；当天来源快照/历史只读；已有上午/下午可调整并补晚上；自动与手动均可更新已有 daily；重启重算候选；单文档部分成功；redirect 校验 |
| execution/Job | bounded run/start/stdin/collect 共用后端；多次 collect 不重复执行；终态不占活任务额度、结果保留有界；stop/取消/退出竞争；大输出分页落盘；活 Job 阻止回答、受控执行已停止的终态不因附属清理错误阻止；文件副作用不回滚 |
| 日切/监督 | Job 跨午夜维持旧 Workspace；等待用户/预算仍占执行位置；正常/取消收尾先停止进程再归档；临时失败在有界复查后可继续；附属清理失败保留诊断且不阻断；受控进程明确存活且无法停止不伪造收敛；无全局清理失败开关 |
| 装配与 SDK | owner 服务失效仍按 generation/day；候选装配失败不损坏旧世代；User/两 Reflection 共用框架；公共入口与 SPI 可导入；跨 owner 无私有访问；worker 在 wheel 安装后可启动 |
| Config/Action | 逐 domain/action 文档身份、域匹配与来源；重复身份拒绝；完整 schema（含特殊属性名/空对象/数组）编辑往返；候选文档一致；已确认选择优先级与未授权启用拒绝；三情景有效视图和 reload 一致 |
| 失败闭环 | 未知 Job 与 backend 契约失败分流；Home/Workspace owner IO 失败不伪装为参数反馈；注入异常文本不进入模型结果；Turn activity cleanup 不吞 Runtime 转移；保留主失败和必要收尾失败 |
| assets/生成/wheel | 隐藏文件与模板完整；common + 选中预设拒绝重复目标；不复制包代码/未选预设；无 catalog 特殊拼接；standard/development init 与 wheel 后三情景装配 |
| Endpoint | 新 Workspace/Reflection 契约映射到同一 Service；不保留旧 CAS 请求字段；修改 docs/endpoint，同轮不改 visualization |

同一契约由 owner 完整覆盖一次；跨模块只测代表路径。重写或删除固化 CAS、mirror、提示词全文、固定文件数的旧测试，不通过宽泛 skip 维持假绿。

实施期使用 Conda `TinySoul`，按聚焦路径 → Fast → Full → typecheck 验证。最终必须运行：

```powershell
conda activate TinySoul
.\scripts\test.ps1 -Suite Full
.\scripts\typecheck.ps1
```

Full 包含 generation/wheel 的本地验收；真实 provider/network 用例按 explicit external 开关单列，未运行如实记录。不要将 R2 历史门禁结果写作 R3 验证证据。

## 11. 文档与完成条件

实施同步更新 `docs/design/` 中实际受影响的 agent/action/context/loop/session/workspace/home/memory/reflection/capabilities、Job/execution、llm/runtime/infra 与项目配置设计，以及 `docs/endpoint/` 的 Workspace、配置与 Reflection 契约；已有文档按实际文件名归位，独立 execution 的设计放在有明确 owner 的位置，不额外复制同义文档。设计文档解释内部职责和依赖，不堆文件列表；详细迁移核对留本计划。同步 package-owned config、Skill、README/命令示例。AGENTS 只更新必要过渡条款，整体重写仍在 S7。

- [x] Q1–Q4 已按最新讨论确认，Q3 原来源冻结建议撤回，execution/Job/process 分工确认。
- [x] Q8/domain 默认选择可由单动作覆盖的语义已确认，不再重复提问。
- [x] Q5/Q6/Q7 的统一配置、清理失败分类、内部组织建议和本轮执行范围已审阅确认：采用 Q5/A，Q6 与 Q7 按本文边界实施。
- [x] R3.1–R3.6 对应实现、调用者、失败边界与测试逐项核对。
- [x] 各后端一级 owner 的内部组织已逐项核对；新子包有职责与局部封装，公共门面清楚，无旧路径转发或无消费者抽象。
- [x] domain/action 各自独立 TOML，统一配置生命周期与一份情景选择规则；无 Reflection 专属域，catalog 单一包来源，权限不由可编辑文件授予。
- [x] Full/typecheck/生成安装和代表性 E2E 有实际结果。
- [x] 设计和 Endpoint 文档只描述已落地行为；新旧配置/动作/持久格式变化写明，不重置部署数据。
- [x] 回填主计划 S3 已完成与残余项，明确 organize 延后，不误勾 S4–S7。
- [x] 满足上述条件后，才将本计划标记 done，文件名加 `-done-` 并移动至 `docs/analysis/done/`。

R3 完成证据见第 13 节，未沿用 R2 门禁结果。S3 仍有明确延后项，不宣称主计划全部完成。

## 12. 决策与方案审阅

| 编号/状态 | 结论或建议 | 实际影响 |
|---|---|---|
| Q1 `confirmed` | 通用 `memory` domain，普通 `core.memory.*` 同步迁为 `memory.*`，Reflection 写动作同组按情景开放 | Phase1 中记忆成为独立规划域，Skill/配置/动作身份一起迁移 |
| Q2 `confirmed` | execution 直接使用真实当日 Workspace，删除 mirror/apply/discard | 文件即时改变，取消不回滚，collect 只读结果；默认独立输出目录 |
| Q3 `confirmed` | 没有 daily 就整理完整文档，已有 daily 就读取后修订、重组并补充 | 无冻结来源标记，自动整理不因文件存在而跳过；触发去重与文件内容分开 |
| Q4 `confirmed` | execution 移至 `plugins/execution`；公共 Job 监督在 kernel/jobs，共用进程原语归 infra/process | bounded/background 使用同一后端与 Job 生命周期；capabilities 保留 web/resource |
| Q5 `confirmed` | 每个 domain/action 独立 TOML；采用 A：统一配置中的独立定义文档；assets/common、standard、development 直属 assets | 保留文档读取/编辑协议，删除分散资源及 Reflection 旁路与双开关表；不建专属 Reflection 域，不深合并同名 Action |
| Q6 `confirmed` | 清理异常先局部恢复和诊断；仅有证据的进程存活/实际依赖契约失败进入既有模块 bridge | 不加全局清理失败闸门；日志/临时文件清理失败不阻断日切，已知活进程不伪造停止 |
| Q7 `confirmed` | 对全部后端一级模块及已有子模块做内部职责封装，具体迁移与 Memory 示例见 §9 | 包含 Home/Memory/Workspace 的存储与查询、LLM 协议/执行、Infra Config 加载/编辑等；同步门面、状态/失败边界和测试 |
| Q8 `confirmed` | domain 是可覆盖默认值；单动作可覆盖域选择，优先级按动作情景→域情景→动作默认→域默认→true | 配置文件粒度与加载模型不影响这条策略；可见性不授予服务权限 |

D1–D3、D5–D8/Q1–Q4/Q8 不再重复申请确认。本次重点审阅 Q5 的独立文件与加载数据模型，以及 Q7 扩展到各模块内部的职责封装；Q6 沿用上次清理分类建议。方案已确认并按本计划实施，实际核对记录见第 13 节；后续若发现真实契约冲突，先呈现证据与选择，不用兼容层或私有访问绕过。

2026-09-19 实施核对：用户已明确确认完整方案并授权实施，Q5/A、Q6 与 Q7 均为 confirmed。上文保留的方案比较记录解释设计取舍，不构成新的审批关卡；若实施发现真实契约冲突，仍按 AGENTS 讨论。

## 13. 实施核对记录

状态：`done`。实现、调用者、失败归属、设计文档和必要验证已核对；Full/typecheck 与独立生成/wheel 均通过。

### 13.1 切片与实际落点

| 切片 | 当前实现与核对证据 |
|---|---|
| R3.0 `done` | Q1–Q8 已确认；按基线复核公共门面、owner、失败与清理流程，§2.1 的装配权限、必要收尾和来源绑定缺口已纳入对应实现与测试。 |
| R3.1 `done` | Agent composition 显式组合真实 Plugin；三个 profile 共享项目 Action 文档及 JobRegistry。Action catalog 严格校验逐文件身份，visibility 使用已确认优先级；grants/受约束服务不由配置授予。assets/common + standard/development 生成，删除分散 catalog 和 Reflection loader。配置编辑、三情景权限、伪造 handler、候选 reload 测试覆盖。 |
| R3.2 `done` | Workspace storage/inspection/actions 分工，manifest v4 包含目录、说明与标签；删 CAS/read-set/retention/mirror/压力 Trash/恢复 Trap。显式文件操作、compose/analyze、Service/Endpoint/Web/Resource 同步。编辑全或无、标签保留、损坏 Trash、扫描覆盖、regex 超时、提交后索引失败、Context 不删除文件均有回归。 |
| R3.3 `done` | plugins/execution 使用唯一 ProcessJobBackend，kernel/jobs 保存监督现态，infra/process 共用受控进程。bounded/background、stdin/collect、容量/终态/停止与必要失败分流有测试。Agent activity 收尾先回收 Jobs 再同步 Workspace；真实进程跨午夜取消、旧文件归档与旧服务失效已通过 SDK 路径核验。 |
| R3.4 `done` | Session record v9 与 manifest v3；records 保存唯一完成事实，views 派生 Map/Background/inspect/Memory 来源。输入、ask/reply、typed Action 与跨日引用可追溯；分页绑定固定来源，schema 不静默迁移。organize/模型推导注释按 D1 延后。 |
| R3.5 `done` | Reflection 来源在执行准备时绑定当前日、归档日或仅已有 daily；请求目标日保持固定。手动与自动均可改写已有 daily；availability 由 owner 目录分页重算，没有持久完成标记。SDK 测试覆盖当天/归档/只有 daily 的重复整理，两类 Reflection 不写 User Session。 |
| R3.6 `done` | 各后端 owner 完成下表核对；公共门面/内部协议分层，没有旧路径转发文件。config section 为 agent/reflection，execution/jobs 分别归能力和监督 owner；终端 /reflection、Endpoint /v1/reflection 与 reflection.* 事件同步。测试按职责子包迁移，保留少量 owner 门面集成测试。 |
| R3.7 `done` | 受影响 design/endpoint、默认 Skill、README/命令和 AGENTS 过渡条款同步；生成项目、wheel 与最终门禁结果见 §13.4；主计划已回填，S3 的 organize/推导注释仍为延后范围。 |

### 13.2 内部职责与生命周期核对

| 原位置 | 新职责/位置 | 对外入口 | 状态与关闭 owner |
|---|---|---|---|
| Agent 根部 builder/assembly、跨 owner capability assembly | agent/composition；根请求与输入进 dispatch；日期/世代进 lifecycle；旁路输出进 observation | Agent/AgentBuilder/AgentAssembly、受约束服务 | Agent 世代与根调度器；同一 JobRegistry，Plugin 不反向 import Agent |
| action/core | catalog/planning/execution；call/result 保留公共契约 | ActionEngine/Builder 与 executor SPI | Action runner 拥有当前批次，Job 不放入 Action 结果状态机 |
| context/segments.py、core/trace/working/composer/controls | segments 协议/注册/活动集合，builtin，projection，control | ContextEngine/Builder、段协议 | TurnSegments 只管理本 Turn 视图；领域事实仍在各 owner |
| loop/phases.py、preparation/completion/inbox/cancellation | phases/contracts + 三 Phase；lifecycle；interaction | TurnProfile/TurnRunner 与公共内核构造 | 唯一 Turn/Cycle 生命周期；activity 必要失败可保留 Runtime 转移 |
| jobs/registry.py 混合静态类型与运行表 | models 与 registry | JobRegistry/JobBackend/JobSnapshot | 只有 registry 维护身份、容量、终态与回收 |
| llm 根部协议/执行/配置文件 | protocol、execution、config；保留 provider | LLMTaskRunner、配置解析和协议 | 活动路由/registry 归 execution；provider client 由所属 Generation 关闭 |
| runtime scope/transfer/exception/frame_runner | control；保留 trap/signals/generation | runtime 公共导出 | 不新增业务状态，不反向依赖 kernel/plugins |
| infra/config project/TOML/dotenv/source/controller/catalog | sources、editing、descriptors；通用进程归 infra/process | ConfigEnvironment/Controller、ManagedProcessRunner | 文件事务归 ConfigController；进程句柄归 ManagedProcess，不了解 Turn/Job |
| environment terminal/scheduler | sources | InputSource/AgentRequestSource | 来源启动/停止由 Agent 装配，向注入端口投递 |
| gateway initializer/instance | project；已有 endpoint 分层保留 | CLI/项目工具、EndpointEngine | 项目锁和服务器归进程外壳，业务经 SDK |
| Session 根部记录/索引/投影 | records、views | SessionEngine/Service | 不可变 record 是唯一事实；图/索引可重建 |
| Workspace 大 Engine/actions 与 CAS/mirror | storage、inspection、actions，瘦 Engine | WorkspaceEngine/Service、ArchiveView | 一个文件/索引提交边界，Workspace 管当前日与 Trash |
| Home overlay/review 混合文件 | content、skills、overlay、review、actions | AgentHomeEngine、HomeService/HomeReviewService | actual/overlay 各一份事实；审核来源 token 保留 |
| Memory documents/catalog 混合文件 | documents、storage、retrieval、actions | MemoryEngine、MemoryService/MemoryKnowledgeService | Markdown 唯一持久事实，检索/embedding 可删除重建 |
| Archive 大 engine | transition 的契约/journal/协调，catalog 与 projection | DailyLifecycleCoordinator/ArchiveReader | 日锁与 journal 仍由 Archive 协调，不移入 Reflection |
| Reflection 领域动作与单一历史来源 | home/memory/turn 保留情景编排，动作归 Home/Memory | ReflectionBuilder/Engine | 根请求仍由 Agent 排队；可用性只是内存投影 |
| script/shell/supervised_process | plugins/execution | ExecutionEngine、显式 action registrar | 短而内聚的 engine/actions/backend 文件保留，未为形式对称加单文件目录；运行状态仅在 JobRegistry |
| web service 中的规范化/worker 算法 | operations、backends | WebService 与 Actions | 无独立持久 store；worker 受 Action 生命周期约束 |
| resource 小而聚焦的 Service/Action/worker | 保留既有局部边界，调用新版 Workspace | ResourceConversionService/Actions | staging 临时文件归资源作用域，输出归 Workspace |

清理了无人消费的 LLM Action protected_resource_links；容量异常保持 owner 原始转移。Endpoint Workspace 不重复转换 SDK 失败，统一 HTTP 边界保留 service.stale/agent.not_ready；移除旧 Digest header 声明。Home review token、Archive journal、Session continuation 和 Memory 检索摘要属于不同的有效协议，未做全仓 digest/revision 关键词删除。

### 13.3 格式变化与部署边界

本轮修改仓库代码、包资源和测试，没有运行 reset、覆盖现有部署或改写历史数据。以下变化不提供兼容别名：

- 配置：`configs/app.toml [app]` → `configs/agent.toml [agent]`；`configs/maintenance.toml [maintenance]` → `configs/reflection.toml [reflection]`。对应环境覆盖使用新 section；script/shell 配置归 `configs/execution.toml`，公共监督上限归 `configs/jobs.toml`。
- 动作：第 5/6/7 节的新集合取代旧 Workspace、core.memory、Reflection 与 Script/Shell 名称；每个 domain/action 仍独立 TOML，开关统一为 visibility。旧 runtime.enabled、loop/reflection 动作选择表拒绝。
- 协议：终端使用 `/reflection`；HTTP 使用 `/v1/reflection`；生命周期观察使用 `reflection.*`。Workspace HTTP 去除 CAS 字段并增加目录、移动、编辑、追加与标签。前端适配说明已同步，本轮未修改 visualization。
- 存储：Session record v9、manifest v3；Workspace manifest v4 与简单 Trash 元数据。旧 schema 明确失败，不自动清空、重写或迁移；旧日志中的 action 名称保持历史身份。
- 资源：包内唯一默认 Home/catalog 在 assets/common，两种初始化预设直属 assets。旧自定义 catalog/Skill 不能直接覆盖新模板，须按动作身份与情景规则合并。

升级顺序：停止旧进程并保留原 checkout 和完整数据副本；在独立空目录用新 init 生成项目并校验；将自定义配置、凭据和 Home/Skill 按新结构显式合并；旧 Session/Workspace/Trash 需先离线转换并通过当前 owner 校验再挂载，仓库不提供自动转换器，不能靠删除 manifest 规避含人工元数据的格式变化；验证后再切换启动路径。可继续在旧 checkout 使用原数据，本轮验证只在隔离测试项目完成。

### 13.4 验证记录

2026-09-19，Conda TinySoul（通过 TINYSOUL_PYTHON 显式选择）执行：

| 验证 | 结果与边界 |
|---|---|
| 聚焦 owner/SDK/Endpoint | Workspace 69 passed；Endpoint 最终 27 passed。真实子进程跨午夜 SDK 用例、Reflection 当前/归档/仅 daily 来源的重复整理均纳入最终 Full。 |
| Fast | 1057 passed、28 deselected；此后新增的提交边界及 SDK 错误映射回归在聚焦测试和最终 Full 中通过。 |
| Generation | 5 passed、1084 deselected；standard/development init、wheel 隔离安装、三 profile 装配及安装后两个 worker 的结构化启动/请求失败验证通过，无真实网络调用。 |
| Full | **1066 passed、23 deselected**；包含本地业务、生成与 wheel，运行目录 `.local-test/runs/9005ad670b10480db76fdd47cb4b489b`。 |
| typecheck | `scripts/typecheck.ps1`：All checks passed。 |
| 差异与依赖 | `git diff --check` 通过；公共入口和依赖方向测试纳入 Full，无旧路径转发层。 |

Full 首次检查暴露的两项生成测试仍读取旧 script/shell 配置，已改为验证统一 execution 配置；最终全量重跑通过。测试仅留下 Starlette 对 httpx 的既有弃用提示，未改变依赖协议。

真实 provider/network 未运行；23 项 external 按套件语义排除，不作为本轮完成证据。未提交 Git、未修改 visualization、未 reset 或迁移实际部署数据。

后续范围：Session organize/模型推导注释继续留在主计划 S3；S4 环境与监督、S5 Gateway v2、S6 ACP/MCP、S7 全仓规约整理均未因此标记完成。
