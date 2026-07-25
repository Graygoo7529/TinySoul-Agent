# TinySoul Desktop Endpoint Frontend Integration

> 本文件以已经实现的后端为事实源，描述 `Backend -> Endpoint -> Frontend` 的稳定接入契约，不作为前端完成记录。当前前端尚未闭环的消费行为由 `visualization/docs/plans/20260721-plan-endpoint-frontend-consistency.md` 跟踪。

## 契约层级

1. **Backend owner**：AppCommandGateway 统一接收 Terminal 与 Endpoint 命令；WorkspaceEngine、SessionEngine、DailyLifecycleCoordinator、Program/Loop、Context 和 LLM 各自拥有业务状态与事件语义；ObservationRouter 负责按 sink level 扇出旁路事件。
2. **Endpoint adapter**：EndpointEngine 复用同一 Gateway 和业务 Engine，在 Daily active-day lease 内提供 REST facade；authenticated loopback HTTP/WebSocket 只负责协议校验、错误映射与有界 Observation replay，不建立第二份业务状态或控制流。
3. **Frontend consumer**：前端把 REST 投影视为持久业务事实，把 Observation 视为有序的运行时通知与临时执行轨迹；前端不得直接读取业务目录，也不得从事件反向重建或提交后端状态。

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

基址为 `http://127.0.0.1:<port>`。除 `GET /v1/health` 和 CORS `OPTIONS` 外，所有 HTTP 请求都必须携带：

```http
Authorization: Bearer <token>
```

带 JSON body 的请求使用 `Content-Type: application/json`；`PUT /v1/workspace/blob` 使用 `application/octet-stream`；GET 请求不要求 Content-Type。当前 Endpoint 会在解析 body 前拒绝声明的 `Content-Length` 超过 `max_request_bytes` 的请求，blob facade 还会校验实际 bytes 长度。调用方必须发送准确的 Content-Length；该限制不应被表述为对缺少 Content-Length 的流式传输提供硬配额。

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
- `413`：声明的请求长度超过 Endpoint body 上限，或 Workspace blob 实际长度超过上限；
- `422`：请求 schema 或 Session history/actions/trace 参数无效；
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

`command_id` 可省略或传空字符串，此时由后端生成；非空值不得超过 128 个字符。该入口使用与 Terminal 相同的 `InputCommandParser`：

- 普通输入在空闲时进入新的 User Turn，在 Turn 活跃时追加到当前 Turn；
- `/maintenance home` 与 `/maintenance memory [YYYY-MM-DD]` 排入 Program Maintenance；
- App 配置中的退出命令会请求退出 Program；Turn 活跃时，配置中的停止命令会请求停止当前 Turn。

因此 `/v1/input` 是统一命令入口，而不是保证把任意字符串都当作对话正文的 raw-text API。明确的 UI 按钮仍应使用 `/v1/control` 和 `/v1/maintenance` typed API，避免在前端复制命令解析规则。`app.command.accepted/rejected` 是跨 Terminal/前端同步命令的权威事件，`turn.started.payload.request_id` 把初始输入关联到实际 Turn。Maintenance decision pending 时所有 Endpoint user input 返回 `409 maintenance.decision_required`；`apply/discard/stop` 只能通过带 `decision_id` 的 typed decision API 解决，不由该入口解释。

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

响应包含 `events`、`next_sequence` 和 `gap`。`gap=true` 表示 `after` 早于内存 replay window。Endpoint 只报告缺口，不为前端维护恢复 checkpoint；前端应清空 event-derived 临时执行视图，并重新读取自己缓存或正在展示的 REST 权威投影，包括 status、Maintenance、Workspace，以及已加载的 Session history。

WebSocket 地址为 `/v1/events/ws`。连接后 5 秒内发送首帧：

```json
{"token": "...", "after": 0, "mode": "model"}
```

首次连接使用 `after=0`，以免跳过启动 Maintenance 提示。认证成功帧包含 instance/project identity；随后收到 `events` page 或 `heartbeat`。每个 authenticated instance 拥有独立 sequence 空间：前端先按 `instance_id` 隔离或清空 store，再在同一 instance 内按 sequence 排序、去重和续传，不能把不同进程的相同 sequence 当作同一事件。断线重连使用最后成功提交到当前 instance store 的 sequence。

Context Background、当前 Phase 和活跃 LLM Task 没有对应的 REST snapshot。发生 gap 时，窗口外的这部分临时事实无法恢复；前端必须将执行视图标记为不完整，直到后续事件或下一次 `context.background.snapshot` 建立新基线，不能伪造连续轨迹。Workspace 编辑草稿属于本地未提交状态，gap 恢复不得清除它。

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

`context.background.*.payload.entries` 包含当前 top link、content、source、owner 和 evictable，可直接驱动 Top Link 面板。MODEL payload 执行结构化裁剪：图片原始字节替换为大小/MIME/digest，远程图片 URL 去除凭证、query 和 fragment，reasoning content 与 provider 原始 payload 不输出。普通 text、JSON part、tool arguments、模型 answer 和归一化 response metadata 会按 provider-neutral 结构保留，因此仍可能包含用户提交的密钥、绝对路径或其它敏感业务文本；可信本地前端不得把 MODEL 事件写入持久 store、日志或遥测。

`workspace.changed` 是 Manifest cache 的失效通知，payload 为：`operation`、`day`、`previous_revision`、`revision`、`links`、`created_links`、`updated_links`、`removed_links`；只有单个 affected link 时兼容字段 `link` 才非空。operation 当前包括 `initialize`、`reconcile`、`describe`、`write`、`bundle`、`patch`、`trash`、`restore`。该事件由 WorkspaceEngine 在最终成功提交后发布，因此 UI mutation、Agent action、Capability bundle 和公开 reconcile 都使用同一事件；失败、回滚和内部中间 reconciliation 不产生通知。前端必须比较 event day/revision 与本地 Manifest：本地投影落后时重新读取 Manifest，但不得用刷新结果覆盖未提交的编辑草稿。

