# Context 叙事与 Inspect 披露收尾及问答卡片修正执行计划

日期：2026-10-07

状态：`pending`（成因调查与方案预览已完成，业务代码尚未实施；待维护者审阅第 8 节的选择）

基线：`d56aff3 refactor(context): improve narrative context and unify references`。

本计划承接[上下文叙事执行计划](<done/20261006-done- 模型上下文叙事投影与引用语义统一执行计划.md>)和[引用统一执行计划](<done/20261006-done- 引用体系梳理与统一执行计划.md>)交付后的复核及实际使用反馈。前两份计划完成了主体迁移，本计划单独记录尚未闭合的语义、分页、消费者和问答问题，不把前次通过门禁等同于这些问题已经解决。

设计依据为 [AGENTS.md](../../AGENTS.md)、[Context](../design/context.md)、[Session](../design/session.md)、[引用格式与渐进读取](../design/references.md)及现有 Action/owner/Runtime 边界。

## 1. 目标、边界与当前结论

继续使用唯一的输入、问题、Action 和 Session 事实，通过正向投影使直接 Context、按引用读取的页面和折叠后的线索可以相互解释。模型应直接读到发生了什么、回答了哪个问题、读取了哪里，以及下一步可以读取哪个引用。

保留已经确认的路线 A、U0、日期/日内序号和 request/Turn 分工。ask 仍使用自己的唯一 ActionResult Entry；input/append/reply 仍是独立输入 Entry。Inspect 属于各 owner，不引入统一工具网关，不扩大跨日 Session/Workspace 访问，不引入摘要模型、正文版本库、平行日志或额外续页令牌保存服务。

本轮拟实施 P1、P2、P3、P4、P6 和清理项。P5 的完整流式读取优化建议明确暂缓；这是现有性能限制，不记为已修复。当前阶段只建立计划，不修改业务代码、默认资源或测试实例。

## 2. 已确认的问题与成因

| 编号 | 事实与成因 | 对使用的影响 |
| --- | --- | --- |
| P1：回复回忆不一致 | `kernel/context/engine.py::_current_search_facts()` 只投影输入原文与内部 reply_to；`builtin/trace.py::append_input()` 已用 typed question/answer 补全叙事。Session `views/navigation.py::project_occurrence()` 的 input 分支也只返回原文。 | 同一回复从 Entry、input occurrence、Session 整轮或历史 input 读取时，问题语境不同；模型需要额外推断关联。 |
| P2：Inspect 仍暴露传输结构 | Trace/Session 的 DisclosurePage 与 Home/Memory 的 inspect_document 直接调用 `continue_json_sequence()`；单项超预算后截断的是整个 JSON 对象的序列化文本。Action 又把这一页面作为通用 JSON ToolResult。 | 模型读到 canonical_json 的半截字符串、转义换行和协议字段；普通交互的阅读重新变成结构重组。 |
| P3：折叠缺少解释与覆盖 | `inspect_recollection()` 猜测 metadata.title/display，缺失时把 ref 当 title；只抽取完整 items 中的 ref，丢弃 title/clue。fragment 页没有完整 item，折叠后只剩 partial_item。 | 读取一个问题回复后可能只记得“读过 #entry/3”；目录保留裸子引用；无法说清某次部分读取实际覆盖了什么。 |
| P4：失败回答消失 | `session/views/interaction.py::project_interactions()` 无条件跳过所有 core.answer，原意是避免成功回答与 output 重复。 | 失败/超时等尝试在持久事实中存在，但线性叙事缺失，后续修正行动失去原因。此项是既有逻辑遗留，并非此次提交新引入。 |
| P5：页预算没有限制读取内存 | `workspace/inspection/reader.py::inspect_text()` 每页先 read_text 全文，再 splitlines、选段、编码及哈希，最后切出返回页。 | 单页输出有界，读取耗时和峰值内存仍随文件/选段增长；续页重复扫描。常规小文件读取语义正常。 |
| P6：问答卡片没有选项 | 实际 core.ask 把问题协议写入普通 json fence，且包含额外 kind=question；后端只识别 tinysoul-question fence，因而把全文作为普通问题并返回 options=[]。 | 正式问题可以等待和接收自由文本，但无法呈现预期的选择卡片；普通 JSON 代码块也不会被前端注册器识别成特殊卡片。 |

