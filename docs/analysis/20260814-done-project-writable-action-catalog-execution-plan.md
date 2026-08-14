# 项目可写 Action Catalog 执行计划

状态：`done`

日期：2026-08-14

## 背景

当前 `tinysoul/action/catalog` 是随 wheel 发布的只读 package resource。它完整定义了 Domain、
模型可见的 Action tool/semantic、框架 runtime 策略和 backend 落点；User Turn 与 Maintenance
Turn 在构建 ActionEngine 时直接加载 package catalog。项目配置只通过
`[action.llm_action]` 管理 LLM-backed Action 的默认 timeout 和 Task Chain 路由。

当前设置页已经能够读取当前有效 User Action 的有限投影，并为 LLM Action 配置 Task Chain；
但不能在项目根目录中查看或修改 Domain description、selection hint、Action description、semantic
或具体 Action timeout。若直接在 package catalog 上写入，会同时破坏项目隔离、wheel/site-packages
只读假设和 Endpoint 只能修改当前项目根目录的边界。若另建稀疏 override，则 package catalog 与
project override 会共同形成同一 Action 定义，用户需要持续理解 base/effective/override 三层关系。

本计划采用项目物化方案：package catalog 只作为 `init/reset` 的初始化模板；初始化后的项目
catalog 是当前项目唯一生效的内置 Action Catalog。配置页面修改项目 catalog 原文件，保存仍统一
经过 `PATCH /v1/config`、候选 Generation 构建、原子文件提交和 Runtime Generation 激活。

## 已确认设计语义

1. `action` 继续拥有 Domain/Action catalog 的类型、解析、校验、继承和运行解释。
2. `infra` 只提供受管 TOML 文档发现、候选编辑、来源投影和多文件事务，不解释 Action 字段。
3. `app` 只协调候选配置与 Generation 装配，不读取或修改 Action catalog 私有字段。
4. `endpoint` 只提供协议映射，不扫描目录、不保存第二份 catalog，也不增加任意文件 API。
5. package `tinysoul/action/catalog` 是初始化模板和 Action 模块测试资源；运行实例只使用项目根目录
   中的物化 catalog，不再叠加 package catalog override。
6. 项目 catalog 是持久项目配置，位于 `configs/`，不放入可清除的 `runtime/` 目录，也不参与每日
   archive。
7. `init/reset` 把当前 package catalog 完整复制到项目根目录；`reset` 继续重建整个项目并只保留
   `.env`，因此会明确恢复当前包版本的默认 Action catalog。
8. 设置页允许修改 Domain/Action 的模型可见语义和 timeout；`parallel_policy`、`trace_mode`、
   tool schema、hooks 与 backend 在设置页只读。
9. Availability 仍由 Capabilities 和 Action registrar 决定；Action Catalog 页面不增加第二套
   `enabled` 开关。
10. 所有 User/Maintenance Turn 共用的内置 Action 使用同一项目 catalog 定义；Maintenance 专属
    `tinysoul/maintenance/catalog` 仍是 Maintenance package resource，不进入本轮可写页面。
11. 任意 User Turn、Maintenance Turn、Daily Transition 或配置激活期间，catalog 完整可读但统一
    不可写；不存在字段级 revision 或独立 apply 操作。
12. 配置页面中的字段标题、说明、分组、importance 和控件提示全部由 Infra catalog 维护；Action
    模块只返回真实 catalog 内容、有效 runtime 投影、availability 与编辑定位信息。

## 目标与非目标

### 目标

- 初始化项目拥有结构清晰、可直接阅读和编辑的完整 Action catalog。
- 配置页面能够按 Domain/Action 浏览并修改 description、semantic 和 timeout。
- 保存成功即持久化到对应 Domain/Action TOML，并在同一请求中激活新的 Runtime Generation。
- catalog 候选错误在写盘前归属到准确 source/path，并保留旧文件与旧 Generation。
- 当前有效 Action、被 capability 暂时裁剪的 Action 都能在设置页读取；后者只显示 unavailable，
  不丢失项目定义。
