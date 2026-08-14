# Action Runtime Activation Policy 执行计划

状态：`done`

日期：2026-08-14

## 背景

当前项目 Action Catalog 已经是项目根目录中的可写配置事实。Capability 与业务 owner 在
Runtime Generation 装配时注册 executor；当 Capability、adapter 或具体功能未开启时，registrar
调用 `ActionEngineBuilder.disable_actions()`，Builder 再从 effective catalog 中裁掉对应 Action。
`ActionEngine` 同时保留完整 configured catalog，因此 `/v1/actions/catalog` 可以继续展示这些
Action，并通过 configured/effective catalog 的集合差投影 `available=false`。

这套机制只能表达“当前 Generation 没有提供该 Action”，不能让配置者在执行能力已经存在时主动
决定是否向 Agent 暴露某个 Action。若继续复用 Capability 的 `enabled`，Action 是否暴露、依赖是否
安装、凭据是否存在和服务是否装配会混成同一事实；若把 Action 开关放在单独的普通配置列表中，
又会与项目 Action TOML 形成重复身份和跨 source 配置。

本计划在 Action-owned runtime policy 中增加可继承的 `enabled`。Domain runtime 提供默认值，
Action runtime 可以局部覆盖；Capability/owner support 与 configured activation 分开投影，最终
available 是二者的交集。保存继续使用现有 source-local `PATCH /v1/config`，并在响应前完成候选
校验、文件提交和 Runtime Generation 激活。

本计划更新此前已完成 Action Catalog 计划中“页面不增加第二套 enabled 开关”的决定。新的开关
不是 Capability availability 的副本，而是 Action owner 明确定义的 Agent exposure policy。

## 已确认设计语义

1. Action 开关只决定 Action 是否进入 Agent 的 effective catalog、Phase1 Domain scope 和 Phase2
   ToolScope；它不改变 Tool Schema、semantic、backend 身份或 executor 实现。
2. Capability/owner support 决定当前 Generation 的环境能力是否提供该 Action，包括 capability
   配置、adapter、依赖、凭据、服务和 executor 注册。
3. Action 关闭不替代 Capability 开关，也不跳过 Capability 的依赖、凭据或配置校验。若不希望装配
   某项 Capability，应关闭 Capability 自己的配置。
4. Action runtime activation 与 runtime support 是独立事实：

   ```text
   available = runtime.enabled && supported
   ```

   User ActionEngine 没有额外 include filter；Maintenance ActionEngine 还会与其精确 Turn action view
   求交集，但该临时视图不进入持久配置或 Endpoint availability 协议。
5. `supported` 使用通用命名，不使用 `capability_enabled`。Core、Workspace、Home、Memory、Session
   等 Action 同样由 owner/executor 支持，但不属于 `capabilities` 包。
6. Action activation 属于 Action runtime policy，持久路径为 `[runtime].enabled`；Infra 只维护其
   展示描述，不解释 enabled、supported 或 available。
7. Domain `[runtime].enabled` 是 Action activation 的默认值；默认且项目模板显式配置为 `true`。
   Action 未声明本地值时继承 Domain default，声明后覆盖 Domain default。
8. Domain default 是默认值而不是不可覆盖的总开关：Domain default 为 `false` 时，局部
   `runtime.enabled=true` 的 Action 仍可启用。
9. Action 页面允许删除本地 `runtime.enabled`，恢复 Domain default；页面必须显示 effective value
   和 `action | domain | default` provenance，不能把继承值误报为 Action 文件本地事实。
10. `core.answer` 与其它项目 Action 使用完全相同的 activation 语义，不建立特殊不可关闭规则、
    特殊 editable path 或候选校验。可信配置者关闭它后，User Turn 将缺少正常的正式回答完成动作；
    这是配置结果，不增加 fallback completion 或兼容分支。
11. 所有 User/Maintenance Turn 复用的项目内置 Action 使用同一 activation policy。Maintenance
    package catalog 自有 Action 继续由 package 拥有，不进入项目 Action 设置页。
12. Action Routing 配置继续针对 configured LLM Action 校验。Action 暂时 disabled/unsupported 时，
    已有 Task Chain override 保留但不进入可用 picker；重新 available 后自动恢复使用，不删除路由。
13. 任意 User/Maintenance Turn、Daily Transition 或 config activation 期间保持完整可读、统一不可写；
    不增加独立 apply、revision 或 Action 专用写 Endpoint。

