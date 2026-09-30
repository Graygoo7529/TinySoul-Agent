# Action 渲染器覆盖矩阵（F4-B，计划 §9/§21.3）

本文档记录 `src/features/trace/` 的 ActionRenderer 注册与覆盖情况。Action ID 以当前 Action Catalog 的 canonical 名称为准（`tinysoul/assets/common/configs/action/catalog/*/actions/*.toml` 的 `name`，共 63 个），注册表是 `registry.ts` 的 `ACTION_FAMILY` 显式映射：精确 Action ID → 一个主结果族 → 通用结构视图兜底。无别名、无旧名兼容映射。

`registry.test.ts` 把下表 ID 全集作为快照断言：后端增删 Action 时，注册表、本矩阵与测试一起更新，不存在静默漂移。

## 结果族规则

- 一个 Action 只选一个主结果族；族之间复用共享组件（引用按钮、事实行、Search 卡片、有界文本），不为每个 Action 复制组件。
- 渲染器只处理呈现与导航，不执行后端动作；摘要行与展开内容全部来自该次调用真实记录的 payload/params，缺字段就少显示，不猜。
- 事件是过程详情的定向读取来源；正式状态以 owner 投影为准。失败、未执行、取消、结果未知按正式执行状态分别展示，不压平成"工具返回文本"。
- 未知 Action（例如更新后端的新动作）落入通用结构视图：保留可读 JSON（结果与调用参数），不吞掉结果。当前 Catalog 中没有任何已知 Action 以通用视图验收——全部 63 个 ID 都有明确族归属，见下表。

### 不虚构原则（全部渲染器共享）

1. 没有历史 before/after 就只显示操作与 locator，并注明"未记录变更前后"——打开链接看到的是 owner 当前内容，绝不查询当前文件冒充历史差异。
2. 无 result 的 Action 按执行态如实说明（未执行/已取消/结果未知/进行中），不伪造工具结果。
3. 高亮只用后端 matches 区间（Unicode 码点映射后切片）；无 matches/basis 时正常显示真实片段，不在前端补造语义命中。
4. source_score 与 evaluation.score 是两个分开的事实，永不合并成一个排行分数。
5. Search 卡片展示 Agent 实际返回的那一页；continuation 属于原 Turn/profile，不提供翻页按钮，Turn 结束不保留假可用游标。
6. 模型调用视图按 task_id/call_id/search_id(+step_index) 定向读取并在打开时固定 through 上界；缺失记录显示"未保留/已截断"，不从别的调用拼补；导出只含实际保留记录并附截断说明。
7. LLM 请求是 TinySoul provider-neutral 记录，不称"网络原始请求"；只展示实际记录的 reasoning summary，不声称能展开供应商内部推理。
8. Reflection 处理对象（home.review/diff、memory.write/write_daily）展示提交结果与读取入口，不提供前端直接审核/编辑按钮；Session 整理只描述语义解释变化，不显示为编辑原始会话。

## 覆盖矩阵

"摘要字段"指对话内联卡（ActionGlimpse）收起时的一行摘要；"展开内容"指卡片展开/详情面板的族视图；"关联"指资源（ResourceRouter）、Job 面板、模型调用 Inspector 的导航。

