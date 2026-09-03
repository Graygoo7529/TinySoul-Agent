# Real Runtime Feedback Optimization Plan

状态：done

日期：2026-07-23

## 事实基线

本计划来自两份真实 Turn record 的确定性复盘。

`reference/turn_6a56f14a.json` 包含 27 条 trace、8 个 Cycle、19 次 Action call：8 次 `web.search` 成功，8 次 `web.fetch` 中 4 次成功、4 次 HTTP 失败，`workspace.scan`、`workspace.write`、`core.answer` 各成功 1 次，总计 15 success、4 failed、0 timeout。Phase2 在调用 `workspace.write` 前明确计划传入 `reference_links`，但实际参数没有该字段；最终文档仍生成成功，因此结果无法证明 action-internal LLM task 实际读取了哪些 Workspace 来源。

`reference/turn_92b63b73.json` 包含 42 条 trace、19 个 Cycle。Agent 两次错误地用 `context.trace.inspect` 访问 prior Session ref，随后执行 1 次 `session.history.inspect` 和 14 次 `session.history.recall`，分页停在 `next_cursor=24`，未读取 27 条 prior trace 的尾部。第一次 `core.answer` 因输出限制失败，两次空 `update_working` 被 Context 拒绝，第二次 `core.answer` 成功。关键事实是：调用 `core.answer` 前的 Phase2 reasoning 已正确识别 8 次搜索、4 次 fetch 失败以及当前 Turn 的 `workspace.read`，但 action-internal answer LLM 又将搜索改写成 6 次，并把当前 Turn 的 read、answer/control failure 归入 prior Turn。

已确认的问题：

1. Session 只有有界 action preview 和 raw recall，没有对 immutable canonical trace 的完整 Action 状态投影。
2. `ActionResult` 没有一等失败字段；Web/LLM 用 `payload.failure` 绕过 renderer，其他失败只在 `frame_data` 中，失败协议不一致。
3. foldable canonical result 当前直接使用业务 `compact_payload` 构造 ToolResult，丢失 `action/status/stage/failure` 通用包络。
4. 当前 `trace_digest` 是计数摘要，不是内容 digest，不能用于来源绑定或 continuation 校验。
5. Session recall 允许首项突破 `max_chars`，缺少 hard limit、entry coverage 和 oversized entry continuation。
6. Workspace edit prompt 与 provenance 分别读取，提交只校验 target digest，不校验 reference read set，也不能表达“target 必须仍不存在”。
7. `update_working` ToolSpec 允许空对象，但 normalizer 拒绝空 patch，模型协议与消费契约不同。
8. 仅让结构化 ActionResult 自然进入 `core.answer` MessageStack，不能保证内部 LLM 保持精确事实和 Turn provenance。

## 已确认设计

### 模块语义

- Action 拥有 Action call/phase 的局部结果、失败事实和结果渲染协议。
- Context 拥有当前 Turn、visible overlay 和 canonical TurnTrace，不解释 Action 业务 payload。
- Session 保存 immutable cross-Turn record，并从 canonical trace 确定性派生 Action history；不解释 capability 私有 payload。
- Workspace 拥有 prompt source 读取、版本证明、read-set 校验和最终 mutation commit。
- Loop 只负责阶段编排和跨模块门面调用，不复制上述规则。

### 不兼容变更

项目仍处于开发阶段，本计划不读取、迁移或适配旧 Session record/result schema：

- 删除 `payload.failure` legacy adapter；
- failed/timeout canonical result 缺少 failure 时视为损坏记录；
- Session Turn record schema 直接升级，旧 record 明确拒绝；
- 删除旧 Control identity `update_working`，不保留 alias；
- 修改或删除建立在旧 payload、旧 digest、旧 record 或旧 tool schema 上的测试。

两份原始 runtime fixture 只作为问题证据，不作为 production schema 兼容输入。新的 projector/replay fixture 使用新 canonical contract。

## Stage 1：Action Local Failure 与 Result Rendering

状态：done

在 Action core 引入 frozen `ActionLocalFailure`：

- `reason`：owner-defined stable identifier；各 owner 使用自己的 `StrEnum` 维护；
- `scope`：失败所处的稳定业务/协议范围；
- `disposition`：Action-owned `ActionFailureDisposition`，固定为 `retry_same`、`change_request`、`use_fallback`、`stop`；
- `feedback`：给模型的有界解释文本；
- `constraint`：模型可见、JSON-safe、有界的恢复约束。

