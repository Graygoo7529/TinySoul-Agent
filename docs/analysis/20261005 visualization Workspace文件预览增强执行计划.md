# Visualization Workspace 文件预览增强执行计划

日期：2026-10-05

状态：待执行

---

## 一、当前情况分析

### 1.1 Workspace 页面架构

**核心文件**：
- `WorkspacePage.tsx`：主入口，负责 manifest 加载和布局
- `Sidebar.tsx`：左侧文件树
- `FilePanel.tsx`：右侧文件内容面板
- `mutations.ts`：文件操作 API（create/edit/delete/rename）

**当前布局**：
```
┌─────────────────────────────────────────┐
│ Workspace · 2026-10-05                  │
├───────────┬─────────────────────────────┤
│ Sidebar   │ FilePanel                   │
│ (文件树)  │ (文件内容)                  │
│           │                             │
│ 📁 docs/  │ [文本编辑器/预览]           │
│ 📄 main.py│                             │
│ 📄 test.md│                             │
└───────────┴─────────────────────────────┘
```

### 1.2 当前问题诊断

#### 问题 A：文件预览单一，缺少类型识别

**当前实现**（推测）：
- 所有文件可能都用纯文本编辑器打开
- 缺少文件类型识别和图标
- Markdown 文件没有渲染预览
- 图片文件无法预览
- JSON 文件没有格式化

#### 问题 B：文件元信息不足

**缺少的信息**：
- 文件大小
- 最后修改时间
- 文件 MIME 类型
- 行数（代码文件）
- 字符数（文本文件）

#### 问题 C：文件操作反馈不明确

**当前问题**：
- 创建/删除/重命名后，文件树可能没有明显变化
- 操作成功/失败的提示不够醒目
- 撤销操作不直观

#### 问题 D：缺少文件搜索和过滤

**用户需求**：
- 按文件名快速搜索
- 按文件类型过滤（.py / .md / .json）
- 按修改时间排序
- 按大小排序

#### 问题 E：Trash 管理不够直观

**当前问题**：
- Trash 中的文件可能只是列表形式
- 缺少恢复操作的可视化
- 不清楚 Trash 占用的空间

---

## 二、设计目标

### 2.1 文件类型识别与图标

> 每种文件类型应有独特的图标和预览方式

**文件分类**：
1. **代码文件**：.py/.js/.ts/.tsx/.jsx/.java/.cpp/.go/...
2. **文档文件**：.md/.txt/.rst
3. **数据文件**：.json/.yaml/.toml/.xml/.csv
4. **图片文件**：.png/.jpg/.jpeg/.gif/.svg/.webp
5. **其他文件**：.pdf/.zip/.tar.gz/...

### 2.2 预览模式多样化

**预览类型**：
1. **代码高亮**：使用 Shiki 或 Prism
2. **Markdown 渲染**：实时预览 + 编辑模式
3. **JSON 格式化**：树形展开 + 语法高亮
4. **图片预览**：缩略图 + 点击放大 + 基本信息
5. **纯文本**：简单编辑器

### 2.3 文件操作可视化

**操作反馈**：
1. 创建后：文件行闪烁高亮 1s
2. 删除后：Toast 通知 + 撤销按钮
3. 重命名后：文件行短暂高亮
4. 保存后：保存指示器 + 成功提示

---

## 三、核心组件设计

### 3.1 FileIcon 文件图标组件

**新建文件**：`visualization/src/features/workspace/FileIcon.tsx`

