# Session Explorer Boundary Correction

> 历史记录：本方案描述的 Session Explorer 已由 `20260725-done-session-explorer-removal.md` 取代，相关 Endpoint 与前端实现均已删除。

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

## Review follow-up

状态：done

- 使用 view-local reducer/hook 持有 history path、selected Turn、actions/trace 独立查询与页轨迹；不把浏览状态放入全局业务 store。
- 每个请求携带 owner ref 与 request identity，切换 Turn/client 时取消旧请求，reducer 继续拒绝迟到响应。
- actions 与 trace 独立加载、独立失败；任一查询失败不保留上一 Turn 数据，也不阻塞另一个页签。
- history/actions/trace 提供缓存页的 Previous/Next；Summary 返回恢复父级页，root revision 变化时清空旧路径和详情后重读 root。
- 增加纯 reducer/page-trail 测试，不引入前端 Session 事实投影或 React DOM 测试框架。

## 验证

- `pnpm test` 通过：1 个 test file，6 个 reducer/page-trail tests。
- `pnpm build` 通过：TypeScript 与 Vite production build 均成功。
- 后端 OpenAPI/Endpoint 路由验收由 `docs/analysis/20260724-done-session history navigation boundary correction plan.md` 统一记录。
