"""Working context state."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from tinysoul.infra.json import JsonObject
from tinysoul.llm.messages import Message, SystemMessage

from .errors import ContextInvariantError


class TodoStatus(StrEnum):
    """Todo item lifecycle status."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class Milestone:
    """A named register storing an important state or conclusion."""

    key: str
    content: str

    def __post_init__(self) -> None:
        if not self.key:
            raise ContextInvariantError("Milestone.key must be non-empty")
        if not self.content:
            raise ContextInvariantError("Milestone.content must be non-empty")


@dataclass(frozen=True)
class TodoItem:
    """A todo item tracked in the working context."""

    key: str
    content: str
    status: TodoStatus = TodoStatus.PENDING

    def __post_init__(self) -> None:
        if not self.key:
            raise ContextInvariantError("TodoItem.key must be non-empty")
        if not self.content:
            raise ContextInvariantError("TodoItem.content must be non-empty")
        if not isinstance(self.status, TodoStatus):
            raise ContextInvariantError("TodoItem.status must be a TodoStatus")


@dataclass(frozen=True)
class WorkspaceResource:
    """A workspace resource handle with a short summary."""

    link: str
    summary: str

    def __post_init__(self) -> None:
        if not self.link:
            raise ContextInvariantError("WorkspaceResource.link must be non-empty")
        if not self.summary:
            raise ContextInvariantError("WorkspaceResource.summary must be non-empty")


@dataclass(frozen=True)
class WorkingPatch:
    """An explicit working-context change set parsed from a signal payload."""

    set_milestones: tuple[Milestone, ...] = field(default_factory=tuple)
    remove_milestones: tuple[str, ...] = field(default_factory=tuple)
    set_todos: tuple[TodoItem, ...] = field(default_factory=tuple)
    remove_todos: tuple[str, ...] = field(default_factory=tuple)
    set_resources: tuple[WorkspaceResource, ...] = field(default_factory=tuple)
    remove_resources: tuple[str, ...] = field(default_factory=tuple)

    def is_empty(self) -> bool:
        return not (
            self.set_milestones
            or self.remove_milestones
            or self.set_todos
            or self.remove_todos
            or self.set_resources
            or self.remove_resources
        )


class WorkingContext:
    """Workspace summary plus milestones and todos for the current turn."""

    def __init__(self) -> None:
        self._milestones: dict[str, Milestone] = {}
        self._todos: dict[str, TodoItem] = {}
        self._resources: dict[str, WorkspaceResource] = {}

    def milestones(self) -> tuple[Milestone, ...]:
        return tuple(self._milestones.values())

    def todos(self) -> tuple[TodoItem, ...]:
        return tuple(self._todos.values())

    def resources(self) -> tuple[WorkspaceResource, ...]:
        return tuple(self._resources.values())

    def check_patch(self, patch: WorkingPatch) -> str:
        """Return a model-facing problem description, or empty when applicable."""

        for key in patch.remove_milestones:
            if key not in self._milestones:
                return f"Unknown milestone key: {key}"
        for key in patch.remove_todos:
            if key not in self._todos:
                return f"Unknown todo key: {key}"
        for link in patch.remove_resources:
            if link not in self._resources:
                return f"Unknown workspace resource link: {link}"
        if patch.is_empty():
            return "Working patch contains no operations"
        return ""

    def apply_patch(self, patch: WorkingPatch) -> None:
        problem = self.check_patch(patch)
        if problem:
            raise ContextInvariantError(f"Working patch is not applicable: {problem}")
        for milestone in patch.set_milestones:
            self._milestones[milestone.key] = milestone
        for key in patch.remove_milestones:
            del self._milestones[key]
        for todo in patch.set_todos:
            self._todos[todo.key] = todo
        for key in patch.remove_todos:
            del self._todos[key]
        for resource in patch.set_resources:
            self._resources[resource.link] = resource
        for link in patch.remove_resources:
            del self._resources[link]

    def to_json(self) -> JsonObject:
        return {
            "milestones": [
                {"key": item.key, "content": item.content}
                for item in self._milestones.values()
            ],
            "todos": [
                {"key": item.key, "content": item.content, "status": item.status.value}
                for item in self._todos.values()
            ],
            "workspace_resources": [
                {"link": item.link, "summary": item.summary}
                for item in self._resources.values()
            ],
        }

    def render_messages(self) -> tuple[Message, ...]:
        return (SystemMessage.from_json(self.to_json(), label="working"),)
