# App 设计

## 定位

App 模块负责 TinySoul 的进程级装配、生命周期和外部输入边界。它把 infra、llm、action、context、runtime 与 loop 组装成可运行的 TinySoulApp，并把终端、API、HTTP、WebSocket 或其他来源的外部输入统一转换为内部输入事件。

App 不定义 Program/Turn/Cycle/Phase 运行语义，不维护 Context 状态，不执行 Action，不适配模型供应商。运行语义仍由 loop 模块负责；app 只负责把真实世界输入和模块装配接到 loop 的明确边界。

## 目录组织

```text
tinysoul/app/
  config.py          # AppSettings 与输入命令配置
  errors.py          # app 契约与不变量错误
  failures.py        # app Runtime bridge 失败枚举
  inputs.py          # InputEvent、InputCommandParser、InputDispatcher
  runtime.py         # TinySoulApp 生命周期入口
  builder.py         # TinySoulAppBuilder 全局装配入口
  native_actions.py  # 当前 app 装配层注册的 native actions
  sources/
    terminal.py      # 终端输入源
```

App 的 Runtime bridge 位于 `tinysoul/runtime/bridge/app.py`，用于将 app 装配或输入边界失败映射为 Runtime 可理解的启动失败或控制流失败。

## 输入模型

外部输入源不直接操作 SignalBus。所有外部输入先转换为 `InputEvent`，再进入 app 的输入解析和分发流程。

输入处理分为两层：

- `InputCommandParser` 是纯解析器，无副作用；它根据当前是否存在活跃 Turn，把 InputEvent 分类为启动 Turn、追加输入、停止 Turn、退出 Program 或忽略。
- `InputDispatcher` 承担副作用；它将 Program 级输入投递到 ProgramRunner 的输入队列，将 Turn 内追加输入转换为 `context.input.append` 信号，将 Turn 内控制请求转换为 `loop.control.request` 信号。

这个拆分保证输入命令策略可以单独测试，也保证终端、API、HTTP、WebSocket 或 IPC 输入源都只依赖同一个 InputEvent 协议。

## Program 输入队列

ProgramRunner 等待的是已分类的 `ProgramInputEvent`，而不是原始字符串。

空闲状态下的普通输入变成 `start_turn` 事件；空闲状态下的退出命令变成 `exit_program` 事件。这样 ProgramRunner 阻塞等待时总能被 Program 级事件唤醒，不依赖 SignalBus 唤醒外部输入。

Turn 活跃期间的普通输入和控制命令不进入 Program 队列，而是由 InputDispatcher 转换为内部信号，由 loop 在 Phase/Cycle 边界消费。

## 输入源

输入源实现 `InputSource` 协议，只负责生产 InputEvent：

- `TerminalInputSource` 从 stdin 读取行输入；
- 测试或嵌入式调用可以直接调用 `TinySoulApp.submit_input()` 或 `InputDispatcher.submit()`；
- 后续 HTTP、WebSocket、IPC 或文件监听输入源应作为 app source adapter 接入。

外部框架只应出现在 source adapter 内部，不应进入 loop、context、action 或 llm 的核心语义。

TinySoulApp 启动输入源后负责在程序退出或启动失败时停止已启动的输入源。停止过程采用 best-effort：一个输入源停止失败不阻止其他已启动输入源停止；当主流程本身没有异常时，停止失败会作为 app 不变量失败向调用方报告。

## 装配入口

TinySoulAppBuilder 负责：

- 加载 ConfigEnvironment；
- 解析 LoopSettings 与 AppSettings；
- 构建 LLMTaskRunner、ContextEngine、ActionEngine、SignalBus 和 RuntimeTrap；
- 注册 app 装配层 native action 与 executor；
- 构建 Phase、CycleRunner、TurnRunner、ProgramRunner；
- 构建 InputCommandParser、InputDispatcher 和输入源；
- 返回 TinySoulApp。

`core.answer` 与 `workspace.scan` 当前仍在 app 装配层注册。`workspace.scan` 是 Workspace 模块接入前的临时能力；完整 Workspace / Agent Home 模块落地后，workspace 扫描、链接解析、资源摘要和 how_action guidance 应迁出 app 装配层，由对应模块提供。

## 与其他模块的关系

- 对 loop：app 创建各级 runner，并向 ProgramRunner 投递 ProgramInputEvent；Turn 活跃期间通过 SignalBus 发出 loop/control 与 context/input 信号。
- 对 runtime：app 注册 Trap handler，并通过 RuntimeAppBridge 映射 app 边界失败。
- 对 action：app 注册 native action 与 executor；具体 action 语义仍由 action 模块执行。
- 对 context：app 当前加载 `AGENT.md` 作为默认背景；Agent Home 接入后应由 Agent Home / Context builder 提供背景条目。
- 对 workspace / Agent Home：当前只有临时注册点；后续应迁移为独立模块门面。
