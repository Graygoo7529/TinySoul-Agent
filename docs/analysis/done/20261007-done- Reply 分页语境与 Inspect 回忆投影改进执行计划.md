# Reply 分页语境与 Inspect 回忆投影改进执行计划

日期：2026-10-07

状态：`done`（实施、文档同步、完整门禁及逐项核对已完成）

实施起点：`0583945 docs: plan reply pagination and inspect recollection improvements`；其业务代码基线为 `164e4ba refactor(context): unify semantic inspect pages and structured ask narratives`。

本计划承接以下三份计划的实施复核，记录新发现的投影缺口与本轮讨论，不改写归档记录的历史结论：

- [模型上下文叙事投影与引用语义统一执行计划](<20261006-done- 模型上下文叙事投影与引用语义统一执行计划.md>)。
- [引用体系梳理与统一执行计划](<20261006-done- 引用体系梳理与统一执行计划.md>)。
- [Context 叙事与 Inspect 披露收尾及问答卡片修正执行计划](<20261007-done- Context 叙事与 Inspect 披露收尾及问答卡片修正执行计划.md>)。

依据：[AGENTS.md](../../../AGENTS.md)、[Context](../../design/context.md)、[Session](../../design/session.md)、[引用设计](../../design/references.md)。

## 1. 目标与当前授权范围

保留现有事实 owner、Action 执行和折叠体系，让同一条回复在直接语境、独立读取、查询导航和长正文续页中都能辨认问题、回答及当前段落。读取行动的回忆应说明当时读了什么、实际执行到哪里；需要资源内容时，再使用该资源的读取入口。

维护者已确认并授权实施：通过 input_id 取得输入事实，只用于统一读取投影，不删除 Trace 正文；Inspect 回忆围绕读取目标、意图和有限反馈，不要求恢复旧页面、完整子项列表或旧续页链；活动 Trace `#action/N` 保留现有行为。前置文档修复已完成：`docs/design/context.md` 移除过时的 Session v10 表述，改为“持久业务记录”，版本协议继续由 Session 代码维护。

保留路线 A、U0、日期/日内序号、request/Turn 分工、唯一输入和 Action 事实。问答仍是结构化 core.ask，details 与 question 组成完整 text；选项、comment、自由回答和等待生命周期保持现有语义。Workspace 全文流式化继续暂缓。

不新增 typed related/source 关系、通用引用网关、问答持久副本、旧正文库、分页令牌保管服务或跨日模型读取能力。固定包装继续放在相应 owner 的 prompts；模型无需学习新的回复或引用协议。

## 2. 实施前事实与复核证据

### 2.1 用户事实、Trace 叙事和 Session 叙事

输入事实和模型叙事不是同一份字段：

- Inbox 接受 choice answer 后，通过 `QuestionContent.answer_text()` 生成包含选项标签/id、选项说明和 comment 的输入 text；typed answer 保存 option_id/comment，reply_to 关联问题。自由回答保存用户文本。输入事实不复制 Agent 的提问正文。
- `TurnTraceHeap.append_input()` 在可见边界从问题事实调用 `reply_narrative()`。Trace reply 正文已经包含关联问题的完整 details + question、所选项标签和说明、comment；自由回答也关联完整问题。reply 正文不会再次列出全部未选选项。
- ask 的唯一 ActionResult Entry 保存可读问题正文、完整有序选项与回答方式。初始 input、append、reply 使用独立 INPUT Entry；正常热区展示不由 Inspect 分页驱动。
- `project_interactions()` 与 Session Background 组合按 Turn 分隔的顺序历史：input/append、ask 正文和完整选项、reply、其它行动及正式回答。reply 同样重复关联问题正文、所选项说明和 comment，使单独阅读时可理解。重复发生在投影中，持久问题和输入事实仍各存一处。
- Session Background 的容量折叠与 Inspect 分页是不同操作。当前问答不能以普通 text 截短规则留下孤立选择；本计划不把线性历史改成每个 reply 单独的底层模型消息。

代码落点：`kernel/loop/interaction/inbox.py::reply`、`kernel/interaction.py`、`kernel/context/builtin/trace.py::append_input`、`plugins/session/views/interaction.py`、`plugins/session/views/background.py`。

