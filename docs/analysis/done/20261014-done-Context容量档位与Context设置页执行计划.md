# Context 容量、配置命名与设置页执行计划

状态：`done`（实现、文档同步与验证已完成）

## 1. 目标与范围

依据重新阅读的 AGENTS.md，保持 Context 段组合、LLM 请求预算、插件事实 owner、检索和配置编辑各自的职责。本次统一容量字段的表达、默认值与设置入口，不引入统一预算管理器，不调整 Phase 协议、token 估算算法或 Context 回收算法。

本轮补全了前一版遗漏的 Execution/Subagent 收集、Web/MCP 内联结果、检索快照、模型/Action 输出覆盖、缓存、SDK 分页和 Endpoint 输入边界。把“是否影响模型语境”“在哪里编辑”“是否改默认值”分别判断：属于外围能力不代表与语境无关，出现在 Context 页也不表示所有权迁入 kernel/context。

已有确认：Data & Knowledge 增加 Context 页；context.* 与 Session 背景预算迁入该页；保留有独立语义的 12k/24k 档；容量默认值与显示采用 1024 基数。以下命名、补充范围和页面细节是本轮推荐方案。

## 2. 语义核对

| 项目 | 实际含义与达到边界后的行为 |
| --- | --- |
| Session Background | 已完成 User Turn 的地图和交互正文投影；按预算摘录/折叠，保留解释和读取入口，不截断持久 Session 事实。容量回收后本轮沿用缩减预算 |
| Active Memory | 当日活动 Memory.md 的内容字符上限；写入超限不提交。不是 Memory 整个 Background 的上限，后者还可能含 latest、target 和按需加载文档 |
| Memory daily/entity/concept/fact/note | 每个持久文档的序列化文本上限，包含文档头等；提交前校验。daily 比 active 大合理，两者的用途与计量范围不同 |
| Home/Workspace read | 单次资源读取默认值/模型侧 Inspect 页上限，具体接口还受 owner 的页策略约束；Inspect 提供 continuation，简单 read 可以返回有界摘录 |
| Home/Workspace write | owner 完整文本写入/改写的内容边界；超限失败，不静默截断。不是磁盘上所有文件的大小上限，Execution 写文件、资源导入/转换有自己的入口和边界 |
| Home Background | 选中的 top 内容按全文加载；home.max_read_chars 不截断它。Skill catalog 有独立元数据总量预算，读取/修改时由 Home 校验超限，不自动截掉一半目录；domain/action Skill 属于 TaskPrompt 局部挂载 |
| Trace chunk | 压缩时的分组目标，不是 Trace 总长度，也不是每条记录的硬上限。实现保持单条 Entry 完整，单个 Entry 可以超过目标 |
| Trace Inspect | 一次渐进披露页的预算，包含必要说明/引用开销；展示保护和 continuation 语义保持现有实现 |
| Retrieval input | select/rerank 的实际操作输入容量。LLM 路径包含选择提示、候选片段和可选 current Context；JEV 包含 state/questions；Embedding 路径计查询及内容单元。超限返回缩小范围的局部失败 |
| Retrieval snapshot/page | 快照保存候选事实，page 约束返回结果；快照不是常驻 Context。页内容经 ActionResult 进入 Trace |
| Embedding cache | 当前实现限制的是序列化缓存 JSON 的字符量（digest/vector 等），不是缓存了多少原文。写入时筛掉放不下的条目，缓存可重建 |
| LLM 生成额度 | max_output_tokens 是 token，不是字符；Task 默认、调用/Action binding、模型覆盖共同决定有效值，同一有效值用于实际请求和 Context 输出预留 |

Background、Trace、Working 是组合槽位，不存在三份固定总配额。Identity、Inputs、Journal、Plan、Workspace 清单、Jobs、Connections 没有各自可编辑的总字符上限；由内容 owner、现有回收能力和完整请求预检共同约束。本次不会为填满页面而新增这些上限。

## 3. 配置命名

### 3.1 规则

