# LLM API 模式回放、缓存与专用 Adapter 复核改进执行计划

状态：`pending`

日期：2026-10-21

本文记录 2026-10-21 对四类 API 模式重构提交的复核结果和下一轮执行计划。它依据 [AGENTS.md](../../AGENTS.md)、[LLM 设计](../design/llm.md)、已归档的 [四类 API 模式执行计划](done/20261019-done-LLM 四类 API 模式真实 SDK 接入与推理状态执行计划.md) 以及当前官方文档。当前提交已经完成上一轮计划，本文件只记录需要继续改进或进一步真实验证的内容，不覆盖上一轮完成结论。

## 1. 本轮复核结论

当前提交 `6638280` 的主线是完整的：`protocol/` 保存 TinySoul 内部消息、工具、模型、请求和响应；`adapter/` 按四种线上 API mode 映射 SDK 请求；`provider` 只提供凭据和 endpoint；专用 adapter 继承通用 mode adapter；`LLMTaskRunner` 拥有重试和 provider/model 切换；配置 Endpoint 和前端 catalog 共用 TOML 解析结果。`ReasoningKeep` 已清除，原生回放统一为 `NativeReplay`，OpenAI、Anthropic、Google 的本地 SDK 请求/响应测试已经存在。

已重新运行当前仓库门禁：

- `scripts/test.ps1 -Suite Full`：1317 passed，23 deselected；
- `scripts/typecheck.ps1`：All checks passed；
- 上一轮已通过前端 811 项测试、TypeScript/Vite build、改动 Python 文件的基础 Ruff/import 检查和 `git diff --check`。

这说明本次复核没有发现已经破坏主线的回归。真实供应商探针没有完成：一次使用 `.env` 中 `ALIYUN_API_KEY` 对阿里云兼容 Anthropic endpoint 的 64-token 调用在自动网络审批期限内未执行，因此没有产生远端请求、费用或响应证据。后续若要执行，必须仍然只输出状态、模型名和 stop reason，不输出 key 或完整响应正文。

## 2. 当前实现与四种 API mode 的对应关系

### 2.1 OpenAI Chat / Responses

`openai/chat.py` 和 `openai/responses.py` 共享 `OpenAIAdapter`、payload/history/tool-name mapper、usage 和错误归类。`gpt` 只继承 Responses adapter 并处理 reasoning 模式下的采样参数；Kimi、DeepSeek、GLM、MiniMax 只覆盖其兼容 Chat API 的真实差异。Responses 的 output item、encrypted reasoning、tool call/output 和 JSON object 已有本地 SDK transport 测试。

需要继续核对的重点是新模型缓存和无状态推理。官方当前文档说明：较新 Responses 模型使用 `prompt_cache_options.mode`、`ttl` 和内容块上的 `prompt_cache_breakpoint`；TTL 目前包含 `30m` 与 `12h`，Responses 还支持 `prompt_cache_options.prewarm=true`。`store=false` 的无状态响应默认带有 `reasoning` item 的 `encrypted_content`，之后应原样携带全部 output item。当前代码已经正确生成 mode、key、单个 breakpoint 和 encrypted item，但只开放 `30m`，没有 prewarm owner，也没有把完整请求前缀纳入回放匹配。

### 2.2 Anthropic Messages

`anthropic/messages.py` 和 `anthropic/payloads.py` 已使用 `AsyncAnthropic.messages.create`，映射 system、messages、tools、thinking、output_config、cache_control、tool_use/tool_result、usage 和签名 block。`native_replay=signed` 会保留完整 block 顺序，`thinking_display=omitted` 的空文本仍保留 signature。

官方当前 thinking 文档进一步明确：`adaptive`、`enabled`、`between_tools`、`disabled` 的可用性取决于具体模型；有些模型拒绝 `disabled`，`between_tools` 只适用于特定 Sonnet 版本和 effort 范围。thinking 配置和 resolved effort 会进入缓存前缀；变更会使后续 cache breakpoint 失效。当前 catalog 对 API mode 暴露了所有候选，TOML 没有模型级 thinking 类型能力，因此存在“前端可选、远端 400”的配置缺口。

### 2.3 Google GenerateContent

