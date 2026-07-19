# TinySoul Desktop Endpoint Frontend Integration

## 技术选择

桌面壳推荐使用 **Tauri 2 + React + TypeScript**。Tauri 只负责进程、窗口、系统托盘和安装包能力，Python TinySoul 作为 sidecar 运行；React 不直接使用 Tauri filesystem API 访问 `runtime/workspace`、Session、Home 或 Memory。Electron 仍可作为不具备 Rust/Tauri 构建环境时的替代壳，但前端协议与本页不变。

前端状态分为两类：

- 对话与执行状态由 Endpoint Observation event 构建，只保存在 UI store；
- Workspace/Session 以 REST 读取当前权威投影，mutation 成功后用响应中的新 Manifest 替换缓存。

## 启动与关闭

Tauri sidecar 启动命令：

```text
tinysoul serve --root <project-root> --host 127.0.0.1 --port 0 --mode model
```

进程成功监听后，stdout 输出且只输出一行 ready JSON：

```json
{
  "type": "endpoint.ready",
  "protocol_version": 1,
  "host": "127.0.0.1",
  "port": 49152,
  "token": "process-local-bearer-token"
}
```

`port=0` 使用预绑定 socket 取得空闲端口。未显式传入 `--token` 时后端生成进程级 token，并通过 child stdout 交给父进程；不要把 token 写入 localStorage、日志或 URL。前端退出时调用 `POST /v1/control` 提交 `exit_program`，等待 sidecar 正常退出；超时后才由 Tauri 收尾子进程。

调试时可使用 `tinysoul serve ... --terminal --terminal-mode verbose` 同时启用 stdin/Console；该模式把 ready JSON 写入 stderr，不适合作为桌面 sidecar handshake。默认不带 `--terminal` 的 serve 仍是 headless 模式。

生产安装包需要携带真实 CPython 环境及 TinySoul desktop extra，不能只把当前入口冻结为不完整的单文件解释器，因为 Script Python action 使用当前 Python executable。desktop extra 包含 FastAPI、Uvicorn 和 WebSockets。

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
  "text": "请分析当前工作区",
  "metadata": {"client_message_id": "msg_123"}
}
```

返回 `202 {"accepted": true}`。空闲时输入进入新的 User Turn；Turn 活跃时输入按现有 InputDispatcher 语义追加到当前 Turn。Maintenance decision pending 时返回 `409 maintenance.decision_required`，普通文本（包括 `apply`、`discard`、`stop`）不会解决该 decision。

### 控制

`POST /v1/control`

```json
{"kind": "stop_turn", "metadata": {}}
```

`kind` 只能是 `stop_turn` 或 `exit_program`。这是 typed control，不应由前端模拟 `/stop` 或 `/exit` 文本。

### 状态

`GET /v1/status` 返回 active day、Turn 是否活跃、Workspace/Session revision、最新 event sequence 和 Maintenance decision pending 状态。`ready=false` 时应继续展示连接状态并重试，不能访问本地目录绕过 Daily 初始化。

## Observation 事件

HTTP 补拉：

```text
GET /v1/events?after=120&mode=verbose&limit=200
```

响应包含 `events`、`next_sequence` 和 `gap`。`gap=true` 表示 `after` 早于内存 replay window，前端应清空临时执行视图，并通过 status、Session、Workspace REST 重新取得权威投影。

WebSocket 地址为 `/v1/events/ws`。连接后 5 秒内发送首帧：

```json
{"token": "...", "after": 120, "mode": "model"}
```

认证成功先收到 `authenticated`，随后收到 `events` page 或 `heartbeat`。断线重连使用客户端最后提交到 store 的 sequence 作为 `after`。

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

- normal：`turn.output`、Turn terminal、Daily/Program work 与 `workspace.changed`；
- verbose：`turn.started`、`loop.phase.started/completed`、`llm.task.started/completed/failed`、`action.call`、`action.result`、`context.background.snapshot/changed`；
- model：`llm.model.request/response`。同一次 LLM Task 的全部事件都带相同 `payload.task_id`；request 中的 `messages` 和 `tools` 是完整 provider-neutral 构造结果。

`context.background.*.payload.entries` 包含当前 top link、content、source、owner 和 evictable，可直接驱动 Top Link 面板。MODEL 事件不含图片原始字节、provider 原始响应、reasoning content、密钥或绝对路径。

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

Endpoint 的 Workspace/Session 请求持有 Daily active-day lease，且与 Agent action 共享同一个 WorkspaceEngine。UI mutation 在活跃 Turn 中还会发布完整 Workspace snapshot；`workspace.changed` 经 ObservationRouter 同时分发到已配置的 Console 与 Endpoint event buffer，不是直接写入 WebSocket buffer。

## Maintenance

- `GET /v1/maintenance/decision`：取得当前 pending decision_id 和 Home change；
- `POST /v1/maintenance/decision`：提交 decision_id 以及 `apply`、`discard` 或 `stop`。

decision_id 防止旧对话框确认后续 change。`409 maintenance.decision_stale` 时关闭旧对话框并重新获取 pending 状态；`409 maintenance.decision_required` 时保持输入草稿并先展示当前 decision。
