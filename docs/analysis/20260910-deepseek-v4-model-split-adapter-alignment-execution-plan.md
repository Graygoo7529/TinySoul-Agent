# DeepSeek V4 模型拆分与 Adapter 对齐执行计划

状态：`done`

日期：2026-09-10

## 目标与确认语义

将当前实际指向 Pro 的 `deepseek_v4` 拆分为 `deepseek_v4_pro` 与 `deepseek_v4_flash`，不保留旧 Model id 兼容别名。两者继续使用 `deepseek` Adapter 和 `orca -> deepseek` Provider Chain；`context_window_tokens` 按 DeepSeek 官方模型能力设为 `1000000`。现有 Task Model Chain 只把 `deepseek_v4` 原位替换为 `deepseek_v4_pro`，不自动加入 Flash，避免改变现有任务选择策略。

DeepSeek Adapter 继续对应 OpenAI-compatible Chat Completions API style。本轮校准 V4 Chat 的 thinking、工具调用、推理回放和响应失败解释，不新增 DeepSeek Responses Adapter、ProviderAdapterBinding、Binding 级参数覆盖或前端协议。

## 设计与失败归属

- DeepSeek thinking 未显式关闭时按供应方默认语义视为启用；规范 reasoning effort 为 `low`、`high`、`max`。thinking 启用时在请求进入供应方前省略无效 sampling 参数。
- 通用 OpenAI SDK payload mapper 不再在 behavior 返回空 tool choice 后隐式补写 `required`。默认 behavior 明确映射 TinySoul required 语义；DeepSeek thinking mode 明确省略 `tool_choice`，其他 Adapter 保持各自既有 wire 语义。
- DeepSeek 携带 tools 且 thinking 启用时要求 `reasoning_keep = "content"`，以保证所有历史 assistant reasoning 均可回放。该调用相关契约及工具数量、strict tool 差异在 Adapter 预检处归类为 Model-scope `ProviderError(CONFIG)`。
- DeepSeek 返回 `finish_reason = "insufficient_system_resource"` 表示供应方推理资源不足，在 DeepSeek behavior 响应校验处归类为 Provider-scope `ProviderError(TRANSIENT)`，复用现有 Provider 重试与切换流程。
- 非法静态 Adapter option 继续由配置入口抛出 `ConfigError`；模型未按 TinySoul task 协议产生所需工具调用继续由任务解释层形成局部 `TaskFailure`。不新增 Runtime failure reason。
- DeepSeek strict tool calling 依赖 beta endpoint；当前 Provider 使用普通 endpoint，因此继续显式拒绝，不引入 beta 模式或隐式 endpoint 切换。

## 实施事项

- [x] 更新 development/standard DeepSeek Model 模板：删除 `deepseek_v4`，增加 Pro/Flash，设置正确 Provider Model、1M context 和一致能力/options。
- [x] 将两套 Task Model Chain 中的 `deepseek_v4` 原位替换为 `deepseek_v4_pro`，不加入 Flash。
- [x] 校准 DeepSeek Adapter 的 thinking 默认值、effort、sampling、tools/reasoning replay、128 tools 上限和 strict 语义。
- [x] 清理公共 OpenAI SDK tool choice 映射的空值歧义，并保持 OpenAI、Kimi、GLM、MiniMax 既有行为。
- [x] 将 DeepSeek `insufficient_system_resource` 响应归类为可重试 Provider 失败。
- [x] 更新现有 LLM 配置、initializer、SDK Adapter 与 external provider 测试，不增加重复或过度防御性组合。
- [x] 同步 `docs/design/llm.md` 的 DeepSeek Chat Adapter 当前实现语义。
- [x] 运行聚焦测试、Fast、Full、typecheck 与 `git diff --check`，逐项核对本计划。

## 实施与核对结果

- development/standard 均只声明 `deepseek_v4_pro` 与 `deepseek_v4_flash`；两者均使用 `deepseek` Adapter、Orca 优先、官方 DeepSeek fallback、`context_window_tokens = 1000000` 和一致的 thinking/reasoning/tool options。
- framework 与 home_search Task Chain 仅将旧 `deepseek_v4` 原位替换为 `deepseek_v4_pro`；Flash 保持可手工选择但不改变现有任务路由。
- DeepSeek Adapter 默认按 thinking enabled 处理；支持 `low/high/max`；thinking 请求省略无效 sampling；工具请求省略 `tool_choice`、要求文本 reasoning replay、限制 128 个可见工具，并保留普通 endpoint 对 strict tools 的明确拒绝。
- Chat behavior 现在拥有完成原因校验 hook；DeepSeek 的 `insufficient_system_resource` 被归类为 Provider-scope transient failure，未新增 Runtime reason 或改变既有 fallback 控制流。
- `my-agent-dev` 未被修改。使用其现有 Orca 与 DeepSeek 凭据完成四个真实端点的最小验证：Pro/Flash × Orca/官方均成功完成 thinking 工具调用、reasoning replay 和最终回答；脚本只输出摘要，不输出 key。
- 聚焦 LLM 测试通过；Fast 为 970 passed、2 skipped、28 deselected；Generation 为 5 passed；Full 为 975 passed、2 skipped、23 external deselected；typecheck 与 `git diff --check` 通过。

## 非目标

- 不修改 Provider/Model Chain 的重试、成功偏好或 cycle 策略。
- 不把 `deepseek_v4_flash` 自动加入任何内置 Task Model Chain。
- 不新增 DeepSeek vision 模型、Responses/Anthropic Adapter、beta strict endpoint 或 provider-specific Model options。
- 不修改 endpoint、前端设置协议或 `my-agent-dev` 实例配置；本轮模板改动通过生成和配置契约验证。

## 验收标准

- 两套模板只声明 `deepseek_v4_pro` 和 `deepseek_v4_flash`，均为 1M context、Orca 优先且官方 DeepSeek fallback；不存在 `deepseek_v4` 内置引用。
- 两套 Task Model Chain 仅以 `deepseek_v4_pro` 原位替换旧条目。
- V4 thinking 默认、effort、sampling、tool choice、reasoning replay、工具数量和资源不足停止原因与官方 Chat 语义一致。
- Adapter 前置契约、供应方可重试失败与 task 局部失败保持清楚分层，现有 fallback/Runtime bridge 无需改变。
- 文档、代码与测试描述同一当前事实，完整本地门禁与类型检查通过。
