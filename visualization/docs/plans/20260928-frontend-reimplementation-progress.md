# Visualization 前端重构执行进度

> 建立：2026-09-29。本文是 `docs/analysis/20260928-visualization-frontend-implementation-plan.md`（权威计划，实施状态由项目维护者更新）在前端仓库内的执行副本，用于记录实施进度、技术验证结论与实施细节；不复制权威计划全文，章节编号与之一致。
> 后端契约基线：`c479ca0`（权威计划复核基线 `6eb0eee` 之后仅多一个文档提交，契约面一致）。
> 契约样例来源：`docs/endpoint/contracts/`；fixture 复制到 `test/fixtures/contracts/` 并注明基线。

## 可行性评估结论（2026-09-29）

实施前已核对：

- API-01～18 与 `tinysoul/gateway/endpoint/http/routes/`（health/turns/reflection/configuration/events/inspection/resources/runtime/workspace）一一对应；`contracts/examples/` 24 个样例覆盖计划引用的全部响应族。
- 旧前端 `src/api/connection.ts` 硬编码 `protocol_version: 1`，按 P00 迁移为 v2 握手。
- 原始 13 点意图全部由计划章节承接；生图模型后端尚无配置面，本轮按计划在“模型与服务”内设预留页，不提交 image_generation 配置。
- 内嵌浏览器本轮不做（网页链接走系统浏览器），与原意图“后续再考虑”一致。

未发现阻塞性设计疑点，按权威计划进入实施。

## 阶段状态

| 阶段 | 状态 | 完成证据/备注 |
| --- | --- | --- |
| F0 契约与技术核对 | done | W1/W2/W3 完成；test 191 例全绿，build + tauri build 通过 |
| F1 数据与壳 | done | 真实 Endpoint E2E 五连绿；vitest 263 例、tsc/build 全绿 |
| F2 设置与方案 | done | F2-A 设置外壳 + ConfigDraft + apply 控制器；F2-B 模型与服务 7 页 + 集合草稿投影/对象编辑原语；F2-C 行为与调用 5 页 + actions 投影/模型用途绑定与检索策略原子；F2-D 工具/连接、数据/知识、系统与界面 10 页 + 集合编辑器 + uiPrefs；F2-E 运行方案管理页 + 草稿确认流 + Composer 方案快捷入口；F2 审计修复完成 |
| F3 对话与历史 | done | F3-A CodeBlockRegistry + Question 代码块协议 + P01 对话体验；F3-B 历史浏览器（日目录/日 Turn 列表）+ Session map + 只读历史轮视图与入口 |
| F4 Context/Action/模型 | done | F4-A Context Drawer（P04 全部）；F4-B Action 渲染器 + Search 卡片 + 模型调用 Inspector（P05 全部）；F4-C 审计修复完成 |
| F5 资源与链接 | done | F5-A ResourceRouter（引用分类/路由/三区分操作/Markdown 协议链接与图片）+ 工作区页（P06 全部）+ 对话侧审计修复；F5-B Home 页（P07）+ Memory 页（P08）+ 两页共享搜索与引用面板落地（§13/§14 相关部分） |
| F6 运行与代码块 | done | F6-A 运行观察页（P09：Execution/Jobs/ACP/MCP/Environment 五分页 + 紧凑概览）+ 代码块收尾（§21.1 全部） |
| F7 收口 | in_progress | F7-A 完成：交接文档 `docs/handoff.md` + 验收映射 `docs/acceptance-map.md`、demand 目录整理（3 项 pending + 5 项归档 + README 索引）、死代码清理（v1 类型簇/占位组件/未消费字段/陈旧注释）、v1 设计文档过期标注、本文收尾；vitest 84 文件 773 例全绿、tsc/build 全绿。F7-B 完成：代表性页面视觉核对——真实后端 harness + Playwright 截取 23 张语义化截图（对话/设置/Home/Memory/工作区/运行观察/Context 抽屉/历史/窄窗口，含明暗双主题），产物 `docs/review/screenshots/` + `docs/review/visual-check.md`；发现 1 中 8 低共 9 项视觉/一致性观察问题（含 Home `home:agent@AGENT` 读取 503 后端疑点），记录未修。F7-C 完成：9 项观察中 7 项低严重度问题（问题 2–8）修复并回归——LLM Models 字段行改名 Feature capabilities、Session map 摘要「·」拍平与下钻钮改面板图标、只读历史 Composer 整体禁用降级、活动 Memory 显式空态、TopBar connecting/reconnecting 区分、引用悬停操作零宽展开；vitest 84 文件 778 例全绿、tsc/build 全绿、视觉 spec 重跑 23 张截图目检+Pillow 复测确认；问题 1 转后端需求单、问题 9 保留观察 |

## F0 实施记录

### W1：v2 契约类型、分页原语、fragment 解码器、连接地址解析、fixtures

已完成。`pnpm test` 26 文件 / 184 用例全绿，`pnpm build`（tsc + vite）通过。

- `test/fixtures/contracts/`：24 个契约样例 + README（注明来源、基线 `c479ca0`、token 不可发送真实后端、resource-resolve 无专门 example）。
- `src/api/v2/`：`json/common/runtime/turn/context/search/job/config/resources/workspace/home/memory/events` 类型（固定 envelope 字段级对齐 schemas，owner 动态内容保持 JsonValue）；`errors.ts` 按 code 分类（continuation 失效、容量拒绝、config.invalid 定位 key 等）；`pagination.ts` 含 CanonicalJsonFragmentDecoder 与 PageFragmentAssembler（逐片即时尝试解析、交付一次、重置语义、Search 顶层 continuation、Job 空页续读）；`connection.ts` 地址解析（IP:Port 默认 http、ws/wss 派生、不被后端 loopback 覆盖）。
- 注意点：home-fragment 首+末样例非相邻页且拼接后仍成形（解码器无法发现跨页缺片，靠 continuation 失效兜底）；capabilities.json 是 acp+mcp 组合包；interaction fragment 解码值的分发（items vs pending_items）留给 F1 client 层。

### W2：Mermaid / TikZJax 最小真实渲染验证

已完成（2026-09-29），产物：`visualization/docs/design/codeblocks.md`、`src/components/markdown/blocks/`（MermaidBlock / TikZBlock / BlockFrame / useInViewport）、dev-only 验证入口 `codeblocks-dev.html` + `src/dev/codeblocks-dev.tsx`、`test/e2e/`（Playwright）与 `test/blocks/codeblocks.test.tsx`（vitest）。

- 依赖：`mermaid@12.0.0`（MIT）、`@drgrice1/tikzjax@1.0.0-beta24`（GPL-3.0+），均锁定进 pnpm-lock.yaml。上游 kisonecat/tikzjax 未发布 npm（`tikzjax` 占位包已下架），采用 drgrice1 维护分支，其 dist 自带 wasm/core dump/tex_files/字体，无需 CDN。
- Mermaid：官方 `initialize` + `render` API（非废弃的 init 扫描），lazy import，视区触发，theme+source LRU 缓存，失败保留源码 + 有限错误。
- TikZJax：隔离方案验证结论为 **iframe（srcdoc）可行、shadow DOM 不可行**（运行时硬绑定 document 扫描/currentScript）；资源以 tikzjax.js 自身 URL 为基准解析，vite 插件 dev 中间件伺服 + build 拷贝至 `dist/tikzjax/`（约 14 MB），全离线。编译在 iframe 内 Worker 进行，SVG 经 `tikzjax-load-finished` 事件提回主文档；失败无错误事件、靠运行时替换的 `//invalid.site` img 标记 + MutationObserver 识别，另有 90s 超时。
- Playwright（chromium）对 vite dev server 真实渲染验证通过：Mermaid/TikZ 正常与失败共 4 例，61 个请求全部同源（含 tikzjax.js/run-tex.js/tex.wasm.gz/core.dump.gz/fonts.css），无 pageerror、无失败请求。
- bundle：主 chunk 不含渲染器（与接入前一致）；一次性证据构建显示 mermaid.core（669 kB）及各图族为独立 async chunk，tikzjax 资源随 dist 交付。
- Tauri：`pnpm tauri build` 成功（cargo 1.97.1，MSI 13.5 MB / NSIS 12.5 MB），dist 自包含（含 tikzjax/ 全部资源，无 CDN 依赖）；webview 内交互式渲染未实测，记录为未覆盖项。
- 已知限制：每个可见 TikZBlock 独占一个 iframe+Worker（未做共享/并发上限）；TikZ 失败详情仅在 iframe 控制台；Mermaid initialize 为全局配置。详见 codeblocks.md「已知限制」。

### W3：配置覆盖清单（计划 §15.2）

已完成，产物：`visualization/docs/design/config-coverage.md`。

- 覆盖后端全部可配置组：llm.providers/models/tasks、infra.model_services、loop.cycle/loop.user、action.models.bindings、action.retrieval（5 个 search action）、execution、jobs、capabilities.web/resource/expand/subagent、workspace/session/home/memory、context、reflection、action.catalog 文档集、agent.* 与 config.* 只读进程项、presets 捕获范围。
- 已记录配置系统事实模型：四类 source 优先级、原子值/collection 展开规则、PATCH→reload/apply 激活语义、凭据脱敏、校验时机。
- 已按 §16–18 逐子页映射编辑归属（清单 §11），并落实 §19 方案捕获精确键清单（清单 §8）。
- 已确认对话/对话记录/对话详情（P01–P03）无需任何配置原语（清单 §10）。
- 发现 8 处与计划/现有前端文档的不一致（catalog render_pdf_pages choices 滞后、旧 settings.md 用 /v1、Kimi 搜索 model 无 catalog choices 等），全部记录于清单 §9；未发现偏离计划的契约问题。

### 原页面视觉保留项（F0 记录，依据 `src/styles/index.css` / `src/utils/motion.ts` 现状）

重构各阶段必须延续的体验资产：

- **Luminous tokens**：三层中性底（`--bg`/`--bg-elev`/`--bg-sunken`）、细边线、靛蓝→蓝 `--accent-grad`、光泽阴影组（`--shadow-card/pop/brand`）、明暗双主题（`:root` / `.dark`）、`@theme inline` Tailwind 映射。新增页面一律消费 tokens，不引入第二套色板。
- **领域色**：core/workspace/execution/web/home/memory/maintenance 七组（含 soft 变体），用于说明 Action 来源；状态色（danger/success/warning/info）只说明运行结果。新增 ACP/MCP/reflection 等来源展示沿用此扩展方式。
- **终端—文档二相性**：`answer-card` 的 terminal（石墨底+磷光绿装饰，双主题一致）→ settle wipe → document 凹版（蚀刻内框、L 角标、扫描线残留）；`--term-*` 调色板、`caret-blink/flicker`、`etch-head` 时序由 `motion.ts` 常量（LIVE_FOLD_MS/FOLD_DELAY_MS/ANSWER_STREAM_DELAY_MS/SETTLE_WIPE_MS）与 CSS 共同驱动。F3 对话重构必须保留这一语言。
- **动效词汇**：EASE_CALM `[0.22,0.9,0.3,1]` 统一 JS/CSS；`grow-in`（reserve-then-expand）、`xfade` 高度滑行、`steps-viewport` 底部溶解、`text-shine`、`live-border` 呼吸边框、`animate-answer-in`、`sub-drawer-in`、`anchor-flash`；`prefers-reduced-motion` 已覆盖全部动效（含 grow-in 强制终态）。
- **Markdown 排版**：`.md-body` 14px/1.65 基线、code/pre/blockquote/table 样式、`.md-inline` 单行塌缩、`.thinking-md` 细斜体推理样式、`.md-calm`；KaTeX 已接入。
- **壳层结构**：`glass-panel`/`glass-elev` 浮层、z-index 阶梯（overlay 40 < drawer 50 < toast 60 < sub-drawer 65/70）、`focus-ring` 统一焦点环、8px 细滚动条、`chat-grid` 蓝图网格背景、`composer-prompt` 终端提示符。
- **既有组件**：`src/components/ui/`（Badge/Button/Card）、shell（AppShell/NavRail/TopBar/StatusBar）、chat（ChatView/Composer/ActionGlimpse/LiveStatus）、trace（TurnTraceDrawer/LlmTaskDrawer/renderers）、workspace 编辑器主布局——按计划 §22.1 保留壳与视觉，仅替换数据来源与旧假设。

记录方式说明：以上为静态核对记录；各阶段（F2/F5/F6）的代表性页面视觉核对将在真实页面上另做对照并记录于本文件对应阶段小节。

## F1 实施记录

### F1-A：v2 类型化 clients 层

已完成。`pnpm test` 281 例（当时基线）全绿，`pnpm build` 通过。

- `src/api/v2/transport.ts`（V2Transport：Bearer、可注入 fetch、AbortSignal、readBlob 支持 Range、错误转 TinySoulApiError）+ `clients/` 14 个 owner client（health/turns/reflection/config/session/context/home/memory/workspace/search/jobs/capabilities/events/resources）+ `createV2Clients` 门面 + `paging.ts`（drainPages，fragment 解码项追加在所属页 items 后）+ `testing.ts`（录制式 fake fetch）。
- 类型增量：session（DaysPage 等）、turn（InboxReceipt/GrantReceipt/CancelReceipt）、runtime（ReflectionAvailability/MCP 族）、config（Preset 请求体）、workspace（TextEdit/Trash）。
- 发现：`GET /v2/reflection` 后端只有 `before` 参数（无 `limit`），client 按后端实现，权威计划 §3.4 的 before/limit 表述待维护者修订（非契约缺口）。

### F1-B：共享 Inspector 组件

已完成。`src/components/inspector/InspectorHost.tsx`（受控 entries 栈、滚动记忆、宽视图、复制真实链接、焦点管理、Esc 逐层关闭、sub-drawer 层），20 个组件测试通过。纯 UI 无 api/store 依赖，页面消费方在后续阶段接入。

### F1-C：连接生命周期 / v2 状态架构 / 壳导航 / 最小对话流

已完成（含 88 个行为测试）。架构切换要点：

