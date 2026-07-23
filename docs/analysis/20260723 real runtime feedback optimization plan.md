# 真实运行反馈优化执行计划

状态：planned（核心语义已确认）

## 背景

真实运行记录 `reference/turn_6a56f14a.json` 与 `reference/turn_92b63b73.json` 表明，TinySoul 已能在一个 User Turn 内完成 Web 检索、Workspace 提交、局部失败恢复、最终回答和 Session 持久化，但“证据是否真正进入 action-internal LLM task”与“如何准确恢复此前 Turn 的 Action 状态”仍未形成完整闭环。

第一轮在 8 个 Cycle 中执行 19 次 Action call：8 次 `web.search_by_kimi` 全部成功，8 次 `web.fetch_with_defuddle` 中 4 次成功、4 次形成稳定 HTTP 局部失败，随后成功写入 14,393 bytes 的调研文档并完成 `core.answer`。其主要缺陷不是行动失败，而是 `workspace.write` 的 reasoning 表达了使用资料 Link 的意图，实际 ActionCall 却没有传递 `reference_links`；instruction 中出现的 `workspace:` 字符串不会被 Workspace prompt resolver 自动加载，因此已下载正文没有进入该次写作任务。

第二轮询问上一轮的工具调用、失败和资料读取情况。Agent 先用两次 `context.trace.inspect` 错误访问跨 Turn ref，随后使用 1 次 `session.history.inspect` 和 14 次 `session.history.recall` 分页恢复上一轮轨迹。分页停在 `next_cursor=24`，没有读取总计 27 项 trace 的尾部；第一次 `core.answer` 又因 output token 上限形成局部失败。最终回答把当前轮的 `workspace.read`、`core.answer` 失败和两次 `update_working` normalize 失败归到上一轮，并把 8 次 Web 搜索回答为 6 次。该结果说明持久事实仍在，但原始分页、Action call/result 配对和当前/历史 Turn provenance 不足以稳定支持精确回答。

## 现有设计事实

### Context 与 Session 所有权

Context 只拥有当前 User Turn。`TurnTraceHeap` 为每项 trace 区分 canonical `message` 与可选 `visible_overlay`；foldable 成功结果在当前 Turn 先展示完整 ToolResultMessage，显式 fold、容量回收和 Turn seal 后只保留 executor 提供的 compact canonical payload。failed/timeout 结果不能携带 trace projection，始终以模型可见、受边界约束的完整失败结果进入 canonical trace。

当前 Action model payload 固定有 status/stage/feedback/payload，但 `frame_data` 只进入 trace/diagnostic renderer，不会整体进入模型可见 ToolResult。Web 和 LLM action 等能力已把稳定原因放在 `payload.failure`，但部分 normalize/prepare/hook/runner 失败只在 `frame_data.reason` 中保留诊断；Session 不能假设所有旧 record 都有结构化 failure reason，也不能解析自然语言 feedback 猜测。

Turn 结束时，`ContextEngine.end_turn()` 生成不可变 `TurnSummary`，包含 canonical trace、trace heap headers、trace digest、Working、UserInputs 与 Background Links。`SessionEngine.record_turn()` 持久化不可变 `session:turn/<turn_id>` record，再派生下一 Turn 的有界 SessionBackground。visible overlay、MODEL Observation、provider 原始响应和未过滤异常都不进入 Session。

### SessionBackground 当前投影

每个近期 Turn 的 SessionBackground 固定包含 ask、最终 answer/references、exhausted 和 `trace_digest`。`trace_digest` 只提供 entry/cycle 数、trace kinds 和使用过的 action names。只有 `background_action_names` allowlist 中的 action 才额外配对 call/result 并携带状态；standard/development 默认最多投影三个 `core.reason`。

因此，下一 Turn 通常知道“此前使用过哪些 action”，但不知道所有 ActionCall 是否都得到了结果、每个 action 成功/失败/超时多少次，也不知道稳定失败原因。不能通过扩大 allowlist 把全部 action raw result 自动复制到 Background；这会挤占 Background、复制历史 payload，并与渐进恢复和未来 Session 语义导航相冲突。

### inspect 与 recall 当前能力

