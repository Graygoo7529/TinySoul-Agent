# 验收映射（权威计划 §24.1 → 证据）

> 建立：2026-09-30（F7-A）。本文把根仓库 `docs/analysis/20260928-visualization-frontend-implementation-plan.md` §24.1 的 30 项验收逐项映射到当前证据。**不修改权威计划的复选框**（实施状态由项目维护者更新）；本文是前端侧的证据索引与缺口声明。
>
> 状态口径：
> - **已覆盖**：有 vitest 行为/单元测试或真实后端 e2e 直接验证该语义；
> - **代码证据**：实现已落地但仅有代码/文档证据，无直接测试；
> - **缺口**：明确未实现或验证缺失。
>
> 测试基线：vitest 84 文件 / 773 例；e2e（真实后端 + 脚本模型）chat-flow + codeblocks 两场景。文件路径相对 `visualization/`。

## 连接与壳

**1. 空项目连接、重连、ready=false、generation 切换与观察缺口，业务历史不被事件丢失破坏 — 已覆盖**

- 实现：`src/app/connection.ts`（握手/快照/WS 全生命周期、epoch guard、有界退避、gap 后 owner 重读 resync、generation/instance 处理、ready=false 轮询）。
- 测试：`src/app/connection.test.ts`（21 例：epoch 防旧连接覆盖、gap resync、重连退避、generation 变化、事件只触发失效）；`src/store/connectionStore.ts` 状态语义随测。
- e2e：`test/e2e/chat-flow.pw.ts` 含 `page.reload()` 后 localStorage 自动重连并从 Session 恢复历史。

**2. Browser/Tauri 手动 IP:Port+token、显式协议、HTTP/WS/blob 地址一致、本机发现、loopback 不覆盖手动入口 — 已覆盖（Tauri webview 实测除外）**

- 实现：`src/api/v2/connection.ts`（地址解析：IP:Port 默认 http、ws/wss 派生、不被后端 loopback 覆盖）；`src/app/discovery.ts`（Browser localStorage 手动目标 + v1 迁移；Tauri lease 只提供地址+token+身份）。
- 测试：`src/api/v2/connection.test.ts`、`src/app/discovery.test.ts`。
- 边界：Tauri `pnpm tauri build` 构建通过（F0/W2 记录），webview 内交互未实测（仅有代码与构建证据）。

**3. 无活动 Turn、无 Job、知识目录为空、MCP 未连接/未发现分别呈现正常状态 — 已覆盖**

- 测试：`src/features/runtime/executionTab.test.tsx`（无活动轮空态保队列）、`acpTab.test.tsx`（空态诚实零 POST）、`mcpTab.test.tsx`（四事实分列不合并红绿灯）、`src/features/memory/memoryPage.test.tsx`（空知识库入口）、`src/features/history/historyBrowser.test.tsx`（空日目录空态）。

## 对话与历史

**4. 新 Turn → 追加 → ask → choice/Other → 补充 → 完成 → 刷新，身份/顺序/全文正确 — 已覆盖**

- e2e：`test/e2e/chat-flow.pw.ts`（真实后端全链路：发送→问题卡→Option B+comment→最终回答点名所选→刷新后只读历史四轮条齐全且各 1 条）。
- 测试：`src/features/chat/turnController.test.ts`、`ChatView.test.tsx`、`interactions.test.ts`（echo→pending→formal 身份收敛 command_id/input_id/question_id）。

**5. preparing 补充、拒绝保稿、排队满/Inbox 容量/失效等待分别处理 — 已覆盖**

- 实现：`src/api/v2/errors.ts`（`isCapacityRejection`：agent.queue_full / turn.inbox_full）、`turnController.ts`（意图提交瞬间固定、容量拒绝保稿不改目标）。
- 测试：`turnController.test.ts`、`ChatView.test.tsx`（意图菜单 pin、409 追加失败 turnClosed → 显式 "Send as next turn" 不自动重发、容量/网络失败无该按钮）。

**6. 翻页期间新增输入、pending→installed/visible、失效序列/分片正确结束、问题和预算不等待正文翻完 — 已覆盖**

