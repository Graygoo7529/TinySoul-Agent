# Action

Action 是 TinySoul 的核心执行单元，位于 `tinysoul/action/`。框架层（`action/framework/`）定义接口与元数据体系，插件层（`action/handlers/`、`action/executors/`）提供具体实现。二者之间保持单向依赖：插件层依赖框架层，框架层对插件层零感知。

---

## Design Principles

### 1. 元数据与执行分离

- `ActionHandler` 负责元数据（name, cluster, profile, contract, detail）
- `ActionExecutor` 负责实际执行逻辑
- 一个 Action 可以更换 Executor 而不影响其元数据暴露给 LLM 的形态

### 2. JSON 作为单一真相源

- 每个 Action 通过 `ACTION_JSON` 字符串自描述其完整 schema
- `JsonMetaProvider` 在运行时自动解析 `ACTION_JSON` 为 `ActionMeta` 和 `ActionDetail`
- 消除过去"JSON schema + Python dataclass 双写"的冗余
- `JsonMetaProvider` 在实例级别缓存解析结果，避免每 turn 重复 `json.loads`
- 解析器做了防御性兼容：LLM 可能把 `postconditions` 写成 list 或把 detail 字段放错位置，均自动归位

### 3. 实例级注册与零全局状态

- `ActionRegistry` 是纯实例级注册表，每个实例维护独立的 `_registry` 字典
- 没有模块级全局注册表，没有类级别 `_REGISTRY`
- Action 模块 import 时**不产生副作用**，不自动注册
- `bootstrap(registry)` 显式遍历模块并调用 `register_to(registry)` 完成注册
- `QueryAction` 接收注入的 `ActionRegistry` 实例，只加载该实例中存在的 Action

### 4. 运行时配置与 LLM 上下文分离

- `ActionRuntimeConfig` 声明在 Handler 上，描述 timeout、LLM/API 预算、dependencies 等基础设施控制参数
- `RunConfig` 在每次 `execute()` 调用前由 Dispatcher/Action 框架组装，携带解析后的实际执行控制值
- timeout、termination、dependency 等运行时控制参数**不进入 ACTION_JSON**，对 LLM 完全不可见
- `PromptBuilder` 只暴露 `ContextProvider`（业务上下文），不暴露 `RunConfig`（执行控制）

### 5. Action 依赖声明与环境适配

- Action 通过 `ActionDependency` 声明所需外部能力（executable、env_var、python_package、file）
- `EnvironmentCapabilities` 在框架启动时探测当前环境
- `ActionRegistry.register()` 自动过滤不满足依赖的 Action，被跳过的 Action 不出现在可用列表中
- 支持 `optional=True` 的依赖：缺失时不阻止注册，但可能限制功能

---

## Layer Architecture

```
┌─────────────────────────────────────────┐
│  loop/                                  │
│  - QueryAction（运行时 Action 管理器）      │
│  - register_temporary_script 手动注入      │
├─────────────────────────────────────────┤
│  action/handlers/                        │
│  - workspace actions（scan/read/create/edit/delete）
│  - calculate, average_dog_weight          │
│  - answer, reasoning, ask_user            │
│  - create/edit/register temporary script  │
│  - git（CLI）                             │
│  - monitor / stop_ongoing_action           │
├─────────────────────────────────────────┤
│  action/executors/                       │
│  - OneStepAIExecutor（LLM 单步模板）       │
│  - ScriptExecutor / TemporaryScriptExecutor│
│  - SubprocessExecutor / CLIExecutor / BashExecutor│
├─────────────────────────────────────────┤
│  action/framework/（框架层）               │
│  - ActionHandler（ABC）                   │
│  - JsonMetaProvider（meta/detail 解析）     │
│  - ActionBase（标准桥接）                  │
│  - make_handler（运行时工厂）              │
│  - ActionExecutor（ABC）                   │
│  - ActionRegistry（实例级，allowlist）     │
│  - ActionRuntimeConfig / RunConfig        │
│  - Metadata dataclasses + Enums           │
│  - Action JSON Schema (schema.py)         │
│  - register_action_class（便捷注册）       │
│  - validation.py（元数据 + 参数校验）       │
├─────────────────────────────────────────┤
│  infra/                                  │
│  - sandbox module（AST 过滤 + 受限 globals）│
│  - capabilities module（环境探测 + 依赖声明）│
└─────────────────────────────────────────┘
```

---

## Core Abstractions

### ActionHandler

Command Pattern 的抽象基类，定义三个契约：
- `get_meta() -> ActionMeta`：暴露 Action 的元数据
- `get_detail() -> ActionDetail`：暴露 Action 的参数 schema、示例、边界处理
- `execute(action_input: dict, context_provider, run_config) -> dict`：接收结构化参数对象，返回结果字典

