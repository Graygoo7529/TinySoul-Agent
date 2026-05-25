# Action 模块

## 定位

Action 模块负责把模型选择出的“下一步动作”落到可执行代码上。它不保存长期状态，也不直接决定 Loop 是否结束；它只完成动作注册、参数校验、运行配置解析、动作执行和结果封装，后续状态写入由 Trap/InterruptHandler 统一处理。

核心路径：

1. `QueryLoop` 通过 `QueryAction` 查询可用动作并执行动作。
2. `ActionRegistry` 维护动作名到 Handler 的映射。
3. `ActionBase` 是所有 Handler 的运行边界。
4. Handler 返回 `ActionResult`，再由 Dispatcher 转成 `Signal`。
5. Trap/InterruptHandler 把信号写入 `QueryState`、`QueryEvents` 或 ongoing 注册表。

## 目录边界

- `tinysoul/action/framework/`：动作基类、注册表、管理器、运行配置和输入校验。
- `tinysoul/action/handlers/`：内置动作实现。
- `tinysoul/action/executors/`：LLM、脚本、子进程等可复用执行器。
- `tinysoul/action/metadata.py`：动作元数据、集群、依赖和风险描述。

Action 模块只定义“能做什么”和“如何执行”。“什么时候做”“做完如何推进”属于 Loop 与 Trap。

## 核心对象

### `ActionBase`

所有动作的统一基类，职责是：

- 暴露 `name`、`metadata`、`input_schema`、`llm_task`、`runtime_config`。
- 在 `execute()` 中解析有效 `RunConfig`。
- 调用 `_execute()` 完成动作业务逻辑。
- 将未知异常包装成 `ActionExecutionError`，并透传已有的 `TinysoulError`。

Handler 内部可以使用 `ContextProvider` 读取上下文、访问工作区、发出信号或控制 ongoing 动作，但应避免直接修改 QueryState 的内部结构。

### `ActionRegistry`

注册表是实例级对象，不是全局单例。`bootstrap()` 会扫描 `tinysoul.action.handlers` 下带 `register_to(registry)` 的模块，并把通过依赖检查的动作注册进去。

`with_allowlist()` 返回一个受限视图，共享底层 registry 和 handler 缓存；运行时新增动作会自动加入该 allowlist，便于动态脚本动作在当前会话中立即可见。

注册有两种模式：

- `strict=True`：依赖、元数据或实例化失败直接抛出异常。
- `strict=False`：失败动作写入 skipped 列表，主流程继续。

### `QueryAction`

`QueryAction` 是 Loop 面向动作层的门面：

- 提供动作列表给模型选择。
- 按动作名解析 Handler。
- 执行最小输入校验。
- 合并默认设置、动作元数据和本次执行配置。
- 返回 `ActionResult`。

输入校验当前只检查 payload 必须是对象，以及必填字段是否存在；不会完整执行 JSON Schema 的类型、枚举或范围校验。

### `RunConfig`

`RunConfig` 是单次执行的控制对象，包含：

- `execution_id`
- timeout/deadline
- cancellation/termination reason
- cancellation event

Dispatcher 会为每个动作创建或补齐 `execution_id`，并把 `RunConfig` 传入 Handler。Handler 和执行器应通过它判断是否超时、取消或需要停止。

## 执行流程

单个动作的主路径是：

1. Loop 从 Step1 得到动作选择。
2. Step2a 使用 LLM 为每个动作生成参数。
3. Step2b 交给 `ParallelDispatcher` 并发执行。
4. Dispatcher 为动作绑定 `RunConfig`。
5. `QueryAction.execute()` 校验动作名和输入。
6. Handler 执行业务逻辑并返回 `ActionResult`。
7. Dispatcher 将结果发成 signal。
8. Trap/InterruptHandler 写入状态或聚合控制信号。

Action 不负责 ack action record。当前 ack 发生在 Loop Step3：状态更新成功后，Loop 才把本轮读取过的 action records 标记为已读。

## 动作类型

### 基础动作

- `answer`：生成最终回答，通常发出 `COMPLETE_LOOP`。
- `ask_user`：向用户提问，写入 inquiry，并发出 `SUSPEND_LOOP`。
- `reasoning`：生成内部推理或阶段性分析，供后续状态更新使用。

### 知识和计算动作

- `calculate`：执行受限数学表达式。
- `average_dog_weight`：示例知识动作，用于测试和演示查询型动作。

### 工作区动作

工作区动作通过 `Workspace` 解析路径，禁止绝对路径和逃逸到工作区外的相对路径。读文件动作只支持文本内容；PDF/DOCX 等二进制文档当前不会在该动作中解析。

### 脚本动作

脚本动作分两类：

- 临时脚本执行器：执行已注册的 workspace-relative Python 脚本。
- 动态脚本管理动作：创建、编辑并注册新的临时脚本动作。

动态脚本注册会先做 AST 安全校验，再让 LLM 生成动作元数据。注册阶段只把脚本变成可选动作，不会立即执行脚本。若编辑已有脚本且动作名可用，系统会重新注册同名临时动作。

### Git 和子进程

Git 动作依赖本机可执行文件能力检查。若当前环境找不到 `git`，注册表会在非 strict 模式下跳过它。

代码中保留了 Bash 子进程执行器，但当前默认动作集中没有注册通用 `bash` 动作。

### Ongoing 动作

Ongoing 动作启动后会返回 `ONGOING_STARTED`，后台任务可继续发出 `ONGOING_TICK` 或 `ONGOING_COMPLETED`。Loop 在正常终止或异常终止时会请求关闭 ongoing 动作；挂起状态不会主动关闭。

## 运行配置

动作运行配置由三层合并：

1. 全局 `settings`
2. 动作元数据/运行时配置
3. 单次执行传入的 overrides

当前默认超时按动作集群选择：

- Native 动作使用 `settings.action_timeout`
- CLI 动作使用 `settings.cli_timeout`
- Script 动作使用 `settings.script_timeout`

如果动作依赖 LLM，默认超时会扩展为 `llm_timeout + action_llm_overhead`。API 依赖也支持在 `ActionRuntimeConfig` 中声明，但全局设置当前没有固定 `api_timeout` 字段。

## 依赖与能力

动作依赖通过 metadata 描述，并在注册时检查：

- Python 包依赖
- 可执行文件依赖
- 运行时能力依赖
- LLM/API 依赖声明

依赖失败的动作不会进入可选动作列表。这样 Loop 给模型的动作空间始终反映当前环境的真实可执行能力。

## 当前边界

- 输入校验是轻量级的，不是完整 JSON Schema 引擎。
- 注册表只管理动作可见性，不管理权限确认。
- `delete_file` 等破坏性动作本身不会弹出确认；是否允许使用由动作 allowlist 和上层策略控制。
- 动态脚本的安全边界依赖 AST 校验、sandbox 和工作区路径解析，适合受控自动化，不应被视为强隔离沙箱。
- 动作执行失败会进入 Trap 体系，而不是在 Handler 层直接恢复 Loop。

## 设计不变式

- 动作名是动作选择、注册和执行的唯一入口。
- Handler 应返回结构化 `ActionResult`，不要把控制流隐藏在字符串结果里。
- 动作只做本动作的事情；状态推进交给 Loop 和 Trap。
- 可执行动作列表必须经过当前环境能力过滤。
- 动态新增动作必须复用同一套 metadata、依赖和运行配置边界。