硬容量采用 `max_<对象或用途>_<单位>`，已经由配置层级表达对象时可用 `max_chars`。分块目标不用 max 冒充硬限制。保留现有配置层级，直接重命名叶字段，不另设 limits/budget 结构。

Session 的 background 与 Memory 的 active 不应改成相同词：前者指 Context 投影，后者指活动文档。`memory.max_active_chars` 保留；active 是现有概念，activate 表达动作，不适合作容量名称。

| 现有配置键 | 推荐配置键 |
| --- | --- |
| session.background_max_chars | session.max_background_chars |
| session.inspect_max_chars | session.max_inspect_chars |
| context.budget_max_image_bytes | context.max_image_bytes |
| context.trace_chunk_max_chars | context.trace_chunk_chars |
| context.trace_inspect_max_chars | context.max_trace_inspect_chars |
| home.skill_catalog_max_chars | home.max_skill_catalog_chars |
| home.search.resource_max_chars | home.search.max_resource_chars |
| home.search.embedding_cache_max_chars | home.search.max_embedding_cache_chars |
| memory.documents.daily/entity/concept/fact/note_max_chars | memory.documents.max_daily/entity/concept/fact/note_chars（五个独立键） |
| memory.inspect.page_max_chars | memory.inspect.max_page_chars |
| memory.search.embedding_cache_max_chars | memory.search.max_embedding_cache_chars |
| action.retrieval.<action>.select/rerank.input_max_chars | action.retrieval.<action>.select/rerank.max_input_chars |
| action.retrieval.<action>.snapshot_max_chars | action.retrieval.<action>.max_snapshot_chars |
| capabilities.expand.search_max_chars | capabilities.expand.max_search_chars |
| agent.output.model_max_chars | agent.output.max_model_detail_chars |

Memory 五个文档键准确展开为 `max_daily_chars`、`max_entity_chars`、`max_concept_chars`、`max_fact_chars`、`max_note_chars`。Retrieval 的 action ID 是原有 TOML 原子键，select/rerank 是两个独立操作表；不改变这些层级。

`context.max_image_bytes` 由说明明确表示构造式 MessageStack 的 inline 图片合计字节预算；无需保留 budget 前缀或新增子表。`context.trace_chunk_chars` 的标题改为“Trace 分块目标”。`agent.output.max_model_detail_chars` 明确是终端观察输出细节，与模型生成上限无关。

`workspace.analysis.max_chars_per_reference` 保留现有 per-reference 表达；`action.retrieval.<action>.page.max_chars` 已符合规则，保持名称。Action 请求中的 max_chars、provider 原生字段、结果单位字段不随配置改名。非容量计数如 trace_branch_factor、redirect_max_hops 不在本次命名清理范围内。

### 3.2 迁移

同步配置 dataclass、parser、消费者、catalog、standard/development 资产、preset、前端路径/翻译、测试和当前设计文档。Python 中直接承载同一配置的成员/参数一起改名；不批量改写所有临时变量或 wire protocol。

开发阶段不保留旧键别名。仓库拥有的配置/示例完整更新；历史分析归档和真实 trace 保留原样。用户已有显式配置不会因为更新默认值自动改变；实施交付说明旧键到新键映射，已有测试实例可以重新生成，不建设自动迁移框架。

## 4. 单位和数值

`k = 1024`，`M = 1024 × 1024`。字符显示如 `12k chars`，生成额度显示 `32k tokens`，字节显示 `5 MiB`；精确整数始终可见/可输入。chars/token 不能标成 KiB。后端字符计量按现有 owner 的 Python 文本/序列化长度定义，前端运行占用直接使用后端结果。

默认值及快捷档位统一，允许用户继续输入任意合法整数，不加“必须为 1024 倍数”的校验，不把用户自定义值自动四舍五入。不按统一显示规则抬高供应商真实窗口；不能整除的值展示原值或带近似符号及精确值。

### 4.1 Context 与知识 owner

下表使用改名后的键；数值单位除特别标明外均为字符。

