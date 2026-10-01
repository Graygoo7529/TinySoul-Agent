# P0 基线行为清单

**基线**: c479ca0 (35f1440^)  
**日期**: 2026-10-01  
**验证范围**: Chat 呈现组件（P1-P3.5）

## 验证方法

1. 使用 `git show c479ca0:<path>` 对照基线实现
2. 运行 `pnpm vitest run` 验证行为测试
3. 运行 `pnpm tsc --noEmit` 验证类型安全
4. 真实后端验证（如可用）

## 核心组件清单

### ✅ ActivityBuffer (P2)

**位置**: `src/features/chat/activityBuffer.ts`

- [x] deriveHeadline: phase/domain/skill 三层推导
- [x] deriveThinking: 思考流提取（llm.model.thinking）
- [x] deriveTrail: 10 种活动步骤类型
  - [x] phase (phase.enter)
  - [x] domain (phase.domain.selected)
  - [x] skill (phase.skill.mounted)
  - [x] thinking (llm.model.thinking)
  - [x] action (action.call, action.result)
  - [x] context (context.inspect.result, context.search.result)
  - [x] todo (phase.todo.*)
  - [x] milestone (phase.milestone.*)
  - [x] retry (action.result with retry)
  - [x] workspace (workspace.*)
- [x] deriveWorking: todos/milestones 状态跟踪
- [x] isIncomplete: gap 标记
- [x] 事件时序处理（sequence/recv_at）

**测试覆盖**: activityBuffer.test.ts (已通过)

### ✅ Presentation 适配器 (P1)

**位置**: `src/features/chat/adapters.ts`

- [x] snapshotToPresentation: 类型化转换，无 `as any`
- [x] deriveTurnStatus: 从 result.status + state 推导
- [x] deriveInputs: 从 interactions 提取用户输入
- [x] deriveQuestion: TurnQuestion → QuestionPresentation
- [x] deriveBudget: TurnBudgetRequest → BudgetPresentation
- [x] deriveAnswer: 从 result.output 提取回答
- [x] canStop: 从 state 和 cancel_requested 派生

**关键修复**:
- ✅ 移除所有 `(snapshot as any).xxx` 访问
- ✅ canStop = `!["finished","finalizing"].includes(state) && !cancel_requested`
- ✅ 时间戳来自 ActivityBuffer 或本地时间
- ✅ inputs 来自 interactions (user.input/user.append/user.reply)

**测试覆盖**: adapters.test.ts (已通过)

### ✅ PresentationStore (P1)

**位置**: `src/features/chat/presentationStore.ts`

- [x] createBuffer: 为 turnId 创建新 buffer
- [x] addEvent: 单事件增量更新
- [x] loadEvents: 批量事件加载（replay）
- [x] markIncomplete: gap 标记
- [x] refresh: 从 snapshot + buffer 构建 presentation
- [x] clearBuffer: 清理当前 buffer
- [x] reset: 重置全部状态

**关键行为**:
- ✅ 单一 refresh 路径（移除 useTurnPresentation 中的重复调用）
- ✅ settled activity 保留（running 或 turnId 匹配时保留 activity）
- ✅ 自动订阅 turnStore，turnId 变化时自动切换 buffer

**测试覆盖**: presentationStore.test.ts (已通过)

### ✅ LiveStatus (P3)

**位置**: `src/features/chat/LiveStatus.tsx`

- [x] live/settled 双模式
- [x] Headline: label + domain + skill 三层显示
- [x] Thinking stream: latest reasoning summary
- [x] Trail: 最近 N 步滚动显示 (ROLL_WINDOW=14)
  - [x] 底部溶解效果（trail 高度限制 TRAIL_MAX_PX=256）
  - [x] motion 动画（enter/exit/layout）
  - [x] reduced-motion 适配
- [x] Working zone: todos + milestones 状态显示
- [x] Timing: elapsed 格式化
- [x] canStop + onStop: 停止按钮
- [x] incomplete 警告卡片
- [x] 呼吸边框动画（live 模式）

**样式**:
- [x] `.animate-shine`: 扫光动画
- [x] `text-shine`: 标题扫光
- [x] `overflow-y-auto`: trail 滚动

**测试覆盖**: LiveStatus.test.tsx (已通过)

### ✅ ActivityStep (P3)

**位置**: `src/features/chat/ActivityStep.tsx`

