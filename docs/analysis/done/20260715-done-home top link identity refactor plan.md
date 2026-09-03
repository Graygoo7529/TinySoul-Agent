# 20260715 Home Top Link Identity Refactor Plan

## 状态

status: done

依赖：`20260715-done-default agent home content plan.md`。

## 目标

将 Home Top Link 统一为无格式后缀的逻辑身份，同时保持 actual/runtime Home 的 Markdown 文件路径、overlay manifest 和 operation journal 相对路径不变。该设计替代 Stage 8.1 中 Agent/WHAT/WHY Top Link 携带 `.md` 的选择，不改变 Memory、Workspace、progressive resource 或 prompt mount Link。

## 已确认语义

1. `home:*@...` 表示可进入 BackgroundContext 的 Top content identity；Agent、WHAT、WHY 和通用 HOW 的 `@` 后逻辑名称都不携带文件格式后缀；
2. `home:agent@AGENT` 映射 `agent/AGENT.md`，`home:agent@user/user` 映射 `agent/user/user.md`；
3. `home:what@entity/tiny-soul` 映射 `what/entity/tiny-soul.md`，WHAT 分类继续属于 Link；
4. `home:why@why-is-updating-home-important` 映射 `why/why-is-updating-home-important.md`；
5. `home:how@tinysoul-docs` 继续映射 `how/tinysoul-docs/SKILL.md`；
6. Home progressive resource 保留真实相对路径和扩展名，Memory 保留 `memory:YYYY-MM-DD.md`，Workspace 保留资源真实扩展名，`how_domain`/`how_action` 保留 framework identity；
7. 旧 `.md` Top Link 不提供 alias、双读或迁移入口；当前项目不承担历史兼容；
8. Top 物理 Markdown 文件不得再通过 `/` Resource Link 读取或修改，通用 HOW 的 `SKILL.md` 同样只能通过 `home:how@<skill>` 表达；
9. actual/runtime 文件、overlay record 与 operation journal 继续保存 `agent/AGENT.md` 等物理相对路径，不进行磁盘迁移。

## 映射

| canonical Top Link | actual/runtime relative path |
| --- | --- |
| `home:agent@AGENT` | `agent/AGENT.md` |
| `home:agent@user/user` | `agent/user/user.md` |
| `home:what@entity/<name>` | `what/entity/<name>.md` |
| `home:what@concept/<name>` | `what/concept/<name>.md` |
| `home:why@<question>` | `why/<question>.md` |
| `home:how@<skill>` | `how/<skill>/SKILL.md` |

正向映射只能由 `AgentHomeLayout.relative_for_top()` 追加物理文件名；反向映射只能由 `top_link_for_relative()` 移除最后一个 `.md` 或识别固定 `SKILL.md`。业务模块、Context、Action 和内容文件不得自行拼接后缀。

## 实施项

1. 收紧 `HomeTopLink`：所有 Top name 使用安全无后缀相对路径；WHAT 仍要求首段为 `entity` 或 `concept`；
2. 修改 `AgentHomeLayout` 的双向映射并增加 round-trip、冲突和非法旧 Link 测试；
3. 将 Top Resource alias 在 read/write/patch/delete 全部拒绝，HOW references 等真实 progressive resource 继续可用；
4. 更新 core/user 默认 Link、core delete guard、Home search、Memory validator、Action Catalog 示例、默认 Home、package template、Context labels 和测试；
5. 更新 `AGENT.md`、`docs/design/agent_home.md`、Context/Memory 设计文档和已完成默认 Home 计划的当前 canonical 示例；
6. 运行全量测试、`ty check`、wheel 隔离安装和默认 Home Link 存在性验证。

## 验收

- 所有模型可见 Home Top Link 均无 `.md`，且映射到原有物理 Markdown 文件；
- 旧 `.md` Top Link 明确失败，不作为 progressive resource 回退；
- Top 物理文件只有一个 canonical Link，Resource action 无法读取或修改；
- runtime overlay 与 actual Home 无物理迁移，既有相对路径 record 仍可解释；
- Memory/Workspace/progressive resource Link 格式不变；
- 默认 Home、初始化项目、wheel 和隔离测试全部使用新 Link。

## 实施结果

`HomeTopLink` 现统一拒绝带文件后缀的 Top name，WHAT 继续要求 `entity/` 或 `concept/` 分类。`AgentHomeLayout.relative_for_top()` 为 Agent/WHAT/WHY 逻辑路径追加 `.md`，通用 HOW 继续映射固定 `SKILL.md`；`top_link_for_relative()` 执行唯一反向映射并通过 round-trip 测试锁定双射。actual/runtime 文件、overlay manifest 和 operation journal 的相对路径均未迁移。

Home resource 入口在 read/write/patch/delete 前统一拒绝 Agent/WHAT/WHY Top Markdown 和通用 HOW `SKILL.md`，因此同一物理 Top 文件不再同时拥有 `@` 与 `/` 两个身份；HOW references、scripts 和 `SKILL_MEMORY.md` 等 progressive resource 保持原语义。

core/user defaults、Home search、Memory Home Link hints/validator、Action Catalog 示例、Context/Session/App 测试、默认 Home 与 package template 已全部迁移为无后缀 Top Link。Memory、Workspace、progressive resource 和 prompt mount Link 未改变。旧 `.md` Top Link 只保留在显式拒绝测试中，不提供 alias。全量测试、wheel 隔离构建/初始化、默认 Home 前向 Link 验证、源码/template 内容镜像和 `ty check` 均通过。
