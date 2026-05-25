# TinySoul

TinySoul 是一个轻量级 LLM Agent 框架原型。当前阶段的目标很明确：围绕**单个 query**，验证一个 Agent 如何在多轮次、多步骤中稳定地选择动作、执行动作、更新状态，并最终给出答案。

它不是一个完整的多用户 Agent 平台，也不是工作流编排器。TinySoul 更像一个可读、可调试、可扩展的 Agent 内核实验：把一次用户请求拆成固定的 Query Loop，让 LLM 在清晰协议里工作，而不是把所有推理、工具调用和状态维护都塞进一段自由文本对话。

---

## 当前定位

TinySoul 关注的是这个问题：

> 对一个用户 query，Agent 如何在有限轮次内，持续观察状态、选择动作、执行动作、记录结果，并根据结果推进任务？

因此项目刻意把范围收窄：

- **单 query 为核心**：一次 `QueryLoop` 对应一个任务目标。
- **多轮次**：每轮 turn 都重新观察上下文和历史结果。
- **多步骤**：每轮固定为选择动作、生成参数并执行、更新状态。
- **结构化协议**：LLM 的关键输出都是 JSON，由框架解析和校验。
- **可插拔动作**：Action 通过元数据自描述，执行逻辑与选择逻辑分离。
- **可观测状态**：todo、milestone、action record、loop error 都是显式状态。

这使 TinySoul 更适合作为 Agent 架构原型、教学项目、个人研究框架，而不是直接作为生产级自动化系统。

“单 query 为核心”不是把问题做小，而是把 Agent 的最小闭环先做清楚。当前它用于验证澄清、行动、反馈、恢复这些基础流程；放到专用领域智能体里，它可以成为流程调试和能力优化的基本单元；放到通用智能体方向上，它指向一个更长期的目标：不要把整个会话历史无差别塞进上下文，而是围绕当前 query 主动收集必要语义、工作区资源、长期记忆、依赖工具和技能，再在一次 query 内规划和利用它们。

---

## 核心思想

### 1. 用 Query Loop 约束 Agent 行为

TinySoul 的核心是一个固定三步骤循环：

| 步骤 | 目标 | LLM 看到什么 | LLM 输出什么 |
|---|---|---|---|
| Step 1: Choose Action | 选择下一步要做什么 | query 事件、当前状态、workspace、Action meta | `{"action_name": "...", "selection_reason": "..."}` |
| Step 2: Take Action | 为动作生成参数并执行 | 选中 Action 的 detail、状态、workspace | 符合 `parameter_schema` 的 JSON 参数 |
| Step 3: Update State | 消化执行结果 | 新 action records、state schema、当前状态 | todo / milestone 更新指令 |

这套结构的价值是把 Agent 的不确定性限制在清晰边界内：LLM 负责判断和生成结构化数据，框架负责执行、记录、路由和恢复。

### 2. Action Meta / Detail 分离

Action 不是一段随意的工具说明，而是一个自描述对象：

- **Meta**：名称、描述、分类、行为画像、适用条件。Step 1 用它做选择。
- **Detail**：参数 schema、示例、边界处理。Step 2 用它生成参数。

Step 1 不需要读完整参数细节，Step 2 也不需要重新理解所有 Action。这能降低 prompt 噪声，也让 Action 目录更容易扩展。

### 3. State 与 Workspace 分离

TinySoul 区分两类上下文：

| 类型 | 作用 | 生命周期 |
|---|---|---|
| `QueryState` | todo、milestone、action record、loop error | 随一次 QueryLoop 创建和结束 |
| `Workspace` | 文件资源、资源描述、变更日志 | 可跨 loop 复用 |

State 是 Agent 的运行时记忆，Workspace 是外部文件世界的索引。二者分离后，Step 3 只负责语义状态更新，文件读写则由具体 Action 执行。

### 4. Signal / Trap 统一控制流

Action 执行现场不直接改状态，而是发出 `Signal`：

- `ACTION_COMPLETED`
- `ACTION_FAILED`
- `ACTION_TIMEOUT`
- `ONGOING_STARTED`
- `LOOP_COMPLETE`
- `LOOP_SUSPEND`
- `LOOP_NEXT_TURN`

