# Detail 面板与 LLM 调用呈现优化执行计划

日期：2026-10-06

状态：待逐项确认与实施

范围：`visualization/src/features/trace/`（ProcessPanel.tsx、ModelCallPanel.tsx、ActionDetailPanel.tsx、facts.ts）与 `visualization/src/components/trace/semantic.tsx`。只改呈现层，不改事件读取（eventWindow）、数据关联（buildTurnProcess）与 Inspector 抽屉机制。

## 目标

Detail 面板（Inspector 抽屉中的 Process / Action / Model call 三个视图）是把 Turn 的 Cycle→Phase→Action 过程和每次 LLM 调用的 request/response 呈现给维护者的窗口。当前它把大量机器协议字段直接摆上台面（裸 `phase1`、全长 `call_id`、原文 media 类型），LLM trace 是数千字无折叠的文字墙，且关键诊断信息（耗时、时间戳）解析了却没显示。本计划把它从"开发者日志"打磨成"可读的决策回放"。

---

## 改进点 1：标识符呈现统一与 phase 标记降级（2026-10-07 与维护者定稿）

状态：**已实施**（2026-10-07，tsc + 全部 806 前端测试通过）

### 现状分析

- Phase 卡片标题行在 headline 后并列挂裸 `phase1` 标签（`features/trace/ProcessPanel.tsx:409`），位置在行中部、与内容争抢视觉重心；phase 命名存在三套并存：`features/chat/presentation.ts:118` 的 `PHASE_META`（LiveStatus headline 消费，**不在本改进点范围内、保持不变**）、`ProcessPanel.tsx:398` 的英文兜底标题（"Context maintenance / Action planning / Execution"）、以及裸枚举本身；
- Action 详情的位置行显示 `cycle cycle_2 · phase3` 原文（`ActionDetailPanel.tsx:130-137`，cycle 前缀未剥离；而 Cycle 标题在 `ProcessPanel.tsx:240` 已做 `cycle_(\d+)` 剥离——同一面板两种写法）；
- 全长 `call_id`/`invoke_id`/`task_id`/`searchId` 以等宽字体直出（`ActionDetailPanel.tsx:141-153`、`ModelCallPanel.tsx:315`、`ProcessPanel.tsx:324`），占据视觉重心却无法整体阅读；
- 语义 chip 库 `components/trace/semantic.tsx` 已有 domain 色调、状态徽章、action 图标的统一映射，但没有 cycle/id 呈现与 phase 释义的规则。

**设计决定（维护者确认）**：`phase1/2/3` 是简洁明确的协议标识，**不翻译为中文**；它的问题不是"看不懂"，而是摆放位置与命名分裂。标题行让位给真实内容（选择了哪些域、几个动作），phase 标记降级为行尾弱化 token。

### 修改范围与内容

- `components/trace/semantic.tsx`：新增——
  - `phaseHint(phase: string): string`：phase1→"更新语境并选择行动域"、phase2→"在已选域内生成动作"、phase3→"组装并执行动作批次"，未知值原样返回；**仅用于 tooltip 与组头释义**，是唯一释义来源；
  - `cycleLabel(cycleId: string): string`：`cycle_2`→"Cycle 2"（剥离下划线前缀，未知格式原样）；
  - `shortId(id: string): string`：保留前 8 位；
  - `IdChip({ id }: { id: string })`：等宽短 id + 点击复制全值（复用现有 CopyButton 语义），title 显示全值。
- `ProcessPanel.tsx` PhaseCard：
  - headline 保持内容优先（现有逻辑：已选域数 / 动作数 / 兜底描述）；`:398` 的英文兜底标题改为中文内容短名——"更新语境"/"规划动作"/"执行动作"（它们出现在 headline 位置本身就是内容描述，不是前缀）；
  - 裸 phase 标签（:409）从行中部移到**行尾**（耗时与 context 芯片之后），10px mono `text-fg-faint`，`title={phaseHint(phase)}`——可见但不抢眼，需要释义时悬停；
  - search 行（:324）与 orphan task 行（:353）的 id 换 `IdChip`。
