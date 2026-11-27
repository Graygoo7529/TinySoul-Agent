# Context 统一预算与 Session 多级压缩前端执行计划

- 日期：2026-11-27
- 状态：`pending`（待与后端计划协同确认实施）
- 核对基线：`712abf02`
- 上游依赖：
  - [Context 统一预算与 Session 多级压缩后端执行计划](20261127%20Context统一预算与Session多级压缩后端执行计划.md)
  - `reference/design/delta-context.png`（视觉与信息层级参考）
- 依据：
  - [AGENTS.md](../../AGENTS.md)（前端仅修改 `visualization/` 目录，消费 Endpoint 结构化协议与配置目录）

---

## 0. 设计目标与界面体验总览

对齐后端统一的 **Token 预算模型、双水位冰山自压缩与 `SessionMap` v2**，前端在 `visualization/` 内完成四项升级：

1. **Delta 风格 Context 窗口总览卡片与抽屉升级**：在 `Settings -> ContextPage` 顶部及 `Context Drawer -> OverviewPanel` 中，以统一 `tokens` 标尺呈现**总有效窗口分段进度条、全局压缩触发刻度线（`Compact at 80%`）、各槽位/各段的“当前占用 / 段最大预算（占比）”、冰山压缩状态标签**，并支持展开 `Home`（受保护基线 vs 动态加载区）等子项明细。
2. **跨 Owner 预算配置双向联动跳转**：在 Context 页面的段分解列表中为每个外围段提供一键跳转至所属 Owner 设置页（`Session`、`Home`、`Workspace`、`Execution/Jobs`、`Subagent`），同时在各 Owner 设置页清晰展示并编辑该段的 Token 预算模式（`pool_share` 比例 vs `fixed` 固定上限）与 `target_ratio`。
3. **`SessionMap` v2 历史与解释视图同步**：适配 `SemanticNode.turn_refs`、移除 `covers` 边以及可选短 `edge.body` 的新结构，优化会话历史浏览器（`SessionMapPanel` / `SessionRefPanel`）的话题成员展示。
4. **Trace 中 `core.session.organize` 动作卡片适配**：支持展示 `upsert_nodes[].turn_refs` 与精简关系边。

进度检查项：

- [ ] CF1：API v2 `ContextOverview` 与 `Session` 注释类型同步
- [ ] CF2：Context 窗口可视化组件（分段进度条 + 全局阈值刻度 + 段预算分解与子项展开 + Owner 跳转）
- [ ] CF3：`ContextPage`、`SessionPage`、`HomePage` 等配置编辑器支持 Token 预算与固定/比例模式切换及双语词条
- [ ] CF4：History `SessionMap` v2 解释渲染与 Trace `session.organize` 视图同步
- [ ] CF5：前端单测（Vitest）、类型检查（`tsc`）与构建门禁验收

---

## 1. 已核实的前端受影响文件清单

1. **API 类型与契约层**：
   - `visualization/src/api/v2/context.ts`（`ContextOverview`、`SegmentView` 新增 `window`、`tokens`、`budget`、`compaction` 字段）
   - `visualization/src/api/v2/types.ts`
2. **Context 监控抽屉与共享模型（`features/context/`）**：
   - `visualization/src/features/context/OverviewPanel.tsx`（抽屉首屏概览，从纯字符展示升级为 Token 窗口占比 + 段预算进度 + 压缩状态，保留字符辅助提示）
   - `visualization/src/features/context/segments.ts` & `segments.test.ts`（`usageLine`、`segmentStatusLine` 适配 `tokens`、`budget`、`compaction`）
   - `visualization/src/features/context/SegmentPanel.tsx`（段详情页展示解析后的预算策略、全局豁免标记与压缩摘要）
