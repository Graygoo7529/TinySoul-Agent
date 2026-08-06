from __future__ import annotations

from datetime import UTC, datetime
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
from tinysoul.infra.json import JsonObject
from tinysoul.infra.time import BusinessDay
from tinysoul.maintenance.memory import MemoryMaintenanceActionController
from tinysoul.maintenance.resources import maintenance_action_catalog_root
from tinysoul.memory import (
    ActiveMemoryDocument,
    ActiveMemorySnapshot,
    DailyCompositionRequest,
    DailyCompositionResult,
    LLMDailyMemoryComposer,
    MemoryEngine,
    MemorySettings,
    NoteMemoryDocument,
)
from tinysoul.runtime import RunLevel, RunScope
from tinysoul.session import SessionMemoryFact, SessionMemoryFactsProjection


DAY = BusinessDay.parse("2026-08-05")


def test_memory_maintenance_draft_requires_inspection_and_commits_daily_and_knowledge(
    tmp_path: Path,
) -> None:
    memory = MemoryEngine(settings=MemorySettings(root=tmp_path / "memory"))
    active = ActiveMemorySnapshot(
        document=ActiveMemoryDocument(
            day=DAY.value,
            revision=1,
            updated_at=datetime(2026, 8, 5, 9, tzinfo=UTC),
            content="Keep the agent-design decision explicit.",
        ),
        text="active memory",
        digest="a" * 64,
    )
    projection = SessionMemoryFactsProjection(
        day=DAY,
        revision=3,
        facts=(
            SessionMemoryFact(
                ref="session:turn/design",
                started_at=datetime(2026, 8, 5, 10, tzinfo=UTC),
                user_inputs=("Record the memory design",),
                answer="Recorded.",
            ),
        ),
    )
    controller = MemoryMaintenanceActionController(
        memory=memory,
        composer=_Composer(),
    )
    controller.begin(
        target_day=DAY,
        projection=projection,
        active_memory=active,
        workspace=None,
    )

    premature = _execute(
        controller,
        "maintenance.memory.stage_create",
        {
            "kind": "concept",
            "inspection_ref": "missing",
            "cite": "agent-design",
            "content": "Design concepts for an agent memory system.",
        },
    )
    assert premature.status is ActionResultStatus.FAILED

    inspected = _execute(
        controller,
        "maintenance.memory.inspect",
        {"query": "agent design", "kinds": ["concept", "note"]},
    )
    inspection_ref = inspected.payload["inspection_ref"]
    assert isinstance(inspection_ref, str)
    concept = _execute(
        controller,
        "maintenance.memory.stage_create",
        {
            "kind": "concept",
            "inspection_ref": inspection_ref,
            "cite": "agent-design",
            "content": "Design concepts for an agent memory system.",
        },
    )
    assert concept.status is ActionResultStatus.SUCCESS
    note = _execute(
        controller,
        "maintenance.memory.stage_create",
        {
            "kind": "note",
            "inspection_ref": inspection_ref,
            "title": "Active and persistent memory",
            "content": "Active memory remains light while maintenance updates durable knowledge.",
            "relations": ["memory:concept/agent-design"],
            "evidence": [],
        },
    )
    note_link = note.payload["link"]
    assert isinstance(note_link, str)

    assert _execute(
        controller,
        "maintenance.memory.compose_daily",
        {},
    ).status is ActionResultStatus.SUCCESS
    assert _execute(
        controller,
        "maintenance.memory.stage_daily",
        {"mode": "create"},
    ).status is ActionResultStatus.SUCCESS
    preview = _execute(controller, "maintenance.memory.preview", {})
    preview_revision = preview.payload["preview_revision"]
    assert isinstance(preview_revision, int)
    assert _execute(
        controller,
        "maintenance.memory.commit",
        {"preview_revision": preview_revision},
    ).status is ActionResultStatus.SUCCESS
    assert _execute(
        controller,
        "maintenance.complete",
        {},
    ).status is ActionResultStatus.SUCCESS
    outcome = controller.finish()

    assert outcome["target_day"] == str(DAY)
    assert outcome["model_calls"] == 1
    assert memory.read_daily(DAY) is not None
    concept_document = memory.read_document(
        next(
            link
            for link in memory.links()
            if str(link) == "memory:concept/agent-design"
        )
    ).document
    assert concept_document.created_on == DAY.value
    recalled_note = memory.recall(note_link)
    assert recalled_note.metadata["title"] == "Active and persistent memory"
    note_document = memory.read_document(
        next(link for link in memory.links() if str(link) == note_link)
    ).document
    assert isinstance(note_document, NoteMemoryDocument)
    assert note_document.activity.activation_count == 1


class _Composer(LLMDailyMemoryComposer):
    def __init__(self) -> None:
        pass

    def compose(
        self,
        request: DailyCompositionRequest,
        *,
        scope: RunScope,
    ) -> DailyCompositionResult:
        del request, scope
        return DailyCompositionResult(
            content="## Events\n\n- Maintained active and persistent memory.",
            model_calls=1,
        )


def _execute(
    controller: MemoryMaintenanceActionController,
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
                batch_id="batch_memory_maintenance",
                scope=RunScope().push(RunLevel.TURN, "turn_memory_maintenance"),
                domain="maintenance",
            ),
        ),
        ActionExecutionContext(),
    )