```tsx
import {
  FileText,
  FileCode,
  FileJson,
  FileImage,
  File,
  Folder,
  FolderOpen,
} from "lucide-react";

const FILE_TYPE_CONFIG: Record<string, { 
  icon: React.ComponentType<any>; 
  color: string;
  category: "code" | "doc" | "data" | "image" | "other";
}> = {
  // Code
  ".py": { icon: FileCode, color: "text-blue-500", category: "code" },
  ".js": { icon: FileCode, color: "text-yellow-500", category: "code" },
  ".ts": { icon: FileCode, color: "text-blue-600", category: "code" },
  ".tsx": { icon: FileCode, color: "text-blue-600", category: "code" },
  ".jsx": { icon: FileCode, color: "text-yellow-500", category: "code" },
  ".java": { icon: FileCode, color: "text-red-500", category: "code" },
  ".cpp": { icon: FileCode, color: "text-purple-500", category: "code" },
  ".go": { icon: FileCode, color: "text-cyan-500", category: "code" },
  ".rs": { icon: FileCode, color: "text-orange-500", category: "code" },
  
  // Docs
  ".md": { icon: FileText, color: "text-blue-400", category: "doc" },
  ".txt": { icon: FileText, color: "text-fg-muted", category: "doc" },
  ".rst": { icon: FileText, color: "text-purple-400", category: "doc" },
  
  // Data
  ".json": { icon: FileJson, color: "text-yellow-600", category: "data" },
  ".yaml": { icon: FileJson, color: "text-red-400", category: "data" },
  ".yml": { icon: FileJson, color: "text-red-400", category: "data" },
  ".toml": { icon: FileJson, color: "text-orange-400", category: "data" },
  ".xml": { icon: FileJson, color: "text-green-500", category: "data" },
  
  // Images
  ".png": { icon: FileImage, color: "text-purple-500", category: "image" },
  ".jpg": { icon: FileImage, color: "text-purple-500", category: "image" },
  ".jpeg": { icon: FileImage, color: "text-purple-500", category: "image" },
  ".gif": { icon: FileImage, color: "text-pink-500", category: "image" },
  ".svg": { icon: FileImage, color: "text-indigo-500", category: "image" },
  ".webp": { icon: FileImage, color: "text-purple-500", category: "image" },
};

export function FileIcon({ 
  name, 
  isDirectory, 
  isOpen, 
  size = 14 
}: { 
  name: string; 
  isDirectory?: boolean; 
  isOpen?: boolean; 
  size?: number;
}) {
  if (isDirectory) {
    const Icon = isOpen ? FolderOpen : Folder;
    return <Icon size={size} className="text-accent" />;
  }
  
  const ext = name.includes(".") ? "." + name.split(".").pop()!.toLowerCase() : "";
  const config = FILE_TYPE_CONFIG[ext] ?? { 
    icon: File, 
    color: "text-fg-faint",
    category: "other" 
  };
  
  const Icon = config.icon;
  return <Icon size={size} className={config.color} />;
}

export function getFileCategory(name: string): string {
  const ext = name.includes(".") ? "." + name.split(".").pop()!.toLowerCase() : "";
  return FILE_TYPE_CONFIG[ext]?.category ?? "other";
}
```

### 3.2 FilePreview 文件预览组件

**新建文件**：`visualization/src/features/workspace/FilePreview.tsx`

