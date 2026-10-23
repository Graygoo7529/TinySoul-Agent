# 真实模型 API 测试与 Claude 代理接入

状态：done。2026-10-22 启动，2026-10-23 完成实现、真实 API 验证和本地门禁；计划已完成，待归档。

## 目标与边界

改进现有 external 模型测试，使图片、JSON、工具、推理回放和缓存具有真实行为断言；以模型为验证单位，每次只选择一条 provider binding。新增 token-advant 的 Anthropic endpoint 和三个已获确认的 Claude 绑定，使用现有 TOKEN_ADVANT_API_KEY 实测。继续使用通用 Anthropic adapter，不添加专属 adapter 或改写 Claude 官方协议语义。

上一轮独立验证完成 11 个模型的 60 次请求，但固定测试仍枚举九个模型，并存在仅检查字符串、工具名，以及只打印缓存统计的不足。本轮将稳定验证方法收敛到现有测试入口。

## 实施方案

1. standard/development 的 providers.toml 增加 `token-advant`，API 模式为 `anthropic-messages`，SDK 根地址为用户指定的 `https://tokenadvent.com`，凭据引用 `TOKEN_ADVANT_API_KEY`。作为可选服务默认关闭；前端沿既有配置机制启用。
2. 两套 claude.toml 的 fable/opus/sonnet 追加该 provider binding，保留现有官方 binding 和模型选项；Haiku 不添加不可用绑定。`.env.example` 已有对应变量，不重复添加。
3. external 测试在显式启用时从指定项目 TOML 收集模型，不在模块导入时读取项目配置。保留 `TINYSOUL_RUN_REAL_LLM_API`、`TINYSOUL_REAL_PROJECT_ROOT`；新增可选 `TINYSOUL_REAL_MODELS` 逗号列表和 `TINYSOUL_REAL_PROVIDER` 单一 provider。
4. 默认按模型绑定顺序选首个启用且有凭据的 provider；显式 provider 只测试其现有 binding，可在本次测试内临时启用，不改 TOML。未绑定、无凭据或不支持的能力明确 skip；非法模型/provider ID 直接报告配置错误。已经发出的真实请求失败就是失败，不转换为 transient skip，也不自动切换路由掩盖结果。
5. 按功能拆成独立用例：JSON 对象、图片内容、工具及结果往返、两轮原生推理回放、两次长前缀缓存。遵循模型 capabilities 和当前 adapter options；不强行将 MiniMax 等未声明 JSON 能力的模型判成 JSON 模式成功。
6. 共用有限的测试会话与 HTTP 请求观察器。通过现有 registry/factory 装配和关闭；观察真实 SDK 序列化后的请求体，保留在测试内存中，不输出 key、推理正文或完整请求。回放比较上一响应保留的非空原生内容是否真的进入下一请求，禁止仅以存在 NativeReplay 对象判成功。
7. JSON 经现有 ResponseInterpreter 解释并检查业务值；图片要求从限定基础色中选择，答案不在文字提示中；工具检查名称、参数和实际使用回传结果。保留完整 assistant 文本、工具调用和 reasoning，避免测试自身破坏签名绑定。
8. 缓存使用每用例唯一的长合成前缀和稳定 key，并提供 Background/Trace 边界；模型须从 600 条记录中分别查出两个随机六位码，再检查真实命中计数。该用例验证上下文使用和缓存，不重复要求 JSON 格式；JSON 有独立用例。显式/automatic Anthropic 缓存检查首次创建及后续读取；其它模式如不提供独立创建计数，明确说明其限制，不伪造资源创建证据。本轮不等待 TTL 到期，不扩展 Google 缓存资源生命周期测试。

## 改动清单

- `tests/llm/adapter/test_real_provider_api.py`：去除固定九模型数组及弱断言，加入模型/provider 选择与共用行为验证。
- `tinysoul/assets/{standard,development}/configs/llm/providers.toml`：可选 token-advant provider。
- `tinysoul/assets/{standard,development}/configs/llm/models/claude.toml`：三个 Claude 模型的额外 binding。
- `README.md`：真实模型测试的启用、模型筛选、provider 切换和结果解释。
- `tests/gateway/project/test_initializer.py`：生成契约检查所有 TOML 凭据引用均有空值示例，允许 `.env.example` 预留尚未绑定 provider 的 key。
- 本计划：保存真实验证证据、覆盖限制与最终核对。

