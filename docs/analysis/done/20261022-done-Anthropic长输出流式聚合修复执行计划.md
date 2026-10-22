# Anthropic 长输出流式聚合修复执行计划

状态：done。2026-10-22 完成内部流式聚合、真实 SDK 测试迁移、设计文档同步和本地/代理验证，并基于 AGENTS.md 与实施情况逐项核对归档。前端两个字段名称在前一轮已完成。

## 目标与范围

解决 Anthropic Messages 在较大输出预算下，于 HTTP 请求前抛出 `Streaming is required for operations that may take longer than 10 minutes.` 的问题。adapter 统一使用 SDK 流式传输并聚合完整 Message，继续返回现有 `RawResponse`。

这属于供应商适配边界的传输实现。LLM Task 继续获得一次完整结果，Context、工具执行、推理回放、Endpoint 和前端不增加增量消息协议。输出预算仍由任务、单次调用与模型覆盖配置确定；不通过降低预算、强设超长 timeout 或新增重试层绕开 SDK 检查。

前一轮已完成前端命名，澄清两种不同配置：

| 配置 | 原名称 | 本轮修改 | 实际语义 |
| --- | --- | --- | --- |
| `adapter_options.output_token_field` | 输出上限字段 | 输出上限请求参数名 | OpenAI Chat 兼容请求使用的外部参数名，如 `max_tokens` |
| `request_overrides.max_output_tokens` | 覆盖输出预算 | 输出预算值覆盖 | 选择该模型时覆盖任务输出预算的数值 |

## 已核对的现状与原因

1. 已重新阅读根 `AGENTS.md`，对照 LLM 的供应商边界、TaskRunner 重试与取消、Registry 客户端所有权和现有设计文档。本次改动只调整已有职责内的调用与失败归类。
2. `turn-trace-2026-10-22-7.zip` 的 Phase1 使用 `claude-haiku`，最终输出预算为 32768。此前以归档的 26 条消息、6 个工具经过真实 adapter、禁止发送网络请求，已复现 SDK 在 HTTP 前抛出长请求 `ValueError`，被任务边界归为 `llm.internal_failure`。
3. 当前 `AnthropicMessagesAdapter.invoke()` 使用 `messages.create()`；factory 创建 `AsyncAnthropic` 时使用默认 timeout、`max_retries=0`。当调用方没有剩余时限时，adapter 不传 timeout，触发 SDK 对非流式长请求的检查。32768 是本次请求预算，不是 adapter 声明的模型最大输出能力。
4. 本地 `anthropic==1.15.0` 已提供异步 `.stream()` 与 `.get_final_message()`；`pyproject.toml` 已要求 `anthropic>=1.15,<2`。修复不要求新增依赖或升级 SDK。
5. 当前真实 SDK 测试使用 4096 预算和显式 15 秒 timeout，成功响应也是一次性 JSON；这些测试没有覆盖本次失败条件，需要迁移为 SSE 响应并补足无显式 timeout 的较大预算用例。
6. SDK 的 `.stream()` 是同步创建异步 context manager 的方法；不能把它声明为 `async def stream()`。SDK 负责消息块、工具参数 JSON 分片、thinking/signature 与最终 usage 聚合。

本轮使用真实 SDK 与本地 `httpx2.MockTransport` 进行了无凭据、无网络的探查：

| 探查 | 实测结果 | 对修复的影响 |
| --- | --- | --- |
| `max_tokens=32768`，不传 timeout，通过 `.stream()` 消费完整 SSE | 请求实际进入 MockTransport，body 含 `stream=true`，返回完整 Message | 主方案可行，保留原预算 |
| `temperature/top_p` 经 SDK `extra_body` 发送 | 请求体保留数值 | 当前 1.15.0 的 `create/stream` 参数表均没有这两个直接形参，需要补齐 adapter 映射 |
| HTTP 200 后返回 `overloaded_error` SSE | SDK 抛 `APIStatusError`，`status_code=200` | 只按 HTTP 状态码会归为 UNKNOWN；需读取有限的结构化错误类型 |
| 有正文但尚无最终 `message_delta` 就结束 | SDK 返回 `stop_reason=None` 的部分 Message | 最终结果需一个完成性检查，不能把部分工具意图当成功结果 |
| 空 SSE 响应 | `get_final_message()` 抛 `AssertionError` | 在 SDK 聚合边界归为响应解析失败，不能变成框架内部失败 |

这些探查验证 SDK 的本地行为，不代表远端代理已通过流式验收。

## 设计

### 1. 单一路径完成调用

`MessagesClient` 从 `create` 协议改为 `stream` 协议，直接引用 SDK 的异步 stream manager 类型，不增加业务流对象或新的传输抽象。所有 Anthropic 请求走同一条调用路径，避免按预算切换两份实现。

