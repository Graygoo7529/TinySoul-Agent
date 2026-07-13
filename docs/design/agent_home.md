# Agent Home 设计

## 状态

本文描述 Agent Home 模块的当前设计。代码已完成 `home:` 链接解析、动态 effective 顶层目录、`home:agent@core`、domain/action HOW、年月 MEMORY actual-read、带 operation recovery 的 schema v2 跨日 overlay、schema v1 原地迁移、渐进资源与 top/prompt mount mutation、Action Catalog mount reconciliation、`SKILL_MEMORY.md` 路径约束和 Runtime copy Trap。Home 已从 DailyLifecycleCoordinator 解耦，不再提供 active day/archive 业务 API。

非 MEMORY 顶层内容、HOW 和渐进资源在真正使用前透明物化到 `runtime/home`；MEMORY 始终读取 actual Home，不进入 overlay。Context 在每个 User Turn 开始时清空 Home Background，再由动态 provider 从 effective Home 重建默认项，Phase1 临时加载项不跨 Turn 保留。普通 Turn 的编辑只落到跨日保留的 active overlay；通用 HOW 的 runtime 包额外维护自上次 Home Maintenance 以来有效的 `SKILL_MEMORY.md`。Home Maintenance service 已直接 review active overlay 并写回 actual Home；Memory Maintenance 将独立读取指定日期 Session archive 和可选同日期旧 MEMORY。Home top search、Memory Maintenance 和 Program/App 调度入口仍未实现。

## 定位

Agent Home 模块负责 TinySoul 的持久化语境资源，包括身份规约、用户偏好、知识、技能、行动域 HOW 和长期记忆。它是 `home:` 链接的唯一语义归属方。

Agent Home 不维护 Turn 内 Context 状态，不驱动 Loop，也不管理 workspace 文件。它向 Context 提供动态顶层目录与内容 provider，向 Loop 提供 domain HOW，向 Action 内部 LLM task 提供 action HOW，并向 Action 提供 Home mutation 门面。Home-owned reviewer/consolidator 可以调用明确的 LLM Task，但调度属于 Loop。Agent Home 只负责跨日 active overlay、effective view、Home Maintenance apply 和长期 MEMORY 写入，不参与 Session/Workspace 的每日归档。

## 设计目标

1. 明确区分顶层内容和渐进式资源。
2. actual Agent Home 在普通运行中只读，运行期修改落在跨日 active runtime overlay。
3. Context 只消费 Agent Home 提供的背景条目，不读取 home 文件树。
4. Loop 只依赖 `DomainHowProvider` 协议，不读取 HOW 文件；Action 内部 LLM task 只依赖 `ActionHowProvider` 协议。
5. HOW、WHAT、WHY、MEMORY 的目录结构由 Agent Home 解释，不泄漏到 AppBuilder。
6. Agent Home 运行时副本错误有明确 failure kind 和 Runtime bridge 映射。
7. Home Maintenance 与 Memory Maintenance 作为可独立触发的 Program work 接入，不混入 User Turn 的 Phase 主链路。

## 链接语义

Agent Home 定义三类 `home:` 链接：

```text
home:<space>@<name>
home:<space>/<relative-posix-path>
home:how_domain:<domain>
home:how_action:<domain>/<action>
```

`home:<space>@<name>` 表示顶层知识入口。顶层内容可以加载为 BackgroundContext 条目。例如：

- `home:agent@core`
- `home:agent@user/preferences`
- `home:what@tinysoul`
- `home:why@context_budget`
- `home:how@python_refactor`
- `home:memory@2026-07-07`

`home:<space>/<relative-posix-path>` 表示渐进式资源，只能通过 action 读取或使用，读取结果进入 TurnTraceHeap。例如：

- `home:how/python_refactor/references/checklist.md`
- `home:how/python_refactor/scripts/inspect.py`

