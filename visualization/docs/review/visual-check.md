# F7-B 代表性页面视觉核对记录

日期：2026-09-30。方法：`test/e2e/visual-review.pw.ts`（独立配置 `test/e2e/visual-review.config.ts`，不进既有 e2e 门禁）连接真实后端 harness（`backend_server.py`：真实 Agent/owners/HTTP/WS + 脚本化模型），Chromium 1440×900（窄窗口组 800×900）逐页截图。

运行方式（visualization/ 下）：

```bash
TINYSOUL_PYTHON=<python> pnpm exec playwright test -c test/e2e/visual-review.config.ts
```

防空白校验：spec 内每张截图断言文件 >15KB；运行后用 Pillow 抽样像素（每 37 像素采样）计算灰度标准差，23 张全部 std ≥ 8.4（空白页 ≈ 0），确认均为真实渲染。截图清单（`docs/review/screenshots/`，尺寸/文件大小/像素方差；2026-09-30 修复后重跑复测值）：

| 文件 | 尺寸 | 大小 | std |
| --- | --- | --- | --- |
| 01-chat-empty-light.png | 1440×900 | 47 KB | 9.0 |
| 02-chat-answer-light.png | 1440×900 | 70 KB | 8.8 |
| 03-chat-question-light.png | 1440×900 | 76 KB | 8.7 |
| 04-context-overview-light.png | 1440×900 | 122 KB | 33.6 |
| 05-context-segment-light.png | 1440×900 | 84 KB | 27.7 |
| 06-chat-conversation-dark.png | 1440×900 | 94 KB | 9.0 |
| 07-chat-daylist-dark.png | 1440×900 | 58 KB | 8.4 |
| 08-history-days-light.png | 1440×900 | 78 KB | 26.7 |
| 09-history-session-map-light.png | 1440×900 | 104 KB | 30.0 |
| 10-settings-overview-light.png | 1440×900 | 187 KB | 25.0 |
| 11-settings-llm-models-light.png | 1440×900 | 170 KB | 19.2 |
| 12-settings-actions-light.png | 1440×900 | 165 KB | 16.1 |
| 13-settings-plans-light.png | 1440×900 | 96 KB | 17.1 |
| 14a-home-unreadable-top-doc-light.png | 1440×900 | 92 KB | 18.8 |
| 14b-home-effective-light.png | 1440×900 | 166 KB | 30.7 |
| 15-memory-active-light.png | 1440×900 | 55 KB | 11.6 |
| 16-memory-knowledge-light.png | 1440×900 | 69 KB | 18.1 |
| 17-workspace-light.png | 1440×900 | 42 KB | 10.1 |
| 18-runtime-execution-light.png | 1440×900 | 38 KB | 12.2 |
| 19-runtime-jobs-light.png | 1440×900 | 37 KB | 12.4 |
| 20-runtime-mcp-light.png | 1440×900 | 43 KB | 13.3 |
| 21-chat-narrow-800-light.png | 800×900 | 64 KB | 12.6 |
| 22-settings-narrow-800-light.png | 800×900 | 175 KB | 32.2 |

（14a/14b 与 21/22 为后补命名；std 为 2026-09-30 修复后重跑的抽样复测值，内容含当次 runId，数值与首轮不可逐位比较。）

## 对话页

**01-chat-empty-light（空态·亮）**：首屏主次清晰——中央空态（图标+标题+两行说明+「Browse earlier days」动作）是唯一定焦点，Composer 居中沉底，意图 chip（New turn）与方案入口（Run plans）各居左右。三层底清楚：页面 `--bg`、NavRail/TopBar/StatusBar `--bg-elev`、细边线 `--line`。靛蓝只出现在品牌块与发送按钮，克制。字号 13px 基线、说明文字 fg-muted，密度舒适。~~注意 TopBar 在连接刚完成、事件流未 live 的瞬间显示「reconnecting…」，与状态栏 connected 并存（见问题 7）。~~（问题 7 已修复：首次接入期间如实显示「connecting…」。）

