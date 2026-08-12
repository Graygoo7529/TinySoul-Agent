# Configuration Semantic Settings Experience Execution Plan

状态：pending

## 背景

当前配置 Endpoint 已经能够完整读取项目配置 source，在 Runtime 空闲时以一次
`PATCH /v1/config` 原子完成候选校验、TOML/dotenv 持久化和 Runtime Generation
切换。visualization 也已经能够读取这些字段并进行基本编辑。

现有设置页面仍以 dotted path 和顶层 section 为主要组织方式：前端自行把
`llm`、`memory`、`infra.embedding` 等路径分配到少量页面，再按路径片段生成分组和
显示名称。这种方式适合验证配置读写链路，但无法表达 Provider、Model、Task Chain、
Action Route、Capability Domain 等真实业务对象，也缺少字段说明、枚举、约束、重要程度和
对象关系。因此继续在前端扩充路径判断会形成独立于模块 parser 的第二套配置语义。

本计划在不改变现有“持久化成功即当前实例激活成功”语义的前提下，为配置提供业务模块
自有的描述和对象投影，并据此重构设置页面的信息架构与交互。

## 目标

1. 设置页按业务语义组织，而不是按 TOML 文件或顶层 key 组织。
2. 每个配置项具有准确名称、用途说明、输入类型、约束和重要程度。
3. 核心配置默认可见；不常修改的高级配置和只读配置分别折叠。
4. Provider、Model、Task Chain 和 Action Route 使用对象化的列表与编辑器。
5. 支持创建 Provider、基于已有 Model 创建新 Model、创建 Task Chain，并把 Chain
   绑定到具体 `llm_action` Action。
6. Capabilities 保持当前模块所有权，但按能力域展示服务开关、具体能力和高级限制。
7. 前端不复制业务 parser 规则；候选配置仍由所属业务模块进行最终校验。
8. 所有配置修改继续通过一次 `PATCH /v1/config` 同步完成持久化与 Runtime
   Generation 激活，不新增独立 apply 流程。

## 非目标

- 不提供任意项目文件浏览或编辑 API。
- 不建立通用插件配置平台或允许前端任意注册配置 schema。
- 不引入全局“当前 Provider”；Provider 只是 Model 引用的轻量连接配置。
- 不在 Provider 页面展示引用它的 Model，也不在 Model 页面展示引用它的 Chain。
- 不把 Embedding 并入 LLM 或 Capabilities；它继续属于 Infra 基础能力接入。
- 不重构当前 LLM Provider、Model 和 Task 的核心执行结构。
- 不提供配置 revision、字段级 `currently_writable` 或第二个激活接口。
- 不把每个配置文件直接映射为一个前端页面。

## 已确认设计语义

### 配置事实、描述和呈现分层

配置体系分为三层：

1. **配置事实**：Infra 持有 source graph、stored value、effective value、来源、静态
   writable、候选文档和配置事务。
2. **业务语义**：LLM、Action、Capabilities、Memory、Workspace 等模块解释自己的
   Settings，并提供本模块配置字段和对象的描述。
3. **前端呈现**：visualization 决定设置页侧边栏目、页面布局、对象列表、编辑器和折叠
   交互，不重新定义字段约束或对象关系。

Infra 只定义可序列化的通用描述类型，不写入 LLM、Memory 或 Capability 的字段知识。
各业务模块把描述放在自己的配置边界附近，并与 parser 共同维护。App 只组合模块提供的
描述和当前 `AppConfigPlan` 投影，不解释业务字段；Endpoint 只做 HTTP DTO 适配。

### 写入与激活

- 页面始终可读。
- 顶层 `activity.can_write` 是当前是否可修改的唯一即时状态。
- User Turn、Maintenance Turn 或配置激活期间，所有编辑控件统一只读。
- 一次 UI 保存可以提交一个或多个 source-aware operations。
- Backend 在同一次 PATCH 内构建完整候选配置和 Runtime Generation；只有新
  Generation 已完成切换才返回成功。
- UI 收到 PATCH 成功响应即可认定持久化和当前实例激活均已完成，然后刷新配置状态。
- 不增加 revision、expected revision、独立 validate-and-apply 或异步激活轮询。

### 对象关系方向

设置页只展示配置本身具有的正向关系：

