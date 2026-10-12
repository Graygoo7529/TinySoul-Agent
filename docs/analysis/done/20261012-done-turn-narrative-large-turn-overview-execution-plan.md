# turn.md 大规模 Turn 轨迹概览执行计划

状态：已完成（2026-10-12）

## 背景与目标

当前导出包已经把完整的 LLM request/response、action 和 cycle 证据放入目录，并由 `turn.md` 提供入口。但 `turn.md` 仍逐条展开 provider/task 生命周期和较长的模型输出；Turn 变大后，概览会被重复内容淹没，难以先定位周期、阶段和失败，再进入细节证据。

本计划只改进 `turn.md` 这个阅读投影，不改变 Observation 事实、导出文件命名、完整 request/response 内容或运行时协议。目标是让几十到上百个 cycle 的 Turn 仍能先通过一份线性、可扫描的概览完成定位，再沿链接查看完整证据。

## 设计方案

1. 保留开头的 Turn 元信息和 Cycle overview 表。表格继续以记录到的 phase lifecycle 和 action result 为依据，明确 `Not observed` 不代表推断跳过。
2. 将时间线收敛为有意义的事件：LLM request/response、phase 状态、action call/result/execution、失败与最终输出。`llm.provider.started/completed` 不再各自生成完整段落；provider 信息在 request/response 中保留，provider 失败或重试只用一行摘要提示。`llm.task.started` 合并进 request，`llm.task.completed` 保留状态和证据入口的短行，避免重复完整 payload。
3. 为模型回答、tool call 参数、action 失败、上下文摘录、最终输出和运行事件设置固定的小型上限。正常 response 只展示足以判断意图的回答和工具调用；异常 stop、空回答或无工具调用时可附带更短的 reasoning summary。完整内容始终通过 request/response 或 action 证据文件读取。
4. Context excerpt 继续由真实 request 选择，不重建历史：首次出现的用户输入/trace 输入、phase note、action result 和任务提示可作为线索；plan/jobs 只在内容变化时显示；相同内容不重复显示。任务提示的重复正文只保留首次或确有变化的短摘录。
5. 每个概览条目保留 cycle/phase、sequence、时间和相关证据链接。所有缩短或省略都在概览中说明，避免把摘要误认为完整事实。实现继续复用现有 EventWindow 和 evidence map，不新增平行日志或运行状态。

## 改动范围

- `visualization/src/features/trace/exportNarrative.ts`：重写概览投影的事件筛选、合并和摘要上限。
- `visualization/src/features/trace/export.test.ts`：更新现有叙事断言，覆盖生命周期压缩、失败提示和上下文选择。
- 新增一个大规模 Turn 回归用例：生成代表性的百余 cycle 事件，验证概览长度有界、仍可定位 request/response/phase/action，且 provider 重复段落不会扩散。
- `visualization/docs/design/chat.md`、`visualization/docs/design/action-renderers.md`：说明 `turn.md` 是有界导航投影，完整模型证据以目录文件为准。

## 不在本计划内

- 不改变导出 ZIP 的根路径、manifest/index 结构或完整证据文件。
- 不改变 Phase1/Phase2 协议、模型生成预算和 provider 适配行为；这些内容由独立计划讨论。
- 不把正文压成一份新的 JSON，也不把模型 request/response 或 action result 从导出包删除。

## 验收标准

- 大型合成 Turn 的 `turn.md` 仍按 cycle/phase 可扫描，长度和单条摘录由固定上限控制。
- 概览能看出每次模型请求/响应的顺序、工具意图、phase/action 结果和失败位置，并可跳转到完整证据。
- provider/task 生命周期的重复 payload 不再占据主要篇幅，异常 provider 信息仍可定位。
- 现有导出测试、前端全量测试、TypeScript 检查和构建通过；计划完成后移动到 `docs/analysis/done/` 并记录验证结果。

## 实施结果

- `exportNarrative.ts` 现在只展开 request/response、phase、action、失败/重试和 Turn 输出；provider started/completed 与 task started 不再重复输出完整 payload，task 完成保留短状态，provider retry/failed 保留原因线索。
- response、tool 参数、reasoning、action、上下文和最终输出均使用固定上限；usage 只显示常用 token 字段。完整内容仍在对应证据文件中。
- 新增 120-cycle 合成回归用例，验证概览长度小于 200,000 字符，同时保留 Cycle overview、LLM request/response、task 状态、provider 重试提示和 request/response 证据入口。
- 前端全量测试通过：91 个测试文件、803 个测试；TypeScript `tsc --noEmit` 通过；Vite production build 通过；`git diff --check` 无错误。