```python
async with self._messages.stream(**kwargs) as stream:
    response = await stream.get_final_message()
```

请求参数仍由当前 adapter 与 payload mapper 构造。SDK 聚合成功并释放本次流后，复用现有完整 Message → RawResponse 转换：

- 文本、JSON 对象输出解释继续走现有逻辑。
- 工具名称还原、完整 arguments 与调用 ID 继续生成 `ToolCallRecord`；不消费半成品工具参数，不引入 SDK tool runner。
- thinking、signature、redacted thinking 及其它已保留的 ordered blocks 继续由现有 NativeReplay 捕获；前缀校验与失效回放策略保持原 owner 负责。
- `stop_reason` 沿用 COMPLETE、TOOL_CALLS、OUTPUT_LIMIT、CONTENT_FILTER、INCOMPLETE 等映射。服务以 `max_tokens` 正常结束仍是 OUTPUT_LIMIT，不是传输中断。
- usage 使用 SDK 聚合后的累计值。input、output、cache read/create 保持现有定义，不逐事件重复累加。

### 2. 保留请求配置的真实效果

max_tokens、thinking、effort、display/header、tools、cache_control、显式断点等继续通过 SDK 正式参数传递。

采样由现有 `sampling` 决定：`omit` 时不发送；其它情况将 `ProviderRequest.temperature/top_p` 的已选数值放入 adapter 构造的 SDK `extra_body`，并合并经过现有 catalog 校验的用户扩展字段。用户配置的 `extra_body` 仍不能覆盖 temperature、top_p、stream、max_tokens 等框架字段；这是 SDK 请求映射方式，不是新增用户配置入口。模型是否支持采样仍由模型设置与远端能力决定。

不新增 `streaming` adapter option，不改变 model/provider TOML 和任务预算合并次序。开发目录的代理 base URL 与 Haiku 4.5 选项匹配属于独立项目配置问题；通用 adapter 不根据代理域名或模型名猜测配置。

### 3. 生命周期与失败归类

Registry 继续持有 generation 共享客户端；adapter 每次调用只持有自己的响应流。`async with` 覆盖读取与异常退出，正常完成、读取失败或取消都释放响应连接，不关闭共享 SDK client。

TaskRunner 仍拥有总时限、取消、重试与 provider/model 切换；`request.timeout_seconds` 按现有方式传入 SDK，不另外建立流式 watchdog 或恢复循环。`CancelledError` 原样传播；现有 TaskRunner 取消后 join 的流程等待流关闭。SDK 保持 `max_retries=0`。

在当前 adapter 内收敛以下真实边界，沿用 `ProviderErrorKind` 与现有 scope，不增加 failure 类型：

| 场景 | 处理 |
| --- | --- |
| HTTP 错误状态 | 继续使用已有 `status_error` 分类 |
| HTTP 200 后的 SSE error | 从 SDK 异常 body 的 `error.type` 读取有限类型；`overloaded_error`、`api_error`、`rate_limit_error`、`timeout_error` 归 TRANSIENT，`authentication_error`、`permission_error` 归 AUTH，`invalid_request_error`、`request_too_large` 复用现有 400/413 的配置与 context-limit 分类，未知类型保持 UNKNOWN。不要以 HTTP 200 判断成功，也不拼接原始正文 |
| 连接、读取超时、流中途 transport error | 覆盖 SDK 连接异常和当前 HTTP 后端 `httpx2.TransportError`，归 TRANSIENT，由 TaskRunner 决定重试 |
| SDK 聚合中的 JSON 解析错误或空流断言 | 在调用 SDK 聚合器的窄边界处理明确异常，归 PARSE；不在整个 invoke 外捕获所有 ValueError/AssertionError，更不使用宽泛 Exception 把内部错误伪装成供应商故障 |
| 聚合返回但 `stop_reason is None` | 作为尚未完成的响应归 TRANSIENT，不发布部分 RawResponse；只增加最终状态检查，不重建逐事件状态机 |

仅需要一个 adapter 内部错误映射 helper 时就留在所属文件，依据结构化错误类型分类。错误反馈为现有简短供应商失败摘要，异常链仅供调试。重试重新发起整次模型调用，不续接中断 SSE，也不保留未完成的 thinking、工具调用或部分缓存统计。

### 4. 设计文档同步

实施后修改 `docs/design/llm.md` 的 Anthropic 调用与“设计范围”段落：说明 adapter 可使用内部流式传输并聚合单次响应；面向调用方/前端的增量输出协议仍不在当前范围。简述流资源由单次调用持有、重试由 TaskRunner 持有即可，不把 SDK 事件字段清单写入长期设计文档。

实施后已同步 `docs/design/llm.md`，描述实际聚合与生命周期边界。