`home:how_domain:<domain>` 与 `home:how_action:<domain>/<action>` 表示框架局部自动 prompt mount，只进入对应 Phase/task prompt，不进入 BackgroundContext，也不作为 `home.resource.read` 的渐进式资源。例如：

- `home:how_domain:workspace`
- `home:how_action:workspace/rewrite`
链接规则:

- 顶层 `space` 只能是 `agent`、`what`、`why`、`how`、`memory`；`how_domain` 与 `how_action` 只用于自动 prompt mount 链接；
- `@` 后的普通顶层名称可以包含安全的 `/` 分段，但通用 HOW skill 使用单段名称，MEMORY 使用严格 `yyyy-mm-dd`；
- `/` 形式始终表示资源路径，不能被 Context 直接加载为背景；
- 所有路径使用 POSIX `/` 分隔；
- 不允许空路径、绝对路径、盘符、反斜杠、`.` 或 `..` 段。
- MEMORY 只接受 `home:memory@yyyy-mm-dd` 顶层 Link；不提供 `home:memory/...` resource Link，年月物理目录不会泄漏到模型协议。

Agent Home 应提供 `HomeTopLink`、`HomeResourceLink` 与 `HomePromptMountLink` 或等价值对象，避免模块内部使用裸字符串判断链接类别。

## 内容空间

目标目录结构：

```text
home/
  agent/
    AGENT.md
    user/
    identity/
  what/
    entity/
    concept/
  why/
  how/
    skill_name/
      SKILL.md
      references/
      scripts/
  how_domain/
    domain_name/
      DOMAIN.md
  how_action/
    domain_name/
      action_name.md
  memory/
    yyyy/
      mm/
        yyyy-mm-dd.md

runtime/
  home/
    .tinysoul/
      home_overlay.json
      operations/
    agent/
    what/
    why/
    how/
      skill_name/
        SKILL_MEMORY.md
    how_domain/
    how_action/
```

`runtime/home` 只包含自上次 Home Maintenance 以来实际物化、创建或删除的非 MEMORY 内容，不预建完整目录树，也不因 Business Day 变化而清空；上图中的内容目录均为按需出现。`SKILL_MEMORY.md` 只允许位于通用 `runtime/home/how/<skill>/`，`how_domain`/`how_action` 不创建平行 memory 文件。`home/memory/yyyy/mm/*.md` 不复制到 runtime。

顶层内容映射建议：

- `home:agent@core` 映射到 `agent/AGENT.md`；
- `home:agent@user/preferences` 映射到 `agent/user/preferences.md`；
- `home:what@name` 映射到 WHAT 索引解析出的实体或概念文档；
- `home:why@name` 映射到 WHY 问题文档；
- `home:how@skill_name` 映射到 `how/skill_name/SKILL.md`；
- `home:how_domain:domain_name` 作为 prompt mount 映射到 `how_domain/domain_name/DOMAIN.md`；
- `home:how_action:domain_name/action_name` 作为 prompt mount 映射到 `how_action/domain_name/action_name.md`；
- `home:memory@yyyy-mm-dd` 映射到 `memory/yyyy/mm/yyyy-mm-dd.md`；年月物理目录不改变稳定 Link。

HOW 采用包目录形式。通用 HOW 使用 `how/<skill>/SKILL.md` 作为顶层入口，references、scripts 等是渐进式资源；skill 使用期间可以在 runtime 包内创建并读写 `SKILL_MEMORY.md`，记录自上次 Home Maintenance 以来的临时工作记忆、使用反馈和待 review 变化。它不进入 actual Home，也不作为长期 HOW 文件直接合并。与 action domain 绑定的 domain HOW 使用 `how_domain/<domain>/DOMAIN.md`，由 Phase2 prompt 自动注入，并可在 Phase3 action-internal LLM task 中继续作为 domain 约束；domain 内 action HOW 使用 `how_action/<domain>/<action>.md`，由 Phase3 中带内部 LLM task 的 action 自动注入。`how_domain` 与 `how_action` 是框架局部自动加载机制，不属于模型通过 `home.resource.read` 按需渐进式加载的普通资源，也不拥有 `SKILL_MEMORY.md`。