- 实现：`src/api/v2/pagination.ts`（fragment 解码/装配/交付一次）、`src/features/history/usePagedSequence.ts`（continuation 失效 catch-up 重读后一次性替换）、`turnController.ts`（readEpoch 防晚到响应）。
- 测试：`pagination.test.ts`、`ChatView.test.tsx`（快照 waiting + interactions 挂起 → 问题卡/预算卡已可提交；正式到达收敛恰 1 卡）、`src/features/context/contextDrawer.test.tsx`（409 转"last captured view"不重试）。

**7. 多页 Session 接替不清空已读正文、原阅读位置与完整问题/回复保留 — 已覆盖**

- 实现：`usePagedSequence.ts`（首页只读一页，"Show more" 续读；曾修复首读排空缺陷）、`turnController.ts`（TAKEOVER_RETRY_DELAYS_MS 有界接替）、`ChatView.tsx`（freshness baseline：viewKey=`turnId:source`，takeover 重定 baseline 不重播）。
- 测试：`historyBrowser.test.tsx`、`turnController.test.ts`、`ChatView.test.tsx`。

**8. 问题与预算同时等待各自提交、排队/取消/finalizing、Reflection 不误接普通追加 — 已覆盖**

- 实现：`ChatView.tsx`（等待区四件恒定挂载列尾：问题卡/排队行/预算卡/结果行）、`interactions.ts`（`resolveComposerIntent` 仅派生意图为 append 时生效，不复活已关闭目标）、`turnController.ts`（`cancelQueuedTurn` 以行自身 Turn id 取消，与 `cancelActiveTurn` 区分）。
- 测试：`ChatView.test.tsx`（问题+预算并存恰各 1 卡、行内取消 POST 到排队轮自身、running 时按钮不出现）；e2e chat-flow（问题卡回复）。

## 设置与方案

**9. 方案应用后实际通道改变、运行中不可假切换、缺引用清晰定位 — 前端语义已覆盖；真实通道切换为代码证据**

- 已覆盖：提交语义（仅发 `{preset_id}` 不混 operations）、忙碌按 `activity.can_reload` 真实原因禁用、成功后重读快照驱动徽标（绝不显示假已切换）——`presets/presetsController.ts` + `presetsController.test.ts`（12 例）、`PlansPage.test.tsx`（12 例）、`PresetEntry.test.tsx`（8 例）。依赖问题卡按结构化 key 经 `pageForPath` 定位到归属设置页。
- 代码证据："应用后 LLM/JEV 与 query 通道实际改变"是后端 generation 行为，前端按 (generation_id, scenario) 缓存 actions 投影自然重取（`behavior/useActionsView.ts`）；无 e2e 验证真实模型链切换。

**10. 草稿确认流：取消/失败保留、确认放弃并成功切换才清除、捕获不清草稿不冒充全量备份 — 已覆盖**

- 实现：`presets/PresetDraftConfirm.tsx` + `usePresetApplyFlow`（方案页与 Composer 共用同一确认流，三分支）、`presetsModel.ts`（受管范围五组注册表，明示"不捕获什么"）。
- 测试：`presetsController.test.ts`（捕获族零 apply 请求且草稿保留、不连发两次请求）、`PlansPage.test.tsx`、`PresetEntry.test.tsx`。

**11. 多页草稿、对象排序、含点 map、整批凭据+配置、失败/重置、pending 说明 — 已覆盖**

- 测试：`draft/model.test.ts`（24）、`draft/catalog.test.ts`、`draft/store.test.ts`（11）、`draft/fields.test.ts`（15）、`models/collectionDrafts.test.ts`（17）、`models/pages.test.tsx`（OrderableRow 排序、rename 级联）、`editors/ToolsPages.test.tsx`（KeyValueMapEditor 含点键、MCP/ACP 集合编辑）、`editors/DataPages.test.tsx`、`SettingsPage.test.tsx`（概览 stale adopt-keep / pending_reload 激活入口）。

**12. active+cleanup_diagnostics 仍显示已应用、清理提示独立、响应中断保留草稿不盲目重发 — 已覆盖**

- 实现：`applyController.ts`（成功只清已提交 keys 并重读；cleanup_diagnostics 独立横幅；uncertain 型保留草稿并提示核对正式状态）。
- 测试：`applyController.test.ts`（16 例：六型分类、cleanup_diagnostics 不翻转结果、uncertain 保留）。

**13. request.invalid 表单级错误、config.invalid 结构化 key 定位、不解析 message — 已覆盖**

