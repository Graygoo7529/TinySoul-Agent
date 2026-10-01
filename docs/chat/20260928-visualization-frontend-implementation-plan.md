# Visualization 前端重构与建设执行计划

> 建立：2026-09-28；最近设计核对：2026-09-29；实施状态：pending。
> 后端契约基线：`5de6991b11cde8a6f5238445b2c339d6dd6011aa`；本次复核检出：`6eb0eee357443d882be230c54c961cf3e7e513c8`。后端已交付本文使用的 Endpoint v2 能力；本次按已确认的复核意见补充实施与验收细节，不表示前端实现或联调已经完成。
> 本文独立定义产品语义、页面布局、用户路径、接口使用、迁移步骤和验收，不需要历史讨论稿补充。API 编号是本文的接口索引。
> 规约依据：根目录 `AGENTS.md`；请求及响应事实以 `tinysoul/gateway/endpoint/http/`、`docs/endpoint/contracts/`、`docs/endpoint/` 和受鉴权 OpenAPI 为准。遇字段差异先核对实现和真实样例，不构造兼容两套语义的前端适配。

## 0. 给接手实施者的应用导读

### 0.1 用户正在使用什么

TinySoul 是一个在独立主机上持续运行的个人 Agent。Visualization 是它的远端界面，既可以在浏览器运行，也可以在 Tauri 桌面壳运行。关闭界面不结束 Agent；打开多个页面也不会创建多个 Agent。一次配置应用会重建 Agent 的运行世代（generation），不是重建项目或删除数据。

Endpoint 只监听后端主机的 loopback。本地调试支持手动输入 `127.0.0.1:1430` 等实际后端地址并提供连接凭据；远端使用以已有隧道/转发为前提，填写客户端可达的转发地址。本轮不部署转发服务或改变后端监听边界，连接细节见 §4。

用户主要在对话页提出目标。Agent 可以连续思考和执行、操作工作区、检索自己的知识、等待后台任务，也可以在同一轮中向用户提问。一个 User Turn 可以包含多个 Cycle、Action 和模型调用；等待回复或预算时仍是同一个 Turn。普通新消息可以开始下一轮，也可以明确追加到正在运行的一轮。前端必须让这些操作的差异可见，但无需让用户学习内核术语。

下面的说明用于指导页面实现和帮助内容，不应原样成为页面上大量的小字。日常界面优先呈现对象、内容和操作；仅在用户第一次进入、展开帮助或遇到选择歧义时解释必要概念。

### 0.2 数据与运行概念

| 概念 | 用户理解及界面责任 |
| --- | --- |
| 对话与 Session | Session 保存当日已完成的对话事实和 Agent 梳理的话题/推导线索；日切归档。历史由正式记录读取，不靠浏览器保存整份聊天或回放全部日志。 |
| Context | 当前 Turn 中 Agent 实际已安装的语境。Background 是背景，Trace 是本轮过程，Working 是当前工作状态。它不是知识库全文，也不是所有历史模型请求的快照。 |
| Workspace | 当天实际可读写的文件和产物。用户可在工作区页编辑；日切后原目录归档只读。pinned/tmp/library 是标签，不能改变归档规则。 |
| Home | Agent 的身份、偏好、技能和行动指导。actual 是已接受的基线，effective 是叠加普通运行修改后的有效内容；这些修改的 overlay 跨日保留。 |
| Memory | 活动记忆是当日 Memory.md；持久知识是 daily/entity/concept/fact/note 文档。活动记忆与同一天的持久 daily 是两个对象，知识库不是按日期还原的快照。 |
| Reflection | 专门整理 Home 或 Memory 的一轮运行，与对话共用根队列。Home Reflection 审核 overlay；Memory Reflection 把指定来源日的经历沉淀到持久文档。它不生成一轮普通用户会话。 |
| Action 与模型用途 | Action 定义做什么；内部可能不需要模型，也可能使用 LLM、JEV 或 Embedding。模型用途声明允许的实现，配置选择实现及目标；前端不能从名字推测模型能力。 |
| Search 与 Inspect | Search 发现/约束候选，返回真实片段和引用；Inspect 按已有引用逐层阅读。界面浏览只是用户阅读，不等于 Agent 执行了 Action 或加载了 Context。 |
| Job、ACP、MCP | Job 是当前 Turn 的后台工作。ACP 连接可以复用，一次委派是 Job；MCP 是外部工具目录与调用能力。查看运行页不自动委派或执行工具。 |
| Agent 设置与运行方案 | 设置包含全量可配能力；运行方案只捕获模型、调用分配、指定检索配置及可选预算。方案存在后端项目中，应用后仍成为普通配置，不增加运行时覆盖层。 |

### 0.3 页面与典型使用路径

| 页面/入口 | 用户来这里做什么 | 与其它页面的衔接 | 操作边界 |
| --- | --- | --- | --- |
| 对话 | 交代目标、补充信息、回答 Agent、查看回答与过程、切换运行方案 | 产物进入工作区；资源引用打开对应 owner；问题和预算留在对话中处理。 | 新轮、追加、回复和补额是不同意图。 |
| 对话历史与 Session | 回看某一天的交流，理解话题和证据 | 从历史菜单进入；地图也可从 Context 的 Session 段进入，无新增常驻日期栏。 | 只读事实和解释，不提供外部编辑地图。 |
| Context 抽屉 | 回答“Agent 这一轮目前看到了什么” | 右上按钮打开；资源全文与模型调用详情是明确的下一层阅读入口。 | 阅读已安装语境，不提供手动加载/逐出控制。 |
| 工作区 | 阅读、编辑和管理文件，寻找执行产物 | 从导航或回答中的 workspace 链接进入；原有目录与编辑主布局保留。 | 活动日可编辑、移入回收站及恢复；归档只读。 |
| Home | 了解 Agent 的身份、偏好、技能与当前改动，发起整理 | 默认读 effective；对照 actual/diff；实际审核由 Reflection 执行。 | 页面不直接写入或接受 Home 改动。 |
| Memory | 查找 Agent 已积累的经历和知识，沿引用阅读 | 当日活动记忆与持久知识分栏；按来源日发起记忆整理。 | 页面不直接保存活动记忆或持久知识正文。 |
| 运行观察 | 了解为什么正在运行或等待、后台任务和外部连接情况 | 跳回对话答问题，跳产物，跳设置修改连接；不成为另一套命令控制台。 | 仅使用已有取消、停止、刷新能力，无任意 Action/MCP 调用。 |
| 设置 | 配置 Provider、模型、任务链、Action 用途、预算及工具，批量应用 | 对话只保留运行方案快捷入口；外观等本地偏好不触发 Agent 重载。 | 后端草稿整批应用，本地外观即时生效。 |

首次配置路径：连接后端 → 设置 Provider/凭据 → 模型及 Provider 顺序 → LLM 链或专用用途 → Phase/Action 绑定 → 查看整批变更 → 应用 → 对话。已有可用配置时直接进入对话，不强制向导。

日常工作路径：发送目标 → 追加或回复问题 → 阅读 Action/Job 过程 → 打开产物 → 完成后从 Session 回看。知识阅读路径：搜索 Home/Memory → 阅读真实片段 → 打开全文/引用/反链 → 必要时将引用放入对话。知识整理路径：在 Home/Memory 明确发起一次 Reflection → 在运行观察查看排队及结果 → 回资源页刷新。

正常空状态不作为系统故障：没有活动 Turn 时 Context 提示暂无当前语境，没有 Job 时显示暂无后台任务，Memory 尚无文档时显示知识目录为空；MCP 已配置但未连接或未发现时引导显式刷新。提示当前事实及适用的下一步，不为填满页面而自动开始 Turn、Reflection 或外部连接；加载失败与空结果分别呈现。

### 0.4 开始编码前的阅读顺序

1. `AGENTS.md` 与本文：掌握所有权、日生命周期、读写边界和页面目标。
2. `docs/endpoint/frontend-integration.md`、`contracts/README.md`，以及当前页对应的 endpoint 文档与 `contracts/examples/`：取得真实请求、响应和分页结构。
3. `visualization/src/components/shell/AppShell.tsx`、`src/styles/index.css`、`src/utils/motion.ts`、现有 Chat/Workspace/Settings：识别要保留的体验和必须删除的旧 v1 假设。这里的 `src/` 均相对 `visualization/`。
4. 需要解释数据时再读对应 owner/route；不把后端存储路径、私有服务或模型执行逻辑搬到前端。

本次核对结论：页面范围和架构具备实施基础，主要工作是消费已交付契约、重组前端状态及补齐交互；本次静态核对未发现需要另设整体后端重构阶段的问题。具体退出条件以真实接口与页面验证为准，Mermaid/TikZ 的 Browser/Tauri 技术路径仍须 F0 验证。实施遇到具体缺口时按 §23 提交需求并继续独立部分，不能假定未提供的写入或调用接口已经存在。

## 1. 产品目标与实施范围

Visualization 是同一个 Agent 的交互、知识/资源浏览、配置和运行观察界面。用户能清楚地输入、追加、回答问题、选择运行方案，看到 Agent 使用的语境、行为和产物；前端消费正式状态，不在浏览器重新实现 Agent 调度。

本轮完整实现：

- 保留原版对话/Workspace 主要布局及成熟交互，适配最新 Turn、Context、Action、Search、Reflection 语义。
- 全面重组设置；保留原 Provider/模型/任务链对象编辑方式，加入统一草稿、整批应用、模型用途和运行方案。
- 新增 Home/Memory，扩充运行观察中的 Jobs/ACP/MCP/Environment。
- 结构化问题、追加/回复/补额、代码块扩展、资源链接路由、真实 Search 片段和模型调用详情。
- 前端本地主题/字体等偏好独立。生图在“模型与服务”内预留页面，仅说明尚未接入，不提供假配置保存或生图执行按钮。

不新增直接编辑 actual Home、持久 Memory、Session map 的页面；需要知识整理时发起 Reflection。不存在全局统一推理强度控件：不同用途使用独立链/模型，运行方案提供一致的切换入口。

## 2. 全局视觉与布局

沿用 `src/styles/index.css`、`src/utils/motion.ts`、现有 AppShell/NavRail/TopBar/StatusBar、ChatView/WorkspaceView 的视觉与交互。保留 Luminous 明暗主题、三层中性底、细边线、靛蓝至蓝色品牌光泽、现有领域色和克制动效。不为统一视觉而重新设计对话结构。

主导航：对话、工作区、Home、Memory、运行观察；设置/连接保留底部入口。默认不增加对话日期栏、话题侧栏、Session 地图常驻栏或全局模型参数工具条。Context 从 TopBar 右上按钮进入。

各页自行选择目录/列表/阅读结构；同一时间一个主详情 Drawer，内部资源以返回路径切换，不无限叠窗。地图/diff 可展开全宽，关闭后恢复原滚动、选择和草稿。

| 宽度 | 布局规则 |
| --- | --- |
| ≥1440px | 保留现有主区；资源页目录稳定，复杂详情可并排或覆盖 |
| 1100～1439px | 主区优先，页面目录可收起，详情按需打开 |
| 768～1099px | 目录用弹层，详情覆盖主区；输入框持续可用 |
| <768px | 紧凑导航与全屏详情；不挤出多列，表格/代码局部滚动 |

断点可按内容最小宽度微调，不用设备型号写特例。正文沿现有约 14px 的尺度并支持缩放；次级信息保持可读，关键按钮/错误不使用低对比小字。领域色说明来源，状态色说明运行结果。等待用户是稳定状态，不继续播放计算流光。

页面以对象、内容、操作为主体，不放愿景口号、每卡固定说明句或用“·”拼装的装饰文案。UUID、owner、shape、原始 ref 等在详情/高级区按需出现，不占据主阅读区。动画不延迟问题显示、提交按钮或真实状态；历史恢复不逐条重播入场。

## 3. 前后端接口与数据契约

### 3.1 接口目录

下表路径均以 `/v2` 为前缀。全部接口已在核对基线中提供；“已有”表示路由/服务契约可用，不表示当前项目已经配置好远端 Provider、ACP 或 MCP 服务。前端本轮完成全部对接。

| ID | 方法与路径 | 状态 | 用途 |
| --- | --- | --- | --- |
| API-01 | GET /health、/status；POST /restart | 已有 | 连接、ready、runtime、宿主重启 |
| API-02 | POST /turns；GET /turns/{id}；POST /turns/{id}/input、reply、grant、cancel | 已有 | 明确新轮/追加/回复/补额/取消 |
| API-03 | GET /turns/{id}/interactions | 已有 | 活动/保留句柄交互投影 |
| API-04 | GET /reflection；POST /reflection | 已有 | 可整理目标和同一根队列中的 Reflection |
| API-05 | GET /config?view=saved或active；GET /config/catalog；GET /config/actions?scenario=…；PATCH /config；POST /config/reload | 已有 | 设置值、声明、运行能力与保存/激活入口 |
| API-06 | POST /config/apply | 已有 | 整批保存并发布 generation |
| API-07 | GET/POST /config/presets；GET/PUT/DELETE /config/presets/{id} | 已有 | 项目命名方案 |
| API-08 | GET /days；GET /session/turns、/session/turns/{id}、/session/map、/session/inspect | 已有 | 日目录、历史对话和地图 |
| API-09 | GET /turns/{id}/context、/turns/{id}/context/segments/{segment_id}、/turns/{id}/context/inspect | 已有 | 当前 Context 只读浏览 |
| API-10 | GET /home/catalog、/home/content、/home/changes、/home/diff | 已有 | Home 阅读与变化 |
| API-11 | GET /memory/active、/memory/catalog、/memory/document | 已有 | 活动与持久 Memory |
| API-12 | /workspace 的 manifest/resource/blob/directory/move/tags/edit/append/trash/restore 路由，方法见 workspace.md | 已有 | 编辑、归档和大内容支持 |
| API-13 | POST /home/search、/memory/search、/workspace/search | 已有 | SDK owner 内容检索，返回 SearchPage |
| API-14 | GET /turns/{id}/jobs；POST /turns/{id}/jobs/{job_id}/stop；GET /turns/{id}/jobs/{job_id}、/turns/{id}/jobs/{job_id}/output | 已有 | Job 状态与输出 |
| API-15 | GET /subagent | 已有 | ACP 目标及 generation 连接状态 |
| API-16 | GET /expand/servers、/expand/tools；POST /expand/servers/{server_id}/refresh | 已有 | MCP 快照及明确刷新 |
| API-17 | GET /events；WS /events/ws | 已有 | 定向过程读取、变化通知 |
| API-18 | GET /resources/resolve | 已有 | Link/ref/相对引用解析为逻辑 ResourceLocator |

