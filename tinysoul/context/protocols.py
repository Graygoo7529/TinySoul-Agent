"""
ContextProvider protocol for TinySoul.

Defines the interface for objects that provide runtime context.
Implementations pass object references (not serialized copies);
serialization is triggered by consumers (e.g. PromptBuilder) when needed.
"""

from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from tinysoul.action.framework.run_config import TerminationReason
    from tinysoul.context.ongoing import OngoingControl
    from tinysoul.action.framework.manager import QueryAction
    from tinysoul.trap.signal import Signal
    from tinysoul.loop.query import QueryEvents, QueryEvent


class ContextProvider(Protocol):
    """
    Protocol for objects that provide runtime context to PromptBuilder and actions.

    Implementors must expose shared context fields as native Python data
    structures (dict/list). Serialization to JSON strings happens only at
    the Prompt boundary (LLMPrompt.serialize()).
    """

    @property
    def query_events(self) -> "QueryEvents":
        """The query event stream (inputs and agent inquiries within this query)."""
        ...

    def get_loop_level_system(self) -> list[dict[str, str]]:
        """Return loop-level system messages for internal LLM actions."""
        ...

    def append_inquiry(self, content: str) -> "QueryEvent":
        """Append an agent inquiry to the query event stream."""
        ...

    def append_response(self, content: str, ask_context: str) -> "QueryEvent":
        """Append a response to an agent inquiry."""
        ...

    @property
    def loop_target(self) -> str:
        """The target goal for the current loop."""
        ...

    @property
    def current_state(self) -> Any:
        """The current QueryState object (not a JSON string)."""
        ...

    @property
    def workspace(self) -> Any | None:
        """The Workspace object (not a JSON string), or None."""
        ...

    @property
    def current_turn(self) -> int:
        """The current turn number in the query loop."""
        ...

    @property
    def query_action(self) -> "QueryAction":
        """The QueryAction manager for the current query loop."""
        ...

    @property
    def client(self) -> Any | None:
        """The injected LLM client for the current query loop, or None."""
        ...

    def get_current_state(self) -> dict:
        """Return current state as a native dict for prompt construction."""
        ...

    def get_workspace(self) -> dict:
        """Return workspace data as a native dict for prompt construction."""
        ...

    def emit_signal(self, signal: "Signal") -> None:
        """Emit an execution signal to the signal bus.

        Used by actions (especially ONGOING actions running in background
        threads) to report results without direct state mutation.
        """
        ...

    def register_ongoing_control(self, control: "OngoingControl") -> None:
        """Register runtime control for an ONGOING action execution."""
        ...

    def unregister_ongoing_control(self, execution_id: str) -> Any | None:
        """Remove runtime control for an ONGOING action execution."""
        ...

    def request_ongoing_termination(
        self,
        execution_id: str,
        reason: "TerminationReason",
    ) -> bool:
        """Request termination for an ONGOING action execution."""
        ...

    def request_all_ongoing_termination(
        self,
        reason: "TerminationReason",
    ) -> int:
        """Request termination for all ONGOING action executions."""
        ...
