# 会话（Session）视图设计

## 定位

Session 视图展示当日已完成的 Turn 历史，并支持召回任意 Turn 的 canonical trace。

## 当前功能

- **历史列表**：调用 `GET /v1/session/history` 获取当前 active day 的有界历史头部，展示每条 Turn 的状态与摘要。
- **Recall 面板**：选择一条历史后，调用 `GET /v1/session/recall?ref=<ref>&cursor=0&max_chars=8000` 分页召回不可变记录。
- 召回结果只读，不写入 Workspace 或当前事件流。

## 设计要点

- Session 是已完成 Turn 的事实源；不要把当前 WebSocket 临时事件写回 Session。
- Recall 返回的 trace 文本用于审阅，不作为可编辑 Workspace 文件处理。
- 未来可扩展：按日期切换、按关键词过滤历史、把历史 Turn 加载为 read-only 参考上下文。
