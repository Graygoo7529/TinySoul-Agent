
# Query Loop

Query Loop（agent turn orchestrator with OS-style exception routing）

`tinysoul.loop.loop` 中的 `QueryLoop` 是 TinySoul 的核心调度器，驱动 Agent 与 LLM 的多轮交互。每轮（turn）固定为三 step：选择 Action → 生成参数并执行 → 更新状态。所有 step 的执行被 `_run_step` 统一包裹，异常通过 `ErrorTrap` 集中路由。

## Design_Principles

（1）**三 step 固定范式**
- Step 1 `choose_action`：从可用 Action 中选择最适配的一个
- Step 2 `generate_parameters` + `execute_action`：生成 JSON 参数并执行
- Step 3 `update_state`：基于执行结果更新 todo / milestone / finished
- 三 step 的输入输出均为结构化 JSON，由 `AITask` + `Interpreter` 统一处理

（2）**OS-Style 异常路由**
- 所有 step 由 `_run_step` 统一包裹，异常不再按类型分散 try/except
- `ErrorTrap.capture()` 作为中断向量表，将异常分类为 CONTINUE / RETRY / ABORT
- `KeyboardInterrupt` 被路由为 ABORT，外层优雅返回当前状态
- 部分失败隔离：`update_state` 中的每个 todo operation 独立 try/except

（3）**ContextProvider 驱动**
- `QueryContext` 实现 `ContextProvider` 协议，持有运行时对象引用
- Prompt 组装由 `PromptBuilder` 负责，LLM 调用由 `AITask` 负责
- `QueryLoop` 只负责调度，不直接操作 prompt 字符串或 LLM 响应

（4）**读取即消费（Consume-on-Read）**
- `action_record_list` 中的记录带有 `read` 标志
- Step 3 前调用 `consume_new_action_records()`，将未读记录标记为已读
- 未读记录作为 `new_action_records` 独立块传入 Step 3，明确告诉 LLM "这是本轮新发生的事件"

## Architecture

```
┌─────────────────────────────────────────┐
│  query/loop.py                          │
│  - QueryLoop（调度器）                    │
│  - _run_step（统一异常包裹）               │
│  - _step1_choose_action                 │
│  - _step2a_generate_parameters          │
│  - _step2b_execute_action               │
│  - _step3_update_state                  │
│  - _apply_state_updates（部分失败隔离）    │
├─────────────────────────────────────────┤
│  query/context.py                       │
│  - QueryContext（ContextProvider 实现）   │
├─────────────────────────────────────────┤
│  query/prompts.py                       │
│  - query_loop_system                    │
│  - CHOOSE_ACTION_TASK_GUIDE             │
│  - TAKE_ACTION_TASK_GUIDE               │
│  - UPDATE_STATE_TASK_GUIDE              │
├─────────────────────────────────────────┤
│  query/steps/                           │
│  - ChooseActionTask（Step 1）            │
│  - TakeActionTask（Step 2a）             │
│  - UpdateStateTask（Step 3）             │
└─────────────────────────────────────────┘
```

## Core_Components

### QueryLoop

调度器，管理 Agent Query Loop 的完整生命周期。

**构造参数：**
- `user_query`：用户查询
- `basic_system`：外部系统上下文
- `loop_target`：循环目标
- `available_action_names`：可用 Action 名称列表（allowlist）
- `init_todo_list`：初始待办事项
- `workspace`：可选的 Workspace 实例
- `client`：可选的 AIClient 注入（测试用）
- `registry`：可选的 ActionRegistry 注入（测试用）
- `logger`：可选的 EventLogger 注入

**初始化行为：**
1. 若未提供 `registry`，自动创建并 `bootstrap()` 内置 Action
2. 若提供 `available_action_names`，对 registry 应用 allowlist 过滤
3. 创建 `QueryState`、`QueryAction`、`QueryContext`、`PromptBuilder`
4. 创建三个 Step Task 实例（复用 across turns）
5. 若 `workspace` 非空且 `resources` 为空，自动触发 `scan()`
6. 清空所有资源的 `resource_desc.relevance`（跨 loop 隔离）
7. 构建 system context（basic_system + query_loop_system）

### _run_step

统一 step 执行包裹器，OS-style 中断模型：

```
step_fn() 执行
    ↓
BaseException 发生（SystemExit / GeneratorExit 直接透传）
    ↓
ErrorTrap.capture(exc, ErrorContext)
    ↓
返回 TrapResult（Disposition + loop_error + action_result）
    ↓
根据 Disposition 执行恢复策略：
  - ABORT：重新 raise（KeyboardInterrupt 原样传播，其他 fatal error 传播）
  - RETRY：记录日志，继续（预留）
  - CONTINUE：记录 loop_error，若 ActionError 则双记录 action_result，继续下一 turn
```

### _drain_signal_bus

每个 step 结束后，QueryLoop 调用 `_drain_signal_bus()` 消费 SignalBus 中缓冲的所有信号：

```
SignalBus.consume() → list[Signal]
    ↓
for signal in signals:
    ErrorTrap.route(signal) → TrapResult
    InterruptHandler.handle(trap_result, signal.to_error_context())
        → action_record_list / loop_error_list / ongoing_action_list 写入
```

这保证了：
- 并行 action 的结果在 Step 3 前已完整写入 state
- ONGOING 后台线程产生的 tick 不会跨轮遗漏
- 所有状态突变（无论来源是硬中断还是软中断）都经过同一套 `InterruptHandler`

ErrorContext 精确标识异常位置：
- `turn`：当前 turn 编号（1-based）
- `step`：`choose_action` | `generate_parameters` | `execute_action` | `update_state`
- `action_name`：由 `FeedbackError` 异常对象自身携带（`exc.action_name`），不在 `_run_step` 中显式注入
- `action_input`：由 `FeedbackError` 异常对象自身携带，不在 `_run_step` 中显式注入