- 保持当前 Domain runtime、Action runtime、LLM Action default timeout 的继承语义可解释。

### 非目标

- 不提供插件系统、Python executor 动态加载或任意项目代码执行入口。
- 设置页不创建、删除、重命名 Domain/Action，也不修改 Action ID/domain 绑定。
- 设置页不编辑 tool schema、backend、hook、parallel policy 或 trace mode。
- 不把 Capability availability 合并进 catalog 持久事实。
- 不把 Maintenance 专属 Action 暴露为 User Action 配置。
- 不增加 Action 专用写 endpoint；写入仍统一走 `PATCH /v1/config`。
- 不兼容未物化 Action catalog 的旧项目；开发阶段的既有运行根目录通过 `reset` 重新初始化。

## 所有权与事实模型

### Package 模板与项目事实

```text
tinysoul/action/catalog/
    package-owned bootstrap template
                  |
                  | tinysoul init / reset
                  v
<project-root>/configs/action/catalog/
    project-owned active Action Catalog
```

两者不是同时参与运行的配置层：

- package catalog 只定义新项目和 reset 后的初始内容；
- project catalog 是运行实例的唯一内置 Action 定义事实；
- Runtime Generation 持有从 project catalog 解析出的不可变 `ActionCatalog`；
- Endpoint 返回当前 Generation 的只读投影，不另建可写 catalog cache；
- 前端 draft 只属于当前编辑器，成功后重新读取权威投影。

### 项目物理目录

```text
configs/
└── action/
    ├── routing.toml
    └── catalog/
        ├── core/
        │   ├── domain.toml
        │   └── actions/*.toml
        ├── execution/
        │   ├── domain.toml
        │   └── actions/*.toml
        ├── home/
        │   ├── domain.toml
        │   └── actions/*.toml
        ├── web/
        │   ├── domain.toml
        │   └── actions/*.toml
        └── workspace/
            ├── domain.toml
            └── actions/*.toml
```

`routing.toml` 承载当前 `[action.llm_action]`；现有 `configs/action.toml` 直接迁移并删除，不保留
兼容 include。项目 catalog 保持当前 Action-owned 文件格式，不为了进入统一 section tree 而把所有
Action 合并成一个大列表，也不引入 Action ID 转义键或重复的配置对象 ID。

## Infra 受管 TOML 文档集合

### 为什么不能作为普通 include

普通 Project TOML source 会按 dotted key 合并为一个配置树。每个 Action 文件都包含相同的
`name`、`domain`、`tool`、`semantic`、`runtime` 和 `backend` 根字段，若直接加入现有 include，
不同 Action 会互相覆盖或冲突。先写真实文件再尝试构建 Generation 也会破坏当前“候选先验证、
文件后提交”的原子语义。

因此需要一个窄而通用的 Infra 概念：受管 TOML 文档集合。它只解决“多个独立 TOML 作为配置事实，
但不参与 section merge”的真实需求，不提供插件发现、任意文件浏览或模块回调注册平台。

### `tinysoul.toml` 声明

计划在只读进程外壳配置中增加：

```toml
[[config.document_sets]]
id = "action.catalog"
include = [
  "configs/action/catalog/*/domain.toml",
  "configs/action/catalog/*/actions/*.toml",
]
```

`config.document_sets` 与 `config.include` 一样只能在进程启动时确定，配置页面只读。Infra 校验：

- set ID 唯一且非空；
- include 只接受项目内相对 TOML glob；
- 每个 pattern 必须匹配文件；
- 同一文件不能同时属于 merged include 和 document set；
- 同一文件不能属于多个 document set；
- source ID 由 set ID 与项目相对路径稳定生成。

### 类型与门面

在 `tinysoul/infra/config` 增加明确类型：

```text
ConfigDocumentSetSpec
ConfigDocument
ConfigDocumentSet
```

