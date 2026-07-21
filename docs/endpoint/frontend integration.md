# TinySoul Desktop Endpoint Frontend Integration

## 技术选择

桌面壳使用 **Tauri 2 + React + TypeScript**。Tauri 只负责窗口和读取 App-owned 连接描述；它不启动、持有或停止 Python 进程。React 不直接使用 Tauri filesystem API 访问 `runtime/workspace`、Session、Home 或 Memory。

前端状态分为两类：

- 对话与执行状态由 Endpoint Observation event 构建，只保存在 UI store；
- Workspace/Session 以 REST 读取当前权威投影，mutation 成功后用响应中的新 Manifest 替换缓存。

## 启动、发现与关闭

用户在可见 Terminal 中启动唯一后端：

```text
tinysoul start --root <project-root> --mode normal
```

`--mode` 只控制该 Terminal 的 Console 输出，Endpoint 始终捕获 model。后端在构建业务 Engine 前持有项目级进程 lease；Endpoint ready 后在当前用户运行目录原子写入连接描述：

```json
{
  "schema_version": 1,
  "protocol_version": 1,
  "instance_id": "instance_...",
  "project_root": "...",
  "project_identity": "sha256-of-canonical-root",
  "pid": 1234,
  "host": "127.0.0.1",
  "port": 49152,
  "token": "process-local-bearer-token"
}
```

前端根据规范化项目根计算 project identity，通过 Tauri 读取对应描述，再以 authenticated status 校验 instance/project identity。没有有效描述时只展示推荐启动命令和重试按钮，不唤起 Terminal。token 只保存在 Tauri/React 当前内存，不写入 localStorage、日志或 URL。前端关闭只断开；后端由拥有它的 Terminal 通过 `exit` 或 EOF 结束，并清理连接描述。第二个相同项目的 `tinysoul start` 在构建第二个 WorkspaceEngine 前失败。

## 鉴权与通用规则

基址为 `http://127.0.0.1:<port>`。除 `GET /v1/health` 外，所有 HTTP 请求都必须携带：

```http
Authorization: Bearer <token>
Content-Type: application/json
```

HTTP 错误统一为：

```json
{
  "error": {
    "code": "workspace.conflict",
    "message": "Workspace manifest revision mismatch: expected 4, current 5",
    "details": {}
  }
}
```

- `401`：token 缺失或错误；
- `409`：Program 尚未完成 active-day 初始化、Maintenance decision 待处理、控制与当前状态冲突，或 Workspace revision/digest 过期；
- `413`：请求超过 Endpoint body 上限；
- `422`：请求 schema 或 Session recall 参数无效；
- `500`：模块 I/O 或内部失败，正文不暴露绝对路径、traceback 或原始异常。

受鉴权的 `GET /openapi.json` 是 HTTP TypeScript client/schema 生成来源；WebSocket 首帧和 server frame 使用本页定义的独立协议，不属于 OpenAPI path。

## 对话与控制

### 输入

`POST /v1/input`

```json
{
  "text": "analyze the workspace",
  "command_id": "command_123",
  "metadata": {"client_message_id": "msg_123"}
}
```

返回 `202` command receipt：

```json
{"accepted": true, "command_id": "command_123", "kind": "start_turn", "state": "queued"}
```

空闲时输入进入新的 User Turn；Turn 活跃时追加到当前 Turn。`app.command.accepted` 是跨 Terminal/前端同步用户输入的权威事件，`turn.started.payload.request_id` 把初始输入关联到实际 Turn。Maintenance decision pending 时返回 `409 maintenance.decision_required`，普通文本不会解决 decision。

### 控制

`POST /v1/control`

```json
{"kind": "stop_turn", "command_id": "command_456", "metadata": {}}
```

`kind` 只能是 `stop_turn` 或 `exit_program`。桌面 UI 通常只使用 `stop_turn`；前端关闭不得提交 `exit_program`。

### 状态

`GET /v1/status` 返回 instance/project identity、active day、Turn 是否活跃、Workspace/Session revision、最新 event sequence 和 Maintenance decision pending 状态。identity 与连接描述不一致时必须断开；`ready=false` 时继续重试，不能访问本地目录绕过 Daily 初始化。

## Observation 事件

HTTP 补拉：

```text
GET /v1/events?after=0&mode=model&limit=200
```

响应包含 `events`、`next_sequence` 和 `gap`。`gap=true` 表示 `after` 早于内存 replay window，前端应清空临时执行视图，并通过 status、Session、Workspace REST 重新取得权威投影。

WebSocket 地址为 `/v1/events/ws`。连接后 5 秒内发送首帧：

```json
{"token": "...", "after": 120, "mode": "model"}
```

首次连接使用 `after=0`，以免跳过启动 Maintenance 提示。认证成功帧包含 instance/project identity；随后收到 `events` page 或 `heartbeat`。断线重连使用客户端最后提交到 store 的 sequence。raw store 以 `(instance_id, sequence)` 去重；gap 后清理临时执行视图，并重新读取 Maintenance、Session 和 Workspace 权威投影。

事件 envelope：

```json
{
  "sequence": 121,
  "name": "loop.phase.started",
  "level": "verbose",
  "source": "loop.cycle",
  "scope": [
    {"level": "program", "name": "program"},
    {"level": "turn", "name": "turn_ab12"},
    {"level": "cycle", "name": "cycle_1"},
    {"level": "phase", "name": "phase1"}
  ],
  "message": "phase1 started.",
  "payload": {"phase": "phase1"},
  "created_at": 1784422800.0
}
```

