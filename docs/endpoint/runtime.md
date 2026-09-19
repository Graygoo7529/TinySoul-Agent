# Runtime

## Status

`GET /v1/status` 返回 protocol version、instance identity、ready、active day、turn activity、latest event sequence 和 event journal 摘要。它不暴露 Session REST snapshot，也不替代业务 owner 的状态。

## Input

`POST /v1/input` 接受：

```json
{"text":"analyze the workspace","command_id":"command_123","metadata":{"client_message_id":"msg_123"}}
```

返回 `202` admission receipt。文本和 Terminal 经过同一 InputCommandParser，并调用 AgentCommands：空闲时排入有界根队列；活动 Turn（包括 Reflection）运行或等待时追加到同一个 TurnInbox。容量不足返回 `accepted=false, state=full`，不再默认所有请求均已排队。明确控件应优先使用 control 或 reflection endpoint。

当前文本入口支持 `/reply QUESTION_ID TEXT` 与 `/grant REQUEST_ID COUNT`，分别关联正在等待的问题和预算请求；普通追加文本不冒充问题回复或补额。独立结构化等待/回复路由仍属于主计划 S5。

## Control

`POST /v1/control` 接受 `stop_turn` 或 `exit_program`，经异步适配进入共享 Agent 命令门面。前者取消当前根 Turn，保留排队请求；后者关闭受理、取消当前与排队工作并退出。Endpoint 不自行终止进程；关闭前端窗口不得自动发送 `exit_program`。独立 Gateway v2 的命名统一留在主计划 S5。
