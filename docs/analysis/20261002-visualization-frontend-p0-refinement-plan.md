# P0 前端视觉基础改进执行计划

**创建日期**：2026-10-02  
**状态**：`pending`  
**基线**：9e6546d (v2 基线复用完成)  
**目标**：在保持 c479ca0 核心体验的基础上，进行 P0 级别的视觉基础改进

## 范围与目标

基于 `20261002-visualization-frontend-refinement-analysis.md` 的深度分析，本计划聚焦 P0 优先级改进：

1. **R1**: 优化 LiveStatus 信息层次与窗口大小
2. **R2**: 统一动效节奏，参考原版 502b76d 的打磨结果
3. **R3**: 增强 thinking 流可读性，改进长段落展示

**预期收益**：
- 减少视觉噪音，信息更聚焦
- 动效语言更一致，流畅度提升
- 长 thinking 段落阅读体验改善

**不改动**：
- v2 接口适配层
- 核心滚动编排（20px 锚点、700ms 滑动）
- 完成折叠与回答流入时序
- Context/Trace 详情结构

## 设计细节

### R1: LiveStatus 信息层次优化

#### 当前状态
```typescript
// visualization/src/features/chat/LiveStatus.tsx:43-44
const ROLL_WINDOW = 14;
const TRAIL_MAX_PX = 256;
```

**问题分析**：
- `ROLL_WINDOW = 14` 比原版 `9` 多 55%，在连续动作场景下信息密度过高
- `TRAIL_MAX_PX = 256` 在窄屏或多任务场景下占据过多垂直空间
- 原版经过多轮打磨（502b76d, 15b3e9a）确立的 `9` 是视觉平衡点

#### 改进方案
```typescript
// LiveStatus.tsx 常量调整
const ROLL_WINDOW = 10;        // 当前 14 → 10，在原版 9 基础上略宽容
const TRAIL_MAX_PX = 220;      // 当前 256 → 220，减少 14%
const MILESTONE_WINDOW = 3;    // 保持不变

// 影响：
// - "Show all steps" 按钮出现频率增加，但信息更聚焦
// - 视口高度减小后，完成折叠更紧凑
// - 需要重新验证自动展开与手动收起逻辑
```

#### 验收标准
- [ ] 浏览器测试：连续 5+ 动作场景下，trail 不超过 220px
- [ ] 组件测试：`ROLL_WINDOW` 边界处的展开逻辑正确
- [ ] Playwright：`chat-flow.pw.ts` 中的 Activity 可见性断言通过
- [ ] reduced-motion：立即显示全部时不受影响

### R2: 动效节奏统一

#### 当前状态
```typescript
// visualization/src/features/chat/LiveStatus.tsx:45-59
const ROLL_STRIDE_MS = 1100;
const DRAIN_STRIDE_MS = 240;
const ROLL_MS = 420;
const REVEAL_MS = 340;
const DRAIN_ROLL_MS = 320;
const DRAIN_REVEAL_MS = 280;
const THINK_ERASE_MS = 300;
const THINK_REVEAL_DELAY_MS = 60;
const THINK_REVEAL_MS = 450;
const THINK_LINE_HEIGHT = 20;
const SLATE_GLIDE_MS = 360;
const MILESTONE_WINDOW = 3;
const GIST_POP_DELAY_MS = 400;
```

**问题分析**：
- `DRAIN_STRIDE_MS = 240` 与 thinking 层节奏（300+60+450）不够协调
- `REVEAL_MS = 340` 与 `ROLL_MS = 420` 的组合形成 760ms 双阶段，略显拖沓
- 原版 502b76d 的 `ROLL_MS = 500` + `REVEAL_MS = 400` 更均衡

#### 改进方案
```typescript
// LiveStatus.tsx 节奏调整
const ROLL_STRIDE_MS = 1100;      // 保持，主节拍器
const DRAIN_STRIDE_MS = 200;      // 240 → 200，与 thinking erase 同步
const ROLL_MS = 500;              // 420 → 500，参考原版
const REVEAL_MS = 400;            // 340 → 400，参考原版
const DRAIN_ROLL_MS = 350;        // 320 → 350，与正常 ROLL 对齐
const DRAIN_REVEAL_MS = 300;      // 280 → 300，与正常 REVEAL 对齐
const GIST_POP_DELAY_MS = 450;    // 400 → 450，保持两拍清晰感

// 其他保持不变：
const THINK_ERASE_MS = 300;
const THINK_REVEAL_DELAY_MS = 60;
const THINK_REVEAL_MS = 450;
const SLATE_GLIDE_MS = 360;
```

