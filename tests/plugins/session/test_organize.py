"""Session ownership, source identity and the shared disclosure contract."""

from dataclasses import replace
from pathlib import Path

import pytest

from tinysoul.infra.json import JsonObject, dumps_json
from tinysoul.infra.time import CalendarDay
from tinysoul.kernel.action import (
    ActionCall,
    ActionFramework,
    ActionResult,
    ActionResultStatus,
)
from tinysoul.kernel.action.call import ExecutionFact, ExecutionState
from tinysoul.kernel.context import (
    ContextEngineBuilder,
    ContextTurnFacts,
    ContextTurnInput,
    TaskPrompt,
    PromptBlock,
)
from tinysoul.kernel.context.segments import TurnInfo
from tinysoul.kernel.context.errors import ContextInspectRequestError
from tinysoul.kernel.context.signals import build_input_append_signal
from tinysoul.kernel.loop.outcomes import TurnOutcomeStatus
from tinysoul.plugins.session import SessionEngine, SessionSettings
from tinysoul.plugins.session.annotations.models import (
    AnnotationKind,
    AnnotationStatus,
    OrganizeChange,
    OrganizeFailureReason,
    SemanticEdge,
    SemanticNode,
    SemanticRelation,
)
from tinysoul.plugins.session.views.navigation import SessionEvidence
from tinysoul.plugins.session.errors import (
    SessionInspectRequestError,
    SessionIOError,
    SessionInvariantError,
)
from tinysoul.plugins.session.projection import (
    UpdatingSessionProvider,
    SessionRefresh,
    session_segment_registration,
)
from tinysoul.plugins.session.records.models import SessionOutputRecord
from tinysoul.plugins.session.services import SessionService, SessionOrganizeService
from tinysoul.runtime import RunScope, RunLevel, SignalBus

from .synthetic import SyntheticAction, completion

DAY = CalendarDay.parse("2026-09-21")
PRIOR = "session:turn/prior"


def _session(tmp_path: Path, *, budget: int = 24000, page: int = 8000) -> SessionEngine:
    result = SessionEngine(
        SessionSettings(
            root=tmp_path / "session",
            background_max_chars=budget,
            inspect_max_chars=page,
        )
    )
    result.initialize_day(DAY)
    return result


def _record(
    session: SessionEngine, turn: str = "prior", *, text: str = "initial task"
) -> None:
    session.record_turn(
        completion(turn, ask=text),
        day=DAY,
        output=SessionOutputRecord(text=f"answer for {turn}"),
        status=TurnOutcomeStatus.ANSWERED,
        exhausted=False,
    )


def _facts() -> ContextTurnFacts:
    return ContextTurnFacts(
        "active", (ContextTurnInput("new evidence", 1, "initial"),), ()
    )


def _node(
    ref: str = "local:topic", *, source: str = PRIOR, body: str = "An interpretation"
) -> SemanticNode:
    return SemanticNode(ref, AnnotationKind.THREAD, "Topic", body, (source,))


def _edge(
    ref: str,
    source: str,
    target: str,
    relation: SemanticRelation = SemanticRelation.COVERS,
) -> SemanticEdge:
    return SemanticEdge(
        ref, source, target, relation, "A source-backed relationship", (PRIOR,)
    )


def _items(page: JsonObject) -> list[JsonObject]:
    values = page["items"]
    assert isinstance(values, list)
    assert all(isinstance(item, dict) for item in values)
    return [item for item in values if isinstance(item, dict)]


