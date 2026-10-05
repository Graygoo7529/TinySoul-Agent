# Visualization WaitingResponseDock 完整优化执行计划

日期：2026-10-05

状态：待执行（修订版）

---

## 一、设计澄清与问题重新分析

### 1.1 设计意图确认

基于你的反馈，我重新理解了设计意图：

**✅ 正确理解**：
1. **等待回答卡片覆盖 Composer 是预期设计**
   - 等待期间不需要用户通过 Composer 输入
   - 卡片自身提供选项和补充想法输入

2. **背景模糊处理**
   - 等待卡片出现后，卡片后面的背景（ConversationView + LiveStatus）应该模糊
   - 不是卡片本身模糊，而是卡片下方的内容模糊

3. **可收起功能**
   - 卡片顶部增加"向下收回"控制
   - 收起后用户可以滚动查看对话历史和 LiveStatus
   - 需要时可以再展开

4. **问题文本渲染**
   - `question.text` 应该支持 Markdown 渲染
   - 当前只是纯文本显示（L113-114 in QuestionForm.tsx）

### 1.2 当前实现的问题

#### 问题 A：背景模糊效果不够明显

**当前实现**（WaitingResponseDock.tsx:41）：
```tsx
<div className="waiting-dock-scrim pointer-events-none absolute inset-x-0 bottom-0 h-[min(70vh,34rem)]" />
```

**问题点**：
- `waiting-dock-scrim` 的样式定义不明确
- 背景模糊可能不够强
- 没有渐变过渡效果

#### 问题 B：卡片高度和动画不够精细

**当前实现**（WaitingResponseDock.tsx:43）：
```tsx
className="... max-h-[min(72vh,38rem)] ... animate-slide-up"
```

**问题点**：
- 固定最大高度可能不适合所有情况
- `animate-slide-up` 动画可能过于简单
- 缺少弹性/缓动效果

#### 问题 C：缺少收起/展开功能

**当前实现**：
- 卡片出现后无法收起
- 用户必须回答或等待超时才能继续查看对话

#### 问题 D：问题文本不支持 Markdown

**当前实现**（QuestionForm.tsx:113-114）：
```tsx
<div className="text-[13px] font-medium break-words whitespace-pre-wrap">
  {question.text}
</div>
```

**问题点**：
- 只是纯文本渲染
- 无法支持 Agent 在问题中使用格式化（加粗、列表、代码等）

---

## 二、优化方案设计

### 2.1 背景模糊增强

**目标**：卡片出现时，背景内容明显模糊，聚焦问题

#### 设计方案

**视觉层次**：
```
┌─────────────────────────────┐
│ ConversationView            │ ← 完全可见
│ (对话气泡 + LiveStatus)     │
├─────────────────────────────┤
│ ╔═══════════════════════╗   │ ← 渐变模糊遮罩
│ ║                       ║   │   (从透明到强模糊)
│ ║  WaitingResponseDock  ║   │ ← 卡片清晰锐利
│ ║  [问题和选项]         ║   │
│ ║  [收起按钮 ↓]         ║   │
│ ╚═══════════════════════╝   │
└─────────────────────────────┘
    ↑ Composer 被完全遮挡
```

**CSS 实现**：

```css
/* styles/index.css */

/* 背景遮罩：渐变模糊 */
.waiting-dock-scrim {
  background: linear-gradient(
    to top,
    rgba(var(--bg-rgb), 0.4) 0%,
    rgba(var(--bg-rgb), 0.2) 40%,
    transparent 100%
  );
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  pointer-events: none;
  transition: opacity 0.3s var(--ease-calm);
}

/* 卡片本身保持清晰 */
.waiting-response-dock {
  backdrop-filter: blur(24px) saturate(1.2);
  -webkit-backdrop-filter: blur(24px) saturate(1.2);
  box-shadow: 
    inset 0 1px 0 rgba(255, 255, 255, 0.1),
    0 8px 32px rgba(0, 0, 0, 0.4),
    0 0 0 1px rgba(var(--accent-rgb), 0.3);
}
```

**需要在 index.css 中增加 RGB 变量**：
```css
:root {
  --bg-rgb: 246, 247, 249;
  --accent-rgb: 99, 102, 241;
}

.dark {
  --bg-rgb: 13, 16, 23;
  --accent-rgb: 129, 140, 248;
}
```

