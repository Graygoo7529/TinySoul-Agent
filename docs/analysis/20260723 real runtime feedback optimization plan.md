# 真实运行反馈优化执行计划

状态：planned

## 背景

真实运行记录 `reference/turn_6a56f14a.json` 与 `reference/turn_92b63b73.json` 表明，TinySoul 已能在一个 User Turn 内完成 Web 检索、Workspace 提交、局部失败恢复、最终回答和 Session 持久化，但“证据是否真正进入 action-internal LLM task”与“如何准确审计此前 Turn”仍未形成完整闭环。

第一轮在 8 个 Cycle 中执行 19 次 Action call：8 次 `web.search_by_kimi` 全部成功，8 次 `web.fetch_with_defuddle` 中 4 次成功、4 次形成稳定 HTTP 局部失败，随后成功写入 14,393 bytes 的调研文档并完成 `core.answer`。其主要缺陷不是行动失败，而是 `workspace.write` 的 reasoning 表达了使用资料 Link 的意图，实际 ActionCall 却没有传递 `reference_links`；instruction 中出现的 `workspace:` 字符串不会被 Workspace prompt resolver 自动加载，因此已下载正文没有进入该次写作任务。

第二轮询问上一轮的工具调用、失败和资料读取情况。Agent 先用两次 `context.trace.inspect` 错误访问跨 Turn ref，随后使用 1 次 `session.history.inspect` 和 14 次 `session.history.recall` 分页恢复上一轮轨迹。分页停在 `next_cursor=24`，没有读取总计 27 项 trace 的尾部；第一次 `core.answer` 又因 output token 上限形成局部失败。最终回答把当前轮的 `workspace.read`、`core.answer` 失败和两次 `update_working` normalize 失败归到上一轮，并把 8 次 Web 搜索回答为 6 次。该结果说明持久事实仍在，但当前检索投影不足以稳定支持精确 Turn 审计。

## 现有设计事实

### Context 当前 Turn trace

`TurnTraceHeap` 为每项 trace 同时区分 canonical `message` 与可选 `visible_overlay`。standard ActionResult 只保存完整 canonical message；foldable 成功结果保存 executor 提供的 compact canonical message，同时把完整 ToolResultMessage 作为当前 Turn visible overlay。Context 构造 MessageStack 时渲染 hot entry 的 visible message；显式 fold 或容量压缩会先移除 overlay，再按完整 Cycle 边界把较旧 canonical entries 移入不可变 leaf，并在需要时合并为 branch。

`context.trace.inspect` 只导航当前 Turn 的 heap head/branch header；`context.trace.recall` 只接受 inspect 得到的 leaf ref，并按 cursor 返回该 leaf 的 canonical entries。它不能读取此前 Turn，也不能恢复已被折叠丢弃的 full overlay。recall ActionResult 自身是 foldable：本 Cycle 可见完整 recalled page，canonical trace 只保留 origin ref、entry count、next cursor 和 folded 标记。

### Context 到 Session

User Turn 结束时，`ContextEngine.end_turn()` 生成不可变 `TurnSummary`，其中包含全部 canonical trace records、trace heap headers、trace digest、最终 Working、UserInputs 与 Background Links；visible overlay 不进入 summary。`SessionTurnCompletionHandler` 把该 summary、最终 output 和 exhausted 状态提交给 `SessionEngine.record_turn()`。Session 先保存不可变 `session:turn/<turn_id>` record，再更新当日 Manifest，并从同一 summary 派生下一 Turn 使用的有界 Session background。

下一 Turn preparation 中，Session 通过版本化 `SessionBackgroundSnapshot` 把 Manifest 当前可见头部交给 Context。Context 只在 preparation 窗口接受该 snapshot，并将每个 item 渲染为 `background:session:<item_id>` JSON UserMessage。它位于 MessageStack 的 UserInputs 之后、通用 Background 和当前 TurnTrace 之前。Session 不在活跃 Turn 中持续修改 Context，也不把 raw store 直接暴露给 Loop。

### Session 既有 Turn recall

