"""
Parallel Dispatcher — heterogeneous parallel action execution with blocking sync.

Dispatches multiple actions concurrently, blocks until all complete/fail/timeout,
then returns control. All results are emitted as Signals into the SignalBus
for later unified consumption (typically by the main loop before Step 3).

Execution model:
  Step 2b: QueryLoop calls dispatch()
      ↓
  ThreadPoolExecutor launches N actions in parallel
      ↓
  Each action: success/failure/timeout → Signal → SignalBus.emit()
      ↓
  Block until ALL_COMPLETED or batch timeout
      ↓
  Request termination for pending executions on timeout
      ↓
  Return DispatchOutcome
      ↓
  Main loop drains SignalBus → ErrorTrap.route → InterruptHandler
      ↓
  Step 3: consume_new_action_records() picks up all records
"""

from __future__ import annotations

import concurrent.futures
import threading
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from tinysoul.action.framework.handler import ActionMode
from tinysoul.action.framework.run_config import RunConfig, TerminationReason
from tinysoul.trap.signal import Signal, SignalBus, SignalType
from tinysoul.trap import ActionCancelledError, ActionTimeoutError
from tinysoul.infra import EventLogger, NullSink
from tinysoul.infra.config import settings
from tinysoul.context.protocols import ContextProvider

from tinysoul.action.framework.manager import QueryAction


@dataclass
class ActionSpec:
    """Specification for a single action in a parallel batch."""

    name: str
    target: str
    args: dict[str, Any]
    mode: ActionMode = ActionMode.SINGLE_RUN
    execution_id: str = ""


@dataclass
class DispatchOutcome:
    """Outcome of a parallel dispatch."""

    total: int
    completed: int
    failed: int
    timed_out: int


