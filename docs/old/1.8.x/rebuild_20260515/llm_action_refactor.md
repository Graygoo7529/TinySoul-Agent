# LLM-Action 扩展与架构演进重构方案

> **Version**: 2.0 — 面向长期架构演进
>
> **原则**: 不向后兼容。干净清除 `finished` flag、`user_query` 字符串语义等历史遗留。所有消费端统一拿到全量 `user_query` 列表。
>
> **核心洞察**: ErrorTrap 从"错误路由器"演进为"事件路由器"；SignalBus 从"内部缓冲"演进为"跨边界事件总线"。

---

## 一、架构演进宣言：从错误处理到事件驱动控制流

### 1.1 当前架构的隐性假设

TinySoul 当前的设计隐含一个假设：**Loop 是自闭环的**。所有控制流（终止、重试、继续）都通过 Step 3 的 `finished` flag 或异常路径表达。这个假设在引入 Ask Action 和 Gateway 后被打破。

### 1.2 演进方向

```
Before:                    After:
┌─────────────┐           ┌─────────────────────────────┐
│  ErrorTrap  │           │        ErrorTrap            │
│  (错误路由)  │           │    (事件路由器 / IVT)        │
│             │           │                             │
│  ABORT      │           │  ABORT  ──▶ 致命终止         │
│  RETRY      │           │  RETRY  ──▶ 重试当前 step    │
│  CONTINUE   │           │  CONTINUE ──▶ 继续下一 step  │
│             │           │  TERMINATE ──▶ 正常结束 loop │
│             │           │  SKIP_STEP3 ──▶ 跳过 State   │
│             │           │  SUSPEND ──▶ 暂停等待输入    │
└─────────────┘           └─────────────────────────────┘
```

**关键认知转变**: `TERMINATE` / `SKIP_STEP3` / `SUSPEND` 不是"错误"，而是**正常的控制流事件**。ErrorTrap 的命名虽然保留（OS-Style Interrupt Controller 的语义已涵盖此范畴），但其职责正式扩展。

---

## 二、核心概念重新定义

### 2.1 user_query — 不再是字符串，而是对话历史

```python
# BEFORE (历史遗留)
user_query: str = "What is their combined weight?"

# AFTER
user_query: list[UserQueryItem] = [
    UserQueryItem(role=USER_INITIAL, content="What is their combined weight?", turn=0),
    UserQueryItem(role=AGENT_ASK, content="What are the breeds?", turn=2),
    UserQueryItem(role=USER_RESPONSE, content="Border Collie", turn=3, ask_context="What are the breeds?"),
]
```

**原则**:
- 接口上只存在 `user_query`，不存在 `query_history`、`latest_query` 或任何别名
- 所有消费端拿到的都是完整列表
- `QueryLoop.__init__(user_query: str)` 的构造函数表面保留（方便调用方），内部立即包装为 `UserQueryItem(role=USER_INITIAL)`

### 2.2 Action 执行结果 — 不再只分"成功/失败"

当前 Action 执行只有两种结果:
- 成功 → `ACTION_COMPLETED` 信号
- 失败 → `ACTION_FAILED` 信号

演进后，Action 执行结果扩展为:
- 成功并继续 → `ACTION_COMPLETED`
- 成功并终止 loop → `LOOP_COMPLETE`（answer）
- 成功并跳过 Step 3 → `LOOP_NEXT_TURN`（reasoning）
- 成功并暂停 loop → `LOOP_SUSPEND`（ask_user）
- 失败 → `ACTION_FAILED`

### 2.3 Loop 终止 — 不再由 Step 3 决定

当前: Step 3 输出 `finished: true` → Loop 终止
演进后: Step 2b 执行 answer action → 发射 `LOOP_COMPLETE` → ErrorTrap 路由为 `TERMINATE` → Loop 立即终止

**Step 3 的职责收窄**: 只更新 todo / milestone，不再决定 loop 生死。

---

## 三、ErrorTrap 重新定位：事件路由器

### 3.1 Disposition 扩展

```python
class Disposition(Enum):
    CONTINUE = "continue"
    RETRY = "retry"
    ABORT = "abort"
    TERMINATE = "terminate"      # 新增：正常终止（answer）
    SKIP_STEP3 = "skip_step3"    # 新增：跳过 State Update（reasoning）
    SUSPEND = "suspend"          # 新增：暂停等待外部输入（ask_user）
```

### 3.2 SignalType 扩展

```python
class SignalType(StrEnum):
    # ── Action execution signals ──
    ACTION_COMPLETED = "action_completed"
    ACTION_FAILED = "action_failed"
    ACTION_TIMEOUT = "action_timeout"

    # ── ONGOING lifecycle signals ──
    ONGOING_STARTED = "ongoing_started"
    ONGOING_TICK = "ongoing_tick"
    ONGOING_COMPLETED = "ongoing_completed"
    ONGOING_FAILED = "ongoing_failed"
    ONGOING_STOPPED = "ongoing_stopped"

    # ── Control signals ──
    TURN_TIMEOUT = "turn_timeout"
    INTERRUPT = "interrupt"

    # ── LLM-Action control flow signals (新增) ──
    LOOP_COMPLETE = "loop_terminate"
    LOOP_NEXT_TURN = "loop_skip_step3"
    LOOP_SUSPEND = "loop_suspend"

    # ── External injection signals (新增) ──
    USER_QUERY_INJECTED = "user_query_injected"
```

### 3.3 route() 方法重构

**关键约束**: `_SUCCESS_SIGNALS` 当前包含 `ACTION_COMPLETED`，且 `route()` 对其硬编码返回 `Disposition.CONTINUE`。

当 answer action 执行时，会发生以下信号序列:
1. answer executor 内部调用 `emit_signal(LOOP_COMPLETE)`
2. Step 2b 执行成功，自动 `emit(ACTION_COMPLETED)`

SignalBus 中会同时存在两个信号。`route()` 需要分别处理:

