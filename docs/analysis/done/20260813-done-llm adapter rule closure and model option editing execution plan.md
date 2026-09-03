# LLM Adapter 规则收口与 Model Option 编辑闭环执行计划

状态：`done`

## 背景与复核结论

上一轮已把 adapter 提升为 Provider 与 Model 共同声明的领域标识，并引入
`adapter_options.protocol`。本轮以提交 `a803456` 为基线重新读取 `AGENT.md`、LLM、Infra
Config、Endpoint、App、Visualization 和测试后，确认主体设计已经成立，但规则闭环仍有
以下真实缺口：

1. adapter option 的允许 key 与 value 校验原本分散在 `AdapterSpec`、配置 parser 和运行时
   adapter，机器规则没有单一来源。
2. `ProviderSpec` 与 `ModelSpec` 的 adapter 曾存在隐式 generic 默认值，直接构造路径不能
   保证 Provider/Model adapter 是显式领域事实。
3. `ProviderAdapter` 协议未表达 adapter identity，共享运行时调用边界不能复验
   Model/Provider adapter 一致性。
4. `ProviderRequest.adapter_options` 与 `ModelSpec.adapter_options` 同时存在。TaskRunner 虽然
   复制 Model options 到 request，但直接调用可以传入另一份值；Kimi protocol 读取 Model，
   其它行为读取 request，形成两个相互冲突的运行时事实源。
5. Model 设置页只能编辑已经持久化的 option，不能从当前 adapter/protocol 允许的 optional
   options 中添加新项，也不能准确区分待编辑草稿与已存字段。
6. Endpoint catalog 文档未完整说明 App 注入的 adapter 机器规则。

## 确定的设计语义

### Adapter、Provider 与 Model

- Adapter 是 LLM 接入与模型行为的底层基石，当前稳定 identity 为 `generic`、`openai`、
  `kimi`、`deepseek`、`glm` 和 `minimax`。
- Provider 显式声明 adapter、API style、endpoint 和凭据引用；Model 显式声明 adapter、
  Provider 引用、`provider_model`、能力、adapter options 和 request overrides。
- Model 只能绑定 adapter 相同的 Provider。配置 parser 在最终候选树上校验该约束；运行时
  ProviderAdapter 也暴露 adapter identity，在共享调用入口复验直接装配路径。
- `provider_model` 只是发送给 endpoint 的不透明模型标识，不参与 adapter、protocol 或
  option 分支判断。endpoint 是否提供该名称由配置者负责。
- 更换同 adapter Provider 只修改 Provider 引用，不修改 `provider_model`、capabilities、
  `adapter_options` 或 `request_overrides`。
- Custom Model 可从空白配置或内置 Model preset 一次性复制完整值；创建后不保存模板来源、
  不继承、不跟随模板变化。内置 Model 由 package TOML 提供，只有 custom source 完整拥有的
  Model 可删除。

### Adapter Options 与 Request Overrides

- `AdapterSpec` 是 adapter 机器规则唯一来源，负责 API style、公共 options、protocol 分支、
  option 值类型/枚举/结构规则和完整配置校验。
- 存在真实协议分支时，`adapter_options.protocol` 是 adapter-owned 判别 option。当前只有
  Kimi 要求 `k2 | k3`；任何分支都不读取 `provider_model` 或 TinySoul Model ID。
- `ModelSpec.adapter_options` 是运行时唯一 adapter option 事实。`ProviderRequest` 不复制、
  覆盖或接受第二份 adapter options；adapter 行为和消息映射统一读取
  `request.model.adapter_options.values`。
- `request_overrides` 与 adapter options 同级，仍只由 TaskRunner 合并到通用调用设置；
  Provider adapter 不解释该配置容器。
- Adapter/protocol 变化时，前端保留仍适用的公共 options，删除不再适用的持久化和本地
  draft options；`request_overrides` 独立保留。最终候选仍由后端 parser 原子校验。

### 配置控制面与展示

- LLM 提供无展示文案的 `rules.llm.adapters` 机器投影；Infra catalog 是标题、说明、分组、
  控件类型、choices、collection identity 和删除策略的唯一维护位置。
- App 只在装配 ConfigController 时组合 Infra catalog 与 LLM 机器规则；Endpoint 继续通过
  `GET /v1/config/catalog` 暴露规则，通过 `PATCH /v1/config` 原子完成持久化和 Runtime
  Generation 激活，不增加独立 apply 接口。
- Model 页面把 optional option 区分为 `persisted` 与 `draft`。Add option 只创建本地 draft；
  首次提交才发送 set mutation；只有已持久化 option 显示删除操作。
- Provider 选项显示全部连接，但只允许当前 Model adapter 相同的 Provider。adapter/protocol
  联动只消费 catalog 机器规则，不在前端复制 adapter 业务判断或说明。

## 模块与改动范围

### LLM

1. 在 `adapter_types.py` 统一 AdapterKind 与 ProviderApiStyle 基础类型。
2. 扩展 `adapter.py` 的 AdapterSpec/AdapterOptionSpec/AdapterProtocolSpec，使其统一验证 API
   style、option key 与 value，并输出 JSON 机器规则。
