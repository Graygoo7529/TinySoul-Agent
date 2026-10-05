# Visualization Settings 页面卡片化与交互优化执行计划

日期：2026-10-05

状态：待执行

---

## 一、当前情况分析

### 1.1 Settings 页面架构

**核心文件**：
- `SettingsPage.tsx`：主入口，负责布局和页面路由
- `SettingsNav.tsx`：左侧导航栏
- `SettingsBottomBar.tsx`：底部 Draft 操作栏
- `SettingsDraftChip.tsx`：Draft 数量提示
- `SettingsDisclosure.tsx`：可折叠区块组件
- `SettingsPicker.tsx`：配置选择器

**页面分类**：
```
Models (模型配置)
├─ llm-providers      // LLM 提供商
├─ llm-models         // LLM 模型
├─ llm-tasks          // LLM 任务链
├─ dedicated-providers // 专用提供商
├─ dedicated-models   // 专用模型
├─ credentials        // 凭据
└─ image-generation   // 图像生成

Behavior (行为配置)
├─ phase-bindings     // Phase 绑定
├─ actions            // Action 配置
├─ search-policies    // 搜索策略
├─ budgets            // 预算
└─ reflection         // Reflection

Editors (编辑器配置)
├─ execution          // 执行
├─ web                // Web
├─ acp                // ACP
├─ mcp                // MCP
├─ workspace          // Workspace
├─ session            // Session
├─ home               // Home
├─ memory             // Memory
└─ system             // System

Presets (预设)
└─ plans              // 计划

Interface (界面)
└─ interface          // 界面偏好
```

### 1.2 当前问题诊断

#### 问题 A：配置项呈现密集，缺少呼吸空间

**当前实现**：
- 配置项直接堆叠在表单中
- 没有卡片化分组
- 视觉层次不清晰

**示例（LlmProvidersPage）**：
```
┌─────────────────────────┐
│ Anthropic               │
│ base_url: [_________]   │
│ api_key: [__________]   │
│ timeout: [____]         │
│                         │
│ OpenAI                  │
│ base_url: [_________]   │
│ api_key: [__________]   │
│ timeout: [____]         │
└─────────────────────────┘
```

所有字段平铺，难以快速定位和理解配置单元。

#### 问题 B：Draft 状态提示不够醒目

**当前实现**：
- Draft 数量只在 BottomBar 显示
- 修改后的配置项没有视觉标记
- 用户容易忘记 Apply

#### 问题 C：表单编辑体验不佳

**问题点**：
1. 编辑时所有字段同时展开，信息过载
2. 缺少"查看 vs 编辑"两种模式的切换
3. 验证错误不够直观
4. 保存/取消操作不够明确

---

## 二、设计目标

### 2.1 卡片化原则

> 每个配置单元是一张独立的卡片，有明确的边界、状态和操作。

**卡片结构**：
```
┌─ Provider Card ───────────────────┐
│ Header (标题 + 状态 + 操作)        │
├───────────────────────────────────┤
│ Body (折叠：摘要 / 展开：表单)     │
└───────────────────────────────────┘
```

### 2.2 状态可视化

**配置项的三种状态**：
1. **Clean**：与服务器一致，无 Draft
2. **Draft**：有未应用的修改
3. **Error**：验证失败或应用失败

**视觉区分**：
- Clean：普通边框 `border-line`
- Draft：橙色边框 `border-warning/40` + 橙色圆点标记
- Error：红色边框 `border-danger/40` + 错误图标

### 2.3 渐进披露

**两种展示模式**：

**查看模式（默认）**：
```
┌─ Anthropic ──────────────────┐
│ ● Connected                   │
│ Base URL: api.anthropic.com   │
│ Models: 12 available          │
│ [Edit →]                      │
└───────────────────────────────┘
```

**编辑模式（点击 Edit）**：
```
┌─ Anthropic ──────────────────┐
│ Base URL                      │
│ [_________________________]   │
│                               │
│ API Key                       │
│ [_________________________]   │
│                               │
│ Timeout (ms)                  │
│ [________]                    │
│                               │
│ [Save] [Cancel]               │
└───────────────────────────────┘
```

---

## 三、核心组件设计

### 3.1 ConfigCard 通用组件

