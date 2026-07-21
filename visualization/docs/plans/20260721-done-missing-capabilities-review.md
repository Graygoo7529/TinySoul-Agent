# 20260721 Done：`missing-capabilities.md` 审查与归类

> 状态：已审查，部分能力已落实，部分已迁移到后续计划

## 已落实 / 已不再属于前端缺失项

### Maintenance

- **已落实**：基础 Maintenance request/decision/status API 已通过 Endpoint 暴露（`GET /v1/maintenance`、`POST /v1/maintenance`、`GET /v1/maintenance/decision`、`POST /v1/maintenance/decision`）。
- **仍待未来**：批量列出所有 pending Home changes 的列表视图。当前后端一次只暴露一个 pending decision，UI 也按单决策设计。

### Model Observability

- **已落实**：`llm.model.request/response` 事件已包含完整 message stack，满足模型级可观测需求。
- **仍待未来**：已完成 Turn 的专用 `GET /v1/llm/tasks?turn_id=...` 回放 API，可减少对有限事件缓冲的依赖。

## 已迁移到专项计划

### Workspace Search and Analysis

- 原需求：`GET /v1/workspace/search`、`GET /v1/workspace/analyze`、`GET /v1/workspace/summary`。
- 迁移至：`../plans/20260721-plan-workspace-directory-markdown-editor.md`。
- 原因：搜索、分析与 Markdown 即时编辑器共同构成下一阶段工作区体验的核心。

### Binary Resource UX

- 原需求：`POST /v1/workspace/blob/upload`（multipart 拖拽上传）、`GET /v1/workspace/preview?link=...`（图片缩略图）。
- 迁移至：`../plans/20260721-plan-workspace-directory-markdown-editor.md`。
- 原因：目录树 + 编辑器阶段需要更自然的二进制资源上传与预览。

## 已迁移到未来能力计划

原 `missing-capabilities.md` 中尚未进入近期实施计划的能力已迁移至：

- `../plans/20260721-plan-future-backend-capabilities.md`

包括：

- Home / Agent Knowledge 主动浏览（`/v1/home/catalog`、`/v1/home/resource`、`/v1/home/search`）。
- Instance Capability Metadata（`/v1/status` 返回 effective Action Catalog）。

## 备注

- 原 `missing-capabilities.md` 中 “Maintenance decisions currently expose only one pending change at a time” 的表述已过时，因为当前设计就是单决策语义；批量列表视图作为新需求另行跟踪。
- 本审查由前端视角完成；若后端接口计划调整，应同步更新本文件与对应执行计划。
