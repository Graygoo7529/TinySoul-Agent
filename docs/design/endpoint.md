# Endpoint 设计

## 定位

`gateway/endpoint` 是本地客户端协议适配层，与 Terminal 共用同一个 Agent 和业务 Engine。它负责鉴权、请求 schema、请求映射、Observation replay 和服务生命周期；不拥有 Agent、Turn、Context、Session、Workspace、Action 或配置事实。

Endpoint 的稳定外观是 `EndpointEngine`。它只装配各领域 engine：

```text
endpoint.engine.runtime
endpoint.engine.reflection
endpoint.engine.events
endpoint.engine.configuration
endpoint.engine.workspace
```

各领域 engine 通过 EndpointEngineContext 使用 Agent ingress、ConfigController、受约束服务和 Observation source。Context 不持有 raw generation、完整 owner 或底层 lease 工厂；服务调用自行完成世代/日准入。Generation 重建时，EndpointHost、进程外壳、事件 buffer、实例锁和连接信息保持稳定。

## 目录边界

```text
tinysoul/gateway/endpoint/
  config.py, errors.py, failures.py, host.py
  engine/
    contracts.py, context.py, runtime.py, reflection.py
    events.py, configuration.py, workspace.py
  events/
    models.py, buffer.py, journal.py
  http/
    app.py, auth.py, errors.py, server.py
    schemas/{runtime,reflection,configuration,workspace}.py
    routes/{health,runtime,reflection,events,configuration,workspace}.py
```

HTTP route 只做路径参数/schema 转换和 engine 调用，不直接访问业务私有状态。`http/app.py` 集中注册 middleware、认证、统一错误处理和 routes；`http/server.py` 在 Agent 的事件循环上运行 uvicorn task，异步等待启动与停止，不创建独立服务器线程，也不接管宿主信号处理。

## Observation

`events.buffer` 是 Observation sink，维护有界 sequence replay；`events.journal` 是可选的 best-effort 分段 NDJSON 持久索引。Journal 失败只降级为 memory-only，并由 status 暴露摘要，不改变业务结果。`EndpointEventsEngine` 只提供 `replay`、`wait_after`、`latest_sequence` 和 journal status，事件写入仍属于 ObservationRouter。

WebSocket 在首帧完成 token、cursor 和 mode 认证；断线续传由前端按 cursor 处理。Observation 不参与业务提交和 Runtime 控制流。

## 配置与 Action projection

`EndpointConfigurationEngine` 读取 ConfigController 的 status/catalog，并 await Agent 服务的 action_catalog 投影。Action catalog 的数据所有权仍属于 ActionEngine；Endpoint 不扫描 TOML、不缓存副本。它通过 `GET /v1/config/actions` 暴露给 Settings 配置工作流，不将其定义为聊天运行时 Action API。

`PATCH /v1/config` 把 typed `set`/`delete` mutation 交给 ConfigController。ConfigController 负责候选环境、owner validator、持久化事务和 Runtime activation；Endpoint 不自行重建 Generation。PATCH 只校验并保存候选，返回 saved/pending_reload；POST /v1/config/reload 在 idle 时显式构造并激活新 Generation。活跃或等待 work 不阻止保存候选，但会阻止激活。进程外壳配置保持只读。

配置 reload 全链异步等待候选构造、失败候选关闭与旧资源退休。退休失败返回有限 cleanup diagnostics，响应仍明确表示新世代已经 active；它不进入“原世代仍生效”的激活失败路径。

## Workspace

`EndpointWorkspaceEngine` 通过 WorkspaceService 的 async operation 作用域调用唯一 Workspace owner，统一处理 manifest、text/blob read/write、显式创建/覆盖、有序编辑、目录/标签与 Trash/Restore 和 context sync。Endpoint 不提供任意文件 API；`PUT /v1/workspace/blob` 是完整 Workspace binary write 能力的一部分。

## 失败边界

请求 schema、鉴权、配置冲突和 Workspace 请求冲突映射为稳定的 `EndpointRequestError` HTTP envelope。模块 I/O 错误只在所属 engine 归类；HTTP 最外层将未知异常收敛为 `endpoint.internal`，不暴露 traceback、绝对路径或敏感值。只有 EndpointHost/Runtime bridge 生命周期错误才进入 Runtime failure 语义。
