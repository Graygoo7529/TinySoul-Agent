# Visualization 主对话与 Context 核心优化执行计划

日期：2026-10-05

状态：部分完成（阶段一已完成，阶段二、三待执行）

基于：代码实际检查与深度分析的综合方案

---

## 执行进度

- [x] **阶段一：WaitingResponseDock 优化**（已完成，2026-10-05）
  - [x] 背景模糊增强（blur 2px → 16px）
  - [x] 收起/展开功能
  - [x] Markdown 渲染支持
  - [x] 弹簧动画优化
  - [x] 后端约束适配
  - [x] 细节修复（补充想法、选项框、编号等）
  - 📄 详见：`docs/analysis/done/20261005-done-WaitingResponseDock完整优化.md`

- [ ] **阶段二：ActivityGlimpse 视觉增强**（待执行）
  - [ ] Plan/Result 容器样式区分
  - [ ] 状态图标（✓/✗/⚠）
  - [ ] 参数格式化改进

- [ ] **阶段三：Context 资源目录紧凑化**（待执行）
  - [ ] ResourceDirectoryRow 组件
  - [ ] BackgroundPanel 改造

---

## 一、当前情况分析

### 1.1 已完成的改进（commit 971b810）

GPT Agent 在最新提交中已经完成了以下工作：

#### WaitingResponseDock 已实现
**位置**：`visualization/src/features/chat/WaitingResponseDock.tsx`

**实现内容**：
- 创建了独立的 `WaitingResponseDock` 组件
- 使用绝对定位在 `ChatView` 底部 (`absolute inset-x-0 bottom-0`)
- 添加了背景模糊效果 (`backdrop-blur-md`)
- 包含渐变遮罩 (`waiting-dock-scrim`)
- 集成了 `QuestionCard` 组件，支持 `commentAsBubble` 模式

**ChatView 集成**：
```tsx
// ChatView.tsx:78-86
export function ChatView() {
  return (
    <div className="relative flex h-full min-h-0 flex-col">
      <div className="min-h-0 flex-1"><ConversationView /></div>
      <Composer />
      <WaitingResponseDock />  // ← 已添加
    </div>
  );
}
```

#### 设计 Token 系统已建立
**位置**：`visualization/src/styles/index.css`

**新增内容**：
- Domain 主题色系统（core/workspace/execution/web/home/memory/maintenance）
- 完善的 light/dark 主题变量
- 阴影层级系统（shadow-card/shadow-pop/shadow-brand）
- 选中光泽效果（--selection-glow）
- Terminal 样式系统

#### ActivityGlimpse 已优化
**位置**：`visualization/src/features/chat/ActivityGlimpse.tsx`

**改进内容**：
- Plan 和 Result 在 `glimpseBody` 中有不同分支
- 失败状态有独立处理（L70-72）
- 增加了更丰富的格式化逻辑（diff/terminal/search/write）

### 1.2 存在的问题与改进空间

#### 问题 A：WaitingResponseDock 的布局问题

**当前实现的问题**：
```tsx
// WaitingResponseDock.tsx:40-41
<div className="waiting-dock-root absolute inset-x-0 bottom-0 z-(--z-overlay) pointer-events-none">
  <div className="waiting-dock-scrim pointer-events-none absolute inset-x-0 bottom-0 h-[min(70vh,34rem)]" />
```

1. **定位不正确**：使用 `absolute bottom-0` 在 `ChatView` 内部，但 `ChatView` 已经是 `relative` 容器，导致 Dock 会覆盖 `Composer`
2. **层级混乱**：`z-(--z-overlay)` 的语法不正确，应该是 `z-[var(--z-overlay)]`
3. **与 Composer 冲突**：当前布局中，Dock 和 Composer 都在底部，会产生重叠

**正确的布局应该是**：
```
ChatView (flex flex-col)
  ├─ ConversationView (flex-1)
  ├─ WaitingResponseDock (固定高度，在 Composer 上方)
  └─ Composer (固定高度)
```

