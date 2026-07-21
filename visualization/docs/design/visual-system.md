# 视觉系统设计

## 设计目标

- 深色、低对比但可读的桌面助手风格。
- 充足留白，避免信息拥挤。
- 清晰的状态颜色与图标系统。
- 组件圆角、阴影、hover 反馈统一。

## 颜色 Token

```css
--bg: #0a0c0f;           /* 主背景 */
--bg-elevated: #111318;  /*  elevated 面板背景 */
--surface: #161a20;      /* 卡片背景 */
--surface-hover: #1d222a;
--surface-active: #232830;
--border: #2b3038;
--border-subtle: #1e2229;
--text: #f0f2f5;
--text-secondary: #9fa6b1;
--text-tertiary: #6b7280;
--accent: #58a6ff;
--accent-hover: #79b8ff;
--success: #3fb950;
--warning: #d29922;
--danger: #f85149;
--info: #39c5cf;
```

## 排版

- 正文字体：系统 sans（-apple-system、Segoe UI、Roboto、Helvetica Neue、Arial）。
- 代码/链接字体：`JetBrains Mono`、`Fira Code`、系统 monospace。
- 正文字号 14px；辅助文本 12px/11px；badge 10px。

## 尺寸与圆角

- 卡片圆角：`--radius-lg: 14px`。
- 行内元素圆角：`--radius-md: 10px`。
- Sidebar 宽度：`--sidebar-width: 68px`。
- Header 高度：`--header-height: 52px`。
- Status Bar 高度：`--status-height: 30px`。

## 组件风格

- **卡片**：`var(--surface)` 背景、`var(--border-subtle)` 边框、轻微阴影；hover 时边框变亮并提升阴影。
- **Badge**：pill 形状，按语义使用 subtle/accent/success/warning/danger 背景。
- **按钮**：Ghost/Primary/Danger 三种主要变体；图标按钮单独提供。
- **输入框**：`var(--surface)` 背景、`var(--border)` 边框；focus 时 accent 边框 + 外发光。
- **Mock Computer 卡片**：深色终端/编辑器背景（`#0d1117`），用于脚本、Shell、文档预览。

## 动效

- 全局使用 `fadeIn` 进入动画。
- 运行状态使用 `animate-spin` / `animate-pulse`。
- 过渡时长统一 0.15s–0.2s ease。