| 配置 | 当前 → 建议 | 用途 / 编辑页 |
| --- | --- | --- |
| context.trace_chunk_chars | 12000 → 12288（12k） | Trace 分块目标 / Context |
| context.max_trace_inspect_chars | 8000 → 8192（8k） | Trace 披露页 / Context |
| context.max_image_bytes | 10485760 → 不变（10 MiB） | Context inline 图片合计 / Context |
| context.compression_trigger_ratio | 0.8 → 不变 | 请求预检触发比例 / Context |
| context.compression_target_ratio | 0.5 → 不变 | 回收目标比例 / Context |
| context.trace_branch_factor | 4 → 不变 | 层级合并数量 / Context |
| context.trace_min_hot_entries | 2 → 不变 | 最近直接展示条目最少数量 / Context |
| session.max_background_chars | 24000 → 24576（24k） | Session 地图+正文背景投影 / Context |
| session.max_inspect_chars | 8000 → 8192（8k） | Session 披露页 / Session |
| home.max_skill_catalog_chars | 8000 → 8192（8k） | Skill 目录投影 / Context |
| home.max_read_chars、workspace.max_read_chars | 各 4000 → 8192（8k） | 读取/Inspect / 各自 owner 页 |
| home.max_write_chars、workspace.max_write_chars | 各 65536 → 32768（32k） | 完整文本写入/改写 / 各自 owner 页 |
| memory.max_active_chars | 12000 → 12288（12k） | 活动 Memory 正文 / Memory |
| memory.documents.max_daily_chars | 32000 → 32768（32k） | Daily 完整文档 / Memory |
| memory.documents.max_entity_chars、max_concept_chars | 各 16000 → 16384（16k） | 两类完整文档 / Memory |
| memory.documents.max_fact_chars | 4000 → 4096（4k） | Fact 完整文档 / Memory |
| memory.documents.max_note_chars | 24000 → 24576（24k） | Note 完整文档 / Memory |
| memory.inspect.max_page_chars | 8000 → 8192（8k） | Memory 披露页 / Memory |
| home.search.max_resource_chars | 128000 → 131072（128k） | 单个搜索来源 / Home |
| home.search.max_embedding_cache_chars、memory.search.max_embedding_cache_chars | 各 16000000 → 16777216（16M） | 缓存 JSON 文本 / 各自 owner 页 |
| workspace.search.max_query_chars | 256 → 不变 | 查询长度 / Workspace |
| workspace.search.max_scan_chars | 1000000 → 1048576（1M） | 搜索扫描 / Workspace |
| workspace.analysis.max_intent_chars | 2000 → 2048（2k） | 分析指令 / Workspace |
| workspace.analysis.max_source_chars | 24000 → 24576（24k） | 分析来源总量 / Workspace |
| workspace.analysis.max_chars_per_reference | 12000 → 12288（12k） | 每个分析 reference / Workspace |
| workspace.analysis.max_answer_chars | 4000 → 4096（4k） | 分析回答 / Workspace |
| workspace.max_image_bytes | 5242880 → 不变（5 MiB） | 单张工作区图片 / Workspace |

`context.system_text` 和 `context.journal` 虽非数值项，也属于本次 context.* 入口迁移，从 System 页移到 Context 高级配置；不新增它们的字符截断规则。

12k/24k 建议保留。活动记忆要便于频繁读取，持久 daily 可以保存更充分的整理结果；Session 24k 是历史摘要投影，可以按需查原文；Trace 12k 是折叠粒度。现在没有证据要求把三者都扩大到 32k。上述数值是合理默认值，不宣称经过性能实验求得最优值。

Workspace 分析保留 12k 单引用、24k 总来源、4k 回答：它是有界局部分析，完整文档生成由 compose 等动作承担。读取页统一 8k，与完整文档 32k 保持分工，不把所有文档一次塞入模型。

### 4.2 模型与检索