- 旧 v1 世界已删除：`src/api/{runtime,history,maintenance,events,tinysoul,exportTrace,connection,transport,configuration,workspace}.ts`、`src/derive/`、`src/components/{chat,monitor,trace,workspace}/`、`src/features/settings/`、`src/store/{configStore,eventRetention}.ts`、`src/hooks/{useBackend,useWorkspace}.ts`、`shell/{MaintenanceDialog,BackgroundDrawer,DisconnectedScreen}.tsx`。旧实现以 git 历史为参考材料，F2/F5 在 v2 上重建（计划 §22.1 的"保留"指复用对象编辑/布局设计而非保留 v1 耦合文件）。
- 新增 `src/app/connection.ts`（handshake → 快照 → WS 订阅全生命周期：epoch guard 防旧连接覆盖、有界退避重连、gap 后 owner 重读 resync、generation/instance 变化处理、ready=false 轮询、显式 restart）与 `src/app/discovery.ts`（Browser localStorage 手动目标 + v1 迁移；Tauri lease 只提供地址+token+身份，协议由 handshake 裁定；lib.rs 无需改动——后端 lease 格式未变）。
- 状态三分：`connectionStore`（连接/status 快照/事件 cursor）、`turnStore`（活动 Turn 投影：正式 interactions + pending_items + 本地 echo，按 command_id/input_id/question_id 身份收敛）、`appStore`（仅本地偏好+toast）；事件只做失效触发，无事件重放权威。
- 壳：NavRail 新导航（Chat/Workspace/Home/Memory/Runtime + 设置），ConnectScreen（地址+token 手动表单、Tauri 本机发现按钮）、PlaceholderPage（未迁移页的诚实空态）。（更新 2026-09-30 F7-A：全部 tab 落地后 PlaceholderPage 已无可达路径，随死代码清理删除，见 F7 实施记录。）
- 最小对话流 `src/features/chat/`：ChatView（owner 投影渲染、当日 Session 列表入口）、Composer（明确意图：新一轮/补充本轮/排队）、QuestionCard（快照恢复即刻可见、choice+comment/Other、预算卡 grant）、turnController（发送收敛、Session 接替有界重试、容量拒绝保稿）。

### F1-D：最小真实交互流程验收

已完成（2026-09-30）。真实 Endpoint（无 mock）+ 受控脚本模型的端到端验证通过：连接 → 提交 Turn → 问题卡 → 选择回复（含 comment）→ 完成 → 刷新后从 Session 恢复。

- 后端 harness `test/e2e/backend_server.py`：装配方式与后端契约测试（`tests/gateway/endpoint/test_contracts.py`）一致——`ProjectInitializer` 初始化临时项目 + `standard_agent` + 配置覆盖（`reflection.schedule.enabled=false`、`loop.user.max_cycles=8`）+ `EndpointEngine` + `EndpointASGIServer`（uvicorn，127.0.0.1）。只有模型输出是脚本（`ScriptedLLM` 实现 TaskRunner 协议，按消息内容驱动）：stage1 选 `core` 域；普通输入回显 `You said: <原文>`；含触发词 `e2e-ask` 时先 `core.ask`（两个选项 + allow_other），检测到回复标记（`e2e-reply-comment`）后 `core.answer` 点名所选 option；`core.answer.generate` 任务返回 input_blocks 中携带的成稿；未知 consumer 返回最小 JSON 兜底。`--port 0` 由 OS 分配空闲端口，实际端口写入 ready file（规避端口冲突），stdout 打 `TINYSOUL_E2E_READY port=N`。
- Playwright 接入 `test/e2e/backend.global.ts`：globalSetup  spawn Python harness（Python 解析顺序 `$TINYSOUL_PYTHON` → `$CONDA_PREFIX/python.exe` → PATH 上的 `python`），轮询 ready file 后把 `{address, token}` 写到 `<repo>/.local-test/e2e-backend/connection.json`，并返回 teardown 杀进程；项目目录每次运行重建（当日 Session 列表从空开始）。运行目录放在仓库根 `.local-test/` 而非 `visualization/.local-test/`：vite dev server 监视 `visualization/`，其瞬时读句柄会导致 Windows 下项目初始化 staging 目录 rename 失败（WinError 5）。
- 场景 `test/e2e/chat-flow.pw.ts`：ConnectScreen 填地址+token 连接（导航解锁、空态可见）；发送 `e2e-plain …` → 用户气泡收敛为恰好 1 条、`.answer-card` 回显恰好 1 条；发送 `e2e-ask …` → 问题卡出现（2 个 radio）→ 选 Option B + 填 comment → Reply → radio 消失、卡片只读（"answered"、所选选项高亮类）、回复气泡（option_id+comment）恰好 1 条、最终回答 `You picked Option B (opt_b).` 且含 comment；`page.reload()` 后经 localStorage 自动重连，当日对话列表出现两轮，打开 ask 轮为只读历史（user.input / 已答问题 / user.reply / agent.output 齐全且各 1 条）；全程 `pageerror` 为空。
- 运行命令（visualization/ 下，需 TinySoul conda 环境）：`TINYSOUL_PYTHON=$CONDA_PREFIX/python.exe pnpm exec playwright test -c test/e2e/playwright.config.ts`（或先 `conda activate TinySoul`）。结果：连续 4 次全绿（chat-flow 约 3.8–3.9s，codeblocks 约 1.2–1.4s），后端每次随机端口（如 55334/49680/64961）。
- 修复的真实 bug（真实浏览器才暴露）：`src/api/v2/transport.ts` 默认分支 `options.fetchImpl ?? fetch` 把全局 `fetch` 裸存为成员，随后以方法形式调用导致 `Illegal invocation`，Connect 必然失败（vitest 注入 fake/Node fetch 不触发）。修复为箭头包装调用。该文件位于"不改 src/api/v2"约定边界内，属阻塞 F1-D 的最小真实 bug 修复，特此说明。
- 既有测试 flake 修复：`test/e2e/codeblocks.pw.ts` 对 tikzjax 失败用例的运行时标记图（`http://invalid.site/img-not-found.png`）的 fetch 失败/DNS 行为是环境相关的，现对该已知标记豁免 `requestfailed` 与 external 检查（设计内的失败信号，非 CDN 拉取）。
- 备注（已过时部分更新）：F1-C 测试文件随后已由测试补齐工作流完成并修正——当前 tsc、vitest 263 例、build 均全绿。

## F2 实施记录

### F2-A：设置外壳与共享 ConfigDraft

已完成（2026-09-30）。`pnpm test` 328 例全绿（其中 settings 64 例：draft core 45 = model 24 + catalog 10 + store 11，apply 流程 16，壳冒烟 3；其余为既有用例），`pnpm build`（tsc + vite）通过，chat 侧互不干扰。

- 外壳 `src/features/settings/`：`SettingsPage.tsx`（连接加载/断开重置、beforeunload 提示、全局 ApplyFailure/CleanupDiagnostics 横幅）、`SettingsNav.tsx`（搜索 + 命中列表 + 可折叠分组 + 每页草稿计数 Badge）、`SettingsBottomBar.tsx`（草稿/stale/校验计数、Reset this page、Discard all、Apply 或 Activate saved，按 `activity.can_reload` 禁用并展示真实原因）、`SettingsOverviewPage.tsx`（运行配置/待激活/本地修改含 stale adopt-keep/方案只读列表）、`SettingsPlaceholderPage.tsx`（未实现子页诚实占位）、`SettingsDraftChip.tsx`（离开设置 tab 后左下角浮动数量提示，草稿仅存内存不落盘——凭据安全）。
- 页面注册表 `pages.ts`：六组（概览与运行方案/模型与服务/行为与调用/工具与连接/数据与知识/系统与诊断）+ 界面设置入口占位（F2-D 接手），共 24 页；每页声明 surfaces + pathPrefixes（底栏原子级撤回的依据）+ placeholder 标记；生图模型在「模型与服务」下设预留占位。`searchConfig` 在 fields/collections/document_fields 上检索并路由到归属页。
- ConfigDraft（`draft/model.ts` 纯逻辑 + `draft/store.ts` zustand）：draft 身份 `(source_id, path)`（JSON codec key）；`setValue/deleteValue/resetEntries/resetEntriesWithin/discardAll`；三态查询 entryView（draft/saved/active）；脱敏识别同时兼容后端实际的 `"<redacted>"` 字符串与文档旧述的 `{$credential:true}`；本地校验（`draft/catalog.ts`：catalog 宽容解码、`*` 段通配 matchField、value_kind 形态 + null 递归 + reference 目标在 projectedKeys 中存在性——同草稿新建对象可被引用）；`rebaseOnSaved` 在 saved 基线移动时把脏条目标记 stale 并保留本地值（双占位不标）；`resetAtomEntries` 支持共享原子（如 `action.models.bindings` 数组按 consumer、`action.retrieval` map 按 key）的逐条目撤回，数组按基线序归位使全量撤回后恰好等于基线从而清草稿。
- 应用/激活 `applyController.ts`：loadConfig 并行读 saved+active+catalog+presets；applyDrafts 批量提交，成功 `state=active` 只清已提交草稿 keys 并重读快照；cleanup_diagnostics 独立横幅提示且不恢复"未应用"；失败一律保留草稿并分类为 ApplyFailure 六型（config-invalid 带 `details.key` 定位导航/无 key 批次错误、request-invalid、activation-unavailable 409、activation-failed、api-error、uncertain 网络/未知）；无本地修改但 saved 待激活（pending_reload）时底栏提供 reload 入口。
- 修正既有文档事实：`config-coverage.md` 的凭据脱敏形态由 `{"$credential": true}` 更正为后端实际行为（`controller.py` `_effective_fields`/`_source_values` 输出字符串 `"<redacted>"`，fields 项另带 `redacted: true`）。
- 集成：`AppShell.tsx` settings 分支渲染 `SettingsPage`，非 settings tab 渲染 `SettingsDraftChip`；`PlaceholderPage.tsx` 删除 settings 死分支（连接提示移入 SettingsPage.ConnectNotice）。
- 修复的实现期 bug：`resetArrayEntries` 原先把"恢复被删基线条目"追加到数组末尾，导致全量撤回后与基线仅差顺序而无法清除草稿——改为按基线序归位（测试"restores owned baseline entries that were removed from the draft"暴露）；`SettingsBottomBar` 的 zustand selector 返回新数组引用导致 getSnapshot 无限循环——改为选稳定 `drafts` 引用 + `useMemo` 派生。
- 设计决策：底栏 "Reset this page" 用 pathPrefixes 原子级撤回，`resetEntriesWithin` 留给后续页面做共享原子内逐条目撤回；无 pathPrefixes 的页（如凭据、生图预留）底栏重置禁用，将来页面自行调用 store；草稿不持久化 localStorage。

### F2-B：模型与服务设置页

已完成（2026-09-30）。`pnpm test` 49 文件 / 427 例：426 过，唯一失败为并行 F3 工作流未跟踪目录 `src/features/history/` 的 historyBrowser 用例（与本批文件无 import 关系、单独运行同样失败）；settings 模块 12 文件 121 例全绿（本项新增 collectionDrafts 17 + pages 8）；`npx tsc --noEmit` 与 `pnpm build`（tsc + vite）全绿。改动集中在自有目录 `src/features/settings/models/`；共享文件仅最小增量——`pages.ts` 七页翻 `placeholder: false`、`SettingsPage.tsx` 的 `PAGE_COMPONENTS` 注册表加 7 条（跟随该文件现行内联注册表模式）、`draft/catalog.ts` 增 adapters 解码、`draft/model.ts`/`draft/store.ts` 草稿投影泛化各一处。

- **集合草稿投影（`models/collectionDrafts.ts` 纯逻辑 + 17 例测试）**：`projectCollection`/`projectedFields` 把 saved/active/草稿三态拍平为对象集合（whole-object set 草稿按 catalog 边界拍平成字段、delete 草稿只删该 source 实际拥有的键）；`projectAtomEntries` 标 new/modified/deleted；引用查找 `providerReferences`/`modelReferences`/`taskChainUsage`/`useConsumers`/`serviceProviderReferences`/`serviceModelReferences` 供删除前置清单；`deriveCredentials` 从 provider/model 的 env 引用推导凭据目录；`providerCredentialStates` 只读投影 `active.runtime.llm.providers` 的运行时凭据状态（不含机密）；另有 `objectDeletable`/`moveItem`/`objectIdError`/`fieldWriteSource`/`fieldLockReason`。
- **对象编辑原语（`models/objectEditing.ts`）**：`setObjectField`/`clearObjectField` 字段级草稿（draft-new 对象的字段编辑折叠进整对象 set 草稿）；`stageObjectCreate`（catalog create_template → create_source 整对象 set）；`stageObjectDelete`（撤本地草稿 + `deleteValue` 逐源删除，依赖 `sourceOwnsPath` 的子树归属泛化）；`stageObjectRename` = 新 id 整对象 set + 旧 id 逐源 delete + 可选调用方引用改写（LlmModelsPage 级联改写 task chains 的 model 引用）；`setAtomEntries` 写共享数组原子（专用服务 uses）。
- **共享 draft 增量**：`draft/catalog.ts` 增 `decodeAdapterRules`（`rules.llm.adapters` → AdapterOptionRule/AdapterProtocolRule/`adapterRule` 查询），供模型页按 adapter 渲染条件高级选项与 protocol 切换清理；`draft/model.ts` 的 `sourceOwnsPath` 由叶子归属泛化为子树归属（叶子或下层键）；`draft/store.ts` 的 `projectedKeys` 感知 set/delete 草稿，使草稿新建对象可被 reference 校验识别。
- **共享控件与布局（models/ 内）**：`controls.tsx`（FieldSection/FieldRow/Text/Number/Select/Toggle/TagList/ChoiceToggles/JsonObjectInput/OrderableRow 上下移+拖拽）；`ObjectEditor.tsx`（ObjectEditorLayout 列表+编辑+分组头，Create/Delete/RenameObjectModal）；`credentials.tsx`（CredentialValueEditor：脱敏占位符绝不回写、Set/Remove 显式操作、shared 徽标）；`capabilities.ts`（7 页各自的能力声明）。
- **七个页面**：`LlmProvidersPage`（provider 对象集合：adapter/base_url/headers/凭据引用，运行时凭据状态只读条，删除前列出 models/tasks 引用）；`LlmModelsPage`（family 分组 + collapsed 家族过滤，adapter 条件高级选项由 catalog adapter rules 驱动，protocol 切换清理不适用字段，rename 级联 task chain 引用，`delete_policy: create_source_only` 的内置模型禁删禁改名）；`LlmTaskChainsPage`（候选 model 有序列表 OrderableRow，model 引用 draft 感知——可引用草稿新建模型）；`DedicatedProvidersPage`（infra.model_services providers 整数组原子经 `setAtomEntries`，条目缺可写 source 时禁用并说明来源——回退源 `project:configs/infra/model_services.toml`，模板 include `configs/infra/*.toml`）；`DedicatedModelsPage`（models/uses 双 tab，kind↔adapter 约束 embedding↔openai_embedding 与 structured_decision↔typesafe_system_one、max_retries 0–5、embedding dimensions>0 且 decision 无 dimensions、batch_size 1–256，与后端校验一致）；`CredentialsPage`（按 group 分组 + Add credential，值走共享 dotenv 草稿、Set/Remove 显式、占位符不回写，"Discard credential changes" 逐组撤回）；`ImageGenerationPage`（诚实预留页——后端尚无 image_generation 配置面，不伪造编辑能力）。
- **分层说明**：对象集合投影放在 `models/` 而非共享 `draft/`，为避免与并行 F2-D 工作流冲突；F2-D 的 `draft/fields.ts`（叶子级写源解析，无草稿投影）与本目录的草稿感知投影是有意分层，重叠点（objectIdIssue/objectIdError 等身份规则）留作后续合并候选。

