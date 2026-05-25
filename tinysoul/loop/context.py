"""
Context Manager for Query Loop.

Provides runtime state data to PromptBuilder and LLM tasks.
Acts as a pure data provider: it holds object references and serializes
on demand, but does NOT assemble prompt strings.

Implements the ContextProvider protocol from tinysoul.context.protocols.
"""

from typing import Any

from tinysoul.action.framework.manager import QueryAction
from tinysoul.action.framework.run_config import TerminationReason
from tinysoul.context.ongoing import OngoingControl, OngoingControlRegistry
from tinysoul.trap.signal import Signal, SignalBus
from tinysoul.context.state import (
    ActionRecord,
    LoopErrorItem,
    QueryState,
    TaskStatus,
    TodoItem,
    build_feedback_errors,
)
from tinysoul.context.workspace import Workspace
from tinysoul.infra.config import settings
from tinysoul.loop.query import QueryEvents, QueryEventRole, QueryEvent


class QueryContext:
    """
    Manages runtime context for the Agent Query Loop.

    Responsibilities:
    - Maintain references to query_state, query_action, workspace
    - Serialize current_state, workspace, and action records on demand
    - Track current turn number
    - Manage the user query history (user inputs and agent questions)

    Does NOT:
    - Build prompt strings (that's PromptBuilder's job)
    - Call the AI model (that's AITask's job)
    """

    def __init__(
        self,
        query_events: str | QueryEvents,
        loop_target: str,
        query_state: QueryState,
        query_action: QueryAction | None,
        workspace: Workspace | None = None,
        signal_bus: SignalBus | None = None,
        client: Any | None = None,
        loop_level_system_messages: list[dict[str, str]] | None = None,
    ):
        if isinstance(query_events, str):
            self._query_events = QueryEvents(query_events)
        else:
            self._query_events = query_events
        self.loop_target = loop_target
        self.query_state = query_state
        self.query_action = query_action
        self._workspace = workspace
        self._signal_bus = signal_bus
        self._client = client
        self._loop_level_system_messages = list(loop_level_system_messages or [])
        self._ongoing_controls = OngoingControlRegistry()
        self.current_turn = 0

    # =======================================================================
    # ContextProvider properties: expose object references
    # =======================================================================

    @property
    def current_state(self) -> Any:
        """Return the QueryState object (not serialized)."""
        return self.query_state

    @property
    def workspace(self) -> Workspace | None:
        """Return the Workspace object (not serialized)."""
        return self._workspace

    # =======================================================================
    # Query Event Stream
    # =======================================================================

    @property
    def query_events(self) -> QueryEvents:
        """Return the query event stream."""
        return self._query_events

    def append_inquiry(self, content: str) -> QueryEvent:
        """Append an agent inquiry to the query event stream."""
        return self._query_events.append_inquiry(content, turn=self.current_turn)

    def append_response(self, content: str, ask_context: str) -> QueryEvent:
        """Append a response to an agent inquiry."""
        return self._query_events.append_response(
            content, ask_context, turn=self.current_turn
        )

    def append_append(self, content: str, turn: int = 0) -> QueryEvent:
        """Append additional input mid-query."""
        effective_turn = turn if turn else self.current_turn
        return self._query_events.append_append(content, turn=effective_turn)

    def get_query_events(self) -> list[dict]:
        """Serialize the query event stream for prompt injection."""
        return self._query_events.to_dict_list()

    @property
    def client(self) -> Any | None:
        """Return the injected LLM client for the current query loop."""
        return self._client

    def get_loop_level_system(self) -> list[dict[str, str]]:
        """Return loop-level system messages for internal LLM actions."""
        return list(self._loop_level_system_messages)

    # =======================================================================
    # Serialization helpers (called by PromptBuilder on demand)
    # =======================================================================

    @staticmethod
    def _status_to_text(todo_status: TaskStatus) -> str:
        return {
            TaskStatus.PENDING: "PENDING",
            TaskStatus.DONE: "DONE",
            TaskStatus.CANCELLED: "CANCELLED",
        }.get(todo_status, str(todo_status.value))

    def _build_todo_list_for_context(self) -> list[dict[str, Any]]:
        """Build todo list for LLM context, exposing key based on conflict status."""
        from collections import Counter

        todos = self.query_state.get_todo_list()
        all_counts = Counter(t.semantic_key for t in todos)
        return [self._serialize_todo(t, all_counts[t.semantic_key] > 1) for t in todos]

    def _serialize_todo(self, todo: TodoItem, has_conflict: bool) -> dict[str, Any]:
        return {
            "key": todo.display_key if has_conflict else todo.semantic_key,
            "description": todo.description,
            "status": self._status_to_text(todo.status),
            "created_at": todo.created_at.isoformat() if todo.created_at else None,
            "completed_at": todo.completed_at.isoformat()
            if todo.completed_at
            else None,
        }

    def _serialize_action_record(
        self,
        record: ActionRecord,
        turn: int | None = None,
        include_timestamp: bool = True,
        include_status: bool = False,
    ) -> dict[str, Any]:
        result: dict[str, Any] = {
            "action_name": record.action_name,
            "action_target": record.action_target,
            "action_input": record.action_input,
            "action_result": record.action_result,
        }
        if record.execution_id:
            result["execution_id"] = record.execution_id
        if include_timestamp:
            result["timestamp"] = (
                record.timestamp.isoformat() if record.timestamp else None
            )
        if turn is not None:
            result["turn"] = turn
        if include_status:
            result["status"] = record.status
        return result

    def _serialize_loop_error(self, item: LoopErrorItem) -> dict[str, Any]:
        return {
            "turn": item.turn,
            "step": item.step,
            "error_type": item.error_type,
            "message": item.message,
            "timestamp": item.timestamp.isoformat() if item.timestamp else None,
        }

    def _build_action_record_list(self, compact: bool = True) -> list[dict[str, Any]]:
        """Build action record list for LLM context.

        When compact=True, recent records (up to compact_max_records) are shown
        in full detail; older records are summarized to action_name + turn + status.
        """
        records = self.query_state.get_action_record_list()
        max_records = settings.compact_max_records
        if not compact or len(records) <= max_records:
            return [
                self._serialize_action_record(r, r.turn, include_timestamp=False)
                for r in records
            ]

        result: list[dict[str, Any]] = []
        # Older records: summarized
        for r in records[:-max_records]:
            result.append({
                "action_name": r.action_name,
                "turn": r.turn,
                "status": r.status,
                **({"execution_id": r.execution_id} if r.execution_id else {}),
            })
        # Recent records: full detail
        for r in records[-max_records:]:
            result.append(
                self._serialize_action_record(r, r.turn, include_timestamp=False)
            )
        return result

    # =======================================================================
    # Public data providers (used by PromptBuilder and tasks)
    # =======================================================================

    def _build_feedback_errors(self, compact: bool = True) -> list[dict[str, Any]]:
        """Extract LLM-facing feedback views from loop_error_list.

        When compact=True, recent errors (up to compact_max_errors) are shown
        in full detail; older errors are summarized to turn + error_type.
        """
        errors = build_feedback_errors(self.query_state.get_loop_error_list())
        max_errors = settings.compact_max_errors
        if not compact or len(errors) <= max_errors:
            return errors

        result: list[dict[str, Any]] = []
        for e in errors[:-max_errors]:
            result.append({
                "turn": e["turn"],
                "error_type": e["error_type"],
            })
        result.extend(errors[-max_errors:])
        return result

    def get_current_state(self, compact: bool = True) -> dict:
        """Build the current_state context as a native dict.

        Args:
            compact: If True, action_record_list and feedback_error_list are
                compacted to control prompt size. Recent items keep full detail;
                older items are summarized. Use compact=False for debug/export.
        """
        return {
            "action_record_list": self._build_action_record_list(compact=compact),
            "feedback_error_list": self._build_feedback_errors(compact=compact),
            "todo_list": self._build_todo_list_for_context(),
            "milestone_list": self.query_state.get_milestones(),
            "ongoing_action_list": self.query_state.get_ongoing_action_list(),
        }

    def get_workspace(self, compact: bool = True) -> dict:
        """Return workspace as a native dict (or empty dict if none).

        Args:
            compact: If True, resource change_logs are truncated to the most
                recent entries (compact_max_logs). Use compact=False for debug.
        """
        if self._workspace is None:
            return {}
        return self._workspace.to_dict(
            compact=compact, max_logs=settings.compact_max_logs
        )

    def peek_new_action_records(self) -> list[dict[str, Any]]:
        """
        Peek unread action records and return them as serialized dicts.

        Does NOT mutate state: records remain unread until ack_action_records().
        """
        unread_records = self.query_state.peek_new_action_records()
        return [
            self._serialize_action_record(r, r.turn) for r in unread_records
        ]

    def ack_action_records(self) -> None:
        """Mark all unread action records as read. Call after successful state update."""
        self.query_state.ack_action_records()

    def emit_signal(self, signal: Signal) -> None:
        """Emit an execution signal to the signal bus.

        Used by actions (especially ONGOING actions) to report results
        from background threads without direct state mutation.
        """
        if self._signal_bus is not None:
            self._signal_bus.emit(signal)

    def register_ongoing_control(self, control: OngoingControl) -> None:
        """Register runtime control for an ONGOING execution."""
        self._ongoing_controls.register(control)

    def unregister_ongoing_control(self, execution_id: str) -> OngoingControl | None:
        """Remove runtime control for an ONGOING execution."""
        return self._ongoing_controls.unregister(execution_id)

    def request_ongoing_termination(
        self,
        execution_id: str,
        reason: TerminationReason = TerminationReason.USER_CANCEL,
    ) -> bool:
        """Request termination for an ONGOING execution by execution_id."""
        return self._ongoing_controls.request_termination(execution_id, reason)

    def request_all_ongoing_termination(
        self,
        reason: TerminationReason = TerminationReason.SHUTDOWN,
    ) -> int:
        """Request termination for all registered ONGOING executions."""
        return self._ongoing_controls.request_all_termination(reason)