`ConfigDocument` 保存 `set_id/source_id/path/data`；它不是有 precedence 的 `ConfigSource`，不会进入
`effective_values()`、`section_tree()` 或 top-level section validation。`ConfigEnvironment` 增加只读
`document_set(id)` 门面，并在候选环境中携带同一组不可变文档快照。

`ConfigController` 的 source lookup 同时覆盖 merged source、dotenv 和 document source：

- 对普通 project TOML，mutation path 仍是全局 dotted config path；
- 对 document TOML，mutation path 是该文件内部的 dotted path，例如 `tool.description`；
- `ConfigFileToml` 负责候选内存编辑和 TOML 渲染；
- 候选 `ConfigEnvironment` 同时替换修改后的 document snapshot；
- validator/activator 使用候选 snapshot 构建完整 Generation；
- `ConfigFileTransaction` 在验证完成后一次提交普通 TOML、dotenv 和 document TOML；
- 激活失败继续回滚所有文件并保留旧 Generation。

`GET /v1/config` 的 effective `fields` 仍只返回合并配置字段，避免把完整 tool schema 展平成普通
设置项；`sources` 增加 document source 诊断项：

```json
{
  "id": "project-document:action.catalog:configs/action/catalog/workspace/actions/read.toml",
  "kind": "project_document_toml",
  "document_set": "action.catalog",
  "path": "configs/action/catalog/workspace/actions/read.toml",
  "exists": true,
  "writable": true
}
```

document 内容由 owner endpoint 投影，不在 ConfigStatus 中重复完整 values。

## Action Catalog 加载与运行装配

### 加载结果

Action 模块新增 project catalog 加载门面，输入为 `ConfigDocumentSet`，输出为：

```text
LoadedActionCatalog
├── catalog: ActionCatalog
└── documents: ActionCatalogDocumentIndex
```

`ActionCatalogDocumentIndex` 只保存 Domain/Action ID 到 `source_id`、相对路径和本地字段路径的稳定
定位，不承载第二份 description/semantic/runtime 内容。`ActionSpec` 与 `ActionDomainSpec` 仍是唯一
类型化定义事实。

`ActionCatalogLoader.load(path)` 继续服务 package template 验收和底层单元测试；新增显式
`load_documents(document_set, ...)` 解析项目文档。二者复用同一 `ActionTomlParser`，不能分叉两套
字段校验或继承实现。

### AppConfigPlan 与 Builder

`AppConfigPlan` 增加当前候选的 `LoadedActionCatalog`。`TinySoulAppBuilder._compile_config_plan()`：

1. 解析 `[action.llm_action]`；
2. 读取候选 `action.catalog` document set；
3. 由 Action 模块解析完整 project catalog；
4. 使用同一 project catalog 校验 LLM Action routes；
5. 再协调 LLM task profile 引用。

App 不检查 Action TOML 字段，也不读取目录。Action-owned loader 抛出的 `ConfigError` 已携带
document source/path，App 只按既有 `RuntimeActionBridge` 映射启动失败。

`ActionEngineBuilder` 改为接收已经解析的 typed catalog，而不是在 build 内隐式打开 package path。
User Action 直接使用 project catalog；Maintenance Action 将同一 project catalog 与只读 Maintenance
fragment 合并，再通过 `include_actions()` 形成 Home/Memory 精确视图。Capability registrar 仍只注册
executor、动态 schema 边界和 availability 裁剪。

### Timeout 继承

保持并明确当前行为：

```text
Action 显式 runtime.timeout_seconds
    > llm_action backend 的 [action.llm_action].timeout_seconds
    > Domain runtime.timeout_seconds
    > None
```

- Domain 页面可以修改 `domain.toml` 的默认 timeout；
- Action 页面可以写入或删除 Action 文件的专用 timeout；
- 删除专用 timeout 后，LLM Action 回到 LLM Action default，其他 Action 回到 Domain default；
- `ActionCatalogEntry` 返回 effective timeout 及 `action | llm_action | domain | none` 来源；
- `parallel_policy` 继续按 Domain/Action 继承，但页面只读；
- `trace_mode`、hooks 仍按现有 catalog 解析，页面只读。