主要 UI 映射：

- normal：`app.command.accepted/rejected`、`turn.output`、Turn terminal、Maintenance availability/decision、Program work 与 `workspace.changed`；
- verbose：`turn.started`、`loop.phase.started/completed`、`llm.task.started/completed/failed`、`action.call`、`action.result`、`context.background.snapshot/changed`；
- model：`llm.model.request/response`。同一次 LLM Task 的全部事件都带相同 `payload.task_id`；request 中的 `messages` 和 `tools` 是完整 provider-neutral 构造结果。

`context.background.*.payload.entries` 包含当前 top link、content、source、owner 和 evictable，可直接驱动 Top Link 面板。MODEL 事件不含图片原始字节、provider 原始响应、reasoning content、密钥或绝对路径。

`workspace.changed` 是 Manifest cache 的失效通知，payload 为：`operation`、`day`、`previous_revision`、`revision`、`links`、`created_links`、`updated_links`、`removed_links`；只有单个 affected link 时兼容字段 `link` 才非空。operation 当前包括 `initialize`、`reconcile`、`describe`、`write`、`bundle`、`patch`、`trash`、`restore`。该事件由 WorkspaceEngine 在最终成功提交后发布，因此 UI mutation、Agent action、Capability bundle 和公开 reconcile 都使用同一事件；失败、回滚和内部中间 reconciliation 不产生通知。

## Session 接口

- `GET /v1/session/history`：当前 active day 的有界历史 head；
- `GET /v1/session/recall?ref=<session-ref>&cursor=0&max_chars=8000`：按 ref 分页召回不可变记录。

Session 是已完成 Turn 的事实，不应把当前 WebSocket 临时事件写回 Session，也不应把 recall 结果当作 Workspace 文件。

## Workspace 接口

### Manifest 与读取

- `GET /v1/workspace/manifest`：先 reconcile，再返回 schema/day/revision/resources；
- `GET /v1/workspace/resource?link=workspace:notes/demo.md`：读取有界 UTF-8 text，返回 text、truncated、size、digest；
- `GET /v1/workspace/blob?link=workspace:assets/image.png`：读取完整但受 byte limit 约束的资源，响应使用 Manifest media type，digest/link/size 位于 `X-TinySoul-*` headers。

### 创建与覆盖

`PUT /v1/workspace/resource`

```json
{
  "link": "workspace:notes/demo.md",
  "text": "new content",
  "overwrite": true,
  "expected_digest": "sha256-of-opened-version",
  "expected_revision": 7,
  "retention": "day"
}
```

创建时 `overwrite=false` 且 `expected_digest=""`；覆盖时必须提交打开资源时取得的 digest。每次 mutation 都必须提交当前 Manifest revision。revision check、digest check 与写入在同一个 Workspace Engine lock 内执行。成功响应同时包含 `record` 和新 `manifest`；前端应整体替换 Manifest cache。

二进制新增/覆盖使用 `PUT /v1/workspace/blob`，query 参数为 link、overwrite、expected_digest、expected_revision、retention，body 为 `application/octet-stream`。正文受 request byte limit；分类和 media type 由 Workspace 根据实际资源确定，前端不能提交任意本地路径或伪造 Manifest record。

### Trash 与恢复

- `POST /v1/workspace/trash`：提交 link、expected_digest、expected_revision；
- `GET /v1/workspace/trash`：返回包含稳定 `ref` 的可恢复项；
- `POST /v1/workspace/restore`：提交 trash_ref、expected_revision。

删除是可恢复 Trash move，不提供直接物理删除。收到 `workspace.conflict` 时保留用户编辑缓冲，重新拉取 Manifest/正文，再由用户决定合并或覆盖，不能自动用新 digest 重试旧正文。

Endpoint 的 Workspace/Session 请求持有 Daily active-day lease，且与 Agent action 共享同一个 WorkspaceEngine。UI mutation 在活跃 Turn 中还会发布完整 Workspace snapshot；Agent action 通过既有 Workspace action projection 同步 Context。`workspace.changed` 经 ObservationRouter 同时分发到已配置的 Console 与 Endpoint event buffer，不是直接写入 WebSocket buffer。前端把该事件作为失效通知：若响应中的 Manifest 尚未覆盖事件的 revision/day，则重新读取 Manifest；sequence gap 时同样回到 Manifest 权威投影，不尝试从事件增量重建完整状态。

## Maintenance

- `GET /v1/maintenance`：取得当前 Home/Memory availability 与 pending decision 权威快照；
- `POST /v1/maintenance`：提交 `kind=home|memory`、可选 Memory `target_day`、`command_id` 与 metadata，返回 command receipt；
- `GET /v1/maintenance/decision`：取得当前 pending decision_id 和 Home change；
- `POST /v1/maintenance/decision`：提交 decision_id、command_id 以及 `apply`、`discard` 或 `stop`。

`program.maintenance.available` 只表示存在可运行工作；`program.work.started/completed/failed` 使用 request identity 关联请求；`home.maintenance.decision.required/resolved` 表示人工决策生命周期。decision_id 防止旧对话框确认后续 change；Terminal 和前端同时提交时第一个有效 decision 生效，另一端从 resolved Observation 收敛。`409 maintenance.decision_stale` 时关闭旧对话框并重新获取状态；`409 maintenance.decision_required` 时保持输入草稿并先展示当前 decision。