这些信号进入 `SignalBus`，再由 `ErrorTrap` 和 `InterruptHandler` 统一处理。异常也是同一套思路：`_run_step()` 捕获异常，`ErrorTrap` 决定是 abort、interrupt，还是反馈给下一步。

这个设计让串行、并行、后台动作和失败恢复走同一个状态写入路径。

### 5. Peek / Ack 消费语义

Action 执行结果先写入 `action_record_list`，Step 3 通过 `peek_new_action_records()` 读取未处理记录。只有 Step 3 成功完成状态更新后，框架才调用 `ack_action_records()` 标记已读。

如果 Step 3 失败，记录保持 unread，下一轮继续处理。这避免了“结果已经读走，但状态没更新”的数据丢失问题。

---

## 架构总览

```
tinysoul/
├── loop/                 # QueryLoop 调度器、三步任务、并行 dispatcher
├── action/               # Action 框架、内置 handlers、执行器
├── context/              # QueryState、Workspace、ContextProvider 协议
├── llm/                  # AITask、PromptBuilder、Provider adapters
├── prompt/               # loop/action system prompt 资源与 markdown guides
├── trap/                 # ErrorTrap、SignalBus、InterruptHandler、异常层级
└── infra/                # 配置、日志、进程控制、脚本沙箱、资源加载
```

运行时主链路：

```
User Query
    ↓
QueryLoop
    ↓
Step 1: ChooseActionTask → AITask → JSON action selection
    ↓
Step 2a: TakeActionTask  → AITask → JSON action parameters
    ↓
Step 2b: ParallelDispatcher → QueryAction → ActionHandler / Executor
    ↓
SignalBus → ErrorTrap → InterruptHandler
    ↓
Step 3: UpdateStateTask → AITask → apply_state_updates()
    ↓
Next turn / answer / suspend / exhausted / aborted
```

---

## 关键模块

### Loop

`tinysoul/loop/` 是核心调度层。`QueryLoop` 是外边界，`query_loop()` 和 `resume()` 都返回 `LoopOutcome`，不会把业务异常直接抛给调用者。

主要能力：

- 固定三步骤 turn。
- `answer` action 通过 `LOOP_COMPLETE` 结束任务。
- `ask_user` action 通过 `LOOP_SUSPEND` 挂起，并可 `resume(user_response)`。
- `ParallelDispatcher` 支持多 Action batch、timeout、late-result filtering。
- ONGOING action 使用 `execution_id` 追踪后台生命周期。

### Action

`tinysoul/action/` 定义可执行能力。每个 Action 通过 `ACTION_JSON` 描述自己，通过 `ActionExecutor` 执行实际逻辑。

Action 层最重要的设计是“自描述”和“执行”分离：

- `ACTION_JSON` 是给 LLM 和框架共同读取的能力说明，拆成 Step 1 使用的 meta 与 Step 2 使用的 detail。
- `ActionHandler` 管元数据、运行时配置和 executor 装配。
- `ActionExecutor` 管真实执行逻辑，失败时抛 `TinysoulError` 子类或在后台路径 emit signal。
- `ActionRuntimeConfig` / `RunConfig` 管 timeout、dependency、termination、execution_id 等运行时控制，不进入 LLM 可见的 action 描述。

执行上，Step 2b 统一经过 `ParallelDispatcher`。即使只有一个 Action，也会按 batch 方式执行；多 Action 时用 `ThreadPoolExecutor` 并发调度，并以最慢 action 的 timeout 加 buffer 作为 batch 边界。超时不会强杀 Python 线程，而是通过 `RunConfig.request_termination()`、timeout signal、late-result filtering 和具体 executor 的协作式停止来收口。

Action mode 分为两类：

- `SINGLE_RUN`：执行完成后返回一次结果。
- `ONGOING`：启动成功后立即返回 `ONGOING_STARTED`，后台通过 `ContextProvider.emit_signal()` 持续发 `ONGOING_TICK` / `ONGOING_COMPLETED`，并通过 `execution_id` 与 `stop_ongoing_action` 管理生命周期。

内置 Action 包括：

