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

### 现状分析

`ProcessPanel.tsx:192-206` 的 Overview 只有四个计数格（Cycles/LLM calls/Actions/Searches）加一行 token 合计。没有总耗时、没有每 cycle 耗时——而 `CycleMeta`（:369-381）其实已经计算了 cycle 级耗时，只是藏在折叠头的小字里；LLM task 级别也没有耗时汇总。

### 修改范围与内容

- `ProcessPanel.tsx` OverviewCard：
  - 计数行下方增加一行指标带：`总耗时 Xs · 平均每 cycle Ys · 38k tokens（Z 次调用）`，数据全部从现有 `process.cycles[].phases[].startedAt/finishedAt` 与 `llmTasks[].tokens` 推导，无新增数据源；
  - 失败计数提示：若存在 failed/timeout 的 action 或 LLM task，指标带末尾加红色小字 `2 个失败`（点击滚动到 ProcessTree 第一个失败 phase——复用现有 DOM 锚点即可，不建新机制）。

### 预期效果

打开 Details 第一眼看到"3 个 Cycle · 5 次模型调用 · 总计 24s · 38k tokens · 1 个失败"，规模与健康度一屏可读，不用逐层展开点数。

---

## 改进点 3：Phase 卡片三级渐进披露与 ActionRow 增强

### 现状分析

- Phase 卡片只有折叠/展开两态（`ProcessPanel.tsx:386,402,424`）：折叠时一行 intent 预览 + 动作状态徽章行；展开后 Reasoning、Control requests、Action 列表全部铺开，信息密度陡增；
- "Control requests"（:429-436）是裸键值对：`call.name` 等宽字体 + `key: value`（非字符串值 `JSON.stringify` 内联）——协议字段直接裸露；
- ActionRow（:443-485）只有 图标+动作名+状态徽章+"N model / N search" 计数——计数语义不自明（"2 model" 不读代码不知道是 2 次模型调用），无耗时、无目标摘要。

### 修改范围与内容

`ProcessPanel.tsx` PhaseCard 与 ActionRow：

- **三级展开**：点击 Phase 头在 折叠 → 半展开 → 全展开 间循环（chevron 角度 0°/90°/90°+强调色区分后两态）：
  - 半展开：Reasoning 块 + Action 紧凑行（见下）——这是默认的"看懂这个 phase"层级；
  - 全展开：追加 Control requests 区块与 LLM task 链接列表（现有的 `phase.llmTasks` 行移入此层）。
- **ActionRow 增强**：每行显示 `状态图标 + 语义动作名 + 状态徽章 + 耗时 + 参数一行摘要 + 语义化计数`：
  - 耗时：从 `trace.result` 的耗时字段（facts 已解析 result 级 timing；若无则省略，不显示 0）；
  - 参数摘要：按 family 提取——write/edit 类显示 target link 末段（`workspace:docs/a.md` → `docs/a.md`），execution 类显示 command 截断 40 字符，search 类显示 query，其余省略；提取函数放 `semantic.tsx`（`actionSummary(action, params)`），与 `actionIcon` 并列；
  - 计数改写为 `2 次模型调用 · 1 次检索`（悬停 title 给出英文原义），点击行仍跳 ActionDetail（行为不变）。
- **Control requests 可读化**：`select_action_domains` 渲染为"选择域：workspace、memory（理由：…）"一行语义文本（intent 字段已有）；其余 control 保持键值对但值较长时改用折叠 JsonTree 小卡。

### 预期效果

每个 Phase 一眼读懂"做了什么、为什么、用了哪些域"；想看协议细节再点一次深入。动作行的"2 次模型调用 · 1 次检索 · 0.8s · docs/a.md"让执行轨迹可扫读。

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

## 改进点 6：Response 渲染增强

### 现状分析

ResponseView（:703-776）：answer 是纯文本块（:729 `whitespace-pre-wrap`，不渲染 Markdown）；reasoning summary 斜体已有；tool calls 的 kind 仅以 "· kind" 小字出现（:748-750），控制类与动作类无视觉区分；usage 只有 "in N / out N" 无合计；模型名不在 response 区。

### 修改范围与内容

`ModelCallPanel.tsx` ResponseView：

- answer 改用共享 `Markdown` 组件（`md-calm` 变体）渲染，origin 传 `{ ref: "" }`（与问答卡片相同做法；注意 `MarkdownOrigin` 的字段名是 `ref`，不是 `link`）；
- tool calls 按 `kind` 着色：control 类用中性灰边框、action 类用对应 domain 色左边条（复用 `domainHueClasses`）；kind 文本保留；
- usage 行追加合计 `in 3.2k · out 412 · 合计 3.6k`；
- response 区块头部（Collapsible title 旁 meta）补模型名（attempt.providerModel，已在父级解析，props 传入）。

### 预期效果

模型回答以排版后的 Markdown 呈现（标题、列表、代码块可读）；动作调用一眼分出"控制意图"与"业务动作"；token 消耗有总数概念。

---

## 改进点 7：调用链合并（lifecycle + attempts）

### 现状分析

"Model lifecycle"（:354-380）与 "Attempts"（:381-383）是两个并列区块：前者列 `llm.model.started/completed/failed` 的模型级事实，后者是按 attempt 分组的 provider 级记录。术语面向开发者，两个列表语义重叠（同一模型链拆成两处）。

### 修改范围与内容

`ModelCallPanel.tsx` LlmTaskView：

- 合并为单一"调用链"区块：按时间顺序渲染每次 attempt 一行——`provider / providerModel · 状态徽章 · 耗时`；模型级 lifecycle 事实（无 attempt 号的 started/completed/failed）作为该行的附属徽标（如"模型级失败：provider_timeout"），不再单独成区；
- Attempt 详情（request/response）仍在行内展开（现有 Collapsible 结构保留，只改标题行呈现）。

### 预期效果

重试链路一眼可见（"第 1 次失败 timeout → 第 2 次成功 6.2s"）；减少一个概念（不再有 lifecycle/attempt 双列表）。

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