### 2.2 长 reply 的读取入口不一致

| 入口 | 当前投影 | 缺口 |
| --- | --- | --- |
| 当前 Trace `#input/N` | 从 typed question 构造回复标题和完整 narrative | 已保留核心问题和回答线索，但没有统一的 reply 分段信息 |
| Trace `#entry/N` | 读取 Entry 正文；标题取 kind 与正文开头 clue | 较长 details 会占满标题；续页进入 comment 后看不到核心问题和已选项 |
| 活动 Session evidence | 生成完整 narrative，没有专门回复标题 | 标题退化为 session_input，续页缺少问题定位 |
| 历史 Session input/interaction | 用问题事实补全标题和 narrative | 标题基本正确，仍需与其它入口共用回复分段语义 |

当前 `fact_unit()` 只为 ask 构建 sections；reply 以整段 narrative 进入公共分页。`DisclosureSlice` 按正文偏移选段并重复标题，因此正文完整存在并不保证每一页都有最小解释。

只读复现：在 2,048 字符页预算下，同一条包含较长提问说明、choice 和长 comment 的回复，第 4 页经 `#input/1` 仍能看到问题及选择；经对应 `#entry/3` 只剩说明开头生成的标题和 comment 正文片段；活动 Session evidence 标题为 session_input。未发现原始问答事实丢失。

### 2.3 Inspect 记录的当前边界

`InspectPage` 从同一次页面选择生成真实返回页和 canonical 读取事实。后者保存目标、标题、view/query、逐项 ref/title、最多 160 字符的实际片段线索、覆盖及 has_more。它保存了短摘录，但没有保存完整返回页或独立旧正文版本。

条目数量受实际页面预算约束，单项线索也有长度限制；Trace Heap 和 Session 另有外层容量管理。因此问题不是已经证明的无界增长或存储错误。一次目录页复现中，8,000 字符页预算返回 36 项，模型页 4,391 字符，回忆文字 3,474 字符；这说明进一步缩减有限，不单凭压缩比例判定错误。

明确缺口在 Session 再次缩减：`_compact_turn()` 将格式化后的 request/result 直接取前 400 字符，可能切断解释或引用，并丢失总体覆盖和后续状态。已有 Action/Turn 入口仍在，故这是可读性与缩减语义问题，不是持久事实被删除。

## 3. 方案 A：统一 reply 的语义投影与分页定位

### 3.1 共用语义来源

以 `QuestionContent + QuestionAnswer` 为已校验来源，补齐同一套回复标题、完整正文及分段表达：

- 标题包含核心问题短定位与回答线索；choice 从 typed option 取得标签，text answer 使用真实回答摘录。
- 正文继续包含完整 details + question、用户选择或自由回答、所选项说明和 comment。
- 分段区分关联提问、选择及选项说明、用户补充或自由回答。优先演进现有 narrative_parts/DisclosureUnit.sections，不增加业务状态机或专用分页服务。
- 部分项的页面包装重复问题定位和当前段落身份；包装不计入原正文覆盖范围，但计入页面预算。完整 item 的正文只呈现一次。

固定文案由 `prompts/kernel/interaction.py` 等所属 owner 的纯文本函数提供。业务 owner 负责问题关联、标题依据、正文顺序、ref、分段偏移和预算。

### 3.2 各入口的装配

- Context 当前 input occurrence 和 Trace Entry 读取使用同一投影。Entry 已有 input_id；由 Context 内部的只读输入访问取得对应 typed input，再通过 reply_to 取得问题事实，不从已渲染文字反解析选择或问题。
- Inputs 继续拥有接受的输入，Trace 不另存输入事实表。若 Trace 披露路径需要只读访问，沿 Context 现有装配显式提供窄访问方式；不绕过 owner、不建立全局查询 registry。
- Session completed record 和活动 evidence 从各自已有事实取得问题/回复，复用同一投影能力。规范的原 text、answer、reply_to、ref 继续保留。
- Inspect、query 和 Search 候选的回复标题/线索保持一致，检查目录提示是否仍只截取冗长说明开头。各入口保留自己的精确 ref，不建立 entry/input 别名。

### 3.3 预期行为

无需分页时：原本已经可见的完整提问、选择、说明和 comment 继续显示；改善标题及读取入口一致性，不新增第二条 ask，也不把用户回答改写成 Agent 提问事实。

