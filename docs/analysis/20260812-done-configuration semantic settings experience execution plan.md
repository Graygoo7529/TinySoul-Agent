# Configuration Semantic Settings Experience Execution Plan

状态：done

## 背景

现有配置控制面已经能够读取项目根目录下由 `tinysoul.toml` 声明的 TOML source 和项目
dotenv，并在 Runtime 空闲时通过一次 `PATCH /v1/config` 完成候选配置构造、模块 parser
校验、完整 Runtime Generation 重建、配置文件事务提交和 Generation 原子切换。PATCH 成功即
表示配置已持久化且当前实例已经使用新 Generation，不需要第二个 apply 接口或异步激活状态。

visualization 当前设置页仍按 dotted path 猜测页面、分组和标签，字段控件主要由当前 JSON
值类型决定。该实现可以验证读写链路，但无法表达 Provider、Model、Task Chain、Action
Route、Capability Domain 等对象，也缺少稳定说明、输入提示和主次层级。继续在前端增加路径
判断会形成一套难以维护的隐式配置语义。

本计划在不改变现有持久化与激活模型的前提下，引入 Infra-owned 配置展示目录，扩展 Action
LLM routing，并重构设置页面。所有配置标题、说明和展示元数据集中由 `infra.config` 管理；
业务模块不增加 descriptor provider，也不在各自代码中硬编码设置页说明。

## 目标

1. 设置页按配置语义组织，而不是按 TOML 文件或顶层 key 组织。
2. 所有配置项具有集中维护的名称、用途说明、输入类型提示和 `primary/advanced` 层级。
3. Provider、Model、Task Chain 和 Action Route 使用对象化列表与编辑器。
4. 支持新增 Provider、基于已有 Model 创建新 Model、新增 Task Chain，并把 Chain 绑定到
   具体 `llm_action` Action。
5. Capabilities 保持现有业务配置归属，但在前端按 Web、Resource、Execution 组织。
6. Home、Session、Memory、Workspace 和 Context Rules 归入统一 Context 栏目并保持独立页面。
7. Embedding 继续属于 Infra，在 Infrastructure 页面作为局部入口展示。
8. 所有修改继续通过一次 source-aware batch PATCH 完成持久化和当前实例激活。
9. 模块 parser 仍是配置合法性的唯一权威；展示目录不成为第二套业务 parser。

## 非目标

- 不提供任意项目文件浏览、任意新建 TOML 文件或任意修改 include graph 的 API。
- 不建立通用插件配置平台或允许运行时模块注册前端页面。
- 不引入全局“当前 Provider”；Provider 只是供 Model 引用的轻量连接配置。
- 不展示 Provider、Model、Task Chain 的反向引用列表。
- 不把 Embedding 并入 LLM 或 Capabilities。
- 不重构 LLM Provider、Model、Task 的核心执行结构。
- 不引入配置 revision、字段级即时 writable、独立 apply 接口或激活轮询。
- 不让 Infra 配置目录 import LLM、Action、Memory 等业务模块。
- 不让 Endpoint 或 visualization 重新实现业务 parser 的跨字段约束。

## 已确认设计语义

### 配置事实、业务解释和呈现

配置体系分为三层：

1. **配置事实与展示目录**：Infra 持有 source graph、stored/effective value、source、静态
   writable、候选文档、文件事务，并集中维护所有配置标题、说明、展示层级、输入提示、
   collection root 和受控创建 source。
2. **业务解释**：LLM、Action、Capabilities、Context、Memory、Workspace 等模块继续用自己的
   Settings/parser/domain type 解释配置，并拥有配置失败语义。业务模块不提供设置页 descriptor。
3. **前端呈现**：visualization 使用 Infra catalog 与当前配置事实决定导航、页面布局、对象
   编辑器和折叠交互，不硬编码字段说明或 parser 规则。

Infra catalog 是配置控制面的 package-owned 静态资源。它只表达展示所需的有限元数据，不
参与候选配置解析、Generation 构建或业务默认值计算，不反向 import 业务模块。Catalog 中的
choice 只是输入提示；最终合法性始终由模块 parser 决定。测试可以同时导入 catalog 和业务
enum 检查一致性，但运行时依赖保持 `业务模块 -> infra` 单向关系。

### 写入与激活