def test_atomic_annotations_preserve_facts_and_stable_refs(tmp_path: Path) -> None:
    session = _session(tmp_path)
    _record(session)
    _record(session, "second")
    history = session.inspect(PRIOR)
    result = session.organize(
        OrganizeChange(
            (PRIOR,),
            nodes=(_node(), _node("local:branch")),
            edges=(
                _edge("local:member", "local:topic", PRIOR),
                _edge("local:shared", "local:branch", PRIOR),
                _edge(
                    "local:fork",
                    "local:branch",
                    "local:topic",
                    SemanticRelation.BRANCHES_FROM,
                ),
            ),
        ),
        _facts(),
    )
    assert result.failure is None
    refs = dict(result.created)
    assert len(result.changed_refs) == 5
    assert session.inspect(PRIOR) == history
    assert [
        item["ref"]
        for item in _items(session.inspect("session:unclassified"))
        if item.get("kind") == "child"
    ] == ["session:turn/second"]
    assert refs["local:branch"] in str(session.inspect(refs["local:topic"]))
    assert str(session.background_snapshot(DAY).items).count("answer for prior") == 1

    old = session.annotation_snapshot()
    rejected = session.organize(
        OrganizeChange((PRIOR,), retract_ids=(refs["local:topic"],)), _facts()
    )
    assert rejected.failure is OrganizeFailureReason.CONFLICT
    assert session.annotation_snapshot() == old
    assert _session(tmp_path).annotation_snapshot() == old

    # A merge is a new entry; old branches and factual identities remain usable.
    merge = session.organize(
        OrganizeChange(
            (refs["local:topic"],),
            nodes=(_node("local:merge"),),
            edges=(
                _edge(
                    "local:left",
                    "local:merge",
                    refs["local:topic"],
                    SemanticRelation.RESOLVES,
                ),
                _edge(
                    "local:right",
                    "local:merge",
                    refs["local:branch"],
                    SemanticRelation.CONTINUES,
                ),
            ),
        ),
        _facts(),
    )
    assert merge.failure is None
    assert session.inspect(PRIOR) == history
    # Explicitly retract every incident relation when removing a branch.
    edge_refs = tuple(
        item.ref
        for item in session.annotation_snapshot().edges
        if refs["local:topic"] in (item.source, item.target)
    )
    result = session.organize(
        OrganizeChange((PRIOR,), retract_ids=(refs["local:topic"], *edge_refs)),
        _facts(),
    )
    assert result.failure is None
    removed = session.annotation_snapshot().get(refs["local:topic"])
    assert removed is not None and removed.status is AnnotationStatus.RETRACTED
    assert "retracted" in str(session.inspect(refs["local:topic"]))
    archive = tmp_path / "archive" / "session"
    session.archive_day(DAY, target=archive)
    session.initialize_day(CalendarDay.parse("2026-09-22"))
    assert session.annotation_snapshot().nodes == ()
    assert "retracted" in str(
        session.archive_view(DAY, root=archive).inspect(refs["local:topic"])
    )


def test_organize_failure_does_not_publish_or_hide_storage_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tinysoul.plugins.session.annotations import store

    session = _session(tmp_path)
    change = OrganizeChange((PRIOR,), nodes=(_node(),))
    assert (
        session.organize(change, _facts()).failure is OrganizeFailureReason.NO_HISTORY
    )
    _record(session)
    assert (
        session.organize(
            OrganizeChange((PRIOR,), nodes=(_node(source="session:turn/future"),)),
            _facts(),
        ).failure
        is OrganizeFailureReason.INVALID_SOURCE
    )
    assert not (session.root / "map.json").exists()
    first = session.organize(change, _facts())
    ref = dict(first.created)["local:topic"]
    before = (session.root / "map.json").read_bytes()
    old = session.annotation_snapshot()

    def fail_write(*args: object, **kwargs: object) -> None:
        raise OSError("test write unavailable")

    monkeypatch.setattr(store, "atomic_write_text", fail_write)
    with pytest.raises(SessionIOError):
        session.organize(
            OrganizeChange((ref,), nodes=(_node(ref, body="replacement"),)), _facts()
        )
    assert session.annotation_snapshot() == old
    assert (session.root / "map.json").read_bytes() == before
    (session.root / "map.json").write_text("{broken", encoding="utf-8")
    with pytest.raises(SessionInvariantError):
        _session(tmp_path)


