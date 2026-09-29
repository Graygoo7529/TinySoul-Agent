# Visualization 对接

## Contract entry point

The frontend consumes only the v2 routes described here. Stable response
schemas and representative payloads live in
[`contracts/`](contracts/README.md); generated OpenAPI is the machine-readable
route index. A client must keep `generation_id`, `day`, `turn_id`, `ref`, and a
continuation token together and discard a continuation after the corresponding
lease changes.

Context overview roots are already inspectable owner links. Home direct refs
use the canonical Home layout (`home:agent@...`, `home:skills@...`,
`home:skills_domain:...`, `home:skills_action:...`, or progressive resource
links), and may be sent to resource resolve without a client-side rewrite.
Disclosure uses the shared read-only page envelope. Search and Job output
have separate response envelopes; model observations use the event envelope.
Each retains its owner's content and continuation semantics.

后端现行协议为 v2，v1 路由已删除。本文描述对接要求；本轮未修改 visualization 源码，其客户端需要同步迁移后才能连接当前后端。`POST /v2/restart` 返回新的 runtime projection，Endpoint instance 与事件游标保持不变；重启窗口内 `ready=false` 是可观察状态。

`ready` 表示生命周期 owner 已可运行；候选依赖和 active day 已存在时仍可能处于激活中，此时业务操作返回 `409 service.unavailable`，status、health 与 replay 仍可读取。重叠重启共用一次 SDK 操作；取消请求等待者不表示底层重启被撤销，重新连接后应读取状态。

客户端继续按 Runtime/Turn、Reflection、Events、Configuration 和 Workspace 分域。传输、Bearer、JSON/error 和 binary headers 集中处理。OpenAPI（需鉴权）提供请求 schema；运行语义分别见 [Runtime](runtime.md)、[Reflection](reflection.md) 和 [Events](events.md)。

连接发现先检查连接描述的 protocol_version=2、instance_id 和 project_identity。发起新对话使用 POST /v2/turns，保存回执中的 turn_id；追加指示、reply、grant 和 cancel 均使用明确身份。回复只绑定 question_id，补额只绑定 budget request_id；两个请求可以同时待决，不能由 UI 自行合并为单一“恢复”命令。需要终端语法时才使用 /v2/input。

重连携带上次 instance_id 与 sequence 进行 replay，再读取 status 与活动 Turn；gap 或实例变化时重建事件派生视图并读取 Reflection/Workspace。通过 TurnSnapshot 恢复问题、预算、Job 和完成结果；不从流文本猜终态，也不因 WebSocket 断开取消 work。历史句柄淘汰的 404 只表示当前运行窗口已无法查询。

配置主流程使用 `POST /v2/config/apply`，请求二选一：`operations` 整批变更或 `preset_id` 方案应用；成功返回 `state=active`、`generation_id`、`pending_reload=false`、变更字段和匹配方案。`GET /v2/config?view=saved|active` 分别读取保存候选和当前 generation 的活动投影，包含 `activity`、`fields`、`sources`。方案摘要和详情由 `/v2/config/presets` 独立提供；前端草稿的 reset 是本地丢弃，不请求后端。

`PATCH /v2/config` 只保存候选，返回 `state=saved,pending_reload=true`；`POST /v2/config/reload` 激活当前 saved。活动或等待 Turn 时激活返回 `409 config.activation_unavailable`，已保存候选保留。激活后重取 status/actions。Action catalog 使用 GET /v2/config/actions?scenario=...，配置 mutation 使用 set/delete union，不增加旧 CAS 字段。

普通读取页使用 `items`，可选 `next_continuation` 或 `content_fragment`；先消费本页 items/fragment，再按 `next_continuation` 续读。空 `items` 不表示没有内容，最后一页也可能包含 fragment。Search 使用独立的 `result_ref/scope/source/items/coverage/page/continuation` 结构，不能读取旧的 `candidates`/`operation` 示例字段。Turn snapshot 的 `question`、`budget_request`、`wait_reason` 和 `result` 是恢复对话、问题卡片、补额和完成状态的正式来源；正常回答的 result status 为 `answered`。InteractionPage 在普通页上增加 Turn/day、待受理输入及适用的状态/结果，不是另一个 TurnSnapshot。Job 输出使用按 channel 的 `items`、`next_continuation`、`truncated` 和 `result_locators`；空输出时仍返回可供后续轮询的 token。

Workspace 只通过 /v2/workspace/* 访问 Link 资源，保留 text/blob、目录、标签、编辑和 Trash；不拼接宿主物理路径。项目 init/reset/start 由本地 CLI 负责，HTTP 不提供 reset。`POST /v2/restart` 只请求宿主重建 Agent generation，Endpoint instance 与事件游标保持稳定；它与 HTTP config/reload 不是同一种操作。

详细错误码见 [Endpoint](index.md)。业务失败按 code/details 显示，不解释 message 字符串，不自动重放可能有副作用的操作。
