# 浏览、定位与运行读取

所有路径前缀为 `/v2`，须 Bearer 鉴权。页面 GET 不调用模型、修改 Context 或隐式发现远端工具。所有内容来自已有 owner；不提供任意文件、Action 执行或历史 Context 数据库。

## 分页

普通列表参数为 continuation、limit（默认 30，1–100）、max_chars（默认 16000，1024–64000），具体支持项见 OpenAPI。结果为 items 与可选 next_continuation。单项超预算使用公共 JSON fragment 协议，按同一 token 顺序拼接 fragment 再解码，不把空 items 当作终页。continuation 绑定实际读取内容，变化返回 409 invalid_continuation/continuation_mismatch/continuation_content_changed/continuation_out_of_range；无效容量为 422 invalid_limit/page_budget_too_small。SearchPage/DisclosurePage 保留原协议，不再套一层分页。

## Turn、Context 与 Session

| GET 路径 | 参数 | 响应来源与内容 |
| --- | --- | --- |
| /days | before?, limit? | items[{day,active}]、next_before；活动及归档日 |
| /turns/{id}/interactions | continuation?, limit?, max_chars? | turn_id/generation_id/day/state、items、pending_items；完成后 result |
| /turns/{id}/context | 无 | turn_id/generation_id/day/captured_at、segments、resolved_references |
| /turns/{id}/context/segments/{segment_id} | continuation?, max_chars? | 段的已安装 messages，原始 message_index |
| /turns/{id}/context/inspect | ref、query?、continuation? | 既有 DisclosurePage |
| /session/turns | day?、普通分页 | Turn 摘要：turn_id/ref/day/status/input/output 线索及问题数 |
| /session/turns/{id} | day、continuation?、max_chars? | 正式 Session 交互页 |
| /session/map | day?、continuation? | session:map 的 DisclosurePage |
| /session/inspect | day、ref?、query?、continuation? | 已提交记录/解释的确定性披露 |

Interaction role 为 user.input/append/reply、agent.question/reason/action/output。id/ref 保留事实身份；输入 delivery 区分 installed/visible。pending_items 保留 Inbox sequence/record_id/kind/payload/state=accepted，与 Trace 顺序分开，和 items 共用有界页。queued_request 只是排队文本线索，不冒充 Context 输入。完成后用 Session 正式交互替换活动内容，不重复拼接；必要提交失败时 history_unavailable=true，不从事件伪造历史。

Context segment descriptor 包含 id/owner/slot/shape/order/capabilities/root_refs 与 available/loaded/protected_refs；chars/image_bytes 不是精确 token。正文来自已安装段，不读取最新文件替换它；TaskPrompt 只在具体 LLM 调用中显示。GET inspect 不追加 Action 结果、不解除展示保护。关闭后 409 context.unavailable；历史转 Session 或 Observation。未找到 Turn/归档日返回 404 turn.resource_not_found；未知 Session ref 为 404 unknown_ref。

## Home、Memory 与定位

| GET 路径 | 参数 | 内容 |
| --- | --- | --- |
| /home/catalog | view=effective或actual、space?、query?、普通分页 | 目录 locator/title/kind/size；含局部 guidance |
| /home/content | link、view?、continuation?、max_chars? | 实际正文与 direct refs 的 DisclosurePage |
| /home/changes | 普通分页 | overlay 的创建/修改/删除；只读，不清理 review 状态 |
| /home/diff | link、continuation?、max_chars? | actual/effective 差异及 baseline_diverged |
| /memory/active | day?、continuation?、max_chars? | 当日或归档活动 Memory.md |
| /memory/catalog | kind?、query?、普通分页 | 五类持久文档、状态与真实 redirect |
| /memory/document | link、continuation?、max_chars? | 持久文档正文、direct refs 与解析链 |
| /resources/resolve | reference、origin_link?、day?、turn_id?、view? | kind、locator、capabilities |

目录 query 只做名称/已有摘要筛选；全文检索用显式 Search。Home 不提供虚构的日期快照，不给 HTTP review token 或接受写权限。Memory active 与 persistent daily 分开，浏览历史日不会把持久知识改成历史版本。

ResourceLocator 只含 link 或 ref，附有意义的 day/turn_id/view。相对引用由 origin_link owner 解释。历史动态 memory:latest/current/target 使用原 Context/Session/Task 记录的绑定，缺失返回 422 resource.unresolved_origin；绝不替换成今天 latest。Workspace 来源 Turn 保留原 day。Search result_ref 和模型短 ID 不是永久资源。网页由客户端直接打开，不经后端代理。

## 页面 Search

`POST /home/search`、`/memory/search`、`/workspace/search` 直接接受现有 Search schema。范围分别为 effective Home、持久 Memory、活动 Workspace；无 actual Home/归档 Search。示例：

```json
{"source":{"kind":"query","scope":"all","query":"部署约定"},"steps":[{"op":"rerank","criterion":"优先可执行约定","context":"none"}],"page":{"limit":20,"max_chars":8000}}
```

续页请求仅为 `{"continuation":"原 token"}`；result 派生沿现有 source=result。SDK context 只能 none，不从活动 Turn 偷取 Context；implementation/provider/model 由配置透明决定。返回原 SearchPage，真实 evidence/evaluation/coverage 语义见 configuration。冻结续页不重新调用模型；结果绑定缓存的 SDK generation/day 服务，不能混入 Turn 句柄。

错误：422 search.invalid_request/scope_required/operation_failed；409 search.view_expired；503 search.source_unavailable。空 items 是有效结果，模型步骤失败不冒充空集。

## Job、ACP、MCP

`GET /turns/{id}/jobs/{job_id}` 返回 Job owner describe；`GET …/output?continuation=&max_chars=` 返回 channel/text 页、next_continuation、truncated、result_locators。游标封装真实输出位置；轮询不消费父 Agent 通知，不把不同流假装成因果总序。Job 收尾回收后 404 job.unavailable，历史查看实际产物和事件；停止沿原路由，无通用 Job reply。

`GET /subagent` 返回 generation_id/day、configured targets 和真实 connections（含空闲跨 Turn 连接）；UI 不创建连接或脱离 Turn 委派。

`GET /expand/servers` 返回已配置服务 enabled/connected/discovered/stale/tool_count/error，支持 continuation/limit。`GET /expand/tools?server_id=…&tool_name=…` 读取同一已发现目录；省略 tool_name 是摘要，指定名称是完整 schema，支持普通分页。GET 不 connect/discover；`POST /expand/servers/{server_id}/refresh` 明确触发 owner 的连接/刷新，返回该服务状态。无通用远端工具执行入口。
