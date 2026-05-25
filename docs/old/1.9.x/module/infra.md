# Infra

Infra 模块位于 `tinysoul/infra/`，为 TinySoul 提供底层基础设施能力：集中配置管理、结构化事件日志、公共进程控制层、脚本沙箱执行环境、通用文本资源加载。其设计目标是**所有可调的框架参数集中在一处，所有事件输出可观测，所有外部执行可控制，所有文本资源加载有统一边界**。

---

## Design Principles

### 1. Single Source of Truth

- 所有框架默认值从 `defaults.py` 导出，禁止在业务代码中写魔法数字
- 原先 13 个硬编码文件已全部接入 `settings` 单例

### 2. 两层优先级覆盖

```
代码默认值（defaults.py）
    ↓ 被覆盖
环境变量 / .env 文件（TINYSOUL_*）
```

- `GlobalSettings.from_env()` 在导入时完成上述两层合并
- `.env` 在模块导入时自动加载；已存在的系统环境变量优先于 `.env`

### 3. 零成本扩展

- 新增一个可调参数只需要 **两步**：在 `defaults.py` 中定义 `DEFAULT_XXX`，在 `GlobalSettings` 中声明同名字段
- `from_env()` 通过反射自动识别新字段，无需手动添加映射代码

### 4. 业务代码与输出格式解耦

- `EventLogger` 只负责「过滤 + 路由」
- `Sink` 负责「格式化 + 输出目的地」
- 新增输出格式（如文件日志、JSON 流）只需新增 Sink，不改业务代码

### 5. 安全与可控的平衡

- 允许 LLM 生成并执行代码 = 打开安全攻击面
- 方案：代码必须在沙箱中执行，禁止危险操作（文件写、网络、系统调用）
- 脚本生命周期绑定到当前 QueryLoop，不持久化，loop 结束即销毁

### 6. 资源加载与语义分离

- `infra.resources` 只负责加载 text/markdown，不理解 prompt、skill、memory 等上层语义
- filesystem 资源必须通过 root + relative path 解析，并校验 resolved path 不越过 root
- package 资源通过 `importlib.resources` 加载，供内置 markdown prompt 使用

---

## Text Resource Loader

`tinysoul.infra.resources` 提供通用文本资源加载：

```python
load_text_from_filesystem(name, root, relative_path, required=True)
load_text_from_package(name, package, resource, required=True)
loaded_text_from_inline(name, content)
```

返回 `LoadedTextResource`：

```python
@dataclass(frozen=True)
class LoadedTextResource:
    name: str
    content: str
    source_type: "filesystem" | "package" | "inline"
    root: Path | None = None
    relative_path: str | None = None
    resolved_path: Path | None = None
```

该 loader 当前用于 `tinysoul.prompt` 加载内置 markdown prompt，也可作为后续 skill、memory、AGENT.md 关联文件的通用加载基础设施。

### Resource Invariants

- infra loader 不拼接 prompt，不决定 system 顺序
- optional 缺失返回 `None`；required 缺失抛错
- filesystem path 必须留在 root 边界内
- builtin prompt 使用 package data 加载，不依赖当前工作目录

---

## Config

### defaults.py

集中存放 20+ 个框架默认常量，按语义分组：

| 分组 | 代表常量 | 说明 |
|------|----------|------|
| LLM | `DEFAULT_TEMPERATURE`, `DEFAULT_MAX_TOKENS`, `DEFAULT_MAX_RETRIES` | 采样参数与重退避策略 |
| Provider | `DEFAULT_PROVIDER_MODEL_SPECS`, `DEFAULT_CHAT_PROFILES`, `DEFAULT_CHAT_PROVIDER_CHAIN` | provider 模型槽位、默认模型、能力标注，以及 step1 / step2 / step3 / action_llm 的独立 chat failover 链 |
| Embedding / Image Gen | `DEFAULT_EMBEDDING_PROVIDER`, `DEFAULT_IMAGE_GEN_MODEL` | 扩展服务配置 |
| Content Truncation | `DEFAULT_REFERENCE_TRUNCATE`, `DEFAULT_CONTENT_TRUNCATE` | Prompt 注入时的内容截断上限 |
| Debug Preview | `DEFAULT_LLM_PARSE_PREVIEW_CHARS` 等 | JSON 解析失败时的预览长度 |
| Timeouts | `DEFAULT_ACTION_TIMEOUT`, `DEFAULT_CLI_TIMEOUT`, `DEFAULT_SCRIPT_TIMEOUT`, `DEFAULT_LLM_TIMEOUT`, `DEFAULT_ACTION_LLM_OVERHEAD`, `DEFAULT_ACTION_API_OVERHEAD` | 各类执行与依赖预算 |
| Query Loop | `DEFAULT_MAX_TURNS` | 单轮查询最大 turn 数 |
| Parallel Dispatch | `DEFAULT_PARALLEL_DISPATCH_BUFFER`, `DEFAULT_PARALLEL_MAX_WORKERS` | 批量并行调度的超时缓冲与并发上限 |
| Logging | `DEFAULT_LOG_LEVEL`, `DEFAULT_LOG_CATEGORIES`, `DEFAULT_LOG_COLOR` | 日志级别、分类、颜色开关 |