- `answer`：生成最终答案并结束 loop。
- `ask_user`：向用户提问并挂起 loop。
- `reasoning`：显式结构化思考，可跳过 Step 3。
- `calculate`：轻量数学计算。
- `average_dog_weight`：demo 用知识查询。
- workspace actions：扫描、读取、创建、编辑、删除文件。
- scripting actions：创建、编辑、注册临时脚本 Action。
- `git`：受限只读 Git CLI action。
- `monitor` / `stop_ongoing_action`：ONGOING action 原型。

### Context

`tinysoul/context/` 管理 Agent 可见状态。

`QueryState` 聚合四类运行时信息：

- `todo_list`
- `milestone_list`
- `action_record_list`
- `feedback_error_list`

`Workspace` 管理文件资源索引和变更日志，所有 `resource_access` 都按 workspace 相对路径解析，并做边界校验。

### LLM

`tinysoul/llm/` 提供统一 LLM 调用入口：

- `PromptBuilder`：把 ContextProvider 数据组装成五元素 prompt。
- `AITask`：执行 LLM 调用并解析结构化输出。
- `Interpreter`：从 LLM 文本中提取 JSON object。
- `AIClient`：管理 provider model pool、重试、failover。

当前 chat 调用按 profile 分层路由：

| Profile | 使用位置 | 作用 |
|---|---|---|
| `step1` | `ChooseActionTask` | 选择下一步 action |
| `step2` | `TakeActionTask` | 为选中 action 生成参数 |
| `step3` | `UpdateStateTask` | 消化 action record 并更新 state |
| `action_llm` | `OneStepAIExecutor` / `run_llm_task()` | Action 内部的一步式 LLM 调用 |

调用链是：`PromptBuilder` 组 prompt → `AITask.run(profile=...)` → `AIClient.chat(profile)` → 合并 profile config 与请求级 `ChatConfig` → 根据 `provider_chain` 构建模型池 → 重试 / failover → adapter 调用 provider → `Interpreter` 解析 JSON。这样 Step 级任务和 Action 内部 LLM 调用可以共用一套 provider、重试、解析和错误映射机制，同时通过 profile 使用不同的模型链、能力要求和生成参数。

支持的 provider：

| Provider | Chat | Embedding | Image Gen | API Key |
|---|---:|---:|---:|---|
| Zhipu | yes | yes | yes | `GLM_API_KEY` / `ZHIPU_API_KEY` |
| Kimi | yes | yes | yes | `KIMI_API_KEY` / `MOONSHOT_API_KEY` |
| DeepSeek | yes | yes | no | `DEEPSEEK_API_KEY` |
| MiniMax | yes | yes | no | `MINIMAX_API_KEY` |

### Prompt

`tinysoul/prompt/` 管理系统提示和内置 markdown prompt 资源：

- loop-level system：外部 `loop_system` sources + 内置 `query_loop.system.md`。
- loop step guides：`choose_action.guide.md`、`generate_parameters.guide.md`、`update_state.guide.md`。
- action system：`action_execution_context.system.md`、`one_step_default.system.md`、`register_script.system.md`。

它与 `PromptBuilder` 的边界是刻意分开的：`prompt/` 负责资源加载与 system message 组装，`llm.tasks.PromptBuilder` 负责五元素 user prompt。

这一层目前解决的是“稳定系统约束”和“任务上下文 prompt”的分离：loop-level system 定义整个 Query Loop 的行为边界，step guide 定义每一步的输出协议，action system 则让内部 LLM action 继承当前 query 的系统约束，同时追加 action execution context 和 action-specific system。

README 层面的预留设计空间主要在 `home/agent`、提示词迭代和 skill 迭代：后续可以把 agent 身份、团队规则、领域规范、可复用 skill 和 prompt 版本演进放入更结构化的 Agent Home，而不是把所有规则硬编码进代码或一次性塞进 system prompt。当前代码已经有 `InlinePromptSource` / `FilePromptRef` / `BuiltinPromptRef` 这样的资源抽象，便于后续逐步接入。

### Trap

`tinysoul/trap/` 是错误和信号的路由中枢。核心分层：

- `AbortError`：配置错误、系统耗尽等致命错误。
- `RecoverableError`：可自动恢复的错误。
- `FeedbackError`：需要反馈给 LLM 的错误。

