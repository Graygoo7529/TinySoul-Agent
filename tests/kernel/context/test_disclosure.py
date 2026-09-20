from datetime import date

import pytest

from tinysoul.infra.json import JsonObject
from tinysoul.kernel.context import ContextEngineBuilder, build_trace_phase_note_signal
from tinysoul.kernel.context.errors import ContextInspectRequestError
from tinysoul.runtime import RunLevel, RunScope, SignalBus


async def test_trace_navigation_query_and_stable_refs_across_folding() -> None:
    context = (ContextEngineBuilder(system_text="test")
               .with_trace_heap(chunk_max_chars=150, branch_factor=2, min_hot_entries=0)
               .with_trace_inspect_max_chars(2048).build())
    turn_id = context.begin_turn("follow clues")
    await context.open_segments(date(2026, 9, 20))
    scope = RunScope().push(RunLevel.TURN, turn_id)
    root = f"turn:trace@{turn_id}"
    bus = SignalBus()
    for index in range(12):
        bus.emit(build_trace_phase_note_signal(
            {"text": f"evidence-{index}: " + "body " * 100}, scope=scope, source="test",
            cycle_id=f"cycle_{index}",
        ))
    await context.consume_signals(bus)
    found = await context.inspect(root, query="evidence-7:")
    hit = found["items"]
    assert isinstance(hit, list) and len(hit) == 1 and isinstance(hit[0], dict)
    fact_ref = str(hit[0]["ref"])
    before = await context.inspect(fact_ref)
    unfinished = await context.inspect(root)
    token = unfinished.get("next_continuation")
    assert isinstance(token, str)
    context.compress(required_chars=100000)
    with pytest.raises(ContextInspectRequestError):
        await context.inspect(root, continuation=token)
    assert await context.inspect(fact_ref) == before
    assert await context.inspect(root, query="evidence-7:") == found
    assert (await context.inspect(fact_ref, query="evidence-8:"))["items"] == []

    # Walk only public child refs, including paginated roots and branches.
    pending = [root]
    leaves: set[str] = set()
    visited: set[str] = set()
    while pending:
        ref = pending.pop()
        assert ref not in visited
        visited.add(ref)
        token = None
        while True:
            page = await context.inspect(ref, continuation=token)
            items = page["items"]
            assert isinstance(items, list)
            for item in items:
                assert isinstance(item, dict)
                if item.get("kind") == "child":
                    pending.append(str(item["ref"]))
                else:
                    leaves.add(ref)
            token = page.get("next_continuation")
            if token is None:
                break
            assert isinstance(token, str)
    assert len(leaves) == 12 and fact_ref in leaves
    with pytest.raises(ContextInspectRequestError):
        await context.inspect(root, query=" ")
    await context.close_segments()
