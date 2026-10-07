# Reply 分页语境与 Inspect 回忆投影改进执行计划

日期：2026-10-07

状态：`pending`（分析与方案讨论；已建立计划，业务代码尚未实施）

代码基线：`164e4ba refactor(context): unify semantic inspect pages and structured ask narratives`。

本计划承接以下三份计划的实施复核，记录新发现的投影缺口与本轮讨论，不改写归档记录的历史结论：

- [模型上下文叙事投影与引用语义统一执行计划](<done/20261006-done- 模型上下文叙事投影与引用语义统一执行计划.md>)。
- [引用体系梳理与统一执行计划](<done/20261006-done- 引用体系梳理与统一执行计划.md>)。
- [Context 叙事与 Inspect 披露收尾及问答卡片修正执行计划](<done/20261007-done- Context 叙事与 Inspect 披露收尾及问答卡片修正执行计划.md>)。

依据：[AGENTS.md](../../AGENTS.md)、[Context](../design/context.md)、[Session](../design/session.md)、[引用设计](../design/references.md)。

## 1. 目标与当前授权范围

保留现有事实 owner、Action 执行和折叠体系，让同一条回复在直接语境、独立读取、查询导航和长正文续页中都能辨认问题、回答及当前段落。读取行动的回忆应说明当时读了什么、实际执行到哪里；需要资源内容时，再使用该资源的读取入口。

维护者当前要求先建立新计划、说明现状和变化、继续讨论确认；本计划不表示已经授权实施下面的业务改动。前一轮明确授权的文档修复已完成：`docs/design/context.md` 移除过时的 Session v10 表述，改为“持久业务记录”，版本协议继续由 Session 代码维护。

保留路线 A、U0、日期/日内序号、request/Turn 分工、唯一输入和 Action 事实。问答仍是结构化 core.ask，details 与 question 组成完整 text；选项、comment、自由回答和等待生命周期保持现有语义。Workspace 全文流式化继续暂缓。

不新增 typed related/source 关系、通用引用网关、问答持久副本、旧正文库、分页令牌保管服务或跨日模型读取能力。固定包装继续放在相应 owner 的 prompts；模型无需学习新的回复或引用协议。

## 2. 当前事实与复核证据

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

最后一项此前已讨论并允许，本轮“无需恢复正文”是否还要求收窄这一既有入口，见第 6 节。未确认前不改变其行为，也不新增由显示折叠触发的结果释放状态机。

### 4.3 “父引用”的准确范围

在本计划中优先使用“原读取入口”或“已有集合入口”。目录 `workspace:docs` 相对于所列文件可以叫父引用，Session Turn 相对于交互也有已有集合关系。读取一个文档片段或单条回复时继续使用该精确 ref，无须寻找上一级。

不通过删路径、剥离 fragment 或猜关联推算父引用。Trace Heap 已有节点组织，与 Inspect 的目标 ref 是两种不同情景，不新建公共 parent_ref 协议。

来源入口用于再次读取 owner 当前内容；行动位置用于回忆读取事实。两者都遵守原有生命周期，不因保存了入口就承诺旧页可恢复。

### 4.4 当前候选方案与建议

确定应改进的是读取事实的模型显示缩减：按完整语义单元保留目标解释、精确 ref、必要实际覆盖和后续状态；替代 Session 对 Inspect 结果字符串的直接截断。进一步放不下时，交给已有 Action/Turn/Trace 的外层折叠。

上一轮建议暂时保留 canonical_payload 中已有的逐项覆盖，仅限制回忆文字。本轮继续区分两个选择：

- **显示缩减**：保留当前有界持久字段，改进 Trace canonical model_text 与 Session 的精简显示。保留这些字段不意味着新增“恢复原读取结果”的需求，也不要求模型把每个子项重新读一遍。
- **读取事实进一步收敛**：若维护者希望连逐项覆盖/短摘录也不作为回忆内容，canonical 只保留目标与请求语义、有限状态及足够解释实际读取的范围/数量等事实。这会调整读取行动的持久结果投影，应与消费者、文档和测试一起设计，不以拼接字符串截断代替。

本轮建议先明确最低回忆契约为“当时读了什么、实际读到哪里”，不将恢复正文或恢复全部子项列为需求。是否继续保留已有逐项 canonical 字段为实施前确认项；不单凭压缩比例增加有损存储变换。

需要缩减多项说明时，少量保留项必须连同解释和完整 ref 一起显示；其余可以用本页项数、部分/完整覆盖及原读取入口说明。对于单个文件，保留具体实际范围，不能泛化为只有“读过某文件”。所有数量和覆盖来自实际页面，不由额外模型总结。

