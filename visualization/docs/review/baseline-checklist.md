# 前端基线组件行为清单

日期：2026-09-30  
基准：commit `c479ca0` (35f1440 之前)  
目标：记录旧版前端组件的可观察行为、布局、视觉节奏和交互逻辑，作为恢复工作的核对基准。

## 组件清单

### 核心待恢复组件

以下组件需要从 `c479ca0` 恢复到当前 v2 数据层之上：

#### 1. `src/components/chat/` 目录

**LiveStatus.tsx** (919 行)
- **职责**：活跃 Turn 的实时状态呈现
- **关键行为**：
  - live/settled 两种模式切换
  - 流光标题显示当前 phase headline
  - thinking 概要展示
  - 活动轨迹（ActivityStep 列表）
  - working 状态区域
  - 计时显示
  - 停止反馈按钮
  - running → settled 的折叠动画
  - 新 Turn 开始后自然收起
- **数据来源**：需改造为从 v2 Observation events 和 TurnSnapshot 读取

**ActivityStep.tsx** (300 行)
- **职责**：单个语义活动条目
- **关键行为**：
  - Phase headline（phase、domain、skill）
  - Thinking 摘要
  - Context 状态
  - Todo/milestone 进展
  - Action plan/result 双阶段
  - Provider retry 反馈
  - 图标、颜色、状态标注
- **数据来源**：需改造为从 Observation activity buffer 读取

**ActionGlimpse.tsx** (295 行)
- **职责**：Action 的规划/执行两阶段预览
- **关键行为**：
  - 规划阶段：显示 canonical name、domain、参数摘要
  - 执行阶段：显示结果类型、时长、成功/失败/超时状态
  - 有限内容预览（前 N 行）
  - 点击展开到 Inspector
- **数据来源**：需改造为从 v2 Action registry 和 TurnSnapshot 读取

**TurnView.tsx**
- **职责**：单个 Turn 的完整呈现
- **关键行为**：
  - 用户气泡（右置 accent-soft 底）
  - Agent 回答卡（左置带头像）
  - LiveStatus 嵌入（running 时）
  - 最终回答（settled 后）
  - Question 卡（等待时）
  - Budget 卡（预算等待时）
  - Pending item、OutgoingEcho
  - 状态尾部（answered/stopped/cancelled）
- **数据来源**：需改造为从 v2 Interaction/TurnSnapshot/Question/Budget 读取

**ChatView.tsx**
- **职责**：主对话页面容器
- **关键行为**：
  - 连续当日会话历史
  - 只读历史 Turn（灰化 Composer）
  - 滚动容器：顶部跟随、手动接管、恢复历史不重播动画
  - 回答 stream/settle 动画
  - reduced-motion 支持
  - Session Day 列表
  - Composer 输入区
- **数据来源**：需改造为从 v2 Session/Interaction/turnStore 读取

**Composer.tsx**
- **职责**：用户输入区
- **关键行为**：
  - 新 Turn / 追加输入 / 回复问题 三种模式
  - 意图 chip（New turn / Append / Reply）
  - 方案入口（Run plans）
  - 只读历史时完全禁用（灰化 + Read-only chip）
  - 发送按钮禁用状态
  - 占位文案切换
- **数据来源**：需改造为从 v2 turnStore 读取

#### 2. `src/components/trace/` 目录

**TurnTraceDrawer.tsx** (303 行)
- **职责**：Turn 过程详情抽屉
- **关键行为**：
  - Cycle/Phase 层级展示
  - Phase 控制操作（control ops）
  - 活动时间线
  - Todo/milestone 分组
  - MessageStack 展示
  - LLM task 分组
  - 背景加载状态
  - 事件窗口边界、truncated 标记
  - 缺少 result、取消、未执行的诚实状态
  - 下钻到 Action/Model/Search/Job Inspector
- **数据来源**：需改造为从 v2 facts/eventWindow/ProcessPanel 读取

**CycleSection.tsx**
- **职责**：单个 Cycle 的展示区
- **数据来源**：v2 process facts

**PhaseSection.tsx**
- **职责**：单个 Phase 的展示区
- **数据来源**：v2 process facts

**ActionCard.tsx**
- **职责**：Action 卡片（在 Trace 中）
- **数据来源**：v2 Action registry

**LlmTaskDrawer.tsx**
- **职责**：LLM Task 详情抽屉
- **数据来源**：v2 ModelCallPanel

**MessageStackView.tsx**
- **职责**：消息栈展示
- **数据来源**：v2 TurnSnapshot

**ControlOpsView.tsx**
- **职责**：Phase 控制操作展示
- **数据来源**：v2 observation events

**WorkingStateView.tsx**
- **职责**：working 状态展示
- **数据来源**：v2 observation events

#### 3. `src/derive/` 目录

**关键说明**：此目录在 Plan B 中**不恢复**作为独立状态权威。仅提取其中有用的：
- 活动语义解析逻辑（activitySemantics.ts）
- Phase 摘要生成（phaseSummary.ts）
- 投影函数（chat.ts 中的 presentation projection）

