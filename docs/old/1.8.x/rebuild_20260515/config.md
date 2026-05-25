# Configuration

Configuration（centralized framework defaults and environment-variable overrides）

Config 模块为 TinySoul 提供统一的配置管理。其设计目标是：**所有可调的框架参数集中在一处，支持代码默认值、环境变量、`.env` 文件三层覆盖，且新增参数零成本**。

## Design_Principles

（1）Single Source of Truth
- 所有框架默认值从 `defaults.py` 导出，禁止在业务代码中写魔法数字
- 13 个原先硬编码的文件已全部接入 `settings` 单例

（2）三层优先级覆盖
```
代码默认值（defaults.py）
    ↓ 被覆盖
环境变量 / .env 文件（TINYSOUL_*）
```
- 模块级单例 `settings = GlobalSettings.from_env()` 在导入时完成上述两层合并；直接实例化 `GlobalSettings` 可进一步覆盖默认值
- `.env` 在模块导入时自动加载；已存在的系统环境变量优先于 `.env`

（3）零成本扩展
- 新增一个可调参数只需要 **两步**：
  1. 在 `defaults.py` 中定义 `DEFAULT_XXX`
  2. 在 `GlobalSettings` 中声明同名字段并绑定默认值
- `from_env()` 通过反射自动识别新字段，无需手动添加映射代码

（4）命名约定即接口
- 环境变量名自动推导：`TINYSOUL_{FIELD_NAME.upper()}`
- 类型转换自动处理：根据字段注解将字符串转为 `int` / `float` / `bool` / `list[str]`

## Core_Components

### defaults.py（常量仓库）

集中存放 20+ 个框架默认常量，按语义分组：

| 分组 | 代表常量 | 说明 |
|------|----------|------|
| LLM | `DEFAULT_TEMPERATURE`, `DEFAULT_MAX_TOKENS`, `DEFAULT_MAX_RETRIES`, `DEFAULT_BASE_RETRY_DELAY` | 采样参数与重退避策略 |
| Provider | `DEFAULT_PROVIDER_CHAIN` | 多模型池 failover 优先级 |
| Embedding | `DEFAULT_EMBEDDING_PROVIDER`, `DEFAULT_EMBEDDING_MODEL` | Embedding 服务提供商与模型 |
| Image Generation | `DEFAULT_IMAGE_GEN_PROVIDER`, `DEFAULT_IMAGE_GEN_MODEL` | 图像生成服务提供商与模型 |
| Content Truncation | `DEFAULT_REFERENCE_TRUNCATE`, `DEFAULT_CONTENT_TRUNCATE` | Prompt 注入时的内容截断上限 |
| Debug Preview | `DEFAULT_LLM_PARSE_PREVIEW_CHARS`, `DEFAULT_INTERPRETER_RAW_PREVIEW_CHARS`, `DEFAULT_INTERPRETER_CLEANED_PREVIEW_CHARS` | JSON 解析失败时的预览长度 |
| Timeouts | `DEFAULT_SUBPROCESS_TIMEOUT`, `DEFAULT_SCRIPT_TIMEOUT`, `DEFAULT_GIT_TIMEOUT` | 各类执行超时 |
| Query Loop | `DEFAULT_MAX_TURNS` | 单轮查询最大 turn 数 |
| Logging | `DEFAULT_LOG_LEVEL`, `DEFAULT_LOG_CATEGORIES`, `DEFAULT_LOG_COLOR` | 日志级别、分类、颜色开关 |

### settings.py（运行时配置）

`GlobalSettings` 是一个标准 dataclass，字段与 `defaults.py` 一一对应：

```python
@dataclass
class GlobalSettings:
    temperature: float = defaults.DEFAULT_TEMPERATURE
    max_tokens: int = defaults.DEFAULT_MAX_TOKENS
    provider_chain: list[str] = field(default_factory=lambda: list(defaults.DEFAULT_PROVIDER_CHAIN))
    ...
```

**`from_env()` 自动推导机制**：

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
- `list[str]` → 按逗号分割（如 `TINYSOUL_PROVIDER_CHAIN=zhipu,deepseek`）
- 其他 → 原样作为 `str`

### __init__.py（公共 API）

暴露模块级单例 `settings` 和 17 个核心 `DEFAULT_*` 常量（Embedding 与 Image Generation 的默认值未在 `__init__.py` 中重新导出）：

```python
from tinysoul.infra.config import settings
print(settings.max_tokens)        # 读取当前生效值
print(settings.provider_chain)    # 读取 failover 链
```

## Environment_Variable_Reference

