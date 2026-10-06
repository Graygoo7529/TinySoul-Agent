# 引用格式与渐进读取

本文记录代码、默认资源和公共接口共同采用的引用格式。引用由各 owner 产生和解释；调用方保留完整字符串及有意义的日期、情景绑定，不自行构造路径或兼容别名。

## 设计意图与公共语法

引用负责精确定位，旁边的标题、摘要或摘录负责让人和模型理解。模型选择一个有解释的引用，调用所属域的 Inspect 获取需要的内容，再沿返回的直接引用继续读取。Inspect 是共同抽象原语，各插件保持自己的 Action、能力和所有权，不设置跨 owner 的万能读取门面。

```text
命名空间:目标层级[#目标内部位置]
```

- 冒号表示归属；命名空间是稳定的逻辑归属，不等于 Python 包名或磁盘目录。
- 斜线表示该 owner 内的层级；目标可以是逻辑入口、资源、交互或解释对象。
- 井号表示目标内部位置；内容片段、事实位置和压缩节点由所属 owner 解释。
- 模型使用系统返回的完整引用。标题、显示缩写和临时搜索候选编号不能替代精确值。
- 引用存在不代表任意工具都能读取它；profile 授予的能力、目标种类和生命周期仍由 owner 校验。

资源名称与内部标识遵守各 owner 的命名规则。引用不是任意物理路径，也不因外形接近 URI 而自动获得通用 URL 解析、转义或访问能力；产生和解析引用必须使用同一 owner 协议。

模型导航用“解释 + 引用”作为一个单元。折叠时二者共同移入父层，父层保留自己的解释与入口；Inspect 返回正文和可继续读取的子入口。不把所有子引用永久铺在顶层，也不留下无法定位的纯总结。

## Home

| 目标格式与示例 | 语义 |
| --- | --- |
| `home:top/agent/identity/soul` | agent 顶层逻辑入口，不带物理文件后缀；可以由已授予的 Background 控制加载 |
| `home:top/skills/tinysoul-docs` | 通用 Skill 的入口正文，通常对应 SKILL.md；不隐式读取整个目录 |
| `home:resource/agent/context/working.md` | Home 中保留实际扩展名的文件资源 |
| `home:resource/skills/tinysoul-docs/references/guide.md` | Skill 内的按需资源 |
| `home:mount/domain/workspace` | 对应 domain 任务的局部 Skill 挂载 |
| `home:mount/action/core/ask` | 对应 Action 任务的局部 Skill 挂载 |

`top`、`resource`、`mount` 明确表达入口类别。顶层与文件资源都可由 Home 的读取能力解释，但深层文件不因可读取就成为常驻 Background。任务挂载仅服务相应 TaskPrompt，不自动成为普通 Inspect/load 入口。

顶层入口和文件资源可能指向同一底层内容；加载资格与内容身份是不同问题。Home owner 负责在存在性、相对引用和 backlinks 中解析它们的关系，不由调用方拼路径或建立全局别名表。

## Memory

| 格式与示例 | 语义 |
| --- | --- |
| `memory:daily/2026-10-06` | 持久 daily 文档 |
| `memory:entity/tinysoul` | 实体文档 |
| `memory:concept/context-projection` | 概念文档 |
| `memory:fact/f-0123456789ab` | 具有稳定身份的事实文档 |
| `memory:note/n-0123456789ab` | 具有稳定身份的笔记文档 |
| `memory:current` | 当前情景绑定的活动记忆 |
| `memory:latest` | 严格早于来源日的最近持久 daily；缺失时不制造目标 |
| `memory:target` | Memory Reflection 绑定的目标来源活动记忆 |

持久引用不带 `.md` 或物理存储层级；entity/concept 使用 owner 允许的名称，fact/note 保持稳定身份并在旁边显示真实标题。文档可以更新，身份稳定不保证正文永远不变。

动态入口依赖 Context 情景及来源日，不是持久写入地址；读取方式以已安装的能力为准。历史记录如果保留动态引用，必须保留当时的绑定，不能把过去的 latest 重新解释为今天的 latest。

