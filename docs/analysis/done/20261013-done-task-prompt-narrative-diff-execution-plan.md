# TaskPrompt 概览差异执行计划

状态：done（2026-10-13）

## 已确认目标

Task Guide 的完整正文发生尾部变化时，当前 turn.md 重复摘录相同前缀，实际变化被截掉。改为首次短摘录、后续展示相对前一次同 label 请求正文的变化；完整 request 继续提供证据。

## 实施方案

- 在导出阅读投影内复用 `visualization/src/utils/diff.ts` 的逐行比较，适用于所有 `task_prompt:*`，不识别特定阶段、提示词或失败文案。
- 以 label 保存最近一次观察的正文和请求 sequence；相同正文省略，变化时显示有界的新增/删除行及比较来源。恢复到已出现版本仍按本次变化呈现，不再用全局见过的正文集合屏蔽。
- 增删两侧都有变化时分配摘录空间，保留当前 request 和上次 request 的链接。现有输入、Trace、plan/jobs 的选择规则与完整导出文件不变。
- 更新导出测试和前端设计文档，核对真实包的 Task Guide 更新投影；不修改原始 ZIP，不变更 Phase 协议或生成预算。

## 验收

- 长 Guide 的尾部追加反馈直接可见，未变正文不反复摘录。
- 连续相同正文省略；替换、删除及回到旧版本均可解释，比较顺序与实际请求一致。
- 摘录有界，证据链接有效，完整 request 正文不受影响。
- 导出专项、前端全量测试、TypeScript 检查与构建通过；按 AGENTS.md 运行完整本地门禁后记录结果并归档。

## 实施核对

- `exportNarrative.ts` 复用通用逐行 diff，替换原有 TaskPrompt 的全局去重和 label 集合，以前一次同 label 的观察为比较基准。正文相同也更新来源 sequence，确保变化所指的是最近一次真实请求。
- 新增两项导出回归，覆盖长前缀后的反馈、连续相同正文、删除、恢复版本、独立 label、双侧长文本摘录及 task/attempt 两种 request 链接。完整 request 正文和链接有效性同时核对。
- `visualization/docs/design/chat.md` 已同步阅读投影语义；实现只改变导出叙事，不进入运行模型 Context、不改变 owner 事实或 Phase 控制流。
- 使用提供的 ZIP 中 30 次 request 做临时投影核对：Phase1 Guide 固定摘录只有 1 次，其余 11 次更新呈现真实的反馈增删；重复正文省略，回到旧版本的变化不再被漏掉。核对工具和预览留在 `B:/tmp/turn-prompt-review/`，原 ZIP 未改写，测试不依赖这份真实轨迹。
- 导出专项 10 项通过；前端全量 91 文件、805 项通过；TypeScript 与 Python ty 检查通过；Vite build 通过（现有 chunk 大小提示）。Python Fast 1270 项、Full 1275 项通过；`git diff --check` 通过。
