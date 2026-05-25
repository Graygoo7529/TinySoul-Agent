# 项目分析

## 总体定位

TinySoul 是一个以 Query Loop 为核心的本地自动化代理框架。它把用户目标拆成多轮模型决策和动作执行，并通过结构化状态持续收敛任务结果。

项目的关键设计不是“让模型直接操作一切”，而是把模型限制在明确边界内：

- 模型选择动作和生成参数。
- Action 执行具体能力。
- Trap 统一处理错误和控制信号。
- Context 暴露压缩后的运行态事实。
- Loop 编排每一轮，并决定继续、挂起、完成或中止。

这种结构让模型可以参与规划和总结，但实际副作用仍落在可注册、可过滤、可观测的动作系统里。

## 主执行链路

一次查询的核心路径是：

1. `QueryLoop` 初始化 registry、state、workspace、context、prompt 和 step tasks。
2. Step1 让模型选择动作。
3. Step2a 并发生成动作参数。
4. Step2b 通过 `ParallelDispatcher` 并发执行动作。
5. 动作结果转成 signal。
6. Trap/InterruptHandler 先把动作事实写入状态。
7. Loop 根据控制信号决定是否进入 Step3。
8. Step3 读取未读 action records，生成状态更新并 ack。
9. Loop 进入下一轮或返回 `LoopOutcome`。

该链路中，状态写入和控制决策是分开的。动作完成不等于状态已经总结；只有 Step3 成功后，本轮读取过的 action records 才会被 ack。

## 模块分工

### Loop

Loop 是编排层，负责轮次、步骤、并发入口、挂起恢复和终态清理。它不实现动作业务，也不直接处理供应商细节。

### Action

Action 是能力层，负责动作注册、依赖过滤、输入校验、运行配置和执行。可用动作由当前环境能力决定，模型只能从注册后的动作空间中选择。

### Context

Context 是运行态视图，组合 QueryState、QueryEvents、Workspace、QueryAction、AIClient、SignalBus 和 ongoing 控制能力。它向 Prompt 和 Action 提供结构化上下文，而不是暴露内部状态列表。

### LLM

LLM 模块封装 provider 配置、模型池、重试、failover、任务运行和 JSON 响应解析。Loop 和 Action 只依赖 `AITask`/`AIClient`，不直接依赖供应商 SDK。

### Prompt

Prompt 模块集中管理 system/guide 资源和组装顺序。Loop-level system 先集中构建，再由 Context 持有；LLM Action 在此基础上叠加动作执行上下文和动作专属 system。

### Trap

Trap 是异常和信号收敛层。它把异常、动作结果、超时、取消、完成、挂起等事件转成 `TrapResult`，并通过 InterruptHandler 写入状态。

### Infra

Infra 提供配置、日志、资源读取、能力探测、进程管理和脚本沙箱。它保持底层能力定位，不反向依赖业务模块。

## 设计优势

### 动作空间可控

动作必须先注册并通过依赖检查，才会出现在模型可选列表中。运行时 allowlist 和动态脚本注册也走同一套 registry 边界。

### 状态更新集中

动作只记录事实，状态总结集中在 Step3。这样可以避免每个动作各自修改 todo、milestone 或错误列表，降低状态不一致风险。

### 错误结构化

异常不会散落在各层临时处理。Dispatcher、Trap 和 InterruptHandler 把失败、超时、取消和控制信号转成统一记录，Loop 再依据 `TrapResult` 决策。

### Prompt 约束可继承

loop-level system 是统一入口。动作级 LLM 调用继承该 system，再叠加动作自己的上下文，避免不同动作形成互相冲突的身份和规则。

### 环境能力可感知

ActionRegistry 会根据可执行文件、Python 包、模型能力等过滤动作。文档、测试和运行时行为都应以“当前环境实际可用能力”为准。

## 当前边界

- Loop 状态是运行态对象，不是持久化会话存储。
- Step2a 参数生成并发上限当前为 3。
- 多动作批次会抑制普通 `LOOP_NEXT_TURN`，完成和挂起控制仍保留。
- 完成或挂起会跳过 Step3，因此终止动作记录不一定立即 ack。
- Action 输入校验只做必要字段检查，不是完整 JSON Schema 校验。
- 脚本沙箱是 best-effort 防护，不是操作系统级强隔离。
- Provider 默认规格不等于实际 adapter 能力；实际能力以注册 adapter 和环境配置为准。
- 真实 API 集成测试默认跳过，需要显式打开环境开关。

## 文档对齐原则

模块文档应描述当前代码事实，而不是未落地的目标形态。后续更新时优先检查：

- 类和函数是否仍在文档所说路径。
- 默认配置值是否改变。
- Signal 聚合和 Loop outcome 是否改变。
- Provider adapter 是否实际注册。
- ActionRegistry 的依赖过滤规则是否改变。
- Sandbox 和 Workspace 的安全边界是否改变。

当实现和设计草案不一致时，`docs/module/*` 应以实现为准；更高层设计讨论保留在私有设计草案中。

## 设计不变式

- Loop 编排流程，Action 执行能力，Trap 收敛异常，Context 暴露事实。
- 模型输出必须先结构化，再进入动作或状态更新。
- 副作用必须通过注册动作或受控执行器发生。
- 状态更新必须有明确输入记录和 ack 边界。
- 文档必须区分“当前实现”“预留能力”和“未来设计”。
