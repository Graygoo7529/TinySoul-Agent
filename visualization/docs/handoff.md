# Visualization 前端交接文档（v2）

> 建立：2026-09-30（F7-A）。面向下一个实施者：本文描述当前前端是什么、怎么跑、各部分归谁管、哪些坑已经知道。不需要重读历史讨论；背景与逐阶段实施细节见
> `docs/plans/20260928-frontend-reimplementation-progress.md`（进度记录）与根仓库
> `docs/analysis/20260928-visualization-frontend-implementation-plan.md`（权威计划，章节编号与进度记录一致）。
> 验收逐项映射见 `docs/acceptance-map.md`。

## 0. 文档地图：哪些可信，哪些是历史

当前有效的文档：

| 文档 | 内容 |
| --- | --- |
| `docs/handoff.md`（本文） | 页面地图、状态所有权、运行命令、已知边界。 |
| `docs/acceptance-map.md` | 权威计划 §24.1 三十项验收 → 实现/测试/e2e 证据逐项映射。 |
| `docs/design/config-coverage.md`（W3） | 配置覆盖清单：每个配置键归哪个设置页、方案捕获范围、与后端不一致记录（§9）。 |
| `docs/design/action-renderers.md`（F4-B） | 63 个 canonical Action ID 的展示矩阵与八条不虚构原则。 |
| `docs/design/codeblocks.md`（F0/W2 + F6-A） | Mermaid/TikZJax 渲染器技术结论与已知限制。 |
| `docs/design/visual-system.md` | Luminous 视觉 token 系统，仍然有效（F0 已核对延续）。 |
| `docs/plans/20260928-frontend-reimplementation-progress.md` | F0–F7 逐阶段实施记录（改动文件、测试数、决策理由）。 |
| `docs/review/`（F7-B） | 代表性页面真实后端视觉核对记录与截图。 |

以下 `docs/design/` 文档描述的是 **v1 前端**（F1-C 已删除旧实现），只作历史参考，不作为当前实现依据：`index.md`、`chat.md`、`connection.md`、`workspace.md`、`settings.md`。各文件顶部已加过期提示。

## 1. 应用骨架

- 入口 `src/main.tsx` → `src/App.tsx` → `src/components/shell/AppShell.tsx`。壳 = 左侧 NavRail + 主列（TopBar / 当前 tab / StatusBar）+ 共享 Inspector 抽屉（`InspectorHost`）+ Toasts。
- 未连接时除设置 tab 外全部显示 `ConnectScreen`（`src/components/shell/ConnectScreen.tsx`）：手动填 `IP:Port` + token；Tauri 壳下另有本机发现按钮（`src/app/discovery.ts`：Browser 走 localStorage 手动目标，Tauri 读 lease 提供的地址+token+身份，协议版本由握手裁定）。
- NavRail 六个 tab：chat / workspace / home / memory / runtime / settings。AppTab 是封闭联合类型（`src/types/ui.ts`），每个 tab 都渲染真实页面，没有占位页。
- TopBar 三个常驻入口：History（历史浏览器）、Context（Context 抽屉）、Restart backend（显式重启，确认弹窗）。
- 主题：亮/暗切换在 NavRail 底部（`appStore.theme`）。

## 2. 页面地图与用户路径

### 2.1 对话（chat，`src/features/chat/`）

