# LLM API 模式回放、缓存与专用 Adapter 复核改进执行计划

- 状态：`done`（P1–P6 及2026-10-22前端交互复核修复完成；实现、文档、AGENTS 规约与必要验证已核对）
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

上一轮归档计划保留历史验证记录。本计划已经获准实施；下文保留问题基线和已确认设计，第14节记录对应实现、验证及范围取舍。

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

这是已支持的配置结构示例，不代表所有型号都支持所列候选。实际模板按对应 binding 声明能力；`updates` 所需 beta header 由选项映射统一添加。

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

**D1 已确认：保持现有构造式 Context，Claude 推理前缀有效时回放，失效时丢弃失效 thinking、保留文本和工具事实继续调用。** 不改变 TaskPrompt 所有权，也不在 adapter 内另存 append-only 会话。

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
- 无可用边界时照常生成：OpenAI explicit 不写显式缓存；Anthropic explicit 不写 marker；Google 不创建 resource。不把可选增强变成任务失败，也不从配置选值伪造命中观察值。
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

模型设置保留 `prompt_cache_ttl` 作为默认寿命；Responses/Anthropic 支持 `prompt_cache_ttls` 按断点名字覆盖。Chat 只支持请求级 `30m`，其 marker 不携带 TTL；Google 为单资源秒数。Anthropic 还校验实际前缀中长 TTL 不位于短 TTL 之后。

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

下面按实际职责核对；文件列表代表需修改或检查的所有权范围，已存在且满足契约的组件直接复用。具体证据见第14节。

### P1：选项定义与解析

- [x] `tinysoul/llm/adapter/catalog.py`：有效选项解析、choices/choice_rules、固定策略、通用 Chat thinking、tool choice/JSON 增强策略、各 API 缓存选项；将 API 固有依赖与模型限制分开。
- [x] `tinysoul/llm/protocol/models.py`、`config/helpers.py`、`config/sections.py`：模型候选声明、选定值检查、迁移 reasoning_efforts；复用原 helpers 的动态边界转换。
- [x] `tinysoul/infra/config/catalog/models.toml` 及现有 LLM descriptor 投影：新的模型选项协议和字段文案，不在 Infra 复制 LLM 判断。
- [x] `tests/llm/test_models_and_registries.py`、`tests/llm/config/test_config.py`、`tests/infra/config/descriptors/test_config_catalog.py`：新增 owner 契约覆盖，复用原 descriptor 协作检查。

验收：新增普通 family 可只用通用 adapter 配置；候选/选值不一致在保存边界报明确 ConfigError；元数据不进入 SDK 请求。

### P2：回放与工具主线

- [x] `protocol/reasoning.py`、`adapter/replay.py`：保留消息指纹，增加仅有实际消费者的可选 Anthropic 前缀摘要；不添加全模式 context_fingerprint。
- [x] `adapter/anthropic/messages.py`、`payloads.py`：前缀绑定、思考类型/display、auto tool choice 和普通工具映射；有效签名完整回放，失效只处理本次发送投影。
- [x] `adapter/google/payloads.py`、`adapter/history.py`、`adapter/openai/payloads.py`：复用既有完整工具交换判断，补普通工具事实映射，不复制 history planner。
- [x] `kernel/context/signals.py`、Trace/Phase 消费点、`llm/execution/observation_payloads.py`：signal 往返内部摘要；既有 Phase/Trace 可直接携带该附件，Observation 不暴露摘要/签名。
- [x] `tests/llm/adapter/test_messages_and_generate_content.py`、`test_provider_openai_sdk.py`、Context/Phase 协作测试：实际 composer、Trace 决策记录与下一次 adapter 请求联动；Phase 信号协作复用原有 owner 测试。

验收：manual/adaptive Claude 能参加 REQUIRED 工具任务；当前模型/消息一致但前缀改变时不发送失效 thinking；Responses/Google 不因无关 Context 更新被过度禁用回放；未完成 Action 仍不被伪造成原生工具结果。

### P3：多缓存断点与生命周期