- `ActionDetailPanel.tsx`：position 行（:130-137）改为 `Cycle 2 · phase3`（cycle 用 `cycleLabel` 剥离，phase **保留原样**并加 `title={phaseHint}` 释义）；call/invoke 两行（:141-153）改用 `IdChip`。
- `ModelCallPanel.tsx`：task id（:315）改用 `IdChip`。

### 预期效果

Phase 卡片标题行一眼读到的是内容（"已选择 2 个域"），`phase1` 退居行尾小字、悬停得释义；位置行与 Cycle 标题写法一致（"Cycle 2 · phase3"）；id 全部短码化、悬停见全值、点击即复制。phase 释义全局只有 `phaseHint` 一份来源，LiveStatus 运行中 headline 完全不变。

---

## 改进点 2：Overview 指标带

状态：**已实施**（2026-10-08，tsc + 全部 807 前端测试通过，含新增行为用例）

### 现状分析

`ProcessPanel.tsx:192-206` 的 Overview 只有四个计数格（Cycles/LLM calls/Actions/Searches）加一行 token 合计。没有总耗时、没有每 cycle 耗时——而 `CycleMeta`（:369-381）其实已经计算了 cycle 级耗时，只是藏在折叠头的小字里；LLM task 级别也没有耗时汇总。

### 修改范围与内容

- `ProcessPanel.tsx` OverviewCard：
  - 计数行下方增加一行指标带：`总耗时 Xs · 平均每 cycle Ys · 38k tokens（Z 次调用）`，数据全部从现有 `process.cycles[].phases[].startedAt/finishedAt` 与 `llmTasks[].tokens` 推导，无新增数据源；
  - 失败计数提示：若存在 failed/timeout 的 action 或 LLM task，指标带末尾加红色小字 `2 个失败`（点击滚动到 ProcessTree 第一个失败 phase——复用现有 DOM 锚点即可，不建新机制）。

### 预期效果

打开 Details 第一眼看到"3 个 Cycle · 5 次模型调用 · 总计 24s · 38k tokens · 1 个失败"，规模与健康度一屏可读，不用逐层展开点数。

---

## 改进点 3：Phase 展开态内容增强与 ActionRow 增强（2026-10-08 维护者定稿 v2：取消三级披露）

状态：**已实施**（2026-10-08，tsc + 全部 807 前端测试通过）

### 现状分析

- Phase 卡片折叠/展开两态（`ProcessPanel.tsx`）：折叠时意图预览 + 动作徽章行在卡片内，展开后这两行消失——**展开时卡片反而变矮**，视觉跳动；
- "Control requests" 被包在折叠区里，内容是裸键值对；维护者对 phase1 展开后的控制内容基本满意，只需微调；
- phase2/phase3 展开后只有动作行文字列表，**没有动作规划与执行的内容预览**——而对话区 LiveStatus 的 ActivityGlimpse 已有成熟的 gist 渲染（diff/终端/搜索预览），两个面板能力倒挂；
- ActionRow 只有 图标+动作名+状态徽章+"N model / N search"（语义不自明），无耗时、无目标摘要；
- phase body 里的 `decision · …` LLM 链接行与头部 🧠 context 芯片功能重复。

### 修改范围与内容（`ProcessPanel.tsx` PhaseCard/ActionRow；`facts.ts` 两处纯增量）