- 实现：`src/api/v2/errors.ts`（`configErrorKey` 只读 `details.key`）、`applyController.ts`（无 key 批次错误表单级呈现）、`SettingsOverviewPage.tsx`（ApplyFailureBanner 按 key 定位导航 + Details 原样 JSON）。
- 测试：`errors.test.ts`、`applyController.test.ts`、`SettingsPage.test.tsx`。

**14. 配置覆盖清单逐项核对、主要/高级区与只读原因、唯一主要编辑入口、本页重置不越界 — 已覆盖（含已知缺口，见文末 G1）**

- 清单：`docs/design/config-coverage.md`（W3 逐项核对记录 + §9 八处与后端不一致记录）。
- 实现：`pages.ts`（pathPrefixes 最长前缀归属 + draftSources 整源归属 + surfaces 路由）、`editors/controls.tsx`（FieldSection 按 catalog importance 分 primary/advanced、`readOnlyReason` 来源文案）。
- 测试：`draft/store.test.ts`（`pageDraftKeys`/`resetEntriesWithin` 本页重置不波及他页共享原子）、`SettingsPage.test.tsx`（搜索路由到归属页并高亮字段行）。

**15. family/collapsed 不禁用模型、Provider 与用途引用真实、生图预留无假保存 — 已覆盖**

- 实现：`models/LlmModelsPage.tsx`（family 分组 + collapsed 过滤仅影响展示）、`models/ImageGenerationPage.tsx`（诚实预留页，不伪造编辑能力）、`collectionDrafts.ts`（provider/model/task 引用查找供删除前置清单）。
- 测试：`models/pages.test.tsx`、`models/collectionDrafts.test.ts`。

## Context 与检索

**16. Context 三槽四形状、折叠披露、Session 证据、UI 阅读不改模型语境、历史 Task 与当前 Context 不混淆 — 已覆盖**

- 实现：`src/features/context/`（OverviewPanel 三槽分组、形状驱动视图、heap 分区跳 owner 阅读并标注"非段内已安装正文"、全 GET 只读无 SELECT/RECLAIM）。
- 测试：`segments.test.ts`、`contextDrawer.test.tsx`、`SegmentPanel.test.tsx`、`ContextInspectPanel.test.tsx`、`OwnerResourcePanel.test.tsx`（共 38 例，含"overview 渲染时零 segments/ 请求""全部请求为 GET"断言）；历史 Task 经 `trace/ModelCallPanel.tsx` 事件定向读取，与 Context 抽屉互不消费。

**17. Heap 无 INSPECT 读 installed messages 并转 owner 阅读、fragment 不丢不重、messages/items/text 不混用 — 已覆盖**

- 实现：`SegmentPanel.tsx`（heap installed/available 分区，ref 按能力路由）、`useOwnerPage.ts`（owner 分页 + metadata）、`pagination.ts` + `clients/paging.ts`（fragment 项追加在所属页 items 后）。
- 测试：`SegmentPanel.test.tsx`（heap 分区与无 SELECT/RECLAIM）、`pagination.test.ts`（canonical_json 跨页 fragment 恰好交付一次；合成短分片验证首/中/末序列，§24.2 允许）、`contextDrawer.test.tsx`（messages 分页 continuation 参数）。

**18. Search 真片段/双通道命中/评分/覆盖、result 派生、续页与失效、不调 current Context、不卡隐式 top-k — 已覆盖**

- 实现：`trace/SearchResultView.tsx` + `highlight.ts`（matches Unicode 码点映射切片）、`resources/searchModel.ts`（`buildQueryRequest`/`buildRefineRequest` 有限管道）。
- 测试：`searchResultView.test.tsx`（双分数分开徽标、无命中不补造、覆盖注记）、`highlight.test.ts`（emoji/CJK 码点断言）、`searchModel.test.ts`、`eventWindow.test.ts`（失效/截断语义）。

**19. Search 控件来自实际 retrieval/tool.schema 及 SDK 限制，不受 visibility/granted/未应用草稿影响 — 已覆盖**

- 实现：`resources/searchCapabilities.ts`（能力从 `/v2/config/actions` 当前 generation 的 tool.schema 读取；SDK 浏览 context=none；document query 由 schema oneOf 检出）。
- 测试：`searchCapabilities.test.ts`（literal/regex 声明才出现、document_ref 变体检出、普通 string query 不检出）。

