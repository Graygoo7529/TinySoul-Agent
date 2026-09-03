# 20260724 Session record integrity and Hook outcome boundary correction plan

状态：done

## 背景与目标

Session schema v3 已经持久化 canonical Turn trace、trace digest 和确定性的 Action history，但这些事实分别由 reconciliation、recall、actions 与 Memory projection 以不同深度校验。普通 history 查询还会隐式执行 orphan reconciliation，使一个本应只读的导航或证据读取请求改变 Manifest revision。Action hook 的拒绝结果已经使用 typed `ActionLocalFailure`，但 `HookOutcome` 尚未完整对齐 `ActionResult` 的 payload/failure/frame_data 三通道。

本计划在现有模块所有权下收敛这些边界，不引入第二套 Session 索引、Action 状态机或兼容层。

## 已确认语义

1. Session 维护唯一的 schema v3 Turn record validator。canonical trace 是证据事实；trace digest 是由证据重算的完整性事实；`action_history` 是由同一 trace 确定性派生并持久化的物化摘要，不是独立事实源。
2. validator 校验 Turn record 的结构、identity、trace digest、Action projection，以及 Background 中复制的稳定内在事实。它不根据当前配置重新选择 Background action detail，避免配置变化改写旧 Turn 的提交语义。
3. `session.history.inspect` 只导航 Manifest/Summary/Turn overview，不扫描 Action；`actions` 读取确定性审计，`recall` 读取 canonical trace。三者只读取最近一次已提交状态，不收养 orphan、不修改 Manifest revision。
4. orphan recovery 只发生在 Engine 加载、Turn preparation/completion、显式 reconcile 和 archive 生命周期。损坏的 Turn record 是 Session invariant failure，不静默修复。
5. `HookOutcome.success()` 表示 hook 放行，不产生独立 ActionResult，也不能携带 payload 或 frame data。拒绝结果通过 typed failure 提供唯一模型失败反馈，可选 payload 提供有界业务数据，可选 frame_data 提供 observation-only 诊断；pipeline 添加真实 hook identity。
6. 测试使用代码内最小符号 trace 和动态构造的 record，验证稳定逻辑契约；不读取本地运行记录，也不建立与具体真实轨迹绑定的 fixture。

## 实施项

- [x] 增加 Session-owned `ValidatedTurnRecord` 与唯一 validator，并接入 reconciliation、actions、recall 和 Memory facts。
- [x] 移除 history 查询中的隐式 reconciliation，使 inspect 保持纯导航并删除其 Action 投影副作用。
- [x] 为 `HookOutcome` 增加拒绝 payload，并将 typed failure、payload、frame_data 一次性映射到最终 ActionResult。
- [x] 删除真实运行文件依赖，补充 validator、只读查询、Action projector 和 hook 三通道测试。
- [x] 同步 `AGENT.md`、Session/Action/Endpoint 设计文档并完成全量测试和类型检查。

## 完成结果

- `tinysoul/session/validation.py` 现在是 schema v3 Turn record 唯一完整性入口；`SessionReconciler`、history actions/recall 与 Memory facts 不再各自解释部分事实。
- inspect/actions/recall 不再隐式执行 reconciliation。测试证明未提交 orphan 不进入 authoritative root，查询不改变 revision，显式 reconcile 才接入该 Turn。
- `HookOutcome.reject` 与 `ActionResult.failed` 共享 failure/payload/frame_data 语义；模型 envelope 不包含 frame data，trace/Observation payload 保留诊断。
- Session/Action 测试改用动态 record 与最小符号 trace，不读取 `reference/turn_*.json`，也不增加轨迹 fixture。
- `python -m pytest tests -q` 与 `python -m ty check` 已通过；全量测试因 CLI 单实例锁需要写入 `%LOCALAPPDATA%`，在允许该既有边界的非沙箱环境完成验收。

## 验收标准

- 任意生命周期 reconciliation 都会拒绝 digest 或持久 Action 摘要不一致的 Turn record。
- inspect 不执行 Action projection；inspect/actions/recall 不改变 revision 或收养 orphan。
- recall 与 actions 对损坏 Turn 使用同一 validator 失败语义；Memory facts 不信任未校验的持久派生摘要。
- hook owner 的模型反馈只来自 `ActionLocalFailure.feedback`；payload 出现在模型 Action envelope，frame_data 只出现在 trace/observation payload。
- 全量 pytest 与 ty 类型检查通过，测试不依赖 `reference/turn_*.json`。