### F2-C：行为与调用设置页

已完成（2026-09-30）。`pnpm test` 59 文件 / 507 例全绿（settings 模块 15 文件 145 例，本轮新增 behavior/actionsView 3 + models 12 + BehaviorPages 9）；`npx tsc --noEmit` 与 `pnpm build`（tsc + vite）全绿。改动集中在自有目录 `src/features/settings/behavior/`；共享文件仅最小增量——`pages.ts` 五页翻 `placeholder: false`（reflection 页 pathPrefixes 同步收紧）、`SettingsPage.tsx` 的 `PAGE_COMPONENTS` 注册表加 5 条。

- **Actions 投影（`behavior/actionsView.ts` + `useActionsView.ts`）**：`GET /v2/config/actions?scenario=user|home_reflection|memory_reflection` 的宽容解码投影（domain/action 元数据、模型用途 consumer、协议摘要）；`useActionsView` 按 (generation_id, scenario) 缓存——投影属于运行世代，apply 发布新世代后自然重取；scenario 切换只改读取视图，不触碰 ConfigDraft。
- **模型用途绑定（`behavior/bindingsModel.ts`）**：`action.models.bindings` 共享数组原子按 consumer 逐条目编辑/撤回（复用 F2-A `resetAtomEntries`，数组按基线序归位使全量撤回恰好清草稿）；条目无更近写源时回退 `project:configs/action/routing.toml` 并如实标注来源。
- **检索策略（`behavior/retrievalModel.ts`）**：`action.retrieval` 整 map 原子按 action key 编辑/撤回；`SEARCH_CAPABILITIES` 静态注册表覆盖五个 search action（`core.context.search`/`home.search`/`memory.search`/`workspace.search`/`expand.search`）的来源与操作能力边界（expand.search 无 backlinks、无 current context，embedding query channel 仅 home/memory），与后端模板 `assets/standard/configs/action/retrieval.toml` 一致；`policyIssues` 本地校验（embedding_similarity 绑定时 allowed_context 不得含 current、embedding channel 需对应 `home/memory.search.embedding_use`、max_steps 1..32 等数值范围）。
- **五个页面**：`PhaseBindingsPage`（`loop.cycle.phase1/2_task_profile` 链选择 + 任务链页跳转，默认 `frame_stage1/2`）；`ActionsPage`（domain/scenario 过滤的行为清单 + 每 action 模型用途绑定编辑 + 协议摘要只读）；`SearchPoliciesPage`（五 action 的来源/操作/预算分区编辑，校验问题就地提示）；`BudgetsPage`（`loop.user.max_cycles`、`reflection.home/memory.max_cycles`、`session.background_max_chars`、`context.*` 预算族，trace 四字段随 catalog 标 advanced 折叠）；`ReflectionPage`（`reflection.schedule.enabled/daily_time`、`reflection.timezone`、`reflection.archive_root`）。
- **接线**：`pages.ts` 五页翻 `placeholder: false`；reflection 页 pathPrefixes 收紧为 `["reflection.timezone", "reflection.archive_root", "reflection.schedule"]`，底栏 "Reset this page" 原子级撤回不波及 `reflection.home/memory.*`（归 Budgets 页）。
- **后续工作**：catalog 文档字段（document_fields）编辑与 `action_catalog` 完整表面留待后续，本轮协议详情为只读摘要。

### F2-D：工具/连接、数据/知识、系统与界面设置页

已完成（2026-09-30）。`pnpm test` 46 文件 / 395 例全绿（settings 模块 10 文件 96 例：F2-A 54 + 本轮 fields 15、ToolsPages 6、DataPages 3、SystemPage 4、InterfacePage 4）；`npx vite build` 通过。`pnpm build` 的 tsc 阶段当前被**另一工作流进行中的文件**阻塞（`settings/models/*` 的 ServiceBinding/ProviderBinding 类型错误与 `chat/ChatView.tsx` 未用导入），与本批文件无关——本批全部文件 tsc 零错误，待该工作流收尾后整体门禁恢复。（更新 2026-09-30：F2-B 已收尾，tsc/build 已恢复全绿。）

- **写源解析与对象原子（`draft/fields.ts` 纯函数 + 15 例测试）**：`writeSourceForPath`（字段在投影中→其可写来源；缺失字段→共享最长点分前缀的可写 project 源）、`readOnlyReason`（environment/override/只读源文案）、`objectBaseline`（叶子字段反扁平化为对象，env/tools 等原子 map 整体赋回）、`objectSourceFor`（持有最多叶子的可写源，新建回退 collection create_source）、`subtreeDeleteRefs`（每个持有叶子的 project_toml 源一条 delete ref）、`objectDraftClears`、`objectIdIssue`（禁点/禁首尾空白/禁纯数字，镜像后端身份规则）。store 增加 `deleteRefs`：跳过叶子归属检查的批量删除（对象根本身不是叶子键）。
- **共享控件（`editors/controls.tsx`）**：`useDraftField`（display/dirty/stale/readOnly/sourceId 聚合，zustand selector 只选稳定引用）；`FieldRow`（catalog 标题/描述、modified/stale/read-only 徽标、撤回按钮、Details 折叠显 path/source、focusPath 滚动定位+高亮后消费）；布尔开关、数字（integer/min/max/单位按路径后缀推断，blur/Enter 提交，非法标红不落草稿，清空=delete 恢复默认）、文本、枚举（catalog choices，可本地覆盖）、enum_list 复选、string_list 行编辑；`CredentialReferenceControl`（引用名走普通字段草稿）+ `CredentialValueEditor`（值走共享 dotenv 草稿：未输入不落 operation，Set 才 set，Remove 显式 delete，状态徽标 configured/not set/pending）；`KeyValueMapEditor`（受控整 map 一次提交，键可含点）；`AdvancedFields` 折叠；`FieldSection`（按 catalog importance 自动分 primary/advanced，`forceAdvanced` 覆盖）；`EmbeddingUseControl`（draft 感知读 `infra.model_services.uses` 过滤 kind==="embedding"，"Not set"=delete 恢复默认，附向量缓存重建说明与专用用途页跳转）。
- **集合编辑器（`editors/collection.tsx`，MCP/ACP 共用）**：左列表右编辑；对象 id 集合=基线叶子前缀 ∪ 同草稿新建 − 删除；整对象编辑经 `update(patch)`（undefined 删键，编回基线自动撤草稿）；新建=catalog create_template 整对象 set 到 create_source（新条目 enabled=false）；删除=撤本地草稿 + `deleteRefs(subtreeDeleteRefs(...))` 逐源删除；草稿新建对象显示 new 徽标，删除仅撤回不产生 delete op。MCP 按 transport 条件渲染（stdio→command/args/cwd/env/env_refs；streamable_http→url/headers/header_refs），tools 布尔 map 折叠编辑（含点工具名为原子键）；env_refs/header_refs 每个引用值旁挂共享 dotenv 编辑器。两页顶部各挂只读运行摘要（`/v2/expand/servers`、`/v2/subagent`，无连接/无条目如实提示）与"运行观察"跳转；改配置不自动启动服务。
- **十个页面（`editors/*.tsx`）**：Execution（当前生效只读条 + 四解释器 + Limits/Jobs，高级折叠）、Web（Kimi Search 含 api_key_env 凭据引用与 model 硬编码 k2.5/k2.6 选择——catalog 无 choices 见 config-coverage §9.5、Page Discovery、Fetchers、共享上限、Resource 转换含 render_pdf_pages 按 catalog choices 显示靠后端 422；明示与内部 Search Policies 的边界）、ACP/MCP（集合编辑器+共享 limits）、Workspace（root/读写/ignore_dirs/watch/search/analysis，pinned/tmp/library 标签说明）、Session（background_max_chars 只读+跳 Budgets——pages.ts 最长前缀归属，与 config-coverage §3.4 表述分歧以注册表为准）、Home/Memory（路径/上限/search + embedding_use，Home 页注明 actual/effective overlay 语义）、System（process_shell 只读投影、sources 列表可写性徽标、agent.*/config.* 进程项只读+归因、可写 context.system_text/journal）。
- **界面设置（§20）**：`src/store/uiPrefsStore.ts`（persist `tinysoul-ui-prefs`：fontSans inter/system/serif、fontMono jetbrains/system/cascadia、fontSize 12–18、lineHeight 1.3–1.9、density compact/comfortable/roomy、reducedMotion；merge 校验 + 数值 clamp）；`applyUiPrefsToDocument` 纯函数把偏好写为 documentElement 上的 `--font-sans/--font-mono/--ui-font-size/--ui-line-height/--ui-density` + `ui-reduced-motion` 类；`App.tsx` 加 effect 与 `<MotionConfig reducedMotion>`；`index.css` 末尾追加小节（body/.md-body 字号行高、`--spacing` 密度缩放、毯式减动画），fallback 恰为原主题故未设置时渲染不变。主题留在 appStore（NavRail 已在用），界面页控件写 `setTheme`；恢复默认一并重置主题。无消费方的自动跟随/通知/宽度三项不交付（不做假开关）。
- **接线**：`pages.ts` 十页翻 `placeholder: false`；`SettingsPage.tsx` PageContent 按 `PAGE_COMPONENTS` 分发（overview 保留；interface 不读配置 store、断连也可渲染）；壳测试 placeholder 用例改点 "Run plans"（F2-E），搜索路由用例改为断言目标页消费 focusPath 并高亮字段行（真实页面行为，原断言 focusPath 驻留是占位页行为）。
- **与计划/清单的对齐记录**：Kimi model 两值选择（§9.5）、render_pdf_pages 按 catalog 显示（§9.1）、MCP/ACP 编辑进同一整批草稿不自动启动服务（§18）、`session.background_max_chars` 归 Budgets（pages.ts 注册表优先于 §3.4 行列表述）、embedding_use 主编辑入口在 Home/Memory 且引用选择 draft 感知（§15.1/§15.2）。

### F2-E：运行方案管理与 Composer 快捷入口（P14 + §5.2）

已完成（2026-09-30）。`pnpm test` 77 文件 / 686 例全绿（本项新增/扩展：presetsModel 13、presetsController 12、PlansPage 12、PresetEntry 8、SettingsPage 壳 4），`pnpm build`（tsc + vite）通过，真实后端 Playwright e2e 2 例通过（chat-flow 4.9s + codeblocks 1.2s）。范围约束遵守：改动集中在 `src/features/settings/presets/`（新建）与 `src/features/chat/PresetEntry.tsx`（新建）；共享文件仅最小增量——`pages.ts` plans 翻 `placeholder: false`、`SettingsPage.tsx` 注册 PlansPage、`SettingsOverviewPage.tsx` 方案区改为跳方案页、`applyController.ts` 增 `ensureConfigLoaded`、`Composer.tsx` 挂载点接线、`ChatView.test.tsx` 适配（注册 config 假路由 + renderChat 吸收首载微任务）；未触碰 api/v2、workspace、resources、trace。

- **方案模型（`presets/presetsModel.ts` 纯逻辑）**：受管范围固定注册表（models/tasks/routing/retrieval/budgets 五组，含各自配置键说明与"不捕获什么"注记），以 `included_scopes` 为后端事实来源；`buildCaptureBody` 三源语义——active→`source:"active"`、saved→`source:"saved"`、draft→`source:"saved" + operations`（空 operations 退化为纯 saved）；`buildRenameBody` 保证无 `capture` 键（重命名不重抓）、`buildRecaptureBody` 保证只有显式覆盖才携带 `capture`；`decodePresetSnapshot` 宽容解码（snapshot 是读取结构，永不作 POST 体）；`snapshotDiff` 在受管范围内对运行配置做叶子级比较（change/add/remove/default 四类，values 组整组双向比较、retrieval 只比较受管字段——sources/operations 等非受管字段绝不进入差异）；`budgetSummary` 关键预算摘要（无 budgets 组返回空，如实表达"预算保持现状"）；`parseValidationIssues` 只取结构化 `{key, message}`，不从 message 解析字段。
- **流程（`presets/presetsController.ts`）**：create/rename/recapture/delete 四个捕获族流程——只保存方案记录，绝不调用 apply、绝不清草稿（有测试断言零 apply 请求且草稿保留）；忙碌时可编辑方案记录，仅激活受 `activity.can_reload` 约束。`applyPreset` 提交且仅提交 `{preset_id}`（类型层 ConfigApplyRequest 已禁混发）；成功 `state=active` 后只清"用户在确认流中同意放弃"的草稿键（飞行中的新编辑保留）、重读 saved/active/catalog/presets、`cleanup_diagnostics` 走既有独立横幅；失败经 `classifyApplyError` 六型分类保留草稿（config.invalid 带 key 可定位、409 activation-unavailable、网络/结果不明归 uncertain）。
- **§15 草稿确认流（`presets/PresetDraftConfirm.tsx`）**：共享确认组件 + `usePresetApplyFlow` 守卫 hook，设置方案页与 Composer 快捷入口共用同一实现。无草稿直接应用；有草稿弹出三分支——"Review my changes first"（回设置概览页自行应用/放弃）、"Discard changes and switch"（只发 `{preset_id}`，成功后才清已同意草稿，失败保留并复用 applyFailure 状态呈现）、取消（保留草稿，不发生请求）。不自动合并、不连发两次请求（均有测试）。
- **设置方案页（`presets/PlansPage.tsx`，挂"概览与运行方案"组）**：左列表（名称/说明/active·matches saved 徽标/依赖问题计数/受管组行）右详情。详情含：应用按钮（active_match 时禁用"已是当前"、忙碌按真实原因禁用）、重命名、显式覆盖捕获、删除（确认框明示不影响运行/保存配置）；依赖问题卡列出后端结构化 key/message 并按 `pageForPath` 跳对应设置页；受管范围卡固定说明五组与排除项；"与运行配置的差异"卡渲染叶子级 diff（bounded 12 行 + 余数）；Stored snapshot 折叠区标 "read model — never an apply body"（JsonTree 只读）。创建对话框：名称/可选说明/三源单选（草稿源显示修改数、无草稿禁用并解释）/包含预算开关（默认开，与后端默认一致）。不提供"任意旧方案复制"——API 无 from_preset，需要变体时编辑草稿另存。
- **Composer 快捷入口（`chat/PresetEntry.tsx`）**：挂 `data-slot="preset-entry"`。收起态显示当前匹配方案名，无方案或已偏离显示 "Custom"；展开 popover 列方案（名称/匹配徽标/说明/问题计数），行内展开惰性读 detail 显示受管组与关键预算摘要；"Manage plans" 切设置 tab 并定位方案页。应用仅在 `activity.can_reload` 时可点（忙碌显示真实原因、列表仍可查看），成功后由重读快照驱动徽标更新，绝不显示假已切换状态；切换与发起 Turn 是两次明确操作。配置快照经 `ensureConfigLoaded` 按连接惰性加载一次（模块级 clients 身份跟踪：同连接重挂载不重取、新连接必重取——覆盖 chat tab 在断开时错过 SettingsPage 重置的边界）。
- **既有行为保持**：概览页方案区保持只读摘要但改为可点跳方案页；`SettingsPlaceholderPage` 随全部子页落地退出壳分发路径（组件与直接渲染测试保留）。