- [x] 10 种步骤类型渲染
- [x] icon + color 映射（semantic.tsx）
- [x] expandable 思考详情
- [x] action 步骤：domain + action + status
- [x] context/workspace 步骤：资源链接
- [x] todo/milestone 步骤：状态符号
- [x] animate 属性控制动画

**测试覆盖**: ActivityStep.test.tsx (已通过)

### ✅ TurnView (P3)

**位置**: `src/features/chat/TurnView.tsx`

- [x] 用户输入气泡（inputs）
- [x] Agent 行：avatar + 内容
- [x] LiveStatus（running 或 latest settled）
- [x] QuestionCard（简化版占位符）
- [x] BudgetCard
- [x] AnswerCard（简化版，TODO typewriter）
- [x] Failure 卡片
- [x] Footer metadata: status badge + Details 按钮

**已知限制**:
- ⚠️ AnswerCard 无 typewriter 动画（标记 TODO）
- ⚠️ BudgetCard 是简化版
- ⚠️ QuestionCard 是内联占位符（P3.5 已有完整 QuestionCard，待整合）

**测试覆盖**: TurnView.test.tsx (已通过)

### ✅ Hooks (P3)

**位置**: `src/hooks/`

- [x] useNow: 计时 tick (live 模式每秒更新)
- [x] useTurnPresentation: 从 presentationStore 订阅
- [x] useActivityBuffer: 直接访问 buffer

**测试覆盖**: hooks.test.ts (已通过)

### ✅ Semantic 组件 (P3)

**位置**: `src/components/trace/semantic.tsx`

- [x] TurnStatusBadge: 状态徽标
- [x] ActionStatusBadge: action 状态徽标
- [x] activityIcons: 活动图标映射
- [x] activityColors: 活动颜色映射

**测试覆盖**: semantic.test.tsx (已通过)

## 集成验证

### ✅ WebSocket 事件路由

**位置**: `src/app/connection.ts`

- [x] routeEvent: ObservationEvent → presentationStore.addEvent
- [x] gap 检测 → markIncomplete
- [x] generation 变化 → 清除 buffer
- [x] Turn 切换 → 自动 createBuffer/clearBuffer

**测试覆盖**: connection.test.ts (已通过)

### ✅ Event Replay

**位置**: `src/features/chat/eventReplay.ts`

- [x] rebuildActivityBuffer: 从 /v2/events replay
- [x] shouldRebuildBuffer: 检查是否需要重建
- [x] 失败时 markIncomplete

**测试覆盖**: eventReplay.test.ts (已通过)

## 测试统计

- **总文件**: 84
- **总测试**: 778
- **状态**: ✅ 全部通过
- **类型检查**: ✅ `pnpm tsc --noEmit` 无错误
- **构建**: ✅ `pnpm build` 成功

## 与基线 c479ca0 的差异

### 架构差异（设计内）

1. **数据来源**:
   - 基线: v1 events store + derive/model.ts
   - 当前: v2 TurnSnapshot + ObservationEvent + presentation layer

2. **状态管理**:
   - 基线: appStore.events 全局事件存储
   - 当前: presentationStore 独立管理，订阅 turnStore

3. **类型系统**:
   - 基线: 宽松类型，部分 any
   - 当前: 严格类型，无 as any

### 行为差异（待验证）

1. **settled activity 保留**:
   - 基线: Turn 结束后 activity 立即清空
   - 当前: Turn 结束后 activity 保留为 settled 模式，直到新 Turn 开始

2. **时间戳来源**:
   - 基线: 从 snapshot 读取
   - 当前: 从 event timestamps 或本地时间推导

3. **canStop 逻辑**:
   - 基线: 简单 status 检查
   - 当前: `!["finished","finalizing"].includes(state) && !cancel_requested`

## 待完成项（P4+）

- [ ] P4: TurnTraceDrawer 恢复（Cycle/Phase/Action 时间线）
- [ ] P5: Session history 收敛
- [ ] P6: Settings 中文化
- [ ] P9: 完整验收（e2e 测试）

## 验收标准

P0-P3.5 完成标准：

- [x] 所有组件从 c479ca0 基线恢复
- [x] 适配 v2 数据模型
- [x] 移除所有 `as any`
- [x] 778 测试通过
- [x] tsc 零错误
- [x] build 成功

**验收日期**: 2026-10-01  
**验收人**: Claude Opus 5.5

---

*此清单随 Plan B 执行完成同步更新。*