P1/P2/P3 是同一事实的不同读取和展示路径没有共同完成语义投影，不能通过删除机器事实或统一替换所有 JSON 来处理。业务产物本身是 JSON、代码或表格时仍可以直接呈现这些内容；应消除的是框架让模型重组传输封装的要求。

### 2.1 实际卡片证据

只读检查了 `B:\WorkSpace\my-agent-dev\runtime\session\turns\2.json`（2026-10-07 的第 2 个 User Turn）及该实例的 core.ask Catalog；没有修改实例。

实际 request.text 的末尾是以下形状，外层没有传 options：

````text
```json
{"kind":"question","question":"……","options":[{"id":"memory","label":"记忆机制"}, …],"allow_other":true}
```
````

实际 ActionResult：`outcome=success`、`options=[]`、`allow_other=true`，text 保留整个原始 Markdown。该例中的省略号只用于本文说明，原记录 JSON 完整。

仓库与实例的 ask schema 一致。对 `272f1f7 → d56aff3` 的检查表明，ask 的 schema 和 `_question_content()` 没有在上一轮改动，新增的是 `model_text=question.narrative(...)`。model_text 不用于 TurnQuestion 或前端 QuestionCard 的事实构造。因此证据支持“模型输出格式不符合既有卡片协议且未得到针对性反馈”，不支持“上一轮把正确的卡片数据改成了 JSON”。

用当前生产解析器验证：普通 json fence 加 kind 字段会成为无选项问题；正确 tinysoul-question fence 会得到真实选项；仅修改 fence 名称但保留 kind 会触发未知字段错误。修正必须同时处理两处格式错误。

进一步发现：正确 fence 外的说明被保存为 ActionResult.explanation，Trace/Session 有该字段；`QuestionRequest` 经 QuestionContent 取得的问题内容及 snapshot 不携带它，前端 QuestionContent/QuestionCard 也不消费 explanation。需要在卡片闭环中一起补齐，避免修好选项后丢失问题说明。

## 3. P1、P4 与清理项：沿已有事实修正投影

### 3.1 当前及历史 reply 使用相同的语义补全

- 复用 `QuestionContent.reply_narrative()` 和现有问题结果，不反解析输入文本，不另存一份问答记录。
- 当前 Turn 按 reply_to 在已结算 core.ask 事实中找 typed question；Trace INPUT、`#input/N`、当前证据及 Search 候选使用一致的问题、选项含义、说明和 comment。各 owner 可在一次投影内建立小型问题索引，不建设长期查询注册表。
- Session 按原 result_id 关联 record.actions 与 record.inputs，整轮、`#input/N`、查询和当前证据的输入投影复用同一解释。保留原始 text、typed answer 与机器关联字段；模型叙事不要求理解内部 result_id。
- 初始输入与 append 使用明确角色。排队/未受理文本不成为事实；不改变 INPUT_INSTALLED/INPUT_VISIBLE 的既有边界，不把安装等同于模型已读。
- 引用、occurrence 和 timeline 顺序保持不变；不增加通用 related/source 关系类型。

### 3.2 Session 只去重确实已被 output 表达的成功回答

- 存在正式 output 时，去重沿成功 core.answer → 正式 output 的既有 completion 契约进行，不比较文案相等性猜测关联。
- core.answer 的 failed/timeout/cancelled/not_executed/unknown 继续作为 Action interaction 展示，位置与普通 Action 相同；只有已有结果时才展示结果和失败反馈。
- 没有正式 output 时不因名称是 core.answer 就删去该 Action，保留“执行结果”与“已正式发布回答”的区别。
- 复核当前 interaction 的失败反馈与完成后投影，避免同一事实在结束边界前后失去原因。持久 Action 记录和主执行/异常体系无需改变。

### 3.3 明确清理范围

- 删除 SessionActionRecord decoder 的 legacy_options 转换及失去消费者的说明；当前版本只接受 typed options。不升级旧实例记录，不增加兼容解析。
- 替换前端测试中作为合法输入使用的 `turn:trace@…`，保留明确用于拒绝旧格式的测试。
- 清除 `ActivityGlimpse` 中重复的 payload.ref fallback；按真实消费者检查相邻字段，避免再次机械替换。
- 修正 `docs/design/session.md` 中 R6/legacy_options 的历史措辞；修正 `docs/endpoint/frontend-integration.md` 中创建请求后保存 turn_id 用于控制的过时表述，明确 request_id 与可空 turn_id。
- 保持清理有明确范围，不借机重构无关前端页面或所有浏览接口。