`session.history.inspect` 返回当前日 Manifest 头部、item ref/kind/char count 和 summary child refs，用于定位 `session:turn/...` 或 `session:summary/...`。它不读取具体 Turn trace，也不提供全 action 状态。

`session.history.recall` 读取一个不可变 record：summary record 返回 child refs；Turn record返回 background 和 canonical trace 分页。它是 foldable ActionResult，因此完整页只在当前 Turn visible overlay 中可见，compact canonical 只保留 origin ref、next cursor 和 folded 标记。当前实现会静默收紧 `max_chars`、允许首个原子 entry 突破限制，并在每个 Turn trace page 重复 background。

`context.trace.inspect/recall` 只导航当前 Turn 的 heap ref，不能读取 `session:turn/...`。改变 ref 拼写不能跨越 owner 边界。

### Control 与 Workspace

`update_working` 描述要求至少一个 operation，但 ToolSpec 允许空对象和全空数组，Context normalizer 才以 `empty_patch` 拒绝；这是模型输出协议与消费契约不一致，而不是 WorkingPatch 状态模型的问题。

Workspace LLM mutation 只有 typed `reference_links` 会解析证据。现有 `WorkspaceEditPrompt` 只保留 target digest，不携带实际 reference provenance；如果 Endpoint/UI 在 LLM 生成期间修改 reference，当前提交边界也不会校验该 read set。

## 后续架构意图：Session Turn 语义地图

后续应用集成可能在 SessionBackground 中建立以 `session:turn/...`、`session:summary/...` 为稳定符号的 Turn 间语义地图，用于表达主题、目标、结论、资源和 Turn 之间的逻辑关系。该地图负责“应该进入哪个 Turn”，而单 Turn Action 投影负责“该 Turn 内执行了哪些 action 以及结果如何”。二者共享同一个 Turn identity，但不得分别持久化一份 Action 事实。

本计划只通过稳定 ref、最小 `action_outcome_digest` 和明确的 history action 边界为未来语义地图保留接入点；不设计地图 schema、节点/边、不增加 LLM 后处理，也不把语义地图列为任何实施 Stage 或完成标准。

## 已确认设计语义

1. 不建立宽泛的全 Turn audit 或跨 Turn audit store；新增局部、只读、按需的 `session.history.actions`。
2. `session.history.actions` 必须完整扫描一个明确 `session:turn/...` 的 canonical trace，但只解释框架通用 ActionCall/ActionResult envelope，不解释 capability 业务 payload、Control Tool 或普通 Phase reasoning。
3. SessionBackground 为每个 Turn 增加最小 `action_outcome_digest`，只包含 call/result/success/failed/timeout/unmatched 数量与 pairing 完整性；不自动加入逐次结果或失败正文。
4. `session.history.inspect` 负责定位 ref；`session.history.actions` 负责 Action 状态配对、统计和 trace index；`session.history.recall` 负责 summary 导航和原始 canonical 内容恢复。三者不得互相复制职责。
5. recall `max_chars` 是 hard limit；oversized canonical entry 通过 entry 内 continuation 恢复，不再隐式突破。
6. 模型侧批量 `update_working` 拆为 `set_milestone`、`remove_milestone`、`set_todo`、`remove_todo` 四个单操作 Control Tools，不扩展公共 JSON Schema 子集。
7. Workspace LLM mutation 使用严格 read-set guard；reference digest 变化时与 target CAS 在同一个 Workspace-owned transaction 中拒绝提交，并返回 `reference_changed`。
8. MODEL 验收复用现有 `llm.model.request`，不新增平行 MessageStack 事件，不把 Observation 持久化。
9. Action 模块负责把通用 failed/timeout 的稳定 failure facts 投影进 canonical model payload；Session 只消费这一通用 envelope，不读取 Action runtime `frame_data` 或 capability 私有结构。

## inspect、actions 与 recall 的边界