async def test_current_evidence_keeps_occurrence_without_sealing_and_resolves_after_completion(
    tmp_path: Path,
) -> None:
    session = _session(tmp_path)
    _record(session)
    context = ContextEngineBuilder(system_text="identity").build()
    context.begin_turn("new constraint", turn_id="active")
    await context.open_segments(DAY.value)
    calls = tuple(
        ActionCall(f"call_{index}", "core.reason", {}, index + 1) for index in range(3)
    )
    context.register_action_calls(calls, cycle_id="c")
    framework = ActionFramework(
        "invoke", "batch", RunScope(), "core", turn_id="active", cycle_id="c"
    )
    context.record_execution(ExecutionFact(calls[0], framework, ExecutionState.STARTED))
    context.record_action_result(
        ActionResult.success(
            call_id="call_1",
            invoke_id="i1",
            batch_id="batch",
            action_name="core.reason",
            sequence=2,
            payload={"decision": "accepted"},
        ),
        cycle_id="c",
    )
    facts = context.current_facts()
    assert [item.state for item in context.current_facts().actions] == [
        ExecutionState.STARTED,
        ExecutionState.SETTLED,
        ExecutionState.REQUESTED,
    ]
    assert SessionEvidence(facts).resolve("turn:trace@active#action/0") is None
    result = session.organize(
        OrganizeChange(
            (PRIOR,),
            nodes=(
                replace(
                    _node(),
                    source_refs=(
                        f"turn:trace@active#input/{facts.inputs[0].input_id}",
                        "turn:trace@active#action/1",
                    ),
                ),
            ),
        ),
        facts,
    )
    assert result.failure is None
    ref = dict(result.created)["local:topic"]
    node = session.annotation_snapshot().get(ref)
    assert node is not None and node.source_refs == (
        "session:turn/active#input/0",
        "session:turn/active#action/1",
    )
    assert (
        session.organize(
            OrganizeChange(
                (PRIOR,),
                edges=(_edge("local:bad", ref, "session:turn/active#input/0"),),
            ),
            facts,
        ).failure
        is OrganizeFailureReason.INVALID_SOURCE
    )
    live = replace(session.snapshot_view(DAY), evidence=SessionEvidence(facts))
    assert "active_turn" in str(live.inspect(node.source_refs[1]))
    assert "accepted" in str(live.inspect(node.source_refs[1], query="accepted"))
    assert live.background_snapshot(DAY).refs == (PRIOR,)
    context.record_execution(
        ExecutionFact(calls[0], framework, ExecutionState.CANCELLED)
    )
    completed = context.end_turn()
    await context.close_segments()
    session.record_turn(
        completed,
        day=DAY,
        output=None,
        status=TurnOutcomeStatus.CANCELLED,
        exhausted=False,
    )
    resolved = _items(session.inspect(node.source_refs[1]))[0]
    assert resolved["result"] == {"decision": "accepted"}
    assert "source_state" not in resolved


async def test_update_is_prepared_then_installed_without_expanding_history(
    tmp_path: Path,
) -> None:
    session = _session(tmp_path)
    _record(session)
    provider = UpdatingSessionProvider(
        SessionService(session), SessionOrganizeService(session), _facts
    )
    segment = await provider.open(TurnInfo("active", DAY.value))
    original = segment.render()
    result = session.organize(
        OrganizeChange((PRIOR,), nodes=(_node(body="installed interpretation"),)),
        _facts(),
    )
    ref = dict(result.created)["local:topic"]
    _record(session, "later")
    prepared = await segment.prepare((SessionRefresh(),))
    assert segment.render() == original
    with pytest.raises(ContextInspectRequestError):
        await segment.inspect(ref)
    segment.install(prepared)
    assert "installed interpretation" in str(segment.render())
    assert segment.seal()["refs"] == [PRIOR]
    assert "session:turn/later" not in str(await segment.inspect("session:history"))
    assert not hasattr(SessionService(session), "organize")


