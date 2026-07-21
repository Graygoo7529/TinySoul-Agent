# 20260721 Plan：Endpoint 前端消费一致性补全

> 状态：pending  
> 责任范围：前端（`visualization/`）  
> 后端基线：`docs/endpoint/frontend integration.md`

## 意图

基于当前已经实现的 Backend 与 Endpoint 契约，补齐 React/Tauri 前端在事件消费、权威投影恢复和敏感数据生命周期上的缺失。该计划不新增后端接口，不在前端复制 Gateway、Loop、Workspace 或 Session 业务状态机。

处理顺序固定为：

1. 后端业务 owner 提交状态并发布 Observation；
2. Endpoint 提供 authenticated REST 投影和有界 sequence replay；
3. 前端按 instance/sequence 消费通知，并回到 REST 权威投影收敛。

## 已有后端能力

- `tinysoul start` 同时装配 Terminal、AppCommandGateway、ObservationRouter 和固定 MODEL route 的 Endpoint。
- `/v1/input` 使用共享 InputCommandParser；typed control、Maintenance request 和带 `decision_id` 的 decision API 使用同一 Gateway。
- WorkspaceEngine 对 UI、Agent action、Capability bundle 和公开 reconcile 的最终提交统一发布 `workspace.changed`。
- `/v1/status`、Workspace、Session 和 Maintenance REST 提供当前 active day 的权威投影。
- 连接描述、status 与 WebSocket authenticated frame 提供 instance identity；WebSocket/HTTP event replay 在该实例内提供 sequence、`next_sequence` 与 `gap`。
- MODEL 事件提供 provider-neutral message/tool/response 结构，并只对图片、远程图片 URL、reasoning 和 provider payload 做结构化裁剪。

这些能力足以完成本计划；不得以直接读取本地目录或新增前端持久副本绕过现有边界。

## 当前缺口

### 1. Workspace 事件没有使 Manifest 自动收敛

当前 `useBackend` 接收了 `workspace.changed`，但只把它保留在 raw events 中；`WorkspaceView` 只在连接、手动刷新和 UI 自身 mutation 后更新 Manifest。Agent action 或 Capability 修改 Workspace 时，资源列表不会实时更新。

### 2. Gap 恢复没有覆盖已加载的 Session

当前 gap 恢复只读取 status、Workspace 和 Maintenance。`SessionView` 把 history 保存在组件局部状态，只在 client 变化或用户手动刷新时读取，无法随 gap 或 `session_revision` 变化收敛。

### 3. Event store 的 instance 与提交游标语义不够显式

当前 store 在 instance 变化时清空 events，并在实例内按 sequence 去重，但类型和状态中没有明确保存 event instance identity。WebSocket manager 在调用 store consumer 前更新内部 `after`，没有直接表达“成功提交后才确认游标”的语义。

### 4. MODEL 数据生命周期缺少显式保护

raw events 目前只在内存中，但前端缺少集中约束和测试，无法防止后续把完整 prompt、tool arguments 或 answer 加入 persist、console log、错误遥测或调试导出。

### 5. 统一命令入口缺少清晰的前端反馈

Chat composer 通过 `/v1/input` 提交文本，但 UI 主要按普通对话理解 receipt。该入口还可能返回 Maintenance、stop 或 exit command receipt；前端不应自行解析命令，却需要按后端 receipt/event 正确反馈，并在 `maintenance.decision_required` 时保留草稿。

## 实施方案

### Stage 1：建立单一 Endpoint 同步协调器

- 由 `useBackend` 统一处理 connection identity、event page、gap 和权威投影刷新，避免 Workspace/Session 组件各自解释 WebSocket 协议。
- 在 store 中显式记录当前 `eventInstanceId` 与 `lastCommittedSequence`；instance 改变时原子清空 raw events、Background 派生状态和权威投影 cache。
- 只有 event page 成功提交到 store 后才推进 committed sequence；同一 instance 内按 sequence 排序去重，拒绝倒退游标。
- 对同一恢复原因做 single-flight/coalescing，避免 gap、status poll 和连续 invalidation 触发并发旧响应覆盖新状态。

### Stage 2：接入 `workspace.changed` 失效通知

- 全局观察 `workspace.changed`，比较 payload `day/revision` 与当前 Manifest。
- 当 day 不同或 event revision 高于本地 revision 时合并刷新请求，调用 `GET /v1/workspace/manifest`；相同或更低 revision 不重复读取。
- UI mutation 的响应 Manifest 仍立即替换 cache；随后到达的同 revision event 必须幂等忽略。
- Manifest 刷新只更新资源投影，不覆盖 `openResource.draft`。若 affected link 是 dirty 的当前资源，标记为 external-change/conflict，要求用户重新读取、比较或放弃草稿。
- `trash`/`restore` 使 Trash 列表失效；仅在 Trash 视图已加载时刷新，避免建立第二份长期缓存。

### Stage 3：补齐 Session revision 与 gap 恢复