**20. Action 覆盖矩阵与 canonical Catalog 逐项对应、各族实际呈现、旧名/兼容映射已清理、未知可回退 — 已覆盖**

- 矩阵：`docs/design/action-renderers.md`（63 个 canonical ID → 13 结果族，无别名无兼容映射）。
- 测试：`trace/registry.test.ts`（63 ID 全集快照断言，增删 Action 必须同步注册表/矩阵/测试；未知 → generic 回退）、`actionGlimpse.test.tsx`、`resultViews` 族覆盖随 F4-C 补齐（discover_pages/analyze/read/trash_list）。

## 资源与页面

**21. Workspace 编辑/外部变化/归档；Home actual/effective/diff/Reflection；Memory active/daily/知识/反链/redirect — 已覆盖**

- 测试：`workspace/workspacePage.test.tsx`（10：分页/fragment 装配、外部变化两分支、归档只读）、`home/homePage.test.tsx`（7：view 切换带参重读、changes→diff 两模式、diverged 横幅无 accept/reject、整理 Home POST `kind:"home"` 无 target_day）、`memory/memoryPage.test.tsx`（9：日绑定、未归档 vs 空、redirect 横幅+Open target、direct refs 零请求+显式反链、整理记忆默认缺 daily 日+target_day、next_before 翻页）、`home/diffModel.test.ts`（7：行分类无损/真实行号/新建文件左侧为空）。

**22. 回收站移入/恢复、归档只读、无永久删除或清空入口 — 已覆盖**

- 测试：`workspacePage.test.tsx`（回收站流、归档只读）；`mutations.ts` 串行写控制器仅接 trash/restore 无永久删除路由（代码结构保证）；F4-C `trash_list` 族渲染（ref+link+tags）。

**23. full=true 完整正文才可覆盖保存、blob 真实鉴权保留 day、Home 非文本不编造下载 — 已覆盖**

- 测试：`workspacePage.test.tsx`（首屏不完整时显式 full=true 整读并检查 complete/editable，被拒 toast 不提交）、`resources/links.test.tsx`（workspace 图片鉴权 blob→Object URL、home/memory 无 blob 路由显示引用提示）、`homePage.test.tsx`（resource.invalid 非文本显示引用与实际支持操作，不伪装下载地址）。

**24. 资源链接正确进入 day/view/fragment、动态引用无绑定时明确、网页走外部浏览器 — 已覆盖**

- 测试：`resources/reference.test.ts`（16：协议分类/fragment/行定位/动态引用）、`router.test.tsx`（18：各协议×day/view 路由矩阵、unresolved_origin 如实提示不落成今天、Tauri opener/Browser window.open）、`Markdown.test.tsx`（origin 传播、白名单外协议不生成链接）。

**25. 引用进 Composer 保留来源、仅可编辑文本、不自动发送不加载全文 — 已覆盖**

- 实现：`router.ts`（`quoteReference`→`buildQuoteText` 保留 day/view/turn 绑定填入 `composerDraft`，不发送）。
- 测试：`router.test.tsx`（quote 文案与来源绑定断言）。

## 运行观察

**26. Job 输出/停止、ACP 连接与委派区分、MCP GET 无副作用及显式刷新、watcher 状态正确 — 已覆盖**

- 测试：`runtime/jobsTab.test.tsx`（选中才读 detail/output、Stop 以正式快照为准）、`acpTab.test.tsx`（targets/connections 分区、委派只填草稿）、`mcpTab.test.tsx`（打开零 POST、Refresh 逐 server 绑定）、`models.test.ts`（environment sources 收窄：failed/error_type → "仅监听受影响"提示）。

**27. Job 空页续轮、终态读剩余、truncated 不误报、stalled 转产物入口；事件过滤空页按 next_sequence 推进；日期/Reflection 按 next_before 续读 — 已覆盖**

- 测试：`runtime/jobOutput.test.ts`（7：空页留 token/终态 drain/stalled/每 tick 上限 8 页/错误分层/channel 拼接）、`trace/eventWindow.test.ts`（7：through 固定、空过滤页照常前进、gap→truncated）、`memoryPage.test.tsx`（availability next_before 翻页）。

## 渲染与体验

**28. Question 三模式、Mermaid、TikZ、普通代码和错误回退、大图不阻塞主对话输入 — 已覆盖**