- 页面始终可读。
- 顶层 `activity.can_write` 是当前是否允许写入的唯一即时状态。
- User Turn、Maintenance Turn、Daily Transition 或配置激活期间，全部项目配置控件统一只读。
- 进程外壳字段的 `writable=false` 是静态只读语义，与暂时不可写分开显示。
- 一次保存可以提交一个或多个 source-aware operations。
- Backend 在同一次 PATCH 中完成候选校验、完整 Generation 构建、文件事务和句柄切换。
- PATCH 成功响应表示新 Generation 已激活；前端随后刷新权威配置状态。
- 不增加 revision、expected revision、独立 validate-and-apply 或异步轮询。

### 配置对象与事实来源

Provider、Model 和 Task Chain 不是独立状态。`GET /v1/config` 仍返回唯一的 source/effective
配置事实；Infra catalog 用 collection root 和字段模板从同一 source graph 动态投影对象。
不在 `AppRuntimeGeneration` 中保存第二份 config objects，也不让业务模块构造对象投影。

对象只表达配置自身的正向关系：

```text
Provider <- Model.provider
Model    <- TaskChain.models（有序）
TaskChain <- ActionRoute.task_profile
```

删除被引用对象由完整候选 parser/装配校验拒绝，前端不维护反向关系。

### Action LLM Routing

Action 配置整理为：

```toml
[action.llm_action]
timeout_seconds = 600
default_task_profile = "llm_action"
overrides = [
  { action_id = "workspace.analyze", task_profile = "workspace_analysis" },
]
```

- 不保留旧 `action.llm_action_timeout_seconds`。
- `default_task_profile` 作用于所有未显式覆盖的 `llm_action` Action。
- override 按完整稳定 Action ID 选择 Task Chain；同一 Action ID 在所有使用位置保持一致。
- Framework、Home Search、Memory Daily Composition 等普通 LLM Task 不进入 Action routing。
- parser 校验 route 结构和重复项；Action 门面校验 Action ID 和 backend kind；LLM task table
  校验 task profile 是否存在。
- route 可引用 package catalog 中的 `llm_action` Action，即使该 Action 因 capability disabled
  暂未进入当前有效 User Catalog；前端新增选择器只显示当前 Generation 的有效 Action。
- 所有 route 错误在候选配置/Generation 构建前形成归属于 Action 的 `ConfigError`，不得推迟到
  Action 执行期。

## Infra 配置展示目录

### 物理组织

```text
tinysoul/infra/config/
├── catalog.py
└── catalog/
    ├── models.toml
    ├── capabilities.toml
    ├── context.toml
    └── runtime.toml
```

`catalog.py` 提供加载、严格校验、path-pattern 匹配、collection 投影和 JSON-safe 输出；四个
TOML 文件按前端主要语义域组织所有说明。Catalog 是 package resource，不复制到运行项目。

### 稳定概念

- `ConfigSurfaceDescriptor`：稳定语义区域、标题和说明。
- `ConfigCollectionDescriptor`：对象集合 ID、root pattern、identity、create/delete 能力和目标
  source policy。
- `ConfigFieldGroupDescriptor`：同一 surface 内的稳定字段分组、标题和说明。
- `ConfigFieldDescriptor`：path pattern、group、标题、说明、value kind、importance 和有限输入提示。
- `ConfigFieldImportance`：`primary` 或 `advanced`。
- `ConfigValueKind`：boolean、integer、number、string、enum、string_list、reference、
  reference_list、object、object_list 等有限类型。
- `ConfigReferenceDescriptor`：provider/model/task/action 等正向引用的 target collection。
- `ConfigChoiceDescriptor`：静态输入提示选项。
- `credential_reference`：标识值声明 dotenv credential 名称，但不携带 credential value。

这些类型使用 frozen dataclass/StrEnum，并在构造时验证唯一 ID、非空说明、合法 pattern、合法
引用和 collection source policy。Catalog 结构错误属于 Infra package contract/invariant，不伪装
为用户 TOML 字段错误；应用启动装配时完成 catalog 加载，因此问题尽早暴露。

Catalog 不包含 React component、CSS、sidebar group、前端 route、当前值、Runtime activity、
secret value、业务 parser callable 或业务默认值。

### 对象发现