- [x] `protocol/cache.py`、`adapter/common.py`：命名的多断点意图、无前缀的可选增强语义、有效索引检查。
- [x] `kernel/context/engine.py`、`projection/composer.py`：复用 provenance 生成三个候选；Phase1/Phase2 沿原 stack/cache 数据流传递，独立 Action 任务无共享前缀时正常调用。
- [x] `adapter/openai/payloads.py`、`common.py`、`options.py`、`chat.py`、`responses.py`：改共用 mapper，Chat/Responses 复用；支持 marker 合法位置、Responses output、implicit + explicit、Responses12h、TTL 覆盖与 key。
- [x] `adapter/anthropic/messages.py`、`payloads.py`：automatic + 多显式断点、TTL 顺序/去重，禁止向 thinking block 加 marker。
- [x] `adapter/google/cache.py`、`generate_content.py`、`payloads.py`：单缓存前缀选择、分离 create/generate 选项、TTL、使用中资源404交还既有重试；复用原资源 store。
- [x] 对应 adapter、TaskRunner、Context provenance 测试：同一任务404恢复验证放在现有真实 SDK transport 测试中，直接调用 LLMTaskRunner；复用 expiry/close 覆盖，不复制 fixture。

验收：三个累计前缀正确映射，Context 改动后 indices 重算；无边界任务正常调用；自动缓存并未被显式 marker 意外关闭；Google 同一前缀只创建一个资源。

### P4：专用模型与 SDK 边界

- [x] `adapter/models/{gpt,kimi,deepseek,glm,minimax}.py`：移除重复 thinking 映射、无消费者类型和 GLM 静态 request_id；MiniMax 固定 split/采样，DeepSeek strict 按 beta endpoint；GPT 原有真实约束已满足，保持复用。
- [x] `adapter/google/generate_content.py`：集中真实 SDK alias 转换，复用已有文件。
- [x] `adapter/factory.py`、`protocol/adapter_types.py`：核对后无需增加构造分支或 Claude 空壳枚举。
- [x] `tinysoul/assets/{development,standard}/configs/llm/models/*.toml`：统一候选结构、固定行为与缓存策略；旧稳定 ID/binding 保留；新增 Claude 模板。
- [x] provider 模板和 `.env.example`：新增默认禁用的 anthropic endpoint、ANTHROPIC_API_KEY 与 Claude Opus/Fable 模板，不加入任务链。
- [x] `tests/llm/adapter/test_api_modes.py` 及既有 SDK transport 测试：options → wire → response/replay 代表性矩阵，清除旧字段断言。

验收：每个保留的可编辑字段有消费者；Kimi 固定策略可见，GLM 清理与生成语义分开，MiniMax reasoning 结构稳定；Google 最终 wire 正确。

### P5：Endpoint 与前端

- [x] 现有配置 catalog/LLM 门面与 `gateway/endpoint/engine/configuration.py`：增加一次 binding 的能力读取；SDK 与能力解释归 `llm/adapter/anthropic/models.py`，Endpoint 仅转发。
- [x] `gateway/endpoint/http/{schemas,routes}/configuration.py`：结构化请求/响应，复用凭据解析和有限请求错误，不创建任意 URL/文件操作接口。
- [x] `LlmModelsPage.tsx`：复用既有 TextInput/SelectInput/JsonEditor/FieldRow 及同一个 AdapterOptionRow；常用值、候选、固定值、依赖清理、断点配置及能力建议均走原草稿机制。其它 object editing 设施核对后直接复用。
- [x] `draft/catalog.ts`、API types/client、i18n：统一消费规则、候选交集与依赖清理；不按 family 特判。
- [x] `pages.test.tsx`、draft/catalog、Endpoint 与 Infra ConfigController 测试：候选输入、模式切换、显式读取/采纳、同批 TOML 保存和重新载入。
- [x] 2026-10-22 复核修复：adapter 切换确认提供保留兼容选项或重置；候选按目标规则整理；能力查询的迟到成功/失败/结束回调不能影响其它编辑对象。实施及验证见14.4。

验收：新增 Claude family 与新增其它 family 走同一流程；更改候选和选中值后可以一次保存；能力读取失败不丢草稿；用户能区分“配置策略”与“实际使用结果”。

### P6：文档与最终核对