Action 错误会双记录：既进入 `loop_error_list`，也作为失败的 `action_record` 进入执行历史。

### Infra

`tinysoul/infra/` 提供配置、日志、进程控制和脚本沙箱。

- 配置集中在 `defaults.py` 和 `GlobalSettings`。
- 环境变量按 `TINYSOUL_{FIELD_NAME.upper()}` 自动映射。
- `EventLogger` 支持 level、category 和 sink。
- `ManagedProcessRunner` 统一 subprocess / sandbox worker 的 timeout 和 termination。
- `sandbox.py` 为 LLM 生成脚本提供 AST 校验、受限 builtins、受限文件 I/O 和子进程超时。

---

## 快速开始

### 1. 安装依赖

项目当前未发布为 pip 包，直接在仓库根目录安装依赖：

```bash
pip install -r requirements.txt
```

环境依赖：Python 3.13.x。项目主要依赖标准库，运行时外部依赖只有 `openai>=1.0`。

### 2. 配置环境变量

复制 `.env.example` 为 `.env`，至少填一个 provider API key：

```bash
GLM_API_KEY=your_zhipu_api_key
# or
KIMI_API_KEY=your_kimi_api_key
# or
DEEPSEEK_API_KEY=your_deepseek_api_key
# or
MINIMAX_API_KEY=your_minimax_api_key
```

### 3. 运行 demo

```bash
python main.py dog_weight
python main.py dynamic_script
```

`dog_weight` 演示多轮查询、知识 action、计算和 workspace 写入。`dynamic_script` 演示 LLM 创建 Python 脚本、注册为临时 Action，并执行数据分析。

### 4. 代码示例

```python
from pathlib import Path

from tinysoul.context.workspace import Workspace
from tinysoul.loop.loop import QueryLoop
from tinysoul.prompt import InlinePromptSource

workspace = Workspace(workspace_location=str(Path("home/workspace/demo").resolve()))

loop = QueryLoop(
    initial_query="计算 Border Collie 和 Scottish Terrier 的平均体重总和，并写入报告。",
    loop_system=[
        InlinePromptSource(
            "basic",
            "You are a careful assistant. Prefer explicit state updates.",
        )
    ],
    loop_target="计算两种狗的平均体重总和，并生成 markdown 报告",
    available_action_names=[
        "average_dog_weight",
        "calculate",
        "create_markdown_file",
        "answer",
    ],
    workspace=workspace,
)

outcome = loop.query_loop(max_turns=8)
print(outcome.status.value, outcome.completed_turns, outcome.answer)
```

---

## 配置

配置通过 `.env` 或系统环境变量读取。`TINYSOUL_*` 配置名由 `GlobalSettings` 字段自动推导。

常用项：

| 环境变量 | 默认值 | 说明 |
|---|---:|---|
| `TINYSOUL_MAX_TURNS` | `20` | 单 query 最大 turn 数 |
| `TINYSOUL_MAX_TOKENS` | `8000` | 单次 completion 最大 token |
| `TINYSOUL_TEMPERATURE` | `0.7` | 采样温度 |
| `TINYSOUL_MAX_RETRIES` | `3` | 单模型重试次数 |
| `TINYSOUL_BASE_RETRY_DELAY` | `1.0` | 指数退避初始秒数 |
| `TINYSOUL_LLM_TIMEOUT` | `120.0` | 单次 LLM 请求超时 |
| `TINYSOUL_ACTION_TIMEOUT` | `120.0` | 默认 Action 生命周期预算 |
| `TINYSOUL_CLI_TIMEOUT` | `60.0` | CLI Action 超时 |
| `TINYSOUL_SCRIPT_TIMEOUT` | `15.0` | SCRIPT Action 沙箱超时 |
| `TINYSOUL_PARALLEL_MAX_WORKERS` | `5` | 并行 Action worker 上限 |
| `TINYSOUL_LOG_LEVEL` | `normal` | `quiet` / `normal` / `verbose` / `debug` |
| `TINYSOUL_LOG_CATEGORIES` | `all` | 逗号分隔分类或 `all` |
| `TINYSOUL_LOG_COLOR` | `1` | 控制台颜色开关 |

Chat provider 顺序由 `TINYSOUL_CHAT_PROFILES` 的 profile JSON 控制，例如：

