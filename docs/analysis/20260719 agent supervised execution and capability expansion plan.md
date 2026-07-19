# 20260719 Agent Supervised Execution And Capability Expansion Plan

## 状态

status: in_progress (Stage 1 Shared Supervised Process and Stage 2 Immediate Shell completed; Stage 3 requires semantic confirmation)

前置计划（已完成）：`20260715-done-agent capabilities stages 1-3 execution plan.md`、`20260718-done-workspace inspection search and analyze execution plan.md`。

## 目标

在已完成 Resource、Web、Script 和 Workspace inspection 的基础上，先抽取 Script/Shell 共用的 Turn-scoped 监督进程层，再建立独立 Shell domain，之后按真实需求推进确定性工具、知识检索增强和外部连接器。

本计划不复制或推测其它 Agent 产品的内部实现。“类似 Codex 的 shell 执行能力”仅指交互形态：Agent 可以启动命令、在后续 Cycle 观察有界日志和候选产物、等待或停止，并决定 apply/discard；TinySoul 仍使用自己的 Action、Context、Runtime、Workspace transaction 和失败语义。

## 已确认的核心判断

1. `subprocess` 表示必须在当前 Action batch 内结束的同步进程。其 executor 返回时进程已经成功、失败或超时，不在后续 Cycle 保留 job。
2. `supervised_process` 表示进程可以在启动 Action 返回后继续存在，并由同一 User Turn 的后续 Cycle 监督；每一次 run/wait/stop/read/apply/discard Action 本身仍在所属 batch 内收敛，不恢复 `ONGOING Action`。
3. Script 和 Shell 使用不同 domain、Catalog action、参数 schema、policy 与 handler，但共用 `backend.kind=supervised_process`、同一个 Turn-scoped job manager、Workspace transaction mirror、日志/候选观察、Cycle pacing 和 cleanup。
4. 同一 Turn 在 Script 与 Shell 之间最多存在一个 unresolved process job。`running`、`ready_to_apply`、`failed`、`timed_out`、`stopped` 只要尚未 apply/discard/cleanup，都占用该唯一名额；稳定 owner capability identity（首版为 `script` 或 `shell`）必须在每个后续 action 校验。
5. 监督执行只提供“事务隔离 + 策略检查”，不宣称 OS 硬沙箱。Workspace mirror 是唯一受 TinySoul 提交控制的文件边界，但脚本或命令仍可能访问宿主绝对路径、网络、环境或启动子进程；apply/discard 不能回滚 mirror 以外的副作用。
6. `tinysoul/action/backends/process.py` 继续是低层 managed process 原语，不注册 Action handler；同步 `subprocess` adapter 和 Turn-scoped `supervised_process` service 都复用它。
7. `supervised_process` 是 capability 内部共享执行设施，不是模型可见 domain，不建立 Catalog 目录、HOW 或 Link namespace。
8. 当前代码统一使用 `backend.kind=supervised_process` 和 shared manager；旧 `script` backend kind、Script-owned job manager 与共用配置键已删除，不保留双轨兼容。

## 推进路线

1. **Stage 1 Shared Supervised Process（done）**：抽取 Script/Shell 共用的 Turn-scoped 进程、事务、监督和 cleanup 层，并把现有 Script 无行为回归地迁移过去；
2. **Stage 2 Immediate Shell（done）**：建立独立 `shell` domain，提供 PowerShell、Cmd 与可选 Bash 的即时命令执行及监督收尾；
3. **Stage 3 Deterministic Utilities**：按真实任务补充数学、时间、编码和结构化格式转换等纯输入输出工具；
4. **Stage 4 Knowledge Retrieval Enhancements**：实现 Home Backlink，并在数据规模和质量需求成立后增强 Memory 片段检索；
5. **Stage 5 Connectors And Interaction**：按具体授权与审批边界增加外部服务连接器、导入导出和交互入口。

Stage 1 与 Stage 2 的语义已经确认，可以连续实施。Stage 3-5 只保留方向和进入门槛，实施前仍需针对真实 action 集合确认。

## Stage 1 Shared Supervised Process

### 1.1 类型与组织

新增内部包：

