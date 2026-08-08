# Agent 人机协作与多轮交接执行计划

## 状态

- `done`

## 背景

默认 Agent Home 已经要求模型保持判断、提出有依据的异议，并在提问前先利用 Context 和 Action 调查。然而，当前 `core.answer` 的 Catalog 语义只允许在任务完成后回答，`home:agent@AGENT` 也把回答与目标完成、todo 终态紧密绑定。这与多轮协作中的正常交接冲突：当后续工作依赖人的重大判断、仅由用户掌握的信息、进一步指示或可行路线选择时，Agent 应当用一次面向用户的回答结束当前 User Turn，并在下一 User Turn 继续，而不必把整体目标或 WorkingContext todos 伪装为已完成。

`UserAnswerCompletionDetector` 只把唯一成功的 `core.answer` 转换为当前 User Turn completion，并不解释回答正文是否为最终成果。Session 随后保存该轮输入和输出，下一轮可从 Session Background 延续，因此无需新增 `ask_user` Action、暂停状态或 Runtime 控制流。

## 已确认设计语义

1. TinySoul 是主动的思考与执行伙伴。它可以提出问题、假设、替代路线和自己的有依据观点，以启发共同思考，而不是只被动接收指令。
2. 想象力用于探索可能性，不能把构想伪装为事实；表达时应区分事实、推断、构想和偏好。
3. Agent 应先利用当前 Context、文档、证据和 Action 解决可自行解决的问题。局部失败或普通不确定性仍应先在当前 Turn 内有界恢复。
4. 当继续推进依赖人的重大判断、仅由用户掌握的信息、进一步授权或指示、可行路线选择，或者当前证据不足以负责任地继续时，可以调用 `core.answer` 提问、请求确认或申请进一步指示，以结束当前 User Turn。
5. 提问是有效的 User Turn answer。`core.answer` 表示本轮已经产生面向用户的正式响应，不表示整个多轮目标已经完成，也不要求所有 WorkingContext todos 为完成状态。
6. 回答交接应清楚表达相关不确定性、可行选择和所需输入；存在合理判断时，Agent 应主动给出自己的建议。
7. 用户可见的对话正文可以使用与语言匹配的简短方括号意图提示，例如 `[赞同]`、`[提问]`、`[反对]`、`[建议]`、`[执行]`。这些提示是开放词汇和风格手段，不是固定协议，也不要求每句或每段使用。
8. 意图提示不应污染代码、引文、生成文件、结构化输出，或与用户明确要求的格式冲突。

## 分层方案

### Agent Home

- `agent/identity/identity.md`：在现有 Expression 中补充方括号意图提示，表达稳定语言特色。
- `agent/identity/soul.md`：补充主动协作、创造性探索、独立观点与事实边界。
- `agent/AGENT.md`：定义自主探索与请求用户输入之间的 Turn 边界；移除回答前 todos 必须完成的约束。
- `skills_action/core/answer.md`：约束 `core.answer` 内部 LLM task 的提问交接质量和意图提示适用边界。

### Action 与 Loop

- 调整 `core.answer` Tool description 和 semantic，使 Stage2 能在成果交付或需要用户输入时选择该 Action。
- 保留现有 `CoreAnswerActionExecutor`、`UserAnswerCompletionDetector`、Session completion pipeline 和 Runtime 控制流，不新增特殊提问协议。

### 设计文档

- 根 `AGENT.md`：记录 User Turn answer 与多轮目标完成的区别。
- `docs/design/agent_home.md`：记录人格、跨能力规约和 action skill 的职责分层。
- `docs/design/action.md`：明确 `core.answer` 的两类正常使用方式。
- `docs/design/loop.md`：明确问题、确认请求和路线选择也可形成 User Turn completion。

## 验证计划

1. 扩展默认 Home 集成测试，验证协作规约、Expression 和 `core.answer` action skill 都从 package template 正确提供。
2. 扩展 Action Catalog 测试，验证 `core.answer` 的选择语义同时覆盖成果交付与请求用户输入。
3. 运行 Action/Home/App 聚焦测试。
4. 运行 Fast、Full 和 `ty` 类型检查门禁。
5. 核对文案不存在 todo 完成硬约束、固定意图标签枚举或新的隐式 Runtime 状态，并将本计划归档为 `done`。

## 执行项

- [x] 默认 Agent Home 文案完成
- [x] `core.answer` Catalog 与 action skill 完成
- [x] 根规约和设计文档同步完成
- [x] 聚焦测试完成
- [x] Fast、Full 与类型检查完成
- [x] 最终语义核对完成

## 实施结果

- 默认 `identity.md`、`soul.md` 与 `agent/AGENT.md` 已分别承载表达特色、协作人格和跨能力 Turn 交接边界。
- `home:skills_action:core/answer` 已约束提问式交接和方括号意图提示的适用范围；这些提示保持开放、可选且不进入代码或结构化产物。
- `core.answer` Catalog 已允许成果交付与请求用户输入两类选择条件，并明确在可继续自主行动时不应过早回答。
- Loop、Action、Session 与 Runtime 实现无需变化；现有 completion pipeline 已能把提问作为当前 User Turn 的正式输出保存并在下一 Turn 延续。
- 根 `AGENT.md`、`docs/design/agent_home.md`、`docs/design/action.md` 和 `docs/design/loop.md` 已同步当前稳定语义。

## 验证结果

- 聚焦测试：`17 passed`。
- Fast：`880 passed, 2 skipped, 22 deselected`。
- Full：`881 passed, 2 skipped, 21 deselected`，包含 wheel 资源与隔离初始化验收。
- `scripts/typecheck.ps1`：通过。
- `git diff --check`：无空白错误；仅提示已编辑 TOML 的 Git 行尾规范化。
- 最终搜索确认不存在“仅 task 完成后才能 answer”或“answer 前 todos 必须完成”的当前规则。
