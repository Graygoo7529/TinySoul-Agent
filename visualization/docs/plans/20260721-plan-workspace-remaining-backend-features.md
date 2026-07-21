# 20260721 Plan：工作区目录树 + Markdown 编辑器的后端依赖项

> 状态：计划/待后端接口确认  
> 责任范围：前端（`visualization/`）；所列接口需后端 owner 评估后提供。  
> 已完成前置：见 `20260721-done-workspace-directory-markdown-editor.md`

本文档承接 `20260721-done-workspace-directory-markdown-editor.md` 中已完成的纯前端部分。以下功能需要后端暴露新接口或确认语义后才能继续实施。

## 1. Workspace 文本搜索

- **目标**：在目录树顶部搜索框支持按内容全文搜索，而不仅是本地路径过滤。
- **依赖接口**：`GET /v1/workspace/search`
  - 参数：`link`（可选前缀）、`q`（查询文本）、`scope`（file/directory/workspace）。
  - 返回：匹配片段列表（含 link、line、snippet）。
- **后端现状**：后端有 `workspace.search_text` action，但 Endpoint 尚未暴露。

## 2. Workspace AI 分析

- **目标**：支持多选资源后触发受控 AI 分析，并在只读面板展示结果。
- **依赖接口**：`GET/POST /v1/workspace/analyze`
  - 参数：`reference_links`、`intent`、可选 `max_chars`。
  - 返回：有界分析文本。
- **后端现状**：后端有 `workspace.analyze` action，但 Endpoint 尚未暴露。

## 3. Workspace 摘要接口

- **目标**：用后端提供的紧凑摘要替换前端对完整 Manifest 的自行统计。
- **依赖接口**：`GET /v1/workspace/summary`
  - 返回：按 kind/retention 的计数、总大小、最近更新等。
- **后端现状**：当前未暴露，前端仍在本地计算。

## 4. 二进制拖拽上传

- **目标**：支持拖拽图片/PDF 等到目录树，自动创建 workspace 资源。
- **依赖接口**：`POST /v1/workspace/blob/upload`（multipart/form-data）
  - 简化当前 `PUT /v1/workspace/blob` + octet-stream 的手动构造体验。
  - 需确认前端能否指定 `retention` 与 `media_type`，还是统一使用后端默认值。
- **后端现状**：Endpoint 当前仅支持 `PUT /v1/workspace/blob`。

## 5. 图片缩略图预览

- **目标**：为图片资源提供轻量缩略图，减少前端加载完整 blob 的开销。
- **依赖接口**：`GET /v1/workspace/preview?link=...`
  - 返回：缩略图 blob。
- **后端现状**：新增需求。

## 6. 右键目录操作语义

- **新建文件夹**：后端是否支持显式 directory 概念？当前目录由文件路径隐式推导。
- **删除文件夹**：是否递归删除其下全部资源？
- **重命名/移动**：是否需要新 API，还是通过 `write/patch` 间接实现？

## 评估建议

- 优先暴露 `/v1/workspace/search` 与 `/v1/workspace/analyze`，可立即提升工作区可用性。
- `/v1/workspace/summary` 与 `/v1/workspace/preview` 属于性能/体验优化，可在搜索/分析稳定后评估。
- multipart 上传与目录操作语义需在确认后端文件系统抽象后设计 schema。
- 实施前需与后端 owner 确认：
  - 各接口 schema、鉴权、size limit、错误码；
  - 搜索是否包含二进制转换后的 Markdown（如 PDF 转换结果）；
  - 预览是否对 `retention=ephemeral/turn` 资源同样有效。
