# LLM 四类 API 模式真实 SDK 接入与推理状态执行计划

状态：`done`，2026-10-21 完成核对。本计划是本轮重构的执行记录和验收清单，依据 [AGENTS.md](../../../AGENTS.md)、[LLM 设计](../../design/llm.md) 及 [API 模式调研](../../../reference/api_mode/README.md)。本轮不保留旧字段的兼容别名，配置、协议、adapter、前端 catalog 和文档一起迁移到当前语义。

## 1. 目标

把 TinySoul 的内部 LLM 请求稳定地映射到四种明确的线上 API 模式，并让专用 family adapter 只表达真实差异：

```text
TaskCall
  → ModelSpec / ProviderBinding
  → API-mode adapter + dedicated adapter hooks
  → SDK client
  → provider request/response
  → RawResponse / Reasoning / NativeReplay
  → TaskResult
```

本轮覆盖：

- OpenAI Chat Completions、OpenAI Responses；
- Anthropic Messages；
- Google GenerateContent（`google-genai` SDK）；
- GPT、Kimi、DeepSeek、GLM、MiniMax 在 OpenAI Chat/Responses 通用 adapter 上的专用配置；
- thinking/reasoning 控制、可读摘要、原生回放、提示缓存 key/breakpoint/implicit/explicit 和缓存资源 TTL；
- TOML、后端 catalog、配置 Endpoint、模型设置页和观察投影。

不在本轮加入 Google Interactions、Vertex IAM/Bedrock 等新 API/认证体系、SDK 自动工具执行、provider 会话状态、跨进程缓存索引或 Responses 独立 prewarm owner。新 API 必须新增独立 `ApiMode`，不靠模型名称或 SDK 品牌隐式切换协议。

## 2. 统一语义

### 2.1 API mode、adapter、provider、model

- `ApiMode` 表示线上请求/响应协议：`openai-chat`、`openai-responses`、`anthropic-messages`、`google-generate-content`。
- 通用 adapter 负责一种 API mode 的消息、工具、图片、JSON、usage、stop reason、缓存和 SDK 错误映射。
- 专用 adapter（GPT、Kimi、DeepSeek、GLM、MiniMax）继承通用 adapter，只增加真实的 variant、采样限制、thinking 字段、工具限制或响应字段映射。
- Provider 只声明一个或多个 API mode endpoint、共享凭据和 headers；不再枚举 Kimi/DeepSeek 等专用 adapter。Model 选择唯一 adapter，并通过 provider binding 给出不透明的远端 `provider_model`。
- `tinysoul.llm.protocol` 只描述 TinySoul 内部消息、请求、响应和缓存意图；SDK payload/protocol 只存在于 adapter 目录。

### 2.2 推理摘要与统一原生回放

`Reasoning.summary` 是供应商返回的有限可读摘要；它不代表原始 chain of thought。`NativeReplay` 是为了下一次同路由请求而保留的、不可解释的供应商原生状态。

`ReasoningKeep` 已删除，配置和响应统一使用 `NativeReplayMode`：

| mode | 真实原生状态 |
| --- | --- |
| `none` | 配置中的关闭值；不创建空 NativeReplay |
| `content` | OpenAI-compatible Chat/Kimi/DeepSeek/GLM/MiniMax 的 `reasoning_content` 等可回放内容 |
| `encrypted` | OpenAI Responses reasoning item 的 encrypted content 及其有序 output item |
| `signed` | Anthropic thinking/redacted thinking/tool_use block、Google thought/functionCall/thoughtSignature part |

`NativeReplay` 必须携带 `mode`、`api_mode`、`adapter`、variant、provider/model route、ordered JSON items 和助手消息 fingerprint。只有 mode、路由和 fingerprint 都匹配时才回放；路由切换、消息改写或工具交换不完整时，adapter 回退普通 TinySoul 文本/工具事实，不发送失配状态。Kernel 只运输协议对象，不解释签名、加密内容或 provider 字段。Observation 只显示摘要和“可回放/来源”，不显示原始状态。

Anthropic/Google 的 `native_replay` option 支持 `none|signed`，默认不保留；需要多轮 thinking/tool continuation 的模型在 TOML 中显式选择 `signed`。OpenAI Chat/Responses 和专用 adapter 只暴露其实际支持的 mode；Kimi K3 的 provider 约束由专用 adapter 固定保留 content 状态。

### 2.3 思考控制与 adapter options

adapter options 由 API mode 提供基础项，再由专用 adapter/variant 增加选项。不同 API 的控制名称和数值语义不强行合并：

