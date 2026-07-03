# Action 设计

## 定位

Action 模块负责 TinySoul 的行动语义、模型侧工具暴露、行动参数生成、行动执行和结果回放。

Action 不负责构造基础语境，不负责模型供应商适配，不负责运行时陷入控制。它依赖 `llm` 提供消息栈、工具消息和任务调用抽象，依赖 `runtime` 提供运行位置、信号和异常转移协议。

Action 的核心职责是把“可选择的域”和“可执行的动作”组织成稳定的 catalog，并把 Phase1 / Phase2 / Phase3 的行为切成清晰的边界。

## 设计目标

1. Phase1 只选择域，不暴露全部 action 细节。
2. Phase2 只在已选域内选择动作并生成参数。
3. Phase3 统一执行一批动作，支持并发、超时、hook 校验和结构化结果。
4. 所有 LLM 调用都基于语境模块构造的 `MessageStack`，Action 只追加临时任务提示。
5. Action 定义使用 TOML 存放，入口动态校验后尽早转换为内部类型。
6. 去掉旧设计中的冗余字段，保持模型侧可见描述和框架内运行配置分离。

## 分层模型

### Phase1: 域选择

Phase1 面向模型暴露的是域，而不是 action 列表。

域的作用只有两个：

1. 让模型先判断当前任务应进入哪个工具选择方向。
2. 为 Phase2 限定可见 action 集合。

Phase1 暴露的工具是少量内部控制工具，例如：

- 选择一个或多个 action domain
- 请求加载某些顶层上下文
- 记录当前轮次的方向意图

Phase1 不再输出二级 action meta，也不直接提供 action 参数 schema。

### Phase2: 动作选择与参数生成

Phase2 只接收 Phase1 选中的 domain，并在这些 domain 内暴露具体 action。

Phase2 的输出不叫 draft。它就是一个规范化的 action call，已经足够进入执行阶段。

Phase2 面向模型暴露的 action 信息只保留两类内容：

1. 工具调用直接需要的结构：`name`、`description`、`schema`
2. 补充语义：`use_when`、`avoid_when`、`effects`、`examples`

`edge_cases` 不再由 action definition 承担，交给 hook 和执行结果表达。

### Phase3: 批次执行

Phase3 将 Phase2 产出的多个 action call 统一装配成一个执行批次。

Phase3 负责：

- 将框架内信息和业务参数拆开
- 对每个 action 执行输入 hook
- 按 batch 维度处理并发和超时
- 将每个 action 的执行结果结构化
- 等待全部 action 收敛并整理 `ActionResult` 序列

Phase3 不保留长期运行或 ongoing action。所有动作都只属于一个批次的成功、失败或超时。

`native` 后端运行在宿主 Python 线程中，只能提供协作式停止；如果 native action 超时后执行体仍在运行，runner 必须阻断后续执行组并在结果中标记泄漏风险。需要硬停止语义的动作应使用 `subprocess` 或 `script` 后端，由后端负责终止执行体。

## 数据模型

### ActionDomainSpec

域定义保持很薄，只用于 Phase1。

建议字段：

- `name`
- `description`
- `selection_hint`

域默认运行配置不放进 domain spec 的可见语义里，交给 loader 作为合并来源处理。

### ActionSpec

Action spec 分成四层：

1. `tool`
2. `semantic`
3. `runtime`
4. `backend`

`tool` 是 Phase2 直接映射成 `llm.ToolSpec` 的部分。

`semantic` 是给模型看的补充说明，不参与执行。

`runtime` 是框架内控制信息，不直接暴露给模型。

`backend` 描述真实执行落点。

### ActionToolSpec

Phase2 直接可见字段：

- `name`
- `description`
- `schema`

补充语义字段：

- `use_when`
- `avoid_when`
- `effects`
- `examples`

其中 `effects` 使用收敛后的环境影响枚举，不再包含 destructive。

### ActionRuntimeSpec

框架内运行配置建议包含：

- `timeout_seconds`
- `parallel_policy`
- `hooks`
- `requires`

`parallel_policy` 用于表示该动作是否可与同批次其他动作并发执行，或是否需要串行执行。当前只保留 `allowed` 和 `serial`，不保留额外 `exclusive` 语义。

`hooks` 是 hook 名称列表，动作可以复用全局 hook，也可以追加自己的专用 hook。

### ActionBackendSpec

后端只负责执行实现，不负责模型侧解释。

建议 kind：

- `native`
- `subprocess`
- `script`
- `llm_step`

`llm_step` 只表示动作内部还需要一次受控 LLM 调用，不意味着 action 退化成 prompt 拼接逻辑。

