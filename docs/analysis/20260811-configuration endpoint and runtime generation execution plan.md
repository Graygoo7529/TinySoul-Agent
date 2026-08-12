# Configuration Endpoint and Runtime Generation Execution Plan

## 目标

为本地前端提供统一的配置读取和修改入口。一次配置修改必须同时完成：

1. 更新项目配置 source（TOML 或 dotenv）。
2. 在当前进程空闲时重新装配业务运行实例。
3. 新 Runtime Generation 成功接管后，修改才算成功。

配置页面始终可读。User Turn 或 Maintenance Turn 活跃期间，配置修改统一不可用；Endpoint 返回明确的当前运行状态和不可修改原因。

本计划只涉及配置、运行时 Generation 和 Endpoint，不涉及 visualization。

## 已确认设计语义

### 运行实例边界

TinySoul 进程拆分为稳定外壳和可替换业务 Generation：

```text
稳定进程外壳
├── ProjectInstanceLease
├── EndpointHost / bearer token / port
├── EndpointEventBuffer / EventJournal
├── Program request queue
├── Config controller
└── ActiveRuntimeHandle
     └── RuntimeGeneration
         ├── AppConfigPlan
         ├── User Turn
         ├── Maintenance Engine
         ├── LLM / Embedding
         ├── Action / Capabilities
         ├── Context / Loop
         └── Home / Memory / Session / Workspace
```

EndpointHost、连接信息、事件缓冲、实例锁和进程外壳不参与 Generation 重建。所有业务配置在 App 空闲时通过重建 Runtime Generation 生效。

Generation 重建不是给旧对象重新赋 Settings，而是根据新的 `AppConfigPlan` 构造一整套新的业务 Engine、服务和 owner 门面，再原子替换当前 Generation。旧 Generation 在切换完成后关闭；业务持久化数据仍由原 owner 管理，不做数据迁移。

### 配置所有权

Infra 只提供配置基础能力：

- 配置 source graph、合并顺序和来源诊断。
- TOML、dotenv 的结构化读取和写入。
- source 文件 revision/fingerprint 的内部一致性检查。
- 原子文件写入和多文件配置事务。
- 候选 `ConfigEnvironment` 的重新加载。

Infra 不解析 `llm`、`memory`、`capabilities` 或其他业务 section。

各业务模块继续拥有自己的 Settings、parser、字段约束和跨字段校验。App 只提供轻量的组合适配：调用各模块 parser 生成 `AppConfigPlan`，再通过 `RuntimeGenerationFactory` 构造新的 Generation。

### Runtime 子包

`runtime` 不只是异常处理模块。它当前还拥有 RunScope、Runtime transfer、Trap、SignalBus 和 Observation 等运行控制语义。因此 Generation 的活跃状态和原子切换属于 Runtime 生命周期。

新增专门子包：

```text
tinysoul/runtime/generation/
├── __init__.py
├── activity.py
├── handle.py
├── lease.py
└── lifecycle.py
```

Runtime 子包只处理泛型对象，不导入 Workspace、LLM、Memory 或其他业务模块：

- `RuntimeHandle[TGeneration]`：当前 Generation 的稳定引用。
- `RuntimeGenerationLease[TGeneration]`：请求或 Turn 使用 Generation 时持有的 lease。
- `RuntimeActivity`：`idle`、`user_turn`、`maintenance_turn`、`config_activation` 等状态。
- `RuntimeActivationState`：配置激活过程的有限状态。
- `RuntimeActivationReceipt`：激活结果的内部类型。

真正的 `RuntimeGeneration` 类型和构造逻辑仍归 App。

### Endpoint 可读和可写语义

Endpoint 返回全部配置字段，包括不可修改字段。字段级只表达静态语义：

```json
{
  "id": "infra.embedding.enabled",
  "value": false,
  "writable": true,
  "source": "project:configs/infra/embedding.toml"
}
```

当前是否允许修改只在顶层返回，不引入字段级 `currently_writable`：

```json
{
  "activity": {
    "state": "user_turn",
    "can_write": false,
    "reason": "turn_active"
  }
}
```