1. **单次展开（取消三级）**：点击 Phase 头只切换 折叠 ↔ 展开；意图预览行在折叠与展开**两种状态都常显**；动作徽章行**两种状态都显示**（展开态作为紧凑摘要置于详细动作行之上——展开只增不减，杜绝高度回跳）；徽章行只在有动作的 phase 出现（phase1 只选域、无动作，无徽章行）；
2. **Reasoning 默认预览**：Reasoning 块默认显示前 3 行（超出渐隐截断），底部"展开全文/收起"按钮。
3. **控制请求平铺**：去掉 "Control requests" 折叠包装，直接平铺现有键值行（**内容形态完全保持现状**，不做语义行转换）；
4. **删除 phase body 的 LLM 链接行**（`decision · …`）——头部 context 芯片已承担跳转。
5. **动作 gist 预览（phase3/执行）**：展开态下每个动作行下方内联 result 阶段 gist（复用 `glimpseBody()`：diff 统计/终端输出/搜索命中），由 `ActionTrace`（call.params + result.payload/failure）构造 `ActionGlimpseData`，静态渲染（无 live 动效）。

   **5b. 动作规划预览（phase2/规划，2026-10-08 运行时修正）**：`action.call` 事件由后端 phase2 发出（`kernel/loop/phases/phase2.py`），但 `buildTurnProcess` 合并同一 callId 时 result 事件的 phase3 scope 后写覆盖——动作行落在 phase3，phase2 看不到"选择了什么动作"。phase2 的规划信息须来自该 phase LLM 响应的 action 类 tool_calls：`facts.ts` 增量——`LlmTaskTrace` 增加 `actionCalls: { name: string; arguments: JsonObject }[]`（仿 `modelControlRequests`，捕获 kind === "action"）；PhaseCard 在 phase2 展开时渲染"动作规划"区：每个动作 名称（domain 色调）+ 参数一行摘要 + plan 阶段 gist。
6. **ActionRow 增强**：状态图标 + 动作名（**保持 `memory.search` 点分形式**）+ 状态徽章 + 目标摘要 + 耗时 + 语义化计数（`2 次模型 · 1 次检索`，悬停 title 英文原义）；目标摘要按 family 提取（write/edit→ref 末段、execution→命令截断、search→query），提取函数 `actionSummary()` 放 `components/trace/semantic.tsx`；点击仍跳 Action 详情。
7. **耗时数据（facts.ts 纯增量，已确认）**：`ActionExecutionFact` 增加可选 `at?: number | null`（事件 created_at），耗时 = 同一 invoke 的 started→settled 差；无数据则省略。

### 预期效果

Phase 展开态一次到位：意图、推理、控制请求、动作及其内容预览同屏可读；phase2 看到"计划做什么"，phase3 看到"实际执行结果"（diff/终端/搜索），与对话区 gist 同一视觉语言；展开收起不再高度回跳。

---

## 改进点 4：LLM Task 头部增补模型 / 耗时 / tokens（2026-10-07 与维护者定稿：保留列表布局）

状态：**已实施**（2026-10-07，tsc + trace 测试 76 例通过，含新增行为断言）

### 现状分析

`ModelCallPanel.tsx` 的 LlmTaskView（:310-386）头部是一个 dl（任务/用途/调用方/目标/状态——改进点 1 已中文化并换 IdChip），**没有耗时与时间戳**：事件流中每条 ObservationEvent 都带 `created_at`，专用模型调用（DedicatedCallView :888）已显示 `elapsedSeconds`，唯独最重要的 LLM task/attempt 不显示——诊断"哪个模型慢"这一最常见诉求缺位。token 只在 Response 深处以 "in N / out N" 出现（:759-766），无合计、不进头部。

### 修改范围与内容

`ModelCallPanel.tsx` LlmTaskView：**保留现有 dl 列表布局**，在"任务"行后、"状态"行前新增三行——

- **模型**：`anthropic / claude-sonnet-4`（取首个 attempt 的 providerId/providerModel，mono 字体）；
- **耗时**：`6.2s（14:32:05 → 14:32:11）`——task 级 = 窗口内该 task 首个事件到终态事件的 `created_at` 差；事件不足时该行整体省略，不显示占位；
- **tokens**：`3.2k → 412（合计 3.6k）`——从各 attempt response 的 `usage` 汇总（现有解析逻辑不变，仅上提）；全部 attempt 都无 usage 时省略该行。

