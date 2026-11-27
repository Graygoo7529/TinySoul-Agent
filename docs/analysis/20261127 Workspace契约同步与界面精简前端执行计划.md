# Workspace 契约同步与界面精简前端执行计划

- 日期：2026-11-27
- 状态：`ready`（上游后端契约已定稿并对齐 `workspace.max_context_tokens`，待后端落地后实施）
- 核对基线：`712abf02`
- 上游依赖：[Workspace 渐进披露与动作收敛后端执行计划](20261127%20Workspace渐进披露与动作收敛后端执行计划.md)、更新后的 [Endpoint Workspace 协议](../endpoint/workspace.md)
- 依据：
  - [AGENTS.md](../../AGENTS.md)（前后端协作规约：前端仅在 `visualization/` 目录下修改，通过 Endpoint 与契约文档对接）

---

## 0. 协作边界与上游契约变更总览

后端重构移除了 Workspace 的 `tags`、`description`、`insert` 及 7 个历史冗余模型动作，升级了 `WorkspaceManifest`（schema v5）、`workspace.create`、锚点 `edit`、片段 `compose` 与配置目录字段。前端计划严格在 `visualization/` 内同步上述契约、清理失效 UI 与死分支，并优化对应轨迹展示。

| 契约维度 | 后端变更内容 | 前端对接动作 |
| --- | --- | --- |
| Manifest & Record（`GET /v2/workspace/manifest` 等） | `schema_version` 升至 `5`；`WorkspaceResourceRecord` 移除 `tags` 与 `description` 字段；目录 `size=0, summary="Directory"` | 更新 `WorkspaceResourceRecord` TS 接口；移除文件树、详情页头、回收站卡片中的标签徽章、描述行及标签编辑弹窗 |
| Endpoint 写入与恢复路由 | 移除 `PUT /v2/workspace/tags`、`POST /v2/workspace/insert`；`POST /v2/workspace/edit` 的单项新增可选 `position?: "replace" \| "before" \| "after"`；`POST /v2/workspace/restore` 支持 `{ trash_ref }` 或 `{ ref }` | `WorkspaceClient` 移除 `setTags`（原本即未使用 `/insert`）；`WorkspaceTextEdit` 类型补充可选 `position`；`restore` 客户端支持 `{ trash_ref } \| { ref }` |
| 配置目录（`/v2/config` & `WorkspacePage`） | 移除 `workspace.max_read_chars` 与 `workspace.analysis.*`；新增 `workspace.max_context_tokens`、`workspace.default_expand_depth`、`workspace.max_inspect_chars`、`workspace.max_create_chars` 及 `workspace.compose.*` | 更新 `Settings -> WorkspacePage.tsx` 分组路径、移除 `pinned/tmp/important` 提示条，并同步 `i18n/catalog/zh-CN.ts` 字段译文 |
| Trace / Live Action 展示 | 移除 `workspace.list`、`read`、`insert`、`tag`、`describe`、`analyze`、`trash_list`；`workspace.write` 更名为 `workspace.create`；`edit` 含 `position`；`compose` 可含 `mode`/`fragment`/`target_range` | 更新 `ACTION_FAMILY` 注册表；清理 `analysisModel.ts`、`resultAnalysis.tsx`、`resultSearchInspect.tsx`、`resultShared.tsx` 死分支；支持 `workspace.create`、锚点 `edit` 与片段 `compose` 展示 |

进度检查项：

- [ ] F1：`api/v2` Workspace 类型与 `WorkspaceClient` 协议同步
- [ ] F2：Workspace 工作台页面清理 `tags` / `description` UI 与状态
- [ ] F3：Settings 工作区配置页与配置字段 i18n 目录同步
- [ ] F4：Trace 抽屉与聊天实时 `ActivityGlimpse` 动作注册及渲染视图精简升级
- [ ] F5：前端单测（Vitest）、类型检查（`tsc`）与构建门禁验收

---

## 1. 已核实的前端受影响文件清单

经在 `visualization/src/` 全量检索核实，受影响文件边界明确集中于以下 4 个子域：

