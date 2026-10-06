# Workspace 页面呈现打磨执行计划

日期：2026-10-06

状态：待逐项确认与实施

范围：`visualization/src/features/workspace/`（Sidebar.tsx、FilePanel.tsx、TextFileView.tsx、BlobView.tsx、WorkspacePage.tsx）。

**现状基线（已核实，不重做）**：文本文件已有 渲染/源码/行 三态视图与编辑时 Edit/Split/Preview 三 tab（TextFileView.tsx）；图片已有内嵌预览与下载（BlobView.tsx）；文件名过滤、内容搜索、Files/Trash 分页与恢复、manifest 直装、外部变更基线比对均已上线。本计划只做呈现打磨，不触碰这些数据层与编辑链路。

## 目标

Workspace 是当日可操作资源空间。功能底子扎实，但文件树是"清一色灰图标列表"，manifest 的语义信息（summary/description）没有呈现，tag 色彩在两处不一致，上传只有拖放。打磨后文件树可扫读、头部信息可读、操作可发现。

---

## 改进点 1：文件树类型图标与 tag 配色统一

### 现状分析

- 树中所有文件用同一个通用 File 图标（`Sidebar.tsx:372`），不按类型区分；
- tag 配色两处不一致：树行里一律灰色 Badge（目录行 `Sidebar.tsx:344`、文件行 `:381`），而 FilePanel 头部有语义三色 `TAG_TONES = { pinned: accent, tmp: yellow, library: teal }`（`FilePanel.tsx:51-55`）——同一标签两种颜色语言。

### 修改范围与内容

- 新建 `features/workspace/fileKind.ts`（或并入现有 tree.ts）：`fileKindIcon(name, mediaType): { Icon, className }`——按后缀/media_type 映射：`.md`→FileText（蓝灰）、`.py/.ts/.tsx/.js`→FileCode（蓝）、`.json/.toml/.yaml`→Braces（黄）、图片→ImageIcon（紫）、其他二进制→File（灰）、目录保持 FolderIcon；色彩用淡色 text 类，不引入新 token；
- `Sidebar.tsx` 文件行用该图标替换通用 FileIcon；目录行不变；
- tag 徽标统一：树行（目录+文件）改用 FilePanel 的 TAG_TONES 映射（提取为共享常量，如放 `workspace/tree.ts` 或新 fileKind.ts），未知 tag 灰 fallback。

### 预期效果

文件树按类型可扫读（代码蓝、文档灰、数据黄、图片紫）；tag 在树与头部同色同义（pinned 蓝、tmp 黄、library 青）。

---

## 改进点 2：树行大小与修改时间

### 现状分析

树行只有名称 + tag，无大小、无修改时间；FilePanel 头部有 `formatSize(record.size)`（`FilePanel.tsx:174`）——manifest 记录已含 size，树行未用。

### 修改范围与内容

`Sidebar.tsx` 文件行：名称后追加右对齐小字 `formatSize(size)`（10px `text-fg-faint`）；修改时间字段若 manifest 记录携带（先核实 `WorkspaceResourceRecord` 的实际字段）则以 title 显示完整时间戳，行内不常驻（避免拥挤）；无该字段则只做大小。

### 预期效果

树的每行能读出规模（`2.3 KB`），大文件一眼可辨。

---

## 改进点 3：FilePanel 头部语义化

### 现状分析

头部直接裸出 `record.media_type` 原值（`FilePanel.tsx:176`，如 `text/markdown`）；manifest 的 `description` 只出现在目录占位视图（:282），文件的 `summary` 字段未呈现。

### 修改范围与内容

`FilePanel.tsx` 头部：

- media_type 原值收进 title tooltip，原位显示可读类型词：`text/markdown`→"Markdown"、`image/png`→"PNG 图片"、`application/json`→"JSON"（映射表放 fileKind.ts，未知值显示原值）；
- `record.summary`/`description` 非空时在头部下方加一行说明文字（11px 灰字，manifest 语义首次进入界面）；
- kind、size、tags、edited 徽标保持现状。

### 预期效果

头部从协议字段变成"这是什么文件 + 它用来做什么"的说明区。

---

## 改进点 4：上传按钮显式化

### 现状分析

上传只有拖放——侧栏底部一行 10.5px 灰字提示；无点击入口（blob PUT 端点与拖放上传链路已存在）。

### 修改范围与内容

`Sidebar.tsx` 工具行（新建文件/文件夹图标按钮旁）：增加一个上传图标按钮，点击打开文件选择器，选定后走与拖放相同的 blob 上传链路（复用现有实现，重名拒绝语义不变）；归档日禁用（与现状拖放一致）。

### 预期效果

上传能力可发现，不必知道"可以拖放"这个隐藏约定。

---

## 改进点 5：目录选中态内容

### 现状分析

选中目录时中央只有一个文件夹图标 + 路径 + description，较空。

### 修改范围与内容

目录占位视图（`FilePanel.tsx:282` 附近）：补充该目录的子项统计——`N 个文件 · M 个子目录 · 共 X KB`（从 manifest 前端聚合该目录子树，无新请求）；description 保留。

### 预期效果

目录不再是空摆设，一眼读出内容规模。

---

## 改进点 6：图片点击放大

### 现状分析

BlobView 的图片内嵌预览（`BlobView.tsx`）无缩放/全屏——这是图片侧唯一真实缺口。

### 修改范围与内容

`BlobView.tsx` ImageBlob：点击图片打开一个全屏查看层（复用 `components/ui/Modal.tsx` 的遮罩与 Esc 关闭语义）：原始尺寸适配视口（`max-w/max-h`）、滚轮缩放（0.25x–4x）、拖拽平移、下载按钮保留；认证 blob URL 机制不变（media 永远不直指端点 URL）。

### 预期效果

图片可放大检查细节（截图、生成图），交互收敛在现有 Modal 语义内。

---

## 实施顺序与验收

建议顺序：1（图标+tag）→ 3（头部）→ 4（上传）→ 2（树行大小）→ 5（目录统计）→ 6（图片放大）。

验收标准：

1. 文件树按类型显示图标与淡色；tag 树内与头部同色系；
2. 树行显示大小（时间字段按 manifest 实际载荷决定有无）；
3. 头部显示可读类型词与 summary/description；media_type 原值仅在 tooltip；
4. 侧栏有上传按钮且与拖放同链路；
5. 目录选中态显示子项统计；
6. 图片可全屏缩放查看，Esc 关闭。

边界：不改 manifest 读取与直装、分页读、外部变更基线比对、串行 mutation；不做代码语法高亮与编辑器行号（单独评估项，不在本计划）；不新增后端端点。