- `ChatView.tsx`：主视图。顶部 "Today's conversations"（当日已完成轮列表 + "Earlier days" 入口），内容列 = 用户气泡 + 回答卡（`.answer-card`，fresh 输出走打字机 + settle wipe；恢复内容即时静态渲染）。底部 pinned 跟随，上滚解 pin 后新内容出现 pill 入口。
- `Composer.tsx`：输入框。意图 chip 三态——无活动 Turn 时 "New turn"；活动 Turn 期间默认 "Append to current turn"，可显式改选 "Queue as next turn"；意图在提交瞬间固定，发送成功后复位。排队行（queued_request）有行内 "Cancel queued turn"。
- 提问卡：`QuestionCard.tsx` + `QuestionForm.tsx`（active/compose/readonly/expired 四模式）。快照 waiting 是唯一待答权威——interactions 未读完时卡片已经可提交；正式 `agent.question` 到达后收敛为一张卡。预算卡（grant）独立。append 失败且 Turn 已关闭时 echo 卡给显式 "Send as next turn"（不自动重发）。
- `PresetEntry.tsx`：Composer 上的运行方案快捷入口（`data-slot="preset-entry"`），收起态显示当前匹配方案名或 "Custom"。
- 典型路径：连接 → 发消息 → （可选）答问题卡 → 看回答 → 点 ActionGlimpse 行看动作结果 → "Details" 进 Inspector 看动作详情/模型调用/整轮过程。

### 2.2 历史与 Session（`src/features/history/`，P03）

- 入口三处：TopBar History 钮、ChatView 空态/头部/底部的 "Earlier days"、"Today's conversations" 列表行。
- Inspector 栈：`DayListPanel`（`/v2/days` 日目录）→ `DayTurnsPanel`（某日 Turn 列表：活动日分 "In progress"/"Queued"/"Completed"，归档日标 "Archived · read-only"）→ `openHistoryConversation` 切回 chat tab 打开只读历史轮（HistoryBanner 标来源日，"Process" 钮开整轮过程树，"Back to the live turn"/"Back to today" 返回）。
- `SessionMapPanel`：当日 Session map（topics → unclassified → history → annotations 四节，全部只读），顶部 locate 框对本日 `session:map` 做 query；`SessionRefPanel` 按内容 kind 分发 interpretation 卡/事实卡，可继续下钻 relation/evidence。

### 2.3 Context 抽屉（`src/features/context/`，P04）

- TopBar Context 钮 → Inspector 打开当前活动 Turn 的语境概览（无活动 Turn 时空态 + 跳历史入口）。**复用共享 Inspector，不是独立抽屉**。
- Overview 按 Background/Trace/Working 三槽分组；选中段才请求正文。形状驱动视图：state（字段正文+引用列表）/ heap（installed/available 分区，ref 行跳 owner 阅读）/ stack（root refs → live inspect 子节点逐层展开）/ map（session:map 等 → live inspect）/ working（摘要 + 跳工作区/运行观察页）。
- 刷新语义：connectionStore 的 `contextGeneration` 只在 `context.installed`/`context.background.changed` 事件后 bump；面板标 RefreshNotice、保留已读内容与滚动，显式 Refresh 才重读。Turn 结束后 409 `context.unavailable` 转为"last captured view"，不重试。

### 2.4 工作区（workspace，`src/features/workspace/`，P06）

- 左侧 Sidebar（Files/Trash、目录树、名称筛选、日选择器、拖入上传）+ 右侧 FilePanel。`store.ts` 的 day：`null`=活动日（可写）、字符串=归档（只读）。
- 文本分页读取（`useWorkspaceText`），首屏不完整时编辑前显式 `full=true` 整读并检查 complete/editable 才启用覆盖保存；外部变化以 record.mtime_ns/size 为基线，有草稿时给"重新载入/继续编辑"选择。
- blob 走鉴权 fetch（Range）→ Object URL，按 media_type 分发 BlobView/TextFileView；大媒体未完整 Range 集成就明确给下载。
- 活动文件删除 = 移入回收站；Trash 标签查看/恢复；无永久删除/清空入口。
- 页面内搜索（`SearchPanel`，见 §5）scope 可为整个 Workspace/目录/文件；归档日先切回活动日再搜。

### 2.5 Home（home，`src/features/home/`，P07）