## 目标与非目标

### 目标

- 在每个项目 Action 上提供持久、可继承、可恢复默认值的 Agent exposure 开关。
- 把“配置关闭”和“当前运行环境不支持”作为两个可以独立读取的事实。
- configured catalog 始终完整可读；effective catalog 只包含 enabled 且 supported 的 Action。
- Domain 默认值、Action 覆盖值、Capability support 和最终 availability 在后端、Endpoint、前端与
  文档中使用同一套语义。
- Toggle 保存后在同一次 PATCH 中持久化并重建 Generation；失败保留旧文件和旧 Generation。
- 不让 Capability registrar 读取 Action TOML 或因 Action disabled 而跳过自身依赖和凭据校验。

### 非目标

- 不引入通用 Action dependency graph、bundle、角色权限、运行期临时开关或按 Turn 覆盖。
- 不让 Domain default 变成强制关闭全部子 Action 的总闸门。
- 不通过 Action 开关卸载 Capability service、释放依赖或清除 credential。
- 不新增 Action 专用配置文件、普通 section override、独立 Endpoint 或前端本地 activation 状态。
- 不为 `core.answer`、supervised-process lifecycle 或其它内置 Action 增加保护名单。
- 不修改 Maintenance package Action 的项目配置归属，也不把它们加入 User Action 页面。
- 不建立旧字段 alias 或迁移层；当前项目处于开发期，模板与运行根目录直接使用新格式。

## 现有装配流程

当前 User ActionEngine 的关键流程为：

```text
project Action documents
        |
        v
LoadedActionCatalog / configured catalog
        |
        +--> owner/capability registrars register executors
        +--> registrar disable_actions(unavailable action ids)
        |
        v
ActionEngineBuilder.build()
        |
        +--> effective catalog removes disabled actions
        +--> validate executors for effective actions
        |
        v
ActionEngine
        +--> Phase1/Phase2 use effective catalog
        +--> catalog_json iterates configured catalog
```

具体例子：

- Web registrar 根据 search/discovery/defuddle/trafilatura 设置分别裁剪 Action；
- Script/Shell registrar 根据 capability 和 adapter 设置裁剪 authoring/run Action；
- supervised-process lifecycle 仅在 Script 或 Shell 至少存在一个进程 adapter 时受支持；
- Resource registrar 根据 converter 开关裁剪对应 Workspace conversion Action。

依赖检查由 Capability 在 registrar 装配边界执行。启用 Capability 但缺少依赖或凭据时，候选
Generation 失败，而不是把配置错误降级成一个静默 unavailable Action。

## 配置与继承模型

### Domain default

项目 Domain TOML 使用现有 runtime table：

```toml
[runtime]
enabled = true
timeout_seconds = 60
parallel_policy = "allowed"
```

所有项目 Domain 模板显式写出 `enabled = true`，使默认 exposure policy 可读。Maintenance package
Domain 同样显式使用默认值，但其配置仍不可通过项目 Action 页面修改。

### Action override

Action 未声明 enabled 时继承 Domain：

```toml
[runtime]
timeout_seconds = 600
parallel_policy = "serial"
```

Action 可以局部覆盖：

```toml
[runtime]
enabled = false
timeout_seconds = 600
parallel_policy = "serial"
```

删除 Action-local `runtime.enabled` 恢复继承。与 timeout 类似，Loader 既产生 effective typed value，
也记录 source provenance；不同点是 enabled 没有 LLM Action default 层，其顺序固定为：

```text
Action runtime.enabled -> Domain runtime.enabled -> built-in true
```

### 类型与错误边界

`ActionRuntimeSpec` 增加 `enabled: bool = True`，并在 frozen dataclass 的 `__post_init__` 中校验布尔
类型。TOML parser 在动态入口使用 source-aware `ConfigError` 拒绝字符串、数字和其它非布尔值，
不能让 Python `bool`/`int` 关系或内部 `ActionInvariantError` 泄漏到 Endpoint。

`ActionCatalogDocumentIndex` 增加 Domain 与 Action 的 enabled provenance：Domain 使用
`domain | default`，Action 使用 `action | domain | default`。Domain/Action projection 都返回
effective enabled 和 provenance。该索引只记录配置解释事实，不复制 TOML 内容。

## Runtime Catalog 模型

### 三层事实

Builder 应明确区分：

