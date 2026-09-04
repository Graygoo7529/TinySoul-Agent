# LLM 多 Adapter Provider 与 Provider Chain 执行计划

状态：`done`

日期：2026-09-04

## 本轮复核与决策点

维护者已确认“Adapter 与 API style 一一对应”。这改变了上一版的结论：既然每个 Adapter 都只有一个确定 wire style，`api_style` 不应再作为 Provider 的可配置字段，也不需要用 `ProviderAdapterBinding` 把同一个 Adapter 与多个 style 重新组合。

维护者进一步确认：删除 `generic`，只保留 `openai_compatible_chat` 作为通用兼容 Adapter；Responses 是 `openai` 专用 Adapter 的 API style。决策结果如下：

| 方案 | 语义 | 影响 | 判断 |
| --- | --- | --- | --- |
| A. 删除 `generic`，只保留具体供应商 Adapter | 每个 Provider 必须使用 `openai`、`kimi` 等行为 Adapter | 任意 OpenAI-compatible endpoint 没有无供应商行为的 Chat 适配器；会迫使代理伪装成具体供应商 | 不推荐 |
| B. 删除 `generic`，只保留 `openai_compatible_chat` | 通用兼容能力限定为 Chat Completions；Responses 由 `openai` Adapter 提供 | 消除 `generic + Provider.api_style` 的隐式组合，同时保持实际需要的通用兼容能力 | **已确认** |
| C. 将 `generic` 拆为两个一一对应的通用 Adapter | `openai_compatible_chat` 与 `openai_compatible_responses` 都是协议固定、无供应商扩展的 Adapter | 会把项目不需要的通用 Responses 行为提升为公开 Adapter 身份 | 不采用 |

本计划后续正文按方案 B 实施。现有通用 Chat mapper 获得稳定的 `openai_compatible_chat` 身份；现有 Responses mapper 继续作为 `openai` Adapter 的基础实现细节，不再作为可独立配置的通用 Adapter 暴露。

需要确认的边界有三项：

1. `openai_compatible_chat` 是唯一通用 Adapter；不提供 `openai_compatible_responses`。
2. Provider 对同一 Adapter 只声明一次；若同一 endpoint 的同一 Adapter 需要两个 base URL、凭据或其它路由身份，它们是两个 Provider，而不是重复 binding。
3. `api_style` 只作为 Adapter 的静态类型属性，不出现在 Provider/Model 配置。

## 执行计划可行性审查

方案可行，且比引入 `ProviderAdapterBinding` 的版本更容易保持所有权清晰：现有 OpenAI SDK 已经有 Chat 与 Responses 两套 mapper，Provider 只需为每个声明的 Adapter 构建一个 `(provider_id, adapter)` 实例；Model Provider Chain 只携带远端模型名，不重复协议事实。现有 catalog 已支持 `enum_list` 与 `object_list`，Endpoint 也已有整值配置 mutation，因此不需要新增通用表单协议或路由。

实施时需要保留四个顺序约束：

1. 先完成 `AdapterKind`/`AdapterSpec`、配置解析和 catalog 的协议迁移，再改 Factory/Registry；避免运行时同时解释新旧 Provider 形状。
2. 再落地 `ModelProviderBinding` 与 `ProviderRequest`，让每次调用的 Provider 身份和远端模型名成为显式输入。
3. 最后在现有 `ModelChainRunner` 调用边界内加入 Provider 重试/切换，并用少量行为测试锁定“重试 -> Provider -> Model -> cycle”顺序。
4. 前端以新 catalog 为唯一字段事实；复合数组只整值提交，后端候选配置校验失败时不部分应用。