```text
tinysoul/capabilities/supervised_process/
  config.py             # 共用 pacing/runtime/log/mirror/candidate 上限
  errors.py             # 共享执行层不变量与生命周期错误
  failures.py           # non-Action activity Runtime bridge 失败分类
  models.py             # owner、job state、log cursor、candidate/diff 投影
  manager.py            # Turn-scoped 单 job 生命周期、owner 校验与 mirror 协调
```

实际文件可在实现时按职责合并，但不得重新把 Script/Shell 业务 policy 塞入共享 manager。共享层只知道 execution owner、冻结入口或固定 argv、managed process、注入的 Workspace mirror 门面、日志、状态、等待、提交和清理；它不解释 Python/Bash 源码，也不解释 PowerShell/Cmd 命令。`tinysoul/workspace/mirror.py` 继续拥有 mirror、diff、baseline CAS 和 Workspace bundle mutation；共享层只协调该服务，不复制或迁走 Workspace 业务规则。`failures.py` 定义共享 failure facts，实际 Runtime bridge 仍按现有组织位于 `tinysoul/runtime/bridge/supervised_process.py`。

### 1.2 Backend 迁移

- `ActionBackendKind.SCRIPT` 改为 `ActionBackendKind.SUPERVISED_PROCESS`，Catalog 字符串统一为 `supervised_process`；
- 删除 `script` backend kind，不提供加载 alias；package Catalog、loader 校验、runner 硬停止分类、测试 fixture 和设计文档一次性同步；
- Script 的 run/wait/stop/read/apply/discard 仍由 Script registrar 注册具体 handler；Shell 后续注册自己的 handler。`backend.kind` 不要求存在同名通用 executor；
- `subprocess.default` 保持同步 handler，不能启动 retained job，也不共享 Turn activity 名额。

### 1.3 单一 Turn Job

共用 manager 以当前 Turn id 作为 scope，并记录稳定 `owner`（首版为 `script` 或 `shell`）。任何 domain 的第二个 run 在已有 unresolved job 时局部失败；wait/stop/read/apply/discard 还必须同时匹配 execution id、Turn scope 和 owner，不能由另一 domain 接管。

job staging 统一为：

```text
runtime/.staging/supervised-process-job-*/
├── source/       # Script 冻结源码需要；Shell 可无此目录
├── workspace/    # active Workspace 的事务 mirror，也是唯一 cwd 根
└── logs/
    ├── stdout.log
    └── stderr.log
```

完整日志和未提交候选没有 Link，不进入 Workspace Manifest、Session、Home、Memory 或 Daily archive。job 不跨 Turn、不跨重启；Program 恢复只清理遗留 staging，不恢复进程或 review 状态。

### 1.4 配置迁移

将两种能力真正共用的设置迁入 `[capabilities.supervised_process]`：

- `initial_wait_seconds`、`min_wait_seconds`、`default_wait_seconds`、`max_wait_seconds`；
- `cycle_wait_seconds`、`max_runtime_seconds`、`max_supervision_cycles`；
- stdout/stderr 增量与总投影上限；
- Workspace mirror 文件数、单文件、总量、candidate read 与 diff 上限。

Script 只保留 `enabled`、Python/Bash adapter、executable、`max_source_chars` 和源码 policy 等 Script-owned 设置。旧 `[capabilities.script]` 中的共享键直接移除，不提供 alias。parser 对旧键和未知键显式失败，避免一份配置被两处解释。

### 1.5 生命周期与 Loop

- `TurnActivityController` 由共享 manager 实现并只装配一次；Loop 不读取 Script/Shell job、日志或 mirror；
- running job 的相邻 Cycle 仍受默认 30 秒最小间隔约束，run initial wait 和当前 Cycle 已耗时间计入，不机械追加；进程完成或当前 Turn 合法 input/control 可提前唤醒；
- 普通 Cycle 预算耗尽后，只有仍在总 runtime/supervision cycle 配额内的 unresolved running job 可以申请额外 Cycle；
- 后续 Cycle 仍完整执行 Phase1/Phase2/Phase3。新的 ActionResult 进入 TurnTrace interaction context，不进入 Background；
- Turn stop、failed、exhausted、Runtime transfer、正常离开和 Program shutdown 都在 `finally` 中终止 retained process 并 best-effort 清理。各清理步骤独立尝试，cleanup 错误形成 Observation，不替换原始异常或 transfer。

