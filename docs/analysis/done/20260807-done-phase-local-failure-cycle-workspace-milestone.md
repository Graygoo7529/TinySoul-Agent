# Phase 局部失败、Workspace 边界与 Milestone 语义改进

状态：`done`

## 背景

`reference/running_trace/20260805-1` 暴露了 Phase1 framework tool protocol 失败后没有稳定恢复、最终 Turn 没有进入完成 Action，以及 Workspace 生成边界与 owner 写入边界含义不清的问题。上一轮已经补充了 Phase1 反馈、Workspace references、写入长度检查和长任务行为原则，但 Phase1/Phase2 仍分别维护内部重试，Phase2 重试耗尽后还会继续执行空 Phase3。

## 已确认设计语义

1. Stage1/Stage2 framework Task 继续使用 `answer_format=NONE` 与 `ToolUse.REQUIRED`。Provider 如果同时返回 `raw_response.answer_text` 或 reasoning，只作为 trace 观察，不作为阶段完成结果。
2. Phase1/Phase2 的可修正 framework 局部失败统一结束当前 Cycle，并作为结构化、有限的反馈进入下一个完整 Cycle。Phase 内不再维护协议重试次数，也不再为 Phase1 建立特例 selection-only 重试作用域。
3. 下一 Cycle 仍必须遵守 Phase1 的域选择协议。模型可以根据上一个 Cycle 的失败反馈修正 Context、改变域或改变后续计划，但不能跳过 Phase1。
4. Runtime 仍拥有 `max_cycles`、supervision cycle、取消和结束语义。删除的是 Phase 内部重试计数，不是 Runtime 防止无限循环的生命周期边界。Provider/model chain 的调用级重试仍由 LLM 模块负责。
5. Phase2 局部失败后不得把空 `ActionNormalization` 交给 Phase3。Cycle 必须在 Phase2 边界结束并携带局部失败反馈。
6. Phase1 prompt 只表达通用阶段边界，不点名 User profile 的 `core.answer`。Phase1 只更新 Context 和选择行动域，不完成 Turn、不产生最终用户输出。
7. Workspace 是写入资源的 owner，`workspace.max_write_chars` 是 Workspace 的硬提交边界。`workspace.write` 与 `workspace.rewrite` 不重复声明 `backend.options.max_output_chars/max_output_tokens`；LLM artifact 和 commit 都使用 Workspace owner 传入的有效边界。其它 owner 的 action backend 配置保持自身语义。
8. Milestone 是少量、持久、可复用的事实寄存器，可以记录有价值的完成、尝试、失败、阻塞、测量值、决定、来源 Link、版本和 digest。它不能伪装 todo 完成，也不记录无长期价值的瞬时噪声。

## 实施范围

- `tinysoul/loop/phases.py`：移除 Phase1/Phase2 内部协议重试，增加统一 `PhaseFailure` 局部结果。
- `tinysoul/loop/cycle.py`、`tinysoul/loop/turn.py`：传播 PhaseFailure，失败后进入下一完整 Cycle，禁止空 Phase3，保留 Runtime cycle guard。
- `tinysoul/loop/assembly.py`、`tinysoul/loop/config.py`、构建器与测试：删除无效的 `phase_retry_limit` 配置和注入。
- Workspace action Catalog、LLM action runner、Workspace prompt/docs/tests：清理重复 backend options，统一 owner boundary。
- Home Agent prompt、Context/Loop/Action/Workspace 设计文档和 AGENT 关键语义：同步 Milestone、阶段边界和失败恢复语义。

## 验收

- Phase1 framework failure 在下一 Cycle 的 Phase1 prompt 中可见，且没有同一 Phase 内第二次协议调用。
- Phase2 framework failure 在下一完整 Cycle 中可见，Phase3 不被调用。
- Runtime transfer、取消、模型链耗尽和模块边界异常仍按原有 bridge 处理。
- Workspace write/rewrite 的 Catalog 不再包含重复输出边界，仍由 Workspace settings 拒绝超长生成和提交。
- Milestone few-shot 覆盖计算值、工作区文档状态、网址/来源和有价值失败尝试。
- TinySoul 环境全量 pytest、typecheck（环境具备 `ty` 时）和静态语义复核通过。

## 实施结果

- `PhaseFailure` 已成为 Phase1/Phase2 的统一局部失败结果；每个 framework Phase 只调用一次，失败在 Cycle 边界停止，Turn 将带 phase/reason 前缀的有限反馈传入下一完整 Cycle。
- Phase2 framework failure 不再执行空 Phase3；原有 provider/model chain 重试和 Runtime cycle budget 保持不变。
- `phase_retry_limit`、Phase1 selection-only 恢复和连续 Phase1 failure 结束逻辑已删除。
- Workspace write/rewrite Catalog 的重复 `backend.options` 已清除，artifact/commit 边界统一由 Workspace `max_write_chars` owner 配置决定；其它 owner action 的 backend options 保持有效。
- Phase1 阶段边界已改为通用“不完成 Turn、不产生最终用户输出”，并保留 Stage1/2 `answer_format=NONE`、`ToolUse.REQUIRED` 与 trace answer/reasoning 语义。
- Milestone 已允许记录有价值的完成、尝试、失败、阻塞、计算值、文档 Link/digest 和权威 URL，并在 Home prompt 中加入 few-shot 示例。

验证：

- `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\test.ps1 -Suite Full`（`TINYSOUL_PYTHON=C:\Anaconda3\envs\TinySoul\python.exe`）：`872 passed, 2 skipped, 21 deselected`。
- `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\typecheck.ps1`（同一解释器）：`All checks passed!`。
- `git diff --check` 通过；Loop/Action/Workspace 聚焦测试通过。