1. **API 客户端与类型层**：
   - `visualization/src/api/v2/workspace.ts`（第 10–25、66–70 行：`WorkspaceTag`、`WorkspaceResourceRecord.description/tags`、`WorkspaceTextEdit`）
   - `visualization/src/api/v2/types.ts`（重导出检查）
   - `visualization/src/api/v2/clients/workspace.ts`（第 13、38、127–147、182–191 行：`setTags`、`edit`、`restore`）
   - `visualization/src/api/v2/clients/workspace.test.ts`（第 117、129 行 `setTags` 用例）
2. **Workspace 功能页（`features/workspace/`）**：
   - `visualization/src/features/workspace/FilePanel.tsx`（第 29、35、46、49、51、126–129、168–172、189–196、220–222 行：标签徽章、`record.description`、标签按钮与 `TagsModal`）
   - `visualization/src/features/workspace/Sidebar.tsx`（第 55 行 `TAG_TONES` 导入及树节点标签展示；第 513 行 `item.descendants.length` 保持不变）
   - `visualization/src/features/workspace/tree.ts`（第 22–27 行 `TAG_TONES` 及过滤逻辑中是否引用 `tags`/`description`）
   - `visualization/src/features/workspace/modals.tsx`（第 10、73–135 行 `KNOWN_TAGS` 与 `TagsModal`）
   - `visualization/src/features/workspace/mutations.ts`（第 19、32、177–186、300 行 `setTags`）
   - `visualization/src/i18n/messages/{zh-CN,en-US}/workspace.ts`（清理无引用的 `workspace.tags`、`workspace.tagsFailed` 等词条）
3. **Settings 配置页与配置目录词条**：
   - `visualization/src/features/settings/editors/WorkspacePage.tsx`（第 18–68 行：`max_read_chars`、` pinned/tmp/important` 说明框、`workspace.analysis.*` 分组）
   - `visualization/src/i18n/catalog/zh-CN.ts`（第 66–80 行：`workspace.*` 配置项中文标题与说明）
   - `visualization/src/i18n/messages/{zh-CN,en-US}/settings.ts`（移除 `workspaceTagsHint`、`boundsOfTheWorkspaceAnalyzeAction` 等旧词条，补充 `compose` 与上下文披露分组标题）
4. **Trace 与聊天实时动作视图（`features/trace/`、`features/chat/live/`）**：
   - `visualization/src/features/trace/model/registry.ts`（第 90–109 行 `ACTION_FAMILY`）与 `registry.test.ts`
   - `visualization/src/features/trace/model/analysisModel.ts`（第 14–29 行：仅服务于 `workspace.describe` 与 `workspace.analyze` 的提取逻辑）
   - `visualization/src/features/trace/views/resultAnalysis.tsx`（第 25–160 行：保留服务于 `workspace.compose` 与 `workspace.convert_with_*` 的结构，清理 `describe`/`analyze` 专属死分支并展示 `compose` 片段范围）
   - `visualization/src/features/trace/views/resultSearchInspect.tsx`（第 42–185、227–313 行：清理 `workspace.read`、`workspace.trash_list`、`params.tags` 死分支；为 `DiffGlimpse` / `WriteView` 补充 `edit` 的 `position: before/after` 锚点插入可读展示）
   - `visualization/src/features/trace/views/resultShared.tsx`（第 66–95 行：清理仅供 `workspace.read` / `workspace.analyze` 使用的辅助函数）
   - `visualization/src/features/chat/live/ActivityGlimpse.tsx`（第 53–58、109–117 行：适配 `edit.position` 预览，清理 `analysisGist` 空死分支）及对应测试文件（`ActivityGlimpse.test.tsx`、`LiveStatus.test.tsx`、`activityBuffer.test.ts`、`facts.test.ts`、`panels.test.tsx`、`AppShell.test.tsx`）

---

## 2. 详细改进设计

### 2.1 API v2 类型与客户端同步（F1）

1. `visualization/src/api/v2/workspace.ts`：
   - 删除 `WorkspaceTag` 类型导出（同步清理 `api/v2/types.ts` 重导出）；
   - `WorkspaceResourceRecord` 移除 `description: string` 与 `tags: WorkspaceTag[]`，保留 8 个核心字段（`ref`、`relative_path`、`kind`、`media_type`、`suffix`、`summary`、`size`、`mtime_ns`）；
   - 新增 `export type WorkspaceEditPosition = "replace" | "before" | "after";`，`WorkspaceTextEdit` 更新为 `{ old_text: string; new_text: string; position?: WorkspaceEditPosition }`；
   - 更新注释中的 schema 版本说明为 `schema v5`。
