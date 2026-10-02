# P0+ 前端视觉基础改进增强执行计划

**创建日期**：2026-10-02  
**状态**：`done`  
**完成日期**：2026-10-02  
**基线**：9e6546d (v2 基线复用完成)  
**目标**：在原P0基础上，增加用户反馈的4项关键改进

## 背景

基于 `20261002-visualization-frontend-p0-refinement-plan.md` 的原始P0计划，用户使用中发现4项关键问题：

1. **无信息的phase标题条目**：Understanding/Planning/Executing 作为独立条目出现在trail中
2. **Turn启动位置反转**：LiveStatus先出现在上、用户气泡在下，然后反转
3. **初始Loaded home显示**：turn开始时不应显示
4. **缺失stage1细节**：原版显示control action、intent、milestone/todo设置等

## 增强范围

### 原P0项目（保留）
- R1: LiveStatus 信息层次优化（ROLL_WINDOW 14→10，TRAIL_MAX_PX 256→220）
- R2: 动效节奏统一
- R3: Thinking 可读性增强

### 新增P0+项目
- **R4**: Phase标题条目优化
- **R5**: Turn启动布局修正
- **R6**: Context snapshot事件过滤
- **R7**: Activity阶段视觉分组（可选增强）

---

## R4: Phase标题条目优化

### 问题分析

**当前行为**：
```typescript
// activityBuffer.ts:221-238
if (event.name === "loop.phase.started") {
  return {
    id: `step-${event.sequence}`,
    type: "phase_start",
    content: {
      type: "phase_start",
      phase: { phase, label: this.getPhaseLabel(phase), ... }
    }
  };
}
```

每次phase切换都生成一个独立的trail条目，显示为"Understanding" / "Planning" / "Executing"，但这些条目本身没有实际信息。

**原版行为**：
- Phase标题只在LiveStatus的headline显示（动态标题）
- Trail中不出现空的phase条目
- 只有phase内的实际动作（domain select、skill mount、action call等）才进入trail

### 解决方案

**方案A（推荐）**：phase_start不进入trail，只更新headline
```typescript
// activityBuffer.ts:221-238
if (event.name === "loop.phase.started") {
  // Don't add to trail — phase transitions only update the headline.
  // The headline already reflects the latest phase via deriveHeadline().
  return null;
}
```

**影响**：
- Trail更紧凑，只显示有实际信息的步骤
- Phase切换仍在headline正确显示
- 与原版行为一致

**方案B（可选）**：合并phase与首个动作
```typescript
// 在首个domain_select/skill_mount时附加phase信息
// 但这会增加复杂度，不推荐
```

### 验收标准
- [ ] Phase切换时headline更新（"Understanding" → "Planning" → "Executing"）
- [ ] Trail中不出现空的phase条目
- [ ] Domain select、skill mount等正常显示
- [ ] 浏览器测试：连续3个phase的turn，trail紧凑无冗余

---

## R5: Turn启动布局修正

### 问题分析

**当前布局顺序**（ChatView.tsx:103-119）：
```typescript
<section data-turn-root>
  {/* 1. 用户输入气泡 */}
  {items.filter(item => item.role === "user.input").map(...)}
  
  <AgentRow>
    {/* 2. LiveStatus（如果有activity） */}
    {activity && <LiveStatus ... />}
    
    {/* 3. 其他交互（包括回答） */}
    {items.filter(item => item.role !== "user.input" && ...).map(...)}
    
    {/* 4. 控制卡片 */}
    <CurrentTurnControls />
    <TurnFooter />
  </AgentRow>
</section>
```

**问题**：
- 新turn启动时，user.input先渲染（第1步）
- activity随后出现（第2步），此时在user.input下方，但在AgentRow内
- 由于AgentRow布局和滚动锚定，可能出现视觉上的位置调整

**预期布局**：
- 用户气泡始终在上
- AgentRow（包含LiveStatus）始终在下
- 新turn出现时不应有位置反转

### 解决方案

**问题根源**：
检查代码后发现，布局结构本身是正确的（用户气泡在上，AgentRow在下）。问题可能来自：