所有业务配置统一在 `idle` 时写入。User Turn、Maintenance Turn 或已有配置激活期间，`PATCH /v1/config` 返回 `409 config.activation_unavailable`，不写入任何文件。

Endpoint 配置、实例锁、端口、token，以及 App 的 interactive、输入命令、输出路由和 retained
outcome 等进程外壳配置可读但 `writable=false`，并返回 `write_reason=process_owned`。

### Revision 语义

当前不向前端暴露 revision，也不要求前端提交 `expected_revision`。Endpoint 是项目配置的主要写入口，后端负责串行化配置操作；PATCH 只接受字段级操作，不接受整棵配置树替换。

Infra 内部仍可使用文件 fingerprint 或事务状态保护单次写入的一致性，但 revision 不是前端协议的一部分。未来如果需要严格协调多个前端或人工编辑器，再增加公开 revision/CAS。

### `.env` 语义

dotenv 的路径由 `[config].env_file` 决定。默认是项目根 `.env`，也可以是 `runtime/.env`；Endpoint 不硬编码路径，而是返回实际解析到的 source：

```json
{
  "source_id": "dotenv",
  "path": "runtime/.env",
  "exists": true,
  "writable": true
}
```

dotenv 支持查询、新增、更新和删除环境变量。写入由 Infra 的 `DotenvDocument` 完成，保留未修改内容并使用原子替换。写入不会修改当前进程的 `os.environ`；新 Runtime Generation 会从新的 dotenv source 重新构建 `runtime_env`。

系统环境变量仍可能覆盖 dotenv。Endpoint 展示 effective value 时必须同时展示实际 winning source，避免把 dotenv 写入误报为当前有效值。

## Endpoint 协议预览

```text
GET   /v1/config
GET   /v1/config/sections/{section_id}
POST  /v1/config/validate
PATCH /v1/config
```

### `GET /v1/config`

返回：

- 当前 Runtime activity。
- 当前有效配置的结构化投影。
- 所有可读 section 和字段。
- source 类型、相对路径和静态 writable 状态。
- 当前 Generation 的配置摘要。
- dotenv source 的实际路径和存在状态。

不暴露任意文件目录，也不提供原始项目文件 API。配置 source 是由 `ProjectConfig` 的主文件和 include graph 产生的明确集合。

### `GET /v1/config/sections/{section_id}`

返回单个业务 owner 的完整配置投影。投影由 owner 的 parser/descriptor 提供，Endpoint 只做 JSON 映射。前端负责显示名称、布局和本地化。

### `POST /v1/config/validate`

使用与 PATCH 相同的操作体，但只构建候选 ConfigEnvironment 和 AppConfigPlan，不写文件、不切换 Generation。返回规范化值、字段错误和跨 section 错误。

### `PATCH /v1/config`

请求采用 source-aware 的字段操作：

```json
{
  "operations": [
    {
      "source_id": "project:configs/infra/embedding.toml",
      "path": "infra.embedding.enabled",
      "op": "set",
      "value": true
    },
    {
      "source_id": "dotenv",
      "path": "GLM_EMBEDDING_API_KEY",
      "op": "set",
      "value": "secret-value"
    }
  ]
}
```

支持 `set` 和 `delete`。路径是 source 内的结构化配置键，不是文件系统路径。

PATCH 执行顺序：

1. Runtime 检查当前是否 `idle`。
2. Infra 在临时文档上应用操作。
3. App 调用各模块 parser 构建 `AppConfigPlan`。
4. App 构建并准备新的 Runtime Generation。
5. 配置事务原子写入 TOML/.env。
6. RuntimeHandle 原子切换到新 Generation。
7. 关闭旧 Generation。
8. 返回成功响应。

只有第 6 步完成后，PATCH 才返回成功。候选构建失败或事务写入失败时，旧 Generation 继续运行，配置不提交。

### 激活观察

稳定 EndpointEventBuffer 发布：

```text
config.activation.started
config.activation.completed
config.activation.failed
```

PATCH 的成功响应是同步权威结果；事件用于前端刷新配置页和其他观察者同步。

