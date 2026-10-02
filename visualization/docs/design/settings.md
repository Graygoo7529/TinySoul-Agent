# Settings 与配置管理

Settings 页面维护前端本地配置草稿、后端配置的只读视图与本地界面偏好。字段目录、类型和可用性来自 v2 catalog/config/actions；页面不直接读写配置文件。

## 草稿与应用

用户可以先批量修改本地 ConfigDraft，主应用入口通过 `POST /v2/config/apply` 一次保存并发布；`POST /v2/config/reload` 激活已保存候选。后端还提供仅保存候选的 `PATCH /v2/config`，页面编辑控件不会逐项调用它。发布前失败保留草稿，用户可修正或放弃；已发布后的清理诊断不反转成功结果。

命名配置使用 `/v2/config/presets` 创建、查看、重命名和删除，按后端限定范围捕获模型路由及可选预算，不包含凭据。保存方案不隐式应用；切换运行方案前必须明确处理未应用草稿。

## 页面语义

- 模型页维护各类 provider、模型及排序；稳定的 provider/model ID 保持原样。
- 行为页维护 Action 的模型用途、Search 策略和 Phase 绑定。
- 数据页维护 Home、Memory、Session、Workspace 等 owner 的配置。
- 工具页维护 MCP、ACP、Web 和执行能力。
- 界面页维护连接地址、主题和本地偏好。

页面分组与用途说明由 `labels.ts` 提供，`i18n/` 维护中文 UI 文案和 catalog 字段映射。先匹配后端实际声明的字段，再翻译标题、说明和枚举显示标签；Action 文档按 document kind/path 映射。映射不增加字段、默认值或校验规则。

搜索同时索引中文、后端原文与稳定路径。没有翻译的新字段回退为原文；后端动态错误保留原始诊断。协议 ID、路径、provider/model/action 名称、枚举 value 和用户输入均不翻译。增加字段时可在 `catalog.zh-CN.ts` 补充标题与说明；页面固定文案在 `ui.zh-CN.ts` 维护。