**新建文件**：`visualization/src/features/settings/ConfigCard.tsx`

```tsx
import { useState } from "react";
import { AlertTriangle, Check, Edit2, X } from "lucide-react";
import { Button } from "../../components/ui/Button";

interface ConfigCardProps {
  title: string;
  subtitle?: string;
  status?: "clean" | "draft" | "error";
  statusLabel?: string;
  error?: string;
  summary?: React.ReactNode;
  children: React.ReactNode;
  onEdit?: () => void;
  onSave?: () => void;
  onCancel?: () => void;
  editing?: boolean;
  actions?: React.ReactNode;
}

export function ConfigCard({
  title,
  subtitle,
  status = "clean",
  statusLabel,
  error,
  summary,
  children,
  onEdit,
  onSave,
  onCancel,
  editing = false,
  actions,
}: ConfigCardProps) {
  const borderColor = 
    status === "draft" ? "border-warning/40" :
    status === "error" ? "border-danger/40" :
    "border-line";
  
  const bgColor = 
    status === "draft" ? "bg-warning-soft/5" :
    status === "error" ? "bg-danger-soft/5" :
    "bg-bg-elev";
  
  return (
    <div className={`overflow-hidden rounded-xl border ${borderColor} ${bgColor} shadow-sm`}>
      {/* Header */}
      <div className="flex items-center gap-3 border-b border-line/60 bg-bg-sunken/40 px-4 py-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <h3 className="font-medium text-[13px] text-fg truncate">
              {title}
            </h3>
            {status === "draft" && (
              <div className="h-2 w-2 rounded-full bg-warning" title="Has unsaved changes" />
            )}
            {status === "error" && (
              <AlertTriangle size={13} className="text-danger" title="Has errors" />
            )}
          </div>
          {subtitle && (
            <div className="font-mono text-[10px] text-fg-faint mt-0.5">
              {subtitle}
            </div>
          )}
        </div>
        
        {/* Status Badge */}
        {statusLabel && (
          <div className={`flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-medium ${
            statusLabel === "Connected" || statusLabel === "Active" 
              ? "bg-success-soft text-success"
              : "bg-fg-faint/10 text-fg-faint"
          }`}>
            {statusLabel === "Connected" && <Check size={10} />}
            {statusLabel}
          </div>
        )}
        
        {/* Actions */}
        {!editing && onEdit && (
          <Button size="sm" variant="ghost" onClick={onEdit}>
            <Edit2 size={12} />
            Edit
          </Button>
        )}
        {actions}
      </div>
      
      {/* Error Banner */}
      {error && (
        <div className="flex items-start gap-2 border-b border-danger/30 bg-danger-soft px-4 py-2 text-[12px] text-danger">
          <AlertTriangle size={13} className="mt-0.5 shrink-0" />
          <span>{error}</span>
        </div>
      )}
      
      {/* Body */}
      <div className="px-4 py-3">
        {!editing && summary ? (
          summary
        ) : (
          children
        )}
      </div>
      
      {/* Footer (Edit Mode) */}
      {editing && (onSave || onCancel) && (
        <div className="flex items-center justify-end gap-2 border-t border-line/60 bg-bg-sunken/20 px-4 py-2.5">
          {onCancel && (
            <Button size="sm" variant="ghost" onClick={onCancel}>
              <X size={12} />
              Cancel
            </Button>
          )}
          {onSave && (
            <Button size="sm" onClick={onSave}>
              <Check size={12} />
              Save Draft
            </Button>
          )}
        </div>
      )}
    </div>
  );
}
```

### 3.2 ConfigSummary 摘要组件

**新建文件**：`visualization/src/features/settings/ConfigSummary.tsx`

```tsx
interface ConfigSummaryProps {
  items: Array<{
    label: string;
    value: string | number | null;
    mono?: boolean;
  }>;
}

export function ConfigSummary({ items }: ConfigSummaryProps) {
  return (
    <div className="space-y-2">
      {items.map((item, i) => (
        <div key={i} className="flex items-baseline gap-2 text-[12px]">
          <span className="text-fg-faint min-w-[100px]">{item.label}:</span>
          <span className={`${item.mono ? "font-mono" : ""} text-fg ${
            item.value === null ? "text-fg-faint italic" : ""
          }`}>
            {item.value ?? "Not set"}
          </span>
        </div>
      ))}
    </div>
  );
}
```