## Actual Home 与 Runtime Home

Agent Home 分为 actual Home 和跨日 runtime Home：

- actual Home 是已经通过 Maintenance 提交的长期资料库，普通 User Turn 中只读；
- runtime Home 是跨 Turn、跨 Business Day、跨重启保留的懒加载可写 overlay；
- Home Maintenance 直接比较 active runtime Home 与 actual Home，再决定 apply 或 discard；Memory Maintenance 独立从指定日期 Session archive 生成长期 MEMORY。

当非 MEMORY 顶层内容、渐进式资源或 prompt mount 被加载到运行期时，Agent Home 确保 runtime Home 中存在对应副本，并从统一 effective view 读取：runtime override 优先，runtime tombstone 隐藏 actual 内容，未物化内容回退 actual Home。MEMORY 是明确例外：它直接读取 actual Home，不复制到 runtime。语义检索可以只读取 effective metadata；一旦非 MEMORY 正文进入 BackgroundContext、HOW 或 action result，就按链接建立 runtime record。所有普通可写操作只能落在 runtime Home。

runtime mutation 按链接类别拆分：

- 渐进式资源继续使用 `home.resource.read/write/patch/delete`；
- 顶层内容使用 `home.top.write/patch/delete`，允许在 runtime 创建不存在的顶层内容；新 WHAT 必须显式提供 `entity` 或 `concept`，`home:agent@core` 允许 write/patch 但禁止 delete；
- 自动 HOW 使用 `home.prompt_mount.write/patch`；逻辑 prompt mount 由框架根据 Action Catalog 中定义的 domain/action 自动创建或删除，模型不直接 create/delete；
- 通用 HOW 的 `SKILL_MEMORY.md` 是允许直接在 runtime 创建的特殊渐进资源；
- MEMORY 不接受上述普通 mutation action。

当前实现已将上述 mutation 全部注册到 Home action catalog。Action executor 只解析参数并映射局部结果/Runtime failure，链接映射、effective resolution 和实际 overlay mutation 仍由 `AgentHomeEngine` 统一负责。

运行时副本准备有两种入口：

1. Home 门面在需要可写副本时同步确保副本存在；
2. 操作边界发现需要全局恢复时，通过 `HOME_RUNTIME_COPY_REQUIRED` 进入 Trap，由 Home runtime copy handler 创建副本后重试当前 frame。

后一种入口用于保持与 Runtime 的 OS 风格陷入设计一致，尤其适合在 Phase 或 action 执行边界处理缺页式副本准备。

当前实现由 `HomeOverlayManager` 统一承担 copy、write、patch、delete 和 reconciliation。Manifest schema v2 不含 Business Day；每条记录包含 relative path、`copied/created/modified/deleted` state、actual baseline digest、runtime digest、size 与 mtime。Builder 在构建 Home 时恢复 operation、迁移 schema v1 并初始化或收养现有 runtime 文件。修改先写入 `.tinysoul/operations/<operation-id>` intent 和 staged bytes，再替换目标、提交 Manifest、清理 operation；若在替换后、Manifest 前退出，下次 initialization/reconciliation 按 digest 前滚。

Home overlay 的存在本身就是尚未提交的事实，不建立第二份 pending/workset/store。每日 Session/Workspace rollover 已保证不移动、清空或重新初始化 `runtime/home`。

Overlay manager 使用进程内 `RLock` 串行化同一 Engine 的读写。纯 `copied` 文件丢失且 actual 仍等于 baseline 时可以确定性重建；modified/created 文件丢失、tombstone 路径重现或 Manifest/operation 状态歧义均属于不变量失败。actual baseline 后续变化不是自动覆盖理由，Home Maintenance 应基于 baseline、runtime 和当前 actual 内容形成明确 review 输入。runtime copy handler 只有在调用前 runtime 文件确实缺失、调用后完成物化时才返回一次 RETRY；文件已经存在却再次请求缺页时直接结束最近 Turn，避免无上限重试。

