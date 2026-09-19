"""Workspace projects owner snapshots in arrival order."""

from tinysoul.llm.protocol.messages import JsonPart
from tinysoul.plugins.workspace.projection import (
    WorkspaceResource,
    WorkspaceSegment,
    WorkspaceSnapshot,
)


async def test_projection_prepares_without_mutation_and_installs_latest_snapshot() -> (
    None
):
    segment = WorkspaceSegment()
    first = WorkspaceSnapshot((WorkspaceResource("workspace:a.md", "a"),))
    latest = WorkspaceSnapshot((WorkspaceResource("workspace:b.md", "b"),))
    prepared = await segment.prepare((first, latest))
    assert segment.seal()["resources"] == []
    segment.install(prepared)
    part = segment.render()[0].parts[0]
    assert isinstance(part, JsonPart)
    assert part.value == {"resources": [{"link": "workspace:b.md", "summary": "b"}]}
    assert segment.seal() == part.value
    await segment.close()
