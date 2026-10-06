"""Workspace refresh prepares the current owner view without mutating the segment."""

from pathlib import Path
from tinysoul.infra.time import CalendarDay

from tinysoul.llm.protocol.messages import TextPart
from tinysoul.plugins.workspace.projection import (
    WorkspaceRefresh,
    WorkspaceSegment,
)
from tinysoul.plugins.workspace import WorkspaceEngineBuilder, WorkspaceSettings


async def test_projection_prepares_without_mutation_and_installs_latest_snapshot(
    tmp_path: Path,
) -> None:
    workspace = WorkspaceEngineBuilder(WorkspaceSettings(root=tmp_path)).build()
    workspace.initialize_day(CalendarDay.parse("2026-09-20"))
    workspace.write_text("workspace:b.md", "body")
    workspace.set_description("workspace:b.md", "b")
    segment = WorkspaceSegment(workspace)
    prepared = await segment.prepare((WorkspaceRefresh(), WorkspaceRefresh()))
    assert segment.seal()["resources"] == []
    segment.install(prepared)
    part = segment.render()[0].parts[0]
    assert isinstance(part, TextPart)
    assert "workspace:b.md" in part.text
    assert workspace.stat("workspace:b.md").context_summary in part.text
    assert segment.seal() == {
        "resources": [
            {
                "ref": "workspace:b.md",
                "summary": workspace.stat("workspace:b.md").context_summary,
            }
        ]
    }
    await segment.close()
