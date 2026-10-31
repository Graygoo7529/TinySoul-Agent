# Visualization frontend demand index

The active frontend work is governed by the current execution plan in
`docs/analysis/`.

## Open demands

- `20261030-endpoint-stable-token-remote-bind.md`（pending，owner: gateway/endpoint）：
  endpoint 配置节提供稳定 token、显式非 loopback host 与固定 port，使本机与
  A/B 部署统一为「address + token 一次输入 + 持久化自动登录」；落地后前端删除
  实例发现链路（projectRoot / discover_backend / 本机实例按钮）。

## Archive

The three September 30 demand notes were implemented or aligned with the v2
catalog and Home browse contracts and are retained under `archived/` as
historical records. They are not additional API requirements.

New backend capability requests discovered during frontend work should be
added here only after checking the existing v2 endpoint contract. A request
must identify the owner, the normal user path, the missing response or
behavior, and whether a frontend-only projection is insufficient.
