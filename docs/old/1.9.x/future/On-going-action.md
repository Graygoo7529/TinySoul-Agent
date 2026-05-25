需要让 `query_loop.py` 支持 `is_ongoing=True` 的 Action，并在适当的时候调用 `remove_ongoing_action`。这可能需要为 ONGOING Action 增加一个 `stop` 或 `check_status` 的回调机制。

ONGOING 运行时配置：终止命令、最大时长
ONGOING 在 loop 结束后自动地回收和销毁
