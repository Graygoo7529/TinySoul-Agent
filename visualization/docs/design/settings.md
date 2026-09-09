# Settings 与配置管理

## 定位

Settings 是主导航中的独立工作页，负责项目 TOML、项目 dotenv credential 和客户端偏好。
前端不直接访问运行目录，不解释业务 parser，也不持有第二份可写配置 tree。`ConfigStatus` 是
当前配置事实；Infra catalog 只提供集中维护的展示语义；Action catalog 提供当前 Generation 的
configured User Action、effective availability/runtime 与项目 document 编辑绑定。

字段标题、说明、value kind、primary/advanced 层级、static choices、reference target 和
credential reference 全部来自 `GET /v1/config/catalog`。前端不得按 dotted path 生成标签、猜
页面归属或复制业务默认值；unknown descriptor 应进入可诊断只读表面，而不是静默隐藏。

## 信息架构

桌面端使用一列栏目侧栏，栏目标题不可点击，子页面才是导航入口：

```text
GENERAL             Overview · Application · Credentials
MODELS & ROUTING    Providers · Models · Task Chains
Actions             Catalog
CAPABILITIES        Web · Resource · Execution
CONTEXT             Home · Session · Memory · Workspace · Context Rules
RUNTIME             Behavior · Maintenance · Infrastructure
```

Task Chains 页面内部提供 Chains/Cycle Routing/Action Routing 局部入口；Infrastructure 页面内部
提供 System/Embedding 局部入口。窄屏先选择栏目，再横向选择该栏子页；不建立第二列侧栏。
Application 未连接时仍可用，其余项目页面禁用。

## 状态与刷新

`configStore` 同时读取：

- `GET /v1/config` 的 sources/effective fields/activity/Generation；
- `GET /v1/config` 中 `runtime.llm.providers` 的当前 Generation Provider 凭据就绪状态；
- `GET /v1/config/catalog` 的 package-owned descriptors；
- `GET /v1/config/actions` 的 configured User Domains/Actions 与 availability。

实例切换或断开时三者一并清空。并发请求仍使用最后一次请求获胜；PATCH 返回 active 后并发刷新
ConfigStatus 与 Action catalog，catalog 作为同一 package contract 无需每次 PATCH 重读。事件只
使权威快照失效，不从 Observation payload 派生第二份激活状态。

## 通用字段页

每个 surface 页包含用途说明、Runtime activity、Primary 字段、默认关闭的 Advanced 和
Read-only 折叠区。字段主信息只显示 catalog title/description；dotted path、source path、
effective source/value 收进 Details。Turn 活跃时所有字段继续可读，仅禁用控件。

boolean 使用 switch，enum/reference 使用 select，scalar 使用输入框，普通 structured value 使用
JSON editor。reference options 从 catalog collection 与当前 ConfigStatus 枚举，不硬编码对象列表。

## 对象页

Provider、Model、Task Chain 不是前端状态实体，只是 catalog collection root 下的动态视图。页面
使用对象列表加详情编辑器，不显示反向引用或全局 current Provider。

- Provider 支持完整 root 创建、字段编辑和删除；`adapters` 使用整值列表编辑，列表摘要展示 enabled、Adapter 集合和 endpoint。Adapter 的 API style 来自 catalog 中的静态 Adapter 规则，只读展示而不形成 Provider 配置字段。摘要和详情同时展示当前 Generation 的凭据状态：`Credential required`、`Ready to enable` 或 `Enabled`。
- Provider 从 disabled 切换为 enabled 前，页面先检查 `runtime.llm.providers` 的就绪投影。凭据缺失时不发送 PATCH，提示所需环境变量并提供前往 Credentials 的操作；后端仍执行同一校验并对竞态或外部客户端返回的 `422 config.invalid` 负责。
- Model 新建默认从 Blank 开始，不复制现有 Model。Blank 创建仍使用 catalog 提供的必需字段、首个兼容 Provider 和其 Adapter，首个 `provider_model` 使用新 Model ID；用户也可以主动选择已有 Model 作为模板，完整复制其 `adapter_options`、`request_overrides` 和 Provider Chain。Provider Chain 编辑器按顺序展示 Provider 与 `provider_model`，支持增删排序并以完整数组写回。切换 Model Adapter 会同时选择兼容的 Provider Chain，清理不适用的 Adapter options；若 adapter 不兼容，PATCH 失败并保留当前编辑 draft 与已激活配置。
- Provider Adapter 与 Model Provider Chain 编辑器都直接持有对应复合根字段，以该字段的
  `storedValue`、`sourceId`、`path` 和 `writable` 作为唯一配置事实。Model 是否由 create source
  创建只决定删除权限和内置 Adapter 锁定，不决定 Provider Chain 是否可写；数组元素 descriptor
  只提供编辑元数据，不构成可独立提交的字段。
