# Agent Home 设计

## 状态

本文描述 Agent Home 的已确认目标边界与当前实施状态。代码已完成 `home:` 链接解析、仅含 `agent`/`skills` 的 effective 顶层目录、`home:agent@AGENT`、严格 skill frontmatter 与自动 metadata 目录、领域/动作 skill、带 operation recovery 的跨日 overlay、渐进资源与 top/prompt mount mutation、effective top search、Action Catalog mount reconciliation、`SKILL_MEMORY.md` 路径约束和 Runtime copy Trap。旧 `what`、`why`、`how` 命名空间已删除，不提供兼容 Link、双读或迁移 API。Home 已从 DailyLifecycleCoordinator 解耦，不再提供 active day/archive 业务 API。

Home 顶层内容、skill 和渐进资源在真正使用前透明物化到 `runtime/home`。Context 在每个 User Turn 开始时清空通用 Background，再由 Home provider 从 effective Home 提供自动 skill metadata 目录、不可逐出的默认 core、effective 存在时同样不可逐出的 allowlisted Context/user Agent Top 正文，以及内部可加载顶层目录；Phase1 临时加载项不跨 Turn 保留。普通 Turn 的编辑只落到跨日保留的 active overlay；skill 的 runtime 包额外维护自上次 Home Maintenance 以来有效的 `SKILL_MEMORY.md`。Home top search 已按 effective metadata 提供确定性候选和 LLM rerank fallback；Home Maintenance service 提供有界 diff snapshot 和 accept/reject/rewrite mutation，推理与任务编排属于 `tinysoul.maintenance.home`。

Stage 6.1 已将长期日期 Memory 整体移交给独立 `tinysoul.memory`。`tinysoul.home` 不再包含 Memory search、Maintenance、配置或 Link/path 映射，也不保留兼容 Link、双读或迁移 API。独立 Memory 设计见 `docs/design/memory.md`。

## 定位

Agent Home 模块负责 TinySoul 的持久化身份规约、用户偏好、通用技能和领域/动作技能。它是 `home:` 链接的唯一语义归属方，不是 `memory:` 链接或长期日期记忆的归属方。

Agent Home 不维护 Turn 内 Context 状态，不驱动 Loop，也不管理 workspace 或 Memory 文件。它向 User Context 提供 effective Home，向 Loop 提供领域 skill，向 Action 内部 LLM task 提供领域/动作 skill，并向 Action 提供普通 runtime mutation；Maintenance-owned actual Home provider 不属于 Home 主线。Home owner 只公开中性的 `HomeReviewService` 与 review/resolve/remove overlay 门面，不拥有 Maintenance task、reviewer、时钟、scheduler 或 Maintenance Turn。

## 设计目标

1. 明确区分顶层内容和渐进式资源。
2. actual Agent Home 在普通运行中只读，运行期修改落在跨日 active runtime overlay。
3. Context 只消费 Agent Home 提供的背景条目，不读取 home 文件树。
4. Loop 只依赖 `DomainSkillProvider` 协议，不读取 skill 文件；Action 内部 LLM task 只依赖 `ActionSkillProvider` 协议。
5. skill 的目录结构由 Agent Home 解释，不泄漏到 AppBuilder。
6. Agent Home 运行时副本错误有明确 failure kind 和 Runtime bridge 映射。
7. Home Maintenance 作为独立 Program work 接入，不混入 User Turn 主线；Home 只提供中性 Review 能力，任务/Turn/Action 由 Maintenance 模块拥有。Memory 同样只提供 Consolidation owner 能力。

## 链接语义

Agent Home 定义三类 `home:` 链接：

```text
home:<space>@<relative-logical-path>
home:<space>/<relative-posix-path>
home:skills@<skill>
home:skills_domain:<domain>
home:skills_action:<domain>/<action>
```

`home:<space>@<relative-logical-path>` 表示 Agent 和通用 skill 顶层入口。Link 使用相对于对应 space 的无后缀逻辑路径；Agent 页面追加 `.md`，skill 映射目录中的固定入口是 `SKILL.md`。顶层内容可以加载为 BackgroundContext 条目。例如：

- `home:agent@AGENT`
- `home:agent@user/preferences`
- `home:skills@python_refactor`

`home:<space>/<relative-posix-path>` 表示渐进式资源，只能通过 action 读取或使用，读取结果进入 TurnTraceHeap。例如：