- OpenAI：`reasoning_efforts` 候选数组 + model 顶层 `reasoning_effort`，Responses 另有 summary/mode/context/verbosity/store；
- Anthropic：`thinking`、`thinking_budget_tokens`、`thinking_display`、`reasoning_efforts`/`output_config.effort`，后端校验 mode/budget/display 依赖；
- Google：`reasoning_efforts`（映射 `thinkingLevel`）或 `thinking_budget_tokens`（映射 `thinkingBudget`）二选一，`include_thoughts` 只控制摘要返回；
- 专用 adapter：Kimi variant/thinking、DeepSeek/GLM thinking、MiniMax reasoning_split、provider 特有的 extra body 等。

`temperature`、`top_p`、`max_output_tokens` 属于通用 request override；adapter 最后根据真实协议删除或改名。`extra_body` 只能扩展未占用字段，不能覆盖 framework-owned request containers、认证、缓存、thinking/reasoning 或工具字段。

### 2.4 提示缓存

`PromptCache` 是一次 Task 的意图：可选 `key` 和 `breakpoint_message_index`。model adapter option 保存模式与 TTL；远端 cache resource 不进入 TOML、运行方案或稳定 model ID。

- OpenAI Chat/Responses：model 配置 `prompt_cache_mode=implicit|explicit`、`prompt_cache_ttl=30m`；Task key → `prompt_cache_key`，boundary → `prompt_cache_breakpoint`，模式 → `prompt_cache_options`。不使用旧 `prompt_cache_retention`；Responses prewarm 暂无独立 owner，暂不接入。
- Anthropic：model 配置 `prompt_cache_mode=automatic|explicit|disabled` 与 `5m|1h` TTL；automatic 映射顶层 `cache_control`，explicit 在指定 block 放置 `cache_control`，Task key 不发送。
- Google：model 配置 `prompt_cache_mode=implicit|explicit`，正整数秒 TTL 仅在 explicit 可配置；implicit 不增加资源字段，explicit 由 generation-local `GooglePromptCacheStore` 按 route/model/prefix/tools/options 复用或创建 `cachedContents`，generation close 清空索引，远端 TTL 负责生命周期，404 失效后下一次自然重建。

缓存只表达输入前缀复用，不与 NativeReplay、Session 或答案缓存混淆。缓存用量统一进入 `TokenUsage`，不把 provider 原始 usage 字典带入 Kernel。

## 3. 实施范围与已完成内容

### A. 协议和公共 adapter

- `tinysoul/llm/protocol/reasoning.py`：新增 `NativeReplayMode`，NativeReplay 绑定 mode/route/fingerprint；删除旧 ReasoningKeep 语义。
- `protocol/models.py`：`AdapterOptions.native_replay_mode()` 解析统一 enum；Model 顶层保留候选数组 + 选定档位校验。
- `protocol/cache.py`、`protocol/usage.py`、`protocol/responses.py`：Task cache intent、typed token usage 和统一响应。
- `adapter/replay.py`：集中 capture、fingerprint、同路由 mode 匹配；`adapter/history.py`：原生工具回放和普通事实回退共用。
- `adapter/common.py`：四类 API 共用配置预检、显式缓存边界校验和 HTTP status 失败归类。OpenAI 通用/专用 adapter 共用一个 replay mode hook，Kimi K3 只覆写固定策略；不再并行解析两份 replay 配置。
- `kernel/context/signals.py`、projection/observation：序列化和安全投影 mode、route、usage，不暴露 opaque payload。

### B. 四类模式和专用 adapter

- `adapter/openai/`：Chat/Responses request mapper、工具/图片/JSON、cache breakpoint/options、usage/stop/error、content/encrypted replay。
- `adapter/anthropic/`：`AsyncAnthropic.messages.create`、system/messages/blocks/tools/thinking/output_config/cache_control、signed block replay、工具结果回放和失败归类。
- `adapter/google/`：`google-genai` async GenerateContent、Content/Part、FunctionDeclaration/FunctionCall/FunctionResponse、thinkingConfig、JSON output、signed thought replay、隐式和显式缓存。
- `adapter/models/`：GPT 复用 Responses；Kimi、DeepSeek、GLM、MiniMax 复用 Chat，并只保留真实专用差异。
- `factory.py`/`registry.py`：按 `(provider, api_mode)` 复用 client；OpenAI/Anthropic/Google SDK retry 关闭；adapter 借用 client，registry 负责 close。

### C. 配置、catalog、前端和文档

