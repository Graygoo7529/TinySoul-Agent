# visualization Workspace 文件预览增强执行计划

**状态**：待执行  
**创建日期**：2026-10-05  
**修订日期**：2026-10-06  
**预计工作量**：2 个工作日  
**负责人**：Claude Opus 5.5

---

## 执行计划总览

本计划旨在增强 Workspace 文件预览功能，支持 Markdown 实时预览、图片预览和大文件虚拟滚动。

**核心原则**：
- 复用现有架构（WorkspaceView、FileTree、TextFileView）
- 只添加真实缺失的功能（Markdown 预览、图片预览）
- 性能优先（虚拟滚动支持大文件）
- 保持设计一致性

---

## 背景分析

### 当前 Workspace 架构

**目录结构**：
```
visualization/src/features/workspace/
├── WorkspaceView.tsx        # ✅ 主视图（左文件树/右预览）
├── FileTree.tsx             # ✅ 文件树组件
├── TextFileView.tsx         # ✅ 文本文件预览
├── api.ts                   # ✅ API 调用
└── types.ts                 # ✅ 类型定义
```

**已有功能**：
- ✅ 左右分栏布局（文件树 + 预览区）
- ✅ 文件树导航（树形结构、展开/折叠）
- ✅ 文本文件预览（行号、只读）
- ✅ 文件创建/删除/重命名

**缺失功能**：
- ❌ Markdown 实时预览（只有纯文本显示）
- ❌ 图片预览（可能显示为"不支持"）
- ⚠️ 大文件虚拟滚动（可能有性能问题）

### 改进空间分析

通过系统性代码核实，确认：
1. **TextFileView 已存在且功能完整** - 不是新建，而是基于它扩展
2. **项目已有 Markdown 组件** - 可直接复用
3. **后端可能需要支持** - 图片预览需要 binary 返回

---

## 阶段一：Markdown 实时预览

**目标**：为 `.md` 文件提供实时预览，支持源码/预览/分屏三种模式。

### 1.1 创建 MarkdownPreviewView 组件

新建文件：`visualization/src/features/workspace/MarkdownPreviewView.tsx`

**功能设计**：

1. **三种显示模式**：
   - 源码模式：带行号的纯文本
   - 预览模式：渲染后的 Markdown
   - 分屏模式：左源码/右预览

2. **工具栏**：
   - 文件路径显示
   - 模式切换按钮（图标）

3. **源码视图**：
   - 行号（左侧固定）
   - 纯文本内容
   - 等宽字体

4. **预览视图**：
   - 使用项目现有 Markdown 组件
   - 传入 workspace origin
   - 支持所有 Markdown 语法

**核心代码结构**：

