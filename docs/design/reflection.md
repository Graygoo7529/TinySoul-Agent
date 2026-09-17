# Reflection 与日切设计

## 所有权

`plugins/reflection` 编排 Home 与 Memory 的模型维护任务、维护可用性投影；`agent/day` 拥有日期决策；`plugins/archive` 协调确定性归档。Reflection 是同一个 Agent 的专门执行情景，由 Home/Memory TurnProfile 提供整理提示、语境与插件能力；它与 User Turn 同级，复用同一 Turn/Cycle/Phase 和 Action 内核，不写 User Session。普通对话不挂载 Reflection 提示、整理请求动作或专属持久写服务。

Terminal、Endpoint 和定时来源只能提交 typed request。Agent 将 daily 触发拆成独立 Home 与前一日 Memory work；Memory 请求必须有明确 target_day。执行日始终是 Agent 持有的当前 CalendarDay，历史目标不修改执行日或当前工作区。

## 日切与归档

DailyLifecycleCoordinator 的 read/write lease 协调活动访问和排他日切。初始化顺序为 Session root、空活动 Memory.md、Workspace；归档前由 Memory owner 校验活动记忆，Session 连同 Memory.md 归档，然后归档 Workspace/Trash 并初始化新日。Home overlay 与持久 memory 跨日保留。

pending transition journal 记录已完成的 owner 步骤，可在启动时恢复。完成布局为 archive/catalog.json 和按时间戳冻结的目录，后者包含 transition.json、session、workspace、trash。ArchiveProjection 只提供日期和 owner 可用的只读来源位置；Reflection 不自行拼接 Memory 或 Session 私有路径。

Agent 启动和每项 work 前运行日切，随后刷新 Reflection availability；短文件操作等待完成后才传播取消。跨午夜活跃 Turn 的 day lease 持续到收尾结束，新日工作等待该 lease 释放。日切不依赖 LLM。

## 请求与 availability

手动入口表示用户明确允许本次指定整理：`/maintenance home [整理要求]` 或 `/maintenance memory YYYY-MM-DD [整理要求]`，HTTP/SDK 传递同义 typed request 与 instructions。每次授权产生一个独立排队 Turn，不抢占活动根、不形成持续许可；受理回执与完成结果分别报告。daily 只供自动策略，在 Agent 边界拆成独立 Home 与前一日 Memory 请求；按触发日/profile 去重。自动 Memory 在 daily 已存在时跳过，手动目标仍可复查。定时源不执行任务、不保存业务 cursor，启动晚于计划时刻不追补。

runtime/maintenance/availability.json 是可重算的待办投影：保存检查日、Home 待审计数和 Memory 日期。新关闭日来自 Archive transition，既有 backlog 跨重启保留；任务执行前仍查询真实 owner。缺失来源或 Session facts/活动 Memory 同时为空是 skipped，已存在但损坏的资料是模块失败。availability 不承担完成事实或审批状态。

## 三种 TurnProfile

三 profile 使用独立 Context/Action 视图、相同执行骨架和 core.answer 完成意图。User 使用 effective Home，只能改 runtime overlay 和活动 Memory。Home/Memory Reflection 使用 actual Home 作为判断基线，同时保留通用域和当前 Workspace 工作台，再增加各自专属写域；不会相互取得另一种持久写 Action。

Home 使用当前 Session、Workspace、memory:current 与可选 latest。Memory 使用目标归档 Session、目标活动 Memory 和严格早于目标日的 latest，当前 Workspace 仍可操作。历史 Workspace 以只读 workspace_archive 段提供日期引用，经 core.context.inspect 分页检查；不会冒充今日 workspace: 资源。

core.ask 可以在确有信息缺口时暂停同一 Reflection Turn，回复、预算和取消仍由同一 Inbox 处理。core.answer 在 Reflection 中保存完成总结，不发布用户正式回答，也不写 User Session；等待超时、停止、耗尽和失败保留通用 TurnOutcome。

情景策略分别配置于 `loop.user.actions`、`maintenance.home.actions` 和 `maintenance.memory.actions`。domains 设域默认，actions 按稳定 Action id 覆盖；未指定时沿用 catalog 默认。策略只在装配已授予能力内筛选，不能开启另一情景的持久写或不可用 backend。Phase1、Phase2 与实际批次执行使用同一有效视图，共享 catalog 不被修改；未知身份明确拒绝。HomeReviewService 和 MemoryKnowledgeService 只注入对应情景，通用服务不暴露持久提交或日生命周期操作。Reflection 动作仍位于 home_reflection/memory_reflection 域。

## Home Reflection

Home owner 提供 diff snapshot 与基于 token/version 的接受/拒绝；Reflection actions 只按稳定 Home Link 选择条目并返回逐项结果。home_reflection.diff 无选择时给目录，明确选择时展开差异；home_reflection.review 接受或拒绝选项。

改写通过通用 home actions 修改 effective overlay，再重新 diff/review。只有 SKILL_MEMORY 的条目不能直接 accept，需要先把经验落实到有效 skill 修改，或拒绝该条。批量 review 逐项提交，失败不撤销已经成功的条目。Turn 结束时报告剩余计数，仅在 owner 确认全部解决后清除空 overlay；core.answer 不伪称所有 diff 已解决。

## Memory Reflection

任务先校验目标是关闭日，归档 Session 和 Memory.md 存在且有效，再绑定只读来源。模型通过通用 inspect/recall 查已有知识、通过 Context inspect 查来源；提示要求少量多步地复用、修正与沉淀。

memory_reflection.write_daily 写目标日完整 daily；memory_reflection.write 写一份 entity/concept/fact/note Markdown。Memory owner 校验完整候选 catalog 后原子替换单文档。引用或 redirect 目标须先存在，因此模型先建立目标再迁移来源；此前成功文档不会因后续写入失败而回滚。

没有 draft/preview/commit 八步控制器、多文档事务或专用 maintenance.complete。task 的本轮绑定只保存 target 与只读来源，清理不撤销已接受持久写入。

## 失败与观察

可修正参数和 review/write 拒绝是局部 ActionResult；损坏存储、契约或配置错误在所属 owner 边界归类并由 owner bridge 映射。Reflection task 的已知 I/O 失败形成有限 task outcome；Runtime transfer 与取消保留原身份。取消后的 ReflectionOutcome 保留 task kind、target_day、底层 TurnOutcome 与已提交事实；不会返回裸 User outcome。准备、可用性和清理文件操作均通过 joined owner 边界完成。

必要 Turn finish 失败阻止成功发布，close 失败保留诊断。Observation 只提供请求身份、执行/目标日期、状态、计数和有限错误类型；不替代业务事实。maintenance.started/completed 中 business_day 与内层 turn.started 都是当前执行日，target_day 单独表达历史来源。