主要风险是失败作用域归类，而不是 Adapter 集合本身。`ProviderError` 应在 LLM 模块内增加明确的 provider/model scope，并由 SDK/HTTP mapper 与本地请求校验分别赋值；不能通过捕获所有异常来猜测是否切换 Provider。Provider Chain 只聚合有限的安全摘要，最终仍由现有 LLM bridge 负责 Runtime 转换。通用 Responses 不作为公开配置能力；供 `openai` Adapter 复用的内部 Responses mapper 和相应 OpenAI 行为测试继续保留。

## 目标

在不改变 LLM 模块所有权、不引入第二套任务状态机的前提下，让一个 Provider 声明多个可用 Adapter，让一个 Model 声明有序的 Provider 路由，并把现有模型链恢复过程扩展为以下固定顺序：

```text
同一 Provider 首次调用
  -> 同一 Provider 重试
  -> 同一 Model 的下一个 Provider
  -> Task Model Chain 的下一个 Model
  -> 下一次完整 Model Chain cycle
```

Provider 与 Model 的成功备用位置都只作为有时限的运行时偏好；偏好到期后回到各自链首。配置、模型能力、调用路由、失败语义和前端编辑必须保持同一套事实，不增加兼容别名或平行状态。

## 现状与问题判断

当前实现有三项直接限制：

- `ProviderSpec` 同时保存单一 `adapter` 和 `api_style`，`ProviderRegistry` 只按 `provider_id` 注册一个 Adapter 实例。
- `ModelSpec` 同时保存单一 `provider_id` 和单一 `provider_model`，所以模型选择后不能在保持模型契约不变的情况下切换端点。
- `LLMTaskRunner._try_model` 把 `max_retries_per_model` 实际用作单一 Provider 的最大调用次数；Provider 异常随后直接交给 `ModelChainRunner`，不存在 Provider Chain 层。

现有 `api_style` 语义可以收敛为一一对应的 Adapter 属性。`AdapterSpec.api_style` 是每个 Adapter 唯一的 wire style：`openai` 使用 Responses，`openai_compatible_chat`、`kimi`、`deepseek`、`glm` 与 `minimax` 使用 Chat。当前 `ProviderSpec.api_style` 只是 Factory 选择通用 mapper 所需的重复配置事实；以明确 Adapter 身份替代后即可删除。

当前运行时映射可以具体概括为：

| AdapterKind | AdapterSpec.api_style | 当前/目标运行时实现 | style 的实际作用 |
| --- | --- | --- | --- |
| `openai_compatible_chat` | `openai_chat` | `OpenAICompatibleChatAdapter` | 通用 Chat payload、response 和 tool mapper，无供应商专属选项 |
| `openai` | `openai_responses` | `OpenAIProviderAdapter` | Responses mapper 加 OpenAI reasoning/cache 等行为 |
| `kimi` / `deepseek` / `glm` / `minimax` | `openai_chat` | 各自供应商 Adapter | Chat mapper 加各自 option、工具和 reasoning 约束 |

`api_style` 作为类型是合理的，但应使用 `StrEnum` 作为稳定协议标识，而不是在 Provider/Model 中再保存一个可编辑字符串。`AdapterSpec` 是静态机器规则的唯一来源；运行时 Adapter 如需把 style 传给 payload helper，应从自身 `AdapterSpec` 暴露只读属性，不复制另一份配置状态。

## 设计结论

### API style、generic 与 ProviderAdapterBinding

本计划不引入 `ProviderAdapterBinding`。在已确认 Adapter 与 API style 一一对应后，`api_style` 是 Adapter 的静态协议属性，不是 Provider 的运行时选择项，也不是 Model 的能力要求。Provider 只声明它支持哪些 Adapter；Adapter 身份已经唯一决定 wire style。

```python
@dataclass(frozen=True)
class AdapterSpec:
    kind: AdapterKind
    api_style: ProviderApiStyle
```

`AdapterKind.GENERIC` 删除，不保留旧的模糊身份。通用协议能力收敛为 `openai_compatible_chat`，固定对应 `openai_chat`。`openai` 表示使用 Responses wire style 并带 OpenAI 专属行为的 Adapter；底层可继续复用 Responses mapper，但不向配置层暴露独立的 compatible Responses Adapter。