**时间线对比**（单步入场）：
```
当前实现：
0ms     ---------- 行开始插入
420ms   ---------- ROLL_MS 完成，内容开始显现
760ms   ---------- REVEAL_MS 完成，内容完全可见
1160ms  ---------- GIST_POP_DELAY_MS，gist 开始展开
1510ms  ---------- gist 展开完成

改进后：
0ms     ---------- 行开始插入
500ms   ---------- ROLL_MS 完成，内容开始显现
900ms   ---------- REVEAL_MS 完成，内容完全可见
1350ms  ---------- GIST_POP_DELAY_MS，gist 开始展开
1700ms  ---------- gist 展开完成（稍晚，但节奏更均匀）
```

#### 验收标准
- [ ] Vitest：`LiveStatus.test.tsx` 的时序断言更新并通过
- [ ] 浏览器测试：录制 3 秒动作入场片段，验证节奏流畅
- [ ] Playwright：逐帧采样验证新时序（参考 `chat-flow.pw.ts:136-148`）
- [ ] reduced-motion：仍为 0ms，不受影响

### R3: Thinking 流可读性增强

#### 当前状态
```typescript
// visualization/src/features/chat/ActivityStep.tsx:144-173
function ThinkingBody({ text }: { text: string }) {
  const [open, setOpen] = useState(false);
  const { ref, truncated } = useTruncated<HTMLSpanElement>(text);
  const lines = text.split("\n").filter((l) => l.trim().length > 0);
  const preview = lines[0] ?? text;  // 只显示第一行
  const hasMore = lines.length > 1 || truncated || open;
  
  return (
    <div>
      <button onClick={() => { holdFollow(); setOpen(!open); }}>
        <span ref={ref} className="truncate text-[12px] italic text-fg-muted">
          {preview}
        </span>
        {hasMore && <ChevronRight />}
      </button>
      {open && hasMore && (
        <div className="rounded-lg bg-accent-soft/50 px-2.5 py-2">
          <Markdown className="md-calm text-[12px] text-fg-muted">{text}</Markdown>
        </div>
      )}
    </div>
  );
}
```

**问题分析**：
- 单行预览在多段 thinking 时信息量不足
- 展开后的段落间距与正文段落不一致
- 长段落（>200 字）展开后可能造成突然的高度跳变

#### 改进方案
```typescript
// ActivityStep.tsx ThinkingBody 增强
function ThinkingBody({ text }: { text: string }) {
  const [open, setOpen] = useState(false);
  const holdFollow = useHoldChatFollow();
  const { ref, truncated } = useTruncated<HTMLSpanElement>(text);
  const lines = text.split("\n").filter((l) => l.trim().length > 0);
  
  // 改进 1：预览显示前两个非空段落（如果第一段很短）
  const firstPara = lines[0] ?? text;
  const secondPara = lines.length > 1 && firstPara.length < 60 ? lines[1] : null;
  const preview = secondPara ? `${firstPara} ${secondPara}` : firstPara;
  
  const hasMore = lines.length > (secondPara ? 2 : 1) || truncated || open;
  const isLong = text.length > 200;

  return (
    <div>
      <button
        onClick={() => { holdFollow(); setOpen(!open); }}
        className="flex w-full items-start gap-1 text-left"
      >
        <span 
          ref={ref} 
          className={`min-w-0 flex-1 text-[12px] italic text-fg-muted ${
            secondPara ? "line-clamp-2" : "truncate"
          }`}
        >
          {preview}
        </span>
        {hasMore && (
          <ChevronRight
            size={11}
            className={`mt-0.5 shrink-0 text-fg-faint transition-transform ${
              open ? "rotate-90" : ""
            }`}
          />
        )}
      </button>
      {open && hasMore && (
        // 改进 2：增加 leading-relaxed，改善段落间距
        <div className="mt-1.5 rounded-lg bg-accent-soft/50 px-3 py-2.5">
          <Markdown 
            className={`md-calm text-[12px] leading-relaxed text-fg-muted ${
              isLong ? "max-h-[240px] overflow-y-auto" : ""
            }`}
          >
            {text}
          </Markdown>
          {isLong && (
            <div className="mt-1 text-[10px] text-fg-faint">
              {text.length} characters
            </div>
          )}
        </div>
      )}
    </div>
  );
}
```

