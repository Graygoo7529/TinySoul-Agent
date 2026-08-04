# App 设计

## 定位

App 模块负责 TinySoul 的进程级装配、生命周期、外部输入边界和外部输出边界。它把 infra、llm、action、context、runtime 与 loop 组装成可运行的 TinySoulApp，把终端、API、HTTP、WebSocket 或其他来源的外部输入统一转换为内部输入事件，并把非控制性的运行观察事件路由到终端或嵌入方提供的输出端。

App 拥有 Program request queue、Program frame 和顶层分派，但不实现 Turn/Cycle/Phase 内核，不维护 Context 状态，不执行 Action，也不适配模型供应商。Program 只把 typed request 分派给 User Turn 或 MaintenanceEngine；可复用 Turn 运行语义仍由 loop 模块负责。

## 目录组织

```text
tinysoul/app/
  program.py         # 顶层请求队列、分派与 Program frame
  requests.py        # UserTurnRequest / MaintenanceRequest / ExitRequest
  config.py          # AppSettings 与输入/输出配置
  errors.py          # app 契约与不变量错误
  failures.py        # app Runtime bridge 失败枚举
  gateway.py         # AppCommandGateway 统一命令与控制入口
  inputs.py          # InputEvent、InputCommandParser、InputDispatcher
  initializer.py     # package project template 初始化
  outputs.py         # OutputSink、ObservationRouter 与终端渲染
  cli.py             # console script 入口
  runtime.py         # TinySoulApp 生命周期入口
  services.py        # Endpoint 等长运行 AppService 生命周期协议
  builder.py         # TinySoulAppBuilder 全局装配入口
  sources/
    terminal.py      # 终端输入源
    scheduler.py     # typed Maintenance request scheduler
```

可编辑项目模板位于 `tinysoul/assets/project/` 并作为 package data 发布；只读 Action Catalog 位于 `tinysoul/action/catalog/`。项目模板只保存一份 README、`.gitignore`、`tinysoul.toml` 与 Home，并保存完整、彼此独立的 standard/development config profile。App 初始化前者，但不复制或改写 Action Catalog。

App 的 Runtime bridge 位于 `tinysoul/runtime/bridge/app.py`，用于将 app 装配或输入边界失败映射为 Runtime 可理解的启动失败或控制流失败。

## 输入模型

外部输入源不直接操作 SignalBus。所有外部输入先转换为 `InputEvent`，再进入 app 的输入解析和分发流程。

输入处理分为三层：

- `AppCommandGateway` 是唯一外部命令入口；它区分可信终端命令与普通用户文本，协调 typed control、Maintenance request 和活跃 Turn Workspace snapshot；
- `InputCommandParser` 是纯解析器，无副作用；它根据当前是否存在活跃 Turn，把 InputEvent 分类为启动 Turn、追加输入、停止 Turn、Daily/Home/Memory Maintenance、拒绝的命令、退出 Program 或忽略；
- `InputDispatcher` 承担副作用；它将 `UserTurnRequest`、`MaintenanceRequest` 和 `ExitRequest` 投递到 ProgramRunner 队列，将 Turn 内追加输入转换为 `context.input.append` 信号，将 Turn 内控制请求转换为 `loop.control.request` 信号。

Maintenance 命令无论 User Turn 是否活跃都进入 Program queue，不解释为 append，也不存在 `apply/discard/stop` decision channel。`source` 只用于审计，不承担授权。

## Program 输入队列

ProgramRunner 等待的是 `AppRequest = UserTurnRequest | MaintenanceRequest | ExitRequest`，而不是原始字符串或带 kind 字符串的平行事件模型。

空闲状态下的普通输入变成 UserTurnRequest，维护指令变成 MaintenanceRequest，退出命令变成 ExitRequest。这样 ProgramRunner 阻塞等待时总能被顶层 request 唤醒，不依赖 SignalBus 唤醒外部输入。

Turn 活跃期间的普通输入和 Turn 控制命令不进入 Program 队列，而是由 InputDispatcher 转换为内部信号，由 loop 在 Phase/Cycle 边界消费。Maintenance 是 Program work，即使在 Turn 活跃时也始终排入 Program 队列，不形成 `context.input.append`；它会在当前 Turn 收束后执行。

## 输入源

终端等外部输入源实现 `InputSource` 协议，只负责生产 InputEvent；时间触发源实现独立的 `ProgramRequestSource`，只负责生产 typed AppRequest：