- `home:skills/python_refactor/references/checklist.md`
- `home:skills/python_refactor/scripts/inspect.py`

`home:skills_domain:<domain>` 与 `home:skills_action:<domain>/<action>` 表示框架局部自动 prompt mount，只进入对应 Phase/task prompt，不进入 BackgroundContext，也不作为 `home.resource.read` 的渐进式资源。例如：

- `home:skills_domain:workspace`
- `home:skills_action:workspace/rewrite`
链接规则:

- 顶层 `space` 只能是 `agent` 和 `skills`；`skills_domain` 与 `skills_action` 只用于自动 prompt mount 链接；
- 所有 Top Link 的 `@` 后内容必须是无文件后缀的安全逻辑路径；skill 顶层 Link 必须使用单段 skill name；
- `skills_domain`/`skills_action` 是框架 mount identity，二者都不追加固定物理入口文件名；
- `/` 形式始终表示资源路径，不能被 Context 直接加载为背景；已经映射为 Agent Top Markdown 或 skill `SKILL.md` 的物理文件不得再通过 Resource Link 读取或修改；
- 渐进资源保留真实扩展名，例如 `.md`、`.py`；Workspace Link 同样保留资源的真实扩展名；
- 所有路径使用 POSIX `/` 分隔；
- 不允许空路径、绝对路径、盘符、反斜杠、`.` 或 `..` 段。
- `memory` 不是 Home space；`home:memory@...` 和 `home:memory/...` 都是非法 Home Link。

Agent Home 应提供 `HomeTopLink`、`HomeResourceLink` 与 `HomePromptMountLink` 或等价值对象，避免模块内部使用裸字符串判断链接类别。

## 内容空间

目标目录结构：

```text
home/
  agent/
    AGENT.md
    user/
    identity/
  skills/
    skill_name/
      SKILL.md
      references/
      scripts/
  skills_domain/
    domain_name/
      DOMAIN.md
  skills_action/
    domain_name/
      action_name.md

runtime/
  home/
    .tinysoul/
      home_overlay.json
    operations/
    agent/
    skills/
      skill_name/
        SKILL_MEMORY.md
    skills_domain/
    skills_action/
```

`runtime/home` 只包含自上次 Home Maintenance 以来实际物化、创建或删除的 Home 内容，不预建完整目录树，也不因 Business Day 变化而清空；上图中的内容目录均为按需出现。`SKILL_MEMORY.md` 只允许位于 `runtime/home/skills/<skill>/`，`skills_domain`/`skills_action` 不创建平行 memory 文件。长期 MEMORY 位于与 `home/` 平级的 `memory/`，不是 Home runtime 副本的例外分支。

顶层内容映射：

- `home:agent@AGENT` 映射到 `agent/AGENT.md`；
- `home:agent@user/preferences` 映射到 `agent/user/preferences.md`；
- `home:skills@skill_name` 映射到 `skills/skill_name/SKILL.md`；
- `home:skills_domain:domain_name` 作为 prompt mount 映射到 `skills_domain/domain_name/DOMAIN.md`；
- `home:skills_action:domain_name/action_name` 作为 prompt mount 映射到 `skills_action/domain_name/action_name.md`。

Skill 采用包目录形式。通用 skill 使用 `skills/<skill>/SKILL.md` 作为顶层入口，references、scripts 等是渐进式资源。每个 `SKILL.md` 必须以 YAML `---` frontmatter 开头，并且 frontmatter 只包含非空、单行、有界的 `title` 与 `description`；正文仍是 Phase1 按需加载的完整顶层内容。Home 使用 `PyYAML.safe_load` 在启动/reconcile、runtime 恢复和 top write/patch 边界统一解析，拒绝缺失 delimiter、未知字段、错误类型、超长或多行 metadata。skill 使用期间可以在 runtime 包内创建并读写 `SKILL_MEMORY.md`，记录自上次 Home Maintenance 以来的临时工作记忆、使用反馈和待 review 变化。它不进入 actual Home，也不作为长期 skill 文件直接合并。与 action domain 绑定的 domain skill 使用 `skills_domain/<domain>/DOMAIN.md`，由 Phase2 prompt 自动注入，并可在 Phase3 action-internal LLM task 中继续作为 domain 约束；domain 内 action skill 使用 `skills_action/<domain>/<action>.md`，由 Phase3 中带内部 LLM task 的 action 自动注入。`skills_domain` 与 `skills_action` 是框架局部自动加载机制，不属于模型通过 `home.resource.read` 按需渐进式加载的普通资源，不进入通用 skill metadata 目录，也不拥有 `SKILL_MEMORY.md`。

