"""
Todo component for Query State.

Provides TodoItem dataclass and TodoManager for todo list operations.
"""

import re
from dataclasses import dataclass
from datetime import datetime
from enum import IntEnum
from uuid import uuid4

from tinysoul.trap import StateError, TodoAmbiguityError


class TaskStatus(IntEnum):
    """Status for todo items."""

    PENDING = 0
    DONE = 1
    CANCELLED = 2


@dataclass
class TodoItem:
    """A single todo item in the todo_list."""

    id: str
    semantic_key: str
    display_key: str
    description: str
    status: TaskStatus
    created_at: datetime
    completed_at: datetime | None = None


class TodoManager:
    """Manages the todo list for query state."""

    def __init__(self, initial_todos: list[TodoItem] | None = None):
        self._todo_list: list[TodoItem] = list(initial_todos or [])
        # Track per-semantic-key creation count for display_key generation
        self._key_counters: dict[str, int] = {}
        for todo in self._todo_list:
            self._key_counters[todo.semantic_key] = (
                self._key_counters.get(todo.semantic_key, 0) + 1
            )

    @property
    def todo_list(self) -> list[TodoItem]:
        """Return a shallow copy of the todo list."""
        return self._todo_list.copy()

    @staticmethod
    def _normalize_key(key: str) -> str:
        """Normalize semantic key to lowercase snake_case."""
        normalized = key.strip().lower()
        normalized = re.sub(r"[\s\-]+", "_", normalized)
        normalized = re.sub(r"_+", "_", normalized)
        return normalized

    def add(self, description: str, semantic_key: str) -> TodoItem:
        """Add a new todo item."""
        if not semantic_key:
            raise StateError("semantic_key is required and must be a non-empty string")
        semantic_key = self._normalize_key(semantic_key)
        self._key_counters[semantic_key] = self._key_counters.get(semantic_key, 0) + 1
        seq = self._key_counters[semantic_key]
        display_key = f"{semantic_key}-{seq}"
        todo = TodoItem(
            id=uuid4().hex[:8],
            semantic_key=semantic_key,
            display_key=display_key,
            description=description,
            status=TaskStatus.PENDING,
            created_at=datetime.now(),
        )
        self._todo_list.append(todo)
        return todo

    def _resolve_pending(self, lookup_key: str) -> TodoItem | None:
        """
        Resolve a single pending todo by lookup_key.

        Resolution order:
        1. Exact match on display_key.
        2. Exact match on semantic_key — only if exactly one pending todo matches.
        3. If multiple pending todos share the same semantic_key, raise TodoAmbiguityError.
        """
        # Step 1: exact display_key match
        for todo in self._todo_list:
            if todo.display_key == lookup_key and todo.status == TaskStatus.PENDING:
                return todo

        # Step 2: semantic_key match with strict uniqueness check
        candidates = [
            todo
            for todo in self._todo_list
            if todo.semantic_key == lookup_key and todo.status == TaskStatus.PENDING
        ]
        if len(candidates) == 1:
            return candidates[0]
        if len(candidates) > 1:
            raise TodoAmbiguityError(
                f"Ambiguous todo key '{lookup_key}': {len(candidates)} pending todos match. "
                f"Use display_key instead: {[t.display_key for t in candidates]}"
            )
        return None

    def complete(self, lookup_key: str) -> TodoItem | None:
        """Mark a todo as completed."""
        todo = self._resolve_pending(lookup_key)
        if todo is None:
            return None
        todo.status = TaskStatus.DONE
        todo.completed_at = datetime.now()
        return todo

    def cancel(self, lookup_key: str) -> TodoItem | None:
        """
        Cancel a todo item.

        Only pending todos can be cancelled.
        Completed or already cancelled todos cannot be cancelled.
        """
        todo = self._resolve_pending(lookup_key)
        if todo is None:
            return None
        if todo.status in (TaskStatus.DONE, TaskStatus.CANCELLED):
            return None
        todo.status = TaskStatus.CANCELLED
        todo.completed_at = datetime.now()
        return todo

    def get_all(self) -> list[TodoItem]:
        """Get all todo items."""
        return self._todo_list.copy()

    def get_by_status(self, status: TaskStatus | None = None) -> list[TodoItem]:
        """
        Get todo items, optionally filtered by status.

        Args:
            status: Filter by status (PENDING, DONE, CANCELLED)
                   If None, return all todos.
        """
        if status is None:
            return self._todo_list.copy()
        return [todo for todo in self._todo_list if todo.status == status]