- `TerminalInputSource` 从 stdin 读取行输入；stdin 到 EOF 时，它提交配置中的首个 Program 退出命令，使阻塞中的 ProgramRunner 通过正常输入/Trap 流程结束；
- 内置 `MaintenanceScheduler` 是时间驱动的 `ProgramRequestSource`，只向 Program 投递一个到期的 Daily MaintenanceRequest，不在 scheduler 线程直接调用业务模块；
- 测试或嵌入式调用可以调用普通文本语义的 `TinySoulApp.submit_input()`；只有受信任的本地命令行适配器使用 `submit_interactive_event()`；
- HTTP/WebSocket Endpoint 是独立 AppService，通过 AppCommandGateway 提交输入和控制，不伪装成 InputSource；后续长运行传输适配器遵循相同边界。

外部框架只应出现在 source adapter 内部，不应进入 loop、context、action 或 llm 的核心语义。

`TinySoulApp.run()` 依次启动 Program request source、AppService 和外部 input source，并在程序退出或启动失败时按逆序停止全部已启动组件。`run_once()` 不启动这些长运行组件，因此不会创建 scheduler 或 Endpoint 线程，但 ProgramRunner 仍执行 Daily preflight。停止过程采用 best-effort。

## 输出与观察事件

`ObservationEvent` 是 Runtime 定义的 provider-neutral、JSON 安全旁路事件，携带稳定名称、详细度、来源、运行位置、消息和结构化 payload。它不进入 SignalBus，不由业务消费者提交状态，也不能触发 Trap 或改变运行转移。业务运行器只发布事件；App 的 `ObservationRouter` 根据配置过滤并扇出到 `OutputSink`。

输出详细度是包含关系：

- `normal` 输出已完成并通过 Turn completion pipeline 提交的最终回答、可行动的 Maintenance 提示、Program work 唯一结果、Daily transition completed/recovered/failed，以及 failed/exhausted/stopped 等需要用户感知的边界；
- `verbose` 在 normal 之上增加 Program、Turn、Phase、模型尝试、Action batch、Runtime trap、Daily transition started 和 Home/Memory Maintenance 细节事件；
- `model` 在 verbose 之上增加 provider-neutral 的模型请求与归一化响应。

MODEL 事件可能包含完整文本 prompt 和模型回答；Console 只应在明确需要诊断时选择 model，Endpoint 则固定捕获该层级供可信本地前端渐进展示。图片字节只记录长度、MIME 与 digest，远程图片 URL 去掉 query/fragment，data URL 被替换为 redacted 标记；推理只保留 summary 和 encrypted item digest，不输出 reasoning content、加密项原文或 provider 原始 payload。Console 渲染再按 `app.output.model_max_chars` 限制单条诊断文本。

`OutputSink.write` 属于外部 I/O 边界。单个 sink 失败后由 router 禁用并记录，不能反向打断 Turn、修改 Session/Workspace 提交或伪装成 Runtime 控制异常；`TinySoulApp.run()` / `run_once()` 在业务边界结束后把累计失败报告为 `AppOutputError`。`ConsoleOutputSink` 只把已完成 completion 提交的最终回答写到 stdout；failed/exhausted/stopped 和 verbose/model 诊断写到 stderr，便于脚本分别消费结果和诊断。

`tinysoul start` 是正式交互 App 入口。它从 `--root` 或当前目录加载项目配置，在同一 AppBuilder 中启动 Terminal input、Console sink、scheduler 和 authenticated Endpoint；`--mode normal|verbose|model` 只覆盖 Terminal Console route，Endpoint route 始终为 model。`tinysoul start --once TEXT` 关闭交互输入、scheduler 和 Endpoint，只执行一个 User Turn，但仍持有同一项目进程 lease；只有 `TurnOutcomeStatus.ANSWERED` 返回 0，exhausted/stopped/failed 均返回 1。无子命令和 `serve` 不构成并行运行入口。

`tinysoul init [DIRECTORY]` 是独立项目初始化命令。`ProjectInitializer` 从已安装包读取公共模板与所选 config profile，确定性合成为普通项目结构，先完整写入目标同级 staging，再安装到不存在或空目录；文件、symlink 或非空目录都被拒绝，不覆盖现有内容。`--config-profile standard|development` 只选择初始 `configs/` 与 `.env.example`，默认 standard；standard 的 provider 全部 disabled 且 host-sensitive capability 使用安全默认值，development 保存项目维护者已启用但不含凭据的开发配置。profile 不安装依赖或 executable，不进入生成项目，也不成为 ConfigEnvironment 的运行时来源。命令不接收 `--provider`。公共模板包含 `tinysoul.toml`、唯一默认 Home、`.gitignore` 和项目 README，initializer 另外建立空的默认顶层 `memory/`；项目不包含 package-owned Action Catalog。生成后 configs/Home 完全归项目所有，package 更新不自动修改已有项目。