actual Home 严格位于 `home/`，runtime Home 严格位于 `runtime/home/`。`home:agent@core` 只映射 `home/agent/AGENT.md` 到 `runtime/home/agent/AGENT.md`；项目根 `AGENT.md` 是仓库开发规约，不属于运行时 Agent Home，也不存在 fallback。

## BackgroundContext 接入

Agent Home 通过 `HomeBackgroundEntryProvider` 向 Context 提供背景目录与正文，而不是让 Context 读文件。provider 每次返回：

- 默认加载条目；
- 可由 Phase1 加载的顶层条目；
- 每个条目的 `home:*@` 链接和渲染文本。

`ContextEngine.begin_turn` 会清空上一 Turn 的 Home Background；`ContextTurnPreparationHandler` 在首个 Cycle 前重新读取 provider catalog 并原子加载默认 core。Phase1 加载项只存在于当前 Turn，跨 Turn 信息必须进入 Session 或 actual/runtime Home 持久事实。静态 `link + content` 仍供测试或嵌入方使用，但不能与动态 provider 重复注册同一链接。

Control Tool 的 `load_background` 和 `evict_background` 仍属于 Context 语义。模型选择顶层链接后，Context 通过已注入的 Home loader 获取文本，不解释 Home 路径；loader 触发的 runtime copy 对模型、ControlResult 和最终 Context 状态透明。

## Domain/Action HOW 接入

Loop 只依赖 `DomainHowProvider` 协议，不读取 HOW 文件。Agent Home 提供 `HomeDomainHowProvider`，接收 Phase1 已选择的 action domain，映射为 `home:how_domain:<domain>`，读取对应 `DOMAIN.md` 并返回适合 Phase2 task prompt 的短文本片段。

Action 内部 LLM task 只依赖 `ActionHowProvider` 协议，不读取 home 文件。Agent Home 提供 `HomeActionHowProvider`，接收 `domain` 与 `action_name`，分别映射为 `home:how_domain:<domain>` 与 `home:how_action:<domain>/<action>`。这两类内容只注入 Phase3 action 内部嵌套 LLM task，用于延续 domain 约束，并约束具体 action 的文本风格、生成策略或领域动作细节。

Domain HOW 与 action HOW 分别属于 `how_domain` 与 `how_action` 的局部自动加载机制：Phase2 自动加载 domain HOW；Phase3 中带内部 LLM task 的 action 同时自动加载 domain HOW 与 action HOW。它们不属于普通渐进式资源加载；模型不需要通过 `home.resource.read` 主动读取这些 HOW，Loop 与 Action 也不感知 Agent Home 的目录结构。

逻辑 prompt mount 由框架从 Action Catalog 派生：catalog 中定义的 domain/action 决定合法 `HomePromptMountLink`，不以 provider 暂时不可用或 action 临时 disabled 作为删除依据。对应 actual/runtime 正文都不存在时 provider 返回空 guidance；`home.prompt_mount.write` 可以为合法 mount 物化 runtime 内容，`home.prompt_mount.patch` 修改已有 effective 内容。domain/action 从 catalog 删除时，框架在 runtime 形成对应删除语义，下一次 Home Maintenance 决定 actual 删除；模型不拥有 prompt mount create/delete action。文件存在但编码损坏、不可读或映射不变量失败时，不得伪装成“没有 HOW”，而应由 Home provider 通过 Runtime bridge 映射为模块边界失败。副本缺失仍使用专门的 runtime-copy 恢复原因。

## Progressive Resource Actions

渐进式资源不进入 BackgroundContext。需要读取或编辑时，应通过 action 完成。

当前已实现的 action：

