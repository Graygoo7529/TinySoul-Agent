# LLM 模块

## 定位

LLM 模块负责把 TinySoul 内部的任务请求转换为供应商调用，并把模型响应还原成结构化结果。它覆盖三层：

- Provider：模型供应商配置、适配器、重试和 failover。
- Task：面向 Loop/Action 的 LLM 子任务封装。
- Prompt：运行态上下文到模型消息的构建。

LLM 模块不决定 Loop 控制流，也不直接写状态。解析失败、供应商错误和系统耗尽会以异常形式交给 Trap。

## Provider 层

### `AIClient`

`AIClient` 是模型调用入口，支持：

- chat
- embedding
- image generation

初始化时会从配置中建立不同模型类型的 pool。chat 还按 profile 建立动态池，可按 required/preferred capabilities、provider 和 model override 选择模型。

调用策略：

1. 从当前 profile 的轮转索引开始。
2. 对当前模型执行有限重试。
3. 当前模型失败后，按池顺序 failover 到后续模型。
4. 所有候选失败后抛出 `SystemExhaustedError`。

鉴权和配置类错误会映射为 `ConfigError`，瞬时供应商错误会映射为 `LLMTransientError`。

### 配置解析

Provider 配置来自环境变量和默认模型规格。解析流程会：

- 读取供应商 key、base url、model。
- 应用默认 capabilities。
- 生成 chat/embedding/image_gen 的 `ModelConfig`。
- 过滤缺少必要凭据的配置。

`.env` 会在 settings 初始化时加载，但系统环境变量优先。

### 当前适配器

当前代码中已注册的适配器：

| Provider | Chat | Embedding | Image generation |
| --- | --- | --- | --- |
| Zhipu | yes | yes | yes |
| Kimi | yes | yes | yes |
| DeepSeek | yes | yes | no |
| MiniMax | yes | yes | no |

默认配置中保留了部分 image_gen 模型规格，但只有注册了 image_gen adapter 的 provider 才能实际执行图像生成。

## Task 层

### `AITask`

`AITask` 是 Loop 和 Action 使用 LLM 的统一封装。它由三部分组成：

- task name
- prompt builder
- response interpreter

`run(profile=..., system=None, config=None)` 会构建消息、调用 `AIClient.chat()`，并返回 `TaskResult(data, response)`。

当前调用始终使用 OpenAI 兼容的 message content list，即使只有文本，也会包装为 text part。这样 text、image、file 等多模态输入可以走同一条消息结构。

### Loop tasks

Loop 主要使用三类任务：

- choose action：选择下一批动作。
- generate parameters：为动作生成参数。
- update state：根据 action records 更新状态。

这些任务共享 PromptBuilder 和 JSON interpreter，但各自使用不同 guide/system prompt。

### Action tasks

LLM 型动作通过 action executor 使用 `build_llm_action_system()` 组装系统消息。动作系统消息由三部分构成：

1. loop-level system
2. action execution context
3. action-specific system

这样动作可以继承当前 Loop 的身份和约束，同时拥有自己的执行说明。

## Prompt 构建

### `PromptBuilder`

`PromptBuilder` 将上下文对象转换为模型消息。默认上下文字段包括：

- `query_events`
- `loop_target`
- `current_turn`
- `current_state`
- `workspace`

`include_context` 支持选择顶层字段或嵌套字段。当前 Loop step task 使用默认上下文；该能力主要用于扩展任务或动作侧 prompt。

### Message 形态

PromptBuilder 输出 `LLMPrompt`，其中包含：

- system messages
- user message
- optional attachments
- metadata

Provider adapter 再把它转换成供应商兼容请求。

## 响应解析

`ResponseInterpreter` 负责把模型文本解析为结构化对象。JSON 解析策略按顺序尝试：

1. 显式 ```json fenced block。
2. 第一个顶层 `{...}` JSON 对象。
3. 通用 fenced block 或整段文本。

解析结果必须是 JSON object。非对象、空响应或非法 JSON 会抛出 `LLMResponseParseError`。

该约束让 Loop step 始终处理结构化数据，而不是从自然语言中猜测动作或状态。

## 与错误系统的关系

LLM 层只做调用、重试和解析：

- 单模型瞬时失败先在 client 内重试。
- 多模型失败进入 failover。
- 池耗尽抛出 `SystemExhaustedError`。
- 解析失败抛出 `LLMResponseParseError`。

这些异常交给 Trap 决定是否反馈给下一轮模型或中止 Loop。

## 当前边界

- Chat profile 池是运行时过滤出来的；没有匹配模型时会快速失败。
- MiniMax 当前没有 image generation adapter。
- JSON interpreter 不接受数组作为顶层结果。
- 模型输出的业务字段校验由各 Step 或 Action 继续完成。
- LLM 模块不保存会话长期记忆；上下文来自 QueryContext 和 PromptBuilder。

## 设计不变式

- Loop 和 Action 只依赖 `AIClient`/`AITask`，不直接依赖供应商 SDK。
- 模型响应进入业务逻辑前必须结构化解析。
- Provider failover 对调用方透明，但耗尽必须显式暴露。
- Prompt 构建只读取上下文，不修改状态。
- system message 由 Prompt 模块集中组装，避免散落在动作实现中。