`session.history.inspect` 返回当日 Manifest 头部、item 元数据及 `session:turn/...`、`session:summary/...` refs。`session.history.recall` 加载一个不可变 record：summary record 返回 child refs；Turn record 返回派生 background 和 canonical trace 分页。该 ActionResult 同样是 foldable，因此完整历史页只作为当前 Turn visible overlay，写回当前 Turn canonical trace 的只是 origin ref、next cursor 和 folded 标记，不会把 recalled history 递归复制进新的 Session record。

当前 `recall_max_chars=8000` 是配置上限，调用方请求更大值会被静默收紧；响应不报告 requested/effective limit。Context 与 Session 的分页实现都会为了保证游标前进而允许第一页的单个原子 entry 突破 max chars。Session 每页还重复返回同一 background。以上行为与设计文档中的“显式且有界”表述没有完全闭合。

### foldable 结果进入 Session 后的信息

只有成功 ActionResult 可以携带 `ActionTraceProjection`。完整成功结果首先被渲染为 `ToolResultMessage(status=ok)`；若 action 配置为 foldable，Context 另构造 `action_result_folded` compact message，但保留相同 call id、tool name 和 `status=ok`。Session record 因此会保留 compact payload、调用身份、action 名称和基本成功状态，不保留 full overlay。

failed/timeout ActionResult 按不变量不能携带 trace projection，所以即使对应 action 的成功策略为 foldable，失败仍以完整、受 action 结果边界约束的 `ToolResultMessage(status=error)` 进入 canonical trace；其中通常包含 action、status、stage、feedback，以及存在时的稳定 failure payload/frame data。因此 Session raw Turn record 和 `session.history.recall` 能看到基本错误状态与局部失败事实。

但“Session record 中存在”不等于“下一 Turn 自动 Background 会逐项展示”。自动 background 固定包含 ask、最终 answer/references、exhausted 与 trace digest；只有 `background_action_names` allowlist 中的 action 才会额外配对 call/result 并携带 status。当前 standard/development 默认只允许最多三个 `core.reason`，所以多数 Workspace、Web、Context 和 Session action 的逐项成功/错误不会自动进入下一 Turn，只能从 trace digest 知道 action 名称，或显式 recall canonical trace。

## 设计目标

1. 保持 Context 只拥有当前 Turn、Session 只拥有跨 Turn 不可变历史的现有边界。
2. 为“上一轮调用了什么、哪些失败、结果属于哪一轮”提供确定性、有界、带 provenance 的 Session-owned 审计投影。
3. 让 Context 与 Session recall 对 requested/effective limit、覆盖范围、完成状态和超大原子 entry 使用一致且真实的协议。
4. 保持 foldable 的完整当前轮可见、compact canonical 持久化语义，不把历史 full overlay 递归写入 Session。
5. 明确 Workspace LLM action 只有 typed `reference_links` 才表示读取证据；不从 instruction 文本猜测或自动提取 Link。
6. 修复工具 schema、模型反馈与实际 normalize/execute 契约不一致的问题。
7. 通过 Endpoint model Observation 和真实 replay 验证 MessageStack，而不是仅凭 Session canonical record 推断模型当时看到的 full overlay。

## 非目标

- 不增加剩余 Cycle 提示、终局 Cycle 预留或另一套 Loop 状态机。
- 不让 Context 读取 Session store，也不让 Session 解释 Web、Workspace 等业务 payload。
- 不扩大 SessionBackground 为全部 action raw result；自动背景仍是有界投影。
- 不把 instruction 内的 `workspace:` 文本隐式升级为文件读取权限。
- 不因为单次记录较大就直接把所有 Web result 改为 foldable；standard/foldable 变更必须同时解决完整事实的稳定 Link 与后续可恢复性。
- 不把 MODEL Observation、完整 MessageStack 或 full overlay 持久化到 Session。

## Stage 1：建立 Session-owned Turn 审计投影

状态：planned

新增一个只读 Session action，暂定名 `session.history.trace.inspect`。它直接投影 `SessionEngine` 已加载并校验的不可变 Turn record，不建立新持久化状态，也不复用 Context heap ref。

输出至少包含：