```tsx
import { useState } from "react";
import { Eye, Edit2, Download, Maximize2 } from "lucide-react";
import { Button } from "../../components/ui/Button";
import { Markdown } from "../../components/markdown/Markdown";
import { JsonTree } from "../../components/ui/JsonTree";
import { CodeBlock } from "../../components/ui/CodeBlock";
import { getFileCategory } from "./FileIcon";

interface FilePreviewProps {
  name: string;
  content: string;
  mimeType?: string;
  onSave?: (content: string) => Promise<void>;
  readOnly?: boolean;
}

export function FilePreview({ 
  name, 
  content, 
  mimeType, 
  onSave,
  readOnly = false 
}: FilePreviewProps) {
  const [mode, setMode] = useState<"view" | "edit">("view");
  const [editContent, setEditContent] = useState(content);
  const [saving, setSaving] = useState(false);
  
  const category = getFileCategory(name);
  const ext = name.includes(".") ? name.split(".").pop()!.toLowerCase() : "";
  
  const handleSave = async () => {
    if (!onSave) return;
    setSaving(true);
    try {
      await onSave(editContent);
      setMode("view");
    } finally {
      setSaving(false);
    }
  };
  
  return (
    <div className="flex h-full flex-col">
      {/* Toolbar */}
      <div className="flex items-center justify-between border-b border-line bg-bg-elev px-4 py-2">
        <div className="flex items-center gap-3">
          <FileIcon name={name} size={16} />
          <div>
            <div className="text-[13px] font-medium text-fg">{name}</div>
            <div className="text-[10px] text-fg-faint">
              {content.length} bytes · {content.split("\n").length} lines
            </div>
          </div>
        </div>
        
        <div className="flex items-center gap-2">
          {category === "doc" && mode === "view" && (
            <Button size="sm" variant="ghost" onClick={() => setMode("edit")}>
              <Edit2 size={12} />
              Edit
            </Button>
          )}
          {mode === "edit" && (
            <>
              <Button 
                size="sm" 
                variant="ghost" 
                onClick={() => {
                  setEditContent(content);
                  setMode("view");
                }}
              >
                Cancel
              </Button>
              <Button size="sm" onClick={handleSave} disabled={saving}>
                {saving ? "Saving..." : "Save"}
              </Button>
            </>
          )}
          <Button size="sm" variant="ghost">
            <Download size={12} />
            Download
          </Button>
        </div>
      </div>
      
      {/* Content */}
      <div className="flex-1 overflow-auto p-4">
        {renderContent(category, ext, mode === "edit" ? editContent : content, mode, setEditContent)}
      </div>
    </div>
  );
}

function renderContent(
  category: string,
  ext: string,
  content: string,
  mode: "view" | "edit",
  setContent: (content: string) => void
): React.ReactNode {
  // Image
  if (category === "image") {
    return <ImagePreview content={content} ext={ext} />;
  }
  
  // Markdown
  if (ext === "md") {
    if (mode === "edit") {
      return (
        <textarea
          value={content}
          onChange={(e) => setContent(e.target.value)}
          className="h-full w-full resize-none rounded-lg border border-line bg-bg px-3 py-2 font-mono text-[12px] focus:border-accent focus:outline-none"
        />
      );
    }
    return <Markdown className="md-calm">{content}</Markdown>;
  }
  
  // JSON
  if (ext === "json") {
    try {
      const parsed = JSON.parse(content);
      return <JsonTree data={parsed} />;
    } catch {
      // Fall through to code view
    }
  }
  
  // Code
  if (category === "code" || category === "data") {
    return (
      <CodeBlock 
        language={ext} 
        code={content}
        showLineNumbers
      />
    );
  }
  
  // Plain text
  return (
    <pre className="font-mono text-[12px] text-fg whitespace-pre-wrap">
      {content}
    </pre>
  );
}

function ImagePreview({ content, ext }: { content: string; ext: string }) {
  const [zoomed, setZoomed] = useState(false);
  
  // 假设 content 是 base64 或 URL
  const src = content.startsWith("data:") ? content : `data:image/${ext};base64,${content}`;
  
  return (
    <div className="flex flex-col items-center gap-4">
      <img
        src={src}
        alt="Preview"
        className={`rounded-lg border border-line shadow-card ${
          zoomed ? "max-w-full" : "max-w-md"
        } cursor-pointer transition-all`}
        onClick={() => setZoomed(!zoomed)}
      />
      <div className="text-[11px] text-fg-faint">
        Click to {zoomed ? "shrink" : "enlarge"}
      </div>
    </div>
  );
}
```

### 3.3 FileTreeNode 增强文件树节点

**修改文件**：`visualization/src/features/workspace/Sidebar.tsx`

