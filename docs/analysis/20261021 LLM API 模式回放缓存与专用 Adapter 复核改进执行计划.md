# LLM API 模式回放、缓存与专用 Adapter 复核改进执行计划

- 状态：`pending`（分析与方案修订完成；等待本次设计确认，尚未实施）
- 日期：2026-10-21
- 复核基线：`a276417`；主要实现来自 `6638280`。
- 范围：四类 API mode、通用/专用 adapter、模型配置与前端编辑、Context 缓存边界，以及真实 SDK 请求验证。
- 原则：遵循 AGENTS.md；不保留迁移兼容别名，不另建模型历史、恢复状态机或动态配置平台；优先正常调用、工具往返和资源结束边界。

## 1. 本轮结论和对上一稿的修正

四类 API mode 已有实际 SDK 调用、消息映射、统一失败处理和本地 transport 测试，不能称为只有 catalog 的空框架。`ReasoningKeep` 已清除，原生回放统一由 `NativeReplay` 承载。但“配置存在”“请求字段正确”“在 TinySoul 主循环中能有效复用”是三个不同的验收层次，上一轮完成记录尚不足以证明最后一层全部成立。

本稿修正以下判断：

1. 不把所有 API 的 `message_fingerprint` 替换为完整 `context_fingerprint`。消息自身一致性、Anthropic 的特定前缀绑定、Google 缓存资源身份是不同职责；不能合并成一个覆盖全部配置的摘要。
2. 当前 Google 的 wire alias 处理有实际依据。本轮用安装的 `google-genai 2.31.0` 和本地 MockTransport 复现：直接构造 `ThinkingConfig` 会在请求中得到 `include_thoughts`、`thinking_level`；现有 alias mapping 得到正确的 `includeThoughts`、`thinkingLevel`。不能为了 typed 外观直接删除它。
3. 当前 GLM 模板绑定 GLM 5.1，没有 effort 候选不属于漏配；最新官方说明将 effort 支持放在 5.2 及以后。升级候选必须对应真实 binding，不能把全 family 更新为新型号能力。
4. OpenAI 多断点应进入本轮，Context 已有 Background/Trace/Working provenance，存在真实消费者。Responses 的 12h TTL 单独开放，不未经核实扩给 Chat。
5. prewarm 明确排除；不增加预热入口、后台任务或额外模型调用。
6. 用户已经允许必要的真实调用，不再增加“重新确认额度”的授权前置条件。真实服务测试与本地测试分开记录，不用兼容网关的结果定义官方 API。

本轮只修订本计划；不将尚未实施的方案写成 `docs/design/` 当前事实。上一轮归档计划保留历史验证记录，新发现的能力缺口以本计划跟踪。

## 2. 当前链路的实际检查

```text
family TOML + provider endpoints
  → ConfigParser / ModelSpec / adapter catalog
  → TaskCall + MessageStack + PromptCache
  → LLMTaskRunner 选择 model / provider
  → API mode mapper + 专用 adapter 差异
  → SDK → HTTP JSON
  → RawResponse / NativeReplay / TokenUsage
  → Phase / Context Trace → 下一次构造式 MessageStack
```

### 2.1 已落地与需要改进的地方

| 切面 | 当前实际实现 | 本轮改进 |
| --- | --- | --- |
| 通用接入 | 四类通用 adapter 均可发 SDK 请求；provider 按 API mode 提供 endpoint | 补齐通用可配置行为，避免新 family 被迫添加 Python adapter |
| Responses 回放 | encrypted reasoning 与有序 output items 捕获、原样回放；有路由和助手消息指纹 | 保持原结构，不添加无证据的全前缀限制；核对真实 Context 路径 |
| Anthropic 回放 | 保存完整 content blocks，支持空摘要签名和 redacted thinking | 补新模型前缀绑定处理；不要把“已保存 signature”当作“远端一定接受” |
| Google 回放 | 保存 model parts，保留 thought signature 所在位置和顺序 | 保持 parts 原样，集中 SDK 类型/alias/bytes 转换并验证最终 JSON |
| 工具历史 | 共用完整有序 call/result 判断；不完整交换转为可读事实 | Anthropic/Google 的普通工具历史不再一概依赖 signed 回放开关；必须保留签名的原生续接仍遵守各 API 约束 |
| 模型候选 | `reasoning_efforts` 支持显式数组，顶层 `reasoning_effort` 选择 | 推广为统一模型候选机制，同时处理真实的条件组合 |
| OpenAI 缓存 | key、mode、30m TTL、单一 explicit marker 已映射 | implicit 可附显式断点、多个断点、Responses tool output marker、12h 与按断点 TTL |
| Anthropic 缓存 | automatic 或单一 explicit marker | automatic 与显式断点并用，多个边界及 TTL 顺序 |
| Google 缓存 | 创建 cachedContents、复用本代索引、过期后创建、404 失效、close 清本地 | 选一个可复用前缀；分开缓存创建与生成选项；使 404 后的下一次尝试真正可恢复 |
| Context 边界 | 只选最后一个 Background message | 每次 compose 根据 provenance 提供 Background/Trace/Working 三个候选前缀 |
| 前端 | API → adapter → variant 的选项投影和依赖编辑已存在 | 增加模型候选/固定值/条件限制与可用来源，沿同一草稿保存链路提交 |

### 2.2 已确认的主线问题

