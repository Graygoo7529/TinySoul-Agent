# Action 模块分析（2026-07-03）

背景：对 `tinysoul/action` 全量代码、`docs/design/action.md` 与 `tinysoul/runtime/bridge/action.py` 的一次架构与质量检查。总体结论：模块主体架构清晰，与 AGENT.md 核心定义和设计文档一致性高，三层失败语义（call 级局部结果 / phase 级局部结果 / Runtime 语义异常）落实完整；问题集中在死字段、兼容残留和少量边界裂缝，另有两个等待上层模块的天然缺口。

## 问题清单

### 1. 死字段与预留抽象 `done`

违反"不预留没有实际功能的类型、接口或抽象"的设计原则：

- `ActionRuntimeSpec.requires`：loader 会从 domain/action TOML 解析并合并该字段，但全项目没有任何消费者。
- `ActionNormalization.phase_results` 与 `ActionCallNormalizer.normalize` 内部的 `phase_results` 列表：没有任何路径会填充，永远为空。
- `ActionCall.intent`：归一化器从不填充，永远是默认空串。

处理方向：删除，或（对 `intent`）让 normalizer 真正从 tool call 提取填充。

已解决（2026-07-06）：三处均已删除，loader 同步清理（`specs.py`、`call.py`、`loader.py`）。

### 2. 兼容层残留 `done`

`ActionFeedbackRenderer.render_result` 自称 "Backward-compatible alias"，`render_many` 内部也走该 alias。本项目是全新重构，不存在旧调用方，违反"不用兼容层维持旧假设"。应删除 alias，调用点直接使用 `render_model_payload`。

已解决（2026-07-06）：alias 已删除，`render_many` 直接使用 `render_model_payload`（`feedback.py`）。

### 3. 裸 KeyError 作为契约错误 `done`

`ActionCatalog.get_action` / `get_domain` 与 `ExecutorRegistry.get` 在未命中时抛裸 `KeyError`，与模块自身的 `ActionContractError` 体系不一致。后果：

- `RuntimeActionBridge.from_action_error` 会把 `KeyError` 归类为 `INTERNAL_FAILURE` 而非 `CONTRACT_VIOLATION`；
- `BatchConcurrencyPlanner.plan` 在 `ActionBatchRunner.run` 的收敛路径之外调用 `catalog.get_action`，若 batch 与 catalog 不一致，`KeyError` 会未经三层失败语义收敛直接逃出 `run()`。

处理方向：未命中改抛 `ActionContractError`；planner 的 catalog 访问纳入 runner 收敛路径，或在 `run` 入口做一次 batch 与 catalog 的一致性断言。

已解决（2026-07-06）：catalog 与 `ExecutorRegistry` 未命中改抛 `ActionContractError`；更进一步，`ActionExecution` 改为自包含携带已解析 `ActionSpec`（`call.py`），runner、planner、execution hook pipeline 执行期不再查询 catalog，逃逸路径连根消除（`runner.py`、`hooks.py`，设计决定记录于 `docs/design/action.md` 执行语义/输入一节）。

### 4. 过宽的异常捕获 `done`

`Phase2ActionScopeBuilder.prepare` 使用 `except Exception` 把一切异常（包括不变量破坏这类编程错误）吞成 SCOPE 阶段 phase result。按设计文档，防御性不变量异常应升级 Runtime。应收窄为只捕 `ActionContractError`（域内无可用 action 属正常局部失败），让不变量错误穿透。

已解决（2026-07-06）：`Phase2ActionScopeBuilder.prepare` 收窄为只捕 `ActionContractError`（`scope.py`）。

### 5. 宽泛占位类型 `done`

`ActionExecutionContext.services` 与 `ActionNormalizeContext.services` 均为 `object | None`，未表达任何契约。可理解为等待 loop/context 模块出现后定型，但应在该模块起步时立即用 Protocol 或明确结构替换。

已解决（2026-07-06）：`services` 字段删除；`ActionExecutionContext` 改为携带有真实功能的 `ActionExecutionControl`（deadline 与协作取消，`executor.py`）。遗留一点见 2026-07-06 复查第 1 条。

### 6. stringly-typed phase 标识 `done`

`ActionFramework.phase: str = "phase3"`、`ActionExecutionBuilder` 的 `phase` 参数为自由字符串，phase 名在 result 与 renderer 中反复出现。建议收敛为枚举或常量。

已解决（2026-07-06）：新增 `ActionCyclePhase` 枚举（`phase.py`），贯穿 `call.py`、`result.py`、`scope.py`、`feedback.py`。

### 7. 轻微重复 `pending`

- `_require_name` / `_require_non_empty` 校验助手在 `specs.py`、`call.py`、`hooks.py` 各写一遍；
- 去重检查在 normalizer、`prepare_batch`、`ActionBatch.__post_init__` 三处叠加。batch 不变量作为最终防线可保留，但 prepare 阶段重复检查与它的关系应有说明或简化。

### 8. 超时改判语义不对称未记录 `done`

