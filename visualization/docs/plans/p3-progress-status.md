# P3 Chat 基线恢复进度状态

日期：2026-10-01  
状态：in_progress

## 已完成

### P0 基线冻结与行为清单 ✅
- `docs/review/baseline-checklist.md`：详细记录 c479ca0 组件结构
- 确认待恢复组件清单
- 确认当前 v2 页面保留清单

### P1 v2 Chat presentation projection ✅
- `src/features/chat/presentation.ts`：核心呈现类型
- `src/features/chat/adapters.ts`：v2 snapshot → presentation 适配
- `src/features/chat/presentationStore.ts`：presentation 层 store
- `src/features/chat/eventReplay.ts`：事件 replay 工具

### P2 ActivityBuffer 完整实现 ✅
- `src/features/chat/activityBuffer.ts`：完整事件解析逻辑
  * deriveHeadline：phase/domain/skill
  * deriveThinking：思考流
  * deriveTrail：活动步骤（10 种类型）
  * deriveWorking：todos/milestones

### P3 基线组件恢复 ✅
- ✅ `src/features/chat/ActivityStep.tsx`：活动步骤组件
- ✅ `src/features/chat/LiveStatus.tsx`：实时状态卡片
- ✅ `src/features/chat/TurnView.tsx`：Turn 容器
- ✅ `src/hooks/useNow.ts`：计时 hook
- ✅ `src/components/trace/semantic.tsx`：状态徽标
- ✅ `src/features/chat/useTurnPresentation.ts`：presentation hooks

### P3.5 ChatView 集成 ✅
- ✅ LiveActivityCard 使用 useTurnPresentation hook
- ✅ Details 按钮连接到 openTurnProcess（Inspector drawer）
- ✅ LiveStatus 支持 live/settled 模式
- ✅ 保留 v2 interaction stream 架构
- ✅ QuestionCard 完整集成
- ✅ AnswerCard + Typewriter + Markdown + 代码高亮

### 集成工作 ✅
- ✅ WebSocket 事件路由到 presentationStore（app/connection.ts）
- ✅ Gap 标记 incomplete
- ✅ Generation 变化重置
- ✅ Turn 切换自动创建/清除 buffer
- ✅ 所有类型错误已修复
- ✅ 构建通过（`pnpm tsc --noEmit` + `pnpm build`）

## 待完成

### P3.5 ChatView 集成
1. ✅ LiveActivityCard Details 按钮：
   - 已连接 openTurnProcess
   - Details 按钮打开 ProcessPanel（Inspector drawer）
   - 支持 running 和 settled 状态

2. QuestionCard 适配：
   - 当前使用完整版 QuestionCard（F3-A）
   - 已集成到 ChatView

3. AnswerCard 完整实现：
   - Typewriter 动画（已有）
   - Markdown 渲染（已有）
   - 代码块高亮（已有）

4. 测试：
   - 实时 Turn 显示
   - 历史 Turn 显示
   - 活动步骤动画

### P4 Turn Trace 主呈现 ✅ (核心功能完成)
**现状**：v2 Inspector 系统（优于基线）
- ✅ ProcessPanel：Cycle/Phase/Action 树形结构
- ✅ OverviewCard：统计（Cycles、Actions、LLM calls、Searches）
- ✅ ActionDetailPanel：单个 Action 详情
- ✅ ModelCallPanel：LLM/Search 模型调用详情
- ✅ InspectorHost：右侧滑出抽屉 + 子抽屉（可伸缩宽度）
- ✅ 导航系统：TraceNavigation 跨面板导航
- ✅ 从 ChatView 的 Details 按钮打开

**待补充功能**（标记为 future work）：
- ⚠️ Working Context 卡片（todos/milestones 显示）
- ⚠️ Activity timeline（时间线 + 过滤器 + anchor 跳转）
- ⚠️ Export trace 功能（导出为 JSON/文件夹结构）

**设计决策**：保留 v2 的 Inspector 系统架构，在 ProcessPanel 基础上增强功能，
而非完全重建基线 TurnTraceDrawer（v2 架构更模块化、可扩展）。

### P5 Session history 收敛 ✅
- ✅ 历史 Turn 只读模式（historyView flag + 禁用 Composer）
- ✅ HistoryBanner（只读提示 + Session map + Process + Back to Today）
- ✅ 历史问题只显示回答事实（不可交互）
- ✅ Home actual/effective 切换（HomePage 顶部切换器）
- ✅ 归档日与活动日区分（archived flag 提示）
- ✅ Session map 面板（SessionMapPanel）
- ✅ History browser（SessionRefPanel）

**设计决策**：Chat 顶部无永久日期栏/session map/model toolbar，
通过 HistoryBanner 动态显示历史上下文。

### P6 Settings 中文化
- 集中式文案映射
- 覆盖所有设置页面

### P9 完整验收
- vitest、tsc、Vite build
- Playwright e2e 测试
- 基线截图对比

## 当前阻塞项

无。P3.5 和 P4 核心功能已完成。

## 下一步行动

1. ✅ P0: 基线清单
2. ✅ P1-P3: Presentation 层恢复
3. ✅ P3.5: ChatView 集成（Details 按钮）
4. ✅ P4: ProcessPanel 增强（Overview）
5. P5: Session history 收敛（历史 Turn 只读模式、Home actual/effective 切换）
6. P6: Settings 中文化
7. P9: 完整验收（vitest/tsc/build/e2e）

**可选增强**（future work）：
- Working Context 卡片
- Activity timeline
- Export trace

## 技术债务

- AnswerCard 的 typewriter 动画未实现（标记为 TODO）
- BudgetCard 是简化版
- LiveStatus 是简化版（移除了一些高级滚动逻辑）
- 需要补充更多测试

## 设计决策记录

1. **渐进式迁移**：保留当前 ChatView，逐步替换组件
2. **自动 buffer 管理**：presentationStore 订阅 turnStore，自动创建/清除
3. **事件驱动**：WebSocket → routeEvent → addEvent → presentation 更新
4. **类型安全**：明确的 TypeScript 接口，运行时校验动态边界
5. **单向数据流**：owner snapshot（正式） + observation events（活动） → presentation → UI