### 2.2 收起/展开功能

**目标**：卡片顶部增加收起按钮，收起后显示紧凑提示条

#### 交互流程

**展开状态（默认）**：
```
╔═══════════════════════════════════╗
║ [↓ Collapse]         问题等待中   ║
║─────────────────────────────────║
║ ❓ Agent's question here...       ║
║                                   ║
║ A. Option 1                       ║
║ B. Option 2                       ║
║                                   ║
║ Comment (optional)...             ║
║                        [Reply →]  ║
╚═══════════════════════════════════╝
```

**收起状态**：
```
╔═══════════════════════════════════╗
║ [↑ Expand]  Agent is waiting...   ║
╚═══════════════════════════════════╝
     ↑ 紧凑提示条，高度约 48px
```

#### 组件实现

**修改 WaitingResponseDock.tsx**：

```tsx
import { useState } from "react";
import { ChevronDown, ChevronUp, Loader2 } from "lucide-react";
import { motion, AnimatePresence } from "motion/react";

export function WaitingResponseDock() {
  const [collapsed, setCollapsed] = useState(false);
  
  // ... 原有逻辑
  
  if (targetId === null || question === null) return null;
  
  return (
    <div 
      className="waiting-dock-root fixed inset-x-0 bottom-0 z-[var(--z-overlay)] pointer-events-none" 
      data-waiting-dock
    >
      {/* 背景模糊遮罩 - 只在展开时显示 */}
      <AnimatePresence>
        {!collapsed && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="waiting-dock-scrim absolute inset-x-0 bottom-0 h-[min(80vh,42rem)]"
            aria-hidden="true"
          />
        )}
      </AnimatePresence>
      
      {/* 卡片主体 */}
      <motion.div
        layout
        initial={{ y: 100, opacity: 0 }}
        animate={{ 
          y: 0, 
          opacity: 1,
          height: collapsed ? "auto" : "auto"
        }}
        exit={{ y: 100, opacity: 0 }}
        transition={{ 
          type: "spring",
          damping: 25,
          stiffness: 300,
          mass: 0.8
        }}
        className={`
          waiting-response-dock pointer-events-auto relative mx-auto 
          w-[min(720px,calc(100%-1.5rem))] rounded-2xl border border-accent/35 
          bg-bg-elev/95 shadow-pop
          ${collapsed ? "" : "max-h-[min(72vh,38rem)] overflow-y-auto"}
        `}
        role="dialog"
        aria-label="Waiting for your reply"
        aria-live="polite"
        aria-expanded={!collapsed}
      >
        {/* 顶部控制栏 */}
        <div className="sticky top-0 z-10 border-b border-accent/20 bg-bg-elev/98 backdrop-blur-md">
          <button
            onClick={() => setCollapsed(!collapsed)}
            className="flex w-full items-center gap-3 px-4 py-3 text-left transition-colors hover:bg-hover/50"
            aria-label={collapsed ? "Expand question" : "Collapse question"}
          >
            <div className="flex items-center gap-2 text-accent">
              <Loader2 size={14} className="animate-spin-slow" />
              <span className="text-[12px] font-medium">
                {collapsed ? "Agent is waiting for your reply" : "Question"}
              </span>
            </div>
            
            <div className="ml-auto flex items-center gap-2">
              {collapsed && (
                <span className="text-[11px] text-fg-faint">
                  {question.options.length} options
                </span>
              )}
              {collapsed ? (
                <ChevronUp size={14} className="text-fg-faint" />
              ) : (
                <ChevronDown size={14} className="text-fg-faint" />
              )}
            </div>
          </button>
        </div>
        
        {/* 问题内容 - 只在展开时显示 */}
        <AnimatePresence mode="wait">
          {!collapsed && (
            <motion.div
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: "auto", opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              transition={{ duration: 0.2 }}
              className="p-4"
            >
              <QuestionCard
                key={question.question_id}
                epoch={epoch}
                turnId={targetId}
                item={null}
                live={question}
                reply={null}
                commentAsBubble
                onSubmitted={(_draft: QuestionDraft) => {
                  setSubmitted({ targetId, question });
                  // 提交后自动收起
                  setCollapsed(true);
                }}
              />
            </motion.div>
          )}
        </AnimatePresence>
      </motion.div>
    </div>
  );
}
```