`tinysoul reset DIRECTORY` 是面向专用开发项目的显式破坏性重建命令。它只接受带普通 `tinysoul.toml` 的已有目录，调用方工作目录必须位于目标外，并在任何读取/替换前持有与 `start` 相同的项目进程 lease。`ProjectResetter` 默认选择 development profile，也允许显式 standard；它先在目标同级 staging 完整生成新项目并按原始字节复制已有普通 `.env`，再以旧目录备份、新目录安装和旧目录清理组成可回滚替换。除 `.env` 外，旧 Home、configs、Memory、runtime、archive、对话数据和其它项目条目均不保留；目标或 `.env` 为 symlink、`.env` 不是普通文件、项目正在运行或新目录无法安装时拒绝，安装失败时恢复旧目录。reset 不保存 profile identity，也不改变 Infra 运行时配置来源。

### 项目模板维护

源码仓库不再同时充当可运行项目。初始化资源只在 `tinysoul/assets/project/` 维护：公共资源位于目录根和 `home/`，profile-owned 资源分别位于 `config_profiles/standard/` 与 `config_profiles/development/`。仓库根不得重新出现用于开发运行的 configs/Home 镜像；真实运行和 provider smoke 使用外部初始化项目。

模板变更遵循以下一致性规则：

- 默认 Home 的 AGENT、WHAT、WHY、通用 HOW、domain HOW、action HOW 及渐进资源只修改共享 `project/home/`；Home 不按 profile 分叉。运行中 Home Maintenance 提交的是具体项目的 actual Home，不会更新 package template；需要改进未来项目的默认内容时必须另行修改 assets。
- 两套 config profile 都是完整快照，不是 overlay。配置 schema、模块 section、模型定义或 include 文件发生增删改时，应同时审查两套 profile，并保持相同的相对 TOML 文件集合；standard 与 development 只在明确记录的 enabled、provider、模型选择和其它开发取值上分化。
- standard 必须保持可分发的安全初始状态；development 可以反映维护者的当前非敏感开发选择，但不能包含 `.env`、密钥、本机绝对路径、runtime 或 archive。每套 `.env.example` 只列出该 profile 所引用的变量名和空值。
- `tinysoul.toml` 的 include 必须能覆盖两套 profile 的完整文件形状。新增目录深度、文件类型或资源类别时同时更新 setuptools package-data；普通同层 TOML/Markdown 增删仍须由 wheel 测试证明实际进入安装包。
- initializer 与 wheel 验收必须覆盖默认 standard、显式 development、内部 `config_profiles/` 不泄漏、共享 Home 内容一致、两套 configs 文件形状一致，以及 clean-source wheel 隔离安装。已初始化项目只能作为真实运行验收对象，不能复制回来覆盖模板。

## 装配入口

TinySoulAppBuilder 负责：

- 加载 ConfigEnvironment；
- 从统一 ConfigEnvironment 读取各模块 section tree，由 app/capabilities/context/home/memory/loop/session/workspace/llm 各自解析所属 settings；Action Catalog 直接读取 package resource，不存在项目级 action path 配置；
- 构建 LLMTaskRunner、ContextEngine、SessionEngine、WorkspaceEngine、AgentHomeEngine、MemoryEngine、ActionEngine、SignalBus 和 RuntimeTrap；
- 调用各模块和已启用 capability 的 registrar 装配 executor，并在 ActionEngine build 前移除禁用 action；
- 构建共用 Phase/Cycle、User/Maintenance Turn、MaintenanceEngine 与 ProgramRunner，并向 MaintenanceEngine 注入默认 IANA business clock 和 Archive coordinator；测试或嵌入方可通过 `with_business_clock` 注入同一窄 `BusinessClock` 协议，不改变生产默认时区语义；
- preparation 顺序固定为 Context 聚合 Home/Memory Background provider、Session、Workspace；把幂等 Session completion 放在外部 `with_turn_completion_handler` 注册项前；
- 构建 InputCommandParser、InputDispatcher、AppCommandGateway、终端输入源、Endpoint service 和内置 scheduler；
- 构建 ObservationRouter，把同一 emitter 注入 LLM、Action、Runtime、Workspace、Daily coordinator、Home/Memory Maintenance service 和各级 Loop runner；
- 返回 TinySoulApp。

