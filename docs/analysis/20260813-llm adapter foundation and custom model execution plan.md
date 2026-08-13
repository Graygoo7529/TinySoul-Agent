# LLM Adapter 基石与 Custom Model 执行计划

状态：`done`

## 目标

把 adapter 明确为 Provider 接入与 Model 行为之间的共同基石，使配置中的每项事实具有稳定、独立的语义：

- Provider 声明 endpoint 实际装配的 adapter、API style、地址与凭据。
- Model 声明自身需要的 adapter、所绑定的 Provider、发送给 endpoint 的 `provider_model`、能力和调用选项。
- Model 只能绑定 adapter 相同的 Provider；切换 Provider 不改变 Model 的 adapter、options、request overrides 或其它模型事实。
- `provider_model` 只作为发送给 endpoint 的不透明模型标识，不再参与 adapter 行为分支判断。
- adapter 自行声明和解释支持的 `adapter_options`；存在真实协议分支的 adapter 可以把 `protocol` 作为判别 option，并按 protocol 约束其余 options。
- Custom Model 是创建后完全独立的 Model。内置 Model 只作为快速创建 preset，不建立继承、模板来源或后续同步关系。

项目处于开发阶段，不保留旧配置兼容字段，也不执行数据迁移。

## 确定的设计语义

### Adapter、Provider 与 Model

adapter kind 是 LLM 模块的稳定领域标识，不再只从属于 Provider。Provider 和 Model 都显式持有同一种 adapter kind：

```toml
[llm.providers.kimi_proxy]
enabled = true
adapter = "kimi"
api_style = "openai_chat"
base_url = "https://example.com/v1"
api_key_envs = ["KIMI_PROXY_API_KEY"]

[llm.models.custom_kimi]
adapter = "kimi"
provider = "kimi_proxy"
provider_model = "proxy-kimi-alias"
context_window_tokens = 262144
capabilities = ["text_input", "tool_calling", "reasoning_output"]
```

Model parser 必须验证：

```text
model.adapter == referenced_provider.adapter
```

该双绑定是显式契约：Model 表达自己需要哪种解释语义，Provider 表达 endpoint 实际提供哪种解释器。运行时仍只为 Provider 构建 adapter 实例，不为每个 Model 重复实例化 adapter。

### Adapter Options 与 Protocol

`adapter_options` 是 Model 下由其 adapter 解释的完整选项对象。`protocol` 是只有具备真实模型协议分支的 adapter 才支持的判别 option：

```toml
[llm.models.custom_kimi.adapter_options]
protocol = "k3"
reasoning_effort = "max"
reasoning_keep = "content"
```

parser 先读取和校验 `protocol`，再按 adapter/protocol 校验其余 option。`protocol` 不发送给远端 API。

当前只有 Kimi 存在明确 protocol：

- `k2`：允许 K2 thinking 行为；不允许 `reasoning_effort`。
- `k3`：允许 `reasoning_effort = "max"`；不允许 K2 `thinking`。
- 两者共享 Kimi 的 `reasoning_keep` 与 `top_p`。
- Kimi Model 必须显式声明 `protocol = "k2" | "k3"`。
- 其它 adapter 当前不接受 `protocol`，不引入无真实意义的 `default`。

OpenAI、DeepSeek、GLM、MiniMax 与 Generic 保持现有 adapter 行为，只把选项支持范围收口到 adapter 规格；它们不依据 `provider_model` 或 TinySoul Model ID 选择分支。

### Provider Model

`provider_model` 只要求是非空字符串，并原样发送给目标 endpoint。官方模型名、代理别名和自定义路由名具有相同地位。TinySoul 不静态确认 endpoint 是否真实提供该名称，也不从名称推断 adapter 或 protocol。

### Request Overrides

`request_overrides` 继续与 `adapter_options` 同级，只表达模型对 provider-neutral 调用参数的固定覆盖。adapter 不解释该对象；修改 adapter、protocol 或 Provider 时不自动修改 request overrides。

### Custom Model 与 Preset

Custom Model 创建支持空白草稿与内置 Model preset：

- preset 只预填 adapter、Provider、provider model、context、capabilities、adapter options 和 request overrides。
- 用户在提交前可以修改预填值。
- 创建使用一次原子 PATCH 写入完整 Model。
- 创建后不保存 `based_on`、`template` 或其它来源关系。
- Custom Model 后续与 preset 独立演化。
- 复制 Custom Model 不作为 preset 继承语义；若保留复用入口，应明确表达一次性 duplicate。

删除权限继续只允许前端删除 custom source 中完整拥有的 Model；内置 Model 不从 package TOML 删除。

## 模块边界

### LLM

LLM 模块拥有 adapter 的业务规则：adapter kind、要求的 API style、支持的 protocols、公共 options、protocol 专属 options 和值校验。它负责：

- 解析 Provider 与 Model 的 adapter。
- 校验 Provider API style 与 adapter。
- 校验 Model/Provider adapter 一致。
- 校验 adapter options 与 protocol。
- 将 protocol 作为已校验的 adapter option 交给运行时 adapter。
- 向配置控制面提供不含展示文案的机器规则投影。

LLM 不提供设置页标题、说明或布局元数据。

### Infra Config

Infra catalog 继续统一维护所有配置字段的标题、说明、值类型、选项标签、重要性和分组。它接收 LLM 提供的机器规则投影并随 `/v1/config/catalog` 输出，但不解释 LLM 业务、不复制 LLM 校验逻辑。