`google/generate_content.py`、`google/payloads.py` 和 `google/cache.py` 已使用 `google-genai` async SDK，映射 systemInstruction、contents、tools、toolConfig、thinkingConfig、JSON MIME、functionCall/functionResponse、thought signature 和 cachedContents TTL。自动函数调用关闭，显式缓存仅持有 generation-local 资源索引，远端 TTL 负责过期。

官方文档仍要求 GenerateContent 的 thought signature 与所有 parts 原样、按顺序回传，不能拼接或合并带 signature 的 part。当前 payload mapper 已保留 part 顺序并有测试，但 thinking config 通过 `cast(ThinkingConfig, dict)` 依赖 SDK 当前 transformer 的 alias 保持行为；应改为 SDK 的明确 typed construction，并增加 wire-level 回归断言。GenerateContent 文档当前标为 Legacy，新接入应另建 `google-interactions` API mode，不能把两者混入现有 mode。

## 3. 已确认的设计缺口

### 3.1 NativeReplay 指纹只覆盖 assistant 输出

当前 `NativeReplay.message_fingerprint` 由 assistant 可见文本和工具调用生成。它可以防止消息本身被编辑，却不能表达此前 system、tools、用户消息、前置 assistant blocks、thinking effort、缓存选项或工具别名是否改变。Anthropic 新模型会验证 thinking block 前的 system/tools/messages 前缀；Google 会验证 thought signature 关联的 parts；OpenAI encrypted reasoning 也要求把原始 output items 和历史一起回放。只匹配当前 assistant 输出仍可能把不可用状态送给 provider。

下一轮应将字段改为 `context_fingerprint`（不保留旧别名），由 adapter 根据“到该 assistant turn 为止的规范化 provider 输入 + 影响原生状态的 adapter options”生成。捕获和匹配共用同一个 canonical serializer，包含：API mode、adapter、provider/model route、variant、thinking/reasoning 配置、工具定义及顺序、前置消息/parts、当前 assistant tool calls 和 cache breakpoint。匹配失败时继续使用已有普通文本/工具事实 fallback；不尝试删除签名、改写 encrypted item 或自动重试另一种回放格式。

该指纹是 adapter-owned 验证信息，不进入模型可见文本，不暴露 signature/encrypted payload，也不新建第二套 reasoning 状态。

### 3.2 Anthropic 模型能力没有进入配置投影

API mode catalog 只能表达接口允许的字段，不能表达每个远端模型允许的 thinking 类型、display、effort 和 JSON/tool 组合。保持正常路径简单的方案是：

1. 在 model TOML 中声明模型实际可用的 thinking 类型候选、display 候选和 reasoning effort 候选；
2. 后端将这些候选作为模型 option projection 返回，后端仍以同一 catalog 规则校验选定值；
3. 前端只显示当前模型声明的候选，切换模型或 adapter 时清理失效值；
4. 不在请求时调用 Models API，不建立动态远端能力发现服务。

同一机制也用于 GLM 的 `reasoning_effort`、`thinking` 和 `clear_thinking`，以及未来专用 adapter 的真实限制。候选数组和顶层选定值仍保持与现有 `reasoning_efforts` 一致，避免把 provider 文档枚举复制成 Python 全局枚举。

### 3.3 专用 adapter 仍有少量“可配置但未完全表达”的字段

- DeepSeek 已正确省略 thinking 模式的 temperature、保留 top_p，并要求带工具时使用 `reasoning_content` 回放；需要补充模型级 effort 候选和 strict/tool-choice 能力声明，避免把某一型号规则扩大到整个 family。
- GLM 官方当前字段包括 `thinking.type`、`thinking.clear_thinking`、`reasoning_effort`、`do_sample`、`request_id`、`user_id`。现有 adapter 已发送 thinking、clear_thinking 及部分扩展字段，但默认模型 TOML 没有 effort 候选，前端无法配置其最新推理档位。
- Kimi 的 k2/k3 variant 仍是合理的 adapter 变体；应继续用官方字段验证 k2 的 thinking/keep 与 k3 的 reasoning effort，不从 provider model 字符串推断行为。若 k3 始终要求 reasoning 回放，应在 variant catalog 明确标注，而不是只在 Python hook 中隐式打开。
- MiniMax 当前 `reasoning_content`/`reasoning_split` 映射已清理旧 `reasoning_details`；下一轮只需用最新官方响应 fixture 验证工具往返，不增加新的专用 reasoning 类型。
- GPT 继续只覆写 Responses 的采样约束；API mode 的通用 reasoning、verbosity、store、cache 和 replay 仍由通用 Responses adapter 负责。

