# Workspace

Workspace endpoint 使用 `workspace:` link 和 active-day lease，不提供任意物理文件路径。

- `GET /v1/workspace/manifest`
- `GET /v1/workspace/resource?link=...`
- `GET /v1/workspace/blob?link=...`
- `PUT /v1/workspace/resource`：JSON text、expected digest/revision、可选 retention
- `PUT /v1/workspace/blob`：query 携带 link、overwrite、expected digest/revision、retention，body 为 `application/octet-stream`
- `GET/POST /v1/workspace/trash`
- `POST /v1/workspace/restore`

成功 mutation 返回 record 和完整 manifest，并发布 `workspace.changed`。CAS 冲突返回 `409 workspace.conflict`，前端保留草稿并重新读取 manifest/正文；不能自动用新 digest 重试旧内容。
