# Context 叙事与 Inspect 披露收尾及问答卡片修正执行计划

日期：2026-10-07

状态：`pending`（进一步调查与方案修订已完成，业务代码尚未实施；P5 暂缓已经确认，其余设计继续讨论）

基线：`d56aff3 refactor(context): improve narrative context and unify references`。

本计划承接[上下文叙事执行计划](<done/20261006-done- 模型上下文叙事投影与引用语义统一执行计划.md>)和[引用统一执行计划](<done/20261006-done- 引用体系梳理与统一执行计划.md>)交付后的复核及实际使用反馈。前两份计划完成了主体迁移，本计划单独记录尚未闭合的语义、分页、消费者和问答问题，不把前次通过门禁等同于这些问题已经解决。

设计依据为 [AGENTS.md](../../AGENTS.md)、[Context](../design/context.md)、[Session](../design/session.md)、[引用格式与渐进读取](../design/references.md)及现有 Action/owner/Runtime 边界。

## 1. 目标、边界与当前结论

继续使用唯一的输入、问题、Action 和 Session 事实，通过正向投影使直接 Context、按引用读取的页面和折叠后的线索可以相互解释。模型应直接读到发生了什么、回答了哪个问题、读取了哪里，以及下一步可以读取哪个引用。

保留已经确认的路线 A、U0、日期/日内序号和 request/Turn 分工。ask 仍使用自己的唯一 ActionResult Entry；input/append/reply 仍是独立输入 Entry。Inspect 属于各 owner，不引入统一工具网关，不扩大跨日 Session/Workspace 访问，不引入摘要模型、正文版本库、平行日志或额外续页令牌保存服务。

本轮拟实施 P1、P2、P3、P4、P6 和清理项。维护者已确认本轮暂缓 P5 的 Workspace 完整流式化；这是现有性能限制，不记为已修复。P6 收窄为已有契约核实、真实说明丢失修复及隔离复验，撤回按某次错误 JSON 形状新增识别规则、默认增设 Skill 和堆叠纠错提示的建议。当前阶段只修订计划，不修改业务代码、默认资源或测试实例。

## 2. 已确认的问题与成因

| 编号 | 事实与成因 | 对使用的影响 |
| --- | --- | --- |
| P1：回复回忆不一致 | `kernel/context/engine.py::_current_search_facts()` 只投影输入原文与内部 reply_to；`builtin/trace.py::append_input()` 已用 typed question/answer 补全叙事。Session `views/navigation.py::project_occurrence()` 的 input 分支也只返回原文。 | 同一回复从 Entry、input occurrence、Session 整轮或历史 input 读取时，问题语境不同；模型需要额外推断关联。 |
| P2：Inspect 仍暴露传输结构 | Trace/Session 的 DisclosurePage 与 Home/Memory 的 inspect_document 直接调用 `continue_json_sequence()`；单项超预算后截断的是整个 JSON 对象的序列化文本。Action 又把这一页面作为通用 JSON ToolResult。 | 模型读到 canonical_json 的半截字符串、转义换行和协议字段；普通交互的阅读重新变成结构重组。 |
| P3：折叠缺少解释与覆盖 | `inspect_recollection()` 猜测 metadata.title/display，缺失时把 ref 当 title；只抽取完整 items 中的 ref，丢弃 title/clue。fragment 页没有完整 item，折叠后只剩 partial_item。 | 读取一个问题回复后可能只记得“读过 #entry/3”；目录保留裸子引用；无法说清某次部分读取实际覆盖了什么。 |
| P4：失败回答消失 | `session/views/interaction.py::project_interactions()` 无条件跳过所有 core.answer，原意是避免成功回答与 output 重复。 | 失败/超时等尝试在持久事实中存在，但线性叙事缺失，后续修正行动失去原因。此项是既有逻辑遗留，并非此次提交新引入。 |
| P5：页预算没有限制读取内存 | `workspace/inspection/reader.py::inspect_text()` 每页先 read_text 全文，再 splitlines、选段、编码及哈希，最后切出返回页。 | 单页输出有界，读取耗时和峰值内存仍随文件/选段增长；续页重复扫描。常规小文件读取语义正常。 |
| P6：问答表达混用与说明缺口 | 第 2 轮只在普通 json fence 内写选项，正式 options 为空；第 5 轮同时传显式 options 和普通 json fence，选项可提交，嵌套 question 未被规范化。另有正确 fence 外 explanation 未进入正式待答内容的既有缺口。 | 区分模型输出形状与前后端缺失；不能把所有显示问题归因于同一字段或上一轮迁移。 |

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