def test_annotation_query_uses_turn_scope_and_leaf_scope(tmp_path: Path) -> None:
    session = _session(tmp_path)
    session.record_turn(
        completion(
            "prior",
            ask="user-only-marker",
            working={
                "milestones": [{"state": "blocked", "text": "working-marker"}]
            },
            actions=(
                SyntheticAction(
                    "execution.shell",
                    request={"command": "specific-command-marker"},
                    result={"stdout": "action-result-marker"},
                ),
                SyntheticAction(
                    "workspace.read",
                    status=ActionResultStatus.FAILED,
                    failure_reason="source_unavailable",
                ),
            ),
        ),
        day=DAY,
        output=SessionOutputRecord(text="answer"),
        status=TurnOutcomeStatus.ANSWERED,
        exhausted=False,
    )
    result = session.organize(
        OrganizeChange(
            (PRIOR,),
            nodes=(
                replace(
                    _node("local:turn-topic", source=PRIOR, body="turn topic"),
                    source_refs=(PRIOR, f"{PRIOR}#action/0"),
                ),
                _node(
                    "local:action-topic",
                    source=f"{PRIOR}#action/0",
                    body="action topic",
                ),
            ),
        ),
        _facts(),
    )
    assert result.failure is None
    refs = dict(result.created)

    for query, suffix in (
        ("specific-command-marker", "action/0"),
        ("action-result-marker", "action/0"),
        ("source_unavailable", "action/1"),
        ("working-marker", "working"),
        ("user-only-marker", "input/0"),
    ):
        turn_hits = _items(session.inspect(refs["local:turn-topic"], query=query))
        assert [item["ref"] for item in turn_hits] == [f"{PRIOR}#{suffix}"]
        assert turn_hits == _items(session.inspect(PRIOR, query=query))
        assert _items(session.inspect(str(turn_hits[0]["ref"])))

    leaf_hits = _items(
        session.inspect(refs["local:action-topic"], query="action-result-marker")
    )
    assert [item["ref"] for item in leaf_hits] == [f"{PRIOR}#action/0"]
    for query in ("user-only-marker", "source_unavailable", "working-marker"):
        assert _items(session.inspect(refs["local:action-topic"], query=query)) == []


@pytest.mark.parametrize("status", list(ActionResultStatus))
async def test_active_action_evidence_matches_completed_inspect_and_query(
    tmp_path: Path,
    status: ActionResultStatus,
) -> None:
    session = _session(tmp_path)
    _record(session)
    context = ContextEngineBuilder(system_text="identity").build()
    context.begin_turn("active input", turn_id="active")
    await context.open_segments(DAY.value)
    success = status is ActionResultStatus.SUCCESS
    source = completion(
        "active",
        actions=(
            SyntheticAction(
                "workspace.read",
                request={"link": "workspace:request.md"},
                result={"read": True} if success else {},
                status=status,
                failure_reason="source_unavailable",
                references=("workspace:report.md",) if success else (),
            ),
        ),
    )
    action = source.trace.actions[0]
    context.register_action_calls((action.call,), cycle_id="cycle")
    assert action.result is not None
    context.record_action_result(action.result, cycle_id="cycle")
    provider = UpdatingSessionProvider(
        SessionService(session), SessionOrganizeService(session), context.current_facts
    )
    segment = await provider.open(TurnInfo("active", DAY.value))
    facts = context.current_facts()
    result = session.organize(
        OrganizeChange(
            (PRIOR,),
            nodes=(
                _node(
                    "local:evidence",
                    source="turn:trace@active#action/0",
                ),
            ),
        ),
        facts,
    )
    assert result.failure is None
    ref = dict(result.created)["local:evidence"]
    segment.install(await segment.prepare((SessionRefresh(),)))
    leaf_ref = "session:turn/active#action/0"
    active = _items(await segment.inspect(leaf_ref))[0]
    assert active["source_state"] == "active_turn"
    assert active["outcome"] == status.value
    if success:
        assert active["result"] == {"read": True}
        assert active["references"] == ["workspace:report.md"]
    else:
        assert action.result.failure is not None
        assert active["failure"] == action.result.failure.to_json()
    query = "workspace:report.md" if success else "source_unavailable"
    for target in (ref, leaf_ref):
        hits = _items(await segment.inspect(target, query=query))
        assert [item["ref"] for item in hits] == [leaf_ref]
    assert segment.seal()["refs"] == [PRIOR]
    assert "session:turn/active" not in str(await segment.inspect("session:history"))
    with pytest.raises(ContextInspectRequestError):
        await segment.inspect("session:turn/active")
    assert context.current_facts() == facts
    completed = context.end_turn()
    await segment.close()
    await context.close_segments()
    session.record_turn(
        completed,
        day=DAY,
        output=None,
        status=TurnOutcomeStatus.STOPPED,
        exhausted=False,
    )
    historical = _items(session.inspect(leaf_ref))[0]
    assert active.pop("source_state") == "active_turn"
    assert active == historical
    hits = _items(session.inspect(ref, query=query))
    assert [item["ref"] for item in hits] == [leaf_ref]