Catalog collection 只声明 root pattern、identity、字段模板、引用和受控创建 source。
visualization 使用 collection descriptor 与现有 `GET /v1/config` 的 `fields/sources` 动态枚举
对象。Backend 不额外返回 `config.objects`，`ConfigController` 不缓存对象，
`AppRuntimeGeneration` 也不保存对象投影，因此配置对象始终只是同一配置事实的前端视图。

## Endpoint 协议

### 保留入口

```text
GET   /v1/config
GET   /v1/config/sections/{section_id}
POST  /v1/config/validate
PATCH /v1/config
```

`PATCH /v1/config` 请求和同步激活语义不变。对象创建或替换对完整 root path 执行一次 `set`；
删除对 root path 执行 `delete`。Task 排序和 Action override 使用 batch mutation 写回完整结构。

### 配置展示目录

```text
GET /v1/config/catalog
```

返回 Infra-owned surfaces、collections 和 fields。它不返回当前值，不规定前端 navigation，不
使用 schema 命名，也不增加 catalog revision。

### Action Catalog

```text
GET /v1/actions/catalog
```

返回当前 Runtime Generation 的有效 User Action 有限投影：stable Action ID、domain、
description、backend kind。Action module 提供投影；Endpoint 通过 RuntimeHandle read lease
读取，不扫描 package TOML，不返回 executor、prompt 或完整 tool schema。

## Source 与标识符策略

- 新 Provider 写入既有 `configs/llm/providers.toml`。
- 新 Task Chain 写入既有 `configs/llm/tasks.toml`。
- standard/development profile 都增加空的 `configs/llm/models/custom.toml`，新 Model 统一写入
  该 source。
- 现有对象编辑回原 source。
- Endpoint 仍只能修改 source graph 中已声明的文件；前端不能提交任意目标文件。
- Provider ID、Model ID 和 Task Profile ID 使用非空、无 `.` 的稳定标识符，以适配当前 dotted
  mutation identity；Action ID 保持带 domain 前缀的完整 ID，但只作为 overrides 数组值。
- `ConfigFileToml` 增加 JSON object/list 中 inline table 的 TOML 序列化支持，使 Action
  overrides 可以由 batch PATCH 正确持久化。

## 设置页信息架构

侧边栏使用栏目标题与可点击子页面：

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

- 桌面端使用一列分组侧栏，不增加双侧栏。
- 移动端先选择栏目，再显示该栏目的子页面。
- Application 在未连接项目时可用；其他依赖项目配置的页面禁用。
- Home 和 Session 保持独立页面；Data 不作为独立栏目。

## 页面与交互

### 通用页面骨架

1. 页面标题、简短用途说明和当前 Runtime activity。
2. 核心配置或主要对象区域。
3. `Advanced` 折叠区，默认关闭并显示字段数。
4. `Read-only` 折叠区，默认关闭并说明不可写原因/source。

字段主要标签和说明全部来自 Infra catalog。dotted path、source path、effective source/value 放入
诊断详情，不作为主要标签。Turn 活跃时字段仍完整可读，控件禁用但不隐藏。

### Providers

- 列表显示 Provider ID、enabled、adapter 和 endpoint 摘要。
- 详情编辑 enabled、adapter、API style、base URL 和 credential env names。
- 支持新建、编辑和删除；不存在全局 current Provider。
- 新建使用 catalog 提供的完整创建模板；最终 parser 校验 adapter/API style 组合。

### Models

- 列表显示 Model ID、Provider、provider model ID 和 capabilities 摘要。
- 新建必须先选择现有 Model 模板。
- 模板中的 provider options 与模型一起复制；切换 Provider 只修改 provider 字段，前端不根据
  Provider adapter 隐式清理 options，最终解释由 LLM parser/adapter 负责。
- provider options 和 request overrides 放入 Advanced。

### Task Chains

- 显示 ordered models、required capabilities、answer format、tool use、temperature 和输出上限。
- retry/switch wait、cycles 和 successful-model preference 放入 Advanced。
- Model picker 只选择当前 Model objects，禁止重复并至少保留一个。
- 拖动手柄作为主要排序入口，同时提供上移/下移图标按钮。
- 支持新增任意合法 profile；未绑定 Chain 显示中性 `Unbound`。

### Action Routing

- 顶部编辑 default task profile。
- override 列表展示 Action ID、Domain、Task Chain 和 backend kind。
- 新建先选择当前有效 `llm_action` Action，再选择现有 Task Chain。
- 删除 override 后自动回到 default，不删除 Chain。