进一步发现：正确 fence 外的说明被保存为 ActionResult.explanation，Trace/Session 有该字段；`QuestionRequest` 经 QuestionContent 取得的问题内容及 snapshot 不携带它，前端 QuestionContent/QuestionCard 也不消费 explanation。需要在卡片闭环中一起补齐。这里专指独立 explanation，不表示写在 text 中的说明无法显示；该缺口在 `272f1f7` 已存在。

### 2.2 最新复验与上一轮改动对照

再次只读检查 `runtime/session/turns/5.json`：

- request 显式传入 4 个 typed options；result 保留这些选项。用户以 `kind=choice` 选择 `chain-verify` 并附 comment，记录均完整。
- text 同时含说明、自然语言提问、推荐和一个普通 json fence；该 fence 内重复 question/options，并包含 kind=question。此调用没有独立 explanation 字段。
- 正式卡片直接显示整个 text 和外层 options，因此说明与选项能够显示；JSON 中的 question 不会另行变成卡片标题。实际 text 中的自然语言提问仍在，不能据此断言所有问题文字被前端删除。当前代码中没有在显示选项时隐藏 question.text 的分支；尚未进行该运行页面的浏览器视觉复现。
- 第 5 轮模型声称第 2 轮用了 core.answer，但第 2 轮正式记录是 core.ask；这是模型对历史的误述，不能拿来解释真实执行。已有错误示例进入 Session，可能影响后续生成，但尚无受控模型对照证明因果。

`272f1f7 → d56aff3`：ask Catalog、`_question_content()` 解析、QuestionContent 的字段/默认值、QuestionRequest 提取、前端 questionContent/QuestionCard 均未变。QuestionForm 只改 Markdown origin 的 link→ref；answer Skill 只改 Link→reference；Home 顶层指导改了 Context 叙事及引用说明，没有替换卡片协议。ask 新增的只是成功结果 model_text。实例 ask Catalog 与仓库一致，actual Home 与 runtime Home 的 Markdown 搜索未发现另一套 tinysoul-question/allow_other/kind=question 指导。

这些证据不足以把偶发误标归结为提示词回归。实现前后的有效输入应按同一契约检查；不先向所有指导加入“禁止 json/kind”等针对单次输出的细碎规则。

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

### 4.6 “共同改进”的具体含义与消费范围

分页和折叠仍是两个不同操作：分页决定这次读取多少，折叠决定已读页面以后在 Context/Session 留下什么。共同改进的是两者使用同一次页面选择及其覆盖事实，不是把二者合成一个运行阶段。

以读取一段问答为例，owner 先从已有问题/回复事实提供“用户回答：正文保留方式”、ref、可读正文和范围。页预算足够时完整返回；不足时保留标题和问题定位，分段返回真正的正文。本次返回选择确定后，生成如下两种模型投影：

```text
实际读取页：
用户回答：正文保留方式
引用：session:turn/2026-10-07/2#input/1
此前问题：如何保留文档？
选择：保留完整正文；选项说明：保留示例与来源。
补充：……本页实际返回的文字……
范围：该回复的第 1 段，正文尚未读完；可用本接口的 continuation 继续。

精简读取事实：
已读取“正文保留方式”的用户回答及部分补充。
引用：session:turn/2026-10-07/2#input/1
实际范围：第 1 段；仍有后续。
```

示例文字中的“部分”必须来自实际覆盖，不由摘要猜测。文档页用行/字符范围；交互页用所属交互及正文范围，不能把渲染后字符偏移冒充源文件行号。精简事实在 Action 返回时即可由同一选择构造，但实际正文只有经过主循环展示保护后才允许按容量被替换。SDK/Endpoint 的只读查看既不往模型 Trace 添加 Action，也不触发这种消费标记。

预计代码工作分为四层：