`ProviderApiStyle` 继续作为 `StrEnum` 保留在 `llm/adapter_types.py`，供 `AdapterSpec`、catalog 和观察数据使用。`AdapterSpec.api_style` 为非空单值并在构造时校验；`validate_api_style`、`api_styles` 这类多 style 组合 API 删除。运行时 Adapter 如需构造 payload，只从自身固定的 AdapterSpec 读取只读 style，不复制配置状态。

Provider 对同一 Adapter 只声明一次。若相同端点需要两个协议，就声明两个不同的 Adapter；若同一协议需要不同 base URL、凭据或路由身份，就拆为两个 Provider。当前没有每个 Adapter 独立配置字段，因此引入 Binding 只会重复 Adapter 与 style 的事实；将来确实出现同一 Provider 下同一 Adapter 的多实例或 per-adapter endpoint/auth，再单独评估 Binding。

### Provider 声明 Adapter 能力集合

`ProviderSpec` 改为：

```python
@dataclass(frozen=True)
class ProviderSpec:
    id: str
    adapters: tuple[AdapterKind, ...]
    base_url: str
    api_key_envs: tuple[str, ...]
    enabled: bool = True
```

`adapters` 必须非空且 Adapter 不重复。它表达端点能力，不表达调用优先级。一个代理端点可以声明多个 Adapter，例如 `["openai", "kimi", "openai_compatible_chat"]`；模型仍只要求一个确定 Adapter。Provider Registry 的稳定键为 `(provider_id, adapter_kind)`，因为 Provider 对同一 Adapter 只声明一次，解析没有歧义。

Provider Factory 为每个已启用 Provider 的每个 Adapter 构建一个实例。`ProviderRegistry` 使用 `(provider_id, adapter_kind)` 作为稳定键，并通过 `get(provider_id, adapter_kind)` 解析调用实例。API key 对同一 Provider 只解析一次，禁用 Provider 不构建实例也不读取凭据。

### Model 绑定有序 Provider Chain

引入模型拥有的核心值对象：

```python
@dataclass(frozen=True)
class ModelProviderBinding:
    provider_id: str
    provider_model: str

@dataclass(frozen=True)
class ModelSpec:
    id: str
    providers: tuple[ModelProviderBinding, ...]
    context_window_tokens: int
    adapter: AdapterKind
    capabilities: frozenset[ModelCapability]
    adapter_options: AdapterOptions
    request_overrides: RequestOverrides
```

`ModelProviderBinding` 同时保存 Provider 身份和该端点公开的模型名，因为同一有效模型在代理与官方端点可能使用不同名称。绑定顺序就是 Provider Chain 顺序；Provider id 必须非空、不可重复，`provider_model` 必须非空。

`context_window_tokens`、`capabilities`、`adapter_options` 和 `request_overrides` 继续属于 Model。由此形成一个明确不变量：同一 `ModelSpec` 的所有 Provider Binding 都必须提供同一个 TinySoul 模型契约。如果某个端点的上下文窗口、能力或 Adapter 行为实质不同，应建立另一个 Model，而不是把差异塞进 Binding。

每个 ModelProviderBinding 引用的 Provider 必须存在，而且 `model.adapter` 必须属于 Provider 的 `adapters`。禁用 Provider 的 Adapter 声明保留为配置事实，但不进入当前运行时路由。Task Model Chain 仍按“至少存在一个已启用且 Adapter 兼容的 Provider Binding”判断 Model 是否可用；过滤后为空继续在配置加载边界失败。

配置形状改为：

