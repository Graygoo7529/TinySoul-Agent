# 视觉系统设计

## 设计目标

- 三档明度的中性工具风：页面底（bg）< 下沉面（bg-sunken）< 抬升面（bg-elev），层级靠明度 + 单层 hairline 边框表达，阴影克制。
- 浅色为默认主题，亮暗双主题由 CSS 变量驱动（`.dark` class 切换），所有组件只消费 token。
- 单一 indigo 强调色；语义色（success/warning/danger/info）各配 soft 底。
- 紧凑密度、清晰排版、克制动效。

## 颜色 Token

完整定义见 `src/styles/index.css`（`:root` 浅色 / `.dark` 暗色），经 `@theme inline` 映射为 Tailwind 工具类（`bg-bg-elev`、`text-fg-muted`、`border-line`、`bg-accent-soft` 等）。

```css
/* 浅色 */
--bg: #f6f7f9;  --bg-elev: #ffffff;  --bg-sunken: #eef0f3;
--fg: #1c2333;  --fg-muted: #5b6577; --fg-faint: #98a2b3;
--line: #e3e6eb; --line-strong: #cfd4dc;
--accent: #6366f1; --accent-strong: #4f46e5; --accent-soft: rgba(99,102,241,.12);
--danger: #dc2626; --success: #16a34a; --warning: #d97706; --info: #0284c7; /* 各配 --*-soft */

/* 暗色 */
--bg: #101216;  --bg-elev: #171a20;  --bg-sunken: #0b0d10;
--fg: #e6e9ef;  --fg-muted: #9aa4b2; --fg-faint: #646e7d;
--line: #262b34; --line-strong: #363d49;
--accent: #818cf8; --accent-strong: #6366f1;
```

## 排版

- 正文：`Inter, PingFang SC, Microsoft YaHei, system-ui…`，基准 14px。
- 等宽：`JetBrains Mono, Cascadia Code, Consolas`（代码、link、ID、token 计数）。
- 层级：14 正文 → 13 导航/按钮 → 12 辅助 → 11/10 时间戳与角标。

## 圆角 / 间距 / 阴影

- 圆角递进：按钮/徽章 6px（rounded-md）→ 输入/折叠块/行 8px（rounded-lg）→ 卡片/弹窗 12px（rounded-xl）→ 聊天气泡 16px（rounded-2xl，用户去右上、Agent 去左上）。
- 卡片内边距 16px；弹层阴影仅 `--shadow-pop`；主按钮/气泡/输入容器用 `shadow-sm`。

## 组件风格

- **按钮**：primary（accent 底白字）/ secondary / ghost / danger / outline 五变体，xs/sm/md 三档高度。
- **Badge**：soft 底 + 同色文字，gray/green/red/yellow/blue/accent/purple/teal/orange/pink 十色调；domain、状态、level 都有固定映射（见 `components/trace/semantic.tsx`）。
- **输入框**：bg-elev + line 边框；focus 时 accent 边框 + `ring-accent/20`，不用 outline。
- **JSON 树**：等宽 12.5px，key=info、字符串=success、数字=accent、布尔=warning、null=faint；对象/数组可折叠。
- **终端块**（stdout/stderr/命令）：固定 `#0d1117` 深底，stderr 红、命令行蓝——双主题下保持一致的可读性。
- **Markdown**（`.md-body`）：紧凑标题层级、行内 code 灰底 accent 字、pre 圆角 code-bg、表格/引用/任务列表齐全。

## 动效

- `fade-in`（0.18s）用于弹层与消息进入；`slide-in-right`（0.22s）用于滑窗；drawer 用 0.24s cubic-bezier 推入。
- 运行态统一 `pulse-dot` / `spin-slow`；流式光标 `stream-caret`。
- 交互反馈只用 `transition-colors`，不用 spring/scale。