### 3.2 页面权威来源

| 内容 | 正式来源 | 实时过程 |
| --- | --- | --- |
| 当前状态、队列、问题、预算 | API-01/02 | 事件触发重新读取 |
| 当前已受理交互 | API-03 | 稳定 identity 合并 |
| 完成 User Turn 与 Session map | API-08 | 完成/Organize 事件失效 |
| 当前模型已安装语境 | API-09 | 固定批次 install 通知 |
| 资源与知识 | API-10/11/12 | owner 变化通知 |
| 页面搜索结果 | API-13 | 冻结结果，用户明确重搜 |
| 模型请求与动作细节 | API-17 | 按 Turn/task/call/search 有界查询 |
| 配置与真实方案 | API-05/06/07 | 应用后重读 |
| 外观、页面选择、编辑草稿 | 本地状态 | 不成为后端业务事实 |

禁止用 raw events 全量重放代替 Session/manifest/TurnSnapshot，也不另建浏览器持久聊天数据库。前端可以做短暂 optimistic 展示，但必须显示发送中/失败，不能将未受理文本当作 Agent 已看到。

### 3.3 必须理解的 DTO

- ResourceLocator：逻辑 link/ref 加实际需要的 day、turn_id、view；不拼物理路径。
- InteractionPage：items 中保留各类交互的 id/role/ref/text 及适用的 question_id/reply_to/delivery；Turn/day 在页级。pending_items 使用 record_id/sequence/kind/payload/state，表示已受理而尚未安装的输入，与正式交互顺序分开；queued_request 只是尚无活动 Context 时的请求摘要。
- ContextOverview/SegmentView：本次 installed 状态，segments 中的 owner/slot/shape/root_refs、容量与加载引用，以及 resolved_references。
- Context 段正文：turn_id/segment_id、messages[{message_index,message}]，可选 next_continuation/content_fragment；不使用资源页的 items 字段。
- 资源读取页：Home/Memory 使用 items 中的 ref/text，locator/direct_refs 等位于 metadata；Context/Session Disclosure 使用带 kind 的 items。按实际 owner 协议消费 content_fragment/next_continuation，不假设通用顶层 text/content。
- Workspace 文本：使用 text/complete/editable/truncated/next_continuation，不能套入上述 items envelope。编辑需显式取得完整正文，见 §10。
- SearchPage：result_ref、scope/source、items、coverage、page/continuation；保持后端原结构。
- JobOutputPage：有界 channel/text、实际顺序、result_locators、next_continuation；不同流不强排精确因果顺序。
- PresetSummary：id/name/description/included_scopes/active_match/saved_match/validation_issues/updated_at。

普通列表默认 30、上限 100；普通文本页默认 16000、上限 64000 字符；Search/Disclosure 服从各 owner 预算。前端不靠截断 JSON 代替分页。continuation 失效与单纯网络错误分开显示，不自动重跑可能调用模型的查询。

分页适配须保留这些区别，不能把所有响应统一转换成 `data + cursor` 后丢失生命周期和覆盖信息：

| 响应族 | 正文/成员 | 续读与结束依据 |
| --- | --- | --- |
| 普通 owner/Disclosure 页 | items；可有 content_fragment | 消费本页后判断 next_continuation；空 items 不能判空或判结束。 |
| Context 段正文 | messages；可有 content_fragment | 同一 JSON fragment 基础协议，集合字段不同。 |
| Workspace 文本 | text、complete、editable、truncated | 按该接口的 next_continuation 读更多；完整编辑另用 full=true。 |
| Search | items、coverage、page、result_ref | 有下一页时使用响应顶层 continuation；不将 page.continuation 当成统一游标，也不把结果为空当作失败。 |
| Job output | items 中的 channel/text | next_continuation 用于增量读取，运行中空页可继续轮询；Job 执行终态与输出阅读进度分开，truncated 不是丢失标记，见 §14。 |
| 日期/Reflection availability | 日期列表或 memory_days/missing_daily_days 等 | next_before；Reflection 列表不是运行队列。 |
| Observation replay | events 与窗口信息 | next_sequence；过滤后 events 为空也可能已经推进扫描位置。 |

`content_fragment` 是一个超长 JSON **单项**的序列化分片，不是 Markdown 文本截断。封装一个轻量的顺序解码器：在同一读取身份下拼接 `encoding=canonical_json` 的 text；完整 JSON 成形后解析并按所属页类型交付一次，然后清空该项缓冲。不要等待 next_continuation 消失才尝试解析，因为该项结束后可能还有其它项；也不要先检查 token 而漏读最后一片。协议未提供 item_id/last 标记，不能自己假定存在。未完整时显示加载进度，不把 JSON 片段当正文渲染；重开或失效后重置缓冲，不跨资源、段或快照拼接。保留后端不透明 token，不解码并改造它。

普通读取页绑定实际内容，不能统一解释为后端长期保留的冻结快照。活动 interactions 中新增输入、pending 安装为正式交互或 Action 结算，都可能改变分页绑定；Context 段正文变化也可能使旧 continuation 失效。已经读取的内容可以保留展示，未读部分不能承诺继续沿旧 token 取得。Interaction 的分片解码后仍按正式交互或 pending 的实际结构分发，不能因为它来自 fragment 就统一当成正文消息。

### 3.4 查询参数与错误处理

| API | 页面使用的参数 |
| --- | --- |
| API-03 | continuation，返回 items 与 pending_items，后者不强行排序成 Trace |
| API-04 | availability: before/limit；发起整理: kind=home或memory、target_day、instructions，Memory 必须明确 target_day |
| API-08 | /days: before/limit；turns: day/continuation/limit；turn: day/continuation；map: day/continuation；inspect: day/ref/query/continuation |
| API-09 | overview 使用明确 Turn ID；segment 正文按返回 continuation；inspect 使用 ref/query/continuation |
| API-10 | catalog: view/space/query/continuation；content: link/view/continuation；changes: continuation；diff: link/continuation |
| API-11 | active: day/continuation；catalog: kind/query/continuation；document: link/continuation |
| API-12 | 归档 GET 携带 day；resource 阅读使用 continuation，完整编辑使用 full=true；blob 按需要使用 Range |
| API-14 | 明确 turn_id/job_id，output 使用 continuation |
| API-16 | tools 使用 server_id/continuation，详情可按 tool_name；refresh 明确 server_id |
| API-17 | after/mode/limit/instance_id；按需 turn_id/task_id/call_id/search_id/step_index/through，step_index 配合 search_id |
| API-18 | reference、可选 origin_link/day/turn_id/view，优先使用响应中已有 resolved locator |

错误外壳是 error.code/message/details。只有结构化 details 提供字段定位时才定位控件；通用 `422 request.invalid` 当前不返回字段定位，显示表单级错误并保留输入，不解析 message 猜字段。`config.invalid` 有可用 key 时定位配置对象，否则显示整批应用错误。409 config.activation_unavailable 保留草稿；404 不自动跳当前同名资源；context.unavailable 停止 live 读取；resource.unresolved_origin 显示需要明确来源。search.scope_required 提示缩小范围，search.view_expired 提供重搜，search.source_unavailable 显示来源问题，search.operation_failed 展示有限步骤失败，均不伪造空结果。已有接口 code 沿真实 schema；Observation gap 是缺失提示，不是断线。后端模块失败和清理诊断按作用范围呈现，前端不自动重启。

| 输入/控制错误 | 前端处理 |
| --- | --- |
| agent.queue_full | 新轮未入队，保留正文与原请求身份，提示队列已满，不自动改为追加。 |
| turn.inbox_full | 追加或回复未受理，保留草稿，提示本次输入超过受理容量；不简单断言都是排队数量已满。 |
| turn.command_rejected、agent.not_ready | 刷新目标 Turn/status；按实际问题、预算及生命周期决定可用操作，不单凭错误码断言等待已过期。 |
| turn.invalid_answer、request.invalid | 保留选择和文字；有明确结构化定位才标注控件，否则在卡片或表单显示错误。 |

等待身份已失效时停止提交旧 question_id/request_id，保留可复制或转入 Composer 的未发送内容；转为新轮或补充须由用户明确选择。网络结果不明确时先核对正式状态和原请求身份，不自动换 ID 重发。

状态码只能辅助分类：Endpoint 尚未绑定服务的 `service.unavailable` 与 SDK owner 不可用有不同 HTTP 状态，Context 关闭又是独立语义。使用具体 code/details 与当前操作决定提示，不能把全部 409 当配置冲突、全部 503 当连接断开。

### 3.5 前端数据流与刷新约定

前端只维护三类状态：后端正式快照/实体缓存，当前请求与编辑草稿，以及本地 UI 偏好。事件是增量过程和失效通知，不是另一个业务数据库。所有页面共用连接、transport、身份范围与错误映射；每个 owner 的 client 保留自己的请求和结果类型，不建设任意 RPC 或万能资源模型。

| 变化 | 刷新对象与 UI 行为 |
| --- | --- |
| Turn 状态/交互 | 刷新 status、目标 TurnSnapshot 和 interactions；立刻更新问题/预算，不等待过程动画。 |
| User Turn 完成 | 查正式 Session 记录；所需历史页就绪后按 turn_id 接替当前交互，不能用首页清空整轮已读内容，详见 §7。 |
| Context install | 标记 overview/当前段可刷新；保留已读内容与位置，不保证旧 continuation 仍有效，刷新后开始新序列。 |
| Workspace/Home/Memory 内容 | 失效对应目录/文档；脏编辑器保留草稿，Search 冻结结果不自动重算。 |
| apply/reload/restart | 重取 status、active/saved、actions、方案与代级运行能力；废弃旧代 Search/Context/Job 句柄。restart 不假定 Endpoint instance/cursor 一定改变。 |
| 日切 | 重新获取活动 day、Session、Workspace、活动 Memory；已经打开的历史资源继续绑定原日。 |

主连接订阅状态所需事件层级；过程页面按需使用 verbose，模型详情通过带过滤条件的 HTTP model replay 读取。WS 的 mode 是层级，不是 Turn 过滤器。HTTP 过滤读始终使用返回 next_sequence 推进，历史详情固定 through，避免无命中页循环或不断追逐新增日志。轻量合并同一批失效即可，不引入前端恢复调度器。

续页返回内容绑定失效时，结束该读取序列并清除未完成的 fragment 缓冲，从无 continuation 的新请求刷新；旧请求晚到的页面不得进入新序列。保留已展示内容和滚动位置，直到新读取可接替；不能将新旧页拼成一份声称完整的快照。活动交互按 §5.1 的身份更新已取得条目，不以一次不完整响应中未出现某项为由删除它；完整新投影或正式 Session 接替后再收敛展示。持续变化导致刷新仍失效时保留内容与明确刷新入口，不无限重试。该只读刷新规则不用于自动重跑 Search 模型步骤。

### 3.6 页面能力的正式依据

| 页面判断 | 读取来源与消费字段 | 使用边界 |
| --- | --- | --- |
| Action 模型实现及目标选择 | API-05 actions 中对应 Action 的 model_uses：consumer、implementations、options 约束、embedding_owner、binding | 不从动作名称或 executor 推断模型能力；草稿不改变当前运行标签。 |
| 页面 Search 来源、操作、条件和预算 | API-05 actions 中对应 home.search、memory.search、workspace.search 的 retrieval 与 tool.schema | 与 SDK owner 使用的已登记 policy 对齐；页面额外限定 context=none，不以 Action visibility/granted 禁止独立 SDK 浏览。 |
| 配置可写位置及原子对象 | API-05 config/catalog 的字段、集合声明，以及 config 的 fields/sources；Action 文档另读 actions 的 source/editable_paths | 用实际 source_id/path；只读归属和完整 map/数组边界保留。 |
| 配置及方案能否激活 | API-05 config 的 activity.can_reload 及活动原因 | API-01 的表面 idle 不能代替激活条件，最终以 apply/reload 回执为准。 |
| 当前问题、预算与取消状态 | API-02 TurnSnapshot 的 question、budget_request、cancel_requested、state、result | 不从日志文字或旧问题卡推断当前控制身份；当前没有公开 Inbox 开放标志。 |

API-13 的 HTTP 请求体是动态 JSON，OpenAPI 请求壳不足以单独生成搜索表单。F0 同时核对对应 retrieval/tool.schema 与真实请求样例，页面仅消费实际使用的声明，不另建通用 schema 执行引擎。能力描述缺失或冲突时按 §23 记录具体缺口，不通过发送模型请求试探有哪些操作。

## 4. P00：应用外壳、连接与共享详情

**页面语义与使用路径：**连接代表正在查看哪个项目的 Agent。主导航切换业务空间；StatusBar 回答当前是否可用，详情抽屉让用户沿资源链接深入后回到原页面。正常启动恢复最近页面即可，首次无连接才显示连接表单；不把调试信息铺成首页。