```bash
TINYSOUL_CHAT_PROFILES={"step1":{"provider_chain":["deepseek","kimi"],"required_capabilities":["text"],"preferred_capabilities":[],"chat_model_overrides":{},"config":{}},"step2":{"provider_chain":["zhipu","kimi"],"required_capabilities":["text"],"preferred_capabilities":[],"chat_model_overrides":{},"config":{}},"step3":{"provider_chain":["kimi","deepseek"],"required_capabilities":["text"],"preferred_capabilities":[],"chat_model_overrides":{},"config":{}},"action_llm":{"provider_chain":["kimi","zhipu"],"required_capabilities":["text"],"preferred_capabilities":["vision"],"chat_model_overrides":{},"config":{}}}
```

模型名可通过 provider 自身变量覆盖，例如 `GLM_MODEL`、`KIMI_MODEL`、`DEEPSEEK_MODEL`、`MINIMAX_MODEL`。

Profile 的合并顺序是：provider/model pool 身份由配置决定；`ChatProfile.config` 提供该 profile 的默认生成参数；单次请求传入的 `ChatConfig` 覆盖 request 级参数，例如 timeout、temperature、max tokens；真正的 provider failover 仍由 `provider_chain` 和模型池顺序决定。

---

## 发布前状态

当前仓库已经包含：

- 核心代码和 demo 入口。
- 模块文档：`docs/module/*`。
- 公开分析与 todo 文档：`docs/analysis/*`、`docs/todo/*`。
- 单元测试和真实 API 集成测试。
- `.gitignore` 与 `.env.example`。

运行测试：

```bash
python -m pytest
```

真实 API 集成测试默认跳过。如需运行：

```powershell
$env:RUN_REAL_API_TESTS = "1"
python -m pytest tests/integration
```

---

## 已知边界

TinySoul 目前仍是原型阶段，有一些边界需要明确：

- `PromptBuilder.include_context` 已实现，但 Step1/2/3 尚未接入精细裁剪，长任务下 token 成本仍会增长。
- `validate_action_input` 当前只校验 payload 是 object 和 required 字段存在，不执行完整 JSON Schema 类型校验。
- `OneStepAIExecutor` 当前要求存在 workspace，因此部分 LLM action 在无 workspace 场景下不能直接运行。
- 脚本沙箱是 best-effort，不是生产级安全隔离；生产使用需要 OS 级沙箱、容器或低权限 worker。
- `delete_file` 这类 destructive action 依赖 LLM 选择策略避免误删，框架层尚未强制用户确认。
- 状态没有持久化数据库，`QueryState` 生命周期绑定单次 QueryLoop。

---

## 路线方向

短期优先级仍然围绕“把单 query 内核打磨清楚”：

1. 接入 Step 级 `include_context` 裁剪，降低 prompt 成本。
2. 升级 Action input 校验，明确 required-only 与 full schema 的边界。
3. 增加 destructive action 的框架级确认策略。
4. 强化脚本沙箱和动态 Action 注册的失败回滚。
5. 完善 ONGOING action 的 list/pause/resume/cleanup 控制面。

中长期方向会更系统化：

1. 将 `home/agent` 发展为 Agent Home：承载身份、规范、prompt 版本、领域 skill 与资源索引。
2. 引入与单次 `QueryState` 分离的长期 memory/session/processing 层，让 query 能主动检索必要记忆，而不是继承全部会话历史。
3. 发展 query-centered context：围绕当前 query 收集会话语义、workspace、长期记忆、工具依赖和 skill，并把收集过程变成可调试流程。
4. 增加 QueryState 持久化、中断恢复、服务化封装、任务队列和指标观测。
5. 探索多 query / 多 session 之上的 Agent 协作模型，以及面向专用领域智能体的流程编排、评测和优化方法。

---

## 文档索引

- [Loop 模块](docs/module/loop.md)
- [Action 模块](docs/module/action.md)
- [Context 模块](docs/module/context.md)
- [Prompt 模块](docs/module/prompt.md)
- [Trap 模块](docs/module/trap.md)
- [LLM 模块](docs/module/llm.md)
- [Infra 模块](docs/module/infra.md)
- [项目分析](docs/module/project_analysis.md)