- `ref`、`source_turn_id`、record kind 和 trace entry count；
- 每项稳定 trace index、cycle id、phase、kind 和 message role；
- action call 的 action name、call id 与有界 arguments；
- 与 call id 配对的 result status、stage 和有界稳定 failure facts；
- Phase control/phase-level failure 的稳定 reason、status 与所属 Cycle；
- `cursor`、`next_cursor`、`complete`、覆盖区间和 remaining count；
- 无法配对的 call/result 作为显式事实报告，不静默丢弃。

Session 只解释自身持久 trace envelope 与通用 ToolResult 结构，不解释具体 capability payload。既有 `_project_action_history` 中的通用配对逻辑应提取为 Session 内部 typed projector，分别服务有界 Background allowlist 和显式完整审计，避免形成两套不一致的 call/result 解释。

精确内容仍通过 `session.history.recall` 按 trace cursor 获取；审计 action 负责先定位和计数，避免为回答调用统计而连续召回全部大块正文。

## Stage 2：对齐 Context 与 Session recall 契约

状态：planned

两类 recall 保持各自 owner 和 ref 空间，但采用一致的分页事实字段：

- `requested_max_chars` 与实际 `effective_max_chars`；
- `cursor`、`next_cursor`、`complete`/`truncated`；
- 当前页覆盖的 entry 起止位置、总 entry 数与 remaining count；
- `actual_chars` 和是否遇到 oversized atomic entry；
- Session 后续页不重复完整 Turn background，只返回稳定 background ref/omitted 标记。

必须明确解决“原子 entry 大于 hard limit”而不是继续隐式越界。首选方案是返回有界 entry header/descriptor，并通过独立的 entry 内部分页读取逐步恢复原始 canonical JSON；如果实现前确认不需要逐字恢复，则必须在设计文档中明确 raw record 与模型可召回投影的差异，不能继续把软目标描述为硬上限。

`context.trace.recall` 仍只读取当前 Turn cold leaf 的 canonical message；`session.history.recall` 仍只读取 Session record。公共字段和值对象可以复用通用 JSON/分页基础设施，但不得建立跨 owner 的共享 history service。

## Stage 3：强化 provenance 与 owner failure

状态：planned

- Session audit/recall 返回的每个 trace item 显式携带 `source_turn_id` 和 trace index，避免与当前 TurnTrace 混淆。
- Context 拒绝 foreign Turn ref 时返回稳定局部 failure facts，例如 `reason=foreign_turn_ref`、`scope=current_turn`、`disposition=change_request`，并说明改变 ref 拼写不能改变 owner；Context 不直接建议某个 Session action。
- Session 对错误 ref kind、未知 record、非法 cursor 和 incomplete pagination 使用自身稳定 reason，不把 store 路径或异常文本暴露给模型。
- 需要声称“全部调用/全部失败”的回答必须以 `complete=true` 的审计投影为依据；未完成时只能声明已覆盖范围。

## Stage 4：闭合 Workspace 来源协议

状态：planned

- 在 package-owned Workspace domain HOW 与 `workspace.write`/`workspace.rewrite` Catalog 描述中明确：instruction 中出现的 Link 只是文本，不会加载资源；生成依赖的每个 Workspace 证据必须出现在 `reference_links`。
- Workspace LLM mutation 成功 metadata 增加有界的 `reference_count` 与实际解析的 `{link, digest}` provenance，使后续 Phase 和审计能够确认生成时真正读取了哪些版本。
- provenance 仍只包含 Link/digest/size 等元数据，不把正文放入 ActionResult。
- 不扫描自然语言 instruction 自动补全或拒绝未声明 Link；业务意图不能通过字符串启发式可靠推断。
- 增加写作类 E2E：reasoning/instruction 即使提及 Workspace Link，只要没有 `reference_links`，嵌套 task 就不得看到正文；正确传参时必须按 digest 加载并在提交结果中报告来源。

## Stage 5：对齐 Control Tool schema 与 normalize

状态：planned

`update_working` 当前描述要求至少一个 operation，但工具 schema 允许 `{}` 和全空数组，normalize 随后以 `empty_patch` 拒绝。需要先扩展并统一 TinySoul 支持的 Tool JSON Schema 子集，再收紧该 control：

