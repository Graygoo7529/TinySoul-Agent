# Visualization 前端重构与建设执行计划

> 日期：2026-09-28；状态：pending；代码基线：`1aa0db4`。
> 产品范围已确认，实施尚未开始。本文完整定义前端页面、交互、数据来源、接口用法和验收；不需要其它讨论材料补充语义。
> 先完成配套 [后端支持执行计划](20260928-visualization-backend-support-plan.md)，取得实际 Endpoint schema/样例，再实施本计划。两份计划的 API 编号一致。
> 规约依据：根目录 AGENTS.md；后端实际契约以实施完成后同步的 `docs/endpoint/` 为准。本文标记为新增/扩展的接口不能提前当作当前已有能力。

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

下表路径均以 `/v2` 为前缀。API-01/02/04/05/12/14/17 中的基础能力已有，其扩展字段和其它接口由后端本轮交付。

| ID | 方法与路径 | 状态 | 用途 |
| --- | --- | --- | --- |
| API-01 | GET /health、/status；POST /restart | 复用 | 连接、ready、runtime、宿主重启 |
| API-02 | POST /turns；GET /turns/{id}；POST /turns/{id}/input、reply、grant、cancel | 扩展 reply | 明确新轮/追加/回复/补额/取消 |
| API-03 | GET /turns/{id}/interactions | 新增 | 活动/保留句柄交互投影 |
| API-04 | GET /reflection；POST /reflection | 复用/必要补齐 | 可整理目标和同一根队列中的 Reflection |
| API-05 | GET /config?view=saved或active；GET /config/catalog；GET /config/actions?scenario=…；PATCH /config；POST /config/reload | 扩展读取 | 设置值、声明、运行能力与已有保存/激活入口 |
| API-06 | POST /config/apply | 新增 | 整批保存并发布 generation |
| API-07 | GET/POST /config/presets；GET/PUT/DELETE /config/presets/{id} | 新增 | 项目命名方案 |
| API-08 | GET /days；GET /session/turns、/session/turns/{id}、/session/map、/session/inspect | 新增 | 日目录、历史对话和地图 |
| API-09 | GET /turns/{id}/context、/context/segments/{segment_id}、/context/inspect | 新增 | 当前 Context 只读浏览 |
| API-10 | GET /home/catalog、/home/content、/home/changes、/home/diff | 新增 | Home 阅读与变化 |
| API-11 | GET /memory/active、/memory/catalog、/memory/document | 新增 | 活动与持久 Memory |
| API-12 | /workspace 现有 manifest/resource/blob/directory/move/tags/edit/append/trash/restore 路由 | 扩展读取 | 保留编辑；增加归档和大内容支持 |
| API-13 | POST /home/search、/memory/search、/workspace/search | 新增 | SDK owner 内容检索，返回现有 SearchPage |
| API-14 | GET /turns/{id}/jobs；POST /turns/{id}/jobs/{job_id}/stop；GET /turns/{id}/jobs/{job_id}、/output | 后两项新增 | Job 状态与输出 |
| API-15 | GET /subagent | 新增 | ACP 目标及 generation 连接状态 |
| API-16 | GET /expand/servers、/expand/tools；POST /expand/servers/{server_id}/refresh | 新增 | MCP 快照及明确刷新 |
| API-17 | GET /events；WS /events/ws | 扩展过滤/内容 | 定向过程读取、变化通知 |
| API-18 | GET /resources/resolve | 新增 | Link/ref/相对引用解析为逻辑 ResourceLocator |

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
- InteractionItem：稳定 id/role/turn_id/content，适用的 input_id/question_id/call_id/ref/reply_to/delivery。pending_items 与已有事实顺序分开。
- ContextOverview/SegmentView：本次 installed 状态、descriptor/shape/root refs、适用 selection/usage、正文原始位置。
- ResourceDocument：locator/title/media_type/text或content/direct_refs/truncated/next_continuation。
- SearchPage：result_ref、scope/source、items、coverage、page/continuation；保持后端原结构。
- JobOutputPage：有界 channel/text、实际顺序、result_locators、next_continuation；不同流不强排精确因果顺序。
- PresetSummary：id/name/description/scopes/active_match/saved_match/validation_issues/updated_at。

普通列表默认 30、上限 100；普通文本页默认 16000、上限 64000 字符；Search/Disclosure 服从各 owner 预算。前端不靠截断 JSON 代替分页。continuation 失效与单纯网络错误分开显示，不自动重跑可能调用模型的查询。

### 3.4 查询参数与错误处理