#### 问题 B：ActivityGlimpse 的视觉区分不够

**当前实现**：
```tsx
// ActivityGlimpse.tsx:43-94
export function glimpseBody(data: ActionGlimpseData) {
  // Plan 和 Result 在同一个函数内
  if (data.stage === "plan") {
    // ... plan 逻辑
  }
  if (data.result?.status === "failure" || data.result?.status === "timeout") {
    // ... failure 逻辑
  }
  // ... result 逻辑
}
```

**问题点**：
1. Plan 和 Result 使用相同的容器样式（`border-line/70 bg-bg-sunken/70`）
2. 缺少状态主题色（success/failure/timeout）
3. 参数格式化还不够直观（特别是 workspace 和 execution 系列）
4. 缺少视觉上的"计划 vs 实际"对比感

#### 问题 C：Context 资源仍然默认展开

**当前实现**：`BackgroundPanel.tsx` 和 `ChunkedMarkdown.tsx`

**问题**：
- 资源内容仍然完整渲染
- 没有紧凑的目录行
- 首屏信息量过大

---

## 二、优化执行计划

### ~~阶段一：WaitingResponseDock 优化~~（✅ 已完成）

**完成日期**：2026-10-05

**实际完成内容**：

#### ✅ 任务 1.1：背景模糊与收起功能
- 背景模糊从 2px 提升到 16px，增加渐变遮罩
- 顶部控制栏可收起卡片
- 收起后显示紧凑提示条（~48px）
- 用户可以滚动查看对话历史和 LiveStatus

#### ✅ 任务 1.2：Markdown 渲染支持
- 问题文本支持 Markdown 格式
- 加粗、斜体、列表、代码、链接
- 紧凑样式不占用过多空间

#### ✅ 任务 1.3：弹簧动画优化
- 使用 spring 参数（damping: 25, stiffness: 300）
- 自然的物理感和轻微回弹

#### ✅ 任务 1.4：后端约束适配
- 分析后端 QuestionAnswer 类型约束
- TEXT 类型禁止 comment，CHOICE 类型禁止 text
- Comment 输入框条件显示（输入 Other 时自动隐藏）

#### ✅ 任务 1.5：细节优化
- 补充想法从气泡改为卡片内斜体引用（图标+左边框+渐变背景）
- Readonly 选项框用框 + 字母标签 + 勾选标记
- 自定义输入也有字母编号（下一个字母）
- 等待期间隐藏 Composer
- 选项间距优化（问题到选项 16px，选项间距 6px）
- 选项 hover 光晕和选中内层光泽
- 顶部装饰光泽条
- 移除 "answered" 文本
- 补充想法不显示引号

#### 验收结果 ✅

- [x] Dock 正确定位，不与 Composer 冲突
- [x] 背景模糊效果明显（blur 16px）
- [x] 收起/展开功能正常
- [x] Markdown 渲染支持完整
- [x] 弹簧动画流畅自然
- [x] 后端约束适配正确
- [x] 所有细节优化完成

**详细文档**：`docs/analysis/done/20261005-done-WaitingResponseDock完整优化.md`

---

---

### 阶段二：增强 ActivityGlimpse 视觉区分（优先级：P0）

#### 目标
让 Plan 和 Result 有明确的视觉差异，增加状态主题色，改进参数格式化

#### 任务 2.1：拆分 Plan 和 Result 的容器样式

**修改文件**：`visualization/src/features/chat/ActivityGlimpse.tsx`

**当前代码**（L35-36）：
```tsx
<Crossfade id={`${data.callId}:${data.stage}`} className="mt-1 rounded-lg border border-line/70 bg-bg-sunken/70 px-2.5 py-1.5">
```

**修改为根据 stage 动态样式**：
```tsx
<Crossfade 
  id={`${data.callId}:${data.stage}`} 
  className={`mt-1 rounded-lg px-2.5 py-1.5 ${getGlimpseStyle(data)}`}
>
```

