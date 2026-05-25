"""Data factories for building complex test objects concisely."""

from __future__ import annotations

from tinysoul.action.framework.run_config import RunConfig
from tinysoul.context.state import QueryState
from tinysoul.context.workspace import (
    ResourceDesc,
    ResourceItem,
    ResourceType,
    Workspace,
)


class QueryStateBuilder:
    """Build a QueryState with chained method calls."""

    def __init__(self) -> None:
        self._state = QueryState()

    def with_todo(self, description: str, key: str) -> "QueryStateBuilder":
        self._state.add_todo(description=description, todo_id=key)
        return self

    def with_completed_todo(self, description: str, key: str) -> "QueryStateBuilder":
        self._state.add_todo(description=description, todo_id=key)
        self._state.complete_todo(key)
        return self

    def with_cancelled_todo(self, description: str, key: str) -> "QueryStateBuilder":
        self._state.add_todo(description=description, todo_id=key)
        self._state.cancel_todo(key)
        return self

    def with_milestone(self, text: str) -> "QueryStateBuilder":
        self._state.add_milestone(text)
        return self

    def with_action_record(
        self,
        action_name: str,
        action_target: str = "",
        action_input: dict | None = None,
        action_result: dict | None = None,
        turn: int = 1,
    ) -> "QueryStateBuilder":
        self._state.record_action(
            action_name=action_name,
            action_target=action_target,
            action_input=action_input or {},
            action_result=action_result or {},
            turn=turn,
        )
        return self

    def with_loop_error(
        self,
        turn: int,
        step: str,
        error_type: str,
        message: str,
        auto_handled: bool = False,
    ) -> "QueryStateBuilder":
        self._state.add_loop_error(
            turn=turn,
            step=step,
            error_type=error_type,
            message=message,
            auto_handled=auto_handled,
        )
        return self

    def build(self) -> QueryState:
        return self._state


def run_config(
    action_name: str = "test",
    *,
    turn: int = 1,
    timeout: float | None = 30.0,
    llm_timeout: float | None = None,
    api_timeout: float | None = None,
) -> RunConfig:
    """Build a per-execution RunConfig for direct action/executor tests."""
    return RunConfig.create(
        action_name=action_name,
        turn=turn,
        timeout=timeout,
        llm_timeout=llm_timeout,
        api_timeout=api_timeout,
    )


class WorkspaceBuilder:
    """Build a Workspace with files in a temporary directory."""

    def __init__(self, tmp_path: str) -> None:
        self._location = str(tmp_path)
        self._resources: list[ResourceItem] = []

    def with_file(
        self,
        relative_path: str,
        content: str,
        resource_type: ResourceType = ResourceType.MARKDOWN,
    ) -> "WorkspaceBuilder":
        from pathlib import Path

        target = Path(self._location) / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        self._resources.append(
            ResourceItem(
                resource_name=target.name,
                resource_type=resource_type,
                resource_access=relative_path.replace("\\", "/"),
            )
        )
        return self

    def build(self) -> Workspace:
        ws = Workspace(
            workspace_location=self._location,
            resources=list(self._resources),
        )
        return ws