**改进要点**：
1. 预览从单行变为智能多行：短段落显示两段，长段落保持单行
2. 展开后使用 `leading-relaxed`（1.625 行高）改善可读性
3. 超长内容（>200 字）限制最大高度并提供滚动
4. 添加字符数提示，帮助用户判断内容长度

#### 验收标准
- [ ] Vitest：`ActivityStep.test.tsx` 覆盖单段/多段/超长场景
- [ ] 浏览器测试：验证短段（<60 字）、中段（60-200 字）、长段（>200 字）展示
- [ ] Playwright：验证 thinking 预览与展开（已有基础断言）
- [ ] 可访问性：展开按钮的 `aria-label` 清晰表达当前状态

## 实施顺序

### Phase 1: R1 信息层次优化（预计 30 分钟）

1. 修改 `LiveStatus.tsx` 常量
2. 运行 `npm run test` 确保组件测试通过
3. 手动浏览器测试连续动作场景
4. 调整 Playwright 断言（如果需要）

### Phase 2: R2 动效节奏统一（预计 45 分钟）

1. 修改 `LiveStatus.tsx` 时序常量
2. 更新 `LiveStatus.test.tsx` 的时序断言
3. 录制浏览器动效片段对比
4. 更新 Playwright 逐帧验证逻辑

### Phase 3: R3 Thinking 增强（预计 1 小时）

1. 修改 `ActivityStep.tsx` 的 `ThinkingBody`
2. 编写新的 Vitest 用例覆盖多场景
3. 浏览器测试短/中/长段落
4. 验证可访问性（`aria-label`）

### Phase 4: 整体验证（预计 30 分钟）

1. 运行完整测试套件：`npm run test && npm run build`
2. 运行 Playwright：`npm run test:e2e`
3. 手动端到端验证：连续多轮 → thinking 展开 → Context 浏览 → Trace 详情
4. 截图对比关键场景（与 9e6546d 基线对比）

## 回归风险控制

### 可能受影响的区域

1. **LiveStatus 折叠逻辑**
   - `ROLL_WINDOW` 减小可能影响 `showAll` 切换
   - 缓解：重点测试边界条件（9-11 个步骤）

2. **动效连贯性**
   - 时序调整可能导致视觉跳变
   - 缓解：逐帧 Playwright 验证，录制前后对比

3. **Thinking 高度变化**
   - 预览行数增加可能影响滚动锚定
   - 缓解：`useConversationScroll` 的 ResizeObserver 会自动调整

### 回滚方案

每个 Phase 独立提交，如果验证失败：
- 回滚对应 commit
- 保留已通过的其他 Phase
- 修正后重新提交

## 验收清单

### 自动化测试
- [ ] `npm run test` 全部通过（799 项 Vitest）
- [ ] `npm run build` 无错误无警告
- [ ] `npm run test:e2e` 全部通过（Playwright）
- [ ] TypeScript 类型检查通过

### 手动验证
- [ ] 连续 5+ 动作场景，LiveStatus 不超过 220px 高度
- [ ] 动作入场节奏流畅，无视觉跳变
- [ ] 短/中/长 thinking 段落展示合理
- [ ] reduced-motion 用户不受影响
- [ ] 刷新后 Session 恢复正确

### 视觉对比
- [ ] 截图对比：LiveStatus 信息密度（改进前后）
- [ ] 录屏对比：动作入场节奏（改进前后）
- [ ] 截图对比：thinking 展开效果（单段/多段/长段）

## 后续建议

完成 P0 后，建议：

1. **收集用户反馈**：实际使用中的信息密度、节奏感受
2. **性能监测**：长会话场景下的渲染性能
3. **规划 P1**：Context Inspector 导航增强、Trace 时间线视图

## 参考

- 原版打磨版本：502b76d, 91cb4d7, 15b3e9a
- 当前基线：9e6546d
- 深度分析：`20261002-visualization-frontend-refinement-analysis.md`
- 原设计：`visualization/docs/design/chat.md`
- 原验收：`docs/analysis/done/20261002-done-visualization-baseline-detail-restoration-plan.md`
