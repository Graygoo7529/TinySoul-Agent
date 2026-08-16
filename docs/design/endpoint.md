# Endpoint 设计

## 定位

`endpoint` 是本地客户端协议适配层，与 Terminal 共用同一个 App 和业务 Engine。它负责鉴权、请求 schema、请求映射、Observation replay 和服务生命周期；不拥有 Program、Turn、Context、Session、Workspace、Action 或配置事实。

Endpoint 的稳定外观是 `EndpointEngine`。它只装配各领域 engine：

```text
endpoint.engine.runtime
endpoint.engine.maintenance
endpoint.engine.events
endpoint.engine.configuration
endpoint.engine.workspace
```

各领域 engine 通过 `EndpointEngineContext` 使用 RuntimeHandle、App gateway、ConfigController、Workspace lease 和 Observation source。Context 只保存依赖与 lease 工厂，不复制业务状态；Generation 重建时，EndpointHost、进程外壳、事件 buffer、实例锁和连接信息保持稳定。

## 目录边界

```text
tinysoul/endpoint/
  config.py, errors.py, failures.py, host.py
  engine/
    contracts.py, context.py, runtime.py, maintenance.py
    events.py, configuration.py, workspace.py
  events/
    models.py, buffer.py, journal.py
  http/
    app.py, auth.py, errors.py, server.py
    schemas/{runtime,maintenance,configuration,workspace}.py
    routes/{health,runtime,maintenance,events,configuration,workspace}.py
```

HTTP route 只做路径参数/schema 转换和 engine 调用，不直接访问业务私有状态。`http/app.py` 集中注册 middleware、认证、统一错误处理和 routes；`http/server.py` 只管理 ASGI 线程与 uvicorn 生命周期。

## Observation

`events.buffer` 是 Observation sink，维护有界 sequence replay；`events.journal` 是可选的 best-effort 分段 NDJSON 持久索引。Journal 失败只降级为 memory-only，并由 status 暴露摘要，不改变业务结果。`EndpointEventsEngine` 只提供 `replay`、`wait_after`、`latest_sequence` 和 journal status，事件写入仍属于 ObservationRouter。

WebSocket 在首帧完成 token、cursor 和 mode 认证；断线续传由前端按 cursor 处理。Observation 不参与业务提交和 Runtime 控制流。

## 配置与 Action projection

`EndpointConfigurationEngine` 读取 ConfigController 的 status/catalog，并在 RuntimeHandle read lease 中读取当前 Generation 的 `user_turn.action_catalog()`。Action catalog 的数据所有权仍属于 ActionEngine；Endpoint 不扫描 TOML、不缓存副本。它通过 `GET /v1/config/actions` 暴露给 Settings 配置工作流，不将其定义为聊天运行时 Action API。

`PATCH /v1/config` 把 typed `set`/`delete` mutation 交给 ConfigController。ConfigController 负责候选环境、owner validator、持久化事务和 Runtime activation；Endpoint 不自行重建 Generation。所有业务配置在 idle 时统一持久化并激活，成功响应表示新 Generation 已可由后续读取观察到。进程外壳配置保持只读。

## Workspace

`EndpointWorkspaceEngine` 在 active-day lease 内调用唯一 Workspace owner，统一处理 manifest、text/blob read/write、revision/digest CAS、Trash/Restore 和 context sync。Endpoint 不提供任意文件 API；`PUT /v1/workspace/blob` 是完整 Workspace binary write 能力的一部分。

## 失败边界

请求 schema、鉴权、配置冲突和 Workspace CAS 失败映射为稳定的 `EndpointRequestError` HTTP envelope。模块 I/O 错误只在所属 engine 归类；HTTP 最外层将未知异常收敛为 `endpoint.internal`，不暴露 traceback、绝对路径或敏感值。只有 EndpointHost/Runtime bridge 生命周期错误才进入 Runtime failure 语义。