### 1.6 失败归属

- action 参数、状态、owner、execution id、进程退出、资源上限、candidate read、apply 冲突等可修正问题返回稳定局部 ActionResult；
- Script/Shell 自有配置和依赖错误仍归各自 capability，例如 `script.configuration_failed`、`shell.configuration_failed`；
- wait pacing、额外 Cycle 判断等非 Action 共用 activity 失败通过 `supervised_process` Runtime bridge 保持共享层归属；Turn cleanup 独立尝试所有回收步骤后聚合共享执行层错误，由 Loop 在 `finally` 中形成 Observation，不发起新的恢复控制流；
- Workspace/Home/Runtime 的 IO、reconciliation、trap 与 invariant failure 保持 owner module 语义，不被泛化成进程业务失败；
- Catalog/backend/registrar 不一致仍属于 Action 装配失败。

### 1.7 Script 迁移验收

迁移必须保持 Script 对外语义不变：

- `script.write/rewrite/patch/promote` 仍只接受 Workspace/Home resource Link；不增加 inline code；
- Python/Bash run 仍执行经过 policy 与 digest 复核的冻结 `ScriptSource`；
- 成功退出仍进入 `ready_to_apply`，必须显式 apply/discard；失败、超时、停止仍只允许观察/read/discard；
- Workspace mirror CAS、不同路径并发保留、同路径冲突、一次 authoritative snapshot signal 不变；
- `core.answer` 在任一 unresolved Script/Shell job 存在时拒绝完成；
- 旧 `script-job-*`、`backend.kind=script`、Script-owned activity controller 和重复共用配置全部移除。

测试至少覆盖 backend migration、配置旧键拒绝、Script 全量回归、跨 owner 第二次 run 拒绝、owner 错误操作拒绝、Cycle pacing、Signal predicate、Runtime transfer cleanup、wheel Catalog/template 和隔离安装。

### 1.8 实施结果

`tinysoul.capabilities.supervised_process` 已拥有共享 settings、owner/state models、Turn-scoped manager、最小环境、answer guard 与 non-Action Runtime bridge；manager 通过 capability-owned preparer 接收冻结 Script 入口或固定 Shell argv，不解释源码或命令。`tinysoul.workspace` 继续拥有 mirror/diff/CAS/bundle mutation。Action backend、Catalog 与 process cancellation 已统一为 `supervised_process`，旧 `ScriptJobManager`、`ScriptJobState`、`script-job-*` 和 `[capabilities.script]` 共用监督键已删除。

Script 通过 `ScriptProcessPreparer` 保持 source Link、snapshot digest、policy、promote、显式 apply/discard 和候选观察语义；共享 manager 对 execution id、Turn scope 与 owner 做统一校验，并只为 running job 申请额外 Cycle。共享 answer guard 已覆盖 Script/Shell unresolved job；Turn cleanup 会在 watcher/process/staging 全部尝试后聚合错误并交由 Loop 观察。Script 定向回归、Action/Loop/App 集成和静态类型检查已通过。

## Stage 2 Immediate Shell

### 2.1 定位与 Action

新增无独立持久状态的 `tinysoul.capabilities.shell` 和模型可见 `shell` domain。Shell 表达即时命令，不负责长期脚本 authoring，不创建临时 `.ps1`/`.cmd` Link，也不进入 Home Maintenance。

首版 action：

- `shell.run_powershell`
- `shell.run_cmd`
- `shell.run_bash`
- `shell.wait`
- `shell.stop`
- `shell.read_candidate`
- `shell.apply`
- `shell.discard`

run 参数只包含有界 `command` 和可选 `working_directory`；`working_directory` 默认 `.`，必须是 Workspace mirror 内已存在的相对目录。模型不能传 executable、解释器 flags、环境变量、stdin、capture 路径或宿主 cwd。

### 2.2 执行协议