## 实施步骤

### 阶段一：Infra 配置文档和事务

- [x] 为 `ConfigSource` 增加类型化 source identity 和相对路径投影。
- [x] 为 `ProjectConfig` 暴露完整 source graph 和重新加载入口。
- [x] 扩展 `ConfigFileToml`，支持结构化 set/delete 和原子保存。
- [x] 增加 `DotenvDocument`，支持键值 set/delete、保留未修改内容和原子保存。
- [x] 增加配置事务，支持多个 TOML/.env source 的候选写入、校验和恢复。
- [x] 保持配置错误包含 key、source、expected 和有限原因。

### 阶段二：Runtime Generation 基础

- [x] 新建 `tinysoul/runtime/generation` 子包。
- [x] 实现泛型 `RuntimeHandle`、Generation lease 和 RuntimeActivity。
- [x] 明确 idle、active turn、maintenance 和 activation 的状态转移。
- [x] 提供 Generation 原子替换和旧 Generation 关闭生命周期。
- [x] 通过 Runtime Observation 发布激活开始、完成和失败。

### 阶段三：App 装配适配

- [x] 从 `TinySoulAppBuilder` 提取 `AppConfigPlan` 编译步骤。
- [x] 提取 App-owned Generation factory，复用现有模块 parser 和 builder。
- [x] 将 User Turn、Maintenance、Workspace、Memory、LLM、Action 和 Capability Engine 放入 Generation。
- [x] 保持 SignalBus、ObservationRouter 等稳定设施的生命周期清晰。
- [x] 让 Program 在 idle 边界访问和切换当前 Generation。
- [x] 为旧 Generation增加显式关闭和资源释放路径。

### 阶段四：Endpoint 配置协议

- [x] EndpointEngine 注入 RuntimeHandle 和配置控制器，不再永久使用旧业务 Engine。
- [x] 增加 `/v1/config` 查询、section 查询、validate 和 PATCH DTO。
- [x] 增加全局 activity/can_write 投影，不增加字段级 currently_writable。
- [x] 活跃 Turn 时将 PATCH 映射为 `409 config.activation_unavailable`。
- [x] 增加 dotenv source 查询和更新。
- [x] PATCH 成功后返回 Generation 切换完成的同步结果。
- [x] 保持 EndpointHost、token、port、事件缓冲和 WebSocket 连接稳定。

### 阶段五：文档和测试

- [x] 更新 `docs/design/infra.md` 的 source、dotenv 和事务语义。
- [x] 更新 `docs/design/runtime.md` 的 Generation 子包和 Handle 语义。
- [x] 更新 `docs/design/app.md` 的 AppConfigPlan 与 Generation 装配边界。
- [x] 更新 `docs/design/endpoint.md` 的配置 API、activity gate 和激活事件。
- [x] 测试 TOML/dotenv 查询、set/delete、原子事务和错误恢复。
- [x] 测试活跃 User/Maintenance Turn 拒绝写入。
- [x] 测试候选 Generation 构建失败时旧 Generation 保持运行。
- [x] 测试成功 PATCH 后文件和当前 Generation 同时更新。
- [x] 测试 EndpointHost、WebSocket 和 EventBuffer 在 Generation 切换后保持可用。

## 完成标准

1. Endpoint 可以读取完整配置投影，包括不可写配置。
2. Endpoint 可以判断当前整体是否允许配置修改。
3. 空闲时一次 PATCH 可以同时更新 TOML/.env 并切换当前业务 Generation。
4. 任意活跃 User/Maintenance Turn 期间不会发生配置写入或 Generation 切换。
5. 配置构建失败不会污染当前运行实例或产生半写入文件。
6. 激活失败时旧 Generation 继续提供业务服务，文件事务可恢复。
7. RuntimeHandle 位于 `runtime/generation`，不携带业务模块依赖。
8. App 只组合各模块配置 parser 和 Generation factory，不建立第二套配置语义。
9. EndpointHost、连接信息、实例锁、EventBuffer 和 WebSocket 不因 Generation 切换而重启。
