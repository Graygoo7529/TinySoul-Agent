# Script Capability 设计

## 定位

`tinysoul.capabilities.script` 提供临时与长期脚本的编写、修改、显式提升和 Turn 内监督执行。它不拥有新的 Link namespace：临时脚本使用 `workspace:scripts/...`，长期脚本使用 `home:how/<skill>/scripts/...`。长期目标必须属于已存在的通用 HOW；创建 HOW 不属于本阶段。

脚本执行面向 Workspace 资源处理。执行器为每个 job 建立 active Workspace 的有界事务镜像，以镜像根作为进程 `cwd`，并设置 `TINYSOUL_WORKSPACE` 指向同一目录。脚本只修改镜像；成功退出只进入 `ready_to_apply`，不隐式修改 active Workspace。这里的安全语义是事务隔离、语法/参数/资源限制和受控进程终止，不宣称操作系统级硬沙箱。

## 源与提升

- `script.write` / `script.rewrite` 复用 `LLMActionTaskRunner`，因此继承当前 Turn Context、Workspace reference 和 Home-owned domain/action HOW；模型只返回完整 source；
- `script.patch` 只做唯一精确替换，并在写入前执行确定性语法策略检查；
- `script.promote` 只允许从 `workspace:scripts/...` 复制到 `home:how/<existing-skill>/scripts/...`，扩展名必须保持一致；
- promote 写入 lazy runtime Home，随后由普通 Home Maintenance review/apply；它不直接写实际 Home，也不自动创建 skill。

`ScriptSource` 是一次 read 产生的不可变源码 snapshot。owner resource digest 绑定 Workspace/Home Link 的资源版本和后续 CAS；解码后的 snapshot 另以固定 UTF-8 字节计算 `snapshot_digest`。policy 只校验该 snapshot，process 也只执行 job `source/` 中经 snapshot digest 复核的冻结入口；不得在 policy 后再次按 Link 读取执行内容。Workspace mirror 创建时逐文件复核复制字节与 baseline resource digest，Workspace source 的 baseline digest 还必须等于 resolver 读取时的 owner digest。`script.promote` 同样直接写入已校验 snapshot，不二次读取 source Link。

`max_source_chars` 是 Script 的读写共同边界：read、LLM write/rewrite 输出、patch 后完整候选、promote 与 resolver 最终 mutation 都必须检查。Workspace/Home 自有 mutation 上限继续独立生效，实际边界取二者较小值。

Python 默认启用并使用当前 TinySoul Python 解释器。Bash 独立配置、默认关闭；启用时由 Infra dependency checker 检查配置的 executable。两种语言使用独立 run action，避免把任意 inline command 或 shell 字符串作为执行接口。

## Job 生命周期

每个 Turn 最多拥有一个 unresolved Script job。job 不跨 Turn、不持久化、不跨重启。`script.run_python` / `script.run_bash` 启动进程后先等待配置的 initial interval，返回 execution id、状态、有界增量日志和候选文件 metadata。

后续动作固定为：

- `script.wait`：等待进程完成、等待区间到期，或当前 Turn 中合法的 `context.input.append` / `loop.control.request`；日志增长、其它 namespace、其它 Turn 和非法 payload 不唤醒；
- `script.stop`：终止进程并保留镜像供检查；stopped 不可 apply；
- `script.read_candidate`：按候选相对路径读取有界 UTF-8 文本；候选路径不是 Link；
- `script.apply`：只允许 `ready_to_apply`，逐文件比较创建 job 时的 baseline digest 与当前 active Workspace；同路径并发变化拒绝整个提交，job 保留；
- `script.discard`：关闭非运行 job 并删除镜像、日志和候选，不修改 active Workspace。

failed、timed_out、stopped 只能 inspect/read/discard。即使进程快速成功也必须显式 apply 或 discard。`core.answer` execution hook 在 job unresolved 时拒绝最终回答。

## 长任务监督

普通 Turn Cycle 上限耗尽后，只有 unresolved Script job 可以申请额外监督 Cycle；额外预算与进程最大运行时间分别受限。每个额外 Cycle 仍完整执行 Phase1、Phase2、Phase3，因此新的 job ActionResult 进入 TurnTrace interaction context，Background 仍按每 Cycle 的既有规则重建，job 状态不进入 Background。

`script.wait` 默认 15 秒，允许范围 5 至 60 秒；运行中 job 的相邻 Cycle 还必须满足默认 `cycle_wait_seconds=30` 的最小启动间隔。run initial wait 和当前 Cycle 的其它耗时计入该间隔，不机械追加完整 30 秒；进程结束或上述当前 Turn input/control 可提前进入下一 Cycle。SignalBus 使用 emission cursor 和 predicate 提供 non-consuming wait，唤醒不抢走业务 Signal，同一旧 Signal 也不能反复唤醒。