- PowerShell 使用配置解析出的 executable 和框架固定的 non-profile/non-interactive flags；命令采用不会被二次 shell 展开的安全 argv/encoded-command 传递；
- Cmd 使用显式 executable 与固定 `/D /Q /S /C` 协议；
- Bash 使用显式 executable、固定非交互 `-c` 协议；
- 宿主 Python 始终以 `shell=False` 启动明确 argv；不把命令交给第二层默认 shell；
- stdin 固定关闭，不支持 PTY、feed stdin、交互式密码或终端 UI；
- 首版不提供 PowerShell/Cmd 长期脚本文件。需要可维护逻辑时继续使用 Script 的 `.py`/`.sh` Link authoring/promote。

命令 policy 只做确定性结构限制：非空、无 NUL、字符上限、合法 working directory、启用的 interpreter 和依赖可用性。首版不维护脆弱的命令关键字 denylist；能力信任边界由项目配置明确表达。

### 2.3 Workspace 与安全边界

每次 Shell run 都先建立 active Workspace 的事务 mirror，并只以 mirror 内目录作为 cwd。`working_directory` 拒绝绝对路径、盘符、`..` 逃逸和 symlink。Shell 的受控提交范围只有 mirror diff；命令仍可能通过绝对路径、网络、环境或子进程影响 mirror 外世界，因此文档、HOW 和 Action semantic 必须明确“不构成硬沙箱”。

首版不增加逐命令人工 approval。当前仓库项目配置计划启用 PowerShell/Cmd、关闭 Bash；`tinysoul init` 模板计划默认关闭整个 Shell capability，由项目维护者明确开启并接受信任边界。启用 adapter 但 executable 不可用时 App 启动失败；禁用 adapter 不检查依赖并从 effective Catalog 移除。

### 2.4 状态与自动清理

- exit code 0 且 mirror 无 diff：run/wait 直接返回 completed，立即清理 job；即使 stdout/stderr 被有界截断也不要求额外 discard；
- exit code 0 且 mirror 有 diff：进入 `ready_to_apply`，必须显式 `shell.apply` 或 `shell.discard`；
- still running：保留 job，后续 wait/stop/read；
- non-zero、timed_out、stopped：保留 job 供有界日志和候选检查，只允许 read/discard，不能 apply；
- apply 使用与 Script 相同的 baseline digest/CAS/bundle mutation；成功后返回真实 Workspace Link、发布一次 authoritative snapshot 并清理；
- discard 不修改 active Workspace并清理完整 staging。

Shell 失败 job 保留到显式 discard 或 Turn cleanup，以便 Agent 根据日志和候选决定后续行动。命令本身不在每个 ActionResult 中重复回放；结果返回 command digest、execution id、状态、有界日志增量、cursor、elapsed、exit code、candidate/diff metadata 和必要诊断。

### 2.5 Context 与 HOW

Shell domain HOW 应说明 PowerShell/Cmd/Bash 的选择、workspace mirror、长任务 wait/stop、成功提交和失败 discard。Phase1 选择 `shell` domain 后，Phase2 只看到当前 effective Shell action；每个 run/wait 等结果按普通 ToolResultMessage 进入 TurnTrace，下一 Cycle Phase1 从正常 Context 构造看到它。

禁用整个 Shell 时，所有 Shell action 和 domain 从 effective Catalog 移除，Home prompt mount reconciliation 不创建伪可用 `home:how_domain:shell`。共享 `supervised_process` 不产生独立 HOW。

### 2.6 测试与发布

至少覆盖：

- settings 未知键、current project/init template 默认值、每个 adapter enabled/disabled/dependency；
- Catalog domain/action pruning、HOW mount reconciliation 和 wheel package data；
- PowerShell/Cmd 真实短命令 smoke；Bash 按 executable opt-in/skip；
- command 上限、NUL、working directory 逃逸、symlink、固定 argv 与 `shell=False`；
- 成功无 diff 自动清理、成功有 diff apply、非零/timeout/stop retained、read/discard；
- Script 与 Shell 交叉占用唯一 job、owner mismatch、`core.answer` admission；
- 长任务 Cycle pacing、同 Turn input/control 唤醒、日志 cursor/candidate read、Turn/Runtime transfer cleanup；
- App 隔离项目 E2E、全量 pytest、静态类型检查、wheel 构建和隔离安装。