1. `configured catalog`：项目定义的完整 Action 集合，包含 effective `runtime.enabled`；
2. `supported actions`：当前 Generation 中 owner/Capability 已提供 executor 的 Action 集合；
3. `effective catalog`：当前 Engine view 中同时 enabled、supported 且被 include 的 Action 集合。

Capability registrar 当前调用的 `disable_actions()` 容易与 configured activation 混淆。实施时将其
重命名为表达真实语义的 `mark_actions_unsupported()`，同步修改 registrars、测试和设计文档，不保留
兼容 alias。Builder 内部 `_disabled_actions` 相应改为 `_unsupported_actions`。

### Builder 顺序

`ActionEngineBuilder.build()` 按以下顺序构建：

1. 保存完整 configured catalog；
2. 校验 include action IDs 和 registrar 标记的 unsupported IDs 都属于 configured catalog；
3. 应用 Maintenance 等调用方的 exact include view；
4. 根据 registrar unsupported 集合与 executor registry 形成 supported action 集合；
5. 从当前 view 中删除 `runtime.enabled=false` 或 unsupported 的 Action，得到 effective catalog；
6. 只对 effective catalog 执行 executor 完整性校验；
7. 把 configured catalog、supported identities 和 effective catalog 一并交给不可变 ActionEngine。

Action 配置关闭时，Capability 仍可以完成 service/executor 装配；多余已注册 executor 不构成错误。
若 Capability 明确不支持 Action，registrar 仍必须标记 unsupported，不能仅依赖“恰好没有注册
executor”猜测业务原因。Executor registry presence 可以作为一致性检查，但不能替代 owner 的 support
声明。

### ActionEngine view

`ActionEngine.view()` 必须同时裁剪 configured projection、supported identities 和 effective catalog，
并继续共享 normalizer、runner、renderer 与 registry。Turn-specific view 不改变项目 activation，
也不把 include 状态写回 `/v1/actions/catalog`。

Phase1 Domain scope 从 effective catalog 派生：一个 Domain 没有任何 effective Action 时自然不进入
Domain selection。Agent Home 的 domain/action prompt mount reconciliation 继续使用 effective identities，
因此 disabled/unsupported Action 不挂载局部 skill；重新 available 后随 Generation 恢复。

## Endpoint 投影

`GET /v1/actions/catalog` 继续遍历 configured User catalog。Action runtime 增加：

```json
{
  "runtime": {
    "enabled": false,
    "enabled_source": "action",
    "timeout_seconds": 30,
    "timeout_source": "domain"
  },
  "supported": true,
  "available": false
}
```

字段语义：

- `runtime.enabled`：Domain/default 与 Action override 合并后的有效配置值；
- `runtime.enabled_source`：`action | domain | default`；
- `supported`：当前 Generation 是否提供该 Action 的 runtime owner/executor；
- `available`：当前 User ActionEngine 中是否同时 enabled 且 supported。

Domain runtime 增加 effective `enabled` 与 `enabled_source = domain | default`，其标题必须明确为
Action 默认值；Domain `available` 仍表示至少一个子 Action 最终 available，不把 Domain default
false 误解释为强制关闭状态。前端可从同一响应中的 Actions 计算
enabled/supported/available 数量，不增加重复计数字段。

Action source `editable_paths` 增加 `runtime.enabled`；Domain source 同样增加该路径。所有 Action
一视同仁，包括 `core.answer`。`PATCH /v1/config` 继续使用 Action/Domain document source ID 与本地
path，Endpoint controller 和 ConfigController 不需要新增业务分支。

## 设置页设计

### Domain

Domain Runtime 中增加 `Default Action Enabled` switch：

- 控制 Domain document 的 `runtime.enabled`；
- 标题、说明、value kind 和分组来自 Infra document catalog；
- 删除本地 Domain 值恢复 built-in `true`；
- Domain availability badge 继续显示是否至少有一个 effective Action。

### Action

Action 详情增加主要的 `Availability` 配置组：

- `Action Enabled` switch 读写 Action-local `runtime.enabled`；
- 当当前值来自 Domain/default 时，页面明确显示 provenance；
- 修改 switch 写入明确的 Action-local 布尔值；
- Action-local 值存在时提供 `Use domain default`，删除字段恢复继承；
- switch 在 `supported=false` 时仍可编辑，因为 activation 与 environment support 独立；
- Turn 活跃或 config activation 期间沿用全局只读行为。

Action 列表和详情头部区分：

