# Execution 与 Job

`plugins/execution` 将显式 script/shell 请求转换为受控进程；`kernel/jobs` 拥有 Job 受理、Turn 隔离、监视、终态通知与有界结果保留；`infra/process` 提供无业务依赖的进程组、标准输入输出和有界停止。Agent 组合根每个运行世代创建一个 JobRegistry，User、Home Reflection 与 Memory Reflection 复用该对象，各自按所属 Turn 访问。

`execution.run_script`、`execution.run_shell` 等待当前 Job 完成；`execution.start` 返回 Job 身份，由后续 Cycle 通过 `core.job.status/wait/stop` 监督。两条路径使用同一 ProcessJobBackend。普通文件或长期脚本的编辑仍属于 Workspace/Home。Action catalog 位于公共 assets；`execution` 配置解释器与执行上限，`jobs` 配置容量，动作可见性由 catalog 的情景策略解释。

进程直接操作当天 Workspace。默认 cwd 是该 Job 独立的 `workspace:jobs/<job_id>`；显式 `cwd_link` 可以选择已有 Workspace 目录，`workspace:` 在此参数中表示当天根目录。Workspace owner 校验并解析物理位置，脚本源码读取为一次有界快照，随后放入 Job 目录运行。这个目录不是操作系统沙箱。文件写入即时生效；失败、停止或取消不回滚已写文件，也没有 apply/discard 提交路径。

`execution.collect` 读取 stdout/stderr 分页、退出事实与资源 Link，重复读取相同 cursor 不会再次执行进程。日志保存在 Job 的 Workspace 目录中，随日生命周期归档。`execution.stdin` 只向仍可写的交互管道提交最多 4096 UTF-8 字节，返回实际接收字节数；未接收部分仍由调用者负责。没有输出不能证明进程正在等待输入。

Job 终态为 succeeded、failed 或 cancelled，超时与输出上限作为失败原因。监视器观察输出大小并停止超限进程，采样之间可能有额外输出；有界 collect 不承诺所有超限字节都能进入模型。进程终止后关闭执行句柄，结果在当前 Turn 内保留，不占活任务额度。结果容量耗尽时拒绝新任务，不悄悄逐出仍承诺可读的结果。

有界 run 遇到 Action 取消或超时，在退出等待边界前停止并 join 所属 Job。Turn 收尾通过 Agent 的 activity 组合先清理共享 Jobs，再让 Workspace reconcile 并同步最终投影，随后才释放日级执行位置。跨午夜的活动 Turn 始终使用其原日 Workspace。日志句柄或临时文件的附属清理失败保留有界诊断；持续无法停止的受控进程由 Jobs bridge 保留必要运行转移，不能伪造成功或移除仍活动的条目。

未知 Job、已关闭 stdin、无效参数与启动失败属于可修正的 Action 结果。Job 监督、Workspace/Home IO 或模块不变量失败经各自 owner bridge 转换；模型反馈不包含原始异常文本、绝对路径或 traceback。通用 answer guard 只阻止存在尚未关闭执行的 Job，未 collect 的终态结果本身不阻止回答。
