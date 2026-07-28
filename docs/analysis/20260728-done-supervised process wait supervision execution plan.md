# Supervised Process 等待监督执行计划

## 目标

在保持每个 Turn 最多一个 unresolved Script/Shell job 的前提下，统一模型显式等待、Loop 自动 pacing、Action Schema、进程活动观察和额外收尾 Cycle 的真实语义。

## 设计决策

- `initial_wait_seconds` 继续表示 run 后的内部首次观察窗口，不属于模型可选等待范围。
- `cycle_wait_seconds` 默认 15 秒，表示没有显式等待时相邻 Cycle 的防空转间隔。
- 模型可选 `wait_seconds` 的确定性边界为 15 至 60 秒；项目配置可以在该绝对范围内收紧，effective Action Catalog 必须投影实际 minimum/default/maximum。
- 显式 wait 正常等待到期后已经满足 pacing，下一 Cycle 不再叠加自动等待；进程结束、当前 Turn 用户输入和 stop/exit control 继续提前唤醒。
- 进度只表达 Manager 可确定的 observed activity，不解释日志业务含义、不虚构完成百分比，也不因普通日志增长主动唤醒模型。
- 普通 Cycle 预算耗尽后，所有 unresolved job 状态都可以申请有界收尾 Cycle，使 ready/failed/timed-out/stopped job 有机会 apply 或 discard。
- 本轮不支持多个 unresolved job，不改变 `_by_turn` 的一对一所有权。

## 执行项

- `completed`：扩展 Action Schema 的 `minimum`、`default`、`maximum` 定义与参数校验，并增加 effective tool property schema override。
- `completed`：调整 supervised-process 配置边界、显式 wait 与自动 pacing 协作、terminal resolution Cycle。
- `completed`：增加 wake reason、实际等待时间、剩余运行时间和日志/候选 observed activity。
- `completed`：同步 package Catalog、Development/Standard 配置、domain HOW、设计文档和项目规约。
- `completed`：补充聚焦测试并运行完整 pytest 与 ty 验证。

## 验收

- 模型在有效 ToolScope 中看到实际 `wait_seconds` minimum/default/maximum。
- 显式 wait 只等待请求区间，不再附加 `cycle_wait_seconds`；提前唤醒原因可区分。
- observation 能稳定表达本次等待和相对上次 observation 的活动事实。
- 配置越过绝对等待边界或内部关系不一致时在配置边界失败。
- terminal unresolved job 在普通 Cycle 上限后仍有有界收尾机会。
- `scripts/test.ps1` 与 `scripts/typecheck.ps1` 通过。

## 验证结果

- `scripts/test.ps1`：832 passed，23 skipped。
- `scripts/typecheck.ps1`：All checks passed。