AppBuilder 是跨模块配置装配边界，但配置错误归属仍属于对应模块。项目配置由 `tinysoul.toml` 显式 include `configs/*.toml` 和模型文件；Infra 只加载与合并，Context、LLM、Loop、App、Session、Workspace、Agent Home、Memory 和 Capabilities 在各自 parser 中解释 section tree。Action 在 package resource 上执行自己的 TOML 加载与 catalog 校验。AppBuilder 在对应 bridge 映射 ConfigError，不把所有装配期配置错误统一归为 app 或 infra 失败。

Resource capability 在此边界解析 `[capabilities.resource]`，检查 enabled action 推导出的依赖，为 Workspace Domain 的 `workspace.convert_with_markitdown`/`workspace.convert_with_pypdf` 注册 `resource.*` handler，或把禁用 action 从 effective Catalog 移除。AppBuilder 不解析文档、不选择 converter，也不读取转换正文；Home prompt mount reconciliation 只观察 ActionEngine 最终暴露的 domain/action identities。

Script capability 在此边界解析 `[capabilities.script]`，装配 Workspace transaction mirror、Home/Workspace source resolver、Turn-scoped job manager 和 Script registrar，并为 Execution Domain 注册脚本 author/run handler。AppBuilder 不解释脚本正文、job state 或 candidate diff；TurnRunner 只接收通用 activity controller，用于在普通 Cycle 预算后申请有限额外 Cycle并在 Turn 边界 cleanup。Python 默认启用，Bash 只有显式启用且 executable 检查通过时才进入 effective Catalog。

AppBuilder 解析 `[capabilities.supervised_process]` 并只装配一个 Shared Supervised Process manager、Workspace transaction coordinator、共享 lifecycle registrar 和 activity controller，再把同一 manager 注入 Script 与 Shell registrar；不会为两个 capability 各建一个 Turn job或向 Loop 注入两个 controller。Script 继续解析 source/Python/Bash 配置；Shell 独立解析 PowerShell/Cmd/Bash 和 command policy 配置。各 registrar 按有效 adapter 移除具体 Action；只要仍有任一 Script/Shell run Action，共享 `execution.wait/stop/read_candidate/apply/discard` 就保留。Execution Domain 内全部 Action 都被移除后，Home mount reconciliation 才不再观察该 domain。App 不解释脚本源码、Shell command、job state、日志或 candidate diff。

`core.answer` 由 Action builtins core actions 提供，不属于 app 装配层 native action。Workspace、Agent Home、Memory 和内置 core action 的具体语义由对应模块提供 registrar、executor 或 provider，AppBuilder 只完成跨模块注册，不直接实现 workspace 扫描、链接解析、资源摘要、Background 加载或 how_domain/how_action HOW。Workspace 的 prompt reference resolver 与 Agent Home 的 action HOW provider 在装配期注入 action 层共享 LLM action backend；Home-owned `LLMHomeSearchReranker` 与 Memory-owned `LLMMemorySearchReranker` 分别注入所属搜索服务，候选构造、校验和 fallback 仍归各业务模块。ActionEngine 构建后，AppBuilder 读取其只读 domain/action identities 并调用 Home mount reconciliation；App 不解析 catalog 文件，也不决定 mount 路径或删除语义。

AppBuilder 构建一个 `MaintenanceEngine` 并注入 `ProgramRunner` 和 Endpoint。MaintenanceEngine 内部组合 `maintenance.archive` 的 DailyLifecycleCoordinator、持久 Availability store、HomeMaintenanceTask 与 MemoryMaintenanceTask；Home/Memory task 需要推理时再调用各自的 Maintenance Turn。长运行 Program 启动先恢复并补做 Session/Workspace/Trash 日切，再增量登记本次归档日、校验既有 Memory 待办、重算 Home pending 并原子保存唯一 availability；该步骤完成后 Endpoint 才能对外就绪。Program 以 `program.maintenance.available` 给出包含一个聚合 Home 待办和全部 Memory 日期的非阻塞提示，Observation 只通知前端重新读取 Endpoint 投影，不在启动时运行 Home/Memory Turn。

Program 运行期的 availability、User request preflight 或 Maintenance request 若遇到 Maintenance contract/invariant failure，统一经 `RuntimeMaintenanceBridge` 转换为 `runtime.program_end`，由当前 Program trap 形成 `ProgramOutcome.transfer`；启动 `prepare()` 的 preflight 仍映射为 `runtime.startup_failed`。Maintenance Turn 已经决议的外层 Program transfer 只展开和消费一次，不重复进入 Trap。未知 Python 异常原样传播，不能伪装成 task failure。

