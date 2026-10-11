# Job 身份、等待唤醒与执行结果读取

状态：`done`（2026-10-11）。实施、文档同步、Fast/Full 回归和 `ty` 类型检查均已完成；以下方案已按代码和验证结果核对。

## 目标与设计依据

保持一个 `core.wait`，使后台执行、状态刷新、唤醒和结果读取各自具有清楚的职责。Job 身份使用简短、稳定且能解释所属 Turn 的编码；模型在完成通知之后应能发现正确的结果读取入口。

依据 AGENTS.md：Agent 分配正式 Turn 身份并调度根 work；JobRegistry 监督 Turn-owned Job，backend 持有执行资源；Workspace 管文件及其读取；Inbox 管受理和等待；Phase1 按域级语义选能力，Phase2 只能调用已选域工具。Signal 刷新状态，EnvironmentEvent 进入 Inbox，Observation 提供旁路观察，三者不互相替代。

## 当前事实与问题

检查了 `reference/traces/turns` 的五份 Session Turn 记录，并沿 Action、Job、Inbox、Workspace 和 LLM 协议实现核对。它们是已结算事实，未包含每次模型请求的完整工具作用域、供应商响应和运行配置，不能据此确定所有模型失败的根因。

| 观察 | 判断 |
| --- | --- |
| Shell 请求收到 interpreter 未启用的短反馈后改用 PowerShell 成功；Python source 请求成功 | 统一 execution.run、静态 enum 与局部失败反馈正常工作 |
| 两次后台执行均完成，等待均收到 `reason=job` 和相应 job_id | Job 监督、终态投递和唤醒主线有效 |
| 有输出的后台任务三次 wait 分别由 event、event、job 恢复；无 stdout 中间输出的任务也先被 stderr 文件事件唤醒 | 环境变化的隐式中断范围过宽；普通输出正在间接触发决策 |
| 文件事件的 wait_resumed 中 topic/source 为 null，随后事件事实却包含真实来源 | 恢复记录使用了等待过滤条件，没有携带实际匹配事件的来源 |
| 一轮在任务已成功后查询五次 status，误用 Context inspect 读取 Workspace，再搜索历史 | 结果发现和域选择不顺畅；status 不提供正文是正确边界 |
| 一轮出现 12 次 Phase 失败：7 次缺少域选择，3 次输出截断，2 次越出工具作用域；另一轮出现 1 次输出截断 | 局部失败收敛有效，但模型决策不稳定，不能把它们全部归因于 wait |
| Job 输出目录被当作回答参考正文加载失败；Workspace 投影把 `.log` 文件标成 binary | 目录定位、输出文件和可加载正文的语义存在缺口 |

五轮最终均为 answered，没有记录 Turn failure 或 finish failure；这说明本次收敛成功，不等于每步决策都合理。最后一轮并未读取 stderr 正文，回答却称它“仅含 CLIXML 进度噪声、无错误”，证据不足；exit code 与字节数不能证明正文内容。

本次改进只处理已确认的身份、等待唤醒和结果可读性问题；第 5 轮回答的证据充分性以及 Phase1/Phase2 失败次数不在本次实施范围内。

## 方案一：复用 Turn 身份分配简短 Job 编号

建议唯一的正式 `job_id` 使用 `YYYYMMDD-<turn_sequence>-<job_sequence>`，例如 `20261011-5-1` 表示活动日第 5 个 Turn 启动的第 1 个 Job。这个形式已确认采用。编号不包含 Job 类型，类型继续由现有 `kind` 表达，如 `execution.process`、`subagent.acp`。

单独的 `acp-1` 在不同 Turn 会重名，而 Job 产物存于同一个当日 Workspace。`YYYYMMDD-1` 若表示日内 Job 序号，需要额外的跨重启分配事实。现有 `TurnIdentity` 和 AgentDayCoordinator 已提供持久递增的 Turn 身份；复用它，再加本轮序号，能够直接利用现有生命周期保证。无需另存 UUID、显示别名或 Job 日级计数文件。

`acp-1` 作为 Turn 内局部身份也可行，但 Registry 键、产物路径和历史呈现必须始终携带所属 Turn。这里推荐完整组合编号，让同一身份在调用、事件和资源路径中都能独立辨认；类型的业务含义仍从 kind 取得。

