# Agent 重构第一轮子计划：底层依赖与失败协议

状态：`done`（R1.1–R1.5 已实施、文档同步并通过门禁）。
日期：2026-09-15。
主执行计划：[Agent 架构重构](../20260915-agent-architecture-refactor-plan.md)。
对应范围：S1 的依赖与 bridge 子项，本文记为 R1；不等于整个 S1，不调整主计划阶段顺序。
审阅 checkout：`685b065`。相对主计划记录的 `e930c9c`，变更只有 AGENTS.md 与主计划文档，代码基线没有变化。未重新查询远端。

维护者已授权按本计划实施，并要求完成后基于 AGENTS.md 核对子计划和主计划。以下为已确认执行范围；完成状态以实际实现、文档与门禁证据为准。

## 1. 总体判断与第一轮选择

主计划合理可行。它保留已有 Turn/Cycle/Phase、资源 owner、MessageStack、Context 批次、日 lease 和 Home overlay，把变更集中到依赖方向、装配、视图协议与生命周期；没有必要推翻这些已有资产。可行性来自静态代码与调用链检查，尚不等于迁移已经通过验证。

第一轮建议完成一项边界明确的结果：Runtime 不再认识上层模块，所有业务失败由所属模块翻译，LLM 只报告自身容量事实，上层选择恢复。当前运行链路及所有消费者同时接入，删除旧桥接入口。

这项工作从分层依赖出发；异常协议是这条依赖的实际载体。它不是全仓异常清扫，也不代表 SDK、插件或暂停能力已经建成。

选择这一范围的依据：

1. `runtime/bridge/` 中有 14 个桥接实现，另有聚合入口和私有 helper；26 个生产文件直接引用该包。需要覆盖整个消费集合，不能只迁移 LLM 或少数 owner。
2. `maintenance/runtime_bridge.py` 已随 owner 放置，但依赖 `runtime.bridge._payload`，说明仅移动文件不能完成边界整理。
3. LLM 的容量原因、Action 内部任务的资源保护、User/Maintenance Trap 注册形成一条真实协作链，可以验证新边界，而不必引入尚无消费者的 SDK/SPI 空壳。
4. async LLM 的消费者包括 Phase、Action 内部任务、Home/Memory 辅助任务和维护装配；它与 S2 的执行生命周期相邻。只改 LLM 签名，或用同步转发器维持旧调用，都会增加需要再删除的运行路径。

后续仍按主计划完成 S1 的 async/事件/取消工作，并紧接 S2 的新内核与全部消费者迁移。本轮可以完成独立验收，但不能据此标记 S1 完成，也不宣称已达到重构后的部署条件。

## 2. 关键证据与后续影响

| 证据 | 当前事实 | 判断与归属 |
|---|---|---|
| `tinysoul/runtime/bridge/__init__.py` | TYPE_CHECKING + `__getattr__` 汇出上层 bridge | 删除业务聚合入口；不以延迟导入掩盖向上依赖 |
| `tinysoul/runtime/exception.py` | 定义 Context/Home/Workspace 恢复原因 | 领域原因移回 owner；Runtime 保留自身原因 |
| `tinysoul/runtime/bridge/llm.py`、`tinysoul/llm/task.py` | 容量超限直接进入 `context.compression_required` | LLM 原因与 Context 恢复策略解耦，R1 完成 |
| `tinysoul/action/backends/llm_action.py` | 按 Context 原因补充 protected resource links | 新 LLM 原因必须接入同一保护链；本轮不删除资源保护 |
| `tinysoul/loop/context_signals.py` | 先捕获 batch，再在 Module callback 消费 | 保留同批重试，不重新 drain，不重做 Action |
| `tinysoul/runtime/trap/trap.py` | 校验 transfer target 属于捕获 scope | 已有正确契约，保留并验证 |
| `tinysoul/runtime/frame_runner.py` | 已解析 transfer 通过 interrupt 向目标 runner 传播 | 不重复进入 Trap；不新增通用 continuation |
| `tinysoul/runtime/bridge/_payload.py` | 配置原值进入 payload，多数 bridge 使用 `str(error)` | owner 显式构造诊断，R1 覆盖所有迁移 bridge 与调用点 |
| `tinysoul/action/core/runner.py::_run_one` | 未知异常、非法对象、身份错误归入普通 ActionResult | 需修正，但与并行收敛、typed Trace/失败记录一起设计，交 S1 后续/S2 |
| `tinysoul/session/completion.py` | 从 Phase2/3 消息恢复调用配对，缺配对即拒绝记录 | S2 必须先提供 typed 执行事实，不能等 S3 才解决取消/失败记录 |
| `tinysoul/context/engine.py` | Session/Workspace signal 被固定分支解释 | S2 由真实 owner 段承接；不能简单包装旧 ContextEngine 为插件 |
| `tinysoul/llm/task.py::_invoke_provider` | 使用线程等待同步 provider，可离开等待而线程仍工作 | async 迁移应贯通实际 provider 与调用方；R1 不宣称解决取消资源问题 |
| `tinysoul/app/generation.py` | 聚合业务世代，逆序清理但忽略 close 异常 | 后续保留资源生命周期，分开执行结果与清理诊断 |