| API | 页面使用的参数 |
| --- | --- |
| API-03 | continuation，返回 items 与 pending_items，后者不强行排序成 Trace |
| API-08 | /days: before/limit；turns: day/continuation/limit；turn: day/continuation；map: day；inspect: day/ref/query/continuation |
| API-09 | overview 使用明确 Turn ID；segment 正文按返回 continuation；inspect 使用 ref/query/continuation |
| API-10 | catalog: view/space/query/continuation；content: link/view/continuation；changes: continuation；diff: link/continuation |
| API-11 | active: day/continuation；catalog: kind/query/continuation；document: link/continuation |
| API-12 | 归档 GET 携带 day；resource 正文使用 continuation；blob 按需要使用 Range |
| API-14 | 明确 turn_id/job_id，output 使用 continuation |
| API-16 | tools 使用 server_id/continuation，详情可按 tool_name；refresh 明确 server_id |
| API-17 | after/mode/limit/instance_id；按需 turn_id/task_id/call_id/search_id/step_index/through，step_index 配合 search_id |
| API-18 | reference、可选 origin_link/day/turn_id/view，优先使用响应中已有 resolved locator |

错误外壳是 error.code/message/details。422 字段错误定位控件；409 config.activation_unavailable 保留草稿；404 不自动跳当前同名资源；context.unavailable 停止 live 读取；resource.unresolved_origin 显示需要明确来源。search.scope_required 提示缩小范围，search.view_expired 提供重搜，search.source_unavailable 显示来源问题，search.operation_failed 展示有限步骤失败，均不伪造空结果。已有接口 code 沿真实 schema；Observation gap 是缺失提示，不是断线。后端模块失败和清理诊断按作用范围呈现，前端不自动重启。

## 4. P00：应用外壳、连接与共享详情

启动顺序：建立连接 → health/status 确认 v2、project/instance/generation/ready → 加载当前页正式快照 → 订阅 events。ready=false 时状态页仍可读，不展示旧连接的资源为当前内容。

修改 `api/connection.ts` 和 Tauri discovery 的版本假设；以握手为准，删除硬编码 protocol_version=1 与 v1 transport。连接信息与 UI 偏好分开，切换项目不携带上个项目的草稿、Turn 或 Search 句柄。

连接入口支持项目/后端地址与真实状态、手动重连、明确的宿主重启。先保存 status 返回的 instance 与事件 cursor，再加载快照，并从该 cursor 订阅/补读过程；快照期间的新事件用于失效刷新，交互按 identity 去重，不因订阅开始较晚漏掉问题。旧 project/generation 的异步响应不得覆盖新连接状态；日志 gap 不清空已经由 Session 读出的对话。关闭页面或 WebSocket 不取消 Agent；重启是显式按钮，不把前端刷新变成重启。

共享 Inspector 保存来源/返回栈，支持关闭、返回、展开宽视图、复制真实链接。跳转后焦点落在详情标题，关闭回触发按钮。常规错误就地呈现；只有应用级连接状态才用全局提示。

使用 API-01/17；资源详情使用 API-18 路由，禁止自行从观测正文解析本地路径当作下载地址。

## 5. P01：主对话与 Composer

保留原 ChatView 的消息宽度、输入区、过程折叠、滚动锚定和 typewriter/motion 行为。顶部不新增日期条；底部输入区旁加入紧凑运行方案选择器，默认只显示方案名或自定义状态，展开才显示预算/模型用途摘要。

### 5.1 状态与操作

| 正式状态 | 输入行为 | 其它控制 |
| --- | --- | --- |
| idle | 新 User Turn | 允许切换方案 |
| User Turn preparing/running | 默认追加到已明确身份的 Turn；菜单可排队下一轮 | 停止当前 Turn |
| waiting question | 卡片内答复；Composer 可独立补充或排队 | 不把补充自动当 reply |
| waiting budget | 独立补额卡片 | 可与问题同时显示；停止仍可用 |
| Reflection 运行 | 普通消息排队 User Turn | 跳转 Reflection 详情，不追加到维护情景 |
| finalizing | 新消息排队下一轮 | 显示收尾，不能再向关闭的 Inbox 追加 |
| finished/句柄消失 | 使用当前状态决定新轮 | 历史内容只读 |

新轮 `POST /turns` 使用 `kind=user,text,command_id,metadata.client_message_id`；追加使用 `/turns/{id}/input` 的 text/input_id。普通聊天不使用终端式 `/input` 解析斜杠命令。队列项提供正文摘要和取消，取消仍走该 Turn 的 API-02。

发送中保留本地 ID。成功受理后按返回 identity 替换状态；重复 accepted=false 不是发送失败。失败保留文字与重试入口；Turn 已关闭时提供“作为下一轮发送”，不能悄悄改请求对象。取消回执仅表示已受理意图，实际结束后再关闭等待卡片。

问题、预算卡片立即出现，不排在长动画之后；用户上滚阅读时不抢滚动，显示“有新内容/待回复”入口；回到底部恢复跟随。窗口恢复不逐条播放历史。

### 5.2 运行方案快捷入口

列表展示名称、当前匹配、有限说明；“管理方案”进入设置。展开摘要包含受管组和关键预算；不提供虚假的统一模型/推理强度。

