# Endpoint 设计

## 定位

Endpoint 是本地桌面客户端与 TinySoul App 的外部协议适配层。它不拥有 Program、Turn、Context、Session、Workspace 或 Maintenance 状态，不解释业务目录，也不建立前端专用事实模型。

Endpoint 由三个边界组成：

- `EndpointEventBuffer` 作为 Observation sink，提供有界进程内 sequence replay；
- `EndpointEngine` 把可信协议请求转换为 AppCommandGateway 或 WorkspaceEngine 调用；
- ASGI/EndpointHost 负责 loopback bind、鉴权、HTTP schema、WebSocket 与服务生命周期。

## 进程与安全

Endpoint 只绑定 loopback，并使用每进程随机 bearer token。HTTP 除 health 外都要求 Authorization header；WebSocket 在首帧提交 token。token 只通过 App 发布的项目实例连接描述交给本机前端，不写入 URL、日志或持久前端 store。

Endpoint 与 Terminal 共同依附一个 `tinysoul start` 进程和同一组业务 Engine。Endpoint 不启动第二个 App、不拥有退出权；`exit_program` 只是向共享 Gateway 提交控制意图，真正退出归 Program。

## 输入与反馈

Terminal 与 Endpoint 的普通文本都进入 AppCommandGateway，再由同一 InputCommandParser/InputDispatcher 解释。typed control、Home/Memory Maintenance request 与带 decision id 的确认也进入 Gateway。所有 accepted/rejected receipt、Turn、Maintenance 和 decision 生命周期反馈都经 ObservationEmitter/Router 同时分发到 Console 与 Endpoint sink。

Console route 由 `tinysoul start --mode` 选择 normal/verbose/model；Endpoint route 固定接收 model，因此前端总能按真实事件切割展示完整层次。Endpoint 不复制 Loop、Action 或 Context 状态机。

## Observation

Event buffer 只保存有界 Observation envelope，并以单调 sequence 支持 HTTP replay 和 WebSocket 断线续传。淘汰产生 gap；客户端清理 event-derived 临时执行视图，并重新读取 status、Maintenance 与 Workspace 权威投影。Context Background、Phase、Action 与 LLM MessageStack 没有 REST snapshot，gap 后不能伪造缺失轨迹。

完整模型上下文来自 `llm.model.request` 的 provider-neutral MessageStack。前端看到的 prior Session 内容因此就是实际进入模型的 Session Background，而不是另一套 Session Explorer 协议。

## Workspace

Workspace REST 持有 Daily active-day lease，并调用同一 WorkspaceEngine：

- manifest 与有界 text/blob read；
- revision/digest CAS text/blob write；
- Trash list/move/restore。

前端不直接访问本地目录。mutation 成功后 WorkspaceEngine 通过共享 ObservationRouter 发布 `workspace.changed`；活跃 Turn 同时由 Gateway 发布 full Workspace snapshot。Endpoint 不绕过 Workspace lock、Manifest、Link、Trash、大小上限或 Context 同步协议。

## 明确不提供

Endpoint 不提供 Home、Memory 或 Session 任意文件 API，也不提供 Session history/actions/trace REST。Session Background、Summary heap 和 prior Action 细节只属于 Agent 的 `core.session.inspect` 语义；调用该 Action 会自然出现在当前 Turn 的 Action 与 MessageStack Observation 中。

Endpoint 也不提供 Context inspect REST、canonical trace REST 或前端审计 checkpoint。应用界面以 Chat 事件观测和 Workspace 资源操作为两个主表面。

## 失败边界

鉴权、schema、状态冲突和 Workspace CAS 失败映射为稳定 HTTP error envelope。模块 I/O 或内部失败不返回绝对路径、traceback 或原始异常。服务启动失败由 RuntimeEndpointBridge 映射为 startup failure；普通请求失败不得改变 Program 控制流。