### 3.4 Google SDK typed mapping 和缓存限制

`thinking_config` 应使用 `types.ThinkingConfig` 的明确字段，避免把 snake/camel alias 行为交给未声明的 mapping。Google explicit cachedContents 只属于 GenerateContent；模型是否支持 explicit cache、最小 token 和 TTL 由 model TOML 声明，不能在 adapter 中按远端名字猜测。generation-local cache index、TTL 失效、404 invalidate 和 close 清理保持现状，不添加后台回收器或跨进程索引。

### 3.5 OpenAI 缓存和 prewarm 的边界

当前单个 `PromptCache.breakpoint_message_index` 足以支持 TinySoul Background 稳定前缀。下一轮先补 `12h` 的 Responses TTL 和真实 content-block wire fixture；不为“最多四个 breakpoint”提前建立平行数组，除非 Context owner 已经能提供多个有明确语义的稳定前缀。

`prewarm` 是一次缓存准备操作，不是普通 LLM Task 的回答。若要启用，应由 LLM owner 提供显式 `prewarm_cache` 入口，复用同一 MessageStack、model/provider chain 和错误归类，成功只返回缓存准备事实，不写入 AssistantMessage、不执行 Action、不改变 Turn。没有真实调用方前不把 `prewarm` 塞进 model adapter option，也不在普通 invoke 中偷偷发起第二次请求。

## 4. 执行步骤

### 阶段一：补充协议和规范化回放身份

- 将 `NativeReplay.message_fingerprint` 改为 `context_fingerprint`，更新 Reasoning、projection、Observation、测试和文档；不保留旧字段。
- 在公共 adapter 中建立只读 canonical replay input builder；各 API mode 只提供 provider wire 差异，不维护第二份 fingerprint 算法。
- 把会影响 native state 的选项、工具定义/别名、前缀 messages/parts 纳入 fingerprint；回放失配统一 fallback。
- 为 OpenAI encrypted、Anthropic signed、Google signed 和 Chat reasoning_content 分别增加“前缀改变、thinking effort 改变、tool schema 改变、工具结果重排”的测试。

### 阶段二：模型级能力和前端 catalog

- 扩展 model option projection，使 TOML 能声明 thinking 类型/display/effort 等候选；adapter mode catalog 仍是字段类型、依赖和互斥的唯一基础规则。
- 更新 Anthropic、GLM、DeepSeek、Kimi、MiniMax 的代表性 TOML，使用真实官方模型能力，不新增内置/自定义分支。
- 前端按模型当前候选呈现 thinking、effort、native replay、cache 选项；切换 adapter/variant/model 时沿现有草稿依赖清理机制提交有效字段。
- 增加设置页测试，覆盖“模型允许的候选少于 API mode 默认候选”和“移除候选后清理顶层选定值”。

### 阶段三：修正 SDK 映射与缓存行为

- Google 使用 `ThinkingConfig` typed construction，并用 SDK MockTransport 断言 `thinkingLevel`/`thinkingBudget`/`includeThoughts` 的实际 JSON。
- OpenAI Responses 增加 `12h` TTL fixture；校验 explicit breakpoint 仍位于支持的 content block，并保留 key、cache write/read usage。
- Anthropic 增加 omitted signature、redacted thinking、prefix mismatch 和 model-specific thinking option fixture；确认 automatic cache 与 explicit block breakpoint 不重复标记同一边界。
- 保留 Google cache generation ownership、TTL 和 404 invalidation；补充 explicit cache 不支持/过期后的下一次创建路径。

### 阶段四：专用 adapter 对齐和真实验证

