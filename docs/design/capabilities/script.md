# Script Capability 设计

## 定位

`tinysoul.capabilities.script` 提供临时与长期脚本的编写、修改、显式提升和 Turn 内监督执行。它不拥有新的 Link namespace：临时脚本使用 `workspace:scripts/...`，长期脚本使用 `home:skills/<skill>/scripts/...`。长期目标必须属于已存在的通用 skill；创建 skill 不属于本阶段。

脚本执行面向 Workspace 资源处理。执行器为每个 job 建立 active Workspace 的有界事务镜像，以镜像根作为进程 `cwd`，并设置 `TINYSOUL_WORKSPACE` 指向同一目录。脚本只修改镜像；成功退出只进入 `ready_to_apply`，不隐式修改 active Workspace。这里的安全语义是事务隔离、语法/参数/资源限制和受控进程终止，不宣称操作系统级硬沙箱。

## 源与提升

- `execution.create_script` / `execution.rewrite_script` 复用 `LLMActionTaskRunner.run_text`，因此继承当前 Turn Context、Workspace reference 和 Home-owned domain/action skill；create 只允许新目标，rewrite 才覆盖已有目标；模型只返回完整 source 文本工件，不使用 JSON wrapper；
- `execution.patch_script` 只做唯一精确替换，并在写入前执行确定性语法策略检查；
- `execution.promote_script` 只允许从 `workspace:scripts/...` 复制到 `home:skills/<existing-skill>/scripts/...`，扩展名必须保持一致；
- promote 写入 lazy runtime Home，随后由普通 Home Maintenance review/apply；它不直接写实际 Home，也不自动创建 skill。

`ScriptSource` 是一次 read 产生的不可变源码 snapshot。owner resource digest 绑定 Workspace/Home Link 的资源版本和后续 CAS；解码后的 snapshot 另以固定 UTF-8 字节计算 `snapshot_digest`。policy 只校验该 snapshot，process 也只执行 job `source/` 中经 snapshot digest 复核的冻结入口；不得在 policy 后再次按 Link 读取执行内容。Workspace mirror 创建时逐文件复核复制字节与 baseline resource digest，Workspace source 的 baseline digest 还必须等于 resolver 读取时的 owner digest。`execution.promote_script` 同样直接写入已校验 snapshot，不二次读取 source Link。

`max_source_chars` 是 Script 的读写共同边界：read、LLM create/rewrite 输出、patch 后完整候选、promote 与 resolver 最终 mutation 都必须检查。Workspace/Home 自有 mutation 上限继续独立生效，实际边界取二者较小值。

Catalog 为 Script authoring 声明 `max_output_tokens=16384` 和 `max_output_chars=100000`。generation budget 属于 provider 调用，artifact bound 与 Script 默认 `max_source_chars` 对齐但由不同边界各自校验：共享 LLM action 在 owner mutation 前拒绝过大完整工件，Script policy 继续验证语言/source 语义和最终 source 大小。输出上限或未完成响应不形成候选 source，也不会把部分源码放入 ActionResult/Context。

Python 默认启用并使用当前 TinySoul Python 解释器。Bash 独立配置、默认关闭；启用时由 Infra dependency checker 检查配置的 executable。两种语言使用独立 run action，避免把任意 inline command 或 shell 字符串作为执行接口。

## Job 生命周期

Script 与 Shell 的模型侧动作统一位于宽泛的 `execution` Domain；Capability 仍分别拥有 source/command policy、配置、依赖和启动 handler。每个 Turn 跨 Script/Shell 最多拥有一个 unresolved job。job 不跨 Turn、不持久化、不跨重启。`execution.run_python_script` / `execution.run_bash_script` 启动进程后先等待配置的 initial interval，返回 execution id、owner、状态、有界增量日志和候选文件 metadata。

后续动作固定为：

- `execution.wait`：等待进程完成、等待区间到期，或当前 Turn 中合法的 `context.input.append` / `loop.control.request`；日志增长、其它 namespace、其它 Turn 和非法 payload 不唤醒；结果区分 interval、process exit、user input、Turn control、runtime limit 与 action cancellation 等 wake reason；
- `execution.stop`：终止进程并保留镜像供检查；stopped 不可 apply；
- `execution.read_candidate`：按候选相对路径读取有界 UTF-8 文本；候选路径不是 Link；
- `execution.apply`：只允许 `ready_to_apply`，逐文件比较创建 job 时的 baseline digest 与当前 active Workspace；同路径并发变化拒绝整个提交，job 保留；
- `execution.discard`：关闭非运行 job 并删除镜像、日志和候选，不修改 active Workspace。

failed、timed_out、stopped 只能 inspect/read/discard。即使进程快速成功也必须显式 apply 或 discard。`core.answer` execution hook 在 job unresolved 时拒绝最终回答。

## 长任务监督

普通 Turn Cycle 上限耗尽后，共享 manager 中任一 unresolved Script/Shell job 都可以申请额外监督 Cycle；额外预算与进程最大运行时间分别受限。running job 由此继续监督，ready/failed/timed-out/stopped job 由此获得有界 apply/discard 收尾机会。每个额外 Cycle 仍完整执行 Phase1、Phase2、Phase3，因此新的 job ActionResult 进入 TurnTrace interaction context，Background 仍按每 Cycle 的既有规则重建，job 状态不进入 Background。

