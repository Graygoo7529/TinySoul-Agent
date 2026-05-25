# Dynamic_Action

动态 Action 机制允许 LLM 在 query-loop 运行期间创建新的 `SCRIPT` 类型 Action，注册后立即使用，loop 结束后随 `ActionRegistry` 实例销毁而自动清理。

## Design_Motivation

（1）内置 Action 的边界
- 框架预置的 Action（calculate、workspace 文件操作等）覆盖常见场景，但无法预知所有用户任务
- 当 LLM 需要执行特定数据分析、文本处理或格式转换时，内置 Action 可能不够用
- 让 LLM 直接生成 Python 代码并执行，比不断扩展内置 Action 列表更灵活

（2）安全与可控的平衡
- 允许 LLM 生成并执行代码 = 打开安全攻击面
- 方案：代码必须定义在沙箱中执行，禁止危险操作（文件写、网络、系统调用）
- 脚本生命周期绑定到当前 QueryLoop，不持久化，loop 结束即销毁

（3）两阶段工作流
- 第一阶段：LLM 用 `create_temporary_script` 把代码写入 workspace 的 `.py` 文件
- 第二阶段：LLM 用 `register_temporary_script` 将该文件注册为 Action
- 第三阶段：LLM 像调用普通 Action 一样调用新注册的脚本
- 第四阶段（可选）：LLM 用 `edit_temporary_script` 修正脚本；再次调用 `register_temporary_script` 时会自动覆盖旧版本，无需先注销
- 分离"写文件"和"注册"两个动作，让 LLM 有机会检查、修正代码

## Core_Concepts

### TEMPORARY_SCRIPT

`cluster.type = SCRIPT` 的动态 Action，与 `INTERNAL`、`CLI` 并列。

特征：
- `cluster.type = SCRIPT`
- `action_environment_effect = MODIFYING`（沙箱允许在 workspace 内读写文件）
- `llm_dependency = NONE`（脚本本身不调用 LLM，是纯 Python 逻辑）
- 脚本可通过标准 Python I/O 读写 workspace 文件（`open()`、`csv`、`pathlib`），禁止路径穿越
- 当前工作目录（CWD）已自动设置为 workspace 根目录，相对路径直接解析到 workspace
- `__file__` 在沙箱中已定义，指向脚本文件的绝对路径
- `open()` 在写模式（`w`/`a`/`wb` 等）下会自动创建缺失的父目录
- `action_mode = SINGLE_RUN`
- 生命周期：与 `ActionRegistry` 实例同生共死

脚本约定：
- 必须定义顶层函数 `def _tinysoul_script(action_input: dict, context: dict) -> Any`
- `action_input` 是 JSON 参数解析后的 dict
- `context` 包含 `user_query`、`loop_target`、`current_turn`、`workspace_location`
- 返回值会被序列化为 JSON 字符串或 str 透传

### Dynamic_Registration

运行时注册新 Action 的能力，由 `register_temporary_script` 内置 Action 触发。

注册流程：
1. LLM 提供参数 `(new_action_name, script_path)`
2. 框架读取脚本内容，验证 AST 安全
3. 框架调用 LLM 基于脚本内容生成完整的 `action_json`（参数 schema、description、contract 等）
4. 验证生成的 `action_json`（name 匹配、cluster.type = SCRIPT）
5. 构造 `RuntimeAction` factory 并注册到 `ActionRegistry` 和 `QueryAction`；若同名 Action 已存在，自动注销旧版本后注册新版本
6. 新 Action 立即在后续 turn 中可见

### Sandbox

`TemporaryScriptExecutor` 在受限环境中执行 LLM 生成的代码。