1. **动画时序**：LiveStatus的animate-fade-in可能比用户气泡更快
2. **滚动锚定**：useConversationScroll在新turn出现时的锚定目标

**方案A（推荐）**：确保用户气泡先完全渲染
```typescript
// ConversationRows.tsx:90-105 (UserBubble)
// 新turn的用户气泡应该立即可见，不应有fade-in延迟

function UserBubble({ text, label }: { text: string; label?: string }) {
  // Remove animate-fade-in for initial user input in fresh turns
  return (
    <div className="flex justify-end">
      {/* ... 保持原有结构 ... */}
    </div>
  );
}
```

**方案B**：LiveStatus延迟显示
```typescript
// 在activityBuffer首次有实际内容（非空trail/thinking）前，不显示LiveStatus
// 但这可能影响"Understanding"标题的显示
```

**方案C**：检查滚动锚定逻辑
```typescript
// useConversationScroll.ts:101-120
// 确保新turn的锚定目标是整个turn-root，而不是LiveStatus
```

### 实施步骤

1. 浏览器录屏验证当前行为（识别确切的反转时机）
2. 添加console.log追踪渲染顺序
3. 调整动画时序或锚定逻辑
4. 验证多种场景（快速回复、长处理、滚动中断）

### 验收标准
- [ ] 新turn启动时，用户气泡始终在上
- [ ] LiveStatus出现时，不会导致用户气泡位置跳变
- [ ] 滚动锚定到turn-root顶部（20px）
- [ ] Playwright录屏验证无反转（参考chat-flow.pw.ts:76-90）

---

## R6: Context snapshot事件过滤

### 问题分析

**当前行为**：
```typescript
// activityBuffer.ts:257-272
if (event.name === "context.background.snapshot" || event.name === "context.background.changed") {
  const loaded = asStringArray(event.payload[...]);
  const summary = [loaded.length ? `Loaded ${loaded.join(", ")}` : "", ...].filter(Boolean).join("; ");
  if (!summary) return null;
  return {
    id: `step-${event.sequence}`,
    type: "context_update",
    content: { type: "context_update", summary },
    autoExpandGist: false,
  };
}
```

**问题**：
1. Turn启动时的初始snapshot显示"Loaded home:xxx"，但这是背景加载，不是动作
2. 原版只显示动态加载/逐出事件，不显示初始snapshot
3. 用户期望：初始Home加载不显示，只有显式加载/逐出才显示

### 解决方案

**方案A（推荐）**：区分snapshot（初始）和changed（增量）
```typescript
// activityBuffer.ts:257-272
if (event.name === "context.background.changed") {  // 只处理changed，忽略snapshot
  const loaded = asStringArray(event.payload.loaded_links);
  const evicted = asStringArray(event.payload.evicted_links);
  
  // 只有实际有变化时才显示
  if (loaded.length === 0 && evicted.length === 0) return null;
  
  const summary = [
    loaded.length ? `Loaded ${loaded.join(", ")}` : "",
    evicted.length ? `Evicted ${evicted.join(", ")}` : ""
  ].filter(Boolean).join("; ");
  
  return {
    id: `step-${event.sequence}`,
    type: "context_update",
    content: { type: "context_update", summary },
    autoExpandGist: false,
  };
}
// 不处理 context.background.snapshot
```

**方案B（可选）**：时间窗口过滤
```typescript
// 只显示turn启动后2秒内的动态加载
// 但这不够可靠，不推荐
```

### 用户期望的更深层问题

用户提到"原版记录stage1的control action信息"，这涉及：

1. **Control Actions**：phase1的control tool调用（如milestone.set、todo.add）
2. **Intent字段**：phase1 LLM response的intent字段
3. **Milestone/Todo设置与完成**：实时更新

**当前v2的限制**：
- v2 observation不发布control action细节
- Working state（todos/milestones）不作为event stream发布
- Intent字段未在reasoning.summary之外单独暴露

**短期方案**：
- 在activityBuffer.ts中，检查是否有control相关的observation事件
- 如果有，提取并显示milestone/todo操作