| Action ID | 结果族 | 摘要字段 | 展开内容 | 关联 |
| --- | --- | --- | --- | --- |
| core.answer | core-dialog | 回答摘录 | 实际披露内容与引用（成功回答在对话流中为答案卡） | 引用 → 资源路由 |
| core.ask | core-dialog | 问题摘录 | 选项与说明（成功提问在对话流中为问题卡 §6） | — |
| core.reason | core-dialog | 推理摘录 | 实际披露的推理文本 | — |
| core.wait | job-control | 等待条件（event_kind/topic） | 超时、条件、实际等待结果 | — |
| core.job.status | job-control | job_id · state | Job snapshot 描述 | Job 面板 |
| core.job.wait | job-control | job_id · ready/timeout | 等待结果与超时事实 | Job 面板 |
| core.job.stop | job-control | job_id · 停止意图 | 停止回执（不冒充已结束） | Job 面板 |
| core.session.organize | session-organize | N 个解释 ref 更新 | changed/created refs、不可变事实注记 | ref → Session 历史 |
| core.context.inspect | inspect | 所读 ref/范围 | DisclosurePage 内容、范围 | ref → Context/资源 |
| core.context.search | search | 结果数 · source | Search 卡片（§9.2） | item ref → 资源路由；search_id → 模型 Inspector |
| execution.start | execution | job_id · state / exit | JobSnapshot、启动事实 | Job 面板；产物链接 |
| execution.run_shell | execution | exit N | stdout/stderr 尾部、截断注记 | Job 面板；产物链接 |
| execution.run_script | execution | exit N | 同上 | Job 面板；产物链接 |
| execution.stdin | execution | job_id · state | 写入事实与 Job 状态 | Job 面板 |
| execution.collect | execution | job_id · exit N | 终态、输出尾部 | Job 面板；产物链接 |
| expand.call | mcp | 内容摘录 | 参数、返回内容、is_error | — |
| expand.describe_servers | mcp | N servers | server 目录页 | — |
| expand.describe_tools | mcp | N items | tool 目录与真实 schema | — |
| expand.search | mcp | 结果数 · source | Search 卡片（MCP 目录管道复用） | search_id → 模型 Inspector |
| home.search | search | 结果数 · home | Search 卡片 | item ref → Home；search_id → 模型 Inspector |
| home.inspect | inspect | 所读 ref | DisclosurePage/目录内容 | ref → Home |
| home.diff | reflection-write | N items | overlay 变化条目（review json/缺失说明） | link → Home |
| home.review | reflection-write | N items 处理 | 各项决定/原因；无前端审核按钮 | link → Home |
| home.top.write | write | 目标 link | 操作 + locator + 无 before/after 注记 | link → Home |
| home.top.patch | write | 目标 link | 同上 | link → Home |
| home.top.delete | write | 目标 link | 同上 | link → Home |
| home.resource.write | write | 目标 link | 同上 | link → Home |
| home.resource.patch | write | 目标 link | 同上 | link → Home |
| home.resource.delete | write | 目标 link | 同上 | link → Home |
| home.prompt_mount.write | write | 目标 link | 同上 | link → Home |
| home.prompt_mount.patch | write | 目标 link | 同上 | link → Home |
| memory.search | search | 结果数 · memory | Search 卡片 | item ref → Memory；search_id → 模型 Inspector |
| memory.inspect | inspect | 所读 ref | 文档内容、direct refs | ref → Memory |
| memory.memorize | write | memory:current | changed/cleared/chars 事实 | — |
| memory.write | reflection-write | 提交 link | 原子替换结果、读取入口 | link → Memory |
| memory.write_daily | reflection-write | 提交 link | 同上 | link → Memory |
| subagent.agents | acp | N agents | 已配置 agent 列表 | — |
| subagent.connect | acp | connection_id | 连接事实 | — |
| subagent.delegate | acp | job_id · state | 委派输入、Job 状态 | Job 面板 |
| subagent.respond | acp | connection_id | 回应事实 | — |
| subagent.collect | acp | job_id · state | 待处理请求、结果 | Job 面板 |
| subagent.disconnect | acp | disconnected | 断开事实 | — |
| web.search_by_kimi | web | 回答摘录 | answer、结果列表、截断/see_more | 结果链接 → 外部浏览器 |
| web.fetch_with_trafilatura | web | 页面标题 | extractor、标题、摘录、产物 markdown、警告码 | markdown_link → Workspace；来源 URL → 外部 |
| web.fetch_with_defuddle | web | 页面标题 | 同上 | 同上 |
| web.discover_pages | web | N pages · host | 来源、页面目录、停止原因、失败数 | 页面链接 → 外部/资源 |
| workspace.search | search | 结果数 · workspace | Search 卡片 | item ref → Workspace；search_id → 模型 Inspector |
| workspace.read | inspect | 目标 link | 所读文本范围（真实区间） | link → Workspace |
| workspace.list | inspect | N resources | 目录页、next_offset | link → Workspace |
| workspace.trash_list | inspect | N resources | 回收站目录 | link → Workspace |
| workspace.analyze | analysis | intent — 摘要 | 实际分析内容、来源、覆盖 | sources → Workspace；模型调用 |
| workspace.describe | analysis | 摘要 | 资源描述结果 | link → Workspace |
| workspace.compose | analysis | 摘要 | 生成内容、产物 | 产物 → Workspace |
| workspace.convert_with_pypdf | analysis | 转换产物 | converter、产物 markdown、视觉引用、警告码 | 产物 → Workspace |
| workspace.convert_with_markitdown | analysis | 转换产物 | 同上 | 产物 → Workspace |
| workspace.write | write | 目标 link | 操作 + locator + 无 before/after 注记 | link → Workspace |
| workspace.append | write | 目标 link | 同上 | link → Workspace |
| workspace.edit | write | 目标 link | 同上 | link → Workspace |
| workspace.mkdir | write | 目标 link | 同上 | link → Workspace |
| workspace.move | write | 目标 link | 同上 | link → Workspace |
| workspace.delete | write | 目标 link | 同上（移入回收站语义由后端表达） | link → Workspace |
| workspace.tag | write | 目标 link | 同上 | link → Workspace |
| workspace.restore | write | 目标 link | 同上 | link → Workspace |

## 代表性样例（测试锚点）

每个族选能区分真实行为的样例，不为每个 Action 复制用例：

- **search**：`searchResultView.test.tsx` 用契约 fixture `search-evidence.json`——真实 evidence 高亮（码点映射含 emoji/CJK）、无 matches 片段如实显示、双分数分离、覆盖注记与 continuation 提示。
- **inspect / write / web / analysis / execution / job-control / acp / mcp / session-organize / reflection-write / core-dialog / generic**：族视图经 `actionGlimpse.test.tsx`（写入无 before/after 注记、失败 feedback、执行态区分）与 `panels.test.tsx`（失败详情、无 result 说明、模块域关联模型调用、Job 分页）覆盖；generic 兜底由 `registry.test.ts` 的未知 ID 断言与 `FAMILY_VIEWS.generic` 存在性保证。

## 已知边界

- 历史轮（Session 投影）的 agent.action 只携带 action/outcome/failure/references，无 result payload——历史内联卡展开时族视图以"无记录 payload"呈现，详情面板经事件定向读取补齐（保留窗口内）。
- Action 参数只存在于 verbose 事件流；保留窗口截断后详情面板标注 truncated，不从别处拼补。
- Observation level 为 normal 时 model 级 request/response 不记录，模型 Inspector 如实显示"未记录"。