### 默认项目内容

package-owned 项目模板提供一组可编辑但不虚构额外能力的默认 Home：

```text
home/
  agent/AGENT.md
  agent/context/background.md
  agent/context/turn-trace.md
  agent/context/working.md
  agent/user/user.md
  skills/tinysoul-docs/SKILL.md
  skills/tinysoul-docs/references/use-tinysoul-context-and-link.md
```

core 作为简洁的身份、行为规约和前向 Top Link 索引；`agent/context/*` 分别说明 Background、TurnTrace、Working 与 Workspace 的稳定可见性、Link 去向和状态优先级；user 保存稳定用户事实；`tinysoul-docs` 是通用 skill，其详细使用说明是通过 `home.resource.read` 进入 TurnTrace 的真实 progressive reference。Context Agent Top 不复制 domain/action skill：它们不指导具体 action 选择或失败恢复。core 不静态宣称 Shell、Script、文档转换等具体能力是否可用；进入 Action Catalog 的能力可以拥有局部 domain/action skill，而实际启用状态仍由 capability 配置与 Action 装配决定。模板不声明 Backlink、Memory 片段检索等尚未实现的能力。默认内容的集成测试从 package template 初始化临时项目，不把仓库实际 `home/` 当成测试夹具。

默认 Home 的唯一源码位置是 `tinysoul/assets/project/home/`，并由 standard/development 两种初始化共享；仓库根不保留第二份 Home，config profile 也不得包含 Home 副本。新增或调整通用使用说明、domain/action 行为约束时，应在这里同步维护对应 AGENT/skills 文档，并继续遵守本设计的 Link、frontmatter、prompt mount 与渐进资源规则。Action Catalog 增删 domain/action 时必须审查共享默认 Home 中相关 skill 是否仍然真实；缺少可选 guidance 合法，但不得留下宣称不存在 action 的陈旧内容。

package template 与已初始化项目之间没有双向同步。项目运行中的 runtime Home 和 Home Maintenance 只更新该项目的 actual `home/`；它们既不会写回 assets，也不能成为默认内容的事实源。反之，wheel 升级后的模板变化也不会覆盖已有项目。默认 Home 变更必须通过 initializer/Context/Home 集成测试和 clean-source wheel 资源检查，新增更深目录或新文件类型时还要同步审查 setuptools package-data glob。

## Actual Home 与 Runtime Home

Agent Home 分为 actual Home 和跨日 runtime Home：

- actual Home 是已经通过 Maintenance 提交的长期资料库，普通 User Turn 中只读；
- runtime Home 是跨 Turn、跨 Business Day、跨重启保留的懒加载可写 overlay；
- Home Maintenance 直接比较 active runtime Home 与 actual Home，再决定 apply 或 discard。Memory Maintenance 操作独立 `memory/` root，不是 actual/runtime Home 规则的例外。

当 Home 顶层内容、渐进式资源或 prompt mount 被加载到运行期时，Agent Home 确保 runtime Home 中存在对应副本，并从统一 effective view 读取：runtime override 优先，runtime tombstone 隐藏 actual 内容，未物化内容回退 actual Home。语义检索可以只读取 effective metadata；一旦 Home 正文进入 BackgroundContext、skill 或 action result，就按链接建立 runtime record。所有普通可写操作只能落在 runtime Home。

runtime mutation 按链接类别拆分：

- 渐进式资源继续使用 `home.resource.read/write/patch/delete`；Top Markdown 和 skill `SKILL.md` 在 resource 入口统一拒绝，不存在同一物理文件的第二 Link；
- 顶层内容使用 `home.top.write/patch/delete`，允许在 runtime 创建不存在的顶层内容；新 skill 使用无后缀单段 Link 和严格 frontmatter；`home:agent@AGENT` 允许 write/patch 但禁止 delete；
- 自动 skill mount 使用 `home.prompt_mount.write/patch`；逻辑 prompt mount 由框架根据 Action Catalog 中定义的 domain/action 自动创建或删除，模型不直接 create/delete；
- 通用 skill 的 `SKILL_MEMORY.md` 是允许直接在 runtime 创建的特殊渐进资源；
- `memory:` 不是 Home mutation action 的合法参数，Home 不供助 Memory 的读写。