- Provider endpoints 支持四类 API mode，Google `api_version` 是 endpoint 连接字段，不是 adapter option。
- `adapter/catalog.py` 组合 API mode → adapter → variant 的有效 options，并将 source、choices、requires/excludes 投影给前端；Anthropic/Google 的 `native_replay=signed` 和 cache/thinking 选项来自 catalog。
- `infra/config/catalog/models.toml`、TOML assets、Endpoint 文档和设置页统一使用 lower-kebab 内部 ID、`native_replay`、候选档位数组 + 顶层选定值。
- 前端依赖后端 catalog，按 adapter 展示有效 options；trace 只展示安全摘要、usage/cache 和回放状态，不展示签名/加密块。
- `visualization/src/features/settings/models/objectEditing.ts`：父对象草稿拥有其子字段编辑；替换子树时撤销旧子字段操作。模式变更清理依赖项与最终提交使用同一机制，不保留界面已删除但提交仍存在的字段。
- `reference/api_mode/` 记录官方 API/SDK 请求、thinking、signature、cache TTL 和当前代码边界。

## 4. 正常数据流和失败边界

1. TaskRunner 根据 ModelSpec 选择 provider binding，adapter 先做配置、能力和路由校验。
2. mapper 把完整 MessageStack 和 ToolScope 转成 SDK 请求；SDK 不执行 TinySoul Action，自动 function calling 已关闭。
3. response parser 提取答案、工具调用、摘要、NativeReplay、stop reason、TokenUsage；原始 SDK 异常在 adapter 边界映射为稳定 ProviderError。
4. TaskRunner 是唯一重试/切换 owner；adapter 不隐式重试、不启动后台任务、不吞取消。
5. replay route/fingerprint 不匹配时普通消息 fallback；不把不完整 native state 伪装成成功的 provider-native continuation。
6. 配置错误、SDK transport/status、解析错误分别进入现有 LLM failure/runtime bridge；不跨边界泄露 SDK 原文、密钥、traceback 或完整 provider payload。

## 5. 验收清单

### Python/协议

- [x] 四 API mode catalog、adapter options、互斥/依赖和 provider endpoint 能转换为 typed config。
- [x] `ReasoningKeep`/`reasoning_keep` 从当前代码、资产和活动文档移除；统一 `NativeReplayMode` 并完成 signal/projection roundtrip。
- [x] OpenAI Chat/Responses request serialization、cache breakpoint/options、tool history 和 content/encrypted replay。
- [x] Anthropic text/thinking/omitted signature/tool_use/tool_result/cache/usage。
- [x] Google text/image/functionCall/functionResponse/thinking signature/cache/usage；Google cache store 的 create/reuse/TTL/404 invalidate。
- [x] dedicated adapter 复用通用 API mode，Kimi/DeepSeek/GLM/MiniMax/GPT 的真实专用参数不重复实现。
- [x] SDK retry=0，TaskRunner retry owner 和 ProviderError bridge 保持单一职责。

### 前端/配置

- [x] Provider endpoint、headers、api_version 和 model adapter options 由后端 catalog 驱动。
- [x] native replay、thinking、cache mode/TTL、候选档位/选定值有统一字段和翻译。
- [x] ModelPicker/任务链复用 family、search、collapsed 和单模型选择组件；Trace 不显示原生 opaque state。

### 门禁

- [x] 运行 `scripts/test.ps1 -Suite Full`、`scripts/typecheck.ps1`、改动文件的 Ruff 基础错误/import 检查和 `git diff --check`。
- [x] 运行前端完整 Vitest、TypeScript/Vite build；通过现有锁定文件恢复依赖安装后全部通过。
- [x] 清理测试工具生成的 `.pnpm-store/` 等未跟踪临时目录。
- [x] 门禁通过后把本文件状态改为 `done`，移动到 `docs/analysis/done/`，并在文件末尾记录实际命令与结果。

## 6. 设计核对结论

本轮保持 AGENTS.md 的 owner 和控制流：Infra 提供配置、JSON 等通用设施，LLM adapter 持有并映射 SDK 边界，Kernel 运输内部协议并提供稳定前缀意图，Gateway/前端通过 catalog 和 Endpoint 编辑 TOML。NativeReplay 是 LLM response data，`native_replay` 是 model policy；两者共享一个 enum 但不复制状态。Prompt cache 是 Task intent + model policy；只有 Google explicit cache 有 generation-local resource owner。四类 API 的真实差异留在各自 mapper 和专用 adapter hook 中，没有并行的 ReasoningKeep、provider-specific history 状态机或前端硬编码选项依赖规则。

正常响应由 adapter 解析，任务输出不符合协议仍由 ResponseInterpreter 返回局部失败；连接/配置/SDK 失败归类为 ProviderError，继续由已有 TaskRunner 与 Runtime bridge 协调。不增加缓存后台回收器或 provider 私有会话。取消不被转换成普通模型结果。所有 native state 只按路由、内容和当前工具别名匹配后回放；失配时使用真实文本/工具事实投影。

## 7. 实施核对记录（2026-10-21）