### 3.3 DraftBanner 顶部提示

**新建文件**：`visualization/src/features/settings/DraftBanner.tsx`

```tsx
import { AlertTriangle } from "lucide-react";
import { Button } from "../../components/ui/Button";
import { motion } from "motion/react";

interface DraftBannerProps {
  draftCount: number;
  onReview: () => void;
  onApply: () => void;
  onDiscard: () => void;
}

export function DraftBanner({ draftCount, onReview, onApply, onDiscard }: DraftBannerProps) {
  if (draftCount === 0) return null;
  
  return (
    <motion.div
      initial={{ height: 0, opacity: 0 }}
      animate={{ height: "auto", opacity: 1 }}
      exit={{ height: 0, opacity: 0 }}
      transition={{ duration: 0.2 }}
      className="border-b border-warning/30 bg-warning-soft"
    >
      <div className="flex items-center gap-3 px-4 py-2.5">
        <AlertTriangle size={14} className="text-warning shrink-0" />
        <span className="flex-1 text-[13px] text-warning">
          You have {draftCount} unsaved {draftCount === 1 ? "change" : "changes"}
        </span>
        <Button size="sm" variant="outline" onClick={onReview}>
          Review Changes
        </Button>
        <Button size="sm" onClick={onApply}>
          Apply Changes
        </Button>
        <Button size="sm" variant="ghost" onClick={onDiscard}>
          Discard All
        </Button>
      </div>
    </motion.div>
  );
}
```

---

## 四、具体页面改造方案

### 4.1 LlmProvidersPage（优先级 P0）

**目标**：把 Provider 配置改为卡片化呈现

#### 改造前（推测当前实现）：
```tsx
// 当前可能是一个大表单，所有 providers 展开
<div>
  {providers.map((provider) => (
    <div key={provider.name}>
      <label>Base URL</label>
      <input name={`${provider.name}.base_url`} />
      <label>API Key</label>
      <input name={`${provider.name}.api_key`} />
      // ...
    </div>
  ))}
</div>
```

#### 改造后：
```tsx
// visualization/src/features/settings/models/LlmProvidersPage.tsx
import { useState } from "react";
import { Plus } from "lucide-react";
import { Button } from "../../../components/ui/Button";
import { ConfigCard } from "../ConfigCard";
import { ConfigSummary } from "../ConfigSummary";
import { useConfigDraftStore } from "../draft/store";

export function LlmProvidersPage() {
  const providers = useConfigDraftStore((s) => s.config?.llm?.providers ?? []);
  const drafts = useConfigDraftStore((s) => s.drafts);
  const [editing, setEditing] = useState<string | null>(null);
  
  return (
    <div className="mx-auto max-w-3xl space-y-3 px-5 py-4">
      {/* 页面标题 */}
      <div className="flex items-baseline justify-between">
        <div>
          <h2 className="text-[16px] font-semibold text-fg">LLM Providers</h2>
          <p className="text-[12px] text-fg-muted mt-1">
            Configure model providers and their base endpoints
          </p>
        </div>
        <Button variant="outline" size="sm">
          <Plus size={13} />
          Add Provider
        </Button>
      </div>
      
      {/* Provider 卡片列表 */}
      <div className="space-y-3">
        {providers.map((provider) => (
          <ProviderCard
            key={provider.name}
            provider={provider}
            draft={drafts[`llm.providers.${provider.name}`]}
            editing={editing === provider.name}
            onEdit={() => setEditing(provider.name)}
            onSave={() => {
              // 保存 draft 逻辑
              setEditing(null);
            }}
            onCancel={() => setEditing(null)}
          />
        ))}
      </div>
    </div>
  );
}

function ProviderCard({ provider, draft, editing, onEdit, onSave, onCancel }) {
  const config = draft ?? provider;
  const hasDraft = draft !== null;
  
  // 检测连接状态（这里假设有个 hook）
  const connected = useProviderStatus(provider.name);
  
  return (
    <ConfigCard
      title={provider.display_name ?? provider.name}
      subtitle={provider.name}
      status={hasDraft ? "draft" : "clean"}
      statusLabel={connected ? "Connected" : "Not configured"}
      summary={
        <ConfigSummary
          items={[
            { label: "Base URL", value: config.base_url, mono: true },
            { label: "Timeout", value: config.timeout ? `${config.timeout}ms` : null },
            { label: "Models", value: provider.available_models?.length ?? 0 },
          ]}
        />
      }
      editing={editing}
      onEdit={onEdit}
      onSave={onSave}
      onCancel={onCancel}
    >
      {/* 编辑表单 */}
      <div className="space-y-3">
        <div>
          <label className="block text-[11px] font-medium text-fg-muted mb-1">
            Base URL
          </label>
          <input
            type="text"
            className="w-full rounded-lg border border-line bg-bg px-3 py-2 text-[13px] focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/20"
            defaultValue={config.base_url}
          />
        </div>
        
        <div>
          <label className="block text-[11px] font-medium text-fg-muted mb-1">
            API Key
          </label>
          <input
            type="password"
            className="w-full rounded-lg border border-line bg-bg px-3 py-2 text-[13px] font-mono focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/20"
            defaultValue={config.api_key}
            placeholder="sk-..."
          />
        </div>
        
        <div>
          <label className="block text-[11px] font-medium text-fg-muted mb-1">
            Timeout (ms)
          </label>
          <input
            type="number"
            className="w-full rounded-lg border border-line bg-bg px-3 py-2 text-[13px] font-mono focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/20"
            defaultValue={config.timeout}
            placeholder="60000"
          />
        </div>
      </div>
    </ConfigCard>
  );
}
```

