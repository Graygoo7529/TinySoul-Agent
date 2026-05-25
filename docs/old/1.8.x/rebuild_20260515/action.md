# Action

Action（command pattern, JSON parameter passing）

Action 是 TinySoul 的核心执行单元。框架层（`tinysoul.action.framework`）定义接口与元数据体系，插件层（`tinysoul.action.handlers`、`tinysoul.action.executors`）提供具体实现。二者之间保持单向依赖：插件层依赖框架层，框架层对插件层零感知。

## Design_Principles

（1）元数据与执行分离
- `ActionHandler` 负责元数据（name, cluster, profile, contract, detail）
- `ActionExecutor` 负责实际执行逻辑
- 一个 Action 可以更换 Executor 而不影响其元数据暴露给 LLM 的形态

（2）JSON 作为单一真相源
- 每个 Action 通过 `ACTION_JSON` 字符串自描述其完整 schema
- `JsonActionHandler` 在运行时自动解析 `ACTION_JSON` 为 `ActionMeta` 和 `ActionDetail`
- 消除过去"JSON schema + Python dataclass 双写"的冗余
- `JsonActionHandler` 在实例级别缓存解析结果，避免每 turn 重复 `json.loads`
- 解析器做了防御性兼容：LLM 可能把 `postconditions` 写成 list 或把 detail 字段放错位置，均自动归位

（3）实例级注册与零全局状态
- `ActionRegistry` 是纯实例级注册表，每个实例维护独立的 `_registry` 字典
- 没有模块级全局注册表，没有类级别 `_REGISTRY`
- Action 模块 import 时**不产生副作用**，不自动注册
- `bootstrap(registry)` 显式遍历模块并调用 `register_to(registry)` 完成注册
- `QueryAction` 接收注入的 `ActionRegistry` 实例，只加载该实例中存在的 Action

（4）运行时配置与 LLM 上下文分离
- `ActionRuntimeConfig` 声明在 Handler 上，描述 timeout、dependencies 等基础设施控制参数
- `RunConfig` 在每次 `execute()` 调用前由框架组装，携带解析后的实际执行控制值
- timeout、dependency 等运行时控制参数**不进入 ACTION_JSON**，对 LLM 完全不可见
- PromptBuilder 只暴露 `ContextProvider`（业务上下文），不暴露 `RunConfig`（执行控制）

（5）Action 依赖声明与环境适配
- Action 通过 `ActionDependency` 声明所需外部能力（executable、env_var、python_package、file）
- `EnvironmentCapabilities` 在框架启动时探测当前环境
- `ActionRegistry.register()` 自动过滤不满足依赖的 Action，被跳过的 Action 不出现在可用列表中
- 支持 `optional=True` 的依赖：缺失时不阻止注册，但可能限制功能

## Layer_Architecture

```
┌─────────────────────────────────────────┐
│  query/                                 │
│  - QueryAction（运行时 Action 管理器）      │
│  - register_temporary_script 手动注入      │
├─────────────────────────────────────────┤
│  action/handlers/internal/scripting/     │
│  - CreateTemporaryScriptAction            │
│  - EditTemporaryScriptAction              │
│  - RegisterTemporaryScriptAction          │
│  - RegisterTemporaryScriptExecutor        │
├─────────────────────────────────────────┤
│  action/executors/script/                │
│  - ScriptExecutor（基类）                 │
│  - TemporaryScriptExecutor（沙箱执行）     │
├─────────────────────────────────────────┤
│  infra/                                  │
│  - sandbox module（AST 过滤 + 受限 globals）│
│  - capabilities module（环境探测 + 依赖声明）│
├─────────────────────────────────────────┤
│  action/executors/subprocess/            │
│  - SubprocessExecutor（基类）             │
│  - CLIExecutor（预定义 CLI 命令）          │
│  - BashExecutor（任意 bash，未注册）        │
├─────────────────────────────────────────┤
│  action/executors/llm/                   │
│  - OneStepAIExecutor                     │
├─────────────────────────────────────────┤
│  action/handlers/internal/               │
│  - workspace actions（ActionBase 子类）    │
│  - calculate, file ops, monitor, etc.     │
├─────────────────────────────────────────┤
│  action/handlers/cli/                    │
│  - git（GitAction + GitExecutor）         │
├─────────────────────────────────────────┤
│  action/framework/（框架层）               │
│  - ActionHandler（ABC）                   │
│  - JsonActionHandler（ABC）               │
│  - ActionBase（标准桥接）                  │
│  - RuntimeAction（运行时构造）             │
│  - ActionExecutor（ABC）                   │
│  - ActionRegistry（实例级，allowlist）     │
│  - ActionRuntimeConfig / RunConfig        │
│  - Metadata dataclasses + Enums           │
│  - Action JSON Schema (schema.py)         │
└─────────────────────────────────────────┘
```

