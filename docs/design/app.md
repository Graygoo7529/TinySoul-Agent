# App 设计

## 定位

App 模块负责 TinySoul 的进程级装配、生命周期、外部输入边界和外部输出边界。它把 infra、llm、action、context、runtime 与 loop 组装成可运行的 TinySoulApp，把终端、API、HTTP、WebSocket 或其他来源的外部输入统一转换为内部输入事件，并把非控制性的运行观察事件路由到终端或嵌入方提供的输出端。

App 不定义 Program/Turn/Cycle/Phase 运行语义，不维护 Context 状态，不执行 Action，不适配模型供应商。运行语义仍由 loop 模块负责；app 只负责把真实世界输入和模块装配接到 loop 的明确边界。

## 目录组织

```text
tinysoul/app/
  config.py          # AppSettings、输入/输出与 scheduler 配置
  errors.py          # app 契约与不变量错误
  failures.py        # app Runtime bridge 失败枚举
  inputs.py          # InputEvent、InputCommandParser、InputDispatcher
  maintenance.py     # 人工 Home review decision broker
  outputs.py         # OutputSink、ObservationRouter 与终端渲染
  cli.py             # console script 入口
  runtime.py         # TinySoulApp 生命周期入口
  builder.py         # TinySoulAppBuilder 全局装配入口
  sources/
    terminal.py      # 终端输入源
    scheduler.py     # typed Program event scheduler
```

App 的 Runtime bridge 位于 `tinysoul/runtime/bridge/app.py`，用于将 app 装配或输入边界失败映射为 Runtime 可理解的启动失败或控制流失败。

## 输入模型

外部输入源不直接操作 SignalBus。所有外部输入先转换为 `InputEvent`，再进入 app 的输入解析和分发流程。

输入处理分为两层：

- `InputCommandParser` 是纯解析器，无副作用；它根据当前是否存在活跃 Turn，把 InputEvent 分类为启动 Turn、追加输入、停止 Turn、Home/Memory Maintenance、拒绝的命令、退出 Program 或忽略。
- `InputDispatcher` 承担副作用；它将 User Turn、Home Maintenance、指定日期 Memory Maintenance 和 Program 退出等 Program 级输入投递到 ProgramRunner 队列，将 Turn 内追加输入转换为 `context.input.append` 信号，将 Turn 内控制请求转换为 `loop.control.request` 信号。

这个拆分保证输入命令策略可以单独测试，也保证终端、API、HTTP、WebSocket 或 IPC 输入源都只依赖同一个 InputEvent 协议。

## Program 输入队列

ProgramRunner 等待的是已分类的 `ProgramInputEvent`，而不是原始字符串。

空闲状态下的普通输入变成 `start_turn` 事件；维护指令变成 Home 或 Memory Maintenance event；退出命令变成 `exit_program` 事件。这样 ProgramRunner 阻塞等待时总能被 Program 级事件唤醒，不依赖 SignalBus 唤醒外部输入。

Turn 活跃期间的普通输入和 Turn 控制命令不进入 Program 队列，而是由 InputDispatcher 转换为内部信号，由 loop 在 Phase/Cycle 边界消费。Maintenance 是 Program work，即使在 Turn 活跃时也始终排入 Program 队列，不形成 `context.input.append`；它会在当前 Turn 收束后执行。

## 输入源

终端等外部输入源实现 `InputSource` 协议，只负责生产 InputEvent；时间触发源实现独立的 `ProgramEventSource`，只负责生产已经分类的 Program event：

- `TerminalInputSource` 从 stdin 读取行输入；stdin 到 EOF 时，它提交配置中的首个 Program 退出命令，使阻塞中的 ProgramRunner 通过正常输入/Trap 流程结束；
- 内置 `MaintenanceScheduler` 是时间驱动的 `ProgramEventSource`，只向 Program 投递 daily rollover/Home Maintenance/Memory Maintenance event，不在 scheduler 线程直接调用业务模块；
- 测试或嵌入式调用可以直接调用 `TinySoulApp.submit_input()` 或 `InputDispatcher.submit()`；
- 后续 HTTP、WebSocket、IPC 或文件监听输入源应作为 app source adapter 接入。

外部框架只应出现在 source adapter 内部，不应进入 loop、context、action 或 llm 的核心语义。