- [x] `TINYSOUL_PYTHON=C:\Anaconda3\envs\TinySoul\python.exe`；`powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/test.ps1 -Suite Full`：**1317 passed，23 deselected**。Full 按规约不运行 external 测试，包含 wheel/项目生成验收。
- [x] `powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/typecheck.ps1`：All checks passed。
- [x] 改动/新增 Python 文件 `ruff check --isolated --target-version py313 --select E4,E7,E9,F,I` 通过；`agent/composition/builder.py` import 专项检查通过。未把仓库其它既有 lint 提示当成本轮新增问题或宣称全仓所有规则清零。
- [x] `pnpm run test`：**94 个文件、811 项测试通过**。`pnpm run build`：TypeScript 与 Vite 通过，仅保留既有 bundle 大小提示。
- [x] `git diff --check` 通过；根目录 `.pnpm-store/` 已清理。前端原有依赖读取/链接问题通过 frozen-lockfile 恢复安装，锁定文件未改；损坏的翻译目录从提交版本恢复后只追加当前字段，未保留编码损坏。
- [x] SDK 实际版本：OpenAI **3.35.1**、Anthropic **1.15.0**、google-genai **2.31.0**。测试使用真实 SDK 与本地 MockTransport，覆盖签名无摘要、原生工具交换、消息修改/别名变化/重复 call ID 回退、缓存创建/复用/过期/404 失效、隐式缓存不创建资源、thinking/JSON 映射和单次网络错误归类。未调用真实供应商账号，未验证远端连通性、收费或缓存命中率。

## 8. 与最初提议和后续确认的逐项核对

| 初始目标 | 当前实现与核对结果 |
| --- | --- |
| 分清内部 protocol、线上 API mode、adapter、provider、model | `protocol/adapter_types.py` 与 `adapter/catalog.py` 定义四模式；`protocol/` 仍只表达 TinySoul 内部事实，SDK wire mapping 位于 `adapter/`。 |
| 通用适配器提供完整主线，专属适配器复用并定制 | `openai/chat.py`、`openai/responses.py`、`anthropic/messages.py`、`google/generate_content.py` 均有真实 SDK 调用；`models/` 仅保留专属字段、variant 和限制。MiniMax 使用当前官方 reasoning_content，不再将旧摘要字段伪装成原生回放。 |
| Provider 一个 key 对多个 API 入口，按模式判断兼容性 | `config/types.py`、`config/sections.py` 与 `factory.py` 使用 endpoints 与共享凭据/header 引用；前端 Provider 和模型表单沿同一 catalog 编辑与筛选。 |
| API mode / adapter / variant 分层提供配置项 | `AdapterSpec.effective_options` 是唯一有效选项来源；来源、候选、依赖和互斥进入 Endpoint 投影。Google api_version 留在 endpoint；Kimi variant 留在 model adapter_options。 |
| 候选档位数组与顶层选择；采样参数归 request override | TOML 声明 `reasoning_efforts`，顶层选择 `reasoning_effort`；前端逗号输入和下拉分别编辑，失效选值要求明确处理。temperature/top_p/max_output_tokens 保持通用合并链。 |
| ReasoningKeep 与 NativeReplay 统一，encrypted 也是原生回放 | 删除旧保留字段与别名，只有 `NativeReplayMode` 和 `NativeReplay`；API-specific state 使用 content/encrypted/signed，摘要与 opaque payload 分离。 |
| 思考回放和缓存分别表达，利用真实 API 能力 | OpenAI key/options/breakpoint；Anthropic thinking/signature、automatic/explicit cache_control；Google thinking/signature、implicit cache 与 cachedContents 生命周期均有 mapper 和 SDK 测试。Context 在 Phase1/Phase2 与 Action LLM 任务中提供 Background 边界。 |
| 配置、前端、观察与文档同步 | development/standard 模型 TOML 使用 native_replay；设置页以 catalog 显示选项、统一草稿修改；Observation 归一化 usage 并隐藏 opaque payload；`docs/design/llm.md`、`docs/endpoint/configuration.md`、`docs/endpoint/events.md` 与前端配置清单同步。 |
| 保持已有稳定模型 ID、family TOML 与选择主线 | 未增加内置/自定义模型分支，未改变运行方案范围语义；新 family/模型仍走既有 TOML create_source/set 与同一 ModelPicker。 |

范围边界保持明确：Anthropic 的 JSON object 使用任务提示与现有解释器，不为其伪造不能表达任意对象的空 schema；Google 使用原生 JSON MIME，严格回答 JSON Schema 不属于当前内部协议。Responses 独立 prewarm、流式 progress、Google Interactions、Vertex/Bedrock 认证以及跨进程缓存索引不在本轮范围。缓存 TTL 与模型选项可配置，不承诺所有远端型号接受每个档位或一定命中缓存。

本轮实现、设计文档、执行计划与必要本地验证已逐项核对完成；真实账号的 external 验证仍是独立的显式操作。