- 为通用 schema definition/runtime validator 增加确有业务需要且 provider 可兼容的非空约束，优先评估 `minItems` 与 `minProperties`；
- Action Catalog 与直接构造的 Control ToolSpec 使用同一明确子集和测试，不允许只把 provider schema 写严而本地不校验；
- `update_working` 每个已提供 operation array 必须非空，根对象必须至少提供一个 operation；
- normalize 保留防御性 `empty_patch` 校验，并把反馈改为“没有真实状态变化时不要调用；需要更新时提供至少一项非空操作”；
- 若目标 provider 无法可靠支持上述 schema keyword，则在实施前重新设计 typed operation 结构，不用 prompt 文案掩盖协议缺口。

## Stage 6：回答构造与 Observation 验证

状态：planned

- 审计型 `core.answer` 应把完整的 Session audit projection 作为明确、带来源的 input block，而不是依赖十余页混合 TurnTrace 自行计数。
- 保留 `core.answer` output limit 的局部 `change_request` 恢复语义；测试确认缩小请求后只改变真实输出规模，不改变已确认审计事实。
- 使用 Endpoint MODEL route 捕获每次 `llm.task.message_stack`、action call/result、phase 和 task identity，验证 Session recall full overlay 在当前 Turn 的实际可见时段、显式/自动 fold 时点及最终回答输入。
- Observation 只用于运行期可观测性和前端展示，不写入 Session、Workspace、Home、Memory 或前端持久缓存。

## Stage 7：测试与真实验收

状态：planned

单元与集成测试至少覆盖：

1. foldable success 在当前 Turn 渲染 full overlay，seal 后只持久化 compact canonical message，同时保留 tool name、call id 与 `status=ok`；
2. foldable action 的 failed/timeout result 不携带 projection，并以完整有界 `status=error` canonical message 进入 Session；
3. 默认 SessionBackground 对非 allowlisted action 只提供 trace digest，不错误宣称带有每次 result status；allowlisted projection 正确配对 compact success 与完整 failure；
4. Context inspect/recall 拒绝跨 Turn ref，Session inspect/recall 不接受 Context heap ref；
5. Session audit 对 `turn_6a56f14a` 稳定统计 8 次 search、8 次 fetch、4 次 fetch failure，并识别最终 write/answer 成功；
6. 对 `turn_92b63b73` 区分上一 Turn 与当前 Turn 事实，不把当前的 read、answer failure 和 control failure归到上一轮；
7. recall 在 requested limit 大于配置上限、超大原子 entry、最后一页和 cursor 越界时返回真实一致的分页字段；
8. Workspace write/rewrite 只加载显式 references，并报告实际 provenance；
9. `update_working` 空对象/空数组在工具参数边界被拒绝，normalize 仍能防御绕过校验的内部调用；
10. fake-provider App E2E 在少量有效 Cycle 内准确回答“上一轮调用、失败和读取来源”，以唯一成功 `core.answer` 结束；
11. 真实 provider replay 同时检查最终答案、Session record 与 MODEL Observation，不再只凭最终文本判断通过。

完成实现后运行完整 pytest、静态类型检查、wheel 构建与隔离初始化验证；涉及前端 model 事件消费时同时运行 TypeScript/Vite 构建。全部验收完成后更新 `AGENT.md`、Context/Session/Action/Workspace 设计文档并将本计划标记为 done。

## 完成标准

- Agent 可以通过一个 Session-owned 有界审计入口准确回答此前 Turn 的调用、成功、失败、Phase feedback 和完成状态；
- Context 与 Session recall 的 owner、容量、覆盖范围与完成语义清晰一致；
- foldable full overlay 不进入 Session，但 compact success 和完整 failure 都保留足够的基础状态与 provenance；
- Workspace 写作能证明实际读取的 sources，不再把 instruction 中的 Link 当成已加载证据；
- 空 `update_working` 不再成为模型可生成但框架必然拒绝的正常工具形态；
- 两份真实记录对应的审计问题能够在不增加 Cycle 预算机制、全量自动 Background 或第二套状态机的前提下稳定正确回答。