| Action | 输入与作用域 | 返回 | 明确不负责 |
|---|---|---|---|
| `session.history.inspect` | 当前 active day，无目标 ref | 有界 history head、turn/summary refs、child refs，以及直接 Turn item 的最小 `action_outcome_digest` | 不加载 Turn trace；不配对 call/result；不递归 summary 图 |
| `session.history.actions` | 一个明确的 `session:turn/...` | 全 trace 的确定性 Action 聚合、失败分组、有界逐次明细、call/result trace index | 不接受 summary ref；不返回 raw arguments/result payload；不解释 Control/Phase/业务内容 |
| `session.history.recall` | 一个 `session:turn/...` 或 `session:summary/...` | summary child 导航，或带明确 trace index 的 canonical record page；支持精确单 entry 与 oversized continuation | 不统计 action；不判断 call/result 是否匹配；不生成失败原因概括 |
| `context.trace.inspect/recall` | 当前 Turn 的 `turn:trace@...` heap ref | 当前 Turn cold leaf 导航和 canonical recall | 不接受任何 Session ref；不建议通过改写 ref 越权读取历史 |

推荐协作顺序：

1. 当前 Background 已暴露目标 `session:turn/...` 时直接调用 `session.history.actions`；ref 未知或只看到 overflow head 时先 `session.history.inspect`。
2. 遇到 `session:summary/...` 时使用 `session.history.recall` 展开 child refs，直到定位具体 Turn；`actions` 不隐式递归多个 Turn。
3. 对 Action 数量、状态和失败原因，只以 `actions` 的全记录聚合和 `pairing_complete` 为依据，不连续 recall 全 trace 后由模型自行计数。
4. 需要核对某次调用的原始 arguments 或 canonical result 时，使用 `actions` 返回的 `call_trace_index`/`result_trace_index`，再以 `recall(cursor=<trace_index>, max_entries=1)` 精确读取。
5. 需要继续读取 oversized entry 时只回传后端给出的 entry continuation；不得自行猜测 offset，也不得在 `page_complete=false` 时声称已覆盖全部原始内容。

## 设计目标

1. 保持 Context 当前 Turn、Session 跨 Turn immutable history 的既有所有权。
2. 用一个 Session-internal typed projector 同时派生最小 Background digest、inspect 提示、allowlisted action preview 和按需 Action View，避免重复解析。
3. 让模型在无需召回全部 raw trace 的前提下准确回答某个 Turn 的 Action 调用、成功、失败、超时和稳定失败原因。
4. 让 inspect/actions 交付的 ref 与 trace index 能把 recall 收敛到一个明确 record/entry。
5. 对齐 Context/Session recall 的容量、coverage、continuation 和失败反馈语义。
6. 让 Workspace 成功结果证明 action-internal LLM task 实际读取的 target/reference 版本，并阻止 stale read set 提交。
7. 消除 Working Control ToolSpec 与 normalizer 的正常输入契约差异。
8. 通过 package-owned Session Domain HOW、Catalog semantic 和测试把正确选择、分页、恢复规则交付给模型和维护者。

## 非目标

- 不实施 Session Turn 语义地图或自动语义摘要。
- 不增加 Turn 结束时的 LLM audit/action analysis；Action 状态投影必须确定性派生。
- 不建立新的 audit record、索引文件、跨 Turn缓存或第二事实源。
- 不把全部 action raw result、失败正文或完整 Action View自动放入 SessionBackground。
- 不让 Session 解释 Web、Workspace、Script 等 capability payload 的业务含义。
- 不让 Context 读取 Session store，也不把 Session ref 伪装成 Context heap ref。
- 不改变 foldable 的 full visible overlay / compact canonical 生命周期。
- 不增加剩余 Cycle 提示、终局 Cycle 预留或另一套 Loop 状态机。
- 不从 instruction 内的 `workspace:` 文本猜测 `reference_links`。
- 不为了单个 Control Tool 引入跨 Action/LLM/Context/provider 的公共 Schema 重构。

## Stage 1：建立 Session TurnActionProjector

状态：planned

在 Session 内新增只解释通用 trace envelope 的 typed `TurnActionProjector`。输入是一个已校验 Turn record 中的 immutable canonical trace，输出一次确定性投影；不读取 Session store 路径、不调用 LLM、不接触 capability executor。

投影至少维护：

