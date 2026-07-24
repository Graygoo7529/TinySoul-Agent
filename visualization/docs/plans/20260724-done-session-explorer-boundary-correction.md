# Session Explorer Boundary Correction

状态：done

日期：2026-07-24

## 意图

将前端 Session 视图从混合 recall 面板收敛为与后端所有权一致的只读 Explorer：history 只负责 Session 图导航，actions 只负责 Turn 审计，trace 只负责 canonical 证据。Endpoint 查询不伪装成 Agent Action，前端不从事件或 trace 重建 Session 事实。

## 实施

- `TinySoulClient` 提供 `sessionHistory`、`sessionActions`、`sessionTrace`，删除旧 `sessionRecall`。
- TypeScript 类型分离 history page、Action projection 和 trace page，root cursor 显式携带可选 revision。
- SessionView 提供 root/Summary/Turn 树导航、Overview/Actions/Trace 页签、Action detail 分页和 trace-index 精确定位。
- 前端不消费 `background_state`，不聚合 Summary 子节点 Action counts，不持久化 Session payload。
- 对话 WebSocket/Observation 与 Session REST 保持分离；Explorer 查询不写入当前 Interaction。

## 验证

- `npm.cmd run build` 通过。
- 后端 OpenAPI/Endpoint 路由验收由 `docs/analysis/20260724-done-session history navigation boundary correction plan.md` 统一记录。