启动顺序：建立连接 → health/status 确认 v2、project/instance/generation/ready → 加载当前页正式快照 → 订阅 events。ready=false 时状态页仍可读，不展示旧连接的资源为当前内容。

修改 `api/connection.ts` 和 Tauri discovery 的版本假设；以握手为准，删除硬编码 protocol_version=1 与 v1 transport。连接信息与 UI 偏好分开，切换项目不携带上个项目的草稿、Turn 或 Search 句柄。

Browser 与 Tauri 均提供手动连接表单，地址和 token 分开输入：

- 地址接受 `IP:Port`，如 `127.0.0.1:1430`，省略协议时按 `http://` 解释；也接受显式 `http://` 或 `https://` 地址。`1430` 是可输入的本地调试地址示例，不是固定后端端口；只有 Endpoint 实际监听或转发至该端口时才能连接。
- 除 health 外，读取和操作仍需有效 token。手动连接填写 token，本机发现可取得实例发布的凭据；不因地址是 loopback 而跳过鉴权。
- HTTP、blob 与 WebSocket 从同一客户端连接地址构建，WebSocket 按协议使用 ws/wss，并沿现有 token 首帧鉴权。转发须同时承载 HTTP 与 WebSocket；不能只替换普通 API 地址而遗漏流和媒体。
- Tauri 的项目发现只读取客户端本机项目/实例记录，不把远端项目路径当作可访问的本地目录。远端连接填写已有隧道/转发的可达地址；`127.0.0.1` 始终指运行客户端的机器。协议和凭据不变时，改 IP:Port 即可切换入口，不必修改后端监听地址。
- 实例身份以 health/status 核对，但传输继续使用客户端可达地址，不被后端报告的内部 loopback host/port 覆盖。

连接入口支持项目/后端地址与真实状态、手动重连、明确的宿主重启。先保存 status 返回的 instance 与事件 cursor，再加载快照，并从该 cursor 订阅/补读过程；快照期间的新事件用于失效刷新，交互按 identity 去重，不因订阅开始较晚漏掉问题。旧 project/generation 的异步响应不得覆盖新连接状态；日志 gap 不清空已经由 Session 读出的对话。关闭页面或 WebSocket 不取消 Agent；重启是显式按钮，不把前端刷新变成重启。

共享 Inspector 保存来源/返回栈，支持关闭、返回、展开宽视图、复制真实链接。跳转后焦点落在详情标题，关闭回触发按钮。常规错误就地呈现；只有应用级连接状态才用全局提示。

使用 API-01/17；资源详情使用 API-18 路由，禁止自行从观测正文解析本地路径当作下载地址。

## 5. P01：主对话与 Composer

**页面语义与使用路径：**这里是唯一的日常交流主入口。用户发送目标后可继续阅读、追加约束或回答问题，Agent 等待时无需另开一个任务页。回答中的产物和知识引用可打开详情，再回到原消息位置；对话的历史和运行过程是按需入口。

保留原 ChatView 的消息宽度、输入区、过程折叠、滚动锚定和 typewriter/motion 行为。顶部不新增日期条；底部输入区旁加入紧凑运行方案选择器，默认只显示方案名或自定义状态，展开才显示预算/模型用途摘要。

### 5.1 状态与操作

| 正式状态 | 输入行为 | 其它控制 |
| --- | --- | --- |
| idle | 新 User Turn | 允许切换方案 |
| 活动 User Turn preparing/running | 已有明确活动 Turn ID 时默认补充该轮；菜单可排队下一轮，实际受理以回执为准 | 停止当前 Turn |
| waiting question | 卡片内答复；Composer 可独立补充或排队 | 不把补充自动当 reply |
| waiting budget | 独立补额卡片 | 可与问题同时显示；停止仍可用 |
| Reflection 运行 | 普通消息排队 User Turn | 跳转 Reflection 详情，不追加到维护情景 |
| finalizing | 新消息排队下一轮 | 显示收尾，不能再向关闭的 Inbox 追加 |
| finished/句柄消失 | 使用当前状态决定新轮 | 历史内容只读 |

新轮 `POST /turns` 使用 `kind=user,text,command_id,metadata.client_message_id`；追加使用 `/turns/{id}/input` 的 text/input_id。普通聊天不使用终端式 `/input` 解析斜杠命令。队列项提供正文摘要和取消，取消仍走该 Turn 的 API-02。

发送中保留本地 ID。成功受理后按返回 identity 替换状态；重复 accepted=false 不是发送失败。失败保留文字与重试入口；Turn 已关闭时提供“作为下一轮发送”，不能悄悄改请求对象。取消回执仅表示已受理意图，实际结束后再关闭等待卡片。

Composer 明确显示“发送新一轮/补充本轮/排队下一轮”的当前意图，但保持原输入框布局，不增加全宽模式面板。preparing 阶段使用 status 已确定的活动 User Turn ID，不等待未提供的 Inbox 开放字段；只有排队请求而无明确活动 User Turn 时，普通发送创建下一轮，不猜测追加对象。提交固定本次意图和目标，状态随后变化不能悄悄改发到其它 Turn；正常拒绝保留草稿，并按 §3.4 刷新状态、提供显式下一轮入口。网络结果不明确时先核对对应请求身份和正式状态，不无条件再发一个新 ID。

交互流区分排队请求、已接受但尚未安装的 pending_items、已进入 Context 的 items 和模型已看到的 delivery 状态。待投递内容可以留在流中显示“待处理”，但不能编造 Trace 位置。正式消息以 interaction id/ref 管理，Question 用 question_id 关联；当前 Trace 身份与归档 Session 身份不保证相同，完成时按 Turn 接替。

| 衔接 | 身份与显示规则 |
| --- | --- |
| 新轮发送 → 已入队 | 保存 command_id 与回执 turn_id；client_message_id 仅为客户端关联信息，不代替正式 Turn 身份。queued_request 可能只有摘要，不冒充全文。 |
| 追加 → pending → 正式交互 | 同一 input_id 对应回执和 pending_items.record_id，安装后对应 interaction.id；从“已受理、待处理”更新为 installed/visible，不再追加第二条相同用户消息。 |
| 问题 → 回复 | question_id 关联当前问题与回复；回复回执 record_id 用于衔接 pending 与正式用户回复。重复请求的 accepted=false 按已有受理事实处理，不重新生成一条回答。 |
| 当前交互 → Session | 以 turn_id/day 切换正式来源，不能要求 Trace ref 等于归档 ref；分页接替遵循 §7。 |

pending_items 的缺席可能只是分页尚未读到或已经安装，不能据此标记发送失败。安装后的顺序以正式交互投影为准，不能长期沿用本地发送时间或 Inbox sequence 排列整轮事实；续页与刷新按 §3.5 处理。

问题、预算卡片立即出现，不排在长动画之后；用户上滚阅读时不抢滚动，显示“有新内容/待回复”入口；回到底部恢复跟随。窗口恢复不逐条播放历史。

### 5.2 运行方案快捷入口

列表展示名称、当前匹配、有限说明；“管理方案”进入设置。展开摘要包含受管组和关键预算；不提供虚假的统一模型/推理强度。

只有后端声明可应用时允许点击激活；运行期间可查看方案，但不显示已经切换的假状态。应用走 API-06，成功后重取 API-01/05/07；随后用户正常发送。切换与发起 Turn 是两次明确操作，不暗示原子性。

快捷入口与设置中的方案应用共用 §15 的草稿处理规则；存在未应用修改时不能绕过确认直接切换。

无方案或已偏离方案显示“自定义”。模型簇的 UI 收起与运行方案本身不是同一开关。

## 6. P02：提问、追加与回复卡片

**使用路径：**Agent 提问时卡片直接出现在对话中；用户选择、可加说明、提交，随后保留问题和回答的完整记录。Composer 仍可作独立补充。卡片服务于同一轮继续工作，不是一个新的聊天主题，也不是通用授权弹窗。

### 6.1 呈现

agent.question 在原对话流内渲染：正文在上，选项为可点选卡片，必要说明在选项内，最后为“其他”输入；底部提交/提交中/已答状态。A/B/C 是视觉编号，提交使用稳定 option_id。

选择后可附 comment；默认不点击即提交，用户按“回复”确认。Other 使用自由文本。问题无 options 时直接文本输入。allow_other=false 不自行增加可提交自由回答，但 Composer 的独立补充仍存在。允许键盘选择、Tab 和明确提交，不用全局单键快捷键误发回复。

已回答卡片显示实际问题、所选 label 和补充文字，用户回复保持用户消息样式；不要把问题从历史删除或只剩一个“A”。补充输入以用户消息显示其关联 Turn，不伪装成新的完整问答。

### 6.2 协议与三种模式

QuestionContent 为 text/options[{id,label,description?}]/allow_other；最多 8 个选项，ID 唯一。`tinysoul-question` fence 的 JSON 使用 question 字段，后端归一化为 text。代码块本身不含执行地址或运行身份。

```json
{"question":"如何继续？","options":[{"id":"execute","label":"开始实施"},{"id":"explain","label":"进一步讨论"}],"allow_other":true}
```

- active：以 API-02 当前 TurnSnapshot.question 的待答身份为准；API-03 提供交互正文和关联。历史交互里仍有 question_id 不代表可以继续提交 reply。
- compose：普通模型回答里的同类块，仅将选项正文放入 Composer，由用户发送。
- readonly：历史 ask 或已结束问题，只读显示，不发送过期 reply。

回复请求：

```json
{"question_id":"q1","answer":{"kind":"choice","option_id":"execute","comment":"先完成后端"}}
```

Other/自由回答：`{"question_id":"q1","answer":{"kind":"text","text":"我的补充……"}}`。后端校验并生成规范模型文本；前端不提交字符串 response 或只发送“A”。格式错误的普通 fence 回退可读代码，不制造等待状态。

预算卡片使用 request_id/count 调用 grant；回复不补预算，补额不答问题。若等待过期，刷新实际状态并保留未发送文本，不反复重试旧 question_id。

TurnSnapshot 恢复的问题即刻可见，不等待 interactions 翻完；随后 interactions 或 core.ask 过程到达时，以同一 question_id 收敛到一个卡片，不在过程卡和正文中制造两个可提交表单。等待卡片是消息流中的定位目标，滚动到底部之外也有紧凑的“待回复”入口。选择只保存在当前问题草稿，提交成功后先按回执显示已受理，再从 pending/正式交互显示后端规范答案；刷新已答问题使用正式交互而不是浏览器选择缓存。

## 7. P03：历史对话与 Session

**页面语义与使用路径：**历史首先用于回看原话，Session map 用于理解 Agent 对当日交流的组织。先选日、再选 Turn、再展开话题或证据；地图不能替代对话正文，也不要求用户先理解图论才能阅读历史。

沿用对话历史/更多入口打开日期与 Turn 列表，不新增常驻日期栏。日期目录使用 API-08 /days；选择日期后取 Turn 摘要，打开一轮才取交互页；不读取整日模型日志作为历史。

摘要使用真实 initial/output excerpt、状态、问题数量。活动/排队项与已完成 Session 项分开；完成时以 turn_id 将活动内容整体接替成 Session 投影，避免 append 两套相同正文。必要持久化失败显示 TurnResult 的有限事实，不伪造“已保存”。

接替前按需取得能够承接当前展示范围的 Session 页；第一响应仍有 continuation 时，不能把它视为整轮内容并删除尚未读到的消息。所需历史页未就绪时保留原阅读内容及历史加载状态，不混排两套正文；就绪后切换到 Session 来源并恢复阅读位置。若不能确定当前展示范围已被历史页覆盖，继续分页核对该轮，读完后再整体接替。此操作只处理正在完成的目标 Turn，重新打开历史仍按需分页，不预读整日。历史不可用时显示已取得的有限结果和未能恢复历史的状态，不宣称持久化成功。

Session map 从 Context 中的 Session 入口或历史详情进入。默认阅读列表：话题/解释入口、相关 Turn、未归类交互；关系图作为展开视图。thread/note 与不可变事实视觉分开，有证据链接；共享节点与回路保留同一 ID，导航树不作为数据模型。

展开节点调用 /session/inspect 的 ref/continuation/query，显示真实 DisclosurePage；query 只定位该范围。用户可把整理要求写入 Composer，由 Agent 使用 Organize，不提供手改 map 按钮。历史日期只读，不承诺跨日语义图。

历史问题保持完整选项与回复。没有新选项 ID 的归档按原文显示，不能通过文字猜新协议身份。历史链接始终带 origin day/turn；“打开当前资源”若与历史不同要明确标识。

地图初始仅加载目录与有界节点，选中后披露相邻关系和证据；不一次布局整日全部图。解释修订、撤回、合流按 owner 的当前状态呈现。Session 为空时显示当日尚无完成对话；有事实但尚无解释时照常列出 Turn，不伪造自动话题。Reflection 运行记录在运行观察读取，不塞入 User Session。

## 8. P04：Context Drawer

**页面语义与使用路径：**用户从右上 Context 按钮查看这一轮的背景、过程和工作状态，选中某段阅读，再按线索进入下一层。想知道“某次调用究竟给模型发了什么”时转到该次模型调用，而不是把现在的 Context 当成当时输入。

右上原 Context 按钮打开；默认当前活动 Turn。无活动 Context 时显示“当前没有运行中的语境”，可跳转历史 Session 或已记录模型请求，不展示上轮缓存为当前内容。

首屏只取 API-09 overview，按 Background、Trace、Working 分组；每段显示名称、简短状态与必要用量。选中段才读取正文。技术 descriptor/owner/shape 放详细信息，但 renderer 由它们驱动，不靠名称猜。

