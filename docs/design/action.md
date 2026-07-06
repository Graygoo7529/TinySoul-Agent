# Action 设计

## 定位

Action 模块负责 TinySoul 的行动语义、模型侧工具暴露、行动参数生成、行动执行和结果回放。

Action 不负责构造基础语境，不负责模型供应商适配，不负责运行时陷入控制。它依赖 `llm` 提供消息栈、工具消息和任务调用抽象，依赖 `runtime` 提供运行位置、信号和异常转移协议。

Action 的核心职责是把“可选择的域”和“可执行的动作”组织成稳定的 catalog，并把 Phase1 / Phase2 / Phase3 的行为切成清晰的边界。

## 设计目标

1. Phase1 只选择域，不暴露全部 action 细节。
2. Phase2 只在已选域内选择动作并生成参数。
3. Phase3 统一执行一批动作，支持并发、超时、hook 校验和结构化结果。
4. 所有 LLM 调用都基于语境模块构造的 `MessageStack`，Action 只追加临时任务提示。
5. Action 定义使用 TOML 存放，入口动态校验后尽早转换为内部类型。
6. 去掉旧设计中的冗余字段，保持模型侧可见描述和框架内运行配置分离。

## 分层模型

### Phase1: 域选择

Phase1 面向模型暴露的是域，而不是 action 列表。

域的作用只有两个：

1. 让模型先判断当前任务应进入哪个工具选择方向。
2. 为 Phase2 限定可见 action 集合。

Phase1 暴露的工具是少量内部控制工具，例如：

- 选择一个或多个 action domain
- 请求加载某些顶层上下文
- 记录当前轮次的方向意图

Phase1 不输出二级 action 描述，也不直接提供 action 参数 schema。

### Phase2: 动作选择与参数生成

Phase2 只接收 Phase1 选中的 domain，并在这些 domain 内暴露具体 action。

Phase2 的输出不叫 draft。它就是一个规范化的 action call，已经足够进入执行阶段。

Phase2 面向模型暴露的 action 信息只保留两类内容：

1. 工具调用直接需要的结构：`name`、`description`、`schema`
2. 补充语义：`use_when`、`avoid_when`、`effects`、`examples`

`edge_cases` 不再由 action definition 承担，交给 hook 和执行结果表达。

### Phase3: 批次执行

Phase3 将 Phase2 产出的多个 action call 统一装配成一个执行批次。

Phase3 负责：

- 将框架内信息和业务参数拆开
- 对每个 action 执行输入 hook
- 按 batch 维度处理并发和超时
- 将每个 action 的执行结果结构化
- 等待全部 action 收敛并整理 `ActionResult` 序列

Phase3 不保留长期运行或 ongoing action。所有动作都只属于一个批次的成功、失败或超时。

`native` 后端运行在宿主 Python 线程中，只能提供协作式停止。runner 到达 deadline 后会先向该 action 的 `ActionExecutionControl` 发出取消请求并等待短暂 grace；如果 native action 通过 `context.control.check_cancelled()` 等方式协作退出，结果收敛为 timeout 且后续执行组可以继续。如果 native action 超时后执行体仍在运行，runner 必须阻断后续执行组并在结果中标记泄漏风险。需要硬停止语义的动作应使用 `subprocess` 或 `script` 后端，由后端负责终止执行体；runner 会为这类后端提供更长的进程回收 grace。

## 定义结构

域定义保持很薄，只服务于 Phase1 的方向选择。域默认运行配置不进入模型可见语义，只作为具体 action 的运行配置合并来源。

具体 action 定义分为四个语义层次：

1. 模型侧工具协议，用于构造 Phase2 可见工具。
2. 模型侧补充语义，用于帮助模型判断何时使用或避免某个 action。
3. 框架内运行配置，用于控制超时、并发和 hook。
4. 后端执行配置，用于描述真实执行落点。

模型侧补充语义不参与执行控制。环境影响语义只描述只读、新增或修改。

后端只负责执行实现，不负责模型侧解释。`llm_step` 只表示动作内部还需要一次受控 LLM 调用，不意味着 action 退化成 prompt 拼接逻辑。

## 执行语义

### 输入

一次 action 执行输入分两层：

1. 框架内信息
2. 模型生成参数

框架内信息描述调用关联、批次关联、运行位置、超时边界和所属域。模型生成参数只保留 action schema 对应的业务参数。

`ActionExecution` 是 Phase3 的自包含执行输入：它同时携带已解析的 `ActionSpec`、规范化后的 `ActionCall` 和 `ActionFramework`。runner、hook 和 backend executor 不再在执行时重新查询 catalog；catalog 一致性在 builder/engine 准备阶段完成。