- call id、action name、call trace index、cycle id、phase；
- 配对 result 的 result trace index、status、stage；
- 通用失败 envelope 中 allowlist 后的 `reason`、`disposition` 和有界 feedback；
- unmatched call/result；
- 全 trace call/result/success/failed/timeout/unmatched counts；
- 按 action name 的状态计数；
- 按 action/reason/stage/disposition 的确定性失败分组。

Projector 不返回 raw arguments 或 result payload；只记录 canonical digest/trace index，精确内容由 recall 恢复。它只读取 Action-owned canonical `failure` envelope；旧 record 只有既有 `payload.failure` 时通过明确 legacy adapter 归一化，二者都缺失时使用显式 `unspecified`。不得从 feedback 文本、`error_type` 或 capability 私有 JSON 猜测原因。扫描完成与 call/result 完整配对分别表达为 `scan_complete` 和 `pairing_complete`。

在 Action feedback renderer 边界增加通用 canonical failure facts 投影，只作用于 failed/timeout：

- 优先采用 executor 已提供的 `payload.failure` 中 allowlist 后的 reason/scope/constraint/disposition；
- 缺少显式 failure 时，只从 Action-owned `frame_data` allowlist 提取 reason/scope/constraint/disposition；
- 仍缺少 reason 时使用稳定的 `action_failed` 或 `action_timeout`，不暴露原始异常；
- 以统一顶层 `failure` 提供给模型和 canonical ToolResult，原业务 payload 继续保留但不成为 Session 的解析入口；
- `frame_data` 仍是诊断载荷，不整体公开给模型，不因本计划变成持久业务协议。

该投影属于 ActionResult 通用反馈语义，覆盖 normalize、prepare、hook、schedule、execute 和 timeout；Session 不复制这些 stage 的构造规则。旧 Session record 继续可读，只是缺失稳定原因时得到 `unspecified`。

现有 `_project_action_history` 的配对逻辑迁入该 projector：

- `SessionEngine.record_turn()` 从同一投影生成 Background allowlist action previews；
- 新增最小 `action_outcome_digest`，字段固定为 call/result/success/failed/timeout/unmatched counts 与 `pairing_complete`；
- `session.history.inspect` 对直接 Turn item返回同一个 digest，不重新扫描或另写解释逻辑；
- summary background 不合并子 Turn 的 action counts，只保留 child refs；进入具体 Turn 后再查询。

`action_outcome_digest` 是 Background 的有界派生视图，不是独立持久事实；canonical Turn trace 始终是权威来源。reconcile 从 record 重建 item 时必须得到相同 digest。

## Stage 2：新增 `session.history.actions`

状态：planned

新增 Catalog action、native executor 和 `SessionEngine` 只读门面。输入：

- 必填 `ref`，且只允许 `session:turn/...`；
- 可选非负 `cursor`，表示逐次 Action detail index；
- 可选正整数 `max_items`，由 Session hard limit 收紧并在响应中报告 requested/effective value。

成功输出分为：

- source：ref、source turn id、record kind、trace digest 和 trace entry count；
- summary：全记录 action/status counts、by-action counts、failure groups、unmatched facts、`scan_complete` 和 `pairing_complete`；
- details page：action/call id、cycle/phase、call/result trace index、status/stage、稳定 failure facts、cursor/next cursor/coverage/remaining 和 `page_complete`。

summary 始终覆盖整个目标 Turn，不受 details cursor 影响。details 分页不能改变 summary；调用方无需把所有 details 页读完才能使用精确聚合，但在声称“每一次明细”时必须要求 `page_complete=true`。

该 action 使用 foldable trace 生命周期：完整 details page 是当前 Turn visible overlay；compact canonical 至少保留 source ref/turn、trace digest、完整 summary、details coverage、continuation cursor 和 folded 标记。这样 overlay 被回收后仍保留已确认统计，又不把此前 Turn 的逐次明细递归复制到新 Session record。

`session.history.actions` 不接受 summary ref。错误 kind 返回 `wrong_record_kind` 和 `disposition=change_request`，提示先通过 inspect/summary recall 定位具体 Turn，但不自动递归或替用户选择多个 Turn。

## Stage 3：对齐并强化 recall

状态：planned