`TinySoulApp.run()` 先启动 Program event source，再启动外部 input source，并在程序退出或启动失败时停止全部已启动 source。`run_once()` 不启动任何 source，因此不会创建 scheduler 线程，但 ProgramRunner 仍执行 Daily preflight。停止过程采用 best-effort：一个 source 停止失败不阻止其他已启动 source 停止；当主流程本身没有异常时，停止失败会作为 app 不变量失败向调用方报告。

## 输出与观察事件

`ObservationEvent` 是 Runtime 定义的 provider-neutral、JSON 安全旁路事件，携带稳定名称、详细度、来源、运行位置、消息和结构化 payload。它不进入 SignalBus，不由业务消费者提交状态，也不能触发 Trap 或改变运行转移。业务运行器只发布事件；App 的 `ObservationRouter` 根据配置过滤并扇出到 `OutputSink`。

输出详细度是包含关系：

- `normal` 输出已完成并通过 Turn completion pipeline 提交的最终回答、可行动的 Maintenance 提示、Program work 结果，以及 failed/exhausted/stopped 等需要用户感知的边界；
- `verbose` 在 normal 之上增加 Program、Turn、Phase、模型尝试、Action batch 和 Runtime trap 等边界事件；
- `model` 在 verbose 之上增加 provider-neutral 的模型请求与归一化响应。

MODEL 事件可能包含完整文本 prompt 和模型回答，只应在明确需要诊断时开启。图片字节只记录长度、MIME 与 digest，远程图片 URL 去掉 query/fragment，data URL 被替换为 redacted 标记；推理只保留 summary 和 encrypted item digest，不输出 reasoning content、加密项原文或 provider 原始 payload。Console 渲染再按 `app.output.model_max_chars` 限制单条诊断文本。

`OutputSink.write` 属于外部 I/O 边界。单个 sink 失败后由 router 禁用并记录，不能反向打断 Turn、修改 Session/Workspace 提交或伪装成 Runtime 控制异常；`TinySoulApp.run()` / `run_once()` 在业务边界结束后把累计失败报告为 `AppOutputError`。`ConsoleOutputSink` 只把已完成 completion 提交的最终回答写到 stdout；failed/exhausted/stopped 和 verbose/model 诊断写到 stderr，便于脚本分别消费结果和诊断。

在包含 `tinysoul.toml`、`configs`、Home 与 Action Catalog 的 TinySoul 项目根中，`tinysoul` console script 是当前正式交互入口。默认从当前目录加载配置并启动终端输入源和已启用 scheduler；`--root` 选择项目根，`--mode normal|verbose|model` 覆盖输出详细度，`--once TEXT` 关闭交互输入、不开启 scheduler 并只执行一个 User Turn。`--once` 只有 `TurnOutcomeStatus.ANSWERED` 返回 0，exhausted/stopped/failed 均返回 1；启动/配置失败也返回 1，键盘中断返回 130。CLI 使用同一 AppBuilder/Console sink，不建立第二套流程。当前仓库尚未提供独立安装后的默认资产打包或项目初始化流程。

## 装配入口

TinySoulAppBuilder 负责：

- 加载 ConfigEnvironment；
- 从统一 ConfigEnvironment 读取各模块 section tree，由 app/action/context/home/loop/session/workspace/llm 各自解析所属 settings；
- 构建 LLMTaskRunner、ContextEngine、SessionEngine、WorkspaceEngine、ActionEngine、SignalBus 和 RuntimeTrap；
- 调用各模块 registrar 装配模块 executor；
- 构建 Phase、CycleRunner、TurnRunner、ProgramRunner，并注入 IANA business clock 与 DailyLifecycleCoordinator；
- preparation 顺序固定为 Context 动态 Home 默认项、Session、Workspace；把幂等 Session completion 放在外部 `with_turn_completion_handler` 注册项前；
- 构建 InputCommandParser、InputDispatcher、终端输入源和内置 scheduler；
- 构建 ObservationRouter，把同一 emitter 注入 LLM、Action、Runtime 和各级 Loop runner；
- 返回 TinySoulApp。

AppBuilder 是跨模块配置装配边界，但配置错误归属仍属于对应模块。项目配置由 `tinysoul.toml` 显式 include `configs/*.toml` 和模型文件；Infra 只加载与合并，Action、Context、LLM、Loop、App、Session、Workspace、Agent Home 在各自 parser 中解释 section tree。AppBuilder 在对应 bridge 映射 ConfigError，不把所有装配期配置错误统一归为 app 或 infra 失败。