| 形状/内容 | 主要视图 | 交互 |
| --- | --- | --- |
| State | 当前字段/状态 | 阅读，按声明查看引用 |
| Heap | 顶层线索、默认/已加载项、可阅读资源 | 按 owner 路由深读，标识哪些内容来自已安装语境 |
| Stack/Trace | 热记录与折叠节点、原事实顺序 | 展开节点、续页、回到父入口 |
| Map/Session | 事实/解释入口及历史交互 | 列表优先，可展开关系图与证据 |
| Working | plan/todos/milestones、Workspace 摘要、连接/Jobs 现态 | 跳对应详情，不常驻全部资源正文 |

段正文是本次已安装视图，不是 owner 最新文件。资源详情打开完整 Home/Memory 不等于该内容已经进入 Context。UI inspect 仅用户阅读，不执行 core.context.inspect、不追加工具结果、load/evict 或解除模型保护。

形状决定阅读布局，capabilities 和 ref owner 决定实际请求；两者不可互相推断。当前 Home/Memory Heap 声明 SELECT/RECLAIM，不因此提供 Context inspect handler，root_refs 也可以为空。具体路由为：

| 阅读目标 | 使用接口 | 说明 |
| --- | --- | --- |
| 任意段当前已安装正文 | API-09 segment messages | 即使无 root_refs 仍可阅读。 |
| 声明可 Inspect 的 Trace/Session 等根或子 ref | API-09 context/inspect | 使用返回的原 ref，保留 Turn 绑定。 |
| Home 已加载/可用链接的资源全文 | API-18 必要解析后 API-10 content | 标注资源 view；这是 owner 当前内容，非重新安装段正文。 |
| Memory 动态/持久链接的内容 | 已解析 locator 或 API-18，再调用 API-11 | 先保留动态绑定，不猜 current/latest 的目标。 |
| 已归档 Session/历史证据 | API-08 inspect | 带明确 day；不继续调用关闭 Turn 的 live inspect。 |

capabilities 是能力说明，不意味着前端应显示模型侧 SELECT/RECLAIM 控制按钮。只对实际支持的读取范围提供 query；打开资源不会成为“已经让 Agent 看过”。

动态 memory 引用使用响应已解析 locator；无法确定原绑定时不自动打开当前 latest。能力未声明 query 时不显示范围搜索控件。usage 字符数不标成 token。

Context 更新时保留当前已读内容和阅读位置，显示可刷新提示；这不表示后端保存了可继续翻页的旧段快照。旧 continuation 失效时按 §3.5 结束序列，刷新 overview 后按需重取段，不能将两份内容的分页混在一起；未变化页面也不因收到一次 install 通知就被前端武断判为失效。Turn close 后停止续读 live Context，已打开内容标记为刚才捕获的视图，历史跳转使用 API-08/17。

## 9. P05：Action、Search 与模型调用详情

**使用路径：**在对话过程摘要中先看做了什么和结果，疑问时再打开参数、真实片段或模型调用。该页解释已发生的事实；用户通过主对话要求后续行动，不在详情里重新执行任意 Action。

保留原过程入口、ActionGlimpse 与折叠卡片的主要风格。路径是 Turn → Cycle → Phase → Action/模型调用；失败、未执行、取消、结果未知按正式执行状态展示，不能都当工具返回文本。

### 9.1 Action renderer

显式注册：精确 Action ID → 结果族 renderer → 通用结构视图。renderer 只处理呈现与导航，不执行后端动作。Action ID 以当前 Action Catalog 的 canonical 名称为准，迁移时删除旧 registry 名称和兼容映射；未知 Action 仍走通用 JSON 回退。

| 结果族 | 默认展示 | 展开内容 |
| --- | --- | --- |
| Search | 来源、步骤与结果数，首批真实片段 | query/criterion/条件、逐步数量、证据/覆盖、原始结构 |
| Inspect/read | 所读资源与片段 | 原始范围、DisclosurePage、更多资源导航 |
| Workspace/Home/Memory 写入 | 操作、目标与结果 | 当时记录的变更片段/diff；打开当前资源另设按钮 |
| Web 搜索/抓取/页面发现 | 来源网页、标题和提取结果摘要 | 真实链接、读取范围、产物与有限失败 |
| Workspace 分析/生成/转换 | 输入资源、结果摘要与输出产物 | 实际分析内容、格式、模型调用或转换结果 |
| execution | 命令与状态 | 输出/退出结果、Job 或产物链接 |
| 等待/Job 控制 | 等待对象、条件与实际状态 | Job 详情、等待结果与相关控制事实 |
| ACP | 委派目标、Job 状态 | 连接、任务输入、待处理请求、结果 |
| MCP | server/tool 与结果摘要 | 参数、真实 schema、返回内容 |
| Session 整理 | 解释入口与变更摘要 | 相关成员、证据和导航，不暗示改写交互事实 |
| Home review/Memory 持久写入 | 处理目标与实际提交结果 | review 决定、文档引用和当时可用的变更信息 |
| core.reason/answer | 模型实际披露的内容 | 关联 Task、引用与产物；core.ask 复用 §6 问题卡 |

没有历史 before/after 就只显示操作和 locator，不能查询当前文件充当历史差异。Unknown renderer 保留可读 JSON，不吞掉结果。正常视图不堆叠所有内部键。

F4 按当前 canonical Action Catalog 建立覆盖矩阵，逐项记录 Action ID、结果族、摘要字段、展开内容、资源/Job/模型导航以及代表性样例。下列动作须明确核对，不能因为已有通用回退就视为完成：

| 现有动作 | 核对重点 |
| --- | --- |
| web.search_by_kimi、web.fetch_with_trafilatura、web.fetch_with_defuddle、web.discover_pages | 外部网页与内部 Search 分开；呈现真实来源和提取产物。 |
| workspace.analyze、workspace.compose、workspace.convert_with_pypdf、workspace.convert_with_markitdown | 区分分析、生成与转换，提供真实输入/输出资源入口。 |
| core.wait、core.job.status、core.job.wait、core.job.stop | 区分等待条件、状态读取和停止意图，不把停止回执冒充已结束。 |
| core.session.organize | 只描述语义解释及证据变化，不显示为编辑原始会话。 |
| home.diff、home.review、memory.write_daily、memory.write | 明确 Reflection 处理对象、提交结果与读取入口，不添加直接审核/编辑按钮。 |

表中是必核对项，不替代完整 Catalog 清单；基础读写、目录/标签/回收站、execution、ACP、MCP 和 core 动作同样要有映射。一个动作只选主要展示方式，可以组合共享结果组件。适合通用结构视图的已知动作在矩阵中说明理由，未适配不能记为通用视图已验收。plan 现态与变化沿实际 Context/Control 意图呈现，不据此注册不存在的 core.plan Action。每个结果族选能区分真实行为的成功、失败或等待样例，不为每个 Action 复制组件和测试。

### 9.2 Search 卡片

source query/backlinks/directory 发掘候选，refs/result 是已知入口；steps filter/select/rerank 按实际顺序显示。每个 criterion 独立，不把 query 自动改写为所有步骤的条件。

条目显示 title/ref、真实 evidence.text/位置、相关命中。用后端 matches 的区间高亮，不重新对整份结果做 lexical 筛选。Embedding 深层命中必须保留；LLM basis 表示所给真实片段指认，JEV Score 不虚构理由或“正确率”。

高亮范围 start/end 是片段 text 的零起始、尾后字符区间；后端 Python 的 Unicode 码点与 JavaScript UTF-16 索引不同，用码点映射后再切片，验证中文与 emoji，不让高亮错位。无 matches/basis 时正常显示真实片段，不在前端补造语义命中。

默认只显示必要覆盖提示，展开区区分来源完整性、内容快照覆盖、模型输入覆盖、页面预览覆盖。source_score 与 evaluation 的 score 不混成同一排行分数；result 派生新请求后不能继续展示旧评估。

卡片展示 Agent 实际返回的页面。其 continuation 属于原 Turn/profile，不能交给页面 API-13 翻页；Turn 结束不保留假可用游标。本轮不提供直接浏览 Agent 未返回结果页的按钮。用户可打开真实资源，或把“继续该搜索”的要求填入 Composer。

### 9.3 模型调用 Inspector

按 API-17 定向读取，打开时固定 through 上界；LLM 用 task_id，JEV/Embedding 用 call_id；Search 关联 search_id/step_index。缺失记录显示观测不可用/已截断，不从别的调用拼补。

| 类型 | 详情 |
| --- | --- |
| LLM | task profile、consumer、model/provider attempts、实际 usage；按真实顺序的 MessageStack、工具作用域、TaskPrompt、已记录输出 |
| JEV | 用途与 Provider、评分 criterion/候选真实输入覆盖、Score、select 阈值或 rerank 结果 |
| Embedding | 用途/模型/Provider、实际内容覆盖、维度/批次、可用调用结果与贡献信息 |

LLM 左侧来源目录可按 Background/Trace/Working/TaskPrompt 定位，正文仍保持真实消息索引顺序；domain/action guidance 依据 provenance refs 展示，不猜文本标题。标明这是 TinySoul provider-neutral 输入，未记录供应商 HTTP 包就不称“网络原始请求”。只展示实际披露的 reasoning，不声称能展开供应商内部推理。

保留现有导出入口，但导出范围来自实际保留记录并附缺失说明，不通过 UI 拼造完整历史。

## 10. P06：工作区

**页面语义与使用路径：**这里是用户与 Agent 共同使用的当日文件空间。用户先从目录或回答中的产物链接定位文件，再预览/编辑，保存到实际工作区。日期切换用于回看归档，不把历史文件变成当前可写文件。

保留左侧文件/回收站与右侧编辑/预览，沿用当前目录宽度、标签与编辑体验。标题栏放路径、保存状态和必要操作；搜索与日期浏览按需展开，不常驻新仪表盘。

- 首次取 API-12 manifest；打开文件取 resource/blob。普通读取使用 text 与 continuation；进入编辑显式 `GET /v2/workspace/resource?link=…&full=true`，检查 complete/editable 后才启用覆盖保存。不得把第一段 text 当完整文件提交。
- 使用现有 directory/move/tags/edit/append/resource/blob/trash/restore，显示 owner 正式结果，不重新引入 digest/revision/CAS。
- 目录内名称筛选即时；点击“搜索内容”使用 API-13，scope 可为 Workspace/目录/文件，literal/regex 仅在能力支持时出现。
- 结果点击定位真实行/片段；引用可复制或填入 Composer。
- 归档从 /days 选择，所有 GET 明确 day；历史只读，不将归档内容 PUT 到当前同名路径。
- 外部变化时保留本地未保存草稿，显示“重新载入/继续编辑”的明确选择；未修改文件可以刷新。
- blob 支持 Range；图片、音视频、其它文件按实际 media_type 处理，未知类型提供下载。统一 Bearer transport 获取 Blob 后创建并回收 Object URL；直接把鉴权 endpoint 填进 img/video 的 src 不会自动附上请求头。大媒体的分段播放只在完成真实 Range 集成后声明支持；否则明确提供下载，不伪造可播放状态。

只有原有或明确支持的上传/创建流程调用后端写入；拖入文件失败保留清晰错误，不自动发起 Agent Turn。日切后当前列表切换，仍打开的归档资源保持明确日期。

写入路由只作用于活动 Workspace，不携带历史 day 来模拟归档编辑。活动文件的删除操作是“移入回收站”；回收站提供查看和恢复，不提供永久删除或清空操作。归档 Workspace 与归档回收站仅供浏览，禁用状态来自真实能力。目录空、文本空、二进制不支持内嵌预览和请求失败分别呈现；只有失败才显示错误。编辑器快捷键与保存状态继续沿用现有体验，跨页回来保留同一文件草稿。

## 11. P07：Home

**页面语义与使用路径：**用户在这里了解 Agent 的长期身份和技能，也能看见它日常工作中提出的改动。默认 effective 回答“下一次使用的是哪些内容”；切到 actual 回答“哪些已经正式接受”。查看差异后可以给出整理指令，由 Home Reflection 决定接受、拒绝或改写，不在前端实现审核流程。

新增左目录、中央阅读、按需变化/引用详情。顶部为 effective/actual 切换、目录筛选、内容搜索、变化入口和“整理 Home”；默认 effective。

目录按真实空间/类型组织：顶层内容、普通资源、通用 Skill、domain/action 指导。通用 Skill 可展开 SKILL.md 与资源；guidance 有清楚类型标识，不误称 Background 常驻技能。

API-10 catalog/content 根据 view 读取。打开资源不改变模型加载状态；若从 Context 进入，保留“已加载”来源提示，但全文仍是资源浏览。Home 没有每日快照，不提供按日还原按钮。

变化入口列 overlay 创建/修改/删除；选择资源查看 actual/effective diff，支持统一/左右模式与大段分页。没有变化时显示简洁空态。不直接提供接受/拒绝写 actual 的按钮。

变化详情保留资源标题、变化类型和返回目录入口。baseline_diverged 只说明基线状态并引导重新读取/整理，不提供未经后端支持的合并编辑器。左目录滚动、选中 view 和中央正文滚动彼此独立；全文和变化视图切换后可返回原阅读位置。

“整理 Home”读取 API-04 availability，输入本次指令并发起 kind=home；已有根 work 时明确排队，跳运行详情。正常对话中的 Home 修改仍进入 overlay，不将 UI diff 面板变成第二套审核器。

内容 Search 使用 API-13，仅 effective 范围。actual 页面保留目录筛选；用户点击内容搜索时明确切到 effective，不在 actual 标题下显示 effective 结果。query/directory 的普通 Skill 按 top 聚合，backlinks 返回真实来源资源；进一步读取遵循 ref，不自动把 top 展开成全部深层内容。

domain/action guidance 可以浏览，但不出现在通用 Home 搜索空间。资源工具栏提供复制引用、在对话中引用、查看反链；反链是明确的 Search 请求，不在每次打开文档时自动调模型。