Context 与 Session recall 保持各自 owner/ref 空间，但采用一致分页事实：

- `requested_max_chars`、`effective_max_chars`、`actual_body_chars`；
- 可选 `requested_max_entries`/`effective_max_entries`；
- `cursor`、`cursor_unit`、可选 `entry_offset`、`next_cursor` 和 `next_entry_offset`；
- coverage 起止、total/remaining entry count、`page_complete` 和 `truncated`；
- source owner、source turn id 和每项显式 `trace_index`；
- Session Turn background 只在首页返回，后续页返回稳定 ref/digest 与 `background_omitted=true`。

`max_chars` 只约束 recall body canonical JSON 字符，不包含 Action 通用 envelope 和固定分页 metadata；配置上限是 hard limit。`max_entries` 是额外的 per-request entry count ceiling；`actions` 返回的 trace index 配合 `max_entries=1` 可以精确读取一次 call 或 result。

普通 entry 整项返回。单项超过 hard limit 时返回稳定 descriptor 与 canonical JSON `entry_chunk`；`cursor` 在该 entry 完成前不前进，调用方只回传 `next_entry_offset` 和 `entry_digest`。offset 是后端 continuation 值，客户端不得自行计算。完整分片拼接后可以通过 digest 校验原始 canonical JSON。

summary ref 的 recall 只导航 child refs/有界 child headers，并显式使用 `cursor_unit=summary_child`；Turn ref 使用 `cursor_unit=trace_entry`。两者共享分页值对象，但不伪装成相同业务内容。summary/Turn 的任何可变长度 body 若超限都必须服从同一 hard limit，不保留“首项例外”。

不完整分页是成功结果，返回 continuation；只有无效请求或 owner/record 失败才形成 failed ActionResult。Session/Context action executor 将稳定恢复事实放入模型可见 `payload`，并将必要诊断放入有界 `frame_data`，不再只返回拼接异常文本。至少覆盖：

- `wrong_owner_ref`；
- `wrong_record_kind`；
- `unknown_record`；
- `invalid_cursor` / `cursor_out_of_range`；
- `invalid_entry_offset` / `entry_offset_out_of_range`；
- `entry_digest_mismatch`。

失败 payload 使用 `reason`、`scope`、`constraint`、`disposition` 和安全的 cursor/ref facts。不得暴露 store path、原始异常或未过滤 record 内容。`requested_max_chars` 超过配置上限不是失败，响应必须如实报告 effective limit；相同 reason 的原样重试不允许超过既有一次恢复约束。

## Stage 4：补充 Session Domain HOW 与 Catalog 语义

状态：planned

在唯一 init 模板源 `tinysoul/assets/project/home/` 新增 `how_domain/session/DOMAIN.md`。

Domain HOW 在 Phase2 自动注入，是三个 native Session action 协作策略的模型可见权威说明，必须明确：

- 当前 Turn detail 使用 Context，prior Turn 使用 Session；
- ref 未知时 inspect，已知具体 Turn 且询问 Action 状态时 actions，需要 summary child 或 exact canonical entry 时 recall；
- 统计不得由多页 raw recall 手工推断；
- actions 的 trace index 配合 recall `max_entries=1`；
- `scan_complete`、`pairing_complete`、details `page_complete` 的不同含义；
- 按 failure disposition 改变请求，不改写 ref 或 offset 猜测 owner/continuation。

按照现有架构，Session actions 是 native backend，不创建 action-internal LLM task，因此不在 package template 中为 `history.inspect`、`history.actions` 或 `history.recall` 提供 Action HOW 正文文件。`how_action` 只属于确实存在 action-internal LLM Task 的 Phase3 action；不能把它当成通用 action 文档或第二套 Phase2 提示。Home 仍可按 Catalog 维护这些 action 的逻辑 mount identity；空逻辑 identity 不等于存在 HOW 内容，也不会被 native action 加载或注入。每个 Session action 的模型可见输入、输出、完整性和恢复约束必须写入 Catalog description/schema/semantic，跨 action 协作只写在 Session Domain HOW。

Catalog 对齐：