建议 commit：`feat(visualization): F2-E run-plan management — presets page with capture/diff/apply, shared §15 draft guard, composer quick entry`

### F2 审计修复

已完成（2026-09-30）。只读审计发现的四项偏差逐项修复，`pnpm test` 77 文件 / 699 例全绿（settings 模块 18 文件 188 例，本项新增 BehaviorPages 滑块 3 例、SettingsPage 壳 3 例，并修正 Budgets 既有用例的选择器）；本批全部文件 `tsc` 零错误。审计确认的有意省略项不动：§20 无消费方偏好不交付；Action catalog 文档字段（document_fields）编辑维持 F2-C 记录的缺口，不在本批实现。

- **数值滑块（计划 §15/§17.4）**：`editors/controls.tsx` 新增 `SliderField`——range 滑块 + 精确数字输入（复用 `DraftNumber` 的校验/提交语义）+ 单位显示 + 显式"恢复默认"（删除来源覆盖，与 FieldRow 的"撤回本地草稿"分开）；滑块只做快速调整并夹取到呈现区间，精确输入仍是权威入口。`FieldOverride.slider` 声明呈现边界；`SettingsField` 在 override 或 catalog 字段声明 min/max 齐备时派发滑块，任一侧缺边界保持纯数字输入（不用滑块表达对象排列）。`draft/catalog.ts` 的 `CatalogField` 宽容解码可选 `min`/`max` 键（后端 catalog 当前未声明，声明后无需改前端即出滑块）；校验边界同时取 override → catalog min/max。Budgets 页全部 11 个有界数值接入滑块（Turn Cycles 三项 1–64、图像字节预算 1–64 MiB、Session 背景 1K–128K chars、两个压缩比 0–1 step 0.01、Trace 四项）；顺带把 `session.background_max_chars` 校验下限对齐后端真实约束 512、`context.trace_inspect_max_chars` 对齐 1024（MIN_CONTINUATION_PAGE_CHARS）。Reflection 调度页无数值项（reflection.home/memory.max_cycles 归属 Budgets 页，已随上覆盖）。
- **凭据页归属（pages.ts）**：`SettingsPageDef` 新增 `draftSources`（整源草稿归属）——dotenv 草稿的 path 是裸变量名、无前缀可匹配，凭据页按来源认领；新增 `pageForDraft`（先整源归属、再最长前缀），`pageDraftKeys` 同步覆盖。接线后：底栏 "Reset this page" 在凭据页可撤回 dotenv 草稿（页面自带 "Discard N credential changes" 按钮保留为等价路径）、`SettingsNav` 每页计数徽标包含凭据草稿、概览 "Local changes" 的 locate 可导航到凭据页。
- **ApplyFailureBanner 保留原 details**：横幅新增 Details 展开区，对携带结构化 details 的失败类型（config-invalid/request-invalid/activation-failed/api-error）原样展示 JSON（JsonTree）；无 details 的类型不出现展开钮，定位仍只依赖结构化 `details.key`。
- **凭据编辑器去重**：`editors/controls.tsx` 与已删除的 `models/credentials.tsx` 两份 `CredentialValueEditor` 合并为 controls.tsx 单一份共享实现——保留 models 版的就绪徽标/Set value 展开流/按实际 dotenv source id 解析/可写性禁用，并入 editors 版的显隐切换与单条撤回；CredentialsPage、LlmProvidersPage、DedicatedProvidersPage、`CredentialReferenceControl`、MCP/ACP 集合编辑器的 env_refs/header_refs 五处调用点全部指向共享实现。

建议 commit：`fix(visualization): settings audit fixes — bounded-number SliderField, credentials page draft ownership, apply-failure details expansion, single shared credential editor`

## F3 实施记录

### F3-A：代码块注册表、Question 代码块协议与 P01 对话体验

已完成（2026-09-30）。`pnpm test` 41 文件 / 367 例全绿（本项新增/扩展：Markdown 11、QuestionCard 10、questionBlock 7、ChatView 6 例），`pnpm build`（tsc + vite）通过，真实后端 Playwright e2e（chat-flow 4.0s + codeblocks 1.4s）通过。范围约束遵守：改动只在 `src/components/markdown/`、`src/features/chat/`、`src/styles/index.css`（append-only），未触碰 api/v2、connectionStore、app、settings，未引入新依赖。

- **CodeBlockRegistry（§21.1）**：`src/components/markdown/codeBlockRegistry.ts` —— language alias（大小写不敏感、可重注册）→ `{parse?, render, fallback}`。`render` 是 ComponentType（renderer 可用 hooks），`parse` 是纯函数，返回 null 或抛错一律落到 fallback。未知 fence 不进注册表、保持默认 pre/code 渲染，任何代码都不会被当作可执行脚本。主题 light/dark 经 `CodeBlockRenderProps.theme` 传入。
- **Markdown 接入**：用 `components.pre` 覆写而非 `components.code`（react-markdown v10 无 inline prop，pre 天然区分块级与行内，行内 code 永不经过注册表）；从 code 子元素取 `language-*` 与源码。流式未闭合 fence 由 `findUnclosedFenceLine` 行扫描判定（只认行尾无 info 的同字符闭合），起始行号经 `MarkdownRenderContext` 传给 pre renderer 并与 hast `node.position.start.line` 比对——只有文档尾部的开放 fence 显示源码，完整 fence 才进注册渲染（Mermaid/TikZ 的 useInViewport 视区触发不变）。context 值以 view 原语为依赖，避免打字机期间 context 身份抖动导致块重挂载。KaTeX/GFM 管道不动。
- **内置注册**：`blocks/builtinBlocks.tsx` 模块级注册 `mermaid`/`flowchart`→MermaidBlock、`tikz`→TikZBlock，由 Markdown.tsx import 触发。
- **Question 协议（§6/§6.2）**：`questionContent.ts` 的 `parseQuestionFence` 解析 `{question, options? ≤8 且 id 唯一, allow_other? 默认 true}`，非法一律返回 null 回退为可读代码块，不伪造待答状态；`questionBlock.tsx` 注册 `tinysoul-question` fence。fence 只产生两模式：`origin.view==="history"`→readonly，live→compose（点选选项把成稿写入 composer 草稿，卡片自身不发送）；active 数据永远来自 TurnSnapshot 的 waiting 问题，由 QuestionCard 路径产生。
- **QuestionForm 统一（§6.1）**：`QuestionForm.tsx` 单一组件承担 active/compose/readonly/expired 四模式；QuestionCard 重写为模式解析 + StatefulQuestionCard（submitting/error + replyToQuestion），live 快照优先于 item.answered（快照是待答权威）。选项 A/B/C 字母 chip 仅视觉编号（aria-hidden）、提交携带稳定 option_id、description 在选项卡内、Other 自由文本、comment、radio+form 键盘可达；readonly 显示问题+所选 label+comment+"answered"；未答且非 live（含历史未答）→expired，显示已失效并保留未发送草稿。预算卡保持独立。`composerDraft.ts`（zustand）在 compose 模式与 Composer 间共享草稿。
- **P01 体验（§5.1/§7）**：ChatView 重写——保留 bubble-user/answer-card；fresh agent.output 走 AnswerCard 入场 + useTypewriter（`durationMs=min(len*6.5, 9000)`，typing 期间 `answer-streaming`，结束后 `answer-settling` 1600ms=SETTLE_WIPE_MS）；恢复内容即时渲染。freshness baseline（viewKey=`${turnId}:${source}`，loading 时不锁定，takeover live→session 重定 baseline）保证窗口恢复/会话切换不重播历史。滚动锚定：底部 pinned（state+ref 双写）、ResizeObserver 跟随、上滚解 pin，未 pin 且有新内容时 pill 入口（"New content"/"Question waiting for your reply"，点击回底恢复跟随）。queued_request（Clock）、pending_items（Inbox + 虚线 bubble-pending）、echo（Loader2 sending / Check accepted）三态清晰区分；echo→pending→formal 收敛仍由 turnController convergeEchoes 唯一承担，视图层不重复实现。Composer 意图 chip 紧凑呈现（Append to current turn / New turn · queued / New turn），运行方案只留 `data-slot="preset-entry"` 挂载点（F2-E 接手）。空/加载/错误分别呈现。
- **样式**：`src/styles/index.css` append-only——`.cb-frame` 族（frame/header/label/toggle/error/loading/diagram 与 `pre.cb-frame-source` 元素限定提权）和 `.bubble-pending` 虚线。
- **e2e 兼容**：chat-flow.pw.ts 无需改选择器即通过——保留了 "Reply" 按钮、"answered" 文本、`border-accent/50` 已选高亮类、"Other answer…"/"Comment (optional)…" 占位符等既有钩子。
- **共享树说明**：另一工作流（F2 settings）的进行中修改与本项文件不相交；其个别在编辑文件曾造成 tsc 短暂报错，与本项无关，已由该工作流自行修复，当前 tsc/build 全绿。

### F3-B：对话历史与 Session map（P03，计划 §7）

已完成（2026-10-09）。`pnpm test` 51 文件 / 445 例全绿（本项新增 history 模块 4 文件 36 例：disclosure 11、historyBrowser 7、SessionMap 12、historyEntry 6），`pnpm build`（tsc + vite）通过，真实后端 Playwright e2e（chat-flow 4.3s + codeblocks 1.9s）通过。范围约束遵守：改动集中在自有新目录 `src/features/history/`，共享文件仅 `features/chat/ChatView.tsx`（历史入口与 banner）与 `components/shell/TopBar.tsx`（History 按钮）；未触碰 `api/v2/`、`settings/`、`components/markdown/`；样式零新增（全部复用既有工具类，index.css 无追加）。

- **模块结构（`src/features/history/`）**：`disclosure.ts` 把 DisclosurePage 的 `items` 按四类收窄（owner content / `{kind:"child"}` 导航 hint / `{kind:"relation"}` 关系 / `{kind:"source"}` 证据），不可解析项丢弃不猜测；`parseAnnotation` 区分 thread/note 节点与 source/target/relation 边（边无 `kind` 字段），`splitAnnotationClue` 剥离列表 hint 的 `{status}: ` 前缀；`shortRef`/`sessionTurnId`/`isAnnotationRef` 负责 ref 身份与紧凑显示。
- **分页原语（`usePagedSequence.ts`）**：Hook 持有 continuation token、PageFragmentAssembler 与 abort/序号防护；首页只读一页，"Show more" 续读；load-more 遇 continuation 失效码时从头重读至屏上页数再一次性替换（新旧序列不混合）。测试曾暴露首读排空整个序列的缺陷（"Show more" 形同虚设），已修为由 fresh=一页 / catchUp=N 页的显式分支。
- **Inspector 条目（`entries.tsx`）**：`openHistoryBrowser`（日目录，替换栈）、`pushDayTurns`、`openSessionMap`（替换栈，导出供 F4 Context Session 节复用）、`pushSessionRef`（模块计数器保证同 ref 多次访问各自成层）、`pushSessionQuery`、`openHistoryConversation`（关抽屉 → 切 chat tab → `openSessionTurn`，复用 F3-A 的 Session 只读读取）、`backToLiveTurn`（关抽屉 → clearTurn → syncFromStatus 回 live）。panel↔entries 的循环 import 经 render 闭包延迟求值消解。
- **日目录与日 Turn 列表**：`DayListPanel` 走 `/v2/days?before=&limit=30`，active 徽标 + 每行 Session map 快捷钮；空目录有独立空态。`DayTurnsPanel` 走 `/v2/session/turns?day=`，活动日从 runtime status 单列 "In progress"（点击回 live 轮）与 "Queued"（仅状态事实，无记录可读）两节，与 "Completed" 已提交记录明确分区；归档日标 "Archived · read-only"；活动日/归档日空态文案各自不同。
- **Session map（`SessionMapPanel`）**：`/v2/session/map` 根 hint 排序为 topics → unclassified → history → annotations 四节；topics/unclassified 默认展开，history 收起但常驻挂载（其空态决定整日"无已完成对话"全局空态），annotations 惰性挂载（含已撤回条目）；"事实存在但无 topic" 与"完全无对话"是两种不同呈现。顶部 locate 框对本日 `session:map` 发起 query。全部只读——不伪造主题、不提供编辑入口，整理只通过对话请求 Agent。
- **inspect 详情（`SessionRefPanel`）**：按内容 kind 分发——interpretation 卡（accent 左边条 + "interpretation" 标 + 撤回 strike/徽标 + 证据 ref chip）与不可变事实卡（turn 头/interaction/input/output/action 含折叠 request+result JsonTree/working/resource）视觉明确区分；relation 行、Contents hint、Evidence chip 均可继续下钻；scope query 只在同 ref 内重定位（带 chip + Clear）；turn 页有 "Open conversation"。证据不可用时显示 warning 条而非编造内容。
- **入口（ChatView/TopBar）**：DayEntryList 三处入口（空态动作钮 / 头部 "Earlier days" / 底部 "Browse earlier days"），保留 "Today's conversations" 既有文案与行结构；HistoryBanner 在 `day !== activeDay` 时追加 "archived day — current resources may differ" 来源提示，挂 "Session map" 钮，存在其他 live 轮时返回钮文案为 "Back to the live turn"（默认 "Back to today" 不变，e2e 钩子兼容）；TopBar 新增 History IconButton（断连禁用）。
- **已知延后**：Markdown 链接的来源日传播需改 `src/components/markdown/`（本轮禁区），归 F5 ResourceRouter；Context 页 Session 节的 map 入口归 F4，经已导出的 `openSessionMap` 接入。