```python
# error/trap.py

# 新增：控制流信号直接路由，不走 IVT
_CONTROL_FLOW_SIGNALS: dict[SignalType, Disposition] = {
    SignalType.LOOP_COMPLETE: Disposition.TERMINATE,
    SignalType.LOOP_NEXT_TURN: Disposition.SKIP_STEP3,
    SignalType.LOOP_SUSPEND: Disposition.SUSPEND,
}

def route(self, signal: Signal) -> TrapResult:
    context = ErrorContext(...)

    # Control signals (existing)
    if signal.type == SignalType.INTERRUPT:
        return self._handle_interrupt(...)
    if signal.type == SignalType.TURN_TIMEOUT:
        return TrapResult(Disposition.CONTINUE)

    # NEW: LLM-Action control flow signals — 直接路由，优先级高于 SUCCESS_SIGNALS
    if signal.type in self._CONTROL_FLOW_SIGNALS:
        return TrapResult(
            disposition=self._CONTROL_FLOW_SIGNALS[signal.type],
            action_result=signal.payload.get("result", {}),
        )

    # Success signals — 仅当没有控制流信号时生效
    if signal.type in self._SUCCESS_SIGNALS:
        return TrapResult(
            Disposition.CONTINUE,
            loop_error=None,
            action_result=signal.payload.get("result", {}),
        )

    # ... existing ACTION_FAILED / failure mapping ...
```

**重要**: 控制流信号的优先级高于 `ACTION_COMPLETED`。即使 SignalBus 中同时存在 `LOOP_COMPLETE` 和 `ACTION_COMPLETED`，QueryLoop 在检查 disposition 时会先看到 `TERMINATE`。

### 3.4 capture() 方法 — 无需修改

新增的 disposition（`TERMINATE` / `SKIP_STEP3` / `SUSPEND`）**不会从 `capture()` 中产生**。它们只从 `route()` 中产生。因此 `_run_step()` 中的异常处置逻辑保持不变:

```python
# query/loop.py _run_step()
if trap_result.disposition == Disposition.ABORT:
    raise exc
if trap_result.disposition == Disposition.RETRY:
    self._logger.step_retry(...)
# CONTINUE / TERMINATE / SKIP_STEP3 / SUSPEND 不会从 capture() 产生
```

---

## 四、QueryLoop 控制流重构

### 4.1 _drain_signal_bus_and_collect()

将现有的 `_drain_signal_bus()` 替换为返回 `TrapResult` 列表的版本:

```python
def _drain_signal_bus_and_collect(self, step_name: str) -> list[TrapResult]:
    signals = self._signal_bus.consume()
    results: list[TrapResult] = []
    for signal in signals:
        trap_result = self._error_trap.route(signal)
        self._interrupt_handler.handle(trap_result, signal.to_error_context())
        results.append(trap_result)
    return results
```

### 4.2 query_loop() 主循环重构

```python
def query_loop(self, max_turns: int = settings.max_turns) -> dict[str, Any]:
    updates: dict[str, Any] | None = None
    completed_turns = 0
    action_specs: list[ActionSpec] | None = None

    try:
        for turn in range(max_turns):
            completed_turns = turn + 1
            self.query_context.current_turn = turn + 1
            self._logger.turn_started(turn=turn + 1, max_turns=max_turns)

            # Step 1: Choose action(s)
            action_specs = self._run_step("choose_action", self._step1_choose_action)
            self._drain_signal_bus_and_collect("choose_action")
            if action_specs is None:
                self._logger.turn_ended(turn=turn + 1)
                continue

            # Step 2a: Generate parameters
            action_specs = self._run_step(
                "generate_parameters",
                lambda: self._step2a_generate_parameters(action_specs),
            )
            self._drain_signal_bus_and_collect("generate_parameters")
            if action_specs is None:
                self._logger.turn_ended(turn=turn + 1)
                continue

            # Step 2b: Execute action(s)
            step2b_result = self._run_step(
                "execute_action",
                lambda: self._step2b_execute_actions(action_specs),
            )
            trap_results = self._drain_signal_bus_and_collect("execute_action")

            if step2b_result is None:
                self._logger.turn_ended(turn=turn + 1)
                continue

            # NEW: Check control flow dispositions from LLM-Actions
            control_dispositions = {
                tr.disposition for tr in trap_results
            }

            if Disposition.TERMINATE in control_dispositions:
                # answer action — loop ends immediately, Step 3 is skipped
                answer_payload = next(
                    tr.action_result for tr in trap_results
                    if tr.disposition == Disposition.TERMINATE
                )
                self._logger.turn_ended(turn=turn + 1)
                return {
                    "completed_turns": completed_turns,
                    "final_state": self.query_context.get_current_state(),
                    "finished": True,
                    "interrupted": False,
                    "answer": answer_payload.get("answer", ""),
                }

            if Disposition.SUSPEND in control_dispositions:
                # ask_user action — loop pauses
                suspend_payload = next(
                    tr.action_result for tr in trap_results
                    if tr.disposition == Disposition.SUSPEND
                )
                self._logger.turn_ended(turn=turn + 1)
                return {
                    "completed_turns": completed_turns,
                    "final_state": self.query_context.get_current_state(),
                    "finished": False,
                    "interrupted": False,
                    "suspended": True,
                    "pending_question": suspend_payload,
                }

            if Disposition.SKIP_STEP3 in control_dispositions:
                # reasoning action — skip Step 3, go directly to next turn
                self._logger.turn_ended(turn=turn + 1)
                continue

            # Step 3: Update state (finished flag removed)
            updates = self._run_step("update_state", self._step3_update_state)
            self._drain_signal_bus_and_collect("update_state")
            if updates is None:
                updates = {
                    "todo_operations": [],
                    "milestone_operation": "no-change",
                    "milestone_param": None,
                }
                self._logger.turn_ended(turn=turn + 1)
                continue

            self._logger.turn_ended(turn=turn + 1)

    except KeyboardInterrupt:
        self._logger.turn_ended(turn=completed_turns)
        self._logger.loop_interrupted()
        return {
            "completed_turns": completed_turns,
            "final_state": self.query_context.get_current_state(),
            "finished": False,
            "interrupted": True,
        }

    # max_turns exhausted
    return {
        "completed_turns": completed_turns,
        "final_state": self.query_context.get_current_state(),
        "finished": False,
    }
```

**关键变化**:
- `finished` flag 从 Step 3 中移除
- Step 2b 后检查 control flow dispositions
- `TERMINATE` / `SUSPEND` / `SKIP_STEP3` 分别触发不同路径

---

## 五、user_query 彻底重构

### 5.1 数据模型

**新建**: `tinysoul/runtime/query_history.py`

```python
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

class QueryItemRole(StrEnum):
    USER_INITIAL = "user_initial"
    USER_APPEND = "user_append"
    USER_RESPONSE = "user_response"
    AGENT_ASK = "agent_ask"

@dataclass
class UserQueryItem:
    role: QueryItemRole
    content: str
    turn: int | None = None
    ask_context: str | None = None
    timestamp: datetime = field(default_factory=datetime.now)

    def to_context_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"role": self.role.value, "content": self.content}
        if self.turn is not None:
            result["turn"] = self.turn
        if self.ask_context is not None:
            result["ask_context"] = self.ask_context
        return result
```

