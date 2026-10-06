# Workspace

Workspace endpoint 使用 `workspace:` ref 和受约束 async WorkspaceService，不提供任意物理文件路径。服务调用自行持有世代/day lease；每次 HTTP 操作重新获取服务。跨日准备导致已取得服务失效时返回 409，客户端重新取得状态后再决定是否重试；不自动重放写入。

- `GET /v2/workspace/manifest`
- `GET /v2/workspace/resource?ref=...`
- `GET /v2/workspace/blob?ref=...`
- `PUT /v2/workspace/resource`：通过 owner 校验 ref、大小和覆盖语义后原子写入 JSON/text 资源
- `PUT /v2/workspace/blob`：通过 owner 写入有界二进制资源，文件内容是唯一事实
- `POST /v2/workspace/directory`：`{ref}`，创建目录
- `POST /v2/workspace/move`：`{source_ref, target_ref}`，移动文件或目录，目标存在时拒绝
- `PUT /v2/workspace/tags`：`{ref, tags}`，替换标签集合；标签为 `pinned/tmp/library`，空列表清空
- `POST /v2/workspace/edit`：`{ref, edits: [{old_text, new_text}]}`，顺序验证 1–64 项唯一匹配后一次提交
- `POST /v2/workspace/append`：`{ref, text}`，追加明确文本
- `GET/POST /v2/workspace/trash`
- `POST /v2/workspace/restore`

四个 GET 接受可选 `day=YYYY-MM-DD`；省略时读取活动日，归档只读且不回退今天。manifest GET 只读已提交索引，不触发 reconcile。resource 接受 `continuation, max_chars=16000`（1024–64000），返回 ref、locator/day、text、size、media_type、editable、truncated、complete 和 next_continuation。正文变化使续接失效。`full=true` 明确请求完整可编辑文本，超 owner 写入上限则拒绝，不能把分页首屏保存为全文。

blob 流式读取，支持标准单 `Range: bytes=start-end`、`bytes=start-` 或 `bytes=-suffix`。部分响应 206 带 Content-Range，非法/不可满足范围 416；完整响应 200。Content-Length、Content-Type 来自实际打开文件；连接期间持有 day/generation lease。trash 为有界 items 页，接受 continuation/limit。所有写入路由仅操作活动日，不接受 day。

成功 mutation 返回 record 和完整 manifest，并发布 `workspace.changed`。公开请求不携带 digest/revision CAS，也不存在 mirror/apply/discard。取消不会回滚已提交文件；若索引提交失败，错误包含有界的已提交 ref，不能伪称副作用未发生。

正式写入和外部文件监听均由 Workspace owner 更新当前状态，后端自动通知活动 Turn 刷新工作台；前端无需再提交同步命令。`workspace.watch.enabled/debounce_ms` 沿配置接口保存并显式 reload。这里只监听当前 Workspace，观察事件仍是 UI 旁路，不能用 replay 代替 manifest 查询。

文本写入请求为 `{ref, text, overwrite?}`，overwrite 默认 false。Trash 请求为 `{ref}`，恢复请求为 `{trash_ref}`。JSON 请求拒绝未知字段，旧 `expected_digest/expected_revision/retention` 返回 422。Manifest 使用 schema v4，资源包含类型、大小、说明与标签，不含版本字段；标签不产生跨日保留语义。

参数、目标冲突返回稳定的 Workspace 请求错误；存储损坏或 IO 失败与参数错误分开。客户端看到已提交引用时应重新查询资源状态，不能假定整次操作已回滚。前端字段与路由使用同一契约。

blob 响应通过 `X-TinySoul-Size` 给出实际大小；引用只含 ASCII 字符时同时提供 `X-TinySoul-Ref`。包含其它字符的资源仍以请求中的 `ref` 精确定位。
