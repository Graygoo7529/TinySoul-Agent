# 代码风格与类型边界分析

## 背景

本分析基于当前源码、私有核心设计草案和 `docs/module/*`。目标不是追求形式化类型覆盖所有动态数据，而是找出当前项目中最容易产生文档漂移、运行期错误或扩展成本的代码边界。

TinySoul 的核心链路有大量 JSON-like 数据：LLM 输出、action input、action result、signal payload、provider messages、workspace/state view。完全消除 `dict` 不现实，但关键跨模块边界应更明确。

## 当前现状

- 关键运行对象已经使用 dataclass，例如 `LoopOutcome`、`ActionSpec`、`TrapResult`、`Signal`、`AIRequest`、`AIResponse`。
- Action metadata 已解析为结构化对象，注册时也会做 metadata 校验。
- Loop/Trap/Action 的主流程边界清晰，状态写入集中在 Trap/InterruptHandler。
- 仍有较多跨模块数据使用 `dict[str, Any]`，字段约定散落在调用方和测试中。
- `PromptBuilder.include_context` 已实现，但 Step1/2/3 当前使用默认完整上下文。
- `ActionHandler` 抽象接口没有声明 `resolve_run_config()`，但 `QueryAction` 会直接调用该方法；内置 `ActionBase` 没问题，自定义非 `ActionBase` handler 存在运行期风险。

## 已修复的旧问题

- provider adapter 已经把 `request.system` 拼入真实 chat 请求，system prompt 不再丢失。
- `ActionRegistry.with_allowlist()` 已经继承原 registry 的环境能力对象。
- action record 的 `action_target` 已经可以从 signal payload 中写入，不再只依赖 action result。
- README 中旧的 `docs/core/core_design_query.md`、`basic_system`、`prompts.py` 等引用已不在当前主文档索引中出现。

## 当前问题

### 1. JSON-like 边界缺少统一类型约定

多个模块依赖隐式字段：

- Step1/2/3 的 LLM 输出。
- `Signal.payload`。
- `TrapResult.action_result`。
- provider message content parts。
- `current_state` 和 `workspace` 的模型视图。

这些数据需要保持 JSON 兼容，但仍应在内部用 `TypedDict`、Protocol 或轻量 dataclass 标注约定。

### 2. Handler 抽象接口与实际调用不完全一致

`ActionHandler` 只声明 `execute()`、`get_meta()`、`get_detail()`，但 `QueryAction` 还依赖 `resolve_run_config()`。当前内置动作都继承 `ActionBase`，所以主路径没有问题；但 registry 允许注册任意 factory，扩展方可能实现了 `ActionHandler` 却在运行时失败。

### 3. Prompt context 裁剪能力没有接入 Step 任务

`PromptBuilder` 支持 `include_context`，但 Step1/2/3 仍注入默认完整上下文。随着 action record、workspace resources 和 todo 增长，token 成本会增加，模型也会接收与当前步骤无关的信息。

### 4. Action input 校验仍是轻量级

`validate_action_input()` 当前只检查 payload 是对象，以及 required 字段存在。类型、enum、范围和嵌套结构没有完整执行 JSON Schema 校验。当前动作多由 LLM 生成参数，错误会进入 Trap，但错误会更晚暴露。

## 建议

- 对跨模块 JSON-like 边界引入 `TypedDict` 或等价结构，优先覆盖高频、稳定字段。
- 将 `resolve_run_config()` 纳入 `ActionHandler` 抽象，或把 `QueryAction` 的依赖收窄到 `ActionBase`/新 Protocol。
- 给 Step1/2/3 显式配置 `include_context`，并用测试锁定每个 Step 需要的上下文字段。
- 对 action input 引入分层校验：required 字段仍快速校验，复杂 schema 可逐步启用。
- 保留外部 LLM/API 边界的动态性，不把所有 action-specific input 强行静态类型化。

## 实施方案

### 阶段 1：整理类型边界

候选类型：

- `Step1Output`
- `Step2Parameters`
- `Step3StateUpdate`
- `ActionResultPayload`
- `SignalPayload`
- `ProviderMessage`
- `MessageContentPart`
- `CurrentStateView`
- `WorkspaceView`

先从 Loop、Trap、LLM 三个边界做，不一次性覆盖所有 handler。

### 阶段 2：修正 Handler 协议

选择一种方式：

- 在 `ActionHandler` 抽象类上声明 `resolve_run_config()`。
- 或新增 `RunnableActionHandler` Protocol，让 `QueryAction` 依赖该 Protocol。
- 或在 registry 注册时校验 handler 是否具备运行所需方法。

同时补充自定义 handler 的失败测试。

### 阶段 3：接入 Step context 裁剪

为 Step 配置默认字段：

- Step1：query events、loop target、todo、milestone、workspace 摘要、available actions。
- Step2：selected action detail、query events、workspace 相关资源、必要 state。
- Step3：未读 action records、feedback errors、todo、milestone。

避免把完整 workspace 和完整历史无差别注入每一步。

### 阶段 4：增强输入校验

先对内置动作启用更完整校验：

- 类型。
- enum。
- required。
- 简单范围。
- unknown fields 策略。

动态脚本动作可以先保持较宽松，只校验注册元数据和必填字段。

## 验收标准

- 关键 JSON-like 边界有类型定义或明确 Protocol。
- 自定义非 `ActionBase` handler 的错误能在注册或执行前明确暴露。
- Step1/2/3 的 prompt context 字段由测试覆盖。
- 内置动作的错误参数能更早给出结构化 `ActionInputError`。
- 类型改造不破坏 LLM 输出仍以 JSON object 进入系统的设计。