- 对照 Kimi、DeepSeek、GLM、MiniMax 官方文档更新 `reference/api_mode/`，只保留当前真实字段和限制。
- 增加 provider payload tests，逐项证明每个可编辑 option 在请求中实际生效；删除只被 catalog 暴露而 mapper 不消费的字段。
- 为阿里云 Token Plan 配置一个独立测试 provider/model fixture：OpenAI-compatible endpoint 与 Anthropic-compatible endpoint 共用 key，但分别使用两个 API mode endpoint；不把阿里云扩展限制写进 Anthropic mode 规则。
- 只有在用户明确要求并确认额度后，使用 `.env` 的 `ALIYUN_API_KEY` 做一次最小真实 Messages 请求；输出仅记录状态、模型和 stop reason。真实账号测试保持 `external` marker，不进入 Full 门禁。

### 阶段五：文档、门禁和计划核对

- 同步 `docs/design/llm.md`、`docs/endpoint/configuration.md`、`docs/endpoint/events.md`、`reference/api_mode/` 和前端配置覆盖文档。
- 运行聚焦 adapter/协议/配置/前端测试，再运行 `scripts/test.ps1 -Suite Full`、`scripts/typecheck.ps1`、前端完整测试/build、改动文件基础 Ruff/import 和 `git diff --check`。
- 只有代码、配置、前端、文档和验证全部逐项完成后，才将本文件改为 `done`、加入 `-done-` 并移动到 `docs/analysis/done/`。

## 5. 预期结果

```text
TinySoul MessageStack
  → model-specific option/capability projection
  → API-mode mapper
  → dedicated adapter hook
  → SDK request
  → normalized RawResponse
       ├─ readable Reasoning.summary
       ├─ route + context-bound NativeReplay
       ├─ normalized TokenUsage/cache usage
       └─ ordinary tool-call result
```

完成后，前端显示的每个 thinking/cache/replay 选项都有对应 TOML 声明和真实 mapper 消费；原生状态只在完整前缀仍一致时回放，签名或加密内容失配会安全回退；缓存意图、远端缓存资源、推理回放和可读摘要仍由不同 owner 表达。四种 API mode 的差异保留在其 mapper，专用 adapter 只保留官方真实差异，TinySoul 内部协议不引入第二套 provider-native 消息或恢复状态机。

## 6. 需要维护者确认的边界

1. 本计划默认下一轮先支持图片理解验证；图片生成需要新增输出模态、资源生命周期和前端表现，是否另立计划待确认。
2. OpenAI Responses `prewarm` 只在存在真实调用方时加入独立 owner；不在普通模型调用中隐式触发。
3. Anthropic/Google 的完整前缀 fingerprint 属于内部回放验证字段，不向前端展示原始内容，不做跨 provider 迁移。
4. Google Interactions 作为新的 `google-interactions` API mode 单独设计；本计划只修正现有 GenerateContent，不把 Legacy mode 偷换成 Interactions。

## 7. 复核依据

- [OpenAI Prompt Caching](https://developers.openai.com/api/docs/guides/prompt-caching)：`prompt_cache_options`、显式 breakpoint、30m/12h TTL、prewarm、usage 和 key。
- [OpenAI Reasoning](https://developers.openai.com/api/docs/guides/reasoning)：Responses encrypted reasoning 和 stateless replay。
- [Anthropic Thinking](https://platform.claude.com/docs/en/build-with-claude/thinking)：thinking 类型、display、effort、缓存失效和 tool replay。
- [Anthropic Preserved Thinking](https://platform.claude.com/docs/en/build-with-claude/preserved-thinking)：前缀绑定和 signature 失配处理。
- [Google Gemini Thinking](https://ai.google.dev/gemini-api/docs/generate-content/thinking)：thinkingConfig、includeThoughts 和 part 读取。
- [Google Thought Signatures](https://ai.google.dev/gemini-api/docs/thought-signatures)：part 顺序和 signature 原样回传。
- [Google Context Caching](https://ai.google.dev/gemini-api/docs/generate-content/caching)：implicit/explicit cachedContents、TTL 和模型支持。
- [DeepSeek Thinking Mode](https://api-docs.deepseek.com/guides/thinking_mode/)：reasoning_content、工具回放、sampling 和 tool choice 限制。
- [GLM Chat Completion](https://docs.z.ai/api-reference/llm/chat-completion)：thinking.clear_thinking、reasoning_effort、do_sample 和工具限制。
- [阿里云 Anthropic-compatible Messages API](https://help.aliyun.com/en/model-studio/anthropic-api-messages)：用于独立兼容 provider 验证，不作为 Anthropic 官方 API 语义来源。