当前实现已将上述 mutation 全部注册到 Home action catalog。Action executor 只解析参数并映射局部结果/Runtime failure，链接映射、effective resolution 和实际 overlay mutation 仍由 `AgentHomeEngine` 统一负责。

运行时副本准备有两种入口：

1. Home 门面在需要可写副本时同步确保副本存在；
2. 操作边界发现需要全局恢复时，通过 `HOME_RUNTIME_COPY_REQUIRED` 进入 Trap，由 Home runtime copy handler 创建副本后重试当前 frame。

后一种入口用于保持与 Runtime 的 OS 风格陷入设计一致，尤其适合在 Phase 或 action 执行边界处理缺页式副本准备。

当前实现由 `HomeOverlayManager` 统一承担 copy、write、patch、delete 和 reconciliation。Manifest schema v2 不含 Business Day；每条记录包含 relative path、`copied/created/modified/deleted` state、actual baseline digest、runtime digest、size 与 mtime。Builder 在构建 Home 时恢复 operation、迁移 schema v1 并初始化或收养现有 runtime 文件。修改先写入 `.tinysoul/operations/<operation-id>` intent 和 staged bytes，再替换目标、提交 Manifest、清理 operation；若在替换后、Manifest 前退出，下次 initialization/reconciliation 按 digest 前滚。

Home overlay 的存在本身就是尚未提交的事实，不建立第二份 pending/workset/store。每日 Session/Workspace rollover 已保证不移动、清空或重新初始化 `runtime/home`。

Overlay manager 使用进程内 `RLock` 串行化同一 Engine 的读写。纯 `copied` 文件丢失且 actual 仍等于 baseline 时可以确定性重建；modified/created 文件丢失、tombstone 路径重现或 Manifest/operation 状态歧义均属于不变量失败。actual baseline 后续变化不是自动覆盖理由，Home Maintenance 应基于 baseline、runtime 和当前 actual 内容形成明确 review 输入。runtime copy handler 只有在调用前 runtime 文件确实缺失、调用后完成物化时才返回一次 RETRY；文件已经存在却再次请求缺页时直接结束最近 Turn，避免无上限重试。

actual Home 严格位于 `home/`，runtime Home 严格位于 `runtime/home/`。`home:agent@AGENT` 只映射 `home/agent/AGENT.md` 到 `runtime/home/agent/AGENT.md`；项目根 `AGENT.md` 是仓库开发规约，不属于运行时 Agent Home，也不存在 fallback。

## BackgroundContext 接入

BackgroundContext 是 Context-owned 的通用 Phase1 Background，不是 Home Background。Agent Home 通过 `HomeBackgroundEntryProvider` 向 Context 提供 Home-owned 目录与正文，而不是让 Context 读文件。provider 每次返回：

- 默认加载条目；
- 可由 Phase1 加载的顶层条目；
- 全部 effective skill 的 Link、frontmatter title 与 description；
- 每个条目的 `home:*@` 链接和渲染文本。

`ContextEngine.begin_turn` 会清空上一 Turn 的通用 Background；Turn preparation 在首个 Cycle 前重新读取全部 provider，原子组装 Home skill metadata 目录、必须存在的默认 core、effective 存在时的 allowlisted `agent/context/*` 与 user，以及其它模块的自动条目。默认 Agent Top 都不可逐出；除 core 外的 allowlisted 文件缺失或被 effective tombstone 隐藏时正常省略，因此旧项目不会因模板新增 Context 页面而启动失败。白名单是框架显式定义，不自动包含任意其它 Agent Top。skill metadata 目录自动且不可逐出，使 Phase1 能先判断应加载哪个 `home:skills@skill`；它不是 skill 正文、不是一个伪造的 Home top Link，也不把 skill body 物化到 runtime。`home.skill_catalog_max_chars` 限制完整目录，超过上限显式失败，不截断 description、不丢弃条目。runtime 中创建、修改或 tombstone 的 skill 在下一个 Turn 的 effective 目录中反映。Home provider 不解释 Memory 日期，也不决定非 Home entry 的逐出政策。Phase1 加载项只存在于当前 Turn，跨 Turn 信息必须进入 Session、actual/runtime Home 或 Memory 持久事实。静态 `link + content` 仍供测试或嵌入方使用，但不能与动态 provider 重复注册同一链接。

