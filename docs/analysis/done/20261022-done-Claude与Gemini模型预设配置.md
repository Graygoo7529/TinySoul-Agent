# Claude 与 Gemini family 预设配置

- 日期：2026-10-22
- 状态：done
- 范围：development / standard 项目模板、共享密钥示例；沿用现有 API mode、通用 adapter、模型 choices 和 TOML 配置链路。

## 设计与配置

内部 ID 保留项目当前的 family 前缀，后缀使用维护者指定的稳定名称。版本只出现在 provider binding 中，不随模型升级修改任务链引用。模型都默认展开，已有 Claude 文件补齐四个模型，新增 Gemini family 文件；通过既有 models/*.toml 自动加载。

| 内部 ID | 远端模型名 | 默认思考强度 | 思考候选 |
| --- | --- | --- | --- |
| claude-fable | claude-fable-5-1 | high | low / medium / high / xhigh / max |
| claude-opus | claude-opus-5-5 | high | low / medium / high / xhigh / max |
| claude-sonnet | claude-sonnet-5-5 | high | low / medium / high / xhigh / max |
| claude-haiku | claude-haiku-5-5 | medium | low / medium / high / xhigh / max |
| gemini-argon | gemini-4-argon | medium | low / medium / high |
| gemini-pro | gemini-3.1-pro-preview | high | low / medium / high |
| gemini-flash | gemini-3.8-flash | medium | low / medium / high |

Opus 保留现有 high；其他新增模型按模型定位及官方默认值选择。Gemini Pro 的官方绑定仍是 preview，内部稳定名称不代表远端版本已经稳定发布。输出预算继续由任务配置决定，主循环当前 32768 tokens；不把模型最大输出上限写成每次任务的固定预算。

### Claude

- 共用 anthropic-messages；family 本身不需要增加无额外职责的专用 adapter。
- 默认 adaptive、summarized、signed 和 replay_prefix_binding。构造式 Context 继续按现有实现回放有效 thinking；前缀变化则移除失效 thinking，保留文本和工具事实。
- Fable / Opus 只开放 adaptive；Sonnet 允许 between_tools；Haiku 允许 disabled。后两者的低思考模式通过 choice_rules 将 effort 限制到 high 以下（含 high）。
- thinking_display 沿 API catalog 的 requires，只在 adaptive 下配置；切换到 between_tools / disabled 时需移除 display。Fable / Opus / Sonnet 可选 updates；Haiku 预设只声明明确使用的 summarized / omitted。
- 省略 temperature / top_p，避免任务采样配置触发远端拒绝。默认 auto 工具选择，实际必需工具仍由 TinySoul 的任务解释契约校验。
- 缓存沿用 automatic + 5m，并保留 Background / Trace 显式断点；缓存命中取决于真实前缀和远端最小长度。
- 上下文 1000000；仅声明 TinySoul 已支持的文本、图片、远程图片 URL、JSON 对象回答、工具、推理和缓存能力。JSON 对象约束沿现有 Anthropic 提示与本地解释路径，不伪造原生 JSON Schema。

### Gemini

- 共用 google-generate-content；新增 google provider，以 GEMINI_API_KEY 连接 generativelanguage.googleapis.com，endpoint 指定 v1beta。
- 默认 signed、include_thoughts=true、implicit，声明工具与原生 JSON 输出；不创建显式缓存资源。Pro / Flash 仍允许用户选择 explicit；Argon 的 choices 只允许 implicit。
- 省略采样参数：Argon 忽略这些参数；Gemini 3 使用服务默认温度，避免继承任务的 0.3。
- 上下文 1048576；Argon 的输入、思考和输出共用该窗口。当前同步 GenerateContent 不声明后台 long decode 能力。
- 图片使用上层准备的字节。当前远程 URL 映射直接发送 FileData，官方图片示例区分上传后的 File URI 和下载后内联的普通 URL，因此预设不宣称任意 image_remote_url 能力。
- Google 最新文档主推 Interactions API，但仍提供 GenerateContent 的相关模型说明；本次配置接入复用已经实现的 GenerateContent，不建立新的会话所有权或调度流程。

## 文件与生效

- tinysoul/assets/{development,standard}/configs/llm/models/claude.toml：补齐模型、默认值和候选约束。
- tinysoul/assets/{development,standard}/configs/llm/models/gemini.toml：新增三个模型。
- tinysoul/assets/{development,standard}/configs/llm/providers.toml：新增可选 Google provider，默认关闭。
- tinysoul/assets/common/.env.example：推理模型区增加 GEMINI_API_KEY。
- 以上是项目初始化模板；已存在项目继续通过自己的配置页或 configs/llm TOML 编辑并应用，不由模板修改自动覆盖。
- 配置投影、family 筛选、顶层思考强度选择和 adapter options 使用现有机制；不增加接口、前端组件或隐藏固定模型表。

## 核对

- [x] 官方模型 ID、思考模式 / 档位、采样与缓存限制核对。
- [x] 两套模板同步，Google provider 与共享密钥示例齐备。
- [x] 生成两套项目并解析配置；七个模型配置完全一致，Sonnet / Haiku 条件档位与 Argon 缓存限制按预期接受或拒绝。
- [x] 七个预设均通过真实 Anthropic / Google SDK 的本地 HTTP 序列化检查：远端绑定、思考强度、摘要、签名捕获、采样省略、工具选择、Claude 自动缓存和断点、Google JSON 与隐式缓存。未发起付费远端调用，不宣称已验证账号可用性或实际缓存命中。
- [x] 配置 / Anthropic / Google adapter 聚焦测试 38 passed；Full 1338 passed、23 external deselected；typecheck 通过；git diff --check 通过。
- [x] 按 AGENTS.md 核对并归档：仅扩展 TOML 预设与密钥示例，不增加 owner、隐式状态、兼容别名或异常流程。现有 docs/design/llm.md 的模型来源、family、稳定 ID 与 adapter 边界继续准确，Endpoint 协议无需变更；本记录保存版本绑定与验证依据。

## 官方依据

查阅日期为 2026-10-22；模型版本与候选是可编辑预设，不做版本号快照测试。

- [Claude 模型概览](https://platform.claude.com/docs/en/models/overview)：模型 ID、窗口、定位和默认值。
- [Claude thinking](https://platform.claude.com/docs/en/build-with-claude/thinking)、[effort](https://platform.claude.com/docs/en/build-with-claude/effort)：各模型模式、强度、display、采样和工具限制。
- [Claude preserved thinking](https://platform.claude.com/docs/en/build-with-claude/preserved-thinking)、[prompt caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching)：签名回放与前缀缓存语义。
- [Gemini Argon](https://ai.google.dev/gemini-api/docs/models/gemini-4-argon)、[最新模型指导](https://ai.google.dev/gemini-api/docs/latest-model)：窗口、采样、思考强度与隐式缓存。
- [Gemini Pro](https://ai.google.dev/gemini-api/docs/models/gemini-3.1-pro-preview)、[Gemini 3 指导](https://ai.google.dev/gemini-api/docs/gemini-3)、[Gemini Flash](https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash)：绑定名、温度建议、能力和档位。
- [GenerateContent thinking](https://ai.google.dev/gemini-api/docs/generate-content/thinking)、[缓存](https://ai.google.dev/gemini-api/docs/generate-content/caching)、[结构化输出](https://ai.google.dev/gemini-api/docs/generate-content/structured-output)、[图片](https://ai.google.dev/gemini-api/docs/generate-content/image-understanding)：当前 API 模式的映射依据。