- `AnthropicMessagesAdapter.invoke` 对 `ToolUse.REQUIRED` 使用 `any`，manual thinking 会在本地直接报配置错误；部分新 Claude 的 adaptive thinking 同样不支持强制 tool choice。即使远端接受，强制工具调用也可能跳过 thinking。这与 TinySoul Phase1/Phase2 的常见使用方式直接相关。
- `openai/payloads.py::_mark_cache_boundary` 只在 explicit 下处理一个 `content`，无法处理 Responses 的 `function_call_output.output`，也不能利用 implicit + explicit 的组合。
- `common.cache_boundary` 将没有断点的 explicit 请求直接变为错误；但 Action 内部任务或普通 SDK task 可能没有共享 Context 前缀。缓存是增强能力，不应因此让普通生成不可用。
- 当前 model 可配置缓存选项但不声明 `prompt_cache` capability，字段会被忽略。需要区分“Task 提供可选缓存意图”和“模型配置自身矛盾”，前者可忽略，后者应在保存时解释清楚。
- Google 创建缓存时复用生成请求的 `http_options.extra_body`，可能将仅用于生成的扩展参数带进 caches.create；这两种 SDK 请求必须各自组装。
- Google 缓存 404 虽会 invalidate，但 `status_error(404)` 为 UNKNOWN；现有测试主要证明手工再次 invoke 能新建，没有完整证明同一任务的重试路径。
- Kimi k3 的强制 content replay 只在 hook 内表达、catalog 隐藏该字段；MiniMax 暴露 `enabled` 和 `reasoning_split=false`，与当前官方参数和 TinySoul 的结构化 reasoning 接入目标不一致。
- GLM `clear_thinking` 已由 replay 策略派生，但其与本轮 thinking 开关的区别没有清晰投影；静态 model option `request_id` 会被每次请求复用，不适合作为逐请求身份。

### 2.3 验证证据及边界

- 上一次代码复核记录：Full 1317 passed、23 deselected；typecheck 通过。前端 811 项与 build 是此前实施记录，不冒充本轮重跑结果。
- 本轮独立 SDK 序列化复现：`google-genai=2.31.0`、`openai=3.35.1`、`anthropic=1.15.0`；typed 与 wire mapping 的差异见 1 节。本地脚本只用假 key 和 MockTransport，未触网。
- 本轮两个最小调用复现：Anthropic `thinking=enabled + ToolUse.REQUIRED` 在 SDK 调用前返回 CONFIG；Responses 将断点放在真实 `function_call_output` 时返回 CONFIG。两者都不是仅从 catalog 推测的风险。
- 原有 `test_messages_and_generate_content.py` 已有真实 SDK 本地传输测试，验证签名 part/block、空摘要、工具交换及缓存创建；应扩充行为缺口，不复制整套 fixture。
- 尚无本轮远端 provider 验证结论。此前阿里云探针执行没有完成，不能记为通过或据此判断 Anthropic 支持程度。

## 3. 概念、目录与职责

### 3.1 继续采用一条适配链

- `protocol/`：TinySoul 消息、工具意图/结果、输出约束、缓存意图与不透明回放附件。
- API mode：线上的请求/响应形状。四个通用 adapter 各自完整负责 SDK 映射、响应读取、错误归类。
- provider：凭据、headers、API mode endpoints、endpoint 的可选 `api_version`；不定义模型推理语义。
- 专用 adapter：复用通用 mapper，补真实的参数规则、响应差异或固定行为。不复制 SDK 调用、NativeReplay 类型或缓存生命周期。
- family：模型目录组织与前端分组。选择 family 不强制选择同名 adapter。
- model：稳定 ID、binding、能力、可配置候选与已选值。远端版本改变时更新 binding 和对应能力声明。

GPT 当前比 Responses 多一条实际行为：非 none 的 effort 下省略 sampling。它并非另一种 API mode，也不负责另存 reasoning。保留有实际规则的 `gpt` adapter；如果规则全部移入通用策略并且已无消费者差异，应删除空壳，而不是为了名称对称保留第二入口。

Claude Opus/Fable 可直接使用 `family="claude"`、`adapter="anthropic-messages"`，文件为 `models/claude.toml`。本计划默认不新增无行为的 `ClaudeAdapter`。如果后续发现只属于 Claude 而不属于 Messages 的真实 wire 差异，再增加薄专用 adapter；单纯候选、默认值和远端型号差异放在 model TOML。

### 3.2 通用 adapter 应具有的能力

新模型只要遵循所选 API 的消息和响应协议，就可通过现有前端主线接入：选 family → adapter → provider endpoint → 远端模型名 → 声明候选并选择值。无需等待专用 family 类。

当前通用 Chat 的不足是：常用兼容协议 `thinking.type` 没有通用配置入口，而 `extra_body.thinking` 整体又被禁止。改为由通用 Chat 提供可选的 `thinking` 映射，并标注为 Chat 兼容扩展；不把它宣称为官方 OpenAI Chat 必备字段。`reasoning_content` 回放继续使用同一个 content replay 实现。Kimi keep、GLM clear_thinking 等专属字段仍由专用规则解释。

受约束 `extra_body` 保留：消息、tools、工具结果、身份凭据、回放及缓存资源字段不能被覆盖；已建模字段不能用第二条路径重写。新增未建模的普通扩展可使用 extra_body。一个 provider 的响应若改变了原生协议结构，仍需要实际 mapper，不能承诺任意新协议都靠 TOML 表达。

不增加 request-time 自动能力发现，不根据远端模型名 contains/startswith 猜测行为。

## 4. 模型选项：候选与选定值统一

### 4.1 三层来源，一次解析

```text
API mode 字段/映射规则
  + 专用 adapter / variant 的真实差异
  + model 的可用候选和少量组合限制
  → 一份有效选项投影
  → 配置校验、前端编辑、SDK mapper 共用
```

候选和当前值继续分开，但不再为 thinking、display、effort 各自发明一套复数命名。

拟使用 `adapter_options.choices` 统一保存模型候选；将现有 `reasoning_efforts` 迁入 `choices.reasoning_effort`，不保留旧字段别名。顶层 `model.reasoning_effort` 保持为实际选定值。其它已选值仍在 `adapter_options` 的原有字段中；“前端顶层常用控件”不等于所有 TOML 字段都迁到 model 顶层。

