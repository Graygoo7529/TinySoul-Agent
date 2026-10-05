# Visualization Home/Memory 图形化优化执行计划

日期：2026-10-05

状态：待执行

---

## 一、当前情况分析

### 1.1 Home 页面架构

**核心文件**：
- `HomePage.tsx`：主入口页面
- `HomeContentView.tsx`：内容编辑器
- 相关 API：`/api/v2/home` endpoints

**当前布局**（推测）：
```
┌─────────────────────────────────────┐
│ Home                                │
├─────────────────────────────────────┤
│ Sidebar (导航)  │  Content Editor   │
│                 │                   │
│ - identity      │  [Markdown 编辑器]│
│ - skills_domain │                   │
│ - skills_action │                   │
└─────────────────────────────────────┘
```

### 1.2 Memory 页面架构

**核心文件**：
- `MemoryPage.tsx`：主入口页面
- `ActiveMemoryView.tsx`：活动记忆视图
- `MemoryDocumentView.tsx`：持久文档视图
- 相关 API：`/api/v2/memory` endpoints

**当前布局**（推测）：
```
┌─────────────────────────────────────┐
│ Memory                              │
├─────────────────────────────────────┤
│ Sidebar         │  Document View    │
│                 │                   │
│ - Active Memory │  [Markdown 内容]  │
│ - Daily         │                   │
│ - Entity        │                   │
│ - Concept       │                   │
│ - Fact          │                   │
│ - Note          │                   │
└─────────────────────────────────────┘
```

### 1.3 核心问题诊断

#### 问题 A：资源导航缺少视觉层次

**当前问题**：
- Home 的 Link 列表（identity/skills_domain/skills_action）是扁平的文本列表
- Memory 的五种类型（daily/entity/concept/fact/note）缺少图形化区分
- 缺少资源元信息（大小、修改时间、引用关系）

#### 问题 B：编辑与预览缺少明确分离

**当前问题**：
- 可能是编辑器与预览混在一起
- 缺少"编辑模式 vs 阅读模式"的切换
- 修改状态不够明确

#### 问题 C：引用关系不可视化

**Home/Memory 的核心价值在于资源之间的引用关系**：
- Home 资源之间可能有 `[[link]]` 引用
- Memory 文档之间有 backlinks
- 当前这些关系是隐藏的，只能通过阅读正文发现

#### 问题 D：缺少整体概览

**用户需要快速了解**：
- Home 有哪些资源、分别多大
- Memory 各类型有多少文档
- 最近修改了什么
- 哪些资源被频繁引用

---

## 二、设计目标

### 2.1 Home 页面重构目标

> Home 是"知识库"，需要像文件管理器一样组织和呈现资源

**核心功能**：
1. **资源浏览**：树形/列表视图切换
2. **元信息展示**：大小、修改时间、来源
3. **引用可视化**：显示资源间的引用关系
4. **快速预览**：hover 或侧边栏预览
5. **编辑模式**：明确的编辑/保存/取消流程

### 2.2 Memory 页面重构目标

> Memory 是"记忆网络"，需要可视化文档之间的关联

**核心功能**：
1. **类型分组**：五种类型独立视图，带图标和色彩
2. **Backlinks 可视化**：显示每个文档被哪些文档引用
3. **时间线视图**：按日期浏览 daily memory
4. **搜索与过滤**：快速定位文档
5. **图谱视图**（可选）：以图的形式展示文档关联

---

## 三、Home 页面优化方案

### 3.1 整体布局重构

**三栏布局**：
```
┌────────────────────────────────────────────────┐
│ Home · Effective                               │
├──────────────┬─────────────────┬───────────────┤
│ Navigator    │ Content View    │ Inspector     │
│ (左 240px)   │ (中 flex-1)     │ (右 280px)    │
│              │                 │               │
│ • Overview   │ [编辑器/预览]   │ Metadata      │
│ • identity   │                 │ - Size        │
│ • domains/   │                 │ - Modified    │
│   - workspace│                 │ - Source      │
│   - memory   │                 │               │
│ • actions/   │                 │ References    │
│   - edit     │                 │ - Links to    │
│   - search   │                 │ - Linked by   │
└──────────────┴─────────────────┴───────────────┘
```

### 3.2 Navigator（左侧导航）重构

