# Endpoint 协议分层、配置外观与 Visualization 对接重构执行计划

- 状态：`done`
- 建立日期：2026-08-16
- 范围：`tinysoul/endpoint`、Visualization Endpoint client、`docs/design/endpoint.md`、`docs/endpoint/`、相关测试

## 1. 背景与真实问题

当前 Endpoint 能力已经覆盖运行状态、输入和控制、Maintenance、Observation replay、配置、Workspace，以及配置页所需的 Action catalog，但实现仍集中在少数大文件中：

- `tinysoul/endpoint/engine.py` 同时持有跨模块 Protocol、RuntimeHandle lease、状态查询、命令提交、配置映射、Workspace 操作、Action catalog 和错误归类；
- `tinysoul/endpoint/server.py` 同时承担 Pydantic 请求模型、认证/CORS/大小限制、异常序列化、所有 HTTP 路由和 WebSocket 循环；
- `events.py`、`journal.py` 与路由生命周期没有形成明确的 Observation 子边界；
- Visualization 的 `TinySoulClient` 仍是一个包含所有 REST 操作的扁平客户端，`events.ts` 只单独抽出了 WebSocket；
- `docs/endpoint/frontend integration.md` 把多个协议域写在一个文件中，难以作为当前前后端接口的功能说明书；
- `GET /v1/config/sections/{section_id}` 没有 Visualization 消费者，且 `ConfigStatus`、`ConfigCatalog` 已提供配置页需要的结构，属于重复外观；`POST /v1/config/validate` 同样没有消费者，而原子化 PATCH 已执行相同候选校验；`PUT /v1/workspace/blob` 保留为完整 Workspace binary write 能力，即使当前 Visualization 尚未使用。
- 当前配置 mutation 的 `op` 与 `value` 没有按操作语义形成判别联合，导致 `delete` 携带值、`set` 缺失值等错误要到业务层才可能发现；
- `/v1/actions/catalog` 的实际消费者是设置页。它读取当前 Runtime Generation 的 `ActionEngine` projection，只服务配置展示和编辑，不是聊天运行时的 Action 读取协议。路径应表达这一语义，避免未来与运行时 Action 观测或调用混淆。

这些问题是 Endpoint 外观组织问题，不是把业务状态搬入 Endpoint 的理由。Endpoint 仍然只是本地客户端协议适配层：解析 HTTP/WS、认证、调用既有 typed engine、映射请求级错误并返回 Observation；业务状态、配置所有权、Runtime Generation 和 Action catalog 仍由原模块持有。

## 2. 已确认的设计语义

### 2.1 公共命名与兼容范围

- 保留 `EndpointEngine` 命名，但将其收敛为 Endpoint 各领域 engine 的聚合对象，不再承担所有领域方法的实现；Endpoint 内部统一使用 `engine` 语义，不建立 `facade` 包。
- 本轮不保留旧内部调用方式或兼容别名。前端、AppBuilder、测试和文档一次性切换到新的清晰结构。
- 保留仍有消费者或属于完整 Workspace 能力的协议语义；删除无消费者且被当前 PATCH 流程覆盖的 section/validate URL。`GET /v1/health` 保留为进程探活协议，不以 Visualization 是否直接调用判断。
- 配置 mutation 使用 `set`/`delete` 判别联合。当前 Infra 以 `value=None` 表示 delete，且 TOML 不支持 null，因此 `set` 必须携带非 null 的 TOML/JSON 值；`delete` 不携带 value。该约束在 HTTP schema/转换处返回 422。

### 2.2 Action catalog 的归属与路径

- Action catalog 的数据所有权属于 `ActionEngine`，由当前 Runtime Generation 的 `user_turn.action_catalog()` 生成；Infra 不复制、不缓存、不解释 Action runtime projection。
- Endpoint 将它组织在 `ConfigurationEngine` 中，因为当前唯一产品消费者是 Settings 配置工作流，且它需要随 Runtime Generation 变化而重新读取。
- 新公共路径为 `GET /v1/config/actions`。
- 删除 `GET /v1/actions/catalog`，不保留重定向或兼容别名。未来若增加聊天运行时 Action 的可见性、调用或事件协议，可在对应的 runtime/action surface 使用不同语义的路径和返回模型。
- Action catalog 仍独立于 `GET /v1/config`：后者是 ConfigController 的源/有效配置状态；Action catalog 是当前业务 Generation 的派生运行时投影，体积和刷新时机也不同。前端可以并行请求两个资源。

### 2.3 Runtime 与错误边界