示意，省略 providers、窗口与 capabilities 等已有必填字段：

```toml
[llm.models.claude-sonnet]
family = "claude"
adapter = "anthropic-messages"
reasoning_effort = "high"

[llm.models.claude-sonnet.adapter_options]
thinking = "adaptive"
thinking_display = "omitted"
native_replay = "signed"
tool_choice_policy = "auto"
replay_prefix_binding = true
prompt_cache_mode = "automatic"
prompt_cache_ttl = "5m"

[llm.models.claude-sonnet.adapter_options.choices]
thinking = ["adaptive", "between_tools"]
thinking_display = ["summarized", "omitted", "updates"]
reasoning_effort = ["low", "medium", "high", "xhigh", "max"]

[[llm.models.claude-sonnet.adapter_options.choice_rules]]
when = { thinking = "between_tools" }
choices = { reasoning_effort = ["low", "medium", "high"] }
```

这是待实现的配置结构示例，不是可直接写进当前版本的配置。实际模板候选必须在实施时与对应 model binding/官方能力核实；`updates` 所需 beta header 由选项映射统一添加。

### 4.2 规则保持有限

- catalog 定义字段类型、API 层候选、requires/excludes 和映射位置；model 只能收窄已知封闭候选。effort 等可扩展字符串候选由 model 显式声明，不硬编码全局档位枚举。
- `choices` 缺省表示采用 adapter 的一般定义，不宣称已经认证远端型号；空数组表示该模型不支持此选项；单值数组表示固定值。固定必需行为需有对应默认/选定值，不能只隐藏控件。
- `choice_rules` 只支持已登记字段的等值条件和候选交集，不支持脚本、任意表达式、字段赋值或规则链。真实消费者是 between_tools/disabled 与 effort 的组合。一般依赖继续使用现有 catalog requires/excludes。
- 修改候选后，已选值失效则清空并提示重新选择，不悄悄改成第一档；不要保存旧值而仅改变显示。
- Google level 与 budget 的互斥检查针对实际已选值，不能因为定义了 effort 候选就禁止暂时使用 budget。
- `choices`、`choice_rules` 只参与配置和投影，绝不作为 SDK extra_body 发送。

“候选数组＋顶层选定值”的原思路保持不变；本轮只是把相同概念推广到其它选项，并补足候选列表不能表达的少量组合限制。

### 4.3 静态声明与动态读取

手工 TOML 是运行时唯一配置事实。当前 Anthropic Models API 已能返回部分 thinking 能力、effort levels 和 token limits；安装的 SDK `ModelCapabilities.effort` / `thinking` 也已有对应类型。可提供一个明确的“从该 binding 读取能力”编辑动作：

1. 用户选择一个已有 provider + 远端 model；后端只请求该 endpoint 的 Models API。
2. 返回能确认的候选/能力建议、来源 binding 和读取结果；不把缺失字段推断成支持。
3. 前端将建议与当前草稿比较，用户选择采纳后，仍沿已有保存 → TOML → reload 链路生效。
4. 多 provider binding 不自动合并能力；用户维护所有 binding 都能工作的共同配置，差异无法统一时定义另一个稳定 model。
5. 不支持 capability discovery 的兼容端点可继续手工编辑；OpenAI/Google 的模型列表不自动等价为完整 thinking/组合能力说明。

本轮只接入有官方字段的 Anthropic 读取；不建设四供应商能力数据库、轮询器或自动覆盖配置流程。入口属于现有 LLM 配置门面，由 Endpoint 转发，不在 Gateway 中解释供应商语义。

### 4.4 Request override 与 adapter option

- `temperature`、`top_p`、`max_output_tokens` 继续属于 RequestOverrides。
- thinking 类型/预算/display、effort 候选、native replay、缓存策略、verbosity、store 等属于 API/adapter options；effort 选定值保留现有顶层位置。
- `sampling` 是 mapper 如何处理 sampling 字段的策略，不是第二份温度或概率值。固定采样的专用协议在 catalog 中显示为固定/不可编辑。
- `tool_choice_policy` 是远端映射策略，允许 `native`、`auto`，Chat 需要时允许 `omit`；内部 REQUIRED/forced_name 的业务约束不变。
- JSON_OBJECT 继续是“完整回答可解析为 JSON object”，不新增严格输出 schema 协议。原生 JSON 参数仅在声明支持的组合中发送，否则使用既有提示和解析。必要的 `json_output_with_tools = "native" | "prompt"` 仅控制原生增强是否用于工具任务，不能放宽本地输出检查。

Anthropic 当前没有与 TinySoul 任意 JSON object 完全等价的原生模式，本轮继续用提示约束和本地解析，不为了勾选 JSON capability 临时构造空 schema 或伪造工具。`json_output_with_tools` 只向确实有原生 JSON mapper 的 API 暴露；Anthropic 的远端 structured_outputs 能力不能直接推导为该开关可用。

## 5. 推理回放与 Context 的实际关系

### 5.1 保持一个 NativeReplay

`Reasoning.summary` 供阅读；`NativeReplay` 保存原始有序 items 及其来源。encrypted、signed、reasoning_content 都属于同一个不透明回放附件，不恢复 ReasoningKeep，不建立第二条 provider 历史。

保留 `message_fingerprint`：它检查当前 AssistantMessage 的正文、工具 ID/名称/参数是否仍与原始输出对应。这有真实作用，因为 Trace 可能提供缩减投影；不能让旧不透明块覆盖已经变化的事实。

OpenAI encrypted、Google signed、Chat content 不增加全 Context 指纹。Google 保持 parts/signatures 的关联与顺序，Responses 保持 output items，不因无关 Working、sampling、cache TTL 或显示选项变化就一律抛弃回放。