- `home.resource.read`：读取 `home:*/` 渐进式资源的 runtime 副本文本前缀，按 `max_chars` 或配置上限返回文本片段，并在 action local result 中表达参数和读取失败；副本缺失时通过 Runtime Trap 建立副本后重试。读取实现只读取上限后的一个额外字符来判断截断，不先把完整文件读入内存。
- `home.resource.write`：在 active overlay 创建 runtime-only 文本，或在显式 `overwrite` 和可选 `expected_digest` 前置条件下替换 effective 内容；
- `home.resource.patch`：对 effective UTF-8 文本执行唯一 `old_text` 精确替换，校验 digest 与完整结果的 `max_write_chars`；
- `home.resource.delete`：写入 tombstone 隐藏资源，不删除 actual Home。
- `home.top.write/patch/delete`：修改非 MEMORY 顶层 runtime 内容；新 WHAT create 强制 `entity`/`concept` 分类，`home:agent@core` 可 write/patch 但拒绝 delete；
- `home.prompt_mount.write/patch`：只修改由 Action Catalog 定义的合法 domain/action mount；逻辑 create/delete 仍由框架 reconciliation 负责；
- 通用 HOW 的 `SKILL_MEMORY.md` 通过 resource action 读写，只允许 `runtime/home/how/<skill>/SKILL_MEMORY.md` 且对应 effective HOW skill 必须存在；actual Home 和其它空间的平行 memory 文件在装配/reconciliation 时被拒绝。

后续需要的能力：

- `home.top.search`：按 WHAT、WHY、HOW、MEMORY 检索候选顶层链接；
- Home Maintenance 与 Memory Maintenance，它们不是普通 User Turn action。

普通 mutation 冲突和 patch 不适用收敛为局部 ActionResult；overlay 图损坏等不变量经 Home bridge 进入 Runtime，不降级为普通模型反馈。成功修改只返回 link、state、digest、baseline digest 和 size，不返回完整新正文。非 MEMORY actual 内容只允许由 Home Maintenance 修改；MEMORY 只允许由 Memory Maintenance 写入，不能伪装为普通 Home mutation。

## Maintenance

Home Maintenance 与 Memory Maintenance 都是与 User Turn 同级的 Program work，不属于普通 User Turn 的 Phase 主链路。两者可以由内置 scheduler、程序启动后的提示或人工命令独立触发；scheduler 与输入适配器只投递 Program event，不直接调用 Home。Maintenance 执行期间不接收新的 User Turn 输入，外部输入进入 Program queue 等待。

### Home Maintenance

Home Maintenance 的输入只包括当前 active `runtime/home`、actual Home，以及 runtime 通用 HOW 包中的 `SKILL_MEMORY.md`。它不读取 Session、Workspace、Trash 或任何 archived Home，也不创建 Home archive、workset、Settlement root 或持久 review 状态。

一次调用在内存中计算 active overlay 与 actual Home 的差异并立即 apply 或 discard：

1. `copied` 表示仅物化而未被 Agent 修改，无论当前 actual 是否已经变化，都不应把旧 runtime 副本写回；Maintenance 直接清理该 runtime record/content；
2. `created/modified/deleted` 以 record baseline、runtime 内容和当前 actual 内容构造有界 review 输入；后台模式允许 Agent 全自动 apply/discard，人工模式通过上层注入的 decision provider 在终端逐项确认；Home reviewer 不直接读取 stdin；
3. apply 使用单文件原子替换或删除更新 actual Home，discard 不修改 actual Home；任一决定完成后都清除对应 runtime record/content，使后续 effective read 回退到 actual Home；
4. `SKILL_MEMORY.md` 用于 review 对应通用 HOW，但文件自身永不写入 actual Home；该 skill review 完成后清空；
5. 全部实际 diff 处理后，active overlay 只保留后续新物化或新修改内容；不保存 status、plan、review result 或 apply journal；
6. 若中断发生在 actual 单文件写入之后、runtime 清理之前，下一次 Maintenance 根据两者已经一致的事实完成清理；未处理项继续保留在 active overlay 并重新 review。

