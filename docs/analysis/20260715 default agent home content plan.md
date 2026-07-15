# 20260715 Default Agent Home Content Plan

## 状态

status: pending

依赖：Stage 8 发布与初始化闭环完成。

## 目标

在运行机制稳定后，统一撰写随项目模板发布的完整默认 Agent Home。该工作只负责可编辑内容及其内在链接，不修改 Home overlay、Context Background、Memory、Maintenance 或 Action Catalog 机制。

默认 Home 应让新项目中的 Agent 从 `home:agent@core` 理解以下稳定语义，并能通过顶层 Link 渐进加载细节：

1. User Turn、Agent Cycle、Phase、Action、Context 与 Maintenance 的职责和关系；
2. `home:space@name` 顶层 Link、`home:space/path` 渐进资源、`memory:YYYY-MM-DD`、`workspace:` 与 prompt mount Link 的差异；
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

## 设计检查

实施前先逐项复核：

1. `home/agent/AGENT.md` 只保留稳定行为规约，避免复制框架开发文档；
2. 每个顶层 Link 都能映射到真实 effective Home 内容，正文中的 Link 均通过存在性检查；
3. HOW frontmatter 描述足以帮助 Phase1 决定是否加载正文，但不把完整流程塞入 description；
4. 内容不暗示 Home 拥有 Memory、Background 或 Daily archive；
5. 模板示例可由用户直接修改，不依赖 TinySoul 源码仓库路径。

## 验收

- package template 与源码示例使用同一内容集合；
- 初始化项目后所有 Home Link、HOW frontmatter 和自动 skill catalog 均通过 Engine 启动校验；
- 新 Agent 仅凭 core 与 HOW metadata 能选择应加载的顶层内容；
- 文档没有失效 Link、重复定义或未实现能力声明。
