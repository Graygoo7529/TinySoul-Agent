"""
ActionRecord component for Query State.

Provides ActionRecord dataclass and ActionRecordManager for action history.
"""

from dataclasses import dataclass
from datetime import datetime


@dataclass
class ActionRecord:
    """
    A record of executed action in action_record_list.

    Each action execution produces one ActionRecord with a single result.
    For ongoing actions with multiple results, multiple ActionRecords are created.
    """

    action_name: str
    action_target: str
    action_input: dict
    action_result: dict
    turn: int
    timestamp: datetime
    execution_id: str = ""
    read: bool = False  # Unread by default
    status: str = "success"  # "success" | "failed" | "timeout" | "cancelled"


@dataclass
class OngoingActionRecord:
    """A currently running ONGOING action execution."""

    execution_id: str
    action_name: str
    turn: int
    status: str = "running"
    started_at: datetime | None = None


class ActionRecordManager:
    """Manages action records and ongoing actions."""

    def __init__(self):
        self._action_record_list: list[ActionRecord] = []
        self._ongoing_action_list: list[OngoingActionRecord] = []

    @property
    def action_record_list(self) -> list[ActionRecord]:
        """Return a copy of the action record list."""
        return self._action_record_list.copy()

    @property
    def ongoing_action_list(self) -> list[dict]:
        """Return a copy of the ongoing action list."""
        return [self._ongoing_to_dict(item) for item in self._ongoing_action_list]

    def record(
        self,
        action_name: str,
        action_target: str,
        action_input: dict,
        action_result: dict,
        turn: int,
        status: str = "success",
        execution_id: str = "",
    ) -> ActionRecord:
        """
        Record an executed action result.

        For both ongoing and single-run actions, each result produces
        a new ActionRecord. For ongoing actions with multiple results,
        call this method multiple times.
        """
        record = ActionRecord(
            action_name=action_name,
            action_target=action_target,
            action_input=action_input,
            action_result=action_result,
            turn=turn,
            timestamp=datetime.now(),
            execution_id=execution_id,
            status=status,
        )

        # Add to action_record_list
        self._action_record_list.append(record)

        return record

    def get_all(self) -> list[ActionRecord]:
        """Get all action records."""
        return self._action_record_list.copy()

    def peek_unread(self) -> list[ActionRecord]:
        """
        Get all unread action records without marking them as read.

        Returns:
            List of ActionRecord where read=False
        """
        return [record for record in self._action_record_list if not record.read]

    def mark_all_read(self) -> None:
        """Mark all unread action records as read."""
        for record in self._action_record_list:
            if not record.read:
                record.read = True

    def add_ongoing(
        self,
        execution_id: str,
        action_name: str,
        turn: int,
        status: str = "running",
    ) -> OngoingActionRecord:
        """Add or replace an ongoing action execution."""
        existing = self.get_ongoing_record(execution_id)
        if existing is not None:
            existing.action_name = action_name
            existing.turn = turn
            existing.status = status
            return existing

        record = OngoingActionRecord(
            execution_id=execution_id,
            action_name=action_name,
            turn=turn,
            status=status,
            started_at=datetime.now(),
        )
        self._ongoing_action_list.append(record)
        return record

    def remove_ongoing(self, execution_id: str) -> OngoingActionRecord | None:
        """Remove an ongoing action execution by execution_id."""
        for idx, item in enumerate(self._ongoing_action_list):
            if item.execution_id == execution_id:
                return self._ongoing_action_list.pop(idx)
        return None

    def get_ongoing(self) -> list[dict]:
        """Get currently running action executions."""
        return [self._ongoing_to_dict(item) for item in self._ongoing_action_list]

    def get_ongoing_record(self, execution_id: str) -> OngoingActionRecord | None:
        for item in self._ongoing_action_list:
            if item.execution_id == execution_id:
                return item
        return None

    @staticmethod
    def _ongoing_to_dict(item: OngoingActionRecord) -> dict:
        return {
            "execution_id": item.execution_id,
            "action_name": item.action_name,
            "turn": item.turn,
            "status": item.status,
            "started_at": item.started_at.isoformat() if item.started_at else None,
        }