class ParallelDispatcher:
    """
    Heterogeneous parallel action dispatcher with blocking synchronization.

    Actions are executed in parallel, but their results are NOT processed
    immediately. Instead, they are buffered as Signals in the SignalBus
    for unified consumption by the main loop. This decouples execution
    from state mutation and supports both SINGLE_RUN and ONGOING actions.
    """

    def __init__(
        self,
        query_action: QueryAction,
        signal_bus: SignalBus,
        logger: EventLogger | None = None,
    ):
        self._query_action = query_action
        self._signal_bus = signal_bus
        self._logger = logger or EventLogger(sinks=[NullSink()])

    def dispatch(
        self,
        specs: list[ActionSpec],
        context_provider: ContextProvider,
        turn: int,
        timeout: float | None = None,
    ) -> DispatchOutcome:
        """
        Dispatch actions in parallel, block until all complete/fail/timeout.

        Args:
            specs: List of ActionSpec to execute
            context_provider: Runtime context
            turn: Current turn number
            timeout: Max seconds to wait for all actions. If None, computed
                     via the "slowest decider" algorithm (max action timeout + buffer).

        Returns:
            DispatchOutcome with completion statistics
        """
        total = len(specs)
        if total == 0:
            return DispatchOutcome(total=0, completed=0, failed=0, timed_out=0)

        if timeout is None:
            timeout = self._resolve_dispatch_timeout(specs)

        max_workers = min(total, settings.parallel_max_workers)
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=max_workers)
        futures: dict[concurrent.futures.Future, ActionSpec] = {}
        run_configs: dict[str, RunConfig] = {}
        done: set[concurrent.futures.Future] = set()
        pending: set[concurrent.futures.Future] = set()
        cancelled_execution_ids: set[str] = set()

        try:
            for spec in specs:
                if not spec.execution_id:
                    spec.execution_id = uuid4().hex[:12]
                terminate_event = threading.Event()
                run_config = self._query_action.build_run_config(
                    spec.name,
                    turn=turn,
                    execution_id=spec.execution_id,
                    terminate_event=terminate_event,
                )
                run_configs[spec.execution_id] = run_config
                future = executor.submit(
                    self._execute_single,
                    spec=spec,
                    context_provider=context_provider,
                    run_config=run_config,
                )
                futures[future] = spec

            # Block until all complete or timeout
            done, pending = concurrent.futures.wait(
                futures,
                timeout=timeout,
                return_when=concurrent.futures.ALL_COMPLETED,
            )

            # Request termination for pending executions and record their IDs.
            # Running threads observe the termination intent via RunConfig.
            if pending:
                for future in pending:
                    spec = futures[future]
                    run_configs[spec.execution_id].request_termination(
                        TerminationReason.TIMEOUT
                    )
                    cancelled_execution_ids.add(spec.execution_id)
                    future.cancel()
                for future in pending:
                    spec = futures[future]
                    self._emit_timeout_signal(spec, turn)
                concurrent.futures.wait(pending, timeout=0.05)
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

        # Collect only the futures that completed before the dispatch boundary.
        # Pending futures may still be unwinding; their late events are ignored.
        completed = 0
        failed = 0
        executor_timeouts = 0
        for future in done:
            event = future.result()
            # Ignore late results from actions that were already timed out.
            if (
                event["execution_id"] in cancelled_execution_ids
                and event["signal_type"]
                in (
                    SignalType.ACTION_COMPLETED,
                    SignalType.ACTION_FAILED,
                    SignalType.ACTION_CANCELLED,
                    SignalType.ACTION_TIMEOUT,
                    SignalType.ONGOING_STARTED,
                )
            ):
                continue
            self._signal_bus.emit(
                Signal(
                    type=event["signal_type"],
                    turn=turn,
                    step="execute_action",
                    action_name=event["action_name"],
                    action_input=event["action_input"],
                    execution_id=event["execution_id"],
                    payload=event["payload"],
                )
            )
            if event["signal_type"] == SignalType.ACTION_COMPLETED:
                completed += 1
            elif event["signal_type"] == SignalType.ACTION_FAILED:
                failed += 1
            elif event["signal_type"] == SignalType.ACTION_TIMEOUT:
                executor_timeouts += 1
            elif event["signal_type"] == SignalType.ACTION_CANCELLED:
                failed += 1
            elif event["signal_type"] == SignalType.ONGOING_STARTED:
                completed += 1

        timed_out = len(pending) + executor_timeouts

        # In parallel batch: suppress LOOP_NEXT_TURN from individual actions.
        # When multiple actions run together, their data results need Step 3
        # to update state; skipping Step 3 would lose those results.
        # LOOP_COMPLETE and LOOP_SUSPEND remain valid regardless of batch size.
        if total > 1:
            signals = self._signal_bus.consume()
            filtered = [
                s for s in signals
                if s.type != SignalType.LOOP_NEXT_TURN
            ]
            for s in filtered:
                self._signal_bus.emit(s)

        self._logger.action_result(
            result={
                "total": total,
                "completed": completed,
                "failed": failed,
                "timed_out": timed_out,
            },
            success=(failed == 0 and timed_out == 0),
        )

        return DispatchOutcome(
            total=total,
            completed=completed,
            failed=failed,
            timed_out=timed_out,
        )

    def _resolve_dispatch_timeout(self, specs: list[ActionSpec]) -> float:
        """
        Slowest-decider algorithm: use the maximum individual action timeout
        across the batch, plus a configurable buffer.
        """
        max_timeout = 0.0
        for spec in specs:
            try:
                action_timeout = self._query_action.get_action_timeout(spec.name)
                max_timeout = max(max_timeout, action_timeout)
            except Exception:
                # If we can't resolve the timeout, use the global default
                max_timeout = max(max_timeout, settings.action_timeout)
        return max_timeout + settings.parallel_dispatch_buffer

    def _execute_single(
        self,
        spec: ActionSpec,
        context_provider: ContextProvider,
            run_config: RunConfig,
    ) -> dict[str, Any]:
        """
        Execute a single action and return a structured event dict.

        The caller (dispatch) is responsible for emitting the Signal so that
        late results from timed-out actions can be filtered before they reach
        the SignalBus.
        """
        try:
            run_config.raise_if_terminated()
            result = self._query_action.execute(
                spec.name,
                spec.args,
                context_provider=context_provider,
                run_config=run_config,
            )
            run_config.raise_if_terminated()
            # ONGOING actions report ONGOING_STARTED when their execute()
            # returns (which means "launch completed"). Background ticks
            # are emitted by the action itself via context_provider.emit_signal().
            if spec.mode == ActionMode.ONGOING:
                signal_type = SignalType.ONGOING_STARTED
            else:
                signal_type = SignalType.ACTION_COMPLETED

            return {
                "signal_type": signal_type,
                "action_name": spec.name,
                "action_input": spec.args,
                "execution_id": spec.execution_id,
                "payload": {
                    "target": spec.target,
                    "result": result,
                },
            }

        except BaseException as exc:
            if isinstance(exc, (SystemExit, GeneratorExit)):
                raise
            error_type = type(exc).__name__
            if exc.__cause__:
                error_type = f"{error_type}/{type(exc.__cause__).__name__}"
            if isinstance(exc, ActionTimeoutError):
                signal_type = SignalType.ACTION_TIMEOUT
            elif isinstance(exc, ActionCancelledError):
                signal_type = SignalType.ACTION_CANCELLED
            else:
                signal_type = SignalType.ACTION_FAILED
            return {
                "signal_type": signal_type,
                "action_name": spec.name,
                "action_input": spec.args,
                "execution_id": spec.execution_id,
                "payload": {
                    "target": spec.target,
                    "error": str(exc),
                    "error_type": error_type,
                },
            }

    def _emit_timeout_signal(
        self, spec: ActionSpec, turn: int
    ) -> None:
        """Emit an ACTION_TIMEOUT signal for a timed-out action."""
        self._signal_bus.emit(
            Signal(
                type=SignalType.ACTION_TIMEOUT,
                turn=turn,
                step="execute_action",
                action_name=spec.name,
                action_input=spec.args,
                execution_id=spec.execution_id,
                payload={
                    "target": spec.target,
                    "error": f"Action '{spec.name}' timed out in parallel batch",
                    "error_type": "ActionTimeoutError",
                },
            )
        )