**02-chat-answer-light（含回答·亮）**：用户气泡右置 accent-soft 底、回答卡左置带 agent 头像，chat-grid 蓝图网格在亮主题下极淡、不抢内容。answer-card 已进入文档态（settle 后），凹版角标与蚀刻内框在亮主题下对比极弱、近看才见（记录为观察项 9）。回答正文 13px、行高合适；回答卡横向跨度大（近全列宽），短回答时卡片显得空，是设计语言内的取舍。

**03-chat-question-light（question 卡·亮）**：首屏焦点全部落在 question 卡——浅靛蓝容器（accent-soft 系）与页面区分明确，A/B 选项整行可点、字母 chip 仅编号、description 次级灰，Other 输入与靛蓝 Reply 主按钮层级正确。TopBar「turn active」徽标、Composer 变为「Append to the current turn…」+ 红色停止键、状态栏「user turn · waiting」三处等待语义一致。

**06-chat-conversation-dark（会话·暗）**：暗主题三层底（#0d1017/#151a23/#090c12）层次清楚，answered question 卡保留所选 Option B 的 accent 描边高亮与「answered」标注；REPLY 气泡与回答卡（暗色终端态，磷光绿 L 角标）形成终端—文档二相性。对比度整体足够，fg-muted 描述文字在暗底下可读。

**07-chat-daylist-dark（日列表·暗）**：reload 后「Today's conversations」卡片列表：标题、回答摘要、日期行三层字号（13/12/11px）递进，绿色 answered 徽标在暗底上不刺眼；「Earlier days」入口在右上、底部「Browse earlier days」呼应，主次正确。

## Context 抽屉与历史

**04-context-overview-light**：抽屉 640px、backdrop 压暗对话页，Background/Trace/Working 三组大写小标题（10.5px tracking-wide）分区，段行=白卡（bg-elev）+细边线：段名 13px medium、shape 徽标（State/Map/Heap/Stack）、「1 root ref · 822 chars」等状态行 11px faint，信息量足而不挤；empty 段以灰徽标如实标注。Captured 时间与「Usage in characters」说明在顶部一行排开。

**05-context-segment-light**：段详情（identity）：返回箭头+段名+`background · state · owner context` 副题，Installed body 卡内 `#0 / system / identity` 三枚 chip 后接正文，Details 折叠区在下。下钻层级清晰；正文区以下大量留白属正常（短段）。

**08-history-days-light**：日目录单行（日期+active 徽标+Session map 快捷钮），单行信息克制；空目录有独立空态（本次未截取）。

**09-history-session-map-light**：Locate 框置顶，Topics（空态文案引导）/Unclassified Turns/All history/All annotations 四节次序符合设计；未归类 Turn 卡显示日期·状态+摘要。~~两处问题见问题 3、4（双 chevron、摘要连排）。~~（问题 3、4 已修复：卡外下钻钮改用面板图标与卡内 chevron 区分，摘要以「·」分隔。）

## 设置

**10-settings-overview-light**：左 220px 分组导航（大写组名+页面行，当前页 accent-soft 高亮）与右侧 max-w-3xl 内容列比例恰当；Running configuration 卡（generation/activity/pending 定义列表 + sources 等宽字体清单）主次正确，idle 绿徽标点睛。sources 清单较长但 mono 11px 行距舒适；底部固定草稿栏（No local changes / Reset / Discard）不遮内容。

**11-settings-llm-models-light**：主从结构——左列模型清单按 family 分组（DEEPSEEK/GLM/KIMI…大写小标题），选中行 accent-soft；右列详情区 Identity/Adapter/Family/Collapsed/Provider 链（拖拽柄+序号+上下移+删除）/Capabilities 分区，说明文字 11px faint 每节一句，密度偏高但分组明确。chips（text_input 等）accent-soft 统一。~~问题 2：「Capabilities」标题连续出现两次。~~（问题 2 已修复：字段行改为「Feature capabilities」，区段标题保留。）