普通 Skill 的深层资源命中可聚合到 top：结果仍呈现实际命中资源的 evidence，点击片段可以到真实资源，点击标题到 top。Home 当前仅提供文本 content，没有通用 Home blob endpoint；可浏览 Markdown 和正文，非文本附件不承诺内嵌预览，显示资源引用及实际支持的操作。不要把 Home 路径伪装成 Workspace 下载地址。

## 12. P08：Memory

**页面语义与使用路径：**活动记忆是 Agent 这一日正在记录的内容，持久知识是整理后的经历与概念。用户可以从当天摘要进入，也可以按知识类型检索；阅读引用和反链帮助理解一条知识的来源与联系。想修改知识时在对话说明要求或发起整理，页面保持只读事实浏览。

新增左侧“活动记忆/持久知识”导航，中央文档，右侧引用详情按需打开。活动记忆使用日期选择器；持久知识按 daily/entity/concept/fact/note 分类和目录筛选。不要把日期切换解释成整个知识库时间旅行。

- API-11 active 读取当前/归档 Memory.md；daily 是持久文档，另有清晰入口。
- catalog/document 提供正文、类型、direct refs、迁移说明；redirect 显示“转向文档”入口，不暗中用目标正文替换旧文档。
- 文档缺失与内容为空分开；无知识时提供开始对话或整理入口，不展示宣传段落。
- 搜索框先确定范围/类别，明确提交后走 API-13；结果显示真实片段与来源。相关文档可使用当前 Memory document_ref query 能力，实际选项由 schema 声明驱动。
- “反向引用”以当前文档为 anchor 调用 backlinks；direct refs 与反链分栏，不把 Memory inspect 改成反链检索。
- 工具栏提供复制链接、在对话中引用；页面不直接保存持久文档。

“整理记忆”用 API-04 选择目标来源日与本次 instructions；默认建议来自 availability，不能总选当前执行日。排队/运行/结果进入统一运行观察。失败不会伪装成日归档失败，Reflection 与日切语义分开。

整理对话框分“目标日”“本次要求”和提交按钮，清楚展示选择的来源日；availability 可用 next_before 继续找更早日期，不把首批结果当全部档案。没有 daily 只是可整理线索，不自动授权批量整理。已有 daily 仍可再整理补充，不能强制锁死为完成日。Home 整理不照搬 Memory 的目标日必填控件。

打开 persistent 文档时保留独立选择，活动记忆日期变化不把该文档重新解释成某日版本。反链列表与正文 direct refs 使用相同资源预览/路由组件，关系方向标明“引用了它/它引用的内容”，不创建前端知识关系库。

## 13. 共享页面搜索面板

**使用路径：**先用查询在选定 owner 中发现内容，再基于完整结果继续筛选或排序，最后打开引用阅读。用户无需编写 pipeline JSON。此面板可以调用配置好的模型，但不取得正在对话的 Context；需要结合当前对话判断时，将要求和资源交给 Agent。

用于 Home/Memory/Workspace；主界面保持 query、范围、明确提交按钮、结果列表。高级区提供 owner 声明的属性条件、literal/regex（适用时）、排除 refs；不把原始 JSON 管道编辑器作为常用交互。

表单能力按 §3.6 读取当前 generation 对应 Search 的 retrieval/tool.schema，并落实 SDK 的 context=none 限制。只隐藏真实未开放的操作，不因该 Action 在某个 Turn 情景中不可见而关闭页面搜索；未应用的设置草稿也不能提前改变本页可用操作。

首次 query 发掘候选；进一步操作用已有 result_ref：选择“语义筛选”输入 criterion→select；“语义排序”输入 criterion→rerank；属性条件→filter。不支持的操作隐藏并在设置中解释原因；不让用户在每次查询选择 Provider/实现，这属于设置。

常用请求：

```json
{"source":{"kind":"query","scope":"all","query":"需要查找的内容"},"steps":[],"page":{"limit":20,"max_chars":8000}}
```

```json
{"source":{"kind":"result","result_ref":"<SDK result_ref>"},"steps":[{"op":"select","criterion":"只保留可直接应用的方案","context":"none"}]}
```

scope、where、Workspace resource scope 按当前 schema 创建，不能把 all 强加到所有 owner。continuation 请求只含 continuation，不重复原 query 和 steps。

用户可按顺序继续 filter/select/rerank，面板显示已执行步骤与返回结果；不在浏览器执行自定义函数。操作“全部结果”必须使用 result，而非当前页 refs；显式 refs 会重新精确读取资源，不等价于保留 Skill 聚合快照。选中条目默认用于引用，不隐式改变下一次模型候选范围。

页面查询始终 context=none；Agent 当前语境下的判断通过对话请求。用户点击才进行可能有模型成本的搜索/筛选/排序，输入联想不发模型请求。操作范围来自 SDK 服务的 retrieval policy，不以当前 Turn 已选域或 Action visibility 禁用正常资源浏览。

原结果页冻结；继续翻页不调模型，源文件变化可提示“可重新搜索”，不改写冻结结果的片段。generation/day 切换使句柄失效，保留已读结果并提供明确重搜，不自动消费额外调用。scope_required 提示缩小范围或先用属性约束，不能静默截 top-k。

布局为顶部查询/范围，紧邻的可折叠条件区，下面步骤记录与结果列表；选中结果在共享详情阅读。提交后保留 query 与已执行步骤；更改输入只形成下一次查询草稿，明确搜索才替换结果。中止页面请求仅停止等待/呈现，不宣称已经取消远端模型执行。快速翻页防止重复提交同一 token，不引入后台全量预抓取。

空结果可以来自无来源命中或 select 明确排除，按 coverage 解释；rerank 保留候选、filter 只处理已有候选，不能在前端追加隐藏词法淘汰。浏览 Workspace 归档或 actual Home 时仅可做目录内筛选，内容 Search 入口明确切回受支持的活动/effective 空间。

## 14. P09：运行观察

**页面语义与使用路径：**这里回答“Agent 现在在做什么、在等待什么、有哪些后台工作和外部能力”。先看当前执行，再按需进入 Job、ACP、MCP 或环境事件。它不是日志大屏：默认给实际状态和必要操作，详细记录按需加载。

顶部紧凑概览：Agent ready、当前 Turn/类型、真实等待原因、队列；不常驻长 UUID。下方 Execution、Jobs、ACP、MCP、Environment 五个分页，各自只在打开时读取详情。

### Execution

API-01/02 提供状态，API-17 提供过程。显示 preparing/running/waiting/finalizing/finished、有限失败与 cleanup；区分执行失败和结束后清理诊断。跳转主对话的问题/预算卡片，取消使用明确 Turn ID。队列取消不误停当前 Turn。

### Jobs

API-14 列表显示 kind/state/summary/所属 Turn；选中才取 detail/output，cursor 追加而非每次整段替换。输出页打开时才轮询/跟随，离开只停止读取，不停止 Job。停止按钮等待正式状态，不等于取消整个 Turn。

stdout/stderr 等 channel 保留标识，可合并阅读但不编造严格跨流顺序。truncated 表示本次有界读取未展示全部输出，不表示日志丢失；通过 continuation 继续读取可取得的内容，达到读取上限时提供 result_locators 中的实际产物入口，不单凭 truncated 持续请求不前进的页面。Job 运行中，空 output 页保留返回 token 继续等待；Job 进入终态也不应立即丢弃尚可读取的剩余输出。执行状态与输出阅读进度分别呈现，不能依 token 是否存在判断 Job 完成。切换 Job 清理对应轮询，不用整个运行页定时全量刷新。

pending_inputs 表示父 Agent 待处理请求；需用户决定时跳主对话 ask，不增加用户直接回复 ACP 的接口。Turn 完成后 Job 被回收，显示实际产物链接和保留过程，不能保留可操作的假历史 Job。

### ACP

API-15 分配置目标与已建立连接；连接显示 idle/busy/不可用及关联 Job，跳 Job 详情。空闲连接可跨 Turn；连接不是一次委派。提供“在对话中委派”填入意图和“编辑配置”跳设置，不直接创建脱离 Turn 的委派。

### MCP

API-16 显示 configured/enabled、connected、discovered、callable 四类事实；工具列表用已发现目录分页，详情展示完整定义及配置选择状态。显式“刷新目录”调用 POST refresh；打开页面或搜索目录名字不自动建立远端连接。

工具启用/默认规则进入配置草稿，经 apply 生效；含点名称作为原子 tools map key，不拼子路径。提供“在对话中使用”引用工具说明，不提供任意 call 测试 RPC。

未配置时给“配置服务”入口，已配置但未发现时给显式刷新入口，已发现但不可调用时显示原因；这些状态不合并成一个连接红绿点。刷新中的指示只绑定该 server，失败保留已有目录并标注 stale/error，不将其清空为无工具。ACP 同样区分无配置、未连接和已连接空闲，不为展示正常空态主动建连。

### Environment

API-01 sources + API-17 事件，按来源/topic/关联 Turn 筛选。显示实际已记录的接收/消费状态，不推测未记录阶段。watcher 失败仅提示监听问题，Workspace 仍可正式操作。观测窗口丢失显示缺口，不重造环境历史。

## 15. P10：设置外壳与统一草稿

**页面语义与使用路径：**用户可以跨多个设置页调整一组相互引用的配置，最后一次应用并重载 Agent。表单编辑没有立即生效；“放弃修改”只是丢弃当前前端草稿。模型/工具属于后端设置，主题/字体属于本地设置，两者入口和保存反馈都要明确。

设置分为 Agent 设置/界面设置。Agent 左侧六组：

| 组 | 子页 |
| --- | --- |
| 概览与运行方案 | 配置状态、方案列表/详情、变更摘要 |
| 模型与服务 | LLM Providers、LLM 模型、任务链；专用 Providers、专用模型/用途；凭据；生图预留 |
| 行为与调用 | Phase1/Phase2 绑定、Actions/用途、Search 策略、Turn/Context 预算、Reflection 调度 |
| 工具与连接 | execution、Web、资源获取、ACP、MCP |
| 数据与知识 | Workspace、Session、Home、Memory |
| 系统与诊断 | Endpoint、来源、观测、配置源及确有功能的系统项 |

分类可折叠，搜索字段/对象可跳到具体页并聚焦。复杂对象页保留左列表右编辑，普通页按任务分组；不能把全部字段挤在“高级”页，也不为平衡数量拆散同一个对象。

概览展示运行配置、待激活保存值和本地修改的摘要，提供应用/重置与方案入口，不复制所有设置表单。主要字段先显示；高级选项按真实业务对象折叠。拖动用于 Provider/模型链等离散次序，必须同时有上下移按钮；滑块用于有边界的数值，并提供精确输入和单位，不能用滑块表达对象排列。

所有 Agent 子页共用一个 ConfigDraft：saved 基线、按稳定配置身份组织的变化、字段问题。切页不保存；底栏显示修改数、重置本页、放弃全部、应用配置。对象内新增/排序先留草稿，不逐条调用 PATCH。

进入设置取 API-05 saved/active/catalog；Actions 页另取 active action catalog。明确区分运行值、已保存待激活、本地未提交；catalog 描述可配能力，当前可用性不由未应用草稿伪造。新草稿的引用与 schema 做本地验证，最终以 apply 结果为准。

Agent 忙碌时允许编辑，禁用应用并显示真实原因；不以 can_write 代替 can_reload。已有 pending 保存时提示本次应用会一并激活它们。无本地修改但 saved 待激活时提供明确 reload 入口，不伪造空 apply。

应用 API-06 返回 state=active 后按成功发布处理：清除本次已提交草稿、重读状态/配置/方案/catalog；即使附带 cleanup_diagnostics，也只另行提示旧资源清理情况，不恢复成“未应用”、不自动再次提交。reload 和方案应用遵循相同结果语义。发布前失败保留草稿，按 §3.4 的真实结构化信息定位字段/来源或显示整批错误。放弃本地修改不撤销其它客户端的 saved。刷新发现 saved 变化：干净字段采用新基线，脏对象保留本地值并提示重新载入/保留，不引入后端 CAS 或复杂自动合并器。

离开设置可保留内存草稿并显示数量；关闭窗口有未保存更改提示。凭据值仅内存编辑，不写 localStorage 草稿，不混进运行方案。网络中断导致应用结果不明确时保留草稿，先读 status 与 active/saved 核对，不单凭断线判定发布失败或成功，也不无条件重复 apply；无法确认的脱敏凭据值不靠占位内容比较后宣称已应用。

有未应用 ConfigDraft 时，所有运行方案应用入口都必须先要求明确处理：用户返回设置应用或放弃修改后再切换，或者确认“放弃未应用修改并切换”；取消切换保留草稿。确认放弃并切换时只提交 preset_id，成功后才清除已同意放弃的草稿，失败仍保留。不自动合并草稿与方案，也不连发草稿应用和方案应用两次请求。仅浏览或捕获方案不清除草稿；本地外观偏好和 Workspace 编辑草稿不属于此处理范围。

### 15.1 配置编辑的实现约束

