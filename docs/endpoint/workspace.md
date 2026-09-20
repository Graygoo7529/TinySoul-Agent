# Workspace

Workspace endpoint 使用 `workspace:` link 和受约束 async WorkspaceService，不提供任意物理文件路径。服务调用自行持有世代/day lease；每次 HTTP 操作重新获取服务。跨日准备导致已取得服务失效时返回 409，客户端重新取得状态后再决定是否重试；不自动重放写入。

- `GET /v2/workspace/manifest`
- `GET /v2/workspace/resource?link=...`
- `GET /v2/workspace/blob?link=...`
- `PUT /v2/workspace/resource`：通过 owner 校验 link、大小和覆盖语义后原子写入 JSON/text 资源
- `PUT /v2/workspace/blob`：通过 owner 写入有界二进制资源，文件内容是唯一事实
- `POST /v2/workspace/directory`：`{link}`，创建目录
- `POST /v2/workspace/move`：`{link, target_link}`，移动文件或目录，目标存在时拒绝
- `PUT /v2/workspace/tags`：`{link, tags}`，替换标签集合；标签为 `pinned/tmp/library`，空列表清空
- `POST /v2/workspace/edit`：`{link, edits: [{old_text, new_text}]}`，顺序验证 1–64 项唯一匹配后一次提交
- `POST /v2/workspace/append`：`{link, text}`，追加明确文本
- `GET/POST /v2/workspace/trash`
- `POST /v2/workspace/restore`

成功 mutation 返回 record 和完整 manifest，并发布 `workspace.changed`。公开请求不携带 digest/revision CAS，也不存在 mirror/apply/discard。取消不会回滚已提交文件；若索引提交失败，错误包含有界的已提交 link，不能伪称副作用未发生。

正式写入和外部文件监听均由 Workspace owner 更新当前状态，后端自动通知活动 Turn 刷新工作台；前端无需再提交同步命令。`workspace.watch.enabled/debounce_ms` 沿配置接口保存并显式 reload。这里只监听当前 Workspace，观察事件仍是 UI 旁路，不能用 replay 代替 manifest 查询。

文本写入请求为 `{link, text, overwrite?}`，overwrite 默认 false。Trash 请求为 `{link}`，恢复请求为 `{trash_ref}`。JSON 请求拒绝未知字段，旧 `expected_digest/expected_revision/retention` 返回 422。Manifest 使用 schema v4，资源包含类型、大小、说明与标签，不含版本字段；标签不产生跨日保留语义。

参数、目标冲突返回稳定的 Workspace 请求错误；存储损坏或 IO 失败与参数错误分开。客户端看到已提交 Links 时应重新查询资源状态，不能假定整次操作已回滚。本文描述后端契约，前端字段与路由须相应迁移。