1. **内容 owner**：Trace/Session 把已有 Entry、问答和交互转成可读单位；Home/Memory 在 Markdown 引用解析时保留真实 label，标题来自当前文档/已有目录；Workspace 目录保留名称、说明与目标。原始输入、Action payload 和 Session 记录继续是事实，不从自然语言恢复机器字段。未知 Action 的业务 JSON 可作为带执行说明的正文展示，不发明通用结果解释器。
2. **共同分页**：演进现有 DisclosurePage/inspect_document，接收正文而非只接收任意 dict；优先完整项，超长则切正文。最少共同值是解释、引用、正文和覆盖；正文位置复用现有 ContentUnit/ContentSlice 可用部分，不把 Search 的评分/evidence 强加给 Inspect。仍由 OpaqueContinuationCodec 校验范围、内容和生命周期。
3. **Action 与持久投影**：Inspect Action 从该页提供 payload/model_text 及 canonical_payload/model_text；Session 用 canonical facts 正向渲染。活动 #action 仍能读实际 ActionResult；旧读取的回忆只承诺读取意图与范围，不恢复未保存正文。
4. **已有宿主消费者**：在原路由读取结构化页；立即显示每个完整项/部分正文页，不等待把传输碎片拼成一个 JSON 对象。若某完整项有供宿主使用的结构字段，仍保留；部分正文项明确标为 partial，不能冒充完整可执行问题、完整 annotation 或原始 Action 对象。

具体消费点与变更预览：

| 消费者 | 当前使用方式 | 预计调整 |
| --- | --- | --- |
| core.context.inspect → ContextEngine/Trace/Session 段 | 直接把 JSON 页作为模型 ToolResult，再从字典猜测 recollection | 接收 typed 页结果，提供可读正文与同页精简事实；保留 ref/query/continuation 的入口语义 |
| home.inspect、memory.inspect | inspect_document 返回 JSON 页及裸 direct_refs | 使用正文/目录语义页；ref 与真实 label/标题一起披露；不展开被引用文档 |
| workspace.inspect | 文本已有 model_text；目录长项仍可能产生 JSON 碎片 | 目录接入共同完整项/正文片段规则，折叠保留说明；文本读取算法不改 |
| SDK Context/Session 与 `/context/inspect`、`/session/inspect`、`/session/map` | 与模型入口共用 DisclosurePage | 保留路由，公开标题、正文及明确 coverage；部分项不再使用 canonical_json 分片 |
| Home content/diff、Memory document/active 宿主读取 | 也调用 inspect_document；有独立的视图/日绑定和 metadata | 随共同返回协议对齐；保留 actual/effective/diff 和日身份，不因复用格式扩大模型权限 |
| ContextInspectPanel、SessionRefPanel、SessionMapPanel | 解析 child/relation/source，内容主要显示 JsonTree | 识别可读正文与覆盖，保留导航与语义关系；超长 annotation 的正文片段不误识别成完整图节点 |
| HomeContentView/HomeDiffView、MemoryDocumentView/ActiveMemoryView、OwnerResourcePanel | 分页后拼正文，部分路径读取 metadata.direct_refs | 对齐正文片段和引用说明，保留原文顺序及范围；不把长目录无界塞进 metadata |
| API 类型、Endpoint 契约样例、相关测试 | Inspect 与机器传输共用 content_fragment 示例 | 为 Inspect 增加明确正文/coverage 用例；原始 interaction、Background、日志等真实机器传输的 JSON 分片不重写 |

保持公共 JSON 页面可消费，但它服务宿主；模型通过 model_text 直接读同一页面内容，不同时收到一份等价 JSON 副本。公开页面变化属于返回内容调整，不新增跨域 Inspect 路由、模型参数或第二套存储。前端仍可保留原始事实的详情查看，主要阅读不再要求先展开 JSON 树。

此项为跨 owner 的中等规模调整，主要成本在逐条迁移并验证现有读取出口，不在新增算法或状态机。实施先固定“短回复完整页、长回复续页、文档选段页、目录页、各自精简事实”五类样例，再迁移共同页协议与实际消费者，避免先建笼统框架再让 owner 适配。

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

维护者已确认本轮暂缓 P5 的完整实现，保留当前确定性语义，明确记录“返回页有界，内部可能全文读取”。不为了本轮达标新增文件 CAS、永久索引、正文快照或另一套 continuation；也不靠硬拒绝所有长文件替代可读能力。本轮也不另行插入部分流式优化。

以后有实际性能需求时，可单独评估“先优化全文/行范围内存、标题保持既有实现”，不能把它称为所有资源读取都流式化。原计划的来源预算要求在收尾记录中明确列为未实施并接受的限制，不再记为已完成。

## 6. P6：ask、Markdown 卡片与正式待答的统一契约

### 6.1 区分三个真实消费者