只有后端声明可应用时允许点击激活；运行期间可查看方案，但不显示已经切换的假状态。应用走 API-06，成功后重取 API-01/05/07；随后用户正常发送。切换与发起 Turn 是两次明确操作，不暗示原子性。

无方案或已偏离方案显示“自定义”。模型簇的 UI 收起与运行方案本身不是同一开关。

## 6. P02：提问、追加与回复卡片

### 6.1 呈现

agent.question 在原对话流内渲染：正文在上，选项为可点选卡片，必要说明在选项内，最后为“其他”输入；底部提交/提交中/已答状态。A/B/C 是视觉编号，提交使用稳定 option_id。

选择后可附 comment；默认不点击即提交，用户按“回复”确认。Other 使用自由文本。问题无 options 时直接文本输入。allow_other=false 不自行增加可提交自由回答，但 Composer 的独立补充仍存在。允许键盘选择、Tab 和明确提交，不用全局单键快捷键误发回复。

已回答卡片显示实际问题、所选 label 和补充文字，用户回复保持用户消息样式；不要把问题从历史删除或只剩一个“A”。补充输入以用户消息显示其关联 Turn，不伪装成新的完整问答。

### 6.2 协议与三种模式

QuestionContent 为 text/options[{id,label,description?}]/allow_other；最多 8 个选项，ID 唯一。`tinysoul-question` fence 的 JSON 使用 question 字段，后端归一化为 text。代码块本身不含执行地址或运行身份。

```json
{"question":"如何继续？","options":[{"id":"execute","label":"开始实施"},{"id":"explain","label":"进一步讨论"}],"allow_other":true}
```

- active：只有 API-02/03 的正式待答 question_id 才能提交 reply。
- compose：普通模型回答里的同类块，仅将选项正文放入 Composer，由用户发送。
- readonly：历史 ask 或已结束问题，只读显示，不发送过期 reply。

回复请求：

```json
{"question_id":"q1","answer":{"kind":"choice","option_id":"execute","comment":"先完成后端"}}
```

Other/自由回答：`{"question_id":"q1","answer":{"kind":"text","text":"我的补充……"}}`。后端校验并生成规范模型文本；前端不提交字符串 response 或只发送“A”。格式错误的普通 fence 回退可读代码，不制造等待状态。

预算卡片使用 request_id/count 调用 grant；回复不补预算，补额不答问题。若等待过期，刷新实际状态并保留未发送文本，不反复重试旧 question_id。

## 7. P03：历史对话与 Session

沿用对话历史/更多入口打开日期与 Turn 列表，不新增常驻日期栏。日期目录使用 API-08 /days；选择日期后取 Turn 摘要，打开一轮才取交互页；不读取整日模型日志作为历史。

摘要使用真实 initial/output excerpt、状态、问题数量。活动/排队项与已完成 Session 项分开；完成时以 turn_id 将活动内容整体接替成 Session 投影，避免 append 两套相同正文。必要持久化失败显示 TurnResult 的有限事实，不伪造“已保存”。

Session map 从 Context 中的 Session 入口或历史详情进入。默认阅读列表：话题/解释入口、相关 Turn、未归类交互；关系图作为展开视图。thread/note 与不可变事实视觉分开，有证据链接；共享节点与回路保留同一 ID，导航树不作为数据模型。

展开节点调用 /session/inspect 的 ref/continuation/query，显示真实 DisclosurePage；query 只定位该范围。用户可把整理要求写入 Composer，由 Agent 使用 Organize，不提供手改 map 按钮。历史日期只读，不承诺跨日语义图。

历史问题保持完整选项与回复。没有新选项 ID 的归档按原文显示，不能通过文字猜新协议身份。历史链接始终带 origin day/turn；“打开当前资源”若与历史不同要明确标识。

## 8. P04：Context Drawer

右上原 Context 按钮打开；默认当前活动 Turn。无活动 Context 时显示“当前没有运行中的语境”，可跳转历史 Session 或已记录模型请求，不展示上轮缓存为当前内容。

首屏只取 API-09 overview，按 Background、Trace、Working 分组；每段显示名称、简短状态与必要用量。选中段才读取正文。技术 descriptor/owner/shape 放详细信息，但 renderer 由它们驱动，不靠名称猜。

| 形状/内容 | 主要视图 | 交互 |
| --- | --- | --- |
| State | 当前字段/状态 | 阅读，按声明查看引用 |
| Heap | 顶层线索、默认/已加载项、可展开入口 | ref 逐层披露，标识是否已经进入模型语境 |
| Stack/Trace | 热记录与折叠节点、原事实顺序 | 展开节点、续页、回到父入口 |
| Map/Session | 事实/解释入口及历史交互 | 列表优先，可展开关系图与证据 |
| Working | plan/todos/milestones、Workspace 摘要、连接/Jobs 现态 | 跳对应详情，不常驻全部资源正文 |