## Workspace

| 格式与示例 | 语义 |
| --- | --- |
| `workspace:docs/plan.md` | 当日工作区的文件资源 |
| `workspace:docs` | 当日工作区的目录资源 |
| `workspace:docs/plan.md#L10-L20` | 文件内第 10 至 20 行 |
| `workspace:docs/plan.md#design-goals` | Markdown 中相应标题的内容范围 |

路径相对活动 Workspace，使用 `/`，目录规范引用不带末尾 `/`。文件与目录由 owner 判断，不通过文件扩展名或显示 label 猜测。

完整 Workspace 搜索范围是范围选择器，不是空资源引用；`{"kind":"workspace"}` 表达全范围，文件/目录范围使用 `{"kind":"file","ref":"workspace:docs/plan.md"}` 或 `{"kind":"directory","ref":"workspace:docs"}`。普通模型不通过旧日 Workspace 字符串取得跨日读取能力。

`workspace.inspect` 无内部模型调用，按引用及可选片段返回真实正文。小文本完整返回，大文本按 continuation 和 max_chars 续页；目录给出直接子项的名称、说明与引用，非文本只返回类型和元数据并说明需要对应读取或转换能力。`workspace.read` 保留其原有行范围接口。Working 只显示资源说明和引用，Inspect 正文通过实际 ActionResult 进入 Trace。

该读取结果采用有界折叠：实际返回的正文页先进入一次取得响应的主循环 Phase1/Phase2 的 LLM 请求，随后才可按容量移除正文展示层，保留资源说明、精确引用、请求/实际范围与执行状态。解除保护不立即触发折叠，也不表示模型已经理解或完成使用。Session 在 completion 时直接保存这一读取事实，与活动 Trace 是否曾折叠无关。回忆 Action 能理解当时读了什么；需要内容时再次 Inspect 当前资源。行范围或标题可能随文件更新而改变，不承诺恢复旧页，也不建立资源版本库。

按 ref 选段、可选 continuation 和单页预算继续成立。“完整结果”指本次实际返回的有界页面，不要求整份文档或整个请求范围一次进入模型。选段决定读哪里，页面预算决定这次返回多少，展示保护决定这次返回页何时可以移出直接可见语境。每次续页是新的读取结果，分别遵守展示保护。这里的主循环 LLM 明确指 Phase1/Phase2；Action 内部的 LLM、JEV 和 Embedding 不解除展示保护。

## 活动 TurnTrace

| 目标格式 | 语义 |
| --- | --- |
| `turn:trace/<turn-id>` | 活动 Turn 的 Trace 根 |
| `turn:trace/<turn-id>#input/0` | 已接受且达到相应可见边界的第一个输入位置 |
| `turn:trace/<turn-id>#action/0` | 按原始请求顺序确定的 Action occurrence |
| `turn:trace/<turn-id>#entry/<entry-id>` | Trace 中的具体条目 |
| `turn:trace/<turn-id>#node/<node-id>` | Trace 压缩层级中的节点 |

所有内部位置共用同一个根。`<turn-id>` 为 `YYYY-MM-DD/<sequence>`，日内序号从 1 开始，例如 `turn:trace/2026-10-06/42#entry/17`。input/action 是从 0 开始的事实 occurrence；entry/node 各自在所属 Turn 内从 1 分配固定序号。不能在抽取部分事实、排序、失败或压缩后重新编号。外部 input_id、问题关联及 action call/result 身份继续服务原协议，不因引用简短化而一并改成 occurrence。

压缩只改变可见投影，已发出的入口仍能定位所保留的事实。引用不会因为压缩节点移动而改指别处。活动 Trace 不提供裸 `turn:trace` 别名，也不让新 Turn 读取旧活动 Trace；User Turn 完成后通过 Session 的持久事实位置回忆。