1. **模型生成 Action 意图**：core.ask 是结构化工具调用，可传 text/options/allow_other；也可让 text 包含一个规范 Markdown 问题块，由后端解析成相同 QuestionContent。
2. **正式交互事实与前端待答**：ActionResult → QuestionRequest → TurnSnapshot.question / agent.question interaction → QuestionCard。前端依据正式 question_id 和等待状态提交 reply，不依据任意 Markdown 创建等待。
3. **普通 Markdown 中的卡片**：前端只注册 tinysoul-question；普通回答里的合法块可显示选择卡片并填写 Composer 草稿，历史只读。它本身不向某个 core.ask 发送回复。

保留 Markdown 特殊卡片能力。前端用 JSON 传输 typed question 是正常边界，不能将其误判为卡片失效原因；也不能通过让前端把任意 json fence 猜成可提交问题来掩盖错误。

### 6.2 当前输入、model_text 与用户回复语义

当前已有两种正式输入，都归一化为 QuestionContent，不是上一轮新加的双协议：

- **显式字段**：Action 工具参数直接传 text 和 options。例如 `{"text":"先说明背景。\n\n你希望如何继续？","options":[{"id":"a","label":"继续讨论"}]}`。text 是完整可读问题正文，可包含说明和多个段落；options 是单独的结构化选项。此方式没有独立 question/explanation 参数，不会从自然语言里自动提取一个标题。
- **Markdown 卡片**：Action 的 text 内含一个规范 tinysoul-question 块。块内 question 归一化为正式 text，块外文字成为 explanation，options 来自块内。其外围 Markdown 本身可以按原样显示在普通回答中，但只有 core.ask 建立正式待答身份。

既有规范示例可省略 allow_other：

````markdown
请确认正文保留方式。

```tinysoul-question
{"question":"如何保留这份文档？","options":[{"id":"keep","label":"保留完整正文","description":"保留示例与来源。"},{"id":"brief","label":"只保留摘要"}]}
```
````

allow_other 表示是否允许用户给出自由文本回答，不是要求用户或模型新增一个候选项。缺省 true；选择已有项提交 `kind=choice/option_id/comment`，自由回答提交 `kind=text/text`。comment 与 allow_other 无关；即使关闭自由回答，选择已有项仍可补充 comment。选项 ID 是机器对应关系，不应把用户回答压缩成孤立字母。

当前 Catalog 将 allow_other 暴露为可选模型参数，但不要求生成；服务端和前端都已有默认值。本轮建议示例省略默认字段，不新增“每次必须写 true”的指导。若维护者希望所有提问都始终允许自行回答，则可进一步删除这一策略开关（Catalog/fence、QuestionContent、Endpoint、前端及相关限制测试共同迁移），不能一边接受 false 一边悄悄忽略它。仓库中未发现专门要求关闭自由回答的业务调用，但此项仍属于行为决策，暂不预设删除。

model_text 是 **Action 执行完成后的模型可读结果投影**。ActionResultRenderer 有它时用文本构造 ToolResultMessage，否则使用结构化 payload；ask 的文本由现有 typed question 正向生成，包含问题、选项和说明。它不是生成本次 ask 参数的输入协议、不替代 payload、不控制前端卡片；它会作为 Context 影响后续模型调用，因此仍需保证语义完整。foldable Inspect 的实际 model_text 和 canonical model_text 则分别用于本次正文与后续精简反馈。payload 与 model_text 保留不同消费者，但两者必须表达同一事实。

### 6.3 指导位置与修订原则

先核对契约和正常输入，再决定是否调整指导。本次对照未发现上一轮删除或修改 ask 卡片协议指导；因此不将“恢复旧提示词”列为修复，更不默认在 Catalog、Home、domain Skill、action Skill 各复制一份协议说明。

真实挂载顺序如下：

```text
Phase2：Context + 当前域的 domain Skill + 该域 Action ToolSpec
        → 生成 core.ask 参数
Phase3：CoreAskActionExecutor 解析参数
        → 返回问题事实 → 同一 Turn 等待回复（无内部模型任务）

core.answer 等具有内部 LLM 的 Action：
        ActionTaskFactory → 挂载 domain/action Skill → 执行 Action 内部任务
```

所以“只新增 ask Action Skill 无效”专指不会自动挂载到生成该工具参数的 Phase2，并不表示 Skill 内容永远不可被模型读取。既有架构刻意把调用工具的约束放在 ToolSpec，把整个域的行动方法放在 domain Skill，把 Action 内部任务的指导放在 action Skill。无需为 ask 修改全局挂载机制，也不应要求模型先自行读取未挂载 Skill 才能正常提问。