`JsonMetaProvider` 自动从 `ACTION_JSON` 解析 meta/detail，并在实例级缓存结果。它是组合组件，不继承 `ActionHandler`。
`ActionBase` 为所有框架内执行的 Action 提供统一基类，通过 `_executor` 注入执行逻辑，组合 `JsonMetaProvider`，并持有 `_runtime_config` 声明运行时配置。
`make_handler()` 工厂函数在运行时构造 `ActionHandler` 实例，无需预先编写子类，用于承载 LLM 生成的动态 Action（如 `register_temporary_script` 注册的脚本）。

### ActionExecutor

执行逻辑的抽象。子类实现 `execute(action_input, context_provider, run_config)`。

`run_config: RunConfig` 携带本次执行的控制参数（已解析的 timeout/deadline、execution_id、terminate_event、LLM/API 预算）。Executor 不直接接收 Dispatcher 的强制停止，只观察 `RunConfig` 并按自身执行载体实现停止。

当前有四种典型实现路径：
- **纯 Python 执行**（如 `CalculateExecutor`、`DeleteFileExecutor`）：直接调用 Python 函数
- **LLM 单步模板执行**（`OneStepAIExecutor`）：parse → build_prompt → LLM call → parse response → apply_result；调用前后检查 termination，并把 action 剩余时间折算进请求级 `ChatConfig.timeout`
- **沙箱脚本执行**（`TemporaryScriptExecutor` → `ScriptExecutor`）：读取文件 → AST 验证 → worker 子进程受限执行；通过 `ManagedProcessRunner` 观察 `RunConfig`
- **子进程执行**（`CLIExecutor` / `BashExecutor` → `SubprocessExecutor`）：构建命令 → `ManagedProcessRunner` → 解析 stdout；超时/终止时先 terminate 再 kill

执行器继承层次：
```
ActionExecutor（ABC）
├── OneStepAIExecutor
├── ScriptExecutor（ABC）
│   └── TemporaryScriptExecutor
└── SubprocessExecutor（ABC）
    ├── CLIExecutor（预定义命令 + env 上下文）
    │   └── GitExecutor（白名单子命令）
    └── BashExecutor（stdin JSON + 黑名单，未注册为默认 Action）
```

> **注意**：`BashExecutor` 在代码库中存在，但**未注册为默认 Action**（出于安全考虑），仅作为基础设施保留。如需启用，可在创建 `ActionRegistry` 后手动调用 `registry.register_action_class(BashAction)`（需自行实现对应的 `BashAction` Handler 并将 `BashExecutor` 绑定为其执行器）。当前默认仅注册 `GitExecutor`（基于 `CLIExecutor`）作为 CLI 类型 Action 的代表。

### LLM Action System

LLM-dependent Action 统一通过 `tinysoul.prompt.action.build_llm_action_system()` 组装 system messages。顺序固定：
1. loop-level system：外部 `loop_system` sources + 内置 `tinysoul.prompt.loop/markdown/query_loop.system.md`，由 `ContextProvider.get_loop_level_system()` 提供
2. 通用 action execution context：来自 `tinysoul.prompt.action/markdown/action_execution_context.system.md`，说明当前 LLM 调用发生在 Step 2b、输出会被 Interpreter 解析、`query_events` 是事件流
3. action-specific system：例如 `OneStepAIExecutor` 的内容生成约束，或 `register_temporary_script` 的 schema designer 约束

该组装入口属于 prompt 层：`QueryContext` 只提供 loop system，不拼接 action execution context。`OneStepAIExecutor` 与 `register_temporary_script` 使用同一 builder，避免内部 LLM action 的 system 语义分叉。

### ActionRuntimeConfig & RunConfig

**ActionRuntimeConfig** 是声明式配置，附着在 Action Handler 类上，描述该 Action 的固有能力需求：
- `timeout: float | None` — 个体超时覆盖值；`None` 表示由框架按 `cluster.type` 推导
- `llm_timeout: float | None` — 单次 LLM 调用预算覆盖值；`None` 使用全局默认
- `api_timeout: float | None` — 单次外部 API 调用预算覆盖值；当前作为 runtime-only 配置使用
- `api_dependency: bool` — 是否用 API 预算放大默认 action timeout；暂不暴露到 LLM 可见 meta/detail
- `dependencies: list[ActionDependency]` — 运行所需外部依赖列表