- view 绑定 effective（默认）/actual；目录分组为顶层内容/通用 Skill（可展开 SKILL.md）/普通资源/domain·action guidance；名称筛选 = 服务端 `query` 参数（防抖）。
- `HomeChanges` 列 overlay 创建/修改/删除；`HomeDiffView` 读 actual→effective unified diff（Unified 着色 / Side-by-side 真实行号双列）；`baseline_diverged` 只作事实横幅，无 accept/reject。
- 内容搜索仅 effective：actual 下点搜索先显式切换并 toast 说明。工具栏：复制引用 / 在对话中引用 / References / 整理 Home（ReflectionDialog，无日期控件）。

### 2.6 Memory（memory，`src/features/memory/`，P08）

- 两节：active（活动 Memory.md，绑定日，`/v2/days` 选择器；归档日 404"未归档" / resource.unavailable / 空文档三态分开）与 persistent（知识目录：daily/entity/concept/fact/note，redirect 徽标）。
- redirect 文档：原文保留在屏 + 显式 "Open target"，绝不暗中替换。工具栏同 Home；整理 Memory 必须显式目标日（默认建议取 availability 中缺 daily 的日，绝不默认今天）。
- References 面板：direct refs（"It references"）随 metadata 到达即列出（零请求）；backlinks（"Referenced by"）只在显式点击后发请求，且仅当 owner 声明 backlinks source。当前文档的"查相关文档"入口由 owner 声明 document query 驱动。

### 2.7 运行观察（runtime，`src/features/runtime/`，P09）

- 顶部 OverviewStrip（Agent ready/启动中、活动日、当前 Turn 短 id + kind/state 徽标 + 真实 wait_reason、队列计数）+ 五个分页：Execution / Jobs / ACP / MCP / Environment。tab 切换即卸载，离开停止全部读取。
- Execution：当前 Turn 卡（state/kind/waiting 真实原因 + "Open in conversation"）、finished 结果分区（execution failure 与 finish_failures/cleanup 分开）、队列卡逐行 Cancel（各自 Turn id）。
- Jobs：绑定打开瞬间的活动 Turn；2.5s 定点轮询列表；选中才读 detail/output；continuation 是轮询位置不是结束标记（空页留 token、truncated 本 tick 续读、stalled 转产物入口、终态 drain）；Stop 以正式快照为准。
- ACP：targets（配置事实）与 connections（运行事实）分区；"Delegate in conversation" 只填 Composer 草稿。
- MCP：configured/enabled、connected、discovered、callable 四事实分列；"Refresh directory" 逐 server 显式触发；工具详情懒读；"Edit configuration" 跳设置 mcp 页。
- Environment：sources 表 + 定向事件窗口（打开时固定 through，手动 Re-read 更新，客户端按 source/topic/Turn 过滤）。

### 2.8 设置（settings，`src/features/settings/`，P10–P14）

- 左导航六组 + 界面设置，共 24 页（注册表 `pages.ts`：每页声明 surfaces/pathPrefixes/draftSources，搜索路由到归属页并高亮字段行）：
  - 概览与运行方案：Configuration status（运行配置/待激活/本地修改含 stale adopt-keep）、Run plans（方案管理）。
  - 模型与服务：LLM Providers、LLM Models（family 分组）、LLM Task Chains、Dedicated Providers、Dedicated Models & Uses（models/uses 双 tab）、Credentials、Image Generation（诚实预留页——后端无 image_generation 配置面）。
  - 行为与调用：Phase Bindings、Actions & Model Uses、Search Policies、Budgets（有界数值带滑块）、Reflection Schedule。
  - 工具与连接：Execution & Jobs、Web & Resource Fetching、ACP Subagents、MCP Servers（后两者为集合编辑器）。
  - 数据与知识：Workspace、Session、Home、Memory。
  - 系统与诊断：Endpoint & Sources（process_shell 只读投影、sources 可写性徽标、agent.*/config.* 进程项只读）。
- 底栏（`SettingsBottomBar`）：草稿/stale/校验计数、Reset this page（按页 pathPrefixes/draftSources 原子级撤回）、Discard all、Apply / Activate saved（按 `activity.can_reload` 禁用并显示真实原因）。
- 离开设置 tab 后左下角 `SettingsDraftChip` 浮动提示未应用草稿数；草稿只存内存不落盘（凭据安全）；有草稿时 beforeunload 拦截。

