from __future__ import annotations

from datetime import UTC, datetime
import json
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
    ConceptMemoryDocument,
    LLMDailyMemoryComposer,
    MemoryActivity,
    MemoryEngine,
    MemorySettings,
    MemoryStatus,
    NoteMemoryDocument,
)
from tinysoul.runtime import RunLevel, RunScope
from tinysoul.session import SessionMemoryFact, SessionMemoryFactsProjection
from tinysoul.workspace import (
    WorkspaceArchiveView,
    WorkspaceManifest,
    WorkspaceResourceKind,
    WorkspaceResourceRecord,
)


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
    staged_inspect = _execute(
        controller,
        "maintenance.memory.inspect",
        {"query": "design concepts", "kinds": ["concept"]},
    )
    assert staged_inspect.status is ActionResultStatus.SUCCESS
    inspected_items = staged_inspect.payload.get("items")
    assert isinstance(inspected_items, list)
    assert any(
        isinstance(item, dict) and item.get("link") == "memory:concept/agent-design"
        for item in inspected_items
    )
    assert len(json.dumps(inspected.payload, ensure_ascii=False, separators=(",", ":"))) <= 8_000
    staged_recall = _execute(
        controller,
        "maintenance.memory.recall",
        {"memory_link": "memory:concept/agent-design"},
    )
    staged_digest = staged_recall.payload["digest"]
    assert isinstance(staged_digest, str)
    assert staged_digest != "staged"
    rewritten = _execute(
        controller,
        "maintenance.memory.stage_rewrite",
        {
            "memory_link": "memory:concept/agent-design",
            "inspection_ref": staged_recall.payload["inspection_ref"],
            "expected_digest": staged_digest,
            "content": "Design concepts for an agent memory system, refined in this turn.",
        },
    )
    assert rewritten.status is ActionResultStatus.SUCCESS
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
    assert isinstance(concept_document, ConceptMemoryDocument)
    assert concept_document.created_on == DAY.value
    assert concept_document.activity.activation_count == 1
    recalled_note = memory.recall(note_link)
    assert recalled_note.metadata["title"] == "Active and persistent memory"
    note_document = memory.read_document(
        next(link for link in memory.links() if str(link) == note_link)
    ).document
    assert isinstance(note_document, NoteMemoryDocument)
    assert note_document.activity.activation_count == 1


def test_memory_maintenance_inspect_sources_pages_session_and_workspace_independently(
    tmp_path: Path,
) -> None:
    memory = MemoryEngine(settings=MemorySettings(root=tmp_path / "memory"))
    active = ActiveMemorySnapshot(
        document=ActiveMemoryDocument(
            day=DAY.value,
            revision=1,
            updated_at=datetime(2026, 8, 5, 9, tzinfo=UTC),
            content="",
        ),
        text="active memory",
        digest="a" * 64,
    )
    projection = SessionMemoryFactsProjection(
        day=DAY,
        revision=3,
        facts=tuple(
            SessionMemoryFact(
                ref=f"session:turn/{index}",
                started_at=datetime(2026, 8, 5, 10 + index, tzinfo=UTC),
                user_inputs=(f"Input {index}",),
                answer=f"Answer {index}.",
            )
            for index in range(2)
        ),
    )
    workspace = WorkspaceArchiveView(
        root=tmp_path / "workspace",
        manifest=WorkspaceManifest(
            day=str(DAY),
            resources=tuple(
                WorkspaceResourceRecord(
                    link=f"workspace:file-{index}.txt",
                    relative_path=f"file-{index}.txt",
                    kind=WorkspaceResourceKind.TEXT,
                    media_type="text/plain",
                    suffix=".txt",
                    summary=f"Workspace file {index}",
                    size=10,
                    mtime_ns=index + 1,
                    digest=(str(index + 1) * 64),
                )
                for index in range(2)
            ),
        ),
        max_read_chars=1000,
    )
    controller = MemoryMaintenanceActionController(memory=memory, composer=_Composer())
    controller.begin(
        target_day=DAY,
        projection=projection,
        active_memory=active,
        workspace=workspace,
    )

    session_page = _execute(
        controller,
        "maintenance.memory.inspect_sources",
        {"source": "session", "offset": 0, "limit": 1},
    )
    assert session_page.status is ActionResultStatus.SUCCESS
    assert session_page.payload["source"] == "session"
    assert session_page.payload["total_count"] == 2
    assert session_page.payload["has_more"] is True
    session_facts = session_page.payload["facts"]
    assert isinstance(session_facts, list)
    assert len(session_facts) == 1
    assert "workspace_resources" not in session_page.payload

    workspace_page = _execute(
        controller,
        "maintenance.memory.inspect_sources",
        {"source": "workspace", "offset": 1, "limit": 1},
    )
    assert workspace_page.status is ActionResultStatus.SUCCESS
    assert workspace_page.payload["source"] == "workspace"
    assert workspace_page.payload["total_count"] == 2
    assert workspace_page.payload["has_more"] is False
    workspace_resources = workspace_page.payload["workspace_resources"]
    assert isinstance(workspace_resources, list)
    assert len(workspace_resources) == 1
    assert "facts" not in workspace_page.payload