段正文是本次已安装视图，不是 owner 最新文件。资源详情打开完整 Home/Memory 不等于该内容已经进入 Context。UI inspect 仅用户阅读，不执行 core.context.inspect、不追加工具结果、load/evict 或解除模型保护。

动态 memory 引用使用响应已解析 locator；无法确定原绑定时不自动打开当前 latest。能力未声明 query 时不显示范围搜索控件。usage 字符数不标成 token。

Context 更新时保留当前阅读位置，显示可刷新提示；刷新 overview 后按需重取段，不能将两份内容快照的分页混在一起。Turn close 后停止续读 live Context，已打开内容标记为刚才捕获的视图，历史跳转使用 API-08/17。

## 9. P05：Action、Search 与模型调用详情

保留原过程入口、ActionGlimpse 与折叠卡片的主要风格。路径是 Turn → Cycle → Phase → Action/模型调用；失败、未执行、取消、结果未知按正式执行状态展示，不能都当工具返回文本。

### 9.1 Action renderer

显式注册：精确 Action ID → 结果族 renderer → 通用结构视图。renderer 只处理呈现与导航，不执行后端动作。

| 结果族 | 默认展示 | 展开内容 |
| --- | --- | --- |
| Search | 来源、步骤与结果数，首批真实片段 | query/criterion/条件、逐步数量、证据/覆盖、原始结构 |
| Inspect/read | 所读资源与片段 | 原始范围、DisclosurePage、更多资源导航 |
| Workspace/Home/Memory 写入 | 操作、目标与结果 | 当时记录的变更片段/diff；打开当前资源另设按钮 |
| execution | 命令与状态 | 输出/退出结果、Job 或产物链接 |
| ACP | 委派目标、Job 状态 | 连接、任务输入、待处理请求、结果 |
| MCP | server/tool 与结果摘要 | 参数、真实 schema、返回内容 |
| core.reason/answer/plan | 模型实际披露的内容/状态 | 关联 Task、plan 变化与产物 |

没有历史 before/after 就只显示操作和 locator，不能查询当前文件充当历史差异。Unknown renderer 保留可读 JSON，不吞掉结果。正常视图不堆叠所有内部键。

### 9.2 Search 卡片

source query/backlinks/directory 发掘候选，refs/result 是已知入口；steps filter/select/rerank 按实际顺序显示。每个 criterion 独立，不把 query 自动改写为所有步骤的条件。

条目显示 title/ref、真实 evidence.text/位置、相关命中。用后端 matches 的区间高亮，不重新对整份结果做 lexical 筛选。Embedding 深层命中必须保留；LLM basis 表示所给真实片段指认，JEV Score 不虚构理由或“正确率”。

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

保留左侧文件/回收站与右侧编辑/预览，沿用当前目录宽度、标签与编辑体验。标题栏放路径、保存状态和必要操作；搜索与日期浏览按需展开，不常驻新仪表盘。

- 首次取 API-12 manifest；打开文件取 resource/blob。文本分段加载与完整编辑分开，拿到完整可编辑内容后才启用覆盖保存。
- 使用现有 directory/move/tags/edit/append/resource/blob/trash/restore，显示 owner 正式结果，不重新引入 digest/revision/CAS。
- 目录内名称筛选即时；点击“搜索内容”使用 API-13，scope 可为 Workspace/目录/文件，literal/regex 仅在能力支持时出现。
- 结果点击定位真实行/片段；引用可复制或填入 Composer。
- 归档从 /days 选择，所有 GET 明确 day；历史只读，不将归档内容 PUT 到当前同名路径。
- 外部变化时保留本地未保存草稿，显示“重新载入/继续编辑”的明确选择；未修改文件可以刷新。
- blob 流式/Range 用于预览下载；图片、音视频、其它文件按实际 media_type 处理，未知类型提供下载，不猜文件后缀已理解内容。

只有原有或明确支持的上传/创建流程调用后端写入；拖入文件失败保留清晰错误，不自动发起 Agent Turn。日切后当前列表切换，仍打开的归档资源保持明确日期。

## 11. P07：Home

新增左目录、中央阅读、按需变化/引用详情。顶部为 effective/actual 切换、目录筛选、内容搜索、变化入口和“整理 Home”；默认 effective。

目录按真实空间/类型组织：顶层内容、普通资源、通用 Skill、domain/action 指导。通用 Skill 可展开 SKILL.md 与资源；guidance 有清楚类型标识，不误称 Background 常驻技能。

API-10 catalog/content 根据 view 读取。打开资源不改变模型加载状态；若从 Context 进入，保留“已加载”来源提示，但全文仍是资源浏览。Home 没有每日快照，不提供按日还原按钮。

变化入口列 overlay 创建/修改/删除；选择资源查看 actual/effective diff，支持统一/左右模式与大段分页。没有变化时显示简洁空态。不直接提供接受/拒绝写 actual 的按钮。