### 2.9 界面设置（settings → interface，§20）

- `InterfacePage` + `src/store/uiPrefsStore.ts`（persist `tinysoul-ui-prefs`）：字体（sans/mono）、字号 12–18、行高 1.3–1.9、密度、reducedMotion；主题控件写 `appStore.setTheme`。纯本地、立即生效、断连也可用；fallback 恰为原主题故未设置时渲染不变。无消费方的偏好（自动跟随/通知/宽度）刻意不交付。

## 3. 状态与接口所有权

核心原则：**owner 投影是正式来源，事件只做失效触发**（计划 §3.5）。没有任何业务状态从事件 payload 派生；事件到达 → `src/app/connection.ts` 路由 → 触发对应 owner 重读（status / displayed turn / day history）。

### 3.1 接口层（`src/api/v2/`）

- `transport.ts`：V2Transport（Bearer、可注入 fetch、AbortSignal、readBlob 支持 Range、错误转 `TinySoulApiError`）。
- `clients/`：14 个 owner client（health/turns/reflection/config/session/context/home/memory/workspace/search/jobs/capabilities/events/resources），`createV2Clients` 门面；`testing.ts` 录制式 fake fetch 供测试。
- `pagination.ts`：CanonicalJsonFragmentDecoder + PageFragmentAssembler（逐片即时尝试解析、交付一次、重置语义）；`clients/paging.ts` 的 `drainPages`。
- `errors.ts`：按 code 分类（continuation 失效四码、容量拒绝、config.invalid 的 details.key 定位、context.unavailable、search.view_expired 等）。**永不解析 message 猜字段**。
- 类型：`types.ts` barrel 按 owner 分文件（turn/context/search/job/config/resources/workspace/home/memory/events/runtime/session/common/json）；envelope 字段级对齐 schemas，owner 动态内容保持 JsonValue。

### 3.2 连接（`src/app/connection.ts` + `src/store/connectionStore.ts`）

