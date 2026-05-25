# LLM Task

LLM Task（unified LLM call infrastructure for Query Loop and Actions）

`llm/tasks/` 是 TinySoul 中所有 LLM 调用的统一通道。无论是 Query Loop 的三步任务，还是 Workspace Action 的内部内容生成，都必须通过 `AITask` 发起调用。

## Design_Principles

（1）统一入口
- 系统中不存在直接调用 LLM provider 的代码（除 `AIClient.chat` 外）
- 所有 prompt 构造、执行、响应解析都收敛到 `AITask`
- 便于统一添加调试日志（`debug_prompt` 事件）、错误处理、重试与故障转移机制

（2）Prompt 与 Execution 分离
- `LLMPrompt` 是纯数据对象，描述 prompt 的五元素结构，支持可选的 `attachments`（多模态附件）
- `PromptBuilder` 负责组装 `LLMPrompt`，自动从 `ContextProvider` 注入共享运行时上下文
- `AITask` 持有 `LLMPrompt` + `Interpreter`，负责执行和解析
- 三者可独立测试和替换

（3）统一结果封装
- `AITask.run()` 返回 `TaskResult`，包含：
  - `data`: `Interpreter` 解析后的 JSON dict
  - `response`: 原始 `AIResponse`（含 content、reasoning_content、usage、model 等元数据）
- 调用方可选择消费结构化数据，也可访问底层模型元数据

（4）ContextProvider 驱动
- `PromptBuilder` 依赖 `ContextProvider` 协议，自动注入共享运行时上下文
- 每个具体 task 只需提供 task_guide、input_spec、output_constraint 和可选 examples

## Five_Element_Prompt_Structure

所有发给 LLM 的 prompt 由五个元素构成，可选附加第六个元素（多模态附件）：

```
=== TASK GUIDE ===
{what the model should do}

=== CONTEXT ===
{user_query, loop_target, current_state, workspace, current_turn}

=== INPUT ===
{task-specific data description}
{task-specific data JSON}

=== OUTPUT CONSTRAINT ===
{expected format, schema, rules}

=== EXAMPLES ===
{few-shot demonstrations}
```

（1）Task Guide：描述当前任务的目标（choose action / take action / update state / write file / edit file）
（2）Context：共享运行时上下文，由 `PromptBuilder` 自动从 `ContextProvider` 注入
（3）Input Spec：任务专属输入数据，由每个 task 或 action 自行构造
（4）Output Constraint：严格的输出格式要求（JSON schema / field rules）
（5）Examples：少数示例，帮助 LLM 理解输入输出映射关系
（6）Attachments（可选）：多模态附件（图片、文件），由 `AITask` 自动转换为 OpenAI-compatible 的 `image_url` content parts

## Core_Components

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

自动将 `ContextProvider` 中的共享运行时上下文注入 CONTEXT 部分。默认注入全部字段：
- `user_query`
- `loop_target`
- `current_state`
- `workspace`
- `current_turn`

**上下文字段选择（`include_context`）**

通过 `include_context` 参数，调用者可以显式指定需要哪些上下文字段，避免向 LLM 暴露不必要的信息、减少 token 消耗：

- 支持顶层字段选择：`["user_query", "current_turn", "current_state"]`
- 支持嵌套字段选择：`["current_state.todo_list", "current_state.milestone_list"]`
- 当父字段（如 `"current_state"`）与子字段（如 `"current_state.todo_list"`）同时出现时，父字段优先，返回完整对象
- 当传入空列表 `[]` 时，context 部分为空（仅保留 extra_context）

使用示例：
```python
# Step 3: 状态更新不需要 workspace 上下文
builder.build(
    task_guide=UPDATE_STATE_TASK_GUIDE,
    input_spec=...,
    output_constraint=...,
    include_context=["user_query", "loop_target", "current_turn", "current_state"],
)

# 仅暴露 current_state 中的 todo 和 milestone
builder.build(
    task_guide=...,
    input_spec=...,
    output_constraint=...,
    include_context=["user_query", "current_state.todo_list", "current_state.milestone_list"],
)
```

### LLMPrompt

五元素 prompt 的数据载体，支持多模态附件：

```python
@dataclass
class LLMPrompt:
    task_guide: str
    context: dict
    input_spec: InputSpec
    output_constraint: OutputConstraint
    examples: list[Example] = field(default_factory=list)
    attachments: list[Attachment] = field(default_factory=list)
```

提供 `serialize()` 方法生成最终字符串。`attachments` 不进入序列化文本，由 `AITask` 在构建 messages 时独立转换为 multimodal content parts。

### AITask

自包含的 AI 任务单元：