### 5.2 Anthropic 前缀绑定：有证据的协议约束

最新 Claude preserved thinking 对部分模型绑定 system、tools 和 thinking block 前面的 messages。TinySoul 的构造式 Context 会更新 Background/Working、折叠 Trace；Phase 还会切换 tools，而原 TaskPrompt 不会自动成为下一次请求的永久历史。即使 AssistantMessage 完全未变，旧签名的前缀也可能不再成立。

因此不能承诺“选择 signed 就在每个 Phase 保留完整 Claude 推理”。这不是加一个指纹就能提升的能力：指纹只能发现失配，不能使失配的签名重新有效。

推荐保留 Context 的现有所有权与临时提示语义，并采用以下单一实现路径：

- model 声明 `adapter_options.replay_prefix_binding=true`，只用于确实有该约束的 Messages 模型；Claude 新模型模板显式声明。通用 Messages 同样可用，不要求 ClaudeAdapter。
- 在同一个 NativeReplay 中增加可选 `prefix_fingerprint`；仅声明前缀绑定的 Anthropic mapper 生成和消费，其他 API 不生成。
- 摘要取自本次实际映射的 system、tools 和原 assistant 输出之前的 messages。捕获和回放用同一规范化入口，保留内容、顺序、工具定义；不把本次 timeout、采样、TTL、HTTP header 等无关配置混进去。缓存标记只是传输注解，先完成 replay eligibility，再注入缓存 marker。
- 不另存一份请求正文。当前助手消息自身仍通过 message_fingerprint 校验；其内部 blocks 保持原顺序。
- 前缀失配时，Anthropic mapper 从该次发送投影中去掉失效的 thinking/redacted_thinking，并保留可合法表达的 text/tool_use/tool_result；后续依赖旧前缀的 thinking 同样不回放。不修改 Trace 持久事实，不伪造 signature，不发生隐藏的模型重试。
- 该检查属于避免真实签名拒绝的 adapter 协议条件，不是通用安全层，也不是全 Context CAS。

官方 `thinking.block_binding.prefix_mismatch_behavior=drop_block` 是另一条可行路径，且能返回 input_transformations；但 between_tools 不接受 block_binding，兼容 Messages endpoint 也不一定实现 beta。为避免一套请求同时做本地与服务端两份失配判断，本计划推荐统一用上面的 Anthropic 局部检查，不额外加入 server-drop 配置。若维护者希望优先使用官方 drop_block，应替换这一策略并讨论 between_tools 的合法路径，不叠加两个默认机制。

**待确认 D1：接受“按真实前缀有效性回放、失效时继续普通工具/文本事实”，还是要求改变 Context 为 Claude 保留 append-only 原始上下文。后者会改变 TaskPrompt 和 Context 的核心语义，不能在 adapter 内偷偷另存会话实现。** 本计划按前者设计。

### 5.3 工具与 JSON 的正常主线

- 所有 API 共用已有 `tool_replay_plan`：只有完整、连续、匹配的真实调用/结果集合才作为原生交换发送；不重排 Trace、不补造结果。
- signed 状态可用时完整回传，不根据 summary 是否为空判断可用性。
- 没有需要签名的输出时，Anthropic/Google 的正常工具调用可由内部 ToolCallRecord/ToolResultMessage 映射，不应为了关闭 reasoning replay 而一概降为文本。
- 已知必须带签名才能续接的调用，不能剥掉 signature 后伪装成同一次合法原生交换。失配时依对应 API 允许的普通事实投影处理。
- Anthropic 默认采用 auto tool choice 以保留 thinking；内部 REQUIRED 仍由 ResponseInterpreter 检查，缺少工具输出返回已有局部 TaskFailure，不变成供应商配置错误。需要原生强制时可选 native，并受模型实际能力约束。
- forced_name 保持现有内部选择语义，不把它擅自收窄成“只能返回一个指定工具”。Google/Anthropic 的远端强制名称映射需对照 interpreter 的真实约束修正。
- thinking=enabled 的 budget 与输出上限在有效请求组装后检查；between_tools 不发送 display/budget/block_binding；display=updates 使用正式字段和所需 header，不伪造 streaming 支持。
- JSON/tool 组合不自动修改用户的 thinking/effort。提示式 JSON 和原生 schema 保证明确区分；本轮不借此扩建输出 schema 系统。

## 6. Prompt cache：多断点与资源生命周期

### 6.1 内部意图与 Context 协作

将单一 `breakpoint_message_index` 改为不可变 `PromptCache.breakpoints`。每个 `PromptCacheBreakpoint` 只保存非空 `name` 和 `message_index`；`key` 保留为可选的不透明请求提示。

Context 每次 compose 后根据已有 provenance 提供候选：

```text
system + Session + Inputs + Home/Memory  ← background
              + 当前已呈现 TurnTrace    ← trace
              + plan/Workspace/连接状态   ← working
              + 本次 TaskPrompt          （不设 Context 默认断点）
```

Context 拥有这些名字和边界的语义；LLM 只理解命名的消息前缀，不导入 Kernel 的 slot enum。其他 SDK 调用者也可以声明自己的前缀名字。

- 边界随当前 MessageStack 重算，不跨 compose 保存 index，不建立 Context 缓存服务。
- 同一个消息位置合并；不存在的槽位不产生边界。Background 是通常复用较多的前缀，并非不可变内容；修正现有“整个 Turn 稳定”的注释。
- 模型 `prompt_cache_boundaries` 可选择候选名字，未设置时使用该 API 的默认策略；显式空数组表示只使用服务端自动/隐式缓存。不会为了模型配置要求而补造缺失的上下文。
- 无可用边界时照常生成：OpenAI explicit 不写显式缓存；Anthropic explicit 不写 marker；Google 不创建 resource。通过有限诊断说明“本次无可用前缀”，不把可选增强变成任务失败。
- 选定边界是最大前缀位置。adapter 在该位置或之前寻找合法的实际 wire block；不能越界把 TaskPrompt 纳入缓存，不能往签名 thinking 或不支持的 function_call 上强加 marker。
- 断点是累计前缀，不是独立段缓存；tools 或 Background 改变可能使后续所有缓存失效。模型窗口计算仍包含完整逻辑输入，不把缓存命中当作节省上下文窗口。