人工命令为 `/maintenance [daily|home]` 与 `/maintenance memory YYYY-MM-DD [--rebuild]`；Endpoint 以结构化 `kind=daily|home|memory` 表达相同意图，其中 Memory 必须提供 target，rebuild 只对该目标生效。人工和 scheduler request 只在 trigger/参数上不同，进入 MaintenanceEngine 后使用同一个任务选择、执行路径和 outcome；不存在持久 `MaintenancePlan`。整个流程自动执行，不存在 decision identity、审批 Endpoint 或 pending 输入阻塞。

`ProjectInstanceLease` 在 AppBuilder 构建业务 Engine 前持有规范化项目根对应的 OS 排他锁。Endpoint 监听成功后，lease 在当前用户运行目录原子发布连接描述，包含 project/instance identity、PID、loopback host、随机端口、进程 token 和协议版本；正常退出时删除描述并释放锁。重复 `start` 必须在任何第二个 WorkspaceEngine 出现前失败。EndpointEngine 是无生命周期的 application facade，EndpointHost 作为 AppService 延迟加载并启停 ASGI server；有界 event buffer 只作为固定 MODEL 的 ObservationRouter sink。

`maintenance.schedule.enabled` 默认开启，`maintenance.schedule.daily_time` 默认 `00:15`，按 `maintenance.timezone` 的本地墙钟解释。scheduler 每日只投递一个 Daily request；启动晚于当日时刻不追补模型任务，Program 只报告完整 availability。计划时刻前已运行的进程按时投递；运行中休眠跨过一个或多个时刻时合并为一个当前日 request。Daily preflight 先收束归档，然后运行 Home task，并且至多运行当前 Maintenance BusinessDay 的昨日一个 Memory task；更早欠账跨重启保留，等待明确日期的 Memory request，不依赖 scheduler cursor 或全量 Archive 扫描。

这些入口由 App 负责外部触发与装配；availability 与 Archive/Home/Memory 编排和 outcome 归 MaintenanceEngine，Home diff mutation 归 Agent Home，Session/Workspace archive projection 归各自 owner，MEMORY 搜索/召回/写入归 Memory。CLI、Endpoint 和 scheduler 不能直接读写业务根。App 不建立 settlement root，也不持久化审批或 review 状态。外部命令发布 `app.command.accepted/rejected`，MaintenanceEngine 发布 `maintenance.started/completed` 与 availability changed，Archive owner 发布 `daily.transition.*`。

无网络 App E2E 应关闭 scheduler，以注入的受控 BusinessClock 和直接投递的 typed AppRequest 验证正式装配链：旧日 User Turn 写 Home overlay，Program preflight 完成 Daily archive，Daily Maintenance 通过 Home/Memory Maintenance Turn 处理变更与记忆，后续 User Turn 自动获得昨日 MEMORY。fake LLM 只替换 provider runner，不替换 App/Maintenance/Loop/Home/Memory/Session/Action/Context 门面。

发布验收另外构建 wheel、检查 package catalog/template 条目、隔离安装 wheel 并从安装包执行 `tinysoul init`。fake-provider CLI E2E 从生成项目启动本地 OpenAI-compatible HTTP provider，实际经过 ConfigEnvironment、provider adapter、Phase1、Phase2、Phase3 和 `core.answer`，不以注入 FakeLLM 代替供应商边界。真实 provider App/CLI smoke 默认 skip，只有显式设置测试开关和已配置项目根时运行。

## 与其他模块的关系

- 对 loop：app 分别创建 User/Maintenance Turn 与共用 Cycle/Phase，并把 UserTurnRequest 分派到 User Turn；Turn 活跃期间通过 SignalBus 发出 loop/control 与 context/input 信号。
- 对 maintenance：app 构建 MaintenanceEngine、Archive/Home/Memory task 与 scheduler，并把 MaintenanceRequest 分派到唯一维护门面；不解释任务内部事实。
- 对 runtime：app 注册 Trap handler，并通过 RuntimeAppBridge 映射 app 边界失败。
- 对 action：app 调用模块 registrar 注册 action executor；具体 action 语义仍由 action 模块调度，由对应业务模块执行。
- 对 context：app 注入 Home/Memory 的 `BackgroundEntryProvider`，不物化 core、不读取 Agent Home 或 Memory 文件。它同时装配共享 ContextSignalConsumer 和 TurnCompletionPipeline 接入点。
- 对 session：app 只构建门面、注册 `core.session.inspect` executor 和安装 Turn preparation/completion adapters，不读取 Session 持久文件，也不向 Endpoint 暴露专用历史查询。
- 对 workspace / Agent Home / Memory：app 只装配模块门面、provider 和 executor，不解释 `workspace:`、`home:` 或 `memory:` 链接。
