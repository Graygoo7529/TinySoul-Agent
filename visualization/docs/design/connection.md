# 前端连接与生命周期

前端只连接已经运行的 Endpoint。浏览器调试时可以直接填写 `127.0.0.1:1430`；存在隧道或转发时，只替换连接地址，不改变 v2 数据契约。

## 生命周期

`src/app/connection.ts` 是唯一连接协调入口：它读取 v2 health/status，建立带 token 的 Observation WebSocket，维护 connection epoch，并在重连、generation 变化或 replay gap 后通过 owner reads 刷新页面投影。WebSocket 事件只作为失效和活动提示，不在前端重建 Session、Turn 或 Context 事实。

连接断开不会停止后端 Agent，也不会取消 Turn。前端显示连接状态并按有界退避重新连接；恢复后重新读取 status、当前 Turn、当天 Session 目录和必要的 Context。

## v2 入口

- `/v2/health`、`/v2/status`：连接握手和运行状态。
- `/v2/events`、`/v2/events/ws`：有限回放和 Observation 流。
- `/v2/turns/*`：当前 Turn 的状态、交互和 Context 投影。
- `/v2/session/*`、`/v2/days`：Session 地图、当天连续会话和历史日。
- `/v2/config/*`、`/v2/workspace/*`、`/v2/home/*`、`/v2/memory/*`：各 owner 的页面服务。

协议类型和错误映射集中在 `src/api/v2/`。页面不得读取 `runtime/`、`home/` 或 `memory/` 文件，也不得维护第二套连接或执行状态机。

Observation 订阅 `mode=model` 以取得真实思考摘要，活动缓冲只保留展示所需部分；完整 MessageStack 由模型详情定向读取。事件归属共用 scope 解析，不能依赖不存在的顶层 `turn_id`。读取窗口的上界取已知 status 与 WebSocket cursor 的较大值。
