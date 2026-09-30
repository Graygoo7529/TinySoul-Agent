# demand 目录索引

前端向后端提出的能力需求。规则（根 AGENTS.md「用户对接」）：前端发现缺失能力时不阻塞实现，
在此记录需求单；后端 v2 重构前的旧需求单一律不作为实现依据，已归档到 `archived/` 并附归档结论。

## 当前需求（前端收口）

| 文件 | 需求 | 提出日期 | 前端临时处理 |
| --- | --- | --- | --- |
| `20260930-catalog-render-pdf-pages-choices.md` | 后端 catalog 已与 `disabled/on_no_text` 对齐 | 2026-09-30 | 前端改为直接消费 choices |
| `20260930-catalog-kimi-search-model-choices.md` | 后端 catalog 已声明 `kimi-k2.5/kimi-k2.6` choices | 2026-09-30 | 前端移除设置页重复硬编码 |
| `20260930-home-agent-top-document-503.md` | Home actual/effective 浏览语义已明确且后端已分离 | 2026-09-30 | 前端实现 actual/effective 切换和未物化空态 |

## 已归档（archived/）

v1 时期的需求单，均不适用于当前 v2 契约；归档结论见各文件。

| 文件 | 结论 |
| --- | --- |
| `archived/20260804-done-endpoint-responsiveness.md` | done：Endpoint 服务与执行解耦已落地 |
| `archived/20260804-done-session-history-persistence.md` | done：事件 Journal 持久化已落地 |
| `archived/20260808-mounted-skills-event.md` | superseded：由 PromptGuidance/TaskPrompt provenance 取代 |
| `archived/20260809-action-execution-started-event.md` | superseded：由统一 `action.execution` 状态观测取代 |
| `archived/20260809-action-result-content-preview.md` | superseded：不设通用 content_preview，由 owner 专用呈现取代 |