主计划另外几处需要在后续子计划落实到代码，而不是改写主计划：

- S2 的“段接入”包括 Session/Home/Memory/Workspace 及能力 Action 的全部调用方、资源投影、测试和包入口；S3 仅深化领域行为。
- S2 的 ask/wait/budget 应已有实际内核语义和可用入口；S4 深化环境接入、容量压力和生命周期竞争，不另建第二套等待器。
- S2 的 typed completion 要覆盖已生成但未执行、已开始但结果未知的 Action；不能通过把内部错误包装成普通失败来满足旧 Session 配对假设。
- Plugin 的可替换性要由明确服务依赖和注册贡献证明；Engine/Segment 不得各保存一份领域事实，注册表不能退化为任意字符串 service locator。
- 原子文件写入、Archive journal 与日 lease 仍是必要边界；S3 删除 Workspace CAS 和 Memory 多文档事务不删除这些不同用途的机制。
- ACP/MCP 可行性须在 S6 以选定官方协议、adapter 与测试验证，本轮不把外部能力列为已验证事实。

## 3. R1 的目标依赖与对象职责

```text
现有组合根 / User 与 Maintenance 装配
    → owner 的 Engine、runtime bridge、恢复策略
        → Runtime 公开协议与诊断构造
            → Infra 通用类型与基础设施

LLM → 自身容量原因 → 上层注册的恢复策略 → Context 门面
```

Runtime 不导入 Action、App、Context、Endpoint、Home、LLM、Loop、Maintenance、Memory、Session、Workspace 或 capabilities。Infra 不导入 Runtime。类型检查分支、包级转导出、函数内导入同样属于依赖检查范围。

业务 bridge 仍是小型、明确类型的对象，复用 frozen dataclass 和现有 failure StrEnum；不是业务 Engine 的替代门面。上层正常调用仍通过现有 Engine/Builder，bridge 仅在模块边界翻译失败。

### 3.1 bridge 迁移表

| 当前位置 | R1 位置/处理 |
|---|---|
| `runtime/bridge/action.py` | `action/runtime_bridge.py` |
| `runtime/bridge/app.py` | `app/runtime_bridge.py` |
| `runtime/bridge/context.py` | `context/runtime_bridge.py` |
| `runtime/bridge/endpoint.py` | `endpoint/runtime_bridge.py` |
| `runtime/bridge/home.py` | `home/runtime_bridge.py` |
| `runtime/bridge/llm.py` | `llm/runtime_bridge.py` |
| `runtime/bridge/loop.py` | `loop/runtime_bridge.py` |
| `runtime/bridge/memory.py` | `memory/runtime_bridge.py` |
| `runtime/bridge/session.py` | `session/runtime_bridge.py` |
| `runtime/bridge/workspace.py` | `workspace/runtime_bridge.py` |
| `runtime/bridge/script.py` | `capabilities/script/runtime_bridge.py` |
| `runtime/bridge/shell.py` | `capabilities/shell/runtime_bridge.py` |
| `runtime/bridge/supervised_process.py` | `capabilities/supervised_process/runtime_bridge.py` |
| `maintenance/runtime_bridge.py` | 保留 owner 位置，统一公共构造与诊断协议 |
| `runtime/bridge/infra.py` | 删除；由实际使用 Infra 的装配/模块边界适配 |
| `runtime/bridge/_payload.py` | 拆分通用 Runtime 构造与纯配置诊断，删除私有跨模块入口 |
| `runtime/bridge/__init__.py` | 删除，不提供旧 import alias |