| 配置 / 范围 | 当前 → 建议 | 说明 |
| --- | --- | --- |
| llm.tasks.frame_stage1/frame_stage2/llm_action.max_output_tokens | 各 65536 → 建议 32768（32k tokens，已确认） | 承接此前“32k”的讨论；三类任务没有字符生成预算，不新增 32k 字符截断 |
| llm.tasks 新建模板 | 65536 → 跟随上述确认值 | 模板与默认资产一致 |
| llm.models.*.context_window_tokens | 保留各模型现值 | 当前资产有 262144、1000000、1048576 等；是模型配置事实，不为二进制风格更改服务能力 |
| llm.models.*.request_overrides.max_output_tokens | 无通用默认，保持显式值 | 模型级覆盖，Context 页只读提示并跳转 Models |
| action.models.bindings 的 options.max_output_tokens | 无通用默认，保持显式值 | Action model-use 覆盖，跳转 Actions & Model Uses |
| action.retrieval.<action>.select/rerank.max_input_chars | 64000 → 65536（64k chars） | 操作输入，不是主循环 Context 总容量 |
| action.retrieval.<action>.max_snapshot_chars | 隐式默认 4000000 → 4194304（4M chars） | 在资产中显式写出，便于定位有效默认值 |
| action.retrieval.<action>.page.max_chars | 8000 → 8192（8k chars） | 返回页 |
| action.retrieval.<action>.max_steps、page.max_items | 8、50 → 不变 | 数量限制，保持独立 |

Task 最大输出和文件最大字符不绑定。用户已确认三类 Task 默认 32768 tokens，Home/Workspace 完整文本写入上限 32768 chars。

完整请求仍由 LLM 的既有预检估算：输入（含工具定义和 TaskPrompt）+ 本次有效生成预留，与模型 window × trigger_ratio 比较；本次没有新建 token/chars 换算系数或自适应预算。页面说明这种关系即可，不用段字符数推算 provider 剩余 token。当前保守 UTF-8 输入估算与图片估算的局限已知，保留为独立议题。

### 4.3 补充发现的能力配置

这些是实际可配置项，建议同时统一数值默认值；主编辑入口仍在 Tools & Connections 的对应页面。Context 页的“行动结果与局部任务”折叠组展示直接影响模型输入的 collect/inline/brief/search 值，落盘和传输大上限在 owner 页展示。

| 配置（相同前缀下的字段成组列出） | 当前 → 建议 | 语义 |
| --- | --- | --- |
| execution.max_collect_chars | 4000 → 4096（4k） | collect 对 stdout、stderr 各自限制；并非整个 ActionResult 只有 4k |
| execution.max_source_chars | 100000 → 102400（100k） | 执行脚本来源 |
| execution.max_command_chars | 20000 → 20480（20k） | command 输入 |
| execution.max_arg_chars | 4000 → 4096（4k） | 单个参数 |
| execution.max_output_bytes | 2097152 → 不变（2 MiB） | 进程 stdout/stderr 合计上限；和收集窗口分开 |
| capabilities.subagent.max_collect_chars | 12000 → 12288（12k） | ACP 输出收集；保留报告型文本的独立粒度 |
| capabilities.subagent.max_brief_chars | 24000 → 24576（24k） | 委派任务及引用组装的 brief |
| capabilities.subagent.max_output_chars | 1000000 → 1048576（1M） | 收集到的输出总量 |
| capabilities.expand.max_inline_chars | 16000 → 16384（16k） | MCP 内联结果/工具说明 |
| capabilities.expand.max_search_chars | 60000 → 61440（60k） | 查询与本次工具候选定义总量，不是 query 单条长度 |
| capabilities.expand.max_catalog_bytes | 4000000 → 4194304（4 MiB） | MCP 工具目录 |
| capabilities.expand.max_result_bytes | 8000000 → 8388608（8 MiB） | MCP 完整结果 |
| capabilities.web.max_output_chars | 1000000 → 1048576（1M） | 抽取/落盘正文上限 |
| capabilities.web.max_excerpt_chars | 600 → 保留 | 短预览长度，有独立阅读用途，不抬高成 1k |
| capabilities.web.search_by_kimi.max_query_chars | 4000 → 4096（4k） | 查询文本 |
| capabilities.web.search_by_kimi.max_result_chars、discover_pages.max_result_chars | 各 100000 → 102400（100k） | 完整结果 |
| capabilities.web.search_by_kimi.max_inline_chars、discover_pages.max_inline_chars | 各 12000 → 12288（12k） | 内联结果，超出走精简说明及落盘引用 |
| capabilities.web.search_by_kimi.max_search_tokens | 100000 → 保留精确原值 | 供应商搜索额度；不以本地显示习惯修改供应商参数 |
| capabilities.web.search_by_kimi.max_output_tokens | 8192 → 保留（8k tokens） | Web 专用生成额度 |
| capabilities.web.max_source_bytes | 5242880 → 不变（5 MiB） | 下载来源上限 |
| capabilities.resource.max_output_chars | 1000000 → 1048576（1M） | 文档转换正文 |
| capabilities.resource.max_source_bytes、max_total_asset_bytes | 20 MiB、50 MiB → 不变 | 文档来源和附属资源 |
| agent.output.max_model_detail_chars | 20000 → 20480（20k） | Console 模型细节显示，不影响实际 request/response、trace 原始证据或模型 Context |

