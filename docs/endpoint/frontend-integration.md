# Visualization 对接

后端现行协议为 v2，v1 路由已删除。本文描述对接要求；本轮未修改 visualization 源码，其客户端需要同步迁移后才能连接当前后端。`POST /v2/restart` 返回新的 runtime projection，Endpoint instance 与事件游标保持不变；重启窗口内 `ready=false` 是可观察状态。

客户端继续按 Runtime/Turn、Reflection、Events、Configuration 和 Workspace 分域。传输、Bearer、JSON/error 和 binary headers 集中处理。OpenAPI（需鉴权）提供请求 schema；运行语义分别见 [Runtime](runtime.md)、[Reflection](reflection.md) 和 [Events](events.md)。

连接发现先检查连接描述的 protocol_version=2、instance_id 和 project_identity。发起新对话使用 POST /v2/turns，保存回执中的 turn_id；追加指示、reply、grant 和 cancel 均使用明确身份。回复只绑定 question_id，补额只绑定 budget request_id；两个请求可以同时待决，不能由 UI 自行合并为单一“恢复”命令。需要终端语法时才使用 /v2/input。

重连携带上次 instance_id 与 sequence 进行 replay，再读取 status 与活动 Turn；gap 或实例变化时重建事件派生视图并读取 Reflection/Workspace。通过 TurnSnapshot 恢复问题、预算、Job 和完成结果；不从流文本猜终态，也不因 WebSocket 断开取消 work。历史句柄淘汰的 404 只表示当前运行窗口已无法查询。

配置 PATCH 保存候选，POST /v2/config/reload 显式激活；活动或等待 Turn 时返回 busy，保留已保存候选。激活后重取 status/actions。Action catalog 使用 GET /v2/config/actions?scenario=...，配置 mutation 使用 set/delete union，不增加旧 CAS 字段。

Workspace 只通过 /v2/workspace/* 访问 Link 资源，保留 text/blob、目录、标签、编辑和 Trash；不拼接宿主物理路径。项目 init/reset/start 由本地 CLI 负责，HTTP 不提供 reset。`POST /v2/restart` 只请求宿主重建 Agent generation，Endpoint instance 与事件游标保持稳定；它与 HTTP config/reload 不是同一种操作。

详细错误码见 [Endpoint](index.md)。业务失败按 code/details 显示，不解释 message 字符串，不自动重放可能有副作用的操作。