**增强节点显示**：
```tsx
function FileTreeNode({ 
  node, 
  selected, 
  onSelect, 
  depth,
  recentlyModified 
}: {
  node: FileNode;
  selected: string | null;
  onSelect: (path: string) => void;
  depth: number;
  recentlyModified?: Set<string>; // 最近修改的文件集合
}) {
  const [expanded, setExpanded] = useState(depth === 0);
  const isSelected = selected === node.path;
  const isRecent = recentlyModified?.has(node.path);
  
  return (
    <div>
      <button
        onClick={() => {
          if (node.type === "directory") setExpanded(!expanded);
          onSelect(node.path);
        }}
        className={`
          flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-[12px]
          transition-all
          ${isSelected 
            ? "bg-accent text-white" 
            : "text-fg hover:bg-hover"
          }
          ${isRecent ? "animate-flash-highlight" : ""}
        `}
        style={{ paddingLeft: `${depth * 12 + 8}px` }}
      >
        {node.type === "directory" && (
          <ChevronRight
            size={11}
            className={`shrink-0 transition-transform ${
              expanded ? "rotate-90" : ""
            }`}
          />
        )}
        {node.type === "file" && <div className="w-[11px]" />}
        
        <FileIcon 
          name={node.name} 
          isDirectory={node.type === "directory"}
          isOpen={expanded}
          size={11}
        />
        
        <span className="flex-1 truncate">{node.name}</span>
        
        {node.size !== undefined && (
          <span className="font-mono text-[9px] text-fg-faint">
            {formatBytes(node.size)}
          </span>
        )}
      </button>
      
      {/* Children */}
      {node.type === "directory" && expanded && node.children && (
        <div className="mt-0.5">
          {node.children.map((child) => (
            <FileTreeNode
              key={child.path}
              node={child}
              selected={selected}
              onSelect={onSelect}
              depth={depth + 1}
              recentlyModified={recentlyModified}
            />
          ))}
        </div>
      )}
    </div>
  );
}

// CSS for flash animation
// Add to styles/index.css
@keyframes flash-highlight {
  0%, 100% { background-color: transparent; }
  50% { background-color: rgba(var(--color-success-rgb), 0.2); }
}

.animate-flash-highlight {
  animation: flash-highlight 1s ease-in-out;
}
```

### 3.4 SearchBar 文件搜索栏

**新建文件**：`visualization/src/features/workspace/SearchBar.tsx`

```tsx
import { useState } from "react";
import { Search, X, Filter } from "lucide-react";

interface SearchBarProps {
  onSearch: (query: string) => void;
  onFilter: (filters: FileFilter) => void;
}

interface FileFilter {
  category?: "code" | "doc" | "data" | "image" | "other";
  sortBy?: "name" | "size" | "modified";
  sortOrder?: "asc" | "desc";
}

export function SearchBar({ onSearch, onFilter }: SearchBarProps) {
  const [query, setQuery] = useState("");
  const [showFilters, setShowFilters] = useState(false);
  const [filter, setFilter] = useState<FileFilter>({});
  
  return (
    <div className="space-y-2 border-b border-line bg-bg-elev p-3">
      {/* Search Input */}
      <div className="relative">
        <Search 
          size={13} 
          className="absolute left-3 top-1/2 -translate-y-1/2 text-fg-faint" 
        />
        <input
          type="text"
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            onSearch(e.target.value);
          }}
          placeholder="Search files..."
          className="w-full rounded-lg border border-line bg-bg py-2 pl-9 pr-9 text-[12px] focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/20"
        />
        {query && (
          <button
            onClick={() => {
              setQuery("");
              onSearch("");
            }}
            className="absolute right-3 top-1/2 -translate-y-1/2 text-fg-faint hover:text-fg"
          >
            <X size={13} />
          </button>
        )}
      </div>
      
      {/* Filter Toggle */}
      <button
        onClick={() => setShowFilters(!showFilters)}
        className="flex items-center gap-2 text-[11px] text-fg-muted hover:text-fg"
      >
        <Filter size={11} />
        Filters
        {Object.keys(filter).length > 0 && (
          <span className="rounded-full bg-accent px-1.5 py-0.5 text-[9px] text-white">
            {Object.keys(filter).length}
          </span>
        )}
      </button>
      
      {/* Filters Panel */}
      {showFilters && (
        <div className="space-y-2 rounded-lg border border-line bg-bg-sunken p-3">
          {/* Category Filter */}
          <div>
            <label className="block text-[10px] font-medium text-fg-muted mb-1">
              File Type
            </label>
            <select
              value={filter.category ?? ""}
              onChange={(e) => {
                const newFilter = { ...filter };
                if (e.target.value) {
                  newFilter.category = e.target.value as any;
                } else {
                  delete newFilter.category;
                }
                setFilter(newFilter);
                onFilter(newFilter);
              }}
              className="w-full rounded border border-line bg-bg px-2 py-1 text-[11px] focus:border-accent focus:outline-none"
            >
              <option value="">All types</option>
              <option value="code">Code</option>
              <option value="doc">Documents</option>
              <option value="data">Data</option>
              <option value="image">Images</option>
              <option value="other">Other</option>
            </select>
          </div>
          
          {/* Sort By */}
          <div>
            <label className="block text-[10px] font-medium text-fg-muted mb-1">
              Sort By
            </label>
            <div className="flex gap-2">
              <select
                value={filter.sortBy ?? "name"}
                onChange={(e) => {
                  const newFilter = { ...filter, sortBy: e.target.value as any };
                  setFilter(newFilter);
                  onFilter(newFilter);
                }}
                className="flex-1 rounded border border-line bg-bg px-2 py-1 text-[11px] focus:border-accent focus:outline-none"
              >
                <option value="name">Name</option>
                <option value="size">Size</option>
                <option value="modified">Modified</option>
              </select>
              <button
                onClick={() => {
                  const newFilter = { 
                    ...filter, 
                    sortOrder: filter.sortOrder === "asc" ? "desc" : "asc" 
                  };
                  setFilter(newFilter);
                  onFilter(newFilter);
                }}
                className="rounded border border-line bg-bg px-2 py-1 text-[11px] hover:bg-hover"
              >
                {filter.sortOrder === "asc" ? "↑" : "↓"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
```

