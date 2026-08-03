from __future__ import annotations

import pytest

from tinysoul.action import (
    ActionEngineBuilder,
    ActionResult,
    builtin_action_catalog_root,
)
from tinysoul.action.core.loader import ActionCatalogLoader
from tinysoul.loop.maintenance import MaintenanceCompletionDetector
from tinysoul.maintenance.actions import (
    COMMON_MAINTENANCE_READ_ACTIONS,
    maintenance_action_view,
    user_action_view,
)
from tinysoul.maintenance.errors import MaintenanceContractError
from tinysoul.maintenance.home import HOME_MAINTENANCE_ACTIONS
from tinysoul.maintenance.memory import MEMORY_MAINTENANCE_ACTIONS
from tests.action_helpers import FunctionActionExecutor


def test_turn_action_views_reuse_read_actions_and_isolate_task_actions() -> None:
    with builtin_action_catalog_root() as root:
        catalog = ActionCatalogLoader().load(root)
        builder = ActionEngineBuilder(root)
        for handler in sorted({item.backend.handler for item in catalog.actions()}):
            builder.register_executor(handler, FunctionActionExecutor(_stub))
        action = builder.build()

    user_names = _names(user_action_view(action))
    home_names = _names(maintenance_action_view(action, kind="home"))
    memory_names = _names(maintenance_action_view(action, kind="memory"))

    assert "core.answer" in user_names
    assert not any(name.startswith("maintenance.") for name in user_names)
    assert home_names == set(COMMON_MAINTENANCE_READ_ACTIONS) | set(
        HOME_MAINTENANCE_ACTIONS
    )
    assert memory_names == set(COMMON_MAINTENANCE_READ_ACTIONS) | set(
        MEMORY_MAINTENANCE_ACTIONS
    )
    assert "core.answer" not in home_names | memory_names
    assert "maintenance.memory.consolidate" not in home_names
    assert "maintenance.home.accept" not in memory_names


def test_action_builder_can_construct_an_exact_maintenance_catalog() -> None:
    selected = (*COMMON_MAINTENANCE_READ_ACTIONS, *HOME_MAINTENANCE_ACTIONS)
    with builtin_action_catalog_root() as root:
        catalog = ActionCatalogLoader().load(root)
        builder = ActionEngineBuilder(root).include_actions(*selected)
        handlers = {
            item.backend.handler
            for item in catalog.actions()
            if item.name in selected
        }
        for handler in handlers:
            builder.register_executor(handler, FunctionActionExecutor(_stub))
        action = builder.build()

    assert _names(action) == set(selected)


def test_maintenance_action_view_rejects_missing_common_inspect_actions() -> None:
    with builtin_action_catalog_root() as root:
        catalog = ActionCatalogLoader().load(root)
        builder = ActionEngineBuilder(root).include_actions(*HOME_MAINTENANCE_ACTIONS)
        handlers = {
            item.backend.handler
            for item in catalog.actions()
            if item.name in HOME_MAINTENANCE_ACTIONS
        }
        for handler in handlers:
            builder.register_executor(handler, FunctionActionExecutor(_stub))
        action = builder.build()

    with pytest.raises(MaintenanceContractError, match="core.context.inspect"):
        maintenance_action_view(action, kind="home")


def test_maintenance_completion_requires_owner_completion_action() -> None:
    unrelated = ActionResult.success(
        call_id="call_unrelated",
        invoke_id="invoke",
        batch_id="batch",
        action_name="maintenance.home.list",
        sequence=1,
        domain="maintenance",
        payload={"items": []},
    )
    completed = ActionResult.success(
        call_id="call_completed",
        invoke_id="invoke",
        batch_id="batch",
        action_name="maintenance.complete",
        sequence=1,
        domain="maintenance",
        payload={"completed": True, "task": "home"},
    )

    detector = MaintenanceCompletionDetector()
    assert detector.detect((unrelated,)) is None
    assert detector.detect((completed,)) == {
        "kind": "maintenance",
        "result_id": completed.result_id,
        "task": "home",
    }


def _names(action) -> set[str]:
    return {name for _domain, name in action.action_identifiers()}


def _stub(execution, context):
    del context
    return {"action": execution.call.action_name}