```typescript
import { useState } from "react";
import { Eye, FileText, Columns } from "lucide-react";
import { Markdown } from "../../components/Markdown";

type PreviewMode = "source" | "preview" | "split";

interface MarkdownPreviewViewProps {
  content: string;
  filePath: string;
}

export function MarkdownPreviewView({ content, filePath }: MarkdownPreviewViewProps) {
  const [mode, setMode] = useState<PreviewMode>("preview");
  
  return (
    <div className="flex flex-col h-full">
      {/* 工具栏：文件路径 + 模式切换 */}
      <div className="flex items-center gap-2 px-4 py-2 border-b border-fg-faint/10">
        <span className="text-xs text-fg-faint flex-1 truncate">
          {filePath}
        </span>
        
        <div className="flex gap-1 bg-surface-2 rounded p-0.5">
          <ModeButton mode="source" current={mode} onClick={() => setMode("source")} />
          <ModeButton mode="preview" current={mode} onClick={() => setMode("preview")} />
          <ModeButton mode="split" current={mode} onClick={() => setMode("split")} />
        </div>
      </div>
      
      {/* 内容区：根据模式渲染 */}
      <div className="flex-1 overflow-hidden">
        {mode === "source" && <SourceView content={content} />}
        {mode === "preview" && <PreviewPane content={content} filePath={filePath} />}
        {mode === "split" && (
          <div className="flex h-full">
            <div className="flex-1 border-r border-fg-faint/10 overflow-auto">
              <SourceView content={content} />
            </div>
            <div className="flex-1 overflow-auto">
              <PreviewPane content={content} filePath={filePath} />
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// 源码视图：带行号的纯文本
function SourceView({ content }: { content: string }) {
  const lines = content.split("\n");
  
  return (
    <div className="h-full overflow-auto">
      <div className="flex font-mono text-[11px]">
        {/* 行号列 */}
        <div className="sticky left-0 bg-surface-2 px-2 py-2 text-fg-faint border-r border-fg-faint/10">
          {lines.map((_, i) => (
            <div key={i} className="text-right">{i + 1}</div>
          ))}
        </div>
        
        {/* 内容列 */}
        <pre className="flex-1 px-4 py-2 text-fg-base">{content}</pre>
      </div>
    </div>
  );
}

// 预览面板：渲染后的 Markdown
function PreviewPane({ content, filePath }: { content: string; filePath: string }) {
  return (
    <div className="h-full overflow-auto px-6 py-4">
      <Markdown
        className="prose prose-sm prose-invert max-w-none"
        origin={{ type: "workspace", path: filePath }}
      >
        {content}
      </Markdown>
    </div>
  );
}

// 模式切换按钮
function ModeButton({ mode, current, onClick }: {
  mode: PreviewMode;
  current: PreviewMode;
  onClick: () => void;
}) {
  const icons = {
    source: <FileText size={12} />,
    preview: <Eye size={12} />,
    split: <Columns size={12} />
  };
  
  const titles = {
    source: "源码",
    preview: "预览",
    split: "分屏"
  };
  
  return (
    <button
      onClick={onClick}
      className={`
        px-2 py-1 text-[10px] rounded transition-all
        ${mode === current
          ? "bg-accent text-white"
          : "text-fg-faint hover:text-fg-base"}
      `}
      title={titles[mode]}
    >
      {icons[mode]}
    </button>
  );
}
```

### 1.2 集成到 WorkspaceView

修改文件：`visualization/src/features/workspace/WorkspaceView.tsx`

在文件预览逻辑中增加 Markdown 判断：

```typescript
import { MarkdownPreviewView } from "./MarkdownPreviewView";
import { TextFileView } from "./TextFileView";

function FilePreview({ file }: { file: WorkspaceFile }) {
  const ext = file.path.split(".").pop()?.toLowerCase();
  
  // Markdown 文件使用 Markdown 预览
  if (ext === "md" || ext === "markdown") {
    return (
      <MarkdownPreviewView
        content={file.content}
        filePath={file.path}
      />
    );
  }
  
  // 其他文本文件使用原有 TextFileView
  return (
    <TextFileView
      content={file.content}
      filePath={file.path}
    />
  );
}
```

**改动文件**：
- `visualization/src/features/workspace/MarkdownPreviewView.tsx`（新建约 150 行）
- `visualization/src/features/workspace/WorkspaceView.tsx`（修改约 20 行）

**验收标准**：
- [ ] `.md` 文件自动使用 MarkdownPreviewView
- [ ] 三种模式切换流畅（源码/预览/分屏）
- [ ] 源码视图显示正确行号
- [ ] 预览视图正确渲染 Markdown（标题、列表、代码块、链接等）
- [ ] 分屏模式左右布局正确
- [ ] 不影响其他文件类型预览

**工作量**：1 天

---

## 阶段二：图片预览

**目标**：为图片文件提供预览，支持缩放、全屏查看。

### 2.1 创建 ImagePreviewView 组件

新建文件：`visualization/src/features/workspace/ImagePreviewView.tsx`

**功能设计**：

1. **基础显示**：
   - 居中显示图片
   - 自适应容器大小
   - 保持宽高比

2. **缩放控制**：
   - 缩小按钮（20% 下限）
   - 百分比显示（可点击重置）
   - 放大按钮（500% 上限）

3. **全屏查看**：
   - 全屏按钮
   - 黑色半透明背景
   - 点击外部关闭

4. **下载功能**：
   - 下载按钮
   - 自动获取文件名

5. **错误处理**：
   - 加载失败友好提示

**核心代码结构**：