发生分页时：长说明、长选项描述、长 comment 或自由回答均可继续按正文范围分页。即使单独读后页，也能辨认这是对哪个问题的哪种回复、当前处于哪个段落。长页不会只剩没有问题定位的 comment。

Session 正常线性历史仍以 Turn 为单位保留完整顺序；本次分页改动主要作用于按 ref 读取的页面，不把后台容量折叠、交互分页和主循环消息装配混成一个机制。

## 4. 方案 B：读取行动的有限回忆与语义缩减

### 4.1 读取事实与资源正文分开

维护者本轮进一步强调：回忆一个已折叠的读取行动，需要知道“之前看了哪本书、做了什么读取”；需要书的内容时重新读取该书。不应为了回忆行动而要求另一个 Inspect 恢复上次 Inspect 的返回正文。

本计划据此限定目标：

1. 本次实际读取页仍作为真实 ActionResult 进入模型，遵守既有展示保护。
2. 折叠回忆以原行动请求/意图为主，保留有解释的资源 ref；必要时补充执行状态、实际读取范围、数量、是否还有后续或局部失败，避免把请求范围冒充实际已读范围。
3. 查看历史读取行动，是查看其已保存的读取事实，不以恢复原页正文、逐项重放结果或继续旧分页链为验收要求。
4. 再次读取资源沿 owner 的现态语义；标准 ask/reply 和其它要求保存完整结果的行动继续按自身契约保留事实，不套用读取行动的舍弃语义。

### 4.2 当前已经存在的三个读取目标

| 目标 | 当前代码实际返回 | 本轮讨论中的含义 |
| --- | --- | --- |
| Trace `#entry/N`，对应 foldable Inspect | canonical message，即有限读取事实；热区首次可见时另有真实页面 overlay | 适合回忆此前做了什么 |
| Session `#action/N`，对应已完成 foldable Inspect | request、状态和 canonical_payload | 不承诺恢复未保存的正文 |
| 活动 Trace `#action/N` | 当前运行中仍保存的实际 ActionResult；折叠 overlay 后这条读取路径仍存在 | 这是既有能力，不能描述为已经只返回输入，也不是本计划新增的回忆能力 |

最后一项已明确保留。原 Action 的结果保留策略与本次 Inspect 的 foldable 投影分开，不新增由显示折叠触发的结果释放状态机。

### 4.3 “父引用”的准确范围

在本计划中优先使用“原读取入口”或“已有集合入口”。目录 `workspace:docs` 相对于所列文件可以叫父引用，Session Turn 相对于交互也有已有集合关系。读取一个文档片段或单条回复时继续使用该精确 ref，无须寻找上一级。

不通过删路径、剥离 fragment 或猜关联推算父引用。Trace Heap 已有节点组织，与 Inspect 的目标 ref 是两种不同情景，不新建公共 parent_ref 协议。

来源入口用于再次读取 owner 当前内容；行动位置用于回忆读取事实。两者都遵守原有生命周期，不因保存了入口就承诺旧页可恢复。

### 4.4 已确认方案与实际预算

确定应改进的是读取事实的模型显示缩减：按完整语义单元保留目标解释、精确 ref、必要实际覆盖和后续状态；替代 Session 对 Inspect 结果字符串的直接截断。进一步放不下时，交给已有 Action/Turn/Trace 的外层折叠。

最低回忆契约已确认为“当时读了什么、实际读到哪里”，不要求保留完整旧子项列表。共享 InspectPage 的 canonical 投影采用 1,200 字符整体目标预算，同时衡量 JSON 和回忆文字；保留目标 ref/title、view/query、真实返回项数 item_count、部分项数 partial_count、has_more，以及能容纳的完整条目说明/覆盖。coverage 不再保证枚举每一个返回项；模型文字明确说明省略数量，并指向原读取入口。

缩减以条目为单位，优先保留短线索，空间不足时可去掉摘录，但标题、精确 ref 和实际范围作为一组保留或省略。唯一正文项的实际范围属于最低事实，必须保留。目标、意图和最低事实不做字符串截断；最低事实本身超过目标预算时，由现有外层容量机制折叠，不伪称硬字符上限。

