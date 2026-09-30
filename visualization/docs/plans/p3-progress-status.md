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

### P3 基线组件恢复（部分完成） 🔄
- ✅ `src/features/chat/ActivityStep.tsx`：活动步骤组件
- ✅ `src/features/chat/LiveStatus.tsx`：实时状态卡片
- ✅ `src/features/chat/TurnView.tsx`：Turn 容器
- ✅ `src/hooks/useNow.ts`：计时 hook
- ✅ `src/components/trace/semantic.tsx`：状态徽标
- ✅ `src/features/chat/useTurnPresentation.ts`：presentation hooks

### 集成工作 ✅
- ✅ WebSocket 事件路由到 presentationStore（app/connection.ts）
- ✅ Gap 标记 incomplete
- ✅ Generation 变化重置
- ✅ Turn 切换自动创建/清除 buffer

## 待完成

### P3 剩余工作
1. 修复类型错误：
   - `adapters.ts`：TurnSnapshot 类型断言
   - `eventReplay.ts`：导入 fetchEvents
   - `TurnView.tsx`：QuestionCard props

2. 创建缺失组件：
   - AnswerCard 完整实现（typewriter 动画）
   - 其他必要的小组件

3. ChatView 集成：
   - 渐进式集成 TurnView
   - 测试实时 Turn 显示
   - 测试历史 Turn 显示

### P4 Turn Trace 主呈现
- TurnTraceDrawer 恢复
- Cycle/Phase/Action 时间线
- 控制操作、MessageStack
- 下钻到 Inspector

### P5 Session history 收敛
- 会话历史层级
- 历史 Turn 只读模式
- Session Day/Turn browser

### P6 Settings 中文化
- 集中式文案映射
- 覆盖所有设置页面

### P9 完整验收
- vitest、tsc、Vite build
- Playwright e2e 测试
- 基线截图对比

## 当前阻塞项

1. **类型错误**：adapters.ts 需要正确的 TurnSnapshot 类型定义
2. **API 缺失**：fetchEvents 需要从正确的位置导入
3. **组件对接**：QuestionCard 需要适配新的 props

## 下一步行动

1. 修复剩余类型错误
2. 运行 `pnpm tsc --noEmit` 验证无错误
3. 运行 `pnpm build` 验证构建通过
4. 创建简单的集成测试验证 presentation 层工作
5. 在 ChatView 中渐进式集成 TurnView

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
