# Visualization frontend demand index

The active frontend work is governed by the current execution plan in
`docs/analysis/`.

## Implemented demands

- `20261030-endpoint-stable-token-remote-bind.md`（implemented，owner: gateway/endpoint）：
  endpoint 使用项目 `.auth` 中的稳定 token、`.env` 中的 bind host/port，并让本机与
  A/B 部署统一为「address + token 一次输入 + 持久化自动登录」；前端已删除实例发现链路。

## Archive

The three September 30 demand notes were implemented or aligned with the v2
catalog and Home browse contracts and are retained under `archived/` as
historical records. They are not additional API requirements.

New backend capability requests discovered during frontend work should be
added here only after checking the existing v2 endpoint contract. A request
must identify the owner, the normal user path, the missing response or
behavior, and whether a frontend-only projection is insufficient.