```text
Provider <- Model.provider
Model    <- TaskChain.models（有序）
TaskChain <- LLM Action Route.task_profile
```

Provider 不维护 Model 列表，Model 不维护 Task Chain 列表。删除仍由后端完整候选校验保护：
删除被引用对象会得到所属模块的明确配置错误，前端显示错误但不维护反向引用状态。

### Provider

- 不存在全局 Provider 或“当前 Provider”。
- Provider 只描述一个可供 Model 引用的 API 接入：enabled、adapter、API style、
  base URL 和 credential environment names。
- Provider 页面支持新增、编辑和删除；实际 API key 值仍在 Credentials 页面编辑。
- Adapter 决定供应商行为；API style 与 adapter 的约束由 LLM parser 校验。创建表单应根据
  adapter 自动填充合理 API style，但后端仍是最终权威。

### Model

- Model 显式引用一个 Provider，不重复持有 adapter。
- Model 页面展示 Provider、provider model id、context window、capabilities 和
  provider-specific options。
- 创建 Model 采用“基于已有 Model”流程。复制相同 Provider 或相同 adapter kind 时可以
  复用 provider options；更换为不同 adapter kind 时只复制通用字段，并清空供应商专用
  options。
- Provider options 属于高级配置；前端根据 LLM descriptor 展示允许字段，不能接受任意
  JSON 文本绕过 parser。
- 新建 Model 写入项目模板中预先声明的专用 writable custom-model source。Endpoint 不因此
  获得任意创建配置文件的能力；现有 Model 继续写回各自 source。

### Task Chain

- `llm.tasks.<profile>` 是命名 Task Chain；`models` 是有序且非空的 Model ID 列表。
- Task Chains 页面是常用核心入口，直接显示顺序、能力要求和主要生成设置。
- Model 顺序支持拖动调整；一次拖动完成后把完整 `models` 数组作为一个 operation 保存。
- 新建 Chain 先创建 profile 和完整 Task 配置。新 Chain 可以暂时处于 `unbound` 状态；
  unbound 只是展示事实，不阻止配置生效。
- Chain 的 retry/switch/cycle/prefer-successful 设置归入 Advanced 折叠区。

### LLM Action Routing

当前 `LLMActionTaskRunner` 固定使用 `TaskProfile.LLM_ACTION`，因此仅在配置文件新增任意
Task profile 并不能改变具体 Action 的模型链。Action 模块需要新增明确路由配置：

```toml
[action.llm_action]
default_task_profile = "llm_action"

[action.llm_action.overrides]
"workspace.analyze" = "workspace_analysis"
```

- `default_task_profile` 适用于没有 override 的所有 `llm_action` backend Action。
- `overrides` 只使用完整稳定 Action ID，不支持通配符、路径模式或隐式优先级。
- 多个 Action 可以分别绑定同一个 Chain。
- Action Routing 页面只允许从当前 Action Catalog 中选择 backend kind 为
  `llm_action` 的 Action，并从现有 Task Chain 中选择目标 profile。
- 推荐交互顺序是先创建 Chain，再创建 Action override 并绑定；路由页同时提供跳转到
  Task Chains 的入口。
- Action 模块拥有路由 Settings、解析、route resolver 和 Action ID/backend kind 校验；
  LLM 模块只接收解析后的 profile 并运行对应 Task，不拥有 Action 路由。
- Generation 装配时必须校验 default/override profile 存在、Action ID 存在且其 backend
  kind 是 `llm_action`。失败时整个候选配置和 Generation 不提交。

### Capabilities

Capabilities 内部继续同时提供能力域的通用配置和具体 Action/服务配置。这与“无独立
持久化和生命周期的外部能力通过 Action 注册自身服务和执行器”语义一致，不迁移其配置
所有权。

Capabilities 页面按能力域组织：

- **Web**：搜索、页面发现和内容提取服务；主要开关、模型/endpoint/credential 为核心
  配置，长度、并发、超时和抓取限制为 Advanced。
- **Resource**：MarkItDown、PyPDF 等转换能力；转换器可用性和格式为核心配置，大小与
  执行限制为 Advanced。
- **Execution**：Shell、Script 和 Supervised Process；能力/adapter 可用性与 executable
  为核心配置，source/args/command/process 限制为 Advanced。

不合成一个跨域的全局 enabled；每个现有 enabled 只表达所属服务或 adapter 的真实开关。