### 2.3 问题文本 Markdown 渲染

**目标**：支持 Agent 在问题中使用 Markdown 格式

#### 修改 QuestionForm.tsx

**当前代码**（L113-114）：
```tsx
<div className="text-[13px] font-medium break-words whitespace-pre-wrap">
  {question.text}
</div>
```

**修改为**：
```tsx
import { Markdown } from "../../components/markdown/Markdown";

// ... 在 QuestionForm 组件内

<div className="text-[13px] font-medium">
  <Markdown 
    className="md-inline-question"
    origin={{ link: "", turnId: null, day: null, view: "active" }}
  >
    {question.text}
  </Markdown>
</div>
```

**增加专用样式**（styles/index.css）：
```css
/* 问题 Markdown 样式 - 紧凑、内联优先 */
.md-inline-question {
  font-size: inherit;
  line-height: 1.5;
}

.md-inline-question p {
  margin: 0;
  display: inline;
}

.md-inline-question p + p {
  display: block;
  margin-top: 0.5em;
}

.md-inline-question strong {
  font-weight: 600;
  color: var(--fg);
}

.md-inline-question em {
  font-style: italic;
  color: var(--fg-muted);
}

.md-inline-question code {
  padding: 0.125rem 0.25rem;
  background: var(--code-bg);
  border-radius: 0.25rem;
  font-size: 0.9em;
  font-family: var(--font-mono);
}

.md-inline-question ul,
.md-inline-question ol {
  margin: 0.5em 0;
  padding-left: 1.5em;
}

.md-inline-question li {
  margin: 0.25em 0;
}

/* 问题中的代码块保持紧凑 */
.md-inline-question pre {
  margin: 0.5em 0;
  padding: 0.5rem;
  font-size: 0.85em;
}
```

### 2.4 卡片尺寸与动画优化

**目标**：更自然的弹出动效，适应不同问题长度

#### 动画参数调整

**当前问题**：
- 可能使用简单的线性动画
- 缺少弹性感

**优化方案**：
```tsx
// 弹簧动画参数
transition={{ 
  type: "spring",
  damping: 25,      // 阻尼：控制震荡
  stiffness: 300,   // 刚度：控制速度
  mass: 0.8         // 质量：控制惯性
}}
```

**效果**：
- 快速弹出，轻微回弹
- 自然的物理感
- 符合直觉的交互反馈

#### 尺寸自适应

**问题文本较短**：
```
╔═══════════════════╗
║ [↓]  Question     ║  ← 卡片高度约 200px
║─────────────────║
║ ❓ Short text?    ║
║ A. Yes            ║
║ B. No             ║
║        [Reply →]  ║
╚═══════════════════╝
```

**问题文本较长 + 多选项**：
```
╔═══════════════════╗
║ [↓]  Question     ║  ← 卡片高度约 600px
║─────────────────║    支持内部滚动
║ ❓ Long question  ║
║ with multiple     ║
║ paragraphs...     ║  ↕ 可滚动
║                   ║
║ A. Option 1       ║
║ B. Option 2       ║
║ ...               ║
╚═══════════════════╝
```

**实现**：
```tsx
className={`
  waiting-response-dock ...
  ${collapsed 
    ? "h-auto" 
    : "max-h-[min(72vh,38rem)] overflow-y-auto"
  }
`}
```

---

## 三、完整代码实现

### 3.1 WaitingResponseDock.tsx（完整修订版）

