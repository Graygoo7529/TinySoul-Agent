# 工作区（Workspace）视图设计

## 定位

Workspace 视图让使用者浏览、创建、编辑和恢复当日工作区中的资源。前端不直接操作本地文件，所有变更都通过 Endpoint REST 提交，由后端 WorkspaceEngine 执行 revision/digest CAS 校验。

## 当前布局

- **左侧边栏**：
  - Workspace 摘要（文件总数、总大小、按 kind 统计）。
  - Files / Trash 标签切换。
  - 资源列表，点击打开编辑器。
- **右侧主区域**：
  - 编辑器标题栏显示 link、size、digest、modified 状态。
  - 纯文本 textarea 用于编辑 UTF-8 text 资源。
  - 未选择资源时显示 empty state。

## 资源操作

- **创建**：通过 modal 输入 `workspace:<path>` 与初始内容；创建时 `overwrite=false`、`expected_digest=""`。
- **读取**：`GET /v1/workspace/resource?link=...`，后端返回有界 UTF-8 text、truncated、size、digest。
- **保存**：`PUT /v1/workspace/resource`，提交当前 digest、expected revision、overwrite=true。
- **删除**：`POST /v1/workspace/trash`，把资源移入可恢复 Trash。
- **恢复**：`POST /v1/workspace/restore`，按 trash_ref 恢复。
- **二进制**：`GET /v1/workspace/blob` 读取，`PUT /v1/workspace/blob` 覆盖。

## 冲突处理

- 收到 `workspace.conflict` 时保留用户编辑缓冲，重新拉取 Manifest/正文，由用户决定合并或覆盖。
- 不能自动用新 digest 重试旧正文。

## 下一步演进方向

当前已实现目录树 + Markdown 分屏即时编辑器 + 二进制资源预览。前端纯实现部分见 `../plans/20260721-done-workspace-directory-markdown-editor.md`。

仍需后端接口支持的能力见 `../plans/20260721-plan-workspace-remaining-backend-features.md`：

- 工作区全文搜索与 AI 分析入口。
- 后端摘要接口 `/v1/workspace/summary`。
- 拖拽上传二进制资源（multipart 上传）。
- 图片缩略图预览 `/v1/workspace/preview`。
- 右键目录操作语义（新建/删除/重命名文件夹）。
