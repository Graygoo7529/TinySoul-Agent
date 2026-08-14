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
  "latest_event_sequence": 121,
  "event_journal": {
    "enabled": true,
    "degraded": false,
    "oldest_sequence": 1,
    "latest_sequence": 121
  }
}
```

status 不暴露 Session revision。`event_journal` 是只读摘要（是否启用、是否写失败降级、保留的 sequence 范围），不参与控制流。`ready=false` 时继续等待，不得访问本地业务目录绕过 Daily 初始化。

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

- `GET /v1/maintenance`：返回 Home pending 计数和持久提示单中的全部 Memory dates；展示层把 Home pending 计为一个聚合任务，每个 Memory date 计为一个任务；
- `POST /v1/maintenance`：提交 `kind=daily|home|memory`、command id 与 metadata；Memory 必须提供 `target_day`，协议不包含 rebuild flag。

Terminal 与前端可同时提交 Maintenance request；请求按进入 Program queue 的顺序串行执行，手动与 scheduler request 走同一 MaintenanceEngine 流程。Daily 只自动处理昨日 Memory，更早日期保留供前端逐日提交。前端首次连接后先读取 availability，如有待办则自动打开一次非阻塞 Maintenance 提示；收到 `program.maintenance.available`、`maintenance.started`、`maintenance.completed` 或 `maintenance.availability.changed` 时只重新读取 `GET /v1/maintenance`，不从事件 payload 建立第二份状态，也不反复自动打开面板。

## 6. Observation 事件

HTTP replay：

前端与 Terminal-owned 后端成对重启是正式重启验收路径；新前端必须重新解析 App 发布的 lease，不得永久复用旧端口或 token。同一前端进程内的失败重发现也只能由一个连接编排 owner 驱动；待验证 lease 不覆盖 active connection identity，新 lease 通过身份与 `ready` 校验后才原子替换 Client/WS。事件历史只保留为 compact observation projection，已结束 Turn 的 MODEL payload 可骨架化，用户输入来自 `app.command.accepted.payload.text`，不依赖本地持久化 echo。

```text
GET /v1/events?after=0&mode=model&limit=200
```

响应含 `events`、`next_sequence`、`gap`。协议字段不变。服务端以内存 buffer 为热缓存；`after` 早于内存窗口时从 Endpoint 事件 Journal（`runtime/endpoint/events/` 分段 NDJSON）深读；超出 journal 保留范围才 `gap=true`。单页可按字节预算提前收页（默认约 1MB），因此即便 `limit` 较大也可能返回更少事件——以 `next_sequence` 继续分页。

连接 / 重连 / `instance_id` 变化后，前端先读取 status 并捕获 `latest_event_sequence` 快照，再从 `after=0` 以单调 cursor 分页恢复到该目标，然后将 WebSocket 挂到实际已恢复的最新 sequence。前端不得设置静默的最大页数/事件数，也不得把未完成 REST 回放标记为恢复成功；不得依赖已删除的 Session REST。

WebSocket 地址为 `/v1/events/ws`，首帧：

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

`gap=true` 时清理 event-derived live Turn/Cycle/Phase/Task 视图，并重新从 `after=0` 分页重放可保留的 journal/内存事件，同时重新读取 status、Maintenance 和 Workspace Manifest。不要调用已删除的 Session REST 补造模型历史；对 journal 已淘汰的前缀标记轨迹不完整。未提交 Workspace 编辑草稿不得因 gap 被清除。

`stop_turn` 经 Gateway 立即置位 Turn 取消令牌并放弃在途 LLM 等待；前端应在 receipt 后展示 stopping 态，并等待 `turn.stopped` / `turn.failed` / 其它终端 NORMAL 事件闭合。长 Turn 期间 `/v1/health`、`/v1/status`、`/v1/control` 与 WS 心跳应保持可服务。

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

## 9. Settings 与配置目录

- `GET /v1/config`：当前 activity、sources、stored/effective fields 与 Generation 状态；
- `GET /v1/config/catalog`：Infra 集中维护的 surfaces、field groups、collections、collection identity、
  merged/document field title/description、value kind、importance、choices、references 与 credential reference；
  `rules.llm.adapters` 是 LLM 提供的机器规则投影，每项包含 `id`、`api_style`、
  `common_option_keys`、`common_options` 和 `protocols`，protocol 项包含 `id`、
  `option_keys` 与 option value specs。规则只用于计算 adapter/protocol 可用字段，
  标题、说明和控件语义仍以 Infra field descriptors 为准；
- `GET /v1/actions/catalog`：当前 Generation 的 configured User Domain/Action、模型可见语义、
  effective runtime、availability、只读 contract 和 project document source binding；
- `PATCH /v1/config`：一次 source-aware operations 数组，返回时已完成持久化与当前
  Generation 激活。

前端必须把 ConfigStatus 作为唯一配置事实，catalog 只用于组织和解释；不得复制业务默认值或按
dotted path 猜字段说明。Provider、Model、Task Chain 通过 collection root 动态枚举，创建和删除
使用完整 root mutation；删除跨多个 project TOML source 的对象时，前端应为每个贡献该 subtree 的
source 提交同一 root 的 delete mutation。Task Chain models 与 `action.llm_action.overrides` 写回完整数组；Action
picker 只展示 `/v1/actions/catalog` 中 `available=true && backend.kind=llm_action` 的 Action。

Action Catalog 页面按 Domain/Action 使用响应中的 `source.source_id` 和 `editable_paths` 建立
mutation；Domain/Action 字段说明按 `document_set=action.catalog + document_kind + local path` 从
Infra document descriptors 获取。description、selection hint、semantic 和 timeout 可写；
`execution.wait` 另外暴露 Tool Schema 中 minimum/default/maximum 三个精确 local path。完整 schema、
parallel policy、hooks、trace mode 与 backend 只读。删除 Action 专用 timeout 表示恢复
`llm_action default -> domain default -> none` 的继承链。

任意 User/Maintenance Turn 或配置激活期间，三个 GET 仍可读取，所有 TOML/dotenv 控件禁用；
PATCH 返回 `409 config.activation_unavailable`。进程环境不枚举、不编辑；dotenv credential 值只
由 credential reference 与 `.env` source 组合展示。