- 将 Session history 从组件局部副作用提升为可失效的 hook/store projection，保留 recall 正文为按需只读状态。
- 连接成功、进入 Session 视图、gap，以及 status `session_revision` 高于已加载 revision 时刷新 history。
- `turn.completed` 只作为刷新提示；最终列表以 `/v1/session/history` 为准，不从 Turn event 合成 Session record。
- gap 恢复同时刷新 status、Maintenance、Workspace，以及已经加载或当前可见的 Session；未打开 Session 时只记录 stale 标记。

### Stage 4：明确无法恢复的 event-derived 状态

- gap 后清空或标记不完整的 Turn/Cycle/Phase/LLM Task 与 Background Context 派生视图。
- 不尝试从 Session recall 伪造当前执行轨迹，也不把 retained suffix events 当作完整 Turn。
- 在收到新的 `context.background.snapshot` 前显示“上下文基线不可用”的状态；不得显示旧 instance 的 top links。
- 保留未提交 Workspace draft，并将恢复后的 Manifest 与打开资源 digest 做冲突比较。

### Stage 5：统一命令与错误反馈

- composer 继续只提交 `/v1/input`，不在 TypeScript 中复制 exit/stop/Maintenance command grammar。
- 根据 command receipt 的 `kind/state/command_id` 建立 pending command UI；以 `app.command.accepted/rejected` 和后续 Turn/work event 完成跨 Terminal/前端收敛。
- Stop 按钮继续使用 typed `/v1/control`；Maintenance 面板继续使用 typed request/decision API。
- 收到 `maintenance.decision_required` 时保留 composer 草稿并打开当前 decision；`maintenance.decision_stale` 时关闭旧对话框并刷新 Maintenance。
- `exit_program` receipt 后进入后端正在退出状态，等待连接关闭，不把它显示为普通 User Turn。

### Stage 6：收紧 MODEL 数据边界和 HTTP client

- raw MODEL events、message stack、tool arguments 和 answer 只保存在当前 instance 的内存 store；Zustand `partialize` 继续只持久化 project root。
- 禁止把 event payload 写入 console、错误上报、localStorage 或 URL；错误日志只记录稳定 code、event name 和 sequence。
- UI 明确区分“结构化裁剪”与“内容脱敏”，不得向用户暗示完整 prompt 已移除业务敏感信息。
- JSON request、blob request 和 GET 分别使用正确 Content-Type；由浏览器生成准确 Content-Length，不手工伪造该 header。

## 测试链路

- 为 store/event coordinator 增加前端单元测试：跨 instance sequence 重置、重复 page 幂等、乱序拒绝、提交后游标推进和 gap 清理。
- 使用 mocked TinySoulClient 验证连续 `workspace.changed` 只触发合并后的 Manifest 刷新，UI response 与 event 同 revision 不重复读取。
- 验证 Agent mutation 刷新 Manifest 时 dirty draft 不丢失，并进入 external-change 状态。
- 验证 gap 恢复 status/Maintenance/Workspace/已加载 Session，同时把 Background/执行轨迹标记为不完整。
- 验证 Session revision 增长刷新 history，recall 仍按需读取。
- 验证 `maintenance.decision_required/stale` 保留输入并刷新对话框；验证 exit receipt 不生成普通聊天消息。
- 增加持久化白名单测试，确保 MODEL payload 不进入 Zustand persisted state。
- 运行 TypeScript test、`npm run build` 和 `cargo check`；与真实 `tinysoul start --mode normal` 做一次 Terminal/前端共存 smoke。

## 验收标准

- Agent 或 Capability 成功修改 Workspace 后，前端无需切换页面或手动刷新即可看到新 Manifest。
- 外部变更不会覆盖 dirty editor；用户能够识别并处理 digest/revision 冲突。
- Endpoint restart 不会混合两个 instance 的事件；断线续传不跳过已接收但未提交的 page。
- gap 后所有可恢复投影回到 REST 权威状态，不可恢复的临时轨迹被明确标记，不伪造连续性。
- Session history 随 revision 收敛，不依赖组件重新挂载。
- Terminal 和前端命令都由同一 Gateway 处理，前端根据 receipt/Observation 展示结果而不复制命令解析器。
- MODEL 全量事件仍可用于分层展示，但不会被持久化或记录到日志。

## 预计改动位置

- `visualization/src/hooks/useBackend.ts`
- `visualization/src/api/events.ts`
- `visualization/src/store/appStore.ts`
- `visualization/src/hooks/useWorkspace.ts`
- `visualization/src/components/WorkspaceView.tsx`
- `visualization/src/components/SessionView.tsx`
- `visualization/src/components/ChatView.tsx`
- `visualization/src/api/tinysoul.ts`
- `visualization/src/types.ts`
- 前端 store/hook/API 对应测试文件

## 非目标

- 不修改 Python Backend 或新增 Endpoint route。
- 不增加 Home/Memory 任意文件访问能力。
- 不持久化 Observation replay 或建立前端 Session/Workspace 事实库。
- 不从事件重建 Manifest、Session record 或 Loop 控制状态。
- 不处理工作区目录树、Markdown 编辑器、search/analyze/upload/preview；这些继续由其它专项计划管理。