### 4.2 ActionsPage（优先级 P1）

**目标**：把 Action 配置改为卡片 + 分组

#### 改造方案：

```tsx
// visualization/src/features/settings/behavior/ActionsPage.tsx
export function ActionsPage() {
  const actions = useConfigDraftStore((s) => s.config?.actions ?? []);
  
  // 按 domain 分组
  const grouped = groupBy(actions, (a) => a.domain ?? "core");
  
  return (
    <div className="mx-auto max-w-3xl space-y-4 px-5 py-4">
      <div>
        <h2 className="text-[16px] font-semibold text-fg">Actions</h2>
        <p className="text-[12px] text-fg-muted mt-1">
          Configure action behaviors and constraints
        </p>
      </div>
      
      {/* 按 domain 分组显示 */}
      {Object.entries(grouped).map(([domain, domainActions]) => (
        <div key={domain} className="space-y-2">
          <h3 className="flex items-center gap-2 text-[13px] font-medium text-fg">
            <DomainIcon domain={domain} />
            {domainLabel(domain)}
          </h3>
          
          <div className="space-y-2">
            {domainActions.map((action) => (
              <ActionCard key={action.action_id} action={action} />
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

function ActionCard({ action }) {
  const [editing, setEditing] = useState(false);
  
  return (
    <ConfigCard
      title={action.action_id}
      summary={
        <ConfigSummary
          items={[
            { label: "Enabled", value: action.enabled ? "Yes" : "No" },
            { label: "Timeout", value: action.timeout ? `${action.timeout}ms` : null },
            { label: "Model", value: action.model_selection },
          ]}
        />
      }
      editing={editing}
      onEdit={() => setEditing(true)}
      onSave={() => setEditing(false)}
      onCancel={() => setEditing(false)}
    >
      {/* 编辑表单 */}
      {/* ... */}
    </ConfigCard>
  );
}
```

### 4.3 PhaseBindingsPage（优先级 P1）

**目标**：Phase 配置的可视化

#### 改造方案：

