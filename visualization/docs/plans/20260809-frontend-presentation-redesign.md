# 前端呈现架构与视觉系统重构执行计划

2026-08-09 与项目维护者讨论确认。范围限定 `visualization/` 工作区。

## 已确认的决策

1. **视觉方向**：方向 A「Luminous · 光影演进」——在现有中性底上演进，域色系统 + 玻璃拟态抽屉 + 卡片光泽 + aurora 渐变，与 LiveStatus 现有动效语言连贯。
2. **命名重构**：全面改名对齐——按命名地图重命名文件并同步 `docs/design/` 文档，业务术语对齐 AGENT.md。
3. **术语统一**：文档与 UI 统一 Phase1/2/3，弃用 Stage 口语；`ActionResult.stage`（normalize/execute/…）在 UI 标为"失败阶段"。
4. **实施顺序**：Phase A 数据架构先行 → Phase B 命名重构 → Phase C 视觉系统。

## 现状诊断（实施依据）

- `action.call`（stage2）带完整 params，`action.result`（stage3）带完整 payload + failure 五元组；endpoint 不截断。**数据不是瓶颈，呈现架构是。**
- `action.call` 永远带 phase2 scope，phase3 不重发 → `LiveStatus.findRunningAction`、`computeCurrentActivity` 的 "Verb action" 分支、`phaseHeadline` 的 "Executing X (2/3)" 均为死路径。
- 差异化渲染缺失：`actionRenderers.tsx` 仅 `core.answer` 特判，其余靠 payload 形状启发式；`VERBS`/`actionTargetOf`/`resultSummaryOf` 三处分散。
- 语义丢失：`failure.disposition/constraint` 不渲染、`frame_data` 无消费方、`invoke_id/batch_id` 被 derive 丢弃、`workspace.patch` 的 old/new 文本无 diff 视图。

---

## Phase A：Activity 呈现架构（done，2026-08-09）

> 完成记录：A1 registry（49 个 action descriptor，15 个 family，`src/derive/actions/`）、
> A2 phase3 预镜像 + activity 状态机（planned→running→succeeded/failed/timeout）、
> A3 `src/components/trace/renderers/` 家族渲染器 + ActionCard 重构（failure 五元组、
> frame_data 诊断区）、A4 ActivityStep 两行条目 + LiveStatus 运行态复活。
> 修正了旧 VERBS 表的死键（真实名为 `workspace.trash.list`）与 `workspace.read`
> 结果协议（`actual:{start,end}`）。验收：`pnpm test` 62 全绿、`pnpm build` 通过。

### A1 Action Presentation Registry（derive 层，纯函数）

新增 `src/derive/actions/`：

- `registry.ts` — `ActionDescriptor` 接口、`descriptorFor(action)` 查找、generic 回退。
- 域文件 `core.ts` / `workspace.ts` / `execution.ts` / `web.ts` / `home.ts` — 每域一个 descriptor 表。

```ts
export type ActionFamily =
  | "answer" | "reason" | "generate" | "patch" | "command" | "process"
  | "search" | "fetch" | "memory-read" | "memory-write" | "read"
  | "inspect" | "scan" | "delete" | "generic";

export interface CallSummary {
  headline: string;           // "编辑 draft.md" / "检索 “Vite 代理”"
  target?: ActionTarget;      // 复用 model.ts 现有类型
  chips?: string[];           // 短事实：["bash"]、["120-180 行"]
}

export interface ResultSummary {
  headline?: string;          // "exit 0 · 4.2s" / "5 条结果" / "rev 14"
  tone: "success" | "danger" | "warning" | "muted";
  chips?: string[];
}

export interface ActionDescriptor {
  action: string;
  verb: string;               // 现在时，运行态标题用
  family: ActionFamily;
  summarizeCall(params): CallSummary;
  summarizeResult?(result): ResultSummary;
}
```

- 收编 `activitySemantics.ts` 的 `VERBS` / `actionTargetOf` / `resultSummaryOf`；`activitySemantics.ts` 保留 skills 辅助与 `firstLine/plainExcerpt/truncate`。
- derive 层保持纯 JSON 安全，不引入 React；family → 视图的映射在组件层。

### A2 derive/chat.ts：phase3 镜像与 action 状态机