修改 `ActionResult`：

- 删除 `model_feedback`；
- 新增 `failure: ActionLocalFailure | None`；
- success 禁止 failure，failed/timeout 必须 failure；
- payload 只表示业务结果或真实的部分业务结果，不承载通用失败协议；
- frame_data 只表示 trace/Observation 诊断，不重复 reason/scope/disposition；
- failed/timeout 禁止 trace projection。

`ActionPhaseResult` 使用同一个 `ActionLocalFailure`。删除当前没有生产者的 phase success 状态和构造器，使 phase result 明确表示不能绑定到具体 Action call 的局部 Action 模块失败。

将 `ActionFeedbackRenderer` 重命名为 `ActionResultRenderer`。Renderer 是 Action 内部表示边界，不是事实来源：

1. model projection 包含 action/status/stage、可选 payload 和 canonical failure，不包含 frame_data；
2. trace projection 额外包含 result/call/invoke/batch/domain/sequence 和 frame_data；
3. ToolResultMessage 使用相同 model projection；
4. phase model/trace projection 使用相同 failure contract。

更新 normalize、prepare、hook、schedule、native、subprocess、LLM backend 以及所有 capability/module executor，使每条 failed/timeout 路径显式提供稳定 reason/scope/disposition。删除 Web/LLM 私有 disposition enum 和所有 `payload.failure`。

## Stage 2：Canonical ToolResult 与真实 Trace Digest

状态：done

保留现有 standard/foldable 生命周期，但修复 canonical 表示：

- `ActionTraceProjection.compact_payload` 更名为 `canonical_payload`，明确它只是 foldable 结果的业务 payload 投影；
- Action renderer 生成 frozen `RenderedActionResult`，包含 `visible_message`、`canonical_message` 和 `origin_refs`；
- standard 的 visible/canonical message 相同；
- foldable 的 canonical message 仍保留完整 `action/status/stage` envelope，只把 envelope 内的 payload 替换为 `canonical_payload`；
- failed/timeout 始终 standard，不折叠；
- Loop 将两条完整 Message 交给 Context，Context signal 不再接受 action-specific raw compact payload。

Context 继续只维护 generic Message/overlay，不解析 Action envelope。

重新定义 Turn trace identity：

- 当前计数对象更名为 `trace_summary`；
- `trace_digest` 是对 canonical trace JSON 的 SHA-256，格式固定；
- Session record 写入时重新计算并校验 digest；
- 单 entry continuation 使用同一 canonical serializer 计算 `entry_digest`；
- “digest”一词不再用于非哈希计数摘要。

## Stage 3：Session TurnActionProjector 与 `history.actions`

状态：done

新增 Session-owned typed projector。输入是已校验 Turn record 的 immutable canonical trace，输出 frozen Action history projection；不读取 store path、不调用 LLM、不接触 capability executor。

扫描规则：

- call 只来自 `kind=decision`、`phase=phase2`、assistant message 中 `tool_kind=action` 的 ToolCall；
- result 只来自 `kind=action_result`、`phase=phase3` 的 ToolResult；
- canonical Action envelope 由 Action-owned parser 校验；ToolResult outer status/tool name 必须与 inner envelope 一致；
- Control call、phase note、reasoning text 和 capability payload 均不参与投影。

配对规则：按 `call_id` 分组，只有恰好一个 call、一个 result 且 action name 一致时形成有效 pair。duplicate call、duplicate result、name mismatch、missing result、orphan result 全部确定性报告，不按字典覆盖，不按出现顺序猜配对。

投影至少包含：

- call/result trace index、call id、action name、cycle/phase、status/stage；
- failure reason/scope/disposition/constraint 和有界 feedback；
- 全 trace call/result/success/failed/timeout/unmatched counts；
- by-action 状态计数和 action/reason/stage/disposition failure groups；
- `scan_complete` 与 `pairing_complete`。

原计划的 `action_outcome_digest` 更名为 `action_outcome_summary`，只包含固定计数、异常计数和 pairing flag。它是 canonical trace 的有界派生视图，不是第二事实源。`record_turn`、Background、inspect 和 reconcile 必须复用同一 projector。

新增 `session.history.actions(ref, cursor?, max_items?)`：