现有 catalog 需要能够描述：

- Model 的 adapter 字段。
- `adapter_options.protocol` 的展示说明和 protocol 标签。
- adapter/protocol 对可用 option path 的适用关系。
- 缺失但可添加的 optional option。

### App 与 Endpoint

App 只在装配 ConfigController 时提供 LLM adapter 规则投影，不承担 adapter 业务判断。Endpoint 继续通过现有 `GET /v1/config/catalog` 暴露组合后的 catalog，通过现有 `PATCH /v1/config` 完成原子持久化与 Runtime Generation 重建，不增加独立 apply API。

### Visualization

前端不硬编码 adapter 描述、protocol 说明或 option 适用规则。Model 页面消费 catalog 中的机器规则与 Infra 描述，提供：

- Model adapter 展示与选择。
- 仅显示 adapter 相同的 Provider 绑定选项。
- adapter/protocol 联动。
- 当前 adapter/protocol 允许的 options 添加、修改和删除。
- request overrides 独立添加、修改和删除。
- Blank 或内置 preset 驱动的完整 Custom Model 草稿。
- 一次 PATCH 提交 adapter、Provider、protocol 和 options 的一致变更。

对于 protocol 切换，前端草稿保留新旧 protocol 都支持的公共 options，移除旧 protocol 独占 options，展示新 protocol 可用的 options；request overrides 保持不变。最终仍由后端 parser 校验完整候选配置。

## 实施步骤

1. 在 LLM 内建立 adapter 领域规格，统一 adapter kind、API style、protocol 和 option 支持范围，替换散落在 config parser 中的 adapter option key 表。
2. 为 `ModelSpec` 与 Model TOML 增加必填 adapter；解析时校验 Model/Provider adapter 一致，并让 runtime adapter 暴露自身 adapter kind 以守住直接装配边界。
3. 将 Kimi K2/K3 判断迁移为必填 `adapter_options.protocol`，删除所有依据 `provider_model` 的分支和校验；更新 Kimi runtime 映射与测试。
4. 更新全部 standard/development Model profiles、测试 fixture 与 LLM 设计文档，不保留旧配置兼容路径。
5. 扩展 Infra catalog 的 adapter 机器规则投影和 Model 字段描述；由 App 装配提供 LLM 规则，更新 Endpoint 协议文档和 catalog 测试。
6. 重构 visualization Model 设置页：实现完整草稿、Blank/内置 preset 创建、adapter/provider/protocol/options 联动、optional options 增删及原子提交；保持 custom-only 删除。
7. 增加后端与前端回归测试，覆盖 adapter 不一致、Kimi protocol、provider model 别名、Provider 筛选、preset 无继承、option 增删和 PATCH 失败保持原 Generation。
8. 同步 `docs/design/llm.md`、配置设置设计文档与本执行记录；运行聚焦测试、Fast、Full、typecheck、visualization tests/build，并按实际结果核对全部验收项。

## 验收标准

- Provider 与 Model 都显式声明 adapter，Model 不能绑定不同 adapter 的 Provider。
- `provider_model` 不再出现在任何 adapter 分支或 option 兼容性判断中，只用于远端请求和观测。
- Kimi K2/K3 完全由 `adapter_options.protocol` 区分，alias provider model 也能选择正确协议。
- LLM adapter 规格是 protocol/option 机器规则的唯一业务来源；前端不复制规则。
- Infra catalog 是配置标题、说明、分组和控件元数据的唯一来源。
- Custom Model 可以从 Blank 或内置 preset 建立，创建后不保存模板关系并可独立维护完整配置。
- Model 页面可添加、修改、删除允许的 adapter options 与 request overrides，并以原子 PATCH 提交一致配置。
- 同 adapter Provider 切换不改写 adapter options、request overrides、capabilities 或 provider model。
- 无效候选配置返回 `config.invalid`，磁盘内容与当前 Runtime Generation 保持不变。
- 设计文档、Endpoint 文档、测试、类型检查和前端构建与实现一致。

## 完成记录

已完成：

- Provider 与 Model 均显式声明 `adapter`，解析阶段强制二者一致；Provider 切换仍只允许同 adapter 目标。
- LLM 新增 adapter 规格与 protocol/option 机器规则，Kimi K2/K3 改由 `adapter_options.protocol` 选择，`provider_model` 不再参与分支。
- Infra catalog 增加 Model adapter/protocol 字段、custom 完整创建模板和 `rules` 机器规则扩展；App 装配时注入 LLM adapter 规则，Endpoint 原有 catalog/status/patch 协议保持不变。
- Visualization Model 页面支持 Blank 或内置 preset 的一次性 custom 创建，创建后无模板继承；按 adapter 过滤 Provider，按 adapter/protocol 过滤 options，并支持 options 与 request overrides 增删。
- 内置模型仍由 package TOML 提供，删除策略保持 `create_source_only`；Provider 切换不改写 model 的 options、overrides、capabilities 或 provider model。
- 已更新配置 profile、LLM 设计文档和回归测试。

验证：

- `C:\Anaconda3\envs\TinySoul\python.exe -m pytest tests/llm tests/infra/test_config_catalog.py tests/infra/test_config_controller.py tests/endpoint/test_endpoint_api.py tests/app/test_builder.py -q`
- `pnpm.cmd test -- --runInBand`
- `pnpm.cmd build`
