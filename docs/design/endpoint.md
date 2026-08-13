# Endpoint 设计

## 定位

Endpoint 是本地桌面客户端与 TinySoul App 的外部协议适配层。它不拥有 Program、Turn、Context、Session、Workspace 或 Maintenance 状态，不解释业务目录，也不建立前端专用事实模型。

Endpoint 由三个边界组成：

- `EndpointEventBuffer` 作为 Observation sink，提供有界内存热缓存与 sequence replay；可选 `EndpointEventJournal` 将同一 envelope 以分段 NDJSON 持久化到 `runtime/endpoint/events/`，支持重启后续号与深读；
- `EndpointEngine` 把可信协议请求转换为 AppCommandGateway 或 WorkspaceEngine 调用；
- ASGI/EndpointHost 负责 loopback bind、鉴权、HTTP schema、WebSocket 与服务生命周期。阻塞业务 handler 使用同步 `def`（线程池），避免冻结事件循环。

## 进程与安全

Endpoint 只绑定 loopback，并使用每进程随机 bearer token。HTTP 除 health 外都要求 Authorization header；WebSocket 在首帧提交 token。token 只通过 App 发布的项目实例连接描述交给本机前端，不写入 URL、日志或持久前端 store。

Endpoint 与 Terminal 共同依附一个 `tinysoul start` 进程和同一组业务 Engine。Endpoint 不启动第二个 App、不拥有退出权；`exit_program` 只是向共享 Gateway 提交控制意图，真正退出归 Program。

## 输入与反馈

Terminal 与 Endpoint 的普通文本都进入 AppCommandGateway，再由同一 InputCommandParser/InputDispatcher 解释。typed control 与 Home/Memory Maintenance request 也进入 Gateway。所有 accepted/rejected receipt、Turn 和 Maintenance 生命周期反馈都经 ObservationEmitter/Router 同时分发到 Console 与 Endpoint sink。

Console route 由 `tinysoul start --mode` 选择 normal/verbose/model；Endpoint route 固定接收 model，因此前端总能按真实事件切割展示完整层次。Endpoint 不复制 Loop、Action 或 Context 状态机。

## Observation

事件 Journal 是 Endpoint-owned 的 best-effort 持久索引。manifest 只作为可重建缓存；启动时从受控命名的 NDJSON segment 校验并重建 sequence，最新 segment 的截断尾行可以修复，中间 segment 损坏则降级为 memory-only，并在 `event_journal.failure` 暴露稳定摘要。分页游标以实际扫描到的 sequence 为准：健康 Journal 因字节/记录预算停止时不得跨过未返回记录拼接内存尾部；读取已确认损坏并以 `gap=true` 表达不可用区间后，可以在同一响应继续交付仍健康的热内存尾部。

Event buffer 保存有界 Observation envelope，并以单调 sequence 支持 HTTP replay 和 WebSocket 断线续传。Journal 在默认启用时 best-effort 追加同一 envelope；写失败只降级为内存路径并在 `GET /v1/status.event_journal` 暴露摘要，不反向影响业务。内存窗口外的 `after` 从 journal 深读；journal 滚动淘汰最旧段后，对该前缀的 replay 才产生 gap。客户端先捕获 status 的 `latest_event_sequence` 快照，再以单调 cursor 完整读取到该目标；Journal 的字节总量是持久历史边界，客户端不得另设静默页数/条数截断。客户端清理 event-derived 临时执行视图，并重新读取 status、Maintenance 与 Workspace 权威投影。不提供 Session REST snapshot；完整 MessageStack 仍只来自 observation 流（含 journal 恢复）。

Maintenance availability 与事件严格分工：Program 在 Endpoint ready 前完成 Archive preflight 和唯一持久 availability 刷新；`GET /v1/maintenance` 只读取这份 Maintenance-owned 投影，不扫描 Archive。前端连接后先读取 GET；收到 `program.maintenance.available`、`maintenance.completed` 或 `maintenance.availability.changed` 后重新读取。事件丢失或进程重启不会丢失提示事实，Endpoint 也不建立第二份前端专用状态。

WebSocket 在没有新事件时按 `EndpointSettings.websocket_heartbeat_seconds` 发送 heartbeat，默认间隔为 15 秒。该设置只控制连接存活反馈，不改变 event sequence、replay 或 gap 语义。

