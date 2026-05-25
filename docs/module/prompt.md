# Prompt 模块

## 定位

Prompt 模块负责管理系统提示词来源和组装顺序。它回答“模型应该遵守哪些全局规则”和“动作执行时应继承哪些上下文约束”。

需要区分两类 prompt 能力：

- `tinysoul/prompt/`：system message 资源、外部文件引用和组装函数。
- `tinysoul/llm/tasks/prompt.py`：运行时 `PromptBuilder`，负责把 ContextProvider 转成 LLM 消息。

本文档主要描述前者，并说明它与 PromptBuilder 的边界。

## Prompt Source

Prompt Source 有三种：

- `InlinePromptSource`：直接内联文本。
- `FilePromptRef`：从工作区或 home 目录文件读取。
- `BuiltinPromptRef`：读取包内内置 markdown 资源。

所有 source 最终都会解析成 system message 文本。解析失败应显式暴露，不应静默替换成空提示。

## Loop system

Loop system 由 `build_loop_system()` 构建。默认顺序是：

1. 外部传入的 system sources。
2. 内置 `query_loop.system.md`。

`home_loop_system_sources(home_root)` 会根据 home 目录下的约定文件生成可选 `FilePromptRef`。它只发现 source，不负责拼接文本；最终组装仍集中在 `build_loop_system()`。

Loop 初始化时会先构建 loop-level system messages，再放入 `QueryContext`。后续 Step Task 和 LLM Action 都可以复用该 system。

## Loop guide

Loop 还内置三类 guide：

- `choose_action.guide.md`
- `generate_parameters.guide.md`
- `update_state.guide.md`

这些 guide 不是全局 system identity，而是各 Step Task 的任务说明。它们与运行时上下文一起交给 PromptBuilder 形成具体 LLM 请求。

## Action system

LLM 型动作通过 `build_llm_action_system(context_provider, action_system)` 构建系统消息。顺序是：

1. `context_provider.get_loop_level_system()`
2. 内置 `action_execution_context.system.md`
3. action-specific system

这样动作执行会继承 Loop 的身份、边界和用户约束，同时再叠加动作自己的指令。

默认 one-step LLM action 使用 `one_step_default.system.md`。动态脚本注册使用 `register_script.system.md` 辅助生成动作元数据。

## 与 PromptBuilder 的边界

Prompt 模块只提供 system/guide 文本。运行时消息由 `PromptBuilder` 完成：

- 读取 `ContextProvider`。
- 注入 query events、current state、workspace 等上下文字段。
- 生成 user message。
- 附加 attachments。
- 交给 `AITask` 调用模型。

因此，system source 不应直接访问 QueryState，也不应包含运行时拼接逻辑。

## 扩展方式

扩展 Prompt 时优先选择：

- 新增内置 markdown 资源。
- 增加新的 Prompt Source。
- 在 Loop 初始化时传入外部 system sources。
- 为新 Action 提供 action-specific system。

不建议在 Handler 内手写完整系统提示词。动作应复用 `build_llm_action_system()`，确保全局约束一致。

## 当前边界

- Prompt Source 只负责文本来源，不负责变量模板渲染。
- 内置 markdown 是包资源，路径应通过 resource helper 读取。
- 外部 home prompt 的发现和最终组装是分离的。
- PromptBuilder 的 `include_context` 支持字段筛选，但当前默认 Loop step 使用标准上下文。
- Prompt 模块不处理模型响应，解析属于 LLM Task/Interpreter。

## 设计不变式

- loop-level system 必须集中构建，并被上下文持有。
- action system 必须继承 loop-level system。
- guide 是任务说明，不替代全局 system。
- Prompt Source 只声明来源，组装顺序由 system builder 决定。
- Handler 不应绕过统一 system 组装路径。
