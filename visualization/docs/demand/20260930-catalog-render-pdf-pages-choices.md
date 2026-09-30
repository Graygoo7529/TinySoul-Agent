# 需求：`capabilities.resource.render_pdf_pages` 的 catalog choices 与代码可接受值对齐

日期：2026-09-30 · 提出方：前端（visualization） · 状态：pending · 阻塞：否

## 现象

`tinysoul/infra/config/catalog/capabilities.toml` 中
`capabilities.resource.render_pdf_pages` 声明的 enum choices 为
`never / on_no_text / always`，而 `tinysoul/plugins/capabilities/resource/config.py`
的 `PdfPageRenderMode` 实际只接受 `disabled / on_no_text`：
`never` 与 `always` 提交后会被后端 422（`config.invalid`）拒绝。

## 前端当前的临时处理

设置 → 工具与连接 → Web & Resource Fetching 页按 catalog 声明展示 choices，
依赖后端 422 反馈拒绝非法值（记录于 `docs/design/config-coverage.md` §9.1）。
用户可以选中两个必然失败的值，体验上依赖错误提示兜底。

## 需求

后端把 catalog choices 修正为代码实际接受的值（`disabled / on_no_text`，
或恢复 `always` 的实现并保留三值）。修正后前端无需改动即自动展示正确选项。