### 5.2 QueryContext

**修改**: `tinysoul/query/context.py`

```python
class QueryContext:
    def __init__(self, user_query: str, loop_target: str, ...):
        # 构造函数保留 str 接口，内部立即包装
        self._query_items: list[UserQueryItem] = [
            UserQueryItem(role=QueryItemRole.USER_INITIAL, content=user_query, turn=0)
        ]
        self.loop_target = loop_target
        # ...

    @property
    def user_query(self) -> list[dict[str, Any]]:
        """Full query dialogue history, serialized for prompt injection.

        Always returns the complete list. No 'latest' accessor exists.
        """
        return [item.to_context_dict() for item in self._query_items]

    def append_external_query(self, content: str) -> None:
        self._query_items.append(
            UserQueryItem(role=QueryItemRole.USER_APPEND, content=content, turn=self.current_turn)
        )

    def append_agent_ask(self, question: str) -> None:
        self._query_items.append(
            UserQueryItem(role=QueryItemRole.AGENT_ASK, content=question, turn=self.current_turn)
        )

    def append_user_response(self, response: str, question: str) -> None:
        self._query_items.append(
            UserQueryItem(
                role=QueryItemRole.USER_RESPONSE,
                content=response,
                turn=self.current_turn,
                ask_context=question,
            )
        )
```

**注意**: `user_query` property 直接返回 `list[dict[str, Any]]`，而非 `list[UserQueryItem]`。这样 PromptBuilder 的 `json.dumps()` 可以直接序列化，无需额外转换。

### 5.3 ContextProvider 协议

**修改**: `tinysoul/runtime/protocols.py`

```python
class ContextProvider(Protocol):
    @property
    def user_query(self) -> list[dict[str, Any]]:
        """Full query dialogue history. Always a complete list."""
        ...

    def get_framework_system(self) -> list[dict[str, str]]: ...
    def append_agent_ask(self, question: str) -> None: ...
    def append_user_response(self, response: str, question: str) -> None: ...
    def emit_signal(self, signal: "Signal") -> None: ...
```

### 5.4 下游消费端适配

所有消费 `user_query` 的地方统一适配为列表:

**BashExecutor** (`action/executors/subprocess/bash.py`):
```python
def _build_context_dict(self, context_provider):
    if context_provider is None:
        return {}
    return {
        "user_query": getattr(context_provider, "user_query", []),
        "loop_target": getattr(context_provider, "loop_target", ""),
        "current_turn": getattr(context_provider, "current_turn", 0),
    }
```

**CLIExecutor** (`action/executors/subprocess/cli.py`):
```python
import json

env["TINYSOUL_USER_QUERY"] = json.dumps(
    context_provider.user_query, ensure_ascii=False
)
```

**ScriptExecutor** (`action/executors/script/base.py`):
```python
ctx["user_query"] = context_provider.user_query  # 已经是 list[dict]
```

---

## 六、框架意图注入

### 6.1 问题

当前 `OneStepAIExecutor` 的默认 system prompt:
```
You are a content generation assistant embedded in an agent framework.
Your output is parsed automatically by an Interpreter...
```

这个 prompt **不包含框架意图**。内部 LLM 不知道:
- 自己在 Agent Query Loop 的 Step 2b 中执行
- `current_state` 中的 `action_record_list` 是单调增长的历史
- `user_query` 现在是完整对话列表
- 自己的执行结果会进入 SignalBus，被 Step 3 消费

### 6.2 解决方案

**QueryContext 提供框架意图**:

```python
def get_framework_system(self) -> list[dict[str, str]]:
    from tinysoul.loop.prompts import query_loop_system
    return [{
        "role": "system",
        "content": (
            f"{query_loop_system}\n\n"
            "=== ACTION EXECUTION CONTEXT ===\n"
            "You are currently executing INSIDE Step 2b of the query loop.\n"
            "Your action's result will be recorded in action_record_list and "
            "consumed by Step 3 (Update State).\n"
            "The user_query field in context is a FULL DIALOGUE HISTORY (list), "
            "not a single string. It contains all user inputs and agent questions.\n"
            "You may emit control signals (TERMINATE, SKIP_STEP3, SUSPEND) that "
            "affect the loop flow."
        ),
    }]
```

**OneStepAIExecutor 动态合并**:

```python
def execute(self, action_input, context_provider, run_config):
    # ... existing workspace check ...

    framework_system = []
    if context_provider is not None:
        getter = getattr(context_provider, "get_framework_system", None)
        if getter is not None:
            framework_system = getter()

    full_system = framework_system + self._system_prompt

    task = AITask(prompt=prompt, interpreter=Interpreter(), client=self._client)
    generated = task.run(system=full_system).data
    # ...
```

**效果**: 所有使用 `OneStepAIExecutor` 的 Action（create_markdown_file、edit_markdown_file、read_markdown_file、answer、reasoning）自动获得完整的框架意图。

---

## 七、Answer Action

### 7.1 定位

- **Cluster**: `INTERNAL` / `REASONING`
- **Intention**: `INTERNAL_REASONING`
- **Effect**: `READ_ONLY`
- **Mode**: `SINGLE_RUN`
- **LLM Dependency**: `REQUIRED`
- **终止语义**: 唯一合法的 loop 终止方式

### 7.2 Executor

