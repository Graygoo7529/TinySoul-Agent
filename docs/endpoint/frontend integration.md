# TinySoul 前端对接协议

## 1. 运行模型

前端只连接用户已启动的后端：

```powershell
tinysoul start --root <project-root> --mode normal
```

`--mode` 只改变 Terminal 输出。Endpoint 始终接收 model 级 Observation。前端未发现实例时只展示推荐命令，不启动或持有后端进程；窗口关闭也不请求退出 Program。

后端 ready 后发布项目实例连接描述，包含 host、随机 port、token、instance id、project identity 与 project root。前端必须验证连接描述、`GET /v1/status` 和当前项目身份一致。

## 2. 鉴权与通用错误

除 `GET /v1/health` 外，HTTP 请求都携带：

```text
Authorization: Bearer <token>
```

WebSocket 在连接后 5 秒内发送 token 首帧。服务只绑定 loopback。

错误 envelope：

```json
{
  "error": {
    "code": "workspace.conflict",
    "message": "Workspace revision mismatch: expected 4, current 5",
    "details": {}
  }
}
```

- `401`：token 无效；
- `409`：Program 未 ready、控制冲突或 Workspace CAS 冲突；
- `413`：请求或资源超过 Endpoint 上限；
- `422`：请求 schema 无效；
- `500`：安全收敛的模块/服务失败。

`GET /openapi.json` 需要鉴权，是当前 HTTP contract 的权威描述。Endpoint 不包含任何 `/v1/session/*` path。

## 3. 状态

`GET /v1/status`：

```json
{
  "protocol_version": 1,
  "instance_id": "instance_...",
  "project_identity": "...",
  "ready": true,
  "active_day": "2026-07-25",
  "turn_active": false,
  "workspace_revision": 8,
  "latest_event_sequence": 121
}
```

status 不暴露 Session revision。`ready=false` 时继续等待，不得访问本地业务目录绕过 Daily 初始化。

## 4. 统一输入

### 普通文本与命令

`POST /v1/input`

```json
{
  "text": "analyze the workspace",
  "command_id": "command_123",
  "metadata": {"client_message_id": "msg_123"}
}
```

返回 `202` receipt：

```json
{"accepted": true, "command_id": "command_123", "kind": "start_turn", "state": "queued"}
```

该入口使用与 Terminal 相同的 `InputCommandParser`，因此普通对话、配置的 stop/exit 命令和 `/maintenance ...` 具有一致语义。明确 UI 控件应优先使用 typed control/Maintenance API。Maintenance 命令始终进入 Program queue，不成为活跃 User Turn 的 append，也不等待人工审批。

### 控制

`POST /v1/control`

```json
{"kind": "stop_turn", "command_id": "command_456", "metadata": {}}
```

`kind` 为 `stop_turn` 或 `exit_program`。前端关闭不应自动发送 `exit_program`。

## 5. Maintenance

- `GET /v1/maintenance`：返回 Home pending 计数和持久提示单中的 Memory dates；
- `POST /v1/maintenance`：提交 `kind=daily|home|memory`、可选 Memory `target_day`/`rebuild_memory`、command id 与 metadata。

Terminal 与前端可同时提交 Maintenance request；请求按进入 Program queue 的顺序串行执行，手动与 scheduler request 走同一 MaintenanceEngine 流程。前端连接后先读取 availability；收到 `program.maintenance.available`、`maintenance.started`、`maintenance.completed` 或 `maintenance.availability.changed` 时只重新读取 `GET /v1/maintenance`，不从事件 payload 建立第二份状态。

## 6. Observation 事件

HTTP replay：

```text
GET /v1/events?after=0&mode=model&limit=200
```

响应含 `events`、`next_sequence`、`gap`。WebSocket 地址为 `/v1/events/ws`，首帧：

```json
{"token": "...", "after": 0, "mode": "model"}
```

空闲连接会收到 `{"type":"heartbeat","next_sequence":121}`；heartbeat 不增加 sequence，也不表示业务状态变化。

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

前端按 `(instance_id, sequence)` 排序、去重和续传：

- normal：command receipt、Turn output/terminal、Maintenance、Program work、`workspace.changed`；
- verbose：Turn/Cycle/Phase、LLM Task、Action call/result、Context Background；
- model：`llm.model.request/response`，同一 Task 使用 `task_id` 关联。

`llm.model.request.payload.messages` 是实际构造的 provider-neutral MessageStack。Session Background、Context heap head、Working 和 Task prompt 均从这里按 label/内容展示。前端不得把 model payload 写入持久 store、日志或遥测。

`gap=true` 时清理 event-derived live Turn/Cycle/Phase/Task 视图，并重新读取 status、Maintenance 和 Workspace Manifest。不要调用已删除的 Session REST 补造模型历史；在下一次真实 MessageStack 或 Background snapshot 到来前标记轨迹不完整。未提交 Workspace 编辑草稿不得因 gap 被清除。

## 7. Workspace

### 读取

- `GET /v1/workspace/manifest`：reconcile 后返回完整 Manifest；
- `GET /v1/workspace/resource?link=workspace:notes/demo.md`：有界 UTF-8 text；
- `GET /v1/workspace/blob?link=workspace:assets/image.png`：完整但受 byte limit 的 blob，link/digest/size 位于 `X-TinySoul-*` headers。

### 写入

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

创建使用 `overwrite=false` 与空 digest；覆盖必须提交打开正文时的 digest。每次 mutation 都提交当前 Manifest revision。成功响应含新 record 与完整 Manifest，前端整体替换缓存。

blob 使用 `PUT /v1/workspace/blob`，query 提交 link、overwrite、expected digest/revision、retention，body 为二进制。

### Trash

- `POST /v1/workspace/trash`：link、expected digest/revision；
- `GET /v1/workspace/trash`：可恢复项；
- `POST /v1/workspace/restore`：trash ref、expected revision。

收到 `workspace.conflict` 时保留编辑草稿，重新拉取 Manifest/正文，由用户决定合并或覆盖，不能用新 digest 自动重试旧正文。

`workspace.changed` 是 Manifest cache 失效通知，来自共享 ObservationRouter，覆盖 UI mutation、Agent Action 与 capability bundle。前端比较 day/revision 后重新读取完整 Manifest，不从事件增量重建 Workspace。

## 8. 前端表面

前端只保留两个主视图：

- Chat：可信输入、Turn/Cycle/Phase/Action 与真实 MessageStack 观测；
- Workspace：Manifest、资源查看/添加/编辑/Trash/Restore。

不存在 History/Session Explorer 页面。prior Turn 的渐进查找由 Agent 在当前 Turn 调用 `core.session.inspect`，相应 call/result 和后续 MessageStack 会自然出现在 Chat 事件流中。
