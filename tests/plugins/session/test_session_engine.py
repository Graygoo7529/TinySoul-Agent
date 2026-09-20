from __future__ import annotations

from tests.action_helpers import builtin_catalog

from tinysoul.kernel.loop.outcomes import TurnOutcomeStatus

from pathlib import Path

import pytest

from tinysoul.kernel.action import (
    ActionCall,
    ActionExecution,
    ActionExecutionContext,
    ActionFramework,
    ActionResultStatus,
)
from tinysoul.kernel.action.catalog.loader import ActionCatalogLoader
from tinysoul.infra import JsonObject, JsonValue
from tinysoul.infra.time import CalendarDay
from tinysoul.runtime import RunScope
from tinysoul.plugins.session.services import SessionService
from tinysoul.plugins.session.runtime_bridge import RuntimeSessionBridge
from tinysoul.plugins.session import SessionEngine, SessionSettings
from tinysoul.kernel.context import ContextEngineBuilder
from tinysoul.kernel.context.actions import ContextInspectExecutor
from tinysoul.kernel.context.runtime_bridge import RuntimeContextBridge
from tinysoul.plugins.session.projection import session_segment_registration
from tinysoul.plugins.session.errors import (
    SessionInspectFailureReason,
    SessionInspectRequestError,
)
from tinysoul.plugins.session.records.models import (
    SessionOutputRecord,
)
from tinysoul.plugins.session.records.store import SessionStore

from .synthetic import SyntheticAction, completion

DAY = CalendarDay.parse("2026-07-25")


def test_background_is_clean_and_inspect_expands_turn_actions(tmp_path: Path) -> None:
    session = _session(tmp_path)
    session.record_turn(
        completion(
            "turn_actions",
            ask="create a report",
            actions=(
                SyntheticAction(
                    "workspace.compose",
                    request={"link": "workspace:report.md"},
                    result={"written": True},
                    references=("workspace:report.md",),
                ),
                SyntheticAction(
                    "web.search",
                    status=ActionResultStatus.FAILED,
                    result={"attempted": True},
                    failure_reason="provider_unavailable",
                ),
            ),
        ),
        day=DAY,
        output=SessionOutputRecord(
            text="report created",
            references=("workspace:report.md",),
        ),
        status=TurnOutcomeStatus.ANSWERED,
        exhausted=False,
    )

    background = session.background_snapshot(DAY)
    assert background.items[0].content["total_turns"] == 1
    item = background.items[1].content
    assert item["ref"] == "session:turn/turn_actions"
    assert item["status"] == "answered"
    assert item["user_ask"] == ["create a report"]
    assert item["answer"] == "report created"
    locator = _json_object_list(item["references"])[0]
    assert locator["link"] == "workspace:report.md" and locator["source_day"] == str(
        DAY
    )
    assert _json_object(item["actions"])["count"] == 2
    assert "trace" not in item
    assert "revision" not in item

    turn = session.inspect("session:turn/turn_actions")
    content = _json_object_list(turn["items"])
    turn_actions = next(item for item in content if item.get("title") == "Actions")
    turn_action_ref = turn_actions["ref"]
    assert isinstance(turn_action_ref, str)
    assert turn_action_ref.endswith("#actions")

    actions = session.inspect("session:turn/turn_actions#actions")
    headers = _json_object_list(actions["items"])
    assert [header["clue"] for header in headers] == ["success", "failed"]
    failed = _json_object_list(session.inspect(str(headers[1]["ref"]))["items"])[0]
    failure = _json_object(failed["failure"])
    assert failure["reason"] == "provider_unavailable"
    assert failed["result"] == {"attempted": True}

    leaf_ref = headers[0]["ref"]
    assert isinstance(leaf_ref, str)
    leaf = session.inspect(leaf_ref)
    detail = _json_object_list(leaf["items"])
    assert detail[0]["request"] == {"link": "workspace:report.md"}
    assert detail[0]["result"] == {"written": True}


def test_inspect_uses_opaque_continuation_for_oversized_content(
    tmp_path: Path,
) -> None:
    session = _session(tmp_path, inspect_max_chars=1024)
    session.record_turn(
        completion("turn_large", ask="q" * 3000),
        day=DAY,
        output=SessionOutputRecord(text="a" * 3000),
        status=TurnOutcomeStatus.ANSWERED,
        exhausted=False,
    )

    first = session.inspect("session:turn/turn_large#input/0")
    token = first["next_continuation"]
    assert isinstance(token, str) and token.startswith("v1.")
    assert "content_fragment" in first
    assert "cursor" not in first
    second = session.inspect(
        "session:turn/turn_large#input/0",
        continuation=token,
    )
    fragment = _json_object(second["content_fragment"])
    assert fragment["text"]

    with pytest.raises(SessionInspectRequestError) as mismatch:
        session.inspect(None, continuation=token)
    assert mismatch.value.reason is SessionInspectFailureReason.INVALID_CONTINUATION