async def test_multiple_complete_dialogues_share_background_and_inspection(
    tmp_path: Path,
) -> None:
    session = _session(tmp_path)
    context = ContextEngineBuilder(system_text="identity").build()
    for index in range(3):
        turn_id = f"dialogue_{index}"
        context.begin_turn(f"original request {index}", turn_id=turn_id)
        await context.open_segments(DAY.value)
        scope = RunScope().push(RunLevel.TURN, turn_id)
        bus = SignalBus()
        reason = ActionCall("reason", "core.reason", {}, 1)
        question = ActionCall("question", "core.ask", {}, 2)
        context.register_action_calls((reason, question), cycle_id="c")
        context.record_action_result(
            ActionResult.success(
                call_id="reason",
                invoke_id="reason",
                batch_id="batch",
                action_name="core.reason",
                sequence=1,
                payload={"private_text": "never inline this reasoning"},
            ),
            cycle_id="c",
        )
        bus.emit(
            build_input_append_signal(
                f"extra constraint {index}", scope=scope, source="test"
            )
        )
        await context.consume_signals(bus)
        context.merge_pending_inputs()
        result = ActionResult.success(
            call_id="question",
            invoke_id="question",
            batch_id="batch",
            action_name="core.ask",
            sequence=2,
            payload={"text": "Which strategy?", "options": ["scheduled", "on demand"]},
        )
        context.record_action_result(result, cycle_id="c")
        bus.emit(
            build_input_append_signal(
                "second option", scope=scope, source="test", reply_to=result.result_id
            )
        )
        await context.consume_signals(bus)
        context.merge_pending_inputs()
        followup = ActionCall("followup", "core.ask", {}, 1)
        context.register_action_calls((followup,), cycle_id="followup")
        followup_result = ActionResult.success(
            call_id="followup",
            invoke_id="followup",
            batch_id="followup",
            action_name="core.ask",
            sequence=1,
            payload={"text": "Apply now?", "options": ["yes", "later"]},
        )
        context.record_action_result(followup_result, cycle_id="followup")
        bus.emit(
            build_input_append_signal(
                "keep the original limit", scope=scope, source="test"
            )
        )
        bus.emit(
            build_input_append_signal(
                "yes", scope=scope, source="test", reply_to=followup_result.result_id
            )
        )
        await context.consume_signals(bus)
        context.merge_pending_inputs()
        session.record_turn(
            context.end_turn(),
            day=DAY,
            output=SessionOutputRecord(text=f"confirmed answer {index}"),
            status=TurnOutcomeStatus.ANSWERED,
            exhausted=False,
        )
        await context.close_segments()
    snapshot = session.background_snapshot(DAY)
    assert len(snapshot.items) == 4
    for index, item in enumerate(snapshot.items[1:]):
        interactions = item.content["interactions"]
        assert isinstance(interactions, list)
        projected = [value for value in interactions if isinstance(value, dict)]
        assert [value["role"] for value in projected] == [
            "user.input",
            "agent.reason",
            "user.append",
            "agent.question",
            "user.reply",
            "agent.question",
            "user.append",
            "user.reply",
            "agent.output",
        ]
        assert projected[0]["text"] == f"original request {index}"
        assert projected[2]["text"] == f"extra constraint {index}"
        assert projected[3]["options"] == ["scheduled", "on demand"]
        assert projected[4]["reply_to"] == projected[3]["ref"]
        assert projected[5]["options"] == ["yes", "later"]
        assert "reply_to" not in projected[6]
        assert projected[7]["reply_to"] == projected[5]["ref"]
        assert "never inline" not in str(projected)
        assert projected == [
            value
            for value in _items(session.inspect(item.item_id))
            if value.get("kind") == "interaction"
        ]
    context.register_segment(session_segment_registration(SessionService(session)))
    context.begin_turn("review prior dialogues")
    await context.open_segments(DAY.value)
    stack = context.compose(
        TaskPrompt(guide_blocks=(PromptBlock.from_text("task", "review"),))
    )
    session_messages = tuple(
        message for message in stack.messages if message.label.startswith("session:")
    )
    assert str(session_messages).count("Which strategy?") == 3
    for index in range(3):
        assert str(session_messages).count(f"original request {index}") == 1
        assert str(session_messages).count(f"extra constraint {index}") == 1
        assert str(session_messages).count(f"confirmed answer {index}") == 1
    context.end_turn()
    await context.close_segments()
    _record(session, "giant", text="long input " * 4000)
    bounded = session.background_snapshot(DAY)
    assert (
        sum(len(dumps_json(item.content)) for item in bounded.items)
        <= bounded.max_chars
    )
    giant = next(item for item in bounded.items if item.item_id.endswith("giant"))
    assert giant.content["folded"] is True
    assert "excerpted" in str(giant.content)
    assert "next_continuation" in session.inspect("session:turn/giant")


