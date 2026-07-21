# 20260721 Plan：工作区目录树 + Markdown 即时编辑器

> 状态：计划阶段，待讨论确认后实施  
> 责任范围：前端（`visualization/`）；后端接口需求在文中注明。

## 目标

把当前 Workspace 视图的“扁平资源列表 + 简单文本框”升级为：

1. **目录树形结构**：按路径层级展示 workspace 资源，支持折叠/展开目录。
2. **Markdown 即时编辑器**：为 `markdown` 资源提供同步滚动或分屏的实时预览编辑体验。
3. **快速搜索与分析入口**：在工作区内搜索文本、对选定资源运行受控分析。
4. **二进制资源友好上传**：支持拖拽上传图片、PDF 等二进制文件并即时看到缩略图/占位。

## 前端设计

### 目录树

- 左侧边栏由“扁平列表”改为“可折叠树”。
- 节点类型：文件夹节点、文本/脚本/markdown 文件节点、二进制节点。
- 点击文件节点在右侧打开编辑器；点击文件夹节点折叠/展开。
- 支持右键菜单（新建文件/文件夹、删除、重命名）。
- 当前选中节点高亮；dirty 文件显示未保存标记。

### Markdown 即时编辑器

- 对 `kind=markdown` 或 `media_type=text/markdown` 的资源使用 Markdown 编辑器。
- 方案 A：左侧源码、右侧实时预览的分屏布局。
- 方案 B：类 Notion 的所见即所得编辑器（较重，可能引入复杂依赖）。
- **建议先采用方案 A**：保持源码可控，预览只读，与后端 digest CAS 兼容。
- 预览渲染仅在前端本地完成，不写入后端；保存时仍提交完整源码。
- 编辑器需展示当前字数、最后保存 digest、revision。

### 搜索与分析

- 在目录树顶部增加搜索框。
- 搜索模式：
  - 按 link/path 前缀过滤。
  - 按内容搜索（需后端支持 `workspace.search_text`）。
- 支持多选资源后触发 `workspace.analyze`（受控 AI 分析）。
- 分析结果以 read-only 面板展示，不直接修改资源。

### 二进制资源

- 图片资源：尝试从后端获取缩略图或完整 blob，在前端以 `<img>` 展示。
- 非图片二进制：展示大小、media type、digest、下载按钮。
- 支持拖拽文件到目录树上传；上传后刷新 Manifest。

## 需要后端支持的接口

| 接口 | 方法 | 说明 | 是否已有后端能力 |
|---|---|---|---|
| `/v1/workspace/search` | GET | `link`、`q`、`scope` 参数；返回匹配片段 | 后端有 `workspace.search_text` action，但 Endpoint 尚未暴露 |
| `/v1/workspace/analyze` | GET/POST | 提交 `reference_links` 与 `intent`，返回有界分析结果 | 后端有 `workspace.analyze` action，但 Endpoint 尚未暴露 |
| `/v1/workspace/summary` | GET | 返回 compact 摘要（counts by kind/retention/total size） | 当前前端通过完整 Manifest 自行计算；未来可由后端提供 |
| `/v1/workspace/blob/upload` | POST | `multipart/form-data` 上传，简化拖拽体验 | Endpoint 当前只支持 `PUT /v1/workspace/blob` + octet-stream |
| `/v1/workspace/preview` | GET | `link` 参数；返回缩略图 blob，用于图片资源 | 新增需求 |

> 注：以上接口需求属于 **Endpoint 协议扩展**，需要后端 owner 确认 schema、size limit、鉴权和错误码后再实施前端。

## 设计语义待用户确认

实施前请与项目维护者确认以下问题：

1. **目录节点是否为真实资源？**
   - Workspace Manifest 当前只记录文件资源，没有独立的“目录”记录。
   - 前端可以从 link 路径推导目录树，但新建文件夹时如何表达？是通过写入一个带路径的文件隐式创建目录，还是需要后端提供显式的 directory 概念？
2. **Markdown 预览与源码的关系**
   - 是否允许所见即所得编辑？还是只读预览 + 源码编辑？
   - 预览渲染是否应支持 Workspace 内部图片/链接的相对路径解析？
3. **自动保存 vs 手动保存**
   - 当前为手动保存（CAS 校验）。切换为 Markdown 即时编辑器后，是否保持手动保存？
   - 若引入自动保存，如何处理 revision/digest 冲突？
4. **搜索范围与权限**
   - `workspace.search_text` 可以搜索单个文件、目录前缀或整个 Workspace；前端默认搜索范围是什么？
   - 是否允许搜索二进制转换后的 Markdown（如 PDF 转换结果）？
5. **二进制上传的 retention/media_type**
   - 拖拽上传时前端能否指定 retention？还是统一使用后端默认值？
   - 图片预览是否对 retention=ephemeral/turn 的资源同样有效？
6. **右键菜单操作的边界**
   - 删除文件夹是否递归删除其下全部资源？还是后端只支持逐个文件删除？
   - 重命名/移动资源是否需要后端新增 API，还是通过 `write/patch` 间接实现？

## 推荐实施顺序

1. **目录树组件**：纯前端从 Manifest 推导目录结构，保留现有编辑能力。
2. **Markdown 分屏编辑器**：替换当前 textarea，预览使用轻量 Markdown 渲染库。
3. **搜索框（link/path 过滤）**：不依赖后端，先实现本地过滤。
4. **后端接口对齐**：与后端 owner 确认并暴露 `/v1/workspace/search`、`/v1/workspace/analyze`、`/v1/workspace/summary`。
5. **拖拽上传与二进制预览**：后端暴露 multipart upload 与 preview 后前端接入。
6. **右键新建/删除/重命名**：确认目录语义后实现。

## 前端相关文件（预计改动）

- `visualization/src/components/WorkspaceView.tsx` — 整体布局重构。
- 新增 `WorkspaceTree.tsx`、`MarkdownEditor.tsx`、`WorkspaceSearchPanel.tsx`。
- `visualization/src/api/tinysoul.ts` — 新增 search/analyze/summary/upload/preview 方法。
- `visualization/src/types.ts` — 补充新接口类型。
- `visualization/src/styles/global.css` — 目录树与编辑器样式。
