# OpenAI Responses 多 Provider 可移植性执行计划

状态：`done`

日期：2026-09-09

## 目标与确认语义

Orca、Wenrugou 与 Sublyx 均作为 `openai` Adapter 的 Provider，通过同一 OpenAI Responses API style 为 GPT-5.5 与 GPT-5.6 Sol/Luna/Terra 提供有序 Provider Chain。Adapter 与 API style 的一一对应关系、Model-owned capabilities/context/options，以及现有“重试 Provider、切换 Provider、切换 Model、进入下一 cycle”的恢复顺序均保持不变。

实测确认三家端点均可执行 Responses 调用。Orca 对 GPT-5.5 与 GPT-5.6 Sol 在非 `none` reasoning effort 下拒绝 `temperature`，但省略 sampling 参数后可以完整接受当前 reasoning summary、encrypted reasoning、JSON、verbosity 和 prompt cache 选项；Wenrugou 的四个目标模型可接受同一完整请求；Sublyx 的三个 GPT-5.6 模型可用，GPT-5.5 当前仅观察到上游限流。由此，统一 Provider Chain 应使用各 Provider 都能解释的 Model/Adapter 契约，而不是在 Binding 中记录端点特例。

## 设计

### Responses 参数归一化

`temperature` 继续是 Task/单次调用提供的 provider-neutral 设置，`reasoning_effort` 继续是 OpenAI Adapter 解释的模型选项。OpenAI Responses Adapter 在完成选项校验与映射后，若 effective reasoning effort 已配置且不为 `none`，省略 `temperature` 与 `top_p`。reasoning 模式因此优先于 sampling 参数；`reasoning_effort = "none"` 或未配置 reasoning effort 时仍保留现有 sampling 行为。

该规则属于 Adapter 对合法 wire payload 的归一化，与 DeepSeek thinking 模式省略不兼容 sampling 参数的现有处理一致。它不引入错误后删参数重试，不把端点差异写入 `ModelProviderBinding`，也不要求新增 `ProviderAdapterBinding`、配置字段或前端状态。

### 配置模板

development 与 standard 模板都声明 Orca、Wenrugou、Sublyx Provider 及对应 env key。development 保持面向维护者的 enabled Provider 语义，新 Provider 默认启用；standard 中新增 Provider 默认禁用，保证空凭据项目仍可启动并连接设置页。

四个 OpenAI Model 使用相同 Responses Adapter，并形成与配置 profile 相符的 Provider Chain：

- development：`orca -> wenrugou -> sublyx_proxy`；
- standard：保留官方 `openai` 链首，追加 `orca -> wenrugou -> sublyx_proxy`；
- Orca 使用 provider-prefixed 远端模型名，GPT-5.5 绑定 `openai/gpt-5.5`，不再以 `openai/gpt-5` 代替；
- Wenrugou 与 Sublyx 使用各自 catalog 中的裸模型名。

task chain 本轮不调整。5.6 context window 保留当前保守配置；在三家端点没有统一、可验证的上下文上限前，不把官方上限直接当作代理共同能力。

## 实施事项

- [x] 在 OpenAI Responses behavior 中归一化 reasoning 与 sampling 参数组合。
- [x] 更新聚焦 SDK 测试，覆盖非 `none` reasoning 省略 sampling、`none` reasoning 保留 sampling。
- [x] 更新 development/standard Provider、env 与四个 OpenAI Model Provider Chain 模板，保持 task chain 不变。
- [x] 更新 initializer/config 生成契约测试，不增加重复防御性组合测试。
- [x] 同步 `docs/design/llm.md` 的 Adapter 参数归一化语义。
- [x] 更新 `my-agent-dev` 的四个 OpenAI Model Provider Chain，并保留现有 task chain。
- [x] 运行聚焦测试、Fast、Full、typecheck 与 `git diff --check`，核对实现和计划。

## 实施与核对结果

- OpenAI Responses Adapter 现在于 reasoning effort 非 `none` 时确定性省略 `temperature` 与 `top_p`；该逻辑在端点调用前完成，不改变 Provider 错误归类和 fallback 流程。
- development 与 standard 模板均已声明 Orca、Wenrugou 与 Sublyx 的 Provider/env，四个 OpenAI Model 已按 profile 形成 Responses Provider Chain；两套 task 配置未改动。
- `B:\WorkSpace\my-agent-dev` 的四个 OpenAI Model 已通过现有 ConfigController 原子更新并通过 LLM 配置解析，未改动 task chain，未输出或写回凭据值。
- 聚焦测试通过；Fast 通过；Full 为 969 passed、2 skipped、21 external deselected；`ty` 类型检查通过；`git diff --check` 通过。

## 非目标

- 不增加 ProviderAdapterBinding、Binding 级参数覆盖或 provider-specific 参数黑名单。
- 不在 400 后自动删除参数并重试，不把确定性请求错误伪装成 transient failure。
- 不修改 Provider/Model fallback、成功偏好、Runtime bridge、Endpoint 协议或前端页面。
- 不通过本轮可用性探测宣称图像、工具调用或最大上下文均已在三家端点完整验收。

## 验收标准

- reasoning effort 非 `none` 的 OpenAI Responses 请求不发送 `temperature`/`top_p`，`none` 模式仍可使用 sampling 参数。
- 两套模板的 env 引用与 Provider 配置完整一致，standard 空凭据仍可启动，development 继续严格要求所有 enabled Provider 具备凭据。
- GPT-5.5 与三个 GPT-5.6 Model 均具备正确、同 Adapter 的 Provider Chain，Orca 远端模型名使用 catalog 中的 prefixed ID。
- task chain、LLM 三层失败语义和 Provider/Model 恢复顺序不变。