20k/60k/100k 也是准确的 1024 倍数；保留近似现状比为了只剩少数档位而把 command/候选/结果显著放大更合理。常见页面采用 4/8/12/16/24/32/64/128k 快捷档位，owner 可以使用其他整数倍。

超限后的失败/预览/分页行为保持原 owner 实现。不把所有上限改成“截断”，也不加入跨 owner 的新失败分类。

### 4.4 已盘点但不新增设置的固定边界

| 位置 | 当前值 / 行为 | 本次处理 |
| --- | --- | --- |
| Retrieval SearchViews | 16 个 view、合计 16000000 chars；淘汰最旧视图 | 合计默认改为 16 × 1024²，仍是内部服务容量，不新增全局 settings 项 |
| Retrieval 候选投影/结果摘录 | selection 单候选 4000 chars；结果摘录 2000 chars；披露默认页 8000 | 对应默认分别统一 4096/2048/8192；保留实际覆盖说明，不扩为第二组用户旋钮 |
| 共用 VectorCache 默认 | 16000000 chars | 与 Home/Memory 传入的缓存默认同步 16 × 1024² |
| Context builder / Trace / owner 内部回退默认 | 12000、8000 等同一业务默认的副本 | 跟随所属 owner 改值；优先复用现有配置常量，避免资产改了而 Builder 仍使用旧值 |
| SDK PageOptions、Endpoint 页默认 | 默认 16000；允许 1024..64000 chars | 默认 16384、范围上界 65536；同步路由默认、schema/示例和前端显式请求值；它是观察/资源服务分页，不等同于 Action Inspect 8k |
| Endpoint 初始 text/instructions、回复 text/comment、Reflection instructions | 这些字段的 max_length=16000；追加输入 text 没有相同字段上限 | 已有 16000 上限同步到 16384；Inputs 说明注明适用入口，不给追加输入补设新上限，不新增全局配置 |
| EventBus / TurnInbox envelope | 默认 64000 bytes；Terminal 记录另有 8192 bytes | 保留，属于运行 envelope 协议，Context 页不展示为语境容量 |
| core.ask、session.organize 的 schema 字段长度 | question/details 16000、选项说明 2000；语义注释正文 4000 等 | 本次保留并注明属 Action 字段约束；不为命名/容量页面扩展成 catalog 协议重构 |
| 短摘要、引用、标签、失败反馈 | 数十至数千字符的局部常量 | 保留语义长度，不做无差别数字替换 |
| Endpoint 传输/资源上限 | request/resource bytes 等已有 2/8 MiB 级上限 | 保留进程配置；与段使用量分开 |
| 时间、重试、并发、文件/页/引用数量 | 各 owner 当前值 | 本次不按 1024 改造 |