安全策略六层：
- **AST 节点黑名单**：禁止 `ClassDef`、`AsyncFunctionDef`、`Yield`、`YieldFrom`、`Global`、`Nonlocal`、`Delete`、`Await`、`AsyncFor`、`AsyncWith` 等危险语法节点
- **内置函数黑名单**：禁止调用 `eval()`、`exec()`、`compile()`、`breakpoint()` 等危险内置函数
- **模块白名单**：仅允许标准库子集（`json`、`math`、`random`、`collections`、`csv`、`io`、`pathlib` 等）；禁止 `os`、`sys`、`subprocess`、`socket`
- **受限 builtins**：`__import__` 被代理为白名单校验函数；危险内置函数被移除
- **受控文件 I/O**：`open()` 被替换为 `_sandbox_open()`，限制在 workspace 目录内，禁止路径穿越；允许读写追加模式（`r`/`w`/`a` 及其二进制变体）；写模式下自动创建缺失的父目录
- **CWD 绑定**：脚本执行前自动 `os.chdir(workspace_location)`，执行后恢复，确保相对路径基于 workspace
- **`__file__` 注入**：沙箱 globals 中注入 `__file__`（脚本绝对路径），支持 `Path(__file__)` 等惯用法
- **超时控制**：通过 `threading.Thread` + `join(timeout)` 限制执行时间（默认 5 秒）

## Workflow

完整的三阶段工作流示例（分析 CSV 文件）：

```
Turn 1: create_temporary_script
  参数: target_access="scripts/analyze.py"
        instruction="读取 CSV 文件，计算每列的 avg/max/min"
  结果: workspace/scripts/analyze.py 被创建

Turn 2: register_temporary_script
  参数: new_action_name="analyze_csv"
        script_path="scripts/analyze.py"
  结果: 框架读取脚本、调用 LLM 生成 action_json，"analyze_csv" 被注册

Turn 3: analyze_csv（新 Action）
  参数: {"file_path": "data/numbers.csv"}
  结果: {"column_a": {"avg": 30, "max": 50, "min": 10}, ...}

Turn 4: create_markdown_file
  参数: target_access="reports/analysis.md"
        instruction="把分析结果写成 markdown 报告"
  结果: workspace/reports/analysis.md 被创建
```

## Architecture

动态 Action 涉及的新组件在现有架构中的位置：

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
│  - sandbox module（AST 过滤 + 受控 open）  │
├─────────────────────────────────────────┤
│  action/framework/（框架层）               │
│  - ActionBase（标准桥接）                  │
│  - RuntimeAction（运行时构造）             │
│  - JsonActionHandler（实例级 meta 缓存）   │
│  - ActionRegistry（实例级，零全局状态）     │
└─────────────────────────────────────────┘
```

关键设计决策：

（1）`RuntimeAction` 不依赖子类化
- 内置 Action 通过继承 `ActionBase` 并编写子类来定义
- `RuntimeAction` 在实例化时接收 `(action_name, action_json, executor)`，无需预先编写类
- 这使得 LLM 生成的任意 Action 都可以被框架承载

（2）`ActionRegistry` 实例级设计
- 没有全局 `_REGISTRY`，也没有模块级默认实例
- 每个 `QueryLoop` 拥有独立的 `ActionRegistry` 实例
- 动态注册的 Action 不会泄漏到其他 QueryLoop
- `bootstrap(registry)` 显式注册内置 Action，import 无副作用

（3）`QueryAction` 单一状态层
- 可用性来源只有 `_registry` 一个 `ActionRegistry` 实例
- `list_available_action_names()` 委托给 `self._registry.get_available_action_names()`
- 动态注册后新 Action 自动可见，无需维护平行列表

## Availability_Control

`create_temporary_script`、`edit_temporary_script` 和 `register_temporary_script` 是内置 Action，但**默认不在可用列表中**。通过 `available_action_names` 显式开启：

```python
QueryLoop(
    available_action_names=[
        "create_temporary_script",
        "edit_temporary_script",
        "register_temporary_script",
        # ... 其他 action
    ]
)
```

当 `available_action_names=None`（无 allowlist）时，所有已注册 Action 都可用，包括上述两个。

## Relationship_to_Existing_System

- 与 `ActionRegistry`：动态注册调用 `registry.register()`，复用现有注册接口
- 与 `QueryAction`：调用 `register_action()`，复用现有 handler 缓存机制
- 与 `Workspace`：`create_temporary_script`、`edit_temporary_script` 和 `TemporaryScriptExecutor` 都通过 `workspace.resolve_access()` 解析文件路径
- 与 `ErrorTrap`：沙箱执行失败抛出 `ActionExecutionError`，被 ErrorTrap 正常捕获并记录