```python
# action/handlers/internal/reasoning/answer.py

def _build_answer_prompt(builder, params, workspace):
    instruction = params.get("instruction", "")
    reference_accesses = params.get("reference_accesses", [])
    refs = workspace.read_reference_files(reference_accesses) if reference_accesses else []

    refs_data = {}
    if refs:
        refs_data = {
            r["target_access"]: r["content"][:settings.reference_truncate]
            for r in refs
        }

    return builder.build(
        task_guide=(
            "You are the Answer Action. Produce the FINAL answer to the user's query.\n\n"
            "Requirements:\n"
            "1. Review the FULL query dialogue history (user_query), current state, and workspace.\n"
            "2. Synthesize all gathered information into a comprehensive answer.\n"
            "3. Directly address the loop_target.\n"
            "4. Cite workspace files when appropriate.\n"
            "5. This is the TERMINAL action -- the loop ends after your answer."
        ),
        input_spec=InputSpec(
            description="Answer instruction and reference materials.",
            data={"instruction": instruction, "reference_files": refs_data},
        ),
        output_constraint=OutputConstraint(
            description='JSON: {"answer_text": str, "confidence": "high|medium|low", "references": [str]}'
        ),
    )

def _apply_answer_result(params, generated, workspace, context_provider):
    answer_text = generated.get("answer_text", "")
    confidence = generated.get("confidence", "medium")
    references = generated.get("references", [])

    # Emit LOOP_COMPLETE signal
    context_provider.emit_signal(Signal(
        type=SignalType.LOOP_COMPLETE,
        turn=context_provider.current_turn,
        step="execute_action",
        action_name="answer",
        action_input=params,
        payload={
            "result": {
                "answer": answer_text,
                "confidence": confidence,
                "references": references,
            }
        },
    ))

    return {
        "result": f"Answer generated ({confidence} confidence)",
        "answer_preview": answer_text[:200],
    }
```

### 7.3 控制流

1. Step 1: LLM 选择 `answer` action
2. Step 2a: LLM 生成参数 `{"instruction": "...", "reference_accesses": ["report.md"]}`
3. Step 2b: `AnswerExecutor` 内部 LLM 生成完整答案，发射 `LOOP_COMPLETE`
4. Step 2b 继续: 自动发射 `ACTION_COMPLETED`
5. `_drain_signal_bus_and_collect()`: 消费到 `TERMINATE` + `CONTINUE`
6. QueryLoop: 检测到 `TERMINATE`，立即 return，跳过 Step 3

---

## 八、Reasoning Action

### 7.1 定位

- **Cluster**: `INTERNAL` / `REASONING`
- **Intention**: `INTERNAL_REASONING`
- **Effect**: `READ_ONLY`
- **Mode**: `SINGLE_RUN`
- **LLM Dependency**: `REQUIRED`
- **控制语义**: 自主决定是否需要 Step 3

### 8.2 Executor

```python
def _build_reasoning_prompt(builder, params, workspace):
    reasoning_type = params.get("reasoning_type", "synthesis")
    topic = params.get("topic", "")
    reference_accesses = params.get("reference_accesses", [])
    refs = workspace.read_reference_files(reference_accesses) if reference_accesses else []

    return builder.build(
        task_guide=(
            f"You are the Reasoning Action. Perform {reasoning_type.upper()} reasoning.\n\n"
            "Requirements:\n"
            "1. Review the full query dialogue, current state, action records, and workspace.\n"
            "2. Perform deep, structured reasoning on the given topic.\n"
            "3. Produce clear conclusions and optional next-action proposals.\n"
            "4. If you produce actionable next steps, the loop will run Step 3 to update todos.\n"
            "5. If your reasoning is purely analytical, set skip_step3=true."
        ),
        input_spec=InputSpec(
            description="Reasoning topic and reference materials.",
            data={
                "reasoning_type": reasoning_type,
                "topic": topic,
                "reference_files": refs,
            },
        ),
        output_constraint=OutputConstraint(
            description='JSON: {"reasoning_type": str, "content": str, "conclusions": [str], '
            '"proposed_next_actions": [str], "skip_step3": bool}'
        ),
    )

def _apply_reasoning_result(params, generated, workspace, context_provider):
    conclusions = generated.get("conclusions", [])
    proposed = generated.get("proposed_next_actions", [])
    skip = generated.get("skip_step3", False)

    if skip or not proposed:
        context_provider.emit_signal(Signal(
            type=SignalType.LOOP_NEXT_TURN,
            turn=context_provider.current_turn,
            step="execute_action",
            action_name="reasoning",
            payload={"result": {**generated, "skipped_step3": True}},
        ))

    return {"result": generated}
```

### 8.3 控制流

- `skip_step3=true` 或 `proposed_next_actions` 为空 → `LOOP_NEXT_TURN` → 跳过 Step 3 → 进入下一轮
- 有 actionable plan → 不发射信号 → 正常走 Step 3 → LLM 将 conclusions 转为 todo

---

## 九、Ask Action + Gateway

### 9.1 Ask Action 定位

- **Cluster**: `INTERNAL` / `INTERACTION`
- **Intention**: `EXTERNAL_PROBING`
- **Effect**: `READ_ONLY`
- **Mode**: `SINGLE_RUN`
- **LLM Dependency**: `REQUIRED`

### 9.2 Executor

```python
class AskUserExecutor(ActionExecutor):
    def execute(self, action_input, context_provider, run_config):
        question = action_input.get("question", "")

        # Record agent ask in query history
        context_provider.append_agent_ask(question)

        # Emit LOOP_SUSPEND signal
        context_provider.emit_signal(Signal(
            type=SignalType.LOOP_SUSPEND,
            turn=context_provider.current_turn,
            step="execute_action",
            action_name="ask_user",
            action_input=action_input,
            payload={
                "result": {
                    "question": question,
                    "context": action_input.get("context", ""),
                    "options": action_input.get("options", []),
                    "urgency": action_input.get("urgency", "blocking"),
                }
            },
        ))

        return {"result": f"Asked user: {question}"}
```

### 9.3 Gateway 注入用户回答

```python
# Gateway 侧（与 Loop 共享同一个 SignalBus）
shared_bus.emit(Signal(
    type=SignalType.USER_QUERY_INJECTED,
    turn=0,
    step="gateway",
    payload={
        "injected_query": "Border Collie and Scottish Terrier",
        "ask_context": "What are the breeds of your two dogs?",
        "source": "gateway",
    }
))
```

### 9.4 InterruptHandler 处理注入

```python
# error/interrupt_handler.py

def __init__(self, query_state, logger=None, query_context=None):
    self._state = query_state
    self._logger = logger
    self._query_context = query_context

def handle(self, trap_result, context):
    # ... existing record / error / ongoing handling ...

    if (
        context.signal_type == SignalType.USER_QUERY_INJECTED
        and self._query_context is not None
    ):
        new_query = trap_result.action_result.get("injected_query", "")
        ask_ctx = trap_result.action_result.get("ask_context", "")

        if ask_ctx:
            self._query_context.append_user_response(new_query, ask_ctx)
        else:
            self._query_context.append_external_query(new_query)

        # Record as special action record for visibility
        self._state.record_action(
            action_name="user_query_injected",
            action_target=f"Query from {trap_result.action_result.get('source', 'unknown')}",
            action_input={"query": new_query, "ask_context": ask_ctx},
            action_result={"acknowledged": True},
            turn=context.turn,
        )
```