## 4. P2、P3：在分页之前建立语义披露单位

### 4.1 路线选择

| 路线 | 能解决的范围 | 评价 |
| --- | --- | --- |
| 在当前 JSON 页外添加 model_text | 完整小页的显示可以改善；已截断的 canonical_json 没有完整语义对象可供投影 | 不足以解决 P2/P3，不采用 |
| owner 从事实构造语义单位，按单位/正文分页，再生成可读消息和精简读取事实 | 分页、标题、引用、实际范围和折叠由同一次选择结果解释 | 推荐 |
| 新建模型专用读取网关或持久摘要库 | 引入新的路由、状态和事实副本 | 不在范围 |

“统一语义单位”只描述一次读取结果，不拥有资源、不跨 owner 读取、不取代 Context 段或 Action。U0 的独立域入口和权限继续成立。

### 4.2 共同结构与 owner 职责

优先演进既有 DisclosurePage/DisclosureHint、inspect_document 和 ActionResult.model_text。Trace/Session 与文档读取确需共享的披露值及页选择放入 `kernel/retrieval/disclosure.py` 的共同协议；Context 仍拥有事实发现和段路由。若移动既有类型，直接迁移内部导入，不留双定义或兼容重导出。

披露单位只需表达以下有实际消费者的内容，不为每个 owner 建继承层次或动态 registry：

- 精确 ref（已有独立身份时）、标题和真实线索；无独立身份的说明随父页，不虚构内容 ref。
- owner 根据 typed facts 构造的可读正文；结构化结果可以保留为业务正文的一部分。规范输入、问题、回复、Action 状态/请求/结果/失败及解释关系都有明确角色。
- owner 提供的范围：文档行/字符范围、某个交互正文范围，或目录的实际子项；内部偏移只供分页，不要求模型拼装。
- 现有机器内容供 SDK/前端使用；可读投影和机器投影源于同一事实，不从 model_text 反推 payload。

Trace owner 负责 Entry/Action/input 的解释；Session owner 复用交互及解释投影；Home/Memory 负责正文、标题和真实 Markdown 直接引用；Workspace 复用现有文本页与目录元数据。公共层只排列、限量和格式化这些输入，不导入各插件、读取文件或推断业务含义。

目标调用链为：

```text
owner facts → 有说明的披露单位 → 本次有界页面
                               ├→ SDK/Endpoint 的页面数据
                               ├→ ActionResult.payload + model_text
                               └→ ActionTraceProjection.canonical_payload + model_text
```

结果可在内部使用明确的 frozen value 携带三份投影；不能把 model_text/recollection 私藏为临时 JSON 魔法字段，再由某个调用者 pop 出来。是否直接扩展既有页对象或增加一个小型返回值，由实施时的实际调用签名决定，职责已限定为“一次页面选择的结果”。

### 4.3 分页规则

1. 优先返回完整语义单位：一个输入、一个问题、一个回复、一条 Action 事实或一个带解释的导航项。
2. 单个正文仍超限时只切正文，每页携带自己的标题、ref、角色及真实范围，明确“此项未完，继续读取”。不能切序列化框架对象，让模型跨页拼出 JSON envelope。
3. 普通问答尽量完整。特别长的问题/选项说明可以分页，但后页重复最少的问题定位和选项身份；不能返回没有问题解释的孤立选择或 comment。Session Background 原有整轮预算策略继续保留。
4. 大业务 JSON/代码若本来就是被读内容，可以作为带范围的正文分段展示；不把它当自然语言、不伪称该页是完整数据，也不擅自删去未知业务字段。
5. 文档 ref、标题/Markdown label 和说明作为整体呈现。目录只读直接子项，不递归加载子正文；说明优先来自实际 label、title、目录 metadata，缺少时使用诚实的名称/类型，不调用模型编造摘要。
6. 公共 Inspect 页继续使用 `ref`、`items`、`next_continuation`。完整项保留所属 owner 的结构化事实；超长项使用有 `ref/title/text/coverage` 的明确正文片段项（例如 kind=content_slice），不使用 canonical_json 传输碎片。模型消息只渲染该页的可读内容一次。
7. 预算同时核对本次序列化页面与模型文本的实际大小；必要的标题、引用、范围和续页说明占预算，不能分页完成后再无界附加。元数据都放不下时沿既有 page_budget_too_small 局部反馈，不截断 ref 或悄悄超限。
8. 保留 OpaqueContinuationCodec 和 owner 校验，不引入新令牌存储。绑定实际披露目标、范围、内容和必要 lease；不因无关注释 revision 变化或 Background 折叠使未变页面失效。现有 Session.inspect 把全局 manifest.revision 加入绑定的路径需要随本项一起核对和收窄。