3. 让 `config_sections.py` 只解析结构并调用 AdapterSpec；移除重复 option 业务规则。
4. 移除 ProviderSpec/ModelSpec adapter 默认值，保持公共导出路径清晰。
5. 扩展 ProviderAdapter 协议与共享 OpenAI SDK adapter identity 检查。
6. 删除 `ProviderRequest.adapter_options`；TaskRunner、payload mapper 和所有 provider behavior
   统一读取 Model options。直接 adapter 测试通过 test-only builder 把 options 写入 ModelSpec。

### Infra、App 与 Endpoint

- Infra catalog 继续维护 Model adapter/protocol/options/request overrides 的字段描述，以及
  custom-only 删除策略和创建模板。
- App 注入 `adapter_specs_json()`；Endpoint 保持既有 catalog/status/patch 与原子激活协议。
- 同步 catalog 和 Endpoint 协议测试，确认机器规则可读取且展示文案不进入 LLM。

### Visualization

- 在配置字段投影中增加 `persisted` 语义。
- 根据 catalog descriptors 与 `rules.llm.adapters` 计算当前 adapter/protocol 可用 options。
- 增加 Add option 草稿、首次 set、持久化项 delete，以及 adapter/protocol 切换后的 draft
  清理行为。
- 保持 preset 仅用于一次性 custom 创建，保持 custom-only 删除和同 adapter Provider 筛选。

### 测试与文档

- 更新 fake Provider/Model fixture，使 adapter 显式必填。
- 覆盖 AdapterSpec key/value/API style、Kimi protocol、provider model alias、运行时 identity
  mismatch、Model options 单一事实源、同 adapter Provider 切换和 PATCH 回滚。
- 覆盖 Model optional option 添加/删除/draft、protocol 切换和 custom preset 独立创建。
- 更新 `docs/design/llm.md` 与 `docs/endpoint/frontend integration.md`。

## 实施顺序

1. 收口 AdapterSpec 与显式 adapter 类型，删除 parser 重复规则。
2. 建立 ProviderAdapter identity 并守住共享调用边界。
3. 删除 ProviderRequest 的 adapter options 副本，统一运行时读取路径并更新直接调用测试。
4. 完成 Infra catalog 机器规则组合和文档。
5. 完成 Visualization optional option 草稿闭环及前端测试。
6. 运行后端聚焦测试、完整测试、类型门禁、前端 tests/build，并逐项核对本计划。
7. 仅在实现、文档和验证全部完成后把状态改为 `done`，记录实际命令和结果。

## 验收标准

- Provider 与 Model 的 adapter 均显式必填，配置和直接调用路径都不能执行 adapter 不一致
  的 Model/Provider 组合。
- `provider_model` 不参与任何 adapter/protocol/option 分支。
- AdapterSpec 是 adapter option 业务规则的唯一静态来源；配置 parser 不维护第二份规则表。
- `ProviderRequest` 不包含 adapter options；所有 adapter 只读取 Model 的已校验 options。
- Kimi K2/K3 完全由 `adapter_options.protocol` 决定，alias provider model 行为一致。
- Model 页面可添加、修改和删除允许的 adapter options 与 request overrides；draft 不显示
  删除操作，adapter/protocol 切换不会留下无效 option 草稿。
- Custom Model preset 是一次性值复制，无模板关系；内置 Model 不可从设置页删除。
- 无效 PATCH 不写磁盘、不替换当前 Runtime Generation；有效 PATCH 返回新 generation id。
- 后端测试、类型检查、Visualization tests/build 全部通过，文档与实际实现一致。

## 实施记录

已完成：

- `AdapterSpec`、`AdapterOptionSpec` 与 `AdapterProtocolSpec` 统一承载 adapter API style、
  option key/value、protocol 分支和 JSON 机器规则；配置 parser 不再维护第二份 adapter 规则。
- Provider 与 Model 的 adapter 保持显式必填，Model parser 校验 Provider/Model adapter 一致，
  ProviderAdapter 协议暴露 `adapter_kind`，OpenAI SDK 共享 adapter 在调用前拒绝 identity mismatch。
- Kimi K2/K3 只由 `adapter_options.protocol` 选择；未发现或保留任何基于 `provider_model` 的
  TinySoul 行为分支。
- `ProviderRequest.adapter_options` 已从生产请求类型删除；TaskRunner、payload mapper、
  DeepSeek/Kimi/OpenAI 行为统一读取 `request.model.adapter_options.values`。直接 adapter 测试
  使用 test-only builder 把 options 写入 ModelSpec，不再模拟第二个运行时事实源。
- Infra catalog 继续集中维护所有配置描述、分组、choices、collection identity、custom-only
  删除策略和创建模板；App 注入 `rules.llm.adapters`，Endpoint 文档同步说明机器规则协议。
- Visualization Model 设置页支持按 adapter/protocol 规则添加 optional option 草稿，首次提交
  使用 set，只有 persisted 字段显示删除；Provider 筛选、custom preset 一次性复制和内置模型
  删除限制保持不变。

验证：

- `$env:TINYSOUL_PYTHON='C:\Anaconda3\envs\TinySoul\python.exe'; .\scripts\test.ps1 -Suite Full`
  通过：`916 passed, 2 skipped, 21 deselected`。
- 同一解释器执行 `scripts/typecheck.ps1`：`All checks passed!`。
- `visualization`: `pnpm.cmd test -- --runInBand` 通过，`16 files / 92 tests`；
  `pnpm.cmd build` 通过（仅保留既有 chunk size warning）。
- `git diff --check` 通过；第三方 Starlette TestClient deprecation warning 与既有基线一致。