新增行样式与现有行一致（dt 灰标签 + dd 内容），耗时与 token 数值用 mono 突出、说明文字用小号灰字。

### 预期效果

每次 LLM 调用的"谁调的、用的哪个模型、多快、多少 token、成败"在头部列表直接读完；慢调用不用展开任何内容就能定位；布局与专用模型调用视图保持一致，无新视觉语言。

---

## 改进点 5：Request 消息栈分段折叠

状态：**已实施**（2026-10-08，tsc + 全部 806 前端测试通过）

> 后续修订（2026-10-08 维护者反馈，并入改进点 6）：顶部英文解释行删除；四段收编进 Context 一级折叠组；左侧文字锚轨改为垂直光轨；`resolved_references` 降级为 Context 内"引用解析"小折叠行。

### 现状分析

RequestView（:479-588）把消息全文铺开：text part 是 12px `whitespace-pre-wrap` 全文（`MessagePart` :675-683），长 system/session 段形成数千字文字墙。左侧已有 slot 锚轨（background/trace/working/task_prompt，:489-558）但只能跳转，不能折叠；单条消息无折叠、无字符数提示。

### 修改范围与内容

`ModelCallPanel.tsx` RequestView/MessageView：

- **按 slot 分组折叠**：消息按 slot 锚轨的四段分组渲染为四个折叠段（复用 `Collapsible`），**全部默认折叠**；每段标题显示 `段名 · N 条消息 · 总字符数`（如 `Background · 4 条 · 12.4k chars`）；段内保持消息顺序与现有消息头（role 徽章/label/tool_name/segmentIds）；
- **单条消息折叠**：段内每条消息默认只显示头部 + 首行预览（截断 80 字符），点击展开全文；json part 保持现有 JsonTree（本身可折叠）不变；
- 保留原 slot 锚轨作为段内跳转（锚轨按钮改为展开对应段并滚动）；`resolved_references`、Tools 折叠区维持现状。

### 预期效果

打开 request 默认看到四段规模摘要（"Background · 4 条 · 12.4k"），输入规模可感知而不被淹没；关心哪段点哪段，段内再逐条展开。文字墙消失，面板长度从数千行回到一屏。

---

## 改进点 6：Request/Response 结构与可读性（2026-10-08 按维护者反馈扩展，含改进点 5 锚轨修订）

状态：**已实施**（2026-10-08，tsc + 全部 806 前端测试通过；同日二次反馈优化：Attempt 折叠头移除、工具定义单开切换、JsonTree 新增 defaultDepth 并默认两层、Response 头部小字移除、思考过程改 Fold、工具调用参数美化、去除一次性流光并强化折叠态可点边框；三次反馈落地：Tools 胶囊选中五态、Context 光轨紧凑 sticky、segmentIds 中文化、slot 段级复制按钮、lifecycle 并入头部"模型"行——后者同时消化改进点 7）

### 现状分析

- 改进点 5 落地后，Request 顶部仍有一行英文解释（"TinySoul provider-neutral request — not a raw provider HTTP exchange"）占位无信息量；
- 四个 slot 段与 Tools、Resolved references、Response 平铺，缺少一层 Context 收编；左侧锚轨是文字+条数的宽轨，偏重；
- Tools 区内 forced 工具用一行 `forced: xxx` 文字表达；工具只显示名字胶囊，看不到模型可见的定义（description/parameters 其实就在 request payload 里）；
- `resolved_references` 是 owner 校验过的 `ref → 资源定位` 映射（后端 `kernel/context/segments/collection.py` 的 ReferenceBindingSegment 收集），服务回放审计（"这次调用时模型看到的 ref 指向什么"），有保留价值但不值一级分组；
- Response 区：answer 是纯文本块（不渲染 Markdown）；tool calls 参数是 JsonTree 文字墙，kind 仅以 "· kind" 小字区分。

