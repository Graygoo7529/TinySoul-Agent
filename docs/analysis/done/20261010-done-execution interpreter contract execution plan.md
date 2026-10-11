# execution interpreter 契约与请求失败反馈执行计划

## 目标

本计划包含三项相互关联的 execution contract 调整：静态 interpreter enum、`ExecutionRequestError` 的有界自然语言反馈，以及前台/后台 execution Action 的统一请求语义。

本计划同时覆盖下方第 3 节的 execution.run 与 execution.start 收敛，以及第 4、5 节的统一 Job 等待和唤醒表达。

## 已确认的改动

### 1. 增加静态 interpreter enum

在最终的公共 Action catalog 中为 `execution.run` 与 `execution.start` 补充明确的 interpreter 值域：

- `execution.run` 的 command 分支：`bash`、`powershell`、`cmd`；source 分支：`python`、`bash`、`powershell`、`cmd`。
- `execution.start.interpreter`：`python`、`bash`、`powershell`、`cmd`。

继续保留 `additionalProperties = false` 以及现有的必填字段和 Action 归一化校验。`sh`、`python3` 不作为隐式别名；如果未来需要支持，必须作为明确的 Interpreter 身份和配置项加入。

静态 enum 表达系统支持的稳定身份，不承诺每个 generation 都启用全部身份。当前 generation 的 executable 可用性仍由 `ExecutionEngine` 和配置决定。

### 2. 使用 execution 模块有界的自然语言反馈

保留现有 Action 失败协议：

- `reason` 继续使用现有稳定值；
- `scope` 继续为 `execution.action`；
- `disposition` 继续为 `change_request`；
- 不新增复杂的 execution failure 类型体系；
- 不把原始异常、traceback、绝对路径或大块运行时数据放入模型结果。

对于 `ExecutionRequestError`，由 execution 模块提供简短、稳定、有界的自然语言反馈，并通过现有 `ActionResult` → `ActionResultRenderer` → ToolResult 的路径呈现给模型。反馈应直接说明可修正的条件，例如：

- interpreter identity 未声明时，提示使用 canonical interpreter 名称；
- interpreter 已声明但当前 generation 未启用时，提示当前配置不可用；
- shell command 与 script source、args 或 interactive 参数组合不符合对应 Action 时，提示正确的请求形状。

Workspace/Home contract、Job supervision 和进程启动失败继续使用各自已有的错误边界和反馈，不把内部异常文本直接暴露给模型。

## 实施顺序

1. 先确定最终的 `execution.run`/`execution.start` command/source 联合 schema 和静态 interpreter enum，同时移除 `run_shell`/`run_script` 的旧 catalog 身份。
2. 复用现有 Action 参数读取与 `ExecutionEngine.start` 公共启动路径，分别接入前台等待和后台 Job 返回；不增加重复的 request normalizer。
3. 更新 `ExecutionRequestError` 的有界反馈，确认未声明值和错误请求在接受 Job 前形成模型可见局部失败，且不会创建 Job。
4. 按第 4、5 节移除 `core.job.wait` 并修正 Job 唤醒原因与来源表达。
5. 更新 catalog、executor、Trace、文档和测试，运行定向测试、类型检查及相关完整测试。

## 当前不纳入范围

- 不为每个 generation 动态重写 ToolSpec schema；
- `core.wait` 与 `core.job.wait` 的等待语义另列于第 4、5 节；本轮新增目标是移除后者并统一唤醒表达。
- `execution.start`、`execution.run_shell`、`execution.run_script` 的 Action 身份收敛见下节；该项不再视为范围外。

### 3. 收敛前台与后台 execution Action

将 execution 的公共请求语义统一为“执行一个 command 或 source”，再由 Action 身份表达是否等待完成：

- `execution.run` 表示前台执行，接受 command 或 source，等待执行结束并返回收集结果；
- `execution.start` 表示后台执行，接受同一组 command/source 请求，创建 Turn-owned Job 并返回 Job 身份；
- `execution.stdin`、`execution.collect` 继续承担运行中 Job 的交互和结果收集。

`run_shell` 与 `run_script` 的差异来自请求形状，而不是进程后端差异。收敛后用一个明确的 command/source 联合 schema 表达二者：command 分支只接受 shell command，source 分支接受 source_ref 与脚本参数；interpreter 仍使用静态 enum，分支中只声明实际允许的值。`interactive` 只属于后台启动请求，避免把前台终态结果和 Job 身份混在同一个返回协议中。

实现上复用 `ExecutionEngine.start` 单一启动路径，以及 `ExecutionActionExecutor` 已有的参数提取和校验；`run` 与 `start` 只在等待策略和返回结果上分叉。代码中没有再增加共享 request normalizer，因为现有边界已经完成这项复用，再加一层只会重复表达同一职责。移除 `run_shell`、`run_script` 的 catalog、注册和旧测试，更新 executor、提示目录及协作文档；开发阶段不为测试数据目录、历史 trace 或旧 Action 名称保留兼容层。该项与前两项一起作为 execution contract 重构的一部分，测试保护新的可观察行为。