```toml
[llm.providers.proxy]
enabled = true
adapters = ["openai", "kimi", "openai_compatible_chat"]
base_url = "https://proxy.example.com/v1"
api_key_envs = ["PROXY_API_KEY"]

[llm.providers.openai]
enabled = true
adapters = ["openai"]
base_url = "https://api.openai.com/v1"
api_key_envs = ["OPENAI_API_KEY"]

[llm.models.gpt_5_6_terra]
adapter = "openai"
providers = [
  { provider = "proxy", provider_model = "gpt-5.6-terra" },
  { provider = "openai", provider_model = "gpt-5.6-terra" },
]
context_window_tokens = 400000
capabilities = ["text_input", "image_input", "tool_calling"]
```

配置直接迁移到复数字段，不保留 Model 的单数 `provider`/`provider_model` 或 Provider 的单数 `adapter`/`api_style` 兼容读取路径。Provider 使用 `adapters`；Model 的单数 `adapter` 保留，因为它定义整个模型所需的统一行为。旧 `generic` 值迁移为 `openai_compatible_chat`，不保留兼容别名。

## 调用与路由流程

### ProviderRequest

`ProviderRequest` 增加当前 `ModelProviderBinding`。Adapter 从 `request.binding.provider_model` 取得远端模型名，并校验 Binding 的 Provider 与当前 Adapter 实例一致；Model 继续提供统一能力、选项和请求覆盖。这样不会临时复制或改写 `ModelSpec`。

### 嵌套路由

每次 LLM Task 的运行流程如下：

1. `ModelChainRunner` 根据 Task profile 的模型成功偏好决定首个 Model；第一轮从偏好位置向链尾尝试，后续 cycle 回到 Model Chain 链首。
2. 进入一个 Model 后，先执行模型级 capability 和本地 context-window 校验；这两项不随 Provider 改变。
3. 从 `ModelSpec.providers` 中过滤出当前已启用、已注册且 Adapter 匹配的 Binding。
4. 第一个 model-chain cycle 根据 `(task profile, model id)` 的 Provider 成功偏好决定首个 Provider；后续完整 cycle 回到该 Provider Chain 链首。
5. 每个 Provider 先调用一次，只对 transient Provider 失败执行 `max_retries_per_provider` 次额外重试。
6. 该 Provider 仍失败时，按失败作用域决定切换 Provider、直接切换 Model 或中止。
7. Provider Chain 耗尽后，把聚合结果交回现有 `ModelChainRunner`：可重试的耗尽进入下一完整 cycle，确定性耗尽切换下一个 Model。
8. 任一 Provider 返回可解释的响应即更新 Provider 成功偏好；任一 Model 返回 `TaskResult` 即更新 Model 成功偏好。输出协议错误、输出截断和内容过滤继续是已完成调用的局部 `TaskFailure`，不触发 Provider 或 Model fallback。

Provider 路由是 Model 调用内部的恢复层，不成为新的 LLM Task、Cycle、Phase 或 Runtime frame，也不拥有第二套业务状态机。

### 恢复配置

`RetryPolicy` 保留为 Task 级策略，字段调整为：

```python
@dataclass(frozen=True)
class RetryPolicy:
    max_retries_per_provider: int = 1
    retry_wait_seconds: float = 0.0
    provider_switch_wait_seconds: float = 0.0
    model_switch_wait_seconds: float = 0.0
    max_cycles: int | None = 10
    prefer_successful_provider_seconds: float = 600.0
    prefer_successful_model_seconds: float = 600.0
```

语义明确为：

- `max_retries_per_provider` 是首次调用之外的额外重试次数，允许为 `0`；总调用上限是 `1 + max_retries_per_provider`。标准配置由原来的 `max_retries_per_model = 2` 迁移为 `max_retries_per_provider = 1`，维持每个路由最多两次调用。
- `retry_wait_seconds` 只用于同一 Provider 的 transient 重试间隔。
- `provider_switch_wait_seconds` 用于同一 Model 内切换 Provider。
- `model_switch_wait_seconds` 用于切换 Model。
- `max_cycles` 仍只限制完整 Model Chain cycle；Provider Chain 不增加独立 cycle 上限。
- 两个 `prefer_successful_*_seconds` 都是非负有限秒数，不再用 `None` 表达永久停留备用项。`0` 表示下一次 Task 立即回到链首。