```typescript
import { useState } from "react";
import { ZoomIn, ZoomOut, Maximize2, Download, X } from "lucide-react";

interface ImagePreviewViewProps {
  file: WorkspaceFile;
}

export function ImagePreviewView({ file }: ImagePreviewViewProps) {
  const [scale, setScale] = useState(1);
  const [fullscreen, setFullscreen] = useState(false);
  
  // 图片 URL（通过后端 API 获取）
  const imageUrl = `/api/v2/workspace/files/${encodeURIComponent(file.path)}?preview=true`;
  
  const handleZoomIn = () => setScale(Math.min(scale * 1.2, 5));
  const handleZoomOut = () => setScale(Math.max(scale / 1.2, 0.2));
  const handleReset = () => setScale(1);
  const handleDownload = () => {
    const a = document.createElement("a");
    a.href = imageUrl;
    a.download = file.path.split("/").pop() ?? "image";
    a.click();
  };
  
  return (
    <div className="flex flex-col h-full bg-surface-1">
      {/* 工具栏 */}
      <div className="flex items-center gap-2 px-4 py-2 border-b border-fg-faint/10">
        <span className="text-xs text-fg-faint flex-1 truncate">
          {file.path}
        </span>
        
        {/* 缩放控制 */}
        <div className="flex items-center gap-1">
          <button onClick={handleZoomOut} className="p-1 hover:bg-surface-3 rounded">
            <ZoomOut size={14} />
          </button>
          <button onClick={handleReset} className="px-2 py-0.5 text-[10px] hover:bg-surface-3 rounded">
            {Math.round(scale * 100)}%
          </button>
          <button onClick={handleZoomIn} className="p-1 hover:bg-surface-3 rounded">
            <ZoomIn size={14} />
          </button>
        </div>
        
        {/* 全屏/下载 */}
        <div className="flex gap-1 ml-2 pl-2 border-l border-fg-faint/10">
          <button onClick={() => setFullscreen(true)} className="p-1 hover:bg-surface-3 rounded">
            <Maximize2 size={14} />
          </button>
          <button onClick={handleDownload} className="p-1 hover:bg-surface-3 rounded">
            <Download size={14} />
          </button>
        </div>
      </div>
      
      {/* 图片显示区 */}
      <div className="flex-1 overflow-auto flex items-center justify-center p-4">
        <img
          src={imageUrl}
          alt={file.path}
          style={{ transform: `scale(${scale})` }}
          className="max-w-full max-h-full object-contain transition-transform duration-200"
          onError={(e) => {
            e.currentTarget.src = "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='200' height='200'%3E%3Ctext x='50%25' y='50%25' text-anchor='middle' fill='%23666'%3E加载失败%3C/text%3E%3C/svg%3E";
          }}
        />
      </div>
      
      {/* 全屏模态框 */}
      {fullscreen && (
        <div
          className="fixed inset-0 z-50 bg-black/90 flex items-center justify-center"
          onClick={() => setFullscreen(false)}
        >
          <img
            src={imageUrl}
            alt={file.path}
            className="max-w-[90vw] max-h-[90vh] object-contain"
            onClick={(e) => e.stopPropagation()}
          />
          <button
            onClick={() => setFullscreen(false)}
            className="absolute top-4 right-4 text-white hover:text-accent"
          >
            <X size={24} />
          </button>
        </div>
      )}
    </div>
  );
}
```

### 2.2 集成到 WorkspaceView

修改文件：`visualization/src/features/workspace/WorkspaceView.tsx`

```typescript
import { ImagePreviewView } from "./ImagePreviewView";

function FilePreview({ file }: { file: WorkspaceFile }) {
  const ext = file.path.split(".").pop()?.toLowerCase();
  
  // Markdown 预览
  if (ext === "md" || ext === "markdown") {
    return <MarkdownPreviewView content={file.content} filePath={file.path} />;
  }
  
  // 图片预览
  if (["png", "jpg", "jpeg", "gif", "svg", "webp"].includes(ext ?? "")) {
    return <ImagePreviewView file={file} />;
  }
  
  // 文本文件
  return <TextFileView content={file.content} filePath={file.path} />;
}
```

### 2.3 后端支持检查

**需要确认**：后端是否已支持图片文件的 binary 返回？

**检查方法**：
1. 查看 `tinysoul/gateway/endpoint/workspace_routes.py`（或类似文件）
2. 确认 `/api/v2/workspace/files/{path}` 是否支持 `preview=true` 参数
3. 确认是否返回正确的 MIME 类型