- 每个编辑项保留 `source_id/path` 与 catalog 声明。`fields` 是正式字段映射，sources 表达来源；不得把某个展示 value 当作完整的可写配置文件。只读来源显示归属，写入来源用后端实际可写 source_id，不按标题拼路径。
- 草稿按可写原子值集中管理。同一个 `action.models.bindings` 数组、`action.retrieval` 对象或 MCP tools map 即使在多页呈现，也只有一份草稿；页面操作更新该完整值，应用时只生成一项相应 mutation，保留其它条目。
- `set` 提交完整合法值，`delete` 表达删除覆盖/恢复来源默认；不提交 null。恢复本页是撤销该页负责条目的草稿修改，与删除后端覆盖值的“恢复默认”分开。共享原子对象按 consumer、Action ID、模型/Provider/use ID 或实际 map key 识别条目；同一条目有唯一主要编辑入口，其它页面跳转，不维护独立副本。撤回本页条目时保留其它页修改，不能把整个数组/map 重置回旧值。
- secret 脱敏占位只用于显示：未改凭据不生成 operation，输入新值才 set，删除须显式操作；不可将 `***` 或空表单默认值写回。凭据引用名与凭据值是不同字段。
- 选择引用时能看到同一草稿中新建对象，完整依赖统一提交；运行状态仍来自 active。后端校验问题具备定位信息时映射到具体对象/字段，其余显示表单或整批错误；保留原 details 供展开，不靠解析 message 找字段。
- 应用条件来自 activity.can_reload；有排队根 work 时即使没有正在执行的 Turn 也不能认为 idle 可用。保存一个运行方案不等于应用配置，不清空 ConfigDraft。

一次 apply 请求示意（source_id 应取真实 catalog/source）：

```json
{"operations":[{"source_id":"project:configs/llm/models.toml","path":"llm.models.primary.providers","op":"set","value":[{"provider":"primary","provider_model":"model-name"}]}]}
```

运行方案应用为 `{"preset_id":"<真实方案 ID>"}`，不同时发送 operations。主设置流程不再使用 onBlur PATCH；仅保存/重载这组底层接口留给明确的 saved 待激活场景，不在普通用户流程重新建立第二种确认方式。

### 15.2 配置覆盖与编辑归属

F0 在 visualization 文档建立配置覆盖清单，以当前 API-05 config/catalog 和 Action 文档可编辑声明为依据。每项记录实际对象或字段路径、所属页面、主要/高级区、可写 source_id/path 或只读原因、原子提交边界及真实引用入口；不按旧设置页是否存在推定覆盖完成。集合按实际 descriptor 和对象编辑能力核对，不把每个用户自建对象变成一份重复规格。

| 配置对象 | 主要编辑入口 | 其它页面的行为 |
| --- | --- | --- |
| LLM Provider、模型、任务链；专用 Provider、模型、use | 各自对象页 | consumer/被引用位置给摘要与跳转，不复制定义。 |
| Phase1/Phase2 链绑定 | Phase 调用分配 | 任务链页显示引用位置。 |
| action.models.bindings、action.retrieval 内条目 | 对应 Action 的用途/Search 分区 | Search 策略导航定位到同一编辑器；按 consumer/Action ID 撤回本页修改。 |
| Home/Memory embedding_use | 对应 owner 设置 | 专用用途及 Action 页显示绑定与跳转，不创建第二份用途选择。 |
| MCP tools map、ACP 目标与连接配置 | MCP/ACP 设置 | 运行观察只读实际连接/目录，修改入口跳设置。 |
| 凭据值 | 统一凭据编辑入口，复用同一 dotenv 草稿 | Provider/工具页引用同一编辑流程，不维护另一份 secret。 |
| Turn/Context/Session 预算与其它 owner/system 参数 | §17～18 指定页面；共享概念确定唯一字段入口 | 概览/方案显示摘要，涉及只读来源说明实际归属。 |

各页主要区承担日常选择和操作，高级区保留所属对象的真实扩展选项。F2 退出时逐项核对覆盖清单、主要入口和本页重置边界；只读项有理由，暂缺项如实记录。不能以一个通用 JSON 编辑器或“高级设置”入口代替主要配置的可用交互，也不为覆盖字段而把内部只读投影做成可写控件。

## 16. P11：模型与服务各子页

**共同语义：**Provider 是连接和凭据，模型是具体能力及有序 Provider 路由，任务链/专用用途是上层调用的目标，Actions 页才决定业务操作用哪个目标。用户沿这个顺序配置，也可从“被引用位置”反向跳转；每页的右侧对象编辑器延续现有成功设计，不把几层关系压成一个巨大表格。

| 子页 | 用户任务与主要呈现 | 典型下一步 |
| --- | --- | --- |
| LLM Provider | 新建或编辑连接；列表选对象，右侧连接/凭据引用表单 | 去模型页选择这些 Provider。 |
| LLM 模型 | 按模型簇找到模型，设置能力和 Provider 优先顺序 | 加入任务链；折叠旧模型只影响展示。 |
| LLM 任务链 | 配置该类调用依次尝试的模型和任务参数 | 在 Phase 或 Action 用途中选择链。 |
| 专用 Provider | 配置 Embedding/JEV 连接、代理与凭据 | 去专用模型页建立真实模型及 Provider 链。 |
| 专用模型与用途 | 模型负责路由，用途用稳定 ID 指向一个模型 | Action 选择 JEV 用途；Home/Memory 选择 Embedding 用途。 |
| 凭据 | 查看环境引用就绪情况，统一编辑同一份 secret | 整批应用；不以本地就绪宣称远端测试成功。 |
| 生图 | 看见其明确归属与未接入状态 | 本轮没有真实配置或生成流程。 |

### 16.1 LLM Provider

保留 ProvidersSettingsPage/ObjectSettingsLayout 的对象逻辑：左列表状态，右侧 id、adapters、base_url、api_key_envs、enabled。凭据区显示引用和就绪，编辑 secret 进入同一个 dotenv 草稿。配置启用与远端可调用不是同一状态，不用“已配置”绿点冒充连接实测。

支持新建、复制、删除；删除前展示引用位置，保留最终后端依赖校验。只显示实际字段；LLM 未支持的专用 Provider proxy 不强行提交。

### 16.2 LLM 模型

列表按 family 分组，collapsed 默认收起并有“显示折叠模型”；搜索可发现旧模型，被链引用的旧模型仍可读。family 是模型簇属性；用户临时折叠组是本地浏览状态，不能混写 collapsed。

编辑 id、adapter、能力、context_window_tokens、providers、request_overrides、adapter_options、family/collapsed。providers 拖动排序，另有键盘上下移；每行实际字段为 provider 与 provider_model，不能将 Provider ID 当模型 ID。列表对象 id 对应配置 map key，重命名必须同时处理明确的草稿引用或提示用户，不静默改坏链。

高级参数按当前 adapter descriptor 条件显示，保留默认值与显式设置的区别。删除/改名影响引用时给明确定位，不自动选择替代模型。

### 16.3 LLM 任务链

保留 TaskChainsSettingsPage：左链列表、右有序模型项及 task 设置、被哪些 Phase/consumer 使用。拖动+键盘排序；加入模型仅选 LLM，专用 use 不进入链。

Task max_cycles/重试与 Agent Turn max_cycles 分开解释；不能共用一个“思考次数”控件。链可多处复用，编辑影响所有引用；Action 页选择链并跳到此页编辑，不复制一份私有链配置。

### 16.4 专用 Provider

同样采用对象编辑，依据 `infra.model_services.providers` 的真实数组结构：id、adapter、base_url、api_key_env、enabled、timeout_seconds、max_retries、proxy。Provider adapter 区分 Embedding 与结构化评估。

这些字段以整数组操作进入草稿；UI 按稳定 id 更新，数组下标不作为对象身份。排序 Provider 链发生在模型内，不将 Provider 目录显示顺序解释成全局优先级。

### 16.5 专用模型与逻辑用途

模型列表按 Embedding/JEV 能力分组；编辑 id/kind、provider_bindings 的有序 provider_id/model、实际支持的 dimensions/batch_size。Embedding 需要维度，JEV 不显示向量维度控件。

用途子页编辑 id/kind/model_id（序列化字段是 id，不是 use_id），并显示真实 consumer 引用；一对一模型，不再增加 model chain。未被选用的目录可保存未就绪连接，启用用途时依赖必须满足正式规则。

JEV 名称配合“结构化评估/评分”用途说明，不把当前 Score 接口宣传为任意文本生成。Home/Memory embedding_use 的编辑位于相应 owner 设置，此处显示被谁使用并跳转。

专用能力的实际 kind 为 embedding、structured_decision；Provider adapter 为 openai_embedding、typesafe_system_one。显示名可以是“Embedding”“JEV”，请求不能提交 jev 作为 kind。专用 Provider 用单数 adapter/api_key_env，LLM Provider 用复数 adapters/api_key_envs；两个表单可复用控件但保留不同协议，不做假统一字段映射。

### 16.6 凭据与生图预留

凭据页集中列环境引用及来源/就绪；相同引用共用一条编辑，固定 env/header 与 env_refs/header_refs 区分；无需为每页重建密钥表。

生图子页在“模型与服务”中有独立入口，简洁显示“尚未接入”和将采用 Provider→模型→用途的归属；不提供失效的新增/保存/测试控件，不向后端提交 image_generation 类型。不为预留引入一套独立配置存储。

## 17. P12：行为、Actions、Search 与预算

**页面语义与使用路径：**这里配置 Agent 如何使用已有能力。先决定框架 Phase 调哪个 LLM 链，再按 domain 找 Action，查看它声明的模型用途并选择实现。Search 的六个操作是 Agent 可以组合的行为；用户在设置中配置各操作内部怎样实现，不替 Agent 写一条固定默认管道。

### 17.1 Phase 调用分配

Phase1/Phase2 分别选择真实 LLM task profile，并可跳转链编辑；不提供当前不存在的 JEV Phase 切换。此处管理框架调用，Actions 页管理内部用途，两者不混成全部“LLM Actions”。

### 17.2 Actions

左侧 domain 与名称搜索、scenario 筛选（user/home_reflection/memory_reflection）；右侧分行为、模型用途、协议详情。行为显示 selection/visibility 的当前值与来源、granted/supported/available、超时/批次等真实设置。

scenario 决定可用能力视图，不自动产生三套模型绑定。Reflection 中的 memory.write/write_daily/home.review 是确定性行为，不能为保持布局加入虚构 LLM 选择器。

模型用途按 consumer 展开：operation、允许 implementation、当前 target 和 options。LLM 选任务链，JEV 选逻辑 use，Embedding 按 descriptor 引用 owner 用途。不可用实现只在真实 descriptor 支持时出现；不从 executor 名猜能力。

用途声明、当前绑定与原子可写来源分别按 §3.6 获取，编辑归属遵循 §15.2。scenario 切换只改变能力视图，同一 consumer 的草稿仍只有一份；草稿中的实现/target 选择不覆盖 active 的可用性、来源和运行状态。

操作路径示例：选 Home search → 找到 select 用途 → 在该 consumer 允许时选择 JEV → 选择 structured_decision 用途 → 调整其真实 options → 查看变更 → 应用。同一 Action 的 query/select/rerank 可有不同配置；只显示对应 descriptor 声明的控件。原 Reflection 独立模型链页面删除，Reflection 扩充的动作在情景视图内展示；确定性 write/review 显示其操作语义即可。

### 17.3 Search 配置

以一个 Action 内的来源/操作/预算分区编辑，同一配置只在此处编辑，其它页跳转：

| 区域 | 控件与含义 |
| --- | --- |
| 来源/步骤 | 开放 sources/operations、max_steps；是能力范围，不是默认管道 |
| query | 当前支持的 lexical/Embedding 通道；owner embedding_use 只读摘要+跳转 |
| select | LLM/JEV 及 target/options；真实阈值才提供控件 |
| rerank | descriptor 支持的 LLM/JEV/Embedding |
| filter | 属性契约说明，没有模型选择器 |
| 输入/展示 | allowed_context、input/snapshot/page 预算；高级区注明真实单位 |

Workspace/Context/MCP 不自动获得 Embedding。MCP 自然语言发现由目录加 select/rerank 表达，不把 query 的词法匹配当作语义检索。operations 为空仍允许纯 source，不把空列表解释成关闭整个 Search。

`action.models.bindings` 原子数组与 `action.retrieval` 整体对象通过统一 draft adapter 更新；Action ID 含点仍是 map key。保持其它 consumer/Action 条目，不生成 `action.retrieval.home.search...` 叶子 PATCH。

### 17.4 预算与 Reflection

Turn/User/Home Reflection/Memory Reflection Cycle 额度分别呈现；Context 背景字符/图像预算、压缩比例、Trace 折叠参数按用途分组。数值输入配合法范围滑块，提供默认值恢复，不在同一滑块混合 token/字符/字节。

Reflection 调度放行为设置：enabled、每日时间、时区等实际参数；发起一次整理在 Home/Memory 页面，不把一次授权保存为持续开启。

## 18. P13：工具、连接、数据与系统设置

**页面语义与使用路径：**工具与连接决定 Agent 能接入哪些能力，数据与知识决定各 owner 的位置和使用参数，系统页只放运行宿主配置。用户在此编辑配置，再去运行观察确认连接/目录事实，不能把“配置保存成功”理解为远端工具已运行。

这些页面依 catalog 组织有设计的表单，保留扩展字段入口；不引入无真实后端消费的配置。

| 子页 | 实施细节 |
| --- | --- |
| execution | shell/script/process 的真实选项与运行限制；高级参数折叠，当前生效 shell 明确为只读状态 |
| Web/资源获取 | API Provider、凭据引用及当前能力；Web 搜索与内部 Search 分开，不套内部向量/管道语义 |
| ACP | agents/targets 对象编辑、命令/地址、工作目录与环境引用、限制；运行连接状态跳运行观察 |
| MCP | stdio/Streamable HTTP 条件字段、env/headers 与引用、tools_default/tools；工具名字含点以完整 map 编辑 |
| Workspace | 根/读写大小等真实参数；路径与日生命周期的说明只在相关项旁，不能把 pinned/library 标签当跨日持久化开关 |
| Session | 当日事实/地图预算与 inspect 约束；不提供跨日合并或手工改图开关 |
| Home | 路径/默认内容及 search.embedding_use；声明 effective/actual 语义，指导挂载按真实能力编辑 |
| Memory | 活动/持久数据参数和 search.embedding_use；模型目录用引用选择，维度与索引影响说明置于修改处 |
| 系统/诊断 | Endpoint、来源、Observation 等真实参数；只读进程/env source 不伪装可写，变更后按后端实际应用方式反馈 |