**新增辅助函数**：
```tsx
function getGlimpseStyle(data: ActionGlimpseData): string {
  if (data.stage === "plan") {
    return "border border-line/70 bg-bg-sunken/70";
  }
  
  // Result 阶段根据状态变化
  const status = data.result?.status;
  if (status === "success") {
    return "border border-success/30 bg-success-soft/10";
  }
  if (status === "failure") {
    return "border border-danger/30 bg-danger-soft/20";
  }
  if (status === "timeout") {
    return "border border-warning/30 bg-warning-soft/20";
  }
  
  return "border border-line/70 bg-bg-sunken/70";
}
```

#### 任务 2.2：增加状态图标

**在 ActivityGlimpse.tsx 中新增组件**：
```tsx
import { Check, XCircle, AlertTriangle, Circle } from "lucide-react";

function StatusIcon({ status }: { status?: string }) {
  if (status === "success") {
    return <Check size={13} className="text-success" />;
  }
  if (status === "failure") {
    return <XCircle size={13} className="text-danger" />;
  }
  if (status === "timeout") {
    return <AlertTriangle size={13} className="text-warning" />;
  }
  return null;
}
```

**在 glimpseBody 中使用**：
```tsx
export function glimpseBody(data: ActionGlimpseData) {
  // ... 原有逻辑
  
  // 在 Result 阶段，顶部增加状态行
  if (data.stage === "result") {
    const status = data.result?.status;
    const statusLabel = status === "success" ? "Success" 
      : status === "failure" ? "Failed"
      : status === "timeout" ? "Timeout"
      : "Completed";
    
    return (
      <div className="space-y-1.5">
        <div className="flex items-center gap-2">
          <StatusIcon status={status} />
          <span className="text-[12px] font-medium text-fg">{statusLabel}</span>
          <span className="ml-auto font-mono text-[10px] text-fg-faint">
            {shortActionName(data.actionId)}
          </span>
        </div>
        
        {/* 失败反馈 */}
        {status === "failure" && data.failure?.feedback && (
          <div className="text-[11px] text-danger/90">{data.failure.feedback}</div>
        )}
        
        {/* 原有的结果内容 */}
        {/* ... 原有的 payload 处理逻辑 */}
      </div>
    );
  }
  
  // Plan 阶段保持原有逻辑
  // ...
}
```

#### 任务 2.3：改进参数格式化

**增强 workspace 系列的格式化**：
```tsx
// 在 glimpseBody 的 plan 分支中
if (data.actionId.startsWith("workspace.")) {
  const target = asString(params.target_link) ?? asString(params.path);
  const edits = Array.isArray(params.edits) ? params.edits.length : 1;
  
  return (
    <div className="space-y-1">
      {target && (
        <div className="flex items-baseline gap-2 text-[11px]">
          <span className="text-fg-faint">Target:</span>
          <span className="font-mono text-fg truncate">{target}</span>
        </div>
      )}
      <div className="flex items-baseline gap-2 text-[11px]">
        <span className="text-fg-faint">Changes:</span>
        <span className="text-fg">{edits} {edits === 1 ? "edit" : "edits"}</span>
      </div>
      {patches.length > 0 && <DiffGlimpse {...patches[0]} />}
    </div>
  );
}
```

**增强 execution 系列的结果格式化**：
```tsx
// 在 TerminalGlimpse 之前增加简要信息
function TerminalSummary({ payload }: { payload: Record<string, unknown> }) {
  const exitCode = asNumber(payload.exit_code);
  const stdoutLines = asString(payload.stdout)?.split("\n").length ?? 0;
  const stderrLines = asString(payload.stderr)?.split("\n").length ?? 0;
  const totalLines = stdoutLines + stderrLines;
  
  return (
    <div className="flex items-center gap-3 text-[11px]">
      {exitCode !== null && (
        <span className={exitCode === 0 ? "text-success" : "text-danger"}>
          exit code {exitCode}
        </span>
      )}
      {totalLines > 0 && (
        <span className="text-fg-faint">{totalLines} lines output</span>
      )}
    </div>
  );
}
```