“整理 Home”读取 API-04 availability，输入本次指令并发起 kind=home；已有根 work 时明确排队，跳运行详情。正常对话中的 Home 修改仍进入 overlay，不将 UI diff 面板变成第二套审核器。

内容 Search 使用 API-13，仅 effective 范围。actual 页面保留目录筛选；用户点击内容搜索时明确切到 effective，不在 actual 标题下显示 effective 结果。query/directory 的普通 Skill 按 top 聚合，backlinks 返回真实来源资源；进一步读取遵循 ref，不自动把 top 展开成全部深层内容。

domain/action guidance 可以浏览，但不出现在通用 Home 搜索空间。资源工具栏提供复制引用、在对话中引用、查看反链；反链是明确的 Search 请求，不在每次打开文档时自动调模型。

## 12. P08：Memory

新增左侧“活动记忆/持久知识”导航，中央文档，右侧引用详情按需打开。活动记忆使用日期选择器；持久知识按 daily/entity/concept/fact/note 分类和目录筛选。不要把日期切换解释成整个知识库时间旅行。

- API-11 active 读取当前/归档 Memory.md；daily 是持久文档，另有清晰入口。
- catalog/document 提供正文、类型、direct refs、迁移说明；redirect 显示“转向文档”入口，不暗中用目标正文替换旧文档。
- 文档缺失与内容为空分开；无知识时提供开始对话或整理入口，不展示宣传段落。
- 搜索框先确定范围/类别，明确提交后走 API-13；结果显示真实片段与来源。相关文档可使用当前 Memory document_ref query 能力，实际选项由 schema 声明驱动。
- “反向引用”以当前文档为 anchor 调用 backlinks；direct refs 与反链分栏，不把 Memory inspect 改成反链检索。
- 工具栏提供复制链接、在对话中引用；页面不直接保存持久文档。

“整理记忆”用 API-04 选择目标来源日与本次 instructions；默认建议来自 availability，不能总选当前执行日。排队/运行/结果进入统一运行观察。失败不会伪装成日归档失败，Reflection 与日切语义分开。

## 13. 共享页面搜索面板

用于 Home/Memory/Workspace；主界面保持 query、范围、明确提交按钮、结果列表。高级区提供 owner 声明的属性条件、literal/regex（适用时）、排除 refs；不把原始 JSON 管道编辑器作为常用交互。

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

## 14. P09：运行观察

顶部紧凑概览：Agent ready、当前 Turn/类型、真实等待原因、队列；不常驻长 UUID。下方 Execution、Jobs、ACP、MCP、Environment 五个分页，各自只在打开时读取详情。

### Execution

API-01/02 提供状态，API-17 提供过程。显示 preparing/running/waiting/finalizing/finished、有限失败与 cleanup；区分执行失败和结束后清理诊断。跳转主对话的问题/预算卡片，取消使用明确 Turn ID。队列取消不误停当前 Turn。

### Jobs

API-14 列表显示 kind/state/summary/所属 Turn；选中才取 detail/output，cursor 追加而非每次整段替换。输出页打开时才轮询/跟随，离开只停止读取，不停止 Job。停止按钮等待正式状态，不等于取消整个 Turn。

pending_inputs 表示父 Agent 待处理请求；需用户决定时跳主对话 ask，不增加用户直接回复 ACP 的接口。Turn 完成后 Job 被回收，显示实际产物链接和保留过程，不能保留可操作的假历史 Job。

### ACP

API-15 分配置目标与已建立连接；连接显示 idle/busy/不可用及关联 Job，跳 Job 详情。空闲连接可跨 Turn；连接不是一次委派。提供“在对话中委派”填入意图和“编辑配置”跳设置，不直接创建脱离 Turn 的委派。

### MCP

API-16 显示 configured/enabled、connected、discovered、callable 四类事实；工具列表用已发现目录分页，详情展示完整定义及配置选择状态。显式“刷新目录”调用 POST refresh；打开页面或搜索目录名字不自动建立远端连接。

工具启用/默认规则进入配置草稿，经 apply 生效；含点名称作为原子 tools map key，不拼子路径。提供“在对话中使用”引用工具说明，不提供任意 call 测试 RPC。

### Environment

API-01 sources + API-17 事件，按来源/topic/关联 Turn 筛选。显示实际已记录的接收/消费状态，不推测未记录阶段。watcher 失败仅提示监听问题，Workspace 仍可正式操作。观测窗口丢失显示缺口，不重造环境历史。

## 15. P10：设置外壳与统一草稿

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

所有 Agent 子页共用一个 ConfigDraft：saved 基线、按稳定配置身份组织的变化、字段问题。切页不保存；底栏显示修改数、重置本页、放弃全部、应用配置。对象内新增/排序先留草稿，不逐条调用 PATCH。

