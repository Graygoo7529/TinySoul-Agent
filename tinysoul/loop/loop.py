"""
Query Loop Manager for Query Loop.

Manages the Agent Query Loop execution flow:
1. Choose action (via ChooseActionTask)
2. Take action with parameters (via TakeActionTask)
3. Update state based on results (via UpdateStateTask)

All LLM calls flow through the LLM Task infrastructure (tinysoul.llm.tasks).

Architecture:
    QueryLoop is the absolute outer boundary — it never raises exceptions.
    All control flow (continue / terminate / suspend / error) returns via
    the unified LoopOutcome dataclass.
"""

import json
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any

from tinysoul.action.framework.handler import ActionMode
from tinysoul.action.framework.manager import QueryAction
from tinysoul.action.framework.run_config import TerminationReason
from tinysoul.action.framework.registry import ActionRegistry
from tinysoul.trap import (
    Disposition,
    ErrorContext,
    ErrorTrap,
    LLMResponseValidationError,
    TrapOutcome,
)
from tinysoul.trap.signal import Signal, SignalBus, SignalType
from tinysoul.loop.parallel_dispatcher import ActionSpec, ParallelDispatcher
from tinysoul.infra import EventLogger, default_logger
from tinysoul.llm.tasks.prompt import PromptBuilder
from tinysoul.prompt import PromptSource, build_loop_system
from tinysoul.action.framework.schema import get_action_schema
from tinysoul.infra.config import settings
from tinysoul.context.state.schema import get_query_state_schema
from tinysoul.context.state import QueryState, TodoItem
from tinysoul.context.state.update import apply_state_updates
from tinysoul.context.workspace import Workspace

from .context import QueryContext
from .steps import ChooseActionTask, TakeActionTask, UpdateStateTask


# Sentinel values for _run_step control flow ---------------------------------
_ABORT_SENTINEL = object()
_INTERRUPT_SENTINEL = object()


@dataclass
class LoopOutcome:
    """
    Unified return value of query_loop() and resume().

    QueryLoop is the absolute outer boundary — it never raises exceptions.
    All paths return a LoopOutcome; callers inspect ``status`` to determine
    what happened.
    """

    class Status(Enum):
        COMPLETED = "completed"      # LOOP_COMPLETE received
        SUSPENDED = "suspended"      # LOOP_SUSPEND received
        EXHAUSTED = "exhausted"      # max_turns reached without resolution
        INTERRUPTED = "interrupted"  # KeyboardInterrupt (Ctrl+C)
        ABORTED = "aborted"          # Unrecoverable error

    status: Status
    completed_turns: int
    final_state: dict[str, Any]
    answer: str = ""
    pending_question: dict | None = None
    error_type: str | None = None
    error_message: str | None = None