迁移沿用现有类名，不为了文件移动同时重命名所有业务类型。S2 再随模块归属整体移动到 kernel/plugins/agent/gateway；那是同一个实现的搬迁，不创建新旧两份 bridge。

模块内部 bridge 依赖自己的 errors/failures 叶子文件，避免通过本包 `__init__` 引入整个 Engine 后造成导入环。包导出按真实公共消费者保留，不机械增加延迟导入。

### 3.2 领域原因与通用原因

- Context、Home、Workspace 恢复原因放入各自既有 `failures.py`，不为几个常量新增 reasons 文件。
- Runtime 中保留 startup/turn_end/cycle_end/program_end 等自身控制原因。本轮仍存在 Program，因此其改名随 S2 Agent 迁移完成。
- Workspace Trash 恢复原因本轮移动所有权，S3 随压力 Trash 功能一起删除；不提前删除仍有实际消费者的恢复路径。
- RuntimeTransfer 的 RETRY/END 及目标合法性保持现有语义；SUSPEND 随有真实预算等待消费者的后续切片落地，本轮不加无消费者枚举。

### 3.3 Infra 失败的归属

`RuntimeInfraBridge` 当前主要服务 App 构建和 UserTurnBuilder 中 staging 准备。不能把它直接搬进 Infra，否则建立反向依赖。

建议由实际使用边界适配：配置源/项目装配失败由 App bridge 报告启动失败；UserTurnBuilder 中执行资源准备失败由该装配边界的 Loop bridge 报告启动失败，稳定 kind 应表达资源准备而非误称配置校验。待 S2 把组合根移至 Agent，装配职责一并迁移。

模块自身配置解释失败仍使用模块 bridge。共享配置加载无法归到业务 owner 时，由组合根负责；不得把未知配置 key 都伪装成某个插件内部故障。

移除 Infra bridge 后检查 `InfraFailureKind` 的真实消费者；若仅剩该 bridge 与汇出测试，则一起删除，Infra 继续暴露 ConfigError/StagingError 等自身异常。

## 4. 失败协议与容量恢复链

### 4.1 公共构造与 owner 诊断

公共 Runtime helper 建议放入 `runtime/failures.py`，只处理 module、kind、reason、message 和已经投影的 JSON details；failure→reason 映射仍保留在各 owner bridge。它不检查业务异常类，不访问配置对象，不推测字段含义。

ConfigError 的纯诊断投影可复用 `infra/config/errors.py`，返回有界的 key、expected 等明确字段；不依赖 Runtime，不携带原始 value，不直接复制可能包含绝对路径的 source。避免 14 个 bridge 各实现一份配置序列化。

每个 bridge 按失败种类生成简短说明，保留 module、全局 kind、error_type 及有消费者的身份/度量。原始异常通过 `raise ... from exc` 保留调试链；message 和 payload 不默认串接 `str(exc)`。也必须检查调用点主动传入的 message/details，不能只改 helper 就宣称完成。

容量 token/字符估计、image usage、必要资源 Link 等恢复输入必须保留；通用“删掉所有动态字段”会破坏恢复协议。资源正文、完整消息栈、配置原值与原始供应商响应不进入这些诊断。

本轮不建立通用脱敏框架、不重写全部 ConfigError，也不全仓替换所有宽泛捕获；范围是迁移后的 Runtime 失败边界及其实际消费者。