def test_memory_maintenance_rewrite_activation_is_deduplicated_per_turn(
    tmp_path: Path,
) -> None:
    memory = MemoryEngine(settings=MemorySettings(root=tmp_path / "memory"))
    existing = ConceptMemoryDocument(
        cite="existing",
        status=MemoryStatus.ACTIVE,
        created_on=DAY.value,
        updated_on=DAY.value,
        activity=MemoryActivity(DAY.value, 4),
        content="An existing durable concept.",
    )
    memory.write_document(existing, expected_absent=True)
    controller = MemoryMaintenanceActionController(memory=memory, composer=_Composer())
    controller.begin(
        target_day=DAY,
        projection=SessionMemoryFactsProjection(day=DAY, revision=1, facts=()),
        active_memory=ActiveMemorySnapshot(
            document=ActiveMemoryDocument(
                day=DAY.value,
                revision=1,
                updated_at=datetime(2026, 8, 5, 9, tzinfo=UTC),
                content="",
            ),
            text="active memory",
            digest="a" * 64,
        ),
        workspace=None,
    )

    inspected = _execute(
        controller,
        "maintenance.memory.inspect",
        {"query": "existing concept", "kinds": ["concept"]},
    )
    assert inspected.status is ActionResultStatus.SUCCESS
    recalled = _execute(
        controller,
        "maintenance.memory.recall",
        {"memory_link": str(existing.link)},
    )
    first = _execute(
        controller,
        "maintenance.memory.stage_rewrite",
        {
            "memory_link": str(existing.link),
            "inspection_ref": recalled.payload["inspection_ref"],
            "expected_digest": recalled.payload["digest"],
            "content": "The existing concept was refined once.",
        },
    )
    assert first.status is ActionResultStatus.SUCCESS
    staged_recall = _execute(
        controller,
        "maintenance.memory.recall",
        {"memory_link": str(existing.link)},
    )
    second = _execute(
        controller,
        "maintenance.memory.stage_rewrite",
        {
            "memory_link": str(existing.link),
            "inspection_ref": staged_recall.payload["inspection_ref"],
            "expected_digest": staged_recall.payload["digest"],
            "content": "The existing concept was refined twice.",
        },
    )
    assert second.status is ActionResultStatus.SUCCESS

    assert _execute(controller, "maintenance.memory.compose_daily", {}).status is ActionResultStatus.SUCCESS
    assert _execute(
        controller,
        "maintenance.memory.stage_daily",
        {"mode": "create"},
    ).status is ActionResultStatus.SUCCESS
    preview = _execute(controller, "maintenance.memory.preview", {})
    assert preview.status is ActionResultStatus.SUCCESS
    assert _execute(
        controller,
        "maintenance.memory.commit",
        {"preview_revision": preview.payload["preview_revision"]},
    ).status is ActionResultStatus.SUCCESS
    assert _execute(controller, "maintenance.complete", {}).status is ActionResultStatus.SUCCESS
    controller.finish()

    document = memory.read_document(existing.link).document
    assert isinstance(document, ConceptMemoryDocument)
    assert document.content == "The existing concept was refined twice."
    assert document.activity.activation_count == 5


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