### 6.2 统一配置入口，保留 API 差异

| API | 配置及映射 | 本地状态 |
| --- | --- | --- |
| OpenAI Chat | implicit/explicit；可在 implicit 下标记候选前缀；当前核实的 TTL 为 30m | 无资源表；服务端拥有缓存 |
| OpenAI Responses | 同上，增加 12h；marker 支持普通内容和 function_call_output 的 input_text | 无资源表；store/previous response 不替代 TinySoul history |
| Anthropic | automatic/explicit/disabled；automatic 顶层 cache_control 可与显式 block markers 并用；5m/1h | 无资源表，不发 Google 式 cache create |
| Google GenerateContent | implicit 不创建资源；explicit 选择一个前缀创建 cachedContents，并只发送未缓存后缀 | 保持 generation-local 资源索引，远端 TTL 管过期 |

OpenAI/Anthropic 默认映射 Context 的至多三个候选，为自动断点保留一个槽位；显式 SDK 请求超过 API 上限应在 adapter 边界给出有限配置错误。按映射后实际位置去重；Anthropic 自动末尾与显式末尾的重复位置、TTL 冲突必须在发送前合并为合法请求。

模型设置保留 `prompt_cache_ttl` 作为默认寿命；增加 `prompt_cache_ttls` 按断点名字覆盖。只校验当前 API 支持的值，Anthropic 还校验实际前缀中长 TTL 不位于短 TTL 之后。

例如 Responses：

```toml
[llm.models.gpt-sol.adapter_options]
prompt_cache_mode = "implicit"
prompt_cache_ttl = "30m"
prompt_cache_boundaries = ["background", "trace", "working"]

[llm.models.gpt-sol.adapter_options.prompt_cache_ttls]
background = "12h"
```

默认 TTL 可维持 30m；12h 是显式可选值，不因为新功能存在就提高全部模板的缓存写入成本。Anthropic 可用 background=1h、其余5m；Google TTL 用秒，单资源不引入逐段 TTL。

### 6.3 key 不承担额外身份职责

PromptCache.key 由实际调用者按共享前缀需要提供；通用 OpenAI 和实际支持的专用协议发送，其他 API 不伪造同名字段。主循环不为了“看起来有缓存”生成随机 key 或强制每 Turn 独占 key。当前没有共享 key 策略消费者，因此不添加新的 key 生成器/设置。

服务端实际前缀匹配决定命中。key 不是 Context 指纹，也不是 Google cachedContents.name；思考状态不是 KV 缓存。

### 6.4 Google 显式资源

- 多候选中默认取最早可用的前缀；TinySoul 正常为 Background。用户可通过 `prompt_cache_boundaries` 为 Google 显式选择一个名字；不为每个 Trace/Working 更新创建三个独立资源。
- 选中的切分必须保留完整工具交换，且存在本次任务后缀；没有合适前缀则普通生成。system/tools/tool_config 随完整缓存前缀创建，生成时不重复发送。
- cache identity 使用真实 model、内容、system、tools 和相关资源配置；这是避免复用错误缓存内容的资源键，与 NativeReplay 的前缀检查无关。
- 缓存创建只使用 CreateCachedContentConfig 允许的字段与必要 transport 设置；generation extra_body 不复制进去。
- 正常周期为首次创建 → 本代复用 → TTL 过期后按需创建 → close 清本地索引。远端 TTL 回收资源，不加持久索引、后台续租、自动删除轮询或跨进程恢复。
- 已命名 cached resource 返回404时使其失效，并按可重试 provider failure 交给既有 TaskRunner 预算处理；只有确实使用了该 resource 的404适用。下一次尝试重新创建，不在 adapter 内套第二个重试循环。
- explicit 支持与阈值按真实模型声明/官方说明展示，不把隐式支持推导为显式支持；短输入/不支持型号的远端失败如实分类，不伪造命中。不增加无消费者的 min-token TOML 字段或本地 KV cache。
- `api_version` 继续属于 provider endpoint；不混入 Kimi variant 或模型 thinking options。

## 7. 专用 adapter 清理与配置对齐

| Adapter | 保留的实际职责 | 修改与验收 |
| --- | --- | --- |
| GPT | Responses 基础上的已确认 sampling 约束 | 通用 Responses 也能靠配置调用 GPT；避免与 base 重复删参数；cache/replay 不复制 |
| Kimi | k2/k3 请求差异、keep、工具名称及协议约束 | k3 replay=content 显示为固定有效值；k2.7-code 的 thinking/keep 固定限制写入模型候选；不按版本字符串猜测；验证原样 reasoning_content |
| DeepSeek | thinking、工具续接要求、实际采样和错误差异 | 复用通用 thinking 映射；tools 存在时保留所需历史 reasoning；top_p 保持型号差异，不全 family 一律删除；strict 依据实际 endpoint 支持，不能继续把 beta 限制写成永久全族禁用 |
| GLM | thinking.clear_thinking、do_sample 等真实扩展 | thinking 控制本次生成；clear_thinking 表达是否保留历史，继续从统一 native_replay 派生并展示有效映射，不再加矛盾独立开关；删除静态 request_id；仅在有实际消费者时接入逐请求 ID；5.1 不盲加 effort |
| MiniMax | Chat 兼容差异 | thinking 候选按型号为 adaptive/disabled；清除无依据 enabled；结构化接入固定 reasoning_split=true，删除可破坏 reasoning 分离的 false 控件；固定采样从 mapper/catalog 一致表达；effort 仅配实际支持型号 |
| Claude family | Messages 通用能力 + model 声明 | 默认用通用 adapter；新增 claude-opus/claude-fable 稳定 ID 配置范例，真实 binding/凭据可用时才进入运行链；不要求同名专用类 |