## Core_Abstractions

### ActionHandler

Command Pattern 的抽象基类，定义三个契约：
- `get_meta() -> ActionMeta`：暴露 Action 的元数据
- `get_detail() -> ActionDetail`：暴露 Action 的参数 schema、示例、边界处理
- `execute(action_input: dict, context_provider, run_config) -> dict`：接收结构化参数对象，返回结果字典

`JsonActionHandler` 自动从 `ACTION_JSON` 解析 meta/detail，并在实例级缓存结果。子类需定义 `action_name` 和 `ACTION_JSON` 类属性。
`ActionBase` 为所有框架内执行的 Action 提供统一基类，通过 `_executor` 注入执行逻辑，并持有 `_runtime_config` 声明运行时配置。
`RuntimeAction` 在运行时构造，无需预先编写子类，用于承载 LLM 生成的动态 Action。

### ActionExecutor

执行逻辑的抽象。子类实现 `execute(action_input, context_provider, run_config)`。

`run_config: RunConfig` 携带本次执行的控制参数（已解析的 timeout、action_name、turn），Executor 从中读取 timeout 并执行相应的中断策略。

当前有四种典型实现路径：
- **纯 Python 执行**（如 `CalculateExecutor`、`DeleteFileExecutor`）：直接调用 Python 函数
- **LLM 单步模板执行**（`OneStepAIExecutor`）：parse → build_prompt → LLM call → parse response → apply_result（LLM 超时由 AIClient 内部控制，忽略 `run_config.timeout`）
- **沙箱脚本执行**（`TemporaryScriptExecutor` → `ScriptExecutor`）：读取文件 → AST 验证 → 受限环境执行（从 `run_config` 读取 timeout）
- **子进程执行**（`CLIExecutor` / `BashExecutor` → `SubprocessExecutor`）：构建命令 → `subprocess.run(timeout=...)` → 解析 stdout（从 `run_config` 读取 timeout，超时抛 `ActionTimeoutError`）

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

### ActionRuntimeConfig & RunConfig

**ActionRuntimeConfig** 是声明式配置，附着在 Action Handler 类上，描述该 Action 的固有能力需求：
- `timeout: float | None` — 个体超时覆盖值；`None` 表示由框架按 `cluster.type` 推导
- `dependencies: list[ActionDependency]` — 运行所需外部依赖列表

**RunConfig** 是运行时实例，每次 `execute()` 调用前由 `QueryAction` 组装，描述这一次具体执行的控制参数：
- `timeout: float | None` — 解析后的实际超时值（个体覆盖 > cluster.type 默认 > 全局默认）
- `action_name: str` — 当前执行的 Action 名称
- `turn: int` — 当前 turn 编号

解析链路（`ActionBase.resolve_run_config`）：
```
ActionRuntimeConfig.timeout
    ├─ 有值 → 直接使用（个体覆盖）
    └─ None → 按 cluster.type 查 settings
         INTERNAL → settings.action_timeout
         CLI      → settings.cli_timeout
         SCRIPT   → settings.script_timeout
              ↓
        写入 RunConfig.timeout
              ↓
        传给 ActionExecutor.execute()
```

### ActionRegistry

实例级注册表，每个实例独立：
```python
_registry: Dict[str, Tuple[str, Callable[[], ActionHandler]]]
```

- `register(name, action_json, factory, *, force=False)`：注册 Action，默认不允许重复注册。当 `force=True` 时，允许覆盖已存在的同名 Action（自动清除旧 handler 缓存）。注册前实例化 handler 并检查 `ActionRuntimeConfig.dependencies`；若有 required 依赖不满足，则记录到 `_skipped` 并跳过注册
- `unregister(name)`：移除 Action（包括从 registry 和 handler_cache 中清除）
- `get_handler(name)`：通过 factory 实例化 Handler，结果惰性缓存
- `get_action_json(name)`：获取原始 ACTION_JSON
- `is_available(name)`：检查 Action 是否注册且未被 allowlist 过滤
- `with_allowlist(names)`：返回新的 registry view，共享底层数据但只暴露指定 Action
- `get_skipped()`：返回因依赖不满足而被跳过的 Action 列表（用于诊断日志）
- 运行时注册自动放行：若当前视图有 allowlist，新注册的 name 自动加入 allowlist

### Timeout_Control

超时按三层优先级解析：

| 优先级 | 来源 | 说明 |
|:--:|:---|:---|
| 1 | Action 个体声明 | `_runtime_config.timeout = 60.0` |
| 2 | cluster.type 默认 | INTERNAL → `action_timeout` (30s)；CLI → `cli_timeout` (30s)；SCRIPT → `script_timeout` (5s) |
| 3 | 全局 fallback | 所有类型最终回退到 `settings.action_timeout` |