### Embedding

Embedding 继续使用 `[infra.embedding]`，作为 Infra 管理的基础能力接入，不属于
capability-backed Action，也不并入 LLM Provider/Model 注册表。前端在 Infrastructure
页面中提供 Embedding 局部入口；其 endpoint、model、credential、dimensions、batch 和
timeout 仍由 Infra descriptor 和 parser 解释。

## 侧边信息架构

取消当前 `PROJECT` / `CLIENT` 两个粗粒度栏目。侧边栏仍使用当前视觉语义：栏目标题是
不可点击的分组标签，栏目下面是可点击的设置子页面。`MODELS & ROUTING`、
`CAPABILITIES`、`CONTEXT` 和 `RUNTIME` 与当前 `PROJECT` / `CLIENT` 处于同一层级，
Providers、Models 等才是页面入口。

```text
GENERAL
├── Overview
├── Application
└── Credentials

MODELS & ROUTING
├── Providers
├── Models
├── Task Chains
└── Action Routing

CAPABILITIES
├── Web
├── Resource
└── Execution

CONTEXT
├── Home
├── Session
├── Memory
├── Workspace
└── Context Rules

RUNTIME
├── Behavior
├── Maintenance
└── Infrastructure
    └── page-local entry: Embedding
```

约束：

- Data 不再作为独立栏目；Memory 和 Workspace 与 Home、Session、Context Rules 一起
  归入 Context。
- Home 与 Session 是两个独立可点击页面，不合并。
- Application 继续允许在未连接项目时打开；依赖项目配置的其他入口在未连接时禁用。
- Credentials 统一管理 dotenv 中被 Provider、Embedding 和 Capability 声明的凭据，不按
  调用模块拆分多个凭据页面。
- Infrastructure 是可点击页面；Embedding 是其页面内部的局部导航/锚点，不再占据全局
  侧边栏入口。
- 桌面端使用一个带栏目标题的嵌套侧栏，不增加并排双侧栏。
- 移动端先选择栏目，再在第二行显示该栏目的子页面，避免把所有入口压在单行横向滚动中。

## 页面结构

### 通用页面骨架

每个设置子页面使用一致结构：

1. 页面标题、简短用途说明和当前 Runtime activity。
2. 主要对象或核心配置区域。
3. `Advanced` 折叠区，默认关闭并显示字段数量。
4. `Read-only` 折叠区，默认关闭并说明不可写原因与 source。

核心字段直接显示名称和一到两句用途说明。高级字段在展开后仍显示完整说明，不以仅有路径
或 tooltip 的方式隐藏语义。dotted path、source path 和 effective source 属于诊断信息，
放在字段详情或 tooltip 中，不作为主要标签。

当前活动 Turn 期间页面保持全部可读，顶部显示只读原因；控件禁用但不隐藏字段。进程外壳
字段根据 field `writable=false` 进入 Read-only，不与暂时不可写状态混淆。

### 对象型页面

Providers、Models、Task Chains 和 Action Routing 使用对象列表与详情编辑区：

- 桌面端左侧是稳定宽度的对象索引，右侧是选中对象的无嵌套卡片详情区。
- 移动端对象索引和详情使用列表到详情的单列导航。
- 列表项只显示辨认对象所需的名称、状态和少量摘要，不显示反向引用。
- 新建和删除是清晰命令；新增表单使用 modal 或独立详情状态，不在卡片内嵌套卡片。
- 修改一个独立 scalar/toggle 时可以立即 PATCH；新建对象或同时修改互相约束的结构字段时
  使用本地 draft，并以一次 batch PATCH 提交。

### Providers 页面

核心区：

- Provider ID
- enabled
- adapter
- base URL
- credential environment names

Advanced：

- API style
- adapter 相关说明和诊断 source

创建 Provider 时选择 adapter 后生成完整可校验对象；不存在“设为当前 Provider”。删除后若
仍有 Model 引用，后端候选校验失败并直接显示错误。

### Models 页面

核心区：

- Model ID
- Provider
- provider model ID
- context window tokens
- capabilities

Advanced：

- provider options
- provider request overrides 等 adapter-specific 字段
- source/effective 诊断

“New model”先选择一个已有 Model 作为模板，再确认新 ID、Provider 与 provider model ID。
相同 adapter 可以复制兼容 options；不同 adapter 只复制通用字段。前端显示即将保留和清除
的字段，最终提交一个完整 `llm.models.<id>` 对象。

