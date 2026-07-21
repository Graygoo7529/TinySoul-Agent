# 20260721 Done：执行轨迹与运行时语义可视化重构

> 状态：已完成

## 已完成内容

### 1. Turn 结束状态修复

- 后端以 `turn.completed` 事件标识 Turn 结束（`payload.status` 为 answered/failed/stopped/exhausted）。
- 前端 `useDerivedChat` 新增对该事件的解析，Turn 结束后立即移除 `currentActivity`，避免仍然显示 “Thinking…” / running 状态。

### 2. Cycle 运行时语义可视化

- **Cycle 头部**：显示本 Cycle 选中的 action domains（从 Phase1 `select_action_domains` tool call 提取）、action 数量、完成状态。
- **Phase1**：分两步展示——“Update context”（loaded/evicted background links）、“Select action domains”（domain chips）。
- **Phase2**：展示 planned actions，状态徽章为 `planned`，不再使用运行中 spinner。
- **Phase3**：展示 executed actions 结果与 workspace effects；结果与计划分离，避免状态混淆。
- 增加横向 Phase stepper（Context / Plan / Act）。

### 3. Mock Computer Action 卡片

- 文档编辑：文件预览、行数、保存状态。
- 脚本执行：代码终端样式、语言、参数、stdout/stderr、exit code。
- Shell 命令：终端样式、工作目录、输出、退出码。
- 长时 Process：job state、elapsed、execution id、stdout/stderr、candidate changes。

### 4. 移除冗余布局

- `ReasoningTree` 简化为仅展示 `CycleTimeline`。
- 原 Turn 级别的 “All model calls” / “Turn context” 标签移除；LLM Context 嵌在 Phase 内，Top links 由全局 Background Context 面板维护。

### 5. 视觉精致化

- Cycle / Phase / Action 卡片统一圆角、阴影、hover 反馈。
- Phase 内部采用左侧圆点 timeline 步骤。
- Domain chip 按 domain 类型着色。
- ActionCard 支持 `planned` / `executed` 两种模式。

## 前端相关文件

- `visualization/src/hooks/useDerivedChat.ts`
- `visualization/src/components/ReasoningTree.tsx`
- `visualization/src/components/CycleTimeline.tsx`
- `visualization/src/components/PhaseCard.tsx`
- `visualization/src/components/PhaseStepper.tsx`
- `visualization/src/components/ActionCard.tsx`
- `visualization/src/styles/global.css`