### 9.5 SUSPEND 后的恢复（长期演进）

**Phase 1**（ immediate ）:
- Loop 返回 `suspended: True` + `pending_question`
- 外部代码获取用户回答
- 创建**新的 QueryLoop**，将旧 Loop 的 `final_state` 作为初始状态传入
- 新 Loop 继续执行

**Phase 2**（长期演进）:
- QueryLoop 支持 `resume()` 方法
- Loop SUSPEND 后不销毁，保持内部状态
- 外部调用 `loop.resume(user_response)` 恢复执行
- `resume()` 将 `user_response` 注入 query_history，继续循环

```python
class QueryLoop:
    def resume(self, user_response: str) -> dict[str, Any]:
        """Resume a suspended loop with user's answer to an ask question."""
        # Find the last AGENT_ASK in query history
        ask_items = [
            item for item in self.query_context._query_items
            if item.role == QueryItemRole.AGENT_ASK
        ]
        last_question = ask_items[-1].content if ask_items else ""

        self.query_context.append_user_response(user_response, last_question)

        # Continue from where we left off
        return self.query_loop(max_turns=self._remaining_turns)
```

---

## 十、下游清理清单

### 10.1 必须清理的历史遗留

| # | 位置 | 历史遗留 | 清理方式 |
|---|------|---------|---------|
| 1 | `query/steps/update.py` | `OutputConstraint` 包含 `finished: true|false` | 移除 `finished` 字段 |
| 2 | `query/prompts.py` `UPDATE_STATE_TASK_GUIDE` | "COMPLETION: Is the overall task complete?" | 移除 finished 相关段落 |
| 3 | `query/loop.py` `_normalize_state_updates()` | `finished` 校验和字符串转换 | 移除 finished 处理 |
| 4 | `query/loop.py` `query_loop()` | `updates.get("finished", False)` | 移除 finished 检查 |
| 5 | `query/loop.py` 返回值 | `finished` 字段由 Step 3 推断 | `finished` 由 `TERMINATE` 推断 |
| 6 | `infra/logger.py` `state_updated()` | 接收 `finished` 参数 | 移除或改为可选 |
| 7 | `infra/logger.py` `loop_complete()` | 接收 `finished` 参数 | 保留（由 TERMINATE 推断） |

### 10.2 bootstrap 子包注册

`handlers/__init__.py` 的 `pkgutil.walk_packages()` 跳过 `ispkg` 为 True 的目录。新建 `reasoning/` 和 `interaction/` 子包后，需要在 `internal/__init__.py` 中显式导入:

```python
# action/handlers/internal/__init__.py

def bootstrap(registry):
    from . import math, knowledge, workspace, scripting, ongoing, reasoning, interaction
    for subpkg in [math, knowledge, workspace, scripting, ongoing, reasoning, interaction]:
        subpkg.bootstrap(registry)
```

每个子包的 `__init__.py`:
```python
# action/handlers/internal/reasoning/__init__.py

def bootstrap(registry):
    from . import answer, reasoning
    answer.register_to(registry)
    reasoning.register_to(registry)
```

---

## 十一、实施路线图

### Phase 0: 基础设施（先完成，再建 Action）

**目标**: 改造核心框架，但不引入任何新 Action。

| # | 文件 | 改动 |
|---|------|------|
| 0.1 | `runtime/query_history.py` | 新建 `QueryItemRole`, `UserQueryItem` |
| 0.2 | `query/context.py` | `user_query` → list property；`append_*` 方法；`get_framework_system()` |
| 0.3 | `runtime/protocols.py` | 协议更新：`user_query: list[dict]`；`get_framework_system`；`append_*` |
| 0.4 | `action/executors/subprocess/bash.py` | `user_query` 消费适配为 list |
| 0.5 | `action/executors/subprocess/cli.py` | `user_query` 消费适配为 list |
| 0.6 | `action/executors/script/base.py` | `user_query` 消费适配为 list |
| 0.7 | `tests/helpers/fakes.py` | `FakeContextProvider.user_query` → list |
| 0.8 | `tests/llm/test_prompt.py` | 断言适配 list 类型 |
| 0.9 | **运行全部测试** | 确保 green |

### Phase 1: 控制流扩展（无 Action）

| # | 文件 | 改动 |
|---|------|------|
| 1.1 | `error/trap.py` | `Disposition` 新增 `TERMINATE`, `SKIP_STEP3`, `SUSPEND` |
| 1.2 | `error/signal.py` | `SignalType` 新增 `LOOP_COMPLETE`, `LOOP_NEXT_TURN`, `LOOP_SUSPEND`, `USER_QUERY_INJECTED` |
| 1.3 | `error/trap.py` | `route()` 新增 `_CONTROL_FLOW_SIGNALS` 路由 |
| 1.4 | `error/interrupt_handler.py` | 新增 `query_context` 参数；处理 `USER_QUERY_INJECTED` |
| 1.5 | `query/loop.py` | `_drain_signal_bus_and_collect()`；Step 2b 后 disposition 检查 |
| 1.6 | `query/loop.py` | 移除 `finished` flag 相关逻辑 |
| 1.7 | `query/steps/update.py` | `OutputConstraint` 移除 `finished` |
| 1.8 | `query/prompts.py` | `UPDATE_STATE_TASK_GUIDE` 移除 finished |
| 1.9 | **运行全部测试** | 确保 green |

### Phase 2: 框架意图注入（无 Action）

| # | 文件 | 改动 |
|---|------|------|
| 2.1 | `action/executors/llm/one_step.py` | `execute()` 动态获取 `framework_system` |
| 2.2 | `query/context.py` | `get_framework_system()` 实现 |
| 2.3 | **运行全部测试** | 验证现有 action 的 prompt 中包含框架意图 |

### Phase 3: Answer Action

| # | 文件 | 改动 |
|---|------|------|
| 3.1 | `action/handlers/internal/reasoning/__init__.py` | 新建 bootstrap |
| 3.2 | `action/handlers/internal/reasoning/answer.py` | 新建 AnswerAction |
| 3.3 | `action/handlers/internal/__init__.py` | 导入 reasoning 子包 |
| 3.4 | `tests/action/handlers/test_answer.py` | 新建测试 |
| 3.5 | `tests/query/test_loop.py` | 重构 DogWeightQueryMock 为 answer action 终止 |

### Phase 4: Reasoning Action

