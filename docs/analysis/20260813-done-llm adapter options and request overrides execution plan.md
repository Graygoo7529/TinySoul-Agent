# LLM Adapter Options 与 Request Overrides 执行计划

状态：`done`

## 目标

将模型配置中混合承载 adapter 私有选项与通用请求覆盖的 `provider_options` 拆分为两个同级概念：

- `adapter_options`：由 Provider 所选 adapter 解释的模型级选项。
- `request_overrides`：模型对通用调用参数的固定覆盖。

保持既有 Provider、Model 和配置激活边界：Provider 绑定 endpoint、凭据、API style 与 adapter；Model 绑定 Provider 引用、provider model 与能力。切换 Model 的 Provider 引用时不自动改写或删除两个选项对象；若新 Provider 的 adapter 无法解释现有 `adapter_options`，配置解析失败，`PATCH /v1/config` 不持久化候选配置且当前 Runtime Generation 保持不变。

项目仍处于开发阶段，不保留 `provider_options` 兼容别名，也不执行数据迁移。

## 设计边界

1. LLM 配置解析器拥有业务配置解释与 adapter 选项兼容性校验；Infra catalog 只维护配置页面需要的路径、说明与分组元数据。
2. `ModelSpec` 分别持有 `AdapterOptions` 与 `ModelRequestOverrides`，不再从 adapter 私有字典中反向提取通用调用参数。
3. TaskRunner 在创建 `ProviderRequest` 前，将模型级 `request_overrides` 覆盖到任务级 `CallSettings`；Provider adapter 只接收已解析的通用请求字段和 `adapter_options`。
4. 配置 endpoint 继续使用既有原子候选配置和 Runtime Generation 重建流程；前端切换 Provider 只提交 Provider 字段，由后端统一验证整个候选模型配置。

## 实施步骤

1. 重构 LLM 模型类型、配置 helper/parser、TaskRunner 与 ProviderRequest 协议。
2. 迁移全部 Provider adapter 对 `adapter_options` 的消费，并删除 adapter 层的 `request_overrides` 解析。
3. 更新 standard/development profiles、Infra catalog 和设置页设计说明。
4. 更新单元测试，覆盖同 adapter Provider 切换保留配置、不同 adapter 不兼容时 PATCH 回滚，以及 request overrides 在 TaskRunner 生效。
5. 同步 `docs/design/llm.md`，运行聚焦测试、`Full`、`typecheck` 与 visualization 门禁；通过后将本记录标记为 `done`。

## 验收标准

- 仓库的活动代码、profiles 与 catalog 中不存在 `provider_options`。
- `adapter_options` 和 `request_overrides` 是 Model 下的同级配置对象。
- Provider adapter 不解析或接收 `request_overrides` 容器。
- 仅切换到同 adapter Provider 时两个对象原样保留并可成功激活。
- 切换到不兼容 adapter 时 PATCH 失败，磁盘配置与当前 Generation 均维持原样。
- 文档、类型检查、后端测试与前端门禁通过。

## 完成记录

- `tinysoul.llm.models` 以 `AdapterOptions` 和 `RequestOverrides` 两个类型表达独立模型配置事实，`ModelSpec` 分别持有二者。
- `ModelConfigParser` 解析同级 `adapter_options`/`request_overrides`，并在候选配置阶段校验 adapter 字段集合、值类型、推理保留形态及 Kimi K2/K3 协议差异。
- `LLMTaskRunner` 在 ProviderRequest 构造前应用模型级 request overrides；ProviderRequest 与所有 provider adapter 只传递和解释 `adapter_options`。
- standard/development profiles、Infra catalog、LLM 设计文档和 Settings 设计说明已迁移；catalog 中 adapter 字段集合与当前 parser/adapter 支持保持一致。
- endpoint 回归测试验证：同 adapter Provider 切换仅修改 provider 引用并保留两个对象；不兼容 adapter 返回 `config.invalid`，源文件和 Runtime Generation id 均保持原样。
- 验证通过：LLM 与 endpoint 聚焦测试、Fast `914 passed`、Full `915 passed`、typecheck、visualization `89 passed` 与 production build。