预算由现有显示消费者明确提供或沿共享投影的内部策略确定；不新增模型需要设置的参数，不建立全局预算服务。具体阈值在确认事实保留范围后用代表性输出核对，不以固定若干条替代字符预算。

## 5. 预计改动范围与实施顺序

| 范围 | 预计改动 |
| --- | --- |
| `kernel/interaction.py`、对应 prompts | 回复标题、完整正文和分段从 typed facts 共用生成 |
| `kernel/context/disclosure.py`、`engine.py`、`builtin/core.py`，必要的 Trace 装配 | input/entry 的同源投影与查询导航，保留既有 ref 和输入可见时机 |
| `plugins/session/views/navigation.py`、`interaction.py`、`inspection.py` | 活动 evidence、历史 input、整轮 interaction 的一致标题和分段 |
| `kernel/retrieval/disclosure.py`、对应 prompts、`plugins/session/views/background.py` | 已确认范围内的 Inspect 回忆与按完整语义缩减 |
| Inspect Action 消费者、Session completion | 核对两份结果的事实来源；只在选择调整 canonical 契约时修改必要消费者 |
| 文档与测试 | 同步 Context/Session/引用说明及本计划；如公开页面字段改变，同步 Endpoint 和实际前端消费者 |

先完成第 6 节确认，再实施 reply 投影，随后实施读取回忆缩减，最后同步文档和验证。保持现有错误分层与取消/结束边界；本计划不设计新的恢复流程。

默认复用现有文件和披露结构。页面包装可能变化，但 question/details/options、typed answer、request/Turn 身份和引用格式不因这次改进重新迁移。若确认需要改变持久投影字段，先补齐明确契约，不保留语义模糊的兼容层。

## 6. 待确认点

- [ ] Reply：确认普通语境继续显示完整问答；仅统一披露投影并补强长正文续页定位，input_id 关联是内部取事实方式，不是让模型按 ID 拼装问题。
- [ ] Inspect 回忆：确认最低需要的是请求/目标解释与有限执行反馈，不要求再次 Inspect 恢复旧返回页；是否保留已有逐项 canonical 覆盖/短摘录，或收敛为读取意图及总体覆盖。
- [ ] 活动 Action 入口：本轮“无需恢复正文”是“不新增该要求”，还是同时要求活动 Trace `#action/N` 对 foldable Inspect 也只展示有限读取事实。前者沿既有能力；后者涉及当前 Action Inspect/Search 投影，应明确后实施，避免与之前允许读取运行中 ActionResult 的决定混淆。

未确认的事项不得写入设计文档作为已实现能力，也不得在编码时通过隐藏分支自行决定。

## 7. 验证与完成条件

- [ ] 同一 choice reply 的当前 input、Trace Entry、活动 Session evidence、历史 input/整轮投影具有一致的问题与选择语义；自由回答验证对应路径。
- [ ] 代表性长 details、选项描述、comment 的分页可还原完整正文；后页保留问题定位、当前段落及真实范围；必要包装计入预算，不重复计入正文。
- [ ] 普通不分页的 Trace 和 Session 问答内容完整、顺序一致；持久输入只保存原有用户事实，ask 不新增重复 Entry。
- [ ] 查询与目录线索能够辨认回复所对应的问题，不仅命中冗长说明开头。
- [ ] Inspect 首次真实返回、展示保护、foldable canonical 保存保持已确认边界；不把未返回的请求范围标为已读。
- [ ] 精简读取叙事不截断 ref 或单元语义；少项、多项、单个部分正文及 Session 再次缩减均保留正确的读取目标和反馈。
- [ ] 查看已折叠读取行动只承诺所确认的读取事实；再次读取资源取得现态，不把旧正文重放列为成功条件。
- [ ] 公共消费者、文档和持久字段若变化，逐项核对；不得通过放宽稳定契约断言换取测试通过。
- [ ] 实施后运行聚焦测试、Fast、Full 和 typecheck；若改变前端公共契约，运行相应前端测试与构建。
- [ ] 实现、文档和验证逐项完成后更新本计划、加入 done 标记并归档。

## 8. 当前进展

- [x] 结合三份归档计划重新核对相关实现，记录实际可见内容、分页差异和 Action 读取边界。
- [x] 完成前轮授权的 Context 设计文档版本残留修复，`git diff --check` 通过。
- [x] 建立本执行计划，明确当前方案与待确认项。
- [ ] 实施业务修改。

前次只读复核在代码基线执行过 Full（1265 passed / 25 deselected）、ty、前端测试（806 passed）及构建；它们是基线验证，不代表本计划尚未实施的改动已经通过验收。本次仅维护文档，进行差异与本地链接检查。
