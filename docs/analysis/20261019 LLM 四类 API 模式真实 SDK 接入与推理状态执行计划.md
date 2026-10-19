# LLM 四类 API 模式真实 SDK 接入与推理状态执行计划

状态：`proposed`。本计划建立在 [AGENTS.md](../../AGENTS.md)、已完成的 [API 模式与适配器重构计划](done/20261018-done-LLM API 模式与适配器重构执行计划.md) 和当前代码核对之上，目标是继续完成 Anthropic Messages 与 Google GenerateContent 的真实 SDK 接入，并把四类 API 模式的请求、工具、推理状态和提示缓存语义收敛到一套干净的 TinySoul 内部协议。

本轮先修复了 `tinysoul/agent/composition/builder.py` 的 import 排序问题。该修改只整理 import 分组，`ruff --select I` 已通过；真实 SDK 接入仍待本计划确认后实施。

## 1. 目标与边界

本轮目标是让以下四种线上 API 都有真实的 SDK adapter，并且都能通过同一条链路完成：

```text
TaskCall
  → ModelSpec / ProviderBinding
  → API mode adapter
  → provider SDK client
  → provider request
  → provider response
  → RawResponse / Reasoning / NativeReplay
  → TaskResult
```

范围包括：

1. OpenAI Chat Completions、OpenAI Responses 继续运行，并补齐最新 prompt cache breakpoint、reasoning 和工具约束的真实映射。
2. Anthropic Messages 使用 `AsyncAnthropic.messages.create`，支持文本、图片、工具、thinking、effort、thinking display、prompt cache 和完整 block 回放。
3. Google GenerateContent 使用 `google-genai` 的异步 SDK，支持文本、图片、工具、thinking level/budget、thought summaries、thought signatures、隐式缓存和由 TinySoul 管理的显式缓存。
4. provider 仍只声明 API mode endpoint、凭据和附加 headers；model 仍只声明一个 adapter、稳定 ID 和远端 model binding。
5. 运行时不使用 SDK 自动函数调用，不由 SDK 执行 TinySoul Action；工具只由 TinySoul 声明，Action 仍由 Kernel/Action owner 执行。
6. 真实 SDK 的重试关闭，由 `LLMTaskRunner` 统一重试和切换 provider；SDK 错误在 adapter 边界转换为 `ProviderError`。

本轮不引入：

- Google Interactions API。它与 GenerateContent 使用不同的 input/output、状态和缓存模型，保留为独立后续 API mode，不让 `google-genai` 这个 SDK 名称隐式切换协议。
- Vertex AI IAM、Bedrock、Google Cloud 特有认证治理。当前 provider 继续按 base URL、API key 和 headers 的个人主机模型工作。
- OpenAI `previous_response_id`、服务端会话或 SDK 自动保存历史。TinySoul 继续自行装配 MessageStack 和保存必要的原生回放状态。
- 没有真实消费者的 provider 私有抽象、空壳 adapter、跨 provider 缓存资源和第二套会话状态机。

## 2. 官方 API 语义核对

### 2.1 四类 API 的请求与响应边界

| API mode | 请求主体 | 工具交换 | 思考控制 | 原生状态回放 | 缓存生命周期 |
| --- | --- | --- | --- | --- | --- |
| `openai-chat` | `messages`、`tools`、`tool_choice` | assistant `tool_calls` → tool message | `reasoning_effort`，受模型约束 | Chat 不把 Responses reasoning item 作为标准历史；专用 provider 的 `reasoning_content` 由专用 adapter 处理 | 新模型支持 `prompt_cache_options` 和内容块 `prompt_cache_breakpoint`；provider 管理 |
| `openai-responses` | `input` items、`tools`、`text`、`reasoning` | `function_call` → `function_call_output` | `reasoning.effort/mode/context/summary` | 有序 reasoning/output items，需按来源和内容指纹回放 | implicit/explicit breakpoint、`ttl=30m`、可选 `prompt_cache_key`；Responses 还支持 prewarm/diagnostic 字段 |
| `anthropic-messages` | 顶层 `system` + `messages`、`tools`、`thinking` | assistant `tool_use` block → user `tool_result` block | `thinking` 为 adaptive/enabled/disabled/between_tools；`output_config.effort` 是软控制；`max_tokens` 同时覆盖 thinking 和文本 | thinking block、signature、redacted thinking、tool_use 必须作为完整原始 block 按原顺序回传 | 顶层自动 `cache_control` 或 block breakpoint；5m/1h，provider 自动过期和刷新 |
| `google-generate-content` | `systemInstruction` + `contents`、`tools`、`toolConfig`、`generationConfig` | model `functionCall` part → user `functionResponse` part | `thinkingConfig.thinkingLevel` 或 `thinkingBudget`；`includeThoughts` 只控制摘要返回 | `thoughtSignature` 附着在具体 `Part` 上；函数调用时必须保留相关 part 和 signature | 隐式缓存由 provider 自动处理；显式缓存是 `cachedContents/...` 远端资源，需要创建、复用和 TTL owner |

