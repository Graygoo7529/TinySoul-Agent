# Agent Home 设计

## 状态

本文描述 Agent Home 模块的当前设计。代码已包含独立 Agent Home 模块，并完成 `home:` 链接解析、默认和可加载背景条目、`home:agent@core` 加载、`home:how_domain:<domain>` domain HOW 注入、`home:how_action:<domain>/<action>` action HOW 注入、运行时副本准备、`home.resource.read` action 和 Runtime bridge/trap handler 接入。

当前实现覆盖 Agent Home 的背景加载、domain/action HOW 注入、渐进式只读资源和 runtime home 缺页式副本准备切面。顶层内容和渐进式资源在读取时都以 runtime 副本为读取位置；当运行期边界发现副本缺失时，通过 `HOME_RUNTIME_COPY_REQUIRED` 进入 Trap，准备副本后重试当前 frame。资源写入、patch、检索、当日 memory 草稿、HOW 使用反馈和每日沉淀仍未实现，后续应继续在 Agent Home 模块内扩展。

## 定位

Agent Home 模块负责 TinySoul 的持久化语境资源，包括身份规约、用户偏好、知识、技能、行动域 HOW 和长期记忆。它是 `home:` 链接的唯一语义归属方。

Agent Home 不维护 Turn 内 Context 状态，不驱动 Loop，不执行模型供应商调用，也不管理 workspace 文件。它向 Context 提供可加载的顶层背景内容，向 Loop 提供 domain HOW provider，向 Action 内部 LLM task 提供 action HOW provider，并向 Action 提供 home 资源读取和编辑动作，并通过 Runtime 恢复例程维护当日 runtime home 副本。

## 设计目标

1. 明确区分顶层内容和渐进式资源。
2. 原始 Agent Home 在日常运行中只读，运行期修改落在当日 runtime 副本。
3. Context 只消费 Agent Home 提供的背景条目，不读取 home 文件树。
4. Loop 只依赖 `DomainHowProvider` 协议，不读取 HOW 文件；Action 内部 LLM task 只依赖 `ActionHowProvider` 协议。
5. HOW、WHAT、WHY、MEMORY 的目录结构由 Agent Home 解释，不泄漏到 AppBuilder。
6. Agent Home 运行时副本错误有明确 failure kind 和 Runtime bridge 映射。
7. 每日沉淀作为独立维护任务接入，不混入用户 Turn 的 Phase 主链路。

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

- `space` 是稳定命名空间，例如 `agent`、`what`、`why`、`how`、`memory`；`how_domain` 与 `how_action` 只用于自动 prompt mount 链接；
- `@` 后的顶层名称可以包含安全的 `/` 分段，但不能包含扩展出的越界路径；
- `/` 形式始终表示资源路径，不能被 Context 直接加载为背景；
- 所有路径使用 POSIX `/` 分隔；
- 不允许空路径、绝对路径、盘符、反斜杠、`.` 或 `..` 段。

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
    yyyy-mm-dd.md

runtime/
  home/
    agent/
    what/
    why/
    how/
    how_domain/
    how_action/
    this_day_memory.md