#### 验收标准

- [ ] Plan 卡片：灰色边框 + 灰色背景
- [ ] Result 卡片（success）：绿色边框 + 浅绿背景
- [ ] Result 卡片（failure）：红色边框 + 浅红背景
- [ ] Result 卡片（timeout）：橙色边框 + 浅橙背景
- [ ] Result 显示状态图标（✓ / ✗ / ⚠）
- [ ] workspace.edit plan 显示 "Target: file.ts · Changes: 2 edits"
- [ ] execution.shell result 显示 "exit code 0 · 15 lines output"

---

### 阶段三：Context 资源目录紧凑化（优先级：P1）

#### 目标
把 BackgroundPanel 改为紧凑的资源目录行，默认折叠，首屏一览所有资源

#### 任务 3.1：创建 ResourceDirectoryRow 组件

**新建文件**：`visualization/src/features/context/ResourceDirectoryRow.tsx`

```tsx
import { useState } from "react";
import { ChevronRight } from "lucide-react";
import { Badge } from "../../components/ui/Badge";
import { Markdown } from "../../components/markdown/Markdown";
import type { BackgroundResource } from "../../api/v2/types";
import type { MarkdownOrigin } from "../../components/markdown/origin";

interface ResourceMeta {
  title: string;
  ref: string;
  source: string;
  sizeBytes: number;
  lineCount: number;
  preview: string;
}

function parseResourceMeta(resource: BackgroundResource): ResourceMeta {
  // 提取标题
  let title = resource.title;
  if (!title || title === resource.ref) {
    const match = resource.content.match(/^#\s+(.+)$/m);
    title = match?.[1] ?? resource.ref;
  }
  
  // 计算元信息
  const sizeBytes = new Blob([resource.content]).size;
  const lineCount = resource.content.split("\n").length;
  const contentWithoutTitle = resource.content.replace(/^#\s+.+$/m, "").trim();
  const preview = contentWithoutTitle.slice(0, 80);
  
  return { 
    title, 
    ref: resource.ref, 
    source: resource.source, 
    sizeBytes, 
    lineCount, 
    preview 
  };
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function getSourceBadge(source: string) {
  return {
    default: { bg: "bg-accent-soft/20", text: "text-accent" },
    automatic: { bg: "bg-blue-500/10", text: "text-blue-500" },
    phase1: { bg: "bg-warning-soft/20", text: "text-warning" },
  }[source] ?? { bg: "bg-fg-faint/10", text: "text-fg-faint" };
}

export function ResourceDirectoryRow({
  resource,
  origin,
}: {
  resource: BackgroundResource;
  origin: MarkdownOrigin;
}) {
  const [expanded, setExpanded] = useState(false);
  const meta = parseResourceMeta(resource);
  const sourceBadge = getSourceBadge(meta.source);
  
  return (
    <div className="overflow-hidden rounded-lg border border-line bg-bg-elev shadow-sm">
      {/* 可点击的头部 */}
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex w-full items-start gap-2 px-3 py-2.5 text-left transition-colors hover:bg-hover"
      >
        {/* 折叠图标 */}
        <ChevronRight
          size={13}
          className={`mt-0.5 shrink-0 text-fg-faint transition-transform ${
            expanded ? "rotate-90" : ""
          }`}
        />
        
        {/* 内容区 */}
        <div className="min-w-0 flex-1 space-y-1">
          {/* 标题行 */}
          <div className="flex items-baseline gap-2">
            <span className="font-medium text-[13px] text-fg truncate max-w-[70%]">
              {meta.title}
            </span>
            <Badge 
              size="xs" 
              className={`${sourceBadge.bg} ${sourceBadge.text} shrink-0`}
            >
              {meta.source}
            </Badge>
          </div>
          
          {/* 信息行 */}
          <div className="flex items-center gap-2 text-[10px] text-fg-faint">
            <span className="font-mono truncate">{meta.ref}</span>
            <span>·</span>
            <span>{formatBytes(meta.sizeBytes)}</span>
            <span>·</span>
            <span>{meta.lineCount} lines</span>
          </div>
          
          {/* 预览行（仅折叠时） */}
          {!expanded && meta.preview && (
            <div className="text-[11px] text-fg-muted truncate">
              {meta.preview}
            </div>
          )}
        </div>
      </button>
      
      {/* 展开的正文 */}
      {expanded && (
        <div className="border-t border-line/60">
          <div className="px-3 py-3">
            <Markdown origin={origin} className="md-calm text-[12px]">
              {resource.content}
            </Markdown>
          </div>
        </div>
      )}
    </div>
  );
}
```