- Endpoint engines 通过 `RuntimeHandle` 取得稳定的 generation snapshot/read lease；Generation 重建时，EndpointHost、进程外壳、事件缓冲、实例锁和连接信息继续保持稳定。
- 配置 patch 仍使用现有 ConfigController 的持久化并激活语义；成功返回时当前 Generation 已可被后续 `GET /v1/config/actions` 读取。Endpoint 不自行重建 Generation，也不维护第二份配置状态。
- 请求级配置、Workspace、Maintenance 和命令错误在各自 engine 中映射为 `EndpointRequestError`；它们不转换成 Runtime trap。
- EndpointHost/ASGI 生命周期或 Runtime bridge 才使用 Endpoint failure/Runtime 语义。HTTP 最外层只负责稳定 JSON 序列化和未知异常的 500 边界，不在路由中散落宽泛捕获。

## 3. 目标后端结构

重构后保留少量稳定的根对象，并按功能域拆分内部职责：

```text
tinysoul/endpoint/
  __init__.py
  config.py                         # EndpointSettings
  errors.py                         # EndpointError 与请求/服务错误
  failures.py                       # Endpoint 与 Runtime bridge 的稳定 failure
  host.py                           # EndpointHost 与进程外壳生命周期
  engine/
    __init__.py                     # EndpointEngine：typed engine 聚合外观
    contracts.py                    # App、Generation、Config、Maintenance 等 Protocol
    context.py                      # 不拥有业务状态的共享依赖与 RuntimeHandle lease
    runtime.py                      # RuntimeEngine：status、input、control
    maintenance.py                  # MaintenanceEngine：availability 与 request
    events.py                       # EventEngine：replay 与 WebSocket 事件流操作
    configuration.py                # ConfigurationEngine：config/actions/patch
    workspace.py                    # WorkspaceEngine：manifest/resource/blob/trash/restore
  events/
    __init__.py
    models.py                       # EventEnvelope、EventPage 等 DTO
    buffer.py                       # EventBuffer 与 replay/append/wait
    journal.py                      # 可选的本地 journal sink
  http/
    __init__.py
    app.py                          # FastAPI app、middleware、异常 handlers、router 注册
    auth.py                         # HTTP/WS authentication dependency/helper
    errors.py                       # HTTP error response serialization
    server.py                       # EndpointASGIServer 与 uvicorn lifecycle
    schemas/
      runtime.py                    # input/control request models
      maintenance.py
      configuration.py              # mutation discriminated union、patch request
      workspace.py
    routes/
      health.py                     # /v1/health
      runtime.py                    # /v1/status、/v1/input、/v1/control
      maintenance.py                # /v1/maintenance
      events.py                     # /v1/events、/v1/events/ws
      configuration.py              # /v1/config、catalog、actions、PATCH
      workspace.py                  # /v1/workspace/*
```

### 3.1 `EndpointEngine` 聚合外观

`EndpointEngine` 仅负责依赖装配和稳定的 Endpoint 内部入口，提供如下 typed 属性：

```python
engine.runtime
engine.maintenance
engine.events
engine.configuration
engine.workspace
```

每个属性对应一个单一职责 engine。HTTP route 只调用相应 engine，不直接读取 Runtime Generation、ConfigController、WorkspaceEngine 或 EventBuffer。`EndpointEngine` 继续持有 Settings、App gateway、RuntimeHandle 和事件源的装配依赖，但不再包含各域的业务映射细节。

`engine/contracts.py` 保留跨边界 Protocol：App gateway 的 typed command、Generation 的 `user_turn`/`maintenance`/`workspace`、ConfigController 的 status/catalog/patch，以及必要的 Event source contract。已核对 `infra.config.ConfigController.section` 和 `ConfigController.validate` 当前都没有 Endpoint 之外的生产调用者，实施时同步删除这两个死接口及对应旧测试；PATCH 内部继续复用 `_candidate` 与 owner validator，不削弱候选校验。

### 3.2 各 engine 的责任

- `runtime.py`：`RuntimeEngine` 读取 generation/activity/status，向 App gateway 提交 User input 与 control；只映射命令受理和运行状态错误。
- `maintenance.py`：`MaintenanceEngine` 读取当前 availability，通过 App gateway 提交 Maintenance request；维护 active-day lease 的错误映射。
- `events.py`：`EventEngine` 提供 Observation replay 和 WebSocket 所需的 typed page、cursor、mode、wait/subscribe 操作。事件缓冲不被配置或运行 engine 复制。
- `configuration.py`：`ConfigurationEngine`：
  - `status()` 从 ConfigController 读取配置源状态，并附加 Runtime snapshot 与 process shell projection；
  - `catalog()` 读取 Infra catalog；
  - `actions()` 在 RuntimeHandle read lease 内调用当前 Generation 的 `user_turn.action_catalog()`；
  - `patch()` 把 typed `ConfigMutation` 交给 ConfigController，映射 ConfigError 和 Runtime activation error；
  - 不在此处保存配置缓存、Action catalog 副本或自行判断 capability/action 语义。