Control Tool 的 `load_background` 和 `evict_background` 仍属于 Context 语义。`load_background` 的 `links` 是开放字符串数组，一次可以请求一个或多个 Top Link；工具 schema 不枚举完整 effective top catalog。模型应从当前 Context 已经暴露的默认 Agent Top 前向 Link、skill metadata、Home search 或 ActionResult 取得 Link，工具定义至多强化这些已有提示。Context 不扫描 Markdown 建立第二套 Link provenance 状态，而是在提交前使用 provider 的内部 effective catalog 校验每个 Link 是否真实可加载。模型选择合法顶层链接后，Context 通过已注入的 Home loader 获取文本，不解释 Home 路径；loader 触发的 runtime copy 对模型、ControlResult 和最终 Context 状态透明。

## Domain/Action Skill 接入

Loop 只依赖 `DomainSkillProvider` 协议，不读取 skill 文件。Agent Home 提供 `HomeDomainSkillProvider`，接收 Phase1 已选择的 action domain，映射为 `home:skills_domain:<domain>`，读取对应 `DOMAIN.md` 并返回适合 Phase2 task prompt 的短文本片段。

Action 内部 LLM task 只依赖 `ActionSkillProvider` 协议，不读取 Home 文件。Agent Home 提供 `HomeActionSkillProvider`，接收 `domain` 与 `action_name`，分别映射为 `home:skills_domain:<domain>` 与 `home:skills_action:<domain>/<action>`。这两类内容只注入 Phase3 action 内部嵌套 LLM task，用于延续 domain 约束，并约束具体 action 的文本风格、生成策略或领域动作细节。

运行规约按稳定职责分层维护。`home:agent@AGENT` 只承载跨能力通用原则，例如每个 Cycle 应推进用户目标、结构化失败必须按 scope/disposition 有界恢复、权威 mutation/apply 结果与必要验证的边界、Phase1 即时对账 WorkingContext，以及目标完成后及时执行唯一 `core.answer`。同一 reason/scope 的 `retry_same` 最多允许一次不变重试；所谓 fallback 必须改变真实 backend、输出协议或限制条件，不能只换 action 名称/domain。domain skill 只解释同一 action domain 内的选择、恢复和收束方式，例如 Workspace 工件失败、Web failure disposition 或 Shell apply/discard。action skill 只约束一个带内部 LLM task 的具体 action，例如 `workspace.write/rewrite` 对完整文本工件、截断输入、证据、结构保留和用户可见引用的要求。具体 capability/action 规则不得反向堆入 core，通用原则也不应在每个 action skill 中重复维护。

这些内容属于模型决策与生成约束，不是第二套 Loop 状态机、Action hook 或自动重试器。core 不接收剩余 Cycle 数，skill 不直接执行 action，也不根据文本改变 Runtime 控制流。需要硬保证的 schema、deadline、事务提交、取消和失败类型仍由 Action、Workspace、Web、supervised process 与 Loop 的代码协议负责；skill 只帮助模型在这些结构化结果之上选择有效下一步。

Domain skill 与 action skill 分别属于 `skills_domain` 与 `skills_action` 的局部自动加载机制：Phase2 自动加载 domain skill；Phase3 中带内部 LLM task 的 action 同时自动加载 domain skill 与 action skill。它们不属于普通渐进式资源加载；模型不需要通过 `home.resource.read` 主动读取这些 skill，Loop 与 Action 也不感知 Agent Home 的目录结构。

逻辑 prompt mount 由框架从 Action Catalog 派生：catalog 中定义的 domain/action 决定合法 `HomePromptMountLink`，不以 provider 暂时不可用或 action 临时 disabled 作为删除依据。对应 actual/runtime 正文都不存在时 provider 返回空 guidance；`home.prompt_mount.write` 可以为合法 mount 物化 runtime 内容，`home.prompt_mount.patch` 修改已有 effective 内容。domain/action 从 catalog 删除时，框架在 runtime 形成对应删除语义，下一次 Home Maintenance 决定 actual 删除；模型不拥有 prompt mount create/delete action。文件存在但编码损坏、不可读或映射不变量失败时，不得伪装成“没有 skill”，而应由 Home provider 通过 Runtime bridge 映射为模块边界失败。副本缺失仍使用专门的 runtime-copy 恢复原因。

## Progressive Resource Actions

渐进式资源不进入 BackgroundContext。需要读取或编辑时，应通过 action 完成。

当前已实现的 action：