### Task Chains 页面

核心区：

- Profile ID
- 有序 Model 列表
- required capabilities
- answer format
- tool use
- temperature
- max output tokens

Advanced：

- max retries per model
- retry wait
- switch wait
- max cycles
- prefer successful model duration

Model picker 只从当前 Model objects 中选择，列表禁止重复并至少保留一个元素。拖动手柄是
主要排序入口，同时提供上移/下移图标按钮用于键盘和精确操作。创建完成后可以直接前往
Action Routing 绑定；未绑定 Chain 显示中性 `Unbound` 状态。

### Action Routing 页面

页面顶部编辑 default task profile；下面以列表展示显式 overrides：

```text
Action ID | Domain | Task Chain | Backend kind
```

新增 override 先选择可路由 Action，再选择已有 Task Chain。已存在 override 的 Action 不再
出现在新增选择器中。删除 override 后自动回到 default profile，不删除 Chain。

### 非对象型页面

- Overview：连接、activity、Generation、配置 source 和关键能力状态摘要；不复制全部字段。
- Application：visualization 本地连接与显示设置，不要求项目连接。
- Credentials：dotenv credential 名称、是否已配置和 masked value 编辑；不展示系统环境变量
  为可编辑 source。
- Home / Session / Memory / Workspace / Context Rules：分别展示所属模块的核心设置，高级
  budget、limit、schedule 或内部行为折叠。
- Behavior：Action 通用 timeout、User Loop、App 业务行为与输出限制；进程外壳字段只读。
- Maintenance：business timezone、schedule、archive 和 maintenance runtime 设置。
- Infrastructure：以局部入口组织 Embedding，并在底部展示 config source/process shell 等
  只读基础状态。

## 配置描述模型

### 通用类型

在 `tinysoul.infra.config` 中提供轻量、JSON-safe 的 frozen dataclass/StrEnum，只表达通用
配置描述，不包含任何页面组件知识。建议的稳定概念：

- `ConfigSectionDescriptor`：业务 section ID、标题和说明。
- `ConfigCollectionDescriptor`：对象集合 ID、root path、identity 语义、create/delete 能力和
  目标 source policy。
- `ConfigObjectDescriptor`：当前对象 kind、ID、root path、source ID 和直接关系。
- `ConfigFieldDescriptor`：相对字段路径、标题、说明、value kind、默认呈现层级和约束。
- `ConfigFieldImportance`：`primary` 或 `advanced`。
- `ConfigValueKind`：boolean、integer、number、string、enum、string_list、object 等有限类型。
- `ConfigReferenceDescriptor`：provider/model/task/action 等直接引用的 target collection。

通用描述不包含 React component 名、CSS、sidebar group 或前端 route。字段实际
`value/source/writable` 继续由现有 Config status 返回；descriptor 不复制当前值。

### 模块提供者

每个有配置的业务模块在现有 config 边界附近提供 descriptor provider：

- LLM：providers、models、task chains 及 adapter-specific provider options。
- Action：通用 Action settings 和 LLM Action routing。
- Capabilities：web/resource/shell/script/supervised process。
- Infra：embedding 与只读基础设置。
- 其他模块：各自 Settings 字段描述。

Descriptor 与 parser 必须共享 enum、默认值和 domain type，不能复制字符串枚举或重新实现
校验。复杂跨字段约束只由 parser/Settings 校验；descriptor 只提供控件需要的有限提示。

### 当前对象投影

当前 Runtime Generation 从已验证 `AppConfigPlan` 提供对象投影。投影只包含：

- kind、stable ID、root path 和 source ID；
- 正向引用关系；
- 展示所需的有限状态，例如 Provider enabled；
- 不包含反向引用列表；
- 不建立独立可写状态或缓存业务配置值。

对象投影由各模块从自身明确类型构造。App 只拼接投影；Endpoint 序列化。配置字段值仍从
`GET /v1/config` 的 fields/sources 取得，避免对象投影成为第二份配置事实。

## Endpoint 协议

### 保留现有入口

```text
GET   /v1/config
GET   /v1/config/sections/{section_id}
POST  /v1/config/validate
PATCH /v1/config
```

