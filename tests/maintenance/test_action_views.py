from __future__ import annotations

from dataclasses import replace

from tinysoul.action import (
    ActionCatalog,
    ActionEngineBuilder,
    builtin_action_catalog_root,
)
from tinysoul.action.core.loader import ActionCatalogLoader
from tinysoul.maintenance.actions import COMMON_MAINTENANCE_READ_ACTIONS
from tinysoul.maintenance.home import HOME_MAINTENANCE_ACTIONS
from tinysoul.maintenance.memory import MEMORY_MAINTENANCE_ACTIONS
from tinysoul.maintenance.resources import maintenance_action_catalog_root
from tinysoul.maintenance.turn import MaintenanceCompletionDetector
from tinysoul.action import ActionResult
from tests.action_helpers import FunctionActionExecutor


def test_user_catalog_physically_excludes_maintenance_actions() -> None:
    with builtin_action_catalog_root() as root:
        catalog = ActionCatalogLoader().load(root)

    names = {item.name for item in catalog.actions()}
    assert "core.answer" in names
    assert not any(name.startswith("maintenance.") for name in names)
    assert all(domain.name != "maintenance" for domain in catalog.domains())


def test_exact_maintenance_catalogs_reuse_common_reads_and_isolate_tasks() -> None:
    home = _build_exact((*COMMON_MAINTENANCE_READ_ACTIONS, *HOME_MAINTENANCE_ACTIONS))
    memory = _build_exact(
        (*COMMON_MAINTENANCE_READ_ACTIONS, *MEMORY_MAINTENANCE_ACTIONS)
    )

    home_names = _names(home)
    memory_names = _names(memory)
    assert home_names == set(COMMON_MAINTENANCE_READ_ACTIONS) | set(
        HOME_MAINTENANCE_ACTIONS
    )
    assert memory_names == set(COMMON_MAINTENANCE_READ_ACTIONS) | set(
        MEMORY_MAINTENANCE_ACTIONS
    )
    assert "core.answer" not in home_names | memory_names
    assert "maintenance.memory.consolidate" not in home_names
    assert "maintenance.home.accept" not in memory_names


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


def test_maintenance_exact_view_honors_shared_project_action_policy() -> None:
    selected = (*COMMON_MAINTENANCE_READ_ACTIONS, *HOME_MAINTENANCE_ACTIONS)

    home = _build_exact(selected, disabled_actions=("core.context.inspect",))

    assert _names(home) == (
        set(selected) - {"core.context.inspect"}
    )


def test_maintenance_package_actions_use_enabled_domain_default() -> None:
    with maintenance_action_catalog_root() as root:
        catalog = ActionCatalogLoader().load(root)

    assert all(action.runtime.enabled for action in catalog.actions())


def _build_exact(
    selected: tuple[str, ...],
    *,
    disabled_actions: tuple[str, ...] = (),
):
    with (
        builtin_action_catalog_root() as core_root,
        maintenance_action_catalog_root() as maintenance_root,
    ):
        catalog = ActionCatalogLoader().load_many((core_root, maintenance_root))
        if disabled_actions:
            catalog = ActionCatalog(
                domains=catalog.domains(),
                actions=tuple(
                    replace(
                        action,
                        runtime=replace(action.runtime, enabled=False),
                    )
                    if action.name in disabled_actions
                    else action
                    for action in catalog.actions()
                ),
            )
        builder = ActionEngineBuilder(catalog)
        builder.include_actions(*selected)
        handlers = {
            item.backend.handler for item in catalog.actions() if item.name in selected
        }
        for handler in handlers:
            builder.register_executor(handler, FunctionActionExecutor(_stub))
        return builder.build()


def _names(action) -> set[str]:
    return {name for _domain, name in action.action_identifiers()}


def _stub(execution, context):
    del context
    return {"action": execution.call.action_name}
