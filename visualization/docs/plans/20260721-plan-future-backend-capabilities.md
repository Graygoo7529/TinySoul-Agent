# 20260721 Plan：未来后端能力扩展（前端视角）

> 状态：计划/待评估  
> 责任范围：前端（`visualization/`）；所列接口需后端 owner 评估后提供。

本文档承接原 `visualization/docs/missing-capabilities.md` 中尚未进入近期实施计划的能力。它们不是当前前端正常运行的必要前提，但可作为后续功能扩展的候选。

## Home / Agent Knowledge 主动浏览

当前 Background Context 面板只能展示 Phase1 已加载的 top links。若希望用户在不发起 User Turn 的情况下主动浏览 Agent Home，需要后端暴露：

- `GET /v1/home/catalog`
  - 列出 effective top-level Home 条目（agent、skills）。
  - 返回字段至少包含：Link、title、description、owner、是否可加载到 Background。
- `GET /v1/home/resource?link=home:...`
  - 按 Link 读取 Home 资源正文（受上限约束）。
- `GET /v1/home/search?q=...`
  - 搜索通用 Skill metadata，返回有界候选列表。

前端用途：新增独立 “Home” 浏览面板，支持查看、搜索，并可选地将条目加载到 Background Context。

## Instance Capability Metadata

当前 `GET /v1/status` 返回 identity、active day、turn active、revisions、event sequence 和 maintenance pending。若前端需要根据后端实际启用的 domain/action 动态隐藏或禁用控件，需要 status 额外返回：

- `capabilities`：当前 effective Action Catalog 中可用的 domain/action 列表。
- 或 `domains`：已启用的 domain 名称集合，以及每个 domain 下的 action 名称。

前端用途：在 Workspace 工具栏、Maintenance 入口、Settings 等处禁用不可用的功能按钮。

## 评估建议

- Home 浏览属于知识管理增强功能，建议在工作区 Markdown 编辑器稳定后再评估优先级。
- Capability metadata 属于通用性较强的基础能力，可在任何需要动态 UI 的阶段优先实现。
- 实施前需与后端 owner 确认：
  - 接口 schema、鉴权、size limit、错误码；
  - Home catalog 是否包含 `home:agent@AGENT` 等不可逐出项；
  - Capability manifest 只需要暴露 effective domain/action identity，不暴露
    `skills_domain` / `skills_action` 等框架内部 prompt mount。
