# 引用格式与渐进读取

本文按维护者要求记录**目标格式**。公共语法、Home 显式类别和 Trace 共用根格式已确认，但代码、默认资源与前后端尚未完成迁移，不能将本文示例当作当前版本已支持的接口。实施与验证以[引用统一计划](<../analysis/20261006 引用体系梳理与统一执行计划.md>)和[上下文叙事计划](<../analysis/20261006 模型上下文叙事投影与引用语义统一执行计划.md>)为准；完成迁移后同步更新本文的落地状态。

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

完整 Workspace 搜索范围是范围选择器，不是空资源引用；目标设计以 `kind=workspace` 表达全范围，仅文件/目录范围携带精确 ref。普通模型不通过旧日 Workspace 字符串取得跨日读取能力。

读取方向是 `workspace.inspect`：无内部模型调用，按引用返回真实、有界的资源内容及覆盖说明。该 Action 尚在设计中，文本/目录、分页和 Action 结果保留契约见引用统一计划；现有 `workspace.read` 的后续去留不由本文提前决定。Working 仍只显示资源说明和引用，Inspect 正文通过实际 ActionResult 进入 Trace。

该读取结果采用有界折叠：实际返回的正文页先进入一次取得响应的决策模型请求，随后才可按容量移除正文展示层，保留资源说明、精确引用、请求/实际范围与执行状态。解除保护不立即触发折叠，也不表示模型已经理解或完成使用。Session 在 completion 时直接保存这一读取事实，与活动 Trace 是否曾折叠无关。回忆 Action 能理解当时读了什么；需要内容时再次 Inspect 当前资源。行范围或标题可能随文件更新而改变，不承诺恢复旧页，也不建立资源版本库。

按 ref 选段、可选 continuation 和单页预算继续成立。“完整结果”指本次实际返回的有界页面，不要求整份文档或整个请求范围一次进入模型。选段决定读哪里，页面预算决定这次返回多少，展示保护决定这次返回页何时可以移出直接可见语境。每次续页是新的读取结果，分别遵守展示保护。续页令牌的折叠后可获得性与保留边界见引用统一计划第 4.9 节，不把令牌当作持久回忆引用。

## 活动 TurnTrace

| 目标格式 | 语义 |
| --- | --- |
| `turn:trace/<turn-id>` | 活动 Turn 的 Trace 根 |
| `turn:trace/<turn-id>#input/<input-id>` | 已接受且达到相应可见边界的输入位置 |
| `turn:trace/<turn-id>#action/0` | 按原始请求顺序确定的 Action occurrence |
| `turn:trace/<turn-id>#entry/<entry-id>` | Trace 中的具体条目 |
| `turn:trace/<turn-id>#node/<node-id>` | Trace 压缩层级中的节点 |

所有内部位置共用同一个根。`action/0` 为 0 起始事实索引；不能在抽取部分 Action、排序、失败或压缩后重新编号。其余身份的具体短编码仍在分析，本文不把 UUID 长度固定为公共语法。

压缩只改变可见投影，已发出的入口仍能定位所保留的事实。引用不会因为压缩节点移动而改指别处。活动 Trace 不提供裸 `turn:trace` 别名，也不让新 Turn 读取旧活动 Trace；User Turn 完成后通过 Session 的持久事实位置回忆。

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
| `session:node/<id>`、`session:edge/<id>` | Organize 持有的解释节点与关系 |

片段的简写示例继承同一 Turn 根。资源出现位置的 ref 与被引用资源的 target_ref 保持区别。thread/note 的名称和解释可修订，稳定节点身份不随标题重命名。

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

## 身份长度与叙事

格式中的 `<id>` 表示 owner 分配的稳定身份，不规定必须使用完整 UUID。缩短身份时必须修改正式身份的生成和消费者，不能只在显示层截断，也不能让模型使用不唯一的前缀。身份不随内容摘要、模型命名或展示次序变化。

已确认 request_id 与 Turn 身份分工：request_id 定位排队请求及其控制；正式 Turn 身份服务执行、Trace 和 Session 定位。正式 Turn 身份在活动日确定后分配，排队时不伪造已有 Turn 编号。模型侧正式引用保留日期，不支持省略日期的短格式或另一套显示 alias。

日期 + 日内序号是当前目标方向，例如 `turn:trace/2026-10-06/42#entry/17`、`session:turn/2026-10-06/42#action/2`。日期表示所属 CalendarDay，不是请求接收日或 Reflection 来源日。Turn 内条目利用已有作用域分配不可重编号的局部身份。分配 owner、跨午夜排队、重启高水位及 request/Turn 消费者的具体修改记录在引用统一计划第 4.8 节；本文表格用 `<turn-id>` 表示正式身份整体，不宣告新编码已经实现。

时间由真实 received_at/started_at 等事实解释，可以显示在引用旁，不由序号推算。时间戳方案的比较保留在执行计划，不再与正式引用省略日期混为一个选择。标题/说明与精确引用仍一起显示和折叠。

不把标题塞进不可变身份来追求“每个字符都有自然语言含义”。示例：

```text
问答卡片调试：确认保留完整问题、选项与用户回答。
引用：session:turn/<turn-id>
```

文本提供语义，精确引用提供可操作的回忆入口。折叠后仍保持这一关系。
