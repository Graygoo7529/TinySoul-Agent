from datetime import date

import pytest

from tinysoul.infra.references import ReferenceResolver
from tinysoul.kernel.context import ContextEngineBuilder, build_trace_phase_note_signal
from tinysoul.kernel.context.errors import ContextInspectRequestError
from tinysoul.kernel.retrieval.contracts import (
    OperationKind,
    QuerySource,
    RetrievalRequest,
    SourceKind,
    TextQuery,
)
from tinysoul.kernel.retrieval.operations import SearchSession
from tinysoul.kernel.retrieval.policy import RetrievalPolicy
from tinysoul.runtime import RunLevel, RunScope, SignalBus


def test_semantic_pages_preserve_long_question_and_business_content_with_real_coverage():
    from tinysoul.infra.continuation import OpaqueContinuationCodec
    from tinysoul.infra.json import dumps_json
    from tinysoul.kernel.context.disclosure import fact_unit
    from tinysoul.kernel.retrieval.disclosure import DisclosurePage

    ref = "session:turn/2026-10-07/1#action/0"
    question = fact_unit(
        {
            "action": "core.ask",
            "result": {
                "details": "Keep the evidence. " * 150,
                "question": "Which version?",
                "options": [
                    {
                        "id": "full",
                        "label": "Full source",
                        "description": "Keep examples. " * 100,
                    }
                ],
            },
        },
        ref,
    )
    business = fact_unit(
        {"action": "external.query", "result": {"rows": ["row" * 500]}}, ref
    )
    source = DisclosurePage(ref, "session_actions", content=(question, business))
    codec = OpaqueContinuationCodec(owner="test", operation="inspect")
    token = None
    bodies = []
    for _ in range(100):
        page = source.render(codec=codec, max_chars=2048, continuation=token)
        assert len(dumps_json(page.to_json())) <= 2048
        assert len(page.model_text) <= 2048
        assert "content_fragment" not in page.to_json()
        assert "next_continuation" not in page.canonical_payload
        for part in page.items:
            bodies.append(part.unit.text[part.start : part.end])
            assert part.coverage["end"] == part.end
            assert part.coverage["complete"] == (
                part.start == 0 and part.end == len(part.unit.text)
            )
            assert part.unit.ref in page.recollection_text
            if part.unit is question and part.start >= question.sections[1][0]:
                assert (
                    "Full source [full]" in part.title or "Answer policy" in part.title
                )
        token = page.next_continuation
        if token is None:
            break
    else:
        pytest.fail("Disclosure did not finish")
    assert "".join(bodies) == question.text + business.text


def test_context_date_filter_uses_installed_fact_dates():
    from tinysoul.kernel.context.disclosure import DisclosureSearchEntry
    from tinysoul.kernel.context.search import disclosure_corpus
    from tinysoul.kernel.retrieval.contracts import DirectorySource

    entries = tuple(
        DisclosureSearchEntry(
            f"session:day-{day}",
            "turn",
            {"text": "original interaction"},
            "session",
            day=date(2026, 9, day),
        )
        for day in (20, 21)
    )
    corpus = disclosure_corpus(
        entries,
        RetrievalRequest(
            DirectorySource(
                "session", {"day": {"after": "2026-09-20", "before": "2026-09-22"}}
            ),
        ),
        ReferenceResolver(),
    )
    assert [item.ref for item in corpus.candidates] == ["session:day-21"]
    assert "original interaction" in corpus.candidates[0].content_units[0].text
    assert corpus.candidates[0].content_units[0].text == "original interaction"


def test_disclosure_blank_lines_keep_actual_source_range_and_small_budget_fails():
    from tinysoul.infra.continuation import (
        ContinuationError,
        ContinuationFailureReason,
        OpaqueContinuationCodec,
    )
    from tinysoul.kernel.retrieval.disclosure import DisclosurePage, DisclosureUnit

    unit = DisclosureUnit(
        "workspace:notes.md", "Notes", "first\n\nlast\n", first_line=8
    )
    blank = unit.select(6, 7)
    assert blank.coverage["start_line"] == blank.coverage["end_line"] == 9
    assert unit.select(0, 7).coverage["end_line"] == 9
    with pytest.raises(ContinuationError) as failed:
        DisclosurePage(unit.ref, "content", content=(unit,)).render(
            codec=OpaqueContinuationCodec(owner="test", operation="inspect"),
            max_chars=32,
        )
    assert failed.value.reason is ContinuationFailureReason.BUDGET_TOO_SMALL


async def test_trace_navigation_query_and_stable_refs_across_folding() -> None:
    context = (
        ContextEngineBuilder(system_text="test")
        .with_trace_heap(chunk_max_chars=150, branch_factor=2, min_hot_entries=0)
        .with_trace_inspect_max_chars(2048)
        .build()
    )
    turn_id = context.begin_turn("follow clues", turn_id="2026-10-06/55")
    await context.open_segments(date(2026, 9, 20))
    scope = RunScope().push(RunLevel.TURN, turn_id)
    root = f"turn:trace/{turn_id}"
    bus = SignalBus()
    for index in range(12):
        bus.emit(
            build_trace_phase_note_signal(
                {"text": f"evidence-{index}: " + "body " * 100},
                scope=scope,
                source="test",
                cycle_id=f"cycle_{index}",
            )
        )
    await context.consume_signals(bus)
    found = (await context.inspect(root, query="evidence-7:")).to_json()
    hit = found["items"]
    assert isinstance(hit, list) and len(hit) == 1 and isinstance(hit[0], dict)
    fact_ref = str(hit[0]["ref"])
    before = (await context.inspect(fact_ref)).to_json()
    unfinished = (await context.inspect(root)).to_json()
    token = unfinished.get("next_continuation")
    assert isinstance(token, str)
    context.compress(required_chars=100000)
    with pytest.raises(ContextInspectRequestError):
        (await context.inspect(root, continuation=token)).to_json()
    assert (await context.inspect(fact_ref)).to_json() == before
    assert (await context.inspect(root, query="evidence-7:")).to_json() == found
    assert ((await context.inspect(fact_ref, query="evidence-8:")).to_json())[
        "items"
    ] == []

    request = RetrievalRequest(QuerySource("trace", TextQuery("evidence-7:")))
    corpus = await context.search_corpus(request, references=ReferenceResolver())

    async def source(_request):
        return corpus

    page = await SearchSession(
        action_id="core.context.search",
        retrieval_policies=(
            RetrievalPolicy(
                "core.context.search", tuple(SourceKind), tuple(OperationKind)
            ),
        ),
        source=source,
    ).search(request)
    assert page.items[0].ref == fact_ref
    assert (await context.inspect(page.items[0].ref)).to_json() == before

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
            page = (await context.inspect(ref, continuation=token)).to_json()
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
    assert len(leaves) == 13 and fact_ref in leaves  # Includes the initial input.
    with pytest.raises(ContextInspectRequestError):
        (await context.inspect(root, query=" ")).to_json()
    await context.close_segments()