每个实际 ActionCall 仍从不可变 `ActionSpec.runtime.timeout_seconds` 构造 `ActionFramework`，执行期
不查询配置文件或 Endpoint 状态。

## 可编辑与只读字段

### Domain

可编辑：

- `description`
- `selection_hint`
- `runtime.timeout_seconds`

只读：

- `name`
- effective `parallel_policy`
- normalize/execution hooks
- 该 Domain 当前 availability 与 Action 数量投影

### Action

可编辑：

- `tool.description`
- `semantic.use_when`
- `semantic.avoid_when`
- `semantic.effects`
- `semantic.examples`
- `runtime.timeout_seconds`（可新增、修改、删除以恢复继承）

只读：

- `name`
- `domain`
- `tool.schema`
- `runtime.parallel_policy`
- `runtime.hooks`
- `runtime.result.trace_mode`
- `backend.kind`
- `backend.handler`
- `backend.options`

`semantic.effects` 仍只是模型可见的受限枚举，不参与 runtime 调度，因此允许配置。Availability 不
写回文件，由当前 Generation 的 capability 裁剪结果投影。

设置页的只读仅表示不提供编辑控件或 mutation binding；项目文件仍是可信用户可写资源。直接手工
修改完整 TOML 后，下一次启动必须通过 Action loader、schema、handler、hook 和 Generation 校验。
本轮不在 Endpoint 增加字段级权限系统，也不改变“可信配置者可修改项目 TOML”的现有语义。

## Infra 展示 Catalog

新增 `tinysoul/infra/config/catalog/actions.toml`，声明：

- surface：`action_catalog`；
- groups：Domain Identity、Domain Selection、Action Selection Semantics、Runtime、Read-only
  Contract；
- document field descriptors：按 `document_set + document_kind + local_path` 匹配字段；
- semantic effects 的有限 choices；
- primary/advanced 层级与所有字段说明。

为避免把 document-local path 伪装成 effective config path，Infra 增加独立
`ConfigDocumentFieldDescriptor`：

```text
document_set
document_kind
path
surface
group
title
description
value_kind
importance
choices
```

`document_kind` 只是不透明匹配键，例如 `domain`、`action`；Infra 不 import Action 类型、不解释
timeout 或 semantic。现有 `ConfigFieldDescriptor` 与 collection 行为保持不变。

## Action Endpoint 投影

扩展 `GET /v1/actions/catalog`，由当前 Runtime Generation 的 ActionEngine 返回完整 User catalog
展示投影。Endpoint 不重新加载文件。

建议响应结构：

```json
{
  "domains": [
    {
      "id": "workspace",
      "description": "...",
      "selection_hint": "...",
      "runtime": {
        "timeout_seconds": 30,
        "parallel_policy": "allowed"
      },
      "available": true,
      "source": {
        "source_id": "project-document:action.catalog:configs/action/catalog/workspace/domain.toml",
        "document_kind": "domain",
        "editable_paths": [
          "description",
          "selection_hint",
          "runtime.timeout_seconds"
        ]
      }
    }
  ],
  "actions": [
    {
      "id": "workspace.read",
      "domain": "workspace",
      "tool": {
        "description": "...",
        "schema": {}
      },
      "semantic": {
        "use_when": [],
        "avoid_when": [],
        "effects": ["read_only"],
        "examples": []
      },
      "runtime": {
        "timeout_seconds": 30,
        "timeout_source": "domain",
        "parallel_policy": "serial",
        "hooks": {"normalize": [], "execute": []},
        "trace_mode": "foldable"
      },
      "backend": {
        "kind": "native",
        "handler": "workspace.read",
        "options": {}
      },
      "available": true,
      "source": {
        "source_id": "project-document:action.catalog:configs/action/catalog/workspace/actions/read.toml",
        "document_kind": "action",
        "editable_paths": [
          "tool.description",
          "semantic.use_when",
          "semantic.avoid_when",
          "semantic.effects",
          "semantic.examples",
          "runtime.timeout_seconds"
        ]
      }
    }
  ]
}
```

