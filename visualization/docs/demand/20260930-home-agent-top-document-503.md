# 需求：确认 Home 顶层 `home:agent@AGENT` 文档的读取语义（正文读取 503）

日期：2026-09-30 · 提出方：前端（visualization） · 状态：resolved · 阻塞：否

## 现象

F7-B 视觉核对（`docs/review/visual-check.md` 问题 1，证据截图 14a）中，真实后端 harness
（`test/e2e/backend_server.py`：ProjectInitializer 初始化临时项目 + standard_agent）下：

- `GET /v2/home/content` 读取 effective 目录首项 `home:agent@AGENT` 返回
  503 `resource.unavailable`（错误类型 `AgentHomeInvariantError`），curl 直连可复现；
- 同目录其余 top content（context/background、identity/identity、identity/soul、
  user/user）均 200 正常；
- Home 目录接口仍把该条目列为普通可选资源，用户首点必踩失败态。

## 需要后端确认

1. `home:agent@AGENT` 在标准项目初始化后是否应当可读？（可能是 harness 初始化内容的
   特有问题，也可能是 AGENT 顶层文档的真实读取缺陷。）
2. 若该资源本不可读，目录接口是否应如实标注或排除，而不是呈现为普通可选项？

## 结论

Home 浏览接口与 Agent 运行时读取已经分离：`view=actual` 直接读取 actual Home，
`view=effective` 只读取已经物化的 runtime/home 副本；浏览不会调用 `read_top()` 或触发
runtime copy。`home:agent@AGENT` 在 actual 目录可读，未被 Agent 读取前不出现在 effective
目录中，Agent 运行时物化后才出现。未物化 effective 内容不会以 503 或空正文伪装为可读资源。

## 前端当前行为

读取失败时如实呈现 "The document could not be read" + 原因 + Retry（不伪造内容）；
目录项展示维持后端返回原样。前端侧无需先行改动，待后端结论。