- 测试：`chat/questionBlock.test.tsx`（compose/readonly/非法回退）、`QuestionCard.test.tsx`（active/expired）、`test/blocks/codeblocks.test.tsx`（17：BlockFrame 缩放/导出/重试/排队、tikzSlots 上限 2 与让位、MermaidBlock 版本感知缓存）。
- e2e：`test/e2e/codeblocks.pw.ts`（真实 Chromium 渲染 Mermaid/TikZ 成功与失败 4 例，全部请求同源）；渲染器 lazy import + 视区触发，主 chunk 不含渲染器（bundle 证据构建，F0/W2 记录）。

**29. 明暗主题、小窗口、字号缩放、键盘焦点、reduced-motion；无演示口号与常驻聊天日期栏 — 已覆盖**

- 实现：`store/uiPrefsStore.ts`（字号 12–18 clamp、密度、reducedMotion 写 documentElement + `<MotionConfig>`）、`appStore.ts`（主题）、`styles/index.css`（`prefers-reduced-motion` 覆盖全部动效）。
- 测试：`editors/InterfacePage.test.tsx`（4 例）、`appStore.test.ts`。
- 视觉核对（F7-B）：`docs/review/visual-check.md` + `docs/review/screenshots/`——明暗双主题各 23 张真实后端截图逐张核对（含 800px 窄窗口组），结论：tokens 消费一致、双主题成立、空态诚实；9 项低严重度观察问题记录未修（见文末 G4）。

**30. F1 最小真实交互流程与代表性页面视觉核对有记录，fixture 与真实接口验收分别说明 — 已覆盖**

- e2e 记录：F1-D 真实后端流程（连接→提交→问题→回复→完成→刷新恢复），`test/e2e/chat-flow.pw.ts` 连续多次全绿，进度文档 F1-D 小节记录 harness 装配与命令；fixture 级渲染验证为 `test/blocks/codeblocks.test.tsx` + `test/e2e/codeblocks.pw.ts`（进度文档明确区分两者）。
- 视觉核对记录（F7-B）：`test/e2e/visual-review.pw.ts`（独立 config，不进 e2e 门禁）+ `docs/review/visual-check.md`——真实后端 harness 截取对话/设置/Home/Memory/工作区/运行观察/Context 抽屉/历史/窄窗口代表页，每张截图经防空白校验（>15KB + 像素灰度方差），逐图记录主次/字号/密度/等待与空态/主题一致性。

## 缺口与边界汇总

| # | 缺口 | 影响验收项 | 记录位置 |
| --- | --- | --- | --- |
| G1 | Action catalog 文档字段（document_fields）编辑未实现；Actions 页协议摘要只读，搜索可路由但无编辑入口 | 14（清单核对已做，编辑面缺） | 进度文档 F2-C/F2 审计；config-coverage §9 |
| G2 | Tauri webview 内交互式渲染与连接未实测（构建通过、dist 自包含） | 2、28、29 | 进度文档 F0/W2 |
| G3 | 方案应用后真实 LLM/JEV/query 通道切换的后端效果无 e2e（前端提交语义与世代重取已覆盖） | 9 | 本文第 9 项 |
| G4 | F7-B 视觉核对发现 9 项低严重度问题，其中 7 项前端问题（问题 2–8）已由 F7-C 修复并经重跑截图与全量门禁确认；剩余 2 项——`home:agent@AGENT` 读取 503（后端需求单）与亮主题凹版角标对比弱（风格化观察） | 29、30（核对已完成并记录；前端项已修复回归，剩余为后端跟进与观察项） | `docs/review/visual-check.md` 问题清单；进度文档 F7-C；`docs/demand/20260930-home-agent-top-document-503.md` |
| G5 | Environment 事件窗口为一次性定向读取（手动 Re-read），非常驻跟随 | 26（语义已覆盖，形态为设计内边界） | 进度文档 F6-A |
| G6 | 历史轮 agent.action 投影无 result payload，历史卡展开依赖事件保留窗口；normal 级别 model 级 request/response 不记录 | 20（已如实呈现并标注） | 进度文档 F4-B |

以上 G5/G6 是后端契约与既定设计内的呈现边界（前端已如实表达并测试），不是前端实现遗漏；G1–G3 是真实未完成项；G4 是视觉核对产出的打磨清单，其中 7 项前端问题已由 F7-C 修复回归，剩余 1 项转后端需求单、1 项为风格化观察记录。
