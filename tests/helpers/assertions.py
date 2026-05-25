"""Domain-specific assertion helpers for TinySoul tests."""

from __future__ import annotations

from tinysoul.context.state.action_record import ActionRecord
from tinysoul.context.state import TaskStatus
from tinysoul.context.state import TodoItem


def assert_todo_status(
    todo: TodoItem, status: TaskStatus, *, key: str | None = None, description: str | None = None
) -> None:
    assert todo.status == status, f"Expected status {status.name}, got {todo.status.name}"
    if key is not None:
        assert todo.semantic_key == key, f"Expected key {key!r}, got {todo.semantic_key!r}"
    if description is not None:
        assert todo.description == description, (
            f"Expected description {description!r}, got {todo.description!r}"
        )


def assert_action_record(
    record: ActionRecord,
    *,
    action_name: str | None = None,
    turn: int | None = None,
    read: bool | None = None,
) -> None:
    if action_name is not None:
        assert record.action_name == action_name
    if turn is not None:
        assert record.turn == turn
    if read is not None:
        assert record.read is read