实施要点：

- JobRegistry 使用现有 `TurnIdentity` 解析所属 Turn，并维护本轮下一个 Job 序号；在调用异步 factory 前递增。启动失败也不重用已分配序号，避免与已产生的文件混淆；Turn 清理时可以移除本轮内存计数，因为同一个正式 Turn 不会再次启动 Job。
- process 与 ACP 共用同一个本轮序列，run 内部复用 Job 也参与编号；编号不承诺连续。
- Workspace.prepare_execution 只校验该值能作为单个安全路径分量；去掉其对 UUID 格式的私有假设，正式 Job 编码归 JobRegistry。
- status/stop/collect、通知、continuation、日志路径与 Endpoint 使用同一个 job_id。Job 仍只在所属 Turn 可操作，保存的产物仍通过 Workspace ref 读取。
- 测试改用正式 Turn 身份；当前开发数据不增加旧编号兼容分支。Endpoint 字段仍是字符串，文档和示例同步新编码；前端不应从编号解析业务状态或类型。

预计代码位置：`kernel/jobs/registry.py` 负责分配，`kernel/identity.py` 提供日期和 Turn 序号解析，`plugins/workspace/engine.py` 只校验安全路径分量，不再校验 UUID 正则；`plugins/execution`、ACP backend、Endpoint schema/examples 和 Job 测试只消费该字符串，不各自生成或解释编号。

## 方案二：区分状态刷新与隐式唤醒

现有 Workspace 插件已经声明 `workspace.changed` 为 `coalesce=True, requires_decision=False`。Inbox.accept_event 保留了该信息，但 `_ready` / `_matches_event` 对 Job 等待的环境中断没有使用它。独立内存复现确认：一个 requires_decision=False 的文件事件就能使 Job wait 返回 WakeReason.EVENT。

建议将已有“需要决策 / 只刷新状态”的语义用于隐式中断，不增加 Action 或模型参数。核心变化只在 Inbox 的匹配判定：`_ready` 把 `InboxRecord.requires_decision` 传入 `_matches_event`；`event_kind="job"` 在没有环境筛选时只匹配 Job、输入、deadline，以及 `requires_decision=True` 的环境记录。显式 `event_kind="event"` / `"timer"`，或在 Job wait 中给出 event_id/topic/source，则表示模型明确监听环境事件，可以匹配纯刷新记录。

| 等待意图 | 唤醒条件 |
| --- | --- |
| 只有 timeout_seconds | 到期或用户新指示；继续保持纯定时等待 |
| event_kind=job，可带 timeout_seconds | 任意所属 Job 终态/待答、用户新指示、到期，或符合现有筛选且需要决策的环境事件 |
| event_kind=event/timer | 显式选中的事件或到期；显式等待可以选中纯状态刷新事件 |
| event_kind=job，同时指定 event_id/topic/source | 任意 Job，或显式筛选的环境事件，包括纯状态刷新事件；过滤条件仍不限制 Job |

这里的显式筛选是已有非空 event_id/topic/source，不新增中断策略结构。普通 `core.wait(event_kind="job", timeout_seconds=45)` 会安静等待 Job 或 45 秒截止；若确实关心文件变化，仍能显式选择 `workspace.changed`。

文件变化继续由 Workspace 提交和发布，进入已有合并槽并在下一正常消费边界刷新语境。等待内部的 asyncio 条件通知可以发生，但不因此授权新 Cycle。这保留文件现态与前端观察，同时减少无效推理和反复记录的刷新事实。

改动集中于 Inbox 的匹配判定及测试。`accepts_event` 继续负责事件是否进入当前 Inbox，`_ready` 负责等待条件是否由该记录唤醒；二者不新增第二套事件队列。无须按 jobs/logs 路径过滤事件、提高全局 debounce、关闭 watcher，或让模型反复 wait 抵消框架唤醒。带明确选择的等待与普通 Job 等待共同复用原有队列、预算和固定批次消费。

`accept_event` 仍然接收、合并并保留 Workspace 事件；`requires_decision=False` 不表示丢弃事件，只表示它不能单独改变等待中的根执行位置。事件最终仍可在 Job 终态、显式事件等待或下一次正常消费边界进入 Context。Workspace owner、watcher 和订阅声明不需要知道 Job wait 的内部规则。