```tsx
export function PhaseBindingsPage() {
  const bindings = useConfigDraftStore((s) => s.config?.phase_bindings ?? []);
  
  return (
    <div className="mx-auto max-w-3xl space-y-3 px-5 py-4">
      <div>
        <h2 className="text-[16px] font-semibold text-fg">Phase Bindings</h2>
        <p className="text-[12px] text-fg-muted mt-1">
          Configure which actions are available in each phase
        </p>
      </div>
      
      {/* Phase 卡片 */}
      {["phase1", "phase2", "phase3"].map((phase) => (
        <PhaseCard key={phase} phase={phase} bindings={bindings[phase]} />
      ))}
    </div>
  );
}

function PhaseCard({ phase, bindings }) {
  const [expanded, setExpanded] = useState(false);
  
  const phaseInfo = {
    phase1: { title: "Phase 1: Domain Selection", color: "text-cyan-500" },
    phase2: { title: "Phase 2: Action Planning", color: "text-purple-500" },
    phase3: { title: "Phase 3: Execution", color: "text-emerald-500" },
  }[phase];
  
  return (
    <ConfigCard
      title={phaseInfo.title}
      summary={
        <div className="text-[12px] text-fg-muted">
          {bindings?.available_domains?.length ?? 0} domains · 
          {bindings?.available_actions?.length ?? 0} actions
        </div>
      }
      editing={expanded}
      onEdit={() => setExpanded(true)}
      onCancel={() => setExpanded(false)}
    >
      {/* 显示可用的 domains 和 actions */}
      <div className="space-y-3">
        <div>
          <div className="text-[11px] font-medium text-fg-muted mb-2">
            Available Domains
          </div>
          <div className="flex flex-wrap gap-1.5">
            {bindings?.available_domains?.map((domain) => (
              <DomainBadge key={domain} domain={domain} />
            ))}
          </div>
        </div>
        
        <div>
          <div className="text-[11px] font-medium text-fg-muted mb-2">
            Available Actions ({bindings?.available_actions?.length ?? 0})
          </div>
          <div className="max-h-[200px] overflow-y-auto space-y-0.5">
            {bindings?.available_actions?.map((action) => (
              <div key={action} className="text-[11px] font-mono text-fg-muted">
                {action}
              </div>
            ))}
          </div>
        </div>
      </div>
    </ConfigCard>
  );
}
```

---

## 五、页面级优化

### 5.1 增加 DraftBanner

**修改文件**：`visualization/src/features/settings/SettingsPage.tsx`

**在 PageContent 顶部增加**：
```tsx
function PageContent({ pageId }: { pageId: keyof typeof SETTINGS_PAGES }) {
  const draftCount = useConfigDraftStore(selectDraftCount);
  const applyChanges = async () => {
    // 现有的 apply 逻辑
  };
  
  return (
    <>
      {/* Draft Banner */}
      <AnimatePresence>
        {draftCount > 0 && (
          <DraftBanner
            draftCount={draftCount}
            onReview={() => {
              // 滚动到第一个 draft 项
            }}
            onApply={applyChanges}
            onDiscard={() => {
              useConfigDraftStore.getState().discardAll();
            }}
          />
        )}
      </AnimatePresence>
      
      {/* 原有内容 */}
      {/* ... */}
    </>
  );
}
```

### 5.2 优化 SettingsNav 的 Draft 指示

**修改文件**：`visualization/src/features/settings/SettingsNav.tsx`

**在每个导航项旁边增加 Draft 计数**：
```tsx
function NavItem({ pageId, label, icon }: {...}) {
  const currentPage = useSettingsUiStore((s) => s.page);
  const draftsInPage = useConfigDraftStore((s) => 
    countDraftsInPage(s.drafts, pageId)
  );
  
  return (
    <button
      className={`nav-item ${currentPage === pageId ? "active" : ""}`}
      onClick={() => useSettingsUiStore.getState().setPage(pageId)}
    >
      {icon}
      <span>{label}</span>
      {draftsInPage > 0 && (
        <span className="ml-auto flex h-5 w-5 items-center justify-center rounded-full bg-warning text-[10px] font-medium text-white">
          {draftsInPage}
        </span>
      )}
    </button>
  );
}

function countDraftsInPage(drafts: Record<string, unknown>, pageId: string): number {
  // 根据 pageId 统计相关 drafts
  const prefix = pageIdToDraftPrefix(pageId);
  return Object.keys(drafts).filter((key) => key.startsWith(prefix)).length;
}
```

---

## 六、实施优先级与工作量

### P0：核心组件与 LlmProvidersPage（2 天）

| 任务 | 时间 | 难度 |
|------|------|------|
| 创建 ConfigCard 组件 | 2h | 中 |
| 创建 ConfigSummary 组件 | 0.5h | 低 |
| 创建 DraftBanner 组件 | 1h | 低 |
| 改造 LlmProvidersPage | 3h | 中 |
| 增加 DraftBanner 到 SettingsPage | 1h | 低 |
| 测试与调整 | 2h | - |
| **小计** | **9.5h ≈ 1.5 天** | |

