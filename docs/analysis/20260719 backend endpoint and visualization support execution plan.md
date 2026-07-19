# Backend Endpoint And Visualization Support Execution Plan

Status: done

## 目标

为 Tauri/React 可视化应用提供稳定的本地后端边界，同时保持 TinySoul 当前 Context、Action、LLM、Workspace、Session、Daily Lifecycle、Runtime 与 App 的职责划分。前端只通过 Endpoint 提交外部输入、读取投影和操作 Workspace，不直接读写 TinySoul 持久目录或解释内部对象。

完成后的后端应支持：

1. 以 `normal`、`verbose`、`model` 三层 Observation 驱动对话与调试界面；
2. 展示 Phase 生命周期、ActionCall、ActionResult、当前 Background Top Link 与正文，以及每次 LLM Task 的完整 provider-neutral MessageStack；
3. 通过同一 `WorkspaceEngine` 实例查询 Manifest、读取、创建、覆盖、删除和恢复资源，并以 digest guard 防止过期 UI 覆盖；
4. 通过本地 HTTP/WebSocket Endpoint 向前端提供有界、鉴权、JSON 安全的接口；
5. 将 Endpoint 生命周期接入 AppBuilder、CLI 与 Runtime failure 语义，并保留原有终端运行方式。

## 设计约束

- Endpoint 是外部协议适配模块，不拥有 Program/Turn/Cycle/Phase 语义，不复制 Workspace、Session、Context 或 Maintenance 业务。
- Observation 只面向外部展示，不参与业务提交；Endpoint sink 失败不能改变已经完成的业务操作。
- MODEL 事件可携带完整文本 MessageStack 与工具定义，但不携带图片原始字节、provider 原始响应、加密 reasoning 原文、绝对路径或密钥。
- Workspace/Session API 在 Daily Lifecycle active-day lease 内执行，不能落入旧日归档与新日初始化之间。
- UI mutation 使用 Workspace Link 和 digest CAS；文件正文不写入 WorkingContext 或 canonical TurnTrace。
- 外部动态数据在 Endpoint 边界转换为明确 DTO；请求失败返回稳定 HTTP 局部结果，只有启动、配置和服务级失败通过 Endpoint Runtime bridge 改变控制流。
- 详细 Observation 仅在进程内有界缓存，不引入新的持久化日志或修改 Session 事实模型。

## 实施阶段

### 1. Observation 协议

- 为 `TaskCall` 增加稳定 `task_id`，发布 LLM task started/completed/failed，并在 model request/response 中保持同一 task id。
- 在 Phase2 归一化后发布 ActionCall，在 Phase3 合并结果后发布 ActionResult；payload 复用 Action 模块现有 JSON-safe trace renderer。
- 由 Context 模块发布 Background snapshot/change，包含当前 Top Link、owner/source、evictable 与有界正文。
- 扩展 ObservationRouter 为 sink-specific level route，并增加 Endpoint 使用的有界、有序事件 hub。

### 2. Endpoint 模块

- 新增 Endpoint settings、errors、failures、Runtime bridge、DTO、事件 envelope、Engine/Builder 与 ASGI server。
- 提供 status、input/control、events、Session history/recall、Workspace manifest/resource/trash 和 Maintenance decision API。
- HTTP 使用 bearer token；WebSocket 使用首帧认证；只允许 loopback bind；事件支持 sequence replay 和 gap。
- OpenAPI 作为 React 类型生成来源；Endpoint 不返回内部 Python 对象。

### 3. 资源与生命周期接入

- 为 DailyLifecycleCoordinator 增加 active-day lease，Endpoint 的 Workspace/Session 操作统一经该边界。
- 为 Workspace 增加通用有界 byte read、guarded trash 和 Endpoint mutation 所需的完整 Manifest 返回。
- UI mutation 成功后，在活跃 Turn 中发布 WorkspaceSnapshot；Context 对低 revision full snapshot 执行幂等 no-op，对同 revision 冲突继续失败。
- 将手工 Home Maintenance decision broker 泛化为可供终端与 Endpoint 共用的 typed broker。

### 4. App 与 CLI

- AppBuilder 在 Endpoint 开启时组装 event hub、EndpointEngine 和 Endpoint input source；终端默认行为不变。
- 新增 `tinysoul serve --root ...`，stdout 只输出结构化 ready handshake，服务错误走 stderr 和非零退出。
- Endpoint 依赖作为 desktop optional dependency；缺失依赖时只影响 serve，不影响普通 CLI/library 导入。

### 5. 验证与文档

- 增加 `tests/endpoint/`，覆盖鉴权、请求校验、事件回放、输入/控制、Session、Workspace CAS、Trash 与 Maintenance。
- 扩展 LLM、Loop、Context、Workspace、App 测试，覆盖新增公共协议和并发边界。
- 在 `docs/endpoint/` 提供前端启动、鉴权、REST/WebSocket schema、状态聚合和错误处理文档。
- 同步 `docs/design/` 对应模块和根 `AGENT.md` 当前进度。
- 运行全量 pytest、ty 类型检查以及 wheel/package-data 验证。

## 验收标准

- fake provider User Turn 可经 Endpoint 启动，并通过 WebSocket 观察 Phase1/2/3、ActionCall/Result 与 LLM MessageStack。
- 前端可读取当前 Workspace Manifest，基于 ETag/digest 创建、覆盖、删除并恢复资源；过期 mutation 稳定返回 conflict。
- Endpoint 请求与日切互斥，Turn 内 Workspace action 和 UI mutation 仍由同一 Engine 线性化。
- Endpoint 断开、慢消费者或 sink 异常不改变 Turn、Workspace mutation 或 Session commit 结果。
- 普通 `tinysoul` 与 `tinysoul --once` 行为和输出层级保持兼容。

## 实施结果

- Observation：`TaskCall.task_id` 贯穿 task/model 事件；Phase2/3 发布结构化 Action call/result；Context 从已提交 Background 条目发布 Top Link/content snapshot/change；ObservationRouter 使用 per-sink mode。
- Endpoint：新增 settings/errors/failures/Runtime bridge、Engine、有界 sequence event buffer 与延迟导入的 FastAPI/Uvicorn server；HTTP bearer、WebSocket 首帧认证、loopback/随机预绑定端口、OpenAPI、稳定错误 envelope 和 ready handshake 已实现。
- 接入：`tinysoul serve` 复用正式 AppBuilder；InputDispatcher 增加 typed control；Daily active-day lease 保护 Endpoint Session/Workspace；HomeDecisionBroker 以 decision_id 同时服务终端和 Endpoint。
- Workspace：text 与 blob read/write、Manifest revision guard、resource digest guard、Trash/Restore 和 mutation 后 full snapshot 已接入；Context 对更低 revision snapshot 幂等 no-op，对同 revision 冲突保持拒绝。
- 文档：模块设计位于 `docs/design/endpoint.md`，前端协议位于 `docs/endpoint/frontend integration.md`，App/Context/LLM/Workspace 与根规约已同步。
- 验证：Endpoint API、真实预绑定 Uvicorn listener、WebSocket、事件分层、Workspace CAS/blob/Trash、producer observation 和 stale snapshot 均有测试；全量 tests 与 ty 类型检查通过。