## 验证与完成条件

- [x] 确认现有加载、异常、客户端生命周期与 SDK 请求观察方式，完成配置与测试改进。
- [x] 通过 token-advant 验证 Claude Opus、Sonnet、Fable 的图片、JSON、工具、推理回放、缓存创建及命中；有失败则准确记录并定位，不修改协议去迁就未确认的代理行为。
- [x] 用其它已有模型验证测试的通用性，覆盖 Chat、Responses 和 Qwen Messages；不遍历 provider 矩阵。
- [x] 同步 README，检查禁用时不读取项目或发送请求，以及模型/provider 筛选行为。
- [x] 运行聚焦测试、Fast、Full、typecheck、修改文件格式/import 与 diff 检查，以最终完整 Full 和 typecheck 通过作为本地完成门禁；记录中间失败及复核。
- [x] 逐项核对 AGENTS.md 和本计划，记录未验证项，完成后归档。

本方案复用现有模型能力、配置解析和 SDK adapter，不改变生产执行链、配置 owner 或失败语义。provider 选择仅是测试路由控制，目标仍是模型能力覆盖。若代理拒绝既有 Claude 配置，先保留失败证据，再判断是配置事实、测试构造还是 adapter 缺陷，避免添加隐式兼容分支。

## 实际验证与限制

测试使用当前仓库 common/development 资源组成的隔离项目，凭据从仓库 `.env` 注入测试子进程；没有修改开发运行目录，也没有把密钥写进临时 TOML 或文档。所有已发请求均由真实 registry/factory、adapter 和 SDK 完成。远端统计只描述这条 binding 的实际返回，不外推官方模型的计费或其它路由行为。

### Claude / token-advant

实际地址为 `https://tokenadvent.com/v1/messages`，使用 `TOKEN_ADVANT_API_KEY`。模型分别是 `claude-opus-5-5`、`claude-sonnet-5-5`、`claude-fable-5-1`。

| 模型 | JSON / 图片 / 工具往返 | 原生推理回放 | 专门缓存用例 |
|---|---|---|---|
| claude-opus | 均通过 | 未通过：未返回原生 thinking 状态 | 最终长前缀查阅通过，返回创建 69,472、后续读取 55,582 tokens |
| claude-sonnet | 均通过 | 通过：非空 thinking/signature 进入下一请求并完成回答 | 未通过：最终两次请求返回创建/读取均为 0 |
| claude-fable | 均通过 | 未通过：未返回原生 thinking 状态 | 未通过：最终两次请求返回创建/读取均为 0 |

Opus/Fable 又以十二步模运算独立复核：真实请求包含 `thinking={type:adaptive,display:summarized}`、`output_config.effort=high`、`stream=true` 和 8192 输出预算，仍未取得原生 thinking。测试没有用普通回答中的解释文字冒充可回放状态，也没有修改通用 adapter 或将 native_replay 关掉以绕过断言。此结果表示本次回放未验证成功，不证明官方模型或 adapter 不支持该能力。

缓存构造先从固定答案改为真正查阅长前缀；随后移除与缓存目标无关的 JSON 格式要求，独立 JSON 用例保持原断言。最终三个模型都查出了两个正确随机记录值，但只有 Opus 的专门缓存用例取得创建和命中。Sonnet 的工具往返曾返回非零缓存计数，不能据专门用例失败宣称完全不支持缓存；本次证据显示该路由的缓存统计/行为尚未稳定验证。Fable 首轮另有一次连接失败，原失败照实保留，复核未自动切换 provider。

Claude 首轮为 10 passed / 5 failed；最后的缓存定向复核为 1 passed / 2 failed。这些 external 失败是验证发现，不作为本地门禁通过，也不通过 skip、放宽缓存断言或兼容逻辑改成成功。

### 其它模型与选择机制