runner 中超时后 executor 返回 SUCCESS 会被改判为 timeout（防止越过 deadline 的副作用被当作正常结果），但超时后的 FAILED 保留原样。推测意图是"失败信息比超时标记更有价值"，行为合理但 `docs/design/action.md` 未声明，应补充说明。

已解决（2026-07-06）：设计文档批次执行一节已声明该不对称及理由；runner 为改判结果附加 `late_success` 标记（`runner.py`）。

### 9. 多泄漏只记录一个 `done`

同一执行组内多个 action 同时超时且泄漏时，`leaked_timeout_invoke_id` 只保留最后一个，后续阻断结果的 `blocked_by` 只指向它。个人项目下影响很小，可低优先级处理或接受现状。

已解决（2026-07-06）：改为 `leaked_timeout_invoke_ids` 元组，阻断结果的 `blocked_by_invoke_ids` 列出全部（`runner.py`）。

## 规划建议

按优先级：

1. **小清理（低风险）**：处理问题 1、2（死字段与 alias 删除）。`done`
2. **边界修补**：处理问题 3、4（KeyError 收敛、捕获范围收窄），顺带处理 6、8。`done`（问题 7 保留 pending）
3. **补齐真正缺口（下一阶段主体工作）**：
   - **组装门面**：`done`（2026-07-06）——`ActionEngine` / `ActionEngineBuilder`（`engine.py`），加载 catalog、注册 executor 与 hook、build 期校验 handler 完备性。
   - **subprocess / script 后端实现**：`done`（2026-07-06）——`backends/subprocess.py` 实现显式 argv 进程执行与进程树终止（Windows `taskkill /T /F`、POSIX 新 session + killpg），`backends/script.py` 复用其运行语义；同时 runner 引入协作取消机制（`ActionExecutionControl` + cancel grace），native action 可协作退出以避免泄漏阻断。设计文档已同步（后端执行、组装入口两节）。
   - **how_action（HOW 文档）注入 Phase2/Phase3 task prompt**：`pending`——AGENT.md 有定义但当前没有落点。建议等 Context 模块起步时与其一起设计接口，避免单侧预留抽象。

## 2026-07-06 复查

对 `opt(action)：基于审核建议继续优化`（46f432b）的复查结论：上述 done 项实现干净，全量测试与 `ty` 检查通过，AGENT.md 与设计文档同步准确。复查中新发现以下小问题：

### R1. `ActionNormalizeContext` 成为空壳 `done`

`services` 字段删除后（问题 5），`hooks.py` 中的 `ActionNormalizeContext` 是一个没有任何字段的 frozen dataclass，docstring 仍写 "Runtime services available to normalize hooks"，名实不符，构成新的无功能占位。应连同 normalize hook 签名中的 context 参数一起删除，或等有真实内容时再引入。

已解决（2026-07-06）：删除 `ActionNormalizeContext`，normalize hook 签名收敛为 `check(item)`；schema normalize hook 继续作为内置阶段化 hook 运行。

### R2. `engine.py` 的层次位置 `done`

组装门面位于 `core/` 内但 import 了 `backends/`，而 backends 又依赖 core 的子模块。运行无问题，但依赖方向上组装层应位于 core 与 backends 之上，移至 `tinysoul/action/engine.py` 更干净。

已解决（2026-07-06）：`ActionEngine` / `ActionEngineBuilder` 移至 `tinysoul/action/engine.py`；`core` 不再依赖或导出组装门面，顶层 `tinysoul.action` 继续作为公共 API 导出。

### R3. subprocess `stdin` 选项双重语义 `done`

`backends/subprocess.py` 的 `stdin` 选项既表达模式（`none` / `json_params`），任意其他字符串又被当作字面量 stdin 内容。应拆为 `stdin_mode` 与显式内容字段，或收敛为纯模式枚举。

已解决（2026-07-06）：subprocess options 收敛为 `stdin_mode = "json_params" | "none"`，不再支持隐式 literal stdin；旧 `stdin` 字段会在加载期作为未知 options 报配置错误。

### R4. backend options 缺少加载期校验 `done`

`_string_list_option` 将格式非法的 `argv` 静默视为缺失并反馈 `missing_argv`，有误导。backend options 属 TOML 动态边界，应由各 backend 在 catalog 加载期校验自身 options 结构，而非执行期宽容降级。

已解决（2026-07-06）：`ActionCatalogLoader` 支持按 backend handler 注册 options validator；`ActionEngineBuilder` 默认注册 subprocess/script validator，并在 catalog 加载期校验 options。执行器仍保留防御性校验，把直接绕过加载器造成的 invalid options 转为局部 action result。

### R5. 两处代码小瑕疵 `done`

- `runner.py` `_run_group` 签名收尾 `) -> _GroupRun:` 缩进多 4 空格；
- `_run_group` 中 `pending -= still_expired` 后紧跟 `pending -= expired`，前者是后者子集，冗余一行。

已解决（2026-07-06）：修正 `_run_group` 签名缩进，并删除冗余 pending 集合操作。
