from __future__ import annotations

from pathlib import Path

from tinysoul.endpoint import (
    EndpointEventBuffer,
    EndpointEventJournal,
    EndpointSettings,
)
from tinysoul.infra.json import JsonObject, to_json_object
from tinysoul.runtime import ObservationEvent, ObservationLevel


def test_journal_survives_restart_and_deep_replay(tmp_path: Path) -> None:
    root = tmp_path / "events"
    journal = EndpointEventJournal(
        root,
        max_segment_bytes=4 * 1024,
        max_total_bytes=64 * 1024,
    )
    buffer = EndpointEventBuffer(
        capacity=2,
        max_bytes=64 * 1024,
        page_bytes=64 * 1024,
        journal=journal,
    )
    for index in range(1, 6):
        buffer.write(_event(f"event.{index}", payload={"n": index}))

    hot = buffer.replay(after=0, mode=ObservationLevel.MODEL, limit=200)
    assert [event.sequence for event in hot.events] == [1, 2, 3, 4, 5]
    assert hot.gap is False

    restarted = EndpointEventJournal(
        root,
        max_segment_bytes=4 * 1024,
        max_total_bytes=64 * 1024,
    )
    assert restarted.latest_sequence == 5
    restored = EndpointEventBuffer(
        capacity=2,
        max_bytes=64 * 1024,
        page_bytes=64 * 1024,
        journal=restarted,
    )
    assert restored.latest_sequence == 5
    page = restored.replay(after=0, mode=ObservationLevel.MODEL, limit=200)
    assert [event.sequence for event in page.events] == [1, 2, 3, 4, 5]
    assert [event.payload["n"] for event in page.events] == [1, 2, 3, 4, 5]
    assert page.gap is False
    assert restored.journal_status()["enabled"] is True
    assert restored.journal_status()["degraded"] is False


def test_journal_trim_reports_gap_for_evicted_prefix(tmp_path: Path) -> None:
    root = tmp_path / "events"
    journal = EndpointEventJournal(
        root,
        max_segment_bytes=400,
        max_total_bytes=900,
    )
    buffer = EndpointEventBuffer(
        capacity=1,
        max_bytes=1024,
        page_bytes=64 * 1024,
        journal=journal,
    )
    for index in range(1, 12):
        buffer.write(
            _event(
                f"event.{index}",
                payload={"n": index, "pad": "x" * 80},
            )
        )

    oldest = journal.oldest_sequence
    assert oldest is not None
    assert oldest > 1
    page = buffer.replay(after=0, mode=ObservationLevel.MODEL, limit=200)
    assert page.gap is True
    assert page.events
    assert page.events[0].sequence == oldest


def test_journal_write_failure_degrades_without_breaking_memory(
    tmp_path: Path,
) -> None:
    root = tmp_path / "events"
    journal = EndpointEventJournal(
        root,
        max_segment_bytes=4 * 1024,
        max_total_bytes=64 * 1024,
    )
    buffer = EndpointEventBuffer(
        capacity=8,
        max_bytes=64 * 1024,
        page_bytes=64 * 1024,
        journal=journal,
    )
    buffer.write(_event("event.1"))
    # Corrupt continuity so the next append fails and degrades the journal.
    journal._latest_sequence = 99  # noqa: SLF001
    buffer.write(_event("event.2"))
    assert journal.degraded is True
    page = buffer.replay(after=0, mode=ObservationLevel.MODEL, limit=200)
    assert [event.sequence for event in page.events] == [1, 2]
    assert page.gap is False


def test_replay_page_stops_on_byte_budget(tmp_path: Path) -> None:
    journal = EndpointEventJournal(
        tmp_path / "events",
        max_segment_bytes=64 * 1024,
        max_total_bytes=256 * 1024,
    )
    buffer = EndpointEventBuffer(
        capacity=32,
        max_bytes=256 * 1024,
        page_bytes=200,
        journal=journal,
    )
    for index in range(1, 6):
        buffer.write(_event(f"event.{index}", payload={"pad": "y" * 80}))
    page = buffer.replay(after=0, mode=ObservationLevel.MODEL, limit=200)
    assert len(page.events) >= 1
    assert len(page.events) < 5
    assert page.next_sequence == page.events[-1].sequence


def test_endpoint_settings_reject_invalid_journal_bounds() -> None:
    try:
        EndpointSettings(
            token="x" * 32,
            journal_segment_bytes=100,
            journal_total_bytes=50,
        )
    except Exception as exc:
        assert "journal_segment_bytes" in str(exc)
    else:
        raise AssertionError("expected journal bound validation failure")


def _event(
    name: str,
    *,
    payload: JsonObject | None = None,
) -> ObservationEvent:
    return ObservationEvent(
        name=name,
        level=ObservationLevel.MODEL,
        source="test",
        message=name,
        payload=to_json_object(payload or {}),
    )