Action fact 引用可以读取本轮已结算、仍由 Trace 持有的实际 ActionResult；Entry 引用读取相应叙事条目保留的内容。读取 Action A 的 Inspect B 会产生自己的结果，B 的正文可以折叠为读取意图、目标引用与覆盖信息，不因此删改 A 或限制其它 Action 的可读取结果。Session 按 A 自身的保留契约提交事实，不能把活动 Turn 的可读性推导成跨 Turn 保存旧正文的承诺。

## 当日 Session

| 格式与示例 | 语义 |
| --- | --- |
| `session:map` | 语义地图入口 |
| `session:history` | 按历史顺序组织的 Turn 目录 |
| `session:topics`、`session:annotations`、`session:unclassified` | 话题、注释和未归类事实目录 |
| `session:history/16` | 从第 17 个 Turn 开始的有界目录组；数字是分组起始位置 |
| `session:turn/<turn-id>` | 一轮已完成 User Turn |
| `session:turn/<turn-id>#input/0` | 第一个输入事实 |
| `session:turn/<turn-id>#actions`、`#action/0` | 该轮 Action 集合或一个 Action |
| `session:turn/<turn-id>#output`、`#working` | 正式回答或已保存 Working 事实 |
| `session:turn/<turn-id>#note/0` | 已保存的 note 事实 |
| `session:turn/<turn-id>#resource/0` | “这一轮引用过某资源”的出现位置 |
| `session:node/2026-10-06/7`、`session:edge/2026-10-06/12` | Organize 持有的解释节点与关系，分别在所属日从 1 分配固定序号 |

片段的简写示例继承同一 Turn 根。资源出现位置的 ref 与被引用资源的 target_ref 保持区别。thread/note 的名称和解释可修订，稳定节点身份不随标题重命名。

Turn 示例为 `session:turn/2026-10-06/42`，与活动 Trace 使用同一个 Turn 身份。Agent 在启动时依据活动日分配；排队请求另有 request_id，不能拿请求接受日期充当 Turn 日期。User/Reflection 共用日内序列，Session 只收录 User Turn，因此编号不要求连续。日期仍不授予跨日模型读取能力。

线性历史以 Turn 分隔，保留有价值的交互和 Action 结果；map 提供解释关系和导航。Session 只保存实际提交的事实，历史 Action 引用只能恢复已经保存的结果，不能凭资源引用推导当时未保存的文件全文。

## 文档片段和相对引用

正文行范围规范输出 `#L10-L20`，单行可用 `#L10`，行号为 1 起始、两端包含。非法范围应返回明确反馈；前端不得把反向范围静默修正为另一范围。读取范围较大时，通过同一入口分页，不因单页返回结束就声称整份文档已读完。

Markdown 标题片段采用 owner 共用的真实标题 slug 规则，例如 `#design-goals`、`#原则`；重复标题使用该规则生成的后缀。标题可能改变，片段不是永久内容版本身份。

Markdown 中的 `../guide.md#section`、`#section` 依赖来源文档解析。owner 提供完整引用供后续工具使用，显示标签用于解释用途。文件标题、命中范围、引用目标与来源原文各有不同职责，不能通过 label 猜测精确身份。

## 专用身份与读取状态

| 形式 | 语义及边界 |
| --- | --- |
| `mcp:<server-id>/<tool-name>` | MCP 工具目录候选；由 expand 的操作解释 |
| `trash:workspace/<id>` | 已删除 Workspace 项目的恢复身份 |
| `workspace_archive:<day>[/path]` | 已有 Reflection 等情景安装的归档视图；不授予普通模型新的跨日读取能力 |
| `local:<name>` | 一次 Organize 请求内声明新解释对象的局部身份 |
| `search-result:<id>` | 由 result_handle 承载的临时完整搜索结果集，可供同一搜索作用域继续处理 |
| continuation、cursor、offset | 所属读取协议中的续页或位置，不是长期内容身份 |

Search result_handle 指向最终保留的完整集合，不只指当前页面，也不包含已筛掉的候选。它与 continuation 都可能随所属生命周期或容量回收失效；不能保存为长期内容引用或交给普通 Inspect。

