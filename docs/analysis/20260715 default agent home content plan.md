# 20260715 Default Agent Home Content Plan

## 状态

status: pending

依赖：Stage 8 发布与初始化闭环完成。

## 目标

在运行机制稳定后，统一撰写随项目模板发布的完整默认 Agent Home。该工作只负责可编辑内容及其内在链接，不修改 Home overlay、Context Background、Memory、Maintenance 或 Action Catalog 机制。

默认 Home 应让新项目中的 Agent 从 `home:agent@AGENT.md` 理解以下稳定语义，并能通过顶层 Link 渐进加载细节：

1. User Turn、Agent Cycle、Phase、Action、Context 与 Maintenance 的职责和关系；
2. 带真实文件路径的 Agent/WHAT/WHY 顶层 Link、保留框架 identity 的通用 HOW/prompt mount Link、`home:space/path` 渐进资源、`memory:YYYY-MM-DD.md` 与 `workspace:` 的差异；
3. actual Home、跨日 `runtime/home` effective view、Home Maintenance 和 runtime-only `SKILL_MEMORY.md`；
4. WHAT 的 entity/concept 分类、WHY 的问题解释、通用 HOW 的使用条件和按需加载方式；
5. Daily rollover、Home Maintenance、Memory Maintenance 相互独立的生命周期；
6. 工具结果进入 TurnTrace、顶层正文进入 Background、局部 HOW 进入 task prompt 的语境边界。

## 内容组织

计划中的模板内容至少包括：

- `home/agent/AGENT.md`：简洁的核心身份、行为规则、Link 使用规则和顶层内容索引；
- `home/what/entity/`、`home/what/concept/`：各一个真实且互不混淆的示例；
- `home/why/`：说明一个重要设计或行为理由的示例；
- `home/how/<skill>/SKILL.md`：包含严格 YAML `title`/`description` frontmatter、适用条件、流程和相关 Link；
- 必要的 `references/` 或 `scripts/` 渐进资源，但不创建仅作占位的目录或文件。

## 规范 Link 与物理文件

默认 Home 正文必须使用以下 canonical 形式，不提供旧 Link 别名：

| 内容 | canonical Link | actual 文件 |
| --- | --- | --- |
| Agent core | `home:agent@AGENT.md` | `home/agent/AGENT.md` |
| Agent user | `home:agent@user/user.md` | `home/agent/user/user.md` |
| WHAT entity | `home:what@entity/<name>.md` | `home/what/entity/<name>.md` |
| WHAT concept | `home:what@concept/<name>.md` | `home/what/concept/<name>.md` |
| WHY | `home:why@<name>.md` | `home/why/<name>.md` |
| 通用 HOW | `home:how@<skill>` | `home/how/<skill>/SKILL.md` |
| HOW 渐进文档 | `home:how/<skill>/references/<name>.md` | 同 Link 相对路径 |
| HOW 渐进脚本 | `home:how/<skill>/scripts/<name>.py` | 同 Link 相对路径 |
| Memory | `memory:YYYY-MM-DD.md` | `memory/yyyy/mm/yyyy-mm-dd.md` |
| Workspace | `workspace:<relative-path.ext>` | 当日 Workspace 中的同名资源 |
| Domain/action HOW | `home:how_domain:<domain>` / `home:how_action:<domain>/<action>` | 框架固定 mount 文件 |

Agent、WHAT、WHY、Memory 与直接资源 Link 保留真实叶文件名或资源扩展名；通用 HOW 与 prompt mount 是有意保留的框架 identity，因为其入口文件名由框架固定。项目根 `AGENT.md` 是 TinySoul 仓库开发规约，不是 `home:agent@AGENT.md` 的 fallback。

WHAT 分类直接属于 Link。`home.top.write` 创建 WHAT 时使用 `entity/` 或 `concept/` 路径，不再额外提供 `what_kind`；entity 与 concept 中的同名文档可并存。

Backlink 属于尚未实现的能力扩展。默认 Home 可以建立前向 Link，但在 Backlink action 实施前不得向 Agent 声称可执行反向查询。

## 设计检查

实施前先逐项复核：

1. `home/agent/AGENT.md` 只保留稳定行为规约，避免复制框架开发文档；
2. 每个顶层 Link 都能映射到真实 effective Home 内容，正文中的 Link 均通过存在性检查；
3. HOW frontmatter 描述足以帮助 Phase1 决定是否加载正文，但不把完整流程塞入 description；
4. 内容不暗示 Home 拥有 Memory、Background 或 Daily archive；
5. 模板示例可由用户直接修改，不依赖 TinySoul 源码仓库路径；
6. package template 与仓库 `home/` 使用同一内容集合，不能只更新其中一份；
7. `.md` 和 `.py` 渐进资源示例确实存在，不以失效 Link 充当说明。

## 验收

- package template 与源码示例使用同一内容集合；
- 初始化项目后所有 Home Link、HOW frontmatter 和自动 skill catalog 均通过 Engine 启动校验；
- 新 Agent 仅凭 core 与 HOW metadata 能选择应加载的顶层内容；
- 文档没有失效 Link、重复定义或未实现能力声明。