- `home.resource.read`：读取 `home:*/` 渐进式资源的 runtime 副本文本前缀，按 `max_chars` 或配置上限返回文本片段，并在 action local result 中表达参数和读取失败；副本缺失时通过 Runtime Trap 建立副本后重试。读取实现只读取上限后的一个额外字符来判断截断，不先把完整文件读入内存；任何 Top Markdown 或 skill `SKILL.md` 的物理别名在解析后立即拒绝。
- `home.resource.write`：在 active overlay 创建 runtime-only 文本，或在显式 `overwrite` 和可选 `expected_digest` 前置条件下替换 effective 内容；
- `home.resource.patch`：对 effective UTF-8 文本执行唯一 `old_text` 精确替换，校验 digest 与完整结果的 `max_write_chars`；
- `home.resource.delete`：写入 tombstone 隐藏资源，不删除 actual Home。
- `home.top.write/patch/delete`：修改 Home 顶层 runtime 内容；新 skill 使用无后缀单段 Link 和严格 frontmatter，`home:agent@AGENT` 可 write/patch 但拒绝 delete；
- `home.prompt_mount.write/patch`：只修改由 Action Catalog 定义的合法 domain/action mount；逻辑 create/delete 仍由框架 reconciliation 负责；
- 通用 skill 的 `SKILL_MEMORY.md` 通过 resource action 读写，只允许 `runtime/home/skills/<skill>/SKILL_MEMORY.md` 且对应 effective skill 必须存在；actual Home 和其它空间的平行 memory 文件在装配/reconciliation 时被拒绝。

## Home Top Search

`home.top.search` 只检索通用 skill，不检索默认注入的 `agent` core，也不检索局部自动挂载的 `skills_domain`/`skills_action` 或任何 MEMORY。Engine 先按统一 effective view 解析每个 Home 顶层 Link：未物化 actual 条目直接有界读取 actual prefix，runtime-only 或 modified 条目读取现有 runtime 文件，tombstone 不进入目录。这个过程不创建 runtime copy、overlay record 或 Background entry。

Home-owned `search.py` 从有界 effective skill 文档构造 metadata，严格复用 frontmatter `title`/`description`。digest 标识完整 effective 文件。确定性评分同时考虑 link、name、title、description 和 searchable prefix，并按 `score desc, link asc` 稳定排序。`home.search.candidate_limit` 默认 20；`default_top_k` 默认 5；`max_top_k` 默认 10。目录未超过候选上限时，词法零分条目仍保留给语义 rerank，避免小型 Home 因同义表达被提前丢弃。

候选通过 JSON-only `home_search` profile 交给受控 LLM task，模型只返回候选内唯一 Link，也可以用空列表明确表示无匹配。Task failure、非 JSON、额外字段、重复 Link、超出 `top_k` 或候选外 Link 都不形成搜索失败，而是回退确定性顺序并标记 `reranked=false`；合法空列表返回空 items 且 `reranked=true`。action result 只返回 query、候选计数、rerank 标记和每项 link/space/title/summary/digest/score，不返回 searchable prefix 或完整正文，也不自动加载结果到 Background。模型后续仍须显式加载选中的顶层 Link。

search 的 Home Link 和 effective overlay 规则属于 Agent Home；Infra 不解释这些业务概念。Memory search/recall 与 consolidation 属于 `tinysoul.memory`，不复用 Home catalog 解释日期资源。

普通 mutation 冲突和 patch 不适用收敛为局部 ActionResult；overlay 图损坏等不变量经 Home bridge 进入 Runtime，不降级为普通模型反馈。成功修改只返回 link、state、digest、baseline digest 和 size，不返回完整新正文。actual Home 内容只允许由 Home Maintenance 修改；Memory Maintenance 不经 Home mutation 或 Home overlay 写入。

## Maintenance

Home Maintenance 是 `tinysoul.maintenance.home` 拥有的自治任务。它由 MaintenanceEngine 计划，通过独立 Maintenance Turn 在完整 Background/Session/Workspace 情景中逐项处理 runtime Home diff。scheduler、Terminal 和 Endpoint 只投递 MaintenanceRequest，不直接调用 Home；手动与定时触发使用同一任务路径，不等待人工审批。

### Home Maintenance

Home owner 的 diff 输入只包括当前 active `runtime/home`、actual Home，以及 runtime skill 包中的 `SKILL_MEMORY.md`。Maintenance Turn 的 Context 另外使用 actual Home Background，并由 task preparation 注入当前 Session 和 Workspace；Home 模块本身不读取 Session/Workspace，也不创建 Home archive、workset、Settlement root 或持久 review 状态。