- Qwen Max/Flash，`qwen / QWEN_API_KEY`：五类用例 10 passed；最终独立长前缀缓存复核 2 passed，首次创建及下一次读取分别为 15,104 / 15,108 tokens。
- GPT 三个、Kimi 两个、DeepSeek 两个、GLM、MiniMax，默认路由均为 `orca / ORCA_API_KEY`：首轮 36 passed / 6 failed / 3 skipped，六个失败均为 JSON 请求连接失败；定向复核八个已声明 JSON 能力的模型全部通过。图片、工具往返和非空原生回放均在适用模型通过。
- 最终长前缀查阅缓存覆盖上述九模型：八个模型在同轮通过；GPT Terra 一次连接失败后定向复核 1 passed，创建/读取均为 10,852 tokens。所有模型均观察到重复前缀的非零命中；没有为远端连接失败自动增加重试或改成 skip。
- 三个能力 skip 分别为 MiniMax 未声明 JSON、DeepSeek Pro/GLM 未声明图片；没有更改模型能力来影响结果。
- 筛选验证：三个指定 Claude 模型收集到 15 个用例；未知 provider/model ID 均明确 UsageError；未开启真实 API 时，即使没有项目路径也只收集五个禁用用例，不读取配置或发请求。

### 本地门禁

- adapter 聚焦：132 passed，5 external deselected。
- Fast: 1,350 passed / 15 deselected; complete rerun passed.
- typecheck、真实 API 测试文件 Ruff/import/format 和 `git diff --check` 已通过。
- 首次 Full：1,353 passed / 2 failed / 10 deselected。除上述 SDK 等待超时外，生成测试要求 `.env.example` 与 TOML 凭据引用完全相等，与用户最新提交 `d551f4e config: update env examples` 中预留的 OPENCODE_API_KEY 不一致。修正生成契约为“必须覆盖所有 TOML 引用且示例均为空值”，允许预留凭据；不删除用户保留的 key，不为它虚构 provider。这是配置允许用户自行新增 provider 的既有语义，不是忽略缺失凭据引用。
- Final Full: 1,355 passed / 10 deselected; the rerun passed completely.
- SDK wait case isolated rerun: 1 passed / 36 deselected; the Full rerun also passed, without changing SDK tests or relaxing the wait assertion.

### AGENTS.md 核对

配置仍由 Infra 解析，模型/adapter 语义仍归 LLM；没有新增客户端全局状态、生产抽象或失败类型。测试共用同一会话、客户端关闭与观察逻辑，真实协议响应交给现有解释器；provider 只是可选择的测试路由，测试身份与断言围绕模型能力。仅缺少前提或遥测时明确 skip，已发请求的失败保留为失败。README 同步四类 SDK adapter 已执行的当前事实，没有把 MockTransport 或单次代理成功宣传为全模型/全 provider 覆盖。

### 2026-10-23 token-advant 定向复测

使用外部网络环境重新执行：

```powershell
$env:TINYSOUL_RUN_REAL_LLM_API = "1"
$env:TINYSOUL_REAL_PROVIDER = "token-advant"
$env:TINYSOUL_REAL_MODELS = "claude-opus,claude-sonnet,claude-fable"
```

本次 15 个请求得到 10 passed / 5 failed。Opus、Sonnet、Fable 的 JSON、图片和工具往返均通过；Sonnet 两轮原生推理回放通过，仍有 signed thinking/signature 进入下一请求；Opus 与 Fable 仍未返回可回放 thinking。缓存行为继续显示代理路由差异：Sonnet 首次创建约 57,293、二次命中约 57,422，但第二次回答内容为空；Opus 与 Fable 的长前缀查询分别返回截断/错误文本，缓存创建和命中均为 0。失败发生在真实响应语义或缓存遥测断言处，不是连接失败，也没有自动切换 provider 或放宽断言。

这次复测增强了“token-advant 对不同 Claude 模型的推理与缓存能力不稳定”的判断，但不能归因于通用 Anthropic adapter 缺陷：同一 adapter 已在 Sonnet 完成 signed replay 和缓存创建/命中，且三个模型的基础 JSON、图片、工具请求均正常。外部失败证据已保留，计划的实现、验证和 AGENTS.md 核对均已完成。


### Final gate

The final verification after the token-advant rerun passed: Full 1,355 passed / 10 deselected; Fast 1,350 passed / 15 deselected; the LLM adapter focus 132 passed / 5 deselected; Generation 5 passed / 1,360 deselected; typecheck, Ruff import/format, and git diff checks passed. The AGENTS.md audit is complete. The external token-advant failures remain recorded as provider behavior evidence, rather than being hidden by skips or relaxed assertions. This execution plan is complete.