- `workspace.py`：`WorkspaceEngine` 持有 Workspace lease、active-day lease、读写和 trash/restore 的错误映射，并通过 App gateway 同步 workspace context。

### 3.3 HTTP 层拆分

`http/app.py` 集中创建 FastAPI、CORS、content-length 限制、认证中间件、异常 handlers 和 router 注册。各 route 文件只定义路径、schema 转换和 engine 调用，不放置 Runtime lease、磁盘操作或业务错误判断。`http/server.py` 只负责 `EndpointASGIServer` 的线程和 uvicorn 生命周期。

迁移完成后删除根级 `endpoint/engine.py`、`endpoint/server.py`、`endpoint/events.py` 和 `endpoint/journal.py`；它们分别由 `engine/`、`http/` 和 `events/` 包取代，不留下只转发旧路径的兼容壳。`host.py`、AppBuilder 和测试改为新的内部导入路径。

认证语义保持当前约定：`/v1/health` 可匿名探活，其余 HTTP 请求需要 Bearer token；WebSocket 连接接受后先通过 token frame 完成认证。未知异常仍由统一 HTTP handler 转为稳定的 `endpoint.internal`，不在每个 route 复制 `try/except`。

## 4. 公共 HTTP 协议

### 4.1 路由保留、删除与新增

| 协议域 | 路径 | 处理 |
| --- | --- | --- |
| Health | `GET /v1/health` | 保留，匿名探活 |
| Runtime | `GET /v1/status` | 保留 |
| Runtime | `POST /v1/input` | 保留 |
| Runtime | `POST /v1/control` | 保留 |
| Maintenance | `GET/POST /v1/maintenance` | 保留 |
| Events | `GET /v1/events` | 保留 |
| Events | `WS /v1/events/ws` | 保留 |
| Configuration | `GET /v1/config` | 保留 |
| Configuration | `GET /v1/config/catalog` | 保留 |
| Configuration | `GET /v1/config/actions` | 新的配置语义路径，替代旧 Action catalog 路径 |
| Configuration | `POST /v1/config/validate` | 删除，无消费者且 PATCH 已执行候选校验 |
| Configuration | `PATCH /v1/config` | 保留 |
| Configuration | `GET /v1/config/sections/{section_id}` | 删除，无前端消费者且重复 |
| Workspace | `GET /v1/workspace/blob` | 保留，BinaryPreview 正在使用 |
| Workspace | `PUT /v1/workspace/blob` | 保留，属于完整 Workspace binary write 能力 |
| Workspace | `/v1/workspace/manifest`、`resource`、`trash`、`restore` | 保留 |
| Session | `/v1/session/*` | 不添加，当前没有该 Endpoint 语义 |

OpenAPI、后端测试、前端请求和文档必须同时反映上述表；不能只在路由层保留旧 URL。

### 4.2 配置 mutation 判别联合

HTTP schema 改为显式操作模型，`extra="forbid"`：

Infra 配置层先定义不含 null 的递归 `ConfigValue`，并把 `ConfigMutation.value` 从宽泛 `object` 收窄为 `ConfigValue | None`；其中 `None` 只服务 delete sentinel。`ConfigMutation.__post_init__` 同时拒绝 set 缺值与 delete 携值，使内部调用和 HTTP 联合保持同一不变量。HTTP schema 直接复用该边界类型：

```python
type ConfigValue = (
    str | int | float | bool | list[ConfigValue] | dict[str, ConfigValue]
)

class ConfigSetMutationRequest(BaseModel):
    op: Literal["set"]
    source_id: str
    path: str
    value: ConfigValue

class ConfigDeleteMutationRequest(BaseModel):
    op: Literal["delete"]
    source_id: str
    path: str

ConfigMutationRequest = Annotated[
    ConfigSetMutationRequest | ConfigDeleteMutationRequest,
    Field(discriminator="op"),
]
```

`ConfigPatchRequest.operations` 使用该联合。HTTP 边界完成 JSON value 校验后，route 转换为 Infra 的 `ConfigMutation`；`delete` 不携带内部 value，`set` 的 null 值在边界被拒绝。转换过程中若 Infra 仍发现路径或值类型错误，必须映射为 `EndpointRequestError`，不能让 `ConfigError` 穿透为 500。错误请求由统一 422 handler 返回，不再依赖 ConfigController 才发现缺字段或多余字段。