## 方案三：恢复记录说明实际唤醒源

当前 TurnRunner 将 pending_wait.topic/source 写入 wait_resumed，它们表达的是筛选条件。建议由 Inbox 将实际匹配事件的 topic/source 通过 CycleReadiness 传回，TurnRunner 填入已有 Trace 字段。具体只增加 `wake_topic` 与 `wake_source` 两个可选字符串字段；它们只在 `WakeReason.EVENT` 时成对出现，Job、timer、input 和 source unavailable 不伪造环境来源。

- Job 继续只报告 reason=job 和 job_id；状态与正文由已有结果和 jobs 投影提供。
- 普通事件报告 reason=event 及实际 topic/source，不复制事件 payload。
- 定时器和用户输入不填无关事件来源。source_unavailable 按现有来源状态语义单独处理，不冒充已收到匹配事件。

仅扩展既有就绪结果所需的有界标量，不建立 wake_source 对象或另一份事件历史。来源信息来自匹配记录，不用显示文字反向恢复事实。

## 方案四：打通输出发现与资源读取

### 域级能力说明

Phase1 只看到域的 description/selection_hint。当前 execution 域仅强调运行命令和脚本；collect/stdin 的职责主要写在 Phase2 的动作说明与 Skill 中。建议修改 `tinysoul/assets/common/configs/action/catalog/execution/domain.toml` 的 domain description/selection_hint，使 Phase1 看到完整但简短的能力边界：execution 支持确定性的本地命令和脚本；`execution.run` 在当前 Action 等待结果，`execution.start` 返回 Turn-owned Job，后续用 `core.wait` 等待、用 `core.job.status/stop` 管理、用 `execution.collect` 读取增量输出，交互任务可用 `execution.stdin`。

实际 TOML 保持英文固定配置文案，避免把 action schema 复制到 domain 描述。`execution.start/run/collect/stdin` 的现有 action description 只在确有歧义处补充“结果由 collect 读取”和“start 后用 core.wait”，不新增参数或自动调用关系。同步 `tinysoul/assets/common/home/skills_domain/execution/DOMAIN.md` 与 `docs/design/execution.md`，让域级选择、Action 说明和设计文档使用同一职责边界。

这修正的是 catalog 能力定义的缺项。不会让 core 自动调用 execution，也不增加重复 status 禁令、强制 collect guard 或 jobs Working 操作菜单。模型每个新 Cycle 都能重新选择 execution/workspace；某次 Phase2 的 core-only 不是整个 Turn 的能力限制。

### 输出文件与目录

ProcessJobBackend 当前将 WorkspaceExecutionLocation.refs 同时作为工作资源和 result_refs，其中包括 Job 根目录。预计将现有 location/backend 边界改为两组已有语义：`workspace_refs` 保留 Job 根目录、logs 目录和 stdout/stderr 文件，供 describe 和 Workspace 导航；`result_refs` 只返回 stdout.log、stderr.log 等实际输出文件，供 JobSnapshot、execution.collect 和模型回答引用。目录仍可在 Workspace Working 投影中出现，但不会被当作回答正文加载。无需给所有 Job 新增通用资源描述体系；ACP 已有单个 output.txt result ref，继续沿用。

WorkspaceResourceClassifier 的通用文本类型补充 `.log`，有效 UTF-8 日志能够通过已有 workspace.inspect 和 PromptReferenceResolver 读取。分类不保证任意进程字节都是 UTF-8，读取继续遵守既有编码与容量约束，不引入编码猜测或静默转码。这样 `result_refs` 的“可定位输出文件”和 Workspace 的“可加载正文”具有一致的正常路径。

PromptReferenceResolver 对目录提供准确的短反馈，说明目录没有可加载正文、应选择具体文件；目录不再笼统描述为 binary。该反馈只作为兜底，正常的 Job result_refs 不再包含目录。结果引用也不等于必须作为回答的 references 重新加载：已取得的输出可直接作为回答输入，ref 保留定位作用。