### settings.py

`GlobalSettings` 是标准 dataclass，字段与 `defaults.py` 一一对应。`from_env()` 自动推导：

```python
@classmethod
def from_env(cls) -> "GlobalSettings":
    kwargs: dict[str, Any] = {}
    type_hints = typing.get_type_hints(cls)
    for f in fields(cls):
        env_name = f"TINYSOUL_{f.name.upper()}"
        raw = _env(env_name)
        if raw is None:
            continue
        kwargs[f.name] = _convert_env_value(raw, type_hints[f.name])
    return cls(**kwargs)
```

类型转换规则：
- `int` / `float` / `bool` → 数值/逻辑解析
- `list[str]` → 按逗号分割
- `dict[...]` → JSON 解析（如 `TINYSOUL_CHAT_PROFILES={...}`）
- 其他 → 原样作为 `str`

模块级单例：`settings = GlobalSettings.from_env()`，导入一次，全局复用。

### Config Invariants

- 所有可调常量定义在 `defaults.py`；业务代码中无魔法数字
- 环境变量名自动推导：`TINYSOUL_` + `FIELD_NAME.upper()`
- 新增参数只需 `defaults.py` + `GlobalSettings` 字段声明；`from_env()` 无需修改
- `.env` 在模块导入时加载一次；系统环境变量优先于 `.env`
- `list[str]` 字段接受逗号分隔值；空格自动 strip
- 空字符串环境变量视为"未设置"，回退代码默认值

---

## EventLogger

### Design

四级日志级别：

| Level | 输出内容 | 典型场景 |
|---|---|---|
| `QUIET` | 无任何输出 | CI 批量测试、headless 运行 |
| `NORMAL` | Loop Ready / Turn 边界 / Step 1-3 核心流 / Todo & Milestone / 简要错误 | 日常交互 |
| `VERBOSE` | NORMAL + 错误详情 / workspace scan / LLM retry & failover | 调试行为异常 |
| `DEBUG` | VERBOSE + 完整 state JSON / action meta/detail / 完整 LLM prompt | 深度调试 |

七类事件分类：

| Category | 用途 |
|---|---|
| `LOOP` | Turn 开始/结束、Loop Ready/Complete、中断 |
| `ACTION` | Action 选择、参数、结果 |
| `STATE` | Todo/Milestone 变更、workspace 扫描 |
| `ERROR` | Step 失败、通用错误 |
| `LLM` | 重试、模型切换 |
| `PROMPT` | 完整 LLM prompt dump |
| `WARN` | 警告信息 |

分类过滤与级别过滤正交：一个事件必须同时满足「级别 >= 阈值」且「分类在订阅集合中」才会输出。

### Sink Architecture

```
EventLogger（level / category filtering → route to sinks）
    ↓
Sink (ABC) — emit(event: Event)
    ├── ConsoleSink（ANSI 颜色 + 固定列对齐 + 智能换行）
    ├── NullSink（静默丢弃）
    └── CaptureSink（记录到 list，用于测试断言）
```

### ConsoleSink 格式化原则

- **固定列对齐**：label(10) + key(6) + separator(2) + value（从第 18 列开始）
- **语义着色最小化**：蓝色(Step/边界)、青色(key)、绿色(Action 名)、红色(错误)、黄色(非致命)
- **智能换行**：超长 value 自动 wrap，续行保持与首行 value 起始列对齐；保留显式 `\n`
- **ANSI 码不计入视觉宽度**：pad 计算使用纯文本长度

### Injection Pattern

```python
class QueryLoop:
    def __init__(self, ..., logger: EventLogger | None = None):
        self._logger = logger or default_logger()
```

- `default_logger()` 从环境变量读取配置
- 测试注入 `CaptureSink`，断言事件序列（取代 `capsys` stdout 断言）

---

## Process Control

`ManagedProcessRunner` 是 subprocess 与 script sandbox 共享的进程控制层。它不理解 Action 业务，只消费 `RunConfig`：
- 启动子进程并捕获 stdout/stderr
- 轮询 `RunConfig.remaining()` 与 `run_config.is_termination_requested()`
- 超时映射为 `ActionTimeoutError`
- 非超时终止映射为 `ActionCancelledError`
- 停止时先 `terminate()`，短暂等待后升级为 `kill()`