**新建文件**：`visualization/src/features/home/HomeNavigator.tsx`

```tsx
import { useState } from "react";
import { 
  Home as HomeIcon, 
  ChevronRight, 
  FileText, 
  FolderOpen,
  Link as LinkIcon
} from "lucide-react";

interface HomeResource {
  ref: string; // home:agent@identity
  title: string;
  type: "root" | "domain" | "action";
  size: number;
  modified?: string;
  children?: HomeResource[];
}

export function HomeNavigator({ 
  resources, 
  selected, 
  onSelect 
}: {
  resources: HomeResource[];
  selected: string | null;
  onSelect: (ref: string) => void;
}) {
  return (
    <div className="h-full overflow-y-auto border-r border-line bg-bg-sunken/40 p-3">
      {/* 概览卡片 */}
      <OverviewCard resources={resources} />
      
      {/* 资源树 */}
      <div className="mt-4 space-y-1">
        {resources.map((resource) => (
          <ResourceNode
            key={resource.ref}
            resource={resource}
            selected={selected}
            onSelect={onSelect}
            depth={0}
          />
        ))}
      </div>
    </div>
  );
}

function OverviewCard({ resources }: { resources: HomeResource[] }) {
  const totalSize = resources.reduce((sum, r) => sum + r.size, 0);
  const domainCount = resources.filter(r => r.type === "domain").length;
  const actionCount = resources.filter(r => r.type === "action").length;
  
  return (
    <div className="rounded-lg border border-line bg-bg-elev px-3 py-2.5">
      <div className="flex items-center gap-2 text-[13px] font-medium text-fg mb-2">
        <HomeIcon size={13} />
        <span>Overview</span>
      </div>
      <div className="space-y-1 text-[11px]">
        <div className="flex justify-between">
          <span className="text-fg-faint">Total Size:</span>
          <span className="font-mono text-fg">{formatBytes(totalSize)}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-fg-faint">Domains:</span>
          <span className="text-fg">{domainCount}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-fg-faint">Actions:</span>
          <span className="text-fg">{actionCount}</span>
        </div>
      </div>
    </div>
  );
}

function ResourceNode({ 
  resource, 
  selected, 
  onSelect, 
  depth 
}: {
  resource: HomeResource;
  selected: string | null;
  onSelect: (ref: string) => void;
  depth: number;
}) {
  const [expanded, setExpanded] = useState(depth === 0);
  const hasChildren = resource.children && resource.children.length > 0;
  const isSelected = selected === resource.ref;
  
  return (
    <div>
      <button
        onClick={() => {
          if (hasChildren) setExpanded(!expanded);
          onSelect(resource.ref);
        }}
        className={`
          flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-[12px]
          transition-colors
          ${isSelected 
            ? "bg-accent text-white" 
            : "text-fg hover:bg-hover"
          }
        `}
        style={{ paddingLeft: `${depth * 12 + 8}px` }}
      >
        {hasChildren && (
          <ChevronRight
            size={11}
            className={`shrink-0 transition-transform ${
              expanded ? "rotate-90" : ""
            }`}
          />
        )}
        {!hasChildren && <div className="w-[11px]" />}
        
        {resource.type === "domain" ? (
          <FolderOpen size={11} className="shrink-0" />
        ) : resource.type === "action" ? (
          <FileText size={11} className="shrink-0" />
        ) : (
          <LinkIcon size={11} className="shrink-0" />
        )}
        
        <span className="flex-1 truncate">{resource.title}</span>
        
        <span className="font-mono text-[9px] text-fg-faint">
          {formatBytes(resource.size)}
        </span>
      </button>
      
      {hasChildren && expanded && (
        <div className="mt-0.5">
          {resource.children!.map((child) => (
            <ResourceNode
              key={child.ref}
              resource={child}
              selected={selected}
              onSelect={onSelect}
              depth={depth + 1}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes}B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)}K`;
  return `${(bytes / (1024 * 1024)).toFixed(1)}M`;
}
```

### 3.3 Inspector（右侧面板）新增

**新建文件**：`visualization/src/features/home/HomeInspector.tsx`

```tsx
import { Clock, FileText, Link as LinkIcon, Tag } from "lucide-react";