上述变化只作用于模型可见的 Inspect 披露及读取同一页的宿主接口。`infra.continue_json_sequence` 仍服务 SDK 原始数据分页、interaction 传输等真实机器消费者，不全局删除它的 JSON 分片能力；Job 输出与 Search 结果集分页也不重写。

### 4.4 各入口的可读形态

- Trace root/node：有说明的子项；Entry：所保存叙事；input occurrence：同一 typed input 的补全叙事；活动 Action：本次执行事实和实际结果，不限缩为折叠 Entry。
- Session Turn：复用按 Turn 包装的交互投影；单个事实仍带所属 Turn、角色和问题语境；map 显示关系的含义和有说明的入口，不复制全部历史正文。
- Home/Memory：标题、精确 ref、正文和实际范围；direct_refs 返回 ref 与来源 label/已知标题，不能全部降成裸字符串。
- Workspace 文本沿现有直接正文投影；目录迁移到同样的完整项/正文片段规则，避免长说明重新产生 JSON 碎片；非文本继续明确 metadata-only。

示意（实际固定包装继续由所属 prompts 管理）：

```text
用户回答：文档保留方式
引用：turn:trace/2026-10-07/2#input/1

此前问题：是否保留完整正文？
用户选择：保留完整正文
选项说明：保留示例。
用户补充：增加来源引用。
```

Action 内部结构化结果仍可供宿主使用，模型不会同时收到同一份可读正文和它的 JSON 副本。分页结果保护仍只由取得响应的主循环 Phase1/Phase2 解除。

### 4.5 精简读取事实从同一页面生成

替换当前“读取任意 dict、猜 title、抽取所有 ref”的 inspect_recollection 做法。共同页值应明确给出：

- 目标 ref、真实标题和有界说明；目标没有人工标题时，以角色和事实内容给出确定性线索，例如“用户回答：保留正文”，而非复制 ref 充当解释。
- 读取意图：正文/目录/查询/metadata 及实际 query；不声称执行了额外搜索或摘要。
- 实际覆盖：本页完整项与部分项、对应 ref 和解释、必要范围；明确仍有后续。片段页不能只留下 partial_item=true。
- 一个可直接阅读的短说明，例如“读取了关于保留正文的用户回答及补充意见”；不得将请求的完整范围写成实际全部已读。

精简结果是有界的。少量子入口可以连同说明保留；超预算时共同折叠到有解释的父 ref，并保留本页范围/数量事实，不能把子项摘要删掉却永久铺开一串裸 ref。query 命中说明来自实际命中，不能用通用“相关”代替。

canonical_payload 保存这些执行事实，canonical model_text 从中格式化；不持久保存完整 Inspect 正文，也不保存独立摘要数据库。Session completion 仍只保存 canonical_payload；Session 叙事需要正确呈现它的目标、说明和覆盖，不把新结构再次包成难读的嵌套 JSON。

Inspect request 中的旧 continuation 可继续作为原调用事实存在；历史叙事以“续读哪个目标及范围”表达，不要求模型解释长令牌。需要继续当前分页时才显示实际可用 token；不增加折叠后的令牌保留机制。

## 5. P5：Workspace 读取成本评估

### 5.1 问题性质

此问题主要是性能与资源使用：每页 O(文件大小) 的读取/分行，以及 O(选段大小) 的编码/哈希，峰值内存不是 O(页面大小)。较长的串行 owner 操作也会影响同时等待的其它 Workspace 调用。它不表示已返回的普通小文件正文、引用或行范围错误。

本轮没有实测具体大文件延迟或内存峰值，不给出未经测量的容量阈值，也不把假定的超大文件故障当成当前日常使用故障。

### 5.2 可行路线与成本