- [x] `docs/design/llm.md`：统一选项、回放有效性、增强能力和各 API 差异；只描述已经落地的事实。
- [x] `docs/design/context.md`：候选缓存前缀来自现有投影、累计前缀限制、无平行历史。
- [x] `docs/endpoint/configuration.md`：有效选项与能力读取同步。既有 usage/replay 安全投影已满足展示，不新增观察事件，`events.md` 无需改协议。
- [x] `reference/api_mode/{README,api-modes,sdk-and-current-code,implementation-notes}.md`：最新复核说明与历史调查区分，来源与未验证边界明确；初始 SDK 调查保留历史事实。
- [x] `visualization/docs/design/config-coverage.md`：新的编辑覆盖与运行语义。
- [x] 聚焦测试 → Fast → Full → typecheck；前端测试/build；改动 Python 文件 Ruff/import 和 `git diff --check`。失败按 owner 修正，不用兼容层或放宽断言通过；Ruff 既有诊断范围见14.3。
- [x] 逐项对照本计划及用户最初目标；实现、文档与必要验证全部完成，已标 done 并归档。

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

已确认并实施以下设计：

- 统一 `choices` 替换单独 `reasoning_efforts` 字段，保留顶层选定 effort；有条件候选用有限规则。
- family 与 adapter 解耦；Claude 默认用 Messages 通用 adapter，不增加空壳类。
- 不做全局 context_fingerprint；仅为 Anthropic 已证实的前缀绑定保留同一 NativeReplay 内的局部摘要。
- 多个 Context 候选断点按 API 映射；只有 Google explicit 管远端资源索引。
- prewarm、全自动能力发现、Google Interactions、图片生成和第二套原生会话不在范围。

D1 已获明确确认并实施5.2节的本地前缀检查，不要求兼容 endpoint 实现 beta drop_block。本轮没有未解决的设计决策项；以最终门禁和第14节逐项审计决定完成状态。

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

## 14. 实施核对与验证记录

### 14.1 与最初目标逐项核对

| 目标 | 实施位置与可观察效果 | 验证依据 |
| --- | --- | --- |
| API mode → 通用 adapter → 专用差异 | `adapter/catalog.py` 组合 API、adapter、variant；通用 Chat 可配置 thinking、tool/JSON 增强策略；其它通用模式复用同一 options 契约 | `test_api_modes.py` 检查通用 options 的真实 SDK HTTP JSON；registry 共用 client/关闭契约沿用 |
| 模型候选与实际选值统一 | `AdapterOptions` 校验 choices 和有限 choice_rules；顶层 effort 与其它选值一起参与条件判断；候选元数据不进入请求 | `test_config.py::test_model_choice_rules_intersect_selected_values` 覆盖有效组合、条件交集、空候选和顶层 effort 条件；前端 `catalog.test.ts` 验证同样的清理行为 |
| 干净统一的回放协议 | 同一 `NativeReplay` 承载 content/encrypted/signed；消息指纹检查保留；只有配置了绑定的 Anthropic 附可选 prefix_fingerprint | composer/Trace 协作测试证明：追加且前缀一致时保留完整签名；重新构造 Context 后丢失效 thinking，文本和真实工具交换继续；原附件不变 |
| 四 API 的思考/工具映射 | Anthropic 默认 auto 保留 thinking，内部 REQUIRED 仍由 interpreter 检查；enabled budget、adaptive omitted/updates、between_tools effort、disabled 都有 SDK 路径 | `test_messages_and_generate_content.py` 的真实 SDK MockTransport；updates header、选定 effort、空摘要签名与 tools 往返均有断言 |
| Context 多缓存前缀 | `ContextEngine.prompt_cache` 每次根据 provenance 产生 background/trace/working；Phase1/Phase2 和 Action-owned tasks 继续沿原入口传递 | `test_composer.py` 覆盖三个当前 index；无 TaskPrompt 默认断点，无新 Context 状态或缓存服务 |
| OpenAI 缓存真实落点 | Chat marker 只有 mode；Responses 支持12h和逐断点 TTL，function_call_output.output 转成合法 input_text；implicit 可叠显式标记，向前寻找合法位置并去重 | `test_provider_openai_sdk.py` 与 `test_api_modes.py`；回放内容在标记前复制，不修改保存的原生附件 |
| Anthropic 缓存组合 | automatic 与多个显式 markers 复用实际 block 顺序；不标记 thinking；重合末尾显式 TTL 优先；总位置数与长短 TTL 顺序校验 | 真实 SDK 测试证明显式1h + 自动5m、重合末尾合并、反向 TTL 在发请求前形成 CONFIG |
| Google typed mapping 与资源生命周期 | typed Content/Part/ThinkingConfig；仅 SDK2.31 alias 差异在一处转换；create 不复用 generation extra_body；TTL/404/close 沿原资源 owner | 真实 SDK 测试覆盖 bytes/signature 往返、工具交换不断开、create/reuse/expiry、同一 TaskRunner 内404重建、implicit 不创建资源 |
| 专用 adapter 清理 | Kimi 固定采样、k3 content replay；DeepSeek 共用 thinking、保留 top_p、beta strict；GLM 清历史从 replay 派生，删除静态 request_id；MiniMax adaptive/disabled、固定 split=true、固定采样/工具策略；GPT 保留真实采样差异 | 既有各专用 adapter 测试更新到现行语义；新增 DeepSeek beta strict 正例；无 family 名称猜测或空壳 ClaudeAdapter |
| TOML、Endpoint、前端共同落地 | development/standard 迁移 choices；新增 `claude.toml` 和禁用的 anthropic provider；能力读取经 LLM owner 后由 Endpoint 返回，采纳进入既有草稿 | Endpoint 验证能力查询协议；`test_config_controller.py::test_family_models_and_task_references_save_and_reload_together` 验证候选、规则、选值、family 文件及任务引用同批保存/重新加载；前端验证打开页不触网、显式读取不改草稿、采纳后清理无效选值 |

