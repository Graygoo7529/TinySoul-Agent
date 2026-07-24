# Session History Navigation Boundary Correction Plan

状态：done

日期：2026-07-24

## 背景与问题

Session 已拥有 immutable Turn/Summary record、Manifest root、确定性 Summary 收缩、下一 Turn 固定 `SessionBackgroundSnapshot`、Action history projector 与 hard pager。当前问题不在持久模型，而在读取职责混合：

- `session.history.inspect` 只能返回 Manifest root，不能沿 Summary 图展开；
- `session.history.recall` 同时返回 Turn trace、Summary child refs 与首屏 Background，混合了图导航、概况投影和原始证据恢复；
- Endpoint 直接复用上述混合 JSON，前端因而消费了模型侧 `background_state`；
- `recall_max_chars/entries` 实际将同时服务后续 inspect/trace 页面，配置名称不能表达完整边界。

## 已确认语义

### Session Background

Session 在 Turn completion 后保存 immutable record，并为下一 Turn 确定性派生有界 Background。Context 在 Turn preparation 接收唯一版本化 Session snapshot；该 Session 段在整个 Turn 固定、不可逐出，Phase/Action 不能修改。

当 Background head 超过 watermark 时，Session 将较旧连续节点收缩为 immutable Summary node，保留至少配置数量的最近 Turn。Summary 可以递归包含 Summary，形成 Session-owned 渐进历史图；原 Turn/Summary record 不删除。极端情况下自动 Background 只提供 `session_overflow_head` 与最近可容纳节点，模型通过无参 inspect 恢复 authoritative Manifest root。

inspect 只读取 Session 图并产生 ActionResult。结果进入当前 Turn Interaction/TurnTrace，不写回 Background，也不发送 `context.session.sync` 或 Background patch。

### 三个 Agent Action

1. `session.history.inspect(ref?, cursor?, max_chars?, max_entries?)`
   - 无 ref：分页返回 authoritative Manifest roots；
   - Summary ref：分页返回该 immutable Summary 的直接 children；
   - Turn ref：返回该 Turn 的单个有界 overview；
   - 每个节点公开 `preview`，其内容来自 Session-owned Background projection，但不以 Background 状态交付；
   - 只负责图导航和节点概况，不返回 raw trace，不重新解释 Action payload。
2. `session.history.actions(ref, cursor?, max_items?)`
   - 只接受具体 Turn ref；
   - 从完整 canonical trace 确定性返回全 Turn Action summary、failure groups、occurrence detail 与 trace indexes；
   - 不返回 raw arguments 或 raw result payload。
3. `session.history.recall(ref, cursor?, max_chars?, max_entries?)`
   - 只接受具体 Turn ref；
   - 只分页返回 canonical trace entries、source、coverage 和 digest-bound continuation；
   - 不返回 Background/preview，不导航 Summary，不统计 Action；
   - 已知 trace index 时使用 `max_entries=1` 精确恢复。

三个 native Session Action 不调用 LLM，因此只维护 Catalog 和 Session Domain HOW，不创建 Action HOW。

### Endpoint 与前端

Endpoint 是 authenticated read adapter，不调用 ActionEngine、不创建 ActionCall/ActionResult、不写入 TurnTrace。Agent Action executor 与 Endpoint 只共享 Session-owned 领域查询及稳定事实，不共享模型专用 envelope。

正式 Endpoint 为：

- `GET /v1/session/history?ref=...`：对应 inspect 查询，ref 可省略；
- `GET /v1/session/actions?ref=...`：对应 Action history 查询；
- `GET /v1/session/trace?ref=...`：对应 canonical trace recall。

删除 `/v1/session/recall`，不保留兼容 alias。前端 Session Explorer 使用 history 展开 root/Summary/Turn，使用 actions 查看历史 Action 审计，使用 trace 按 index 查看原始证据；不消费 `background_state`，不在客户端重建 projector。

Gateway 继续只统一用户命令输入和 Observation 输出。Session 只读 API 与 Workspace 只读 API 一样在 Daily active-day lease 内直接调用所属 Engine，不伪装成 Gateway command。

### 配置与失败

删除 `recall_max_chars`、`recall_max_entries`，改为：

```toml
history_page_max_chars = 8000
history_page_max_entries = 50
actions_page_max_items = 50
```

inspect 与 recall 共享 Infra immutable JSON sequence pager，但各自拥有 Session ref/kind/source 语义。无效 ref、wrong kind、limit、cursor、offset、digest 和 root revision 属于 `SessionHistoryRequestError`；Action adapter 转为局部 failure，Endpoint 转为安全 `422 session.<reason>`。Store I/O 与 Session invariant 继续经 Runtime bridge 或安全 `500`，不得降级为可修正请求。