scope 中的 all/trace/session 等选择器，以及 question_id/job_id/call_id 等业务身份，不因为字符串可指代某物就自动获得 ref + Inspect 语义。

Execution/ACP 的 cwd 参数还支持 `workspace:` 表示活动工作区根目录；这是已有 cwd 操作约定，不是可交给普通 Workspace Inspect 的空路径资源。发现整个 Workspace 仍使用 Search 的 `kind=workspace` 范围。

## continuation 的共同语义

continuation 是“在同一读取接口继续取得后续内容”的不透明令牌，与 LLM 续写、JEV 判断或主循环的展示保护标记无关。调用者使用所属接口返回的令牌，owner 校验目标、读取条件及适用生命周期；不能在不同接口间交换令牌，也不能根据其编码拼造位置。

当前已有以下使用者，语义相近而绑定方式各有职责：

| 读取场景 | 现有机制与绑定 |
| --- | --- |
| Trace / Session Inspect | DisclosurePage 复用 infra 的 OpaqueContinuationCodec，绑定目标和实际披露内容/查询 |
| Home / Memory Inspect | inspect_document 复用同一基础 codec，按正文或 direct refs 视图校验内容绑定 |
| Workspace 文本浏览及 SDK/Endpoint 目录浏览 | Workspace reader 与 PageOptions 复用基础 codec，按相应内容及读取参数续页 |
| Search | SearchViews 持有有界结果视图，以临时 token 定位下一页；续页不重新执行检索或模型评估，受 Turn/profile 或 SDK lease 生命周期及容量约束 |
| Job 输出 | JobOutputPosition 复用基础 codec，绑定 Job 与输出通道位置；读取可继续增长的输出，不采用固定文档快照的含义 |

因此统一的是续读的理解和用法，当前并非所有接口都采用同一种 token 编码或状态存储。Search 的 result_handle 定位整个保留集合，continuation 定位该集合的下一页，二者也不合并。新 Workspace Inspect 复用已有读取/分页设施，不建设全局令牌服务。

已确认不为容量折叠额外保留旧续页令牌：令牌可取得且仍有效时直接续页；否则沿保留的目标及范围重新读取当前内容，重新取得分页入口。折叠不等于令牌失效，但不保证旧令牌仍在模型可见上下文中；重新读取也不冒充恢复原分页链。

## 身份长度与叙事

格式中的 `<id>` 表示 owner 分配的稳定身份，不规定必须使用完整 UUID。缩短身份时必须修改正式身份的生成和消费者，不能只在显示层截断，也不能让模型使用不唯一的前缀。身份不随内容摘要、模型命名或展示次序变化。

已确认 request_id 与 Turn 身份分工：request_id 定位排队请求及其控制；正式 Turn 身份服务执行、Trace 和 Session 定位。正式 Turn 身份在活动日确定后分配，排队时不伪造已有 Turn 编号。模型侧正式引用保留日期，不支持省略日期的短格式或另一套显示 alias。

日期 + 日内序号是正式编码，例如 `turn:trace/2026-10-06/42#entry/17`、`session:turn/2026-10-06/42#action/2`。日期表示所属 CalendarDay，不是请求接收日或 Reflection 来源日。Turn 内条目利用已有作用域分配不可重编号的局部身份。Agent 日协调在实例的 `runtime/agent/turn-sequence.json` 保存日期和分配高水位，重启后继续分配，新日重新从 1 开始；Session 按日保存 `turns/<sequence>.json`。本文表格用 `<turn-id>` 表示正式身份整体。

时间由真实 received_at/started_at 等事实解释，可以显示在引用旁，不由序号推算。时间戳方案的比较保留在执行计划，不再与正式引用省略日期混为一个选择。标题/说明与精确引用仍一起显示和折叠。

不把标题塞进不可变身份来追求“每个字符都有自然语言含义”。示例：

```text
问答卡片调试：确认保留完整问题、选项与用户回答。
引用：session:turn/<turn-id>
```

文本提供语义，精确引用提供可操作的回忆入口。折叠后仍保持这一关系。