## 文件范围与执行顺序

| 文件 | 改动/核对内容 |
| --- | --- |
| `visualization/src/features/settings/i18n/catalog.zh-CN.ts` | 已修改两个中文标题；字段路径、数值、说明和保存协议不变 |
| `tinysoul/llm/adapter/anthropic/messages.py` | 修改模块说明及客户端协议；内部 stream 聚合；采样 SDK 映射；必要的流失败归类与最终完成检查；复用 RawResponse 映射 |
| `tinysoul/llm/adapter/factory.py` | 核对注入的 SDK messages 对象满足新协议，仅按类型检查结果调整必要注解；保留 Registry 所有权与 max_retries=0 |
| `tests/llm/adapter/test_messages_and_generate_content.py` | 现有 Anthropic 真实 SDK 测试改用 SSE fixture，继续覆盖回放、缓存、思考模式和 header；保留 Google 测试行为 |
| `tests/llm/adapter/test_anthropic_streaming.py` | 集中覆盖长预算无 timeout、采样透传、流异常和取消关闭等新增行为 |
| `tests/support/anthropic.py` | 为 adapter 与 Context 的真实 SDK 测试共用 SSE 响应生成器；由于实际消费者跨测试目录，采用已有 tests/support 约定，未保留局部 conftest 或第二份 fixture |
| `tests/kernel/context/projection/test_composer.py` | 将旧 create 替身迁移到真实 SDK + 同一 SSE helper，继续验证构造式 Context 的有效/失效签名回放 |
| `tinysoul/llm/execution/task.py` 与现有 task runner 测试 | 核对取消 join、重试和失败 scope 的既有契约；复用现有机制，预期不修改生产控制流 |
| `docs/design/llm.md`、本执行计划 | 实施后同步实际设计并记录验证证据，逐项核对后归档 |

执行清单：

- [x] A. 重读规约、核对 SDK 和现有 owner，完成设计与本地 SDK 探查。
- [x] B. 实施两个前端名称修改，复用现有界面与保存链路。
- [x] C. 改造 Anthropic 客户端协议和单次流聚合，补齐采样参数映射。
- [x] D. 完成必要的错误归类、结束检查与取消释放验证。
- [x] E. 迁移真实 SDK fixture，执行聚焦测试并确认回放、缓存统计和输出解释保持可用。
- [x] F. 同步设计文档，运行完整门禁；按实际远端条件进行独立的代理冒烟检查。
- [x] G. 基于 AGENTS.md、计划和最终 diff 逐项核对，完成后加 `-done-` 并移动至 `docs/analysis/done/`。

## 验证要求

沿用真实 SDK + 本地 HTTP transport，不只以 stub 返回最终 Message：

1. 请求预算为 32768、没有显式 timeout，断言实际发出 `stream=true` 且预算未被改写；该用例应能直接区分旧实现与修复。
2. 代表性响应覆盖分段文本、thinking/signature、工具 JSON 分片及最终 usage；验证工具参数完整、原生块有序、可回放，缓存计数读取最终累计值。复用现有回放测试，不重复建立一整套协议测试。
3. 在现有测试中保持 automatic/explicit cache 与 thinking/display/effort/header 的请求体断言；新增 sampling pass-through 验证，与已有 omit 用例形成区分。
4. 代表性 stop reason 覆盖 `max_tokens` 与正常工具/文本结束，保证输出预算耗尽不被误当传输失败。
5. 覆盖一次 HTTP 错误、HTTP 200 中的 overloaded SSE、读取中断、空/明显未完成流。错误不泄露供应商正文；SDK 不自行重试。
6. 以明确事件阻塞读取后取消，断言响应流关闭且取消向上传播；共享 client 仍可进行下一次请求。测试等待明确同步信号，不用固定 sleep 判断释放。
7. 聚焦 adapter 测试后运行 Fast；交付前按规约运行 `scripts/test.ps1 -Suite Full` 与 `scripts/typecheck.ps1`。新增错误分支核对 `ProviderError`、TaskRunner 与 Runtime bridge 的既有协作。
8. 代理冒烟与本地门禁分开记录：使用用户已授权的开发配置和独立的简短合成提示，预算可保持 32768，但要求只回答短文本；需要回放验证时仅使用合成工具。不要将归档 Trace、真实 Action Catalog 或其它私有正文外发。记录是否支持 SSE、是否完成及失败摘要，不记录密钥；代理特有失败不改变通用 Anthropic 协议设计。

## 验证与实施核对

### 设计轮基线

字段名称修改时的验证：