### 2.7 实施结果

`tinysoul.capabilities.shell` 已提供独立 settings/dependency/policy/process/action 分层和八个 Catalog action。PowerShell 使用 fixed non-profile/non-interactive encoded-command argv，Cmd 使用固定 `/D /Q /S /C`，Bash 使用固定 non-profile/non-interactive `-c`；三者都由 `ManagedProcessRunner` 以 `shell=False` 启动，模型不能传 executable、flags、env 或 stdin。

当前项目配置启用 PowerShell/Cmd、关闭 Bash；`tinysoul init` 模板关闭整个 Shell capability，因此 effective Catalog 和 Home mount 都不暴露 Shell。当前项目的 capability domain HOW 使用正式 `home/how_domain/<domain>/DOMAIN.md` Layout；同时修正了 Resource/Web/Script 遗留的扁平 HOW 文件。真实 PowerShell/Cmd、无 diff 自动清理、有 diff apply、失败 retained、working-directory 边界、跨 owner 单 job 与共享 answer guard 测试已通过；全量 pytest、静态类型检查以及 wheel 构建和隔离安装验证均已闭环。

## Stage 3 Deterministic Utilities

只实施真实任务频繁需要且 Python 标准库或稳定依赖能够确定性完成的 utility。候选包括数学计算、日期/时区转换、编码/hash、JSON/TOML/YAML/CSV 的校验与受控转换。进入实施前需要逐项确认：

- 输入输出应直接作为有界值，还是通过 Workspace Link；
- 日期时间采用项目 business timezone、显式参数 timezone，还是纯 offset；
- 是否产生 Workspace artifact；
- 精度、大小、递归深度和错误定位协议。

不得用一个自由字符串 `eval` 或通用 Python action 冒充 utilities。

## Stage 4 Knowledge Retrieval Enhancements

### Home Backlink

Backlink 是 Home-owned Link 图能力，不放入 Infra 或通用 capability：输入规范 Home top Link，基于 `runtime override/tombstone -> actual fallback` 的 effective Home 查找引用来源，返回有界 source Link、摘要和结果 digest，不为查询把 actual 文件懒拷贝到 runtime。默认只解释 Home 图，不自动跨 Memory/Workspace。渐进资源扫描范围和是否需要持久索引在实施前确认。

### Memory 检索增强

当前 `memory.search` 按单日文档发现候选日期，`memory.recall` 按精确 `memory:YYYY-MM-DD` 返回有界完整正文；二者进入 TurnTrace，Phase1 只自动加载精确昨日记忆。后续片段级检索应保留这两个入口，并返回片段、所属日期 Link 和可验证来源位置。是否引入持久索引、embedding provider、增量更新或新 action，必须先由真实数据规模和查询质量证明需要。

## Stage 5 Connectors And Interaction

每个 connector 单独确认凭据来源、授权方式、读写范围、速率限制、幂等性、人工审批和审计输出。交互入口继续由 App-owned input/output adapter 接入，不绕过 Runtime、Context、Action 或 Workspace 生命周期。本阶段不预先建设通用插件平台。

## 跨阶段实施门槛

- 真实用户场景、domain 归属、`use_when`/`avoid_when` 与 effects 已确认；
- 参数 schema 不以自由路径、命令、网络或 provider payload 绕过 owner 边界；
- 正常失败映射为局部 ActionResult，配置/环境/不变量失败保持模块归属；
- 文本、文件、网络响应、运行时间、进程和并发均有明确上限；
- registrar、Catalog handler、backend kind、业务 service 与 Runtime bridge 所有权一致；
- 模块测试、Phase2/Phase3 集成、App 隔离工作流和发布验证闭环。

## 当前下一步

Stage 1 与 Stage 2 已完成。下一步在实施 Stage 3 前确认真实 deterministic utility 集合、输入输出协议、business timezone 与 Workspace artifact 边界；不得借 Utilities 引入自由字符串 `eval`、第二套任意命令执行或新的未确认持久状态。