**12-settings-actions-light**：Action 目录（63 configured）左列按域分组，右列定义列表把 Availability（granted/supported/available 三绿标）、Model selection（selectable+source）、Visibility、Timeout、Hooks 等解析值以「左说明/右等宽值」排布，可读性好；catalog 文档路径与「编辑为后续 surface」的诚实说明并存。

**13-settings-plans-light**：空方案状态——左列窄卡「No run plans yet + New plan」、右侧「Select a plan」引导，双空态文案不重复、动作明确。观察：左卡标题「Run plans」与页面 h1 重名（轻微）。

## Home / Memory / 工作区 / 运行观察

**14a-home-unreadable-top-doc-light**：目录首项 agent@AGENT 的正文读取失败态：中央 warning 图标+「The document could not be read」+原因一行+Retry，呈现诚实、不伪造内容（见问题 1）。

**14b-home-effective-light**：effective 目录（TOP CONTENT/GENERAL SKILLS/GUIDANCE 三组，skill/action/domain 徽标用领域色紫/青/蓝）+ 正文 md-body 排版（标题、段落、行内 code accent 色）层次好；effective 徽标+mono link 标头信息完整。~~问题 8：`session:map` 引用后有一处异常宽空白。~~（问题 8 已修复：悬停操作不再预留布局宽度，引用后恢复正常单词间距。）

**15-memory-active-light**：Active memory/Knowledge 切换+日绑定选择器，「active · 2026-09-30」徽标准确；新日活动 Memory.md 为空，~~正文区全空、仅左栏说明（问题 6：缺显式空态）~~（问题 6 已修复：空文档呈现「Nothing recorded yet」显式空态）。

**16-memory-knowledge-light**：kind tabs（All/Daily/Entities…）+过滤框，左列「No persistent knowledge yet」含两个引导动作（Start a conversation 主按钮、Organize Memory 次按钮），右侧「Knowledge」空态说明——空态文案分工清楚，属合法空态核对对象。

**17-workspace-light**：日选择器+Files/Trash+过滤，左列「No files yet」、右列「Workspace」引导（选择/新建/拖拽上传），底部 drop hint 常驻；空态层级正确。

**18/19/20-runtime-\***：概览条（Agent ready 绿标/Day/Turn none running/Queue 0）+ 五 tab；Execution「No turn is running」、Jobs「No active turn」、MCP「No MCP servers configured + Configure servers 动作」三个空态图标/标题/说明一致，且 MCP 给了明确下一步。空态全部诚实、无红绿灯式伪造。

## 窄窗口（800px）

**21-chat-narrow-800-light**：只读历史 banner（说明+Session map/Process/Back to today 三钮）在 800px 下不折行溢出；气泡与回答卡自适应，Composer 居中宽度合理。~~问题 5：只读状态下 Composer 视觉上看不出禁用。~~（问题 5 已修复：Composer 整体灰化降级，占位文案与「Read-only」chip 明示禁用，发送钮禁用。）

**22-settings-narrow-800-light**：220px 导航+内容列仍可用；generation id 换行、sources 右列截断为省略号（title 兜底），底栏三钮未溢出。密度可接受，无横向滚动。

## 问题清单与修复状态

2026-09-30 修复复核：问题 2–8 已修复并经重跑截图确认（修复位置见表内），问题 1 留后端跟进（已转需求单），问题 9 维持观察记录。

