"""
Query event model for TinySoul Query Loop.

Provides structured representation of the events within a single query
(a single loop execution) — initial inputs, append inputs, agent inquiries,
user responses, and future internal triggers.
This is NOT the full loop execution history (which is action_record_list).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class QueryEventRole(StrEnum):
    """Role of an event in the query's event stream."""

    INITIAL = "initial"
    """The original input that started the query."""

    APPEND = "append"
    """Additional input provided mid-query (rare)."""

    RESPONSE = "response"
    """Answer to an agent inquiry."""

    INQUIRY = "inquiry"
    """Question asked by the agent (via ask_user action)."""


@dataclass
class QueryEvent:
    """
    A single event in the query's event stream.

    QueryEvents is a chronologically-ordered list of QueryEvent,
    capturing all inputs and agent inquiries within the current query.
    It does NOT include action execution results or LLM reasoning steps.
    """

    role: QueryEventRole
    content: str
    turn: int = 0
    timestamp: datetime = field(default_factory=datetime.now)
    ask_context: str | None = None
    """When role is RESPONSE, the question this answers (the preceding INQUIRY content)."""

    def to_dict(self) -> dict:
        """Serialize to dict for prompt injection."""
        result: dict = {
            "role": self.role.value,
            "content": self.content,
        }
        if self.turn:
            result["turn"] = self.turn
        if self.ask_context:
            result["ask_context"] = self.ask_context
        return result


class QueryEvents:
    """
    Mutable container for the query's event stream.

    Replaces the plain string initial_query with a structured list that
    preserves turn boundaries and event roles.

    Note: This captures only query inputs and agent inquiries. The full
    loop execution history is available via action_record_list.
    """

    def __init__(self, initial_query: str = ""):
        self._items: list[QueryEvent] = []
        if initial_query:
            self._items.append(
                QueryEvent(
                    role=QueryEventRole.INITIAL,
                    content=initial_query,
                    turn=0,
                )
            )

    # ------------------------------------------------------------------
    # Mutation operations
    # ------------------------------------------------------------------

    def append_append(self, content: str, turn: int = 0) -> QueryEvent:
        """Append additional input mid-query."""
        item = QueryEvent(
            role=QueryEventRole.APPEND,
            content=content,
            turn=turn,
        )
        self._items.append(item)
        return item

    def append_inquiry(self, content: str, turn: int = 0) -> QueryEvent:
        """Append an agent inquiry (triggered by ask_user action)."""
        item = QueryEvent(
            role=QueryEventRole.INQUIRY,
            content=content,
            turn=turn,
        )
        self._items.append(item)
        return item

    def append_response(
        self, content: str, ask_context: str, turn: int = 0
    ) -> QueryEvent:
        """
        Append a response to an agent inquiry.

        Args:
            content: The response text.
            ask_context: The question being answered (the INQUIRY content).
            turn: Current turn number.
        """
        item = QueryEvent(
            role=QueryEventRole.RESPONSE,
            content=content,
            turn=turn,
            ask_context=ask_context,
        )
        self._items.append(item)
        return item

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    @property
    def items(self) -> list[QueryEvent]:
        """Return the query events (immutable view)."""
        return list(self._items)

    def to_dict_list(self) -> list[dict]:
        """Serialize query events to a list of dicts for prompt injection."""
        return [item.to_dict() for item in self._items]

    def __len__(self) -> int:
        return len(self._items)

    def __iter__(self):
        return iter(self._items)

    def __getitem__(self, index: int) -> QueryEvent:
        return self._items[index]

    def __repr__(self) -> str:
        return f"QueryEvents({len(self._items)} items)"