**如果不支持**，需要在后端增加：

```python
# tinysoul/gateway/endpoint/workspace_routes.py
@router.get("/files/{file_path:path}")
async def get_workspace_file(file_path: str, preview: bool = False):
    """获取 Workspace 文件内容"""
    # 如果是图片且 preview=true，返回 binary
    if preview and is_image_file(file_path):
        content = read_file_binary(file_path)
        return Response(content, media_type=guess_mime_type(file_path))
    
    # 否则返回文本
    content = read_file_text(file_path)
    return {"path": file_path, "content": content}
```

**改动文件**：
- `visualization/src/features/workspace/ImagePreviewView.tsx`（新建约 120 行）
- `visualization/src/features/workspace/WorkspaceView.tsx`（修改约 10 行）
- `tinysoul/gateway/endpoint/workspace_routes.py`（可能需要修改约 20 行）

**验收标准**：
- [ ] 图片文件自动使用 ImagePreviewView
- [ ] 支持 png、jpg、jpeg、gif、svg、webp
- [ ] 缩放功能正常（20% - 500%）
- [ ] 全屏查看功能正常
- [ ] 下载功能正常
- [ ] 加载失败时显示友好提示
- [ ] 不影响其他文件类型预览

**工作量**：0.5 天

---

## 阶段三：虚拟滚动优化（可选）

**目标**：为超大文本文件（> 1000 行）提供虚拟滚动，避免性能问题。

### 3.1 现状分析

**问题**：全量渲染大文件（如 10,000 行代码）会导致：
- 初始渲染慢
- 滚动卡顿
- 内存占用高

**解决方案**：使用虚拟滚动（只渲染可见区域）

### 3.2 实现方案

使用 `react-window` 库（轻量、成熟）：

```bash
npm install react-window @types/react-window
```

修改文件：`visualization/src/features/workspace/TextFileView.tsx`

**策略**：
- 小文件（< 1000 行）：直接渲染（不增加复杂度）
- 大文件（≥ 1000 行）：虚拟滚动

```typescript
import { FixedSizeList } from "react-window";
import { useMemo } from "react";

interface TextFileViewProps {
  content: string;
  filePath: string;
}

export function TextFileView({ content, filePath }: TextFileViewProps) {
  const lines = useMemo(() => content.split("\n"), [content]);
  const lineHeight = 18;  // 行高（px）
  
  // 小文件直接渲染
  if (lines.length < 1000) {
    return <SimpleTextView lines={lines} filePath={filePath} />;
  }
  
  // 大文件使用虚拟滚动
  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center gap-2 px-4 py-2 border-b border-fg-faint/10">
        <span className="text-xs text-fg-faint flex-1 truncate">{filePath}</span>
        <span className="text-[10px] text-fg-faint">{lines.length.toLocaleString()} 行</span>
      </div>
      
      <FixedSizeList
        height={800}  // 需要动态计算实际高度
        itemCount={lines.length}
        itemSize={lineHeight}
        width="100%"
        className="flex-1"
      >
        {({ index, style }) => (
          <div style={style} className="flex font-mono text-[11px] hover:bg-fg-faint/5">
            <span className="w-16 px-2 text-right text-fg-faint shrink-0">
              {index + 1}
            </span>
            <span className="flex-1 px-2 text-fg-base whitespace-pre">
              {lines[index]}
            </span>
          </div>
        )}
      </FixedSizeList>
    </div>
  );
}

// 简单文本视图（小文件）
function SimpleTextView({ lines, filePath }: { lines: string[]; filePath: string }) {
  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center gap-2 px-4 py-2 border-b border-fg-faint/10">
        <span className="text-xs text-fg-faint flex-1 truncate">{filePath}</span>
        <span className="text-[10px] text-fg-faint">{lines.length} 行</span>
      </div>
      
      <div className="flex-1 overflow-auto">
        <div className="flex font-mono text-[11px]">
          <div className="sticky left-0 bg-surface-2 px-2 py-2 text-fg-faint border-r border-fg-faint/10">
            {lines.map((_, i) => (
              <div key={i} className="text-right h-[18px]">{i + 1}</div>
            ))}
          </div>
          <pre className="flex-1 px-4 py-2 text-fg-base">{lines.join("\n")}</pre>
        </div>
      </div>
    </div>
  );
}
```