```

顶层内容映射建议：

- `home:agent@core` 映射到 `agent/AGENT.md`；
- `home:agent@user/preferences` 映射到 `agent/user/preferences.md`；
- `home:what@name` 映射到 WHAT 索引解析出的实体或概念文档；
- `home:why@name` 映射到 WHY 问题文档；
- `home:how@skill_name` 映射到 `how/skill_name/SKILL.md`；
- `home:how_domain:domain_name` 作为 prompt mount 映射到 `how_domain/domain_name/DOMAIN.md`；
- `home:how_action:domain_name/action_name` 作为 prompt mount 映射到 `how_action/domain_name/action_name.md`；
- `home:memory@yyyy-mm-dd` 映射到 `memory/yyyy-mm-dd.md` 或当日 memory 摘要。

HOW 采用包目录形式。通用 HOW 使用 `how/<skill>/SKILL.md` 作为顶层入口，references、scripts 等是渐进式资源。与 action domain 绑定的 domain HOW 使用 `how_domain/<domain>/DOMAIN.md`，由 Phase2 prompt 自动注入，并可在 Phase3 action-internal LLM task 中继续作为 domain 约束；domain 内 action HOW 使用 `how_action/<domain>/<action>.md`，由 Phase3 中带内部 LLM task 的 action 自动注入。`how_domain` 与 `how_action` 是框架局部自动加载机制，不属于模型通过 `home.resource.read` 按需渐进式加载的普通资源。

## 原始 Home 与 Runtime Home

Agent Home 分为原始 home 和当日 runtime home：

- 原始 home 是长期资料库，日常运行中只读；
- runtime home 是当日懒加载副本，运行期可写；
- 每日沉淀任务比较 runtime home 与原始 home 的差异，再决定合并、丢弃或生成记忆。

当某个顶层内容或渐进式资源被加载到运行期时，Agent Home 应确保 runtime home 中存在对应副本，并从 runtime home 读取。语义检索这类候选发现可以只读取原始 home；一旦链接内容进入 BackgroundContext、domain HOW 或 action result，就按链接建立 runtime 副本。可写操作必须落在 runtime home。

运行时副本准备有两种入口：

1. Home 门面在需要可写副本时同步确保副本存在；
2. 操作边界发现需要全局恢复时，通过 `HOME_RUNTIME_COPY_REQUIRED` 进入 Trap，由 Home runtime copy handler 创建副本后重试当前 frame。

后一种入口用于保持与 Runtime 的 OS 风格陷入设计一致，尤其适合在 Phase 或 action 执行边界处理缺页式副本准备。

当前实现提供显式 `ensure_runtime_copy`、Trap handler、`AgentHomeRuntimeCopyRecovery` 和 `HomeBackgroundContentLoader`。启动装配只通过 recovery 物化默认 `home:agent@core`；其它可加载背景只枚举链接并注册 loader，不读取正文、不创建副本。Phase1 实际加载时，loader 在 Context 的事务批次和 Module frame 内读取 runtime home；缺页映射为 `HOME_RUNTIME_COPY_REQUIRED`，Trap 创建副本后重试同一批次。domain/action HOW 与渐进式 action read 复用相同缺页语义。副本通过 runtime 目标同目录临时文件流式复制、flush/fsync 后原子 replace，读取方不会观察半份内容；原始根和 runtime 根禁止相同或互相嵌套，目标路径始终重新约束在 runtime root 内。

runtime copy manager 以进程内锁串行化同一目标，并记住已经物化的目标。已经物化的副本若随后消失或变成非普通文件，视为 I/O 不变量失败，不从 original home 静默重建覆盖运行期状态。runtime copy handler 只在副本成功建立时重试当前 frame；启动 recovery 对同一 link 最多处理一次缺页，链接失效、源文件消失、复制失败或重试后仍缺页时结束最近 Turn（启动阶段结束 Program），避免不可恢复缺页形成无上限重试。

原始 Home 严格位于 `home/`，runtime Home 严格位于 `runtime/home/`。`home:agent@core` 只映射 `home/agent/AGENT.md` 到 `runtime/home/agent/AGENT.md`；项目根 `AGENT.md` 是仓库开发规约，不属于运行时 Agent Home，也不存在 fallback。

## BackgroundContext 接入

Agent Home 向 Context 提供背景条目，而不是让 Context 读文件。建议定义背景条目提供协议，返回：

- 默认加载条目；
- 可由 Phase1 加载的顶层条目；
- 每个条目的 `home:*@` 链接和渲染文本。

ContextEngineBuilder 可以继续接收静态 `link + content`，但内容来源应由 Agent Home 门面生成。后续若要支持按 Turn 动态 top-k 语义匹配，仍应由 Agent Home 先解析为顶层条目，再交给 Context。

Control Tool 的 `load_background` 和 `evict_background` 仍属于 Context 语义。模型选择顶层链接后，Context 通过已注入的 Home loader 获取文本，不解释 Home 路径；loader 触发的 runtime copy 对模型、ControlResult 和最终 Context 状态透明。

## Domain/Action HOW 接入

Loop 只依赖 `DomainHowProvider` 协议，不读取 HOW 文件。Agent Home 提供 `HomeDomainHowProvider`，接收 Phase1 已选择的 action domain，映射为 `home:how_domain:<domain>`，读取对应 `DOMAIN.md` 并返回适合 Phase2 task prompt 的短文本片段。

Action 内部 LLM task 只依赖 `ActionHowProvider` 协议，不读取 home 文件。Agent Home 提供 `HomeActionHowProvider`，接收 `domain` 与 `action_name`，分别映射为 `home:how_domain:<domain>` 与 `home:how_action:<domain>/<action>`。这两类内容只注入 Phase3 action 内部嵌套 LLM task，用于延续 domain 约束，并约束具体 action 的文本风格、生成策略或领域动作细节。

Domain HOW 与 action HOW 分别属于 `how_domain` 与 `how_action` 的局部自动加载机制：Phase2 自动加载 domain HOW；Phase3 中带内部 LLM task 的 action 同时自动加载 domain HOW 与 action HOW。它们不属于普通渐进式资源加载；模型不需要通过 `home.resource.read` 主动读取这些 HOW，Loop 与 Action 也不感知 Agent Home 的目录结构。

HOW prompt mount 是可选内容：对应源文件不存在时 provider 返回空 guidance；文件存在但编码损坏、不可读或映射不变量失败时，不得伪装成“没有 HOW”，而应由 Home provider 通过 Runtime bridge 映射为模块边界失败。副本缺失仍使用专门的 runtime-copy 恢复原因。

## Progressive Resource Actions

渐进式资源不进入 BackgroundContext。需要读取或编辑时，应通过 action 完成。

当前已实现的 action：

- `home.resource.read`：读取 `home:*/` 渐进式资源的 runtime 副本文本前缀，按 `max_chars` 或配置上限返回文本片段，并在 action local result 中表达参数和读取失败；副本缺失时通过 Runtime Trap 建立副本后重试。读取实现只读取上限后的一个额外字符来判断截断，不先把完整文件读入内存。

后续可设计的 action：

- `home.resource.write`：写入 runtime home 副本；
- `home.resource.patch`：按结构化 patch 修改资源；
- `home.top.search`：按 WHAT、WHY、HOW、MEMORY 检索候选顶层链接；
- `home.memory.append`：向当日 memory 草稿追加候选记忆；
- `home.how.record_feedback`：更新 HOW 包的当日使用反馈。

这些 action 不应默认把长文件内容写入 TurnTraceHeap。读取长内容时应提供大小限制、片段读取和摘要策略；写入结果应返回变更摘要和资源链接。

## 每日记忆与沉淀

每日沉淀是与用户 Turn 同级的维护任务，不属于普通 User Turn 内的 Phase 主链路。

沉淀任务输入：

- 当日 TurnSummary 集合；
- runtime home 与原始 home 的 diff；
- HOW/how_domain/how_action 的使用反馈；
- 当日 workspace 归档摘要；
- 用户显式要求保留或删除的内容。

沉淀任务输出：

- 追加或修改 MEMORY；
- 合并 WHAT、WHY、HOW、how_domain 或 how_action 的变更；
- 丢弃 runtime home 中不应长期保留的临时修改；
- 生成可审阅的 diff 摘要。

执行沉淀可以调用独立 LLM Task，但调度和审批策略不属于 Agent Home 的基础读写门面。Agent Home 只提供 diff、写入候选、合并和归档所需的资源操作。

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

1. 局部 action result：链接不存在、资源不是渐进式链接、文件过大、写入冲突、patch 不适用；
2. 模块边界异常：home root 不可用、已有内容无法按 UTF-8 解释、链接映射不变量破坏、runtime copy 缺失且无法本地修复、索引损坏、配置不可解释；
3. Runtime 语义异常：启动配置失败映射为 `runtime.startup_failed`，运行期不可继续失败默认映射为 `runtime.turn_end`，运行时副本准备映射为 `home.runtime_copy_required`。

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
  runtime_copy.py
  guidance.py
  actions.py
  errors.py
  failures.py
```