### Capabilities、Context 与 Runtime

- Web、Resource、Execution 按 capability service/action 局部结构展示 primary 和 advanced。
- Home、Session、Memory、Workspace、Context Rules 分页展示各自核心配置。
- Behavior 展示 App、Loop 和 Action 通用行为；进程外壳字段放入 Read-only。
- Maintenance 展示 timezone、schedule、archive 和 turn settings。
- Infrastructure 页面用局部导航组织 Embedding，并展示 config source/process shell 诊断。

### Credentials

Catalog 的 `credential_reference` 字段声明哪些 TOML 值引用 credential 名称。Credentials 页面
合并这些声明与 dotenv 当前键；只显示 dotenv stored value，并支持 masked 编辑、设置和删除。
系统进程环境不枚举、不作为可编辑 source。

## 模块与代码改动

### Backend

`tinysoul/infra/config`

- 增加集中 catalog loader、descriptor 类型、pattern resolver 和 JSON 投影。
- `ConfigController` 新增 `catalog()`，现有 status 继续只返回配置事实。
- `ConfigFileToml` 支持 inline table/list TOML 写回。
- 不 import 任何业务模块，不承担业务 parser 逻辑。

`tinysoul/action`

- 重构 `ActionSettings` 为 `llm_action` 子设置，增加 default profile 和 overrides。
- 增加 Action-owned `LLMActionProfileResolver`。
- `LLMActionTaskRunner` 按完整 Action ID 选择 profile。
- `ActionEngine` 提供有效 Action Catalog 的有限只读投影。
- Action 门面提供 route 对 package catalog backend kind 的校验。

`tinysoul/llm`

- 为 TaskSpecTable 提供稳定 profile 查询门面。
- 配置 parser 明确拒绝含 `.` 的 Provider/Model/Task Profile ID。
- 不增加配置 descriptor 或 UI 说明。

`tinysoul/loop/user`

- UserTurnEntry 通过只读方法暴露已装配 ActionEngine 的 catalog 投影，不泄漏 executor。

`tinysoul/app`

- 保持 AppConfigPlan/Generation 现有职责。
- 在候选编译/Generation 装配前协调 Action route、package Action catalog 和 LLM task profiles 的
  跨模块引用校验。
- App 不聚合配置 descriptor，不保存 config object projection，不判断前端页面。

`tinysoul/endpoint`

- 增加 config catalog route/DTO。
- 增加 Action Catalog route/DTO，并在 RuntimeHandle read lease 下读取当前 Generation。
- 保持 Endpoint 无业务状态、无 descriptor 所有权。

`tinysoul/assets/project/config_profiles`

- standard/development 同步使用新的 `[action.llm_action]`。
- 两个 profile 同步增加 `configs/llm/models/custom.toml`。
- 更新 package-data、initializer 和 wheel 验收。

### Visualization

`visualization/src/types.ts` 与 API client

- 增加 config catalog 和 action catalog 协议类型与读取方法。
- 保持 `ConfigStatus` 为当前配置事实。

`visualization/src/store/configStore.ts`

- 同时加载 status、catalog 和 action catalog。
- 支持 batch patch；成功后刷新 status/action catalog。
- 不缓存第二份可写配置 tree；draft 只属于当前编辑器。

`visualization/src/features/settings`

- 用明确的栏目/页面定义替代 PROJECT/CLIENT 和 `settingsPageForPath`。
- 建立 Settings shell、通用 descriptor field renderer、Advanced/Read-only 折叠和诊断详情。
- 建立 Provider、Model、Task Chain、Action Route 对象编辑器。
- Capabilities、Context、Runtime 页面使用 catalog surface/field pattern，不再猜测标签和说明。
- Credentials 使用 `credential_reference`，不再按字段名后缀寻找声明。

前端允许按领域重组文件，但不为每个字段建立组件，也不把所有页面继续堆进单个
`ConfigSettingsPage`。对象编辑器负责交互，通用 renderer 负责 scalar/list/reference 字段。

## 异常与失败归属

- 项目 TOML/dotenv/mutation/parser 错误继续使用 `ConfigError` 并带 key/source/expected。
- Catalog package 资源格式错误属于 Infra contract/invariant，应用启动时通过 Infra Runtime bridge
  转换为 startup failure；Endpoint 不把内部 catalog bug 返回为可编辑字段错误。