2. `visualization/src/api/v2/clients/workspace.ts`：
   - 删除 `setTags` 方法；
   - `restore` 参数类型更新为 `body: { trash_ref: string } | { ref: string }`（前端回收站列表已有 `item.ref` 即 `trash_ref`，保持直接传 `{ trash_ref: item.ref }` 即可，类型上完整对齐后端协议）。

### 2.2 Workspace 工作台界面精简（F2）

1. **目录树与过滤（`tree.ts`、`Sidebar.tsx`）**：
   - 删除 `TAG_TONES` 常量及树行上的标签渲染；文件搜索过滤仅匹配路径/名称，清晰直观；
   - 保留回收站列表的 `+{item.descendants.length}` 子项徽章与一键恢复交互。
2. **文件详情面板与弹窗（`FilePanel.tsx`、`modals.tsx`、`mutations.ts`）**：
   - `FilePanel` 头部移除 `record.tags` 徽章组、`record.description` 展示行、工具栏中的“标签”图标按钮及 `"tags"` 弹窗状态；
   - `modals.tsx` 删除 `TagsModal` 与 `KNOWN_TAGS`；
   - `mutations.ts` 删除 `setTags` 回调与返回项；
   - 清理 `i18n/messages/{zh-CN,en-US}/workspace.ts` 中对应的标签文案键。

### 2.3 Settings 工作区配置页同步（F3）

1. **`visualization/src/features/settings/editors/WorkspacePage.tsx`**：
   - 移除原本夹在中间的 `pinned` / `tmp` / `important` 静态说明横幅；
   - 重组为三个语义清晰的 `FieldSection`：
     - **位置、容量与上下文披露**：
       - `workspace.root`
       - `workspace.max_files`（`min: 1`）
       - `workspace.max_context_tokens`（`min: 128`）
       - `workspace.default_expand_depth`（`min: 1`）
       - `workspace.max_inspect_chars`（`min: 512`）
       - `workspace.max_create_chars`（`min: 1`）
       - `workspace.max_write_chars`（`min: 1`）
       - `workspace.max_image_bytes`（`min: 1`）
       - `workspace.ignore_dirs`
     - **文件监听与搜索**：
       - `workspace.watch.enabled`
       - `workspace.watch.debounce_ms`（`min: 0`）
       - `workspace.search.max_query_chars`（`min: 1`）
       - `workspace.search.max_scan_chars`（`min: 1`）
     - **长文生成（Compose）**：
       - `workspace.compose.max_instruction_chars`（`min: 1`）
       - `workspace.compose.max_reference_refs`（`min: 1`）
       - `workspace.compose.max_reference_chars`（`min: 1`）
2. **`visualization/src/i18n/catalog/zh-CN.ts`**：
   - 删除 `workspace.max_read_chars` 与 `workspace.analysis.*` 6 个旧键；
   - 新增 `workspace.max_context_tokens`、`workspace.default_expand_depth`、`workspace.max_inspect_chars`、`workspace.max_create_chars` 及 `workspace.compose.*` 的中文名称与说明（英文标题与说明直接来自后端 `infra/config/catalog/context.toml`）。

### 2.4 Trace 抽屉与实时活动卡片适配（F4）

1. **动作注册表（`features/trace/model/registry.ts`）**：
   - `workspace` 域动作映射更新为当前唯一事实集合（11 个）：
     - `"workspace.search": "search"`
     - `"workspace.inspect": "inspect"`
     - `"workspace.compose": "analysis"`
     - `"workspace.convert_with_pypdf": "analysis"`
     - `"workspace.convert_with_markitdown": "analysis"`
     - `"workspace.create": "write"`
     - `"workspace.edit": "write"`
     - `"workspace.append": "write"`
     - `"workspace.mkdir": "write"`
     - `"workspace.move": "write"`
     - `"workspace.delete": "write"`
     - `"workspace.restore": "write"`
   - 移除 `workspace.read`、`workspace.list`、`workspace.trash_list`、`workspace.analyze`、`workspace.describe`、`workspace.write`、`workspace.tag`（注：未登记 ID 在 `actionFamily()` 中天然回退 `"generic"` `GenericView`，浏览旧归档日历史记录不会崩溃）。