`core.answer` 由 Action builtins core actions 提供，不属于 app 装配层 native action。Workspace、Agent Home 和内置 core action 的具体语义由对应模块提供 registrar、executor 或 provider，AppBuilder 只完成跨模块注册，不直接实现 workspace 扫描、链接解析、资源摘要、Agent Home 背景加载或 how_domain/how_action HOW。Workspace 的 prompt reference resolver 与 Agent Home 的 action HOW provider 也在装配期注入到 action 层共享 LLM action backend 服务，让 `core.reason`、`core.answer` 等通用动作可以使用 `reference_links`，让带内部 LLM task 的 action 自动获得 domain/action HOW；Home-owned `LLMHomeSearchReranker` 同样由 AppBuilder 注入 search executor，但候选构造、校验和 fallback 仍归 Home。ActionEngine 构建后，AppBuilder 读取其只读 domain/action identities 并调用 Home mount reconciliation；App 不解析 catalog 文件，也不决定 mount 路径或删除语义。

AppBuilder 把同一个 `DailyLifecycleCoordinator` 注入 ProgramRunner 和 `ProgramMaintenanceRunner`。长运行 Program 启动先恢复并补做 Session/Workspace/Trash 日切，保留 `runtime/home`；随后检查 active Home 的真实修改/`SKILL_MEMORY.md`，并检查“昨日 Session archive 存在、Session Memory facts projection 非空且昨日 MEMORY 不存在”，以 `program.maintenance.available` 给出非阻塞提示。Home 提示可跳过，overlay 继续保留；Memory 不保存 skipped 状态，只在目标日期仍是昨日时自动提示。

人工命令为 `/maintenance home` 与 `/maintenance memory [YYYY-MM-DD]`，Memory 未指定日期时默认昨日。`TerminalHomeDecisionBroker` 为 Home Maintenance 在终端逐项确认，只在存在 pending change 时消费精确 `apply/discard/stop`；其它输入继续走正常解析并在 Program queue 等待。EOF 或 Program 退出先停止 pending review，避免 Program 阻塞。scheduler 触发 Home 时使用 Home-owned LLM reviewer；scheduler 触发 Memory 时若昨日 MEMORY 已存在则 skipped，人工指令仍可基于旧 MEMORY 和 Session 重写。

`app.scheduler.enabled` 默认开启，`home_maintenance_time` 默认 `00:05`，`memory_maintenance_time` 默认 `00:15`，均按 `loop.daily.timezone` 的本地墙钟解释，且 Home 必须早于 Memory。进程启动晚于当日时刻时不补跑停机期间的 Maintenance；daily rollover 由 Program 启动/每项 work preflight 补做，Home overlay 保留到下一次 Maintenance，Memory 自动提醒只检查昨日。scheduler 内存游标按 `daily -> Home -> Memory` 顺序投递当日事件，不保存调度状态。

这些入口由 App 负责外部触发与装配，但 Home diff、review/apply、Session archive 读取和 MEMORY 重写语义归 Agent Home，work 调度与 outcome 归 Loop maintenance runner；CLI、terminal source 和 scheduler 不能直接 diff 或修改 Home。App 不建立 settlement root，也不持久化 review/apply 状态。Stage 6 的最小 normal 输出只固定 `program.maintenance.available`、`program.work.completed` 与 `program.work.failed`；模块级细粒度 Maintenance Observation 留待后续确认。

## 与其他模块的关系

- 对 loop：app 创建各级 runner，注入 daily settings/coordinator、Maintenance runner 与 scheduler，并向 ProgramRunner 投递 typed ProgramInputEvent；Turn 活跃期间通过 SignalBus 发出 loop/control 与 context/input 信号。
- 对 runtime：app 注册 Trap handler，并通过 RuntimeAppBridge 映射 app 边界失败。
- 对 action：app 调用模块 registrar 注册 action executor；具体 action 语义仍由 action 模块调度，由对应业务模块执行。
- 对 context：app 注入 `HomeBackgroundEntryProvider`，不物化 core、不读取 Agent Home 文件。它同时装配共享 ContextSignalConsumer 和 TurnCompletionPipeline 接入点。
- 对 session：app 只构建门面、注册 history actions 和安装 Turn preparation/completion adapters，不读取 Session 持久文件。
- 对 workspace / Agent Home：app 只装配模块门面和 executor，不解释 `workspace:` 或 `home:` 链接。
