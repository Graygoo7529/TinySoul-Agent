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
| F1 数据与壳 | in_progress | A/B/C 完成；D 真实 Endpoint 验收待做 |
| F2 设置与方案 | pending | |
| F3 对话与历史 | pending | |
| F4 Context/Action/模型 | pending | |
| F5 资源与链接 | pending | |
| F6 运行与代码块 | pending | |
| F7 收口 | pending | |

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

已完成主体，测试补齐中。架构切换要点：

- 旧 v1 世界已删除：`src/api/{runtime,history,maintenance,events,tinysoul,exportTrace,connection,transport,configuration,workspace}.ts`、`src/derive/`、`src/components/{chat,monitor,trace,workspace}/`、`src/features/settings/`、`src/store/{configStore,eventRetention}.ts`、`src/hooks/{useBackend,useWorkspace}.ts`、`shell/{MaintenanceDialog,BackgroundDrawer,DisconnectedScreen}.tsx`。旧实现以 git 历史为参考材料，F2/F5 在 v2 上重建（计划 §22.1 的"保留"指复用对象编辑/布局设计而非保留 v1 耦合文件）。
- 新增 `src/app/connection.ts`（handshake → 快照 → WS 订阅全生命周期：epoch guard 防旧连接覆盖、有界退避重连、gap 后 owner 重读 resync、generation/instance 变化处理、ready=false 轮询、显式 restart）与 `src/app/discovery.ts`（Browser localStorage 手动目标 + v1 迁移；Tauri lease 只提供地址+token+身份，协议由 handshake 裁定；lib.rs 无需改动——后端 lease 格式未变）。
- 状态三分：`connectionStore`（连接/status 快照/事件 cursor）、`turnStore`（活动 Turn 投影：正式 interactions + pending_items + 本地 echo，按 command_id/input_id/question_id 身份收敛）、`appStore`（仅本地偏好+toast）；事件只做失效触发，无事件重放权威。
- 壳：NavRail 新导航（Chat/Workspace/Home/Memory/Runtime + 设置），ConnectScreen（地址+token 手动表单、Tauri 本机发现按钮）、PlaceholderPage（未迁移页的诚实空态）。
- 最小对话流 `src/features/chat/`：ChatView（owner 投影渲染、当日 Session 列表入口）、Composer（明确意图：新一轮/补充本轮/排队）、QuestionCard（快照恢复即刻可见、choice+comment/Other、预算卡 grant）、turnController（发送收敛、Session 接替有界重试、容量拒绝保稿）。

### F1-D：最小真实交互流程验收

待做：真实 Endpoint + 受控模型的端到端验证（提交 Turn→恢复问题→回复→完成→Session 恢复）。

## 实施中发现的需求/缺口

> 仍然真实存在的后端缺口按 `visualization/docs/demand/` 规则记录；过时需求单不作为实现依据。

（暂无）
