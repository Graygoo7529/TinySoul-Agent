# Loop 设计

## 定位

Loop 模块只负责一次 Turn 内的运行编排：Turn、Cycle、Phase 及 Runtime 运行转移的消费。顶层 Program、typed request queue、外部输入和 scheduler 属于 `tinysoul.app`；业务日、确定性日切和 Archive/Home/Memory 任务编排属于 `tinysoul.maintenance`。

Loop 根不维护语境状态，不定义行动或 Maintenance 业务语义，不做模型供应商适配，也不直接读写 Home、Memory、Session 或 Workspace。`assembly.py` 把 context、action、llm 三个门面组合成可复用的 3-stage Turn kernel；`loop.user` 构造 User Turn 主线，Maintenance 支线在 `tinysoul.maintenance.turn` 内复用 kernel。

## 目录组织

```text
tinysoul/loop/
  assembly.py                # owner-neutral Turn kernel assembly
  turn.py                    # 通用 TurnRunner
  cycle.py                   # 共用 CycleRunner
  phases.py                  # Phase1/Phase2/Phase3
  preparation.py             # 通用 preparation pipeline
  completion.py              # 通用 completion pipeline
  prompts.py                 # 共用 Phase prompt 构造
  outcomes.py                # TurnOutcomeStatus / TurnFailure
  signals.py                 # Turn 内 control/output 信号
  context_signals.py         # Context signal 批量提交
  pressure.py                # owner-neutral pressure protocol/result/sizing
  trap_handlers.py           # owner-neutral frame/pressure handler
  user/
    builder.py / entry.py    # User Turn 构造与 App 轻量入口
    actions.py / context.py  # User ActionEngine 与 effective Context
    runtime.py / pressure.py # User Home/Workspace runtime policy
    preparation.py           # User Turn preparation exports
    completion.py            # core.answer completion
    prompts.py               # User Turn guidance
    outcomes.py              # User Turn outcome exports
```

`loop/__init__.py` 只导出通用运行 SPI；`loop.user` 导出主线 builder/entry。Loop 根和 User 包都不导入 `tinysoul.maintenance`，也不存在 `loop.maintenance`、`loop.program`、`loop.daily` 或跨模块 Maintenance runner。

## 通用 Turn

`TurnRunner` 接受本轮输入、权威 `BusinessDay`、Program scope 和 request identity。BusinessDay 由调用方捕获；同一 Turn 内不再读取系统日期，因此跨午夜仍属于开始时的业务日。

Turn scope 建立后，Runner 依次：

1. 调用 Context begin，建立独立 UserInputs、Background、TurnTrace 和 Working 状态；
2. 运行有序 `TurnPreparationPipeline`，批量提交 Background、Session、Workspace 等 owner signals；
3. 循环运行 Cycle，直到 profile completion、Runtime transfer、失败或 cycle budget 耗尽；
4. 对成功 completion 运行可选 `TurnCompletionPipeline`；
5. 在 finally 中结束 Context 并清理 Turn-scoped activity。

`TurnOutcomeStatus` 对两类 Turn 统一表达 `completed/exhausted/stopped/failed`。profile 可以把 completion 映射为用户输出，也可以仅保留 owner completion；通用 Runner 不假定每个 Turn 都产生聊天回答。

## User Turn

User Turn preparation 按以下顺序构造情景：

1. Context 从 effective Home 与 `memory:current + optional latest` 等 provider 原子重建 Background；
2. Session 投影当前业务日的跨 Turn 历史；
3. Workspace reconcile 当前业务日并投影 Manifest。

User ActionEngine 只加载 `tinysoul.action` 自有 catalog；Maintenance domain 物理上不在该资源根，因此不需要字符串过滤。唯一成功的 `core.answer` 由 `UserAnswerCompletionDetector` 直接转换为 Turn completion，再由 User profile 转换为用户输出；默认 completion pipeline 先由 Session 校验 sealed entries 并幂等写入 schema v4 User Turn record，再运行其它后处理。

User Turn 可以在 Phase/Cycle 边界消费当前 Turn scope 的 `context.input.append` 和 `loop.control.request`；旧 scope 或无 Turn scope 的信号不得影响后续 Turn。

## Maintenance Turn

Maintenance Turn 由 `tinysoul.maintenance.turn` 拥有，并与 User Turn 使用同一个 `TurnRunner`、`CycleRunner` 和 Phase1/2/3 kernel。它不是一次独立裸 LLM 调用，而是在完整情景中继续思考和整理：仍有 Background、Session、Workspace、TurnTrace 和 Working，只改变输入、专用 guidance、精确 ActionEngine 与 completion policy。