`AgentHomeEngine` 是上层唯一门面，提供链接解析、顶层背景条目、渐进式资源访问、runtime copy 和 domain/action HOW。`AgentHomeEngineBuilder` 负责接收已解析设置、校验目录、装配布局和 runtime copy manager。每日沉淀资源操作尚未落地，后续可在 `settlement.py` 或更明确的维护任务模块中加入。

AppBuilder 的目标职责是：

1. 构建 AgentHomeEngine；
2. 将默认 core 内容和其它 top-level link 的 lazy loader 交给 ContextEngineBuilder；
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
- 启动期仅通过 `AgentHomeRuntimeCopyRecovery` 准备默认 core；其它背景在 Context Module frame 中按需复制并重放同一 signal batch；
- `home:agent@core` 的 runtime 副本位置稳定为 `agent/AGENT.md`；
- `home.resource.read` 不写入 BackgroundContext，并返回有界文本；
- `HOME_RUNTIME_COPY_REQUIRED` trap handler 能准备副本并重试当前 frame；
- Agent Home 的配置错误、索引损坏和 runtime copy 失败经专门 bridge 映射；
- 每日沉淀只作为独立维护任务接入，不改变普通 User Turn 的三阶段主流程。

仍需补充的验收点包括：home 写入/patch action、top search、memory append、HOW 使用反馈和 daily settlement。