Home Maintenance 与 User Turn 由 Program 单写者边界串行化，因而 review/apply 期间不会出现新的 runtime mutation。未触发或人工跳过 Home Maintenance 时，active overlay 原样跨 Turn、跨日、跨重启保留，Agent 继续透明读取和修改同一 effective Home。`SKILL_MEMORY.md` 同样保留到下一次 Home Maintenance。

当前代码已实现 Home-owned `HomeMaintenanceService`、内存态 frozen change/decision/outcome、自动 reviewer 与人工 decision provider 协议。自动 reviewer 使用 JSON-only `home_maintenance` LLM profile，并且只接受精确 `apply`/`discard` 字段；review task failure、缺失 JSON、额外字段或非法 decision 收敛为当次 `FAILED/review_failed` outcome，未处理 overlay 保留。人工 provider 返回 `None` 时在当前未确认项之前停止。change 只携带有界 runtime/actual 文本预览、baseline/runtime/actual digest 和可选同 skill `SKILL_MEMORY`，完整 runtime 内容仅在 apply 前重新校验后由文件边界读取。Home 服务返回有界 outcome；Program work、Observation、终端逐项输入与 scheduler 尚未装配。

overlay cleanup 不保存 review decision。copied record 若遇到 actual 外部变化，先把 runtime 对齐 current actual 或形成 current deletion，再清除 record，旧副本永不写回。created/modified 的 runtime digest 已等于 current actual、或 deleted 对应 actual 已不存在时，Maintenance 直接清理，覆盖“actual 原子写完成但 runtime 清理中断”的恢复窗口。discard 清理若中断，未清除的 runtime diff 可以在下一次重新 review。

### Memory Maintenance

Memory Maintenance 接受明确的目标 Business Day，并读取该日期不可变 Session archive 中已经提交的 Turn/summary 事实。输出固定为：

```text
home/memory/yyyy/mm/yyyy-mm-dd.md
```

目标文件不存在时，只根据该日期 Session 生成完整 MEMORY；目标文件已经存在时，同时读取同日期旧 MEMORY 与同日期 Session，重新生成完整文档并原子覆盖。它不读取其它日期 MEMORY、active Home diff、Workspace 或 `SKILL_MEMORY.md`，不创建 runtime MEMORY，也不执行 append。

启动自动检测只检查配置业务时区中的昨日：存在昨日 Session archive 且昨日 MEMORY 不存在时提示 Memory Maintenance；不扫描更早日期，也不持久化 skipped 状态。因此同一业务日内再次启动仍可能再次提示，日期变成更早历史后不再自动提示。人工命令可以显式指定任意仍有 Session archive 的日期，包括对已有同日 MEMORY 的重写。

Home Maintenance 与 Memory Maintenance 的触发、输入、结果和失败边界相互独立；任一任务失败不回滚或伪装另一项任务的结果。

## 与 Workspace 的关系

Agent Home 和 Workspace 都基于链接和相对路径，但语义边界不同：

- Agent Home 管理持久化知识、技能和记忆；
- Workspace 管理当日任务资源和产物；
- Home 文档可以引用 `workspace:` 链接，但不解析 workspace 路径；
- Workspace action 可以生成 `home:` 链接作为参考，但不读取 home 文件；
- 两者共享 infra 的路径和文件基础能力，不互相绕过门面读写。

跨模块协作应通过 action、link、context signal 和 builder 注入完成。

## 失败与 Runtime 桥接

Agent Home 失败分三层：