## 实施中发现的需求/缺口

> 仍然真实存在的后端缺口按 `visualization/docs/demand/` 规则记录；过时需求单不作为实现依据。

当前 pending 需求（索引与详情见 `docs/demand/README.md`，均为非阻塞）：

- `20260930-catalog-render-pdf-pages-choices.md`：`render_pdf_pages` 的 catalog choices（never/on_no_text/always）与代码可接受值（disabled/on_no_text）不一致（F0/W3 发现，config-coverage §9.1）。
- `20260930-catalog-kimi-search-model-choices.md`：`capabilities.web.search_by_kimi.model` 代码只接受 kimi-k2.5/k2.6 但 catalog 无 choices（F0/W3 发现，config-coverage §9.5）。
- `20260930-home-agent-top-document-503.md`：`home:agent@AGENT` 正文读取 503（`AgentHomeInvariantError`），需后端确认读取语义（F7-B 视觉核对发现，visual-check 问题 1）。

## F4 实施记录

### F4-A：Context Drawer（P04）

已完成（2026-09-30）。`npx vitest run` 56 文件 / 483 例全绿（本项新增 5 文件 38 例），`npx vite build` 通过；`npx tsc --noEmit` 本批文件零错误（唯一报错在并行工作流的 `settings/behavior/bindingsModel.ts`，与本批不相交）。范围约束遵守：改动仅 `src/features/context/`（新建）、`src/components/shell/TopBar.tsx`（启用按钮）、本文档；未触碰 api/v2、settings、chat、markdown，未引入新依赖。

- **架构决策：复用共享 Inspector，不新建 Drawer**。理由：计划 §2 要求"同一时间一个主详情 Drawer"，AppShell 已挂载绑定 `inspectorStore` 的唯一 InspectorHost；Context 的阅读路径（overview → 段正文 → inspect 子节点 → owner 资源）正是受控回退栈，返回/宽视图/复制链接/滚动记忆/焦点管理全部免费获得，与 history 的 `entries.tsx` 模式一致。因此不新增 contextUiStore：抽屉开关即 inspector 栈，刷新标记为面板内本地状态（订阅 connectionStore status）。
- **入口**：TopBar Context 按钮启用（`openContextDrawer(epoch)`，未连接时禁用）。默认当前活动 Turn（`status.runtime.active_turn_id`）；无活动 Turn 时开"暂无运行语境"空态 + 跳历史入口（`openHistoryBrowser`），不展示上轮缓存。
- **Overview 首屏**：只取 API-09 overview；`groupBySlot` 按 Background/Trace/Working 分组（未知 slot 排后、按原值标注）；行内显示段名、shape Badge、形状感知状态行（heap: `7 installed · 3 available`；stack/map: root ref 数；空段标 empty）与字符用量（`usageLine` 只标 chars/图像字节，永不标 token——有断言）。技术 descriptor（owner/shape/order/capabilities/root_refs/protected_refs）收进段详情 Details 折叠区。选中段才请求正文（测试断言 overview 渲染时零 segments/ 请求）。
- **形状驱动视图**（renderer 由 `shape`/`capabilities` 驱动，不靠名称猜；`canInspect`/`canQuery` 只读 capabilities）：
  | shape | 视图 | 实现 |
  | --- | --- | --- |
  | state | 字段/状态正文 + 声明引用列表 | messages + root_refs（可 inspect 才可点） |
  | heap | installed/available 两组 ref 行 + "打开读 owner 当前内容、不改变加载状态"注记 | `partitionHeapRefs`；installed 带 Badge；home/memory ref 跳 owner 阅读，session/turn ref 按 inspect 能力路由，workspace 等静态展示 |
  | stack | 热记录 root refs → live inspect；子节点展开成新栈层，Back 回父 | `ContextInspectPanel` |
  | map | session:map 等 root refs → live inspect + "Browse day history" 次入口 | 同上 |
  | working | messages 摘要 + owner 跳转（workspace→工作区页、jobs/subagent→运行观察页，F5/F6 深化为带参深链） | `WorkingJump` |
- **阅读路由对照（计划 §8 路由表）**：段正文→`context.segment`（messages 分页 + `usePagedSequence`，fetch 包装把 messages 映射为 items 并复用 fragment 装配）；可 Inspect 的 Trace/Session ref→`context.inspect`（原 ref + Turn 绑定，`canQuery` 时才显示 Locate 范围搜索）；Home/Memory→优先用 overview `resolved_references` 已解析 locator，否则 API-18 携带 turn/day 绑定解析，再 `home.content`（view 来自 locator，默认 effective）/`memory.document`，面板顶部固定标注"owner 当前内容，非段内已安装正文"；`resource.unresolved_origin` 如实提示缺原绑定，绝不替代成今天 latest；已归档历史→历史浏览器入口（不依赖 F3-B 的 Session 详情内部）。UI inspect 只读：全部请求为 GET（有断言），无 SELECT/RECLAIM 控件。
- **刷新语义（§3.5/§8）**：无专门 context 失效通道，按计划允许的最简路线——`context.installed` 等 turn 事件已路由到 status 重读，`useTurnActivity(turnId)` 以 status 快照身份变化为"可刷新"信号：标 RefreshNotice、保留已读内容与滚动、不自动重排，显式 Refresh 后 markFresh 重置基线。续页 continuation 失效走 `usePagedSequence` 既有 catch-up（重读接替前保留旧列表）；409 `context.unavailable` 在 fetch 包装层转为序列终态（不重试、隐藏 Show more），已读内容保留并标"last captured view"；活动 Turn 切换/结束后 overview 提供"打开当前语境"或"浏览历史"。
- **测试**（`segments.test.ts` 11、`contextDrawer.test.tsx` 10、`SegmentPanel.test.tsx` 9、`ContextInspectPanel.test.tsx` 5、`OwnerResourcePanel.test.tsx` 3）：三槽分组与段行摘要、选中才读正文、stale/Refresh、Turn 结束 captured 视图、另一 Turn 接管、409 空态、messages 分页 continuation 参数、canonical_json 跨页 fragment 恰好交付一次、loadMore 409 停读不重试、heap 分区与无 SELECT/RECLAIM、stack root ref 路由、Details 收技术字段、working 跳页、inspect 子节点展开/原 ref 绑定/query 能力门控/全 GET 断言、API-18 解析参数、resolved locator 跳过 resolve、unresolved_origin 不发 owner 读。
- **已知边界**：`useTurnActivity` 的 stale 粒度是"turn 相关事件后"而非仅 install 事件（活动 Turn 期间 refresh 提示较常出现，语义诚实且不打断阅读）；Working 跳转为整页切换（F6 运行观察落地后可加 section 参数）；fragment 首/中/末序列用合成短分片验证（§24.2 允许构造符合协议的短分片）。

建议 commit：`feat(visualization): F4-A Context Drawer — inspector-hosted three-slot overview, shape-driven segment views, read-only inspect and owner-resource routing`

### F4-B：Action 渲染器与模型调用 Inspector（P05，计划 §9/§21.3）

已完成（2026-09-30）。`pnpm test` 73 文件 / 640 例全绿（本项新增 8 文件 68 例），`pnpm build`（tsc + vite）通过，真实后端 Playwright e2e 2 例通过（chat-flow 4.8s + codeblocks 1.4s）。范围约束遵守：改动仅 `src/features/trace/`（新建）、`src/features/chat/ChatView.tsx`（ActionGlimpse 接入 + HistoryBanner "Process" 入口）、新建 `docs/design/action-renderers.md` 与本文档；未触碰 api/v2、styles、settings、store，未引入新依赖。

- **架构决策：单一 `features/trace` 模块承载全部过程表面**。ActionGlimpse（对话内联卡）、Action/Process/ModelCall/Job 四个 Inspector 面板共享同一组纯函数：`facts.ts`（事件 payload 收窄 + Turn→Cycle→Phase→Action 过程模型）、`eventWindow.ts`（API-17 定向读取，打开时固定 `through`，按 `next_sequence` 翻页——空过滤页照常前进，首页 gap 记为 truncated）、`registry.ts`（63 个 canonical Action ID → 13 结果族显式映射，无别名）。渲染器只做呈现与导航；事件是过程详情来源，正式状态以 owner 投影为准。
- **ActionGlimpse（§9.1）**：收起行 = Wrench + domain 色动作名 + 正式状态徽标（outcome 优先；live 无 outcome 时按执行态 requested/started→in progress、cancelled/not_executed/unknown 分别呈现）+ 族摘要行（只读 payload 实有字段）；展开 = 族结果视图（live 用 interaction `result` canonical payload，历史无 payload 如实显示）+ "Details" 推入动作详情。写入族固定注明"未记录 before/after，链接为当前内容"（有测试断言零 workspace 请求）。历史轮按"同名第 k 个"序号与事件流对齐（ChatView 预计算 ordinal 表）；live 携带 call_id 时优先精确关联。
- **ActionDetailPanel**：verbose 定向读取整轮 → buildTurnProcess → locateAction（call_id 或同名序号）；位置（cycle/phase）、执行链、failure{reason,stage,feedback}、无 result 时的诚实执行态说明（未执行/取消/未知，不伪造工具结果）、params 折叠、族结果视图、模块域关联的模型调用/搜索链接、Job 链接、原始 payload 折叠、"Turn process" 入口。
- **ModelCallPanel（§9.3）**：按 task_id / call_id / search_id(+step_index) 定向 model 级读取。LLM：合并 started/completed 表头（profile/consumer/target/status/error_type）、按 attempt 分组 provider/model 尝试、provider-neutral 请求视图（消息按真实栈序渲染 role/label/parts，左侧 Background/Trace/Working/TaskPrompt 槽位导航由 provenance message_indices 计算、tools/tool_selection、resolved_references、"非供应商原始 HTTP"注记）、响应（answer_text、tool_calls、usage、仅 reasoning.summary——测试断言不出现 digest）；缺失即"未记录"。JEV/Embedding：尝试序列（attempt/retry/elapsed/usage/input_count/dimensions）+ detail JsonTree + search 关联。Search：步骤按 step_index 排序（input/evaluated/output）、retrieval.model.invoked → llm 任务链接、model.call → 专用调用链接。导出按钮下载"定向读取实际保留记录 + 窗口边界 + truncated 注记"的 JSON，不拼造完整历史。
- **Search 卡片（§9.2）**：source 徽标 + 请求 source 摘要与逐步 criterion（按请求顺序，query 不改写为所有步骤条件）；item 卡 title/ref（点击走 ResourceRouter）+ source_score 与 evaluation.score 分开徽标 + evidence 高亮——后端 matches 为 Unicode 码点偏移，经 `highlight.ts` 码点边界映射后切片（emoji/CJK 有专项断言）；无 matches/basis 正常显示真实片段不补造命中；覆盖注记区分 source 完整性/内容快照/模型输入/页面预览覆盖；continuation 只属于原 Turn，无翻页按钮。
- **JobPanel**：owner 投影（state/kind/pending_inputs/result_links/details exit_code/bytes）+ stdout/stderr 分通道输出（`next_continuation` 是轮询位置而非结束标记，"Show more" 按需续读，running 可显式 Refresh）。
- **ProcessPanel + ChatView 入口**：整轮树（cycle→phase→action 行 + phase 决策任务 + searches + 无域任务），"正式记录以对话与 owner 投影为准"注记；HistoryBanner 新增 "Process" 按钮（`openTurnProcess` 替换栈），动作详情内可再下推整轮视图。
- **覆盖矩阵**：`docs/design/action-renderers.md` 记录全部 63 个 canonical ID 的族归属、摘要字段、展开内容与资源/Job/模型导航，含八条不虚构原则；`registry.test.ts` 把 ID 全集作为快照断言（增删 Action 必须同步注册表/矩阵/测试），当前无任何已知 Action 以通用视图验收。
- **测试**（8 文件 68 例）：`highlight.test.ts` 9（码点映射/emoji/CJK/无效与重叠区间）、`facts.test.ts` 18（事件解析/过程模型分组关联排序/状态归约/序号定位）、`registry.test.ts` 5（63 ID 快照、族断言、未知→generic）、`eventWindow.test.ts` 7（through 固定、next_sequence 翻页、空过滤页前进、gap→truncated、无前进即止）、`actionGlimpse.test.tsx` 8（状态呈现、失败 feedback、无 before/after 伪造、Details 关联）、`modelCallPanel.test.tsx` 7（定向参数断言、request/response 渲染、缺失/截断如实）、`searchResultView.test.tsx` 5（fixture 高亮、无命中片段、双分数、覆盖注记）、`panels.test.tsx` 9（过程树/详情失败与无 result/Job 分页/entries 栈语义）。
- **已知边界**：历史轮 agent.action 投影无 result payload，历史卡展开以事件读取补齐（保留窗口内；截断如实标注）；normal 观察级别下 model 级 request/response 不记录，Inspector 显示"未记录"。

建议 commit：`feat(visualization): F4-B Action renderers & model-call inspector — 63-ID registry, family result views, search card with code-point highlights, directed event reads, process tree and chat glimpse`

### F4-C：审计修复（Context 抽屉与 Action/模型详情只读审计）