本轮不提供历史完整 answer/output section。inspect 只交付有界 preview；若真实使用证明需要完整最终输出，再以显式 record section 设计，不借用 Background 或 trace payload。

## 实施阶段

### Stage 1：Session 领域查询

状态：done

- 重构 inspect 为 root/Summary/Turn 三种明确来源；
- 对 root/Summary 节点使用字符和条目双 hard limit；
- 输出稳定 source、items、coverage、cursor 和 `preview`；
- root 页面绑定 Manifest revision，revision 变化时要求从 root 重新开始；Summary/Turn record 保持 immutable；
- recall 限制为 Turn trace，删除 Background fallback 与 Summary 分支；
- 保持 actions projector 与 recall trace index 的协作关系。

### Stage 2：Action 与 HOW

状态：done

- 更新 inspect/recall executor 参数、typed failure 与 foldable policy；
- 更新三个 Session Catalog 的 use/avoid/examples；
- 重写 Session Domain HOW，说明固定 Background、overflow/Summary inspect、actions audit 与 exact recall；
- 明确 inspect ActionResult 位于 Interaction，且不改变 Background。

### Stage 3：Endpoint 与前端

状态：done

- 重构 Session Endpoint query methods 和 OpenAPI；
- 删除 `/v1/session/recall`，新增 `/v1/session/actions` 与 `/v1/session/trace`；
- 更新前端 API/types/SessionView，提供 Summary 展开、Action audit 与 trace detail；
- 更新 `docs/endpoint/frontend integration.md` 和前端执行记录。

### Stage 4：配置、模板与发布

状态：done

- 同步 Session config parser、standard/development init profiles；
- 更新 initializer、wheel package resource 和 clean install 断言；
- 不增加 legacy config key 或 Endpoint alias。

### Stage 5：验收

状态：done

至少覆盖：

1. Session Background 在 Turn preparation 后固定，inspect 不改变 snapshot；
2. Summary 收缩保留 immutable children，inspect 可从 root 逐层展开到 Turn；
3. overflow head 通过无参 inspect 恢复被省略的 authoritative roots；
4. inspect page 遵守 char/entry hard limit，并对 root revision 变化显式失败；
5. actions summary 完整且 trace index 可驱动 recall `max_entries=1`；
6. recall 拒绝 Summary ref，响应不含 Background/preview/action summary；
7. Agent inspect result 进入 Interaction/TurnTrace，不产生 Background signal；
8. Endpoint 三条正式路由、typed 422、安全 500 与 OpenAPI；
9. 前端能展开历史树、查看 Action audit 和 trace page，TypeScript/Vite build 通过；
10. Session Domain HOW 进入 Phase2，三个 Session native Action 均不存在 Action HOW；
11. standard/development 配置形状一致，新配置与 Home/Catalog 进入 wheel/init；
12. 完整 pytest、`ty`、`git diff --check` 通过。

## 完成标准

- Background、inspect、actions、recall 各自只有一个明确职责；
- Session 图的渐进展开不再依赖 recall Summary 分支；
- Agent Action 与 Endpoint 是同一领域事实的独立适配器，不互相伪装；
- 前端不消费模型 Interaction 专用状态，不重建 Session projector；
- 不增加兼容 alias、第二事实源、第二套状态机或无 LLM 的 Action HOW。

## 实施结果

状态：done

- SessionEngine 已将 history inspect 收敛为 root/Summary/Turn 三种 source，并为 root continuation 绑定 Manifest revision；Summary 只由 inspect 展开，recall 只读取 Turn canonical trace。
- `session.history.inspect/actions/recall` 的 Catalog、typed local failure 与 Session Domain HOW 已对齐；三个 native Action 不调用 LLM，没有 Action HOW。inspect 结果经正常 Action renderer 进入 Interaction/TurnTrace，不改写 SessionBackground。
- Endpoint 已提供 authenticated `/v1/session/history`、`/v1/session/actions`、`/v1/session/trace`，删除旧 recall 路由；三条查询在 Daily active-day lease 内直接读取 SessionEngine，不经 Gateway/ActionEngine 且不产生 Observation。
- 前端 SessionView 已改为 Summary 树导航与 Overview/Actions/Trace 三页签，可分别定位 call/result trace index；root revision 变化时自动放弃旧 cursor 并重读最新 root。
- Session 配置已更名为 `history_page_max_chars/entries`，standard/development init profile 保持同形；Catalog、Domain HOW 和新配置已纳入 initializer/wheel 验收，不保留旧配置 key 或 Endpoint alias。
- 完整 `pytest tests` 通过；`ty check --python C:\\Anaconda3\\envs\\TinySoul\\python.exe` 通过；`visualization` 的 `npm.cmd run build` 通过。