| # | 严重度 | 位置 | 问题 | 状态 |
| --- | --- | --- | --- | --- |
| 1 | 中 | Home 页 / 后端 | effective 目录首项 `home:agent@AGENT` 正文读取 503（`resource.unavailable`，`AgentHomeInvariantError`）；curl 直连复现，其余 top content（context/background、identity/identity、identity/soul、user/user）均 200。目录把不可读条目呈现为普通可选项，用户首点必踩。需后端确认 AGENT 顶层文档读取语义（可能为 harness 初始化内容特有问题）。证据：14a。 | 未修（后端需求单 `docs/demand/20260930-home-agent-top-document-503.md`） |
| 2 | 低 | 设置 LLM Models | 详情区「Capabilities」节标题与子节标题连续重名出现两次，信息层级重复。证据：11。 | 已修复：字段行改为「Feature capabilities」（`LlmModelsPage.tsx`），区段标题保留 |
| 3 | 低 | Session map | 未归类 Turn 卡片内侧 chevron 与卡片外侧紧跟的 chevron 按钮并列，两个相同箭头含义不同（下钻/打开），视觉上像重复或错位。证据：09。 | 已修复：卡外「Inspect the recorded facts」钮改用 PanelRightOpen 面板图标（`history/panelShared.tsx`），与卡内跳转 chevron 区分 |
| 4 | 低 | Session map | 未归类 Turn 摘要把提问、所选 option 与 comment 无分隔连排（"…/ Option B (opt_b) The second option e2e-reply-comment …"），可读性差。证据：09。 | 已修复：clue 的换行与「 / 」分隔统一拍平为「 · 」（`history/disclosure.ts` `flattenClue`） |
| 5 | 低 | 对话页（只读历史） | banner 声明「replies and edits are disabled」，但 Composer 与发送按钮呈现为完全可用态，禁用语义只靠 banner 文字。证据：21。 | 已修复：只读历史下 Composer 整体降级（opacity-60、无焦点环），输入框与发送钮禁用、意图 chip 换为「Read-only」静态标、方案入口隐藏，占位与提示文案明示（`chat/Composer.tsx`） |
| 6 | 低 | Memory 活动记忆 | 活动 Memory.md 为空时正文区完全空白，无显式空态（仅左栏说明）；与 Knowledge/工作区的完整空态不一致。证据：15。 | 已修复：空文档（后端返回单个空文本 chunk）按文本判定为无内容，呈现既有「Nothing recorded yet」空态（`memory/ActiveMemoryView.tsx`；同一根因的持久文档视图 `MemoryDocumentView.tsx` 一并修复） |
| 7 | 低 | TopBar | 连接刚完成、事件流未 live 的窗口期 TopBar 显示「reconnecting…」，与状态栏 connected 并存，易误读为连接异常。证据：01。 | 已修复：事件流首次接入（offline/connecting）显示「connecting…」，仅断流恢复（reconnecting）才显示「reconnecting…」（`shell/TopBar.tsx`） |
| 8 | 低 | Home 正文渲染 | markdown 中 `session:map` 引用后出现一处异常宽空白（引用渲染空隙）。证据：14b。 | 已修复：引用悬停操作（copy/quote）隐藏时不再预留约 38px 布局宽度，改为零宽、悬停/聚焦展开（`resources/links.tsx` `ReferenceActions`） |
| 9 | 观察 | 对话页 answer-card | 亮主题文档态的凹版角标/蚀刻内框对比极弱，近看才可见；风格化取舍，记录备查。证据：02。 | 观察（风格化取舍，未改） |

## 总体结论

代表性页面全部消费 Luminous tokens：三层中性底、细边线、靛蓝只用于主动作与激活态、领域色（skill 紫/action 青/domain 蓝）仅说明来源、状态色仅说明运行结果；明暗双主题各自成立，暗主题终端态 answer-card 保留二相性。空态/等待态普遍诚实（图标+标题+说明+动作，无伪造数据）。首轮发现的问题 2–8（7 项低严重度）已于 2026-09-30 完成前端修复，并经重跑截图目检、新增测试与全量门禁确认（修复位置见问题清单表）；剩余待办为问题 1（Home 顶层 AGENT 文档读取失败，需后端跟进，已转需求单）与问题 9（亮主题 answer-card 凹版角标对比，维持观察记录）。