| 路线 | 收益与代价 | 本计划建议 |
| --- | --- | --- |
| 只复用流式 read_text_range | 全文/行范围可减少正文驻留，但现有 token 在读取前验证完整选段哈希；标题仍依赖 CommonMark 全文解析。不能仅换一行函数调用就宣称全面有界。 | 可作为以后优化的起点 |
| 分块扫描并计算选段摘要，再读一页 | 可限制全文/行范围的峰值内存；仍可能每页扫描选段，需设计同次读取内容/范围的解释及当前文件变化语义。 | 中等工作量，收益主要是内存 |
| 支持全部 CommonMark 标题的流式定位与高效续页 | 必须保持围栏代码、Setext/ATX 标题、嵌套结构、重复 slug、Unicode 和范围语义，不能用一个标题正则替换现有解析器。引入索引/cache 又增加生命周期。 | 成本较高，不随本轮加入 |

建议本轮暂缓 P5 的完整实现，保留当前确定性语义，明确记录“返回页有界，内部可能全文读取”。不为了本轮达标新增文件 CAS、永久索引、正文快照或另一套 continuation；也不靠硬拒绝所有长文件替代可读能力。

若维护者希望本轮处理，可独立选择“先优化全文/行范围内存、标题保持既有实现”，并单独验收，不把它称为所有资源读取都流式化。原计划的来源预算要求需要在收尾记录中明确列为未实施并接受的限制，不能继续记为已完成。

## 6. P6：ask、Markdown 卡片与正式待答的统一契约

### 6.1 区分三个真实消费者

1. **模型生成 Action 意图**：core.ask 是结构化工具调用，可传 text/options/allow_other；也可让 text 包含一个规范 Markdown 问题块，由后端解析成相同 QuestionContent。
2. **正式交互事实与前端待答**：ActionResult → QuestionRequest → TurnSnapshot.question / agent.question interaction → QuestionCard。前端依据正式 question_id 和等待状态提交 reply，不依据任意 Markdown 创建等待。
3. **普通 Markdown 中的卡片**：前端只注册 tinysoul-question；普通回答里的合法块可显示选择卡片并填写 Composer 草稿，历史只读。它本身不向某个 core.ask 发送回复。

保留 Markdown 特殊卡片能力。前端用 JSON 传输 typed question 是正常边界，不能将其误判为卡片失效原因；也不能通过让前端把任意 json fence 猜成可提交问题来掩盖错误。

### 6.2 规范输入与指导

推荐继续支持现有两种正式输入，归一化到唯一 QuestionContent，不新增第三种别名：

- 显式字段：text 是可读问题，options 是真实选择，allow_other 控制自由回答。
- Markdown 卡片：text 内使用下列唯一标记，块外文字是问题说明；块内不带 kind 或 text 别名。

````markdown
请确认正文保留方式。

```tinysoul-question
{"question":"如何保留这份文档？","options":[{"id":"keep","label":"保留完整正文","description":"保留示例与来源。"},{"id":"brief","label":"只保留摘要"}],"allow_other":true}
```
````

更新 Catalog 的真实 ToolSpec 描述和短示例，明确普通 json fence 不定义选项、kind 字段不属于此协议、不要同时提交冲突的显式选项和问题块。Catalog 内容仍由 Catalog 管理，不复制到 prompts。

为生成 core.ask 参数的 Phase2 提供可见的简短指导：优先在 core domain Skill 中写规范示例（当前默认只有 workspace/web/execution 的 domain Skill）。只新建 action/core/ask Skill 不足以解决问题，因为 core.ask 没有内部 LLM 任务，Phase2 挂载的是 domain Skill。若普通 core.answer 输出展示卡片，其现有 answer Skill 也说明同一个 fence 及 display-only 语义。

固定解析失败反馈进入所属 prompts，动态约束由执行器传入，不把用户问题或大段无效 JSON 放进异常。

### 6.3 错误协议如何反馈（待确认的行为选择）

推荐：在 core.ask 的局部参数解释中，针对本次已出现的明确误用给出可修正失败，而非接受成“无选项问题”：外层没有显式选项，普通 json 块是声明 kind=question 且含 question/options 的问题对象。反馈指出应使用 tinysoul-question、移除 kind，或改用显式 options。不得静默把这种格式转换成有效卡片。

此检测只处理声明为问题协议的有限形状，不扫描普通自然语言猜测“像不像提问”，不禁止问题正文包含正常 JSON 示例，不增加宽泛容错解析器。合法 plain-text ask 继续成立。