这些逻辑需改造为纯函数，放入新的 `features/chat/` 和 `features/trace/` 的 presentation 层。

### 当前 v2 页面保留（不回退）

以下页面已在 F0-F6 完成，保持当前实现：
- Home 页面（actual/effective 浏览）
- Memory 页面（Active/Knowledge）
- Workspace 页面
- Runtime 页面（Execution/Jobs/MCP）
- Settings 页面（需增加中文化）
- Context 抽屉
- ResourceRouter 和 Inspector
- Search 结果页
- CodeBlock 语法高亮

## 视觉与交互节奏

### 动画时序

从 `c479ca0` 的实现和视觉文档提取的关键时序：

**回答动画**：
- Terminal 态打字机：逐字显示，光标闪烁
- Terminal → Document settle：淡入淡出 + 内容擦除动画，约 300-500ms
- Settle 后凹版角标和蚀刻内框（亮主题对比极弱，记录为观察项）

**LiveStatus 展开/收起**：
- 新 Activity 进入：从上滑入，约 200ms
- Cycle 结束折叠：高度收缩 + 透明度变化，约 300ms
- 新 Turn 开始自然收起：整体淡出，约 200ms

**滚动行为**：
- 默认：新内容进入时自动滚动到底部（顶部跟随）
- 用户手动滚动：接管自动跟随，显示"回到底部"按钮
- 恢复历史：不重播历史动画，直接呈现最终态
- Reduced-motion：禁用所有动画，瞬间呈现

### 布局层级

**对话页三层底**：
- 页面背景：`--bg`
- NavRail/TopBar/StatusBar：`--bg-elev`
- 卡片/输入框：`--bg-elev` + `--line` 细边线

**消息宽度**：
- 用户气泡：最大 60% 宽度，右对齐
- Agent 回答卡：近全列宽（约 95%），左对齐
- Question 卡：中等宽度（约 70%），居中

**Trace 抽屉**：
- 固定宽度 640px（窄窗口下全宽）
- Backdrop 压暗对话页
- 内部滚动容器
- 三层信息：Cycle headline → Phase → Action/LLM/Control

### 状态标注

**Turn 状态**：
- `running`：绿色动画点 + "turn active"
- `answered`：绿色对勾 + "answered"
- `stopped`：橙色方块 + "stopped"
- `cancelled`：灰色叉号 + "cancelled"
- `failed`：红色叹号 + "failed"
- `waiting`：黄色时钟 + "waiting"

**Action 状态**：
- `planning`：蓝色 → "planning"
- `executing`：蓝色动画 → "executing"
- `success`：绿色对勾
- `failed`：红色叉号
- `timeout`：橙色时钟
- `cancelled`：灰色
- `not_executed`：灰色虚线
- `result_unknown`：灰色问号

**Phase 状态**：
- `phase1`：靛蓝
- `phase2`：青色
- `phase3`：绿色
- `failure`：红色
- `cancelled`：灰色

## 数据流改造要点

### 旧版数据来源（不恢复）

- `src/api` 下的 v1 请求模块
- `src/derive` 作为独立状态权威
- 旧 `appStore` 事件回放状态
- `exportTrace` 接口
- 任意旧路径兼容层
- v1 protocol_version

### 新版数据来源（必须使用）

**正式状态**（owner snapshot）：
- `turnStore.current`：当前 Turn 的 TurnSnapshot
- `sessionStore`：Session 历史
- `Interaction`、`TurnSnapshot`、`PendingItem`、`TurnResult`
- `Question`、`Budget`
- formal owner snapshot 决定状态、问题、预算、结果、取消和是否允许输入

**观察活动**（短生命周期）：
- WebSocket `ObservationEvent`（verbose 模式）
- `/v2/events` 定向 replay（turn_id + through）
- Activity projector：phase headline、thinking、domain/skill、context、todo/milestone、action plan/result、provider retry、working 摘要
- 连接断开、gap 或截断时：保留已显示内容并标记"不完整"
- 不用 buffer 覆盖正式结果，不补造结果

**Action 详情**：
- `features/trace/facts.ts` 的 Action registry
- canonical ID（不恢复旧别名）
- 复用 ProcessPanel、ModelCallPanel、SearchResultView、JobPanel

## 待办事项（按 Plan B 顺序）

### ✅ P7：后端 catalog 契约修正（已完成）
- `capabilities.resource.render_pdf_pages` choices 对齐
- `capabilities.web.search_by_kimi.model` catalog 声明

### ✅ P8：Home 顶层文档读取语义（已完成）
- actual/effective browse projection
- Agent `read_top()` runtime copy 分离
- 浏览接口不触发 runtime copy

### 🔄 P0：基线冻结与行为清单（当前）
- 本文档即为 P0 输出
- 下一步：补充截图对比和详细交互流程

### ⏳ P1：v2 Chat presentation projection
- 在 `features/chat/` 建立纯类型和适配函数
- `Interaction` → 消息、状态、操作行
- `TurnSnapshot` → 正式状态
- `PendingItem` → pending item
- `TurnResult` → 最终回答
- Observation facts → 过程细节和动画输入