## 执行语义

### 输入

一次 action 执行输入分两层：

1. 框架内信息
2. 模型生成参数

框架内信息包括：

- `invoke_id`
- `batch_id`
- `turn_id`
- `cycle_id`
- `phase`
- `domain`
- `deadline`
- `timeout_seconds`
- `call_id`

模型生成参数只保留 action schema 对应的业务参数。

`call_id` 使用 TinySoul 归一化后的模型侧 tool call id。它是后续渲染 `ToolResultMessage` 的相关性字段；执行期另有 `invoke_id`，用于框架内部观测。

### Hook

每个 action 可以复用通用 hook，也可以定义专用 hook。

hook 顺序建议为：

1. 全局 hook
2. domain hook
3. action hook

hook 只做输入检查、上下文约束和可执行性裁剪，不执行真实动作。

hook 失败应转为结构化 action result，而不是直接升级成 Runtime 陷入。

未知 hook、hook 自身抛出的异常、hook 返回拒绝都应收敛为 `ActionResult(status=failed, stage=hook)`。

### 批次执行

Phase3 使用 map-reduce 风格执行：

- map：每个 invoke 独立执行
- reduce：只负责等待收敛并整理 `ActionResult` 序列

Batch 只是执行编排容器，runner 的核心输出是 `ActionResult` 序列。

单个 action result 只收敛为三类：

- `success`
- `failed`
- `timeout`

批次内允许部分成功，但不需要额外定义 batch result。

Phase2 的模型侧 action tool call 即使无法归一化，也必须产出局部 `ActionResult(status=failed, stage=normalize)`。因此一个 action tool call 在 Action 模块内总是对应一个局部结果：normalize failed、hook failed、schedule failed、execute failed、timeout 或 success。

### 输出

Action result 需要同时表达三类信息：

1. 给模型看的反馈
2. 框架内状态
3. 执行可观测数据

结果中应保留：

- `result_id`
- `call_id`
- 成功/失败/超时
- 所处阶段
- 原始 call 顺序 `sequence`
- 可选的 `invoke_id` / `batch_id` / `domain`
- 结构化 payload
- model feedback
- frame data

大块文件内容、长文本和非结构化资源不直接塞回结果，改用资源句柄或摘要。

`ActionResult` 是 Action 局部事实记录，不等同于 LLM message。`ActionFeedbackRenderer` 负责把它渲染为：

1. 给模型看的 compact JSON payload。
2. 给 trace/log 使用的完整 JSON payload。
3. 可由 context 模块加入下一 cycle MessageStack 的 `ToolResultMessage`。

Context 模块决定这些渲染结果如何进入 TurnTraceContext 或 Interaction Context；Action 模块不直接维护 MessageStack。

## Action Schema

Action tool schema 使用 TinySoul 支持的 JSON Schema 子集。加载 TOML 时必须检查 schema 自身，运行时再校验模型生成参数。

当前支持的 keyword：

- `type`
- `description`
- `properties`
- `required`
- `additionalProperties`
- `items`
- `enum`

当前支持的 type：

- `object`
- `array`
- `string`
- `number`
- `integer`
- `boolean`
- `null`

不支持的 keyword 必须在加载期抛出配置错误，避免 action TOML 写了 schema 但运行时静默忽略。

## LLM 调用原则

所有 LLM 调用都从语境模块已经构造好的 `MessageStack` 出发。

Action 只负责追加临时 task prompt overlay，不重新发明消息栈。

因此一个 action 相关的 LLM task 由两部分组成：

1. 上层语境提供的 base message stack
2. Action 追加的 phase-specific task prompt

Phase1 和 Phase2 只是在这个基础上选择不同的工具作用域和不同的 prompt overlay。

## TOML 组织

建议目录：

```text
tinysoul/action/
  core/
  backends/
  builtin/
    core/
    workspace/
    script/
    shell/
```

### `builtin/core`

放 action 顶层框架性内容，主要是 Phase1 可见的控制工具和共享行为说明。

### `builtin/<domain>`

每个 domain 一个目录，目录下放：

- `domain.toml`
- `actions/*.toml`

`domain.toml` 放域描述和域级默认运行配置。

`actions/*.toml` 放具体 action 定义。

### 继承规则

加载器按以下顺序合并：

1. 内置默认值
2. domain 默认值
3. action 定义
4. 运行时覆盖

动态边界必须在加载阶段完成校验，不把宽泛映射留到执行中。

## 实现拆分

### 1. `tinysoul/action/core/specs.py`

职责：定义内部数据模型。