- Task Chain 新建至少选择一个 Model；models 禁止重复或为空，支持拖放与上下移动图标，写回
  完整有序数组。列表摘要分别显示 Cycle Phase、Action default 和 Action override 数量；没有任何
  路由引用的 chain 只显示模型数量，不把合法闲置定义标记为错误状态。
- Cycle Routing 编辑 User Turn 与所有 Maintenance Turn 共享的 Phase1/Phase2 task profile 引用。
- Action Routing 编辑 default profile；override 只能选择当前 Action catalog 中
  `available=true && backend.kind=llm_action` 的 Action 和当前 Task Chain。删除 override 自动回退 default。

## Action Catalog

`ACTIONS / Catalog` 按 Domain 列表、Domain 设置、当前 Domain 的 Action 列表和 Action 详情组织。
Domain 导航同时展示简短 description；description/selection hint 是主要字段，Domain timeout 位于
Advanced，Domain Runtime 提供可继承的 Default Action Enabled。稳定 identity、parallel policy、
hooks 与 trace mode 位于 Read-only Contract。Action tool
description、use/avoid hints 是主要字段；effects、examples 和专用 timeout 位于 Advanced；稳定 identity、
完整 schema、parallel policy、hooks、trace mode 和 backend 位于默认折叠的 Read-only Contract。
`execution.wait` 通过 Infra document field group 额外展示 minimum/default/maximum Wait Policy。
Action Availability 组提供 Action-local enabled 开关和恢复 Domain default 的操作；列表与详情分别
表达 Disabled、Unsupported 与 Available，两个不可用原因可以同时存在。unsupported 项保持可读可编辑，
因为 activation 与 runtime owner support 是独立事实。

每个可写字段使用 Action 投影的 document `source_id` 与文件内 local path 提交普通 ConfigMutation。
字段标题、说明、choices 和层级全部来自 Infra `document_fields`；页面不按 Action ID 或 path 硬编码
业务说明。控件只有在 local path 同时存在于 source `editable_paths` 时才可写；其它字段保持可读。
Action timeout 删除后恢复继承并显示新的 effective value/source。
Action enabled 同样显示 `action | domain | default` provenance；删除本地值恢复 Domain/default。

创建/替换对完整 object root 执行 `set`，删除执行 `delete`。Provider 和 Task Chain 使用 catalog
template；Model 写入 catalog 预声明的 `configs/llm/models/custom.toml`。Backend parser 与候选
Generation 校验仍是最终权威。

## Credentials

Credentials 从 catalog 中 `credential_reference=true` 的有效字段值和 dotenv 当前键合并。页面
只显示、编辑或删除 dotenv stored value；系统进程环境不枚举、不编辑。输入默认遮罩，区分
Unset、Empty 和 Configured。Provider 页面使用 Runtime 的 `configured | missing` 投影判断是否
可以启用；纯空白值与后端一样视为未配置。

## 写入与激活

每次用户提交直接调用 `PATCH /v1/config`。后端在返回前完成候选校验、Generation 构建、文件
原子提交和 RuntimeHandle 切换；前端没有独立 Apply Runtime 或 revision。单字段通常提交一个
mutation；Task order 和 Action overrides 使用一次 batch/完整数组 mutation。

任意 User Turn、Maintenance Turn、Daily Transition 或 config activation 期间，页面完整可读但
统一禁用。Backend 错误保留当前编辑器 draft 并显示 owner 提供的 message；成功提示显示 receipt
Generation id，再以权威 GET 替换页面事实。
