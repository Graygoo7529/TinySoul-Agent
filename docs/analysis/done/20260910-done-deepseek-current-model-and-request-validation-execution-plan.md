# DeepSeek 当前模型与请求校验执行计划

状态：`done`

## 背景与结论

DeepSeek 当前以 `deepseek-flash` 表达持续更新的 Flash 产品路线；历史
`deepseek-v4-flash-vision-exp` 名称仍可调用，但由当前 Flash 服务。TinySoul 内部模型身份
因此不再绑定具体 V4 版本，而使用 `deepseek_pro` 与 `deepseek_flash`。Provider Binding 继续
保存各 endpoint 实际接受的远端名称，不据此选择 adapter 行为。

现有 OpenAI SDK 形态 adapter 在构造 payload 前调用 `validate_tools`。该 hook 已同时承担工具
数量、strict tool、thinking 与 reasoning replay 等请求组合约束；DeepSeek Vision 还要求图片
只出现在 user message。继续把消息约束塞入 `validate_tools` 会造成职责与名称不一致，而重写
DeepSeek adapter 的完整调用流程会复制公共映射。因此公共 behavior 使用单一
`validate_request` 预检入口，供应方内部按需以私有函数拆分具体规则。

## 已确认设计语义

- 内置模型 identity 从 `deepseek_v4_pro`、`deepseek_v4_flash` 分别迁移为
  `deepseek_pro`、`deepseek_flash`，不保留兼容 alias。
- `deepseek_pro` 的远端模型名保持不变；内置 Task Chain 只把旧 Pro identity 替换为
  `deepseek_pro`，不自动加入 `deepseek_flash`。
- `deepseek_flash` 首选 Orca 的 `deepseek/deepseek-v4-flash-vision-exp`，备用 DeepSeek 直连的
  `deepseek-flash`；两个 binding 必须共同满足 Model 声明的图片、远程图片、JSON、推理与工具
  能力。
- `validate_request` 是 OpenAI SDK 形态 adapter 在 payload 构造前调用的供应方请求预检入口。
  它不替代 `ProviderRequest` 结构校验、Task capability policy、配置 schema 或服务端配额。
- DeepSeek 的非 user 图片属于 model-scope capability failure，使用
  `ProviderErrorKind.CAPABILITY`，不成为局部模型输出失败，也不误归为 transient provider
  failure。
- 不增加 Files API、图片文件探测、尺寸/数量配额镜像或新的前端协议。设置页继续从现有配置
  status/catalog 动态显示模型与能力。

## 实施事项

1. `done`：迁移 development/standard 模型 identity、Flash binding/capabilities 与 Task
   Chain 引用。
2. `done`：把公共 behavior 预检入口改为 `validate_request`，同步各供应方 behavior，并为
   DeepSeek 增加图片 message role 校验。
3. `done`：更新初始化、LLM 配置、adapter 与 external provider 测试，保持测试聚焦当前真实
   契约。
4. `done`：同步 `docs/design/llm.md` 的当前 DeepSeek 模型、视觉边界与请求预检职责。
5. `done`：迁移 `B:\WorkSpace\my-agent-dev` 的模型与 Task Chain 配置，验证候选配置可解析。
6. `done`：使用已有凭据验证 DeepSeek/Orca 的 Flash 文本、图片、远程图片和 thinking tool
   calling；若 binding 能力不一致则停止并重新确认，不降低或伪造 Model 能力。
7. `done`：运行聚焦测试、Fast、Full、typecheck 与 diff 检查，逐项核对后将本计划标记为
   `done`。

## 验收标准

- 新生成的 development/standard 项目只包含 `deepseek_pro` 与 `deepseek_flash`；全部内置
  Task Chain 不再引用旧 identity。
- `deepseek_flash` 的两个 Provider Binding 均能承载已声明能力；配置与真实调用结果一致。
- OpenAI SDK 公共 adapter 只调用语义完整的 `validate_request`，代码中不再存在作为公共入口的
  `validate_tools`。
- DeepSeek 在发送 provider 请求前拒绝 system/assistant 图片，并允许 user 图片进入现有 Chat
  payload 映射；失败类型与 model-scope 切换策略一致。
- Endpoint 与 Visualization 不需要专用模型清单或条件分支；现有动态配置页面自然展示新身份。
- 完整本地门禁通过，设计文档、执行记录、代码和测试一致。

## 实施与核对结果

- development/standard 的 DeepSeek 配置已迁移到 `deepseek_pro`、`deepseek_flash`，Task Chain
  只迁移 Pro identity；`deepseek_flash` 的两个 Provider Binding、1M context window、视觉与工具能力
  位于对应 profile 的 `configs/llm/models/deepseek.toml`。
- OpenAI SDK 形态 adapter 在 adapter identity 校验后、name map 与 payload 构造前调用
  `validate_request`；DeepSeek behavior 使用私有校验函数分别拥有图片角色、工具限制和 thinking
  reasoning replay 约束。GLM、Kimi、MiniMax 已同步到同一 hook，不保留旧公共入口。
- `B:\WorkSpace\my-agent-dev` 已迁移为同一模型和 Task Chain 配置，并由当前
  `ConfigEnvironment`、`LLMConfigParser` 成功解析；解析结果不再包含旧 DeepSeek identity。
- 真实调用验证通过：Orca 的 Flash Vision Exp binding 完成文本、内联 PNG、JSON、远程图片、
  thinking 和两轮工具调用；DeepSeek 直连 `deepseek-flash` 完成内联 PNG、远程图片，以及携带
  reasoning 回放的两轮工具调用。验证过程未输出凭据，临时探针已删除。
- 聚焦测试通过：`112 passed`；Fast 通过：`973 passed, 2 skipped, 28 deselected`；Full 通过：
  `978 passed, 2 skipped, 23 deselected`；`scripts/typecheck.ps1` 通过；`git diff --check` 通过。
