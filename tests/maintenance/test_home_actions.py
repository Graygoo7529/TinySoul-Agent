from __future__ import annotations

from pathlib import Path

from tinysoul.action import (
    ActionCall,
    ActionExecution,
    ActionExecutionContext,
    ActionFramework,
    ActionResult,
    ActionResultStatus,
)
from tinysoul.action.core.loader import ActionCatalogLoader
from tinysoul.home import AgentHomeEngineBuilder, AgentHomeSettings
from tinysoul.infra.json import JsonObject
from tinysoul.maintenance.home import HomeMaintenanceActionController
from tinysoul.maintenance.resources import maintenance_action_catalog_root
from tinysoul.runtime import RunLevel, RunScope


_SKILL_TEXT = """---
title: Review HOW
description: Review working guidance.
---

# Review HOW

Keep the current method.
"""


def test_home_actions_require_inspect_before_resolving_how_review(
    tmp_path: Path,
) -> None:
    skill = tmp_path / "home" / "how" / "review" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text(_SKILL_TEXT, encoding="utf-8")
    home = AgentHomeEngineBuilder(
        AgentHomeSettings(
            original_root=tmp_path / "home",
            runtime_root=tmp_path / "runtime" / "home",
        )
    ).build()
    home.write_resource(
        "home:how/review/SKILL_MEMORY.md",
        "The method was useful as written.",
    )
    controller = HomeMaintenanceActionController(home)
    controller.begin()

    listed = _execute(controller, "maintenance.home.list", {})
    items = listed.payload["items"]
    assert isinstance(items, list)
    item = items[0]
    assert isinstance(item, dict)
    assert item["kind"] == "skill_how_review"
    assert item["allowed_resolutions"] == ["reject", "rewrite"]
    token = item["token"]
    assert isinstance(token, str)

    premature = _execute(
        controller,
        "maintenance.home.reject",
        {"token": token},
    )
    assert premature.status is ActionResultStatus.FAILED
    assert home.review_pending().skill_memory_count == 1

    inspected = _execute(
        controller,
        "maintenance.home.inspect",
        {"token": token},
    )
    assert inspected.status is ActionResultStatus.SUCCESS
    actual = inspected.payload["actual"]
    assert isinstance(actual, dict)
    assert actual["text"] == _SKILL_TEXT
    resolved = _execute(
        controller,
        "maintenance.home.reject",
        {"token": token},
    )
    assert resolved.status is ActionResultStatus.SUCCESS
    assert resolved.payload["remaining_reviews"] == 0

    completed = _execute(controller, "maintenance.complete", {})
    assert completed.status is ActionResultStatus.SUCCESS
    assert controller.finish()["runtime_home_removed"] is True


def _execute(
    controller: HomeMaintenanceActionController,
    action_name: str,
    params: JsonObject,
) -> ActionResult:
    with maintenance_action_catalog_root() as root:
        action = ActionCatalogLoader().load(root).get_action(action_name)
    return controller.execute(
        ActionExecution(
            action=action,
            call=ActionCall(
                call_id=f"call_{action_name}",
                action_name=action_name,
                params=params,
                sequence=1,
            ),
            framework=ActionFramework(
                invoke_id=f"invoke_{action_name}",
                batch_id="batch_home_maintenance",
                scope=RunScope().push(RunLevel.TURN, "turn_home_maintenance"),
                domain="maintenance",
            ),
        ),
        ActionExecutionContext(),
    )