正确 fence 的未知字段、多块、不闭合、字段冲突等失败应返回具体而有限的原因与修正方式。现有统一 INVALID_QUESTION 没有说明 fence 名称与字段，需改善；仍使用 Action 局部结果，不让 Runtime 接管可修正协议失败。无效问题不发布、不进入等待。

可选的更窄范围是只改提示与示例、保持误标 json 被当普通文本的现状；它不引入新校验，但不能避免同类误用再次成功进入等待。本计划推荐前一种，待维护者确认。

### 6.4 补齐问题说明与消费者

- 将已有 explanation 作为规范问题内容的一部分，优先扩展既有 QuestionContent，避免 ActionResult、QuestionRequest、Session 和前端各维护不相干的说明文本。
- fence 外文字由后端归一化，仍是代码/用户提供的真实文本；显式字段输入继续按原 text 表达其问题语境。
- question_from_results、snapshot、当前/历史 interaction、Endpoint schema/样例、前端类型与 QuestionForm 一起传递和显示说明。保留 question_id、选项 ID 和提交语义，避免出现两个可提交卡片。
- 前端 Markdown fence 与后端使用同一份语义规则：question/options/allow_other，类型、唯一 ID、未知字段行为明确；前端普通展示块解析失败仍回退代码块，不制造执行事实。
- model_text 继续服务模型叙事；QuestionCard 使用正式 typed question，不反解析 Trace 自然语言，也不要求后端把正式待答重新编码成 Markdown 再解析。

## 7. 预计改动范围、实施顺序与验收

### 7.1 代码和公开消费者

| owner / 入口 | 预计改动 |
| --- | --- |
| kernel.interaction、context/engine、builtin/trace | 复用输入/回复叙事，补齐当前 input occurrence 和证据读取；问题说明进入规范问题内容 |
| kernel/context/disclosure、kernel/retrieval/disclosure | owner 语义单位、页面选择、可读渲染、覆盖与精简事实；必要的共同值集中一处 |
| context segments、ContextInspectExecutor | 传递同一次读取结果；保持现有路由、局部失败与展示保护 |
| plugins/session/views、completion、records | 历史输入语境、Action 失败可见性、Inspect 叙事、canonical 结果可读性、移除无效兼容；不改为第二份历史 |
| Home/Memory Inspect、Workspace 目录 Inspect | 接入正文/导航分页与同页精简事实；direct_refs 保留解释；Workspace 文本读取算法暂缓 |
| core.ask、loop QuestionRequest、Agent snapshot | 正式问题归一化、明确反馈与说明传递；不修改等待/恢复状态机 |
| Catalog、core domain Skill、answer Skill、prompts | 在真实生成位置给出协议指导，固定包装归所属 owner |
| SDK/Endpoint | Context/Session/Home/Memory Inspect 页面中的标题/覆盖/正文片段契约；TurnQuestion 说明字段；文档及契约样例同步 |
| visualization | 消费 Inspect 正文片段项和说明；QuestionCard/QuestionForm/fence 对齐；修正旧引用测试和重复 fallback。只处理本计划的接口消费者 |

公共接口预览：不新增读取路由或模型参数；ref/continuation 和各域 Inspect 入口保留。相关 Inspect 页由 canonical_json 碎片改为语义明确的部分正文项，需对齐读取这些页的真实消费者；通用 interaction/原始数据分页保持现有用途。TurnSnapshot.question 增加有来源的问题说明。无历史格式兼容要求，不自动修改 my-agent-dev。

### 7.2 执行顺序

1. 确认第 8 节选择，固定 P2/P3 页面样例与最少的 owner 返回值；建立能复现当前缺口的行为用例。
2. 先完成 P1、P4、清理和 P6 的问答闭环，让直接用户交互恢复可靠反馈；同步相关 Endpoint/前端消费者。
3. 从一条回复和一段文档验证完整页/部分页/续页的共同设计，再扩展 Trace、Session、Home、Memory 与 Workspace 目录；不留下旧、新并行的模型 Inspect 路径。
4. 从实际页生成精简事实，验证折叠和 Session completion 后仍有解释与精确范围；复核引用与说明共同折叠、无关注释不使续页失效。
5. 同步 AGENTS 必要的稳定语义、设计、Endpoint、默认资源和本计划进度；完成门禁后逐项核对。P5 明确标为暂缓限制，不计入“已修复”。