def test_map_preserves_all_facts_when_background_is_bounded(
    tmp_path: Path,
) -> None:
    session = _session(tmp_path, background_max_chars=512)
    for index in range(3):
        session.record_turn(
            completion(f"turn_{index}", ask=f"question {index}"),
            day=DAY,
            output=SessionOutputRecord(text="x" * 1000),
            status=TurnOutcomeStatus.ANSWERED,
            exhausted=False,
        )

    root = session.inspect()
    nodes = _json_object_list(root["items"])
    turns = [node for node in nodes if node["kind"] == "child"]
    assert [node["ref"] for node in turns] == [
        f"session:turn/turn_{index}" for index in range(3)
    ]
    edges = [node for node in nodes if node["kind"] == "relation"]
    assert len([edge for edge in edges if edge["relation"] == "precedes"]) == 2
    assert all(edge["basis"] == "fact" for edge in edges)
    assert not (session.root / "summaries").exists()

    background = session.background_snapshot(DAY)
    head = background.items[0].content
    assert head["ref"] == "session:map"
    assert head["total_turns"] == 3 and head["omitted_turns"] == 3
    from tinysoul.infra.json import dumps_json

    assert sum(len(dumps_json(item.content)) for item in background.items) <= 512


def test_reconcile_adopts_an_uncommitted_turn_record(tmp_path: Path) -> None:
    session = _session(tmp_path)
    record = completion("turn_orphan")
    from tinysoul.plugins.session.completion import project_turn_record

    store = SessionStore(root=session.root)
    store.save_record_if_absent(
        project_turn_record(
            record,
            day=DAY,
            output=None,
            status=TurnOutcomeStatus.EXHAUSTED,
            exhausted=True,
        )
    )

    result = session.reconcile_active()
    assert result.adopted_turn_refs == ("session:turn/turn_orphan",)
    nodes = _json_object_list(session.inspect()["items"])
    assert nodes[0]["ref"] == "session:turn/turn_orphan"


def test_inspect_rejects_record_outside_authoritative_graph(tmp_path: Path) -> None:
    session = _session(tmp_path)
    for turn_id in ("turn_root_1", "turn_root_2"):
        session.record_turn(
            completion(turn_id),
            day=DAY,
            output=None,
            status=TurnOutcomeStatus.EXHAUSTED,
            exhausted=True,
        )
    from tinysoul.plugins.session.completion import project_turn_record

    orphan_ref = "session:turn/not_indexed"
    SessionStore(root=session.root).save_record_if_absent(
        project_turn_record(
            completion("not_indexed"),
            day=DAY,
            output=None,
            status=TurnOutcomeStatus.STOPPED,
            exhausted=False,
        )
    )

    with pytest.raises(SessionInspectRequestError) as raised:
        session.inspect(orphan_ref)

    assert raised.value.reason is SessionInspectFailureReason.UNKNOWN_REF


async def test_session_inspect_executor_returns_foldable_origin(
    tmp_path: Path,
) -> None:
    session = _session(tmp_path, inspect_max_chars=1024)
    session.record_turn(
        completion("turn_executor", ask="q" * 3000),
        day=DAY,
        output=None,
        status=TurnOutcomeStatus.EXHAUSTED,
        exhausted=True,
    )
    catalog = builtin_catalog()
    action = catalog.get_action("core.context.inspect")
    execution = ActionExecution(
        action=action,
        call=ActionCall(
            call_id="call_inspect",
            action_name=action.name,
            params={"ref": "session:turn/turn_executor"},
            sequence=1,
        ),
        framework=ActionFramework(
            invoke_id="invoke_inspect",
            batch_id="batch_inspect",
            scope=RunScope(),
            domain="core",
        ),
    )
    context = ContextEngineBuilder(system_text="identity").build()
    context.register_segment(session_segment_registration(SessionService(session)))
    context.begin_turn("inspect prior turn")
    await context.open_segments(DAY.value)
    result = await ContextInspectExecutor(
        context,
        runtime_bridge=RuntimeContextBridge(),
    ).execute(execution, ActionExecutionContext())
    await context.close_segments()
    assert result.status is ActionResultStatus.SUCCESS
    assert result.trace_projection is not None
    assert result.trace_projection.origin_refs == ("session:turn/turn_executor",)
    assert "next_continuation" in result.payload
    assert "next_continuation" not in result.trace_projection.canonical_payload


