# Model Provider 绑定与 Custom 删除执行计划

状态：`done`

## 目标

让设置页以清晰、低误操作的方式管理 Model，同时保持配置 Endpoint 面向可信配置者的高权限和灵活性：

- 既有 Model 在页面中更换 Provider 时，只允许选择与当前 Provider 使用相同 adapter 的 Provider；不比较、不改写也不删除 `adapter_options`、`request_overrides`、capabilities 或 `provider_model`。
- `llm.providers.<provider>.adapter` 仍可直接编辑；后端只校验最终候选配置是否合法，不增加新旧配置转换约束。
- 设置页只允许删除完全定义在 Model collection `create_source` 中的 Custom Model；内置模型及跨 source 模型不显示删除命令。
- `PATCH /v1/config` 继续允许直接修改或删除任意可写 project TOML，不把前端交互策略扩张为后端权限规则。

## 设计语义

### Provider 绑定

Provider 拥有 endpoint、凭据、API style 与 adapter；Model 引用 Provider，并拥有 provider model、能力、adapter options 与 request overrides。

设置页将“更换 Provider”解释为同 adapter endpoint 之间的轻量重绑定：

1. 从当前 Model 的 Provider 引用解析当前 adapter。
2. Provider 选择器展示全部 Provider 及其 adapter，但只允许选择 adapter 名称相同的项。
3. 提交只修改 `llm.models.<id>.provider`。
4. 无法静态确认目标 endpoint 是否提供现有 `provider_model`，由配置者负责。

该规则只属于前端 Model 编辑体验。Provider adapter 可以独立编辑，直接 Endpoint batch PATCH 也不受新旧 adapter 比较限制。LLM parser 继续在候选配置边界校验最终 `adapter_options`，但不把 options 兼容性作为前端 Provider 选择算法。

### Collection 删除策略

Infra catalog 继续只维护配置展示与交互元数据。Collection 使用明确的 `delete_policy`：

- `all`：设置页允许删除任意 collection 对象。
- `create_source_only`：只有对象全部 project TOML 定义都来自 collection `create_source` 时允许删除。
- `none`：设置页不提供删除命令。

Model collection 使用 `create_source_only`；Provider 和 Task Chain 使用 `all`。对象不增加 `custom = true` 配置字段。Custom 身份由 source graph 派生：对象根下所有 project TOML 字段的 source ID 集合必须精确等于 `{create_source}`。内置模型被 `custom.toml` 局部覆盖后具有多个 source，仍不可由页面删除。

`delete_policy` 只控制前端命令是否出现；Infra `ConfigController` 不执行 collection policy，也不 import LLM 业务语义。

## 改动范围

### Infra catalog

- `tinysoul/infra/config/catalog.py`
  - 增加 collection delete policy 枚举。
  - 用 `delete_policy` 替换 `allow_delete`，完成 TOML 解析与 JSON 投影。
- `tinysoul/infra/config/catalog/models.toml`
  - Provider、Task Chain 声明 `all`。
  - Model 声明 `create_source_only`。
- catalog 测试覆盖枚举解析、JSON 投影和 Model 策略。

### Visualization

- `visualization/src/types.ts`
  - 同步 `ConfigCollectionDeletePolicy` 与 collection descriptor。
- `visualization/src/features/settings/model.ts`
  - 为 collection object 派生 contributing project source IDs。
  - 提供基于 `delete_policy` 的 `objectDeletable`。
  - 提供 Model 当前 adapter 与 Provider 选项投影所需的纯函数。
- `ConfigValueControl`、`ConfigFieldRow`、`ObjectFieldEditor`
  - 支持页面为特定 reference 字段提供 label/disabled 选项覆盖，不改变其它字段默认引用行为。
- `ModelsSettingsPage`
  - Provider 选择器显示 Provider ID 与 adapter，禁用不同 adapter 项。
  - Custom Model 显示 Custom 标记和删除命令；内置/跨 source Model 显示 Built-in 标记且不渲染删除命令。
- `ObjectSettingsLayout`
  - 支持按当前对象隐藏删除命令，并支持对象状态标记。
- Provider、Task Chain 页面迁移到 `delete_policy`。

### 文档

- 更新 `docs/design/infra.md`、`docs/design/endpoint.md` 与 `docs/design/llm.md`。
- 完成验证后将本记录状态改为 `done`，并记录实际门禁结果。

## 验收标准

1. Model 页面同 adapter Provider 可选择，不同 adapter Provider 可识别但不可选择。
2. 更换 Provider 只提交 provider 字段，模型的其它配置不改变。
3. Provider adapter 仍可在 Provider 页面编辑，Backend 不增加 transition validator。
4. 仅完全定义在 `configs/llm/models/custom.toml` 的 Model 显示删除命令。
5. 内置模型和跨 source 模型不显示删除命令；直接 Endpoint PATCH 能力不变。
6. Infra catalog、前端纯函数和页面交互测试覆盖新语义。
7. Backend Full、typecheck、visualization test/build 与 `git diff --check` 全部通过。

## 完成记录

- Infra catalog 已以 `all`、`create_source_only`、`none` 三值 `delete_policy` 替换 collection 的
  `allow_delete`；该策略只通过 JSON catalog 投影给设置页，`ConfigController`、Endpoint、AppBuilder
  与 Runtime Generation 均未增加权限或转换约束。
- Model collection 使用 `create_source_only`。前端从 ConfigStatus 的 project TOML source graph
  派生对象来源；只有全部定义都来自 `configs/llm/models/custom.toml` 的 Model 显示 Custom 和删除
  命令，内置及跨 source Model 显示 Built-in 且不渲染删除命令。
- Model 页 Provider 选择器展示 Provider ID 与 adapter；当前 Provider adapter 名称相同的项可选择，
  不同 adapter 的项可见但禁用。提交仍只修改 Model 的 Provider 引用，不触碰 adapter options、
  request overrides、capabilities 或 provider model。
- Provider adapter 自身继续正常可编辑；直接 `PATCH /v1/config` 的高权限 source-aware 写入能力保持
  不变，最终候选配置仍由现有业务 parser 校验并通过 Runtime Generation 重建激活。
- 验证通过：Infra catalog 聚焦测试、Backend Full `915 passed, 2 skipped, 21 deselected`、全项目
  `ty`、visualization `16 files / 92 tests`、production build 与 `git diff --check`。