运行时状态重构为一个 LLM 路由状态门面，内部保存两类有时限偏好：

- Model 偏好键：`task profile`。
- Provider 偏好键：`(task profile, model id)`。

状态保存成功项 id 和单调时钟时间，不保存数组下标。配置重建、禁用或重排后找不到成功项时自然回到链首。链首成功会清除对应备用偏好；只有成功会改变偏好，失败不会把临时尝试位置固化。

现有 `ModelChainState` 相应改名或收敛为 `LLMRouteState`，由 `LLMTaskRunner` 单点拥有。`ModelChainRunner` 继续负责外层 cycle 和 Model blocking；Provider Chain 执行器只负责一个 Model 内的有序路由与重试。两者复用相同的时钟、sleep 边界和成功偏好规则，不引入通用 Gateway 或抽象插件框架。

## 失败归属与切换策略

当前 `ProviderErrorKind` 只描述错误类别，不能区分“换 Provider 可能恢复”和“同一模型请求在所有 Provider 上都会失败”。为避免把确定性模型错误重复发送到所有代理，引入 `ProviderFailureScope`：

- `provider`：端点、凭据、传输或该端点返回值的问题，可以切换 Provider。
- `model`：Adapter 对模型配置、工具或请求能力的确定性拒绝，直接切换 Model。

外部 SDK/HTTP 映射出的认证、限流、服务故障、响应解析和端点 4xx 默认是 provider scope；本地 Adapter 行为校验产生的配置或 capability 失败是 model scope。动态入口仍优先在配置解析期消除可静态发现的问题。

| 失败 | 同 Provider 重试 | 下一个 Provider | 下一个 Model | 下一 cycle / 结果 |
| --- | --- | --- | --- | --- |
| `TRANSIENT`, provider scope | 是，受次数限制 | 是 | Provider Chain 耗尽后是 | 标记可重试，允许下一完整 cycle |
| `AUTH` / `PARSE` / `CONFIG` / `UNKNOWN`, provider scope | 否 | 是 | Provider Chain 耗尽后是 | 确定性耗尽不重复该 Model |
| `CONFIG` / `CAPABILITY`, model scope | 否 | 否 | 是 | 当前 Task 内阻塞该 Model |
| Provider 报告 `CONTEXT_LIMIT` | 否 | 是 | 仅在并非全部路由都是 context limit 时按普通耗尽处理 | 全部已尝试路由均为 context limit 时转换为现有 `ModelContextPressureError` |
| 本地 context-window 预检 | 否 | 否 | 否 | 立即使用现有 context pressure 恢复语义 |
| `TaskCancelled` / `RuntimeException` / LLM 契约错误 | 否 | 否 | 否 | 立即中止并由现有边界处理 |
| `TaskFailure` 局部结果 | 不适用 | 否 | 否 | 返回结构化局部结果 |

Provider Chain 耗尽使用 LLM 模块内部的聚合异常，最多携带是否出现 transient、最后稳定 kind/scope 和尝试过的安全身份摘要。它不会直接越过 LLM 边界。最终仍只有现有的模型链耗尽、上下文压力、配置/契约等 LLM 模块边界异常进入 `RuntimeLLMBridge`，不扩展 Runtime Trap 原因。

Observation 不携带 SDK 异常、traceback、密钥、绝对路径或完整消息栈。事件职责调整为：

- `llm.model.started/failed/completed` 表达一个 Model 层尝试。
- `llm.provider.started/retry/failed/completed` 表达一个具体 Binding 的尝试与切换。
- `llm.model.request/response` 继续承载真实发送给模型的 model-level 观察数据，并增加当前 `provider_id`、`provider_model`、`adapter` 和安全的尝试序号，保持前端模型上下文保留逻辑只有一个事实源。