3. **Settings 配置页（`features/settings/`）**：
   - `visualization/src/features/settings/editors/ContextPage.tsx`（升级顶部 `ContextUsageCard` 为分段可视化总览 + 段级跳转；更新全局预留开销、`Trace` 比例/固定预算与 `Plan` 预算控件）
   - `visualization/src/features/settings/editors/SessionPage.tsx`（编辑 `[session.context]` 比例/固定预算与 `target_ratio`，并提供回跳 `ContextPage` 总览链接）
   - `visualization/src/features/settings/editors/HomePage.tsx`（更新 `max_skill_catalog_tokens` 与 `[home.context]` 动态加载区预算控件）
   - `visualization/src/features/settings/editors/WorkspacePage.tsx`（对齐 `workspace.max_context_tokens`）
   - `visualization/src/features/settings/editors/ExecutionPage.tsx`（补充 `jobs.max_context_tokens` / `context_target_ratio`）
   - `visualization/src/i18n/catalog/zh-CN.ts` 与 `visualization/src/i18n/messages/{zh-CN,en-US}/{context,settings,history}.ts`
4. **Session 历史地图与 Trace 展示（`features/history/`、`features/trace/`）**：
   - `visualization/src/features/history/disclosure.ts` & `disclosure.test.ts`（`AnnotationNodeView` 新增 `turnRefs: string[]`；`AnnotationEdgeView` 兼容空 `body`）
   - `visualization/src/features/history/SessionRefPanel.tsx` & `SessionMapPanel.tsx` & `SessionMap.test.tsx`（展示 `thread` 节点的 `turn_refs` 覆盖轮次徽章，空 `edge.body` 时不渲染空白段落）
   - `visualization/src/features/trace/views/resultSession.tsx`（`SessionOrganizeView` 适配 `turn_refs` 展示）

---

## 2. 详细界面与交互设计

### 2.1 Delta 风格 Context 窗口分解视图（参考 `delta-context.png`，贴合 TinySoul 三槽位语义）

抽取可复用的 `<ContextWindowBreakdown />` 组件，同时服务于 `Settings -> ContextPage` 顶部的实时卡片与右侧 `Context Drawer -> OverviewPanel`：

1. **顶部总窗口计量条**：
   - 左侧主数字：`{used_tokens} / {reference_window_tokens}`（如 `42.2k / 262.1k tokens`，若存在最近一次真实模型调用的 `non_message_tokens` 则合并展示 Tool Definitions 占用）；
   - 右侧阈值标注：`Compact at {trigger_tokens} ({trigger_ratio * 100}%)`；
   - 进度条本体：按 `Background`（蓝青色系）、`Trace`（琥珀/主色系）、`Working`（紫/绿色系）、`Tools & Reserved`（中性暗灰斜纹）分段着色填充，并在 `trigger_ratio`（如 `80%`）处绘制清晰的垂直刻度指示线（与 `delta-context.png` 一致，一眼看清距离全局保险线还有多少余量）。
2. **段级明细列表（按 `Background → Trace → Working` 装配顺序排列）**：
   - 每行左侧带槽位色条、段名、形状标签（`MAP` / `HEAP` / `STACK` / `STATE`）及 **`Exempt`**（全局豁免）或 **`Pool {share}%`** 徽章；
   - 中部展示**压缩冰山状态摘要**（`compaction.summary`，如 `L1: 3 turns, L2: 6 turns`、`2 cold branches, 4 folded reads`、`14 dirs collapsed`）；
   - 右侧对齐展示 **`{tokens} / {effective_max_tokens}`**（如 `11.4k / 24.5k`）及占有效窗口百分比；当某段接近自身最大预算（`> 85%`）时进度数值高亮提示；
   - **可展开子项**：点击 `home` 行可展开查看 `Protected Baseline (Defaults + Skill Catalog)`（不参与逐出）与 `Dynamic Loaded Tops`（参与 `target_ratio` LRU 逐出）两行拆分数据；
   - **一键配置跳转**：在 `ContextPage` 中，每行末尾附轻量设置跳转图标按钮（点击调用 `useSettingsUiStore.getState().navigateTo(segment.budget.settings_page, primaryFieldPath)`，直达对应 Owner 配置项并高亮）。