class QueryLoop:
    """
    Manager for the Agent Query Loop.

    Orchestrates the cycle of:
    - Action selection (ChooseActionTask)
    - Action execution with parameters (TakeActionTask)
    - State update (UpdateStateTask)

    Supports control flow signals for loop completion (COMPLETE_LOOP),
    turn skipping (NEXT_TURN), and suspension (SUSPEND_LOOP).
    """

    def __init__(
        self,
        initial_query: str = "",
        loop_system: list[PromptSource] | None = None,
        loop_target: str = "",
        available_action_names: list[str] | None = None,
        init_todo_list: list[TodoItem] | None = None,
        workspace: Workspace | None = None,
        client: Any | None = None,
        registry: ActionRegistry | None = None,
        logger: EventLogger | None = None,
        env_caps=None,
    ):
        """
        Initialize QueryLoop.

        Args:
            initial_query: The initial input that triggered this query.
            loop_system: External loop-level system sources. The built-in query
                         loop system is appended automatically.
            loop_target: The target goal for this loop
            available_action_names: Optional whitelist of action names to use from the
                                    registry. If None, all registered actions are available.
            init_todo_list: Initial todo items (TodoItem objects)
            workspace: Optional Workspace instance for file-system context
            client: Optional injected LLM client (avoids global singleton in tests)
            registry: Optional ActionRegistry instance. If None, a default registry is
                      created and built-in actions are bootstrapped automatically.
            env_caps: Optional environment capabilities for dependency filtering.
        """
        if registry is None:
            from tinysoul.action.handlers import bootstrap

            registry = ActionRegistry(env_caps=env_caps)
            bootstrap(registry)

        if available_action_names is not None:
            registry = registry.with_allowlist(available_action_names)

        self.initial_query = initial_query
        self.loop_system = list(loop_system or [])
        self.loop_target = loop_target
        self._client = client
        self._logger = logger or default_logger()

        # Initialize state and action managers
        self.query_state = QueryState(init_todo_list or [])
        self.query_action = QueryAction(
            registry.get_available_action_names(), registry=registry, logger=self._logger
        )
        self.workspace = workspace

        # Signal bus — unified buffer for all execution events
        self._signal_bus = SignalBus()

        # Context manager: pure data provider for prompts
        self.query_context = QueryContext(
            query_events=self.initial_query,
            loop_target=self.loop_target,
            query_state=self.query_state,
            query_action=self.query_action,
            workspace=self.workspace,
            signal_bus=self._signal_bus,
            client=self._client,
            loop_level_system_messages=self._build_system_context(),
        )

        # Prompt builder bound to the context manager
        self._prompt_builder = PromptBuilder(self.query_context)

        # Task instances (reused across turns)
        self._choose_task = ChooseActionTask(self._prompt_builder)
        self._take_task = TakeActionTask(self._prompt_builder)
        self._update_task = UpdateStateTask(self._prompt_builder)

        # Exception router (injected with AIClient for failover handling)
        from tinysoul.llm.provider import get_ai_client

        if self._client is None:
            self._client = get_ai_client()
            if hasattr(self._client, "set_logger"):
                self._client.set_logger(self._logger)

        self._error_trap = ErrorTrap(
            ai_client=self._client,
            query_state=self.query_state,
            query_context=self.query_context,
            logger=self._logger,
        )

        # Parallel dispatcher for heterogeneous parallel action execution
        self._parallel_dispatcher = ParallelDispatcher(
            query_action=self.query_action,
            signal_bus=self._signal_bus,
            logger=self._logger,
        )

        # Auto-scan workspace if location provided but resources empty
        if self.workspace is not None and not self.workspace.resources:
            self.workspace.scan()

        # Build system context
        self.system = self.query_context.get_loop_level_system()

        # Resume state (preserved across suspend/resume cycles)
        self._turn_offset: int = 0
        self._suspended_at_turn: int | None = None
        self._max_turns_limit: int = settings.max_turns

        # Emit loop-ready event
        self._logger.loop_ready(
            query=self.initial_query,
            target=self.loop_target,
            action_count=len(self.query_action.list_available_action_names()),
        )

    def _build_system_context(self) -> list[dict[str, str]]:
        """
        Build the global system context for LLM calls.

        Contains:
        1. external loop_system sources
        2. built-in query loop execution contract
        """
        return build_loop_system(self.loop_system)

    def _maybe_debug_state(self, state_json: str, step_name: str) -> None:
        self._logger.debug_state(state_json=state_json, step=step_name)

    def _get_current_turn_action_result(self, action_name: str | None = None) -> dict:
        """Read the most recent action result for the current turn from query_state."""
        for record in reversed(self.query_state.action_record_list):
            if record.turn == self.query_context.current_turn:
                if action_name is None or record.action_name == action_name:
                    return record.action_result
        return {}

    def _build_action_spec(self, name: str, target: str) -> ActionSpec:
        """Build an ActionSpec with the correct mode from action metadata."""
        try:
            mode = self.query_action.get_action_mode(name)
        except Exception:
            # Fallback to SINGLE_RUN if action metadata cannot be resolved.
            # This preserves safety: unknown/unavailable actions default to
            # single-run semantics and will fail later at execution time
            # with ActionNotFoundError, which is already handled by ErrorTrap.
            mode = ActionMode.SINGLE_RUN
        return ActionSpec(name=name, target=target, args={}, mode=mode)

    def _last_loop_error(self) -> tuple[str | None, str | None]:
        """Return (error_type, message) of the most recent loop error, or (None, None)."""
        if self.query_state.loop_error_list:
            err = self.query_state.loop_error_list[-1]
            return err.error_type, err.message
        return None, None

    def _drain_signal_bus(self) -> None:
        """Consume pending signals and route their data side effects."""
        signals = self._signal_bus.consume()
        if signals:
            self._error_trap.process_signal_batch(signals)

    def _shutdown_ongoing_actions(
        self,
        reason: TerminationReason = TerminationReason.SHUTDOWN,
        drain_timeout: float = 0.3,
    ) -> None:
        """Request shutdown for registered ONGOING controls and drain completions."""
        self._drain_signal_bus()
        requested = self.query_context.request_all_ongoing_termination(reason)
        if requested <= 0:
            return

        deadline = time.monotonic() + drain_timeout
        while time.monotonic() < deadline:
            self._drain_signal_bus()
            if not self.query_state.get_ongoing_action_list():
                return
            time.sleep(0.02)
        self._drain_signal_bus()

    # ========================================================================
    # Unified exception wrapper
    # ========================================================================

    def _run_step(
        self,
        step_name: str,
        step_fn: Any,
        action_name: str | None = None,
        action_target: str | None = None,
    ) -> Any:
        """Execute a step wrapped by ErrorTrap. Returns data, None, or a sentinel."""
        try:
            return step_fn()
        except BaseException as exc:
            if isinstance(exc, (SystemExit, GeneratorExit)):
                raise

            context = ErrorContext(
                turn=self.query_context.current_turn,
                step=step_name,
                action_name=action_name,
            )
            outcome = self._error_trap.capture(exc, context)

            if outcome.decision == Disposition.ABORT:
                return _ABORT_SENTINEL
            if outcome.decision == Disposition.USER_INTERRUPT:
                return _INTERRUPT_SENTINEL

            # Non-ABORT / Non-INTERRUPT: step failed but loop continues
            self._logger.step_recovered(step=step_name)
            return None

    @staticmethod
    def _normalize_state_updates(data: dict) -> dict:
        """
        Normalize and validate state-update dict from LLM.
        """
        result = {
            "todo_operations": data.get("todo_operations", []),
            "milestone_operation": data.get("milestone_operation", "no-change"),
            "milestone_param": data.get("milestone_param"),
        }

        if not isinstance(result["todo_operations"], list):
            raw_preview = json.dumps(data, ensure_ascii=False)[:240]
            raise LLMResponseValidationError(
                f"'todo_operations' must be an array, but got {type(result['todo_operations']).__name__}. "
                f"Your raw output preview: {raw_preview}"
            )

        for op in result["todo_operations"]:
            if not isinstance(op, dict):
                raw_preview = json.dumps(data, ensure_ascii=False)[:240]
                raise LLMResponseValidationError(
                    f"Each todo operation must be an object, but got {type(op).__name__}: {op!r}. "
                    f"Your raw output preview: {raw_preview}"
                )
            if "operation" not in op or "key" not in op:
                missing = [f for f in ("operation", "key") if f not in op]
                raw_preview = json.dumps(data, ensure_ascii=False)[:240]
                raise LLMResponseValidationError(
                    f"Todo operation missing required fields {missing} in {op!r}. "
                    f"Your raw output preview: {raw_preview}"
                )

            op_type = op.get("operation")
            if op_type not in ("add", "complete", "cancel"):
                raw_preview = json.dumps(data, ensure_ascii=False)[:240]
                raise LLMResponseValidationError(
                    f"Invalid todo operation '{op_type}'. Must be one of: add, complete, cancel. "
                    f"Your raw output preview: {raw_preview}"
                )

            if op_type == "add":
                desc = op.get("description")
                if not desc or not isinstance(desc, str):
                    raw_preview = json.dumps(data, ensure_ascii=False)[:240]
                    raise LLMResponseValidationError(
                        f"Todo operation 'add' requires a non-empty string 'description'. "
                        f"Your raw output preview: {raw_preview}"
                    )

            if op_type in ("complete", "cancel"):
                key = op.get("key")
                if not key or not isinstance(key, str):
                    raw_preview = json.dumps(data, ensure_ascii=False)[:240]
                    raise LLMResponseValidationError(
                        f"Todo operation '{op_type}' requires a non-empty string 'key'. "
                        f"Your raw output preview: {raw_preview}"
                    )

        milestone_op = result["milestone_operation"]
        if milestone_op not in ("add", "no-change"):
            raw_preview = json.dumps(data, ensure_ascii=False)[:240]
            raise LLMResponseValidationError(
                f"Invalid milestone_operation '{milestone_op}'. Must be 'add' or 'no-change'. "
                f"Your raw output preview: {raw_preview}"
            )

        return result

    # ========================================================================
    # Step implementations
    # ========================================================================

    def _step1_choose_action(self) -> list[ActionSpec]:
        """Step 1: Choose action(s) from available actions."""
        current_state = self.query_context.get_current_state(compact=False)
        self._maybe_debug_state(json.dumps(current_state, ensure_ascii=False, indent=2), "choose action")

        available_actions_meta = self.query_action.get_available_actions_meta()
        action_schema = get_action_schema()

        self._logger.debug_action_meta(meta_list=available_actions_meta)

        result = self._choose_task.run(
            system=self.system,
            available_actions_meta=available_actions_meta,
            action_schema=action_schema,
            client=self._client,
            logger=self._logger,
        )

        if "actions" in result:
            actions = result["actions"]
            specs = []
            for a in actions:
                name = a.get("action_name", "").strip()
                target = a.get("selection_reason", "").strip()
                if not name:
                    raise LLMResponseValidationError(
                        f"Missing 'action_name' in action selection: {a}"
                    )
                specs.append(self._build_action_spec(name, target))
            for spec in specs:
                self._logger.action_selected(
                    name=spec.name, reason=spec.target
                )
            return specs

        action_name = result.get("action_name", "").strip()
        action_target = result.get("selection_reason", "").strip()

        if not action_name:
            raise LLMResponseValidationError(
                f"Missing 'action_name' in action selection: {result}"
            )

        self._logger.action_selected(name=action_name, reason=action_target)
        return [self._build_action_spec(action_name, action_target)]

    def _step2a_generate_parameters(self, action_specs: list[ActionSpec]) -> list[ActionSpec]:
        """Step 2a: Generate JSON arguments for each selected action."""
        import concurrent.futures

        current_state = self.query_context.get_current_state(compact=False)
        self._maybe_debug_state(json.dumps(current_state, ensure_ascii=False, indent=2), "generate parameters")

        def _generate_for_spec(spec: ActionSpec) -> None:
            selected_action_detail = self.query_action.get_selected_action_detail(
                spec.name
            )
            self._logger.debug_action_detail(detail=selected_action_detail)

            action_args = self._take_task.run(
                system=self.system,
                selected_action_detail=selected_action_detail,
                client=self._client,
                logger=self._logger,
                selection_reason=spec.target,
            )
            self._logger.action_args(args=action_args, action_name=spec.name)
            spec.args = action_args

        with concurrent.futures.ThreadPoolExecutor(
            max_workers=min(len(action_specs), 3)
        ) as executor:
            futures = [
                executor.submit(_generate_for_spec, spec) for spec in action_specs
            ]
            for future in concurrent.futures.as_completed(futures):
                future.result()

        return action_specs

    def _step2b_execute_actions(self, action_specs: list[ActionSpec]) -> bool:
        """Step 2b: Execute action(s) with generated arguments.

        All actions (single or parallel) are dispatched through ParallelDispatcher
        for unified signal emission and error handling.
        """
        current_state = self.query_context.get_current_state(compact=False)
        self._maybe_debug_state(json.dumps(current_state, ensure_ascii=False, indent=2), "execute action")

        self._parallel_dispatcher.dispatch(
            action_specs,
            self.query_context,
            turn=self.query_context.current_turn,
        )
        return True

    def _step3_update_state(self) -> dict[str, Any]:
        """Step 3: Update runtime state based on action results."""
        current_state = self.query_context.get_current_state(compact=False)
        self._maybe_debug_state(json.dumps(current_state, ensure_ascii=False, indent=2), "update state")

        new_action_records = self.query_context.peek_new_action_records()
        state_schema = get_query_state_schema()

        raw_updates = self._update_task.run(
            system=self.system,
            state_schema=state_schema,
            new_action_records=new_action_records,
            client=self._client,
            logger=self._logger,
        )
        updates = self._normalize_state_updates(raw_updates)

        todo_parts = []
        for todo_op in updates.get("todo_operations", []):
            op = todo_op["operation"]
            if op in ("add", "complete", "cancel"):
                todo_parts.append(op)
        todo_info = " | ".join(todo_parts) if todo_parts else "no-change"

        milestone_info = updates.get("milestone_operation", "no-change")
        self._logger.state_updated(
            todo=todo_info, milestone=milestone_info
        )

        apply_state_updates(
            self.query_state,
            updates,
            self.query_context.current_turn,
            self._logger,
        )
        self.query_context.ack_action_records()
        return updates

    # ========================================================================
    # LoopOutcome builders
    # ========================================================================

    def _loop_outcome_for_sentinel(
        self, sentinel: Any, completed_turns: int
    ) -> LoopOutcome | None:
        """Map a sentinel to LoopOutcome, or None if not a sentinel."""
        if sentinel is _INTERRUPT_SENTINEL:
            self._shutdown_ongoing_actions()
            self._turn_offset = 0
            self._suspended_at_turn = None
            self._logger.turn_ended(turn=completed_turns)
            self._logger.loop_interrupted()
            return LoopOutcome(
                status=LoopOutcome.Status.INTERRUPTED,
                completed_turns=completed_turns,
                final_state=self.query_context.get_current_state(compact=False),
            )
        if sentinel is _ABORT_SENTINEL:
            self._shutdown_ongoing_actions()
            self._turn_offset = 0
            self._suspended_at_turn = None
            self._logger.turn_ended(turn=completed_turns)
            error_type, error_message = self._last_loop_error()
            return LoopOutcome(
                status=LoopOutcome.Status.ABORTED,
                completed_turns=completed_turns,
                final_state=self.query_context.get_current_state(compact=False),
                error_type=error_type,
                error_message=error_message,
            )
        return None

    def _loop_outcome_for_batch(
        self, decision: Disposition, completed_turns: int, turn: int
    ) -> LoopOutcome | None:
        """Map a batch control-flow decision to LoopOutcome, or None to continue."""
        if decision == Disposition.COMPLETE_LOOP:
            self._shutdown_ongoing_actions()
            self._turn_offset = 0
            self._suspended_at_turn = None
            self._logger.turn_ended(turn=turn + 1)
            return LoopOutcome(
                status=LoopOutcome.Status.COMPLETED,
                completed_turns=completed_turns,
                final_state=self.query_context.get_current_state(compact=False),
                answer=self._get_current_turn_action_result("answer").get("answer", ""),
            )
        if decision == Disposition.SUSPEND_LOOP:
            self._turn_offset = turn + 1
            self._suspended_at_turn = turn + 1
            self._logger.turn_ended(turn=turn + 1)
            return LoopOutcome(
                status=LoopOutcome.Status.SUSPENDED,
                completed_turns=completed_turns,
                final_state=self.query_context.get_current_state(compact=False),
                pending_question=self._get_current_turn_action_result("ask_user"),
            )
        if decision == Disposition.NEXT_TURN:
            self._logger.turn_ended(turn=turn + 1)
            return None  # sentinel meaning "continue to next turn"
        return None

    # ========================================================================
    # Main Loop
    # ========================================================================

    def query_loop(self, max_turns: int | None = None) -> LoopOutcome:
        """
        Execute or resume the query loop.

        Args:
            max_turns: Maximum number of loop iterations. Overrides the
                default from settings when provided.

        Returns:
            LoopOutcome with unified status and state.
        """
        if max_turns is not None:
            self._max_turns_limit = max_turns

        updates: dict[str, Any] | None = None
        completed_turns = 0
        action_specs: list[ActionSpec] | None = None

        for turn in range(self._turn_offset, self._max_turns_limit):
            completed_turns = turn + 1
            self.query_context.current_turn = turn + 1
            self._logger.turn_started(turn=turn + 1, max_turns=self._max_turns_limit)

            # Step 1: Choose action(s)
            action_specs = self._run_step(
                "choose_action", self._step1_choose_action
            )
            outcome = self._loop_outcome_for_sentinel(action_specs, completed_turns)
            if outcome is not None:
                return outcome
            if action_specs is None:
                self._logger.turn_ended(turn=turn + 1)
                continue

            # Step 2a: Generate action parameters
            action_specs = self._run_step(
                "generate_parameters",
                lambda: self._step2a_generate_parameters(action_specs),
            )
            outcome = self._loop_outcome_for_sentinel(action_specs, completed_turns)
            if outcome is not None:
                return outcome
            if action_specs is None:
                self._logger.turn_ended(turn=turn + 1)
                continue

            # Step 2b: Execute action(s)
            step2b_result = self._run_step(
                "execute_action",
                lambda: self._step2b_execute_actions(action_specs),
            )
            outcome = self._loop_outcome_for_sentinel(step2b_result, completed_turns)
            if outcome is not None:
                return outcome
            if step2b_result is None:
                self._logger.turn_ended(turn=turn + 1)
                continue

            # Batch-process all signals: data side effects + control flow aggregation
            signals = self._signal_bus.consume()
            batch_outcome = self._error_trap.process_signal_batch(signals)

            outcome = self._loop_outcome_for_batch(
                batch_outcome.decision, completed_turns, turn
            )
            if outcome is not None:
                return outcome

            # Step 3: Update state
            updates = self._run_step("update_state", self._step3_update_state)
            outcome = self._loop_outcome_for_sentinel(updates, completed_turns)
            if outcome is not None:
                return outcome
            if updates is None:
                updates = {
                    "todo_operations": [],
                    "milestone_operation": "no-change",
                    "milestone_param": None,
                }
                self._logger.turn_ended(turn=turn + 1)
                continue

            self._logger.turn_ended(turn=turn + 1)

        # max_turns exhausted
        self._shutdown_ongoing_actions()
        self._turn_offset = 0
        self._suspended_at_turn = None
        return LoopOutcome(
            status=LoopOutcome.Status.EXHAUSTED,
            completed_turns=completed_turns,
            final_state=self.query_context.get_current_state(compact=False),
        )

    # ========================================================================
    # Resume
    # ========================================================================

    def resume(self, user_response: str) -> LoopOutcome:
        """
        Resume a suspended loop with the user's response to the last ask.

        Preconditions:
            - query_loop() previously returned with status=SUSPENDED
            - user_response is the answer to pending_question

        Postconditions:
            - The user's response is appended to query_history
            - Loop continues from the next turn after suspension

        Returns:
            LoopOutcome with unified status and state.  If the loop is not in
            suspended state or no ask question is found, returns ABORTED.
        """
        from tinysoul.loop.query import QueryEventRole

        if self._suspended_at_turn is None:
            return LoopOutcome(
                status=LoopOutcome.Status.ABORTED,
                completed_turns=0,
                final_state=self.query_context.get_current_state(compact=False),
                error_type="ResumeStateError",
                error_message="Loop is not in suspended state. Call query_loop() first and wait for SUSPEND.",
            )

        # Find the last INQUIRY in query event stream
        ask_items = [
            item for item in self.query_context.query_events.items
            if item.role == QueryEventRole.INQUIRY
        ]
        if not ask_items:
            return LoopOutcome(
                status=LoopOutcome.Status.ABORTED,
                completed_turns=self._suspended_at_turn,
                final_state=self.query_context.get_current_state(compact=False),
                error_type="ResumeStateError",
                error_message="No inquiry found in query event stream",
            )

        last_question = ask_items[-1].content
        self.query_context.append_response(user_response, last_question)

        # Reset suspension flag but keep _turn_offset
        self._suspended_at_turn = None

        # Continue execution
        return self.query_loop()

    def is_suspended(self) -> bool:
        """Check if the loop is currently in suspended state."""
        return self._suspended_at_turn is not None