**长期方案**：
- 后端增加control action observation事件
- 后端增加working state变更事件
- 前端消费这些事件并显示在trail中

### 验收标准
- [ ] Turn启动时不显示"Loaded home:xxx"
- [ ] 显式Home/Memory加载/逐出正常显示
- [ ] Context Inspector的四子页仍正常显示背景内容

---

## R7: Activity阶段视觉分组（可选增强）

### 用户建议

"在Activity面板中，可以按照三个阶段，使相同阶段的activity背景呈现相同的淡色泽"

### 设计方案

**视觉设计**：
```typescript
// 为每个phase定义淡色背景
const phaseColors = {
  phase1: "bg-blue-500/5",     // Understanding - 淡蓝
  phase2: "bg-amber-500/5",    // Planning - 淡琥珀
  phase3: "bg-emerald-500/5",  // Executing - 淡翠绿
};

// 在ActivityStep或ActivityGlimpse中应用
<div className={`${phaseColors[currentPhase]} ...`}>
  <ActivityStep ... />
</div>
```

**实施位置**：
- 在ActivityGlimpse或LiveStatus的renderStep中
- 根据item的timestamp和phase transitions计算所属phase
- 为连续的同phase步骤应用相同背景色

**注意事项**：
- 颜色应非常淡（5-8%透明度），不干扰正文阅读
- 只在Activity面板（LiveStatus trail）应用，不影响Trace详情
- 考虑暗色模式的适配

### 实施步骤

1. 在activityBuffer中，为每个ActivityStep附加phase信息
2. 在LiveStatus的renderStep中，根据phase应用背景色
3. 定义配色方案（浅色/深色模式）
4. 浏览器测试视觉效果

### 验收标准
- [ ] 同phase的连续步骤有一致的淡色背景
- [ ] Phase切换时，背景色平滑过渡
- [ ] 颜色不干扰文本阅读（对比度充足）
- [ ] 深色模式下效果合理

---

## 实施顺序

### Phase 1: 原P0基础改进（1.5小时）
1. R1: LiveStatus信息层次（30分钟）
2. R2: 动效节奏统一（45分钟）
3. R3: Thinking可读性（15分钟快速版本）

### Phase 2: P0+关键修正（1.5小时）
4. R4: Phase标题条目优化（30分钟）
   - 修改activityBuffer.ts:221-238，返回null
   - 验证headline仍正确更新
   - 浏览器测试trail紧凑性

5. R6: Context snapshot过滤（30分钟）
   - 修改activityBuffer.ts:257-272，只处理changed
   - 验证初始Home不显示
   - 验证显式加载仍显示

6. R5: Turn启动布局修正（30分钟）
   - 录屏验证当前反转行为
   - 追踪渲染顺序和滚动锚定
   - 调整动画或锚定逻辑
   - Playwright验证无反转

### Phase 3: R3完整版 + R7可选增强（1小时）
7. R3完整实现（30分钟）
   - 智能多行预览
   - 展开排版优化
   - 超长内容处理

8. R7: 阶段视觉分组（30分钟，可选）
   - 附加phase信息
   - 应用淡色背景
   - 暗色模式适配

### Phase 4: 整体验证（30分钟）
- 完整测试套件
- 端到端浏览器验证
- Playwright录屏对比
- 截图归档

**总计**：约4.5小时（含R7），4小时（不含R7）

---

## 后端协作需求

### 短期（可选，不阻塞前端）

如果希望在Activity中显示更丰富的stage1细节，后端可以考虑：

1. **Control Action Events**
   ```typescript
   // 新增observation事件
   {
     name: "loop.control.milestone.set",
     payload: { text: "...", status: "pending" }
   }
   {
     name: "loop.control.todo.add",
     payload: { text: "...", status: "pending" }
   }
   ```

2. **Intent Field**
   ```typescript
   // 在llm.model.response中增加intent字段
   {
     name: "llm.model.response",
     payload: {
       reasoning: { summary: "...", intent: "..." }
     }
   }
   ```