`CurrentModelCapabilities` 的 context window 和 capabilities 始终来自 Model；其 provider 字段表示按当前 Provider 偏好计算出的“下一次首选路由”，而不是模型能力来源。

## 前端设置设计

### Providers 页面

- 用 Adapter 集合编辑器替换单一 Adapter/API Style 字段。每行选择一个 Adapter；`api_style` 从 `rules.llm.adapters` 派生为只读协议标签，不提供第二个可编辑选择。
- Adapter 顺序不是调用优先级，但保持稳定以便配置 diff；不允许重复 Adapter，至少保留一项，保存时对完整 `llm.providers.<id>.adapters` 执行一次原子 `set`。
- Provider 摘要显示 enabled、Adapter 数量/名称和 endpoint；API style 作为 Adapter 的静态说明显示，不再作为 Provider 根级字段展示。
- 新建 Provider 的 catalog template 使用 `openai_compatible_chat`。删除或移除 Adapter 导致 Model Provider Chain 不兼容时，后端候选配置校验整体拒绝，前端展示该稳定配置错误，当前运行配置不变。

### Models 页面

- 保留 Model Adapter 单选。候选 Adapter 只展示至少被一个 Provider 声明的 Adapter。
- 用有序 Provider Chain 编辑器替换单一 Provider 与 Provider Model ID 字段。每行包含 Provider 选择、该 Provider 的 `provider_model` 输入、上移、下移和删除操作，并提供添加 Provider 操作。
- 可选 Provider 只包括声明了当前 Model Adapter 的 Provider；同一 Provider 不可重复；链至少保留一项。
- 添加、删除、重排或编辑远端模型名都对完整 `llm.models.<id>.providers` 数组执行一次原子 `set`，不把数组索引暴露为配置路径。
- 切换 Model Adapter 时，在一个 mutation 中同时写入新 Adapter、重建兼容 Provider Chain，并清理不属于新 Adapter 的 `adapter_options`。已有且兼容的 Model Provider Binding 可保留其远端模型名；若无兼容项，用户必须先选择一个 Provider 后才能提交。
- `context_window_tokens`、capabilities、Adapter options 和 request overrides 仍只编辑一次，并在 Provider Chain 区域之外显示，避免暗示它们是逐 Provider 配置。
- Model 列表摘要增加 Provider Chain 顺序，例如 `proxy -> openai`，让备用位置可直接辨认。

### Task Chains 页面与运行轨迹

- Model Chain 编辑方式不变；Recovery 区域替换为 `max_retries_per_provider`、两类 switch wait 和两类成功偏好时长。
- 运行轨迹把现有 Provider retry 文案订阅从 `llm.model.retry` 调整到 `llm.provider.retry`，并显示实际命中的 Provider。`llm.model.request/response` 的保留与导出协议继续工作，可展示一次 Task 内的多 Provider 尝试。
- 前端不维护“当前 Provider”全局状态；列表和编辑草稿都来自 `GET /v1/config`，运行偏好只由 Observation 呈现。

### Catalog 与 Endpoint

不增加 Endpoint 路由。现有 `GET /v1/config/catalog`、`GET /v1/config` 和 `PATCH /v1/config` 足以承载新形状：

- `llm.providers.*.adapters`：`enum_list`，整值读写。
- `rules.llm.adapters`：每个 Adapter 的稳定 kind、显示名称与只读 `api_style`。
- `llm.models.*.providers`：`object_list`，整值读写。
- `llm.models.*.providers.*.provider`：供自定义编辑器读取标签、说明和 Provider reference 元数据。
- `llm.models.*.providers.*.provider_model`：供自定义编辑器读取文本字段元数据。
- Task recovery 新字段使用现有 number/integer 描述符。