`PATCH /v1/config` 请求格式和同步激活语义保持不变。前端需要新增 batch mutation helper，
但 Backend 已允许一次提交多条 operations。对于对象创建/替换，可以对对象 root path 执行
一次 `set` 并提交完整 JSON object；对象删除对 root path 执行一次 `delete`。Backend 仍用
TOML document、模块 parser 和完整 Generation 构建验证结果。

### 新增配置 schema

```text
GET /v1/config/schema
```

返回所有已装配模块的 section、collection 和 field descriptors。该 Endpoint 不返回当前值，
也不返回前端导航布局。它用于：

- 提供字段说明和输入类型；
- 提供 enum/options、reference collection 和有限约束；
- 标记 primary/advanced；
- 说明对象创建模板与目标 source policy。

协议使用现有 `/v1` 作为 shape 边界，不额外引入配置 schema revision。

### 扩展配置状态

`GET /v1/config` 增加 `objects` 投影：

```json
{
  "objects": [
    {
      "kind": "llm.model",
      "id": "gpt-5.6",
      "root_path": "llm.models.gpt-5.6",
      "source_id": "project:configs/llm/models/openai.toml",
      "references": [
        {"kind": "provider", "target": "openai"}
      ]
    }
  ]
}
```

`objects` 是当前已验证 Generation 的只读语义索引；实际值、来源和 writable 继续以现有
`fields` 和 `sources` 为准。PATCH 成功后的响应或随后 GET 必须返回新 Generation 的对象
投影。

### 新增 Action Catalog 查询

```text
GET /v1/actions/catalog
```

返回当前 Generation 已注册 Action 的有限只读投影：

- stable action ID；
- domain；
- title/description；
- backend kind。

不返回 executor、prompt、完整 schema 或内部 callable。Action Routing 页面仅消费其中
`backend_kind=llm_action` 的条目。Catalog 事实由 Action module 提供，Endpoint 不自行扫描
TOML catalog 文件。

## source 策略

现有 Endpoint 只能修改 source graph 中已声明的文件，这一边界保持不变。

- Provider 新增到既有 `configs/llm/providers.toml`。
- Task Chain 新增到既有 `configs/llm/tasks.toml`。
- Model 新增到 project template 明确包含的 custom-model TOML source；standard 和
  development profile 都必须提供该 source，`tinysoul.toml` 的 include graph 能稳定发现它。
- 现有 Provider/Model/Task 编辑回原 source。
- 不通过 Endpoint 接受任意相对文件名，也不根据用户输入自动扩展 include graph。

custom-model source 的空初始文件是项目模板结构的一部分，不代表新的业务 section；其中
仍使用 `[llm.models.<id>]`，由 LLM parser 统一解释。

## 模块与代码改动

### Backend

`tinysoul/infra/config`

- 增加通用 descriptor/object projection 类型和 JSON 投影。
- 保持 ConfigController 只处理 source、candidate、transaction 和 serializer。
- 验证对象 root path set/delete 与多 operation 原子写入测试覆盖。

`tinysoul/llm`

- 提供 Provider、Model、Task Chain descriptors 和 object projections。
- 复用现有 enum、ModelCapability、ProviderAdapterKind、ProviderApiStyle 和 parser 默认值。
- 提供 adapter-specific provider option descriptor，不在 Endpoint 硬编码供应商字段。

`tinysoul/action`

- 扩展 `ActionSettings`，增加 `llm_action.default_task_profile` 和 overrides。
- 增加明确的 LLM Action profile resolver。
- `LLMActionTaskRunner` 根据完整 Action ID 选择 profile，不再固定
  `TaskProfile.LLM_ACTION`。
- 从当前 Action Catalog 提供只读 action projection。
- 在 Generation 装配边界校验 routes、Task profiles 与 backend kind。

`tinysoul/capabilities` 及其他业务模块

- 各自提供本模块字段 descriptor；不移动 Settings/parser 所有权。
- Capabilities descriptors 按 web/resource/execution 语义组合展示信息，但现有子模块继续
  解析自己的配置。

`tinysoul/app`

- 在现有 `AppConfigPlan`/Generation 装配中轻量聚合模块 descriptor provider 和当前对象
  projection。
- 不添加字段路径判断、页面名称或业务校验副本。
- 构建新 Generation 时完成 Action route 的跨模块引用校验。

`tinysoul/endpoint`