进入设置取 API-05 saved/active/catalog；Actions 页另取 active action catalog。明确区分运行值、已保存待激活、本地未提交；catalog 描述可配能力，当前可用性不由未应用草稿伪造。新草稿的引用与 schema 做本地验证，最终以 apply 结果为准。

Agent 忙碌时允许编辑，禁用应用并显示真实原因；不以 can_write 代替 can_reload。已有 pending 保存时提示本次应用会一并激活它们。无本地修改但 saved 待激活时提供明确 reload 入口，不伪造空 apply。

应用 API-06 成功后清草稿、重读状态/配置/方案/catalog；失败保留草稿并定位字段/来源或模块错误。放弃本地修改不撤销其它客户端的 saved。刷新发现 saved 变化：干净字段采用新基线，脏对象保留本地值并提示重新载入/保留，不引入后端 CAS 或复杂自动合并器。

离开设置可保留内存草稿并显示数量；关闭窗口有未保存更改提示。凭据值仅内存编辑，不写 localStorage 草稿，不混进运行方案。网络中断后先读真实状态，不无条件重复 apply。

## 16. P11：模型与服务各子页

### 16.1 LLM Provider

保留 ProvidersSettingsPage/ObjectSettingsLayout 的对象逻辑：左列表状态，右侧 id、adapters、base_url、api_key_envs、enabled。凭据区显示引用和就绪，编辑 secret 进入同一个 dotenv 草稿。配置启用与远端可调用不是同一状态，不用“已配置”绿点冒充连接实测。

支持新建、复制、删除；删除前展示引用位置，保留最终后端依赖校验。只显示实际字段；LLM 未支持的专用 Provider proxy 不强行提交。

### 16.2 LLM 模型

列表按 family 分组，collapsed 默认收起并有“显示折叠模型”；搜索可发现旧模型，被链引用的旧模型仍可读。family 是模型簇属性；用户临时折叠组是本地浏览状态，不能混写 collapsed。

编辑 id、adapter、能力、context_window、provider bindings、request overrides、adapter options、family/collapsed。Provider bindings 拖动排序，另有键盘上下移；每行明确 Provider 与 provider_model，不能将 Provider ID 当模型 ID。

高级参数按当前 adapter descriptor 条件显示，保留默认值与显式设置的区别。删除/改名影响引用时给明确定位，不自动选择替代模型。

### 16.3 LLM 任务链

保留 TaskChainsSettingsPage：左链列表、右有序模型项及 task 设置、被哪些 Phase/consumer 使用。拖动+键盘排序；加入模型仅选 LLM，专用 use 不进入链。

Task max_cycles/重试与 Agent Turn max_cycles 分开解释；不能共用一个“思考次数”控件。链可多处复用，编辑影响所有引用；Action 页选择链并跳到此页编辑，不复制一份私有链配置。

### 16.4 专用 Provider

同样采用对象编辑，依据 `infra.model_services.providers` 的真实数组结构：id、adapter、base_url、api_key_env、enabled、timeout_seconds、max_retries、proxy。Provider adapter 区分 Embedding 与结构化评估。

这些字段以整数组操作进入草稿；UI 按稳定 id 更新，数组下标不作为对象身份。排序 Provider 链发生在模型内，不将 Provider 目录显示顺序解释成全局优先级。

### 16.5 专用模型与逻辑用途

模型列表按 Embedding/JEV 能力分组；编辑 id/kind、provider_bindings 的有序 provider_id/model、实际支持的 dimensions/batch_size。Embedding 需要维度，JEV 不显示向量维度控件。

用途子页编辑 use_id/kind/model_id，并显示真实 consumer 引用；一对一模型，不再增加 model chain。未被选用的目录可保存未就绪连接，启用用途时依赖必须满足正式规则。

JEV 名称配合“结构化评估/评分”用途说明，不把当前 Score 接口宣传为任意文本生成。Home/Memory embedding_use 的编辑位于相应 owner 设置，此处显示被谁使用并跳转。

### 16.6 凭据与生图预留

凭据页集中列环境引用及来源/就绪；相同引用共用一条编辑，固定 env/header 与 env_refs/header_refs 区分；无需为每页重建密钥表。

生图子页在“模型与服务”中有独立入口，简洁显示“尚未接入”和将采用 Provider→模型→用途的归属；不提供失效的新增/保存/测试控件，不向后端提交 image_generation 类型。不为预留引入一套独立配置存储。

## 17. P12：行为、Actions、Search 与预算

### 17.1 Phase 调用分配

Phase1/Phase2 分别选择真实 LLM task profile，并可跳转链编辑；不提供当前不存在的 JEV Phase 切换。此处管理框架调用，Actions 页管理内部用途，两者不混成全部“LLM Actions”。

### 17.2 Actions

左侧 domain 与名称搜索、scenario 筛选（user/home_reflection/memory_reflection）；右侧分行为、模型用途、协议详情。行为显示 selection/visibility 的当前值与来源、granted/supported/available、超时/批次等真实设置。

