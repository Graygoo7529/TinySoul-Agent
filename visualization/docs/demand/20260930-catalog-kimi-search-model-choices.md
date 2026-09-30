# 需求：`capabilities.web.search_by_kimi.model` 在 catalog 中声明 choices

日期：2026-09-30 · 提出方：前端（visualization） · 状态：resolved · 阻塞：否

## 现象

`tinysoul/plugins/capabilities/web/config.py` 只接受
`kimi-k2.5 / kimi-k2.6`（`_KIMI_SEARCH_NO_THINKING_MODELS`，no-thinking 协议约束），
其它值提交后被 422 拒绝；但 `tinysoul/infra/config/catalog/capabilities.toml`
对该字段只声明 `value_kind = "string"`，没有 choices。

## 前端当前的临时处理

设置 → 工具与连接 → Web & Resource Fetching 页把该字段硬编码为两个值的选择控件
（记录于 `docs/design/config-coverage.md` §9.5）。后端新增可用型号时，
前端需要同步改代码才能放开选择。

## 需求

后端在 catalog 中为该字段声明 choices（当前为 `kimi-k2.5 / kimi-k2.6`）。
声明后前端按 catalog 渲染选择列表，新增型号无需改前端。

## 结论

后端 catalog 已声明 `kimi-k2.5 / kimi-k2.6` choices。前端后续应直接消费该列表，移除
当前设置页的重复硬编码。
