"""Working context state."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from tinysoul.infra.json import JsonObject
from tinysoul.llm.messages import Message, UserMessage

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
class WorkspaceSnapshot:
    """A complete, versioned Workspace manifest projection."""

    revision: int
    resources: tuple[WorkspaceResource, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if (
            isinstance(self.revision, bool)
            or not isinstance(self.revision, int)
            or self.revision < 0
        ):
            raise ContextInvariantError(
                "WorkspaceSnapshot.revision must be a non-negative integer"
            )
        links = tuple(resource.link for resource in self.resources)
        if len(set(links)) != len(links):
            raise ContextInvariantError(
                "WorkspaceSnapshot.resources must contain unique links"
            )


@dataclass(frozen=True)
class WorkingPatch:
    """An explicit working-context change set parsed from a signal payload."""

    set_milestones: tuple[Milestone, ...] = field(default_factory=tuple)
    remove_milestones: tuple[str, ...] = field(default_factory=tuple)
    set_todos: tuple[TodoItem, ...] = field(default_factory=tuple)
    remove_todos: tuple[str, ...] = field(default_factory=tuple)

    def is_empty(self) -> bool:
        return not (
            self.set_milestones
            or self.remove_milestones
            or self.set_todos
            or self.remove_todos
        )


class WorkingContext:
    """Workspace summary plus milestones and todos for the current turn."""

    def __init__(self) -> None:
        self._milestones: dict[str, Milestone] = {}
        self._todos: dict[str, TodoItem] = {}
        self._resources: dict[str, WorkspaceResource] = {}
        self._workspace_revision = -1

    def milestones(self) -> tuple[Milestone, ...]:
        return tuple(self._milestones.values())

    def todos(self) -> tuple[TodoItem, ...]:
        return tuple(self._todos.values())

    def resources(self) -> tuple[WorkspaceResource, ...]:
        return tuple(self._resources.values())

    @property
    def workspace_revision(self) -> int:
        return self._workspace_revision

    def check_patch(self, patch: WorkingPatch) -> str:
        """Return a model-facing problem description, or empty when applicable."""

        milestones = dict(self._milestones)
        todos = dict(self._todos)
        return _apply_patch_to_projection(
            patch,
            milestones=milestones,
            todos=todos,
        )

    def check_patch_sequence(self, patches: tuple[WorkingPatch, ...]) -> tuple[str, ...]:
        """Validate patches against a projected working state."""

        milestones = dict(self._milestones)
        todos = dict(self._todos)
        problems: list[str] = []
        for patch in patches:
            next_milestones = dict(milestones)
            next_todos = dict(todos)
            problem = _apply_patch_to_projection(
                patch,
                milestones=next_milestones,
                todos=next_todos,
            )
            problems.append(problem)
            if not problem:
                milestones = next_milestones
                todos = next_todos
        return tuple(problems)

    def check_workspace_sequence(
        self,
        snapshots: tuple[WorkspaceSnapshot, ...],
    ) -> tuple[str, ...]:
        revision = self._workspace_revision
        resources = dict(self._resources)
        problems: list[str] = []
        for snapshot in snapshots:
            incoming = {resource.link: resource for resource in snapshot.resources}
            problem = ""
            if snapshot.revision < revision:
                problems.append("")
                continue
            elif snapshot.revision == revision and incoming != resources:
                problem = (
                    "Workspace snapshot conflicts with the current revision: "
                    f"{revision}"
                )
            if not problem:
                revision = snapshot.revision
                resources = incoming
            problems.append(problem)
        return tuple(problems)

    def apply_workspace_snapshot(self, snapshot: WorkspaceSnapshot) -> None:
        if snapshot.revision < self._workspace_revision:
            return
        problem = self.check_workspace_sequence((snapshot,))[0]
        if problem:
            raise ContextInvariantError(
                f"Workspace snapshot is not applicable: {problem}"
            )
        self._resources = {
            resource.link: resource for resource in snapshot.resources
        }
        self._workspace_revision = snapshot.revision

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
            "workspace_revision": self._workspace_revision,
        }

    def model_projection(self) -> JsonObject:
        """Return the business state exposed in model Context."""

        value = self.to_json()
        value.pop("workspace_revision")
        return value

    def render_messages(self) -> tuple[Message, ...]:
        return (
            UserMessage.from_json(
                self.model_projection(),
                label="working",
            ),
        )


def _apply_patch_to_projection(
    patch: WorkingPatch,
    *,
    milestones: dict[str, Milestone],
    todos: dict[str, TodoItem],
) -> str:
    if patch.is_empty():
        return "Working patch contains no operations"
    problem = _operation_problem(
        set_keys=tuple(item.key for item in patch.set_milestones),
        remove_keys=patch.remove_milestones,
        label="milestone",
    )
    if problem:
        return problem
    problem = _operation_problem(
        set_keys=tuple(item.key for item in patch.set_todos),
        remove_keys=patch.remove_todos,
        label="todo",
    )
    if problem:
        return problem
    for key in patch.remove_milestones:
        if key not in milestones:
            return f"Unknown milestone key: {key}"
        del milestones[key]
    for key in patch.remove_todos:
        if key not in todos:
            return f"Unknown todo key: {key}"
        del todos[key]
    for milestone in patch.set_milestones:
        milestones[milestone.key] = milestone
    for todo in patch.set_todos:
        todos[todo.key] = todo
    return ""


def _operation_problem(
    *,
    set_keys: tuple[str, ...],
    remove_keys: tuple[str, ...],
    label: str,
) -> str:
    duplicate = _first_duplicate(set_keys)
    if duplicate:
        return f"Working patch contains duplicate {label} set key: {duplicate}"
    duplicate = _first_duplicate(remove_keys)
    if duplicate:
        return f"Working patch contains duplicate {label} remove key: {duplicate}"
    conflict = sorted(set(set_keys) & set(remove_keys))
    if conflict:
        return f"Working patch cannot set and remove the same {label}: {conflict[0]}"
    return ""


def _first_duplicate(values: tuple[str, ...]) -> str:
    seen: set[str] = set()
    for value in values:
        if value in seen:
            return value
        seen.add(value)
    return ""