1. 局部 action result：链接不存在、链接类别不适用于当前 mutation、WHAT 分类缺失、core delete、文件过大、写入冲突、patch 不适用；
2. 模块边界异常：home root 不可用、已有内容无法按 UTF-8 解释、链接映射不变量破坏、runtime copy 缺失且无法本地修复、索引损坏、配置不可解释；
3. Runtime 语义异常：启动配置失败映射为 `runtime.startup_failed`，User Turn 中不可继续失败默认映射为 `runtime.turn_end`，运行时副本准备映射为 `home.runtime_copy_required`；Home/Memory Maintenance failure 结束对应 maintenance task，不伪装为 User Turn failure。

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
  runtime_copy.py
  guidance.py
  actions.py
  errors.py
  failures.py
```

`AgentHomeEngine` 是普通 User Turn 与 Maintenance 的 Home 门面，提供链接解析、动态顶层目录、effective read、runtime mutation、overlay reconciliation、domain/action HOW、Home reviewer 和 Memory consolidator。`HomeOverlayManager` 只管理跨日 active overlay record 与 operation recovery，不再提供 Business Day/archive 业务语义，也不承载 LLM review policy。`AgentHomeEngineBuilder` 负责接收已解析设置、校验目录并装配布局与 overlay。Home reviewer/consolidator 是 Home-owned 独立服务，由门面组合；不建立 Settlement store，也不把维护 LLM 逻辑放进普通 action executor。

AppBuilder 的目标职责是：

1. 构建 AgentHomeEngine；
2. 将 `HomeBackgroundEntryProvider` 交给 ContextEngineBuilder，不在启动时读取或物化 core；
3. 将 HomeDomainHowProvider 注入 Phase2Unit，并将 HomeActionHowProvider 注入 LLM action executor；
4. 将 Home action handler 注册到 ActionEngineBuilder；
5. 注册 home runtime copy Trap handler；
6. 不直接读取 `AGENT.md`、HOW、WHAT、WHY 或 MEMORY 文件。

## 测试与验收

验收点：

- AppBuilder 不直接读取 `home/agent/AGENT.md`，项目根 `AGENT.md` 不参与 Home 映射；
- Context 默认背景来自 Agent Home 门面；
- `DomainHowProvider` 能从 `home:how_domain:domain` 获取 domain HOW；`ActionHowProvider` 能从 `home:how_domain:domain` 与 `home:how_action:<domain>/<action>` 获取 domain/action HOW；
- `home:*@` 与 `home:*/` 链接解析和越界防护有单元测试；
- runtime home 显式副本准备行为有单元测试；
- 每个 User Turn 的 preparation 通过动态 provider 重建默认 core；其它背景在 Context Module frame 中按需复制并重放同一 signal batch；
- `home:agent@core` 的 runtime 副本位置稳定为 `agent/AGENT.md`；
- `home.resource.read` 不写入 BackgroundContext，并返回有界文本；write/patch/delete 只修改 active overlay，actual Home 保持零写入；
- `home.top.write/patch/delete` 只修改 runtime；WHAT create 要求分类，core delete 被拒绝；
- prompt mount 由 Action Catalog 自动维护逻辑生命周期，模型只通过 write/patch 修改 runtime；
- `HOME_RUNTIME_COPY_REQUIRED` trap handler 能准备副本并重试当前 frame；
- Agent Home 的配置错误、索引损坏和 runtime copy 失败经专门 bridge 映射；
- MEMORY 读取不创建 runtime copy，稳定日期 Link 映射年月目录；runtime-only 内容、tombstone 和 operation recovery 跨日、跨重启保持；
- 只有通用 HOW runtime 包拥有 `SKILL_MEMORY.md`，跨 Turn/跨日可读写且 Home Maintenance 后清空；
- Home Maintenance 不创建 archive 或持久状态，apply/discard 后清理 active overlay record，中断后通过仍存在的 active diff 重算；
- Memory Maintenance 从指定日期 Session 和可选同日旧 MEMORY 原子重写固定日期文件；
- 每日日切不移动、清空或重新初始化 runtime Home，也不改变普通 User Turn 的三阶段主流程。

仍需补充的验收点包括：top search、Memory Maintenance 和 Home/Memory 的 scheduler/启动/人工调度。
