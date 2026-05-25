# LLM

LLM 模块位于 `tinysoul/llm/`，是 TinySoul 与外部大语言模型服务之间的统一适配层。它屏蔽了不同厂商 API 的差异，为上层 `loop/` 和 `action/` 提供单一、稳定的调用接口，同时内置多模型池、逐模型重试与跨模型故障转移能力。

---

## Design Principles

### 1. OpenAI SDK 为统一底座

- 所有 Chat、Embedding、Image Generation 适配器均基于 `openai` Python SDK 构建
- 通过 `base_url` + `api_key` 切换不同 provider，降低多厂商适配成本
- Provider-specific 参数（如 thinking、reasoning_effort、max_completion_tokens）通过 `_build_params()` 覆盖注入

### 2. 统一中间表示

- `AIRequest`：所有 adapter 的输入中间表示，携带 OpenAI-compatible messages、system messages、可选的 per-request config override
- `AIResponse`：所有 adapter 的输出中间表示，统一包含 `content`、`reasoning_content`、`embedding`、`images`、`metadata`
- 上层 `AITask` 和 `Interpreter` 无需关心底层 provider

### 3. 多模型池与故障转移

- `AIClient` 内部按 `model_type`（chat / embedding / image_gen）维护独立模型池
- Chat 模型按 provider 分组保存，运行时再按 `ChatProfile` 构造当前调用的 provider 链
- 每个模型配置独立的 `max_retries` 和 `base_retry_delay`
- 单模型重试耗尽后，自动故障转移到同池的下一模型
- 全部耗尽时抛出 `SystemExhaustedError`，由 `ErrorTrap` 路由为 `ABORT`
- **Failover 索引持久化**：`_call_with_retry()` 返回 `(AIResponse, final_index)`。Chat 调用按 `step1` / `step2` / `step3` / `action_llm` profile 独立保存索引，Embedding / Image Gen 分别保存自己的索引，避免不同调用场景互相污染。
- Chat profile 可声明 `required_capabilities` 与 `preferred_capabilities`。前者是硬约束，后者是软偏好；vision 等多模态能力通过 `ModelCapability` 表达，不引入独立的 `CHAT_VISION` 类型。

### 4. Prompt 与 Execution 分离

- `LLMPrompt` 是纯数据对象，描述 prompt 的五元素结构，支持可选的 `attachments`（多模态附件）
- `PromptBuilder` 负责组装 `LLMPrompt`，自动从 `ContextProvider` 注入共享运行时上下文
- `AITask` 持有 `LLMPrompt` + `Interpreter`，负责执行和解析
- 三者可独立测试和替换

### 5. 装饰器注册，零配置扩展

- 新增 provider 只需继承基类 adapter，覆盖少量常量，加上 `@register_adapter(provider, model_type)`
- 无需修改工厂函数或维护巨大的 if/else 映射表

---

## Architecture

```
llm/
├── provider/
│   ├── client.py         AIClient（多模型池 + 故障转移 + 索引持久化）
│   ├── config.py         ModelConfig / ModelType / ModelCapability
│   ├── request.py        AIRequest
│   ├── response.py       AIResponse
│   └── adapters/
│       ├── base.py       OpenAIChatAdapter / OpenAIEmbeddingAdapter / OpenAIImageGenAdapter
│       ├── deepseek.py
│       ├── kimi.py
│       ├── minimax.py
│       └── zhipu.py
└── tasks/
    ├── task.py           AITask（统一 LLM 调用入口）
    ├── prompt.py         PromptBuilder + LLMPrompt
    ├── interpreter.py    响应解析器
    ├── result.py         TaskResult
    └── multimodal.py     Attachment + ContentBuilder
```

---

## Provider

### AIClient

多模型 AI 客户端，管理模型池、重试与故障转移：

```python
class AIClient:
    def chat(self, messages, system=None, config=None) -> AIResponse
    def embed(self, texts, config=None) -> AIResponse
    def generate_image(self, prompt, config=None) -> AIResponse
```

构造方式：
- 生产环境：通过 `_AIClientSingleton` 自动从环境变量检测并构建
- 测试环境：直接注入 `AIClient(configs)` 实例到 `QueryLoop(client=...)` 或 `AITask(client=...)`，绕过单例

