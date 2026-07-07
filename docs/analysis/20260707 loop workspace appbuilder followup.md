# 20260707 loop workspace appbuilder followup

## 状态

status: in_progress

本文记录 App 装配层中与 Workspace、Agent Home 后续模块相关的遗留装配问题。Loop 与 App 已拆分：Loop 保留 Program/Turn/Cycle/Phase 运行编排，App 负责 TinySoulApp 装配入口、输入源、输入解析与输入分发。以下内容不是当前功能错误，而是后续推进 Workspace / Agent Home 资源读写机制时需要优先处理的边界。

## 当前实现位置

- `tinysoul/app/builder.py` 的 `TinySoulAppBuilder` 负责装配 LLM、Action、Context、SignalBus、RuntimeTrap、输入分发器、输入源和各级 loop runner。
- `workspace.scan` 当前作为内置 native action 在 `TinySoulAppBuilder._build_action()` 中注册。
- `workspace.scan` 的实现位于 `tinysoul/app/native_actions.py`，扫描项目根目录，生成 `workspace:` 链接和简短摘要，并通过 `context.working.patch` 更新 WorkingContext。
- Phase2 的 domain guidance 通过 `DomainGuidanceProvider` 注入，默认实现为空，尚未接入 Agent Home 的 `how_action` 内容。
- Context 默认只加载项目根目录 `AGENT.md` 为 `home:agent@core` 背景条目，尚未接入 Agent Home 运行时副本、懒加载、顶层/渐进式链接管理。

## 设计意图

App 的职责是进程装配、生命周期和外部输入边界，不应长期承担 workspace 文件扫描、Agent Home 内容读取、运行时副本管理、how_action 检索或每日沉淀策略。

当前把 `workspace.scan` 放在 app 装配层，是 Workspace 模块未落地前的轻量装配能力：它让 Phase3 可以通过 action -> signal 的既有通道向 WorkingContext 写入 workspace 资源摘要，验证了 App、Loop、Action、Context 的协作路径。

## 风险与不足

- `workspace.scan` 的扫描规则、跳过目录、数量上限、摘要格式都写在 App 装配层，属于 Workspace 语义泄漏。
- `TinySoulAppBuilder` 的 `_build_action()` 同时承担 action catalog 装配、native action 注册、workspace 扫描函数闭包构造和 nested LLM executor 注册，随着 Workspace / Agent Home 接入仍会继续膨胀。
- `workspace.scan` 当前只返回文件链接和大小，不维护 workspace manifest、资源摘要缓存、文件内容读取策略、每日归档或资源变更检测。
- `DomainGuidanceProvider` 已提供注入点，但默认空实现意味着 Phase2 尚无法自动获得 `how_action/<domain>` 的 HOW 文档。
- Context 默认背景只从项目根 `AGENT.md` 读取，尚未区分原始 Agent Home、当日运行时副本、顶层内容和渐进式内容。
- AppBuilder 装配层仍有兜底 `except Exception`，作为启动边界可以接受；后续模块增多后，应让 Workspace / Agent Home 的 startup failure 归属到各自 bridge，而不是落入 loop fallback。

## 后续迁移方向

- 新增 Workspace 模块，提供 WorkspaceEngine / WorkspaceBuilder 或等价门面，负责 workspace 根目录、manifest、资源扫描、链接解析、摘要维护和读写策略。
- `workspace.scan` 迁移为 Workspace 模块提供的 native action 或 Action executor 注册材料；App 只负责调用 Workspace builder 的注册方法或接收已装配好的 ActionEngine。
- Workspace 模块通过稳定信号或返回结果更新 WorkingContext，继续保持“文件内容不直接进入 Context，Context 只持有 workspace 链接和摘要”的规则。
- 新增 Agent Home 模块，负责原始 home、当日运行时副本、顶层背景条目、渐进式资源、how_action/domain guidance 和每日沉淀。
- `DomainGuidanceProvider` 的真实实现应由 Agent Home 模块提供，Loop 继续只依赖协议，不直接读取 HOW 文件。
- Context 的默认背景加载应改为从 Agent Home 门面获得顶层背景条目，而不是由 Loop 直接读取 `AGENT.md`。
- AppBuilder 应保持全局装配入口，但把模块专属构造逻辑下沉到对应模块 builder，避免 `builder.py` 和 `native_actions.py` 累积业务语义。

## Workspace / Agent Home 构建注意事项

- Workspace 应是 `workspace:` 链接的唯一语义归属模块。路径解析、路径归一化、沙箱边界、忽略规则、资源摘要、manifest 更新、读写策略和每日归档都应由 Workspace 门面负责；App 只传入根目录、配置和注册材料。
- Workspace action 不应默认把文件正文写回 Context。WorkingContext 中只应保留资源句柄、摘要、大小、类型、修改时间等轻量信息；需要读取正文时，应在 Phase3 的 action 执行期按链接加载，并作为临时 task prompt 或 action 内部输入使用。
- `workspace.scan` 的当前实现只验证 action -> signal -> context 的协作路径。后续迁移时应保留这个外部行为，但把扫描规则、返回摘要格式和 WorkingContext patch 构造迁出 `tinysoul/app/native_actions.py`。
- Workspace 的启动配置错误、路径不可用、沙箱越界、manifest 损坏和运行时读写失败需要有模块自己的 failure kind，并通过 runtime bridge 转换为少量 Runtime 原因；不要让这些错误只落入 AppBuilder 的兜底 startup failure。
- Agent Home 应负责原始 home 与当日 runtime home 副本的关系，包括顶层内容、渐进式内容、懒加载拷贝、运行时修改、每日 diff 和沉淀决策。App 不应直接读取或解释 HOW / WHAT / WHY / MEMORY 文件结构。
- Context 默认 BackgroundContext 的来源应由 Agent Home 或 Context builder 的装配协议提供。当前 `AGENT.md -> home:agent@core` 的读取是尚未接入 Agent Home 前的装配占位，后续不应扩展为更多 app 侧文件读取逻辑。
- `how_action` 应由 Agent Home 提供 `DomainGuidanceProvider` 实现，并注入 Loop 的 Phase2 / Phase3 prompt 构造；Loop 继续只依赖 provider 协议，不直接感知 home 目录结构。
- Agent Home 链接语义需要明确区分 `home:*@` 顶层背景内容与 `home:*/` 渐进式资源。顶层内容可进入 BackgroundContext；渐进式资源只能通过 action 按链接加载，避免把整个 home 文件树提前塞入模型语境。
- Workspace 与 Agent Home 可以共享 infra 层的路径、JSON 和文件读写基础能力，但不应互相绕过对方门面直接操作对方资源；跨模块协作通过 link、action、context signal 和 builder 注入完成。
- 非终端输入源、ProgramInputEvent 与 InputDispatcher 属于 App 输入边界，不应成为 Workspace / Agent Home 的依赖。Workspace / Agent Home 接收的是装配配置、动作调用和链接请求，而不是外部输入事件。

## 建议验收点

- Loop 中不再出现 workspace 目录扫描实现。
- Loop 中不直接读取 Agent Home 文件内容，只接收 Agent Home / Context builder 提供的背景条目或 provider。
- `workspace.scan` 的行为测试迁移到 Workspace 模块；Loop 只保留装配协作测试。
- Workspace / Agent Home 的配置错误和运行时副本错误有明确 failure kind 与 runtime bridge 映射。
- `docs/design/loop.md` 只描述装配边界，不把 Workspace / Agent Home 内部能力写成 Loop 能力。