固定边界仅同步已有默认，不新建设置服务。为 SDK/HTTP 分页提供的默认值在已有 infra/paging owner 统一供消费者使用；受影响 Endpoint 文档同步。仍保留的十进制值有明确的协议、预览或数量语义，不能把“容量显示统一”理解成仓库所有数字必须二进制。

## 5. Context 页的编辑归属与布局

### 5.1 唯一编辑入口

| 配置 | 主编辑入口 | 其他页面 |
| --- | --- | --- |
| context.* | Data & Knowledge → Context | Budgets/System 移除相应编辑控件 |
| session.max_background_chars | Context | Session 只读摘要 + 跳转 |
| home.max_skill_catalog_chars | Context | Home 只读摘要 + 跳转 |
| Session Inspect、Home/Workspace read/write、Memory 文档与 Inspect | 保留原 owner 页 | Context 只读相关值 + 跳转 |
| 模型窗口、Task 输出、Action model-use 覆盖 | 保留 Models/Task Chains/Actions | Context 只读关联信息 + 跳转 |
| Retrieval policy | 保留 Search Policies | Context 展示 select/rerank/page 摘要 + 跳转 |
| Execution/Web/ACP/MCP 结果边界 | 保留各能力页 | Context 按需要折叠呈现 |
| Cycle 预算 | Behavior → Budgets | 保留 User/Home/Memory Reflection 的 cycle 配置 |

Session Inspect 留在 Session，与 Memory/Home/Workspace 的 Inspect 保持一致；它不是 Background 常驻投影。Home Skill catalog 则只服务 Context 投影，适合一起迁入 Context。UI 页面归属不改变后端配置 owner。

已核实前端允许控件复用，但现有搜索/draft/reset 的归属逻辑不完全一致。`pageForPath` 按最长合法路径前缀判断；现有 `context.budget_` 等字符串不是该函数认可的字段子树，且 `pageDraftKeys` 会同时匹配父页和特定子页。迁移时使用完整 `context` 前缀和明确的 Session/Home 字段路径，让 reset 复用唯一的 `pageForDraft` 归属，避免 Session/Home“重置本页”撤销 Context 草稿。这是页面迁移必须同步的行为修正。

### 5.2 页面预览

```text
Data & Knowledge / Context                 当前 Turn · 采集时间 · 刷新

[ Background                              ][ Trace      ][ Working            ]
 Identity → Session → Inputs → Journal?     TurnTrace      Plan → Workspace
 → Home → Memory                                          → Jobs → Connections

  语境段合计：约 … chars       inline 图片：… MiB
  条形色块表示当前段字符构成；图片单列；没有活动 Turn 时显示结构示意

[选中的段：Session]
 当前投影 … chars     背景上限 24k chars [编辑]
 Inspect 页 8k chars [前往 Session]        [查看当前段]

[Context 压力]
 触发 80%   回收目标 50%   图片总量 10 MiB
 Task 生成额度 … tokens [前往 Task Chains]
 模型窗口 / 模型覆盖 [前往 Models]

[相关读取与文档边界]  Workspace · Home · Memory · Retrieval
[行动结果与局部任务 ▸] Execution · Web · ACP · MCP
[高级配置 ▸] System identity · Journal · Trace 分块/合并/热条目
```

宽屏顶部用连续分区和轻量色块，选中段后高亮对应设置卡；窄屏允许横向滚动/换行，不把所有字段塞入横条。主视图强调名称、用途、字符数和主要配置；owner/shape/order、已加载/可用/保护数量进入展开详情。已有字段组件、draft store 和深浅主题样式复用。

实际槽内顺序由 endpoint descriptors 决定。普通 User Turn 的典型顺序为 identity(10)、session(20)、inputs(30)、journal(39，可选)、home(40)、memory(50)；Trace；plan(10)、workspace(20)、jobs(30)、connections(40)。Reflection 可以有其他段，页面不硬编码成所有 Turn 都有相同内容。TaskPrompt 在 MessageStack 后局部追加，在图边缘提示这一关系，不能伪装成永久 Segment。

### 5.3 当前占用