- enabled + supported：`Available`；
- disabled + supported：`Disabled`；
- enabled + unsupported：`Unsupported`；
- disabled + unsupported：同时表达 `Disabled` 与 `Unsupported`，不让一个状态覆盖另一个事实。

页面不从 Capability 配置反向推导 support，也不按 Action ID 硬编码说明。`runtime.enabled` 的标题与
描述由 Infra catalog 维护；状态值来自 Action endpoint。Action Routing picker 继续只选择
`available=true && backend.kind=llm_action`。

## 模块改动范围

### Action

- `tinysoul/action/core/specs.py`
  - 为 `ActionRuntimeSpec` 增加 enabled 与不变量校验。
- `tinysoul/action/core/loader.py`
  - 解析 bool、复用现有 Domain runtime inheritance、记录 Domain/Action enabled provenance；
  - 扩展 `ActionCatalogDocumentIndex`。
- `tinysoul/action/engine.py`
  - 分离 configured/supported/effective；
  - 将 registrar API 改名为 `mark_actions_unsupported()`；
  - 扩展 view、catalog projection 和 document editable paths。
- `tinysoul/action/catalog/*/domain.toml`
  - 显式配置默认 `enabled = true`。
- `tinysoul/action` registrars/tests/docs
  - 同步新的 support API 与运行语义。

### Capability 与业务 owner

- Web、Resource、Script、Shell、supervised-process registrars 改用
  `mark_actions_unsupported()`；判断逻辑、依赖校验顺序、service 创建和 executor 注册保持原有 owner
  语义。
- Workspace、Home、Memory、Session、Context 和 core registrars 不读取 activation policy；始终按
  当前设计注册 owner executor，由 Builder 统一应用 Action runtime policy。
- supervised-process wait policy 继续从 configured `execution.wait` Action contract 编译；关闭该
  Action 不跳过 manager policy 编译，也不修改 Capability 配置。

### App 与 Maintenance

- `AppConfigPlan` 和 ConfigEnvironment 不增加 activation override；项目 Action document 已是唯一事实。
- User Action 装配只消费 Builder 的新语义，不增加 `core.answer` 特判。
- Maintenance exact include 在 configured catalog 上校验，再与 supported/enabled 求交；复用的项目
  Core Action 遵守项目 activation，Maintenance package Action 保持 package default。
- Runtime Generation、handle、EndpointHost、事件缓冲与配置事务协议无需改变。

### Infra、Endpoint 与 Visualization

- `tinysoul/infra/config/catalog/actions.toml`
  - 增加 Domain default enabled 与 Action enabled 的集中展示描述；
  - 根据页面结构增加或复用 Availability field group。
- Endpoint ASGI 路由和 ConfigController 不新增接口；仅同步 Action catalog JSON 文档和前端类型。
- `visualization/src/types.ts` 扩展 runtime provenance 与 supported。
- `ActionCatalogSettingsPage` 增加 Domain default、Action switch、继承恢复和两维状态展示。
- Action page 测试、Settings 设计、Endpoint frontend integration 同步更新。

## 失败语义

1. TOML 中 enabled 非布尔值是 Action-owned `ConfigError`，附带 document source/local key；Endpoint
   candidate PATCH 返回 `422 config.invalid`，不写文件、不切换 Generation。
2. Capability enabled 但配置、依赖、凭据或 service 无法成立，继续是 Capability/App Generation
   构建失败；Action disabled 不吞掉或降级该错误。
3. Registrar 标记未知 Action、include 未知 Action、effective Action 缺失 executor 属于 Action
   装配契约失败，经既有 RuntimeActionBridge 映射；不作为模型可反馈局部结果。
4. Action disabled/unsupported 本身不是失败，不产生 RuntimeException 或 ActionResult；它只是不进入
   ToolScope。
5. 关闭 `core.answer` 后没有正常 User completion 是可信配置结果，不在配置边界伪造错误，也不建立
   第二条回答路径。

## 实施步骤

### 一：Action runtime 类型与继承

- [x] 为 `ActionRuntimeSpec` 增加 `enabled: bool = True` 和不变量校验。
- [x] 在 Action TOML parser 增加 source-aware boolean parsing。
- [x] 让 Domain runtime enabled 参与现有 base inheritance，Action local 值覆盖。
- [x] 扩展 `ActionCatalogDocumentIndex`，记录 Domain/Action enabled provenance。
- [x] 在项目与 Maintenance package Domain 模板显式写入 `enabled = true`。
- [x] 增加 loader、非法类型、Domain default、Action override 和删除恢复继承测试。