预计具体文件：`plugins/workspace/engine.py` 的 `WorkspaceExecutionLocation` 增加明确的输出文件投影；`plugins/execution/backend.py` 分别接收 workspace_refs/result_refs；`plugins/execution/engine.py` 传递两组引用；`plugins/workspace/inspection/classification.py` 增加 `.log`；Workspace prompt 文案补充目录边界。同步 `JobSnapshot`、Endpoint examples、执行/Job 测试中的引用示例。`JobSnapshot` 不新增第二个结果字段，仍由 result_refs 承担结果文件集合。

后端只更新 `docs/endpoint` 及后端契约说明，不直接修改 `visualization` 目录。接口形状仍是字符串 `job_id`、字符串数组 `result_refs/result_locators` 和既有 `workspace_refs` 详情，前端无需新增动作或解析 Job 编号；前端现有精确断言旧 Job 示例或结果数量时，由前端维护者按接口文档更新 fixture。若需要主动交接，使用 `visualization/docs/demand` 记录该契约变化，不在后端实现中建立兼容值。

## 分支比较与裁决

### 是否把 Job wait 建模为 EnvironmentEvent

可以把 Job 终态包装成 `source=kernel.jobs`、某个 `topic` 和 `event_id` 的 EnvironmentEvent，但这会把两个不同层次的身份混在一起：`event_id` 标识一次事实，`job_id` 标识一个可跨 Cycle 管理的后台工作；同一个 Job 还可能产生待答、输入和终态等多类事实。用 topic 表示“任意 Job”也不能清楚区分 Job 类型、事实阶段和是否已到达终态。

现有 `InboxKind.JOB`、`WakeReason.JOB` 和 `wake_job_id` 已经表达了 Job 的专用所有权与唤醒来源；Job 事件也不能创建新的根 Turn。将它们改成通用环境事件会模糊 JobRegistry 与 EnvironmentEvent 的边界，并使通用事件订阅承担 Job 监督语义。因而本计划不采用 Job-as-event：`event_id/topic/source` 继续用于 EnvironmentEvent 的显式筛选，Job 以专用 Inbox 记录唤醒。

Job 唤醒只携带恢复所需的最小事实：`reason=job`、实际唤醒的 `job_id` 和顺序信息。Job 记录本身以及 Working 的 Job 投影继续提供状态、终态原因、结果引用等内容；模型需要正文时再使用 `core.job.status` 或 `execution.collect`。这些 Job 事实会进入当前 Turn 的 Trace，`wait_resumed` 不重复复制完整状态或结果引用。环境事件唤醒则记录实际匹配的 topic/source，避免把等待条件误写成唤醒事实。

### 目录加载是否等同于 `workspace.inspect(dir)`

当前运行中的目录失败不是 inspect 缺失，而是把目录作为 `core.answer` 的正文引用交给 Workspace PromptReferenceResolver。目录是导航资源，没有可直接加载的正文；此处应返回简短提示，引导模型选择具体输出文件或调用 `workspace.inspect`。

`workspace.inspect(dir)` 已经是现有设计的一部分：它对已知目录列出有界的直接子项，返回 `DisclosurePage` 和 continuation，不调用内部模型；这与 Trace、Session 以及归档 Workspace 的根目录导航保持一致。因而本计划不新增另一种目录 inspect，也不让回答引用自动展开目录。结果引用收敛和 `.log` 文本分类完成后，模型可先 inspect Job 目录或 logs 目录，再 inspect/加载具体 stdout、stderr 文件。

以上两个分支结论不改变已确认的 Job 编号、单一 `core.wait`、Job wait 的隐式中断规则或结果引用改造；它们用于固定职责边界，避免为特定运行轨迹添加新的事件字段、目录工具或平行资源模型。

## 明确排除

- 第 5 轮回答中的证据充分性不在本次改进范围内。
- 12 次 Phase1/Phase2 失败及其模型协议根因不在本次改进范围内。
- PowerShell CLIXML、中文输出和解释器编码问题不在本次改进范围内；本次只修正日志作为 Workspace 结果的正常读取分类，不改变进程启动参数或模型提示。

## 实施顺序、验证与范围

