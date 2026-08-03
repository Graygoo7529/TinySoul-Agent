from __future__ import annotations

from pathlib import Path
from typing import cast

from tinysoul.action import (
    ActionEngine,
    ActionEngineBuilder,
    ActionResult,
    ActionResultStatus,
    builtin_action_catalog_root,
)
from tinysoul.action.core.loader import ActionCatalogLoader
from tinysoul.home import AgentHomeEngineBuilder, AgentHomeSettings
from tinysoul.llm.tools import ToolCallRecord, ToolKind
from tinysoul.maintenance import (
    BusinessDay,
    MAINTENANCE_HOME_ACTIONS,
    MAINTENANCE_MEMORY_ACTIONS,
    MaintenanceActionController,
    MaintenanceCompletionDetector,
    maintenance_action_view,
    register_maintenance_actions,
    user_action_view,
)
from tinysoul.memory import (
    MemoryConsolidator,
    MemoryEngine,
    MemoryMaintenanceFailure,
    MemoryMaintenanceOutcome,
    MemoryMaintenanceStatus,
)
from tinysoul.runtime import RunScope
from tinysoul.session import SessionMemoryFactsProjection
from tests.action_helpers import FunctionActionExecutor


def test_turn_action_views_isolate_user_home_and_memory_actions(
    tmp_path: Path,
) -> None:
    action, _controller = _action_engine(tmp_path)

    user_names = {name for _domain, name in user_action_view(action).action_identifiers()}
    home_names = {
        name
        for _domain, name in maintenance_action_view(
            action,
            kind="home",
        ).action_identifiers()
    }
    memory_names = {
        name
        for _domain, name in maintenance_action_view(
            action,
            kind="memory",
        ).action_identifiers()
    }

    assert "core.answer" in user_names
    assert not any(name.startswith("maintenance.") for name in user_names)
    assert home_names == set(MAINTENANCE_HOME_ACTIONS)
    assert memory_names == set(MAINTENANCE_MEMORY_ACTIONS)
    assert "core.answer" not in home_names | memory_names
    assert "maintenance.memory.consolidate" not in home_names
    assert "maintenance.home.accept" not in memory_names


def test_home_complete_requires_owner_postcondition(
    tmp_path: Path,
) -> None:
    action, controller = _action_engine(tmp_path)
    home_action = maintenance_action_view(action, kind="home")
    controller.begin_home()

    blocked = _run_action(home_action, "maintenance.complete")

    assert blocked.status is ActionResultStatus.FAILED
    assert blocked.failure is not None
    assert blocked.failure.reason == "maintenance_action_failed"
    assert MaintenanceCompletionDetector().detect((blocked,)) is None

    listed = _run_action(home_action, "maintenance.home.list")
    items = listed.payload["items"]
    assert isinstance(items, list) and len(items) == 1
    item = items[0]
    assert isinstance(item, dict)
    token = item["token"]
    assert isinstance(token, str)
    rejected = _run_action(
        home_action,
        "maintenance.home.reject",
        {"token": token},
    )
    completed = _run_action(home_action, "maintenance.complete")

    assert rejected.status is ActionResultStatus.SUCCESS
    assert completed.status is ActionResultStatus.SUCCESS
    assert MaintenanceCompletionDetector().detect((completed,)) == {
        "kind": "maintenance",
        "result_id": completed.result_id,
        "task": "home",
    }
    assert controller.finish().details == {"remaining_changes": 0}


def test_memory_complete_rejects_failed_consolidation(
    tmp_path: Path,
) -> None:
    day = BusinessDay.parse("2026-08-02")
    failed = MemoryMaintenanceOutcome(
        day=day,
        link="memory:2026-08-02",
        status=MemoryMaintenanceStatus.FAILED,
        failure=MemoryMaintenanceFailure.CONSOLIDATION_FAILED,
    )
    action, controller = _action_engine(
        tmp_path,
        memory=_OutcomeMemory(failed),
    )
    memory_action = maintenance_action_view(action, kind="memory")
    controller.begin_memory(
        target_day=day,
        projection=SessionMemoryFactsProjection(day=day, revision=0),
        workspace=None,
        rebuild_memory=False,
    )

    consolidated = _run_action(
        memory_action,
        "maintenance.memory.consolidate",
    )
    blocked = _run_action(memory_action, "maintenance.complete")

    assert consolidated.status is ActionResultStatus.SUCCESS
    assert consolidated.payload["status"] == "failed"
    assert consolidated.payload["failure_kind"] == "consolidation_failed"
    assert blocked.status is ActionResultStatus.FAILED
    assert MaintenanceCompletionDetector().detect((blocked,)) is None
    controller.abort()


def _action_engine(
    tmp_path: Path,
    *,
    memory: object | None = None,
) -> tuple[ActionEngine, MaintenanceActionController]:
    (tmp_path / "home").mkdir()
    home = AgentHomeEngineBuilder(
        AgentHomeSettings(
            original_root=tmp_path / "home",
            runtime_root=tmp_path / "runtime" / "home",
        )
    ).build()
    home.write_top("home:why@pending", "runtime-only change")
    controller = MaintenanceActionController(
        home=home,
        memory=cast(MemoryEngine, memory or object()),
        consolidator=cast(MemoryConsolidator, object()),
        timezone="Asia/Shanghai",
    )
    with builtin_action_catalog_root() as root:
        catalog = ActionCatalogLoader().load(root)
        builder = ActionEngineBuilder(root)
        maintenance_handlers = {
            action.backend.handler
            for action in catalog.actions_in_domain("maintenance")
        }
        for handler in sorted(
            {action.backend.handler for action in catalog.actions()}
            - maintenance_handlers
        ):
            builder.register_executor(
                handler,
                FunctionActionExecutor(
                    lambda execution, context: {"stub": execution.call.action_name}
                ),
            )
        register_maintenance_actions(builder, controller=controller)
        return builder.build(), controller


class _OutcomeMemory:
    def __init__(self, outcome: MemoryMaintenanceOutcome) -> None:
        self._outcome = outcome

    def run_maintenance(self, **kwargs: object) -> MemoryMaintenanceOutcome:
        return self._outcome


def _run_action(
    action: ActionEngine,
    name: str,
    params: dict[str, object] | None = None,
) -> ActionResult:
    normalization = action.normalize(
        (
            ToolCallRecord(
                id=f"call_{name}",
                name=name,
                arguments=cast(dict, params or {}),
                kind=ToolKind.ACTION,
            ),
        )
    )
    assert normalization.results == ()
    preparation = action.prepare_batch(
        normalization.calls,
        scope=RunScope(),
    )
    assert preparation.results == ()
    results = action.run_batch(preparation.batch)
    assert len(results) == 1
    return results[0]