**Request-level Config Override**：每个 API 调用支持传入 `config` 参数（`dict`），与 pool config 合并。合并规则：
- `merge_config(override, base)`：递归合并，override 字段优先
- `resolve_defaults(config)`：补全缺失字段为 pool 或全局默认值

### Auto-Detection

`AIClient` 初始化时遍历 `DEFAULT_PROVIDER_MODEL_SPECS`：
1. 检查模型槽位声明的 API key 环境变量
2. 读取模型名（模型环境变量覆盖 > `default_model`）
3. 将 `model_type` 与 `capabilities` 转换为 `ModelConfig`
4. 构造完整模型配置列表并注入 `AIClient`

Provider 模型槽位集中描述默认模型、模型环境变量、API key 环境变量和能力标注。`chat_vision` 是 zhipu 的一个 chat 槽位，`model_type` 仍为 `chat`，其多模态能力由 `capabilities=["text", "vision"]` 表达。

Chat 调用时，`AIClient` 根据当前 profile 的 `provider_chain` 动态构造本次模型池：
1. 按 provider 顺序查找可用 chat 配置
2. 若存在 `chat_model_overrides[provider]`，使用其中的 `model` 覆盖默认模型
3. 否则先筛选满足 `required_capabilities` 的模型
4. 再优先选择满足 `preferred_capabilities` 的模型
5. 单个 provider 只进入本次模型池一次

支持的 Provider：

| Provider | Chat | Embedding | Image Gen | API Key 环境变量 |
|----------|------|-----------|-----------|-----------------|
| zhipu | ✅ | ✅ | ✅ | `GLM_API_KEY`, `ZHIPU_API_KEY` |
| kimi | ✅ | ✅ | ✅ | `KIMI_API_KEY`, `MOONSHOT_API_KEY` |
| deepseek | ✅ | ✅ | — | `DEEPSEEK_API_KEY` |
| minimax | ✅ | ✅ | — | `MINIMAX_API_KEY` |

### Retry & Failover

单模型重试策略：指数退避（`base_retry_delay × 2^attempt`），最多 `max_retries` 次。

异常映射：
- `APIConnectionError` / `APITimeoutError` / `RateLimitError` / `InternalServerError` → `LLMTransientError`（触发重试/故障转移）
- `AuthenticationError` → `ConfigError`（致命错误，直接 `ABORT`）

故障转移日志：`llm_ready`（首个可用模型）、`llm_retry`（当前模型重试中）、`llm_failover`（模型 A → 模型 B）。

**索引持久化**：`_call_with_retry()` 返回 `(response, final_index)`。`chat()` 将 `final_index` 写回对应 profile 的索引；`embed()` / `generate_image()` 写回各自索引，确保后续调用从上次成功的模型继续。

### Adapter Architecture

三类抽象基类：

| 基类 | 方法 | 用途 |
|------|------|------|
| `ChatAdapter` | `chat(request, config) -> AIResponse` | 对话补全，支持 multimodal |
| `EmbeddingAdapter` | `embed(texts, config) -> AIResponse` | 文本嵌入 |
| `ImageGenAdapter` | `generate(prompt, config) -> AIResponse` | 图像生成 |

所有 Chat adapter 继承 `OpenAIChatAdapter`，其模板方法：
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

### Provider Specifics

**Zhipu**：`thinking` 通过 `extra_body` 传递；支持 Chat、Embedding、Image Gen。

**Kimi**：`thinking` 通过 `extra_body` 传递（顶层参数会被 OpenAI SDK 拒绝）；`kimi-k2.6` 自动移除 `temperature`；`max_tokens` 映射为 `max_completion_tokens`。

**DeepSeek**：`thinking` / `reasoning_effort` 作为顶层参数直接传递；`deepseek-v4-pro` 支持 reasoning 模式。

**MiniMax**：`max_tokens` 映射为 `max_completion_tokens` 且上限截断为 **2048**；响应中可能包含 `<think>...</think>` 标签，框架通过正则自动过滤。

---

## Tasks

### Five-Element Prompt Structure

所有发给 LLM 的 prompt 由五个元素构成，可选附加第六个元素（多模态附件）：

