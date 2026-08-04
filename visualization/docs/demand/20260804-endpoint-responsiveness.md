# 需求：Endpoint 在 Turn 执行期间必须保持可服务（含一次挂起实录）

日期：2026-08-04 · 提出方：前端（visualization） · 状态：pending

## 观察实录

2026-08-04 约 17:04 后端（pid 30888，port 57000）处理一个真实用户轮（输入"帮我在工作区写一个 markdown 待办清单文件"）期间：

- 进程存活，端口可建立 TCP 连接，但 `GET /v1/health`（无鉴权）5 秒无任何字节返回；
- WebSocket `/v1/events/ws` 连接后 8 秒内无任何帧（无 authenticated、无 events、无关闭帧）；
- 持续数分钟未恢复。

直接后果（用户可见）：主对话 cycle/stage 状态完全冻结、状态轮询失败、停止指令无法下达——前端在 Endpoint 停止服务时没有任何可补救的手段。

## 需求

1. **Endpoint 服务与 Program 执行解耦**：无论当前 Turn 处于哪个阶段（包括长时间 LLM 调用、workspace.write 的 LLM 组合、action 批次执行），HTTP 与 WS 都必须保持响应；`/v1/health`、`/v1/status`、`/v1/events`、`/v1/control` 的延迟应与空闲时一致。
2. **stop_turn 必须始终可下达**：控制通道是用户中断失控 Turn 的唯一手段，其可用性不应依赖当前 Turn 的执行状态。
3. 若挂起由后端内部锁/同步调用引起（本次疑似与 workspace.write 相关），建议排查该路径；如需要前端提供更细的复现步骤或事件序列，可以再补充。

## 前端侧已做的配合

- 状态轮询失败不再清空连接态、不再切走对话界面；改为顶部横幅 + 状态栏 "not responding…" 提示，保留现场持续自动重试。
- 轮询恢复后若发现 instance_id 变化（后端已重启），自动重新走实例发现流程（端口/token 可能已变）。