3. **Working State Events**
   ```typescript
   {
     name: "context.working.changed",
     payload: {
       added_todos: [...],
       completed_todos: [...],
       set_milestones: [...]
     }
   }
   ```

### 前端适配

如果后端提供上述事件，前端在activityBuffer.ts中增加相应的处理逻辑：

```typescript
// activityBuffer.ts eventToActivityStep

// Milestone set
if (event.name === "loop.control.milestone.set") {
  return {
    id: `step-${event.sequence}`,
    type: "milestone",
    content: {
      type: "milestone",
      text: event.payload.text,
      status: event.payload.status
    }
  };
}

// Todo add/complete
if (event.name === "loop.control.todo.add") {
  return {
    id: `step-${event.sequence}`,
    type: "todo",
    content: {
      type: "todo",
      text: event.payload.text,
      status: "pending"
    }
  };
}

// Intent (as a variant of thinking)
if (event.name === "llm.model.response" && event.payload.reasoning?.intent) {
  return {
    id: `step-${event.sequence}`,
    type: "thinking",
    content: {
      type: "thinking",
      text: `Intent: ${event.payload.reasoning.intent}`
    }
  };
}
```

---

## 回归风险控制

### 高风险项

1. **R4 Phase标题移除**
   - 风险：headline可能失效，phase不显示
   - 缓解：deriveHeadline()独立工作，不依赖trail条目
   - 回滚：恢复phase_start返回值

2. **R5 布局修正**
   - 风险：滚动锚定失效，位置跳变加剧
   - 缓解：逐步调整，每次验证
   - 回滚：恢复原有动画/锚定逻辑

### 中风险项

3. **R6 Context过滤**
   - 风险：有用的加载事件被过滤
   - 缓解：只过滤snapshot，保留changed
   - 回滚：恢复两者都处理

### 低风险项

4. **R1/R2 常量调整**
   - 风险：视觉节奏不理想
   - 缓解：基于原版打磨结果
   - 回滚：恢复旧常量值

5. **R3 Thinking增强**
   - 风险：预览显示异常
   - 缓解：渐进式增强，保留基础功能
   - 回滚：恢复单行预览

6. **R7 视觉分组**
   - 风险：颜色干扰阅读
   - 缓解：非常淡的背景，可选特性
   - 回滚：移除背景色

---

## 验收清单

### 自动化测试
- [ ] `npm run test` 全部通过
- [ ] `npm run build` 无错误无警告
- [ ] `npm run test:e2e` 全部通过
- [ ] TypeScript 类型检查通过

### 手动验证 - 原P0
- [ ] R1: LiveStatus高度不超过220px
- [ ] R2: 动作入场节奏流畅（录屏对比）
- [ ] R3: Thinking预览合理，展开可读

### 手动验证 - P0+
- [ ] R4: Trail中无空phase条目，headline正确显示phase
- [ ] R5: 新turn启动无位置反转（录屏验证）
- [ ] R6: 初始Home加载不显示，显式加载正常
- [ ] R7: (可选) 阶段背景色合理，不干扰阅读

### 视觉对比
- [ ] 截图：LiveStatus信息密度（9e6546d vs 改进后）
- [ ] 录屏：动作入场节奏（9e6546d vs 改进后）
- [ ] 录屏：Turn启动过程（9e6546d vs 改进后）
- [ ] 截图：Thinking展开效果（单段/多段/长段）
- [ ] 截图：(可选) 阶段视觉分组效果

---

## 后续建议

完成P0+后：

1. **收集用户反馈**：实际使用中的体验改进效果
2. **监测性能**：确认动画和渲染性能无退化
3. **规划P1**：Context Inspector导航增强、Trace时间线视图
4. **后端协作**：如需stage1细节，协调后端增加observation事件

---

## 参考

- 原P0计划：`20261002-visualization-frontend-p0-refinement-plan.md`
- 深度分析：`20261002-visualization-frontend-refinement-analysis.md`
- 原版基线：502b76d, 91cb4d7
- 当前基线：9e6546d
- 设计文档：`visualization/docs/design/chat.md`