| # | 文件 | 改动 |
|---|------|------|
| 4.1 | `action/handlers/internal/reasoning/reasoning.py` | 新建 ReasoningAction |
| 4.2 | `action/handlers/internal/reasoning/__init__.py` | 注册 reasoning |
| 4.3 | `tests/action/handlers/test_reasoning.py` | 新建测试 |

### Phase 5: Ask Action

| # | 文件 | 改动 |
|---|------|------|
| 5.1 | `action/handlers/internal/interaction/__init__.py` | 新建 bootstrap |
| 5.2 | `action/handlers/internal/interaction/ask_user.py` | 新建 AskUserAction |
| 5.3 | `action/handlers/internal/__init__.py` | 导入 interaction 子包 |
| 5.4 | `tests/action/handlers/test_ask_user.py` | 新建测试 |
| 5.5 | `tests/query/test_loop.py` | 新增 SUSPEND 测试 |

---

## 十二、风险与应对

| # | 风险 | 应对 |
|---|------|------|
| 1 | `ACTION_COMPLETED` 与 `LOOP_COMPLETE` 同时存在于 SignalBus | 控制流信号优先级高于 SUCCESS_SIGNALS，QueryLoop 只响应 `TERMINATE` |
| 2 | `query_loop_system` 较长，增加 token 开销 | 对内部 LLM action 是必要的；未来可精简为 `framework_intent_minimal` |
| 3 | `finished` flag 移除导致大量测试重构 | 按 Phase 实施，每 Phase 后保持测试 green |
| 4 | `pkgutil.walk_packages()` 跳过子包 | 在 `internal/__init__.py` 中显式导入新子包 |
| 5 | LLM 在 Step 1/2/3 中不习惯 `user_query` 是数组 | 在 `query_loop_system` 中明确说明 `"user_query is a FULL DIALOGUE HISTORY (list)"` |
| 6 | SUSPEND 后 Loop 恢复机制复杂 | Phase 1 用"返回 suspended + 外部重建 Loop"；Phase 2 引入 `resume()` |


---

## 十三、Action 行为内容设计

### 一、Answer Action — 终结性答案生成

#### 1.1 行为定位

Answer Action 是 **Loop 的唯一合法终止者**。它的职责不是"执行某个外部操作"，而是**综合所有已收集的信息，生成最终答案，并宣告 Loop 使命完成**。

它与 `create_markdown_file` 的关键区别在于：
- `create_markdown_file`：将内容写入工作区文件，Loop 继续
- `answer`：将内容作为答案返回，Loop 终止

#### 1.2 两步 LLM 调用的职责分离

| 阶段 | LLM 职责 | 输入 | 输出 |
|------|---------|------|------|
| **Step 2a** | **决策**：选择参考文件、确定答案方向 | parameter_schema（instruction, reference_accesses, confidence） | `{"instruction": "...", "reference_accesses": ["report.md"]}` |
| **Step 2b** | **生成**：基于完整上下文 + 参考文件写出答案 | task_guide + context（含完整 user_query 列表）+ instruction + reference_files | `{"answer_text": "...", "confidence": "high"}` |

#### 1.3 Step 2b 内部 LLM 的 Prompt 结构

```
=== SYSTEM (框架意图 + Action-specific) ===
{query_loop_system}
=== ACTION EXECUTION CONTEXT ===
You are the Answer Action. Produce the FINAL answer...

=== CONTEXT ===
{
  "user_query": [
    {"role": "user_initial", "content": "What is combined weight?", "turn": 0},
    {"role": "agent_ask", "content": "What breeds?", "turn": 2},
    {"role": "user_response", "content": "Border Collie + Scottish Terrier", "turn": 3}
  ],
  "loop_target": "Compute combined weight and save report",
  "current_state": {
    "action_record_list": [...],
    "milestone_list": ["Combined weight is 57 lbs"]
  },
  "workspace": {
    "resources": [{"resource_access": "report.md", ...}]
  },
  "current_turn": 7
}

=== INPUT ===
{
  "instruction": "基于 report.md 给出最终答案",
  "reference_files": {"report.md": "# Report\nCombined: 57 lbs..."}
}

=== OUTPUT CONSTRAINT ===
JSON: {"answer_text": str, "confidence": "high|medium|low", "references": [str]}
```

#### 1.4 失败处理

如果 Step 2b 内部 LLM 调用失败（网络错误、JSON 解析失败）：
1. `OneStepAIExecutor` 抛出 `ActionExecutionError`
2. `ActionBase.execute()` 边界包装后透传
3. Step 2b 发射 `ACTION_FAILED` 信号
4. `ErrorTrap` 路由为 `Disposition.CONTINUE`
5. `InterruptHandler` 双记录：`loop_error_list` + `action_record_list`
6. 下一轮 Step 1，LLM 看到错误记录，可能重试 `answer` 或选择其他 action

#### 1.5 关键设计决策：答案是否写入工作区

**决策**：Answer Action 的答案**不自动写入工作区文件**。它的产出是 `action_result` 中的 `answer_text`，直接出现在 Loop 返回值中。

理由：
- answer 是"终结性"的，不需要持久化到文件系统
- 如果用户需要保存答案，可以在 Loop 返回后由外部代码处理
- 与 `create_markdown_file` 的职责边界清晰

---

### 二、Reasoning Action — 结构化显式思考

#### 2.1 行为定位

Reasoning Action 是 **Loop 的"认知节拍器"**。当 LLM 需要：
- 停下来分析连续失败的原因（reflection）
- 在复杂任务前制定详细计划（planning）
- 从多个 action records 中综合洞察（synthesis）
- 形成可验证的假设（hypothesis）

它**不产生外部副作用**，只产生一个"思考记录"存入 `action_record_list`。

#### 2.2 思考内容的持久化

**设计决策**：Reasoning 的完整思考内容直接存入 `action_result`（即 `action_record_list`），**不写入工作区文件**。

理由：
- 简化实现，不引入文件 I/O 复杂度
- action_record_list 本身就是 Loop 的运行时记忆，reasoning 内容作为记忆的一部分是合理的
- 如果未来思考内容过长导致 token 膨胀，再考虑分文件存储

#### 2.3 读取工作区文件作为思考参考

Reasoning Action 支持 `reference_accesses` 参数，可以在思考前读取工作区文件：

```python
def _build_reasoning_prompt(builder, params, workspace):
    reasoning_type = params.get("reasoning_type", "synthesis")
    topic = params.get("topic", "")
    reference_accesses = params.get("reference_accesses", [])
    refs = workspace.read_reference_files(reference_accesses) if reference_accesses else []
    # ... 将 refs 注入 prompt ...
```