#### 任务 3.2：修改 BackgroundPanel 使用新组件

**修改文件**：`visualization/src/features/context/BackgroundPanel.tsx`

**找到资源渲染部分并修改为**：
```tsx
import { ResourceDirectoryRow } from "./ResourceDirectoryRow";

export function BackgroundPanel({ epoch, turnId, day, owner, ... }) {
  const resources = data?.items.filter((item) => item.owner === owner) ?? [];
  const origin = { link: "", turnId, day, view: "history" as const };
  
  return (
    <div className="space-y-2">
      {/* 顶部元信息 */}
      {resources.length > 0 && (
        <div className="flex items-baseline justify-between text-[11px] text-fg-faint px-1">
          <span>{resources.length} resources</span>
          <span>
            {formatBytes(resources.reduce((sum, r) => sum + new Blob([r.content]).size, 0))}
          </span>
        </div>
      )}
      
      {/* 资源目录 */}
      {resources.map((item) => (
        <ResourceDirectoryRow
          key={item.ref}
          resource={item}
          origin={{ ...origin, link: item.ref }}
        />
      ))}
      
      {/* 空状态 */}
      {resources.length === 0 && (
        <EmptyState
          title={`No ${owner === "home" ? "Home" : "Memory"} loaded`}
          description="This turn did not load content from this source."
        />
      )}
    </div>
  );
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
```

#### 验收标准

- [ ] 默认所有资源折叠
- [ ] 每个资源显示：标题、ref、大小、行数、预览
- [ ] 点击任意位置展开/折叠
- [ ] 展开时显示完整 Markdown
- [ ] 多个资源可以同时展开
- [ ] 来源标签有不同颜色（default/automatic/phase1）
- [ ] 首屏可见全部资源概览

---

## 三、预期效果对比

### 3.1 WaitingResponseDock

**改进前**：
```
┌─ ConversationView ─┐
│ [对话内容...]      │
│                    │
│ [Question 可能在   │  ← 可能滚出视口
│  这里，需要滚动]   │
└────────────────────┘
│ Composer           │
│ [Dock 覆盖这里?]   │  ← 布局混乱
```

**改进后**：
```
┌─ ConversationView ─┐
│ [对话内容...]      │
│ 可自由滚动         │
├════════════════════┤ ← 固定分界
│ WaitingDock        │
│ • 背景模糊         │
│ • 选项外晕/光泽    │
│ • 始终可见         │
├────────────────────┤
│ Composer           │
└────────────────────┘
```

### 3.2 ActivityGlimpse

**改进前**：
```
┌──────────────────┐
│ workspace.edit   │  ← Plan 和 Result 难以区分
│ old: "text..."   │
│ new: "text..."   │
│ +5 / -2          │
└──────────────────┘
```

**改进后 - Plan**：
```
┌──────────────────┐  灰色边框
│ Target: file.ts  │
│ Changes: 2 edits │
│ +5 / -2 lines    │
└──────────────────┘
```

**改进后 - Result (Success)**：
```
┌──────────────────┐  绿色边框 + 浅绿背景
│ ✓ Success        │
│ Written 1 file   │
│ +45 / -12 lines  │
└──────────────────┘
```

**改进后 - Result (Failure)**：
```
┌──────────────────┐  红色边框 + 浅红背景
│ ✗ Failed         │
│ File not found   │
└──────────────────┘
```