### 2.2 比例预算 / 固定预算双模式配置控件

在 `ContextPage`（管理全局窗口、触发/目标比例、预留开销、`Trace`、`Plan`）、`SessionPage`（管理 `Session`）、`HomePage`（管理 `Home` 动态区）中复用统一的 `<SegmentBudgetControl />` 组合控件：

- 当 `mode == "pool_share"` 时：主滑块编辑 `pool_share`（显示实时折算出的参考窗口等效 token 数预览），折叠高级项编辑 `min_tokens`、`max_tokens`（可选封顶）与 `target_ratio`；
- 当 `mode == "fixed"` 时：主输入框编辑固定的 `max_tokens` 与 `target_ratio`；
- 在 `ContextPage` 汇总展示当前三个 `pool_share` 弹性段的权重占比条（如 `Trace 60% · Session 25% · Home 15%`），权重之和偏离 `100%` 时给出归一化实际生效比例提示，直观透明。

### 2.3 `SessionMap` v2 与历史浏览面板同步

1. `visualization/src/features/history/disclosure.ts`：
   - `AnnotationNodeView` 增加 `turnRefs: string[]`（解析 `item.turn_refs`）；
   - `parseAnnotation` 中对 `AnnotationEdgeView` 允许 `body === ""` 及 `sourceRefs` 为空数组。
2. `SessionRefPanel.tsx` / `SessionMapPanel.tsx`：
   - 渲染 `thread` 节点卡片时，直接展示 `turnRefs` 的可点击轮次芯片（`Turn #1`, `Turn #3`...），无需再依赖旧 `covers` 关系边列表；
   - 渲染 `edge` 关系项时，若 `edge.body === ""` 仅紧凑渲染 `source → [relation] → target` 单行拓扑胶囊，界面大幅清爽化。

---

## 3. 分阶段实施步骤与验证门禁

| 阶段 | 工作内容 | 验证重点 |
| --- | --- | --- |
| **CF1：类型与解析同步** | 更新 `api/v2/context.ts`、`history/disclosure.ts` 及对应解析单测 | 新字段类型严格匹配后端 schema；缺失活动 Turn 或旧快照优雅展示 |
| **CF2：窗口分解组件** | 实现 `<ContextWindowBreakdown />` 并接入 `ContextPage` 与 `OverviewPanel` | 进度条总宽、全局阈值刻度线、`Home` 基线/动态拆分展开、Owner 跳转路由准确 |
| **CF3：各页预算编辑器** | 实现 `<SegmentBudgetControl />`，更新 `ContextPage`、`SessionPage`、`HomePage`、`WorkspacePage`、`ExecutionPage` 与 `i18n/catalog/zh-CN.ts` | 草稿修改、`PATCH /v2/config`、`apply` 校验及预设（Presets）读写正常 |
| **CF4：SessionMap v2 视图** | 更新 `SessionMapPanel.tsx`、`SessionRefPanel.tsx`、`resultSession.tsx` 及测试夹具 | `thread.turn_refs` 跳转正常，空 `edge.body` 无多余空框 |

前端验证命令（`visualization/` 目录）：

```powershell
pnpm test -- --run
pnpm run typecheck
pnpm run build
```

---

## 4. 合理性与可行性分析

1. **信息架构与后端所有权完全一致**：每个 Owner 仍在自己的配置命名空间持有持久配置字段（无跨模块配置污染），而前端 `ContextPage` 通过实时聚合 `ContextOverview` 与 `navigateTo` 跨页路由，既提供了像 `delta-context.png` 一样一目了然的全局仪表盘，又保持了单点真实配置源。
2. **与 Workspace 前端计划平滑衔接**：两份前端计划仅在 `WorkspacePage.tsx` 的 `workspace.max_context_tokens` 一处字段名交汇，其余文件互不重叠，可按顺序无冲突合入。