**RunConfig** 是运行时实例，每次 `execute()` 调用前由 `ParallelDispatcher` 创建、`QueryAction`/`ActionBase` 解析，描述这一次具体执行的控制参数：
- `execution_id: str` — 本次 execution 的稳定 id，用于 Signal 关联和 ONGOING 控制
- `timeout: float | None` — 解析后的实际 action 生命周期预算
- `deadline: float | None` — 基于 timeout 推导的单调时钟截止点
- `terminate_event` / `termination_reason` — Dispatcher 或 controller 发出的终止意图
- `llm_timeout` / `api_timeout` — 单次 LLM/API 调用预算
- `action_name: str` — 当前执行的 Action 名称
- `turn: int` — 当前 turn 编号

解析链路（`ActionBase.resolve_run_config`）：
```
ActionRuntimeConfig.timeout
    ├─ 有值 → 直接使用（个体覆盖）
    └─ None → 按 cluster.type 取默认值
         NATIVE → settings.action_timeout
         CLI    → settings.cli_timeout
         SCRIPT → settings.script_timeout
              ↓
        若 llm_dependency != NONE：
          timeout = max(timeout, llm_timeout + action_llm_overhead)
        若 api_dependency=True：
          timeout = max(timeout, api_timeout + action_api_overhead)
              ↓
        写入 RunConfig.timeout
              ↓
        传给 ActionExecutor.execute()
```

显式 `ActionRuntimeConfig.timeout` 绝对优先，不再因 LLM/API 依赖被放大。依赖预算只用于更聪明地推导默认 action timeout。

### ActionRegistry

实例级注册表，每个实例独立：
```python
_registry: Dict[str, Tuple[str, Callable[[], ActionHandler]]]
```

- `register(name, action_json, factory, *, force=False, strict=False)`：注册 Action，默认不允许重复注册。当 `force=True` 时，允许覆盖已存在的同名 Action（自动清除旧 handler 缓存）。当 `strict=True` 时，依赖不满足或实例化失败会抛出异常（用于运行时动态注册，失败需立即反馈给 LLM）；`strict=False` 时则静默跳过并记录到 `_skipped`。注册前实例化 handler 并检查 `ActionRuntimeConfig.dependencies`
- `unregister(name)`：移除 Action（包括从 registry 和 handler_cache 中清除）
- `get_handler(name)`：通过 factory 实例化 Handler，结果惰性缓存
- `get_action_json(name)`：获取原始 ACTION_JSON
- `is_available(name)`：检查 Action 是否注册且未被 allowlist 过滤
- `with_allowlist(names)`：返回新的 registry view，共享底层数据但只暴露指定 Action
- `get_skipped()`：返回因依赖不满足而被跳过的 Action 列表（用于诊断日志）
- 运行时注册自动放行：若当前视图有 allowlist，新注册的 name 自动加入 allowlist

---

## Validation Layer

`tinysoul/action/framework/validation.py` 提供 Action 元数据与输入参数的结构校验，手写 validator，无外部依赖。

### `validate_action_metadata(action_json: str) -> dict`
- 校验顶层必须包含 `name`, `description`, `cluster`, `profile`, `contract`, `detail`
- 校验 `cluster` 必须包含 `type`（NATIVE | CLI | SCRIPT）和 `domain`
- 校验 `profile` 必须包含 `action_mode`（SINGLE_RUN | ONGOING）
- 校验 `detail` 必须包含 `parameter_schema`

### `validate_action_input(action_name, schema, payload)`
- 校验 `payload` 必须是 `dict`
- 校验 `required` 字段必须全部存在
- 缺失字段抛 `ActionInputError`

校验时机：
1. **注册期**：动态 Action 生成 `ACTION_JSON` 后立即调用 `validate_action_metadata`
2. **执行期**：`QueryAction.execute()` 调用 handler 前调用 `validate_action_input`
3. **动态注册**：`register_temporary_script` 生成 JSON 后校验

---

## Metadata System

### Action Cluster

`{type, domain}` 二元分类，用于组织 Action 目录结构和路由：

- `{"type": "NATIVE", "domain": "BASIC"}`：answer, reasoning, ask_user
- `{"type": "NATIVE", "domain": "MATH"}`：calculate
- `{"type": "NATIVE", "domain": "KNOWLEDGE"}`：average_dog_weight
- `{"type": "NATIVE", "domain": "WORKSPACE"}`：scan_workspace, read_file, create_markdown_file, edit_markdown_file, delete_file
- `{"type": "NATIVE", "domain": "SCRIPTING"}`：create_temporary_script, edit_temporary_script, register_temporary_script
- `{"type": "NATIVE", "domain": "MONITOR"}`：monitor（ONGOING）/ stop_ongoing_action
- `{"type": "CLI", "domain": "GIT"}`：git