### 二：Support 与 effective catalog

- [x] 将 `disable_actions()` 重命名为 `mark_actions_unsupported()`，不保留 alias。
- [x] 同步所有 Capability/owner registrar 与测试调用。
- [x] 在 Builder 中明确 configured、included、supported、enabled 和 effective 构建顺序。
- [x] ActionEngine 保存不可变 supported identities，并在 view 中正确裁剪。
- [x] Phase1/Phase2、domain/action identities 和 executor validation 继续只消费 effective catalog。
- [x] 增加 enabled/supported 四种组合、空 Domain、include view、executor 完整性测试。

### 三：Action catalog Endpoint 投影

- [x] 为 Domain runtime 投影 effective enabled default 与 enabled_source。
- [x] 为 Action runtime 投影 enabled 与 enabled_source。
- [x] 为 Action 投影独立 supported，并保持 available 为最终交集。
- [x] Domain/Action editable paths 增加 `runtime.enabled`，不特判 `core.answer`。
- [x] 更新 Endpoint 与 frontend integration 协议文档。
- [x] 增加 disabled、unsupported、双重关闭和 project source binding 测试。

### 四：统一配置事务与 Generation

- [x] 增加 Domain default enabled PATCH 的持久化和 Generation 重建测试。
- [x] 增加 Action local enabled set/delete、provenance 变化和 Generation 重建测试。
- [x] 验证 Turn 活跃时保持可读、PATCH 返回既有 409。
- [x] 验证非法 enabled 候选返回 422，文件、Generation 和 effective ToolScope 保持原样。
- [x] 验证 Action disabled 不跳过已启用 Capability 的依赖/凭据校验。
- [x] 验证 LLM Action routing override 在 Action disabled 时保留，重新 enabled 后恢复可选。

### 五：Maintenance 与共享语义

- [x] 验证复用的项目 Action disabled 后不进入对应 Maintenance exact view。
- [x] 验证 Maintenance package Actions 继续按 package Domain default enabled。
- [x] 验证关闭 `core.answer` 的候选 Generation 可以成功构建且没有特殊 fallback/protection。
- [x] 验证 disabled/unsupported identities 不参与 Agent Home prompt mount reconciliation。

### 六：Infra catalog 与设置页

- [x] 在 Infra catalog 增加 Domain Default Action Enabled 与 Action Enabled descriptor。
- [x] 增加或调整 Action Availability field group，说明全部由 Infra 维护。
- [x] 扩展前端 Action catalog types 和 fixtures。
- [x] Domain Runtime 增加默认 enabled switch 与恢复默认操作。
- [x] Action 详情增加 enabled switch、enabled provenance 和 Use domain default。
- [x] 列表与详情分别表达 Disabled、Unsupported 和 Available，不混淆 support 与 activation。
- [x] 保持 unsupported Action 的开关可编辑，并继续遵守全局 activity write lock。
- [x] Action Routing picker 继续只消费最终 available LLM Actions。

### 七：文档与完整验证

- [x] 同步 `docs/design/action.md` 的 runtime inheritance、catalog 三层事实和 Builder 语义。
- [x] 同步 `docs/design/capabilities.md`，明确 Capability support 不读取 Action activation。
- [x] 同步 `docs/design/app.md`、`docs/design/endpoint.md`、frontend integration 和 Settings 设计。
- [x] 运行 Action/Capability/App/Endpoint/Visualization 聚焦测试。
- [x] 运行 Backend Fast，再运行 Full 与 typecheck。
- [x] 运行 Visualization test 与 production build。
- [x] 使用真实 Endpoint 数据进行桌面和移动端设置页检查，确认状态、switch、继承操作和布局无溢出。
- [x] 运行 wheel 隔离 init/reset 验收与 `git diff --check`。
- [x] 核对全部计划条目，将文件状态和文件名更新为 `done`，记录最终实施结果。

## 实施结果

1. Action runtime activation 已在 `ActionRuntimeSpec`、TOML loader、project document provenance、
   Builder 和 `ActionEngine` 投影中贯通。Domain 默认、Action override、删除恢复继承以及
   `configured -> supported -> effective` 三层事实使用同一套语义。
2. Capability/owner registrars 已统一使用 `mark_actions_unsupported()`；Action disabled 不参与
   Agent scope，但不跳过 Capability 依赖、凭据、service 或 executor 装配。
