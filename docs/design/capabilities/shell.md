# Shell Capability 设计

## 状态

status: implemented

## 定位

`tinysoul.capabilities.shell` 提供即时 PowerShell、Cmd 和可选 Bash 命令执行。它是独立的 `shell` action domain，但不拥有 Link namespace、持久状态或 Home Maintenance 内容。Shell 解决“一次性输入命令并监督运行”的问题；可维护的 Python/Bash 程序仍由 Script 通过 Workspace/Home resource Link 编写、运行和 promote。

Shell 与 Script 使用不同 Action handler、参数 schema、policy 和依赖设置，同时共用 `tinysoul.capabilities.supervised_process` 的 Turn-scoped job manager、Workspace transaction mirror、日志/候选观察、Cycle pacing、额外 Cycle、apply/discard 和 cleanup。同一 Turn 跨 Script/Shell 最多一个 unresolved process job。

## Action

首版提供：

- `shell.run_powershell`
- `shell.run_cmd`
- `shell.run_bash`
- `shell.wait`
- `shell.stop`
- `shell.read_candidate`
- `shell.apply`
- `shell.discard`

run 输入只包含：

```text
command: bounded non-empty string
working_directory: optional Workspace-mirror-relative directory, default "."
```

模型不能设置 executable、解释器 flags、env、stdin、capture path、宿主 cwd 或进程启动模式。`working_directory` 必须是 mirror 内已存在的相对目录，拒绝绝对路径、盘符、`..` 逃逸和 symlink。

## 解释器协议

- PowerShell 使用配置解析出的 executable 和框架固定的 non-profile/non-interactive flags；命令使用不会被第二层 shell 再解释的安全 argv/encoded-command 传递；
- Cmd 使用配置 executable 和固定 `/D /Q /S /C` 协议；
- Bash 使用配置 executable 和固定非交互 `-c` 协议；
- 宿主 Python 始终以 `shell=False` 启动明确 argv；
- stdin 固定关闭，不支持 PTY、feed stdin、交互式密码、终端 UI 或跨 Action 的输入流。

首版不把 inline 命令物化为临时 `workspace:` Link，也不提供长期 `.ps1`/`.cmd` authoring/promote。需要维护的任务逻辑应写成 Script 当前支持的 `.py` 或 `.sh` 资源；是否扩展长期 PowerShell/Cmd 脚本必须另行确认。

## Policy 与信任边界

确定性 policy 只检查命令非空、无 NUL、字符上限、合法 working directory、adapter enabled 和 executable dependency。首版不维护基于关键字的命令 denylist，因为字符串匹配无法形成可靠安全边界。

每次 run 都以 active Workspace 的有界事务 mirror 为 cwd，`TINYSOUL_WORKSPACE` 指向同一 mirror。TinySoul 只对 mirror diff 提供 apply/discard 和冲突检查；这不构成 OS 硬沙箱。命令仍可能读取或修改宿主绝对路径、使用网络或环境、启动子进程，并产生无法由 discard 回滚的外部副作用。Catalog semantic、domain HOW 和项目配置必须明确该限制。

首版不增加逐命令人工 approval。信任由项目维护者在配置中显式启用：当前仓库项目计划启用 PowerShell/Cmd、关闭 Bash；`tinysoul init` 模板默认关闭整个 Shell capability。enabled adapter 缺少 executable 时 App 启动失败；disabled adapter 不检查依赖并从 effective Catalog 移除。整个 domain 没有有效 action 时同时移除 domain，Home 不创建伪可用 Shell prompt mount。

## Job 生命周期

`shell.run_*` 启动进程后先等待共用 initial interval，并返回 execution id、owner、状态、有界日志增量、cursor、elapsed、exit code 与候选/diff metadata。命令正文不在后续结果中反复回放，只提供稳定 command digest。

状态收尾固定为：

- exit code 0 且 mirror 无 diff：`completed`，立即清理 job；stdout/stderr 即使被有界截断也不要求额外 discard；
- exit code 0 且 mirror 有 diff：`ready_to_apply`，只允许 `shell.apply` 或继续 read 后 apply/discard；
- still running：保留 job，可 wait/stop/read；
- non-zero、timed_out、stopped：保留 job供有界 inspect/read，只允许 discard，不能 apply；
- apply：按 job baseline digest 与当前 active Workspace 执行整批 CAS；同路径冲突拒绝提交并保留 job，不同路径并发变化可以保留；成功后返回真实 Workspace Link、发布一次 authoritative Workspace snapshot 并清理；
- discard：不修改 active Workspace，删除 mirror、source（如有）、日志和候选。

wait 只接受 matching owner/execution id，并复用共用的当前 Turn input/control predicate、Signal cursor 和 Cycle 最小间隔。stop 终止进程树但保留 staging。read_candidate 只读取 mirror 内有界 UTF-8 slice；候选路径在 apply 前不是 Link。

Turn stop、failed、exhausted、Runtime transfer、正常离开和 Program shutdown 都强制终止 retained process 并 best-effort 清理。job 不跨 Turn、不持久化、不跨重启；启动 cleanup 只删除遗留 staging，不恢复 job。

## Context 与 ActionResult

Shell run/wait/stop/read/apply/discard 都是普通 Action，每次在所属 ActionBatch 内收敛。进程可以在 run Action 返回后继续存在，但 ActionResult status 不使用 ongoing。后续 Cycle 仍完整执行 Phase1、Phase2、Phase3；最新结果进入 TurnTrace interaction context，不进入 Background。

结果不暴露 staging 绝对路径、完整无界日志、敏感环境或重复命令。payload 只包含 execution id、owner、command digest、job state、elapsed、exit code、有界 stdout/stderr delta、cursor、truncated 标记、candidate/diff metadata、真实提交 Link 或稳定失败 reason。`core.answer` 在任一 Script/Shell unresolved job 存在时局部拒绝。

## 失败语义

- command/working directory/状态/owner/execution id 非法、进程非零、超时、停止、输出或 mirror 上限、candidate read、apply conflict 属于局部 ActionResult；
- Shell 配置非法、enabled executable 缺失或 registrar 与 effective Catalog 矛盾属于 `shell.configuration_failed`/装配边界；
- 共用 wait pacing、额外 Cycle 和 cleanup 等 non-Action activity failure 归 `supervised_process` Runtime bridge；
- Workspace IO/reconciliation/invariant 与 Runtime transfer 保持 owner module 语义，不能包装成普通 Shell 失败。

## 测试要求

- settings 未知键、domain/adapter enabled、dependency 和 project/init 默认配置；
- Catalog pruning、handler/options 校验、domain HOW mount 与 wheel package data；
- PowerShell/Cmd 真实短命令，Bash 根据 executable opt-in/skip；
- 固定 argv、`shell=False`、NUL/长度/cwd 逃逸/symlink 拒绝；
- 无 diff 自动 cleanup、有 diff apply、non-zero/timeout/stop retained、read/discard；
- Script/Shell 唯一 job 和 owner mismatch；
- Cycle pacing、同 Turn input/control 唤醒、日志 cursor、candidate read、answer guard 与 Turn/Runtime cleanup；
- 隔离 App E2E、全量测试、类型检查、wheel 和安装后初始化验证。