### 7.3 验收清单

- [ ] 当前 Trace Entry/input occurrence、Session Turn/input occurrence 和 Search 命中都能读懂同一 typed reply；原始 text/answer/ref/timeline 不被改写。
- [ ] 失败/超时等 core.answer 保留执行事实；成功正式回答只展示一次；无 output 不伪造发布。
- [ ] 同一 Inspect 页的实际返回内容、模型文本与覆盖事实一致；模型不接收框架 canonical_json 半截封装。
- [ ] 长问题、选项说明、comment、业务 JSON 和跨页文档都保留角色、目标及范围；续页不漏正文、不伪称完整。
- [ ] 目录、direct_refs、查询命中始终提供真实解释；没有标题时使用事实线索，不以 ref 冒充摘要。
- [ ] 折叠保留目标、短解释、实际完整/部分覆盖和有无后续；不保存全文或额外 token，不把请求范围当实际已读范围。
- [ ] 主循环展示保护、活动 #action 实际结果读取、canonical Session 保存保持既有边界。
- [ ] 普通背景压缩或无关 map 更新不使未变目标续页失效；内容变化按 owner 契约反馈，不静默重启。
- [ ] 实际错误 json/kind 问题形状得到已确认的处理；正确 Markdown fence、显式 options、纯文本提问均验证等待/回复闭环。
- [ ] 正式卡片、说明、完整选项、comment 在 snapshot → interaction → 历史之间一致；普通回答里的卡片只影响草稿，不创建待答。
- [ ] Phase2 实际任务可见正确协议指导；不以未挂载的 ask Action Skill 代替验证。
- [ ] 旧 Trace 形式的合法测试、legacy_options 和过时文档已清理；拒绝旧格式的测试仍保留。
- [ ] 聚焦测试、Fast、Full、ty，以及受影响前端测试和 TypeScript/build 通过；Endpoint 真实契约样例对齐。
- [ ] 完成逐项核对后才改为 done 并归档；接受暂缓的性能限制明确列出。

测试以 owner 行为与真实边界为中心：关键问答矩阵由 typed question/Action owner 覆盖，SDK/Endpoint/前端各保留一条真实往返；页面测试验证正文覆盖和可读信息，不锁死可编辑文案。`continue_json_sequence` 的真实机器分片测试保留，Inspect 测试不继续固化模型必须消费 JSON 碎片的旧假设。生成资源用例验证新增 core domain Skill 的实际装配。

## 8. 待审阅选择

1. **P2/P3 推荐方案**：接受 owner 在分页前提供语义单位，并让模型与宿主读取同一次页面选择；相关 Inspect 部分页接口同步调整。无需改变 U0 或增加通用读取 Action。
2. **P6 推荐方案**：保留显式字段和规范 Markdown fence 两种输入；对本次明确误标的 question JSON 给出局部失败与修正提示；问题说明贯通正式卡片。不会让普通 Markdown 卡片自行取得等待身份。
3. **P5 推荐范围**：完整流式化本轮暂缓，明确记录限制。若要做有限的全文/行范围内存优化，再按第 5 节选定范围。

前三项是方案审阅点，不阻塞当前文档交付。用户已确认 P1/P4/清理方向；本计划不再为这些方向重复设置批准点。实施仍需在上述语义和公开页面变化审阅后开始。

## 9. 本次调查与文档交付记录

- 重新读取 AGENTS，核对 `d56aff3` 实施、前两份归档计划、Inspect 分页和公共消费者。
- 只读查看测试实例当日 4 份 Session 记录，并限定提取 core.ask 请求/结果和相关回答；核对实例 ask Catalog 与仓库一致。未修改、迁移或复制整个测试实例。
- 当前生产 `_question_content()` 的三个最小输入复现确认普通 json / 正确 fence / 错误 kind 的分歧。尚未运行真实模型复现，不保证仅改提示能消除模型输出错误。
- 上一轮审查的 328 项后端、68 项前端聚焦验证属于既有基线，不能作为本计划实现验收。本轮只新增本计划，进行 Markdown 本地链接及 diff 检查，不重复无关代码全量门禁。

本次建议提交文本：`docs: plan context disclosure follow-up and question card fixes`。
