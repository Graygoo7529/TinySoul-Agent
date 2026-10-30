# Workspace 页面呈现打磨执行计划

日期：2026-10-06；2026-10-27 按最新 manifest 与标签语义复核

状态：待逐项确认与实施

范围：`visualization/src/features/workspace/`（Sidebar、FilePanel、TextFileView、BlobView、tree/共享呈现helper）及测试。

**现有能力不重做**：文本渲染/源码/行视图、编辑时 Edit/Split/Preview、图片内嵌预览与下载、过滤/搜索、Files/Trash、manifest 直装、外部变更基线比对和串行 mutation 保持。只打磨呈现与操作可发现性。

## 改进点 1：文件类型图标与 tag 配色统一

状态：done（2026-10-30）

### 现状与修改

文件树统一使用灰色 File 图标；树内 tag 全灰，FilePanel 头部使用语义色。新增共享 fileKind 映射（可放现有 tree.ts，避免无必要新文件）：

- Markdown → FileText；代码 → FileCode；JSON/TOML/YAML → Braces；图片 → ImageIcon；其它二进制 → File；目录仍 Folder；
- 颜色使用现有淡色 text/token，不新增一套色板；
- TAG_TONES 提取共享常量：**pinned=accent、tmp=yellow、important=teal**，未知 tag 灰色。当前正确标签是 important，不是旧 library。

实施验证：tree.ts 新增 fileKindIcon（media_type image/* 判图片，suffix 小写归一后映射 .md/.markdown→FileText text-info、常见代码后缀→FileCode text-success、.json/.jsonc/.toml/.yaml/.yml→Braces text-warning，未知灰色 File；着色图标 opacity-75 保持淡色）与共享 TAG_TONES；Sidebar 文件行接入类型图标、文件与目录行 tag 用同一映射并加 opacity-80 减淡；FilePanel 删除本地 TAG_TONES 改导入。测试覆盖 fileKindIcon 各族、大小写与未知兜底，及树行图标/徽章色调。99 个测试文件、866 个用例，TypeScript 检查与生产构建通过。

### 预期效果

文件类型可扫读，同一 tag 在树与头部同色同义，不引入第四种标签。

## 改进点 2：树行大小与修改时间

- 文件行右侧以 10px 淡色显示 `formatSize(record.size)`，长名称优先截断，标签过多时允许隐藏次要信息而不是撑破树；
- manifest 已提供 `mtime_ns`，在 title 中显示完整修改时间（按 ns → ms 转换），行内不常驻第二时间列；
- dirty 点和 tags 语义不变。

预期效果：大文件与文件新旧可判断，树仍保持紧凑。

## 改进点 3：FilePanel 头部语义化

状态：done（2026-10-30）

- media_type 原值收进 title，原位显示可读类型词（Markdown、PNG 图片、JSON 等），未知类型保留原值；
- ~~`record.summary` 与 `record.description` 并列考虑~~（2026-10-30 修订）：核对后端后确认 summary 由 reconcile 自动生成（`"{类型label}, {size} bytes"`），与头部类型词和大小完全重复，不上屏；说明行只显示 description（set_description 写入的真实用途说明，非空时一行截断 + 悬浮全文）；
- kind、size、tags、edited、归档只读和外部变更提示保持。

实施验证：tree.ts 新增 mediaTypeLabel（与后端 classification 词汇同源；目录/二进制/办公文档/图片均有词，未知原值，空值不显示）；FilePanel 头部原位替换为可读词（点线下划线 + title 原值）并增加 description 行；目录占位不再追加 description，BlobView 非图片卡删除重复 Description 行，图片内嵌条复用同一映射。测试覆盖映射各族/未知/空值、头部类型词与 description 行、目录去重。99 个测试文件、869 个用例，TypeScript 检查与生产构建通过。

预期效果：头部从协议字段变成“文件类型 + 用途说明”，不新增请求。

## 改进点 4：上传按钮显式化

- 在新建文件/文件夹旁增加上传图标按钮，点击打开文件选择器；
- 选定文件复用拖放的 `mutations.upload(files, targetDir)`，重名拒绝、归档禁用和 busy 语义一致；
- 保留拖放提示，不建立第二条上传流程。

预期效果：上传可发现，点击与拖放结果一致。

## 改进点 5：目录选中态内容

- 目录占位视图增加直接/子树统计：`N 个文件 · M 个子目录 · 共 X KB`，从当前已加载 manifest 聚合，不新增请求；
- description 保留；统计只描述 manifest 覆盖范围，不声称扫描了 manifest 之外的磁盘。

预期效果：目录不再只是空图标，能够表达内容规模。

## 改进点 6：图片点击放大

- 点击图片打开全屏查看层，复用 Modal 遮罩与 Esc 关闭；
- 原图适配视口，支持 0.25x–4x 滚轮缩放与拖拽平移，提供复位和下载；
- 鉴权 Blob/Object URL 生命周期不变，不让 `<img>` 直接指向需鉴权端点。

预期效果：截图和生成图可检查细节，操作收敛在现有 Modal 语义内。

## 实施顺序与验收

顺序：1 → 3 → 4 → 2 → 5 → 6。

- 树按类型显示图标，pinned/tmp/important 与头部一致；
- 大小、mtime、summary/description 均来自真实 manifest，不错误换算 mtime_ns；
- 上传复用拖放链路；目录统计不越过 manifest；
- 图片可放大、平移、复位、下载和 Esc 关闭；
- `npx tsc --noEmit` 与 `npx vitest run` 通过。

边界：不改 manifest 读取/直装、分页、外部变更比对、串行 mutation；不做代码语法高亮与编辑器行号；不新增后端端点。