scenario 决定可用能力视图，不自动产生三套模型绑定。Reflection 中的 memory.write/write_daily/home.review 是确定性行为，不能为保持布局加入虚构 LLM 选择器。

模型用途按 consumer 展开：operation、允许 implementation、当前 target 和 options。LLM 选任务链，JEV 选逻辑 use，Embedding 按 descriptor 引用 owner 用途。不可用实现只在真实 descriptor 支持时出现；不从 executor 名猜能力。

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

列表显示名称、简短说明、active/saved 匹配状态与依赖问题；右侧详情显示受管范围、任务链/用途/预算摘要。支持新建、复制、重命名、删除、覆盖捕获、应用；删除不影响当前配置。

捕获源选择当前运行、已保存、或当前草稿。草稿捕获使用 `source=saved + operations`，只保存方案，不应用配置。只有显式覆盖才更新快照，重命名不重抓当前值。

范围固定且在详情清楚说明：

- 必选：完整 llm.models（包括 family/collapsed）、llm.tasks；Phase1/2 链绑定；完整 Action implementation/target/options；retrieval query.channels。
- 可选 budgets：loop.user.max_cycles、reflection.home/memory.max_cycles、session.background_max_chars；context.budget_max_image_bytes、compression_trigger/target_ratio、trace_chunk_max_chars/branch_factor/min_hot_entries/inspect_max_chars；每个 retrieval 的 max_steps、snapshot_max_chars、page.max_items/max_chars、已开放 select/rerank 的 input_max_chars。
- 不包含 Provider 连接/凭据、专用模型与 uses 目录、Home/Memory embedding_use、paths、system_text、调度、visibility、sources/operations/allowed_context、知识正文和本地外观。

所以方案可改变 LLM/JEV 选择与是否使用已有 Embedding 通道，不更换向量空间。没有 budgets 的方案保留当前预算；有 budgets 完整替换该组的默认/显式值。不要把缺省显示成 set(null)。

API-07 捕获 `name,description,source,operations?,include_budgets`；PUT 只有 capture 明确存在才覆盖；API-06 preset_id 激活。依赖缺失时列出具体目标并跳设置，不能自动补造模型。忙碌可编辑方案记录，应用仍受正式 idle 条件约束。

配置 sources 的物理路由、preset 文件内容由后端管理，前端不直接读写 configs/presets。方案不作为运行时叠加层。

## 20. P15：界面本地设置

本地即时保存主题、字体/字号、行高、代码字体、密度、减少动画、自动跟随、通知与目录/详情宽度。采用统一 tokens，不让各页保存相互冲突的字号。提供本地“恢复默认”，不改 Agent 设置。

偏好可全局共享；页面选择、资源打开状态按项目命名空间保存；Search 句柄、活动 Turn 控制身份和 secret 不长期保存。系统通知只来自真实运行状态，点击跳对应 Turn/资源，不从长日志关键词猜完成。

显示字体选择的真实预览即可，不加解释性演示页。键盘 focus、对比度、字体缩放和 reduced-motion 覆盖所有新增卡片与图表。

## 21. 共享渲染与资源路由

### 21.1 CodeBlockRegistry

在现有 ReactMarkdown/remark-gfm/math/KaTeX 基础上增加显式注册：language、parse、render、fallback。Question、Mermaid、TikZ 是具体消费者；未知 fence 保持普通代码。不会把任意 Markdown 代码当作可执行 JavaScript。

Question 采用 §6 协议与 active/compose/readonly 模式。Mermaid 使用官方 render API 生成 SVG，按需加载，支持图/源码切换、缩放和导出；flowchart 采用 Mermaid 的图语法，不再平行引入同义引擎。TikZ 使用 TikZJax 的浏览器编译路径，将运行时与资源封装在专用渲染容器中，单独加载并输出 SVG；不把其全局扫描混入 React 主文档。

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

点击跳转、复制原引用、“在对话中引用”是不同操作；引用仅填入 Composer，用户决定发送。Search result_ref 和内部模型短 ID 不提供永久资源跳转。相对图片等资源也通过 owner 解析与 blob 获取，不把原文路径拼成任意 URL。

### 21.3 独立注册职责

ActionRenderer、CodeBlockRegistry、ResourceRouter、Settings editor adapters 分别负责结果、内容协议、定位、配置编辑。可以共用 DisclosureBrowser/ResourcePreview，不合并为一个万能插件容器。所有扩展在应用装配时显式组合，有真实调用者才建立接口。

## 22. 前端代码组织与迁移

保留当前 React 19/TypeScript/Vite/Tauri/Zustand/Tailwind/motion 等基础，不为架构整齐更换技术栈。

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

## 23. 实施阶段

阶段均为 pending。依赖表示实施顺序，所有页面和共享能力属于本轮完整交付。