- `app/connection.ts` 拥有全部异步生命周期：握手（health+status、协议 v2 校验、lease 身份核对）→ 快照 → WS 订阅；有界退避重连、gap 后 owner 重读 resync、generation/instance 变化处理、ready=false 轮询、显式 restart、事件失效路由。
- `connectionStore` 是它发布的状态：phase/info/clients/status/eventCursor/eventsPhase/eventGap/unreachable/**epoch**（连接代际守卫，旧连接的异步完成不得覆盖新连接）/contextGeneration（Context 刷新信号）/restartPending。
- `app/discovery.ts`：Browser localStorage 手动目标（含 v1 host/port 形态迁移）；Tauri lease。

### 3.3 对话（`src/store/turnStore.ts` + `src/features/chat/turnController.ts`）

- `turnStore`：活动 Turn 投影——turnId/day/source(live|session)/historyView/snapshot/items/pendingItems/queuedRequest/result + 当日 sessionTurns 列表 + outgoing echoes。本地状态只有 echo（sending/accepted/failed，携带 command_id/input_id/question_id 身份）与读取簿记（readEpoch 防晚到响应）。
- `turnController`：全部读写编排——对齐 status 与展示轮、drain InteractionPages（formal/pending/fragment 装配）、echo 收敛（convergeEchoes 唯一承担 echo→pending→formal 合并）、问题/预算回复、取消、Session 接替（有界重试）、accepted 回执即开轮（防快速完成竞态）。事件只经 connection 调度这里的刷新。

### 3.4 设置（`src/features/settings/draft/store.ts` + `applyController.ts` + `presets/presetsController.ts`）

- `useConfigDraftStore`：正式快照（saved/active/catalog/presets）+ 本地原子草稿 + stale 标记 + apply 生命周期。草稿身份 `(source_id, path)`。详见 §4。
- `applyController`：loadConfig（并行读 saved+active+catalog+presets）、applyDrafts（批量提交）、失败六型分类。
- `presetsController`：方案 create/rename/recapture/delete/apply + §15 草稿确认流（`PresetDraftConfirm` + `usePresetApplyFlow`，方案页与 Composer 快捷入口共用）。

### 3.5 共享 UI 状态

- `inspectorStore`（`src/store/inspectorStore.ts`）：共享 Inspector 的条目栈（push/pop/open/close）。任何页面可推详情层；AppShell 挂唯一 InspectorHost，同时只有一个主抽屉。history/context/trace 的 `entries.tsx` 都是它的条目工厂。
- `targetsStore`（`src/features/resources/targetsStore.ts`）：ResourceRouter 给 owner 页的一次性导航意图（home/memory 各一槽），页面 mount 消费后清除。
- `appStore`（`src/store/appStore.ts`）：只有本地偏好（theme/activeTab/projectRoot）+ toasts。**不放任何后端业务状态**。activeTab 持久化时 v1 的 "monitor" 值迁移为 "runtime"。
- `uiPrefsStore`（`src/store/uiPrefsStore.ts`）：界面设置持久化（见 §2.9）。
- 各 feature 自有 store：`workspace/store.ts`（day/选中/树）、`home/store.ts`（view/选中/diff 覆盖）、`memory/store.ts`（active 日/persistent 选中）、`runtime/store.ts`（分页选择）、`settings/uiStore.ts`（设置内导航/focusPath）、`chat/composerDraft.ts`（compose 模式共享草稿）。

### 3.6 Inspector 条目工厂（导航枢纽）

`src/features/{history,context,trace}/entries.tsx` 分别导出 open/push 系列函数（openHistoryBrowser/openSessionMap/openContextDrawer/openTurnProcess/pushJobDetail 等）。资源类链接统一走 `src/features/resources/router.ts`（见 §6）。

## 4. 设置保存与方案语义

### 4.1 ConfigDraft 原子模型

- 后端配置事实：`saved`（已保存视图）与 `active`（运行视图）两份 Configuration；catalog 提供字段标题/说明/value_kind/choices/reference/collection 描述/adapter rules。
- 草稿身份 `(source_id, path)`（JSON codec key）；操作只有 set/delete 两种原子。整对象 set 草稿按 catalog 边界拍平成字段投影；delete 只删该 source 实际拥有的键。
- 三态查询 `entryView`：draft（本地修改）/ saved（已保存未激活）/ active（运行值）。脱敏凭据显示 `"<redacted>"` 占位，**绝不回写**；Set/Remove 是显式操作，值走共享 dotenv 草稿。
- saved 基线移动时 `rebaseOnSaved` 把脏条目标 stale 并保留本地值（用户在概览页 adopt/keep）。共享原子（`action.models.bindings` 数组按 consumer、`action.retrieval` map 按 key、`infra.model_services.providers` 整数组）支持逐条目编辑与撤回（`resetAtomEntries`，数组按基线序归位使全量撤回恰好清草稿）。
- 本地校验（`draft/catalog.ts`）：value_kind 形态 + null 递归 + reference 目标存在性（草稿新建对象可被引用）。校验只是提交前提示，不替代后端校验。

### 4.2 apply / reload 语义（`applyController.ts`）

- `applyDrafts` 批量提交 operations；成功 `state=active` 后只清已提交的草稿 keys 并重读快照。`cleanup_diagnostics` 独立横幅呈现，**绝不**把结果翻回"未应用"。
- 无本地修改但 saved 待激活（pending_reload）时底栏提供 "Activate saved"（reload 入口）。
- 失败一律保留草稿，六型分类：`config-invalid`（带 `details.key` 可定位导航到归属页字段；无 key 是批次错误，表单级呈现）、`request-invalid`、`activation-unavailable`（409）、`activation-failed`、`api-error`、`uncertain`（网络/结果不明——提示先核对正式状态，不盲目重发）。带结构化 details 的失败在横幅 Details 区原样展示 JSON。
- 改配置不会自动启动 MCP/ACP 服务；apply 发布新 generation 后，按 (generation_id, scenario) 缓存的 actions 投影自然重取。

### 4.3 运行方案（presets，`presets/`）

- 受管范围固定五组：models / tasks / routing / retrieval / budgets（`presetsModel.ts` 注册表，以 `included_scopes` 为后端事实来源，明示"不捕获什么"）。
- 捕获三源：`active` / `saved` / `draft`（= saved + operations；空 operations 退化为纯 saved）。重命名不重抓；显式覆盖才携带 capture。捕获/重命名/删除只动方案记录，**绝不调 apply、绝不清草稿**。
- `applyPreset` 提交且仅提交 `{preset_id}`（类型层禁止与 operations 混发）；成功后只清"用户在确认流中同意放弃"的草稿键，飞行中的新编辑保留。
- §15 草稿确认流：无草稿直接应用；有草稿三分支——"Review my changes first" / "Discard changes and switch" / 取消。不自动合并、不连发两次请求。
- 方案详情含依赖问题卡（后端结构化 key/message，按 `pageForPath` 跳对应设置页）与"与运行配置的差异"（受管范围内叶子级 diff）。Stored snapshot 是只读 read model，永不作 apply body。

## 5. Context 与资源的差别（已安装语境 vs owner 当前内容）

这是最容易混淆的一条边界：

- **Context（语境）**是模型在某一 Turn 实际看到的内容，属于那个 Turn。Context 抽屉读的是 API-09（`context.overview/segment/inspect/query`）：段描述（owner/shape/order/capabilities/root_refs）与已安装正文。heap 段的 installed/available 只是"该 Turn 加载了哪些 ref"的事实。
- **资源**是 owner（Home/Memory/Workspace/Session）当前持有的内容，随写入变化。从 heap ref 点进 Home/Memory 阅读，走的是 owner 接口（`home.content`/`memory.document`），面板顶部固定标注"owner 当前内容，非段内已安装正文"——**不保证等于模型当时看到的版本**。
- 打开 owner 阅读不改变模型侧任何加载状态（无 SELECT/RECLAIM 控件，UI inspect 全 GET 只读）。
- 历史轮/归档日的引用解析必须携带来源绑定：相对引用经 API-18 `resources.resolve` 携带 origin（day/turn_id/view）；`resource.unresolved_origin` 如实提示缺原绑定，**绝不**默认落成今天 latest。live 与 history 的 Markdown origin 由 `origin.ts` 的 `conversationOrigin` 统一构造：仅归档日内容绑定 day/turn。
- 历史 Task 的模型请求（事件定向读取，ModelCallPanel）与当前 Context 是两回事，界面不混。

## 6. 代码块注册方法（CodeBlockRegistry）

`src/components/markdown/codeBlockRegistry.ts`（计划 §21.1）：

```ts
registerCodeBlock("mermaid", {
  parse?: (source: string) => T | null,   // 可选；返回 null 或抛错 → fallback
  render: ComponentType<CodeBlockRenderProps<T>>,  // 真组件，可用 hooks
  fallback?: ComponentType<CodeBlockFallbackProps>, // 可选，默认纯代码块
});
```

- alias 大小写不敏感，可传数组（`["mermaid", "flowchart"]`）；重复注册覆盖。未注册 fence 不进注册表，保持默认 pre/code——任何代码都不会被当作可执行脚本。
- 接入点：Markdown.tsx 用 `components.pre` 覆写（行内 code 永不经过注册表）。流式未闭合 fence 由 `findUnclosedFenceLine` 判定，只有文档尾部的开放 fence 显示源码。
- props：`parsed`（parse 结果，无 parse 时是原文）、`source`、`language`、`theme`（light/dark）、`origin`（MarkdownOrigin：view=live|history + ResourceOrigin 路由事实）。
- 内置注册在 `blocks/builtinBlocks.tsx`（模块级执行，由 Markdown.tsx import 触发）：mermaid/flowchart → MermaidBlock，tikz → TikZBlock；`tinysoul-question` → questionBlock（chat 内注册）。
- **新增 renderer 步骤**：① 在 `src/components/markdown/blocks/` 写组件（需要 frame 就复用 `BlockFrame`：缩放/导出/重试/排队语义已有）；② 在 `builtinBlocks.tsx` 注册 alias；③ 重资源按 Mermaid/TikZ 模式懒加载（`import()` + `useInViewport` 视区触发）；④ 在 `test/blocks/codeblocks.test.tsx` 加 vitest 覆盖，真实渲染验证加 `test/e2e/codeblocks.pw.ts`。
- 复杂渲染器的技术结论（iframe 隔离、wasm 资源伺服、编译槽位上限 2）见 `docs/design/codeblocks.md`。

## 7. 资源链接与引用（ResourceRouter）

`src/features/resources/`：

- `reference.ts`：`classifyReference` 分类（workspace/home/memory/session/turn/http/dynamic-memory/unknown），合法协议才判定可路由；`splitFragment`/`parseLineFragment` 处理 `#L…` 行定位。
- `router.ts`：已带正式 locator 的引用直接路由；相对/动态/未解析引用经 API-18 携带 origin 解析（ResolveOutcome: resolved/unresolved_origin/unsupported/error）；`routeTarget` 按 target 分发到工作区页/Home/Memory（targetsStore）/history 条目/外部浏览器（Tauri opener 插件，Browser `window.open`）。
- 三操作：点击跳转 `openReference` / 复制原引用 `copyReference`（复制用户可见原文，不是解析后 locator）/ 在对话中引用 `quoteReference`（`buildQuoteText` 生成可编辑文本草稿填入 Composer，保留来源 day/view/turn 绑定，不自动发送）。
- Markdown 链接/图片：`links.tsx` 只对白名单协议生成链接控件；workspace 图片走鉴权 blob → Object URL，home/memory 无 blob 路由显示引用提示。
- 共享搜索面板 `SearchPanel.tsx`：能力（literal/regex/document query/backlinks）从 `/v2/config/actions` 对应 search action 的 schema 读取，只出现实际声明的控件；Workspace/Home/Memory 三页共用；结果就地打开不关面板。

## 8. 实际运行/测试命令

在 `visualization/` 下执行：

```bash
pnpm install --frozen-lockfile   # 依赖安装（锁文件唯一，不加 npm 锁文件）
pnpm test                        # vitest 全量（当前 84 文件 / 773 例）
pnpm build                       # tsc + vite build（门禁）
pnpm dev                         # vite 开发服务器
```

Playwright e2e（真实后端 + 受控脚本模型，chromium）：

```bash
# 需 TinySoul conda 环境；Python 解析顺序 $TINYSOUL_PYTHON → $CONDA_PREFIX/python.exe → PATH python
conda activate TinySoul   # 或显式：
TINYSOUL_PYTHON=$CONDA_PREFIX/python.exe pnpm exec playwright test -c test/e2e/playwright.config.ts
```

- 两个受门禁场景：`chat-flow.pw.ts`（连接→发 Turn→问题卡→回复→完成→刷新恢复）与 `codeblocks.pw.ts`（Mermaid/TikZ 成功与失败真实渲染，全部请求同源）。globalSetup 启动 `backend_server.py`（真实 Agent + Endpoint，`--port 0` 随机端口，连接信息写到 `<repo>/.local-test/e2e-backend/connection.json`）。
- 视觉核对（F7-B，独立 config，不在默认门禁内）：
  `TINYSOUL_PYTHON=$CONDA_PREFIX/python.exe pnpm exec playwright test -c test/e2e/visual-review.config.ts`，产物在 `docs/review/`。
- bundle 证据构建（一次性，不在门禁内）：`pnpm exec vite build --config test/e2e/vite.bundle-evidence.config.ts`。
- Tauri：`pnpm tauri build`（F0 验证过 cargo 1.97.1 成功，dist 自包含含 tikzjax 资源；webview 内交互式渲染未实测）。
- 契约 fixtures：`test/fixtures/contracts/` 24 个样例复制自后端 `docs/endpoint/contracts/examples/`（基线 `c479ca0`，README 注明）；token 样例只展示结构，不能发真实后端。

## 9. 已知边界与遗留

实现缺口（如实保留，均有记录）：

1. **Action catalog 文档字段（document_fields）编辑未实现**（F2-C 记录）：catalog 文档集（domain/action 的 `visibility.default` 等文档内声明）在 Actions 页为只读协议摘要；`action_catalog` 完整编辑表面留待后续。设置搜索能路由到这些条目但页面不提供编辑。
2. **Environment 事件窗口是打开时的一次性定向读取**（F6-A 记录）：手动 Re-read 更新，不做常驻跟随。
3. **TikZ 无跨块共享运行时**（F6-A 记录）：并发槽位上限 2 + 排队/卸载释放已就位；Mermaid initialize 是全局配置；TikZ 失败详情仅在 iframe 控制台；导出文件名固定 `diagram.svg`。
4. **历史轮 agent.action 投影无 result payload**（F4-B 记录）：历史卡展开以事件定向读取补齐（保留窗口内，截断如实标注）；normal 观察级别下 model 级 request/response 不记录，Inspector 显示"未记录"。
5. **Memory active 的 backlinks 未开放**（F5-B 记录）：anchor 是动态 `memory:current`，References 面板仅服务持久文档。
6. **Context 进入 Home 阅读的"已加载"来源提示**（F5-B 记录）：依赖 Context 侧导航契约，owner 阅读路径已就位。
7. **Working 节跳转为整页切换**（F4-A/F6-A 记录）：运行观察落地后可加 section 参数深链。
8. **生图模型是诚实预留页**：后端尚无 image_generation 配置面，不伪造编辑能力。
9. **内嵌浏览器未做**：网页链接走系统浏览器（与原意图一致）。
10. **Tauri webview 内交互式渲染未实测**（F0/W2 记录）：构建通过，dist 自包含。
11. **`GET /v2/reflection` 无 limit 参数**（F1-A 记录）：后端只有 before；client 按后端实现，权威计划 §3.4 表述待维护者修订（非契约缺口）。
12. **F7-B 视觉核对观察问题的处理状态**（记录于 `docs/review/visual-check.md` 问题清单表）：9 项中 7 项低严重度前端问题（问题 2–8：LLM Models「Capabilities」重名标题、Session map 双 chevron 与摘要连排、只读历史下 Composer 禁用语义、活动 Memory 空白无显式空态、连接瞬间 TopBar「reconnecting…」并存、Home 正文 `session:map` 引用后异常空隙）已于 F7-C 修复并经重跑截图与全量门禁确认；剩余 2 项——`home:agent@AGENT` 正文读取 503（`AgentHomeInvariantError`，后端跟进，需求单 `docs/demand/20260930-home-agent-top-document-503.md`）与亮主题 answer-card 凹版角标对比极弱（风格化取舍，观察记录）。
13. **需求目录** `docs/demand/`：3 项 pending（两项 catalog choices 对齐、一项 Home AGENT 文档 503 确认）；v1 旧需求单全部归档于 `archived/`（含归档结论）。索引见 `docs/demand/README.md`。

刻意不交付（设计决策，非缺口）：无消费方的界面偏好（自动跟随/通知/宽度）；Search 结果翻页按钮（continuation 属于原 Turn/profile）；Home diff 的 accept/reject 与 merge 编辑器；永久删除/清空回收站；任何从事件 payload 派生业务状态的通道。