```tsx
import { useEffect, useState } from "react";
import { ChevronDown, ChevronUp, Loader2 } from "lucide-react";
import { motion, AnimatePresence } from "motion/react";
import type { TurnQuestion } from "../../api/v2/types";
import { useConnectionStore, selectActiveTurnId } from "../../store/connectionStore";
import { useTurnStore } from "../../store/turnStore";
import { QuestionCard } from "./QuestionCard";
import { useLiveWaitingQuestion } from "./ConversationRows";
import type { QuestionDraft } from "./questionContent";

const EMPTY_ITEMS: ReturnType<typeof useTurnStore.getState>["items"] = [];

/**
 * The single active question surface. It lives at the ChatView layout edge so
 * a long activity stream cannot push the reply controls below the viewport.
 * The question and submit path remain owned by QuestionCard/turnController.
 * 
 * Features:
 * - Covers Composer when active (user replies through the dock)
 * - Blurs background content (ConversationView) for focus
 * - Collapsible: user can minimize to scroll conversation history
 * - Spring animation for natural feel
 */
export function WaitingResponseDock() {
  const [submitted, setSubmitted] = useState<{ targetId: string; question: TurnQuestion } | null>(null);
  const [collapsed, setCollapsed] = useState(false);
  
  const epoch = useConnectionStore((state) => state.epoch);
  const activeTurnId = useConnectionStore(selectActiveTurnId);
  const displayedTurnId = useTurnStore((state) => state.turnId);
  const targetId = activeTurnId ?? displayedTurnId;
  const liveQuestion = useLiveWaitingQuestion(targetId);
  const items = useTurnStore((state) => targetId !== null && targetId !== state.turnId
    ? state.runtimeProjections[targetId]?.items ?? EMPTY_ITEMS
    : state.items);
  const hasFormalReply = submitted !== null && items.some((item) =>
    item.role === "user.reply" && item.question_id === submitted.question.question_id,
  );
  const question = liveQuestion ?? (submitted?.targetId === targetId && !hasFormalReply ? submitted.question : null);

  useEffect(() => {
    if (hasFormalReply) setSubmitted(null);
    else if (submitted !== null && liveQuestion !== null && submitted.question.question_id !== liveQuestion.question_id) setSubmitted(null);
    else if (submitted !== null && targetId !== submitted.targetId && liveQuestion === null) setSubmitted(null);
  }, [hasFormalReply, liveQuestion, submitted, targetId]);
  
  // Reset collapsed state when question changes
  useEffect(() => {
    if (question !== null) {
      setCollapsed(false);
    }
  }, [question?.question_id]);

  if (targetId === null || question === null) return null;

  return (
    <div 
      className="waiting-dock-root fixed inset-x-0 bottom-0 z-[var(--z-overlay)] pointer-events-none" 
      data-waiting-dock
    >
      {/* Background blur scrim - only when expanded */}
      <AnimatePresence>
        {!collapsed && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.25, ease: [0.4, 0, 0.2, 1] }}
            className="waiting-dock-scrim absolute inset-x-0 bottom-0 h-[min(80vh,42rem)]"
            aria-hidden="true"
          />
        )}
      </AnimatePresence>
      
      {/* Dock card */}
      <motion.div
        layout
        initial={{ y: 100, opacity: 0, scale: 0.95 }}
        animate={{ 
          y: 0, 
          opacity: 1,
          scale: 1
        }}
        exit={{ y: 100, opacity: 0, scale: 0.95 }}
        transition={{ 
          type: "spring",
          damping: 25,
          stiffness: 300,
          mass: 0.8
        }}
        className={`
          waiting-response-dock pointer-events-auto relative mx-auto mb-3
          w-[min(720px,calc(100%-1.5rem))] rounded-2xl border border-accent/35 
          bg-bg-elev/95 shadow-pop
          ${collapsed ? "" : "max-h-[min(72vh,38rem)]"}
        `}
        role="dialog"
        aria-label="Waiting for your reply"
        aria-live="polite"
        aria-expanded={!collapsed}
      >
        {/* Top control bar */}
        <div className="sticky top-0 z-10 border-b border-accent/20 bg-bg-elev/98 backdrop-blur-md rounded-t-2xl">
          <button
            onClick={() => setCollapsed(!collapsed)}
            className="flex w-full items-center gap-3 px-4 py-3 text-left transition-colors hover:bg-hover/50 rounded-t-2xl"
            aria-label={collapsed ? "Expand question" : "Collapse question"}
          >
            {/* Indicator */}
            <div className="flex items-center gap-2 text-accent">
              <Loader2 size={14} className="animate-spin-slow" />
              <span className="text-[12px] font-medium">
                {collapsed ? "Agent is waiting for your reply" : "Question"}
              </span>
            </div>
            
            {/* Collapse/Expand control */}
            <div className="ml-auto flex items-center gap-2">
              {collapsed && (
                <span className="text-[11px] text-fg-faint">
                  {question.options.length} {question.options.length === 1 ? "option" : "options"}
                </span>
              )}
              {collapsed ? (
                <ChevronUp size={14} className="text-fg-faint" />
              ) : (
                <ChevronDown size={14} className="text-fg-faint" />
              )}
            </div>
          </button>
        </div>
        
        {/* Question content - only when expanded */}
        <AnimatePresence mode="wait">
          {!collapsed && (
            <motion.div
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: "auto", opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              transition={{ duration: 0.2 }}
              className="overflow-y-auto"
              style={{ maxHeight: "calc(72vh - 3rem)" }}
            >
              <div className="p-4">
                <QuestionCard
                  key={question.question_id}
                  epoch={epoch}
                  turnId={targetId}
                  item={null}
                  live={question}
                  reply={null}
                  commentAsBubble
                  onSubmitted={(_draft: QuestionDraft) => {
                    setSubmitted({ targetId, question });
                    // Auto-collapse after submit
                    setTimeout(() => setCollapsed(true), 500);
                  }}
                />
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </motion.div>
    </div>
  );
}
```