### 4.3 Action catalog response 语义

`GET /v1/config/actions` 返回当前 Generation 的 Action configuration/runtime projection，包括 domain/action、description/semantic、enabled/available、source binding、runtime policy、schema/backend/hook 等现有字段。Endpoint 不重新定义 Action catalog 字段，也不将其压平为 Config source。配置 PATCH 完成后，前端再次读取该路径得到新 Generation 的 catalog；读取失败时按照现有 request error 语义处理。

## 5. Visualization 对接重构

### 5.1 客户端结构

保留 `TinySoulClient` 作为前端唯一 Endpoint 入口，但把传输和域操作拆开：

```text
visualization/src/api/
  transport.ts              # base URL、Bearer、JSON/body、HTTP error、binary headers
  tinysoul.ts               # TinySoulClient 聚合入口与 EndpointInfo
  runtime.ts                # status/input/control client
  maintenance.ts
  events.ts                 # replay 与 WebSocket 连接
  configuration.ts          # config/status/catalog/actions/patch
  workspace.ts
```

`TinySoulClient` 构造这些 domain client，并以 `client.runtime`、`client.configuration`、`client.workspace` 等属性暴露。旧的扁平方法一次性改掉，不保留别名。Workspace、useBackend、Composer、MaintenanceDialog、configStore、Settings 及测试改用对应 domain client；`writeWorkspaceBlob()` 继续由 Workspace client 暴露。删除未使用的 `health()` client 包装。`GET /v1/health` 本身仍由进程探活和真实 server smoke 使用，不属于前端业务 client。

### 5.2 类型边界

把 Endpoint wire DTO 从混杂 UI 状态的 `visualization/src/types.ts` 中按领域迁入 `types/endpoint/`，拆分 runtime、maintenance、events、configuration、workspace 和 common JSON types；`types/index.ts` 作为稳定 barrel，纯 UI 的 `AppTab`、Top Link 等类型留在 `types/ui.ts` 或对应 feature。API domain client 直接依赖所属 Endpoint types，组件自己的 view model 继续留在 feature/store 附近。配置 mutation 在 TypeScript 中与后端保持同形：

```ts
type ConfigValue =
  | string
  | number
  | boolean
  | ConfigValue[]
  | { [key: string]: ConfigValue };

type ConfigMutation =
  | { op: "set"; source_id: string; path: string; value: ConfigValue }
  | { op: "delete"; source_id: string; path: string };
```

`configStore` 仍并行读取 `configuration.status()`, `configuration.catalog()` 和 `configuration.actions()`；PATCH 成功后刷新 status/actions，不引入第二份 Generation 或 action 状态。`actionCatalog` URL 更新为 `/v1/config/actions`。

### 5.3 WebSocket 与 HTTP 传输共性

REST transport 统一处理认证、查询编码、JSON 解析、HTTP error 和 binary response headers；WebSocket 保留独立连接生命周期和 replay cursor，但复用 EndpointInfo/token/error 类型。事件订阅不能通过 REST client 硬编码业务状态，也不应把 WebSocket 循环塞回 `TinySoulClient` 根文件。

## 6. 文档重组

### 6.1 Endpoint 协议文档

保留 `docs/design/endpoint.md` 作为架构与所有权说明，重写为 `EndpointEngine` 聚合各领域 engine、HTTP adapter、RuntimeHandle lease、错误边界和 App assembly 的当前实现。

将 `docs/endpoint/` 从单一 frontend integration 文档拆为：

```text
docs/endpoint/
  index.md                    # 认证、错误格式、路由总表、版本语义
  runtime.md                  # health/status/input/control
  maintenance.md              # availability 与 maintenance request
  events.md                   # replay、cursor、WebSocket auth/frames
  configuration.md            # config status/catalog/actions、PATCH、mutation union
  workspace.md                # manifest、resource/blob、trash/restore
  frontend-integration.md     # Visualization client/store/workflow 说明
```

删除旧的 `frontend integration.md`，避免同一协议有两个当前说明。文档中明确 `/v1/config/actions` 是配置投影，不描述为聊天 Action API；明确 section/validate URL 已删除。若 `docs/design/app.md`、`docs/design/action.md`、`docs/design/infra.md` 含当前 Endpoint 组装或协议断言，同步更新其当前语义，不重写历史 done 分析记录。

### 6.2 文档内容边界

- `docs/design/` 只描述职责、所有权、数据流和稳定概念，不复制完整路由字段清单；
- `docs/endpoint/` 描述当前 URL、参数、响应、认证和前端调用时序；
- 配置/Action 字段描述仍由 Infra catalog/Action catalog 所属文档维护，Endpoint 文档只描述投影与调用边界，不在每个 route 文件硬编码业务描述。