Maintenance Context 与 User Context 相互独立，并使用 actual Home provider，避免待审 runtime override 先成为判断规则。Home 与 Memory Turn 也各自构造 Context、SignalConsumer 和 trap，不共享活跃 Turn 状态。Home preparation 注入当前 Session 与 Workspace；目标关闭日的 Session/Workspace 绑定属于 `tinysoul.maintenance.memory.ArchivedMemoryMaintenanceContext`。Maintenance pressure recovery 只回收自身 Context，不注册 User 专属的 active Workspace cleanup、Workspace trash restore 或 Home runtime copy；Memory 任一路径都不会修改 active Workspace。Maintenance Turn 不写入 User Session completion。

Maintenance ActionEngine 只包含：

- 两类 Turn 可复用的只读 `core.context.inspect`、`core.session.inspect`；
- 当前 task 的精确 `maintenance.home.*` 或 `maintenance.memory.*` actions；
- task owner-bound `maintenance.complete`。

Home 与 Memory Maintenance Turn 不互相暴露 actions，也不提供 `core.answer`、普通 Home mutation、Workspace mutation、Shell 或其它 User actions。成功的 `maintenance.complete` 先由 action owner 校验所有后置条件，再由 `MaintenanceCompletionDetector` 结束 Turn；模型不能用普通文本自行宣布完成，也不能等待人类审批。

## Cycle 与 Phase

每个 Cycle 固定顺序执行三个单元：

1. Phase1 基于完整 Context 调用 framework task，消费 Context control tools，并选择一个或多个可见 action domain；重试耗尽时返回空 domain 与 phase note（局部结果），不直接 end turn；无有效 domain 时先消费有效控制调用再反馈重试。若 provider 在要求选择时返回了其它可见控制调用，后续有界重试收窄为只暴露 domain-selection tool，并把稳定失败反馈带入同一 Cycle 以及下一 Cycle；Turn 级仅在连续多次 Phase1 选择失败后有界收敛；
2. Phase2 只暴露已选 domain 的具体 Action Tools，生成并归一化 ActionCall；
3. Phase3 装配和执行 ActionBatch，把 ActionResult 反馈写入 TurnTrace，并交给 profile completion detector。

Phase1/Phase2 的共用 task prompt 可以叠加 `turn_guidance`。User profile 要求围绕当前用户请求工作并最终调用 `core.answer`；Maintenance profile 说明这是自治维护、应结合 Background/Session/Workspace、不得生成用户回答或等待审批，并要求仅在 owner 后置条件满足后调用 `maintenance.complete`。

`ContextSignalConsumer.emit_and_consume` 把同一逻辑步骤的 decision、action results 或 phase notes 作为可重放批次提交。Home 缺页或 Context 压缩 Trap 发生在批次提交前时，Module/Phase retry 不丢信号，也不留下半提交语境。

## Trap 与失败

各运行器只在自己的 frame 边界消费 Runtime transfer。通用 handler 只包含 frame 与 pressure 协议；User runtime policy 额外注册 Home runtime copy、active Workspace pressure cleanup 和 Workspace trash restore，Maintenance runtime policy 只注册 Context pressure。`MaintenanceTurnEntry` 解释通用 Turn outcome 并将指向 Program 的 transfer 以 `RuntimeTransferInterrupt` 原样展开，task 不直接依赖 `TurnRunner`/`TurnOutcomeStatus`；Program 使用独立 Program-only trap。

Action 局部失败留在 ActionResult 中供下一 Cycle 修正。LLM 链耗尽、Context 不变量或 owner preparation failure 经模块 bridge 进入 Runtime，再形成有界 `TurnFailure`。User answer、用户 stop/exit 和正常 Maintenance completion 不伪装为失败。

## 模块边界

- 对 app：App 只调用 `loop.user.UserTurnBuilder/UserTurnEntry`，Loop 不接收顶层 AppRequest。
- 对 maintenance：MaintenanceBuilder 使用通用 kernel SPI 构造自己的 Turn；Loop 不导入或解释 Maintenance、archive journal、Home diff 或 MEMORY 文件。
- 对 context：只经 ContextEngine 门面构造 MessageStack、消费 control tools/signals 和管理 Turn 生命周期。
- 对 action：只经 ActionEngine 门面选择 domain/action、归一化调用并执行批次。
- 对 llm：构造 TaskCall 并消费 provider-neutral TaskResult。
- 对 runtime：信号经 SignalBus，控制流经 RuntimeException、Trap 和 RuntimeTransfer。

Loop 的设计范围到 Turn 边界为止。Program queue、scheduler、日切、Maintenance plan、外部协议、持久化目录与业务 owner 状态均不得回流到 Loop。