`type` 维度同时承担 Action 分类语义：
- `NATIVE`：框架内 Python 执行
- `CLI`：预定义子进程命令
- `SCRIPT`：沙箱脚本执行

### Profile Enums

Action 的 profile 由四个枚举维度刻画：

- `action_intention`：`EXTERNAL_PROBING` | `INTERNAL_REASONING` | `EXECUTION`
- `action_environment_effect`：`READ_ONLY` | `ADDITIVE` | `MODIFYING` | `DESTRUCTIVE`
- `action_mode`：`SINGLE_RUN` | `ONGOING`
- `llm_dependency`：`NONE` | `OPTIONAL` | `REQUIRED`

`applicability_mode`（`ALWAYS_CONSIDER` | `CONDITIONAL`）位于 `action_contract.applicability`，不属于 profile。

---

## QueryAction

QueryLoop 中的 Action 运行时管理器。职责：
- 根据 `available_actions` 名称列表，从注入的 `ActionRegistry` 实例化 Handler
- 提供 `execute(action_name, action_input)` 供 Step 2b 调用；调用前组装 `RunConfig`（含解析后的 timeout、action_name、current_turn）并传给 Handler
- 提供 `build_run_config(action_name, turn, execution_id, terminate_event)` 供 `ParallelDispatcher` 创建 execution 级运行配置
- 提供 `get_available_actions_meta()` 供 Step 1 构建 prompt（实时遍历，meta 由 handler 内部缓存；被依赖检查跳过的 Action 不会出现在列表中）
- 提供 `get_selected_action_detail(action_name)` 供 Step 2a 构建 prompt
- 提供 `register_action()` 供 `register_temporary_script` 在运行时注册新 Action（支持 `force=True` 覆盖）
- 提供 `unregister_action()` 供运行时注销 Action
- 提供 `get_action_timeout(action_name)` 供 `ParallelDispatcher` 解析批量超时
- 提供 `get_action_mode(action_name)` 供 `QueryLoop._build_action_spec()` 正确设置 `ActionSpec.mode`，解决 ONGOING action 被误当 SINGLE_RUN 的问题

可用性语义：
- `list_available_action_names()` 委托给 `ActionRegistry.get_available_action_names()`，返回按 allowlist 过滤并排序后的名称列表
- 只有成功注册且未被 allowlist 排除的 Action 才被视为"可用"
- 动态注册的 Action 自动加入 allowlist，下一 turn 自然可见

---

## Dynamic Action

动态 Action 机制允许 LLM 在 query-loop 运行期间创建新的 `SCRIPT` 类型 Action，注册后立即使用，loop 结束后随 `ActionRegistry` 实例销毁而自动清理。

### Workflow

1. `create_temporary_script`：将 Python 代码写入 workspace 的 `.py` 文件
2. `register_temporary_script`：框架读取脚本内容，验证 AST 安全，调用内部 LLM 生成完整的 `ACTION_JSON`，校验元数据，然后通过 `make_handler()` 构造动态 `ActionHandler` 注册到 `ActionRegistry`
3. LLM 像调用普通 Action 一样调用新注册的脚本
4. `edit_temporary_script`（可选）：修正脚本；再次注册时自动覆盖旧版本

> **去耦合设计**：`register_temporary_script` 注册期不初始化 LLM client（不要求注册时必须有 API Key），执行期从 `context_provider.client` 延迟获取，支持 bootstrap 阶段无 API Key 启动。

### Sandbox Security

`TemporaryScriptExecutor` 在受限环境中执行 LLM 生成的代码。安全策略六层：
- **AST 节点黑名单**：禁止 `ClassDef`、`AsyncFunctionDef`、`Yield`、`Global`、`Nonlocal` 等
- **内置函数黑名单**：禁止 `eval()`、`exec()`、`compile()`、`breakpoint()` 等
- **模块白名单**：仅允许标准库子集（`json`、`math`、`csv`、`pathlib` 等）；禁止 `os`、`sys`、`subprocess`、`socket`
- **受限 builtins**：`__import__` 被代理为白名单校验函数
- **受控文件 I/O**：`open()` 被替换为沙箱版本，限制在 workspace 目录内，写模式自动创建父目录
- **超时/终止控制**：脚本在 worker 子进程中执行，由 `ManagedProcessRunner` 根据 `RunConfig` deadline/termination 结束进程

脚本约定：
- 必须定义顶层函数 `def _tinysoul_script(action_input: dict, context: dict) -> Any`
- `context` 包含 `query_events`、`loop_target`、`current_turn`、`workspace_location`

