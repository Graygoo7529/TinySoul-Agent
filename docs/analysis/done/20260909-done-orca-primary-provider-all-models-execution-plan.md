# Orca 作为全模型首 Provider 执行计划

状态：`done`

日期：2026-09-09

## 目标与边界

将 Orca 设为 development、standard 配置模板中每个内置 Model 的第一个 Provider，并先在 `my-agent-dev` 验证实时模型目录、精确远端模型名与 TinySoul 现有 Adapter 请求。本轮不修改 Task Model Chain、Model 能力、context window、Adapter options、Provider fallback 策略或 Endpoint 协议。

Orca 是一个可同时服务多个 Adapter 的 Provider。Model 继续拥有唯一 Adapter，所有 Provider Binding 继续共享该 Model 的能力与请求契约；供应商官方 Provider 保留为 Orca 之后的 fallback。

## 可用性结论

Orca 官方文档规定以 `/v1/models` 作为账户实时可用目录，并推荐使用 provider-prefixed 模型 ID。当前账户目录包含全部九个目标模型，对应关系为：

- `gpt_5_5` -> `openai/gpt-5.5`
- `gpt_5_6_sol` -> `openai/gpt-5.6-sol`
- `gpt_5_6_terra` -> `openai/gpt-5.6-terra`
- `gpt_5_6_luna` -> `openai/gpt-5.6-luna`
- `deepseek_v4` -> `deepseek/deepseek-v4-pro`
- `kimi_k2_7` -> `kimi/kimi-k2.7-code`
- `kimi_k3` -> `kimi/kimi-k3`
- `glm_5_1` -> `z-ai/glm-5.1`
- `minimax_m3` -> `minimax/minimax-m3`

非侵入实测已使用当前 Model 的 Adapter options 和 TinySoul 真实 Adapter 分别调用上述模型，九个请求均返回非空结果；DeepSeek、Kimi、GLM 与 MiniMax 请求也成功返回推理内容。因此保留 `deepseek`、`kimi`、`glm`、`minimax` 的 Adapter 语义，不把非 OpenAI Model 改为 `openai` Responses Adapter。

## 实施事项

- [x] 原子更新 `my-agent-dev`：Orca 声明五种内置 Model Adapter，非 OpenAI Model 在现有官方 Provider 之前新增 Orca Binding。
- [x] 使用 `my-agent-dev` 的最终配置执行配置解析、Registry 装配与真实多轮模型调用验证。
- [x] 同步 development/standard 的 Orca Adapter 声明和全部内置 Model Provider Chain，不修改 task 配置。
- [x] 更新现有 LLM config 与 initializer 契约测试，不为每个等价组合增加重复防御性测试。
- [x] 运行聚焦测试、Fast、Full、typecheck 与 `git diff --check`，核对计划。

## 实施与验证结果

- `my-agent-dev` 通过 `ConfigController` 原子更新 6 个配置字段，完整 LLM 配置校验通过，Task 配置 SHA-256 保持不变。
- 以最终 `my-agent-dev` 配置运行两组 external 真实 Provider 测试，九个模型的两轮主调用与两轮工具调用均通过，两组结果分别为 9 passed、9 deselected。覆盖内容包括 JSON 输出、模型声明支持时的图像输入、reasoning 提取/回放、工具调用解析与工具结果回放。
- 模板聚焦契约已由 Fast/Full 覆盖；Fast 为 966 passed、2 skipped、26 deselected，Full 为 971 passed、2 skipped、21 external deselected，`ty` 类型检查与 `git diff --check` 通过。

## 验收标准

- 两套模板的所有内置 Model 均以 Orca 为第一 Provider Binding，远程模型名使用 Orca 实时目录中的 prefixed ID。
- Orca 声明 `openai`、`deepseek`、`kimi`、`glm`、`minimax` Adapter，每个 Model 继续使用原 Adapter 和原官方 Provider fallback。
- standard 中 Orca 保持 disabled，空凭据项目仍可启动；development 中 Orca 保持 enabled，凭据缺失仍遵循既有严格启动失败语义。
- Task Model Chain 和 LLM 失败/切换流程不变。