- `loop.phase.started(phase3)`（或 `action.batch.started`）到达时，把当前 cycle phase2 的 planned 记录**预镜像**进 phase3 `PhaseStep.actions`（无 result = pending）；`action.result` 按 `call_id` 认领更新（同时回写 phase2 记录的 result）。result 无匹配镜像（normalize 失败单侧记录）时保持现有追加行为。
- `ActionRecord` 增补：`invokeId?` / `batchId?`（现有字段全部保留， additive）。
- Activity feed：phase2 完成时为每个 planned action 加一条 `kind:"action"` 条目（status planned："已规划 · 编辑 draft.md"）；phase3 开始后将首个无 result 条目翻转为 running；result 到达翻转为 done/failed 并写入 result headline。条目状态经 `callId` 关联、derive 重算时幂等。
- `ActivityItem` 增补：`action?`、`status?: "planned"|"running"|"succeeded"|"failed"|"timeout"`、`resultHeadline?`。
- 效果：`findRunningAction`、action 计时器、"Verb action" 标题、`phaseHeadline` 执行进度全部复活。

### A3 组件渲染器（trace 层）

新增 `src/components/trace/renderers/`，按 family 渲染：

- `DiffBlock.tsx` — old/new 行级 diff（新增 `src/utils/diff.ts`，小型 LCS 实现）；覆盖 `workspace.patch`、`execution.patch_script`、`home.*.patch`（old/new 均在 params）。
- `TerminalBlock.tsx` — 命令 + stdout/stderr/exit_code/elapsed（从 actionRenderers 提取并令牌化）。
- `ResultListBlock.tsx` — 检索结果列表（标题/url/snippet 或 link/summary/score）。
- `FetchBlock.tsx` — url → 标题/excerpt/内容统计。
- `MemoryBlock.tsx` — recall 的 Markdown 预览、memorize 的 ops 清单、inspect 的条目列表。
- `ReadBlock.tsx` — link + 行范围 + 文本预览（截断标注）。
- `GenerateBlock.tsx` — create/rewrite 的 instruction 预览 + 结果元数据格。
- `AnswerBlock.tsx` — 现有 answer Markdown 渲染迁移。
- `GenericBlock.tsx` — JsonTree 兜底（现有行为）。

`ActionCard` 重构：header = 域色图标 + verb + target（registry），Input = family renderer + Raw parameters 折叠，Output = failure 框（**补全 disposition/constraint**）+ family renderer + Raw payload + `frame_data` 诊断折叠区。`actionRenderers.tsx` 由 renderers/ 取代后删除，引用点全部更新。

### A4 chat 组件接入

- `ActivityStep`：action 条目两行呈现——上行 verb+target（域色图标、planned/running 状态图标），下行 result headline（成功绿/失败红）；running 显示 spinner + 经过时间。
- `LiveStatus`：步骤栈呈现 planned→running→done 状态流转；右侧 action 计时器复活；标题用 registry verb。
- `stageSummary.ts`：phase2 折叠行 "Planned N actions: …" 用 registry verb/target；phase3 "Executing X (i/n)" 真实可用。

### 验收标准

- `pnpm test`（含新增 registry/chat 测试）与 `pnpm build` 通过。
- 运行中 turn 的 LiveStatus 显示真实 action 名 + 计时；步骤栈可见 planned/running/done 流转。
- ActionCard 对 patch/search/command/fetch/recall/read/create 七类呈现家族化视图，未知 action 回退 JsonTree 不回归。

---

## Phase A+：浮动栏行动披露增强（done，2026-08-09）

> 维护者验收 Phase A 后追加：LiveStatus（中文定名"活跃状态"，保留原名）步骤栈
> 新增 `ActionGlimpse` 内联详情——运行中的 action 披露 stage2 输入（命令行、
> patch 迷你 diff、生成 instruction、memorize ops），最近完成的 action 披露
> stage3 结果要点（输出尾部、检索前三条、抓取标题摘要、diff 统计 +N/−M、
> 失败 feedback）。`TerminalOutput` 增加 `tailLines` 紧凑模式；`ActivityStep`
> 增加 `glimpse` 插槽。

## Phase B：命名重构（done，2026-08-09）