| 环境变量 | 字段类型 | 默认值 | 说明 |
|----------|----------|--------|------|
| `TINYSOUL_TEMPERATURE` | float | 0.7 | LLM 采样温度 |
| `TINYSOUL_MAX_TOKENS` | int | 8000 | 单次 completion 最大 token |
| `TINYSOUL_MAX_RETRIES` | int | 3 | 单模型内部重试次数 |
| `TINYSOUL_BASE_RETRY_DELAY` | float | 1.0 | 退避初始延迟（秒） |
| `TINYSOUL_PROVIDER_CHAIN` | list[str] | kimi,deepseek,zhipu,minimax | 多模型 failover 顺序 |
| `TINYSOUL_REFERENCE_TRUNCATE` | int | 8000 | 引用文件内容注入 prompt 时的截断长度 |
| `TINYSOUL_CONTENT_TRUNCATE` | int | 16000 | 现有文件内容送入 LLM 时的截断长度 |
| `TINYSOUL_LLM_PARSE_PREVIEW_CHARS` | int | 2000 | 日志中 LLM 原始响应预览长度 |
| `TINYSOUL_INTERPRETER_RAW_PREVIEW_CHARS` | int | 800 | 异常消息中原始响应预览长度（反馈给 LLM） |
| `TINYSOUL_INTERPRETER_CLEANED_PREVIEW_CHARS` | int | 400 | 异常消息中清洗后响应预览长度（反馈给 LLM） |
| `TINYSOUL_SUBPROCESS_TIMEOUT` | float | 30.0 | 通用 subprocess 超时（已废弃，同 cli_timeout） |
| `TINYSOUL_ACTION_TIMEOUT` | float | 30.0 | 通用 Action 执行超时（SINGLE_RUN 启动阶段及未指定类型的 Action） |
| `TINYSOUL_CLI_TIMEOUT` | float | 30.0 | CLI 类型 Action 执行超时 |
| `TINYSOUL_SCRIPT_TIMEOUT` | float | 5.0 | SCRIPT 类型 Action 沙箱执行超时 |
| `TINYSOUL_GIT_TIMEOUT` | float | 30.0 | Git CLI 操作超时（已废弃，同 cli_timeout） |
| `TINYSOUL_MAX_TURNS` | int | 20 | 单次查询最大 turn 数 |
| `TINYSOUL_PARALLEL_DISPATCH_BUFFER` | float | 10.0 | 并行批次最慢决定者算法的缓冲时间 |
| `TINYSOUL_LOG_LEVEL` | str | normal | 日志级别：quiet \| normal \| verbose \| debug |
| `TINYSOUL_LOG_CATEGORIES` | str | all | 日志分类，逗号分隔或 all |
| `TINYSOUL_LOG_COLOR` | str | "1" | 控制台颜色："1"=启用，"0"=禁用 |
| `TINYSOUL_EMBEDDING_PROVIDER` | str | zhipu | Embedding 服务提供商 |
| `TINYSOUL_EMBEDDING_MODEL` | str | embedding-3 | Embedding 模型名称 |
| `TINYSOUL_IMAGE_GEN_PROVIDER` | str | zhipu | 图像生成服务提供商 |
| `TINYSOUL_IMAGE_GEN_MODEL` | str | cogview-3-plus | 图像生成模型名称 |

## Integration

### LLM Provider

`LLMClient` 从 `settings` 读取默认值构建 `LLMConfig`：
- `temperature`, `max_tokens`, `max_retries`, `base_retry_delay` → `LLMConfig` 字段
- `provider_chain` → `_LLMClientSingleton._auto_detect_configs()` 的检测顺序

### Logging

`infra/logger.py` 从 `settings` 读取：
- `log_level` → `EventLevel` 映射
- `log_categories` → 分类过滤器
- `log_color` → ANSI 颜色开关

### Query Loop

`loop.py` 从 `settings` 读取 `max_turns` 控制循环终止条件。

### Action Handlers

多个 action handler 从 `settings` 读取截断和超时参数：
- `reference_truncate` → `create_markdown_file`, `edit_markdown_file`, `create_temporary_script`, `edit_temporary_script`
- `content_truncate` → `edit_markdown_file`, `read_markdown_file`
- `subprocess_timeout` → `SubprocessExecutorBase`
- `action_timeout` / `script_timeout` → `ScriptExecutor`
- `cli_timeout` / `subprocess_timeout` / `git_timeout` → `SubprocessExecutor`

## Config_Invariants

All tunable constants are defined in `defaults.py`; no magic numbers in business code
Environment variable names are auto-derived: `TINYSOUL_` + `FIELD_NAME.upper()`
Adding a new parameter requires only `defaults.py` + `GlobalSettings` field declaration; `from_env()` needs no change
`.env` is loaded once at module import time; existing system env vars take precedence over `.env`
`list[str]` fields accept comma-separated values; spaces around items are stripped during parsing
Empty string env vars are treated as "not set" and fall back to code defaults
`settings` is a module-level singleton; imported once and reused everywhere
Provider failover order is controlled by `settings.provider_chain`, not hard-coded in `client.py`