#### 2.4 SKIP_STEP3 的语义

| 场景 | reasoning 输出 | 信号 | 效果 |
|------|---------------|------|------|
| 纯分析，无行动计划 | `skip_step3: true` | `LOOP_NEXT_TURN` | 跳过 Step 3，直接进入下一轮 |
| 有行动计划 | `skip_step3: false, proposed_next_actions: [...]` | 无 | 正常走 Step 3，LLM 将 conclusions 转为 todo |

#### 2.5 Reasoning 与 selection_reason 的关系

当前 Step 1 的 `selection_reason` 是"隐式思考"（只用于选择 action）。Reasoning Action 是"显式思考"（独立记录、结构化、可回顾）。

两者的互补关系：
- `selection_reason`：轻量、即时、依附于 action 选择
- `reasoning action`：重量、深度、独立存在于 action_record_list

---

### 三、Ask Action — 人机协作中断

#### 3.1 行为定位

Ask Action 是 **Loop 的"软中断"机制**。当 Agent 发现：
- 用户 query 存在歧义
- 缺少关键信息无法继续
- 需要用户确认才能执行破坏性操作

它**暂停 Loop**，将控制权交还给外部（Gateway / 用户）。

#### 3.2 llm_dependency 的决策

Ask Action 的 `execute()` 不调用内部 LLM（只是发射信号和记录历史）。所以：

```json
"profile": {
    "llm_dependency": "NONE"
}
```

但这不意味着 Ask Action "不需要 LLM"。Step 2a（Generate Parameters）的 LLM 调用是框架层的，Ask Action 的 question、context、options 都由 Step 2a 的 LLM 生成。

`llm_dependency: NONE` 准确表达的是：**Step 2b 的 execute() 不触发内部 LLM 调用**。

#### 3.3 Ask 问题的保存

Ask Action 执行时，通过 `context_provider.append_agent_ask(question)` 将问题保存到 `user_query` 列表中：

```
user_query 列表：
[
  {"role": "user_initial", "content": "What is combined weight?"},
  {"role": "agent_ask", "content": "What are the breeds?"},
  {"role": "user_response", "content": "Border Collie", "ask_context": "What are the breeds?"}
]
```

#### 3.4 SUSPEND 后的状态

Ask Action 发射 `LOOP_SUSPEND` 后，QueryLoop 返回：

```python
{
    "completed_turns": 3,
    "final_state": {
        "action_record_list": [...],  # 包含 ask_user 的 action record
        "todo_list": [...],
        "milestone_list": [...],
    },
    "finished": False,
    "interrupted": False,
    "suspended": True,
    "pending_question": {
        "question": "What are the breeds?",
        "context": "Need breeds to look up weights",
        "options": ["Border Collie + Scottish Terrier", "Other"],
        "urgency": "blocking"
    }
}
```

---

## 十四、QueryLoop Resume 方案 — 保持内部状态

### 4.1 核心问题

当前 `query_loop()` 是一次性函数。SUSPEND 后如何"恢复"？

**方案**：QueryLoop 维护内部恢复状态，提供 `resume()` 方法。

### 4.2 实现设计

```python
class QueryLoop:
    def __init__(self, user_query: str = "", ...):
        # ... existing init ...
        
        # Resume state (preserved across suspend/resume cycles)
        self._turn_offset: int = 0
        """The turn index to resume from. 0 means start from beginning."""
        
        self._suspended_at_turn: int | None = None
        """The turn where SUSPEND occurred, or None if not suspended."""
        
        self._max_turns_limit: int = settings.max_turns
    
    def query_loop(self, max_turns: int | None = None) -> dict[str, Any]:
        """Execute or resume the query loop."""
        if max_turns is not None:
            self._max_turns_limit = max_turns
        
        updates: dict[str, Any] | None = None
        completed_turns = 0
        action_specs: list[ActionSpec] | None = None
        
        try:
            # Resume from _turn_offset instead of 0
            for turn in range(self._turn_offset, self._max_turns_limit):
                completed_turns = turn + 1
                self.query_context.current_turn = turn + 1
                self._logger.turn_started(turn=turn + 1, max_turns=self._max_turns_limit)
                
                # Step 1: Choose action(s)
                action_specs = self._run_step("choose_action", self._step1_choose_action)
                self._drain_signal_bus_and_collect("choose_action")
                if action_specs is None:
                    self._logger.turn_ended(turn=turn + 1)
                    continue
                
                # Step 2a: Generate parameters
                action_specs = self._run_step(
                    "generate_parameters",
                    lambda: self._step2a_generate_parameters(action_specs),
                )
                self._drain_signal_bus_and_collect("generate_parameters")
                if action_specs is None:
                    self._logger.turn_ended(turn=turn + 1)
                    continue
                
                # Step 2b: Execute action(s)
                step2b_result = self._run_step(
                    "execute_action",
                    lambda: self._step2b_execute_actions(action_specs),
                )
                trap_results = self._drain_signal_bus_and_collect("execute_action")
                
                if step2b_result is None:
                    self._logger.turn_ended(turn=turn + 1)
                    continue
                
                # Check control flow dispositions
                control_dispositions = {tr.disposition for tr in trap_results}
                
                if Disposition.TERMINATE in control_dispositions:
                    answer_payload = next(
                        tr.action_result for tr in trap_results
                        if tr.disposition == Disposition.TERMINATE
                    )
                    self._turn_offset = 0
                    self._suspended_at_turn = None
                    self._logger.turn_ended(turn=turn + 1)
                    return {
                        "completed_turns": completed_turns,
                        "final_state": self.query_context.get_current_state(),
                        "finished": True,
                        "interrupted": False,
                        "answer": answer_payload.get("answer", ""),
                    }
                
                if Disposition.SUSPEND in control_dispositions:
                    suspend_payload = next(
                        tr.action_result for tr in trap_results
                        if tr.disposition == Disposition.SUSPEND
                    )
                    # SAVE resume state
                    self._turn_offset = turn + 1
                    self._suspended_at_turn = turn + 1
                    self._logger.turn_ended(turn=turn + 1)
                    return {
                        "completed_turns": completed_turns,
                        "final_state": self.query_context.get_current_state(),
                        "finished": False,
                        "interrupted": False,
                        "suspended": True,
                        "pending_question": suspend_payload,
                    }
                
                if Disposition.SKIP_STEP3 in control_dispositions:
                    self._logger.turn_ended(turn=turn + 1)
                    continue
                
                # Step 3: Update state
                updates = self._run_step("update_state", self._step3_update_state)
                self._drain_signal_bus_and_collect("update_state")
                if updates is None:
                    updates = {
                        "todo_operations": [],
                        "milestone_operation": "no-change",
                        "milestone_param": None,
                    }
                    self._logger.turn_ended(turn=turn + 1)
                    continue
                
                self._logger.turn_ended(turn=turn + 1)
        
        except KeyboardInterrupt:
            self._turn_offset = 0
            self._suspended_at_turn = None
            return {
                "completed_turns": completed_turns,
                "final_state": self.query_context.get_current_state(),
                "finished": False,
                "interrupted": True,
            }
        
        # max_turns exhausted
        self._turn_offset = 0
        self._suspended_at_turn = None
        return {
            "completed_turns": completed_turns,
            "final_state": self.query_context.get_current_state(),
            "finished": False,
        }
    
    def resume(self, user_response: str) -> dict[str, Any]:
        """
        Resume a suspended loop with the user's response to the last ask.
        
        Preconditions:
            - query_loop() previously returned with suspended=True
            - user_response is the answer to pending_question
        
        Postconditions:
            - The user's response is appended to query_history
            - Loop continues from the next turn after suspension
        """
        if self._suspended_at_turn is None:
            raise RuntimeError(
                "Loop is not in suspended state. Call query_loop() first and wait for SUSPEND."
            )
        
        # Find the last AGENT_ASK in query history
        ask_items = [
            item for item in self.query_context._query_items
            if item.role == QueryItemRole.AGENT_ASK
        ]
        if not ask_items:
            raise RuntimeError("No ask question found in query history")
        
        last_question = ask_items[-1].content
        self.query_context.append_user_response(user_response, last_question)
        
        # Reset suspension flag but keep _turn_offset
        self._suspended_at_turn = None
        
        # Continue execution
        return self.query_loop()
    
    def is_suspended(self) -> bool:
        """Check if the loop is currently in suspended state."""
        return self._suspended_at_turn is not None
```