复用 `GET /v2/requests/{request_id}/context`、现有 ContextOverview/segment client 与 Context drawer。已有字段足以提供 slot/order/chars/image_bytes/加载情况，不新建 usage endpoint 或后端统计状态。

- 进入页面按当前运行请求读取一次，后续复用已有 stale 提示与手动刷新，不新增持续轮询器。
- 使用 backend `chars`，汇总时明确是“已安装语境段的字符估算”；不包含每次 TaskPrompt、工具定义和 provider 包装，不表示完整模型 request tokens。
- 段大小可按字符总和画构成比例；只有确有同语义额度才展示上限。不能把 Trace 当前长度除以 chunk 目标，或 Memory 全段除以 active 文档上限。
- 图片字节单列；10 MiB 图片预算不保证 provider 图片 token 能装下。
- 配置值区分草稿/已保存/当前生效。Live 占用使用运行中的 active 配置，不把尚未应用的草稿和旧运行占用拼成“即时效果”。
- 无活动 Turn 时展示结构说明与配置，不伪造零占用；已读 Turn 结束后保留采集视图并标记已关闭，切换到新 Turn 时重新绑定，沿用已有 Context drawer 生命周期。
- 缓存/下载/大结果存储不计入语境构成条；Context 相关卡片可通过已有 catalog/config 快照取得值，不另存默认配置副本。

## 6. 实施步骤与边界

1. **配置契约与文案**：按第 3 节改名，校验错误 key、catalog 说明与真实计量范围同步；避免继续把 Trace 目标/缓存 JSON 写成硬上限/原文容量。沿消费者同步 prompts 的动态值，保留现有短失败类型与处理流程。
2. **默认值**：按第 4 节同步 Python 默认、Builder、standard/development 资产、SDK 页默认和必要 Endpoint schema；不更改旧 traces/归档文档，不把测试中代表小预算的任意数字批量改掉。三类 Task 采用已确认的 32768 tokens。
3. **配置编辑**：更新 config catalog、preset whitelist/快照路径及前端读取方；移动页面不改变 preset 的业务范围，不把 Context 页所有相关字段自动加入 preset。
4. **前端页面**：注册 Context、迁移主编辑入口、修正统一归属/reset；复用 Context overview 展示运行组成，接入单位格式/只读跳转和中英文本。
5. **文档**：实现时同步 docs/design/context.md、session.md、memory.md、agent_home.md、workspace.md、llm.md、action-model-retrieval.md 及相关 capability/config 设计；按 Endpoint 改动同步 docs/endpoint，前端设计记录在 visualization 对应文档。
6. **核对**：检查下面的验收项，完成必要验证后记录证据，再改成 done 并移入 docs/analysis/done。

不建立全项目公共容量常量表把所有 owner 绑到同一值。各 owner 保留语义默认，基础 paging 等确有公共消费者的默认留在 infra；前端容量格式化复用一个简单公共函数。

## 7. 验收

- 配置解析、dataclass 默认、资产、catalog、preset、调用方一致；旧键明确未知，不保留兼容别名。
- 正常读取和 continuation、文档超限不提交、完整文档生成与 token 预算独立；保持 owner 原有成功/失败边界。
- Trace chunk 明确是目标，Session 背景和 Memory 文档说明正确；不改变展示保护、折叠和回收算法。
- Retrieval 所有已登记 policy 的输入/快照/页默认一致；MCP 搜索容量与 Retrieval 操作输入仍由各 owner 分别校验。
- Execution 每流 collect 与 ACP/Web/MCP 页/inline 不伪装为统一 ActionResult 硬上限。
- 请求有效 max_output_tokens 与输出预留仍一致；模型/Action 覆盖保持现有优先级。
- Context 页的搜索、焦点、草稿计数和 reset 只归一个页面；从其他页只读跳转后定位到正确字段。
- 运行占用顺序取自后端、单位准确；支持无活动 Turn、关闭快照和配置尚未生效状态，不显示伪 token 额度。
- SDK/Endpoint 页默认及输入 schema 调整同步文档/前端；观察页 16k 与模型 Inspect 页 8k 保持各自用途。
- 用最小代表性测试覆盖配置 owner 契约、跨层传播和页归属/回收行为；实现阶段运行聚焦测试、Full、typecheck、前端测试/构建及页面视觉核对。仅修改本计划不运行业务测试。