### 3.3 Context 资源目录

**改进前**：
```
┌─ Home ─────────────┐
│ Agent Identity     │  ↑
│ home:agent@id      │  │
│                    │  │
│ # Agent Identity   │  │ 几千行内容
│ You are TinySoul...│  │ 需要滚动很长
│ [100+ lines...]    │  ↓
│                    │
│ Domain: workspace  │
│ [又是几十行...]    │
└────────────────────┘
```

**改进后**：
```
┌─ Home ─────────────┐
│ 5 resources · 12 KB│  ← 总览
│                    │
│ ⊕ Agent Identity   │  ← 紧凑行
│   1.2 KB · 45 lines│
│   Defines agent... │
│                    │
│ ⊕ Domain: workspace│
│   0.8 KB · 28 lines│
│   File operations..│
│                    │
│ ⊕ Action: edit     │
│   0.5 KB · 18 lines│
│   Modify files...  │
└────────────────────┘

所有资源一屏可见 ✓
```

---

## 四、实施顺序与工作量

### ✅ 阶段一：WaitingResponseDock（已完成）

| 任务 | 预估 | 实际 | 状态 |
|------|------|------|------|
| 背景模糊与收起功能 | 4h | 4h | ✅ |
| Markdown 渲染支持 | 2h | 2h | ✅ |
| 后端分析与适配 | - | 2h | ✅ |
| 细节优化与修复 | - | 8h | ✅ |
| **小计** | **6h** | **16h ≈ 2天** | ✅ |

### 优先级 P0（待执行，1.5 天）

| 任务 | 时间 | 难度 |
|------|------|------|
| 2.1 拆分 Glimpse 容器样式 | 1h | 低 |
| 2.2 增加状态图标 | 1.5h | 低 |
| 2.3 改进参数格式化 | 2h | 中 |
| 测试与调整 | 1h | - |
| **小计** | **5.5h ≈ 1 天** | |

### 优先级 P1（待执行，1 天）

| 任务 | 时间 | 难度 |
|------|------|------|
| 3.1 创建 ResourceDirectoryRow | 3h | 中 |
| 3.2 修改 BackgroundPanel | 1.5h | 低 |
| 测试与调整 | 1.5h | - |
| **小计** | **6h ≈ 1 天** | |

### 剩余工作量：2 个工作日

---

## 五、风险评估与注意事项

### 低风险
- ✅ 纯前端改进，不依赖后端
- ✅ 不改变数据流和状态管理
- ✅ 可随时回退

### 中风险
- ⚠️ WaitingResponseDock 布局调整可能影响现有交互
  - **缓解**：充分测试不同窗口尺寸
- ⚠️ ActivityGlimpse 样式改动可能影响现有视觉一致性
  - **缓解**：保持现有动画和过渡效果

### 测试检查清单

#### 功能测试
- [ ] 不同窗口尺寸下 Dock 正常显示
- [ ] 长对话时 Dock 不被遮挡
- [ ] Plan 和 Result 卡片渲染正确
- [ ] 资源目录展开/折叠正常

#### 兼容性测试
- [ ] 测试 `prefers-reduced-motion` 模式
- [ ] 测试键盘导航
- [ ] 测试触摸设备交互

#### 视觉测试
- [ ] Light/Dark 主题均正常
- [ ] 各状态颜色对比度达标
- [ ] 动画流畅无卡顿

---

## 六、后续可选优化

完成核心改进后，可以考虑：

1. **ProcessPanel 三级展开**（已在另一份执行计划中）
2. **Settings 页面优化**（独立执行计划）
3. **Home/Memory 页面优化**（独立执行计划）
4. **Workspace 页面优化**（独立执行计划）

---

**执行状态**：部分完成（阶段一 ✅，阶段二、三待执行）

**预计剩余时间**：2 个工作日

**已完成时间**：2 个工作日（2026-10-05）

**负责人**：Claude（实施与审查）