嵌套字段描述符只为现有领域编辑器提供 catalog 元数据，不要求 infra 把数组元素展开为可独立 PATCH 的字段，也不为此建设通用表单 schema。Endpoint 配置文档同步说明复合数组必须整值提交及其错误形状。

## 非目标

- 不做按权重负载均衡、随机选择、并行竞速、熔断器、自动健康检查或跨进程路由偏好持久化。
- 不引入 ProviderAdapterBinding；Provider 的 Adapter 集合不覆盖 context window、capabilities、Adapter options、base URL 或凭据。
- 不把 Provider Chain 暴露成新的 Task、Action、Runtime frame 或前端持久状态。
- 删除 `generic` AdapterKind，不保留旧 Provider 的单数 `adapter`、根级 `api_style` 或旧 retry 字段的兼容别名。

## 实施事项

### 1. 设计与配置协议

- [x] 将本方案确认后的稳定语义同步到 `docs/design/llm.md`。
- [x] 更新 Provider、Model 与 Task recovery 的标准/开发配置模板。
- [x] 更新 config catalog 的 collection template、字段描述符和 LLM machine rules。
- [x] 更新 `docs/endpoint/configuration.md` 与前端 settings 设计文档。

### 2. Adapter 与 Provider 装配

- [x] 删除 `generic`，增加固定为 Chat style 的 `openai_compatible_chat` AdapterSpec，并让 `AdapterSpec.api_style` 成为非空单值。
- [x] 把 `ProviderSpec.adapter/api_style` 改为 `ProviderSpec.adapters`，禁止同一 Provider 重复 Adapter；不引入 `ProviderAdapterBinding`。
- [x] 让 Provider Factory 对一个 Provider 构建多个 Adapter 实例。
- [x] 把 ProviderRegistry 改为 `(provider_id, adapter_kind)` 复合身份并维持重复注册不变量。

### 3. Model Provider Binding

- [x] 增加 frozen `ModelProviderBinding`，把 `ModelSpec` 的单一 Provider 字段替换为有序 Binding 元组。
- [x] 在配置入口校验 Provider 引用、Adapter 兼容、绑定唯一性和可用 Model。
- [x] 让 `ProviderRequest` 显式携带当前 Binding，Adapter 不再从 Model 读取单一 Provider。
- [x] 更新模型注册表、当前能力视图、真实 Provider 验证入口和应用装配。

### 4. 重试、切换与失败语义

- [x] 把 RetryPolicy 迁移为 Provider 重试、Provider/Model switch wait、外层 cycle 和双层成功偏好配置。
- [x] 将 ModelChainState 收敛为 LLMRouteState，并用成功项 id 管理 Model/Provider 两类有时限偏好。
- [x] 在现有 model-chain 调用内部加入 Provider Chain 执行器，严格实现“重试 Provider -> 换 Provider -> 换 Model -> 下一 cycle”。
- [x] 增加 ProviderFailureScope 并清理 Adapter 本地校验与 SDK/HTTP 错误的作用域归类。
- [x] 保持 context pressure、局部 TaskFailure、模型链耗尽和 Runtime bridge 的现有三层边界。
- [x] 调整 Observation payload 和前端派生，保证多 Provider 尝试可解释且不泄露原始异常。

### 5. 前端配置体验

- [x] Providers 页面实现 catalog 驱动的 Adapter 集合编辑、静态 API style 展示与摘要。
- [x] Models 页面实现兼容 Provider 过滤、有序 Binding 编辑和整数组原子提交。
- [x] Adapter 变更以单次 mutation 协调 Provider Chain 与 Adapter options。
- [x] Task Chains 页面展示新的 recovery 字段；运行轨迹展示 Provider retry/fallback。

### 6. 聚焦验证

