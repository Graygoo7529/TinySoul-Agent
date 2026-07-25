# 20260725 Action authoring deadline and model context transparency execution plan

状态：done

## 背景与目标

真实运行中，`workspace.write/rewrite` 与 `script.write/rewrite` 在生成完整文本工件时可能耗尽 90 秒 Action owner deadline。四个 Action 都在提交前调用同一个 `LLMActionTaskRunner`，且当前将 owner 的全部剩余时间直接交给 provider；当内部 Task 恰好在 owner deadline 到期时退出，外层只剩极短的 native cooperative grace，无法稳定完成取消、结果归一化和 executor 返回。

同时，Context 与 Session 的内部完整性事实已经扩展到 canonical revision、trace digest 和 Workspace manifest revision。这些事实对持久化校验、并发控制、Endpoint 审计和 cursor 绑定必要，但不都是 Agent 决策所需的业务语义。模型侧重复看到内部版本字段，会增加无效比较和提示负担。

本计划保持现有模块所有权：Catalog 定义 Action runtime policy，LLM Action backend 负责嵌套 Task 生命周期，Context/Session 各自提供有界模型投影；不新增 LLM task profile、第二套历史事实源或 action-specific Context 分支。

## 已确认语义

1. `workspace.write/rewrite` 与 `script.write/rewrite` 是完整工件生成 Action，Catalog owner deadline 统一为 180 秒；`max_output_tokens = 16384` 与既有 `max_output_chars` 不变。
2. `LLMActionTaskRunner` 为 owner deadline 预留 5 秒收尾窗口。内部 Task 使用扣除该窗口后的 remaining time；内部到期仍映射为普通 Action timeout，不向模型暴露 provider、backend、线程或 executor 实现。
3. 其余 Workspace Action 保持 30 秒默认值，`workspace.analyze` 保持 90 秒；Script 运行与监督 Action 保持既有 70 秒 domain/作业协议。它们不是同类完整工件生成，不因本次 trace 一并放宽。
4. Session Turn Background 持久事实继续包含 ask、answer、Action 名称/聚合状态、可选 Action outcome detail 和 trace digest。`background_action_names` 是 Session-owned 的有界状态审计选择，不复制任意 ActionResult payload；最终 answer 已有独立投影，不再通过 Catalog 重复持久化。
5. Session record、validator、Endpoint 和内部 cursor binding 保留完整 digest/revision。只有模型投影隐藏实现性完整性字段：Working 只显示 milestones、todos、Workspace resource links/summary；Trace heap header 不显示 canonical revision；Session Background 与 Session ActionResult 不显示 trace digest/source revision。
6. active-head cursor 中的 revision 是 owner-bound opaque continuation。Agent 只原样提交 `next_cursor`，不读取、构造或比较其字段；Endpoint 客户端仍可按完整协议处理 revision reset。
7. 自动加载的 Context 文本只解释 Background、TurnTrace、Working 的顶层关系。Domain HOW 只解释同域 Action 的选择边界；Action HOW 只保留该内部 LLM Action 必需的生成要求。

## 实施项

- [x] 将四个完整工件 Action 的 Catalog timeout 调整为 180 秒，并保留既有输出预算。
- [x] 在 `LLMActionTaskRunner` 增加 5 秒 completion reserve，并把内部 deadline 到期归一为稳定 Action timeout。
- [x] 为 Working、Trace heap、Session Background 与 Session Action adapter 建立显式模型投影，保留内部/Endpoint 完整事实。
- [x] 验证 Session Background 的 ask、answer、Action names 和受选 outcome detail；不新增通用 ActionResult payload 复制策略。
- [x] 精炼 context/session Catalog 选择提示、三个 Agent Context Top、Session/Script Domain HOW 与 Core Answer HOW。
- [x] 补充 Catalog、LLM Action deadline、Context render、Session model projection 和 Home package 相关测试。
- [x] 同步 `AGENT.md` 与相关设计文档，完成 pytest、type check 和 diff check。

## 验收标准

- 四个完整工件 Action 给嵌套生成最多约 175 秒，并在 owner timeout 前保留约 5 秒协作退出时间；模型只收到普通 timeout 事实。
- Context model message 不包含 `as_of_trace`、`canonical_revision`、`workspace_revision`、Session `trace_digest` 或 source `revision`。
- Session 持久 record、validator 和 Endpoint 查询仍包含其完整性字段；模型透明化不降低审计与 CAS 能力。
- 下一 Turn 的固定 Session Background 能看到之前 Turn 的 ask、answer、Action 名称与总体成功/失败信息；配置选中的 Action 可看到有界 outcome detail，但看不到任意业务 payload。
- Agent 能从精炼的 Context/Domain hints 区分当前 Turn Context、已完成 Turn Session、Workspace 内容操作与 Script 生成，不需要理解 revision/digest。
- 测试不读取本地真实运行记录，也不建立与具体轨迹绑定的 fixture。

## 实施结果

- 四个完整工件 Action 的 Catalog owner timeout 已统一为 180 秒；`workspace.analyze` 仍为 90 秒，其余 Workspace/Script Action 保持原有 domain/job 边界。
- `LLMActionTaskRunner` 只对存在 owner deadline 的嵌套 Task 扣除 5 秒；预留窗口到期返回 `execution_timeout/action.timeout`，显式外部取消仍保持 `cancelled`，两者都不暴露执行后端细节。
- Working model projection、自动 Trace heap header、Session Context projection 和 Session Action adapter 已移除指定内部 revision/digest；内部 state、Session record/validator、Context inspect 与 Endpoint 直接使用的 Engine query 保持完整。
- Session Background 测试证明 ask、answer、Action names/outcome summary 与配置选中的 `core.reason` status detail 可用，且未复制 ActionResult 业务 payload；`core.answer` 继续由最终 answer 独立投影。
- 默认 Home 新增精炼的 Context Domain HOW，并压缩三个 Context Top、Session/Script Domain HOW 与 Core Answer HOW；Script 只增加通用复用、避免嵌入大段目标文本的弱约束。
- 聚焦测试与完整 `pytest tests` 通过；`ty check --python C:\Anaconda3\envs\TinySoul\python.exe` 通过；`git diff --check` 通过。全量测试仅报告既有 FastAPI TestClient deprecation warning。