| 顺序 | 内容 | 验证重点 |
| --- | --- | --- |
| 1 | Inbox 的隐式中断与恢复来源 | 纯刷新不触发 Job Cycle；需要决策的事件仍可中断；显式文件等待有效；Job 终态/待答、deadline、输入和预算约束保持有效；匹配事件的实际来源进入 Trace |
| 2 | Job 正式编号与 Workspace 路径边界 | 同 Turn 连续/失败启动不重号；不同 Turn 不冲突；process/ACP 使用同一规则；清理和输出读取仍按所属 Turn 隔离 |
| 3 | execution 域说明、结果引用、日志读取 | Phase1 获得完整域用途；`result_refs` 只含输出文件；UTF-8 日志可 inspect/加载；目录反馈准确；非 UTF-8 按现有局部失败处理；collect 仍提供增量输出 |
| 4 | 文档与集成核对 | 同步 design 的 loop/execution/references/Workspace、catalog 与受影响 Endpoint 示例；确认前端只透传 Job 字符串，不新增动作映射 |

Inbox owner 覆盖匹配契约，Turn 测试验证一条真实订阅到模型 Trace 的协作路径，JobRegistry 覆盖身份生命周期，Workspace 覆盖通用分类与读取。测试使用代表性事件和资源，不重放特定示例脚本、不固定上述运行记录的次数或文案。后端实现按 AGENTS.md 执行聚焦测试、Fast、Full 和 ty；接口变化通过 `docs/endpoint` 与前端交接记录同步。实施、文档、验证均完成后再归档本计划。

可行性：三组改动均可落在现有 owner 和对象上，不需要新调度器、持久表或等待动作。正式 Job 编码、`requires_decision` 的解释、唤醒来源字段和结果引用边界已经确认；结果引用只做现有 location/backend 字段职责收敛，不引入第二套资源模型。当前没有需要维护者再次裁决的设计语义，计划已完成实施。

## 实施记录与计划核对

| 计划项 | 实施结果 | 核对结论 |
| --- | --- | --- |
| Job 正式编号 | `JobRegistry` 从所属 `TurnIdentity` 生成 `YYYYMMDD-turn-sequence`，并按 Turn 维护本轮序号；Workspace 路径允许该稳定身份。 | 已完成；同一 Turn 的多 Job、不同 Turn、启动失败和清理路径均由现有 Registry 测试覆盖。 |
| 单一 `core.wait` 与隐式中断 | `TurnInbox._matches_event` 保留一个等待入口；普通 `event_kind=job` 忽略 `requires_decision=False` 的环境刷新，显式 event_id/topic/source 仍可选择它们。 | 已完成；Job 终态/待答、用户输入、定时器、需要决策的环境事件和显式刷新等待均通过原有队列验证。 |
| 唤醒来源表达 | `CycleReadiness` 增加有界的 `wake_topic`/`wake_source`；TurnTrace 使用实际匹配记录的来源，Job 只携带 `wake_job_id`。 | 已完成；不复制事件 payload，也未引入第二套事件历史。 |
| 域级说明与结果引用 | execution catalog/Skill/design/endpoint 文档补充 run/start/wait/status/collect/stdin 的职责；Workspace execution location 分离 `workspace_refs` 与 `result_refs`，后者只含 stdout/stderr。 | 已完成；Endpoint 示例与契约测试同步，前端继续透传字符串 ID 和引用数组。 |
| 目录与日志读取 | `workspace.inspect` 继续负责目录导航；目录作为正文引用返回 `directory_requires_inspection`，`.log` 归入有界文本分类。 | 已完成；新增目录反馈和 `.log` 分类测试。 |
| 前端边界 | 未修改 `visualization`；后端已更新 `docs/endpoint` 和前端集成契约，未建立兼容字段或 Job ID 解析规则。 | 符合 AGENTS.md；前端若有旧 fixture 精确断言，由前端维护者按契约更新。 |
| 明确排除项 | 未重做第 5 轮证据充分性、12 次 Phase 失败、PowerShell/编码问题。 | 范围保持与已确认计划一致。 |

验证结果：`scripts/test.ps1 -Suite Fast` 为 1270 passed、30 deselected；`scripts/test.ps1 -Suite Full` 为 1275 passed、25 deselected；`ty check`、`compileall`、Endpoint JSON 解析和 `git diff --check` 均通过。实现仍复用 Agent/Turn/Inbox/JobRegistry/Workspace 既有 owner 和生命周期，没有新增调度器、Job wait 动作、持久表或兼容别名。计划完成，按 `docs/analysis/done/` 约定归档。