---

## Timeout Control

超时按"显式覆盖优先，默认值智能推导"解析：

| 优先级 | 来源 | 说明 |
|:--:|:---|:---|
| 1 | Action 个体声明 | `_runtime_config.timeout = 60.0` |
| 2 | cluster.type 默认 | NATIVE → `action_timeout`；CLI → `cli_timeout`；SCRIPT → `script_timeout` |
| 3 | dependency budget widening | LLM/API 依赖只放大默认值，不覆盖显式 timeout |

超时行为：
- `ParallelDispatcher`：batch timeout 后对对应 `RunConfig` 发出 `request_termination(TIMEOUT)`，并补发 `ACTION_TIMEOUT`；它表达终止意图，不直接杀 executor 的执行载体
- `SubprocessExecutor` / script sandbox worker：通过 `ManagedProcessRunner` 观察 `RunConfig`，超时或终止时结束子进程
- `OneStepAIExecutor`：同步 LLM 调用无法被强杀；调用前后检查 termination，并用 `llm_timeout` 与 action 剩余时间设置请求级 timeout
- native executor：短任务在入口/出口检查即可；长循环型 native action 应在循环中主动调用 `run_config.raise_if_terminated()`
- ONGOING action：`RunConfig.timeout` 只控制启动阶段。启动成功后返回 `ONGOING_STARTED`，后台生命周期由 ongoing control 管理

`ActionTimeoutError` 和 `ActionCancelledError` 均继承自 `ActionExecutionError`，被 `ErrorTrap` 路由为 `Disposition.NEXT_STEP`，双记录到 `loop_error_list` 与 `action_record_list`。`ACTION_TIMEOUT` 记录为 `timeout` 状态，`ACTION_CANCELLED` 记录为 `cancelled` 状态。

---

## Dependency Check

**ActionDependency** 声明单个外部依赖：
- `type`：`"executable" | "python_package" | "env_var" | "file"`
- `name`：依赖标识（如 `"git"`、`"OPENAI_API_KEY"`）
- `optional`：`False`（缺失则跳过注册）或 `True`（缺失仍注册）

**EnvironmentCapabilities** 探测当前环境：
- `probe()`：检查常见可执行文件和环境变量
- `satisfies(dep)`：判断环境是否满足单个依赖
- `unsatisfied(deps)`：返回所有未被满足的 required 依赖

注册时过滤逻辑：`ActionRegistry.register` 先实例化 handler，读取其 `get_runtime_config().dependencies`，调用 `env_caps.unsatisfied(deps)` 检查；存在未满足的 required 依赖则记录到 `_skipped`，不注册。

---

## Invariants

- 所有框架错误继承自 `TinysoulError`
- `ActionRegistry` 是纯实例级，不存在模块级全局注册表
- Action 模块 import 时不产生副作用，不自动注册
- `ACTION_JSON` 是 Action 的唯一真相源，`JsonMetaProvider` 自动解析并缓存
- timeout、dependency 等运行时控制参数不进入 ACTION_JSON，对 LLM 不可见
- LLM-dependent Action 的 system messages 必须通过 `tinysoul.prompt.action.build_llm_action_system()` 组装，顺序固定为 loop-level system → action execution context → action-specific system
- `ActionBase.execute()` 边界包装器：未知异常升级为 `ActionExecutionError`，`TinysoulError` 子类原样透传
- 动态注册的 Action 自动加入当前 allowlist，下一 turn 立即可见
- `QueryAction` 的 handler 缓存完全委托给 `ActionRegistry`，自身不维护平行缓存
- `RunConfig` 在每次 `execute()` 调用前由框架组装，携带本次执行的解析后 timeout
- `execution_id` 是一次 Action execution 的关联 id；ONGOING 状态和 stop action 均以它为准
- Dispatcher 发出 termination intent，Executor 按自身载体协作式停止
- ONGOING action 的启动 timeout 不约束后台生命周期；后台终止由 ongoing control 和 stop action 处理
- `ActionRegistry.with_allowlist` 返回的 view 共享底层 `_registry` 和 `_handler_cache`
- `ActionRegistry.register_action_class()` 便捷方法消除重复注册样板代码
- `validate_action_metadata` 在注册期拒绝结构不合法的动态 Action
- `validate_action_input` 在执行期拒绝参数不匹配的 Action 调用
- `register_temporary_script` 注册期不初始化外部依赖（无 API Key 可启动）
- `SubprocessExecutor` 输出契约：JSON 非 object 时包装为 `{"result": parsed}`；空/非 JSON 时包装为 `{"output": stdout}`