## 8. 可行性与确认

方案合理可行。Context 观测已有接口，容量策略仍由现有 owner 执行；主要成本是改名跨越 Python、TOML、catalog、preset、前端路径，以及页面布局与归属修正。它是涉及多个模块的配置/界面改进，不是几处数字替换，也不需要重新设计 Agent 内核。

本次重新核对修正了旧稿的遗漏与不准确处：外围 collect/inline 与语境有关；Trace chunk 是目标；缓存限制的是 JSON；page.max_chars 已经是正确配置键；字符/token 不能写成 KiB；System 的 context 字段也要迁移；Session Inspect 保持原 owner 页；页面 reset 需要遵守唯一归属。

全部方案已获确认；Task 默认输出为 32768 tokens，文件完整写入为 32768 chars。按此实施并核对。

## 9. 实施核对（2026-10-14）

已按本计划完成并核对：

- 配置字段已按 owner 语义改名，旧键不保留兼容别名；Python parser/dataclass、消费者、catalog、preset、standard/development 资产和当前文档保持一致。
- 三类主循环 Task 与模板默认 `max_output_tokens = 32768`；Home/Workspace 完整文本写入默认 `32768` 字符；读取、Session、Memory、Retrieval、Execution、Web、ACP、MCP、缓存和分页边界按计划采用 1024 基数档位。Provider 窗口、事件 envelope、短反馈和数量限制仍保留原语义。
- Context 配置编辑入口已注册在 Data & Knowledge → Context。页面以 Background → Trace → Working 横条说明装配顺序，显示当前活动 Turn 的只读字符/图片占用，并提供 owner 导航；Session/Home 保留只读跳转，Budgets/System 移除重复编辑控件，草稿 reset 使用唯一页面归属。
- Context catalog 已修正 Trace 分块是目标、Embedding cache 是序列化 JSON、Session background 是投影预算等说明；Endpoint 分页和 Reflection 输入文档同步到 16384/65536 的新默认范围。
- 验证通过：受影响 Python 测试、完整本地 Python 门禁 `scripts/test.ps1 -Suite Full`（1276 passed, 25 deselected）、配置 generation/release 测试、`scripts/typecheck.ps1`、前端 Vitest（91 文件/805 测试）和 Vite production build；`git diff --check` 无错误。

本计划依据 AGENTS.md 的 owner、配置单一事实、前后端边界和文档归档规约完成归档。

## 10. 提交后复核补充（2026-10-14）

提交后的交叉核对发现少量同步遗漏，已在当前实现中补齐：

- `visualization/docs/design/config-coverage.md` 中任务链默认输出、Agent 模型细节、Web/Resource/ACP/Workspace/缓存容量的旧约数已与资产和 owner 默认同步；Resource 设计示例也改为 `1048576`。
- DeepSeek standard/development 模型窗口由约数 `1000000` 统一为精确的 `1048576`；前端任务链及模型覆盖控件的默认填充值同步为 `32768`，避免 UI 在缺少显式值时回退到旧的 `2048`。
- Context 设置页复用 Context drawer 的 stale/closed 语义，保留已读 Turn 的占用快照；占用卡按后端 segment 的 slot/order 汇总 Background、Trace、Working 字符和图片字节，仍明确不把它伪装成 provider token 统计。
- 前端 token 紧凑显示改用 1024 基数，与配置值及 Context 容量显示一致；其它非模型窗口的 `1000000` 测试/时间换算值不作无关替换。

复核验证：LLM 配置测试 17 项通过，前端完整 Vitest 91 文件/805 测试通过，Vite `tsc` 与 production build 通过，generation/release 测试通过，`git diff --check` 无错误。当前模型窗口只保留 `262144`（256 Ki）和 `1048576`（1 Mi）两档实际资产值。