def test_pagination_depends_on_read_content_and_query_scope(tmp_path: Path) -> None:
    session = _session(tmp_path, page=1024)
    _record(session, text="evidence " * 400)
    result = session.organize(
        OrganizeChange(
            (PRIOR,),
            nodes=(
                _node(body="target " * 250),
                _node("local:other", body="unrelated interpretation"),
            ),
            edges=(
                _edge(
                    "local:related",
                    "local:topic",
                    "local:other",
                    SemanticRelation.SUPPORTS,
                ),
            ),
        ),
        _facts(),
    )
    refs = dict(result.created)
    target, other = refs["local:topic"], refs["local:other"]
    frozen = session.snapshot_view(DAY)
    token = frozen.inspect(target)["next_continuation"]
    factual = frozen.inspect(PRIOR)["next_continuation"]
    assert isinstance(token, str) and isinstance(factual, str)
    session.organize(
        OrganizeChange((other,), nodes=(_node(other, body="independent change"),)),
        _facts(),
    )
    assert session.inspect(target, continuation=token) == frozen.inspect(
        target, continuation=token
    )
    session.organize(
        OrganizeChange((target,), nodes=(_node(target, body="new understanding"),)),
        _facts(),
    )
    with pytest.raises(SessionInspectRequestError):
        session.inspect(target, continuation=token)
    assert session.inspect(PRIOR, continuation=factual) == frozen.inspect(
        PRIOR, continuation=factual
    )
    assert session.inspect(target, query="independent")["items"] == []
    assert "session:turn/prior#input/0" in str(
        session.inspect("session:map", query="evidence")
    )


async def test_map_and_interactions_share_budget_and_reclaim_stays_folded_after_update(
    tmp_path: Path,
) -> None:
    session = _session(tmp_path, budget=5000)
    for index in range(7):
        _record(session, f"t_{index}", text=f"user {index} " + "text " * 80)
    prior = "session:turn/t_0"
    result = session.organize(
        OrganizeChange(
            (prior,),
            nodes=tuple(
                _node(
                    f"local:n_{index}",
                    source=prior,
                    body=f"topic {index} " + "detail " * 300,
                )
                for index in range(12)
            ),
        ),
        _facts(),
    )
    assert result.failure is None
    provider = UpdatingSessionProvider(
        SessionService(session), SessionOrganizeService(session), _facts
    )
    segment = await provider.open(TurnInfo("active", DAY.value))
    original = segment.render()
    snapshot = session.background_snapshot(DAY)
    assert sum(len(dumps_json(item.content)) for item in snapshot.items) <= 5000
    assert len([item for item in snapshot.items if "interactions" in item.content]) >= 2
    assert segment.reclaim(10000).reclaimed_chars > 0
    folded = segment.render()
    assert len(str(folded)) < len(str(original))
    segment.install(await segment.prepare((SessionRefresh(),)))
    assert len(str(segment.render())) < len(str(original))
    assert "session:topics" in str(segment.render())
    assert "user 0" in str(await segment.inspect(prior))