模型可选 wait 默认 15 秒，范围为 15 至 60 秒；三项值由项目 `execution.wait` Action TOML 的 Tool Schema 单一拥有，并可在 Action Catalog 设置页修改。Generation 编译时，supervised-process 把有效 `ActionSpec` 转换为强类型 wait policy；Manager 用其校验边界，executor 用其解释缺省参数。运行中 job 在没有显式 wait 时受默认 `cycle_wait_seconds=15` 的防空转间隔约束；该间隔与 Action 参数 contract 分属不同语义。显式 wait 正常到期时本身已经完成 pacing，下一 Cycle 立即开始，不再追加自动间隔。run initial wait 是独立的内部首次观察窗口。进程结束、当前 Turn input/control 可提前进入下一 Cycle。SignalBus 使用 emission cursor 和 predicate 提供 non-consuming wait，唤醒不抢走业务 Signal，同一旧 Signal 也不能反复唤醒。

每次 job observation 还返回 requested/actual wait、剩余运行时间，以及相对上次 observation 的 observed activity：日志字节增量、Workspace diff 是否变化、候选数量变化和距上次观测到活动的时间。这些是 Manager 可以确定的运行事实，不解释日志业务含义或完成百分比；日志活动本身不触发新的模型 Cycle。所有 job observation 只进入 TurnTrace，不成为 Background 状态。

默认进程上限 1800 秒，额外监督 Cycle 上限 32。Turn stop、失败、耗尽、Runtime transfer 或正常离开时，TurnRunner 在 `finally` 中调用 job manager 终止进程并 best-effort 清理 retained staging；cleanup 错误只形成 Observation，不能替换原始 transfer 或失败。

每个 job 的完整 staging 固定为：

```text
runtime/.staging/supervised-process-job-*/
├── source/       # policy 校验并经 snapshot digest 复核的执行入口
├── workspace/    # active Workspace 的事务 mirror/cwd
└── logs/
    ├── stdout.log
    └── stderr.log
```

完整日志不建立 Link、不进入 Workspace Manifest 或 Daily archive。`ManagedProcessRunner` 在 Script 场景使用调用方提供的 `logs/`；同步 subprocess 未提供 capture root 时仍使用自己拥有并清理的系统临时目录。

## 共用执行层

当前实现已在保持本文件上述 Script 行为不变的前提下完成以下迁移：

- job manager、Workspace transaction 协调、日志/候选观察、Cycle pacing、额外 Cycle 与 cleanup 位于 capability-internal `tinysoul.capabilities.supervised_process`；`tinysoul.workspace` 仍拥有 mirror/diff/CAS/bundle mutation；
- Catalog 使用 `backend.kind=supervised_process`，Script registrar 仍注册 Script 专用 author/run handler；共享层只注册 `execution.wait/stop/read_candidate/apply/discard` 对应的生命周期 handler，不存在接受任意 inline 参数的通用 run executor；
- staging identity 为 `runtime/.staging/supervised-process-job-*`；Script job 使用 `source/` 保存经 snapshot digest 复核的冻结入口，Shell job 不需要该目录；
- `[capabilities.script]` 只保留 Script-owned source、authoring、Python/Bash 与依赖配置；runtime/log/mirror/candidate 及内部 initial/cycle pacing 位于 `[capabilities.supervised_process]`；模型显式 wait 的 minimum/default/maximum 属于 `execution.wait` Action contract；
- 同一 Turn 的唯一 unresolved job 从“仅 Script”提升为“Script 与 Shell 共用”；启动 action 记录 owner，后续生命周期 action 只提交 execution id，由 Manager 在当前 Turn 内解析实际 owner，模型无需先判断它是 Script 还是 Shell job；
- `core.answer` admission 由共享 manager 判断任一 owner 的 unresolved job；Loop 仍只依赖一个通用 activity controller。

该组织不改变 Script 的身份：authoring/run 继续只接受 `workspace:scripts/...` 或 `home:skills/<existing-skill>/scripts/...` Link，不接受 inline source；promote、source policy/digest、成功后显式 apply/discard 和 Home Maintenance 语义都保持不变。Script 配置、依赖和 source 失败仍由 Script 拥有；共用 wait/continuation/cleanup 的 non-Action activity failure 由 `supervised_process` Runtime bridge 表达。

## Workspace 提交

事务镜像记录创建时每个资源的 digest、retention 与 owner Turn。apply 只提交实际 diff：

- 既有路径只有 active digest 仍等于 baseline 才可覆盖或删除；
- 新路径只有 active Workspace 仍不存在才可创建；
- 不同路径的 Turn 内并发变化可以保留；同路径冲突拒绝整批提交；
- 新资源归当前 Turn，既有资源保留原 retention 与 owner。

镜像文件数、单文件大小、总大小、日志、参数、source 和候选读取都有独立上限。镜像拒绝 symbolic link，提交继续通过 WorkspaceEngine bundle mutation，而不是绕过 manifest/trash/reconciliation 规则直接写 active root。

## 失败语义

无效 Link、缺失 skill、语法拒绝、source digest 变化、参数越界、非零退出、日志越界、运行超时、非法状态和 apply 冲突是局部 ActionResult。Home lazy copy 与 Workspace Trash restore 保留既有 Runtime trap 语义。Home/Workspace IO、reconciliation 与 invariant 失败通过 owner Runtime bridge 保留模块归属；Loop 直接调用的 `wait_before_cycle` 与 `allow_additional_cycle` 属于共享 non-Action activity 边界，内部失败使用 `supervised_process` failure kind/Runtime bridge。Script 配置错误和启用 Bash 但 executable 不存在使用 `script.configuration_failed`；Catalog/Action registrar 自身不一致仍属于 Action 启动失败。

job 的原始 staging 绝对路径不进入 ActionResult。结果只暴露 execution id、source Link/digest、状态、等待/活动事实、有界日志、候选相对路径及 digest/size；候选正文只能通过显式有界读取获得。