该层让 `SubprocessExecutor` 与 sandbox worker 保持不同安全模型，同时复用一致的 deadline/termination 行为。

## Sandbox

`tinysoul.infra.sandbox` 为 LLM 生成的 Python 脚本提供 AST 验证 + 受限执行环境。

### AST Validation

禁止的 AST 节点：`ClassDef`, `AsyncFunctionDef`, `Yield`, `YieldFrom`, `Global`, `Nonlocal`, `Delete`, `Await`, `AsyncFor`, `AsyncWith`

禁止的函数调用：`__import__`, `exec`, `eval`, `compile`, `input`, `exit`, `quit`, `help`, `dir`, `globals`, `locals`, `vars`, `breakpoint`

允许的模块白名单：`json`, `re`, `math`, `random`, `datetime`, `time`, `collections`, `itertools`, `statistics`, `csv`, `io`, `pathlib` 等 20+ 个标准库子集。禁止 `os`, `sys`, `subprocess`, `socket`。

必须定义顶层函数：`def _tinysoul_script(action_input: dict, context: dict) -> Any`

### Restricted Execution

- **`__import__` 代理**：替换为白名单校验函数
- **`open()` 代理**：替换为 `_sandbox_open()`，限制在 workspace 目录内，禁止路径穿越；写模式自动创建父目录
- **CWD 绑定**：执行前 `os.chdir(workspace_location)`，执行后恢复
- **`__file__` 注入**：指向脚本绝对路径，支持 `Path(__file__)` 惯用法
- **stdout 捕获**：`print()` 输出被捕获并随返回值返回
- **超时/终止控制**：脚本在独立 worker 子进程中运行，由 `ManagedProcessRunner` 根据 `RunConfig` 控制 deadline 和 termination

### Known Limitations

沙箱当前为**尽力而为**（best-effort）安全，非生产级隔离：
- worker 子进程可被 terminate/kill，但没有 OS 级 syscall/network 权限隔离
- `pathlib.Path` 可能绕过 `open()` 代理：受限 globals 仅替换内置 `open()`，但 `pathlib` 使用 C 实现，可能不经过 Python 层的代理
- 未禁止顶层可执行语句：`while True` 在函数外仍可执行；进程级 timeout 可以收口，但无法把这类代码改写为安全代码

> 生产级隔离需要更强的 OS 级沙箱（如容器、job object、seccomp 或独立低权限 worker），当前实现为实验性方案。

### Sandbox Invariants

- 脚本必须通过 AST 验证才能执行
- 所有文件操作限制在 workspace 边界内
- 模块导入必须经过白名单校验
- 危险内置函数在 globals 中不可见
- 超时/终止由 `ManagedProcessRunner` 结束 worker 子进程，并抛出对应 ActionError
- 脚本生命周期绑定到当前 QueryLoop，不持久化

---

## Dependencies

### Runtime

| Package | Version | Purpose |
|---------|---------|---------|
| `openai` | >=1.0 | Unified LLM client base |

其余功能完全依赖 Python 标准库：`dataclasses`, `enum`, `typing`, `pathlib`, `json`, `re`, `abc`, `os`, `sys`, `time`, `threading`, `ast`, `datetime`。

Python 版本基线：**3.13.x**（`python -m compileall` 通过）。项目为个人用途，不追求 Python 3.9 兼容。

### Development

| Package | Purpose |
|---------|---------|
| `pytest` | Test runner |

测试基线：`pytest.ini` 固定 `testpaths = tests`，使用 `--basetemp .pytest-basetemp` 避免 Windows 权限问题。

> **Note:** 项目根目录无 `pyproject.toml` 或 `setup.py`；依赖通过 `requirements.txt` 声明，需手动安装。Conda 环境名 `TinySoul`。

---

## Invariants

- `settings` 是模块级单例；导入一次，全局复用
- `EventLogger` 不直接输出，只路由到 Sink
- `ConsoleSink` 的 ANSI 颜色自动检测 tty，可通过 `TINYSOUL_LOG_COLOR=0` 关闭
- 测试优先使用 `CaptureSink` 断言事件，而非匹配 stdout 字符串
- Sandbox 的 AST 验证和执行必须在同一线程顺序完成（先 validate，再 compile/exec）
- `execute_script()` 不返回裸值，总是返回 `{"return_value": ..., "stdout": ...}`
- subprocess 与 sandbox worker 共享 `ManagedProcessRunner`，但安全策略不合并
- Python 基线 3.13.x；标准库为主，仅依赖 `openai` SDK
