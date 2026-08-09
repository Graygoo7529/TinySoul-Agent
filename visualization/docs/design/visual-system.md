# 视觉系统设计（Luminous）

## 设计目标

「Luminous · 有光的工作台」：LiveStatus 运行态的流光与呼吸边框是全系统的语言——运行 = 光在流动，域 = 光的颜色，层级 = 光的抬升。

- 三档明度中性底：页面底（bg）< 下沉面（bg-sunken）< 抬升面（bg-elev），层级靠明度 + hairline 边框 + 光泽投影表达。
- 浅色为默认主题，亮暗双主题由 CSS 变量驱动（`.dark` class 切换），所有组件只消费 token，不硬编码色值。
- aurora 强调渐变 + 行动域色系统；语义色（success/warning/danger/info）各配 soft 底。
- 紧凑密度、清晰排版、动效服务于"运行中"语义。

## 颜色 Token

完整定义见 `src/styles/index.css`（`:root` 浅色 / `.dark` 暗色），经 `@theme inline` 映射为 Tailwind 工具类（`bg-bg-elev`、`text-fg-muted`、`border-line`、`bg-accent-soft`、`text-domain-web` 等）。

### 中性底与文字

```css
/* 浅色 */  --bg: #f6f7f9;  --bg-elev: #ffffff;  --bg-sunken: #eef0f3;
/* 暗色 */  --bg: #0d1017;  --bg-elev: #151a23;  --bg-sunken: #090c12;
--fg / --fg-muted / --fg-faint；--line / --line-strong hairline。
```

### 强调色：aurora 渐变

`--accent-grad`（135° indigo → violet → sky）是唯一的品牌渐变，只用于品牌触点：用户气泡、Agent 头像、NavRail logo、primary 按钮、发送按钮。运动渐变（text-shine 流光标题、live-border 呼吸边框）经 `--hue-violet` 在 accent→violet→info 间流动。

### 行动域色（domain hues）

与后端行动域一一对应的一致色，各配 `-soft` 底；用于 DomainChip（Badge 色调）、ActionCard 家族图标盒、MessageStackView 分区点：

| 域 | 色（浅色 / 暗色） | token |
|---|---|---|
| core | indigo（= accent） | `--domain-core(-soft)` |
| workspace | blue `#2563eb / #60a5fa` | `--domain-workspace(-soft)` |
| execution | orange `#ea580c / #fb923c` | `--domain-execution(-soft)` |
| web | teal `#0d9488 / #2dd4bf` | `--domain-web(-soft)` |
| home | purple `#9333ea / #c084fc` | `--domain-home(-soft)` |
| memory | pink `#db2777 / #f472b6` | `--domain-memory(-soft)` |
| maintenance | slate | `--domain-maintenance(-soft)` |

Badge 十色调全部经 token：gray/green/red/yellow/blue/accent 用语义变量，purple/teal/orange/pink 映射到 home/web/execution/memory 域色。组件侧经 `domainHueClasses(domain)`（`components/trace/semantic.tsx`）取静态类名。

### 语义色

`--danger/--success/--warning/--info` 各配 `--*-soft`；状态语义（成功绿、失败红、超时/警示黄、信息蓝）与域色正交——域色表达"谁在行动"，语义色表达"结果如何"。

## 层级、光泽与玻璃

- **elevation 投影**：`--shadow-card`（e1 卡片：顶部 1px 内高光 + 接触影 + 氛围影）、`--shadow-pop`（e2 弹层/抽屉：内高光 + 大氛围影）、`--shadow-brand`（渐变品牌件：内高光 + accent 色晕）。同级表面只用对应档位的投影，不再混用 shadow-sm。
- **玻璃拟态**：e2 覆盖层（TurnTraceDrawer / LlmTaskDrawer / BackgroundDrawer）用 `.glass-panel`（80% 底 + 14px blur + 1.35 饱和），与下层内容产生景深；抽屉头部保持实色 bg-elev 以稳定阅读。
- **暗色辉光**：运行中的 LiveStatus 卡在暗色主题下有低透明度 accent 辉光（`.dark .live-border` box-shadow）。
- **z-index 刻度**：`--z-overlay(40) < --z-drawer(50) < --z-toast(60) < --z-subdrawer(70)`，组件经 `z-(--z-*)` 消费，不硬编码数字。
- **统一焦点环**：`--focus-ring`（3px accent-soft），Composer 用 `focus-within:shadow-(--focus-ring)`，文本输入统一 `focus-ring` 类。

## 排版

- 正文：`Inter Variable`（本地打包可变字体）→ PingFang SC / Microsoft YaHei / system-ui 回退，基准 14px。
- 等宽：`JetBrains Mono Variable` → Cascadia Code / Consolas 回退（代码、link、ID、token 计数）。
- 数字场景（计时器、统计、token 计数）启用 `tabular-nums` 防止跳动。
- 层级：14 正文 → 13 导航/按钮 → 12 辅助 → 11/10 时间戳与角标。

## 圆角 / 间距

- 圆角递进：按钮/徽章 6px（rounded-md）→ 输入/折叠块/行 8px（rounded-lg）→ 卡片/弹窗 12px（rounded-xl）→ 聊天气泡 16px（rounded-2xl，用户去右上、Agent 去左上）。
- 卡片内边距 16px；步骤栈/列表间距 4–6px。

## 组件风格

- **NavRail**：激活 tab 为 bg-active + 左侧 3px accent 指示条；logo 为 aurora 渐变 + shadow-brand。
- **按钮**：primary（aurora 渐变底白字）/ secondary / ghost / danger / outline 五变体，xs/sm/md 三档高度；发送/停止按钮用 shadow-brand。
- **Badge**：soft 底 + 同色文字，十色调全 token 化；domain、状态、level 固定映射（见 `components/trace/semantic.tsx`）。
- **聊天气泡**：用户气泡 aurora 渐变 + shadow-brand（含顶部内高光）；Agent 回答卡 bg-elev + shadow-card。
- **Composer**：e1 抬升输入卡（shadow-card），focus-within 时 accent 边框 + 统一焦点环。
- **输入框**：bg-elev + line 边框；focus 时 accent 边框 + `--focus-ring`，不用 outline。
- **JSON 树**：等宽 12.5px，key=info、字符串=success、数字=accent、布尔=warning、null=faint；对象/数组可折叠。
- **终端块**（stdout/stderr/命令）：固定 `#0d1117` 深底，stderr 红、命令行蓝——双主题下保持一致的可读性；exit 0 用 success token。
- **Markdown**（`.md-body`）：紧凑标题层级、行内 code 灰底 accent 字、pre 圆角 code-bg、表格/引用/任务列表齐全。

## 动效

- `fade-in`（0.18s）用于弹层与消息进入；`slide-in-right`（0.22s）用于抽屉；drawer 用 0.24s cubic-bezier 推入。
- 运行态统一 `pulse-dot` / `spin-slow`；LiveStatus 专属 `text-shine`（2.6s 流光）、`live-border`（2.8s 呼吸）、`status-in`（0.28s 上浮）、`reveal`（0.45s 实体化）、`step-in`（0.3s 交错 + 纵深渐隐）。
- 交互反馈只用 `transition-colors`，不用 spring/scale；无限动效全部服务"运行中"语义。
- `prefers-reduced-motion` 下禁用流光/呼吸/浮动类动效。