### 3.5 TrashPanel Trash 管理面板

**新建文件**：`visualization/src/features/workspace/TrashPanel.tsx`

```tsx
import { useState } from "react";
import { Trash2, RotateCcw, X } from "lucide-react";
import { Button } from "../../components/ui/Button";
import { FileIcon } from "./FileIcon";

interface TrashItem {
  path: string;
  name: string;
  size: number;
  deletedAt: string;
}

export function TrashPanel({ 
  items, 
  onRestore, 
  onPermanentDelete, 
  onEmptyTrash 
}: {
  items: TrashItem[];
  onRestore: (path: string) => Promise<void>;
  onPermanentDelete: (path: string) => Promise<void>;
  onEmptyTrash: () => Promise<void>;
}) {
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const totalSize = items.reduce((sum, item) => sum + item.size, 0);
  
  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-line bg-bg-elev px-4 py-3">
        <div className="flex items-center gap-2">
          <Trash2 size={14} className="text-fg-faint" />
          <div>
            <div className="text-[13px] font-medium text-fg">Trash</div>
            <div className="text-[10px] text-fg-faint">
              {items.length} items · {formatBytes(totalSize)}
            </div>
          </div>
        </div>
        
        {items.length > 0 && (
          <Button 
            size="sm" 
            variant="outline" 
            onClick={onEmptyTrash}
            className="text-danger hover:bg-danger-soft"
          >
            <Trash2 size={12} />
            Empty Trash
          </Button>
        )}
      </div>
      
      {/* Items */}
      <div className="flex-1 overflow-y-auto p-3 space-y-1">
        {items.length === 0 ? (
          <div className="flex h-full items-center justify-center text-[12px] text-fg-faint">
            Trash is empty
          </div>
        ) : (
          items.map((item) => (
            <div
              key={item.path}
              className="flex items-center gap-3 rounded-lg border border-line bg-bg-elev px-3 py-2 hover:border-accent/30"
            >
              <FileIcon name={item.name} size={14} />
              <div className="flex-1 min-w-0">
                <div className="truncate text-[12px] text-fg">{item.name}</div>
                <div className="text-[10px] text-fg-faint">
                  {formatRelativeTime(item.deletedAt)} · {formatBytes(item.size)}
                </div>
              </div>
              <div className="flex items-center gap-1">
                <Button
                  size="xs"
                  variant="ghost"
                  onClick={() => onRestore(item.path)}
                  title="Restore"
                >
                  <RotateCcw size={12} />
                </Button>
                <Button
                  size="xs"
                  variant="ghost"
                  onClick={() => onPermanentDelete(item.path)}
                  title="Delete permanently"
                  className="text-danger hover:bg-danger-soft"
                >
                  <X size={12} />
                </Button>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}

function formatRelativeTime(isoString: string): string {
  const date = new Date(isoString);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMins = Math.floor(diffMs / 60000);
  
  if (diffMins < 60) return `${diffMins}m ago`;
  const diffHours = Math.floor(diffMins / 60);
  if (diffHours < 24) return `${diffHours}h ago`;
  const diffDays = Math.floor(diffHours / 24);
  return `${diffDays}d ago`;
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
```