### 14.2 实施取舍与未扩展范围

- 没有修改 AGENTS 的核心定义：LLM 仍只解释调用，Context 仍纯构造，Trace 仍拥有事实，TaskRunner 仍独占重试。模块失败经 ProviderError 及既有 bridge/Endpoint 请求错误处理；本轮没有新增 Trap 原因。
- `adapter/history.py`、factory、adapter enum、Google cache store、Phase/Action task 传递、前端对象保存设施已经满足职责，核对后直接复用。计划中列出的这些文件不必为了产生 diff 而修改。
- Anthropic Models API 的 SDK 读取新增在 `llm/adapter/anthropic/models.py`，职责为一次显式能力查询；通过现有 LLM 配置门面暴露。Endpoint 不解释远端 capability，也不持有第二套长生命周期客户端。
- 条件规则始终是等值条件和候选交集，不做字段赋值或自动挑选下一档。前端 effort 编辑与其它 options 共用归一化，Google level/budget 只清实际冲突选值，保留候选定义。
- 未增加新的 Observation 事件或回放日志。现有 safe replay 摘要和真实 usage 继续供界面观察；配置 signed/explicit 不展示为“已经复用/命中”。没有实际消费者的逐断点运行统计不进入本轮。
- Claude 模板使用稳定 ID `claude-opus`/`claude-fable`，binding 为官方文档核对的 `claude-opus-5-5`/`claude-fable-5-1`。默认 provider 禁用，不写入任务链；保守声明 adaptive/high，额外候选可手工配置或从指定 binding 读取后采纳。
- prewarm、Interactions、图片生成、全局 context_fingerprint、后台续租、本地 KV、崩溃缓存恢复和新的原生会话历史均未引入。图像输入沿现有 typed message/SDK mapper 保留。
- 全文检索确认当前源码、模板、测试、设计与 Endpoint 文档不再使用 `reasoning_efforts`、单一 `breakpoint_message_index` 或 `ReasoningKeep`；历史归档保留当时表述，不提供兼容别名。

### 14.3 验证结果与实际边界