### 4.2 LLM 容量原因与调用方恢复权限

建议新增 LLM 自己的原因 `LLM_CONTEXT_CAPACITY_EXCEEDED = "llm.context_capacity_exceeded"`，由 LLM failure/bridge 声明。Context 自身预算不足继续使用自己的原因。两者可以由装配注册到同一恢复策略，但 LLM 不导入 Context 原因。

现有 `ModelContextOverflowPolicy` 表达的调用方选择有实际用途：构造式 Context Task 可以请求外层恢复，独立且输入固定的 Task 未必可以。因此不简单删除该选择，也不让所有 LLM 容量失败都触发 Context 压缩。建议其值收敛为 `FAIL` / `REQUEST_RECOVERY`，取消由 LLM 指定“结束 Turn / 重组 Context”的上层业务措辞；相关 TaskCall、failure kind 与全部调用方同步更新，无旧值 alias。

行为约定：

1. 固定输入/不允许外层恢复：容量失败按 LLM 模块失败收束，不反复调用相同请求。
2. 允许外层恢复：LLM 报告自身容量原因及现有 ModelContextUsage 投影。
3. User/Maintenance 装配分别登记自己的恢复策略，同时处理 LLM 容量原因与 Context 预算原因。
4. 策略通过 Context 公共门面回收并判断实际进展；仅对已声明可重放的边界返回 RETRY，无进展则结束，不因改名增加无限重试。
5. Action 内部任务仍携带目标/参考资源保护信息，必须同时识别 LLM 容量与 Context 自身预算两条路径。
6. 重试要重新构造 Task 的 MessageStack；不能仅把旧 TaskCall 再次送给 LLM。容量检查发生在副作用提交前，已提交 Action 和此前批次不得重放。

R1 复用现有 Phase/Module runner 和 User/Maintenance 恢复实现；通用段回收算法、Workspace 去压力 Trash 属于后续阶段。不能把现有 Workspace 特有回收逻辑塞入底层 Context，以追求本轮目录上的统一。

### 4.3 保持三层语义

| 场景 | R1 后的边界 |
|---|---|
| 模型回答不符合解释协议、无效 Action 参数 | 原有 typed 局部结果，下一完整 Cycle；不提升为 Runtime 失败 |
| 模块配置、契约、不变量与持久依赖失败 | owner bridge → RuntimeException → 注册的 Trap |
| LLM 供应商重试/模型链切换 | 仍由 LLM 本地完成；耗尽才桥接 |
| RuntimeException/RuntimeTransferInterrupt | 已归类控制继续传播；不再次包装或重新陷入 |
| 已有 Task/Action 取消 | 保持已有身份与传播，R1 不宣称统一 async 取消已完成 |
| Observation sink 失败 | 旁路隔离，不能改变结果与转移 |

Action runner 对未知异常和身份错配的分类修正留到执行链子计划，届时必须同时处理 sibling 收敛和 typed completion。R1 记录该缺口，不把已有局部包装作为目标架构认可，也不在这里只改一个 `raise` 留下取消与 Session 记录问题。

## 5. 执行拆分与验收

以下条目均已完成；S1 的 async/事件/取消剩余范围继续由主计划安排。

| 条目 | 实施内容 | 必须交付的证据 |
|---|---|---|
| R1.1 | 建立公开 Runtime 构造；配置诊断归 Infra；明确 owner message/details | helper 不 import 业务；保留恢复度量；合成异常/配置原值不进入边界诊断 |
| R1.2 | 全部 bridge、原因及消费者迁移；清除旧入口与无消费者 Infra failure | 静态依赖检查、全包导入；旧路径无活跃代码引用；模块自己维护映射 |
| R1.3 | LLM 容量原因、调用策略、User/Maintenance 注册及 Action 保护同步 | fake provider 验证恢复后 MessageStack 改变、固定输入不循环、保护 Link 生效 |
| R1.4 | 审阅迁移边界三层语义；重放、取消和 Observation 回归 | 同批 Context 重试不重新取队列，先前 Action 不重复，控制身份不被吞掉 |
| R1.5 | 按实现同步设计与测试，执行完整门禁：Fast 983 passed/2 skipped，Full 988 passed/2 skipped，typecheck passed。 | 聚焦 → Fast → Full → typecheck；核对改动文件、删除入口、文档路径与计划状态 |