### 修改范围与内容（`ModelCallPanel.tsx`：RequestView/ResponseView/AttemptView）

**Request 区**
1. 删除顶部英文解释行（语义留在代码注释）；
2. 新增 **Context 一级折叠组**（默认折叠，头部 `Context · N 条消息 · Xk 字符`），四个 slot 段收编其中；顺序为 Context → Tools → Response；
3. `resolved_references` 降级为 Context 内末尾小折叠行"引用解析（N 条）"（title 解释：owner 校验的引用→定位映射，用于回放审计）；
4. 左侧文字锚轨改为**垂直光轨**：Context 区块左缘一列细刻线（每段一条），展开态刻线变长、变亮并带 accent 光晕，hover 显示段名与规模 tooltip——无文字纯光效导航；
5. Tools 区：删除 `forced:` 文字行，forced 工具胶囊改 accent 描边 + 淡光泽（title="本次强制"）；**点击胶囊内联展开该工具的模型可见定义**（description 正文 + parameters 折叠 JsonTree），再点收起。

**Response 区**
6. 分三个小分组（与 Request slot 段同一视觉语言）：**思考过程**（reasoning summary，保持斜体风格）、**工具调用 (N)**、**模型回答**；默认折叠策略（2026-10-08 运行时反馈定稿）：思考过程与工具调用默认折叠（带规模摘要），模型回答默认展开；
7. answer 改用共享 `Markdown` 组件（`md-calm`）渲染，origin 传 `{ ref: "" }`；
8. 工具调用改**通用可读卡片**：头部 = 工具名 + kind chip（control 中性灰 / action 用 `domainHueClasses` 色调）；参数按通用规则渲染——原始值内联键值行、嵌套值才用折叠 JsonTree，**不做任何 per-tool 特殊渲染**；
9. usage 行追加合计；response 头部 meta 补模型名。

**光泽与交互**
10. 折叠头状态色：关闭=中性，打开=`bg-accent-soft/20` + 左侧 2px accent 细条；打开瞬间一次性流光扫过（`text-shine` 同族，reduced-motion 降级为静态）。

### 预期效果

一次 LLM 调用的默认视图是 "Context（规模摘要）→ Tools → Response（三分组）" 三层结构，一屏读完这次调用的构成；想看哪层点哪层，工具定义、引用解析、完整消息、原始 JSON 各就其位；forced 工具与展开状态有克制的光泽引导。

---

## 改进点 7：调用链合并（lifecycle + attempts）

状态：**已实施**（2026-10-08，随改进点 6 后续优化以更简形态落地，见下）

### 现状分析

"Model lifecycle"（:354-380）与 "Attempts"（:381-383）是两个并列区块：前者列 `llm.model.started/completed/failed` 的模型级事实，后者是按 attempt 分组的 provider 级记录。术语面向开发者，两个列表语义重叠（同一模型链拆成两处）。

### 实际落地（2026-10-08，随改进点 6 二次优化）

Attempt 折叠头在改进点 6 优化中已移除（单 attempt 直渲、多 attempt 细分隔行），独立的 "Model lifecycle" 区块随之失去存在意义，最终形态比原设计更简：

- lifecycle 区块删除；模型级状态并入头部 dl "模型"行（`provider / model · completed`，失败同行红字原因）；
- 多 attempt 时"模型"行附重试摘要（"第 1 次 failed → 第 2 次 completed"），尝试详情由细分隔行承担；
- 同步落地：Tools 胶囊选中态五态、Context 光轨紧凑 sticky、消息头 segmentIds 中文化（`segmentLabel`）、slot 段级复制按钮（hover 显现）。

### 预期效果

无 lifecycle/attempt 双列表、无开发者术语；模型级成败与重试在头部一行读完。

---