```
=== TASK GUIDE ===
{what the model should do}

=== CONTEXT ===
{query_events, loop_target, current_state, workspace, current_turn}

=== INPUT ===
{task-specific data description}
{task-specific data JSON}

=== OUTPUT CONSTRAINT ===
{expected format, schema, rules}

=== EXAMPLES ===
{few-shot demonstrations}
```

### PromptBuilder

绑定到一个 `ContextProvider`，提供 `build()` 方法：

```python
def build(
    *,
    task_guide: str,
    input_spec: InputSpec,
    output_constraint: OutputConstraint,
    examples: list[Example] | None = None,
    extra_context: dict | None = None,
    include_context: list[str] | None = None,
    attachments: list[Attachment] | None = None,
) -> LLMPrompt
```

自动将 `ContextProvider` 中的共享运行时上下文注入 CONTEXT 部分。默认注入全部字段：`query_events`, `loop_target`, `current_state`, `workspace`, `current_turn`。

**上下文字段选择（`include_context`）**：
- 支持顶层字段选择：`["query_events", "current_turn", "current_state"]`
- 支持嵌套字段选择：`["current_state.todo_list", "current_state.milestone_list"]`
- 当父字段与子字段同时出现时，父字段优先，返回完整对象
- 当传入空列表 `[]` 时，context 部分为空（仅保留 `extra_context`）

### AITask

自包含的 AI 任务单元：

```python
class AITask:
    def run(self, system: list[dict[str, str]] | None = None) -> TaskResult:
        ...
```

执行流程：
1. 序列化 `LLMPrompt` 为 user prompt 字符串
2. 如有 `attachments`，将其转换为 OpenAI-compatible multimodal content parts
3. 通过 `EventLogger` 发射 `debug_prompt` 事件
4. 调用注入的 `client.chat()`（或默认 `get_ai_client()`）
5. 将原始 `AIResponse` 交给 `Interpreter` 解析
6. 返回 `TaskResult(data=dict, response=AIResponse)`

### Interpreter

解析 LLM 原始响应为 JSON 对象：
- 自动去除 markdown code fence（```json ... ```）
- 通过花括号深度扫描提取首个顶层 JSON object
- 调用 `json.loads()` 解析为 Python 对象
- 验证结果必须是 `dict` 类型，否则抛出 `LLMResponseParseError`

解析失败时抛出 `LLMResponseParseError`，由上层（QueryLoop 或 ActionExecutor）捕获并转化为错误响应。

### Multimodal Support

`Attachment` 支持三种构造方式：
- `Attachment.from_image_file(path)`：从本地图片文件读取并 base64 编码
- `Attachment.from_image_base64(data, mime_type)`：从 base64 字符串构造
- `Attachment.from_image_url(url)`：从远程 URL 构造（部分 provider 不支持）

`ContentBuilder` 提供静态方法直接生成 OpenAI-compatible content parts。

---

## Integration

### With Prompt Resources

- 框架级 prompt 文本位于 `tinysoul/prompt/*/markdown/`，以 markdown 作为内置 package resource 维护
- `tinysoul.infra.resources` 提供通用 text/markdown 加载能力，不理解 prompt 语义，可复用于 skill、memory 等外部资源
- `tinysoul.prompt.loop.system` 负责组装 loop-level system，`tinysoul.prompt.action.system` 负责组装 LLM action system；`PromptBuilder` 仍只负责五元素 user prompt
- Action schema、State schema、`InputSpec.data`、`OutputConstraint` 等运行时结构化内容不进入 system context

### With Query Loop

- 三个 Step 均通过 `AITask` 调用 LLM
- `PromptBuilder` 自动注入共享上下文
- Action schema 和 State schema 通过 `InputSpec.data` 传入，而非 system context

### With Actions

Workspace Action（如 `create_markdown_file`, `edit_markdown_file`）是 `AITask` 的重度使用者。

`OneStepAIExecutor` 的模板方法：
```
receive action_input (dict)
    ↓
build prompt via PromptBuilder + custom _build_*_prompt function
    ↓
build_llm_action_system(context_provider, action_system)
    ↓
AITask.run(system=full_system)
    ↓
interpreter parses LLM response as JSON object
    ↓
apply result via custom _apply_*_result function
    ↓
return dict
```