当前 ask ToolSpec 已说明两种形式、稳定选项 ID 和默认自由回答。若隔离复验仍显示表达有歧义，优先在这一处简洁写清“可读问题正文 + 可选候选项”，必要时附一个规范示例；具体错误由局部失败解释。只有确有整个 core 域的稳定方法需要指导时才新增 domain Skill；不以修复某次 kind/json 输出为理由默认新增。普通 answer 中展示卡片的说明也只在有实际需求时补入其 Skill。

### 6.4 已知缺失修复与隔离复验

撤回原先对“普通 json 块包含 kind=question”新增专门拒绝规则的建议。普通代码块仍是合法 Markdown 内容，不猜测它是否意图构成协议；不静默转换、不扫自然语言识别问题。正确 tinysoul-question 块继续使用既有解析和局部失败规则。固定反馈若改进，只描述真实解析失败，由所属 prompts 管理，不把大段无效输入或原始异常给模型。

复验依次区分两个层面：

1. 用明确的显式字段、规范 fence 两组输入验证后端归一化、snapshot、当前/历史 interaction 与前端卡片；覆盖说明、问题、选项、自定义回答和 choice+comment。这是契约检查，不依赖模型是否偶然选择正确形式。
2. 在不带上述错误历史的临时会话/隔离实例中，让真实模型自行生成 ask 参数，对照实际 Action request/result 与显示。仅清空前端、重新开始一个同日 Turn 不保证隔离，因为 Session 仍会带入之前的错误示例。此时先保留原 Catalog/Skill，避免同时改代码、提示和历史而无法区分原因。

不为复验删除或重置 my-agent-dev 的 Session/Home/Memory。当前只完成生产解析器与结果到待答的最小复现、前端现有行为测试和运行记录核对；尚未进行干净 Context 下的真实模型与浏览器显示对照，不能承诺重置一定消除问题。

### 6.5 补齐独立问题说明与消费者

- 将已有 explanation 作为规范问题内容的一部分，优先扩展既有 QuestionContent，避免 ActionResult、QuestionRequest、Session 和前端各维护不相干的说明文本。
- fence 外文字由后端归一化，仍是模型/调用者提供的真实文本；显式字段输入继续按原 text 表达其问题语境，不新增猜测式的 question 标题提取。
- question_from_results、snapshot、当前/历史 interaction、Endpoint schema/样例、前端类型与 QuestionForm 一起传递和显示说明。保留 question_id、选项 ID 和提交语义，避免出现两个可提交卡片。
- 前端 Markdown fence 与后端使用同一份语义规则：question/options/allow_other，类型、唯一 ID、未知字段行为明确；前端普通展示块解析失败仍回退代码块，不制造执行事实。
- model_text 继续服务模型叙事；QuestionCard 使用正式 typed question，不反解析 Trace 自然语言，也不要求后端把正式待答重新编码成 Markdown 再解析。

目标展示顺序为“说明（若独立存在）→ 问题正文 → 完整选项 → 自行回答/选择后补充 comment”。普通 Markdown 展示卡片的块外说明已由外层 Markdown 显示，不应再重复塞进内层 QuestionForm。修复的是正式问题事实的说明传递，不另建卡片协议或用提示要求模型把同一说明重复放进两个字段。

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
| Catalog、Skill、prompts | 先对照并隔离复验；仅在真实消费者处修正已证实的歧义，固定包装归所属 owner。不默认新增 core domain/ask Skill |
| SDK/Endpoint | Context/Session/Home/Memory Inspect 页面中的标题/覆盖/正文片段契约；TurnQuestion 说明字段；文档及契约样例同步 |
| visualization | 消费 Inspect 正文片段项和说明；QuestionCard/QuestionForm/fence 对齐；修正旧引用测试和重复 fallback。只处理本计划的接口消费者 |

公共接口预览：不新增读取路由或模型参数；ref/continuation 和各域 Inspect 入口保留。相关 Inspect 页由 canonical_json 碎片改为语义明确的部分正文项，需对齐读取这些页的真实消费者；通用 interaction/原始数据分页保持现有用途。TurnSnapshot.question 增加有来源的问题说明。无历史格式兼容要求，不自动修改 my-agent-dev。

### 7.2 执行顺序