- 增加 config schema DTO/route。
- 在 config status 中加入 active Generation object projection。
- 增加 Action Catalog DTO/route。
- 保持 Endpoint 只适配协议，不拥有 descriptor 或 catalog 状态。

`tinysoul/assets/project/config_profiles`

- standard/development 同步加入预声明 custom-model source。
- action 配置加入默认 LLM Action routing。

### Visualization

`visualization/src/types.ts` 与 API client

- 增加 config schema、object projection 和 action catalog 协议类型。
- 增加 schema/catalog 读取方法和 batch patch helper。

`visualization/src/store/configStore.ts`

- 同时管理 status、schema 和 action catalog 的加载状态。
- PATCH 成功后以返回值/refresh 更新当前 Generation 状态。
- 不缓存第二份可写 config tree；object drafts 只属于当前编辑器。

`visualization/src/features/settings`

- 用明确的 `SettingsSection`/`SettingsPage` 定义替代当前 PROJECT/CLIENT 和
  `settingsPageForPath` 路径分配。
- Settings shell 负责栏目导航、连接要求、activity banner 和页面路由。
- 通用配置组件负责 descriptor-driven field control、说明、Advanced/Read-only 折叠和
  source diagnostics。
- Models & Routing 页面使用专门的 Provider/Model/Task Chain/Action Route 编辑器。
- Capabilities 页面按 Web/Resource/Execution 拆分，并复用通用字段组件。
- Context 与 Runtime 页面按所属模块组合，不自行定义 parser 规则。

前端目录按领域分组，不为每个小字段创建独立文件，也不把所有页面继续堆入一个
`ConfigSettingsPage`。对象列表、详情布局和 descriptor field controls 是可复用 UI；
Provider/Model/Chain/Route 的创建逻辑保持在各自领域组件内。

## 实施步骤

### 一：协议和描述基础

- [ ] 在 Infra 定义有限的 descriptor/object projection 类型与 JSON DTO。
- [ ] 为所有当前配置模块补齐字段名称、说明、value kind、primary/advanced 和约束描述。
- [ ] 让 descriptor 复用 parser enum/default/domain type，并专项检查重复 schema。
- [ ] App 聚合 descriptor 和 active Generation object projection。
- [ ] 增加 `GET /v1/config/schema`，扩展 `GET /v1/config.objects`。
- [ ] 更新 `docs/design/infra.md`、`docs/design/app.md`、`docs/design/endpoint.md` 和
  `docs/endpoint/` 协议文档。

### 二：LLM 对象与创建能力

- [ ] 提供 Provider、Model、Task Chain descriptors/projections。
- [ ] standard/development profiles 加入稳定 custom-model source。
- [ ] 验证 object-root set/delete 和 batch PATCH 能创建、替换、删除业务对象。
- [ ] 实现前端 Providers 对象列表、编辑和创建。
- [ ] 实现前端 Models 对象列表、编辑和基于已有 Model 创建。
- [ ] 实现 Task Chains 列表、模型选择、拖动排序和 Advanced retry 设置。
- [ ] 删除被引用对象、重复 Model、空 Chain、adapter option 不兼容等错误由 Backend parser
  返回并由前端就地显示。

### 三：LLM Action Routing

- [ ] 扩展 ActionSettings 和项目 profile action TOML。
- [ ] 增加 Action-owned profile resolver，替换 runner 的固定 LLM_ACTION profile。
- [ ] 在候选 Generation 构建中校验 default/override references 和 backend kind。
- [ ] 增加 `GET /v1/actions/catalog` 及 Endpoint 文档。
- [ ] 实现 Action Routing default、override 新增/修改/删除和 Chain 入口。
- [ ] 更新 `docs/design/action.md`、`docs/design/llm.md` 和相关测试。

### 四：完整设置页信息架构

- [ ] 重写 Settings navigation 为 GENERAL、MODELS & ROUTING、CAPABILITIES、CONTEXT、
  RUNTIME 栏目和子页面入口。
- [ ] 实现移动端栏目选择与子页面导航。
- [ ] 完成 Overview、Application、Credentials 页面归位。
- [ ] 完成 Web、Resource、Execution 三个 Capability 页面。
- [ ] 完成 Home、Session、Memory、Workspace、Context Rules 页面。
- [ ] 完成 Behavior、Maintenance、Infrastructure 页面及 Embedding 局部入口。
- [ ] 所有页面统一接入 activity read-only、Advanced、Read-only 和 source diagnostics。
- [ ] 删除 `settingsPageForPath` 等前端业务路径推断和已经失去用途的扁平页面逻辑。