- ref 只允许 `session:turn/...`；summary/Context ref 返回 typed local failure；
- summary 始终覆盖完整目标 Turn，不受 detail cursor 影响；
- details 按 Action occurrence index 分页并显式返回 coverage/remaining/page_complete；
- source 返回 ref、turn id、record kind、trace digest、trace entry count；
- foldable visible result包含完整 detail page，canonical result保留 source、完整 summary、coverage、continuation 和 folded 标记；
- projector 不返回 raw arguments 或 raw result payload，精确 entry 由 recall 按 trace index 恢复。

Session record schema 直接升级；生产代码不保留 v1/v2 adapter。

## Stage 4：Context/Session Hard Pager

状态：done

Context 与 Session 保持各自 owner/ref 语义，只共享 immutable JSON sequence 的字符预算和 oversized entry 分片算法，不共享 owner/store 导航逻辑。

统一分页事实：

- requested/effective max chars；
- requested/effective max entries；
- cursor、cursor unit、next cursor；
- coverage、total/remaining、page_complete、truncated；
- source owner、turn id、trace digest；
- 每项显式 trace index。

预算基于返回 body 的 canonical JSON 字符数。普通 entry 整项返回，不允许首项例外。单项超过 hard limit 时只返回该 entry 的 canonical JSON chunk：

- continuation 使用后端返回的 `next_entry_offset`；客户端不得计算；
- cursor 在 entry 完成前不前进；
- 请求必须回传 `entry_digest`，不匹配时失败；
- final chunk 完成后 next cursor 前进到下一 entry；
- 配置必须大于最小 chunk wrapper 开销。

summary ref 使用 `cursor_unit=summary_child`；Turn ref 使用 `cursor_unit=trace_entry`。Session Turn background 只在首个 trace page 返回，后续页只返回稳定 source metadata。

错误全部通过 ActionLocalFailure 交付：wrong owner/kind、unknown record、invalid/out-of-range cursor、invalid/out-of-range entry offset、entry digest mismatch。不得暴露 store path、原始异常或未过滤 record。

## Stage 5：Session Domain HOW 与 Answer Grounding

状态：done

在唯一 package init template `tinysoul/assets/project/home/` 新增 `how_domain/session/DOMAIN.md`：

- current Turn detail 使用 Context，prior Turn 使用 Session；
- ref 未知时 inspect，已有具体 Turn ref且查询 Action 状态时 actions，需要 exact entry 时 recall；
- 不从多页 raw recall 手工统计 Action；
- actions trace index 配合 recall 精确恢复；
- 区分 scan_complete、pairing_complete 和 page_complete；
- 遵循 failure disposition，不猜 owner/ref/offset。

Session 三个 native action 不创建 Action HOW，全部输入输出契约写入 Catalog schema/semantic。

新增 `how_action/core/answer.md`，因为 `core.answer` 确实创建 action-internal LLM task：

- 目标 prior Turn 的统计以 ref/trace digest 匹配、scan_complete 的最近 `session.history.actions` 为权威；
- 精确配对声明还要求 pairing_complete；
- 必须原样保留结构化结果中的数字、状态、失败和来源；
- 不得把当前 Turn Action/Control/phase failure 归入 prior Turn；
- coverage 不完整时必须限定结论；
- output limit 重试只缩短文字，不改变已确认事实。

`core.answer` 不新增 Session 专用参数或复制 payload；既有 Context MessageStack 仍是唯一任务输入。

## Stage 6：Workspace Prompt Source 与 Read Set

状态：done

在 Workspace 内引入 frozen typed values：

- `WorkspaceResourceState`：present/absent；
- `WorkspaceResourceVersion`：link/state/digest/size/kind；
- `WorkspaceEditReadSet`：target version 与全部 reference versions；
- `WorkspaceEditPrompt`：TaskPrompt 与 read set。

Workspace Engine 在一次 lock 中读取 target 和全部显式 `reference_links`，返回构造 PromptBlock 所需内容及版本；prompt builder 不再 inspect/read 两次，也不再另行读取 provenance。target 不能与 reference 重复，references 必须唯一。

action-internal LLM task 在 lock 外执行。完成后 commit API 在一次 Workspace lock 中：