一次任务从当前事实动态构造 snapshot，并通过 owner-bound actions 处理：

1. `copied` 表示仅物化而未被 Agent 修改，无论当前 actual 是否已经变化，都不应把旧 runtime 副本写回；Maintenance 直接清理该 runtime record/content；
2. `maintenance.home.list/inspect` 向 Maintenance Turn 提供 token、Link、state、digest 和有界 before/after 内容；token 绑定当前 snapshot，actual/runtime 任一变化都会使旧 token 失效；
3. `maintenance.home.accept` 将 runtime 版本原子提交到 actual，`reject` 保留 current actual，`rewrite` 把 Turn 给出的整理正文原子写入 actual；三种 resolution 都在成功后清除对应 runtime record/content；skill rewrite 在写入前重新校验 frontmatter，非法正文保持 actual 和 review 不变；
4. `SKILL_MEMORY.md` 是独立的 `skill_review`，不是普通 diff 的附件；`inspect` 返回 actual skill 和临时记忆，只有 inspect 后才能 `reject`/`rewrite`，对应 skill 处理完成后清空；
5. `maintenance.complete` 只有在 snapshot 和 pending 事实均无未处理项时成功；Turn 结束后 controller 再调用 `remove_resolved_overlay()`，校验 runtime root 只含空 overlay 元数据并整体移除 `runtime/home`；
6. 下一次 Home 访问发现 runtime root 不存在时重新初始化 overlay，并按需从 actual 懒加载。

Home Maintenance 与 User Turn 由 Program 单写者边界串行化。未触发或任务失败时，尚未处理的 overlay 原样跨 Turn、跨日、跨重启保留；已完成的单项 resolution 不回滚。若中断发生在 actual 写入之后、runtime 清理之前，下一次 snapshot 根据 runtime/actual 已一致事实完成确定性清理，不需要持久 review decision。

`HomeReviewService` 不调用 LLM、不读取 stdin、不解释自动或手动模式。Maintenance Turn 的推理失败形成 Home task outcome；Home owner 只维护 `review_snapshot`、`resolve_review`、`review_pending` 和 `remove_resolved_overlay` 契约。事件和 outcome 只携带 Link、state、resolution、digest、计数和稳定错误类型，不包含完整正文、diff、reasoning 或绝对路径。

## 与 Workspace 的关系

Agent Home 和 Workspace 都基于链接和相对路径，但语义边界不同：

- Agent Home 管理持久化身份规约、知识和技能；长期日期记忆由 Memory 管理；
- Workspace 管理当日任务资源和产物；
- Home 文档可以引用 `workspace:` 链接，但不解析 workspace 路径；
- Workspace action 可以生成 `home:` 链接作为参考，但不读取 home 文件；
- 两者共享 infra 的路径和文件基础能力，不互相绕过门面读写。

跨模块协作应通过 action、link、context signal 和 builder 注入完成。

## 失败与 Runtime 桥接

Agent Home 失败分三层：

1. 局部 action result：链接不存在、链接类别不适用于当前 mutation、skill frontmatter 不合法、core delete、文件过大、写入冲突、patch 不适用；
2. 模块边界异常：home root 不可用、已有内容无法按 UTF-8 解释、链接映射不变量破坏、runtime copy 缺失且无法本地修复、索引损坏、配置不可解释；
3. Runtime 语义异常：启动配置失败映射为 `runtime.startup_failed`，User Turn 中不可继续失败默认映射为 `runtime.turn_end`，运行时副本准备映射为 `home.runtime_copy_required`；Home Maintenance failure 结束对应 maintenance task，不伪装为 User Turn failure。

Agent Home 应定义 `AgentHomeFailureKind`，并通过 `tinysoul/runtime/bridge/` 下的专门 bridge 转换为 Runtime 通用原因。`home.runtime_copy_required` 的 payload 应包含 `link`、`source_path`、`runtime_path`、`error_type` 和模块失败类型等摘要，不包含文件正文。Home 配置错误应由 home bridge 映射为 `runtime.startup_failed`，而不是落入 infra 或 app 的兜底失败。

当 Home action 或 provider 需要通过 Runtime 触发 copy handler 时，action runner 必须允许 `RuntimeException` 穿透到 Loop/Trap，而不是把它吞成普通 `ActionResult`。