Session 压力缩减复用同一个语义投影，目标预算为 400 字符，保持请求字段及实际反馈完整，只去掉不保证保留的 continuation。放不下时沿原有规则折叠整 Turn。普通业务 Action 的保留规则与活动 `#action/N` 的实际结果读取不变。

需要缩减多项说明时，少量保留项必须连同解释和完整 ref 一起显示；其余可以用本页项数、部分/完整覆盖及原读取入口说明。对于单个文件，保留具体实际范围，不能泛化为只有“读过某文件”。所有数量和覆盖来自实际页面，不由额外模型总结。

预算沿共享投影内部策略及 Session 显示消费者明确提供，不新增模型参数或预算服务。新增计数字段使已保存读取事实可解释省略范围，Session record schema 升为 12；不保留旧 canonical 格式兼容层。公开 Inspect 页面字段不变，历史 Action result 的消费说明同步至 Endpoint 文档。

## 5. 预计改动范围与实施顺序

| 范围 | 预计改动 |
| --- | --- |
| `kernel/interaction.py`、对应 prompts | 回复标题、完整正文和分段从 typed facts 共用生成 |
| `kernel/context/disclosure.py`、`engine.py`、`builtin/core.py`，必要的 Trace 装配 | input/entry 的同源投影与查询导航，保留既有 ref 和输入可见时机 |
| `plugins/session/views/navigation.py`、`interaction.py`、`inspection.py` | 活动 evidence、历史 input、整轮 interaction 的一致标题和分段 |
| `kernel/retrieval/disclosure.py`、对应 prompts、`plugins/session/views/background.py` | 已确认范围内的 Inspect 回忆与按完整语义缩减 |
| Inspect Action 消费者、Session completion | 核对两份结果的事实来源；只在选择调整 canonical 契约时修改必要消费者 |
| 文档与测试 | 同步 Context/Session/引用说明及本计划；如公开页面字段改变，同步 Endpoint 和实际前端消费者 |

第 6 节已确认；实施顺序为 reply 投影、读取回忆缩减、文档同步与验证。保持现有错误分层与取消/结束边界；本计划不设计新的恢复流程。

默认复用现有文件和披露结构。页面包装可能变化，但 question/details/options、typed answer、request/Turn 身份和引用格式不因这次改进重新迁移。若确认需要改变持久投影字段，先补齐明确契约，不保留语义模糊的兼容层。

## 6. 已确认决策

- [x] Reply：普通语境继续显示完整问答；统一披露投影并补强长正文续页定位，input_id 只在内部关联事实，模型直接读正文。
- [x] Inspect 回忆：围绕读取目标、意图和有限反馈，不要求恢复旧返回页、完整子项列表或旧续页链。
- [x] 活动 Action 入口：保留活动 Trace `#action/N` 的既有行为；Inspect 的可折叠结果与原 Action 的事实保留策略分开。

## 7. 验证与完成条件

- [x] 同一 choice reply 的当前 input、Trace Entry、活动 Session evidence、历史 input/整轮投影具有一致的问题与选择语义；自由回答验证对应路径。
- [x] 代表性长 details、选项描述、comment 的分页可还原完整正文；后页保留问题定位、当前段落及真实范围；必要包装计入预算，不重复计入正文。
- [x] 普通不分页的 Trace 和 Session 问答内容完整、顺序一致；持久输入只保存原有用户事实，ask 不新增重复 Entry。
- [x] 查询与目录线索能够辨认回复所对应的问题，不仅命中冗长说明开头。
- [x] Inspect 首次真实返回、展示保护、foldable canonical 保存保持已确认边界；不把未返回的请求范围标为已读。
- [x] 精简读取叙事不截断 ref 或单元语义；少项、多项、单个部分正文及 Session 再次缩减均保留正确的读取目标和反馈。
- [x] 查看已折叠读取行动只承诺所确认的读取事实；再次读取资源取得现态，不把旧正文重放列为成功条件。
- [x] 公共消费者、文档和持久字段若变化，逐项核对；不得通过放宽稳定契约断言换取测试通过。
- [x] 实施后运行聚焦测试、Fast、Full 和 typecheck；若改变前端公共契约，运行相应前端测试与构建。
- [x] 实现、文档和验证逐项完成后更新本计划、加入 done 标记并归档。