2. **Trace 视图精简与新语义展示**：
   - **清理死代码**：删除 `analysisModel.ts`（原文件 100% 仅判断 `workspace.describe` 与 `workspace.analyze`），清理 `resultAnalysis.tsx`、`ActivityGlimpse.tsx`、`resultShared.tsx` 中对其的引用；清理 `resultSearchInspect.tsx` 中专门针对 `workspace.read`（`requested/actual` 行号块）、`workspace.trash_list`（`trashItems` 列表）与 `params.tags` 的死分支；
   - **增强 `workspace.edit` 锚点插入预览**：在 `WriteView` 与 `ActivityGlimpse` 渲染 `params.edits` 时，若 `patch.position` 为 `"before"` 或 `"after"`，在 `DiffGlimpse` 上方显示轻量位置标签（如 `insert before anchor` / `insert after anchor`），避免把锚点插入误展示为“把 `old_text` 删除替换成 `new_text`”；
   - **增强 `workspace.compose` 片段生成展示**：在 `AnalysisView`（处理 `compose` 与 `convert`）中，若 `result` 含有 `mode` / `fragment` / `target_range` / `generated_chars`，在执行结果 FactGrid 中清晰展示定位片段、插入/替换模式、目标行区间及生成字数；
   - **适配 `workspace.restore`**：`WriteView` 已读取 `targetRef = asString(params.target_ref) ?? asString(params.ref)` 与 `trashRef = asString(params.trash_ref)`，天然兼容按原路径 `ref` 或 `trash_ref` 恢复的入参展示。

---

## 3. 分阶段实施步骤与验证方案

| 阶段 | 工作内容 | 验证重点 |
| --- | --- | --- |
| **F1：API 与类型收敛** | 修改 `api/v2/workspace.ts`、`clients/workspace.ts` 及 `workspace.test.ts` | 客户端请求路径与 payload 断言通过，无残留 `WorkspaceTag` / `setTags` 引用 |
| **F2：Workspace 与 Settings 页面更新** | 修改 `FilePanel.tsx`、`Sidebar.tsx`、`tree.ts`、`modals.tsx`、`mutations.ts`、`WorkspacePage.tsx` 及 i18n 词条文件 | 文件浏览、编辑、追加、查找替换、上传下载、移入回收站与恢复流程完整；配置页字段路径与后端 catalog 一一对应，双语词条无孤立缺漏 |
| **F3：Trace 与聊天卡片更新** | 更新 `registry.ts`、`resultAnalysis.tsx`、`resultSearchInspect.tsx`、`resultShared.tsx`、`ActivityGlimpse.tsx` | `workspace.create`、带 `position` 的 `edit`、带 `#fragment` 的 `compose`、目录/根 `inspect` 正确渲染；未登记旧动作平滑落入 `GenericView` |
| **F4：测试迁移与前端门禁** | 将前端测试夹具中借用 `workspace.read`/`list`/`write`/`analyze`/`describe` 作为通用示例的用例迁移至 `workspace.inspect`/`create`/`compose`，补充新契约用例 | 通过全部前端门禁 |

前端本地验证命令（在 `visualization/` 目录下执行）：

```powershell
pnpm test -- --run
pnpm run typecheck
pnpm run build
```

---

## 4. 合理性与前后端协同可行性分析

1. **职责边界清晰（合理）**：前端修改全部围绕后端 Endpoint 与观测事件契约收敛展开，减法大于加法（移除了 `TagsModal`、`analysisModel.ts` 及多处专属兼容渲染分支），降低了前端状态与组件维护复杂度。
2. **浏览历史归档安全性（可行）**：
   - Trace 侧通过 `actionFamily(id) ?? "generic"` 天然兜底历史 Turn 中的旧动作名称，删除专用视图分支不会导致查看历史会话白屏；
   - Workspace 侧 `WorkspaceResourceRecord` 去掉 `tags` / `description` 后，组件不再读取这两个属性，即使静态 mock 或宽松 JSON 中多出或缺少字段也不会引发运行时异常。
3. **联调顺序（顺畅）**：后端计划（P1–P5）先落地并同步 `docs/endpoint/workspace.md` 与 `/v2/config` catalog，前端计划（F1–F4）随后按文档一次性对齐并通过 Vitest + `tsc` + `build`，全程无交叉阻塞。