MCP/ACP 修改进入同一整批草稿，不能在表单每次变化时自动启动服务。工具列表用于帮助设置引用；MCP 显式刷新目录在运行页，新增配置未应用时不能宣称运行目录已经刷新。

## 19. P14：运行方案管理

**页面语义与使用路径：**用户把常用的调用策略命名保存，例如一个更节省的方案和一个更充分的方案，再从对话输入区旁切换。它不是单模型选择，也不打包账户、凭据和整个项目。列表选方案、右侧看范围和实际差异，确认应用后才影响后续 Turn。

列表显示名称、简短说明、active/saved 匹配状态与依赖问题；右侧详情显示受管范围、任务链/用途/预算摘要。支持从运行值/保存值/当前草稿新建、重命名、删除、显式覆盖捕获、应用；删除不影响当前配置。

捕获源选择当前运行、已保存、或当前草稿。草稿捕获使用 `source=saved + operations`，只保存方案，不应用配置或清除草稿。捕获仅包含下述受管范围，不能当作全部配置草稿的备份；应用方案共用 §15 的草稿处理规则。只有显式覆盖才更新快照，重命名不重抓当前值。

创建对话框包含名称、可选说明、捕获源和“包含预算”；捕获范围为后端定义的整组，前端不增加任意字段勾选导出。详情 snapshot 是读取结构，不是 POST 请求体。当前 API 没有 from_preset/任意 snapshot 写入，不提供“任意旧方案复制”按钮，也不在前端复制后端的 snapshot 替换算法；需要新变体时编辑当前配置草稿并另存为方案。这满足命名保存与切换需求，并保持唯一的捕获/应用语义。

范围固定且在详情清楚说明：

- 必选：完整 llm.models（包括 family/collapsed）、llm.tasks；Phase1/2 链绑定；完整 Action implementation/target/options；retrieval query.channels。
- 可选 budgets：loop.user.max_cycles、reflection.home/memory.max_cycles、session.background_max_chars；context.budget_max_image_bytes、compression_trigger/target_ratio、trace_chunk_max_chars/branch_factor/min_hot_entries/inspect_max_chars；每个 retrieval 的 max_steps、snapshot_max_chars、page.max_items/max_chars、已开放 select/rerank 的 input_max_chars。
- 不包含 Provider 连接/凭据、专用模型与 uses 目录、Home/Memory embedding_use、paths、system_text、调度、visibility、sources/operations/allowed_context、知识正文和本地外观。

所以方案可改变 LLM/JEV 选择与是否使用已有 Embedding 通道，不更换向量空间。没有 budgets 的方案保留当前预算；有 budgets 完整替换该组的默认/显式值。不要把缺省显示成 set(null)。

API-07 捕获 `name,description,source,operations?,include_budgets`；PUT 只有 capture 明确存在才覆盖；API-06 preset_id 激活。依赖缺失时列出具体目标并跳设置，不能自动补造模型。忙碌可编辑方案记录，应用仍受正式 idle 条件约束。

配置 sources 的物理路由、preset 文件内容由后端管理，前端不直接读写 configs/presets。方案不作为运行时叠加层。

## 20. P15：界面本地设置

**页面语义与使用路径：**用户只想改变阅读体验时到这里，修改立即作用于当前客户端；不会排队重载 Agent，也不会改变其他客户端的模型设置。入口与 Agent 设置并列，避免本地字号被误当作一次待应用配置。

本地即时保存主题、字体/字号、行高、代码字体、密度、减少动画、自动跟随、通知与目录/详情宽度。采用统一 tokens，不让各页保存相互冲突的字号。提供本地“恢复默认”，不改 Agent 设置。

偏好可全局共享；页面选择、资源打开状态按项目命名空间保存；Search 句柄、活动 Turn 控制身份和 secret 不长期保存。系统通知只来自真实运行状态，点击跳对应 Turn/资源，不从长日志关键词猜完成。

显示字体选择的真实预览即可，不加解释性演示页。键盘 focus、对比度、字体缩放和 reduced-motion 覆盖所有新增卡片与图表。

## 21. 共享渲染与资源路由

### 21.1 CodeBlockRegistry

在现有 ReactMarkdown/remark-gfm/math/KaTeX 基础上增加显式注册：language、parse、render、fallback。Question、Mermaid、TikZ 是具体消费者；未知 fence 保持普通代码。不会把任意 Markdown 代码当作可执行 JavaScript。

Question 采用 §6 协议与 active/compose/readonly 模式。Mermaid 使用官方 render API 生成 SVG，按需加载，支持图/源码切换、缩放和导出；flowchart 采用 Mermaid 的图语法，不再平行引入同义引擎。TikZ 使用 TikZJax 的浏览器编译路径，将运行时与资源封装在专用渲染容器中，单独加载并输出 SVG；不把其全局扫描混入 React 主文档。

注册使用稳定 language alias 与明确 props（源码、主题、origin、交互模式），组件卸载负责释放实例/资源。Mermaid 使用 initialize 后的 render API，不采用已废弃 init 扫描。TikZJax 使用它实际支持的 TeX/TikZ 子集；编译资源和 DOM 隔离不能自动等同于 Worker 并行。F0 先验证本地资源、WASM/字体与 Browser/Tauri 路径，确定可行容器；若主线程长编译影响输入，应在真实 API 可支持的方式下调度、按需启动并限制并发，不能声称 iframe 本身解决性能问题。协议未知或语法不支持时保留源码和清楚错误，不吞掉块。

复杂渲染只在完整 fence 且进入视区/用户展开后触发；流式未闭合块显示代码。缓存按 source/renderer version/theme 建立；离屏/关闭可释放，失败保留源码与有限错误，重试由用户触发。资源优先随应用构建交付，记录第三方许可与依赖锁定，不依赖每次页面打开从 CDN 临时下载运行时。