async def test_session_segment_is_fixed_and_seals_references_not_history(
    tmp_path: Path,
) -> None:
    from tinysoul.kernel.context.errors import ContextInspectRequestError

    session = _session(tmp_path)
    session.record_turn(
        completion("prior", ask="private prior body"),
        day=DAY,
        output=SessionOutputRecord(text="prior answer"),
        status=TurnOutcomeStatus.ANSWERED,
        exhausted=False,
    )
    context = ContextEngineBuilder(system_text="identity").build()
    context.register_segment(session_segment_registration(SessionService(session)))
    context.begin_turn("next")
    await context.open_segments(DAY.value)
    sealed = context.segment_snapshot("session")
    assert sealed["refs"] == ["session:turn/prior"]
    assert "private prior body" not in str(sealed)
    assert (await context.inspect("session:map"))["kind"] == "session_map"
    with pytest.raises(ContextInspectRequestError):
        await context.inspect("session:turn/not_in_view")
    session.record_turn(
        completion("later"),
        day=DAY,
        output=None,
        status=TurnOutcomeStatus.STOPPED,
        exhausted=False,
    )
    assert context.segment_snapshot("session") == sealed
    fixed_map = await context.inspect("session:map")
    assert "session:turn/prior" in str(fixed_map)
    assert "session:turn/later" not in str(fixed_map)
    with pytest.raises(ContextInspectRequestError):
        await context.inspect("session:turn/later")
    await context.close_segments()


def test_session_map_relates_occurrences_and_shared_resources(tmp_path: Path) -> None:
    session = _session(tmp_path)
    session.record_turn(
        completion(
            "mapped",
            actions=(
                SyntheticAction(
                    "workspace.read",
                    result={"read": True},
                    references=("workspace:report.md",),
                ),
                SyntheticAction(
                    "workspace.read",
                    result={"read": True},
                    references=("workspace:report.md",),
                ),
            ),
        ),
        day=DAY,
        output=None,
        status=TurnOutcomeStatus.STOPPED,
        exhausted=False,
    )
    nodes = _json_object_list(session.inspect("session:turn/mapped")["items"])
    resources = [node for node in nodes if node["kind"] == "child" and "#resource/" in str(node["ref"])]
    actions = _json_object_list(session.inspect("session:turn/mapped#actions")["items"])
    edges = [node for node in nodes if node["kind"] == "relation"]
    assert len(resources) == 1
    assert len({action["ref"] for action in actions}) == 2
    assert all(
        any(
            edge["relation"] == "contains" and edge["target"] == action["ref"]
            for edge in edges
        )
        for action in actions
    )
    assert len([edge for edge in edges if edge["relation"] == "references"]) == 2
    assert all(edge["basis"] == "fact" for edge in edges)


def test_map_rebuilds_replies_and_preserves_historical_resource_binding(
    tmp_path: Path,
) -> None:
    from dataclasses import replace
    from tinysoul.kernel.context import ContextTurnInput

    session = _session(tmp_path)
    source = completion(
        "dialogue",
        working={"milestones": [{"state": "blocked", "text": "Needs input"}]},
        actions=(
            SyntheticAction("core.ask", result={"text": "Which file?"}),
            SyntheticAction("core.reason", request={"intent": "Compare inputs"}),
            SyntheticAction(
                "workspace.read",
                result={"read": True},
                references=("workspace:report.md",),
            ),
        ),
    )
    source = replace(
        source,
        inputs=(
            source.inputs[0],
            ContextTurnInput(
                text="Report", received_at=2, input_id="reply", reply_to="result_0"
            ),
            ContextTurnInput(text="Keep it brief", received_at=3, input_id="append"),
        ),
    )
    session.record_turn(
        source, day=DAY, output=None, status=TurnOutcomeStatus.STOPPED, exhausted=False
    )
    # No graph database is needed: a fresh owner derives the same relation.
    rebuilt = _session(tmp_path)
    nodes = _json_object_list(rebuilt.inspect("session:turn/dialogue")["items"])
    reply = next(node for node in nodes if node.get("relation") == "replies_to")
    assert reply["source"] == "session:turn/dialogue#input/1"
    assert reply["target"] == "session:turn/dialogue#action/0"
    detail = _json_object_list(rebuilt.inspect(str(reply["source"]))["items"])[0]
    assert detail["text"] == "Report"
    working = _json_object_list(
        rebuilt.inspect("session:turn/dialogue#working")["items"]
    )[0]
    assert working["working"] == source.working
    locator = next(node for node in nodes if node["kind"] == "child" and "#resource/" in str(node["ref"]))
    resource = _json_object_list(rebuilt.inspect(str(locator["ref"]))["items"])[0]
    assert resource["source_day"] == str(DAY)
    archive = (tmp_path / "archive" / "session").resolve()
    rebuilt.archive_day(DAY, target=archive)
    next_day = CalendarDay.parse("2026-07-26")
    rebuilt.initialize_day(next_day)
    with pytest.raises(SessionInspectRequestError):
        rebuilt.inspect(str(resource["ref"]))
    historical = rebuilt.archive_view(DAY, root=archive)
    assert (
        _json_object_list(historical.inspect(str(resource["ref"]))["items"])[0]
        == resource
    )