`editable_paths` 是当前投影到 ConfigMutation 的明确绑定，不是安全权限声明。前端按
`document_kind + local path` 查询 Infra document field descriptor，并以同一 `source_id/path`
提交 mutation。Action Routing picker 改为只选择 `available=true && backend.kind=llm_action` 的项。

PATCH 成功后现有 config store 并发刷新 ConfigStatus 与 Action catalog；响应中的
`generation_id` 继续证明新 Generation 已激活，不增加 catalog revision 或独立 apply endpoint。

## Visualization 信息架构与交互

新增独立侧边栏目：

```text
ACTIONS
└── Catalog
```

Action Routing 仍属于 Task Chains 的局部标签页，因为它表达 Task Chain 与 LLM-backed Action 的
绑定；Catalog 页面表达 Action 自身定义，不放入 Models & Routing 或 Capabilities。

页面结构：

1. 左侧局部 Domain 列表：Domain ID、availability、Action 数量和简短 description。
2. Domain 详情：Description、Selection Hint；Domain timeout 放入 Advanced。
3. 当前 Domain 的 Action 列表：Action ID、backend kind、availability、effective timeout。
4. Action 详情：Tool Description、Use When、Avoid When 为主要设置。
5. Effects、Examples 和专用 Timeout 放入 Advanced；timeout 显示当前 effective value 与继承来源，
   提供“Use inherited timeout”删除专用字段。
6. Schema、parallel policy、hooks、trace mode、backend 放入默认折叠的 Read-only。
7. unavailable Action 保持可读可编辑，并以中性状态说明当前未进入有效 User Action surface；页面
   不提供 enable 命令。
8. Turn 活跃时所有编辑器统一 disabled，结构和只读信息不隐藏。
9. Backend 错误保留当前 draft，并定位到 Domain/Action 与本地字段。

页面复用现有 Settings disclosure、字段组、list editor、JSON read-only viewer 和 source diagnostics，
不把每个 Action 写成单独 React 组件。所有可见字段说明来自 Infra catalog。

## 异常与失败归属

### Infra 配置边界

- document set 声明、glob、项目路径、重复归属和 TOML 解析错误：`ConfigError`，key 归属
  `config.document_sets...` 或具体 document source。
- mutation source/path、文件事务和候选文档构造错误：现有 `ConfigError` / Config transaction
  边界。
- Config document descriptor package 格式错误：`ConfigCatalogError`，属于 Infra package
  contract，在应用启动时失败。

### Action 模块边界

- Domain/Action TOML 动态内容、继承、schema、enum、重复 ID、未知 domain、backend option 错误：
  Action-owned `ConfigError`，携带 document source 与本地 key。
- executor/hook 缺失或 catalog 不变量：现有 Action contract/invariant failure，经
  `RuntimeActionBridge` 转为 startup/config activation failure。
- LLM Action route 引用 project catalog 中不存在或非 `llm_action` 的 Action：
  `ConfigError(key="action.llm_action...")`，写盘前失败。

### Endpoint 与 Runtime

- Runtime 非 idle：`409 config.activation_unavailable`。
- 可定位的候选 catalog 配置错误：`422 config.invalid`。
- 候选 Generation 的模块装配失败：`500 config.activation_failed`，旧文件和旧 Generation 不变。
- Observation 继续只报告 started/completed/failed 摘要，不携带 catalog 正文、schema 或绝对路径。

## 模块与文件改动预览

### `tinysoul/infra/config`

