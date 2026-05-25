# LLM Provider

LLM Provider（multi-model AI client with retry and failover for TinySoul）

`llm/provider/` 是 TinySoul 与外部大语言模型服务之间的统一适配层。它屏蔽了不同厂商 API 的差异，为上层 `llm/tasks/` 提供单一、稳定的调用接口，同时内置多模型池、逐模型重试与跨模型故障转移能力。

## Design_Principles

（1）OpenAI SDK 为统一底座
- 所有 Chat、Embedding、Image Generation 适配器均基于 `openai` Python SDK 构建
- 通过 `base_url` + `api_key` 切换不同 provider，降低多厂商适配成本
- Provider-specific 参数（如 thinking、reasoning_effort、max_completion_tokens）通过 `_build_params()` 覆盖注入

（2）统一中间表示
- `AIRequest`：所有 adapter 的输入中间表示，携带 OpenAI-compatible messages、system messages、可选的 per-request config override
- `AIResponse`：所有 adapter 的输出中间表示，统一包含 `content`、`reasoning_content`、`embedding`、`images`、`metadata`
- 上层 `AITask` 和 `Interpreter` 无需关心底层 provider

（3）多模型池与故障转移
- `AIClient` 内部按 `model_type`（chat / embedding / image_gen）维护三个独立模型池
- 每个模型配置独立的 `max_retries` 和 `base_retry_delay`
- 单模型重试耗尽后，自动故障转移到同池的下一模型
- 全部耗尽时抛出 `SystemExhaustedError`，由 `ErrorTrap` 路由为 ABORT

（4）装饰器注册，零配置扩展
- 新增 provider 只需继承基类 adapter，覆盖少量常量，加上 `@register_adapter(provider, model_type)`
- 无需修改工厂函数或维护巨大的 if/else 映射表

## Core_Components

### AIClient

多模型 AI 客户端，管理模型池、重试与故障转移：

```python
class AIClient:
    def chat(self, messages, system=None) -> AIResponse
    def embed(self, texts) -> AIResponse
    def generate_image(self, prompt) -> AIResponse
```

属性：
- `current_chat_config`：当前正在使用的 chat 模型配置
- `current_chat_model_name`：当前 chat 模型名称
- `has_next_chat_model()`：池中是否还有后备模型

构造方式：
- 生产环境：通过 `_AIClientSingleton` 自动从环境变量检测并构建
- 测试环境：直接注入 `AIClient(configs)`，绕过单例

### AIRequest

规范化的请求结构：

```python
@dataclass
class AIRequest:
    messages: list[dict[str, Any]]   # OpenAI-compatible，支持 multimodal content parts
    system: list[dict[str, str]] | None = None
    config: ModelConfig | None = None  # 可选的 per-request 配置覆盖
```

### AIResponse

规范化的响应结构：

```python
@dataclass
class AIResponse:
    content: str = ""                         # 主文本输出
    reasoning_content: str | None = None      # 思维链 / thinking 内容
    embedding: list[float] | None = None      # Embedding 向量
    images: list[str] | None = None           # Base64 编码的图片数据
    metadata: dict = field(default_factory=dict)  # usage、model、finish_reason 等
```

### ModelConfig

单个模型的完整配置：

```python
@dataclass
class ModelConfig:
    provider: str
    model: str
    model_type: ModelType = ModelType.CHAT
    capabilities: list[ModelCapability] = field(default_factory=lambda: [ModelCapability.TEXT])
    api_key: str | None = None
    base_url: str | None = None
    temperature: float = 0.7
    max_tokens: int = 4000
    enable_thinking: bool = False
    dimensions: int | None = None        # embedding 专用
    extra_params: dict = field(default_factory=dict)
    max_retries: int = 3
    base_retry_delay: float = 1.0
```

### ModelType & ModelCapability

```python
class ModelType(StrEnum):
    CHAT = "chat"
    EMBEDDING = "embedding"
    IMAGE_GEN = "image_gen"

class ModelCapability(StrEnum):
    TEXT = "text"
    VISION = "vision"
    REASONING = "reasoning"
    TOOL_USE = "tool_use"
```

### Adapter Architecture

三类抽象基类：