---

## 四、WorkspacePage 布局重构

### 4.1 增加顶部工具栏

**修改文件**：`visualization/src/features/workspace/WorkspacePage.tsx`

```tsx
export function WorkspacePage() {
  // ... 现有逻辑
  const [view, setView] = useState<"files" | "trash">("files");
  const [searchQuery, setSearchQuery] = useState("");
  const [filter, setFilter] = useState<FileFilter>({});
  
  return (
    <div className="flex h-full flex-col">
      {/* Toolbar */}
      <div className="flex items-center justify-between border-b border-line bg-bg-elev px-4 py-2">
        <div className="flex items-center gap-3">
          <h1 className="text-[14px] font-semibold text-fg">Workspace</h1>
          <span className="text-[11px] text-fg-faint">
            {isActive ? "Active · Today" : `Archived · ${viewDay}`}
          </span>
        </div>
        
        <div className="flex items-center gap-2">
          {/* View Toggle */}
          <div className="flex rounded-lg border border-line bg-bg-sunken/40">
            <button
              onClick={() => setView("files")}
              className={`px-3 py-1 text-[11px] ${
                view === "files" 
                  ? "bg-accent text-white rounded-lg" 
                  : "text-fg-muted hover:text-fg"
              }`}
            >
              Files
            </button>
            <button
              onClick={() => setView("trash")}
              className={`px-3 py-1 text-[11px] ${
                view === "trash" 
                  ? "bg-accent text-white rounded-lg" 
                  : "text-fg-muted hover:text-fg"
              }`}
            >
              Trash ({trashItems.length})
            </button>
          </div>
          
          {/* Actions */}
          {view === "files" && (
            <Button size="sm" variant="outline">
              <Plus size={12} />
              New File
            </Button>
          )}
        </div>
      </div>
      
      {/* Main Content */}
      <div className="flex flex-1 min-h-0">
        {view === "files" ? (
          <>
            <div className="w-[280px] border-r border-line flex flex-col">
              <SearchBar onSearch={setSearchQuery} onFilter={setFilter} />
              <Sidebar 
                manifest={manifest}
                selected={link}
                onSelect={handleSelect}
                searchQuery={searchQuery}
                filter={filter}
              />
            </div>
            <div className="flex-1">
              <FilePanel link={link} />
            </div>
          </>
        ) : (
          <div className="flex-1">
            <TrashPanel
              items={trashItems}
              onRestore={handleRestore}
              onPermanentDelete={handlePermanentDelete}
              onEmptyTrash={handleEmptyTrash}
            />
          </div>
        )}
      </div>
    </div>
  );
}
```

---

## 五、实施优先级与工作量

### P0：文件类型识别与基础预览（2 天）

| 任务 | 时间 | 难度 |
|------|------|------|
| 创建 FileIcon 组件 | 2h | 低 |
| 创建 FilePreview 组件（基础版） | 4h | 中 |
| 增强 FileTreeNode（图标 + 大小） | 2h | 低 |
| 集成到 WorkspacePage | 2h | 低 |
| 测试各种文件类型 | 2h | - |
| **小计** | **12h ≈ 2 天** | |

### P1：搜索过滤与 Trash 管理（2 天）

| 任务 | 时间 | 难度 |
|------|------|------|
| 创建 SearchBar 组件 | 3h | 中 |
| 实现搜索和过滤逻辑 | 3h | 中 |
| 创建 TrashPanel 组件 | 3h | 中 |
| 集成 Trash 操作 API | 2h | 低 |
| 测试与调整 | 2h | - |
| **小计** | **13h ≈ 2 天** | |

### P2：高级预览功能（1-2 天）

| 任务 | 时间 | 难度 |
|------|------|------|
| 代码高亮（Shiki 集成） | 3h | 中 |
| JSON 树形展开 | 2h | 低 |
| 图片放大预览 | 2h | 低 |
| Markdown 编辑器增强 | 3h | 中 |
| 测试与调整 | 2h | - |
| **小计** | **12h ≈ 2 天** | |

### 总计：5-6 个工作日

---

## 六、预期效果对比