已完成（2026-09-30）。`npx vitest run` 77 文件 / 699 例全绿（本项新增/纠偏 8 例），`pnpm build`（tsc + vite build）通过。范围约束遵守：改动 `src/features/trace/`（ModelCallPanel、resultViews、两个测试）、`src/features/context/`（SegmentPanel、activity、OverviewPanel 注释、三个测试）、`src/store/connectionStore.ts` 与 `src/app/connection.ts`（context 代际信号）、`src/app/connection.test.ts`、`docs/design/action-renderers.md` 与本文档；未触碰 api/v2、settings、chat，未引入新依赖。实施期间并行工作流正在改写 `features/home/*`、`chat` 与 `turnStore.OutgoingEcho`（一度阻塞 tsc）：本批只在 `src/app/connection.test.ts` 两处 echo fixture 补 `turnClosed: false` 做机械类型对齐，其余阻塞均由所属工作流自行收敛后复验通过。

- **ModelCallPanel attempt 分组伪影**：对照 `tinysoul/llm/execution/task.py` 的真实 payload——`llm.model.started/completed/failed` 只携带 profile/model_id(+status/error_type)，没有 attempt/provider_id/adapter。改为：无 attempt 字段的 model 生命周期事件进入任务级 "Model lifecycle" 头/尾列表（model_id + 状态徽标 + error_type·provider_error_kind），不再落入误导性的 "Attempt ?" 组；attempt 分组只消费真实携带 attempt 的 `llm.model.request/response` 与 `llm.provider.*`，分组键含 model_id/provider_id（不同 provider 的同名 attempt 号不再误合并），attempt 状态改由 `llm.provider.completed/failed` 供给，`llm.provider.failed` 错误类型读 `provider_error_kind`（原读不存在的 error_type 恒为 null）。`modelCallPanel.test.tsx` fixture 全部对齐真实 payload（去掉虚构的 attempt/provider_id/adapter，request/response 补 profile/provider_model），新增 provider 失败/模型失败分层断言。
- **Context query 控件死接线**：`segments.ts` 的 `canQuery` 此前无消费者——`SegmentPanel` 两处 `pushContextInspect`（stack/map root refs 与 heap 内 session/trace refs）现按段 capabilities 传 `canQuery`，与 `canInspect` 同样能力驱动；declared `query` 的段（Session map、Trace）的 "Locate in this scope" 真实出现，无 query 能力的段不出现（两个新测试覆盖两方向）。
- **四个展示缺口**（`resultViews.tsx`，均按真实 payload 形状解码）：`web.discover_pages` 渲染逐页目录（pages 数组：状态徽标 visited/failed/candidate + 外链 + 失败原因，24 条截断 + 计数，截断预览沿用 see_more_at）；`workspace.analyze` 显示 coverage（complete/files_loaded/source_chars 一行）；`workspace.read` 等 inspect 族显示 requested→actual 真实区间（无界请求的哨兵 end_line 显示为 "end"）；`workspace.trash_list` items（每项同时带 ref+link）渲染为可点原 link + tags 徽标 + trash ref，不再落 JsonTree。`action-renderers.md` 矩阵对应行与测试锚点说明同步更新。
- **stale 粒度**：`useTurnActivity` 原以 status 快照身份变化标 stale（任何 status 重读都触发）。改为 connectionStore 新增轻量 `contextGeneration` 代际信号：`app/connection.ts` 的 routeEvent 只对 `context.installed`/`context.background.changed` 两个 context 安装相关事件 bump（turn.* 等事件不 bump），面板以代际变化标 stale、markFresh 重置基线；closed 判定仍来自 status.active_turn_id。无关 status 刷新不再把已读视图标为过期（drawer/inspect 两测试各加负向断言），安装事件仍安全地标过期，`connection.test.ts` 新增路由断言（install/background 事件 bump、turn.phase 不 bump）。F4-A"已知边界"中记录的粗粒度问题由本项消除。
- **测试**：`modelCallPanel.test.tsx` 8 例（生命周期呈现、无 "Attempt ?"、provider_error_kind、fixture 纠偏）、`SegmentPanel.test.tsx` 11 例（canQuery 两方向）、`actionGlimpse.test.tsx` 12 例（四个展示缺口）、`contextDrawer.test.tsx`/`ContextInspectPanel.test.tsx` stale 语义更新、`connection.test.ts` 21 例（代际路由）。

建议 commit：`fix(visualization): F4-C audit fixes — attempt grouping excludes attempt-less model lifecycle events, provider_error_kind read, canQuery wiring, discover_pages/analyze/read/trash_list renderers, context-generation stale signal`

## F5 实施记录

### F5-A：ResourceRouter 与工作区页（P06，计划 §10/§13/§21.2）

已完成（2026-09-30）。`pnpm test` 73 文件 / 640 例全绿（本项新增 7 文件 76 例），`pnpm build`（tsc + vite）通过，真实后端 Playwright e2e 2 例通过（chat-flow 4.8s + codeblocks 1.4s）。范围约束遵守：改动 `src/features/resources/`（新建）、`src/features/workspace/`（新建）、`src/components/markdown/`（Markdown.tsx 重写 + origin.ts 新建 + codeBlockRegistry.ts 扩展 origin 类型）、`src/components/shell/AppShell.tsx`（workspace→WorkspacePage，home/memory→PendingTargetLanding 占位接线）与本文档；未触碰 api/v2、settings、chat、history、styles，未引入新依赖。并行工作流对 resources/workspace 六文件做过最小类型修复、他人修复了 Markdown.tsx 的 extractCodeChild 派发 bug，均未改变本项设计；本批对 `src/features/trace/actionGlimpse.test.tsx` 有一行类型签名修复（并行 F4-B 工作流引入的 tsc 阻塞，已向其报备）。

- **ResourceRouter（§21.2，`router.ts` + `reference.ts`）**：`reference.ts` 纯函数层负责引用分类（`classifyReference` → workspace/home/memory/session/turn/http/dynamic-memory/unknown，合法协议才判定可路由，`splitFragment` 分离 `#L…` fragment，`parseLineFragment` 解析行定位）；`router.ts` 负责解析与导航——已带正式 locator 的引用直接路由，相对/动态/未解析引用经 API-18 `resources.resolve` 携带 origin（day/turn_id/view）解析（`resolveReference`/`ResolveOutcome` 区分 resolved/unresolved_origin/unsupported/error），`routeTarget` 按 target 分发：workspace→工作区页对应 day/file/fragment（归档日只读）、home/memory→`targetsStore` 挂起目标 + PendingTargetLanding（F5-B 落地页协议本轮定义并占位接线）、session/turn ref→复用 history 条目工厂、http(s)→Tauri shell 走 opener 插件、Browser 用 `window.open`。动态 memory 引用（current/latest/target）只用响应已解析 locator，缺绑定如实提示，绝不默认落成今天。
- **操作三区分**：点击跳转（`openReference`）/ 复制原引用（`copyReference`，复制用户可见原文而非解析后 locator）/ "在对话中引用"（`quoteReference`→`buildQuoteText` 生成可编辑文本草稿填入 Composer，保留来源 day/view/turn 绑定，不自动发送、不附加正文；引用文本的来源描述以被引用 ref 自身的协议分类为准）。
- **Markdown 统一接入**：`Markdown.tsx` 重写为 origin 驱动——`MarkdownOrigin`（codeBlockRegistry.ts）扩展 `ResourceOrigin` 携带 day/turn/view/locator；所有实例（回答、问题说明、资源正文、Search 片段）经同一 `MarkdownRenderContext`（origin.ts）；url 转换与 a/img renderer（`links.tsx`）只对白名单协议生成链接控件（任意冒号文本不识别）；workspace 图片走鉴权 blob client → Object URL，home/memory 无 blob 路由不内嵌、显示引用提示，http(s) 图片正常加载。
- **共享搜索面板接入（§13）**：`SearchPanel.tsx` + `searchModel.ts`（SearchDraft→`buildQueryRequest`/`buildRefineRequest` 有限管道、匹配片段 `highlightSegments`）+ `searchCapabilities.ts`（literal/regex 等能力从 /v2/config/actions 对应 search action 的 schema 读取，仅声明支持时出现，SDK 浏览 context=none）。scope 可为 Workspace/目录/文件；仅活动工作区可搜——归档日点搜索先切回活动日并 toast 说明；结果就地打开不关面板（workspace target 本地解析后 `select(link, fragment)`，其他走 routeTarget）；scope 拒绝/空结果/失败分别如实呈现，不伪造。
- **工作区页（P06）**：左侧 Sidebar（Files/Trash 标签、目录树 `tree.ts`、名称即时筛选、日选择器、拖入上传——后端 blob 写路由真实存在故提供，同名拒绝）+ 右侧 FilePanel。`store.ts` 的 day：null=活动日（可写）、字符串=归档（只读）；manifest → resource 分页读取（`useWorkspaceText`：text/next_continuation 翻页 + fragment 装配，首屏不完整时显式 `full=true` 整读并检查 complete/editable 才启用覆盖保存，被拒 toast"不可编辑"——绝不拿首屏 text 当完整文件提交）；`mutations.ts` 串行写控制器接齐 directory/move/tags/edit/append/trash/restore/upload（活动文件删除=移入回收站；回收站查看/恢复，无永久删除/清空）；外部变化以 record.mtime_ns/size 为基线——无草稿静默重读，有草稿显式"重新载入/继续编辑"选择；blob 经 `blobUrl.ts` 鉴权 fetch（Range）→ Object URL（回收），按 media_type 分发 BlobView/TextFileView，未知类型下载，大媒体未完整 Range 集成就明确提供下载不伪造可播放；归档经 /days 选择、GET 带 day、全页只读。
- **测试**（7 文件 76 例）：`reference.test.ts` 16（协议分类/fragment/动态引用/行定位）、`router.test.tsx` 18（路由矩阵：各协议/day/view/动态绑定/未解析/外链接/三操作）、`links.test.tsx` 7（Markdown 协议链接渲染与点击、图片鉴权与无路由提示）、`Markdown.test.tsx` 11（origin 传播、代码块注册表、白名单外协议不生成链接）、`searchModel.test.ts` 10、`searchCapabilities.test.ts` 4、`workspacePage.test.tsx` 10（分页/fragment 装配、full=true 编辑门控、外部变化两分支、回收站流、归档只读、搜索结果定位）。
- **已知边界**：home/memory 落地页归 F5-B（targetsStore 跳转协议与 PendingTargetLanding 已就位）；e2e 在双工作流并发负载下曾出现一次 chat-flow 失败（视图回到日列表；同代码并行工作流数分钟后复跑即绿，本项干净复跑亦绿——失败路径位于 chat turn 编排而非本项文件，已留待 F3 owner 关注）；Working 节的带参深链归 F6。

建议 commit：`feat(visualization): F5-A ResourceRouter & workspace page — reference routing with quote/copy/open, origin-driven Markdown links, P06 workspace with paged reads, full-read edit gating, serialized mutations and shared search panel`

### F5-B：Home 页与 Memory 页（P07/P08，计划 §11/§12/§13/§14 相关部分）

已完成（2026-09-30）。`pnpm test` 80 文件 / 740 例全绿（本项新增 3 个测试文件 + 扩展 1 个，共 25 例：diffModel 7、homePage 7、memoryPage 9、searchCapabilities +2），`pnpm build`（tsc + vite）通过，真实后端 Playwright e2e 2 例通过（chat-flow 5.3s + codeblocks 1.9s）。范围约束遵守：改动集中在 `src/features/home/`（新建）、`src/features/memory/`（新建）、`src/features/resources/`（小幅扩展，API 未推翻）、`src/components/shell/AppShell.tsx`（home/memory 分支接线）与本文档；未触碰 api/v2、settings、chat、workspace、styles，未引入新依赖。F5-A 的 `PendingTargetLanding` 占位组件随两页落地删除（targetsStore 跳转协议不变，由两页自行消费）。

