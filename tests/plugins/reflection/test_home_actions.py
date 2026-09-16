from __future__ import annotations

from pathlib import Path

from tinysoul.kernel.action import (
    ActionCall,
    ActionExecution,
    ActionExecutionContext,
    ActionFramework,
    ActionResult,
    ActionResultStatus,
)
from tinysoul.kernel.action.core.loader import ActionCatalogLoader
from tinysoul.plugins.home import AgentHomeEngineBuilder, AgentHomeSettings
from tinysoul.infra.json import JsonObject
from tinysoul.plugins.reflection.home import HomeReflectionActionController
from tinysoul.plugins.reflection.resources import maintenance_action_catalog_root
from tinysoul.runtime import RunLevel, RunScope, SignalBus


_SKILL_TEXT = """---
title: Review Skill
description: Review working guidance.
---

# Review Skill

Keep the current method.
"""


async def test_home_diff_and_review_do_not_require_stage_tokens(
    tmp_path: Path,
) -> None:
    skill = tmp_path / "home" / "skills" / "review" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text(_SKILL_TEXT, encoding="utf-8")
    home = AgentHomeEngineBuilder(
        AgentHomeSettings(
            original_root=tmp_path / "home",
            runtime_root=tmp_path / "runtime" / "home",
        )
    ).build()
    home.write_resource(
        "home:skills/review/SKILL_MEMORY.md",
        "The method was useful as written.",
    )
    controller = HomeReflectionActionController(home)

    listed = await _execute(controller, "home_reflection.diff", {})
    assert listed.status is ActionResultStatus.SUCCESS
    assert home.review_pending().skill_memory_count == 1
    inspected = await _execute(controller, "home_reflection.diff", {"paths": ["home:skills@review"]})
    assert inspected.status is ActionResultStatus.SUCCESS
    resolved = await _execute(controller, "home_reflection.review", {
        "paths": ["home:skills@review"], "decision": "reject",
    })
    assert resolved.status is ActionResultStatus.SUCCESS
    assert not home.review_pending().pending


async def _execute(
    controller: HomeReflectionActionController,
    action_name: str,
    params: JsonObject,
) -> ActionResult:
    with maintenance_action_catalog_root() as root:
        action = ActionCatalogLoader().load(root).get_action(action_name)
    return await controller.execute(
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
                domain="home_reflection",
            ),
        ),
        ActionExecutionContext(signal_bus=SignalBus()),
    )