超时行为：
- `SubprocessExecutor`：通过 `subprocess.run(timeout=...)` 实现，超时后抛 `ActionTimeoutError`
- `ScriptExecutor`：通过 `thread.join(timeout=...)` 实现，超时后抛 `ActionTimeoutError`
- `OneStepAIExecutor`：不处理 `run_config.timeout`，LLM 调用超时由 `AIClient` 内部重试与故障转移机制控制
- `CalculateExecutor` 等纯 Python 执行器：瞬时完成，通常不触发超时；框架仍传递 `RunConfig` 供未来扩展

`ActionTimeoutError` 继承自 `ActionExecutionError`，被 `ErrorTrap` 路由为 `Disposition.CONTINUE`，双记录到 `loop_error_list` 与 `action_record_list`。LLM 在下一 turn 的 Step 3 看到超时记录后可自行调整策略。

### Dependency_Check

**ActionDependency** 声明单个外部依赖：
- `type`：`"executable" | "python_package" | "env_var" | "file"`
- `name`：依赖标识（如 `"git"`、`"OPENAI_API_KEY"`）
- `constraint`：可选版本/路径约束（预留）
- `optional`：`False`（缺失则跳过注册）或 `True`（缺失仍注册）

**EnvironmentCapabilities** 探测当前环境：
- `probe()`：检查常见可执行文件（git、docker、kimi-cli 等）和环境变量
- `satisfies(dep)`：判断环境是否满足单个依赖
- `unsatisfied(deps)`：返回所有未被满足的 required 依赖

**注册时过滤逻辑**（`ActionRegistry.register`）：
1. 调用 `factory()` 实例化 handler
2. 读取 `handler.get_runtime_config().dependencies`
3. 调用 `env_caps.unsatisfied(deps)` 检查
4. 若存在未满足的 required 依赖：记录到 `_skipped`，**不注册**
5. 若全部满足（或只有 optional 缺失）：正常注册

依赖检查是**交集（AND）**逻辑：所有 required 依赖都必须满足，不是并集。

## Metadata_Enums

Action 的 profile 由四个枚举维度刻画：

- `action_intention`：EXTERNAL_PROBING | INTERNAL_REASONING | EXECUTION
- `action_environment_effect`：READ_ONLY | ADDITIVE | MODIFYING | DESTRUCTIVE
- `action_mode`：SINGLE_RUN | ONGOING
- `llm_dependency`：NONE | OPTIONAL | REQUIRED

`applicability_mode`（ALWAYS_CONSIDER | CONDITIONAL）位于 `action_contract.applicability`，不属于 profile。

> 注：`action_type` 已从 profile 中移除，并入 `action_cluster.type`。

## Action_Cluster

`{type, domain}` 二元分类，用于组织 Action 目录结构和路由：

- `{"type": "INTERNAL", "domain": "MATH"}`：calculate
- `{"type": "INTERNAL", "domain": "KNOWLEDGE"}`：average_dog_weight
- `{"type": "INTERNAL", "domain": "WORKSPACE"}`：scan_workspace, read_markdown_file, create_markdown_file, edit_markdown_file, delete_file
- `{"type": "INTERNAL", "domain": "SCRIPTING"}`：create_temporary_script, edit_temporary_script, register_temporary_script
- `{"type": "INTERNAL", "domain": "MONITORING"}`：monitor（ONGOING 实验性 Action）
- `{"type": "CLI", "domain": "VERSION_CONTROL"}`：git

`type` 维度同时承担 Action 分类语义：
- `INTERNAL`：框架内 Python 执行
- `CLI`：预定义子进程命令
- `SCRIPT`：沙箱脚本执行

## QueryAction

QueryLoop 中的 Action 运行时管理器。职责：
- 根据 `available_actions` 名称列表，从注入的 `ActionRegistry` 实例化 Handler
- 提供 `execute(action_name, action_input)` 供 Step 2b 调用；调用前组装 `RunConfig`（含解析后的 timeout、action_name、current_turn）并传给 Handler
- 提供 `get_available_actions_meta()` 供 Step 1 构建 prompt（实时遍历，meta 由 handler 内部缓存；被依赖检查跳过的 Action 不会出现在列表中）
- 提供 `get_selected_action_detail(action_name)` 供 Step 2a 构建 prompt
- 提供 `register_action()` 供 `register_temporary_script` 在运行时注册新 Action（支持 `force=True` 覆盖）
- 提供 `unregister_action()` 供运行时注销 Action
- 提供 `get_action_timeout(action_name)` 供 `ParallelDispatcher` 解析批量超时

可用性语义：
- `list_available_action_names()` 委托给 `ActionRegistry.get_available_action_names()`，返回按 allowlist 过滤并排序后的名称列表
- 只有成功注册且未被 allowlist 排除的 Action 才被视为"可用"
- 动态注册的 Action 自动加入 allowlist，下一 turn 自然可见