3. `GET /v1/actions/catalog` 已返回 enabled provenance、supported、available 与 source-local
   editable path；`PATCH /v1/config` 已覆盖 Domain/Action set/delete、候选失败回滚和 Generation
   原子激活。LLM Action routing override 在不可用期间保持持久配置。
4. Action Catalog 设置页已增加 Domain 默认开关、Action 局部开关、继承恢复和双维状态显示；字段
   标题与说明继续由 Infra catalog 集中维护。桌面与 390px 移动端使用真实 Endpoint 数据检查，
   `body.scrollWidth == body.clientWidth`，两个开关均渲染且无状态遮挡。
5. Maintenance exact view、`core.answer` 普通关闭语义、Home effective identity 和 package 默认值均
   已按统一 policy 验证；设计文档、Endpoint 协议与 Visualization 文档已同步。
6. 最终门禁：Backend Fast `946 passed, 2 skipped`；Full（含 wheel 隔离 init/reset）
   `947 passed, 2 skipped`；`ty` typecheck 通过；Visualization `111 passed`，production build 通过；
   `git diff --check` 通过。

## 测试矩阵

### Loader

1. Domain 未显式 enabled 时 built-in default 为 true。
2. Domain false 被无本地值的 Actions 继承。
3. Action true/false 分别覆盖 Domain default。
4. 删除 Action local enabled 后 provenance 和 effective value恢复 Domain。
5. bool 以外的 TOML 值产生带 source/key 的 ConfigError。

### Builder 与 Capability

1. enabled=true、supported=true：available 且进入 ToolScope。
2. enabled=false、supported=true：disabled，不进入 ToolScope，executor 可保持注册。
3. enabled=true、supported=false：unsupported，不进入 ToolScope。
4. enabled=false、supported=false：两个事实均保留，available=false。
5. 一个 Domain 全部 effective false 时不进入 Phase1；局部 true override 可以恢复 Domain。
6. Capability dependency/credential failure 不因 Action disabled 而跳过。
7. unknown unsupported ID 和 effective missing executor 继续明确失败。

### Endpoint 与配置事务

1. GET 同时返回 effective enabled、provenance、supported、available 和 editable path。
2. Domain/Action toggle 写入正确 document local path，并在响应前激活新 Generation。
3. 删除 Action override 后恢复 Domain default。
4. invalid candidate 不修改文件、Generation、Action catalog 或后续 ToolScope。
5. 活跃 Turn 中 GET 可读、控件禁用、PATCH 返回 409。
6. disabled LLM Action 的 routing override 保留但 picker 不再提供；重新开启后恢复。

### Visualization

1. Availability、字段标题和说明来自 Infra catalog。
2. inherited、local override、unsupported 和 available 状态显示正确。
3. unsupported 不禁用 Action Enabled switch；activity lock 才禁用写操作。
4. Use domain default 提交 delete mutation，不写前端猜测的 Domain 值。
5. Domain default 与 Action local toggle 后以权威刷新结果替换 draft。
6. 桌面和移动端无嵌套卡片、横向溢出、状态遮挡或 switch 偏移。

## 完成标准

1. 项目 Action Catalog 中 activation 是 Action-owned runtime policy，不存在第二份普通 section 开关。
2. Domain default、Action override 与 provenance 可以从 TOML、typed catalog、Endpoint 和设置页互相解释。
3. Capability/owner support 与 Action configured activation 独立，available 是二者明确交集。
4. Action disabled 不参与 Phase1/Phase2、execution 或 prompt mount，但保持 configured 定义和路由配置。
5. Capability registrar 不读取 Action activation，Action disabled 不跳过依赖、凭据或 service 校验。
6. `core.answer` 不存在特殊保护或 fallback；Maintenance shared/package Action 边界保持清楚。
7. 所有修改继续走统一 PATCH、候选验证、事务提交和 Runtime Generation 激活。
8. Backend、Endpoint、项目模板、Visualization、设计文档和执行记录一致并通过完整门禁。

## 已确认决策

1. 确认 Domain runtime 可以作为 Action enabled 默认值，默认开启；Action 可以局部覆盖。
2. 确认 `core.answer` 不做特殊处理，配置者可以使用统一 Action 开关关闭它。
3. 确认 Action 关闭只影响 Agent exposure，不替代 Capability 开关，也不跳过 Capability 依赖和凭据
   校验。
4. 确认 support 使用独立运行事实表达，不写回 Action TOML。