行动调用使用 TinySoul 归一化后的模型侧 tool call id 作为后续工具结果回放的相关性字段；执行期另有框架内部观测标识，用于 trace 和调度。

### Hook

每个 action 可以复用通用 hook，也可以定义专用 hook。hook 按 action 生命周期分为 normalize hook 和 execution hook。

normalize hook 发生在 Phase2，用于检查模型侧 action tool call 是否能成为 ActionCall。schema 参数检查属于内置 normalize hook，默认对所有 action 启用；action 也可以追加自己的 normalize hook，用于检查参数组合、链接格式或领域约束。

execution hook 发生在 Phase3，用于检查 ActionExecution 是否可以真实执行，例如工作区状态、资源存在性或运行上下文限制。

每个阶段内 hook 顺序为：

1. 全局 hook
2. domain hook
3. action hook

hook 只做输入检查、上下文约束和可执行性裁剪，不执行真实动作。

hook 失败应转为结构化 action result，而不是直接升级成 Runtime 陷入。

normalize hook 的未知 hook、hook 自身异常和 hook 拒绝都收敛为 normalize 阶段的 ActionResult。execution hook 的未知 hook、hook 自身异常和 hook 拒绝都收敛为 hook 阶段的 ActionResult。

### 批次执行

Phase3 使用 map-reduce 风格执行：

- map：每个 invoke 独立执行
- reduce：只负责等待收敛并整理 `ActionResult` 序列

Batch 只是执行编排容器，runner 的核心输出是 `ActionResult` 序列。

单个 action result 只收敛为三类：

- `success`
- `failed`
- `timeout`

批次内允许部分成功，但不需要额外定义 batch result。

Phase2 的模型侧 action tool call 即使无法归一化，也必须产出局部 ActionResult。因此一个 action tool call 在 Action 模块内总是对应一个局部结果：normalize failed、prepare failed、hook failed、schedule failed、execute failed、timeout 或 success。

超时结果有两类来源：runner 发现 deadline 已过并给出 timeout；后端执行器在自身边界内发现 timeout 并给出 timeout。超时后的成功结果必须改判为 timeout，避免越过 deadline 的副作用被当作正常完成；超时后的失败结果可以保留 failed，因为失败信息通常比 timeout 标签更有利于下一 cycle 修正。

无法绑定到具体 action tool call 的阶段性框架问题不伪造成 ActionResult，而是产出 phase-level result，供 Context 记录为 cycle phase 执行反馈。

### 输出

Action result 需要同时表达三类信息：

1. 给模型看的反馈
2. 框架内状态
3. 执行可观测数据

结果中应保留：

- `result_id`
- `call_id`
- 成功/失败/超时
- 所处阶段
- 原始 call 顺序 `sequence`
- 可选的 `invoke_id` / `batch_id` / `domain`
- 结构化 payload
- model feedback
- frame data

大块文件内容、长文本和非结构化资源不直接塞回结果，改用资源句柄或摘要。

`ActionResult` 是具体 action call 的局部事实记录，不等同于 LLM message。Action phase result 是 action 模块某个 phase 的局部执行记录，用于表达无法绑定到具体 action call 的框架性问题。

`ActionFeedbackRenderer` 负责把 action result 渲染为：

1. 给模型看的 compact JSON payload。
2. 给 trace/log 使用的完整 JSON payload。
3. 可由 context 模块加入下一 cycle MessageStack 的 `ToolResultMessage`。

Context 模块决定这些渲染结果如何进入 TurnTraceContext 或 Interaction Context；Action 模块不直接维护 MessageStack。

Phase-level result 没有模型侧 tool call id，因此不渲染为 ToolResultMessage，只渲染为普通模型反馈 payload 或 trace payload，由 Context 写入对应 phase 的执行记录。

### 失败与异常边界

Action 模块的正常执行流不应把可反馈失败暴露为普通异常。能够绑定到具体 action tool call 的问题应收敛为 action result，例如参数无法归一化、normalize hook 拒绝、batch prepare 阶段某个 call 无法装配、execution hook 拒绝、executor 失败、executor 返回错配结果和超时。

无法绑定到具体 action tool call、但仍属于当前 Action phase 局部流程的问题，应收敛为 phase-level result，例如 Phase2 无法准备可用 action scope，或 Phase3 的批次准备出现无法归因到单个 call 的问题。Context 模块可以把这类结果记录为当前 cycle phase 的执行反馈，并在后续 message stack 中按需呈现给模型。

防御性不变量异常和模块调用契约错误不属于可继续的 action flow。它们表示 Action 模块内部对象关系、catalog、执行输入或公共边界被破坏，应在模块公共边界通过 Runtime bridge 映射为 Runtime 语义异常，由 Trap 决定结束当前 Turn 或采取其他运行转移。Runtime payload 只携带模块名、稳定失败类型和必要摘要，不携带原始异常对象、大块上下文或完整消息栈。