### 3.2 QuestionForm.tsx（修改问题文本渲染）

**只需修改 L112-115**：

```tsx
import { Markdown } from "../../components/markdown/Markdown";

// ... 在 QuestionForm 组件内，替换原来的纯文本显示

<div className="min-w-0 flex-1">
  <div className="text-[13px] font-medium">
    <Markdown 
      className="md-inline-question"
      origin={{ link: "", turnId: null, day: null, view: "active" }}
    >
      {question.text}
    </Markdown>
  </div>
  {/* ... 其余保持不变 */}
</div>
```

### 3.3 styles/index.css（新增样式）

**在文件末尾添加**：

```css
/* ============================================
   Waiting Response Dock Styles
   ============================================ */

/* Background blur scrim */
.waiting-dock-scrim {
  background: linear-gradient(
    to top,
    hsl(var(--bg-h) var(--bg-s) var(--bg-l) / 0.6) 0%,
    hsl(var(--bg-h) var(--bg-s) var(--bg-l) / 0.3) 50%,
    transparent 100%
  );
  backdrop-filter: blur(16px) saturate(0.8);
  -webkit-backdrop-filter: blur(16px) saturate(0.8);
  pointer-events: none;
  transition: opacity 0.25s cubic-bezier(0.4, 0, 0.2, 1);
}

/* Dock card blur and glow */
.waiting-response-dock {
  backdrop-filter: blur(24px) saturate(1.2);
  -webkit-backdrop-filter: blur(24px) saturate(1.2);
  box-shadow: 
    inset 0 1px 0 rgba(255, 255, 255, 0.08),
    0 12px 48px rgba(0, 0, 0, 0.3),
    0 0 0 1px rgba(129, 140, 248, 0.25),
    0 0 32px rgba(129, 140, 248, 0.12);
}

/* Slow spin animation for loader */
@keyframes spin-slow {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.animate-spin-slow {
  animation: spin-slow 2s linear infinite;
}

/* ============================================
   Inline Question Markdown Styles
   ============================================ */

.md-inline-question {
  font-size: inherit;
  line-height: 1.5;
  color: var(--fg);
}

.md-inline-question p {
  margin: 0;
  display: inline;
}

.md-inline-question p + p {
  display: block;
  margin-top: 0.5em;
}

.md-inline-question strong {
  font-weight: 600;
  color: var(--fg);
}

.md-inline-question em {
  font-style: italic;
  color: var(--fg-muted);
}

.md-inline-question code {
  padding: 0.125rem 0.375rem;
  background: var(--code-bg);
  border: 1px solid var(--line);
  border-radius: 0.25rem;
  font-size: 0.9em;
  font-family: var(--font-mono);
  color: var(--fg);
}

.md-inline-question ul,
.md-inline-question ol {
  margin: 0.5em 0;
  padding-left: 1.5em;
}

.md-inline-question li {
  margin: 0.25em 0;
}

.md-inline-question li::marker {
  color: var(--fg-faint);
}

/* Question code blocks - compact */
.md-inline-question pre {
  margin: 0.5em 0;
  padding: 0.5rem;
  font-size: 0.85em;
  background: var(--code-bg);
  border: 1px solid var(--line);
  border-radius: 0.5rem;
  overflow-x: auto;
}

.md-inline-question pre code {
  padding: 0;
  background: none;
  border: none;
  font-size: inherit;
}

/* Question links */
.md-inline-question a {
  color: var(--accent);
  text-decoration: underline;
  text-underline-offset: 2px;
}

.md-inline-question a:hover {
  color: var(--accent-strong);
}
```