### ⏳ P2：短生命周期 Observation activity buffer
- WebSocket `onEvent` → activity projector
- `/v2/events` replay 重建活动窗口
- 产生 phase headline、thinking、domain/skill、context、todo/milestone、action plan/result、provider retry、working 摘要
- 不覆盖正式状态，不补造结果

### ⏳ P3：恢复 Chat 基线
- 恢复 TurnView 消息顺序、活动卡、最终回答
- 恢复 LiveStatus live/settled 模式、滚动轨迹、working 区域
- 恢复 ActivityStep 语义条目
- 恢复 ActionGlimpse 双阶段预览
- 保留 v2 QuestionCard、BudgetCard、pending item、OutgoingEcho
- 保留回答 stream/settle、anchor follow、manual scroll takeover、reduced-motion
- 历史 Turn 不重播动画
- 使用当前 ResourceRouter 和 Inspector

### ⏳ P4：恢复 Turn Trace 主呈现
- 将 ProcessPanel 数据与旧版活动时间线合并
- 增加 Phase 控制操作、背景加载、todo/milestone、MessageStack、LLM task 分组
- 下钻到 Action detail、ModelCallPanel、SearchResultView、JobPanel
- 保留事件窗口边界、truncated、缺失 result、取消、未执行、结果未知的诚实状态
- 旧导出入口：导出 v2 定向 observation window 与正式交互快照 JSON

### ⏳ P5：Session history 与新增 v2 页面收敛
- 主 Chat 采用旧版会话历史层级
- Session Day/Turn browser 作为按需入口
- 只读历史不允许 Composer 提交
- Home/Memory/Workspace/Runtime/Context/ResourceRouter/Search/CodeBlock 不回退
- Home 页面提供 actual/effective 切换
- 不增加常驻 Session map、模型参数工具条

### ⏳ P6：Settings 中文化
- 增加集中式设置界面文案映射
- 覆盖导航、页面标题、section、字段说明、按钮、状态、校验、空状态
- Action、Search policy、model-use、provider/model/chain 用户解释
- aria-label、tooltip、Retry/Apply/Reset
- 配置路径、Action canonical ID、provider/model ID、枚举值、HTTP code、failure kind、代码块协议保留原值

### ⏳ P9：完整验收和文档收口
- vitest、tsc、Vite build
- 真实后端 Playwright：新 Turn、追加、回复、问题等待、预算等待、running LiveStatus、settled fold、历史 Turn、Trace、Search、Home/Memory、Settings 中文、窄窗口、明暗主题
- 以 `c479ca0` 基线截图和本清单核对 Chat/Trace
- reduced-motion、event gap、历史恢复、截断状态测试
- 更新 visualization demand 和 endpoint 文档
- 计划归档到 `docs/analysis/done/`

## 打磨改进备忘（在恢复基础上）

待补充：在 P0-P6 实施过程中记录值得改进的地方。

### 已发现项

1. **亮主题 answer-card 凹版角标对比极弱**（观察项 9）
   - 当前：凹版角标与蚀刻内框在亮主题下近看才可见
   - 改进方向：考虑增强对比度或改用其他视觉标记

2. **待补充...**

## 附录：关键代码位置

### 旧版组件（c479ca0）

```
visualization/src/components/
├── chat/
│   ├── LiveStatus.tsx (919 行) ⚠️ 核心
│   ├── ActivityStep.tsx (300 行) ⚠️ 核心
│   ├── ActionGlimpse.tsx (295 行) ⚠️ 核心
│   ├── TurnView.tsx ⚠️ 核心
│   ├── ChatView.tsx ⚠️ 核心
│   └── Composer.tsx
└── trace/
    ├── TurnTraceDrawer.tsx (303 行) ⚠️ 核心
    ├── CycleSection.tsx
    ├── PhaseSection.tsx
    ├── ActionCard.tsx
    ├── LlmTaskDrawer.tsx
    ├── MessageStackView.tsx
    ├── ControlOpsView.tsx
    └── WorkingStateView.tsx

visualization/src/derive/
├── activitySemantics.ts ⚠️ 逻辑可提取
├── phaseSummary.ts ⚠️ 逻辑可提取
└── chat.ts ⚠️ projection 函数可提取
```

### 当前 v2 数据层（保留）

```
visualization/src/features/
├── chat/
│   ├── ChatView.tsx (当前 ~900 行，需拆分)
│   └── turnStore.ts ⚠️ 唯一正式 Turn 投影
├── trace/
│   ├── facts.ts ⚠️ v2 事件解析
│   ├── eventWindow.ts ⚠️ 分页窗口
│   └── ProcessPanel.tsx ⚠️ Cycle/Phase/Action 数据
└── settings/
    └── (各页面，需增加中文化)
```

### API clients（保留）

```
visualization/src/api/
├── v2/
│   ├── client.ts
│   ├── turns.ts
│   ├── sessions.ts
│   ├── events.ts
│   ├── home.ts
│   ├── memory.ts
│   └── ...
└── websocket.ts ⚠️ ObservationEvent 来源
```

## 下一步

创建详细的交互流程对比文档，并准备 P1 的 presentation projection 层设计。