1. reconcile 当前磁盘状态；
2. 校验 target 仍为相同 digest，或仍保持 absent；
3. 校验每个 reference 仍 present 且 digest 相同；
4. 全部通过后写入、完整 reconcile、返回单 revision；
5. lock 外只发布一次成功 change/snapshot。

任一 source 改变时不提交生成文本，返回稳定 source_changed failure 和 expected/actual 有界 constraint。成功 ActionResult 只返回版本/provenance 元数据，不返回正文、图片字节或 PromptBlock。

Domain HOW、Catalog 和 workspace write/rewrite Action HOW 必须声明：instruction 内的 Link 只是文本；所有生成依赖必须显式列入 `reference_links`。

## Stage 7：Working Control Identity

状态：done

删除 `update_working`，增加四个单操作 Context Control Tools：

- `set_milestone(key, content)`；
- `remove_milestone(key)`；
- `set_todo(key, content, status)`；
- `remove_todo(key)`。

每个 ToolSpec 的 required 字段能完整表达正常输入，normalizer 对每个有效 ToolCall 生成一个非空 WorkingPatch signal。Phase1 多个 calls 按 sequence 在 projected Working 上校验；无效 call 形成 Context-owned local ControlResult，全部有效 patch 仍在同一 signal batch 中原子消费。WorkingPatch 内部批量结构继续作为 Context 状态提交值，不暴露为模型 tool schema。

同步更新 Loop prompts、package Home AGENT、项目 AGENT.md、Context/Loop 设计和测试，不建立 Action/Control 公共失败基类。

## Stage 8：验收

状态：done

至少覆盖：

1. 所有 Action failed/timeout 都有 typed failure；success 禁止 failure；model projection 不泄漏 frame_data。
2. foldable canonical ToolResult 保留 action/status/stage，visible overlay 回收后 Session 仍可投影。
3. trace digest/entry digest 对 canonical JSON 稳定，trace summary 不再冒充 digest。
4. projector 得到 19 calls、15 success、4 failed、0 timeout，以及 8 search、8 fetch、4 fetch failure；Control/phase note 被排除，异常配对明确报告。
5. Background、inspect、actions 使用同一个 action outcome summary；summary node 不合并 child Action counts。
6. `history.actions` summary 与 detail pagination 独立，trace index 可驱动 recall 精确恢复。
7. Context/Session recall hard limit、Unicode、oversized chunk、digest/offset continuation、首页/后续页和所有 typed failure。
8. Session Domain HOW 进入 Phase2；三个 native Session action不加载 Action HOW；`core.answer` Action HOW 进入内部 task。
9. Workspace prompt provenance 来自实际读取版本；target absent 和 reference 并发变化均原子拒绝提交。
10. 四个 Working controls 不存在空 patch 正常输入，多 call sequence 与原子消费保持一致。
11. fake-provider E2E 在有限 Cycle 内准确回答 prior Turn Action 统计和读取来源，不混入当前 Turn failure，并以唯一成功 `core.answer` 结束。
12. Endpoint MODEL event 检查 provider-neutral MessageStack、task identity/attempt、action call/result 与 Observation sequence。

完成后运行完整 pytest、`ty` 类型检查、wheel build 和 standard/development 隔离初始化验证。仅在 Endpoint/frontend 消费契约实际变化时运行 TypeScript/Vite 构建。

## Review Follow-up Stage 9：Pager 与三层失败边界

状态：done

复审确认原 Stage 4 尚有两个实现缺口：`max_entries` 只存在于计划，没有进入 pager/配置/Catalog/API；Session 首屏把完整派生 Background 放进不可分页 base metadata，合法记录可能在常用 `max_chars=4000` 下整体失败。修复语义如下：

- Infra pager 同时执行 requested/effective max chars 与 max entries，字符预算始终优先，`max_entries=1` 支持已知 trace index；
- 通用 pager 以 enum reason 和 JSON-safe constraint 报告 cursor、digest、offset、limit 与 metadata budget 失败，不解释 owner/ref；
- Context/Session 将通用失败映射为各自 typed request error；只有该类型可由 action executor 转为 `ActionLocalFailure`；
- Context/Session I/O、budget 和 invariant 不再被宽泛 catch 压平，经 App 注入的所属 Runtime bridge 处理；Context invariant 明确映射为 internal failure；
- Session 首屏尽力携带派生 Background；超限时明确返回 `background_state.reason=page_budget` 并继续交付 canonical trace，不建立 Background cursor。后续页使用 `reason=continuation`；
- standard/development profile 同步 `trace_recall_max_entries` 与 `recall_max_entries`，两套配置保持相同文件和 key 形状。

