# Runtime

## Status

`GET /v1/status` 返回 protocol version、instance identity、ready、active day、turn activity、workspace revision、latest event sequence 和 event journal 摘要。它不暴露 Session REST snapshot，也不替代业务 owner 的状态。

## Input

`POST /v1/input` 接受：

```json
{"text":"analyze the workspace","command_id":"command_123","metadata":{"client_message_id":"msg_123"}}
```

返回 `202` queued receipt。文本和 Terminal 经过同一 InputCommandParser；明确控件应优先使用 control 或 maintenance endpoint。

## Control

`POST /v1/control` 接受 `stop_turn` 或 `exit_program`。它只向共享 App gateway 提交控制意图，Endpoint 不拥有退出权；关闭前端窗口不得自动发送 `exit_program`。