这些语义来自官方文档：

- [OpenAI Chat Completions](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create)、[OpenAI Responses](https://developers.openai.com/api/reference/resources/responses/methods/create)、[OpenAI reasoning](https://developers.openai.com/api/docs/guides/reasoning)、[OpenAI prompt caching](https://developers.openai.com/api/docs/guides/prompt-caching)。
- [Anthropic thinking](https://platform.claude.com/docs/en/build-with-claude/thinking)、[Anthropic steering and cost](https://platform.claude.com/docs/en/build-with-claude/thinking-steering-and-cost)、[Anthropic prompt caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching)、[Anthropic tool caching](https://platform.claude.com/docs/en/agents-and-tools/tool-use/tool-use-with-prompt-caching)、[Anthropic structured outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs)。
- [Google GenerateContent reference](https://ai.google.dev/api/generate-content)、[Google thinking](https://ai.google.dev/gemini-api/docs/generate-content/thinking)、[Google thought signatures](https://ai.google.dev/gemini-api/docs/generate-content/thought-signatures)、[Google function calling](https://ai.google.dev/gemini-api/docs/generate-content/function-calling)、[Google context caching](https://ai.google.dev/gemini-api/docs/generate-content/caching)、[google-genai Python SDK](https://googleapis.github.io/python-genai/)。

### 2.2 思考、摘要和原生状态必须分开

四类 API 的“思考”不是同一类字段：

- `effort`/`thinking_level`/`thinking_budget` 是请求控制；不能把 Anthropic 的软 effort、Google 的 level 和 OpenAI 的 effort 强行换算成同一个数值。
- 可见的 thinking summary 是模型给出的有限摘要，不是原始 chain of thought。Anthropic 的 `display="summarized"`、Google 的 `includeThoughts=true` 和 OpenAI Responses 的 reasoning summary 都应进入有限的 `Reasoning.summary`。
- signature、encrypted reasoning item、thought signature、redacted thinking 是模型继续多轮或工具交换所需的原生状态。它们必须保持原始类型、顺序、工具关联和来源路由，不能转成普通文本或只保留一个字符串。

因此本轮不再扩大 `Reasoning.content` 的含义，也不以 `reasoning_keep=content/encrypted` 表达四种 API 的全部语义。

### 2.3 SDK 基线

当前 `pyproject.toml` 已声明 `openai>=3.35,<4`、`anthropic>=1.15,<2`、`google-genai>=2.31,<3`。实施前用项目指定 Python 环境重新安装/锁定这三个范围内的最新版本，并以 SDK 实际类型签名为准；计划不在 adapter 中绕过 SDK 拼接 HTTP 请求。`AsyncAnthropic.messages.create`、`google.genai.Client().aio.models.generate_content` 和 OpenAI async client 都由 Registry 统一生命周期管理，SDK retry 关闭后由 `LLMTaskRunner` 负责重试。

## 3. 目标内部协议

### 3.1 `Reasoning` 与 `NativeReplay`

修改 `tinysoul/llm/protocol/reasoning.py`：

```python
@dataclass(frozen=True)
class Reasoning:
    summary: str | None = None
    native_replay: NativeReplay | None = None

@dataclass(frozen=True)
class NativeReplay:
    api_mode: ApiMode
    adapter: AdapterKind
    provider_id: str
    provider_model: str
    kind: NativeReplayKind
    ordered_items: tuple[JsonObject, ...]
    message_fingerprint: str
    variant: str | None = None
```

具体语义：

1. `ordered_items` 取代只适合 reasoning item 的 `ordered_parts` 命名。OpenAI Responses 保存 output items，Anthropic 保存 content blocks，Google 保存 model Content/Part 投影，OpenAI Chat 专用 adapter 保存 Kimi/DeepSeek/GLM/MiniMax 等实际需要的 provider-native reasoning payload。
2. `kind` 只表达如何解释有序 payload，例如 `openai-response-items`、`anthropic-message-blocks`、`google-content-parts`、`openai-chat-reasoning`；它不把 provider JSON 暴露给 Kernel。
3. `Reasoning.summary` 是可供 Context、Observation 和前端有限展示的摘要。签名、encrypted content、redacted thinking 和 thought signature 永远只存在 `NativeReplay`；观察投影只输出来源及是否可回放，不输出原始 payload 或摘要 digest。
4. 原生 replay 按 API mode、adapter/variant、provider、provider model 和 assistant 内容/工具指纹匹配；普通文本历史可按现有消息策略重建，若历史包含签名或加密状态却 route/fingerprint 不匹配，则返回 capability failure，不伪造原生连续性。
5. Anthropic 和 Google 的 adapter 在同一路由中遇到供应商要求原样回传的签名块却没有匹配 replay 时，返回明确的 provider capability/config failure；不发送一个可预期会被供应商拒绝的半截 block。
6. 迁移 OpenAI Chat 专用 adapter：provider 的 `reasoning_content` 是 replay payload；如产品需要有限可见内容，只放入 `Reasoning.summary`，不再把原始 reasoning 当作通用 `Reasoning.content`。`reasoning_keep` 若仍有实际消费者，只作为对应 adapter option 控制原生状态保留，不扩展成所有 API 共用的字段语义。

同步修改 `kernel/context/signals.py`、trace/projection/composer、`llm/execution/context_window.py`、`llm/execution/observation_payloads.py` 和相关 JSON 测试，保证容量统计、持久事实和外部观察仍只看到有限摘要。

### 3.2 Prompt cache 的模型默认策略与调用边界分层

修改 `tinysoul/llm/protocol/cache.py`：

```python
@dataclass(frozen=True)
class PromptCache:
    key: str | None = None
    breakpoint_message_index: int | None = None
    prewarm: bool = False
```

缓存 mode/TTL 留在模型 `adapter_options`，由后端 catalog 给出对应 API mode 实际支持的候选值；`PromptCache` 只表达单次任务的稳定边界和少数调用参数。这样不会要求业务 Task owner 重复声明模型 TOML 已固定的缓存策略。

约束：

- 模型配置的策略只控制该模型实际支持的默认缓存行为；Anthropic 可配置 automatic/explicit/disabled 与 5m/1h TTL，Google 可配置 implicit/explicit 与正整数秒 TTL，OpenAI 只暴露新模型支持的 implicit/explicit 与 30m TTL。旧 OpenAI model binding 不展示 explicit/TTL 不支持选项。provider 差异不换算成一个虚假的通用 enum。
- `breakpoint_message_index` 是 TinySoul 的有界消息边界，不是 provider 字段。OpenAI/Anthropic adapter 把它映射为稳定内容块 marker；Google adapter 将该前缀交给 cache owner 创建 `CachedContent`。
- 使用 explicit 模式时必须由调用提供稳定边界，不能猜测“最后一条消息”；automatic/implicit 模式按 provider 规则工作，不要求调用者构造远端缓存资源。
- `key` 只由支持 cache key 的 OpenAI adapter 消费；`prewarm` 只由 OpenAI Responses adapter 消费。其它模式对不支持的参数报局部配置/能力错误，不把字段伪装成跨 API 通用能力。
- Google 的 `cached_content` 不再作为 model TOML 中的固定字符串。它是运行时由 cache owner 生成的远端资源名，不进入运行方案、model 配置或持久 Session。

### 3.3 工具协议保持 TinySoul 语义，API 特有约束留在 adapter options

不增加 `ToolSelection.parallel`。当前协议表达的是是否启用工具、是否必需以及允许/强制哪个名称；供应商允许模型一次返回几个 function call，不等价于 TinySoul 的 Action 并行执行策略。OpenAI 的 `parallel_tool_calls` 和 Anthropic `disable_parallel_tool_use` 若有真实模型需求，分别作为各自 API mode 的 adapter option 暴露；Google 不虚构相同开关。所有 SDK automatic function execution 都关闭，工具只归一化成模型侧 Tool Message/ActionCall，由 TinySoul 既有 owner 执行。

### 3.4 归一化 usage

把 `RawResponse.usage: dict[str, object]` 收敛为小型 frozen `TokenUsage`：`input_tokens`、`output_tokens`、`reasoning_tokens`、`cached_input_tokens`、`cache_creation_input_tokens` 都可为空。OpenAI、Anthropic、Google 分别把其 SDK usage 字段映射到这些可解释指标；没有对应数据时保留 `None`，不填零或伪造跨 API 可比性。Trace/Observation 仅序列化该类型，不保留 SDK usage 对象。

## 4. 四类真实 adapter 的设计

### 4.1 OpenAI Chat / Responses

保留 `tinysoul/llm/adapter/openai/`，做以下统一修正：

1. `OpenAIAdapter` 只负责 API mode 公共映射；专用 Kimi/DeepSeek/GLM/MiniMax adapter 只覆盖真实的 provider 差异。
2. Chat 和 Responses 按支持模型映射 `prompt_cache_options.mode`、`prompt_cache_options.ttl`、`prompt_cache_key` 和 `prompt_cache_breakpoint`；旧模型不暴露新字段，旧 `prompt_cache_retention` 不进入配置。
3. Responses 增加 `reasoning.mode`、`reasoning.context` 的 typed option；`configuration_update` 暂不加入 MessageStack，因为当前没有真实 consumer，不为未来特性建立无主协议。
4. Chat 不把 provider `reasoning_content` 宣称为 OpenAI 标准 reasoning replay；只有 Kimi/DeepSeek/GLM/MiniMax 等专用 adapter 声明需要时才保留在 `NativeReplay` 并按原 route 回传。
5. Responses 的 replay 保存与工具调用相关的完整有序 output items，而不是只在检测到 encrypted reasoning 时保存，确保 tool call continuation 不丢失原生 item。
6. OpenAI SDK client 显式 `max_retries=0`；请求超时继续由 `ProviderRequest.timeout_seconds` 传递。

### 4.2 Anthropic Messages adapter

新增 `tinysoul/llm/adapter/anthropic/`：

- `client.py`：构造和关闭 `AsyncAnthropic`，传入 provider endpoint 的 `api_key`、`base_url`、合并后的 headers，设置 `max_retries=0`。
- `messages.py`：实现 `AnthropicMessagesAdapter`，负责 `system`、`messages`、`tools`、`tool_choice`、`thinking`、`output_config`、`cache_control` 和 `max_tokens` 映射。
- `payloads.py`：把 TinySoul System/User/Assistant/ToolResult 映射为 Anthropic content blocks；支持 base64/URL 图片和 JSON/text tool result。
- `response_parsing.py`：解析 text、thinking、redacted thinking、tool_use、stop_reason、usage 和 cache usage。
- `replay.py`：保存并校验完整 assistant content blocks，保留 thinking/signature/redacted block/tool_use 原顺序。

请求映射：

1. 所有 SystemMessage 合并为顶层 `system`；非文本系统内容按现有 renderer 转成有限文本，不能创建多个隐式 system conversation。
2. AssistantMessage 若有同路由 `NativeReplay`，原样发送 block；若前序消息包含签名 thinking/tool-use block 却没有匹配 replay，返回 capability failure。普通文本历史可以按 TinySoul 消息投影重建。
3. ToolResultMessage 始终成为 `role=user` 的 `tool_result` block，并保留 `tool_use_id`、错误状态和原始结果顺序。
4. `thinking` 支持 adaptive/enabled/disabled/between_tools，但后端 catalog 必须表达模型可用值；`enabled` 必须有 `budget_tokens`，且不与 adaptive 混用。`between_tools` 不接受 display/budget 等其它字段，只有明确支持该模式的模型可选。Anthropic `effort` 映射到 `output_config.effort`，不转换为 budget。
5. `thinking_display` 支持 `summarized`/`omitted`；首轮不接 `updates` beta，因为它是面向流式 agent UI 的进度块，而当前 TinySoul adapter 是一次性生成接口，没有实时进度消费者。完整 blocks 和 signature 仍回放；后续若 LLM 增加流式 Observation，再单独设计 beta header 和事件投影。
6. `max_output_tokens` 映射为 `max_tokens`，文档和前端明确它包括 thinking 和可见输出。
7. 模型 `adapter_options.prompt_cache_mode` 决定 disabled/automatic/explicit 默认策略，`prompt_cache_ttl` 只接受 API 支持的 5m/1h；请求的 `breakpoint_message_index` 定位稳定边界。automatic 通过顶层 `cache_control` 使用 Anthropic 自动缓存；explicit 将 `cache_control` marker 放在指定完整 message block 边界。
8. `AnswerFormat.JSON_OBJECT` 使用当前稳定 `output_config.format` JSON Schema，传入最小 `{"type":"object"}`；不新增 schema 协议，也不使用已弃用/旧 beta `output_format`。
9. `tool_choice` 映射为 auto/any/tool，并校验 manual thinking 与强制 tool choice 的不兼容组合。

响应映射：

- text blocks 合并为 `RawResponse.answer_text`。
- thinking blocks 的可见摘要进入 `Reasoning.summary`；完整 blocks 进入 `NativeReplay`。
- tool_use blocks 转为 `ToolCallRecord`，使用 provider id 与 TinySoul tool name 映射。
- `end_turn`、`tool_use`、`max_tokens`、拒答及 context-window stop 映射到现有 `ResponseStopReason`；不能归一化的 SDK block 由 adapter 作为稳定 PARSE 失败处理。
- `usage.input_tokens/output_tokens/cache_read_input_tokens/cache_creation_input_tokens` 进入结构化 usage；不把 SDK 原始对象放入模型反馈。

### 4.3 Google GenerateContent adapter

新增 `tinysoul/llm/adapter/google/`：

- `client.py`：构造 `google.genai.Client`，配置 `HttpOptions(base_url, headers, timeout, retry_options)`，使用 `client.aio.models.generate_content`。
- `generate_content.py`：实现请求配置、工具、thinking、缓存和 response format 映射。
- `payloads.py`：把 TinySoul MessageStack 转为 `Content(role=user/model, parts=...)`。
- `response_parsing.py`：解析 Candidate、Part、FunctionCall、thought summary、thought signature、usage 和 finish reason。
- `replay.py`：保存完整 model Content/Part，并以同路由和 message fingerprint 校验 signature 回放。

请求映射：

1. SystemMessage 合并为 `system_instruction`；其它消息按 user/model Content 顺序生成 `contents`。图片 bytes 映射为 `inline_data`；任意 HTTP 图片 URL 不冒充 Google `file_uri`，若协议没有可用 bytes 或 Google 文件 URI则返回 capability failure。
2. AssistantMessage 若有同路由 NativeReplay，必须保留完整 model parts 及每个 part 的 `thought_signature`；不能把多个带 signature 的 part 合成一段文本。signature-bearing tool history 缺少匹配 replay 时失败，不重建不完整的模型消息。
3. ToolResultMessage 映射为 user Content 中的 `function_response` part，保留函数名、调用 id、响应 JSON 和顺序。
4. ToolSpec 映射为 `FunctionDeclaration(parameters_json_schema=...)`，封装在 `Tool(function_declarations=...)` 中；设置 `automatic_function_calling.disable=True`，由 TinySoul 自己执行 Action。
5. `ToolUse` 和 `ToolSelection` 映射到 `FunctionCallingConfig.mode` 与 `allowed_function_names`；不伪造 Google 没有的 parallel 关闭选项，也不让 SDK 自动执行函数。
6. `thinking_level` 和 `thinking_budget_tokens` 二选一，候选档位按 model family 配置；不得把 Gemini 2.5 的 budget 语义伪装成 Gemini 3/4 的 level。`include_thoughts` 只决定是否返回 thought summary，不等于 thought signature 是否保留。
7. `AnswerFormat.JSON_OBJECT` 映射 `response_mime_type="application/json"`；当前没有 JSON Schema consumer 时不新增无主 schema 协议。
8. 模型 `adapter_options.prompt_cache_mode` 选择 implicit/explicit；implicit 不添加请求字段，使用 API 对该模型提供的 implicit caching 并记录 `cached_content_token_count`。explicit 由 cache owner 传入 `cached_content`，不让 model TOML 保存远端资源名。调用的稳定边界由 `PromptCache.breakpoint_message_index` 给出；`prompt_cache_ttl_seconds` 用正整数秒配置，仅在 explicit 模式传给 cache create。
9. 请求 timeout 使用 `GenerateContentConfig.http_options.timeout`，单位转换为 SDK 要求的毫秒；`HttpRetryOptions(attempts=1)` 关闭 SDK 隐藏重试。

响应映射：

- candidate content 中 `part.text` 且 `thought` 为真时，进入 `Reasoning.summary`；普通 text 合并为答案。
- `part.function_call` 转为 `ToolCallRecord`，保留 id/name/args。
- model Content 的全部 parts（包括 thought、function call、thought_signature）进入 NativeReplay；signature bytes 以 JSON 安全的 base64 表达保存，重新调用时还原为 bytes。
- `STOP`、`MAX_TOKENS`、`SAFETY`、`BLOCKLIST`、`PROHIBITED_CONTENT`、`MALFORMED_FUNCTION_CALL` 等 finish reason 进入稳定 stop/failure 语义。
- `usage_metadata` 中 prompt/cache/output/thought token 数进入 RawResponse usage；provider payload 只供诊断投影，不能进入普通模型反馈。

Google AI 文档当前将 GenerateContent 页面标为 Legacy。本计划仍明确支持该 API mode；后续若切换 Interactions API，应作为新的 `ApiMode` 与 adapter 设计，不通过 SDK 或模型名称隐式改协议。

## 5. Provider client 与缓存生命周期

### 5.1 client 绑定

修改 `tinysoul/llm/adapter/factory.py`、`registry.py` 和相关 client 协议：

1. Registry 仍按 `(provider_id, api_mode)` 复用一个 client，并负责 close。
2. OpenAI 使用 `AsyncOpenAI`，Anthropic 使用 `AsyncAnthropic`，Google 使用 `google.genai.Client().aio`。
3. provider headers 先合并 shared headers 与 endpoint headers，再交给 SDK；SDK 默认认证头仍由 SDK 负责，TinySoul 不在 adapter 内重复拼 Bearer、x-api-key 或 x-goog-api-key。
4. provider 没有凭据或 endpoint 时不创建 client；模型仍可以保存，任务运行时按已有 model-chain exhaustion 处理。
5. Registry 沿现有 `AsyncResourceScope` 生命周期关闭 adapter 与所拥有的 client；adapter 借用 client，不重复 close。新增 cache store 只清空 generation 内索引，不创建独立后台回收流程。

### 5.2 Google explicit cache owner

新增轻量的 LLM adapter runtime-owned `GooglePromptCacheStore`，由对应 `ProviderRegistry` generation 持有，不属于 model、provider 配置或 Session：

```text
provider route + provider_model + prefix content + system/tool declarations + cache-affecting options
  → cachedContents resource name
```

生命周期：

1. adapter 根据 `breakpoint_message_index` 构造 API 可缓存的稳定前缀；store 以 provider route/model、前缀内容、工具声明和影响缓存兼容性的选项查找复用项。内部 digest 仅作 map key，不发送给模型或前端。
2. 没有可复用资源时调用 `client.aio.caches.create(model, CreateCachedContentConfig(..., ttl=...))`；必要时以一把 store-local lock 合并同一 generation 的并发首次创建。
3. 后续请求通过 `GenerateContentConfig(cached_content=resource_name)` 使用该资源；store 只保留 resource name 和本地过期时间，不持久化 provider 资源对象。
4. 资源过期或 provider 返回 not found 时移除索引；本次错误沿现有 provider failure/retry 流程处理，下一次调用自然创建新资源。不引入跨进程恢复或后台刷新。
5. generation close 清空索引；远端资源由 API TTL 过期，不逐项 delete，不建立额外后台生命周期。进程重启后不复用旧索引，允许旧资源自然过期。
6. Anthropic/OpenAI 不使用该 store：它们的缓存由请求 marker 和 provider TTL 管理；Google implicit cache 也不需要 TinySoul 资源 owner。

这样可以利用 Google 显式缓存，又避免把远端资源 ID 写入 TOML、运行方案或内部稳定模型 ID。

## 6. 配置、catalog 与前端

### 6.1 后端配置与 catalog

修改：

- `tinysoul/llm/config/types.py`、`sections.py`、`loader.py`：解析四种 endpoint、headers、SDK-specific endpoint fields 和 model adapter options。
- `tinysoul/llm/adapter/catalog.py`：为每个 API mode/adapter 声明 option type、choices、依赖/互斥关系、request/model 归属和 runtime availability；只增加前端确实需要表达的条件字段。
- `infra/config/catalog/models.toml`、`docs/design/llm.md`、`docs/endpoint/configuration.md`：去除“Anthropic/Google 尚未接入”的旧表述。

catalog 规则：

| 模式 | model adapter options | request override | runtime 状态 |
| --- | --- | --- | --- |
| OpenAI Chat | reasoning effort candidates + selected effort、sampling、output token field、cache mode/TTL、专用 provider options | temperature、top_p、cache key/breakpoint | 有 factory 才可运行 |
| OpenAI Responses | reasoning effort candidates + selected effort、summary、verbosity、store、cache mode/TTL | temperature、top_p、cache key/breakpoint/prewarm | 有 factory 才可运行 |
| Anthropic Messages | thinking mode、enabled budget、summarized/omitted display、effort candidates + selected effort、cache mode/TTL | max tokens、cache breakpoint、tool choice | SDK factory 可运行 |
| Google GenerateContent | thinking level candidates + selected level，或 Gemini 2.5 budget、include thoughts、cache mode/TTL、JSON output | max tokens、cache breakpoint、tool choice | SDK factory 可运行 |

思考控制保留 API 自己的名字与含义：OpenAI `reasoning_effort`、Anthropic `effort`/`thinking`、Google `thinking_level`/`thinking_budget_tokens` 不合并成一个通用“深度”字段。沿用 `ModelSpec.reasoning_effort` 作为“从该 adapter 候选列表中选出的 opaque label”，它只做候选成员校验和原值透传，不声称不同 API 的 `high` 具有相同效果；候选值列表留在 adapter options，Anthropic/Google 的专用控制仍由各自 option 表达。catalog 将候选列表提供给选中值控件，并描述 `thinking=enabled`、Google level/budget 二选一等展示条件。后端仍校验这些关系，前端不复制 API 规则。

`cached_content`、Anthropic signature、Google thought signature、OpenAI encrypted item 都不在普通 model TOML 中作为用户编辑字段。

### 6.2 Provider 页面

继续使用现有 `LlmProvidersPage` endpoint 编辑器：

- 每个 API mode 显示 base URL、key env、共享 headers 和 endpoint headers。
- Anthropic 显示 Messages endpoint 和附加 headers；不把 beta headers 用作默认功能开关。
- Google 显示 GenerateContent endpoint 及 API version/base URL 提示；不展示 Vertex IAM 等未接入认证。
- 凭据只显示环境变量名和就绪状态，不显示密钥值。

### 6.3 Model 页面

继续使用 `LlmModelsPage` 和后端 catalog 驱动表单：

- 选择 adapter 后只显示该 API mode 和专用 adapter 的有效选项。
- Anthropic 根据 `thinking` mode 显示合法的 budget、effort 和 display 控件；按模型候选值隐藏不支持的组合；显示缓存策略与 TTL。
- Google 根据配置的 model generation family 显示 thinking level 或 budget 其中一组，并显示 thought summary 和缓存策略；不显示远端 cached content ID。
- OpenAI 显示 breakpoint/key/prewarm 仅在实际 API mode 与 model capability 支持时出现；cache mode/TTL 留在模型选项。
- 所有模式的 effort/level 控件使用“允许候选列表 + 当前选定值”模式；更换候选列表时校验/清理已选值，符合 catalog 的互斥和依赖约束。
- family、collapsed、搜索和不可运行筛选继续复用 ModelPicker；列表增加 API mode badge 和 runtime reason。
- 配置页可以保存未配置凭据的模型，但正常运行列表只默认展示有 factory、endpoint 和启用状态的路由。

### 6.4 Trace 与观察

修改 `visualization/src/features/trace/ModelCallPanel.tsx` 及其 types/decoder：

- 显示 API mode、adapter、model、safe reasoning summary、stop reason 和归一化 token/cache usage。
- NativeReplay 只显示“可回放/来源”，不显示 signature、encrypted item、thought signature 或原始 provider payload。
- Anthropic `display=omitted` 和 Google `include_thoughts=false` 时仍可显示“已保留原生回放状态”，不误报为没有推理。

### 6.5 预计文件范围

| 所属层 | 主要位置 | 改动职责 |
| --- | --- | --- |
| LLM protocol | `tinysoul/llm/protocol/`、`tinysoul/llm/protocol/reasoning.py`、`cache.py`、`responses.py` | `NativeReplay`/`Reasoning`、`PromptCache`、typed usage 和响应投影 |
| LLM adapter | `tinysoul/llm/adapter/factory.py`、`registry.py`、`catalog.py`、`openai/`、新增 `anthropic/`、`google/` | SDK client 组装、四 mode mapper/parser、错误分类、cache owner |
| LLM config/runtime | `tinysoul/llm/config/`、`tinysoul/llm/execution/`、`tinysoul/llm/runtime_bridge.py` | TOML 校验、runtime availability、TaskRunner retry 和安全失败映射 |
| Kernel/observation | `tinysoul/kernel/context/signals.py`、LLM trace/projection、`visualization/src/features/trace/` | replay/status/usage 的有界传播和展示 |
| Settings UI | `visualization/src/features/settings/models/`、`visualization/src/features/settings/draft/catalog.ts`、`visualization/src/features/settings/i18n/` | endpoint、模型 adapter options、候选档位/选中值和条件表单 |
| Config/docs | `tinysoul/infra/config/catalog/models.toml`、`docs/design/llm.md`、`docs/endpoint/configuration.md`、`reference/api_mode/` | 配置项描述、当前设计正典和 SDK/API mode 调研记录 |
| Tests | `tests/llm/`、`tests/kernel/context/`、`visualization/src/features/settings/`、trace tests | 协议、SDK transport、route replay、错误、设置表单和观察投影契约 |

实现时以实际 owner 文件为准；若某一职责已有清晰归属，则修改现有模块，不额外复制 parser、registry 或 catalog。

## 7. 失败与控制流

新增或统一 provider error bridge：

- Anthropic SDK 的 401/403 → AUTH；408/409/429/5xx → TRANSIENT；400 context window → CONTEXT_LIMIT；其它 400 → CONFIG；响应 block 无法解释 → PARSE。
- Google `google.genai.errors.APIError` 按 status code 和错误内容映射同一组稳定 `ProviderErrorKind`；safety/blocked response 映射现有 `ResponseStopReason.CONTENT_FILTER` 或稳定 task failure，不把 SDK 原文直接反馈模型。
- 显式缓存创建/使用失败是当前 provider call 的 provider error，由任务层重试或切换 provider；过期索引清理不掩盖已提交响应，不建立独立 cache error state machine。
- SDK 关闭、请求取消和超时沿现有 LLM/Action 生命周期传播；adapter 不创建后台任务、不吞取消、不自带重试。
- 所有跨模块错误继续在 `llm/runtime_bridge.py` 映射为少量 Runtime 原因；原始 SDK 异常只保留在调试链，不进入 JSON payload。

## 8. 分阶段实施

### 阶段 A：清理正典与协议 — `planned`

1. 修订 `reference` 研究记录或迁移到可跟踪文档，记录四类 API 的最新字段和官方链接。
2. 重构 `Reasoning`/`NativeReplay`，引入 `NativeReplayKind` 和 `ordered_items`；把专用 Chat reasoning payload 移出通用 `Reasoning.content`。
3. 让模型 adapter options 拥有 API-specific cache mode/TTL；简化 `PromptCache` 为 key、稳定消息边界和 Responses prewarm，删除 Google `cached_content` TOML 字段。
4. 用小型 frozen `TokenUsage` 替代任意 usage 字典，并同步 RawResponse、Context、Observation 和 UI projection。
5. 不增加通用 parallel tool protocol；如现有真实模型需要，分别通过 OpenAI/Anthropic adapter options 表达。
6. 先更新 protocol/config/catalog 单测，再继续 adapter，避免 provider JSON 反向决定内部协议。

验收：四种 API 的选项和互斥约束可以由 typed protocol 表达；没有 raw SDK 字段进入 Kernel；所有现有 OpenAI replay 测试迁移到新字段。

### 阶段 B：OpenAI adapter 对齐 — `planned`

1. Chat/Responses 完成 breakpoint 生成、explicit/implicit cache 和 usage 映射。
2. Responses 完整保存工具相关 output items；Chat 专用 reasoning content 与通用 reasoning summary 分离。
3. 保持 SDK retry=0、TaskRunner retry 单一 owner。

验收：MockTransport 覆盖 Chat/Responses 的 explicit breakpoint、工具历史和 native replay；不发送 deprecated retention。

### 阶段 C：Anthropic Messages runtime — `planned`

1. 增加 Anthropic client、factory、registry resource 和 adapter。
2. 实现消息/图片/工具/thinking/effort/cache payload mapper。
3. 实现 block response parser、typed usage、stop reason、签名 block replay；签名历史缺少匹配 replay 时返回 capability failure。
4. 增加 Anthropic SDK MockTransport 测试，不使用真实 key。

验收：一次普通文本、一次 thinking 摘要、一次 tool_use/tool_result、一次 omitted signature replay 和一次 cache breakpoint 请求均能得到 TinySoul RawResponse。

### 阶段 D：Google GenerateContent runtime — `planned`

1. 增加 Google client、factory、registry resource 和 adapter；关闭 automatic function calling 和 SDK retry。
2. 实现 Content/Part、图片、FunctionDeclaration、FunctionCall/FunctionResponse、thinkingConfig 和 JSON output 映射。
3. 实现 thought summary、thought signature 的完整回放及错误校验。
4. 实现 implicit cache usage 与 `GooglePromptCacheStore` 的 explicit cache create/use/expiry；远端资源由 TTL 回收。
5. 使用 SDK mock transport 或 fake async client 验证真实 SDK 类型序列化，不发送真实网络请求。

验收：普通文本、图片、工具调用、多轮 signature 回放、explicit cache 复用和过期重建均有代表性测试。

### 阶段 E：配置与前端 — `planned`

1. 更新 config parser、catalog、endpoint projection 和 model mutation。
2. 更新 Provider 页面四类 endpoint 编辑和 headers 提示。
3. 更新 Model 页面按 adapter 显示 thinking/cache/tool options；移除 cached content ID 输入。
4. 更新 ModelPicker、任务链模型选择和运行状态 badge。
5. 更新 Trace/Observation 投影和文档。

验收：前端可以通过 TOML mutation 新增 Anthropic/Google provider、family 和 model；四种 API mode 的 options 都从后端 catalog 来，不在前端复制规则。

### 阶段 F：失败、文档和门禁 — `planned`

1. 更新 `docs/design/llm.md`、`docs/design/infra.md`、`docs/endpoint/configuration.md`、README 和配置示例。
2. 更新模块 failure、runtime bridge 和错误 observation 测试。
3. 运行 LLM adapter/config/execution、agent composition、前端 settings、全量 Python、typecheck、TypeScript 和 Vite 构建。
4. 只有实现、文档和验证全部完成后，才将本计划改名为 `-done-` 移入 `docs/analysis/done/`。

## 9. 测试矩阵与验收标准

### 后端

- 四 API mode 的 catalog、模型选项互斥、provider endpoint 和 runtime availability。
- Anthropic request body：system/messages/tool/thinking/cache/headers/max_tokens。
- Anthropic response：text/thinking/redacted thinking/tool_use/usage/stop reason/signature replay。
- Google request body：systemInstruction/contents/tools/toolConfig/thinkingConfig/cachedContent/timeout。
- Google response：thought summary/functionCall/thoughtSignature/usage/finish reason。
- OpenAI Chat/Responses explicit breakpoint、prewarm、reasoning replay 和 deprecated 字段拒绝。
- provider error classification、SDK retry=0、TaskRunner retry、取消和 close。
- Google cache store 的兼容 key、TTL、create/reuse/expiry；不把远端资源名保存到 TOML，也不建立持久化索引或后台回收器。

### 前端

- adapter 切换后只显示对应 API mode options。
- Anthropic thinking mode 与 budget/effort 互斥。
- Google thinking level 与 budget 互斥、include thoughts 和 cache policy。
- provider endpoint、headers、model binding、family TOML 新建/追加。
- ModelPicker 的 family/search/collapsed/runtime availability 和任务链单模型替换。
- trace 中安全 summary/cache usage/native replay 状态，不显示原始 signature。

### 完成条件

1. 四种 API mode 都能在本地 SDK mock 下完成真实 request serialization 和 response parsing。
2. Anthropic/Google 的真实 SDK client 能由 Registry 创建、复用和关闭；没有 SDK 隐藏重试。
3. 工具调用的 provider-native 状态可以在同一路由中完整回放；要求签名的历史缺失或 route/model/content 不匹配时，adapter 返回 capability failure，不伪造 native continuation。
4. Google explicit cache 由 runtime owner 管理，配置和运行方案只保存 cache policy，不保存远端资源 ID。
5. 配置、前端 catalog、adapter mapper、错误 bridge、文档和测试对同一 API mode 使用同一术语。
6. Full/typecheck/frontend build 和 `git diff --check` 通过；全仓 `ruff` 不再报告 `builder.py` 的 import 排序问题。

## 10. 设计决定与边界

1. 本轮包含 Google explicit cache，因为它与 GenerateContent 的缓存资源生命周期直接相关；实现限于 generation 内索引 + TTL，不持久化远端 ID、不要求删除/刷新后台任务。若真实使用中 explicit cache 的模型/前缀条件不满足，adapter 通过现有 provider failure 反馈，不引入预检流程。
2. Anthropic `display=updates` 暂缓：它需要 beta header 且当前是 agent UI 的进度事件，不只是最终答案 reasoning summary。TinySoul 当前 adapter 为非流式调用，因此首轮提供 `summarized`/`omitted` 和完整签名回放；不把 beta progress block 错投影为普通 reasoning。
3. Google GenerateContent 当前官方文档标记为 Legacy，但用户本轮明确选定它。后续换 Interactions API 必须新增独立 API mode，不改变本轮模式定义。
4. 不改变运行方案语义、model stable ID、family TOML 组织、LLM retry owner 或 ModelPicker 主线。
