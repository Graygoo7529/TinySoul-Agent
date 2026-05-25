# TypedDict 与结构化边界

## 背景

项目中存在大量 JSON-like 数据。它们来自 LLM 输出、provider messages、action input/result、signal payload、state/workspace view。完全静态化这些数据不现实，但关键跨模块边界需要更明确，避免字段约定只存在于调用方脑中。

## 当前现状

- `LoopOutcome`、`ActionSpec`、`TrapResult`、`Signal`、`AIRequest`、`AIResponse` 已经是 dataclass。
- Action metadata 会解析成结构化对象。
- Step 输出、signal payload、provider content part、current state view 等仍主要是 `dict[str, Any]`。
- `ActionHandler` 抽象接口没有声明 `resolve_run_config()`，但运行路径实际依赖它。

## 问题

### 1. 字段约定分散

例如 signal payload 中的 `target`、`result`、`error`、`error_type`，provider message content 中的 `type`、`text`、`image_url`，这些字段在多个模块间传递，但缺少统一类型定义。

### 2. Step 输出缺少明确结构

Step1、Step2、Step3 的 LLM 输出都要求 JSON object，但内部字段结构主要靠 prompt、normalizer 和测试维护。

### 3. 扩展方容易踩隐式接口

自定义 action handler 如果只实现 `ActionHandler` 抽象方法，可能因为缺少 `resolve_run_config()` 在 `QueryAction` 执行时失败。

## 建议

- 对稳定、高频、跨模块的数据结构引入 `TypedDict`。
- 对运行时行为接口用 Protocol 或抽象方法表达。
- 不把 action-specific 任意参数强行静态化。
- 先覆盖 Loop/Trap/LLM provider message 三类边界。

## 实施方案

### 阶段 1：定义核心 TypedDict

候选：

- `ActionCompletedPayload`
- `ActionFailedPayload`
- `OngoingPayload`
- `ProviderTextPart`
- `ProviderImagePart`
- `Step1Output`
- `Step3UpdateOutput`
- `CurrentStateView`
- `WorkspaceView`

放置位置建议靠近使用模块，例如 `tinysoul/trap/types.py`、`tinysoul/llm/tasks/types.py`。

### 阶段 2：修正 ActionHandler 协议

选择一种方式：

- `ActionHandler` 增加 `resolve_run_config()` 抽象方法。
- 或新增 `RunnableActionHandler` Protocol。
- 或 registry 注册时检测 handler 能力。

优先保证错误在注册/初始化阶段暴露。

### 阶段 3：逐步替换关键签名

先替换内部 helper 和 payload 构造函数，不急着改所有 handler 的 `dict` 入参。

重点替换：

- Dispatcher event/payload。
- Trap route payload。
- AITask message content parts。
- Step update normalized output。

### 阶段 4：补测试

测试目标：

- payload 字段变更会被测试捕获。
- provider multimodal content part 类型正确。
- 自定义 handler 缺少运行接口时有明确错误。

## 验收标准

- 至少 Loop/Trap/LLM 三个跨模块边界有明确类型定义。
- `ActionHandler` 的抽象接口与 `QueryAction` 实际调用一致。
- 类型改造不影响 LLM 输出仍为 JSON object 的设计。
- 相关测试能捕获字段名漂移。

## 设计原则

- 类型用于约束边界，不用于压死所有动态扩展。
- 稳定结构优先 typed，action-specific payload 保持灵活。
- Protocol 用于行为能力，TypedDict 用于 JSON-like 数据形态。