跨专用 adapter 的 root schema、工具数量/strict 参数约束，应先检查通用校验是否已有相同契约，再合并真实重复；不要为了“去重”把某家限制硬写入全 API mode。

`strict=false` 不等于启用 strict；只拒绝真实不支持的要求。需要 strict 的 task 不能悄悄删除约束。受支持的参数、固定参数和仅被远端忽略的参数在配置投影中区分，避免展示可调控件却始终不生效。

## 8. Google typed mapping 的具体修改

1. 从经校验的 options 构造明确的 ThinkingConfig/Content/Part 等 SDK 类型，不在业务路径传播任意 object 字典。
2. 将当前 2.31.0 的 alias 差异集中在 Google SDK 边界的单一转换函数：从已经验证的对象生成 API 所需 mapping。仅在 SDK 类型声明与已证明的 serializer 行为不一致处使用有说明的有限 cast，不把 dict 伪装成业务 typed 对象到处传递。
3. 保留 MockTransport 对最终 HTTP JSON 的断言：thinkingLevel/思考预算/includeThoughts、functionCall/functionResponse、systemInstruction、cachedContent。
4. signature bytes → JSON → SDK Part → HTTP 的往返逐字节验证，不能双重 base64；空 summary 与含 signature 的普通 text part 同样可回放。
5. 外部 URL 图片与 inline bytes 使用已有内部 ImagePart/ImageUrlPart；对实际支持的 Google 文件来源与请求字段做代表性测试，不增加隐式下载/上传资产生命周期。
6. 不只 mock 自己的 wrapper：真实 SDK transformer 必须进入测试。未来升级 SDK 后若 typed 直接输出正确 wire，删除这一个边界转换；不保留两条并行发请求路径。

本轮不迁移 Google Interactions，不把它冒充 GenerateContent；图片生成也不混入 reasoning/cache 协议改动。已有图像输入应进入代表性验证。

## 9. 前端效果与配置提交

沿现有 model editor 改进，不新增“自定义模型业务”或另一套保存机制：

- 模型卡片常用区呈现当前 thinking、effort、回放与缓存选择；高级区编辑候选、固定值说明、TTL 和少量真实扩展。
- 字段显示来源：API 模式 / 专用 adapter / variant / 当前模型。模型候选收窄后只显示有效值；固定值显示其含义，不显示假开关。
- effort 候选继续用逗号输入并保存为数组；同一候选编辑器复用于 thinking/display 等，不复制多套专用 UI。
- between_tools 会隐藏/清理 display 和预算，并收窄 effort；开启 Google budget 后清理已选 level，但不删除用户准备好的候选定义。
- 缓存区解释 automatic/implicit、显式边界和 Google 资源的实际差异；只有对应 API 支持时才显示 TTL/断点覆盖设置。不能把所有模式都画成同一个布尔开关。
- 配置读取、草稿、保存、TOML、激活继续走原链路。模型候选变更、dependent option 清理与当前选择作为一次草稿提交；后端最终校验。
- Anthropic 能力读取只提供可采纳的草稿建议，不自动写盘，不让打开设置页触发供应商请求。
- Observation 最多补充有效 replay 数/跳过原因、缓存模式/断点数/资源复用及真实 usage；不给模型正文塞签名、hash、resource name 或调试协议。
- 配置中的 signed/encrypted 只能说明请求策略，前端不能据此显示“已命中缓存”或“旧推理已使用”。命中以 SDK usage 为证，未返回指标保留 unknown，不补零。

## 10. 执行步骤、文件范围与验收

下面步骤均未实施。每一步完成时补充修改位置和证据，不用测试数量代替功能验收。

### P1：选项定义与解析

- [ ] `tinysoul/llm/adapter/catalog.py`：有效选项解析、choices/choice_rules、固定策略、通用 Chat thinking、tool choice/JSON 增强策略、各 API 缓存选项；将 API 固有依赖与模型限制分开。
- [ ] `tinysoul/llm/protocol/models.py`、`config/helpers.py`、`config/sections.py`：typed 模型候选声明、选定值检查、迁移 reasoning_efforts；直接构造和 TOML 入口保持同一不变量。
- [ ] `tinysoul/infra/config/catalog/models.toml` 及现有 LLM descriptor 投影：新的模型选项协议和字段文案，不在 Infra 复制 LLM 判断。
- [ ] `tests/llm/test_models_and_registries.py`、`tests/llm/config/test_config.py`、`tests/infra/config/descriptors/test_config_catalog.py`：只覆盖候选收窄、固定值、真实条件组合和结构化错误。

验收：新增普通 family 可只用通用 adapter 配置；候选/选值不一致在保存边界报明确 ConfigError；元数据不进入 SDK 请求。

### P2：回放与工具主线

- [ ] `protocol/reasoning.py`、`adapter/replay.py`：保留消息指纹，增加仅有实际消费者的可选 Anthropic 前缀摘要；不添加全模式 context_fingerprint。
- [ ] `adapter/anthropic/messages.py`、`payloads.py`：前缀绑定、思考类型/display、auto tool choice 和普通工具映射；有效签名完整回放，失效只处理本次发送投影。
- [ ] `adapter/google/payloads.py`、`adapter/history.py`、`adapter/openai/payloads.py`：统一完整工具交换判断；普通工具事实与 signed 附件的边界，保持跨 provider fallback 可解释。
- [ ] `kernel/context/signals.py`、Trace/Phase 消费点、`llm/execution/observation_payloads.py`：传输新增内部摘要字段；不把它变成 Context 状态机或可见提示。
- [ ] `tests/llm/adapter/test_messages_and_generate_content.py`、`test_provider_openai_sdk.py`、Context/Phase 协作测试：增加真实 compose → phase decision → trace → 下一次 SDK 请求的代表性路径。