- 前端现有测试：94 文件、820 用例通过；`pnpm build` 通过。
- `scripts/test.ps1 -Suite Full`：1343 passed，23 deselected；耗时 302.25 秒。
- `scripts/typecheck.ps1`：通过；`git diff --check`：通过。
- 真实 SDK + 本地 MockTransport 探查：长预算流式聚合、采样发送、流内错误与未完成响应行为均已核对；未调用远端 provider。

以上属于设计轮的前端修改及后端基线验证，修复后的证据单独记录如下。

### 实施轮验证

- Adapter 聚焦：132 passed，18 deselected。
- Adapter 与 Context projection 联合聚焦：140 passed，18 deselected。
- `scripts/typecheck.ps1`：通过；改动 Python 文件的 Ruff imports/unused 检查与格式检查通过。
- `scripts/test.ps1 -Suite Fast`：1350 passed，28 deselected；336.53 秒。
- `scripts/test.ps1 -Suite Full`：1355 passed，23 deselected；353.13 秒。
- 最终 `scripts/typecheck.ps1`、`git diff --check`：通过。

真实代理验证通过仓库的 `build_provider_registry` 装配当前 adapter，使用用户已授权开发目录的 endpoint 与凭据，仅发送合成提示和合成工具，没有写入开发目录配置：

| 验证 | 结果与解释 |
| --- | --- |
| 当前已保存 `claude-haiku` → `claude-haiku-5-5` | HTTP 404，进入现有 provider 失败分类；已实际发出请求，不再是 HTTP 前的长请求 ValueError。该 binding 的可用性需要维护者确认 |
| 临时内存 binding 改为此前可用的 `claude-haiku-4-5`，保持其余配置；预算 32768，不覆盖 SDK timeout | COMPLETE，回答 `OK`，input 2516、output 1；证实代理支持本次流式聚合 |
| 临时 Haiku 4.5、enabled thinking/budget 1024、signed replay/prefix binding；两轮合成 `echo_probe` 工具交互，每轮预算 32768 | 第一轮 TOOL_CALLS、1 个完整工具调用、取得 NativeReplay；第二轮携带回放与合成工具结果成功 COMPLETE 并回答 `OK`。两轮 output 分别 99、1 |

上述请求有独立的 60 秒冒烟总时限，`ProviderRequest.timeout_seconds` 保持 None；没有以 SDK timeout 覆盖绕过原问题。短回答验证的是请求允许较大输出预算，不代表测试生成了 32768 token 或持续了 10 分钟。代理测试只证明这条兼容路由的实际表现，官方协议语义仍以 SDK/官方文档为准。

### AGENTS.md 与计划核对

| 核对项 | 实施情况 |
| --- | --- |
| 单一 owner 与生命周期 | SDK 客户端继续由 Registry 持有；本次流由 invoke 的 async with 关闭；factory 无需修改 |
| 三层失败语义 | SDK/传输失败在 adapter 转为已有 ProviderError；未新增失败类型，TaskRunner/Runtime bridge 未增加特殊分支 |
| 取消、重试、时限 | 复用 TaskRunner 的取消 join、重试/切换与剩余时限；测试验证取消释放及共享 client 再次调用；SDK max_retries=0 |
| 内部协议与业务职责 | RawResponse、NativeReplay、PromptCache、工具映射继续复用；无 SSE 执行状态机、自动工具执行或部分结果提交 |
| 配置与前端 | 无新 adapter option、TOML 字段或 Endpoint 协议；前轮两个中文字段名称已核对 |
| 测试与复用 | 现有 Anthropic 请求/回放/缓存用例迁移到 SSE；跨模块测试复用 tests/support；没有保留 create 兼容替身 |
| 设计文档 | llm.md 已说明内部聚合与对外单次响应的边界；只有修复实际落地后才同步 |

执行计划已完成：实际生产改动集中于一个 adapter，配套迁移测试与同步设计文档。内部请求/响应、缓存和推理回放协议复用现有设计；本地 SDK 测试及真实代理冒烟均证明修复可以保留较大输出预算并完成调用。

没有需要新增产品语义的决策项。远端代理的 SSE 与签名工具回放已完成代表性验收；当前保存的 Haiku 5.5 binding 返回 404 是独立配置发现，未通过自动降级或修改 TOML 掩盖。

## 参考依据

- [Anthropic Python SDK 长请求说明](https://platform.claude.com/docs/en/cli-sdks-libraries/sdks/python#long-requests)。
- [Streaming messages：获取完整 Message、事件与流内错误](https://platform.claude.com/docs/en/build-with-claude/streaming)。
- [Anthropic API errors](https://platform.claude.com/docs/en/api/errors)。
- 本地 SDK 1.15.0 的 `resources/messages/messages.py`、`lib/streaming/_messages.py`、`_streaming.py` 与 `_client.py`；源码检查及上述 MockTransport 探查共同确认实际行为。