- Action route 结构、未知 Action、非 `llm_action` backend 和未知 Task Profile 都转换为
  `ConfigError(key="action.llm_action...")`，PATCH 返回 `422 config.invalid`。
- Turn 活跃导致不可写继续返回 `409 config.activation_unavailable`。
- 完整 Generation 构建中的非配置模块失败继续返回 `500 config.activation_failed`，旧配置与旧
  Generation 保持有效。
- visualization 保留 Backend error details，并把可定位错误绑定到对应对象/字段；失败不丢失 draft。

## 实施步骤

### 一：执行计划与 Infra catalog

- [x] 重写本执行计划，删除 module descriptor provider、App/config object projection 旧语义。
- [x] 定义 Infra descriptor/catalog contract 和集中 TOML 资源。
- [x] 为当前 standard/development 配置字段补齐标题、说明、kind、importance 和引用提示。
- [x] 实现 catalog 严格加载、pattern 匹配、JSON 输出和 package resource 验收。
- [x] 实现 `ConfigController.catalog()`。
- [x] 增加 `GET /v1/config/catalog`，保持 `GET /v1/config` 配置事实 shape。

### 二：配置对象 source 与 TOML 写回

- [x] standard/development 增加 `models/custom.toml` 并同步 package-data/wheel 测试。
- [x] 增加 Provider/Model/Task Profile stable ID 校验。
- [x] 扩展 TOML serializer 支持 inline table/list。
- [x] 覆盖对象 root set/delete、多 operation 原子写入和引用失败不提交测试。

### 三：Action LLM Routing

- [x] 重构 ActionSettings 和两个 profile action TOML。
- [x] 增加 Action-owned profile resolver，替换固定 `TaskProfile.LLM_ACTION`。
- [x] 增加 TaskSpecTable profile 查询门面。
- [x] 在候选装配边界校验 Action ID、backend kind、default/override task profile。
- [x] ActionEngine/UserTurnEntry 提供有效 Action catalog 投影。
- [x] 增加 `GET /v1/actions/catalog` 和完整 Endpoint 测试。

### 四：Visualization 基础重构

- [x] 增加 catalog/object/action API 类型和 configStore 并发加载、batch patch。
- [x] 重写导航为 GENERAL、MODELS & ROUTING、CAPABILITIES、CONTEXT、RUNTIME。
- [x] 实现移动端栏目与子页面选择。
- [x] 实现 catalog-driven 通用字段控件、说明、Advanced/Read-only 和 source diagnostics。
- [x] 重写 Credentials credential discovery。

### 五：对象页面与完整设置页

- [x] 实现 Providers 创建、编辑、删除。
- [x] 实现 Models 列表、详情和基于模板创建。
- [x] 实现 Task Chains 创建、Model picker、拖动/按钮排序和 retry advanced。
- [x] 实现 Action Routing default、override 新增/修改/删除。
- [x] 实现 Web、Resource、Execution 页面。
- [x] 实现 Home、Session、Memory、Workspace、Context Rules 页面。
- [x] 实现 Behavior、Maintenance、Infrastructure 页面及 Embedding 局部入口。
- [x] 删除旧路径推断、自动标签和扁平 ConfigSettingsPage 逻辑；通用字段页和对象详情页均消费
  Infra catalog 的显式 field group 与 collection identity。

### 六：文档和门禁

- [x] 更新 `docs/design/infra.md`、`docs/design/action.md`、`docs/design/llm.md`、
  `docs/design/app.md` 和 `docs/design/endpoint.md`。
- [x] 更新 `docs/endpoint/frontend integration.md`。
- [x] 重写 `visualization/docs/design/settings.md`，关闭相关 demand。
- [x] 增加 Backend catalog、projection、routing、batch write 和 activation 集成测试。
- [x] 通过前端 model/store 测试覆盖 catalog 驱动字段、read-only/error 保留和 batch patch；通过 Playwright 覆盖 navigation、catalog rendering、对象编辑布局与模型链排序。
- [x] 使用 Playwright 检查桌面/移动端，无文字溢出、导航重叠和布局跳动。
- [x] 运行 visualization test/build。
- [x] 运行 Backend Fast、Full、typecheck 和 `git diff --check`。
- [x] 将本记录重命名为带 `-done-`，状态更新为 `done`。

## 实施结果

