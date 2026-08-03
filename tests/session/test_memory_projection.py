from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from tinysoul.maintenance import BusinessDay
from tinysoul.session import SessionEngine, SessionSettings
from tinysoul.session.models import SessionOutputRecord

from .synthetic import SyntheticAction, completion


DAY = BusinessDay.parse("2026-07-12")
ZONE = ZoneInfo("Asia/Shanghai")


def test_memory_projection_expands_summary_to_chronological_turn_facts(
    tmp_path: Path,
) -> None:
    session = _session(tmp_path, background_max_chars=512)
    starts = (
        datetime(2026, 7, 12, 20, 0, tzinfo=ZONE),
        datetime(2026, 7, 12, 9, 0, tzinfo=ZONE),
        datetime(2026, 7, 12, 14, 0, tzinfo=ZONE),
    )
    for index, started_at in enumerate(starts):
        session.record_turn(
            completion(
                f"turn_{index}",
                ask=f"question {index}",
                received_at=started_at.timestamp(),
                working={"milestone": f"milestone {index}"},
                background_links=("home:agent@AGENT",),
                actions=(SyntheticAction("workspace.read"),),
            ),
            output=SessionOutputRecord(
                text=f"answer {index} " + "x" * 700,
                references=("workspace:source.md",),
            ),
            exhausted=False,
            day=DAY,
        )

    archive = tmp_path / "archive" / "session"
    session.archive_day(DAY, target=archive)
    projection = session.memory_facts(DAY, root=archive)

    assert tuple(fact.ref for fact in projection.facts) == (
        "session:turn/turn_1",
        "session:turn/turn_2",
        "session:turn/turn_0",
    )
    first = projection.facts[0]
    assert first.user_inputs == ("question 1",)
    assert first.working == {"milestone": "milestone 1"}
    assert first.actions[0]["action"] == "workspace.read"
    assert "trace" not in first.to_json()
    assert "trace_digest" not in first.to_json()


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