完整模型上下文来自 `llm.model.request` 的 provider-neutral MessageStack。前端看到的 prior Session 内容因此就是实际进入模型的 Session Background，而不是另一套 Session Explorer 协议。

## Workspace

Workspace REST 持有 Daily active-day 读 lease（与 User Turn 共享读；日切持写），并调用同一 WorkspaceEngine：

- manifest 与有界 text/blob read；
- revision/digest CAS text/blob write；
- Trash list/move/restore。

前端不直接访问本地目录。mutation 成功后 WorkspaceEngine 通过共享 ObservationRouter 发布 `workspace.changed`；活跃 Turn 同时由 Gateway 发布 full Workspace snapshot。Endpoint 不绕过 Workspace lock、Manifest、Link、Trash、大小上限或 Context 同步协议。

## 明确不提供

Endpoint 不提供 Home、Memory 或 Session 任意文件 API，也不提供 Session history/actions/trace REST。Session Background、Summary heap 和 prior Action 细节只属于 Agent 的 `core.session.inspect` 语义；调用该 Action 会自然出现在当前 Turn 的 Action 与 MessageStack Observation 中。

Endpoint 也不提供 Context inspect REST、canonical trace REST 或前端审计 checkpoint。应用界面以 Chat 事件观测和 Workspace 资源操作为两个主表面。

## Configuration API

Endpoint 提供以下配置协议入口：

- `GET /v1/config` 返回 activity、generation/activation 状态、全部 effective fields、每个
  source 的类型、相对路径、值投影和静态 writable；`config.*` 入口及 Endpoint 进程外壳以
  `writable=false` 返回。App 的 interactive、输入命令、输出路由和 retained outcome
  也属于进程外壳，读取可见但不在当前进程内改写。
- `GET /v1/config/sections/{section_id}` 返回指定 section 的字段投影。当前投影由
  Infra `ConfigController` 从 effective fields 按 dotted key 前缀筛选，不引入 owner descriptor
  或第二套业务配置 schema；字段的业务解释和可编辑布局仍由各模块及前端负责。
- `GET /v1/config/catalog` 返回 Infra package-owned 的 surfaces、field groups、collections 和
  fields。collection 提供对象 identity 文案，field 通过显式 group 归属到同一 surface。它只
  表达展示元数据与受控创建 source，不返回当前值、前端 navigation 或 revision；当前事实仍
  只来自 `GET /v1/config`。
- `GET /v1/actions/catalog` 在 RuntimeHandle read lease 下读取当前 Generation 的 User Action
  有限投影，返回 Action ID、domain、description 和 backend kind。Endpoint 不扫描 package
  TOML，也不缓存 Action 状态。
- `POST /v1/config/validate` 只构建候选 ConfigEnvironment/Plan，不写文件或切换 Generation。
- `PATCH /v1/config` 接受 source-aware `set`/`delete` operations。Infra 临时编辑 TOML/.env，
  App 构建候选 Generation；文件提交和 handle 切换完成后才返回 `state=active` 与
`generation_id`。候选解析、事务或激活失败会保留旧文件和旧 Generation。

Provider、Model 和 Task Chain 的创建/替换对 collection object root 使用一次 `set`；删除对同一
root 使用 `delete`。Action overrides 与 Task Chain 排序提交完整数组，TOML writer 使用 inline
table 保持结构化 round trip。Backend 不额外提供 config object endpoint，前端用 catalog
collection descriptor 与 ConfigStatus 动态枚举对象。

所有配置修改统一要求 Runtime activity 为 `idle`；User Turn、Maintenance Turn、每日切换或
已有激活期间返回 `409 config.activation_unavailable`，不提供字段级 currently_writable 或
前端 revision/CAS。dotenv 读取保留原始键值、不会修改 `os.environ`，下一代 Generation 从
新的 dotenv source 重新创建 runtime env。

## 失败边界

鉴权、schema、状态冲突和 Workspace CAS 失败映射为稳定 HTTP error envelope。模块 I/O 或内部失败不返回绝对路径、traceback 或原始异常。服务启动失败由 RuntimeEndpointBridge 映射为 startup failure；普通请求失败不得改变 Program 控制流。