| 基类 | 方法 | 用途 |
|------|------|------|
| `ChatAdapter` | `chat(request, config) -> AIResponse` | 对话补全，支持 multimodal |
| `EmbeddingAdapter` | `embed(texts, config) -> AIResponse` | 文本嵌入 |
| `ImageGenAdapter` | `generate(prompt, config) -> AIResponse` | 图像生成 |

所有 Chat adapter 继承 `OpenAIChatAdapter`，其模板方法如下：

```
_build_params(request, config)    # 构造 API 参数（可覆盖）
    ↓
_call_chat(params)                # 调用 openai.chat.completions.create
    ↓
_extract_content(response)        # 提取 content + reasoning_content（可覆盖）
    ↓
_build_metadata(response)         # 提取 usage、model 等元数据
    ↓
AIResponse
```

Provider 只需覆盖 `_build_params` 和（可选）`_extract_content`，即可接入框架。

## Provider_Specifics

### Zhipu（智谱 AI / GLM）

（1）端点
- Base URL：`https://open.bigmodel.cn/api/paas/v4/`
- 身份验证：HTTP Bearer Token（`Authorization: Bearer {API_KEY}`）

（2）环境变量
- `GLM_API_KEY` 或 `ZHIPU_API_KEY`
- `GLM_MODEL`（默认 `glm-4.7`）
- `GLM_VISION_MODEL`（默认 `glm-4v`）
- `GLM_EMBEDDING_MODEL`（默认 `embedding-3`）
- `GLM_IMAGE_GEN_MODEL`（默认 `cogview-3-plus`）

（3）特殊参数
- `thinking` 通过 `extra_body={"thinking": {"type": "enabled"}}` 传递（OpenAI SDK 兼容方式）
- 支持 Chat、Embedding、Image Generation 三类任务

### Kimi（Moonshot AI）

（1）端点
- Base URL：`https://api.moonshot.cn/v1`
- 身份验证：HTTP Bearer Token

（2）环境变量
- `KIMI_API_KEY` 或 `MOONSHOT_API_KEY`
- `KIMI_MODEL`（默认 `kimi-k2.6`）
- `KIMI_EMBEDDING_MODEL`（默认 `kimi-embedding-v1`）
- `KIMI_IMAGE_GEN_MODEL`（默认 `kimi-k2-image`）

（3）特殊参数
- `kimi-k2.6` / `kimi-k2.5` 的 `thinking` 参数必须通过 `extra_body` 传递，否则 OpenAI SDK 会将其视为未知顶层参数而拒绝
- `kimi-k2.6` 仅接受 `temperature=0.6`；框架自动移除 `temperature` 键，让 API 使用内部默认值
- `max_tokens` 需映射为 `max_completion_tokens`（OpenAI 新规范）
- 支持 Chat、Embedding、Image Generation

### DeepSeek

（1）端点
- Base URL：`https://api.deepseek.com`
- 身份验证：HTTP Bearer Token

（2）环境变量
- `DEEPSEEK_API_KEY`
- `DEEPSEEK_MODEL`（默认 `deepseek-v4-pro`）
- `DEEPSEEK_EMBEDDING_MODEL`（默认 `deepseek-embedding`）

（3）特殊参数
- `thinking` 与 `reasoning_effort` 作为顶层参数直接传递
- `deepseek-v4-pro` 支持 reasoning 模式；`deepseek-v4-flash` 为高速非思考模式
- 支持 Chat、Embedding；Image Generation 暂由其他 provider 提供

### MiniMax

（1）端点
- Base URL：`https://api.minimaxi.com`
- 身份验证：HTTP Bearer Token

（2）环境变量
- `MINIMAX_API_KEY`
- `MINIMAX_MODEL`（默认 `MiniMax-M2.7`）
- `MINIMAX_EMBEDDING_MODEL`（默认 `minimax-embedding`）

（3）特殊参数
- `max_tokens` 映射为 `max_completion_tokens`，且上限截断为 **2048**
- 响应内容中可能包含 `<think>...</think>` 标签，框架通过正则自动过滤，避免污染下游 JSON 解析
- 支持 Chat、Embedding；Image Generation 暂由其他 provider 提供

## Configuration_&_Auto_Discovery

### 自动检测流程

`AIClient` 初始化时执行以下自动检测：

（1）遍历 `_PROVIDER_MODELS` 元数据表，检查各 provider 的环境变量
（2）发现 API key 后，读取对应模型名（环境变量覆盖 > 默认值）
（3）按 `provider_chain` 优先级排序模型池
（4）构造 `ModelConfig` 列表并注入 `AIClient`