### P1：其他主要页面（2 天）

| 任务 | 时间 | 难度 |
|------|------|------|
| 改造 ActionsPage | 3h | 中 |
| 改造 PhaseBindingsPage | 3h | 中 |
| 改造 CredentialsPage | 2h | 低 |
| 优化 SettingsNav Draft 指示 | 2h | 中 |
| 测试与调整 | 2h | - |
| **小计** | **12h ≈ 2 天** | |

### P2：其他页面（按需）

- LlmModelsPage
- DedicatedProvidersPage
- SearchPoliciesPage
- ExecutionPage
- WebPage
- ...

**每个页面预计 1-2 小时**

### 总计：3.5-4 个工作日

---

## 七、预期效果对比

### 7.1 LlmProvidersPage

**改进前**：
```
┌────────────────────────┐
│ Anthropic              │
│ base_url: [________]   │
│ api_key: [_________]   │
│ timeout: [____]        │
│                        │
│ OpenAI                 │
│ base_url: [________]   │
│ api_key: [_________]   │
│ timeout: [____]        │
└────────────────────────┘
```

**改进后**：
```
┌─ Anthropic ────────────────────┐
│ ● Connected                     │
│ Base URL: api.anthropic.com     │
│ Timeout: 60000ms                │
│ Models: 12 available            │
│ [Edit →]                        │
└─────────────────────────────────┘

┌─ OpenAI ───────────────────────┐
│ ○ Not configured                │
│ Base URL: Not set               │
│ [Edit →]                        │
└─────────────────────────────────┘
```

### 7.2 ActionsPage

**改进前**：
```
┌────────────────────────┐
│ workspace.edit         │
│ enabled: [x]           │
│ timeout: [____]        │
│                        │
│ workspace.write        │
│ enabled: [x]           │
│ timeout: [____]        │
└────────────────────────┘
```

**改进后**：
```
workspace
  ┌─ workspace.edit ─────┐
  │ Enabled: Yes         │
  │ Timeout: 30000ms     │
  │ [Edit →]             │
  └──────────────────────┘
  
  ┌─ workspace.write ────┐
  │ Enabled: Yes         │
  │ Timeout: 30000ms     │
  │ [Edit →]             │
  └──────────────────────┘
```

### 7.3 Draft 状态

**改进前**：
- 只在底部栏显示数量
- 修改的项没有标记

**改进后**：
- 顶部 Banner 醒目提示
- 修改的卡片有橙色边框 + 圆点
- 导航栏显示每页的 Draft 数量

---

## 八、验收标准

### 功能验收
- [ ] ConfigCard 支持 clean/draft/error 三种状态
- [ ] 卡片支持查看/编辑模式切换
- [ ] DraftBanner 正确显示并响应操作
- [ ] 至少 3 个页面完成卡片化改造

### 视觉验收
- [ ] 卡片间距统一（12px）
- [ ] Draft 状态有明确视觉标记
- [ ] 编辑模式有明确的保存/取消操作
- [ ] 响应式布局在不同窗口尺寸下正常

### 交互验收
- [ ] 编辑→保存→查看 流程流畅
- [ ] 取消编辑恢复原值
- [ ] Apply Changes 应用所有 Draft
- [ ] Discard All 清除所有 Draft

---

## 九、风险评估

### 低风险
- ✅ ConfigCard 是纯展示组件，不影响现有逻辑
- ✅ 可以逐页改造，不阻塞其他页面

### 中风险
- ⚠️ Draft 状态管理可能需要调整
  - **缓解**：保持现有 `useConfigDraftStore` 结构
- ⚠️ 表单验证逻辑可能需要适配卡片结构
  - **缓解**：验证逻辑保留在原位置，只改变呈现

### 注意事项
- 测试所有配置页面的保存/应用流程
- 确保 Draft 数量统计正确
- 验证页面切换时 Draft 不丢失

---

**执行状态**：待开始

**预计完成时间**：3.5-4 个工作日

**负责人**：GPT Agent（实施）+ Claude（审查）