## 4. 移除冗余的 `core.job.wait`

### 目标语义

等待是订阅 Turn 的下一次可处理唤醒，Job 身份是状态查询、停止、输入和结果收集所需要的资源身份。两者职责不同：

- `core.wait` 是唯一的等待 Action；`event_kind = "job"` 表示等待本 Turn 内任意 Job 产生可处理事实；
- 用户输入和环境事件也可中断 Job 等待并启动下一 Cycle；Wait note 按实际唤醒原因表达，不将中断伪装为 Job 完成。`event_id`、`topic`、`source` 只筛选环境事件中断，不限制 Job 唤醒；
- 可处理事实包括 Job 进入终态，或出现需要父 Agent 回应的 `waiting_input`；普通运行进度不强制唤醒；
- 任意 Job 唤醒后，下一 Cycle 继续使用已有的 `jobs` Working 投影处理当前任务；等待语义本身不复制 Job 操作清单；
- 不增加 `and/or` 或 Job 集合参数。等待全部 Job 是 Agent 在每次任意唤醒后检查剩余活动 Job 的循环策略；
- `core.job.status` 与 `core.job.stop` 保留，因为它们对具体资源执行操作；`execution.collect` 与 `execution.stdin` 的 Job 身份参数也不受影响。

### 实施内容

1. 删除 `core.job.wait` catalog 文件及其模型可见说明；扩展 `core.wait` 的描述，明确 `job` 是任意所属 Job 的终态或待答唤醒。
2. 从 `JobOperation` 和 `JobActionExecutor` 移除 WAIT 分支、等待参数校验和对应提示常量；Job 注册只保留 status/stop。
3. 从 `WaitRequest` 和成功结果解析中移除 `job_id`、`ready` 及 `core.job.wait` 分支。`WaitRequest` 只保留 timeout、event kind/id、topic 和 source。
4. 从 `WaitCondition` 移除指定 Job 筛选和 `job_ready` 特殊旁路；`InboxKind.JOB` 记录仍由 JobRegistry 保留，作为 `core.wait(event_kind="job")` 的普通匹配事实。
5. 更新 Phase3 的互斥意图检查、Turn 等待调用、Action catalog 注册和所有当前设计文档。历史 `docs/analysis/done/` 与聊天记录只保留历史事实，不作为当前接口。

## 5. 明确 Job 唤醒原因与唤醒源

### 当前问题

Job 终态和待答事实已经通过 `deliver_terminal`、`deliver_job_inputs` 进入 TurnInbox，也会 `notify_all`。但 `_ready` 只有在指定 `job_id` 分支中才返回 `WakeReason.JOB`；无身份的 `event_kind = JOB` 会继续走通用事件匹配并返回 `WakeReason.EVENT`。同时 `CycleReadiness` 只返回原因和序列号，Turn 的 `wait_resumed` 记录无法指出哪个 Job 触发了恢复。

### 目标表达

- 保留现有稳定的 `WakeReason.JOB`，任意 Job 条件匹配 Job 记录时直接返回该原因；不新增复杂的失败或状态枚举。
- 给 `CycleReadiness` 增加一个可选的 `wake_job_id`。它只承载匹配 Job 记录中的稳定 Job 身份，不携带终态正文、原始异常或完整输入。
- `TurnRunner` 继续发布已有的等待恢复 Trace note，并增加一个简单的 `job_id` 字段：`reason = "job"`，`job_id = ...`。Job 的其他状态和内容仍由随后刷新到模型的 `jobs` 投影提供，不在唤醒 note 中复制。
- 将硬编码的 `"wait_resumed"` 纳入 `LoopTraceNoteKind`，保持 Trace note 类型稳定；事件、定时器、用户输入和来源不可用的既有表达不改变。
- Job 记录本身已经包含 `job_id`，不新增 JobRegistry 状态、不建立第二个通知通道，也不把 EnvironmentEvent 伪装成 Job 完成。Job 唤醒只由 `event_kind="job"` 选择；环境事件可以独立中断，并仍以 `WakeReason.EVENT`（或 timer deadline 的 `WakeReason.TIMER`）表达。

### 设计删减结论

下列内容不是本目标的必要实现，已从方案中去除：

- 不为 `event_kind = "job"` 新增一套 event_id/topic/source 拒绝分支；这些字段仍服务于通用环境事件等待，Job 等待只由 `event_kind` 表达。
- 不在唤醒结果中复制 Job 状态、待答正文、结果引用或操作菜单；已有 `jobs` Context 继续承担这些内容。
- 唤醒只增加一个有界 `job_id`，用于回答“哪个 Job 触发了恢复”；原因继续复用 `WakeReason.JOB`，不增加 `wake_source` 对象或新的状态枚举。

### 正常数据流

```text
Job backend 终态/待答
  → JobRegistry monitor
  → TurnInbox JOB record(job_id)
  → core.wait(event_kind="job")
  → WakeReason.JOB + job_id
  → wait_resumed Trace note
  → jobs Working projection
  → 下一 Cycle 继续处理
```