## Review Follow-up Stage 10：Projection 与 Hook failure 单一来源

状态：done

- Action call/result name mismatch 拆为两个按真实 action 归属的异常 occurrence；一次 mismatch 的 `pairing_issue_count=2`，by-action status/failure 不再错误记到 call action；
- `session.history.inspect` 的直接 Turn item复用同一 projector 输出 `action_outcome_summary`，summary item仍不聚合 descendant counts；
- `HookOutcome` 直接携带 `ActionLocalFailure`；pipeline 对普通拒绝沿用 owner reason/scope/constraint，只把 hook identity 放在 frame data；
- Supervised Process answer guard 直接报告 `unresolved_supervised_process_job`，不再使用通用 `execution_hook_rejected` 加 `frame_data.reason` 表达两份失败事实。

## Review Follow-up Stage 11：Endpoint、Frontend 与发布验收

状态：done

- Endpoint Session recall 增加 `max_entries`，typed request error 映射为稳定 `422 session.<reason>`，其它 Session failure 使用安全通用 `500`；
- 前端 Session 类型以真实 Manifest head 为准，cursor 原样回传，消费双限制和 Background omission，不在前端重建 projector；
- Catalog 与 Session Domain HOW 描述 exact-index、双限制和 Background omission；Context/Session native actions 仍无 Action HOW；
- wheel/init 明确断言 Session actions catalog、Session Domain HOW、Core Answer HOW 存在，且不存在 Session Action HOW；
- 新增 hard budget、exact entry、typed error、name mismatch、inspect projector、Endpoint OpenAPI/error 和前端 build 回归。

## 完成标准

- Action failure 只有一个 typed source，renderer 只投影，不从 payload/frame_data 猜语义。
- canonical foldable result、Session projector 和 exact recall 使用同一稳定 Action envelope。
- 下一 Turn 无需加载全部 raw trace即可得到 prior Turn 完整 Action counts/status/failure summary。
- `core.answer` 能保持权威结构化事实和 current/prior provenance。
- Workspace mutation 能证明实际 prompt source 版本，stale read set 不能提交。
- Control ToolSpec 与 normalizer 对正常输入完全一致。
- 不增加 legacy adapter、第二事实源、LLM audit、语义地图或第二套 Loop/Action 状态机。

全部验收完成后，将本计划状态改为 done，并同步 `AGENT.md` 进度及 Action/Context/Session/Workspace/Loop/Home 设计文档。

## 实施结果

状态：done

- 生产代码已删除旧 `feedback.py`、`payload.failure`、`compact_payload` 与 `update_working` 路径，不保留兼容 adapter/alias；
- 真实 `turn_6a56f14a` fixture 在测试边界规范化为新 canonical contract 后，projector 得到 19 calls、15 success、4 failed、0 timeout，8 search、8 fetch 和 4 fetch failure；
- hard pager 通过完整响应字符预算、Unicode oversized chunk、digest/offset continuation、coverage/remaining/page_complete 验收；
- Workspace target-absent 与 reference 并发变化均以 `source_changed` 拒绝提交；
- Endpoint/前端 Session recall 已同步结构化 continuation cursor，并通过 TypeScript/Vite build；
- Review Follow-up 已补齐 Context/Session `max_entries` 全链路、结构化 request failure、Session Background 显式省略、inspect 同源 outcome summary、name mismatch 真实归属与 Hook failure 单一来源；Session Store 继续只表达底层契约和持久化错误，面向调用方的 invalid/unknown ref 只在 Session Engine 请求边界形成；
- Endpoint 使用稳定 `422 session.<reason>` 交付可修正 Session 请求，前端类型和 Session view 消费真实 Manifest head、双限制与 `background_state`，不在客户端重建 projector；
- `python -m pytest tests -p no:cacheprovider -q` 全量通过（22 项按条件跳过），`ty check`、`git diff --check` 与 `npm run build` 通过；全量测试已覆盖 wheel build、wheel 隔离安装及 standard/development 初始化，两套初始化文件形状一致，新 Catalog/HOW/config 资源已进入 wheel。