**改动文件**：
- `visualization/src/features/workspace/TextFileView.tsx`（修改约 100 行）
- `visualization/package.json`（添加 react-window 依赖）

**验收标准**：
- [ ] 小文件（< 1000 行）使用简单渲染
- [ ] 大文件（≥ 1000 行）使用虚拟滚动
- [ ] 虚拟滚动流畅（60fps）
- [ ] 行号正确显示
- [ ] 支持键盘导航（上下滚动）
- [ ] 不影响 Markdown 预览和图片预览

**工作量**：0.5 天

---

## 总体工作量

| 阶段 | 内容 | 状态 | 工作量 |
|------|------|------|--------|
| 一 | Markdown 实时预览 | ⏳ 待执行 | 1 天 |
| 二 | 图片预览 | ⏳ 待执行 | 0.5 天 |
| 三 | 虚拟滚动优化 | 🔵 可选 | 0.5 天 |

**必做**：1.5 天  
**可选**：0.5 天

---

## 验收清单

### 阶段一验收
- [ ] MarkdownPreviewView 组件创建
- [ ] 三种模式切换（源码/预览/分屏）
- [ ] Markdown 正确渲染
- [ ] 集成到 WorkspaceView

### 阶段二验收
- [ ] ImagePreviewView 组件创建
- [ ] 图片加载和显示
- [ ] 缩放功能
- [ ] 全屏功能
- [ ] 下载功能
- [ ] 后端支持（如需要）

### 阶段三验收
- [ ] 虚拟滚动实现
- [ ] 性能提升明显
- [ ] 行号正确
- [ ] 不影响小文件

### 整体验收
- [ ] 所有文件类型预览正常
- [ ] 不破坏现有功能
- [ ] TypeScript 类型检查通过
- [ ] 性能无明显问题

---

## 风险与缓解

### 风险 1：Markdown 预览与 Markdown 组件不兼容

**缓解**：
- 使用项目现有的 Markdown 组件
- 提供正确的 origin 参数（workspace 路径）
- 测试各种 Markdown 语法（标题、列表、代码块、表格、链接等）

### 风险 2：图片预览需要后端支持

**缓解**：
- 先检查后端是否已支持 binary 返回
- 如需修改后端，与后端 agent 协商或提交需求
- 提供降级方案（显示"不支持预览，请下载查看"）

### 风险 3：虚拟滚动破坏搜索/选择功能

**缓解**：
- 阶段三标记为可选，优先级最低
- 先实现核心预览功能（Markdown、图片）
- 实际遇到性能问题时再优化
- 小文件保持原有渲染方式

### 风险 4：react-window 依赖冲突

**缓解**：
- 检查 package.json 现有依赖
- 考虑使用 react-virtuoso（更现代的替代）
- 或自行实现简单虚拟滚动（只需渲染可见区域）

---

## 与其他计划的关系

- **依赖**：无
- **优先级**：P2（建议在计划①之后执行）
- **后续**：Workspace 增强后，可考虑增加文件编辑功能（但需要架构讨论）

---

## 支持的文件类型

### Markdown 预览
- `.md`
- `.markdown`

### 图片预览
- `.png`
- `.jpg` / `.jpeg`
- `.gif`
- `.svg`
- `.webp`
- `.bmp`（可选）
- `.ico`（可选）

### 文本预览（已有）
- `.txt`
- `.json`
- `.yaml` / `.yml`
- `.toml`
- `.py`
- `.js` / `.ts` / `.jsx` / `.tsx`
- `.css` / `.scss`
- `.html`
- `.xml`
- 其他纯文本文件

### 不支持预览
- 二进制文件（.exe、.bin、.zip 等）
- Office 文档（.docx、.xlsx 等）
- PDF（可在后续版本支持）

---

## 改动效果

### 用户体验提升
- Markdown 文件可直接预览，不需要切换工具
- 图片文件可直接查看，支持缩放和全屏
- 大文件打开更流畅（虚拟滚动）
- 文件预览功能更完整

### 技术指标
- Markdown 渲染性能良好（复用现有组件）
- 图片预览响应迅速
- 大文件虚拟滚动流畅（60fps）
- 不增加显著 bundle 大小
- 保持现有功能完整性

---

**计划结束**