- **owner 内容读取原语（resources 扩展）**：`useOwnerPage.ts` 在 `usePagedSequence` 语义（首页一页、Show more 续读、continuation 失效 catch-up 重读后一次性替换、canonical_json fragment 装配）之上额外暴露页面级 `metadata`（locator/direct_refs/redirect 链/diff 事实），错误保留原始对象供按 code 分支——Home content/diff、Memory active/document 四处阅读共用同一 Hook。`ChunkedMarkdown.tsx` 把 `{ref,text}` 分块渲染为共享 Markdown（origin 驱动链接/图片路由），`#L…` fragment 定位覆盖行所在块、高亮并 scrollIntoView，打开资源不改变模型侧任何加载状态；`decodeContentChunk` 供普通 page.json envelope（Memory active）在边界处收窄为类型化分块。
- **共享搜索落地（§13/§3.5/§8/§9 相关）**：`searchCapabilities.ts` 新增 `documentQuery` 检测（query 属性 oneOf 含 `document_ref` 变体，由当前 generation 的 tool.schema 声明驱动）；`searchModel.ts` 新增 `buildDocumentQueryRequest`（`query: {document_ref}`，绝不把 link 改写为文本查询）与 `buildBacklinksRequest`；`SearchPanel` 新增可选 `documentAnchor`——owner 声明 document query 时提供"查相关文档"入口（Memory 当前文档），未声明不出现。`ReferencesPanel.tsx`（新建）：direct refs（"It references"）随文档 metadata 到达即列出（零模型调用），backlinks（"Referenced by"）只在用户显式点击后以当前文档为 anchor 发起 `{kind:"backlinks", scope:"all", anchor_ref}` 请求，且仅当 owner 声明 backlinks source 才出现；两个方向共用同一资源预览/路由组件。`ReflectionDialog.tsx`（新建，§14 会话内维护快捷入口）：Home 只带 instructions（无 target_day 控件）；Memory 必须显式目标日，默认建议取 availability（缺 daily 的日优先、绝不默认今天），`next_before` 继续翻更早日期，另可手动选日；"缺 daily 只是线索、已有 daily 仍可再整理"均在 UI 文案表达；共享根队列忙碌时明示排队，成功回执跳运行观察，409 `agent.queue_full` 保稿不丢 instructions。
- **Home 页（§11）**：`store.ts` 绑定 view（默认 effective）+ 选中资源 + 覆盖中央的 diff（关闭后回到原阅读位置）；`catalogModel.ts` 把扁平 catalog 分组为顶层内容/通用 Skill（可展开 SKILL.md 与其余资源，SKILL.md 识别大小写不敏感）/普通资源/domain·action guidance（显式类型徽标，不误称 Background 技能）；目录名称筛选即服务端 `query` 参数（250ms 防抖）。`HomeContentView` 按 view 读取；`resource.invalid`（非 UTF-8）显示引用与实际支持操作（复制/引用/References），不伪装下载地址；`resource.not_found` 与空文档分开呈现；工具栏含复制引用/在对话中引用/References。`HomeChanges` 列 overlay 创建/修改/删除（kind 色调 + baseline_diverged 徽标）；`HomeDiffView` 读 actual→effective unified diff，`diffModel.ts` 行级分类（meta/hunk/context/add/del 无损保留），Unified 模式按类着色，Side-by-side 模式以 `@@ -l +r @@` 真实行号双列对齐、del/add 相邻行配对；`baseline_diverged` 只作事实横幅并引导重读/整理——无 accept/reject、无 merge 编辑器、无按日快照恢复。内容搜索仅 effective：actual 下点击先显式切换并 toast 说明，actual 视图保留目录筛选。
- **Memory 页（§12）**：`store.ts` 分 active/persistent 两节——active 绑定日（null=活动日，`/v2/days` 选择器，日切换只绑定该 Memory.md 的阅读，不解释成知识库时间旅行）；persistent 选中独立，active 日变化不重新解释。`ActiveMemoryView`：metadata `{day, locator}` 显示绑定日；归档日 404（"未归档"）、`resource.unavailable`、空文档（"今日尚无记录"）三种状态分开。`catalogModel.ts` 解码 catalog 项（link/kind/display/status/redirect_to），列表带 redirect 徽标与状态徽标；空知识库提供"开始对话"与"整理记忆"入口，无宣传段落。`MemoryDocumentView`：redirect 经 `resolution_chain.length>1` 表达——原文保留在屏、显式"Open target"入口，绝不暗中用目标正文替换旧文档；404 缺失与空文档分开；工具栏复制/引用/References。搜索面板 scopes 为 all/daily/entity/concept/fact/note，`documentAnchor` 在当前选中持久文档时提供相关文档查询。
- **测试**：`diffModel.test.ts` 7（行分类无损/headers 归 meta/配对与真实行号/新建文件左侧为空/hunk 重置编号）；`homePage.test.tsx` 7（effective/actual 切换带 view 参数重读目录与正文、fragment 块定位、缺失与非文本两态、changes→diff unified/side-by-side/字符摘要/返回后内容选择保留、diverged 横幅且无 accept/reject、actual 下搜索切 effective+toast、整理 Home 无日期控件且 POST 体 `kind:"home"` 无 target_day）；`memoryPage.test.tsx` 9（活动记忆读取与日切换参数、未归档 vs 空、kind 过滤与防抖 query、空知识库入口、redirect 横幅+Open target、缺失 vs 空、References 面板 direct refs 零请求+显式反链请求体断言、整理记忆默认建议缺 daily 日+POST 带 target_day、next_before 翻页）；`searchCapabilities.test.ts` +2（document_ref 变体检出/普通 string query 不检出）。
- **已知边界**：Home 阅读从 Context 进入时的"已加载"来源提示依赖 Context 侧导航契约，未在本页单独实现（owner 阅读路径已就位）；Memory active 的 backlinks 未开放（anchor 为动态 `memory:current`，References 面板仅服务持久文档）；搜索面板对归档工作区/actual Home 的入口切换沿用 F5-A 既有约定，本轮两页未新增归档搜索入口（与计划 §13 一致）。

建议 commit：`feat(visualization): F5-B Home & Memory pages — owner paged reading with chunked markdown, home catalog/changes/diff views, memory active/knowledge views with redirect and backlinks, shared references panel and reflection dialog`

### F5-A 审计修复（对话页与历史视图六项）

已完成（2026-09-30）。只读审计发现的六项偏差逐项修复。本批全部改动完成后首次完整门禁 `pnpm test` 80 文件 / 740 例全绿、`npx tsc --noEmit` 与 `pnpm build`（tsc + vite）全绿、真实后端 Playwright e2e（chat-flow 5.3s）通过；随后并行代码块工作流开始改写 `src/components/markdown/blocks/*`（15:54 起，新增 zoom/export 控件），其进行中的 `test/blocks/codeblocks.test.tsx` 2 例（BlockFrame toggle 首匹配变成 zoom "−"、TikZBlock iframe 惰性创建）当前失败，与本批文件无 import 关系，待该工作流自行收尾。范围约束遵守：改动集中在 `src/features/chat/`、`src/store/turnStore.ts`（OutgoingEcho 增 `turnClosed` 必填字段）、`src/components/markdown/origin.ts`（新增 `conversationOrigin`）与本文档；`src/app/connection.test.ts` 仅两处 echo fixture 机械补字段；未触碰 api/v2、settings、workspace、home、styles，未引入新依赖。

- **快照等待即刻可见（§6.2）**：原 WaitingQuestionCard/BudgetCard 位于 `loading && items.length===0` 的 Loading 占位分支内——快照已报告 waiting 而 interactions 未读完时卡片不可达。ChatView 内容列重排：等待区四件（WaitingQuestionCard/QueuedRequestRow/BudgetCard/TurnResultRow）移出条件分支、恒定挂载于列尾（树位置稳定，加载→读完无重挂载，未提交草稿不丢），Loading 占位仅在无项时作为首行显示。`useLiveWaitingQuestion` 以快照为唯一待答权威：`state==="waiting"` 且同 question_id 无正式 user.reply / answered 标记即渲染唯一可提交卡（`item=null`）；正式 `agent.question` 到达后 QuestionRow 对同 id 返回 null，收敛为一张卡（不会两个可提交表单）；正式回复到达后卡片转只读。新测试：快照 waiting + interactions 挂起 → 卡片可见可提交（恰 1 个 `[data-question-form="active"]` / 1 个 radio），预算卡同见；放行 drain（未答 question）后仍恰 1 卡；含 answered+reply 的页刷新后 0 radio + "answered"。
- **Composer 显式意图菜单（§5.1）**：活动 Turn 期间意图 chip 变为紧凑菜单（非全宽面板）：默认 "Append to current turn"，可显式改选 "Queue as next turn"；`applyIntentChoice` 仅在派生意图为 append 时让选择生效，绝不复活已关闭/不可用目标。意图在提交瞬间固定（`sendUserMessage` 第三参 `intent`），飞行中的状态变化不改道；发送成功后选择复位。菜单 Escape/外点关闭。新测试：改选后发送走 `POST /v2/turns` 而非 `/input`、成功后 chip 复位；提交后 Turn 转 idle 仍只发 `/v2/turns`（pin 生效）。
- **追加失败且 Turn 已关闭 → 显式"作为下一轮发送"（§5.1）**：`OutgoingEcho.turnClosed`（必填）仅对 append 且 409 `turn.command_rejected` / 404 `turn.not_found` 置真（文案 "This turn is closed and can no longer accept input."）；EchoRow 在 turnClosed 时提供 "Send as next turn"——只在用户明确点击时 `sendEchoAsNewTurn`：移除旧 echo、以全新 command_id 把原文发为新 Turn（不自动、不复用旧 input_id）。新测试：409 追加失败置 turnClosed=true；点击产生 `POST /v2/turns` 且 command_id 不同于旧 echo、另一可重试 echo 不受影响；容量/网络失败 turnClosed=false 且无该按钮。
- **队列项取消（§5.1）**：queued_request 摘要行在快照 state 为 queued/preparing 且未 cancel_requested 时提供 "Cancel queued turn"，`cancelQueuedTurn` 以该行自身 Turn id 发 `POST /v2/turns/{id}/cancel`——与 `cancelActiveTurn`（status 当前运行轮）明确区分；409/404 视为状态已迁移，刷新不报错。新测试：行内取消 POST 到排队轮自身；state=running 时按钮不出现。
- **历史 origin（§7）**：live 与 history 的 Markdown origin 构造收口到 `origin.ts` 的 `conversationOrigin({view, day, turnId, activeDay})`：仅当内容日 ≠ 活动日（归档日）时绑定 `origin.day/turnId`，归档回答的 `workspace:`/相对引用按历史来源解析（新测试：归档日轮中点击 workspace 链接打开 `day:"2026-09-28"` 的只读工作区）；同日内容不绑定（"current" 语义保留、今日工作区不被路由成归档；新测试：活动日历史轮链接仍以 `day:null` 打开）。
- **e2e 竞态修复（F5-A 记录的 chat-flow 失败根因）**：前端此前只能经 `syncFromStatus` 看到 `active_turn_id` 才打开会话视图；脚本模型后端的 Turn 在"POST 回执到达"与"首次状态读取"之间整体开始并结束，状态里 `active_turn_id` 已是 null → 视图留在日列表、answer-card 永不出现。修复：新轮回执 accepted 后若当前无展示轮（`turn.turnId===null`）立即 `openAcceptedTurn` 打开该轮（sendNewTurn/resendNewTurn/sendEchoAsNewTurn 共用）；明确不做 `syncFromStatus` 的 echo 兜底打开——那会偷走用户显式 "Back to today" 的视图。回归测试：status 恒 idle + 回执即 finished 的场景下 `sendUserMessage` 后 `turnId==="contract-turn"` 且答案在屏；真实后端 e2e chat-flow 通过。

建议 commit：`fix(visualization): F5-A audit fixes — snapshot waiting card before interaction drain, composer intent menu with pinned submit intent, closed-turn send-as-new-turn, queued-row cancel, historical markdown origin, accepted-receipt turn opening for the fast-finish race`

## F6 实施记录

### F6-A：运行观察页与代码块收尾（P09，计划 §14/§21.1）

已完成（2026-09-30）。`pnpm test` 86 文件 / 781 例全绿（本项新增 6 个测试文件 31 例 + 重写 `test/blocks/codeblocks.test.tsx` 17 例），`pnpm build`（tsc + vite）通过，真实后端 Playwright e2e 2 例通过（chat-flow 5.5s + codeblocks 1.3s，4 个用例块真实渲染、64 请求全同源）。范围约束遵守：改动 `src/features/runtime/`（新建）、`src/components/markdown/blocks/`（BlockFrame/MermaidBlock/TikZBlock 重写 + downloadSvg/tikzSlots 新建）、`src/styles/index.css`（zoom 控件样式，append）、`src/components/shell/AppShell.tsx`（runtime 分支接线）、`test/blocks/codeblocks.test.tsx`、`docs/design/codeblocks.md` 与本文档；未触碰 api/v2、chat、settings、workspace、home/memory，未引入新依赖。对既有模块的复用仅限读取：`trace/panelShared`（useAsyncRead）、`trace/eventWindow`（readEventWindow）、`trace/entries`（openTurnProcess/pushJobDetail）、`history/usePagedSequence`、`resources/router`（openReference）、`chat/turnController`（cancelQueuedTurn）、`chat/composerDraft`、`settings/uiStore`。

- **运行观察页（§14，`src/features/runtime/`）**：RuntimePage = 顶部 OverviewStrip（Agent ready/启动中、活动日、当前 Turn 短 id + kind/state 徽标 + 真实 wait_reason、队列计数；长身份不常驻、一键复制）+ Execution/Jobs/ACP/MCP/Environment 五分页；tab 切换即卸载（离开即停止该页全部读取，重开重新读）。`useActiveTurnSnapshot` 由 overview 与 Execution 共享：以 status 对象身份为刷新信号（app/connection 在 turn 事件后重读 status），同轮刷新保留旧快照不闪烁。
- **Execution**：当前 Turn 卡（state/kind/cancel_requested 徽标、waiting 时真实原因 + 问题文本/预算轮次 + "Open in conversation"）；finished 时 result 分区——execution failure 默认展开、output/completion 折叠、finish_failures/cleanup 单独"事后诊断"区（执行失败与收尾诊断不混为一谈）；队列卡逐行短 id + Cancel——每行显式命名自己的 Turn id（`cancelQueuedTurn`），绝不波及运行中的 Turn。
- **Jobs**：绑定打开瞬间的活动 Turn（later Turn 不继承本视图）；列表 2.5s 定点轮询（非整页刷新）；选中才读 detail/output。`JobOutputReader`（jobOutput.ts）落实 API-14 语义：continuation 是轮询位置而非结束标记——运行中空页保留 token 下轮再读；truncated 页在本 tick 内续读（每 tick 上限 8 页）；truncated 且不前进 = stalled，停轮询并给出 result_locators 实际产物入口；终态 drain 到无进展才 exhausted；channel 分块拼接不编造跨流顺序。Stop 按钮以 POST 返回的正式快照为准（不乐观更新），停 Job ≠ 取消 Turn；pending_inputs 给"回对话处理"入口。Turn 回收（列表由非空变空或 active_turn_id 迁移）→ 冻结最后已读 + 产物链接 + "Turn process" 入口，不保留可操作的假历史。
- **ACP**：targets（配置事实）与 connections（generation 运行事实）分区；空态诚实（无配置给设置入口、无连接说明"阅读本页不建连"）；连接行显示 ready/busy/unavailable + 跨 Turn 空闲复用标注 + cwd 链接 + 关联 Job（同属当前 Turn → 页内 openJob，否则 pushJobDetail 到 Inspector）；"Delegate in conversation" 只填 Composer 草稿（不发送、不建连）。
- **MCP**：configured/enabled、connected、discovered、callable 四事实分列（永不合并成红绿灯）；打开页/名称过滤只发无副作用 GET（过滤纯客户端）；显式"Refresh directory"按钮逐 server 绑定（仅 POST 该 server，禁用态置灰并说明）；失败保留既有目录并标注。工具目录分页读取，详情懒读 definition + 一次性 `config.get("active")` 推导配置选择（tools map 原子键覆盖 ?? tools_default，server 开关优先），"Edit configuration"跳设置 mcp 页对应 tools 路径，"Use in conversation" 填草稿不调用。
- **Environment**：API-01 sources 表（failed/error_type → "仅监听受影响，正式 Workspace 操作可用"提示）+ `readEventWindow`（verbose、through 固定打开时 head、gap → TruncationNotice 如实截断）客户端按 source/topic/关联 Turn 过滤（选项来自已读事件，turn 短显全题）；只显示实际记录的事件，不推测未记录阶段。
- **代码块收尾（§21.1，`src/components/markdown/blocks/`）**：BlockFrame 新增缩放控件（0.5×–3× CSS zoom 包裹层）、"导出 SVG"（`downloadSvg.ts`：Blob→objectURL→anchor→延时回收）、失败"重试"与"排队等待编译…"态；MermaidBlock 缓存键升级为渲染器版本 + theme + source（包升级旧条目自然失效），模块加载先于缓存检查（命中后零成本），失败重试以 attempt 态驱动；`tikzSlots.ts` 编译槽位上限 2——可见块取槽后才挂载 iframe，槽满排队（取消等待者被跳过、槽位转让不计数），编译收敛或块卸载即释放槽位并卸载 iframe 终止 Worker，失败提供用户触发重试；embed 拒绝（`</script` 序列）不进队列、直接错误态。
- **测试**：`jobOutput.test.ts` 7（空页留 token/终态 drain/stalled/每 tick 上限/错误分层/channel 拼接/初态）；`models.test.ts` 10（acp/mcp 收窄、tools 原子键选择、environment 过滤）；`jobsTab.test.tsx` 3（选中才读 detail/output、运行中持续轮询、stop 以正式快照为准且终态 drain 后停、回收冻结）；`mcpTab.test.tsx` 4（打开零 POST/四事实/刷新只绑该 server/工具懒读 + 配置选择）；`acpTab.test.tsx` 3（空态诚实零 POST/目标与连接分区/委派草稿）；`executionTab.test.tsx` 4（队列取消只命中该 Turn/真实等待原因/失败与事后诊断分区/无活动轮空态保队列）；`test/blocks/codeblocks.test.tsx` 17（BlockFrame 缩放/导出/重试/排队、downloadSvg、tikzSlots 上限与让位、TikZBlock 惰性/并发/卸载让位、MermaidBlock 缓存）。
- **已知边界**：Environment 事件流为打开时的一次性定向窗口（手动 Re-read 更新），不做常驻跟随；Mermaid 重试为整图重渲染，导出文件名固定 `diagram.svg`；TikZ 未实现跨块共享运行时（并发上限已就位）；Working 节带参深链与 §14 之外的运行控制项归后续阶段。

