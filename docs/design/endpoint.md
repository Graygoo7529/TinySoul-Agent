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

现行外部协议为 v2，旧 v1 路由已删除。结构化 Turn 请求直接使用 ingress 提供的 AgentCommands；终端式文本入口保留 parser 语义。两者使用同一根队列与 Inbox，但新建、追加和等待决定的输入意图明确区分。项目 init/reset/start 继续属于 CLI；HTTP 通过独立 restart 路由请求宿主重建 generation，EndpointHost、事件 buffer、journal 和 instance identity 保持进程级稳定。

CLI 在 Agent factory 中绑定稳定 host，外部单独启动/停止 HTTP server；Agent.wait_for_exit 跨越重启，重建失败不会关闭 Endpoint。单 generation 的嵌入式装配可使用 mount_endpoint 随 Assembly 启停；需要跨 restart 的嵌入方应显式持有 EndpointHost 并按 CLI 的宿主生命周期装配。

依赖绑定与业务可用性分开表达：bind 只替换候选 facade 和 Observation route，EndpointEngineContext 通过显式注入的同步只读函数获取 owner 可用性。CLI 使用 Agent 的 running 状态；单 Assembly 挂载使用其激活完成且仍受理工作的投影。Host 尚未接入可用性来源时不放行业务访问，status、health、replay 和宿主 restart 仍可使用。业务入口集中检查同一可用性，不保存平行 ready 状态；active_day 不作为 activation 完成的替代条件。

HTTP restart 只等待 SDK 已有的共享重启任务并投影结果，不逐请求解绑。重叠请求加入同一操作，等待者取消不改变成功绑定；操作结束之后的新请求可再次重启。观察 route 可记录启动与收尾，故障隔离仍由 Observation owner 负责。

## Turn 与 Job 投影

TurnSnapshot 由 Agent 从保留的 TurnHandle 构造；完成结果通过 TurnResult 投影 owner outcome，包含正式输出、必要提交失败与独立清理诊断，不包含运行时 trace 或 transfer。排队、等待和完成没有 Endpoint 状态副本；句柄淘汰后返回明确的未找到。Reflection 请求进入同一结构化受理与查询路径。

问题与预算请求可同时待决，reply 与 grant 分别传入同一个 Inbox；断开连接不改变等待或取消状态。Job 查询/停止经 Agent 服务和 JobControl 进入唯一 JobRegistry，不暴露 backend。Job owner 串行处理外部停止与 Turn 收尾，停止失败保留可由 Turn sync/Trap 消费的事实；Job 在 Turn 清理后不被 Endpoint 另行保留。ACP Job 应答由 S6 adapter 按权限请求协议实现，不预建通用 Endpoint 状态或回应路由。

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
    schemas/{runtime,turns,reflection,configuration,workspace}.py
    routes/{health,runtime,turns,reflection,events,configuration,workspace}.py
```

HTTP route 只做路径参数/schema 转换和 engine 调用，不直接访问业务私有状态。`http/app.py` 集中注册 middleware、认证、统一错误处理和 routes；`http/server.py` 在 Agent 的事件循环上运行 uvicorn task，异步等待启动与停止，不创建独立服务器线程，也不接管宿主信号处理。

## Observation

`events.buffer` 是进程级 EndpointHost 的 Observation sink，维护有界 sequence replay；`events.journal` 是可选的 best-effort 分段 NDJSON 持久索引。Journal 失败只降级为 memory-only，并由 status 暴露摘要，不改变业务结果。`EndpointEventsEngine` 只提供 `replay`、`wait_after`、`latest_sequence` 和 journal status，事件写入仍属于 ObservationRouter。generation 切换只重绑 route，不重置 instance/cursor。

WebSocket 在首帧完成 token、cursor 和 mode 认证；HTTP replay 与 WebSocket 都使用实例身份和序号续传。实例变化、超前游标或已淘汰区间通过 gap 明确呈现；客户端重新获取 owner 状态，不能把事件丢失当作业务丢失。Observation 不参与业务提交和 Runtime 控制流。

## 配置与 Action projection

`EndpointConfigurationEngine` 读取 ConfigController 的 status/catalog，并 await Agent 服务的 action_catalog 投影。Action catalog 的数据所有权仍属于 ActionEngine；Endpoint 不扫描 TOML、不缓存副本。它通过 `GET /v2/config/actions` 暴露给 Settings 配置工作流，不将其定义为聊天运行时 Action API。

`PATCH /v2/config` 把 typed `set`/`delete` mutation 交给 ConfigController。ConfigController 负责候选环境、owner validator、持久化事务和 Runtime activation；Endpoint 不自行重建 Generation。PATCH 只校验并保存候选，返回 saved/pending_reload；POST /v2/config/reload 在 idle 时显式构造并激活新 Generation。活跃或等待 work 不阻止保存候选，但会阻止激活。进程外壳配置保持只读。

配置 reload 全链异步等待候选构造、失败候选关闭与旧资源退休。退休失败返回有限 cleanup diagnostics，响应仍明确表示新世代已经 active；它不进入“原世代仍生效”的激活失败路径。

## Workspace

`EndpointWorkspaceEngine` 通过 WorkspaceService 的 async operation 作用域调用唯一 Workspace owner，统一处理 manifest、text/blob read/write、显式创建/覆盖、有序编辑、目录/标签与 Trash/Restore 和 context sync。Endpoint 不提供任意文件 API；`PUT /v2/workspace/blob` 是完整 Workspace binary write 能力的一部分。

## 失败边界

请求 schema、鉴权、配置冲突和 Workspace 请求冲突映射为稳定的 `EndpointRequestError` HTTP envelope。模块 I/O 错误只在所属 engine 归类；HTTP 最外层将未知异常收敛为 `endpoint.internal`，不暴露 traceback、绝对路径或敏感值。只有 EndpointHost/Runtime bridge 生命周期错误才进入 Runtime failure 语义。