def test_archive_snapshot_contains_only_validated_roots(tmp_path: Path) -> None:
    session = _session(tmp_path)
    session.record_turn(
        completion("turn_archive"),
        day=DAY,
        output=SessionOutputRecord(text="done"),
        status=TurnOutcomeStatus.ANSWERED,
        exhausted=False,
    )
    archive = (tmp_path / "archive" / "session").resolve()
    session.archive_day(DAY, target=archive)
    snapshot = session.archive_snapshot(DAY, root=archive)
    assert snapshot.refs == ("session:turn/turn_archive",)
    assert snapshot.has_facts


def test_hierarchical_map_query_is_scoped_and_continuation_bound(tmp_path: Path) -> None:
    session = _session(tmp_path, inspect_max_chars=2048)
    for index in range(35):
        session.record_turn(completion(f"t_{index}", ask=f"needle {index}: " + "body " * 80),
                            day=DAY, output=None, status=TurnOutcomeStatus.STOPPED, exhausted=False)
    root = _json_object_list(session.inspect()["items"])
    groups = [str(item["ref"]) for item in root if item["kind"] == "child"]
    assert groups == ["session:map/0", "session:map/16", "session:map/32"]
    refs: list[str] = []
    edges: list[tuple[str, str]] = []
    for group in groups:
        token = None
        while True:
            page = session.inspect(group, continuation=token)
            refs.extend(str(item["ref"]) for item in _json_object_list(page["items"])
                        if item.get("kind") == "child")
            edges.extend(
                (str(item["source"]), str(item["target"]))
                for item in _json_object_list(page["items"])
                if item.get("relation") == "precedes"
            )
            token = page.get("next_continuation")
            if token is None:
                break
            assert isinstance(token, str)
    assert refs == [f"session:turn/t_{index}" for index in range(35)]
    assert edges == list(zip(refs, refs[1:]))
    found = _json_object_list(session.inspect("session:map/16", query="needle 22:")["items"])
    assert [item["ref"] for item in found] == ["session:turn/t_22#input/0"]
    assert session.inspect("session:map/0", query="needle 22:")["items"] == []
    result = session.inspect("session:map", query="needle")
    token = result["next_continuation"]
    assert isinstance(token, str)
    with pytest.raises(SessionInspectRequestError):
        session.inspect("session:map", query="another", continuation=token)


async def test_session_reclaim_is_governed_by_its_own_watermark(tmp_path: Path) -> None:
    from tinysoul.plugins.session.projection import SessionSegmentProvider
    from tinysoul.kernel.context.segments import TurnInfo

    session = _session(tmp_path, background_max_chars=4000)
    provider = SessionSegmentProvider(SessionService(session))
    minimal = await provider.open(TurnInfo("empty", DAY.value))
    assert minimal.reclaim(100000).reclaimed_chars == 0
    for index in range(8):
        session.record_turn(completion(f"t_{index}", ask="question " * 120), day=DAY,
                            output=None, status=TurnOutcomeStatus.STOPPED, exhausted=False)
    view = await provider.open(TurnInfo("next", DAY.value))
    before = view.seal()
    assert view.reclaim(100000).reclaimed_chars > 0
    assert view.reclaim(100000).reclaimed_chars == 0
    assert view.seal() == before
    assert "question" in str(await view.inspect("session:turn/t_0#input/0"))


def _session(
    tmp_path: Path,
    *,
    background_max_chars: int = 24000,
    inspect_max_chars: int = 8000,
) -> SessionEngine:
    session = SessionEngine(
        SessionSettings(
            root=tmp_path / "runtime" / "session",
            background_max_chars=background_max_chars,
            inspect_max_chars=inspect_max_chars,
        )
    )
    session.initialize_day(DAY)
    return session


def _json_object(value: JsonValue) -> JsonObject:
    assert isinstance(value, dict)
    return value


def _json_object_list(value: JsonValue) -> list[JsonObject]:
    assert isinstance(value, list)
    return [_json_object(item) for item in value]