- 新增 document set spec/document/snapshot 类型和项目 glob 加载。
- `ProjectConfig` 解析只读 `config.document_sets`，区分 merged include 与独立 documents。
- `ConfigEnvironment` 携带并读取 document sets，不将其混入 effective section tree。
- `ConfigController` 支持 document source status、candidate mutation、validate、transaction 和
  activation。
- `ConfigCatalog` 增加 document field descriptor，不 import Action。
- 增加 `catalog/actions.toml`。

### `tinysoul/action`

- 增加 project document catalog loader 与 `LoadedActionCatalog`/document index。
- 保留一个 `ActionTomlParser` 和一套继承/validator，不复制 project/package parser。
- `ActionEngineBuilder` 接收 typed catalog；package path 加载移出隐式 build 流程。
- Action catalog projection 扩展 Domain、semantic、runtime、backend、availability 和 source binding。
- LLM Action route 校验改用当前 project catalog。
- `resources.py` 明确 package catalog 是 bootstrap template。

### `tinysoul/app`

- `ProjectInitializer/ProjectResetter` 把 package Action catalog 映射复制到项目
  `configs/action/catalog`。
- `AppConfigPlan` 携带 loaded project Action catalog。
- `_compile_config_plan()` 协调 Action settings、project catalog 和 LLM profile 引用。
- `_build_generation()` 把同一 typed project catalog 注入 User/Maintenance builder。
- App 不解析 Action 字段、不缓存 Endpoint projection。

### `tinysoul/loop/user` 与 `tinysoul/maintenance`

- User builder/build_user_action 接收 project catalog，不再自行读取 package root。
- Maintenance builder 复用 project base catalog，再合并只读 Maintenance fragment。
- capability registrar 与 exact Maintenance view 语义保持不变。

### `tinysoul/endpoint`

- 扩展 `/v1/actions/catalog` DTO；保持 RuntimeHandle read lease。
- Config request schema 不增加 Action 专用 mutation 类型。
- 更新 `docs/endpoint/frontend integration.md` 与 OpenAPI/Endpoint 测试。

### `tinysoul/assets/project` 与 packaging

- `configs/action.toml` 迁移到 `configs/action/routing.toml`。
- `tinysoul.toml` 增加 routing include 与 `action.catalog` document set 声明。
- initializer 从 `tinysoul.action` package resource 复制 catalog，不在 standard/development profile
  重复两份相同文件。
- wheel 继续包含 package catalog，并验证隔离安装后的 `tinysoul init` 生成项目 catalog。

### `visualization`

- 扩展 ActionCatalog API types/store tests。
- Settings navigation 增加 ACTIONS/Catalog。
- 新建 Action catalog 页面和 domain/action editor，消费 Infra document field descriptors。
- Action Routing picker 适配 `available` 与嵌套 backend 投影。
- 增加桌面/移动布局、折叠区、继承 timeout 和活跃 Turn 只读测试。

### 设计文档

- 更新 `docs/design/infra.md`：受管 document sets 与事务语义。
- 更新 `docs/design/action.md`：project-owned runtime catalog、字段可写边界和加载顺序。
- 更新 `docs/design/app.md`：init/reset、AppConfigPlan 和 Generation 装配。
- 更新 `docs/design/endpoint.md` 与 `docs/endpoint/frontend integration.md`。
- 更新 `visualization/docs/design/settings.md`。
- 实施完成后将本记录重命名为 `20260814-done-project-writable-action-catalog-execution-plan.md`
  并记录最终门禁结果。

## 实施步骤

### 一：Infra document set 基础

- [x] 定义 `config.document_sets` TOML contract 和 typed spec。
- [x] 实现项目内 glob 展开、路径边界、重复归属与 document source identity。
- [x] 为 `ConfigEnvironment` 增加不可变 document set snapshot/read 门面。
- [x] 扩展 ConfigController status、candidate、validate、patch 和多文件事务。
- [x] 覆盖普通 TOML + dotenv + document TOML 同批提交及回滚测试。
- [x] 保证 effective fields/section parser 不包含 document-local keys。