## 改进点 8：Activity 时间线组头与时序

### 现状分析

`ProcessPanel.tsx` ActivityTimeline（:125-174）：按 phase 分组染色（PHASE_META tint，:159）但**无组头文字、无图例**——用户无法知道颜色含义；时间戳为绝对时刻（:164）；与上方 ProcessTree 的语义标题命名不一致。

### 修改范围与内容

`ProcessPanel.tsx` ActivityTimeline：

- 每组增加组头：`phaseN` 小徽章 + `phaseHint(phase)` 中文释义 + 组内条数 + 组起止时间（如"phase1 · 更新语境 · 6 条 · 14:32:01–05"），颜色保留；
- 时间戳保留绝对时刻，title 追加相对 turn 开始的偏移（`+12.4s`），数据从 `item.timestamp` 与组首事件推导；
- 时序方向维持现状（最新在前），在 Collapsible 的 meta 处加一行说明文字"最新在前"，避免与 ProcessTree 正序的阅读预期冲突（不强行翻转已有交互习惯）。

### 预期效果

时间线分组可读懂（"语境与域 · 6 条 · 14:32:01–14:32:05"）；两种时序各有明示，不再困惑。

---

## 改进点 9：Action 详情与 gist 能力对齐

### 现状分析

编辑类 action 的最佳可视化（diff）只在对话区的 live gist 里（`features/chat/ActivityGlimpse.tsx` 的 DiffGlimpse，基于 params 的 old_text/new_text）；而 ActionDetailPanel 的 write family 结果视图反而看不到 diff——详情面板能力弱于一闪而过的 gist，能力倒挂。位置行与 id 呈现问题由改进点 1 覆盖。

### 修改范围与内容

- `features/trace/resultViews.tsx` 的 write family 视图：当 params 含 `old_text`/`new_text`（或 edits 数组）时，复用 `features/chat/ActivityGlimpse.tsx` 的 DiffGlimpse 渲染差异（把 DiffGlimpse 从 chat 移到可共享的位置，如 `components/trace/`，两处引用）；无 diff 数据时保持现状文案；
- `ActionDetailPanel.tsx`：补一行耗时（result 级 timing，有则显示）；`GenericView`（未知 action 的 JsonTree 兜底）头部增加一行说明"未识别的动作类型，以下为原始数据"。

### 预期效果

详情面板成为信息的最高点而非最低点：gist 里看到的 diff，详情里一定能看到（且更完整）；未知动作有明确预期管理。

---

## 实施顺序与验收

建议顺序：1（语义层，其他改进点依赖）→ 4+5+6+7（LLM trace 一组）→ 3（Phase/Action）→ 2+8（Overview/时间线）→ 9。

验收标准（逐改进点）：

1. Phase 卡片标题行内容优先，phase 标记退居行尾弱化小字、悬停显示中文释义；`cycle_N` 写法全局统一剥离；id 全部短码化可复制；phase 释义全局只有 `phaseHint` 一份来源（LiveStatus headline 不变）；
2. Overview 显示总耗时/平均耗时/token 合计；有失败时出现红色计数；
3. Phase 三态循环展开；ActionRow 显示耗时/摘要/语义计数；select_action_domains 渲染为语义行；
4. LLM task 头部显示模型、耗时、起止时间、token 合计；
5. request 默认只显示四个 slot 段的规模摘要，逐段/逐条可展开；
6. response 的 answer 渲染 Markdown；tool call 按 kind 着色；usage 有合计；
7. lifecycle 与 attempts 合并为一个调用链区块；
8. 时间线有组头与"最新在前"说明；
9. write family 详情可见 diff；GenericView 有说明行。

边界：不改动 `facts.ts` 的解析逻辑与 `eventWindow.ts` 的读取机制；不新增后端端点；不影响现有 `ProcessPanel.test` 等测试的行为断言（需要同步更新的断言随改动一并修改）。