### 6.1 文件树

**改进前**：
```
┌─ Files ───────┐
│ docs          │
│ main.py       │
│ test.md       │
│ data.json     │
└───────────────┘
```

**改进后**：
```
┌─ Files ───────────┐
│ [Search...]       │
│ [Filters ▼]       │
│                   │
│ 📁 docs           │
│ 🐍 main.py   2.3K │
│ 📄 test.md   1.1K │
│ {} data.json 0.8K │
└───────────────────┘
```

### 6.2 文件预览

**改进前（可能）**：
```
┌─ main.py ─────────┐
│ def hello():      │
│     print("hi")   │
└───────────────────┘
```

**改进后**：
```
┌─ main.py ──────────────────┐
│ 🐍 main.py               │
│ 234 bytes · 12 lines      │
│ [Edit] [Download]         │
├───────────────────────────┤
│ 1  def hello():           │
│ 2      print("hi")        │
│ 3                         │
│ 4  if __name__ == ...     │
└───────────────────────────┘
  ↑ 语法高亮
```

**Markdown 预览**：
```
┌─ README.md ────────────────┐
│ 📄 README.md              │
│ [View] [Edit]              │
├───────────────────────────┤
│ # TinySoul                │ ← 渲染后的 Markdown
│                            │
│ An AI agent framework...   │
└────────────────────────────┘
```

**图片预览**：
```
┌─ logo.png ─────────────────┐
│ 🖼️ logo.png               │
│ [Download] [Enlarge]       │
├────────────────────────────┤
│     ┌────────┐             │
│     │  Logo  │             │
│     │  Image │             │
│     └────────┘             │
│ 512x512 · 45 KB            │
│ Click to enlarge           │
└────────────────────────────┘
```

### 6.3 Trash 管理

**改进前（可能没有）**：
```
Files only
```

**改进后**：
```
┌─ Trash ───────────────────┐
│ 3 items · 5.2 KB          │
│ [Empty Trash]             │
├───────────────────────────┤
│ 🐍 old.py                 │
│    2h ago · 2.3 KB        │
│    [Restore] [Delete]     │
│                           │
│ 📄 draft.md               │
│    1d ago · 1.8 KB        │
│    [Restore] [Delete]     │
└───────────────────────────┘
```

---

## 七、验收标准

### 功能验收
- [ ] 文件图标根据类型正确显示
- [ ] 代码文件有语法高亮
- [ ] Markdown 文件有渲染预览
- [ ] JSON 文件有格式化展示
- [ ] 图片文件有缩略图和放大功能
- [ ] 搜索功能正常工作
- [ ] 过滤功能正常工作
- [ ] Trash 恢复/删除操作正常

### 视觉验收
- [ ] 文件图标颜色一致且易识别
- [ ] 代码高亮主题协调
- [ ] 预览面板布局清晰
- [ ] 操作按钮位置合理

### 性能验收
- [ ] 大文件（> 1MB）加载不卡顿
- [ ] 搜索响应 < 200ms
- [ ] 文件树展开/折叠流畅

---

## 八、技术依赖

### 新增依赖（可选）

```json
{
  "dependencies": {
    "shiki": "^1.0.0",          // 代码高亮
    "react-json-tree": "^0.18.0" // JSON 树形展开（或自己实现）
  }
}
```

**如果不想增加依赖**：
- 代码高亮可以先用简单的 `<pre><code>` + CSS
- JSON 可以用递归组件自己实现

---

## 九、风险评估

### 低风险
- ✅ 文件图标是纯视觉改进
- ✅ 搜索和过滤是客户端逻辑

### 中风险
- ⚠️ 大文件预览可能耗时
  - **缓解**：限制预览大小（如 1MB），超过则提示下载
- ⚠️ 图片文件可能很大
  - **缓解**：使用缩略图 API（如果后端提供）

### 注意事项
- 测试不同文件类型的预览
- 确保 Trash 操作有确认提示
- 文件操作后正确刷新 manifest

---

**执行状态**：待开始

**预计完成时间**：5-6 个工作日

**负责人**：GPT Agent（实施）+ Claude（审查）

**依赖**：可选的代码高亮库（可以后续添加）
