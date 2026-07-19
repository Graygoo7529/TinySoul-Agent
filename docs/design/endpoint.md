# Endpoint 模块设计

## 定位

Endpoint 是本地桌面客户端与 TinySoul App 之间的外部协议适配模块。它不拥有 Program、Turn、Context、Session、Workspace 或 Maintenance 状态，也不直接解释持久目录；所有请求调用 App 已装配的同一业务门面。

Endpoint 由三个边界组成：有界事件缓冲接收 Observation；Engine 把 HTTP 语义转换为明确的输入、控制和业务门面调用；ASGI adapter 只负责 loopback bind、鉴权、schema、错误 envelope 与 WebSocket 收发。FastAPI/Uvicorn 仅由 `tinysoul serve` 延迟导入。

## 生命周期与安全

服务只允许绑定 loopback IP。HTTP 使用进程级 bearer token，WebSocket 使用首帧 token，token 不进入 URL、Observation 或持久化。随机端口通过预绑定 socket 交给 Uvicorn，避免先探测再监听的端口竞争。

Endpoint 作为 App InputSource 启停，与 ProgramRunner、终端和 scheduler 共享 App 生命周期。启动或 server 失败由 Endpoint failure kind 经 RuntimeEndpointBridge 映射为 startup failure；单次请求的参数、状态冲突和资源冲突属于 HTTP 局部结果，不改变 Runtime 控制流。

## 事件与状态

事件缓冲只保存有界的进程内 Observation envelope，以单调 sequence 支持 HTTP replay 与 WebSocket 断线续传。缓存淘汰产生 gap，客户端必须回到 Session、Workspace 和 status 权威投影恢复，不把 Observation 当作业务日志持久化。

normal、verbose、model 是包含层级。Endpoint 捕获层级由 AppBuilder 与 App 输出层级取较高值，客户端订阅可选择不高于已捕获层级的视图。模型上下文、Action 和 Background 事件由各自 owner 发布，Endpoint 不从私有字段重建这些内容。

## 业务接入

输入和控制统一进入 InputDispatcher。Session 查询调用 SessionEngine。Workspace 查询和 mutation 调用同一 WorkspaceEngine，并在 Daily active-day lease 中执行；UI mutation 同时使用 manifest revision 和 resource digest guard，成功后在活跃 Turn 中发布 Workspace full snapshot。Maintenance decision 复用 App-owned typed broker，并使用 decision identity 关联请求。

Endpoint 不提供 Home、Memory、Session 或 Workspace 任意路径文件 API，不允许前端绕过 Link、Manifest、Trash 和模块大小限制。文本协议使用 Workspace 有界 UTF-8 read/write；其它资源使用受 byte limit 约束的完整 blob read/bundle write，分类、media type、digest 与 Manifest 仍由 Workspace owner 确定。