## 7. 测试与验证计划

### 7.1 后端

Endpoint API 测试保留一个跨域集成 smoke 文件，因为 Runtime、Workspace、Observation 和 Config
共享同一套构造 fixture；在该文件中按功能域组织 route/engine 断言，避免用没有独立语义的薄包装复制
测试。独立的 Journal 测试继续保留。测试重点：

- OpenAPI 包含 `/v1/config/actions`，不包含 `/v1/actions/catalog`、`/v1/config/validate` 和 `/v1/config/sections/{section_id}`，仍包含 `PUT /v1/workspace/blob`，且不产生 `/v1/session/*`；
- 认证、匿名 health、CORS、body size、统一错误响应和 WebSocket token frame 行为不回归；
- `GET /v1/config/actions` 读取 current Runtime Generation，Generation 变化后读取到新 catalog，不建立 Endpoint 缓存；
- `set` 缺少 value、`delete` 携带 value、未知 op、额外字段和 `set(null)` 都返回 422；合法 `set` 才进入 ConfigController；
- Config patch 的持久化、空闲限制、Runtime activation failure 映射保持现有语义；
- 每个 engine 的错误映射、RuntimeHandle read lease、Workspace context sync 和 maintenance availability 分别有 focused coverage；
- AppBuilder 组装新的 EndpointEngine aggregate，EndpointHost 生命周期和 server smoke 仍可工作。

### 7.2 前端

- transport/domain client 的 URL、认证、错误和 binary header 测试；
- configStore 使用 `configuration.actions()`，PATCH 后刷新 status/actions，并覆盖 mutation union；
- useBackend、Composer、Maintenance、Workspace 页面改用 domain client 后的行为测试；
- Visualization lint/typecheck/unit test/build；运行本地真实 Endpoint smoke，确认配置页、Workspace、事件 replay/WS、输入和 Maintenance 流程。

### 7.3 门禁

实现完成后按 AGENT 规约运行：后端 focused tests、`scripts/test.ps1 -Suite Full`、`scripts/typecheck.ps1`，以及 Visualization 的测试、lint、typecheck/build。跨前后端 URL 和 OpenAPI 必须在同一提交中核对；失败时保留测试产物，不以兼容层掩盖结构问题。

## 8. 实施顺序

- [x] 重新组织 `tinysoul.endpoint` engine、events、http 包，保留 `EndpointEngine` 聚合外观。
- [x] 将现有 engine/server 行为迁入各域 engine/routes，统一 HTTP middleware/error/auth。
- [x] 删除 section/validate endpoints、对应 Endpoint Protocol/方法及无生产消费者的 Infra dead methods；保留 binary write endpoint/client method；PATCH 保留完整候选校验并更新测试。
- [x] 将 Action catalog 改为 `GET /v1/config/actions`，由 `ConfigurationEngine` 在 current Generation read lease 中提供；删除旧 URL 的所有代码、测试和文档。
- [x] 将 Config mutation 改为后端 Pydantic 判别联合，补齐 422/null 行为测试。
- [x] 更新 AppBuilder/Host/server assembly 与后端 import/export，清理空壳和重复 helper。
- [x] 拆分 Visualization transport、domain clients、Endpoint wire types，更新所有消费者和测试。
- [x] 重写 `docs/design/endpoint.md`，拆分 `docs/endpoint/` 协议文档并更新当前模块交叉引用。
- [x] 运行完整门禁、真实 Endpoint smoke，逐项核对本计划并将本文件改为 `done` 文件名与状态。

## 9. 完成标准

只有同时满足以下条件才可标记完成：

1. Endpoint 根对象仍为 `EndpointEngine`，但路由和领域逻辑已经按上述 engine/http/events 结构拆分，任何 route 不直接操作业务引擎私有状态。
2. 当前有效 URL 与路由表一致：使用 `/v1/config/actions`，不存在旧 Action catalog 和无消费者的 section/validate URL，binary write URL 保持可用。
3. Action catalog 的所有权、Runtime Generation 读取和配置刷新语义在代码、测试、文档中一致，Infra 没有重复副本。
4. 前后端的配置 mutation union、错误码、认证和空闲激活流程通过类型门禁与测试。
5. Visualization 的所有 Endpoint 消费者均通过分域客户端和明确 wire types 工作，文档和 OpenAPI 与实现一致。
6. `scripts/test.ps1 -Suite Full`、`scripts/typecheck.ps1` 以及 Visualization 验证全部通过。