新增依赖实施时按官方文档核验 Browser/Tauri 构建与资源路径；不预填未经验证的版本。技术依据：[Mermaid API](https://mermaid.js.org/config/usage)、[TikZJax](https://github.com/kisonecat/tikzjax)。只将它们封装为实际 renderer，不建设动态插件市场。

### 21.2 ResourceRouter

输入是 reference 与 origin：资源 link、day、turn_id、view、必要已解析 locator。已带正式 locator 可直接路由；相对/动态/未解析引用调用 API-18。web 链接 Browser 新页/Tauri 系统浏览器；本轮不做内嵌浏览器。

| 资源 | 目标 |
| --- | --- |
| workspace | 工作区对应 day/file/fragment，归档只读 |
| home top/resource/guidance | Home 对应 view 与资源 |
| memory persistent | Memory 文档与片段 |
| memory current/latest/target | 使用来源 resolved locator；无绑定给明确提示，不能默认变成今天 |
| Session ref | 日期/Turn/解释披露详情 |
| Trace ref | 活动 Context 披露或实际保留的历史来源；不可用则明确告知 |
| HTTP(S) | 外部浏览器 |

点击跳转、复制原引用、“在对话中引用”是不同操作；引用仅填入 Composer，用户决定发送。Search result_ref 和内部模型短 ID 不提供永久资源跳转。相对图片等资源先通过 owner 解析，再按实际提供的读取能力展示，不把原文路径拼成任意 URL。

“在对话中引用”生成可检查、可编辑的文本草稿，保留原引用以及辨认资源所必需的来源日期、view 或原始 Turn；动态引用已有正式解析结果时同时保留对应资源身份。例如：`请参考 workspace:reports/result.md，来源为 2026-09-28 的归档工作区。` 前端内部 origin 不会自动成为模型可见信息，不依赖自定义 metadata 实现隐式附件或内容注入。引用不等于已读取或加载全文，不自动附加大段正文，也不承诺当前 Action 具有该来源的读取能力。

所有 Markdown 实例——回答、问题说明、资源正文、Search 片段详情、模型输出——传入同一 origin 结构，并复用 a/img 解析。ReactMarkdown 的 URL 转换与 renderer 要一起适配自定义协议，否则合法 home:/memory:/workspace: 链接可能在到达点击处理前被清空；只传递本文明确的资源协议与网页链接，不依赖 raw HTML 或物理路径。fragment、day、view 与 turn_id 保留到最终详情，返回栈恢复原页面和滚动位置。

媒体按实际能力分发：解析为 Workspace 的资源走鉴权 blob client；当前 Home/Memory 无通用 blob 路由，不能承诺所有相对图片都可内嵌。HTTP(S) 图片按正常网络资源能力处理；不支持的本地附件保留有意义的引用/提示，不猜接口。纯文本或 inline code 中的引用仅在确认为合法资源格式时提供链接控件，不把任意冒号文本识别成资源。

### 21.3 独立注册职责

ActionRenderer、CodeBlockRegistry、ResourceRouter、Settings editor adapters 分别负责结果、内容协议、定位、配置编辑。可以共用 DisclosureBrowser/ResourcePreview，不合并为一个万能插件容器。所有扩展在应用装配时显式组合，有真实调用者才建立接口。

## 22. 前端代码组织与迁移

保留当前 React 19/TypeScript/Vite/Tauri/Zustand/Tailwind/motion 等基础，不为架构整齐更换技术栈。

前端遵循 React 的组件/hook 与 TypeScript 类型习惯，不机械移植 Python dataclass/异常体系。transport 边界接收 unknown/JSON-safe owner 内容并收窄为当前 renderer 真正消费的类型；固定 envelope 对齐后端 schemas，动态 owner 字段由专属 decoder 解释，避免全项目 any 或复制一套后端业务类。

| 位置 | 职责与改动 |
| --- | --- |
| src/app 或现有壳 | 导航、连接生命周期、主详情返回栈 |
| src/api | v2 类型化 clients、错误和 continuation；清理 v1/终端式聊天调用 |
| src/store/state | 正式快照/实体、ConfigDraft、偏好；不复制后端控制流 |
| features/chat | 对话交互、Question/预算卡、方案、Session 导航 |
| features/context/trace | installed 段、披露、Action/模型详情 |
| features/workspace/home/memory | 各 owner 页面与共享 SearchPanel |
| features/runtime | Execution/Jobs/ACP/MCP/Environment |
| features/settings | 重用对象编辑器，重组导航，模型用途与方案 |
| shared/components | 资源路由、Markdown/代码块、排序、预览、DisclosureBrowser |

目录可就近使用现有组件位置，不为照抄表格大量搬空文件。迁移同一功能后删除对应旧 store/derive/API 类型，不并行保留两套对话与配置逻辑。旧 maintenance 业务入口统一使用 Reflection 名称，不能只换页面标题而仍发旧协议。

缓存 key 按真实 project/instance/generation/day/turn/locator/view 区分。关闭页面取消读取订阅，不取消 Agent；切 generation 清代级能力/Search 句柄，Session 按 owner 重新取。事件只更新实际相关对象，不对每条日志全应用重算。

状态事件在全局订阅，model 正文按需读；长列表/输出使用分页与合适的虚拟化。保持 Chat 滚动锚定，不因统一虚拟列表破坏原成熟行为。资源变化不覆盖用户编辑草稿，Context 更新不强制移动阅读位置。

### 22.1 现有入口的迁移清单

| 现有位置/模式 | 保留与替换要求 |
| --- | --- |
| `src/components/shell/AppShell.tsx`、TopBar/NavRail/StatusBar | 保留壳和视觉；添加 Home/Memory 导航、统一 Inspector，替换旧连接/数据来源。 |
| `src/api/connection.ts`、`src-tauri/src/lib.rs` | Browser/Tauri 手动地址+token 及 Tauri 本机发现共用 v2 握手；移除 protocol_version=1 假设；HTTP/binary/WS 共用客户端可达地址与现有鉴权。 |
| `src/api/` 中 runtime/history/maintenance/configuration/workspace clients | 按 API-01～18 整理；删 v1 与旧 maintenance 路由，普通聊天不走终端命令解析。 |
| `src/derive/chat.ts`、现有 useDerivedChat(events,localInputs) | 正式对话来自 interactions/Session；事件继续支持过程细节，不能继续承担完整聊天权威来源。 |
| `src/api/history.ts` 的全量事件恢复 | 用 Session 分页读取替代对话恢复；历史模型日志仅在打开详情时定向读取。 |
| `src/store/configStore.ts` 和 settings 对象编辑页 | 替换逐字段 PATCH/自动生效，复用对象布局控件，接入唯一 ConfigDraft；运行状态刷新不得重置脏表单。 |
| `src/derive/actions/registry.ts` 与 result renderers | 精确 Action ID 注册并逐类适配当前结果；保留通用回退，删除旧别名。 |
| 现有 `Markdown.tsx` 与链接处理 | 显式 registry 与统一 origin/router，所有资源阅读入口使用同一能力。 |
| `src/types/` 的 configuration/runtime/events/maintenance/workspace/ui | 对齐 v2，移除 obsolete DTO；AppTab 增加真实页面，避免同一状态同时保留旧/新定义。 |

目录定位以实际仓库为准；表中是检索入口，不要求保留每个文件名。新共用模块以真实消费者为依据：fragment decoder 被普通页与 Context 使用，Search/Job 各自保留 continuation 语义，不能为了统一再建一套内容/检索引擎。

## 23. 实施阶段

阶段均为 pending。依赖表示实施顺序，所有页面和共享能力属于本轮完整交付。

| 阶段 | 工作 | 依赖与退出条件 |
| --- | --- | --- |
| F0 契约与技术核对 | API-01～18 类型/fixtures、§3.6 能力来源、§15.2 配置覆盖清单、v2 手动连接/本机发现、TikZ/Mermaid 最小真实渲染验证 | 核对 HTTP/WS/blob 地址及鉴权、分页和资源路径，记录原页面视觉保留项；不要求前端部署隧道/转发 |
| F1 数据与壳 | 正式实体缓存、事件失效、共享详情、导航及最小真实交互流程 | 提交 Turn→恢复问题→回复→完成→Session 恢复，身份和正式来源正确 |
| F2 设置与方案 | P10～15、统一草稿、模型/用途、apply/presets | 多页编辑/应用/失败/重置、方案切换闭环；配置覆盖清单逐项核对并完成代表性页面视觉核对 |
| F3 对话与历史 | P01～03、Question/预算、追加/排队、历史接替 | 正常交互不丢、不重复，原滚动体验保留 |
| F4 Context/Action/模型 | P04～05、Search renderer、provenance、canonical Action 覆盖矩阵 | 读视图无执行副作用，模型详情真实；内置动作展示逐项有归属及验证依据 |
| F5 资源与链接 | P06～08、共享 SearchPanel、ResourceRouter | 日期/view/动态绑定正确，归档只读；Home/Memory 代表性页面及状态视觉核对 |
| F6 运行与代码块 | P09、完善 Mermaid/TikZ/通用 registry | 在 F0 已验证的技术路径上完成状态、刷新、图渲染与回退，完成运行观察代表性页面视觉核对 |
| F7 收口 | 清理旧逻辑、性能、响应式、主题、文档 | 全部页面验收、测试和 build 完成 |

前端实现只修改 `visualization/` 及其内文档。本文位于 docs/analysis，由项目维护者更新实施状态；前端实施者在 visualization 文档记录进度即可。遇缺失能力，在 `visualization/docs/demand/` 记录具体页面、请求/结果、owner 和复现；可用与已定契约一致的 fixture 开发，不把 mock 当成功集成。若实际后端契约需要调整，由后端同步接口文档并由维护者修订本计划，不加前端猜测兼容层。

依赖细化：F1 依赖 F0；F2～F6 都复用 F1 数据/壳，F3 的方案入口依赖 F2，F4 的资源深读与 F5 共用 ResourceRouter，Question 的 registry 在 F3 建立而不是等 F6。F4/F5 先完成最小真实资源导航，再扩完整页面。F0 的技术验证属于正式实现的基础，不保留另一个演示应用。

F1 的最小真实流程复用正式 client/state 与真实 Endpoint，可使用临时项目和受控模型响应验证，不要求真实供应商调用。它先验证回执、等待身份、交互与 Session 来源衔接；完整 Question renderer、Composer、动画与历史页面仍在 F3 完成。保留这条集成路径供 F3 扩展使用，不另造临时聊天状态或第二套客户端。

设置、Home、Memory 和运行观察在各自阶段先做代表性实际页面与关键状态的视觉核对，再扩展同类表单或视图。以现有应用的 tokens、布局和成熟交互为基准，记录首屏主次、字号、控件密度、等待状态、明暗主题及小窗口阅读体验；对照原版保留项展示实际页面，按项目规约讨论重要布局调整，不另建 Demo 应用。加载/空态/错误可以使用同一正式组件的契约 fixture 检查视觉，但阶段退出仍需真实接口闭环。

实施阶段安排服务于逐项集成，不能把 Home/Memory、代码块、运行页或完整设置当作未来可选项。每个阶段以真实接口闭环和语义验收退出；一页完成不能仅指布局和 mock 已完成。

## 24. 验收与性能要求

### 24.1 必须走通的完整场景

- [ ] 空项目连接、重连、ready=false、generation 切换与观察缺口，业务历史不被事件丢失破坏。
- [ ] Browser/Tauri 可手动填写实际 IP:Port 和 token；显式协议、HTTP/WS/blob 地址一致，本机发现可用，后端内部地址不覆盖手动入口。
- [ ] 无活动 Turn、无 Job、知识目录为空、MCP 未连接/未发现分别呈现正常状态，不误报故障或自动启动工作。
- [ ] 新 Turn → 追加 → ask → choice/Other → 补充 → 完成 → 刷新，身份/顺序/全文正确；输入未受理和已受理状态明确。
- [ ] preparing 阶段使用明确活动 User Turn ID 补充，拒绝后保留草稿；排队满、Inbox 容量不足与失效等待分别处理，不改发请求意图或依赖不存在的 Inbox 开放字段。
- [ ] 活动交互翻页期间新增输入、pending→installed/visible、Context 正文更新时，失效序列/分片正确结束，已读内容不丢且不混接新旧页；问题和预算不等待正文翻完。
- [ ] 完成 Turn 的 Session 超过一页时，首页不清空整轮已展示正文；所需页面就绪后按 Turn 接替，原阅读位置与完整问题/回复保留。
- [ ] 问题与预算同时等待，各自提交；排队/取消/finalizing 正确；Reflection 运行不误接普通追加。
- [ ] 运行方案应用后实际 LLM/JEV 与 query 通道改变；运行中不可假切换；缺引用清晰定位。
- [ ] 有未应用草稿时，对话和设置中的方案切换均要求明确处理；取消/失败保留，确认放弃并成功切换才清除；捕获方案不清草稿或冒充全量备份。
- [ ] 多页配置草稿、对象排序、含点 map、整批凭据+配置、应用失败/重置、已有 pending 配置的说明正确。
- [ ] apply/reload/方案返回 active 且带 cleanup_diagnostics 时仍显示已应用并更新配置，清理提示独立；响应中断保留草稿并核对正式状态，不盲目重发。
- [ ] request.invalid 无字段定位时显示表单级错误；有结构化配置 key 时定位对应控件，不解析 message 猜字段。
- [ ] 配置覆盖清单逐项核对，主要/高级区与只读原因明确；同一条目只有一个主要编辑入口，本页重置不撤回其它页负责条目的修改。
- [ ] family/collapsed 展示不禁用模型；LLM/专用 Provider 与用途引用真实；生图预留无假保存。
- [ ] Context 三槽四形状、折叠披露、Session 证据；UI 阅读不改变模型语境；历史 Task 与当前 Context 不混淆。
- [ ] Home/Memory Heap 无 INSPECT 时仍可读取 installed messages，并正确转 owner 阅读；fragment 中间页/末页不丢项或重复项，messages/items/text 不混用。
- [ ] Search 真片段/双通道命中/评分/覆盖、result 派生、续页与失效；页面不调用 current Context，不卡在隐式 top-k。
- [ ] Search 控件来自实际 retrieval/tool.schema 及 SDK 限制，不以 Action visibility/granted 或未应用草稿改变页面搜索能力。
- [ ] Action 覆盖矩阵与当前 canonical Catalog 逐项对应，Web、分析/转换、等待/Job 控制、Session 整理及 Reflection 提交均有实际呈现；已知动作采用通用视图有理由，旧名称/兼容映射已清理，未知扩展可回退。
- [ ] Workspace 完整编辑/外部变化/归档；Home actual/effective/diff/Reflection；Memory active/daily/知识/反链/redirect。
- [ ] 活动文件移入回收站及恢复可用，归档回收站只读，无永久删除或清空入口。
- [ ] Workspace full=true 完整正文才可覆盖保存；Blob 预览真实携带鉴权且保留 day；不为 Home 非文本资源编造下载接口。
- [ ] 资源链接正确进入 day/view/fragment；动态引用无绑定时明确；网页打开外部浏览器。
- [ ] 资源引用进入 Composer 时保留必要的来源日期/视图/Turn 或正式解析身份；仅形成可编辑文本，不自动发送或加载全文。
- [ ] Job 输出/停止、ACP 连接与委派区分、MCP GET 无副作用及显式刷新、watcher 状态正确。
- [ ] Job 运行中空输出继续轮询，终态仍可读取剩余输出；truncated 不误报丢失，读取上限转实际产物入口。事件过滤空页仍按 next_sequence 推进；日期/Reflection 按 next_before 续读，不能依赖统一 cursor 假设。
- [ ] Question active/compose/readonly、Mermaid、TikZ、普通代码和错误回退；大图不阻塞主对话输入。
- [ ] 明暗主题、小窗口、字号缩放、键盘焦点、reduced-motion；无演示口号与新增常驻聊天日期栏。
- [ ] F1 最小真实交互流程及设置/Home/Memory/运行观察的代表性页面视觉核对有记录，fixture 视觉检查与真实接口验收分别说明。

### 24.2 测试组织

TypeScript 契约与核心状态合并用单元测试；Question/ConfigDraft/排序/ResourceRouter 用行为组件测试；代表性 Browser 流程用 Playwright。fixtures 取自后端真实 schema；fake timers 替代长 sleep，不用大批全页面快照固化像素或字段顺序。

至少覆盖 API 重连后交互去重、pending→installed/visible、动态续页失效和多页 Session 接替、配置失败保留与成功清理诊断、Search lifecycle、实际路由来源。不要为低影响样式改动写镜像实现的测试。

契约样例以 `docs/endpoint/contracts/examples/` 为来源，挑选当前 UI 有消费者的最小集合复制到 visualization 测试 fixtures，并注明基线。重点包括 turn-waiting/interactions/question-reply、context-overview/context-messages、home-fragment/home-fragment-end、search-evidence、job-output、config-views/config-apply/preset、resource resolve。fragment 的首/末样例并非相邻页，必须补齐真实中间序列或构造符合协议的短分片测试，不能直接拼首尾宣称通过。token 样例仅展示结构，不能发送到真实后端。

| 风险/协作边界 | 必要验证 |
| --- | --- |
| 配置共享原子对象 | 在两个 Action 页修改同一 map 后一次提交，两个改动均保留；reset 本页不丢另一页修改；masked secret 不回写。 |
| 草稿与方案 | 两个应用入口共用确认规则；取消/失败保留草稿，确认放弃并成功应用才清除；请求不混用 operations/preset_id。 |
| 应用结果与错误定位 | active 附 cleanup_diagnostics 仍成功更新；请求结果不明确时先核对；通用 request.invalid 与有定位 key 的 config.invalid 使用不同反馈。 |
| 交互与控制 | 同一 question 从快照和交互到达只生成一个待答卡；预算并存；追加 record_id→interaction.id 无重复，拒绝保稿且不换目标。 |
| 动态分页与历史接替 | 翻页中新增/安装输入及更新段正文后，旧 token/晚到响应/未完成 fragment 不进入新序列；Session 多页就绪前不清空已读正文，接替后无重复。 |
| 阅读与日期 | 当前 Context/Home 全文区分，动态 Memory 原绑定、归档 Workspace day、链接 fragment 和返回位置均正确；引用到 Composer 的文本保留必要来源。 |
| 内容与检索 | 连续 JSON fragment 解码、最后片消费、真实 evidence 含 emoji 高亮、派生 result 与冻结分页不混淆。 |
| 能力与展示覆盖 | 同一 Search 的 SDK 浏览不受 Action visibility 误禁用；配置清单和 Action 矩阵逐项核对，行为测试按代表性编辑操作及结果族组织，不固化整个 Catalog 快照。 |
| 运行与观察 | Job 运行中空页可续读、终态读取剩余页、truncated 不误报丢失、退出详情停轮询；事件过滤可前进，MCP 打开页面不发 refresh。 |
| 连接与转发地址 | IP:Port 与显式协议均正确构建 HTTP/WS/blob 请求并携带对应鉴权；握手不把客户端可达地址改回服务端 loopback。 |
| 渲染与应用壳 | 完整/不完整 fence、Question 三模式、Mermaid/TikZ 成功与失败；Browser/Tauri 本地资源可用且不影响输入。 |

仓库现有 `pnpm-lock.yaml` 与 Tauri 的 pnpm hooks 保持一致，在 `visualization/` 使用 `pnpm install --frozen-lockfile`、`pnpm test`、`pnpm build`；新增依赖时更新同一锁文件，不另加 npm 锁文件。为代表性流程建立明确的 Playwright 配置/命令后执行并记录，不能仅因有依赖就声称已有端到端门禁。Tauri 连接/外链/本地资源与 Browser 均做代表性验证，记录环境和未覆盖项，不用 Browser build 代替桌面集成结论。完成源码改动时仍遵守根 AGENTS.md 的完整本地门禁要求；平台或环境不能执行的项目明确列出，不能写成已通过。

性能验证针对实际风险：聊天打开不加载全部 model 正文，设置刷新不逐字段 HTTP，Job 输出只读新增页，图模块按需加载，运行事件不触发全局大列表重算；不创建无使用场景的独立性能平台。

## 25. 交付与文档规则

每阶段记录改动文件、真实完成项、命令/结果、剩余缺口和可用 commit 文本。前端设计说明同步到 visualization 文档，Endpoint 使用与后端已发布契约一致；无消费者组件、重复状态或临时兼容分支在 F7 删除。

交接文档至少包含页面地图/用户路径、状态和接口所有权、设置保存与方案语义、Context 与资源的差别、代码块注册方法、实际运行/测试命令，并附配置覆盖清单、canonical Action 展示矩阵、最小真实交互流程与代表性页面视觉核对记录。清单记录实际缺口和验证依据，不用“通用回退”或 mock 页面代替完成证据。用实际页面操作示例解释，不要求下一个实施者重新阅读整个历史讨论。已有 `visualization/docs/demand/` 文档只保留仍真实存在的缺口，过时条目按项目文档规则整理，不把旧需求编号当作新实现依据。

只有 F0～F7、所有页面、接口集成和必要验证逐项完成，才将计划标为 done，并按 AGENTS.md 移入 `docs/analysis/done/` 加 `-done-`。本计划具备实施基础，具体退出条件以真实接口与页面验证为准；当前仍为 pending，不表示前端实现或测试已经完成。