验收：manual/adaptive Claude 能参加 REQUIRED 工具任务；当前模型/消息一致但前缀改变时不发送失效 thinking；Responses/Google 不因无关 Context 更新被过度禁用回放；未完成 Action 仍不被伪造成原生工具结果。

### P3：多缓存断点与生命周期

- [ ] `protocol/cache.py`、`adapter/common.py`：命名的多断点意图、无前缀的可选增强语义、有效索引检查。
- [ ] `kernel/context/engine.py`、`projection/composer.py`：复用 provenance 生成三个候选；检查 `kernel/loop/phases/phase1.py`、`phase2.py` 和 `kernel/action` 内部模型调用均传递当前 stack 对应意图。
- [ ] `adapter/openai/payloads.py`、`common.py`、`options.py`、`chat.py`、`responses.py`：marker 合法位置、Responses output block、implicit + explicit、Responses12h、TTL 覆盖与 key；避免分散重复组装。
- [ ] `adapter/anthropic/messages.py`、`payloads.py`：automatic + 多显式断点、TTL 顺序/去重，禁止向 thinking block 加 marker。
- [ ] `adapter/google/cache.py`、`generate_content.py`、`payloads.py`：单缓存前缀选择、分离 create/generate 选项、TTL、使用中资源404交还既有重试。
- [ ] 对应 adapter、`tests/llm/execution/test_task_runner.py`、Context provenance 测试：测试真实发送边界、同一任务缓存失效恢复及 close；不添加本地 KV 实现。

验收：三个累计前缀正确映射，Context 改动后 indices 重算；无边界任务正常调用；自动缓存并未被显式 marker 意外关闭；Google 同一前缀只创建一个资源。

### P4：专用模型与 SDK 边界

- [ ] `adapter/models/{gpt,kimi,deepseek,glm,minimax}.py`：按7节移除冗余映射/死字段/过时约束；typed options 与 catalog 同步。
- [ ] `adapter/google/generate_content.py` 及必要的同包转换函数：集中真实 SDK alias 转换；复用已有文件，只有职责确实无法容纳才新增文件。
- [ ] `adapter/factory.py`、`protocol/adapter_types.py`：仅在真实 adapter 构造需要时修改；不为 Claude 空壳而扩枚举。
- [ ] `tinysoul/assets/{development,standard}/configs/llm/models/*.toml`：统一候选结构、模型实际能力、固定行为和缓存策略；保留稳定 ID，不擅自升级用户 binding。
- [ ] provider 模板和 `.env.example`：仅为实际新 Claude 使用补必要 endpoint/key 说明；若尚无可用 binding，提供明确的配置范例，不塞进默认任务链。
- [ ] `tests/llm/adapter/test_api_modes.py` 及既有 SDK transport 测试：逐类 options → wire → response/replay 的小型矩阵，清除固化旧误解的断言。

验收：每个保留的可编辑字段有消费者；Kimi 固定策略可见，GLM 清理与生成语义分开，MiniMax reasoning 结构稳定；Google 最终 wire 正确。

### P5：Endpoint 与前端

- [ ] 现有配置 catalog/LLM 门面与 `gateway/endpoint/engine/configuration.py`：投影模型有效选项；增加按一个 provider binding 读取 Anthropic 能力的只读操作。
- [ ] `gateway/endpoint/http/{schemas,routes}/configuration.py`：结构化入参和响应，复用已有凭据解析和请求错误流程，不创建任意 URL/文件操作接口。
- [ ] `visualization/src/features/settings/models/LlmModelsPage.tsx`、`controls.tsx`、`ObjectEditor.tsx`、`objectEditing.ts`、`collectionDrafts.ts`：复用候选编辑组件、固定值、依赖清理、断点配置及能力建议采纳。
- [ ] `visualization/src/features/settings/draft/catalog.ts`、相关 API types/client、i18n：共享 catalog 协议的前端消费；不按 family 写另一套选项判断。
- [ ] 既有 `pages.test.tsx`、draft/catalog 与 object editing 测试：候选输入、切模式清理、保存后的 TOML 投影和重新载入。

验收：新增 Claude family 与新增其它 family 走同一流程；更改候选和选中值后可以一次保存；能力读取失败不丢草稿；用户能区分“配置策略”与“实际使用结果”。

### P6：文档与最终核对

- [ ] `docs/design/llm.md`：统一选项、回放有效性、增强能力和各 API 差异；只描述已经落地的事实。
- [ ] `docs/design/context.md`：候选缓存前缀来自现有投影、累计前缀限制、无平行历史。
- [ ] `docs/endpoint/configuration.md`、`events.md`：有效模型选项、能力读取和新增有限观察字段；与 Endpoint 同步提交。
- [ ] `reference/api_mode/{README,api-modes,sdk-and-current-code,implementation-notes}.md`：官方来源、SDK 版本、具体字段、已验证与未验证边界。
- [ ] `visualization/docs/design/config-coverage.md`：新的编辑覆盖与运行语义。
- [ ] 聚焦测试 → Fast → Full → typecheck；前端测试/build；改动 Python 文件 Ruff/import 和 `git diff --check`。失败按 owner 修正，不用兼容层或放宽断言通过。
- [ ] 逐项对照本计划及用户最初目标；实现、文档与必要验证全部完成后才标 done 并归档。

## 11. 验证设计

### 11.1 必须由本地测试证明

