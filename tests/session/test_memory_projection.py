"""Session-owned facts projection for Memory Maintenance."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from tinysoul.context import TurnSummary
from tinysoul.loop import BusinessDay
from tinysoul.session import SessionEngine, SessionSettings


DAY = BusinessDay.parse("2026-07-12")
ZONE = ZoneInfo("Asia/Shanghai")


def test_memory_projection_recursively_expands_summary_to_unique_turn_facts(
    tmp_path: Path,
) -> None:
    session = _session(tmp_path, background_max_chars=900)
    starts = (
        datetime(2026, 7, 12, 20, 0, tzinfo=ZONE),
        datetime(2026, 7, 12, 9, 0, tzinfo=ZONE),
        datetime(2026, 7, 12, 14, 0, tzinfo=ZONE),
    )
    for index, started_at in enumerate(starts):
        session.record_turn(
            summary=TurnSummary(
                turn_id=f"turn_{index}",
                inputs=(
                    {
                        "input_id": f"input_{index}",
                        "text": f"complete question {index}",
                        "received_at": started_at.timestamp(),
                        "merged": True,
                    },
                ),
                working={"milestone": f"milestone {index}"},
                background_links=("home:agent@AGENT",),
                trace_digest={"entry_count": index + 1},
            ),
            output={
                "text": f"complete answer {index} " + "x" * 700,
                "references": ["home:agent@AGENT"],
            },
            exhausted=False,
            day=DAY,
        )

    history_items = session.inspect_history().get("items")
    assert isinstance(history_items, list)
    assert any(
        isinstance(item, dict) and item.get("kind") == "summary"
        for item in history_items
    )
    archive = tmp_path / "archive" / "session"
    session.archive_day(DAY, target=archive)

    projection = session.memory_facts(DAY, root=archive)

    assert tuple(fact.ref for fact in projection.facts) == (
        "session:turn/turn_1",
        "session:turn/turn_2",
        "session:turn/turn_0",
    )
    assert projection.revision == 3
    assert projection.has_facts
    first = projection.facts[0]
    assert first.user_inputs == ("complete question 1",)
    assert first.working == {"milestone": "milestone 1"}
    assert first.answer.endswith("x" * 700)
    assert first.references == ("home:agent@AGENT",)
    assert first.trace_digest == {"entry_count": 2}
    assert "trace" not in first.to_json()


def test_memory_projection_for_empty_archive_has_no_facts(tmp_path: Path) -> None:
    session = _session(tmp_path)
    archive = tmp_path / "archive" / "session"
    session.archive_day(DAY, target=archive)

    projection = session.memory_facts(DAY, root=archive)

    assert not projection.has_facts
    assert projection.facts == ()


def _session(tmp_path: Path, *, background_max_chars: int = 24000) -> SessionEngine:
    session = SessionEngine(
        SessionSettings(
            root=tmp_path / "runtime" / "session",
            background_max_chars=background_max_chars,
            summary_watermark_ratio=0.60,
            summary_target_ratio=0.40,
            min_recent_turns=1,
        )
    )
    session.initialize_day(DAY)
    return session