### 二：项目 Catalog 物化

- [x] 将 action routing 配置迁移到 `configs/action/routing.toml`。
- [x] 更新 `tinysoul.toml` include/document set 声明。
- [x] 扩展 initializer/resetter，从唯一 package catalog 模板复制完整目录。
- [x] 更新 standard/development 初始化断言、reset 语义与 wheel 隔离验收。
- [x] 明确旧根目录不兼容，无 fallback/package overlay。

### 三：Action project catalog

- [x] 定义 `LoadedActionCatalog` 与 document provenance index。
- [x] 实现 document set loader，并复用现有 Action TOML parser/validator。
- [x] 明确 Domain/Action/LLM timeout 继承与来源投影。
- [x] 重构 ActionEngineBuilder 接收 typed catalog。
- [x] 使用 project catalog 校验 LLM Action routes。
- [x] 为 User/Maintenance 共用、capability-disabled Action 和 Maintenance fragment 增加测试。

### 四：Generation 与 Endpoint

- [x] `AppConfigPlan` 编译 candidate project catalog。
- [x] User/Maintenance Generation 使用同一 project base catalog。
- [x] 扩展 ActionEngine/UserTurnEntry catalog projection。
- [x] 扩展 `/v1/actions/catalog` 协议和 Endpoint 文档。
- [x] 验证 PATCH 成功返回新 generation ID；解析/装配/提交/激活失败保持旧事实。

### 五：Infra 展示语义

- [x] 定义并校验 `ConfigDocumentFieldDescriptor`。
- [x] 新增 `infra/config/catalog/actions.toml`，覆盖全部可编辑和只读字段说明。
- [x] 扩展 `/v1/config/catalog` JSON/types/tests。
- [x] 保证 Infra catalog 不 import Action、不携带当前 Action 值或 parser callable。

### 六：Visualization

- [x] 扩展 API 类型和 config store 刷新行为。
- [x] 增加 ACTIONS/Catalog 导航和响应式页面骨架。
- [x] 实现 Domain 列表/编辑器与 Action 列表/编辑器。
- [x] 实现 semantic list、effects choice、domain/action timeout 和恢复继承操作。
- [x] 实现 availability、timeout source、backend kind 等摘要。
- [x] 实现只读 schema/hooks/parallel/trace/backend 折叠区。
- [x] Action Routing 仅筛选 available LLM Actions。
- [x] 覆盖 Turn 活跃禁用、错误 draft 保留和 PATCH 后权威刷新。

### 七：文档、检查与收口

- [x] 同步 Infra/Action/App/Endpoint/Settings 设计文档。
- [x] 运行 Backend Fast/Full 与 typecheck。
- [x] 运行 visualization test/build。
- [x] 使用 Playwright 检查桌面和移动端 Domain/Action 页面，无横向溢出、标题错位或嵌套卡片。
- [x] 运行 wheel 隔离初始化/启动验收与 `git diff --check`。
- [x] 核对本计划全部条目，将状态标记为 `done` 并记录实施结果。

## 测试重点

### Infra

1. document set 与 merged includes 不相互污染，同一路径不能重复归属。
2. document mutation 使用 source-local path，候选 snapshot 可见而真实文件未提前变化。
3. Action document 与普通 TOML 同批提交时任一失败都会整体回滚。
4. document set 配置属于 process shell，运行时不可修改声明本身。
5. ConfigStatus fields 不包含完整 Action schema，sources 能诊断 document identity。

### Action/App

1. 初始化项目 catalog 与 package template 字节一致。
2. Runtime 不读取 package catalog；缺失 project document set 明确启动失败。
3. Domain description/selection hint 修改进入 Phase1 prompt。
4. Action description/semantic 修改进入 Phase2 ToolSpec。
5. Domain timeout、LLM default 和 Action timeout precedence 正确。
6. parallel policy、trace mode、hooks、schema/backend 继续按项目 catalog 校验和执行。
7. capability-disabled Action 仍出现在配置投影，但不进入 effective ToolScope。
8. User 与 Maintenance 复用的内置 Action 使用同一项目定义。
9. route validation 使用项目 catalog；未知或非 LLM Action 在写盘前失败。
10. invalid catalog PATCH 不改变文件、Generation 或后续 Action scope。