| 阶段 | 工作 | 依赖与退出条件 |
| --- | --- | --- |
| F0 契约接收 | API-01～18 类型/fixtures、Browser/Tauri v2 连接、能力核对 | 后端 B7 交付；不凭示意图猜字段 |
| F1 数据与壳 | 正式实体缓存、事件失效、共享详情、导航 | status/Turn/Session 来源区分正确 |
| F2 设置与方案 | P10～15、统一草稿、模型/用途、apply/presets | 多页编辑/应用/失败/重置、方案切换闭环 |
| F3 对话与历史 | P01～03、Question/预算、追加/排队、历史接替 | 正常交互不丢、不重复，原滚动体验保留 |
| F4 Context/Action/模型 | P04～05、Search renderer、provenance | 读视图无执行副作用，模型详情真实 |
| F5 资源与链接 | P06～08、共享 SearchPanel、ResourceRouter | 日期/view/动态绑定正确，归档只读 |
| F6 运行与代码块 | P09、Mermaid/TikZ/通用 registry | 真状态、显式刷新、图渲染与失败回退 |
| F7 收口 | 清理旧逻辑、性能、响应式、主题、文档 | 全部页面验收、测试和 build 完成 |

前端工作只修改 visualization 及其文档。遇缺失能力，在 `visualization/docs/demand/` 记录具体页面、请求/结果、owner 和复现；可用与已定契约一致的 fixture 开发，不把 mock 当成功集成。若实际后端契约需要调整，更新两份计划与接口文档，不能加一层前端猜测兼容。

## 24. 验收与性能要求

### 24.1 必须走通的完整场景

- [ ] 空项目连接、重连、ready=false、generation 切换与观察缺口，业务历史不被事件丢失破坏。
- [ ] 新 Turn → 追加 → ask → choice/Other → 补充 → 完成 → 刷新，身份/顺序/全文正确；输入未受理和已受理状态明确。
- [ ] 问题与预算同时等待，各自提交；排队/取消/finalizing 正确；Reflection 运行不误接普通追加。
- [ ] 运行方案应用后实际 LLM/JEV 与 query 通道改变；运行中不可假切换；缺引用清晰定位。
- [ ] 多页配置草稿、对象排序、含点 map、整批凭据+配置、应用失败/重置、已有 pending 配置的说明正确。
- [ ] family/collapsed 展示不禁用模型；LLM/专用 Provider 与用途引用真实；生图预留无假保存。
- [ ] Context 三槽四形状、折叠披露、Session 证据；UI 阅读不改变模型语境；历史 Task 与当前 Context 不混淆。
- [ ] Search 真片段/双通道命中/评分/覆盖、result 派生、续页与失效；页面不调用 current Context，不卡在隐式 top-k。
- [ ] Workspace 完整编辑/外部变化/归档；Home actual/effective/diff/Reflection；Memory active/daily/知识/反链/redirect。
- [ ] 资源链接正确进入 day/view/fragment；动态引用无绑定时明确；网页打开外部浏览器。
- [ ] Job 输出/停止、ACP 连接与委派区分、MCP GET 无副作用及显式刷新、watcher 状态正确。
- [ ] Question active/compose/readonly、Mermaid、TikZ、普通代码和错误回退；大图不阻塞主对话输入。
- [ ] 明暗主题、小窗口、字号缩放、键盘焦点、reduced-motion；无演示口号与新增常驻聊天日期栏。

### 24.2 测试组织

TypeScript 契约与核心状态合并用单元测试；Question/ConfigDraft/排序/ResourceRouter 用行为组件测试；代表性 Browser 流程用 Playwright。fixtures 取自后端真实 schema；fake timers 替代长 sleep，不用大批全页面快照固化像素或字段顺序。

至少覆盖 API 重连后交互去重、pending→Session 接替、配置失败保留、Search lifecycle、实际路由来源。不要为低影响样式改动写镜像实现的测试。

运行仓库 package.json 的 `npm test`、`npm run build`；按已配置方式执行新增端到端测试。Tauri 连接/外链/本地资源与 Browser 均做代表性验证，记录环境和未覆盖项，不用 Browser build 代替桌面集成结论。

性能验证针对实际风险：聊天打开不加载全部 model 正文，设置刷新不逐字段 HTTP，Job 输出只读新增页，图模块按需加载，运行事件不触发全局大列表重算；不创建无使用场景的独立性能平台。

## 25. 交付与文档规则

每阶段记录改动文件、真实完成项、命令/结果、剩余缺口和可用 commit 文本。前端设计说明同步到 visualization 文档，Endpoint 使用与后端已发布契约一致；无消费者组件、重复状态或临时兼容分支在 F7 删除。

只有 F0～F7、所有页面、接口集成和必要验证逐项完成，才将计划标为 done，并按 AGENTS.md 移入 `docs/analysis/done/` 加 `-done-`。本计划当前是完整可实施设计，不是已完成实现或测试报告。