### 4.3 状态保持分析

Resume 时保持的内部状态：

| 状态 | 是否保持 | 说明 |
|------|---------|------|
| `query_state` | ✅ | Todo/Milestone/ActionRecord/LoopError 全部保持 |
| `query_context` | ✅ | user_query 列表、current_turn、workspace 保持 |
| `workspace` | ✅ | 文件系统上下文保持 |
| `query_action` | ✅ | ActionRegistry 视图保持（含动态注册的 action） |
| `_signal_bus` | ✅ | 共享总线，Gateway 注入的信号在 resume 后消费 |
| `_turn_offset` | ✅ | 记录恢复位置 |
| `_choose/_take/_update_task` | ✅ | Task 实例复用 |
| `_client/_logger/_error_trap` | ✅ | 基础设施保持 |
| `completed_turns` | ❌ | 局部变量，每次 query_loop() 重新计算 |

### 4.4 Resume 后的执行流程

```
Turn 3: Ask Action → SUSPEND
  Loop returns suspended=True
  _turn_offset = 4, _suspended_at_turn = 3
  
Gateway displays question → User answers "Border Collie"
  
loop.resume("Border Collie"):
  1. append_user_response("Border Collie", "What are the breeds?")
  2. _suspended_at_turn = None
  3. query_loop() called
  
Turn 4 (resume from _turn_offset=4):
  Step 1: choose → average_dog_weight
  Step 2a: generate → {"breed": "Border Collie"}
  Step 2b: execute → result "37 lbs"
  Step 3: update → complete todo, add milestone
  
Turn 5:
  Step 1: choose → average_dog_weight (Scottish Terrier)
  ...
  
Turn 7:
  Step 1: choose → answer
  Step 2b: answer executor → LOOP_COMPLETE
  Loop returns finished=True
  _turn_offset = 0 (reset)
```

### 4.5 多次 SUSPEND 的支持

`_turn_offset` 和 `_suspended_at_turn` 的设计支持多次 SUSPEND：

```
Turn 3: Ask → SUSPEND → resume(user_answer_1)
Turn 5: Ask → SUSPEND → resume(user_answer_2)
Turn 7: Ask → SUSPEND → resume(user_answer_3)
Turn 9: answer → TERMINATE
```

每次 resume 后 `_turn_offset` 被更新为当前 turn + 1，下一次 query_loop() 从正确位置继续。

### 4.6 与 Gateway 的集成模式

```python
# Gateway 侧
shared_bus = SignalBus()
loop = QueryLoop(
    user_query="What is combined weight?",
    signal_bus=shared_bus,
    ...
)

# 第一次执行
result = loop.query_loop(max_turns=10)

while result.get("suspended"):
    # 显示问题给用户
    question = result["pending_question"]["question"]
    user_answer = gateway.ask_user(question)
    
    # 用户回答通过 SignalBus 注入（可选，用于记录）
    shared_bus.emit(Signal(
        type=SignalType.USER_QUERY_INJECTED,
        turn=0, step="gateway",
        payload={"injected_query": user_answer, "source": "gateway"}
    ))
    
    # Resume loop
    result = loop.resume(user_answer)

# Loop 结束
print(result["answer"])
```

---

## 十五、三个 Action 行为内容总结

| | Answer | Reasoning | Ask |
|--|--------|-----------|-----|
| **意图** | 生成最终答案，终止 Loop | 结构化深度思考，不执行外部操作 | 向用户提问，暂停 Loop |
| **LLM 依赖** | Step 2b 内部 LLM | Step 2b 内部 LLM | 仅 Step 2a（框架层） |
| **参考文件** | `reference_accesses` | `reference_accesses` | 无 |
| **产出** | `answer_text` + `confidence` | `content` + `conclusions` + `proposed_next_actions` | `question` + `options` |
| **持久化** | 返回 Loop 结果，不写入文件 | 完整思考存入 `action_record_list`，**不写入工作区文件** | 问题保存到 user_query 列表 |
| **控制信号** | `LOOP_COMPLETE` | `LOOP_NEXT_TURN`（可选） | `LOOP_SUSPEND` |
| **对 Step 3 的影响** | 跳过 Step 3 | 可选择跳过 Step 3 | 跳过 Step 3（Loop 暂停） |
| **失败处理** | 记录 error，下一轮重试 | 记录 error，下一轮重试 | 记录 error，下一轮重试 |