### Step 1: Choose Action

`ChooseActionTask` 通过 `AITask` 调用 LLM，输入：
- 可用 actions 的 meta 列表（不含 detail）
- action schema（定义 action 结构的标准 schema）

期望输出：
```json
{"action_name": "<name>", "selection_reason": "<reason>"}
```

若 `action_name` 缺失，抛出 `LLMResponseValidationError`。

### Step 2a: Generate Parameters

`TakeActionTask` 通过 `AITask` 调用 LLM，输入：
- 选中 action 的 detail（parameter_schema, examples, edge_case_handling）

期望输出：符合 parameter_schema 的 JSON 对象。

### Step 2b: Execute Action

`QueryAction.execute()` 调用对应 Handler 的 `execute()`，传入：
- `action_input`：Step 2a 生成的参数
- `context_provider`：`QueryContext` 实例

执行结果（成功、失败、超时）统一 emit 为 `Signal` 进入 `SignalBus`：
- 成功 → `Signal(ACTION_COMPLETED)`，payload 含 `result`
- 失败 → `Signal(ACTION_FAILED)`，payload 含 `error`、`error_type`（原始异常类型，含 cause 链）
- 超时 → `Signal(ACTION_TIMEOUT)`，payload 含 `error`

**串行与并行路径终点一致**：无论单 action 还是多 action batch，结果都进入 SignalBus，不在执行现场直接写 state。

### Step 3: Update State

`UpdateStateTask` 通过 `AITask` 调用 LLM，输入：
- `new_action_records`：本轮未读的 action records（consume-on-read）
- `state_schema`：state 结构的标准 schema

期望输出：
```json
{
  "todo_operations": [
    {"operation": "add", "key": "<key>", "description": "<desc>"},
    {"operation": "complete", "key": "<key>"},
    {"operation": "cancel", "key": "<key>"}
  ],
  "milestone_operation": "add" | "no-change",
  "milestone_param": "<desc>" | null,
  "finished": true | false
}
```

`_normalize_state_updates()` 做防御性校验：
- `finished` 字符串（"yes"/"true"/"1"）转 bool
- `todo_operations` 必须是数组，元素必须是含 `operation` + `key` 的字典

`_apply_state_updates()` 逐个应用 todo operation，单个失败不影响同轮其他操作。

## State_Update_Semantics

（1）**Todo Operation 隔离**
- 每个 todo operation 独立 try/except
- 一个 operation 失败（如歧义 key）不会丢弃同轮的其他 operation 或 milestone
- 失败记录为 `loop_error`；非 `TinysoulError` 子类的异常 error_type 前缀 `state/`，框架异常直接使用类名

（2）**Milestone 只增**
- 仅支持 `add` 操作，不支持删除或编辑
- 保证里程碑是单调增长的历史记录

（3）**Finished Flag**
- 当前由 LLM 显式输出 `finished` 控制循环终止
- Future：由专用 `answer` action 终止 loop，移除显式 flag

## Query_Context

`QueryContext` 实现 `ContextProvider` 协议，职责：
- 持有运行时对象引用：`query_state`, `query_action`, `workspace`
- 按需序列化：`get_current_state()`, `get_workspace()`, `consume_new_action_records()`
- 维护 `current_turn`

`get_current_state()` 的字段顺序有语义：
1. `action_record_list` — 静态边界（单调增长的历史）
2. `feedback_error_list` — 派生自 loop_error_list，过滤 auto_handled
3. `current_turn` — 动态部分
4. `todo_list`, `milestone_list`, `ongoing_action_list`

## Loop_Termination

正常终止条件：
- `finished == true`（Step 3 输出）
- 达到 `max_turns`（默认 20，由 `settings.max_turns` 控制）

异常终止：
- `KeyboardInterrupt`：外层捕获，返回 `interrupted: true`
- `AbortError`（如 `ConfigError`, `SystemExhaustedError`）：向上传播

返回结果：
```python
{
    "completed_turns": int,
    "final_state": dict,  # QueryContext.get_current_state()
    "finished": bool,
    "interrupted": bool,  # 仅 KeyboardInterrupt 时
}
```

## Integration

### 与 Action 的关系
- `QueryLoop` 持有 `QueryAction`，通过它执行 Action
- `QueryAction` 从注入的 `ActionRegistry` 解析 Handler
- 动态注册的 Action（如 temporary script）下一 turn 立即可见

### 与 LLM Task 的关系
- 三个 Step 均通过 `AITask` 调用 LLM
- `PromptBuilder` 自动注入共享上下文（user_query, loop_target, current_state, workspace, current_turn）
- Action schema 和 State schema 通过 `InputSpec.data` 传入，而非 system context

### 与 ErrorTrap 的关系
- `_run_step` 是硬中断（异常）的单一入口
- `_drain_signal_bus` 是软中断（Signal）的单一入口
- `ErrorTrap` 的 `capture()` 和 `route()` 共享同一套 IVT，统一输出 `TrapResult`
- `InterruptHandler.handle()` 是所有状态突变的唯一执行点
- `ActionError` 双记录：`loop_error_list` + `action_record_list`

## Invariants

All steps are wrapped by _run_step; no per-step try/except scattered in business code
Action schema and State schema travel via InputSpec.data, not system context
new_action_records are consumed before Step 3 and marked as read immediately
Each todo operation is isolated; partial failures do not discard the entire round
KeyboardInterrupt is routed through ErrorTrap and re-raised for graceful outer handling
max_turns is read from settings.max_turns, not hard-coded
