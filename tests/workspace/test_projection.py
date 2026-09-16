"""Workspace owns its Turn projection and revision interpretation."""

import pytest

from tinysoul.llm.messages import JsonPart
from tinysoul.runtime import RuntimeException
from tinysoul.workspace.projection import WorkspaceResource, WorkspaceSegment, WorkspaceSnapshot


async def test_projection_prepares_without_mutation_and_hides_consistency_metadata() -> None:
    segment = WorkspaceSegment()
    first = WorkspaceSnapshot(2, (WorkspaceResource("workspace:a.md", "a"),))
    stale = WorkspaceSnapshot(1, (WorkspaceResource("workspace:b.md", "b"),))
    prepared = await segment.prepare((first, stale))
    assert segment.seal()["resources"] == []
    segment.install(prepared)
    assert segment.seal()["revision"] == 2
    part = segment.render()[0].parts[0]
    assert isinstance(part, JsonPart)
    assert part.value == {"resources": [{"link": "workspace:a.md", "summary": "a"}]}

    conflicting = WorkspaceSnapshot(2, (WorkspaceResource("workspace:c.md", "c"),))
    with pytest.raises(RuntimeException) as raised:
        await segment.prepare((conflicting,))
    assert raised.value.payload["module"] == "workspace"
    assert segment.seal()["resources"] == [{"link": "workspace:a.md", "summary": "a"}]
    await segment.close()