建议 commit：`feat(visualization): F6-A runtime observation page & codeblock finishers — P09 five tabs with overview strip, job output polling/drain/stop semantics, MCP four-fact directory with per-server refresh, ACP honest states, environment window, mermaid zoom/export/version-aware cache, tikz compile slots (max 2) with queue/release/retry`

## F7 实施记录

### F7-A：文档收口、验收映射、demand 整理与死代码清理

已完成（2026-09-30）。`pnpm test` 84 文件 / 773 例全绿，`pnpm build`（tsc + vite）通过。范围约束遵守：新增/整理的全部为 `visualization/docs/` 文档；`src/` 改动仅限死代码删除与陈旧注释修正（无业务行为变化）；未运行 git；未触碰 `docs/analysis/` 权威计划（其复选框由维护者更新）。

- **交接文档 `docs/handoff.md`（新建）**：按权威计划 §25 覆盖——文档地图（区分当前有效文档与 v1 历史文档）、九个页面地图与用户路径（含实际操作示例）、状态与接口所有权（connectionStore/turnStore/turnController/configDraft/inspectorStore/targetsStore 及各 feature store，owner 投影为正式来源、事件只做失效）、设置保存与方案语义（ConfigDraft 原子模型、apply/reload 结果语义、preset 捕获/应用与 §15 草稿确认流）、Context 与资源的差别（已安装语境 vs owner 当前内容）、CodeBlockRegistry 注册方法与新增 renderer 步骤、ResourceRouter 三操作、实际运行/测试命令（含 Playwright e2e 与 TINYSOUL_PYTHON）、已知边界与遗留 13 项。
- **验收映射 `docs/acceptance-map.md`（新建）**：§24.1 三十项逐项映射到实现文件/测试文件/e2e 场景并标注状态——28 项已覆盖（含 F7-B 视觉核对落地后的 29/30），2 项部分覆盖（第 9 项真实通道切换的后端效果仅有代码证据、第 14 项缺 document_fields 编辑面）；缺口汇总 G1–G6（G1 document_fields 编辑、G2 Tauri webview 未实测、G3 方案通道切换无 e2e、G4 F7-B 九项视觉观察问题、G5/G6 为设计内呈现边界）。
- **demand 目录整理**：通读 `docs/demand/`——v1 旧需求单 5 份已全部在 `archived/`（2 份 done、3 份 superseded 均带归档结论），无仍真实存在的旧缺口；新建 3 份当前语义需求单（两份 catalog choices 对齐——W3 记录的后端不一致转正式需求、一份 F7-B 发现的 `home:agent@AGENT` 503 读取语义确认）；新建 `README.md` 索引（pending 表 + archived 表）。旧需求编号不作为新实现依据。
- **死代码/占位扫描与清理**（全部经 tsc + vitest 验证无引用）：
  - 删除 `src/components/shell/PlaceholderPage.tsx` 及 AppShell 兜底分支（AppTab 封闭联合六值全部有真实页面，分支不可达）；所有 tab 均渲染真实页面。
  - 删除 v1 类型簇 `src/types/{maintenance,workspace,configuration,events,runtime,common}.ts`（`src/types/` 桶仅 AppTab 有消费者；`types/index.ts` 收窄为只导出 `ui`）。
  - 删除无消费者 hooks `src/hooks/{useNow,useOverflowing,useTruncated,useThrottledValue}.ts`（+ 后者自测）与 `src/components/ui/Crossfade.tsx`（+ 自测）——均为 v1 LiveStatus 遗留。
  - 删除 `SettingsPageDef.placeholder` 字段（声明 + 24 处 `placeholder: false` 赋值，无任何读取方）。
  - 陈旧注释/文案修正：`src/api/v2/errors.ts`（删掉对已删除 v1 transport 的引用）、`src/features/resources/targetsStore.ts`（F5-B 已落地）、`SettingsPlaceholderPage`（保留为未注册页防御性兜底，文案与测试同步更新——不再称 "later F2 milestone"）。
  - 全仓扫描确认：无 TODO/FIXME/XXX/HACK、无 "under construction" 残留（仅保留组件内防御文案）、无 monitor/maintenance 旧命名残留（`appStore` 的 v1 "monitor"→"runtime" 持久化迁移为有意保留）。
- **v1 设计文档过期标注**：`docs/design/{index,chat,connection,workspace,settings}.md` 顶部加过期提示并指向 handoff.md（内容不重写，留作历史参考）；`visual-system.md` 经核对仍有效。
- **一致性修正**：阶段表 F1–F6 翻 done（全部子项完成、门禁绿）；F1-C 的 PlaceholderPage 早期声称加注更新；「实施中发现的需求/缺口」小节由（暂无）更新为 3 项 pending 索引。
- **与 F7-B 的并行说明**：本项与 F7-B（视觉核对）并行执行；F7-B 产物（`docs/review/`、`test/e2e/visual-review.pw.ts`）已落地，其 9 项观察问题如实汇入 handoff.md §9 与 acceptance-map.md G4，其中 `home:agent@AGENT` 503 一项转为后端需求单。

建议 commit：`docs(visualization): F7-A closeout — handoff & acceptance-map docs, demand reorganization with three pending notes, dead-code sweep (v1 types/placeholder/unused hooks) and progress-doc consistency fixes`

### F7-B：代表性页面视觉核对（§24.1 末项）

已完成（2026-09-30）。真实后端 harness（`test/e2e/backend_server.py` + 既有 `backend.global.ts` 生命周期）+ Playwright 截取 23 张语义化截图，逐张人工核对并记录。范围约束遵守：未改 `src/` 业务代码；新增 `test/e2e/visual-review.pw.ts` 与独立入口 `test/e2e/visual-review.config.ts`（端口 5198，`testMatch` 仅本 spec），既有 `playwright.config.ts` 仅加一行 `testIgnore` 把本 spec 排除在 chat-flow/codeblocks 门禁之外；文档产物在 `docs/review/`。

- **产物**：`docs/review/screenshots/`（23 张 PNG：对话空态/回答/question 卡、Context overview+段详情、暗主题会话与日列表、历史日目录+Session map、设置概览/LLM Models/Actions/Run plans、Home 目录+正文+读取失败态、Memory 活动+Knowledge、工作区、运行观察 Execution/Jobs/MCP、800px 窄窗口对话+设置）；`docs/review/visual-check.md`（每图一段：首屏主次、字号/密度、等待与空态、明暗主题、与 Luminous tokens 的一致性 + 问题清单 + 总体结论）。
- **运行与防空白**：`TINYSOUL_PYTHON=… pnpm exec playwright test -c test/e2e/visual-review.config.ts` 1 例通过（~30s）；spec 内每张断言 >15KB，运行后以 Pillow 抽样像素（每 37px）测灰度标准差，23 张 std ∈ [8.4, 33.5]，无空白截图；全程零 pageerror。
- **核对结论**：tokens 消费一致（三层底/细边线/靛蓝主动作/领域色仅表来源/状态色仅表运行结果），明暗双主题成立，空态与等待态普遍诚实。
- **问题清单摘要**（详见 visual-check.md，本轮不修）：①中——Home effective 目录首项 `home:agent@AGENT` 正文读取 503（`AgentHomeInvariantError`，curl 直连复现，其余 top content 均 200，目录仍把它呈现为普通可选项，需后端跟进）；②–⑨低——LLM Models 页「Capabilities」标题连续重名、Session map 未归类 Turn 双 chevron 并列与摘要无分隔连排、只读历史下 Composer 禁用语义仅靠 banner、活动 Memory 空白无显式空态、连接瞬间 TopBar「reconnecting…」与状态栏并存、Home 正文 `session:map` 引用后异常空隙、亮主题 answer-card 凹版角标对比极弱（观察）。

建议 commit：`test(visualization): F7-B visual review — real-backend screenshot tour (23 pages, both themes, narrow window) with blank-capture guards, visual-check record and issue list under docs/review/`

### F7-C：视觉核对 7 项低严重度问题修复（visual-check.md 问题 2–8）

已完成（2026-09-30）。对 F7-B 记录的 9 项观察问题中的 7 项低严重度前端问题（问题 2–8）做小范围修复；问题 1（`home:agent@AGENT` 503）属后端、已转需求单 `docs/demand/20260930-home-agent-top-document-503.md`，问题 9（凹版角标对比弱）为风格化取舍、保留观察。`pnpm test` 84 文件 / 778 例全绿（本项新增/修改测试 5 处），`pnpm build`（tsc + vite）通过，视觉核对 spec 重跑 1 例通过（23 张截图重截，六处修复点目检确认，Pillow 每 37px 抽样灰度 std ∈ [8.4, 33.6] 无空白）。范围约束遵守：改动仅 `visualization/` 内 src 与测试、视觉核对 spec 产物与文档；未触碰后端。

- **问题 2（LLM Models「Capabilities」重名）**：`src/features/settings/models/LlmModelsPage.tsx` 字段行标题由读 field meta（与区段标题同为 "Capabilities"）改为硬编码 "Feature capabilities"；区段标题与 meta description 保留。测试：`test/settings/models/pages.test.tsx` 断言 "Feature capabilities" 存在且全文精确 "Capabilities" 的 div 仅区段标题 1 个。
- **问题 3（Session map 双 chevron）**：`src/features/history/panelShared.tsx` 未归类 Turn 卡外「Inspect the recorded facts」下钻钮图标由 ChevronRight 改为 PanelRightOpen（面板语义），与卡内表「跳转对话」的 chevron 区分。
- **问题 4（Session map 摘要连排）**：根因是后端 `_turn_hint` 以 " / " 连接 inputs 且回复文本内含换行（label+description+comment），HTML 折叠空白后连排。`src/features/history/disclosure.ts` 新增 `flattenClue`（按 `\n` 与 " / " 拆分、去空、以「 · 」连接），`panelShared.tsx` HintRow clue 渲染改调之。测试：`test/history/SessionMap.test.tsx` 新增用例覆盖拍平分隔与面板图标（同时断言无 chevron 图标）。
- **问题 5（只读历史 Composer 看不出禁用）**：`src/features/chat/Composer.tsx` 读 `useTurnStore` 的 `historyView` 为 readOnly——`canSend` 加 `!readOnly`，textarea 禁用，placeholder/hint 改为明示文案（"Read-only history — replies and edits are disabled" / "Back to today to send a message"），composer-box 灰化（opacity-60、无 accent 焦点环），意图 chip 换为静态「Read-only」灰 chip，方案入口（PresetEntry）与停止钮不渲染（发送钮渲染但禁用）。测试：`test/chat/ChatView.test.tsx` 新增 describe 覆盖禁用态五断言。
- **问题 6（活动 Memory 空态缺失）**：根因是后端 `content_units` 对空文档也返回一个空文本 chunk，原 `items.length` 判定使空态永不触发。`src/features/memory/ActiveMemoryView.tsx` 与 `MemoryDocumentView.tsx`（同一协议形状、同一根因一并修复）改为 `hasContent`（存在非空文本 chunk）判定空态/错误态/footer，空文档呈现既有「Nothing recorded yet」空态。测试：`test/memory/memoryPage.test.tsx` 两处空态用例 mock 对齐真实后端形状（单空文本 chunk）。
- **问题 7（TopBar 窗口期误显 reconnecting）**：`src/components/shell/TopBar.tsx` ReconnectIndicator——phase=connected 且事件流 `reconnecting` 才显「reconnecting…」；首次接入窗口期（offline/connecting）显「connecting…」。测试：`test/context/contextDrawer.test.tsx` TopBar 用例补三阶段断言。
- **问题 8（`session:map` 引用后宽空白）**：`src/features/resources/links.tsx` ReferenceActions——隐藏操作条原以 opacity-0 恒占位约 38px，改为 `max-w-0 overflow-hidden` 零宽、`group-hover/ref` 与 `focus-within` 时展开（`max-w-10`），保留原 hover/focus 交互；接受悬停展开时后文右移约 38px 的布局让步。测试：`test/resources/links.test.tsx` 断言容器类名。
- **文档同步**：`docs/review/visual-check.md` 逐图记录（01/09/11/14b/15/21）以删除线保留原问题描述并追加「已修复」标注，问题清单整节改为「问题清单与修复状态」（含状态列与修复位置），截图清单表更新为重跑后的尺寸/KB/std 复测值（注明 runId 内容不可与首轮逐位比较），总体结论同步；`docs/handoff.md` §9 第 12 项与 `docs/acceptance-map.md` G4 同步改写。

建议 commit：`fix(visualization): F7-C visual-check follow-ups — distinct Feature capabilities label, session-map clue flattening & panel-icon inspect affordance, read-only composer degradation in history, empty-memory explicit state, honest connecting vs reconnecting indicator, zero-width hover reference actions`