## 8. 当前进展

- [x] 结合三份归档计划重新核对相关实现，记录实际可见内容、分页差异和 Action 读取边界。
- [x] 完成前轮授权的 Context 设计文档版本残留修复，`git diff --check` 通过。
- [x] 建立本执行计划，明确当前方案与待确认项。
- [x] 实施业务修改：InteractionNarrative 复用完整正文及分段；Trace 通过已有 input_id 只读关联；活动/历史 Session 复用；Inspect 及 Session 压力缩减采用整体语义预算。

前次只读复核的测试仅是基线记录；本轮验证单独记录于收尾核对，不沿用基线结果宣告完成。

## 9. 实施核对与验证证据

| 目标 | 实际实现与核对 |
| --- | --- |
| 同源回复语境 | `QuestionContent.reply_projection` 生成 `InteractionNarrative`，`reply_narrative` 复用其完整正文；固定段落标签仍在 prompts。已有输入/问题事实、问答等待流程与 Trace 写入顺序不变。 |
| 当前 Trace 披露 | Context 给 TraceSegment 注入只读 input_id 投影访问；current input 与 Entry 的 Inspect 使用同一正文/分段。原 Entry 正文继续保存，不从字符串逆向解析问题，不新增事实表。 |
| Session 各读取路径 | completed record、active evidence、Turn interaction 从各自原事实调用同一回复投影；query/Search/目录标题也保留问题和回答线索。 |
| 语义分页 | `DisclosureUnit.sections` 继续记录真实正文偏移；部分页附当前段落标题，完整页保持完整交互标题。机器与模型页共同受预算约束，分页正文可无损拼回。 |
| Inspect 回忆与缩减 | `compact_recollection` 由公共 InspectPage 和 Session 压力缩减共同使用；实际页面保持原协议，canonical 计数覆盖全部实际返回项，详细 coverage 只保存预算内容。原目标及最低范围不截断。 |
| Action 边界 | 核对当前 `#action/N` 构造逻辑，仍使用原 ActionResult envelope/model_text；本次 Inspect 自己的 trace_projection 独立缩减。原展示保护、主循环消费标记与 completion 事实选择流程保持原设计。 |
| 持久与公开消费者 | Session record schema 12 对应新增读取计数契约；Context/Home/Memory/Workspace Inspect executor 沿共享 InspectPage 自动取得一致投影，completion 沿原 canonical 选择持久化。前端没有针对旧 canonical coverage 全量列表的专门消费者；无前端源码改动。 |
| 文档 | 同步 Context、Session、引用设计及 Endpoint inspection；AGENTS.md 已有对应 owner/投影规约，本次无需添加重复条款。 |

代表性目录核对：80 个候选子项、8,000 字符实际页预算，本次返回 19 项，模型页 3,713 字符；canonical JSON 1,137 字符、回忆文字 968 字符，保留 5 项详情，仍明确总数 19 和 has_more。Session 再次缩减为 352 字符、1 项详情，保持读取入口、总数与后续状态。这是具体样例，不是固定压缩率承诺。

新增回归覆盖：

- `tests/plugins/session/test_organize.py`：choice/free reply 经当前 input、Trace Entry、活动 evidence、历史 input 和整 Turn 五条真实路径读取；长说明、选项说明和回答/comment 的范围连续且可完整还原，各页标题包含核心问题及回答线索；原输入仍仅是用户事实。
- `tests/kernel/context/test_disclosure.py`：多项读取的整体预算及真实计数；单项部分正文的实际行/字符范围；最低事实超小预算时保持完整而不截断。
- `tests/plugins/session/test_session_engine.py`：经过实际 Background.fit 压力缩减的读取事实保留意图及计数，不生成半截 request/result；保存的 canonical 结果不被显示缩减改写。

验证记录：聚焦 Context 78 passed；聚焦 Session 56 passed；Fast 1264 passed / 30 deselected；Full 1269 passed / 25 deselected（含 wheel 安装及资源验收）；ty 通过；前端 90 个文件、806 项通过，构建通过。前端测试仍输出已有 jsdom/storage/act 提示，构建有既有 chunk 体积提示。最终差异、引用链接和实施条目核对通过，计划归档至 done。