- Infra catalog 已集中维护四组 TOML 资源；初始化 standard/development 的现有配置叶子均能唯一匹配 descriptor，未知字段进入 Overview 的 unsupported/read-only 区域。
- Provider、Model、Task Chain、Action Routing 已使用 source-aware 对象编辑器；创建、删除、克隆、模型链排序和 override 绑定均通过单次 batch PATCH 持久化并重建当前 Generation。
- 设置页已使用 General、Models & Routing、Capabilities、Context、Runtime 五组信息架构；移动端采用栏目选择器加子页面横向入口，Embedding 位于 Infrastructure 的局部入口。
- 本轮额外修正移动端对象页的最小列宽和窄屏状态栏溢出；Provider 列表摘要包含 enabled、adapter 和 endpoint。
- 本轮补充跨 project TOML source 的 subtree 删除 batch；collection identity 与 field group 统一由
  Infra catalog 提供，移除 Model Provider 切换时的前端隐式 options 删除。
- 验证结果：Backend Full `913 passed, 2 skipped, 21 deselected`；`ty` typecheck 通过；visualization
  Vitest `15 files / 89 tests passed`；`pnpm build` 通过；Playwright 桌面 `1440x900` 与移动
  `390x844` 均无横向溢出，Providers/Task Chains 页面截图核验通过。

## 测试重点

### Backend

1. Infra catalog 不 import 业务模块，不包含当前值、secret value 或前端组件知识。
2. standard/development 中每个可展示字段都能匹配且只匹配一个 catalog descriptor。
3. collection descriptor 足以由当前 ConfigStatus 动态枚举对象，不存在 Backend objects 缓存。
4. Provider/Model/Task Profile 的 choice/reference 提示与业务 parser 支持集合保持一致。
5. Provider、Model、Task Chain 可以由完整对象 root mutation 创建、替换和删除。
6. custom model 只能写入预声明 source，不能接受任意项目路径。
7. inline table 数组可稳定 round trip，不损坏其它 TOML section。
8. default route 和 override route 正确选择 Task Chain。
9. unknown action、非 `llm_action` action、unknown profile、重复 override 阻止 PATCH。
10. 删除被引用对象时文件和旧 Generation 不变。
11. Action Catalog 只返回当前 Generation 的有效 User Action 有限投影。
12. Turn 活跃时 catalog/status/action catalog 可读，PATCH 返回现有 409。

### Visualization

1. 未连接时 Application 可打开，项目页面禁用。
2. 栏目标题不可点击，子页面正确切换；Context 包含 Home、Session、Memory、Workspace 和
   Context Rules。
3. 所有字段名称和说明来自 Backend catalog；未知字段进入可诊断的 unsupported/read-only 区。
4. primary 默认可见，advanced/read-only 默认折叠且数量正确。
5. Turn 活跃时内容完整可读，所有项目配置控件禁用。
6. Provider/Model 页面不显示反向引用或 current Provider。
7. Model clone 复制模板事实；切换 Provider 不触发前端隐式 options 清理。
8. Task Chain 禁止空/重复 models，拖动与图标排序生成同一完整数组 mutation。
9. 新 Chain 可保持 Unbound；override 建立后关系正确显示。
10. PATCH loading 期间布局稳定，不重复提交；Backend 错误保留 draft 并定位对象/字段。

## 完成标准

1. 用户无需理解 TOML 路径即可进入 Provider、Model、Task Chain、Action Routing、Capability、
   Context 和 Runtime 配置。
2. 所有字段说明集中维护于 Infra catalog，业务模块和前端不存在分散描述副本。
3. 核心、高级和只读层次清楚，Turn 活跃期间仍完整可读。
4. Provider 可新增；Model 可基于已有 Model 创建；Task Chain 可创建和排序；`llm_action` 可
   通过 override 绑定 Chain。
5. Provider -> Model -> Chain -> Action Route 只维护正向关系。
6. ConfigController 仍拥有唯一配置事实；Backend 不保存 config object projection。
7. Embedding 仍属于 Infra 并在 Infrastructure 页面作为局部入口。
8. 每次保存仍是一次持久化加当前 Generation 激活，成功即当前实例生效。
9. Backend、Endpoint、visualization 文档、测试和实现一致。
10. 完整门禁和桌面/移动端视觉检查通过后，本记录标记为 `done`。
