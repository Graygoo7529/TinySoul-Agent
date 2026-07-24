# 会话（Session）视图设计

## 定位

Session 视图是已完成 Turn 的只读 Explorer。它沿 Session 拥有的 Manifest/Summary/Turn 图导航，展示确定性 Action 审计，并按需恢复 canonical trace 证据。

## 当前功能

- **历史树**：通过 `GET /v1/session/history` 加载 active root，再以 Summary ref 逐层展开 direct children。节点展示 Session-owned 有界 preview，不在前端重建 Summary 或 Action 投影。
- **Turn 概览**：选中 Turn 后，右侧 Overview 显示 preview 和 trace identity；选中 Summary 只展开子节点，不请求 trace。
- **Actions 页签**：调用 `GET /v1/session/actions` 展示全 Turn counts、pairing 状态、failure groups 和分页 occurrence details。点击 detail 的 call/result trace index 可转到精确 trace entry；Actions 查询独立加载和失败。
- **Trace 页签**：调用 `GET /v1/session/trace` 分页展示 canonical trace；一个已知 index 使用 `max_entries=1`，oversized entry 按后端 cursor 续读；Trace 查询不受 Actions 失败影响。
- **回退导航**：history、actions 和 trace 都保存当前 Explorer 会话内最多 32 页的路径缓存，支持 Previous/Next；从 Summary 返回时直接恢复父级原页面，不重新发起父级查询。
- 三类结果都只读，不写入 Workspace、当前对话 event store 或 Agent Background。

## 设计要点

- Endpoint 直接调用 SessionEngine 只读查询，不伪装成 Agent Action；因此 Explorer 查询不会出现在当前 Turn Interaction 中。
- Explorer 状态只存在于 SessionView 的 reducer/hook，不进入全局业务 store。history level、selected Turn、actions 与 trace 分别持有 owner ref、request identity、loading/error 和页面轨迹。
- 切换 Turn 或 client 时通过 `AbortController` 取消旧请求；reducer 仍同时校验 ref 和 request identity，保证无法取消或已经到达的迟到响应不能写入当前 Turn。Actions 与 Trace 分别收敛，不使用 `Promise.all` 耦合成功或失败。
- active-root 续页绑定 revision。收到 `session.revision_changed` 后原子清空 root 路径、当前 Turn 和全部详情页，再读取新 root；不用新 revision 重放旧 cursor。
- Summary/Turn 记录不可变，但页面只缓存当前连接所需的有界投影。不持久化 trace/actions 到应用 store 或遥测。
- 前端不消费模型侧 `background_state`，也不通过 Session API 变更 Context SessionBackground。