- inspect `use_when`：缺少具体 prior Turn ref或需要展开 history head；
- actions `use_when`：已有具体 Turn ref并需要 Action counts/status/failure；
- recall `use_when`：需要 summary child 或 actions 指向的 exact canonical detail；
- 三者的 `avoid_when` 明确排除彼此职责和 current-Turn Context ref；
- schema 增加 actions cursor/max_items，以及 recall max_entries/entry continuation；
- actions/recall 保持 foldable，inspect 保持 standard read-only。

补充 wheel/package-data/init tests，证明 Session Domain HOW 只在共享 package template Home 中维护，并被 standard/development 初始化共同复制；同时断言 package/init 不为三个 native Session action 提供 Action HOW 正文文件，执行期间也不加载或注入 Action HOW。不得在仓库根重建 Home 镜像。

## Stage 5：闭合 Workspace 来源与并发协议

状态：planned

- 在 package-owned Workspace domain HOW 与 `workspace.write`/`workspace.rewrite` Catalog/Action HOW 中明确：instruction 中出现的 Link 只是文本；生成依赖的每个 Workspace 证据必须出现在 `reference_links`。
- 引入 Workspace-owned typed prompt source/provenance value。resolver 在读取 text/image 并构造 PromptBlock 的同一步返回 `{link, digest, size, kind}`；`WorkspaceEditPrompt` 分别持有可选 mutation 前 `target_input` 与 `references`，避免 prompt 与 provenance 分别读取。
- Workspace mutation 成功 metadata 返回可选 `target_input`、`reference_count` 与实际 `references`；digest 必须来自 prompt build，不能在 LLM 完成或提交后重新 inspect。
- Workspace commit API 在同一 transaction/lock 内校验 target CAS 与全部 reference read set。任一 reference 被修改、删除或替换时不提交文本、不发布成功 `workspace.changed`，返回 `reason=reference_changed`、`disposition=change_request` 和有界 `{link, expected_digest, actual_digest/state}`。
- 失败后丢弃未提交生成文本；下一次调用重新解析 references。不得只重放同一个 stale prompt 或把旧 digest覆盖为当前状态。
- provenance 只包含元数据，不把正文、图片字节或 prompt block 放入 ActionResult。
- 增加并发 E2E：LLM task 期间通过 Endpoint/UI 修改 reference，验证 read-set guard 无 TOCTOU；仅 instruction 提及 Link 时仍不得加载正文。

## Stage 6：拆分 Working Control Tools

状态：planned

用四个模型侧 Control identity 替换批量 `update_working`：

- `set_milestone(key, content)`；
- `remove_milestone(key)`；
- `set_todo(key, content, status)`；
- `remove_todo(key)`。

每个 ToolSpec 只使用现有 JSON Schema 子集表达必填字段。normalizer 校验类型和非空字符串，每个有效 ToolCall 确定性生成一个非空 `WorkingPatch` signal；同一 Phase1 可以返回多个 calls，继续按 ToolCall sequence 在 projected Working 上校验，并由同一 signal batch 原子提交。

不改变现有 WorkingPatch sequence 语义：后续 set 可以覆盖前序 set，非法 remove 形成局部 consume failure，全部可行 patch 在准备后一次提交。删除旧模型侧 `update_working`，不保留 alias；同步更新 Loop prompts、Context controls/tests、package-owned core AGENT/HOW、项目 `AGENT.md` 和设计文档。不要把这次局部协议修复扩展为公共 Action/Control Schema 重构。

## Stage 7：回答、Observation 与验收

状态：planned

- 对某 Turn 的 Action 统计，以当前 TurnTrace 中最近一次、目标 ref/trace digest 匹配且 `scan_complete=true` 的 `session.history.actions` ActionResult 为权威来源；配对声明还要求 `pairing_complete=true`。
- `core.answer` 不增加 Action summary 专用 input 参数或 payload 副本；ActionResult 通过既有 Context MessageStack 构造自然进入后续 LLM Task。
- 保留 `core.answer` output limit 的局部 `change_request` 恢复；缩小输出不得改变已确认统计。
- 通过 Endpoint MODEL route 捕获现有 `llm.model.request`，按 task identity/attempt 检查 provider-neutral MessageStack，并核对 phase、action call/result 与 observation sequence。
- Observation 只用于运行期可观测性和前端展示，不写入 Session、Workspace、Home、Memory 或前端持久缓存。