- [x] LLM 配置测试覆盖多 Adapter Provider、Adapter 唯一性、未知/不兼容引用和禁用 Provider 过滤。
- [x] Registry/Factory 测试覆盖一个 Provider 的多个 Adapter 实例与复合键重复保护。
- [x] Task runner 使用少量行为测试覆盖 transient 重试后换 Provider、Provider 耗尽后换 Model、下一 cycle 回到链首、备用 Provider 成功偏好及到期回首。
- [x] 保留取消、context pressure 和局部 TaskFailure 的代表性回归测试，不为每个错误 kind 建立组合穷举测试。
- [x] 前端测试覆盖 Provider Adapter 集合、兼容 Provider Chain 的展示/编辑、Adapter 切换原子 mutation 和 catalog 派生。
- [x] 运行聚焦测试、Fast、`./scripts/test.ps1 -Suite Full`、`./scripts/typecheck.ps1`、前端 test/build 与 `git diff --check`。

## 预计改动范围

后端核心改动集中在：

- `tinysoul/llm/adapter_types.py`
- `tinysoul/llm/adapter.py`
- `tinysoul/llm/config_types.py`
- `tinysoul/llm/config_sections.py`
- `tinysoul/llm/models.py`
- `tinysoul/llm/model_chain.py`
- `tinysoul/llm/task.py`
- `tinysoul/llm/provider/`
- `tinysoul/infra/config/catalog/models.toml`
- `tinysoul/assets/project/config_profiles/`

前端改动集中在：

- `visualization/src/features/settings/model.ts`
- `visualization/src/features/settings/ProvidersSettingsPage.tsx`
- `visualization/src/features/settings/ModelsSettingsPage.tsx`
- `visualization/src/features/settings/TaskChainsSettingsPage.tsx`
- `visualization/src/derive/` 与 `visualization/src/store/eventRetention.ts`

测试以既有 `tests/llm/`、`tests/infra/test_config_catalog.py`、`tests/app/` 和对应前端 settings/derive 测试为主，更新旧构造方式并增加上述关键行为断言。原则上不新增业务模块文件；Provider Chain 的内部执行类型优先与现有 `model_chain.py` 共同形成 LLM routing 实现，只有代码职责在实施时无法保持清晰时才拆出专门文件。

## 验收标准

- 一个启用 Provider 可以同时注册多个 Adapter，Model 只能选择该 Provider 已声明的目标 Adapter。
- 一个 Model 可以按配置顺序跨多个 Provider 调用，并为每个 Provider 使用独立 `provider_model`。
- 调用顺序可观察且严格为同 Provider 重试、换 Provider、换 Model、下一完整 cycle。
- 备用 Provider 或 Model 成功后可在配置时限内成为首选，时限到期自动回到链首。
- Model capability/context 契约不因 Provider 切换而改变，输出协议失败仍是局部结果。
- 配置错误停在 LLM/Infra 配置边界，Provider 与 Model Chain 耗尽继续经既有 LLM bridge 进入 Runtime，不新增含糊异常路径。
- 前端只能创建后端可接受的 Adapter/Provider 组合，并以一次原子 mutation 保存每个复合变更。
- 设计文档、Endpoint 文档、catalog、默认项目配置、后端实现、前端页面和测试描述同一事实。

## 最终核对

- 后端 Full 门禁：`scripts/test.ps1 -Suite Full` 通过，960 passed、2 skipped、21 deselected；仅有既存的 Starlette/httpx 弃用警告。
- 类型检查：`scripts/typecheck.ps1` 通过，`ty` 无诊断。
- 前端验证：`pnpm test -- --run` 通过，21 个测试文件、127 项测试；`pnpm build` 通过。Vite 仅提示现有 bundle 超过 500 kB 的拆包建议。
- 差异检查：`git diff --check` 通过；工作树中的换行提示是 Git 的 CRLF/LF 属性提示，不是空白错误。
- 旧协议核对：运行时代码、默认配置、catalog、Endpoint 文档和设置页不再读取 `generic`、Provider 单数 `adapter/api_style`、Model 单数 `provider/provider_model` 或 `max_retries_per_model`；历史分析记录保留原始方案说明。
