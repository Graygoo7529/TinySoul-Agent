# 20260715 Default Agent Home Content Plan

## 状态

status: done

依赖：Stage 8 发布与初始化闭环完成。

## 目标

在运行机制稳定后，统一撰写随项目模板发布的完整默认 Agent Home，并收口默认 Agent/user Background 与 `load_background` 发现语义。该工作不修改 Home overlay、Memory、Maintenance 或 Action Catalog；Context 只做开放多 Link 参数的局部协议调整，Home provider 只增加已确认的 user 默认正文。

已确认语义：

1. `home:*@...` 只表示可进入 BackgroundContext 的顶层内容，不等于自动加载；
2. `home:agent@AGENT.md` 每 Turn 必须自动加载且不可逐出；effective `home:agent@user/user.md` 存在时同样自动加载且不可逐出，缺失或 tombstone 时正常省略；
3. 其它 Agent/WHAT/WHY/通用 HOW 顶层正文按需加载；全部通用 HOW 的 Link/title/description 继续自动进入 metadata catalog；
4. `load_background` 接受一个或多个开放字符串 Top Link，不把完整 effective top catalog 作为工具 schema `enum` 暴露；模型从当前 Context 的 core/user 前向 Link、HOW metadata、Home search 或 ActionResult 感知 Link，Context 在提交前仍校验 Link 属于当前 effective provider catalog；
5. Agent/WHAT/WHY 顶层 Link 继续保留真实 `.md` 文件名，`@` 已表达顶层知识入口；通用 HOW 保留无 `.md` 的框架 skill identity；
6. 默认内容测试必须在 `tmp_path` 初始化的独立项目或 synthetic Home 中运行，不读取或写入仓库根 actual `home/`/`runtime/home/`。

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
- `home/agent/user/user.md`：可由用户和 Agent 持续维护的稳定用户事实与偏好，存在时作为不可逐出的自动 Background 正文；
- `home/what/entity/tiny-soul.md` 与 `home/what/concept/`：真实 entity 定义，以及 Context/Link、Daily Lifecycle 等稳定概念；
- `home/why/why-is-updating-home-important.md`：直接以问题命名并说明一个重要设计或行为理由；
- `home/how/tinysoul-docs/SKILL.md`：包含严格 YAML `title`/`description` frontmatter，作为整体文档导航 skill；
- `home/how/tinysoul-docs/references/use-tinysoul-context-and-link.md`：由 HOW 正文前向链接的真实渐进式 reference，说明实际如何使用 Context 与各类 Link；
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
6. 本轮实现同时更新 package template 与仓库 `home/` 的初始内容，但 package template 是新项目默认内容的测试基线；仓库 actual Home 后续允许通过 Maintenance 演化，不建立长期字节相等测试；
7. `.md` 和 `.py` 渐进资源示例确实存在，不以失效 Link 充当说明。

## 验收

- 本轮 package template 与仓库 Home 初始内容同步；
- 初始化到独立临时项目后，所有 Home Link、HOW frontmatter 和自动 skill catalog 均通过 Engine 启动校验；
- 新 Agent 仅凭 core 与 HOW metadata 能选择应加载的顶层内容；
- 文档没有失效 Link、重复定义或未实现能力声明。

## 实施结果

Home provider 现将 core 与存在的 effective `home:agent@user/user.md` 作为每 Turn 自动且不可逐出的默认正文；user 缺失或 tombstone 时只保留 core。`load_background.links` 保持数组并改为开放字符串，一次可以加载多个 Top content，工具 schema 不再把完整 effective top catalog 暴露为 `enum`；现有 Context signal transaction 在提交前继续依据内部 provider catalog 校验每个 Link。

默认 Home 已建立 core、user、TinySoul entity、Context/Link 与 Daily Lifecycle concept、问题式 WHY、`tinysoul-docs` 通用 HOW，以及真实 `use-tinysoul-context-and-link.md` progressive reference。Agent/WHAT/WHY Link 继续保留 `.md`，通用 HOW 继续使用无后缀框架 identity。仓库 Home 与 package template 在本轮同步，但只有 package template 是新项目默认内容的长期测试基线。

默认内容集成测试通过 `ProjectInitializer` 安装到 `tmp_path` 后构建 Home/Context，验证全部前向 Link、progressive resource、HOW metadata、自动 core/user、初始正文可见性、开放多 Link load 和搜索结果；Home/Context 单元测试继续使用 synthetic Home，不依赖仓库 root。package-data 已补充嵌套 Agent 文档、HOW references 和 scripts 规则，wheel 隔离安装可以保留完整 skill 包。全量测试、wheel 验证与 `ty check` 均通过。