单元与集成测试至少覆盖：

1. projector 对 `turn_6a56f14a` 稳定得到 19 calls、15 success、4 failed、0 timeout，并按 action 统计 8 次 search、8 次 fetch、4 次 fetch failure；
2. projector 不把 Control Tool 或普通 Phase note 当作 ActionCall，并显式报告 unmatched call/result；
3. Action renderer 为 generic failed/timeout 生成受控 canonical `failure`，不泄漏完整 frame_data；旧 record 缺少结构化原因时 projector 返回 `unspecified`；
4. Background 与 inspect 使用同一个最小 `action_outcome_digest`，allowlisted preview 继续有界，summary node 不合并子 Turn counts；
5. `session.history.actions` summary 覆盖整个 Turn且不受 details cursor 影响，failure groups 只使用稳定通用 facts；
6. actions 返回的 call/result trace index 与 recall `cursor + max_entries=1` 精确对应同一 canonical entry；
7. inspect -> summary recall -> actions 的 ref 导航闭环，不允许 actions 接受 summary/Context ref；
8. recall 对 hard limit、requested/effective limit、Unicode oversized entry、多 chunk digest、首页/后续页、summary child、最后一页和全部稳定 failure reason 返回一致事实；
9. foldable actions/recall 在当前 Turn 渲染 full overlay，seal 后只持久化 compact canonical；failed/timeout 结果不折叠；
10. Session Domain HOW 实际进入 Phase2 `llm.model.request`，Catalog semantics 足以选择三个 native actions；package/init 不提供其 Action HOW 正文文件，执行期间也不加载或注入 Action HOW；
11. Workspace write/rewrite 只加载显式 references，成功结果报告 prompt-build provenance，reference 并发变化时原子拒绝提交；
12. 四个 Working Control Tools 排除空批次，多个 signals 继续按 projected sequence 原子消费；
13. 对 `turn_92b63b73` 不把当前 Turn 的 read、answer failure 和 Control failure 归到目标 prior Turn；
14. fake-provider App E2E 在不超过 5 个有效 Cycle 内准确回答“上一轮调用、失败和读取来源”，并以唯一成功 `core.answer` 结束；
15. replay fixture 同时检查最终答案、Session record 与 `llm.model.request`；显式 opt-in 的真实 provider smoke 检查相同契约，但不作为离线测试和 wheel 验收的网络前置条件。

完成实现后运行完整 pytest、静态类型检查、wheel 构建与隔离初始化验证。只有 Endpoint 事件契约或 visualization 消费代码实际变化时才要求 TypeScript/Vite 构建；消费既有 `llm.model.request` 不制造无关前端改动。

## 完成标准

- 下一 Turn 能从最小 digest 判断 prior Turn 是否存在 Action 失败，而无需自动加载全部 action result；
- Agent 能通过 `session.history.actions` 准确回答一个具体 Turn 的 Action 调用、成功、失败、超时和稳定失败分组；
- inspect、actions、recall 和 Context trace 的 owner、ref、统计、raw recovery 边界清晰，actions 提供的 trace index 能驱动精确单 entry recall；
- recall 对预算、coverage、oversized continuation 和失败 feedback 使用真实、稳定、可恢复的协议；
- Session Domain HOW/Catalog 把正确 action 选择和恢复方式交付给模型；不为无内部 LLM Task 的 native action 提供或加载 Action HOW 正文，同时不改变 Catalog-derived logical mount identity 的统一生命周期；
- Workspace mutation 成功能证明实际读取的 target/reference 版本，stale reference 不能通过提交边界；
- Working Control Tool 与 normalizer 对有效操作使用同一契约；
- 两份真实运行记录对应的问题能在不增加全量 Background、LLM Turn audit、语义地图实现、Cycle 预算机制或第二套状态机的前提下稳定正确回答。

全部验收完成后更新项目 `AGENT.md` 进度与 Session/Context/Action/Workspace/Agent Home 设计文档，并将本计划标记为 done。