- SDK 环境：OpenAI3.35.1、Anthropic1.15.0、google-genai2.31.0；真实 SDK 通过本地 HTTP MockTransport 验证最终请求，使用假 key，不发送真实付费请求。
- Fast：1319 passed、28 deselected；后续新增代表性条件/SDK 测试另行聚焦验证37 passed；family TOML 与配置激活协作测试15 passed。
- Full：`scripts/test.ps1 -Suite Full`，1332 passed、23 deselected，228.09s；包含项目生成与 wheel 安装验收，不包含 external。
- `scripts/typecheck.ps1`：通过（Python3.13.12、ty0.0.84）。前端 `pnpm test`：94 files、814 passed；`pnpm build`：TypeScript 与 Vite 构建通过，仅有现存 chunk 体积提示。
- Python 改动文件 import 检查和 `git diff --check` 已通过；改动的 LLM 代码 Ruff 通过。Ruff 对照 HEAD 无新增诊断，既有 PageOptions 默认参数和测试 helper 等诊断未混入本轮清理；未宣称整个仓库 Ruff 零诊断。`agent/composition/builder.py` import 排序已合规，无需再次修改。
- 本轮没有远端 provider 实测结论。已证明本地选择、序列化、响应读取、资源生命周期和重试协作；不把模拟 usage 当成真实缓存命中，不宣称每个兼容服务都接受全部官方能力。Google 官方资源阈值、Claude 真实签名校验与具体代理能力仍以所选端点实际返回为准。

2026-10-21 实施核对：当时已确认范围完成；后续复核发现并补充修复的前端交互缺口见14.4。真实 provider 结果属于上述明确的外部验证边界，不以本地 SDK 测试代替实测结论。

### 14.4 2026-10-22 前端交互复核与修复

复核 `73ca07e` 时独立复现两项 P5 缺口：切换 adapter 只按字段名保留候选，可能留下目标不支持的值并导致保存失败；查询模型 A 的能力期间切换到模型 B，A 的迟到结果仍可被采纳到 B。维护者确认复用现有切换弹窗、允许选择保留兼容选项或重置，并用组件内请求有效性处理异步结果。本次修改基于包含提示词工作提交的 `266ee45`，没有修改提示词及后端业务实现。

- `draft/catalog.ts::retainAdapterOptions` 负责切换时的整理，然后复用 `normalizeAdapterOptions` 处理当前选值和依赖。普通值按目标 catalog 类型、候选及下界筛选；候选保留交集；条件规则整条保留或丢弃，不删条件扩大作用范围；固定字段使用目标定义。显式空候选仍表示不支持，原候选全部不适用时移除旧声明。extra_body、断点 TTL 覆盖等对象选项清除后重新配置。
- `LlmModelsPage.tsx` 每次切换 adapter 都先确认，默认勾选保留兼容选项；取消勾选时清除旧选项、候选、规则与顶层 effort，仅建立目标所需 variant。无效选值清除，不自动选择其它档位。切换 variant 复用整理逻辑，兼容 provider bindings 和配置草稿保存流程沿用既有实现。
- 能力查询只增加组件内请求序号；模型、adapter、binding、连接变更及退出组件使旧请求失效。旧请求的成功、失败与 finally 均不修改当前页面状态；不增加后端接口、请求重试或全局状态机。
- `catalog.test.ts` 覆盖候选交集、整条规则、固定/对象选项清理、显式空候选与 effort；`pages.test.tsx` 覆盖确认前不写草稿、保留/重置两种路径，以及切换模型后的迟到成功、修改 binding 后的迟到失败不干扰正在进行的新查询。
- `visualization/docs/design/config-coverage.md` 同步实际编辑语义。按 AGENTS 核对，配置 owner 与最终校验仍在后端，前端只管理编辑草稿和查询展示；本轮不改变 API mode、NativeReplay、Context 或缓存生命周期。

验证：聚焦前端 41 passed；前端完整 94 files、820 passed；`pnpm build` 与 Python typecheck 通过。`scripts/test.ps1 -Suite Full`：1332 passed、23 deselected，298.21s；包含上一轮复核曾偶发失败的 execution UTF-8 用例，本次通过。`git diff --check` 通过。前端测试既有 jsdom/act 提示与构建 chunk 大小提示不影响通过结果；本次没有真实 provider 调用。

最终核对：本次确认的两项交互缺口已关闭，P5/P6 的补充验收完成；无需新增设计决策、配置协议或后端状态机。四类 API 模式的远端验证范围仍按14.3说明。