因此 Action 失败处理分为三层：action call 级局部结果、phase 级局部结果、Runtime 语义异常。前两者服务于 Context 记录和模型反馈，后者服务于运行控制流。

## 后端执行

### native

`native` 后端通过 `NativeFunctionExecutor` 包装宿主 Python 函数。native 函数返回 JSON object payload；执行器负责包装为 success result。native 函数应在长循环、阻塞前后或分块处理边界调用 `context.control.check_cancelled()`，从而响应 runner 的超时取消请求。未协作退出的 native action 会被标记为泄漏风险，后续执行组会被 schedule failed 结果阻断。

### subprocess

`subprocess` 后端以显式 `argv` 启动进程，禁止 `shell=True`。默认把 action params 以 JSON 写入 stdin；stdout/stderr 会按配置截断后进入 payload。进程 exit code 为 0 时返回 success，非 0 返回 failed，deadline 超时时终止进程树并返回 timeout。Windows 使用 `taskkill /T /F`，POSIX 使用新 session/process group。

### script

`script` 后端用于临时 Python 脚本动作。它从 action params 中读取脚本内容，写入临时目录，然后复用 subprocess 运行语义。script 后端只提供执行机制；是否向模型暴露脚本编写动作由具体 action TOML 决定。

### llm_step

`llm_step` 表示 action 内部还需要一次受控 LLM task。它必须继续遵守“所有 LLM 调用基于 Context 构造的 MessageStack”的原则；具体实现等待 Context/Loop 模块落地后再接入。

## 组装入口

`ActionEngine` 是 action 模块面向 Loop/Context 的装配门面，负责持有 catalog、scope builder、normalizer、execution builder、runner 和 feedback renderer。它不改变结果模型，不引入 batch result。

`ActionEngineBuilder` 负责加载 TOML catalog、注册 executor、注册 normalize/execution hook，并在 build 阶段校验 catalog 中所有 backend handler 都有 executor。通用 `subprocess.default` 和 `script.temporary` 后端可以由 builder 默认注册；native handler 需要调用方显式注册具体函数。

## Action Schema

Action tool schema 使用 TinySoul 支持的 JSON Schema 子集。加载 TOML 时必须检查 schema 自身，运行时再校验模型生成参数。

当前支持的 keyword：

- `type`
- `description`
- `properties`
- `required`
- `additionalProperties`
- `items`
- `enum`

当前支持的 type：

- `object`
- `array`
- `string`
- `number`
- `integer`
- `boolean`
- `null`

不支持的 keyword 必须在加载期抛出配置错误，避免 action TOML 写了 schema 但运行时静默忽略。

## LLM 调用原则

所有 LLM 调用都从语境模块已经构造好的 `MessageStack` 出发。

Action 只负责追加临时 task prompt overlay，不重新发明消息栈。

因此一个 action 相关的 LLM task 由两部分组成：

1. 上层语境提供的 base message stack
2. Action 追加的 phase-specific task prompt

Phase1 和 Phase2 只是在这个基础上选择不同的工具作用域和不同的 prompt overlay。

## TOML 组织

建议目录：

```text
tinysoul/action/
  core/
  backends/
  builtin/
    core/
    workspace/
    script/
    shell/
```

### `builtin/core`

放 action 顶层框架性内容，主要是 Phase1 可见的控制工具和共享行为说明。

### `builtin/<domain>`

每个 domain 一个目录，目录下放：

- `domain.toml`
- `actions/*.toml`

`domain.toml` 放域描述和域级默认运行配置。

`actions/*.toml` 放具体 action 定义。

### 继承规则

加载器按以下顺序合并：

1. 内置默认值
2. domain 默认值
3. action 定义
4. 运行时覆盖

动态边界必须在加载阶段完成校验，不把宽泛映射留到执行中。

运行配置中的 hook 使用阶段化配置，分别声明 normalize 阶段和 execution 阶段的 hook 名称。domain 默认 hook 与 action 自身 hook 按阶段合并。

## 设计边界总结

1. Phase1 只选 domain。
2. Phase2 只在 domain 内选 action。
3. Phase3 统一执行批次。
4. Action 定义保持模型侧语义、框架运行配置和后端执行配置分离。
5. 所有 action tool call 都收敛为局部 action result。
6. 无法绑定到具体 action call 的 action phase 问题收敛为 phase-level result。
7. 防御性不变量异常通过 Runtime bridge 映射为运行时语义异常。
8. 所有 LLM 调用都基于上下文模块构造的 base `MessageStack`，Action 只追加临时 prompt。