### 五：文档、视觉和门禁

- [ ] 更新 `visualization/docs/design/settings.md`，记录栏目、页面、对象编辑与读写状态语义。
- [ ] 在 `visualization/docs/demand` 记录并在 Backend 落地后关闭 schema/object/catalog 协议需求。
- [ ] 更新受影响模块设计文档，确保只描述已落地能力。
- [ ] 增加 Backend descriptor、schema、object projection、routing、batch write 和 activation
  集成测试。
- [ ] 增加前端 navigation、descriptor rendering、object editor、drag reorder、read-only 和
  PATCH success/error 测试。
- [ ] 使用 Playwright 检查桌面和移动端设置页：文字不溢出、导航不重叠、折叠状态清晰、
  对象列表与编辑区可用。
- [ ] 运行 visualization lint/build/tests。
- [ ] 运行 Backend Fast 聚焦测试、`scripts/test.ps1 -Suite Full`、
  `scripts/typecheck.ps1` 和 `git diff --check`。

## 测试重点

### Backend

1. Descriptor 中的 enum/default 与 parser/domain type 一致。
2. Schema 不携带当前值、secret value 或前端组件知识。
3. Object projection 只来自已激活 Generation，并在 PATCH 成功后同步更新。
4. 创建 Provider/Model/Task Chain 可以通过一次 batch PATCH 完成。
5. custom-model source 不能被用户输入替换为任意项目路径。
6. 删除被引用 Provider/Model/Task Chain 时完整候选校验失败，文件和旧 Generation 不变。
7. default route 和 override route 正确选择 Task Chain。
8. unknown action、非 `llm_action` action、unknown profile、重复 override 均阻止激活。
9. active User/Maintenance Turn 期间 schema/status 可读，所有 PATCH 仍返回现有 409。
10. EndpointHost、事件缓冲和连接不因配置对象创建或路由切换而重启。

### Visualization

1. 未连接时 Application 可打开，项目页面禁用。
2. 侧边栏目标题不可点击，子页面入口正确切换；Context 同时包含 Home、Session、Memory、
   Workspace 和 Context Rules。
3. primary 默认可见，advanced/read-only 默认折叠且数量正确。
4. Turn 活跃时所有项目配置控件禁用，但内容、说明和 source 仍可读。
5. Provider/Model 页面不显示反向引用或全局 current provider。
6. Model clone 在 adapter 兼容与不兼容时分别保留或清除正确 options。
7. Task Chain 不允许空列表/重复 Model，拖动与图标排序生成同一完整数组 mutation。
8. 新 Chain 可保持 Unbound；创建 override 后路由关系正确显示。
9. PATCH loading 期间相关控件稳定，不发生布局跳动或重复提交。
10. Backend 校验错误映射到对象/字段，并保留原 draft 供用户修正。

## 完成标准

1. 用户能从业务栏目快速进入 Provider、Model、Task Chain、Action Routing、Capability、
   Context 和 Runtime 配置，不需要理解 TOML 文件路径。
2. 所有显示字段都有模块提供的准确名称和用途说明；前端不存在独立业务 schema。
3. 核心、高级和只读配置层次清楚，Turn 活跃期间仍完整可读。
4. Provider 可以新增；Model 可以基于已有 Model 创建；Task Chain 可以创建和排序；
   `llm_action` 可以通过显式 override 绑定 Chain。
5. Provider -> Model -> Chain -> Action Route 只维护正向关系，不建立反向状态副本。
6. Capabilities 保持模块所有权，并按 Web、Resource、Execution 清晰呈现。
7. Embedding 仍属于 Infra，并在 Infrastructure 页面作为局部入口展示。
8. 每次保存仍是单次持久化加当前 Generation 激活；成功响应表示新配置已经运行。
9. Backend 和 visualization 的设计/Endpoint 文档、测试和实现保持一致。
10. 完整 Backend 门禁、前端 lint/build/tests 和桌面/移动端视觉检查全部通过后，本记录重命名
    为带 `-done-` 标记的文件并把状态更新为 `done`。