建议类签名：

```python
class ActionDomainSpec: ...
class ActionToolSpec: ...
class ActionSemanticSpec: ...
class ActionRuntimeSpec: ...
class ActionBackendSpec: ...
class ActionSpec: ...
class ActionParallelPolicy(StrEnum): ...
class ActionBackendKind(StrEnum): ...
class ActionEnvironmentEffect(StrEnum): ...
```

### 2. `tinysoul/action/core/catalog.py`

职责：只读 catalog 查询和视图裁剪。

建议类签名：

```python
class ActionCatalog: ...
```

公开方法建议：

- `domains()`
- `actions_in_domain(domain_name)`
- `get_domain(domain_name)`
- `get_action(action_name)`
- `with_domains(domain_names)`
- `with_actions(action_names)`

### 3. `tinysoul/action/core/loader.py`

职责：读取 TOML、做动态边界校验、产出 catalog。

建议类签名：

```python
class ActionCatalogLoader: ...
class ActionTomlParser: ...
```

公开方法建议：

- `load(root_path) -> ActionCatalog`
- `parse_domain(table, source) -> ActionDomainSpec`
- `parse_action(table, source, default_runtime) -> ActionSpec`
- `parse_runtime(table, key, base) -> ActionRuntimeSpec`

### 4. `tinysoul/action/core/scope.py`

职责：为 Phase1 / Phase2 构建工具作用域。

建议类签名：

```python
class Phase1DomainScopeBuilder: ...
class Phase2ActionScopeBuilder: ...
```

公开方法建议：

- `Phase1DomainScopeBuilder.build(catalog) -> ToolScope`
- `ActionDomainPromptRenderer.render(catalog) -> str`
- `Phase2ActionScopeBuilder.build(catalog, selected_domains) -> ToolScope`

### 5. `tinysoul/action/core/call.py`

职责：Phase2 输出和 Phase3 执行包装。

建议类签名：

```python
class ActionCall: ...
class ActionNormalization: ...
class ActionExecution: ...
class ActionBatch: ...
```

公开方法建议：

- `ActionCallNormalizer.normalize(tool_calls, catalog) -> ActionNormalization`
- `ActionExecutionBuilder.build_batch(calls, catalog, scope, ...) -> ActionBatch`

### 6. `tinysoul/action/core/hooks.py`

职责：统一 hook 注册、查找和执行。

建议类签名：

```python
class ActionHook(Protocol): ...
class HookOutcome: ...
class ActionHookRegistry: ...
class ActionHookPipeline: ...
```

公开方法建议：

- `register_global(...)`
- `register_domain(...)`
- `register_action(...)`
- `run(...)`

### 7. `tinysoul/action/core/result.py`

职责：结果结构化。

建议类签名：

```python
class ActionResultStatus(StrEnum): ...
class ActionResultStage(StrEnum): ...
class ActionResult: ...
```

### 8. `tinysoul/action/core/executor.py`

职责：单个动作的执行接口。

建议类签名：

```python
class ActionExecutor(Protocol): ...
class ActionExecutionContext: ...
class ExecutorRegistry: ...
```

### 9. `tinysoul/action/core/runner.py`

职责：批次并发执行与 reduce。

建议类签名：

```python
class ActionBatchRunner: ...
class BatchConcurrencyPlanner: ...
```

### 10. `tinysoul/action/core/feedback.py`

职责：把 action result 渲染成模型可读反馈。

建议类签名：

```python
class ActionFeedbackRenderer: ...
```

### 11. `tinysoul/action/backends/*.py`

职责：真实执行后端。

建议类签名：

```python
class NativeFunctionExecutor: ...
class SubprocessActionExecutor: ...
class TemporaryScriptExecutor: ...
class LLMStepActionExecutor: ...
```

### 12. `tinysoul/action/failures.py`

职责：action 模块服务于 runtime bridge 的稳定失败类型。

建议枚举：

```python
class ActionFailureKind(StrEnum): ...
```

### 13. `tinysoul/runtime/bridge/action.py`

职责：把 action 模块失败映射成 runtime 语义异常。

建议类签名：

```python
class RuntimeActionBridge: ...
```

## 设计边界总结

1. Phase1 只选 domain。
2. Phase2 只在 domain 内选 action。
3. Phase3 统一执行批次。
4. `edge_cases` 删除。
5. `destructive` 删除。
6. `ActionInvokeDraft` 不保留，Phase2 输出直接称为 `ActionCall`。
7. 所有 LLM 调用都基于上下文模块构造的 base `MessageStack`，Action 只追加临时 prompt。