> 已按命名地图完成：`NavRail`（原 Sidebar）、`TopBar`（AppShell 内联 header
> 抽出）、`TurnTraceDrawer`（原 TurnDetailDrawer）、`PhaseSection`（原
> PhaseCard）、`LlmTaskDrawer`（原 LlmCallDrawer）、`BackgroundDrawer`（原
> BackgroundPanel）、`MaintenanceDialog`（原 MaintenancePanel）、`MonitorView`
> （原 EventsView）、`derive/phaseSummary.ts`（原 stageSummary.ts）；store
> 字段 `traceTurnId`/`openTurnTrace`/`closeTurnTrace`；UI 与文档统一 Phase
> 术语，`ActionResult.stage` 标注为 "stage: \<value\>"。LiveStatus 保留原名
> （中文"活跃状态"）。命名地图与术语约定见 `docs/design/index.md`；
> `chat.md`、`connection.md`、`visual-system.md` 已同步。AppShell.tsx 与
> TurnTraceDrawer.tsx 顺带从 CRLF 规范化为 LF（.gitattributes 要求）。

## Phase C：视觉系统「Luminous」（done，2026-08-09）

> 维护者确认方向后直接全面实施（免预览页）。已落地：
> - 令牌：aurora 渐变 `--accent-grad`、域色 `--domain-*(-soft)`（core=indigo、
>   workspace=blue、execution=orange、web=teal、home=purple、memory=pink、
>   maintenance=slate）、elevation 三档（card/pop/brand 均含顶部内高光）、
>   z-index 刻度、`--focus-ring`、glass-panel/glass-elev，全部入 `@theme`。
> - 域色应用：DomainChip（Badge purple/teal/orange/pink 令牌化）、ActionCard
>   家族图标盒、MessageStackView 分区点（原硬编码色板清除）。
> - 质感：e2 抽屉（TurnTrace/LlmTask/Background）玻璃拟态；暗色主题运行卡
>   辉光；用户气泡/头像/logo/发送按钮 aurora + shadow-brand；CycleSection/
>   Composer/DisconnectedScreen 统一 shadow-card。
> - 字体：本地打包 Inter Variable + JetBrains Mono Variable；计时/统计/token
>   启用 tabular-nums。focus ring 统一（Composer 与 4 处文本输入）。
> - text-shine/live-border 渐变升级为 accent→violet→info。
> 验收：`pnpm test` 62 全绿、`pnpm build` 通过。详见 `docs/design/visual-system.md`。

## 后端需求单（已提交，不阻塞后续阶段）

1. `docs/demand/20260809-action-result-content-preview.md`：编辑/生成类 action result 增加内容预览/diff（前端短期用 params diff + `/v1/workspace/resource` 补拉）。
2. `docs/demand/20260809-action-execution-started-event.md`：`action.execution.started` 事件（并发批次精确标识运行项；phase3 镜像启发式已够用）。
3. mounted skills 结构化事件（`docs/demand/20260808-mounted-skills-event.md`，维持 pending）。

---

## 细节微调（done，2026-08-09 第二轮，维护者反馈驱动）

1. **用户气泡沉稳化**：`--accent-grad` 改为深靛→深紫两段渐变（白字对比度达标，双主题同值）；`--shadow-brand` 同步靛紫色晕。炫酷感保留在运动渐变（text-shine/live-border 的 accent→violet→info）。
2. **LiveStatus 节奏**：新增 `hooks/useThrottledValue.ts`（600ms 尾随节流），activity 与 currentActivity 最小驻留显示，停止请求绕过节流；step-in 动效柔化（位移 6→4px、时长 0.32s）。
3. **PhaseSection**：折叠行 reasoning 预览用 `plainExcerpt` 剥除 markdown 记号；Phase2 折叠文案改为纯 "Planned N actions"；intent/reasoning 块改引述式（accent 左边线 + 浅底，替代 accent-soft 大色块）；新增 `.md-calm` 将思考文本加粗降为 500（PhaseSection/LlmTaskDrawer/LiveStatus/ActivityStep 统一）；core.answer 文案 "撰写回答" → "进行回答"。
4. **LlmTaskDrawer**：头部重构为两行（标题行 + 模型/用量元信息行，窄窗口不重叠）；新增 `sub-drawer-in` 弹出动效与点击面板外收回（`--z-subdrawer-overlay: 65`）；抽屉内 JSON 默认展开；JsonTree 重构——嵌套 hairline 导轨线、行悬停、`defaultExpanded` 语义改为全展开（Raw/诊断视图显式 false 不变）。
5. **走查**：终端块加细描边；确认 NavRail/StatusBar/Card 等无遗留漂移。

验收：`pnpm test` 62 全绿、`pnpm build` 通过。