默认进程上限 1800 秒，额外监督 Cycle 上限 32。Turn stop、失败、耗尽、Runtime transfer 或正常离开时，TurnRunner 在 `finally` 中调用 job manager 终止进程并 best-effort 清理 retained staging；cleanup 错误只形成 Observation，不能替换原始 transfer 或失败。

每个 job 的完整 staging 固定为：

```text
runtime/.staging/script-job-*/
├── source/       # policy 校验并经 snapshot digest 复核的执行入口
├── workspace/    # active Workspace 的事务 mirror/cwd
└── logs/
    ├── stdout.log
    └── stderr.log
```

完整日志不建立 Link、不进入 Workspace Manifest 或 Daily archive。`ManagedProcessRunner` 在 Script 场景使用调用方提供的 `logs/`；同步 subprocess 未提供 capture root 时仍使用自己拥有并清理的系统临时目录。

## 共用执行层迁移（已确认，待实施）

当前实现由 `tinysoul.capabilities.script` 自己拥有 job manager、Turn activity controller 和 `runtime/.staging/script-job-*`，Catalog 使用 `backend.kind=script`。下一阶段会在保持本文件上述 Script 行为不变的前提下完成以下迁移：

- job manager、Workspace transaction 协调、日志/候选观察、Cycle pacing、额外 Cycle 与 cleanup 下沉到 capability-internal `tinysoul.capabilities.supervised_process`；`tinysoul.workspace` 仍拥有 mirror/diff/CAS/bundle mutation；
- `backend.kind=script` 无 alias 地替换为 `backend.kind=supervised_process`，Script registrar 仍注册 Script 专用 handler，不增加通用 inline executor；
- staging identity 改为 `runtime/.staging/supervised-process-job-*`；Script job 仍使用 `source/` 保存经 snapshot digest 复核的冻结入口，Shell job 可以不使用该目录；
- `[capabilities.script]` 只保留 Script-owned source、authoring、Python/Bash 与依赖配置；wait/runtime/log/mirror/candidate 共用上限迁到 `[capabilities.supervised_process]`；
- 同一 Turn 的唯一 unresolved job 从“仅 Script”提升为“Script 与 Shell 共用”，后续 action 必须校验 execution id、Turn scope 和 owner，Shell 不能 wait/apply Script job，反之亦然；
- `core.answer` admission 由共享 manager 判断任一 owner 的 unresolved job；Loop 仍只依赖一个通用 activity controller。

迁移不改变 Script 的身份：authoring/run 继续只接受 `workspace:scripts/...` 或 `home:how/<existing-skill>/scripts/...` Link，不接受 inline source；promote、source policy/digest、成功后显式 apply/discard 和 Home Maintenance 语义都保持不变。Script 配置、依赖和 source 失败仍由 Script 拥有；共用 wait/continuation/cleanup 的 non-Action activity failure 才改由 `supervised_process` Runtime bridge 表达。

## Workspace 提交

事务镜像记录创建时每个资源的 digest、retention 与 owner Turn。apply 只提交实际 diff：

- 既有路径只有 active digest 仍等于 baseline 才可覆盖或删除；
- 新路径只有 active Workspace 仍不存在才可创建；
- 不同路径的 Turn 内并发变化可以保留；同路径冲突拒绝整批提交；
- 新资源归当前 Turn，既有资源保留原 retention 与 owner。

镜像文件数、单文件大小、总大小、日志、参数、source 和候选读取都有独立上限。镜像拒绝 symbolic link，提交继续通过 WorkspaceEngine bundle mutation，而不是绕过 manifest/trash/reconciliation 规则直接写 active root。

## 失败语义

无效 Link、缺失 HOW、语法拒绝、source digest 变化、参数越界、非零退出、日志越界、运行超时、非法状态和 apply 冲突是局部 ActionResult。Home lazy copy 与 Workspace Trash restore 保留既有 Runtime trap 语义。Home/Workspace IO、reconciliation 与 invariant 失败通过 owner Runtime bridge 保留模块归属；Loop 直接调用的 `wait_before_cycle` 与 `allow_additional_cycle` 属于同一 non-Action Script activity 边界，内部失败使用 Script failure kind/Runtime bridge。Script 配置错误和启用 Bash 但 executable 不存在使用 `script.configuration_failed`；Catalog/Action registrar 自身不一致仍属于 Action 启动失败。

job 的原始 staging 绝对路径不进入 ActionResult。结果只暴露 execution id、source Link/digest、状态、有界日志、候选相对路径及 digest/size；候选正文只能通过显式有界读取获得。