## Session 接口

- `GET /v1/session/history?ref=<optional-session-ref>&cursor_entry_index=0&cursor_char_offset=0&cursor_entry_digest=<sha256>&cursor_revision=<revision>&max_chars=8000&max_entries=50`：无 ref 时分页读取 authoritative active head，Summary ref 时读取直接 children，Turn ref 时读取单个 overview。`source.scope` 分别为 `active_head`、`summary_children`、`turn_overview`；每个 item 只交付 `ref/kind/child_count/char_count/preview`。active-head 的 `cursor`/`next_cursor` 携带 revision，续页时必须通过 `cursor_revision` 原样回传；若 revision 已变化，后端返回 `422 session.revision_changed`，前端从 root 重新加载。Summary/Turn 是 immutable record，其 cursor 不得携带 revision；
- `GET /v1/session/actions?ref=<session:turn/...>&cursor=0&max_items=50`：返回该 Turn 的确定性 Action summary、by-action 计数、failure groups 与分页 details。summary 覆盖完整 canonical trace，details 携带 call/result trace indexes，不包含 raw arguments 或 raw result payload；
- `GET /v1/session/trace?ref=<session:turn/...>&cursor_entry_index=0&cursor_char_offset=0&cursor_entry_digest=<sha256>&max_chars=8000&max_entries=50`：只分页返回具体 Turn 的 canonical trace。客户端必须原样回传 `next_cursor`；普通 entry 以 index 前进，oversized entry 以 digest 和 Unicode character offset 续读。从 actions 获得已知 trace index 后，使用该 index 作为 `cursor_entry_index` 并提交 `max_entries=1` 精确恢复；trace 响应不含 Background、preview 或 Action summary；
- history/trace 共享 requested/effective char/entry limits、coverage、remaining、page_complete 和 digest-bound oversized continuation，最终 JSON 不超过 effective max chars。owner/ref/kind/limit/cursor/revision 可修正错误返回 `422 session.<reason>`，`details` 只携带稳定 constraint；Session I/O/invariant 返回安全通用 `500 session.failed`，不包含 store path 和原始异常消息。

Session REST 是 SessionEngine 在 Daily active-day lease 内的只读适配，不经 Gateway 或 ActionEngine，不产生 ActionCall/ActionResult，也不写入当前 TurnTrace。无 ref history 只读取最近一次提交的 authoritative Manifest root；已知具体 ref 的 history/actions/trace 可以读取已经原子落盘且校验有效的 immutable record，即使它尚未因生命周期 reconciliation 接入 root。该 record 仍不属于当前 SessionBackground，查询不会触发 orphan reconciliation 或 Manifest revision 变化；前端必须通过 root revision/status/event 判断导航头部是否已提交，不能用重复查询推动 Session 恢复。Session 是已完成 Turn 的事实：前端不得把 WebSocket 临时事件写回 Session，也不得把 history/actions/trace 结果当作 Workspace 文件。

上述 REST 是前端诊断协议，和 Agent 的模型投影有意不同。Agent 只使用 `session.history.inspect` 与 `session.history.recall`：自动 Background 为每个 Turn 提供一个 `session:turn/<turn_id>#actions` 虚拟集合 ref，inspect 将其展开为 compact Action leaf，recall 再按 `session:turn/<turn_id>#action/<occurrence>` 返回语义化 request/result；虚拟 ref 不落盘，也不进入 Manifest。模型侧不再注册 `session.history.actions`，也不接收 trace indexes、call id、cycle id、历史 stage 或完整 canonical trace。前端 `/v1/session/actions` 和 `/v1/session/trace` 继续保留这些诊断事实，以支持 Actions/Trace 页签，但不得把 REST 响应伪装成 Agent Background 或 ActionResult。

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

Endpoint 的 Workspace/Session 请求持有 Daily active-day lease，且与 Agent action 共享同一个 WorkspaceEngine。UI mutation 在活跃 Turn 中还会发布完整 Workspace snapshot；Agent action 通过既有 Workspace action projection 同步 Context。`workspace.changed` 经 ObservationRouter 同时分发到已配置的 Console 与 Endpoint event buffer，不是直接写入 WebSocket buffer。事件只负责失效通知：前端通过 Manifest REST 收敛，不从事件增量重建完整 Workspace；sequence gap 时遵循同一规则。

## Maintenance

- `GET /v1/maintenance`：取得当前 Home/Memory availability 与 pending decision 权威快照；
- `POST /v1/maintenance`：提交 `kind=home|memory`、可选 Memory `target_day`、`command_id` 与 metadata，返回 command receipt；
- `GET /v1/maintenance/decision`：取得当前 pending decision_id 和 Home change；
- `POST /v1/maintenance/decision`：提交 decision_id、command_id 以及 `apply`、`discard` 或 `stop`。

`program.maintenance.available` 只表示存在可运行工作；`program.work.started/completed/failed` 使用 request identity 关联请求；`home.maintenance.decision.required/resolved` 表示人工决策生命周期。decision_id 防止旧对话框确认后续 change；Terminal 和前端同时提交时第一个有效 decision 生效，另一端从 resolved Observation 收敛。`409 maintenance.decision_stale` 时关闭旧对话框并重新获取状态；`409 maintenance.decision_required` 时保持输入草稿并先展示当前 decision。
