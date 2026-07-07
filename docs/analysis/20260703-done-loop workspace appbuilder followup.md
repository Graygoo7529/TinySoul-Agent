# 20260707 loop workspace appbuilder followup

## 状态

status: done

本文记录 App 装配层中与 Workspace、Agent Home 后续模块相关的遗留装配问题。Loop 与 App 已拆分：Loop 保留 Program/Turn/Cycle/Phase 运行编排，App 负责 TinySoulApp 装配入口、输入源、输入解析与输入分发。本文记录的问题已通过 Workspace 与 Agent Home 基础接入处理；剩余项继续进入后续模块切面推进。

## 当前实现位置

- `tinysoul/app/builder.py` 的 `TinySoulAppBuilder` 负责装配 LLM、Workspace、Agent Home、Action、Context、SignalBus、RuntimeTrap、输入分发器、输入源和各级 loop runner。
- `workspace.scan` 仍在 `TinySoulAppBuilder._build_action()` 中注册，但实现已迁入 `tinysoul/workspace/actions.py`，并通过 `WorkspaceEngine` 完成扫描、manifest 更新和 `context.working.patch` 同步。
- App 层旧的 `workspace.scan` 临时实现已从 `tinysoul/app/native_actions.py` 删除，app 层只保留 `core.answer`。
- Phase2 的 domain guidance 通过 `HomeDomainGuidanceProvider` 注入，并从 Agent Home 的 `home:how_action@<domain>` 顶层内容读取。
- Context 默认背景通过 Agent Home 门面加载 `home:agent@core`，AppBuilder 不再直接读取项目根目录 `AGENT.md`。
- Agent Home 已接入 `home.resource.read` 渐进式资源读取 action、显式 runtime home 副本准备和 `HOME_RUNTIME_COPY_REQUIRED` trap handler。

## 设计意图

App 的职责是进程装配、生命周期和外部输入边界，不应长期承担 workspace 文件扫描、Agent Home 内容读取、运行时副本管理、how_action 检索或每日沉淀策略。

当前保留 `workspace.scan` 在 AppBuilder 中注册，是因为 AppBuilder 仍承担跨模块装配入口；具体扫描语义已经下沉到 Workspace 模块。这个通道继续验证 Phase3 可以通过 action -> signal 向 WorkingContext 写入 workspace 资源摘要，但 App 不再拥有 workspace 业务实现。

## 已处理问题

- `workspace.scan` 的扫描规则、跳过目录、数量上限、摘要格式已迁出 App 装配层，由 Workspace 模块维护。
- Workspace 已维护 manifest，并将扫描结果投影为 WorkingContext 可消费的轻量资源摘要。
- `DomainGuidanceProvider` 已接入 Agent Home，Phase2 可以自动获得 `how_action/<domain>` 的 HOW 文档。
- Context 默认背景来源已改为 Agent Home 门面，AppBuilder 不直接读取 `AGENT.md`。
- Workspace / Agent Home 已拥有独立 failure kind 和 runtime bridge，启动期模块失败不再只能落入 AppBuilder 兜底。

## 仍需推进

- `WorkspaceEngine` 当前只覆盖扫描和 manifest，仍需补充 read/write/patch/delete、单资源摘要刷新、删除检测和日终归档。
- Agent Home 当前只覆盖背景、guidance、只读渐进式资源和显式 runtime copy，仍需补充检索、写入、patch、memory append、HOW 使用反馈和每日沉淀。
- `TinySoulAppBuilder` 仍是全局装配入口，随着模块增多可以继续抽出更细的模块注册方法，但不应把业务语义重新放回 app。

## 后续扩展方向

- Workspace 模块继续补齐 workspace read/write/patch/delete、删除检测、单资源摘要刷新和日终归档。
- Workspace 模块继续通过稳定信号或返回结果更新 WorkingContext，保持“文件内容不直接进入 Context，Context 只持有 workspace 链接和摘要”的规则。
- Agent Home 模块继续补齐原始 home 与当日 runtime home 的可写资源操作、检索、HOW/HOW_ACTION 使用反馈、memory append 和每日沉淀。
- Loop 继续只依赖 `DomainGuidanceProvider` 协议，不直接读取 HOW 文件。
- Context 继续只消费 Agent Home 提供的背景条目，不直接打开 home 文件。
- AppBuilder 保持全局装配入口，但模块专属业务逻辑应继续下沉到对应模块 builder、engine、action executor 或 trap handler，避免 `builder.py` 和 `native_actions.py` 累积业务语义。

## Workspace / Agent Home 构建注意事项

- Workspace 应是 `workspace:` 链接的唯一语义归属模块。路径解析、路径归一化、沙箱边界、忽略规则、资源摘要、manifest 更新、读写策略和每日归档都应由 Workspace 门面负责；App 只传入根目录、配置和注册材料。
- Workspace action 不应默认把文件正文写回 Context。WorkingContext 中只应保留资源句柄、摘要、大小、类型、修改时间等轻量信息；需要读取正文时，应在 Phase3 的 action 执行期按链接加载，并作为临时 task prompt 或 action 内部输入使用。
- `workspace.scan` 当前实现保留 action -> signal -> context 的协作路径，扫描规则、返回摘要格式和 WorkingContext patch 构造已经迁出 `tinysoul/app/native_actions.py`。
- Workspace 的启动配置错误、路径不可用、沙箱越界、manifest 损坏和运行时读写失败需要有模块自己的 failure kind，并通过 runtime bridge 转换为少量 Runtime 原因；不要让这些错误只落入 AppBuilder 的兜底 startup failure。
- Agent Home 应负责原始 home 与当日 runtime home 副本的关系，包括顶层内容、渐进式内容、懒加载拷贝、运行时修改、每日 diff 和沉淀决策。App 不应直接读取或解释 HOW / WHAT / WHY / MEMORY 文件结构。
- Context 默认 BackgroundContext 的来源由 Agent Home 门面提供，后续不应扩展为更多 app 侧文件读取逻辑。
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