## 组装入口

当前目录：

```text
tinysoul/home/
  __init__.py
  engine.py
  config.py
  links.py
  layout.py
  overlay.py
  search.py
  review.py
  runtime_copy.py
  guidance.py
  actions.py
  errors.py
  failures.py
```

`AgentHomeEngine` 是普通 User Turn 与 Maintenance 的 Home 门面，提供链接解析、effective/actual 顶层目录、effective read、runtime mutation、overlay reconciliation、top search、domain/action skill、Maintenance snapshot/resolution 和 finalize。`HomeOverlayManager` 只管理跨日 active overlay record 与 operation recovery，不提供 Business Day/archive 或 LLM policy。`HomeTopSearchService` 只消费 Engine 交付的 bounded effective documents，不重复解释 overlay；`AgentHomeEngineBuilder` 负责接收已解析设置、校验目录并装配这些服务。不建立 Settlement store，也不把 Maintenance Turn 编排放进 Home。

AppBuilder 的目标职责是：

1. 构建 AgentHomeEngine；
2. 将 `HomeBackgroundEntryProvider` 交给 ContextEngineBuilder，不在启动时读取或物化 core；
3. 将 HomeDomainSkillProvider 注入 Phase2Unit，并将 HomeActionSkillProvider 注入 LLM action executor；
4. 将 Home action handler 注册到 ActionEngineBuilder，并向 search executor 注入 `LLMHomeSearchReranker`；
5. 注册 home runtime copy Trap handler；
6. 为 Maintenance Context 注入 `ActualHomeBackgroundEntryProvider`，为 Home Maintenance task 注册 owner-bound actions；
7. 不直接读取 `AGENT.md`、skill 文件，也不读取 Memory 文件。

## 测试与验收

验收点：

- AppBuilder 不直接读取 `home/agent/AGENT.md`，项目根 `AGENT.md` 不参与 Home 映射；
- Context 默认背景来自 Agent Home 门面；
- `DomainSkillProvider` 能从 `home:skills_domain:domain` 获取 domain skill；`ActionSkillProvider` 能从 `home:skills_domain:domain` 与 `home:skills_action:<domain>/<action>` 获取 domain/action skill；
- `home:*@` 与 `home:*/` 链接解析和越界防护有单元测试；
- runtime home 显式副本准备行为有单元测试；
- 每个 User Turn 的 preparation 通过动态 provider 重建默认 core 与 effective 存在时的 allowlisted Context/user Agent Top；其它背景在 Context Module frame 中按需复制并重放同一 signal batch；
- `home:agent@AGENT` 的 runtime 副本位置稳定为 `agent/AGENT.md`；
- `home.resource.read` 不写入 BackgroundContext，并返回有界文本；write/patch/delete 只修改 active overlay，actual Home 保持零写入；
- `home.top.write/patch/delete` 只修改 runtime；skill create 要求严格 frontmatter，core delete 被拒绝；
- `home.top.search` 只返回 effective skill metadata；actual 搜索不物化，runtime-only 可见，tombstone 不可见，非法 rerank 确定性回退；
- prompt mount 由 Action Catalog 自动维护逻辑生命周期，模型只通过 write/patch 修改 runtime；
- `HOME_RUNTIME_COPY_REQUIRED` trap handler 能准备副本并重试当前 frame；
- Agent Home 的配置错误、索引损坏和 runtime copy 失败经专门 bridge 映射；
- Home parser/catalog 拒绝 `memory` space 和 `home:memory@...`；runtime-only Home 内容、tombstone 和 operation recovery 跨日、跨重启保持；
- 只有通用 skill runtime 包拥有 `SKILL_MEMORY.md`，跨 Turn/跨日可读写且 Home Maintenance 后清空；
- Home Maintenance 不创建 archive 或持久状态，accept/reject/rewrite 后清理 active overlay record，全部解决后移除空 runtime Home，中断后通过仍存在的 active diff 重算；
- Home Maintenance 对顶层 `memory/` 零读写，Memory Maintenance 验收归独立 Memory 模块；
- 每日日切不移动、清空或重新初始化 runtime Home，也不改变普通 User Turn 的三阶段主流程。

当前测试覆盖 Home actual write、三种 resolution、stale token、overlay cleanup、空 runtime Home 移除与下一次访问重建；Maintenance task/action/Turn 的完整编排由 `tests/maintenance` 与 AppBuilder 测试覆盖。
