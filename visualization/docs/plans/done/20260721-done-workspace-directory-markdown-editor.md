# 20260721 Done：工作区目录树 + Markdown 即时编辑器（前半部分）

> 完成日期：2026-07-19  
> 责任范围：前端（`visualization/`）  
> 原执行计划：`20260721-plan-workspace-directory-markdown-editor.md`（已归档删除；剩余需求见 `20260721-plan-workspace-remaining-backend-features.md`）

## 完成项

### 1. 目录树形结构

- 新增 `src/components/WorkspaceTree.tsx`，从 Manifest 的 `relative_path` 隐式推导目录层级。
- 支持文件夹节点折叠/展开、文件节点高亮、dirty 未保存标记、删除操作。
- `WorkspaceView` 左侧边栏由扁平列表替换为目录树。
- 影响文件：`src/components/WorkspaceTree.tsx`、`src/components/WorkspaceView.tsx`。

### 2. Markdown 分屏即时编辑器

- 新增 `src/components/MarkdownEditor.tsx`：左侧源码、右侧实时预览。
- 预览使用 `marked` 本地渲染，不写入后端；保存仍提交完整源码到 `/v1/workspace/resource`。
- 编辑器头部展示字数、大小、digest、dirty 状态与保存/丢弃按钮。
- 影响文件：`src/components/MarkdownEditor.tsx`、`src/components/WorkspaceView.tsx`。

### 3. 二进制资源友好预览

- 新增 `src/components/BinaryPreview.tsx`：图片通过 blob URL 展示，其他二进制展示元数据与下载按钮。
- `WorkspaceView` 根据资源 `kind/media_type` 自动选择 Markdown 编辑器或二进制预览。
- 影响文件：`src/components/BinaryPreview.tsx`、`src/components/WorkspaceView.tsx`。

### 4. 本地过滤搜索

- 在目录树顶部增加搜索框，按路径/文件名本地过滤。
- 匹配节点保留其祖先路径，未命中节点自动隐藏。
- 影响文件：`src/components/WorkspaceTree.tsx`、`src/components/WorkspaceView.tsx`、`src/styles/global.css`。

### 5. 样式补充

- `src/styles/global.css` 新增目录树、分屏编辑器、冲突提示条、搜索框、二进制预览等样式。

## 未纳入本次范围（依赖后端接口）

- 后端文本搜索 `/v1/workspace/search`
- AI 分析 `/v1/workspace/analyze`
- 后端摘要 `/v1/workspace/summary`
- 拖拽上传 / multipart 上传 / 缩略图预览
- 右键新建/删除/重命名目录语义

以上需求已拆分至 `20260721-plan-workspace-remaining-backend-features.md`，待后端 owner 确认 schema 后实施。

## 验证

- `pnpm exec tsc --noEmit` ✅
- `pnpm run build` ✅
- `pnpm tauri build` ✅
- `python -m pytest tests -q` ✅
- `ty check` ✅
