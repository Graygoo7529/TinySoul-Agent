# 会话（Session）视图设计

## 定位

Session 视图是已完成 Turn 的只读 Explorer。它沿 Session 拥有的 Manifest/Summary/Turn 图导航，展示确定性 Action 审计，并按需恢复 canonical trace 证据。

## 当前功能

- **历史树**：通过 `GET /v1/session/history` 加载 active root，再以 Summary ref 逐层展开 direct children。节点展示 Session-owned 有界 preview，不在前端重建 Summary 或 Action 投影。
- **Turn 概览**：选中 Turn 后，右侧 Overview 显示 preview 和 trace identity；选中 Summary 只展开子节点，不请求 trace。
- **Actions 页签**：调用 `GET /v1/session/actions` 展示全 Turn counts、pairing 状态、failure groups 和分页 occurrence details。点击 detail 的 call/result trace index 可转到精确 trace entry。
- **Trace 页签**：调用 `GET /v1/session/trace` 分页展示 canonical trace；一个已知 index 使用 `max_entries=1`，oversized entry 按后端 cursor 续读。
- 三类结果都只读，不写入 Workspace、当前对话 event store 或 Agent Background。

## 设计要点

- Endpoint 直接调用 SessionEngine 只读查询，不伪装成 Agent Action；因此 Explorer 查询不会出现在当前 Turn Interaction 中。
- active-root 续页绑定 revision。收到 `session.revision_changed` 后清空当前 root page cursor 并重新读取；不用新 revision 重放旧 cursor。
- Summary/Turn 记录不可变，但页面只缓存当前连接所需的投影。不持久化 trace/actions 到应用 store 或遥测。
- 前端不消费模型侧 `background_state`，也不通过 Session API 变更 Context SessionBackground。