该设计让 Workspace Action 只需提供两个函数：
- `build_prompt(builder, params, workspace) -> LLMPrompt`
- `apply_result(params, generated, workspace, context_provider) -> dict`

其余流程（system 组装、LLM 调用、错误处理、响应解析、重试、故障转移）由 `tinysoul.prompt.action.build_llm_action_system()`、`OneStepAIExecutor` 和 `AITask` 统一处理。`register_temporary_script` 等非 OneStep 模板的 LLM-dependent action 也复用同一 system builder。

### With ErrorTrap

- `AIClient.chat()` 内部指数退避重试
- 单模型失败 → 捕获 `LLMTransientError`，自动重试/切换模型
- 全部模型池耗尽 → 抛出 `SystemExhaustedError`
- `SystemExhaustedError` 被 ErrorTrap 识别为 `AbortError` → `Disposition.ABORT`

---

## Extension Guide

### 新增 Provider

```python
from tinysoul.llm.provider.adapters import OpenAIChatAdapter, register_adapter
from tinysoul.llm.provider.config import ModelConfig

@register_adapter("example", "chat")
class ExampleChatAdapter(OpenAIChatAdapter):
    DEFAULT_BASE_URL = "https://api.example.com/v1"
    ENV_KEY_NAMES = ("EXAMPLE_API_KEY",)

    def _build_params(self, request, config):
        params = super()._build_params(request, config)
        params["custom_param"] = "value"
        return params
```

无需修改 `AIClient`、`create_adapter()` 或任何工厂函数；装饰器自动注册到二维适配器表 `_ADAPTER_REGISTRY[provider][model_type]`。

### 新增 LLM Task

任何需要调用 LLM 的组件都应通过 `AITask`：
1. 使用 `PromptBuilder` 构造 `LLMPrompt`
2. 实例化 `AITask(prompt=..., interpreter=Interpreter(), client=...)`
3. 调用 `task.run(system=...)` 获取 `TaskResult`
4. 消费 `task_result.data`（已解析的 JSON dict）

不要直接调用 `AIClient.chat()`，以确保一致的调试输出和错误处理。

---

## Invariants

- `AIClient` 的三个模型池（chat / embed / image_gen）相互独立，故障转移不会跨类型发生
- 所有 adapter 必须返回 `AIResponse`，不允许直接返回 provider-native 响应对象
- `reasoning_content` 的提取由各自 adapter 负责；若 provider 不返回 thinking 内容，该字段为 `None`
- `embedding` 和 `images` 字段仅在对应任务类型中填充，chat 任务中保持 `None`
- 系统中不存在直接调用 LLM provider 的代码（除 `AIClient.chat` 外）
- 所有 prompt 构造、执行、响应解析都收敛到 `AITask`
- `LLMPrompt.serialize()` 生成的字符串是纯文本；attachments 不进入序列化文本，由 `AITask` 独立转换为 multimodal content parts
- `Interpreter` 解析失败时必须抛出 `LLMResponseParseError`，不能静默返回空 dict
- `TaskResult.data` 永远是 `dict` 类型（即使为空也是 `{}`）
- `PromptBuilder` 的 `include_context` 支持嵌套字段选择，但父字段优先于子字段
- Provider failover 顺序由 `settings.chat_profiles[profile].provider_chain` 控制，非硬编码在 `client.py`
- Provider 模型槽位、默认模型、env key 与能力标注集中在 `DEFAULT_PROVIDER_MODEL_SPECS`
- Chat profile 支持 `required_capabilities` 硬约束和 `preferred_capabilities` 软偏好；vision 等多模态能力通过 `ModelCapability` 表达，不引入独立的 `CHAT_VISION` 类型
- Chat profile 支持 `chat_model_overrides: dict[provider, {model, capabilities?}]`，可在同一 profile 中覆盖多个 provider 的 chat 默认模型。覆盖未知模型时必须显式声明 capabilities，避免错误继承基础模型能力。
- `_call_with_retry()` 返回 `(AIResponse, final_index)`；调用方负责将 `final_index` 持久化到对应 profile 或模型类型索引
- `merge_config()` 递归合并 request-level override；`resolve_defaults()` 补全缺失字段