interface HomeResourceMeta {
  ref: string;
  title: string;
  size: number;
  lineCount: number;
  modified?: string;
  source: "actual" | "overlay";
  linksTo: string[];      // 此资源引用了哪些资源
  linkedBy: string[];     // 哪些资源引用了此资源
}

export function HomeInspector({ resource }: { resource: HomeResourceMeta | null }) {
  if (!resource) {
    return (
      <div className="flex h-full items-center justify-center border-l border-line bg-bg-sunken/20 p-4">
        <div className="text-center text-[12px] text-fg-faint">
          Select a resource to view details
        </div>
      </div>
    );
  }
  
  return (
    <div className="h-full overflow-y-auto border-l border-line bg-bg-sunken/20 p-4 space-y-4">
      {/* Metadata */}
      <section>
        <h3 className="flex items-center gap-2 text-[12px] font-medium text-fg mb-2">
          <FileText size={12} />
          Metadata
        </h3>
        <div className="space-y-1.5 text-[11px]">
          <div className="flex justify-between">
            <span className="text-fg-faint">Size:</span>
            <span className="font-mono text-fg">{formatBytes(resource.size)}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-fg-faint">Lines:</span>
            <span className="font-mono text-fg">{resource.lineCount}</span>
          </div>
          {resource.modified && (
            <div className="flex justify-between">
              <span className="text-fg-faint">Modified:</span>
              <span className="text-fg">{formatRelativeTime(resource.modified)}</span>
            </div>
          )}
          <div className="flex justify-between">
            <span className="text-fg-faint">Source:</span>
            <Tag 
              size={10} 
              className={resource.source === "overlay" ? "text-warning" : "text-success"}
            />
            <span className={`text-[10px] ${
              resource.source === "overlay" ? "text-warning" : "text-success"
            }`}>
              {resource.source === "overlay" ? "Overlay" : "Actual"}
            </span>
          </div>
        </div>
      </section>
      
      {/* Links To */}
      {resource.linksTo.length > 0 && (
        <section>
          <h3 className="flex items-center gap-2 text-[12px] font-medium text-fg mb-2">
            <LinkIcon size={12} />
            Links To ({resource.linksTo.length})
          </h3>
          <div className="space-y-1">
            {resource.linksTo.map((ref) => (
              <button
                key={ref}
                className="block w-full truncate rounded px-2 py-1 text-left text-[11px] text-accent hover:bg-accent-soft"
              >
                {ref}
              </button>
            ))}
          </div>
        </section>
      )}
      
      {/* Linked By (Backlinks) */}
      {resource.linkedBy.length > 0 && (
        <section>
          <h3 className="flex items-center gap-2 text-[12px] font-medium text-fg mb-2">
            <LinkIcon size={12} className="rotate-180" />
            Linked By ({resource.linkedBy.length})
          </h3>
          <div className="space-y-1">
            {resource.linkedBy.map((ref) => (
              <button
                key={ref}
                className="block w-full truncate rounded px-2 py-1 text-left text-[11px] text-fg-muted hover:bg-hover"
              >
                {ref}
              </button>
            ))}
          </div>
        </section>
      )}
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
  if (diffDays < 7) return `${diffDays}d ago`;
  return date.toLocaleDateString();
}
```

### 3.4 ContentView（中间内容区）增强

**修改文件**：`visualization/src/features/home/HomeContentView.tsx`

**增加编辑模式切换**：
```tsx
import { useState } from "react";
import { Edit2, Eye, Save, X } from "lucide-react";
import { Button } from "../../components/ui/Button";
import { Markdown } from "../../components/markdown/Markdown";

export function HomeContentView({ 
  resource, 
  onSave 
}: {
  resource: HomeResourceMeta;
  onSave: (content: string) => Promise<void>;
}) {
  const [mode, setMode] = useState<"view" | "edit">("view");
  const [content, setContent] = useState(resource.content);
  const [saving, setSaving] = useState(false);
  
  const handleSave = async () => {
    setSaving(true);
    try {
      await onSave(content);
      setMode("view");
    } finally {
      setSaving(false);
    }
  };
  
  return (
    <div className="flex h-full flex-col">
      {/* Toolbar */}
      <div className="flex items-center justify-between border-b border-line bg-bg-elev px-4 py-2">
        <div>
          <h2 className="text-[14px] font-medium text-fg">{resource.title}</h2>
          <div className="font-mono text-[10px] text-fg-faint">{resource.ref}</div>
        </div>
        
        <div className="flex items-center gap-2">
          {mode === "view" ? (
            <Button size="sm" variant="outline" onClick={() => setMode("edit")}>
              <Edit2 size={12} />
              Edit
            </Button>
          ) : (
            <>
              <Button size="sm" variant="ghost" onClick={() => {
                setContent(resource.content);
                setMode("view");
              }}>
                <X size={12} />
                Cancel
              </Button>
              <Button size="sm" onClick={handleSave} disabled={saving}>
                <Save size={12} />
                {saving ? "Saving..." : "Save"}
              </Button>
            </>
          )}
        </div>
      </div>
      
      {/* Content */}
      <div className="flex-1 overflow-y-auto p-4">
        {mode === "view" ? (
          <Markdown className="md-calm">{content}</Markdown>
        ) : (
          <textarea
            value={content}
            onChange={(e) => setContent(e.target.value)}
            className="h-full w-full resize-none rounded-lg border border-line bg-bg px-3 py-2 font-mono text-[12px] focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/20"
          />
        )}
      </div>
    </div>
  );
}
```

---

## 四、Memory 页面优化方案

### 4.1 整体布局重构

**三栏布局 + 类型导航**：
```
┌────────────────────────────────────────────────┐
│ Memory                                         │
├──────────────┬─────────────────┬───────────────┤
│ Type Nav     │ Document List   │ Inspector     │
│ (左 200px)   │ (中 flex-1)     │ (右 280px)    │
│              │                 │               │
│ 📅 Daily (12)│ [文档列表]      │ Metadata      │
│ 👤 Entity (8)│                 │ - Created     │
│ 💡 Concept(5)│                 │ - Modified    │
│ 📌 Fact (45) │                 │               │
│ 📝 Note (23) │                 │ Backlinks     │
│              │                 │ - [...]       │
└──────────────┴─────────────────┴───────────────┘
```

### 4.2 TypeNav（左侧类型导航）新增

**新建文件**：`visualization/src/features/memory/MemoryTypeNav.tsx`

```tsx
import { Calendar, User, Lightbulb, Pin, FileText } from "lucide-react";

interface MemoryType {
  key: "daily" | "entity" | "concept" | "fact" | "note";
  label: string;
  icon: React.ComponentType<{ size: number; className?: string }>;
  color: string;
  count: number;
}

const MEMORY_TYPES: Omit<MemoryType, "count">[] = [
  { key: "daily", label: "Daily", icon: Calendar, color: "text-blue-500" },
  { key: "entity", label: "Entity", icon: User, color: "text-purple-500" },
  { key: "concept", label: "Concept", icon: Lightbulb, color: "text-yellow-500" },
  { key: "fact", label: "Fact", icon: Pin, color: "text-green-500" },
  { key: "note", label: "Note", icon: FileText, color: "text-orange-500" },
];

export function MemoryTypeNav({ 
  counts, 
  selected, 
  onSelect 
}: {
  counts: Record<string, number>;
  selected: string;
  onSelect: (type: string) => void;
}) {
  return (
    <div className="h-full overflow-y-auto border-r border-line bg-bg-sunken/40 p-3">
      {/* 概览卡片 */}
      <div className="rounded-lg border border-line bg-bg-elev px-3 py-2.5 mb-3">
        <div className="text-[13px] font-medium text-fg mb-2">Memory Overview</div>
        <div className="text-[11px] text-fg-muted">
          {Object.values(counts).reduce((a, b) => a + b, 0)} total documents
        </div>
      </div>
      
      {/* 类型列表 */}
      <div className="space-y-1">
        {MEMORY_TYPES.map((type) => {
          const Icon = type.icon;
          const count = counts[type.key] ?? 0;
          const isSelected = selected === type.key;
          
          return (
            <button
              key={type.key}
              onClick={() => onSelect(type.key)}
              className={`
                flex w-full items-center gap-3 rounded-lg px-3 py-2 text-left
                transition-colors
                ${isSelected 
                  ? "bg-accent text-white" 
                  : "text-fg hover:bg-hover"
                }
              `}
            >
              <Icon 
                size={14} 
                className={isSelected ? "text-white" : type.color}
              />
              <span className="flex-1 text-[13px]">{type.label}</span>
              <span className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${
                isSelected 
                  ? "bg-white/20 text-white" 
                  : "bg-fg-faint/10 text-fg-faint"
              }`}>
                {count}
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
```

### 4.3 DocumentList（中间文档列表）新增

**新建文件**：`visualization/src/features/memory/MemoryDocumentList.tsx`

```tsx
import { useState } from "react";
import { Search, SortAsc, SortDesc } from "lucide-react";

interface MemoryDocument {
  ref: string; // memory:entity/john-doe
  title: string;
  preview: string;
  size: number;
  created: string;
  modified: string;
  backlinks: number;
}

export function MemoryDocumentList({ 
  documents, 
  selected, 
  onSelect 
}: {
  documents: MemoryDocument[];
  selected: string | null;
  onSelect: (ref: string) => void;
}) {
  const [search, setSearch] = useState("");
  const [sortBy, setSortBy] = useState<"modified" | "created" | "title">("modified");
  const [sortOrder, setSortOrder] = useState<"asc" | "desc">("desc");
  
  const filtered = documents.filter((doc) =>
    doc.title.toLowerCase().includes(search.toLowerCase())
  );
  
  const sorted = [...filtered].sort((a, b) => {
    const valueA = a[sortBy];
    const valueB = b[sortBy];
    const comparison = typeof valueA === "string" 
      ? valueA.localeCompare(valueB as string)
      : (valueA as number) - (valueB as number);
    return sortOrder === "asc" ? comparison : -comparison;
  });
  
  return (
    <div className="flex h-full flex-col">
      {/* Toolbar */}
      <div className="flex items-center gap-2 border-b border-line bg-bg-elev px-3 py-2">
        <div className="relative flex-1">
          <Search size={13} className="absolute left-2 top-1/2 -translate-y-1/2 text-fg-faint" />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search documents..."
            className="w-full rounded-lg border border-line bg-bg py-1.5 pl-8 pr-3 text-[12px] focus:border-accent focus:outline-none"
          />
        </div>
        
        <button
          onClick={() => setSortOrder(sortOrder === "asc" ? "desc" : "asc")}
          className="rounded p-1 text-fg-muted hover:bg-hover hover:text-fg"
        >
          {sortOrder === "asc" ? <SortAsc size={14} /> : <SortDesc size={14} />}
        </button>
      </div>
      
      {/* Document Cards */}
      <div className="flex-1 overflow-y-auto p-3 space-y-2">
        {sorted.map((doc) => (
          <button
            key={doc.ref}
            onClick={() => onSelect(doc.ref)}
            className={`
              block w-full rounded-lg border px-3 py-2.5 text-left
              transition-all
              ${selected === doc.ref
                ? "border-accent bg-accent-soft/40 shadow-[0_0_0_1px_rgba(129,140,248,0.3)]"
                : "border-line bg-bg-elev hover:border-accent/30 hover:bg-accent-soft/10"
              }
            `}
          >
            <div className="font-medium text-[13px] text-fg mb-1">
              {doc.title}
            </div>
            <div className="text-[11px] text-fg-muted line-clamp-2 mb-2">
              {doc.preview}
            </div>
            <div className="flex items-center gap-3 text-[10px] text-fg-faint">
              <span>{formatRelativeTime(doc.modified)}</span>
              {doc.backlinks > 0 && (
                <>
                  <span>·</span>
                  <span>{doc.backlinks} backlinks</span>
                </>
              )}
              <span>·</span>
              <span className="font-mono">{formatBytes(doc.size)}</span>
            </div>
          </button>
        ))}
        
        {sorted.length === 0 && (
          <div className="flex h-full items-center justify-center text-[12px] text-fg-faint">
            No documents found
          </div>
        )}
      </div>
    </div>
  );
}
```

### 4.4 MemoryInspector（右侧面板）新增

**新建文件**：`visualization/src/features/memory/MemoryInspector.tsx`

```tsx
import { Clock, Link as LinkIcon, FileText, Tag } from "lucide-react";

interface MemoryDocumentMeta {
  ref: string;
  title: string;
  type: "daily" | "entity" | "concept" | "fact" | "note";
  size: number;
  created: string;
  modified: string;
  tags?: string[];
  linksTo: string[];
  linkedBy: Array<{ ref: string; title: string; context?: string }>;
}

export function MemoryInspector({ document }: { document: MemoryDocumentMeta | null }) {
  if (!document) {
    return (
      <div className="flex h-full items-center justify-center border-l border-line bg-bg-sunken/20 p-4">
        <div className="text-center text-[12px] text-fg-faint">
          Select a document to view details
        </div>
      </div>
    );
  }
  
  return (
    <div className="h-full overflow-y-auto border-l border-line bg-bg-sunken/20 p-4 space-y-4">
      {/* Metadata */}
      <section>
        <h3 className="flex items-center gap-2 text-[12px] font-medium text-fg mb-2">
          <FileText size={12} />
          Metadata
        </h3>
        <div className="space-y-1.5 text-[11px]">
          <div className="flex justify-between">
            <span className="text-fg-faint">Type:</span>
            <TypeBadge type={document.type} />
          </div>
          <div className="flex justify-between">
            <span className="text-fg-faint">Size:</span>
            <span className="font-mono text-fg">{formatBytes(document.size)}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-fg-faint">Created:</span>
            <span className="text-fg">{formatRelativeTime(document.created)}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-fg-faint">Modified:</span>
            <span className="text-fg">{formatRelativeTime(document.modified)}</span>
          </div>
        </div>
      </section>
      
      {/* Tags */}
      {document.tags && document.tags.length > 0 && (
        <section>
          <h3 className="flex items-center gap-2 text-[12px] font-medium text-fg mb-2">
            <Tag size={12} />
            Tags
          </h3>
          <div className="flex flex-wrap gap-1.5">
            {document.tags.map((tag) => (
              <span
                key={tag}
                className="rounded-full bg-accent-soft px-2 py-0.5 text-[10px] text-accent"
              >
                {tag}
              </span>
            ))}
          </div>
        </section>
      )}
      
      {/* Backlinks */}
      {document.linkedBy.length > 0 && (
        <section>
          <h3 className="flex items-center gap-2 text-[12px] font-medium text-fg mb-2">
            <LinkIcon size={12} className="rotate-180" />
            Backlinks ({document.linkedBy.length})
          </h3>
          <div className="space-y-2">
            {document.linkedBy.map((link) => (
              <button
                key={link.ref}
                className="block w-full rounded-lg border border-line bg-bg-elev px-2.5 py-2 text-left hover:border-accent/30 hover:bg-accent-soft/10"
              >
                <div className="truncate text-[11px] font-medium text-fg">
                  {link.title}
                </div>
                {link.context && (
                  <div className="line-clamp-2 text-[10px] text-fg-muted mt-1">
                    {link.context}
                  </div>
                )}
              </button>
            ))}
          </div>
        </section>
      )}
      
      {/* Links To */}
      {document.linksTo.length > 0 && (
        <section>
          <h3 className="flex items-center gap-2 text-[12px] font-medium text-fg mb-2">
            <LinkIcon size={12} />
            Links To ({document.linksTo.length})
          </h3>
          <div className="space-y-1">
            {document.linksTo.map((ref) => (
              <div
                key={ref}
                className="truncate rounded px-2 py-1 text-[11px] font-mono text-fg-muted hover:bg-hover"
              >
                {ref}
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}

function TypeBadge({ type }: { type: string }) {
  const config = {
    daily: { label: "Daily", color: "text-blue-500 bg-blue-500/10" },
    entity: { label: "Entity", color: "text-purple-500 bg-purple-500/10" },
    concept: { label: "Concept", color: "text-yellow-500 bg-yellow-500/10" },
    fact: { label: "Fact", color: "text-green-500 bg-green-500/10" },
    note: { label: "Note", color: "text-orange-500 bg-orange-500/10" },
  }[type] ?? { label: type, color: "text-fg-faint bg-fg-faint/10" };
  
  return (
    <span className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${config.color}`}>
      {config.label}
    </span>
  );
}
```

### 4.5 Daily Memory 时间线视图（可选增强）

**新建文件**：`visualization/src/features/memory/DailyTimeline.tsx`

```tsx
import { Calendar } from "lucide-react";

interface DailyEntry {
  date: string; // YYYY-MM-DD
  ref: string;  // memory:daily/YYYY-MM-DD
  entryCount: number;
  size: number;
}

export function DailyTimeline({ 
  entries, 
  selected, 
  onSelect 
}: {
  entries: DailyEntry[];
  selected: string | null;
  onSelect: (ref: string) => void;
}) {
  // 按月份分组
  const grouped = entries.reduce((acc, entry) => {
    const month = entry.date.slice(0, 7); // YYYY-MM
    if (!acc[month]) acc[month] = [];
    acc[month].push(entry);
    return acc;
  }, {} as Record<string, DailyEntry[]>);
  
  return (
    <div className="space-y-4">
      {Object.entries(grouped).reverse().map(([month, monthEntries]) => (
        <div key={month}>
          <div className="flex items-center gap-2 text-[12px] font-medium text-fg mb-2">
            <Calendar size={12} />
            {formatMonth(month)}
          </div>
          <div className="space-y-1">
            {monthEntries.map((entry) => (
              <button
                key={entry.ref}
                onClick={() => onSelect(entry.ref)}
                className={`
                  flex w-full items-baseline justify-between rounded-lg px-3 py-2 text-left
                  transition-colors
                  ${selected === entry.ref
                    ? "border border-accent bg-accent-soft/40"
                    : "border border-line bg-bg-elev hover:border-accent/30"
                  }
                `}
              >
                <div>
                  <div className="text-[13px] font-medium text-fg">
                    {formatDate(entry.date)}
                  </div>
                  <div className="text-[10px] text-fg-faint">
                    {entry.entryCount} entries · {formatBytes(entry.size)}
                  </div>
                </div>
              </button>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

function formatMonth(month: string): string {
  const date = new Date(month + "-01");
  return date.toLocaleDateString("en-US", { year: "numeric", month: "long" });
}

function formatDate(dateStr: string): string {
  const date = new Date(dateStr);
  return date.toLocaleDateString("en-US", { 
    month: "short", 
    day: "numeric",
    weekday: "short"
  });
}
```

---

## 五、实施优先级与工作量

### P0：Home 页面核心重构（3 天）

| 任务 | 时间 | 难度 |
|------|------|------|
| 创建 HomeNavigator | 4h | 中 |
| 创建 HomeInspector | 3h | 中 |
| 增强 HomeContentView（编辑模式） | 3h | 中 |
| 集成三栏布局 | 2h | 低 |
| API 对接（资源列表、元信息、引用关系） | 4h | 中 |
| 测试与调整 | 3h | - |
| **小计** | **19h ≈ 3 天** | |

### P1：Memory 页面核心重构（3 天）

| 任务 | 时间 | 难度 |
|------|------|------|
| 创建 MemoryTypeNav | 2h | 低 |
| 创建 MemoryDocumentList | 4h | 中 |
| 创建 MemoryInspector | 3h | 中 |
| 创建 DailyTimeline（可选） | 3h | 中 |
| 集成三栏布局 | 2h | 低 |
| API 对接（文档列表、元信息、backlinks） | 4h | 中 |
| 测试与调整 | 3h | - |
| **小计** | **21h ≈ 3.5 天** | |

### P2：可选增强（按需）

- 图谱视图（使用 react-flow 或 d3）
- 全文搜索
- 批量编辑
- 导出功能

### 总计：6-7 个工作日

---

## 六、预期效果对比

### 6.1 Home 页面

**改进前**：
```
┌─────────────────┐
│ Home            │
├─────────────────┤
│ • identity      │
│ • domain:ws     │
│ • action:edit   │
│                 │
│ [编辑器]        │
└─────────────────┘
```

**改进后**：
```
┌────────────────────────────────────────┐
│ Home · Effective                       │
├───────────┬────────────────┬───────────┤
│ Navigator │ Content        │ Inspector │
│           │                │           │
│ Overview  │ # Identity     │ Metadata  │
│ 5 res     │ You are...     │ 1.2 KB    │
│ 12.8 KB   │                │ 45 lines  │
│           │ [Edit/Save]    │           │
│ Resources │                │ Links To  │
│ • identity│                │ - ws:edit │
│ • domains/│                │           │
│   - ws    │                │ Linked By │
│   - mem   │                │ - phase2  │
└───────────┴────────────────┴───────────┘
```

### 6.2 Memory 页面

**改进前**：
```
┌─────────────────┐
│ Memory          │
├─────────────────┤
│ • Daily         │
│ • Entity        │
│ • Concept       │
│                 │
│ [文档内容]      │
└─────────────────┘
```

**改进后**：
```
┌────────────────────────────────────────┐
│ Memory                                 │
├───────────┬────────────────┬───────────┤
│ Type Nav  │ Document List  │ Inspector │
│           │                │           │
│ 📅 Daily  │ [Search...]    │ Metadata  │
│    (12)   │                │ Type:     │
│           │ ┌────────────┐ │ Entity    │
│ 👤 Entity │ │ John Doe   │ │           │
│    (8)    │ │ Software   │ │ Backlinks │
│           │ │ engineer...│ │ - proj A  │
│ 💡 Concept│ └────────────┘ │ - task B  │
│    (5)    │                │           │
│           │ ┌────────────┐ │ Links To  │
│ 📌 Fact   │ │ Jane Smith │ │ - concept │
│    (45)   │ │ Product... │ │           │
└───────────┴────────────────┴───────────┘
```

---

## 七、验收标准

### 功能验收

#### Home 页面
- [ ] Navigator 正确显示资源树
- [ ] 资源分层（root/domain/action）清晰
- [ ] Inspector 显示正确的元信息
- [ ] 引用关系（links to / linked by）正确
- [ ] 编辑模式与查看模式切换流畅
- [ ] 保存后正确更新资源

#### Memory 页面
- [ ] TypeNav 显示五种类型及数量
- [ ] DocumentList 支持搜索和排序
- [ ] Inspector 显示正确的 backlinks
- [ ] 点击 backlink 可以跳转到对应文档
- [ ] Daily Timeline（如果实现）按月份分组

### 视觉验收
- [ ] 三栏布局在不同窗口尺寸下正常
- [ ] 类型图标和颜色一致
- [ ] 卡片 hover/选中状态明确
- [ ] 编辑器与预览样式协调

### 性能验收
- [ ] 大量文档（100+）时列表流畅
- [ ] 搜索响应及时（< 300ms）
- [ ] 切换文档无明显延迟

---

## 八、后端 API 需求

### Home API 增强

**需要提供的额外数据**：
```typescript
// GET /api/v2/home/manifest
{
  resources: [
    {
      ref: "home:agent@identity",
      title: "Agent Identity",
      type: "root" | "domain" | "action",
      size: 1234,
      line_count: 45,
      modified: "2026-10-05T10:30:00Z",
      source: "actual" | "overlay",
      links_to: ["home:skills_domain:workspace"],
      linked_by: ["home:skills_action:workspace/edit"]
    }
  ]
}
```

### Memory API 增强

**需要提供的额外数据**：
```typescript
// GET /api/v2/memory/documents
{
  documents: [
    {
      ref: "memory:entity/john-doe",
      title: "John Doe",
      type: "entity",
      preview: "Software engineer...",
      size: 2345,
      created: "2026-09-01T00:00:00Z",
      modified: "2026-10-05T12:00:00Z",
      tags: ["team", "engineering"],
      links_to: ["memory:concept/agile"],
      linked_by: [
        {
          ref: "memory:fact/project-a",
          title: "Project A",
          context: "... mentioned John Doe as the lead ..."
        }
      ]
    }
  ]
}
```

**如果后端暂时无法提供**：
- 可以先在前端 mock 数据
- 或者从现有 API 中解析和计算

---

## 九、风险评估

### 低风险
- ✅ 布局重构不影响现有功能
- ✅ 可以逐步迁移，保留旧版作为后备

### 中风险
- ⚠️ 引用关系解析可能复杂
  - **缓解**：从简单的 `[[link]]` 语法开始
- ⚠️ Backlinks 计算可能耗时
  - **缓解**：后端预计算并缓存

### 高风险
- 🔴 大量文档时性能问题
  - **缓解**：使用虚拟滚动（react-window）
  - **缓解**：分页加载文档列表

---

**执行状态**：待开始

**预计完成时间**：6-7 个工作日

**负责人**：GPT Agent（实施）+ Claude（审查）

**依赖**：后端 API 增强（可选，可先 mock）