1. 每类有效 option 进入真实 SDK HTTP JSON，固定策略不能被 UI 假装修改。
2. signed/ encrypted/content 回放保持必要结构；消息改写、路由变化、工具结果缺失使用真实普通事实；仅 Anthropic 绑定前缀的模型做前缀检查。
3. 空摘要、redacted thinking、包含签名的非 thought part 不丢失；工具别名与调用 ID 仍关联正确。
4. Background/Trace/Working 三个候选在重建后与消息一致；模式不同但意图共用；Responses function output 的 marker 位置正确。
5. Google create/reuse/expire/404→既有重试/close 路径；extra_body 不泄漏到 caches.create；签名 bytes 往返正确。
6. Anthropic enabled+budget+REQUIRED、adaptive+REQUIRED、between_tools+effort、display=omitted/updates 的代表性有效/无效组合。
7. 一条真正经过 Context compose/Trace 的多轮路径，避免仅手工拼接 append-only messages 就宣布 Agent 推理回放全部完成。
8. 前端编辑→后端校验→写入 family TOML→再载入的代表性协作测试；同一契约不在各层重复做大快照。

### 11.2 有凭据时的有界外部验证

按用户已有授权，使用 `.env` 中实际可用 key；不输出凭据、签名、加密原文或大响应。先选能正常工作的具体模型，验证基础文本/图像输入/JSON，再做两次调用的工具续接、推理回放和足够长度的前缀缓存。设置有界输出，不无差别遍历全部付费模型。

阿里云 Token Plan 两个 endpoint 共用 ALIYUN_API_KEY，可验证同一 provider 配置的多 API mode：

- `https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1`
- `https://token-plan.cn-beijing.maas.aliyuncs.com/apps/anthropic`

记录兼容服务接受哪些字段与实际 usage；其不支持 Claude 签名、beta 或某种 thinking，不能据此删掉官方 Messages 能力。没有官方凭据的功能明确记录“SDK wire 验证通过，远端行为未验证”。请求成功不等于 cache hit；未满足最小长度、未返回统计或命中0分别如实记录。

## 12. 可行性、取舍和待确认项

整体可行：复用四个已接通 adapter、现有 model catalog、TOML 写入设施、Context provenance 和前端草稿；新增职责集中在有效选项解析、多断点映射及 Anthropic 的真实回放约束。无需重写 Agent/Turn 调度，不新增持久缓存系统。

主要成本在有序 wire 消息的回放与断点映射，以及模型条件候选的前后端一致性；不是 SDK 安装。现有 SDK 版本已能做本轮本地验证，Google 的具体 serializer 差异已复现，应封装而不是猜测修复。

必须诚实保留一个能力限制：构造式 Context 与新 Claude 的 append-only preserved thinking 存在实际张力。按 D1 推荐方案，正确调用和上下文事实优先，无法承诺跨 Phase 保留所有旧 thinking。提高这部分复用率需要另一轮讨论 Context/TaskPrompt，不属于偷偷扩展 adapter 的理由。

建议确认以下设计预览后实施：

- 统一 `choices` 替换单独 `reasoning_efforts` 字段，保留顶层选定 effort；有条件候选用有限规则。
- family 与 adapter 解耦；Claude 默认用 Messages 通用 adapter，不增加空壳类。
- 不做全局 context_fingerprint；仅为 Anthropic 已证实的前缀绑定保留同一 NativeReplay 内的局部摘要。
- 多个 Context 候选断点按 API 映射；只有 Google explicit 管远端资源索引。
- prewarm、全自动能力发现、Google Interactions、图片生成和第二套原生会话不在范围。

本稿为可实施方案，D1 尚待维护者确认；本轮不启动重构代码。D1 确认的是 Context 与回放的行为取舍；具体推荐实现为5.2节的本地前缀检查，不要求兼容 endpoint 实现 beta drop_block。

## 13. 官方依据

以下资料于2026-10-21核对；配置举例不是各型号永久能力承诺。

- [OpenAI Prompt Caching](https://developers.openai.com/api/docs/guides/prompt-caching)：新缓存选项、多断点、mode/TTL/key；本轮不采用旧 retention 参数与 prewarm。
- [OpenAI Reasoning](https://developers.openai.com/api/docs/guides/reasoning)：原生 Responses items 与 stateless encrypted replay。
- [Anthropic Thinking](https://platform.claude.com/docs/en/build-with-claude/thinking)：thinking 类型、display、effort 和型号差异。
- [Anthropic Tool Workflows](https://platform.claude.com/docs/en/build-with-claude/thinking-tool-workflows)：tool choice 与完整 thinking block 往返。
- [Anthropic Preserved Thinking](https://platform.claude.com/docs/en/build-with-claude/preserved-thinking)：前缀绑定、官方 drop_block 和压缩后行为；本计划选择局部检查，避免并行机制。
- [Anthropic Prompt Caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching)：automatic/explicit、断点与 TTL。
- [Anthropic Models Overview](https://platform.claude.com/docs/en/models/overview)：Models API 能力读取及其局限。
- [Google Thinking](https://ai.google.dev/gemini-api/docs/generate-content/thinking)：level/budget、summary 与有序 signature parts。
- [Google Caching](https://ai.google.dev/gemini-api/docs/generate-content/caching)：implicit、cachedContents、TTL 与支持型号差异。
- [Kimi Chat API](https://platform.kimi.com/docs/api/chat)：variant、keep、effort 与 reasoning_content。
- [DeepSeek Thinking](https://api-docs.deepseek.com/guides/thinking_mode/)：tools、reasoning_content 与按型号不同的 sampling。
- [GLM Chat Completion](https://docs.z.ai/api-reference/llm/chat-completion)：thinking、clear_thinking、effort、请求字段。
- [MiniMax OpenAI SDK](https://platform.minimax.io/docs/api-reference/text-openai-api)：thinking、reasoning_split、sampling 与型号差异。