```python
class AITask:
    def __init__(
        self,
        prompt: LLMPrompt | None = None,
        interpreter: Interpreter | None = None,
        client: Any | None = None,
        logger: EventLogger | None = None,
    ):
        ...

    def run(self, system: list[dict[str, str]] | None = None) -> TaskResult:
        ...
```

执行流程：
1. 序列化 `LLMPrompt` 为 user prompt 字符串
2. 如有 `attachments`，将其转换为 OpenAI-compatible multimodal content parts
3. 通过 `EventLogger` 发射 `debug_prompt` 事件（供调试使用）
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

### TaskResult

```python
@dataclass
class TaskResult:
    data: dict           # Interpreter 解析后的结构化数据
    response: AIResponse # 原始响应（含 reasoning_content、usage、model 等）
```

### Attachment & ContentBuilder

`Attachment` 支持三种构造方式：
- `Attachment.from_image_file(path)`：从本地图片文件读取并 base64 编码
- `Attachment.from_image_base64(data, mime_type)`：从 base64 字符串构造
- `Attachment.from_image_url(url)`：从远程 URL 构造（部分 provider 不支持）

`ContentBuilder` 提供静态方法直接生成 OpenAI-compatible content parts：`text()`、`image_url()`、`image_base64()`、`image_file()`。

## Integration_with_Action

Workspace Action（如 `create_markdown_file`, `edit_markdown_file`, `read_markdown_file`）是 `AITask` 的重度使用者。

`OneStepAIExecutor` 的模板方法：

```
receive action_input (dict)
    ↓
build prompt via PromptBuilder + custom _build_*_prompt function
    ↓
AITask.run(system=self._system_prompt)
    ↓
interpreter parses LLM response as JSON object
    ↓
apply result via custom _apply_*_result function
    ↓
return {"result": str}
```

该设计让 Workspace Action 只需提供两个函数：
- `build_prompt(builder, params, workspace) -> LLMPrompt`：如何构造 prompt
- `apply_result(params, generated, workspace, context_provider) -> str`：如何处理 LLM 输出

其余流程（LLM 调用、错误处理、响应解析、重试、故障转移）全部由 `OneStepAIExecutor` 和 `AITask` 统一处理。

## LLM_Provider

`llm/provider/` 提供 provider 适配与多模型池管理：

- `AIClient`：多模型池管理器，支持 chat / embedding / image_gen 三类任务，内置逐模型重试与跨模型故障转移
- `AIRequest` / `AIResponse`：统一中间表示，所有 adapter 输入输出均收敛到此格式
- `ModelConfig`：单个模型配置（provider、model、model_type、capabilities、temperature、max_tokens、enable_thinking 等）
- `ChatAdapter` / `EmbeddingAdapter` / `ImageGenAdapter`：抽象基类，基于 OpenAI SDK 实现 provider-specific 覆盖
- 适配器注册表：`register_adapter(provider, model_type)` 装饰器自动注册，无需手动维护映射字典

### 多模型池与故障转移

`AIClient` 内部维护三个模型池：
- `_chat_pool`：按 `provider_chain` 优先级排序的 chat 模型列表
- `_embed_pool`：embedding 模型列表
- `_image_gen_pool`：图像生成模型列表

调用流程：
1. 对当前模型执行最多 `max_retries` 次重试，指数退避（`base_retry_delay × 2^attempt`）
2. 若当前模型全部重试失败，自动故障转移到池中的下一模型
3. 若所有模型耗尽，抛出 `SystemExhaustedError`

异常映射（OpenAI SDK → TinySoul）：
- `APIConnectionError` / `APITimeoutError` / `RateLimitError` / `InternalServerError` → `LLMTransientError`（触发重试/故障转移）
- `AuthenticationError` → `ConfigError`（致命错误，直接 ABORT）

### 当前支持的 Provider

| Provider | Chat | Embedding | Image Gen | 环境变量 |
|----------|------|-----------|-----------|----------|
| zhipu    | ✅   | ✅        | ✅        | GLM_API_KEY, ZHIPU_API_KEY |
| kimi     | ✅   | ✅        | ✅        | KIMI_API_KEY, MOONSHOT_API_KEY |
| deepseek | ✅   | ✅        | —         | DEEPSEEK_API_KEY |
| minimax  | ✅   | ✅        | —         | MINIMAX_API_KEY |

新增 provider 时，只需继承 `OpenAIChatAdapter` / `OpenAIEmbeddingAdapter` / `OpenAIImageGenAdapter`，覆盖 `DEFAULT_BASE_URL` 和 `ENV_KEY_NAMES`，并通过 `@register_adapter(provider, model_type)` 装饰器注册即可。

（detail: llm_provider.md）
