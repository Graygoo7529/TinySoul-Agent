# Trace 包根路径与 Turn 叙事执行计划

状态：`done`。2026-10-12 完成实施、设计同步和验证。

## 目标和范围

桌面端继续通过保存对话框导出 ZIP；所有文件使用同一个包根，根目录增加 `turn.md`，使研究者先了解整个 Turn，再沿链接查看完整 Cycle/Phase/Task/Attempt 证据。本计划由此前混合草案中的 Trace 部分独立整理，Phase1/Phase2 方案不作为已完成内容，见 [独立阶段计划](../20261012-phase-protocol-and-generation-budget-execution-plan.md)。

## 实施内容

```text
turn-trace-<turn-id>/
├── turn.md                         # 阅读入口
├── manifest.json / index.json     # 窗口边界和导航
├── cycles/001/
│   ├── cycle.json                  # 阶段范围及生命周期事实
│   ├── phase1/llm/tasks/...
│   ├── phase2/llm/tasks/...
│   ├── phase2/actions/calls/...
│   ├── phase3/llm/tasks/...
│   ├── phase3/actions/results/...
│   └── phase3/auxiliary-model/...
└── unscoped/...                    # 无 Cycle 归属的现有记录
```

1. `visualization/src/features/trace/export.ts`：各生产函数统一输出包内相对路径，返回归档文件集合时统一加根。索引和 request_ref 仍相对于包根。manifest/index 升为 schema version 2，增加 narrative_path；cycle_count 只统计真实 Cycle，不把 unscoped 算作 Cycle。
2. `cycle.json` 增加原始 `loop.phase.*` 生命周期事件投影，保存阶段失败、取消、selected_domains 和已产生的 control_results，供概览链接核对；不推断缺失的阶段。
3. `exportNarrative.ts`：独立的纯阅读投影构造器，从相同 EventWindow 生成 turn.md。先给出 Cycle/Phase 状态及 Action 结果总览表，再按 sequence 展示窗口边界、Cycle/Phase、模型请求入口、返回文本、工具意图、usage/推理摘要摘录、task/provider 结果、Action 准备/执行/结果和 Turn 输出；Phase3 内模型调用与其它阶段同样展示。
4. 从实际 request.messages 摘录初始输入、TaskPrompt、phase_note、模型可见 action_result 及变化的 plan/jobs。相同语境不反复展开，重复出现次数增长的 Trace 消息仍可见，Working 状态恢复为旧值也视为变化。每次新增摘录归属首次捕获该内容的请求，不倒推原始事件时间。
5. 长文本、参数和摘要只做有标记的摘录，完整 request/response 不截断。模型调用意图不视为控制已应用或 Action 已执行；provider 返回也不视为 task/Phase 成功。缺失请求、响应或反馈如实保留。

模型可见 ActionResult 的正文仍以实际后续 request 为准，不读取 Session 文件补造历史。Job 唤醒和阶段失败有时只出现在下次模型请求的 Context 中，概览展示该原始语境摘录，不凭 Action 名称或最终输出猜测原因。内部 provenance/resolved_references 继续不进入导出 request；概览不复制完整 Background、工具 schema 或消息栈。

## 边界与所有权核对

- Observation 是唯一输入；没有新日志、SDK 请求或模型总结调用。
- LLM、Action、Context 和 Job 的业务状态没有改变，Tauri 仍只负责归档传入文件集合。
- 新 TS 文件只分离文字投影职责，目录分组和路径归属仍由原 export 构造器统一维护；证据路径从文件构造处传入，不重新猜路径。
- `turn.md` 面向轨迹研究，不自动回灌运行中的 Context；其中内容不是新增的模型固定提示。
- 正常窗口与截断窗口使用同一路径。保留的原始请求再长也保存在详细文件中，概览只是阅读入口。

## 核对表

- [x] Action、LLM、auxiliary-model 和叙事均在唯一包根下。
- [x] 包内索引和 Markdown 证据链接可解析，request 共享和 attempt 差异仍正确。
- [x] Phase1–3、模型返回、Action 状态、请求语境及 Turn 输出进入时间线。
- [x] 待答/Job/失败事实有来源时可见，无来源时不补造。
- [x] `unscoped` 不计入真实 Cycle 数量；阶段生命周期可核对。
- [x] 前端 chat/action-renderers 设计文档已同步。
- [x] 导出器及保存桥接共 7 项测试、前端全量 91 文件/802 项、TypeScript/Vite、Tauri 归档测试通过。保存桥接验证对话框参数、文件集合传递、取消、错误传播和浏览器 fallback。
- [x] 项目 Fast 1270 项、Full 1275 项及 ty 检查通过；未触发真实 provider/network 测试。

验证使用通用构造样例保护契约，未把某一轮的周期数量、脚本或模型文本固定为测试输入。旧真实 ZIP 留作诊断证据；本轮没有重写 reference，也未重新运行桌面 GUI 保存流程。Vite 仍提示已有的大 chunk，构建成功。