### 环境变量总表

| Provider | API Key 环境变量 | 模型环境变量 | 默认 Chat 模型 |
|----------|-----------------|-------------|---------------|
| zhipu | GLM_API_KEY, ZHIPU_API_KEY | GLM_MODEL | glm-4.7 |
| kimi | KIMI_API_KEY, MOONSHOT_API_KEY | KIMI_MODEL | kimi-k2.6 |
| deepseek | DEEPSEEK_API_KEY | DEEPSEEK_MODEL | deepseek-v4-pro |
| minimax | MINIMAX_API_KEY | MINIMAX_MODEL | MiniMax-M2.7 |
| minimax | — | MINIMAX_IMAGE_GEN_MODEL | abab6.5s-image |

### 全局配置覆盖

通过 `TINYSOUL_*` 前缀的环境变量可覆盖默认值：

| 环境变量 | 类型 | 默认值 | 说明 |
|----------|------|--------|------|
| TINYSOUL_PROVIDER_CHAIN | list[str] | `["kimi", "deepseek", "zhipu", "minimax"]` | 故障转移优先级链 |
| TINYSOUL_MAX_RETRIES | int | 3 | 单模型重试次数 |
| TINYSOUL_BASE_RETRY_DELAY | float | 1.0 | 指数退避初始延迟（秒） |
| TINYSOUL_TEMPERATURE | float | 0.7 | 采样温度 |
| TINYSOUL_MAX_TOKENS | int | 8000 | 框架级最大生成 token 数（模型级默认仍为 4000） |

> 注：AIClient 自动检测直接采用 `ModelConfig` 字段默认值（max_tokens=4000 等）；上述 `TINYSOUL_*` 为框架级配置，供显式调用方读取使用。

## Retry_&_Failover

### 单模型重试策略

```
attempt 0: 立即执行
    ↓ 失败
sleep(base_retry_delay × 2^0)
attempt 1: 重试
    ↓ 失败
sleep(base_retry_delay × 2^1)
attempt 2: 重试
    ↓ 失败
→ 故障转移
```

### 异常映射与决策

| OpenAI SDK 异常 | 映射为 | 处理方式 |
|----------------|--------|----------|
| `APIConnectionError` | `LLMTransientError` | 重试 / 故障转移 |
| `APITimeoutError` | `LLMTransientError` | 重试 / 故障转移 |
| `RateLimitError` | `LLMTransientError` | 重试 / 故障转移 |
| `InternalServerError` | `LLMTransientError` | 重试 / 故障转移 |
| `AuthenticationError` | `ConfigError` | ABORT（配置致命错误） |
| 其他未知异常 | 原样抛出 | 重试 / 故障转移 |

### 故障转移日志

`AIClient` 通过注入的 `EventLogger` 发射以下事件：
- `llm_ready`：首个可用模型就绪
- `llm_retry`：当前模型重试中
- `llm_failover`：从模型 A 故障转移到模型 B

## Extending_Provider

新增一个 provider（以示例 ` ExampleAI` 为例）：

```python
from tinysoul.llm.provider.adapters import OpenAIChatAdapter, register_adapter
from tinysoul.llm.provider.config import ModelConfig

@register_adapter("example", "chat")
class ExampleChatAdapter(OpenAIChatAdapter):
    DEFAULT_BASE_URL = "https://api.example.com/v1"
    ENV_KEY_NAMES = ("EXAMPLE_API_KEY",)

    def _build_params(self, request, config):
        params = super()._build_params(request, config)
        # provider-specific overrides
        params["custom_param"] = "value"
        return params
```

无需修改 `AIClient`、`create_adapter()` 或任何工厂函数；装饰器会自动注册到二维适配器表 `_ADAPTER_REGISTRY[provider][model_type]` 中。

## Invariants

- `AIClient` 的三个模型池（chat / embed / image_gen）相互独立，故障转移不会跨类型发生
- 所有 adapter 必须返回 `AIResponse`，不允许直接返回 provider-native 响应对象
- `reasoning_content` 的提取由各自 adapter 负责；若 provider 不返回 thinking 内容，该字段为 `None`
- `embedding` 和 `images` 字段仅在对应任务类型中填充，chat 任务中保持 `None`