---

## 四、效果对比与验收

### 4.1 视觉效果对比

#### 改进前

```
┌─────────────────────────┐
│ ConversationView        │
│ [对话内容...]           │
│                         │
├─────────────────────────┤
│ Composer                │ ← 被覆盖但无遮罩
├─────────────────────────┤
│ ╔═══════════════════╗   │
│ ║ Question          ║   │ ← 卡片直接出现
│ ║ Options...        ║   │   无收起功能
│ ╚═══════════════════╝   │
└─────────────────────────┘
```

**问题**：
- ❌ 背景不够模糊，分散注意力
- ❌ 无法查看对话历史
- ❌ 问题文本不支持格式化
- ❌ 动画可能生硬

#### 改进后（展开状态）

```
┌─────────────────────────┐
│ ConversationView        │ ← 强模糊背景
│ [模糊的对话内容...]     │   (blur(16px))
│                         │
│ ╔═══════════════════╗   │ ← 渐变遮罩
│ ║ [↓] Question      ║   │
│ ║─────────────────║   │
│ ║ ❓ **Important:** ║   │ ← Markdown 渲染
│ ║ Choose an option  ║   │
│ ║                   ║   │
│ ║ A. Option 1       ║   │
│ ║ B. Option 2       ║   │
│ ║                   ║   │
│ ║      [Reply →]    ║   │
│ ╚═══════════════════╝   │ ← 弹簧动画
└─────────────────────────┘   清晰锐利
```

**改进**：
- ✅ 背景强模糊，聚焦问题
- ✅ 渐变遮罩自然过渡
- ✅ 问题支持 Markdown
- ✅ 弹簧动画自然

#### 改进后（收起状态）

```
┌─────────────────────────┐
│ ConversationView        │ ← 完全可见
│ [对话内容...]           │   可自由滚动
│ [LiveStatus]            │
│                         │
│ ╔═══════════════════╗   │
│ ║ [↑] Waiting... 2  ║   │ ← 紧凑提示条
│ ╚═══════════════════╝   │
└─────────────────────────┘
```

**改进**：
- ✅ 用户可以滚动查看对话
- ✅ 紧凑提示不遮挡内容
- ✅ 需要时可以再展开

### 4.2 交互流程

**场景 1：Agent 提问**

1. Agent 生成问题
2. Dock 从底部弹出（弹簧动画）
3. 背景渐变模糊
4. 用户看到清晰的问题和选项

**场景 2：用户想查看历史对话**

1. 点击顶部"[↓] Question"
2. Dock 收起为紧凑条
3. 背景模糊消失
4. 用户可以自由滚动对话

**场景 3：用户回答问题**

1. 从收起状态点击"[↑] Expand"
2. Dock 展开，显示完整问题
3. 选择选项并点击 Reply
4. 提交后 Dock 自动收起（500ms 延迟）
5. 随后 Dock 完全消失

### 4.3 Markdown 渲染示例

**Agent 问题文本**：
```markdown
**Important decision**: Which approach should we take?

Consider these factors:
- Performance implications
- Code maintainability
- Team expertise

See `implementation.md` for details.
```

**渲染效果**：
```
╔═══════════════════════════════╗
║ [↓] Question                  ║
║─────────────────────────────║
║ ❓ Important decision: Which  ║ ← 粗体
║ approach should we take?      ║
║                               ║
║ Consider these factors:       ║
║ • Performance implications    ║ ← 列表
║ • Code maintainability        ║
║ • Team expertise              ║
║                               ║
║ See implementation.md for     ║ ← 代码样式
║ details.                      ║
║                               ║
║ A. Approach 1                 ║
║ B. Approach 2                 ║
╚═══════════════════════════════╝
```

---

## 五、验收标准

### 功能验收

- [ ] **背景模糊**
  - [ ] Dock 展开时背景明显模糊（blur ≥ 16px）
  - [ ] 渐变遮罩自然过渡（从透明到模糊）
  - [ ] Dock 本身清晰锐利

- [ ] **收起/展开**
  - [ ] 点击顶部控制栏可以收起
  - [ ] 收起后显示紧凑提示条（高度 ≤ 60px）
  - [ ] 收起状态显示选项数量
  - [ ] 点击提示条可以再次展开
  - [ ] 展开/收起动画流畅