1. 讨论第 8 节剩余选择，固定 P2/P3 页面样例与最少的 owner 返回值；建立能复现当前缺口的行为用例。P5 暂缓不再重复确认。
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
- [ ] 正确 Markdown fence、显式 options、纯文本提问均验证等待/回复闭环；普通 JSON 不被猜测为问题协议，不为单次误标增加专门解析分支。
- [ ] 正式卡片、说明、完整选项、comment 在 snapshot → interaction → 历史之间一致；普通回答里的卡片只影响草稿，不创建待答。
- [ ] 确认 Phase2 的真实 ToolSpec/Skill 可见性；指导变更有实际复验证据，不以未挂载的 ask Action Skill 或重复细则代替契约修复。
- [ ] 旧 Trace 形式的合法测试、legacy_options 和过时文档已清理；拒绝旧格式的测试仍保留。
- [ ] 聚焦测试、Fast、Full、ty，以及受影响前端测试和 TypeScript/build 通过；Endpoint 真实契约样例对齐。
- [ ] 完成逐项核对后才改为 done 并归档；接受暂缓的性能限制明确列出。

测试以 owner 行为与真实边界为中心：关键问答矩阵由 typed question/Action owner 覆盖，SDK/Endpoint/前端各保留一条真实往返；页面测试验证正文覆盖和可读信息，不锁死可编辑文案。`continue_json_sequence` 的真实机器分片测试保留，Inspect 测试不继续固化模型必须消费 JSON 碎片的旧假设。若确有默认资源改动，生成资源用例验证其实际装配；不新增只断言某个提示词句子的测试。

## 8. 待审阅选择

1. **P2/P3 推荐方案**：owner 在分页前提供语义单位，实际页面与精简事实使用同一次选择；按第 4.6 节对齐已有读取消费者。保持 U0，不增加通用读取 Action。
2. **P6 收窄方案**：保留当前显式字段和规范 Markdown fence 输入，修复已复现的独立 explanation 丢失；先保持现有指导做隔离复验。撤回专门误标 JSON 校验和默认新增 Skill 的建议。
3. **allow_other 待讨论**：当前保持可选、默认 true，模型不必生成。若维护者要求用户始终有自由回答入口，则可统一删除关闭自由回答的能力；这不是修复显示缺失的前提，不静默实施。
4. **P5 已确认**：本轮暂缓 Workspace 完整流式化，记录限制；不再设确认点。

剩余方案继续讨论，不阻塞当前文档交付。用户已确认 P1/P4/清理方向和 P5 暂缓；本计划不再为这些方向重复设置批准点。当前请求是分析与计划修订，不视为本轮业务代码实施授权。

## 9. 本次调查与文档交付记录

- 重新读取 AGENTS，核对 `d56aff3` 实施、前两份归档计划、Inspect 分页和公共消费者。
- 只读查看测试实例当日 4 份 Session 记录，并限定提取 core.ask 请求/结果和相关回答；核对实例 ask Catalog 与仓库一致。未修改、迁移或复制整个测试实例。
- 当前生产 `_question_content()` 的三个最小输入复现确认普通 json / 正确 fence / 错误 kind 的分歧。尚未运行真实模型复现，不保证仅改提示能消除模型输出错误。
- 上一轮审查的 328 项后端、68 项前端聚焦验证属于既有基线，不能作为本计划实现验收。原计划建立时只新增本文并进行 Markdown 本地链接及 diff 检查；进一步修订的验证另列如下。

### 9.1 进一步讨论后的修订验证

- 维护者已提交原计划为 `f749951`；本次只修订此计划，业务代码仍基于 `d56aff3`。
- 只读核对第 5 轮 request/result/answer，并对照上一轮 ask、QuestionContent、completion、前端 QuestionContent/QuestionForm、Catalog 与 Home/Skill 的实际 diff。
- 生产解析器 + question_from_results 的三组最小复现：显式 text/options、规范 fence、显式 options 加普通 JSON。三者均支持默认自由回答和选择后 comment；规范 fence 的独立 explanation 确认丢失在 QuestionRequest 内容中，另外两组无独立 explanation。
- 运行现有 `QuestionCard.test.tsx` 与 `questionBlock.test.tsx`：2 个文件、17 项通过。这证明既有用例正常，不代表已覆盖独立 explanation 缺口或已复现浏览器中“question 未出现”。
- 计划本地链接、空白与 diff 检查；没有运行真实模型、重置测试实例或修改业务/前端代码。

本次建议提交文本：`docs: refine disclosure plan and clarify question card contracts`。