这五项是同一子计划的实现顺序，不是每项都新增一组框架。文件移动、调用点和对应测试应形成可审阅的提交；不通过临时 alias 让中间状态长期存在。

测试组织建议：

- Runtime 的 scope/trap/transfer/helper/Observation 契约由 `tests/runtime/` 覆盖，使用测试原因标识，不依赖业务恢复常量。
- bridge 分类与失败投影跟随 owner 测试；已有 `tests/runtime/test_bridge_exports.py` 的中央汇出假设删除。
- 全局 failure 命名/import 方向检查作为架构契约验证，不以“文件必须有多少个”或提示词全文作断言；尽量复用现有测试切面，只在职责确有独立性时新增文件。
- 跨模块保留代表路径：User 与 Maintenance 各自的容量恢复、嵌套 LLM Action 资源保护、Context 捕获批次重放、模块失败退出、Observation 失败隔离。
- R1 不触网，fake provider 足以检验协议；Full 中的 generation/wheel 验收不跳过，不把真实供应商 smoke 冒充本地通过证据。

## 6. 文件与文档边界

生产改动集中在各 owner 的 `runtime_bridge.py`/`failures.py`、公共 helper、包导出、既有装配与引用位置；旧 `runtime/bridge/` 入口已删除；容量语义还涉及 `llm/task.py`、`llm/requests.py`、`action/backends/llm_action.py`、`loop/user/runtime.py` 和 `maintenance/turn/runtime.py`。

设计同步以 `docs/design/runtime.md`、`llm.md`、`loop.md`、`context.md`、`action.md` 为主，其他 owner 文档仅修改实际受影响的 bridge/失败说明。现有 Runtime 文档仍有 Phase 内重复模型调用等陈旧表述，触及相关章节时应按现有 PhaseFailure 代码修正，不复制到新文档。

不新建 `kernel/`、`agent/` 或插件壳，不改 Session schema、Workspace 写协议、Memory 事务、Home review、Action domain、项目配置 section 或前端代码。若 Endpoint 的可观察错误 payload 因 owner 迁移发生变化，必须核对并同步对接文档；不能仅因未改路由就声称协议完全未受影响。

本轮不修改部署数据、不 reset 项目、不替换真实 provider SDK、不调整 AGENTS 已确认目标。主计划保持阶段与内容，只在实际验收后记录 S1 对应子项进度；R1 完成文件移入 `docs/analysis/done/` 并加入 `-done-`，S1 仍保留未完成状态。

## 7. 待确认范围与后续衔接

R1.1–R1.5 已完成：全量 bridge 消费者迁移、Infra 特例处理、LLM 容量恢复链、三层失败边界审阅及测试/文档同步均已落地。主计划的 SDK、段、Job、SUSPEND、async/事件/取消仍未完成。

建议下一组子计划一起设计 S1 剩余 async/事件/取消与 S2 消费迁移：原生 async provider → LLM Task → Phase/Action → Turn；所有短 owner 操作通过明确 async 适配完成后退出边界；用一条实际运行链验证 SDK submit → wait → resume → finish。段 prepare/install、typed Trace/TurnCompletion、Plugin 注册与真实 owner 接入必须在这一组中一起闭合。

届时再锁定 SDK 请求/结果与 rejection 类型、段能力组合及注册泛型、等待与 Job 的竞争边界、typed completion 对未完成 Action 的表达。只为已有消费者增加协议，公开结果不依赖 Observation 是否成功发送。

如果维护者希望第一轮以 SDK 可运行闭环为交付，范围应明确扩大为主计划 S1+S2 的完整迁移，而不是把 R1 称作 SDK 完成。当前推荐先实施 R1，以一个可独立审阅和验收的依赖边界开局。