- [ ] **Markdown 渲染**
  - [ ] 问题文本支持加粗、斜体
  - [ ] 支持列表（有序/无序）
  - [ ] 支持行内代码
  - [ ] 支持代码块
  - [ ] 支持链接（可点击）
  - [ ] 样式紧凑不过分占用空间

- [ ] **动画效果**
  - [ ] 弹出动画有弹性（spring）
  - [ ] 不会过度震荡
  - [ ] 退出动画流畅
  - [ ] 展开/收起过渡自然

### 视觉验收

- [ ] **光泽与材质**
  - [ ] Dock 有轻微内层光泽
  - [ ] 边框有淡淡的 accent 色晕
  - [ ] 背景模糊饱和度适中
  - [ ] 整体符合 Luminous 设计系统

- [ ] **响应式**
  - [ ] 窄屏下宽度自适应（min 375px）
  - [ ] 高度不超过视口 72%
  - [ ] 内容可滚动时有明确指示

- [ ] **可访问性**
  - [ ] `aria-expanded` 正确反映状态
  - [ ] `aria-label` 描述清晰
  - [ ] 键盘可以操作（Tab/Enter）
  - [ ] 屏幕阅读器友好

### 性能验收

- [ ] 动画帧率稳定（≥ 60fps）
- [ ] Markdown 渲染不卡顿
- [ ] 展开/收起响应及时（< 50ms）

---

## 六、实施计划

### 阶段一：背景模糊与收起功能（4h）

| 任务 | 时间 | 难度 |
|------|------|------|
| 增加 RGB 变量到 index.css | 0.5h | 低 |
| 实现 waiting-dock-scrim 样式 | 1h | 低 |
| 修改 WaitingResponseDock 增加收起功能 | 2h | 中 |
| 调整动画参数（弹簧） | 0.5h | 低 |

### 阶段二：Markdown 渲染（2h）

| 任务 | 时间 | 难度 |
|------|------|------|
| 修改 QuestionForm 使用 Markdown | 0.5h | 低 |
| 增加 md-inline-question 样式 | 1h | 低 |
| 测试各种 Markdown 格式 | 0.5h | - |

### 阶段三：测试与调整（2h）

| 任务 | 时间 | 难度 |
|------|------|------|
| 测试不同问题长度 | 0.5h | - |
| 测试收起/展开交互 | 0.5h | - |
| 测试 Markdown 边缘情况 | 0.5h | - |
| 调整动画和视觉细节 | 0.5h | - |

**总工作量**：8 小时 ≈ 1 个工作日

---

## 七、风险评估

### 低风险
- ✅ 纯视觉和交互改进
- ✅ 不改变数据流
- ✅ 可以逐步实施

### 中风险
- ⚠️ Markdown 渲染可能与现有样式冲突
  - **缓解**：使用独立的 `.md-inline-question` 作用域
- ⚠️ 动画在低端设备可能卡顿
  - **缓解**：检测 `prefers-reduced-motion`，降级为简单动画

### 注意事项
- 测试不同长度的问题文本
- 确保收起状态不遮挡重要内容
- 验证 Markdown 渲染不会破坏布局

---

## 八、总结

### 核心改进点

1. **背景模糊增强**
   - 渐变遮罩从透明到强模糊
   - 聚焦问题，减少干扰
   - 视觉层次清晰

2. **收起/展开功能**
   - 用户可以查看对话历史
   - 紧凑提示条不遮挡内容
   - 流畅的展开/收起动画

3. **Markdown 渲染支持**
   - Agent 可以使用格式化
   - 加粗、列表、代码高亮
   - 紧凑样式不占用过多空间

4. **弹簧动画**
   - 自然的物理感
   - 轻微回弹
   - 符合直觉

### 预期效果

**用户体验提升**：
- ✅ 问题更加醒目，减少错过
- ✅ 可以自由查看对话历史
- ✅ Markdown 支持更丰富的表达
- ✅ 动画更自然流畅

**视觉一致性**：
- ✅ 符合 Luminous 设计系统
- ✅ 统一的模糊和光泽效果
- ✅ 协调的配色和间距

---

**执行状态**：待开始

**预计完成时间**：1 个工作日

**负责人**：GPT Agent（实施）+ Claude（审查）
