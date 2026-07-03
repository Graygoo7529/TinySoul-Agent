# Action 模块分析（2026-07-03）

背景：对 `tinysoul/action` 全量代码、`docs/design/action.md` 与 `tinysoul/runtime/bridge/action.py` 的一次架构与质量检查。总体结论：模块主体架构清晰，与 AGENT.md 核心定义和设计文档一致性高，三层失败语义（call 级局部结果 / phase 级局部结果 / Runtime 语义异常）落实完整；问题集中在死字段、兼容残留和少量边界裂缝，另有两个等待上层模块的天然缺口。

## 问题清单

### 1. 死字段与预留抽象 `pending`

违反"不预留没有实际功能的类型、接口或抽象"的设计原则：

- `ActionRuntimeSpec.requires`：loader 会从 domain/action TOML 解析并合并该字段，但全项目没有任何消费者。
- `ActionNormalization.phase_results` 与 `ActionCallNormalizer.normalize` 内部的 `phase_results` 列表：没有任何路径会填充，永远为空。
- `ActionCall.intent`：归一化器从不填充，永远是默认空串。

处理方向：删除，或（对 `intent`）让 normalizer 真正从 tool call 提取填充。

### 2. 兼容层残留 `pending`

`ActionFeedbackRenderer.render_result` 自称 "Backward-compatible alias"，`render_many` 内部也走该 alias。本项目是全新重构，不存在旧调用方，违反"不用兼容层维持旧假设"。应删除 alias，调用点直接使用 `render_model_payload`。

### 3. 裸 KeyError 作为契约错误 `pending`

`ActionCatalog.get_action` / `get_domain` 与 `ExecutorRegistry.get` 在未命中时抛裸 `KeyError`，与模块自身的 `ActionContractError` 体系不一致。后果：

- `RuntimeActionBridge.from_action_error` 会把 `KeyError` 归类为 `INTERNAL_FAILURE` 而非 `CONTRACT_VIOLATION`；
- `BatchConcurrencyPlanner.plan` 在 `ActionBatchRunner.run` 的收敛路径之外调用 `catalog.get_action`，若 batch 与 catalog 不一致，`KeyError` 会未经三层失败语义收敛直接逃出 `run()`。

处理方向：未命中改抛 `ActionContractError`；planner 的 catalog 访问纳入 runner 收敛路径，或在 `run` 入口做一次 batch 与 catalog 的一致性断言。

### 4. 过宽的异常捕获 `pending`

`Phase2ActionScopeBuilder.prepare` 使用 `except Exception` 把一切异常（包括不变量破坏这类编程错误）吞成 SCOPE 阶段 phase result。按设计文档，防御性不变量异常应升级 Runtime。应收窄为只捕 `ActionContractError`（域内无可用 action 属正常局部失败），让不变量错误穿透。

### 5. 宽泛占位类型 `pending`

`ActionExecutionContext.services` 与 `ActionNormalizeContext.services` 均为 `object | None`，未表达任何契约。可理解为等待 loop/context 模块出现后定型，但应在该模块起步时立即用 Protocol 或明确结构替换。

### 6. stringly-typed phase 标识 `pending`

`ActionFramework.phase: str = "phase3"`、`ActionExecutionBuilder` 的 `phase` 参数为自由字符串，phase 名在 result 与 renderer 中反复出现。建议收敛为枚举或常量。

### 7. 轻微重复 `pending`

- `_require_name` / `_require_non_empty` 校验助手在 `specs.py`、`call.py`、`hooks.py` 各写一遍；
- 去重检查在 normalizer、`prepare_batch`、`ActionBatch.__post_init__` 三处叠加。batch 不变量作为最终防线可保留，但 prepare 阶段重复检查与它的关系应有说明或简化。

### 8. 超时改判语义不对称未记录 `pending`

runner 中超时后 executor 返回 SUCCESS 会被改判为 timeout（防止越过 deadline 的副作用被当作正常结果），但超时后的 FAILED 保留原样。推测意图是"失败信息比超时标记更有价值"，行为合理但 `docs/design/action.md` 未声明，应补充说明。

### 9. 多泄漏只记录一个 `pending`

同一执行组内多个 action 同时超时且泄漏时，`leaked_timeout_invoke_id` 只保留最后一个，后续阻断结果的 `blocked_by` 只指向它。个人项目下影响很小，可低优先级处理或接受现状。

## 规划建议

按优先级：

1. **小清理（低风险）**：处理问题 1、2（死字段与 alias 删除）。
2. **边界修补**：处理问题 3、4（KeyError 收敛、捕获范围收窄），顺带处理 6、7、8。
3. **补齐真正缺口（下一阶段主体工作）**：
   - **组装门面**：action 模块目前缺一个把 catalog 加载、executor 注册、hook 注册、normalizer/builder/runner 装配收拢的启动入口，供未来 Loop 使用（现状只能由测试手工拼装散件）。
   - **subprocess / script 后端实现**：占位类目前构造即抛 `NotImplementedError`。它们同时是超时硬停止语义的承载者，能消解 native 后端线程泄漏问题的大部分场景。
   - **how_action（HOW 文档）注入 Phase2/Phase3 task prompt**：AGENT.md 有定义但当前完全没有落点。建议等 Context 模块起步时与其一起设计接口，避免单侧预留抽象（与问题 5 的定型时机对齐）。