### Endpoint/Visualization

1. Action catalog 返回 Domain、Action、availability、runtime source 和 source binding。
2. 页面所有字段标题/说明来自 Infra document descriptors。
3. semantic 与 timeout mutation 指向正确 Action 文件和本地 path。
4. 删除 Action timeout 后显示正确继承值和来源。
5. unavailable Action 可读可编辑，但 Action Routing picker 不可选。
6. parallel policy、trace mode、schema、hooks、backend 只读展示。
7. Turn 活跃时 GET 正常、全部编辑禁用、PATCH 返回既有 409。
8. PATCH 成功后 ConfigStatus 与 Action catalog 同时刷新到新 Generation。

## 完成标准

1. 新项目与 reset 项目都包含完整 `configs/action/catalog`，且 Runtime 只读取该项目事实。
2. 不存在 package + project override 双层 Action 定义，也不存在 Action 专用第二套写 endpoint。
3. Action 是 catalog 解析与运行语义 owner；Infra 仅拥有 document/transaction/presentation 基础设施。
4. 配置页面能够管理 Domain/Action description、semantic 和 timeout，availability 仍由 Capability
   owner 决定。
5. `parallel_policy`、`trace_mode`、schema、hooks 和 backend 清晰可读但不提供页面写控件。
6. 每次 PATCH 在返回前完成候选校验、文件提交和 Runtime Generation 激活。
7. 配置错误、Action contract failure 与 Runtime activation failure 的归属和 HTTP 映射保持清楚。
8. Backend、Endpoint、项目模板、Visualization、设计文档和执行记录全部一致，并通过完整门禁。

## 实施结果

- Infra 已增加独立受管 TOML document set、source-local mutation、候选快照和统一事务回滚；
  document-local 字段不进入 effective section tree。
- package Action catalog 仅用于 init/reset；项目 `configs/action/catalog` 是运行时唯一内置 catalog
  事实，`AppConfigPlan` 将同一 `LoadedActionCatalog` 注入 User 与 Maintenance Generation。
- `/v1/actions/catalog` 返回 configured Domain/Action、availability、effective runtime、只读 contract
  和 document binding；无效 PATCH 在写盘前返回带 source 的 `422`，旧文件与 Generation 保持不变。
- Settings 已新增 `ACTIONS / Catalog`，支持 Domain/Action 语义与 timeout 编辑、effects choices、
  timeout 恢复继承，以及只读 schema/hooks/parallel/trace/backend；Action Routing 只选择 available
  LLM Actions。
- 门禁结果：Backend 全量测试通过，`ty check` 通过，wheel 隔离构建/init/reset 通过；Visualization
  109 项测试与 production build 通过。Playwright 在 1440x900 与 390x844 真实 Endpoint 数据下通过，
  两个视口的 document/body `scrollWidth` 均等于 viewport width。

## 已确认决策

1. 确认 package catalog 只作为 `init/reset` 模板，运行时不再作为 fallback 或 overlay。
2. 确认项目 catalog 保持当前“一 Domain 一目录、一 Action 一 TOML”结构，并通过 Infra 受管
   document set 接入统一配置事务，而不是改成一个大型合并 TOML。
3. 确认 Domain timeout 允许在页面修改；Action timeout 允许新增/删除以恢复继承；当前
   LLM Action default 的优先级保持不变。
4. 确认设置页不提供 Domain/Action 创建、删除、重命名，也不提供 availability 开关。
5. 确认“只读”是设置页面/编辑绑定语义；项目 catalog 文件仍是可信用户可直接编辑的完整资源。