### 变更范围与验证

- `kernel/loop/interaction/inbox.py`：统一 JOB 匹配为 `WakeReason.JOB`，返回 Job 身份；删除指定 Job 等待旁路；补充任意 Job 终态、待答和“两个 Job 中任意一个先完成”的行为测试。
- `kernel/loop/lifecycle/completion.py`、`phase3.py`、`turn.py`：收敛等待请求字段与解析入口，传递匹配到的 `job_id` 并写入 Trace note。
- `kernel/loop/signals.py`、当前设计文档、catalog 和 prompts：登记等待恢复 note，删除 `core.job.wait` 的当前语义描述。
- `tests/`：删除旧 Action/catalog 断言和指定 Job wait 测试，改为验证统一 `core.wait`；保留输入、预算、timer、event、source unavailable 和 Job 收尾测试。
- 验证顺序为 catalog 加载、Inbox/JobRegistry 定向测试、Phase/Turn 协作测试，再运行 `ty` 类型检查和相关完整测试集。开发阶段不维护旧测试数据、旧 trace 或旧 Action 名称的兼容。

## 实施结果与计划核对

**状态：实施完成；按当前代码、测试和 AGENTS.md 核对通过。**

### 实际改动

- `execution.run` 与 `execution.start` 使用严格的 command/source `oneOf` schema；静态 enum 将 command 限定为 bash/powershell/cmd，将 source 限定为 python/bash/powershell/cmd。参数说明补充在 catalog 中；当前 runtime 未启用的 interpreter 由 execution 返回可修正反馈。
- 删除 `run_shell`、`run_script` catalog 身份并新增统一 `execution.run`。前后台 Action 共用既有参数校验和 `ExecutionEngine.start`，未增加单独的 normalizer。
- `ExecutionRequestError` 通过既有 Action 局部失败结果反馈 execution 自己生成的自然语言，最多 240 字符；保留原 `reason`、`scope`、`disposition`，不传原始异常或 traceback。
- 删除 `core.job.wait` 和 WAIT executor 分支。`core.wait(event_kind="job")` 由任意 Job 终态或待答记录唤醒；用户输入也可中断，环境事件可按可选 event filters 中断，但 filters 不限制 Job 唤醒。Job 唤醒以 `WakeReason.JOB` 和 `wake_job_id` 写入 `wait_resumed` note，Job 详情继续走原有 Working 投影。

### 按 AGENTS.md 核对

- 所有权清楚：execution 解释执行请求并产生局部反馈，kernel/jobs 继续拥有 Job 监督，Loop/Inbox 拥有等待与唤醒；没有平行状态机或重复 Job 通知通道。
- 模型协议保持有限：catalog 明示字段和 enum；失败走现有 ActionResult 渲染链，仅增加有界自然语言，不暴露实现异常；Trace 只记录唤醒原因和必要的 Job 身份。
- 控制流和结束边界沿用现有 Turn/Job 生命周期；移除重复等待 Action，保留 status/stop/collect/stdin 等实际资源操作。
- 未引入 schema 动态重写、复杂失败类型、通用 normalizer 抽象或兼容层，符合“先保证正常主线、避免重复设计”的规约。

### 验证

已覆盖 catalog schema、ExecutionRequestError 反馈、JobRegistry/Inbox 唤醒、前后台执行 Action 及 TurnRunner 模型可见 Trace 的测试。`scripts/typecheck.ps1` 的 `ty check` 通过；`scripts/test.ps1 -Suite Full` 通过，结果为 **1273 passed, 25 deselected**，耗时 244.25 秒。随后将环境事件测试加强为“等待已挂起后再由 EnvironmentEvent 唤醒”，Inbox 与 JobRegistry 定向测试再次通过（29 passed）。

### 效果与结论

模型只需学习统一的前台/后台执行请求和一个等待 Action。Job 完成时，等待以短小且可定位的原因与 Job 身份恢复；随后由既有 jobs 投影提供状态和结果。方案与实现保持一致，没有遗留设计裁决项。

### 提交后集成层复核

提交后按 AGENTS.md 重新核对时发现，后端计划虽已完成，但 Visualization 的 ActionRenderer canonical registry、覆盖矩阵和测试 fixture 仍保留已删除的 `core.job.wait`、`execution.run_shell`、`execution.run_script`，且没有登记 `execution.run`。这属于动作合并后必须同步的前端协议映射，而不是旧数据兼容层。

已补齐以下同步：

- `visualization/src/features/trace/registry.ts` 与 registry 快照改为当前 62 个 catalog action，删除旧动作并登记 `execution.run`；
- trace 覆盖矩阵、Activity/Process 测试和 E2E fixture 改用 `execution.run`；
- execution 与 subagent 的模型可见技能文案改用 `core.wait(event_kind="job")`，不再引用删除的 `core.job.wait`；
- Visualization Vitest 通过（89 files / 795 tests），TypeScript/Vite build 通过。

后端负向 catalog 测试中仍保留旧名称，是为了明确断言它们不存在，不是活动接口引用。
