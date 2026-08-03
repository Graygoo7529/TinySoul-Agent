"""Date-scoped Memory Maintenance tests."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

import tinysoul.memory.store as store_module
from tinysoul.home import AgentHomeEngineBuilder, AgentHomeSettings
from tinysoul.infra.json import JsonObject
from tinysoul.llm import JsonAnswer, RawResponse, TaskCall, TaskProfile, TaskResult
from tinysoul.maintenance import BusinessDay
from tinysoul.memory import (
    LLMMemoryConsolidator,
    MemoryLink,
    MemoryConsolidationRequest,
    MemoryConsolidationResult,
    MemoryEngine,
    MemoryIOError,
    MemoryInvariantError,
    MemoryMaintenanceFailure,
    MemoryMaintenanceSettings,
    MemoryMaintenanceSkipReason,
    MemoryMaintenanceStatus,
    MemorySettings,
    parse_memory_settings,
)
from tinysoul.runtime import (
    ObservationEmitter,
    ObservationEvent,
    ObservationLevel,
    RunLevel,
    RunScope,
)
from tinysoul.session import SessionMemoryFact, SessionMemoryFactsProjection


DAY = BusinessDay.parse("2026-07-12")
ZONE = ZoneInfo("Asia/Shanghai")


def test_memory_maintenance_uses_ordered_sources_and_renders_one_daily_body(
    tmp_path: Path,
) -> None:
    known = tmp_path / "home" / "what" / "concept" / "known.md"
    known.parent.mkdir(parents=True)
    known.write_text("known", encoding="utf-8")
    memory = _memory(tmp_path)
    projection = _projection(
        _fact("first <home:what@concept/known>", 9),
        _fact("second", 14),
        _fact("third", 20),
    )
    consolidator = _CapturingConsolidator(
        "## Durable facts\n\n- retained <home:what@concept/known>"
    )
    assert memory.maintenance_eligible(projection)

    outcome = memory.run_maintenance(
        projection=projection,
        consolidator=consolidator,
        timezone="Asia/Shanghai",
    )

    assert outcome.status is MemoryMaintenanceStatus.COMPLETED
    assert outcome.fact_count == 3
    assert outcome.document_digest
    request = consolidator.requests[0]
    joined = "\n".join(request.sources)
    assert joined.index("first") < joined.index("second") < joined.index("third")
    assert request.home_link_hints == ("home:what@concept/known",)
    assert "home:what@concept/known" in request.allowed_home_links
    assert _target(tmp_path).read_text(encoding="utf-8") == (
        "# 2026-07-12\n\n"
        "## Durable facts\n\n"
        "- retained <home:what@concept/known>\n"
    )
    assert not (tmp_path / "runtime" / "home" / "memory").exists()
    assert not memory.maintenance_eligible(projection)


def test_memory_maintenance_observations_are_verbose_and_content_free(
    tmp_path: Path,
) -> None:
    observations = _RecordingObservations()
    memory = _memory(tmp_path, observations=observations)
    scope = RunScope().push(RunLevel.MODULE, "memory_maintenance")

    outcome = memory.run_maintenance(
        projection=_projection(_fact("private Session fact", 9)),
        consolidator=_CapturingConsolidator("- private consolidated Memory"),
        timezone="Asia/Shanghai",
        scope=scope,
    )

    assert outcome.status is MemoryMaintenanceStatus.COMPLETED
    assert [event.name for event in observations.events] == [
        "memory.maintenance.started",
        "memory.maintenance.completed",
    ]
    assert all(
        event.level is ObservationLevel.VERBOSE
        for event in observations.events
    )
    assert all(event.scope == scope for event in observations.events)
    completed = observations.events[-1]
    assert completed.payload["target_day"] == str(DAY)
    assert completed.payload["fact_count"] == 1
    assert "private Session fact" not in repr(observations.events)
    assert "private consolidated Memory" not in repr(observations.events)
    assert str(tmp_path) not in repr(observations.events)


def test_missing_and_empty_session_skip_without_touching_memory(tmp_path: Path) -> None:
    observations = _RecordingObservations()
    memory = _memory(tmp_path, observations=observations)
    target = _target(tmp_path)
    target.parent.mkdir(parents=True)
    target.write_text("existing bytes stay unchanged", encoding="utf-8")

    missing = memory.run_maintenance(
        projection=None,
        consolidator=None,
        timezone="Asia/Shanghai",
        target_day=DAY,
    )
    empty = memory.run_maintenance(
        projection=_projection(),
        consolidator=None,
        timezone="Asia/Shanghai",
    )

    assert missing.status is MemoryMaintenanceStatus.SKIPPED
    assert missing.skip_reason is MemoryMaintenanceSkipReason.SESSION_NOT_FOUND
    assert empty.status is MemoryMaintenanceStatus.SKIPPED
    assert empty.skip_reason is MemoryMaintenanceSkipReason.SESSION_EMPTY
    assert target.read_text(encoding="utf-8") == "existing bytes stay unchanged"
    assert [event.name for event in observations.events] == [
        "memory.maintenance.started",
        "memory.maintenance.skipped",
        "memory.maintenance.started",
        "memory.maintenance.skipped",
    ]
    assert observations.events[1].payload["skip_reason"] == "session_not_found"
    assert observations.events[3].payload["skip_reason"] == "session_empty"


def test_existing_free_form_memory_is_one_source_and_is_rewritten(
    tmp_path: Path,
) -> None:
    memory = _memory(tmp_path)
    target = _target(tmp_path)
    target.parent.mkdir(parents=True)
    target.write_text(
        "Legacy memory without the current heading\n\n## Notes\n\n- old fact",
        encoding="utf-8",
    )
    consolidator = _CapturingConsolidator(
        "## Reorganized\n\n- old fact\n- new fact"
    )

    outcome = memory.run_maintenance(
        projection=_projection(_fact("new fact", 9)),
        consolidator=consolidator,
        timezone="Asia/Shanghai",
    )

    assert outcome.status is MemoryMaintenanceStatus.COMPLETED
    request = consolidator.requests[0]
    assert any("Legacy memory" in source for source in request.sources)
    assert any('"kind":"existing_memory"' in source for source in request.sources)
    assert target.read_text(encoding="utf-8") == (
        "# 2026-07-12\n\n## Reorganized\n\n- old fact\n- new fact\n"
    )


def test_automatic_memory_maintenance_validates_then_skips_existing_target(
    tmp_path: Path,
) -> None:
    memory = _memory(tmp_path)
    target = _target(tmp_path)
    target.parent.mkdir(parents=True)
    existing = "arbitrary readable Markdown"
    target.write_text(existing, encoding="utf-8")
    consolidator = _CapturingConsolidator("must not replace")

    outcome = memory.run_maintenance(
        projection=_projection(_fact("new session fact", 9)),
        consolidator=consolidator,
        timezone="Asia/Shanghai",
        rewrite_existing=False,
    )

    assert outcome.status is MemoryMaintenanceStatus.SKIPPED
    assert outcome.skip_reason is MemoryMaintenanceSkipReason.MEMORY_EXISTS
    assert consolidator.requests == []
    assert target.read_text(encoding="utf-8") == existing

    target.write_text("   \n", encoding="utf-8")
    with pytest.raises(MemoryInvariantError, match="empty"):
        memory.maintenance_eligible(_projection(_fact("new session fact", 9)))
    with pytest.raises(MemoryInvariantError, match="empty"):
        memory.run_maintenance(
            projection=_projection(_fact("new session fact", 9)),
            consolidator=consolidator,
            timezone="Asia/Shanghai",
            rewrite_existing=False,
        )


def test_llm_consolidator_reduces_and_retries_with_bounded_link_hints(
    tmp_path: Path,
) -> None:
    known = tmp_path / "home" / "what" / "concept" / "known.md"
    unused = tmp_path / "home" / "what" / "concept" / "unused.md"
    known.parent.mkdir(parents=True)
    known.write_text("known", encoding="utf-8")
    unused.write_text("unused", encoding="utf-8")
    memory = _memory(
        tmp_path,
        maintenance=MemoryMaintenanceSettings(
            chunk_max_chars=512,
            source_max_chars=10000,
            link_hints_max_chars=64,
            max_calls=20,
            validation_retries=2,
        ),
    )
    runner = _MemoryTaskRunner(repair_link=True)

    outcome = memory.run_maintenance(
        projection=_projection(
            _fact("x" * 1800 + " <home:what@concept/known>", 9)
        ),
        consolidator=LLMMemoryConsolidator(runner),
        timezone="Asia/Shanghai",
        scope=RunScope().push(RunLevel.PROGRAM, "program"),
    )

    assert outcome.status is MemoryMaintenanceStatus.COMPLETED
    assert outcome.model_calls > 3
    assert all(call.profile is TaskProfile.MEMORY_MAINTENANCE for call in runner.calls)
    assert any(
        any(
            message.label == "memory_maintenance_feedback"
            for message in call.messages.messages
        )
        for call in runner.calls
    )
    final_prompts = [
        repr(call.messages)
        for call in runner.calls
        if any(
            message.label == "memory_maintenance_output"
            for message in call.messages.messages
        )
    ]
    assert final_prompts
    assert all(
        "home:what@concept/unused" not in prompt for prompt in final_prompts
    )
    assert "<home:what@concept/known>" in _target(tmp_path).read_text(
        encoding="utf-8"
    )


def test_invalid_memory_output_fails_without_creating_target(tmp_path: Path) -> None:
    memory = _memory(
        tmp_path,
        maintenance=MemoryMaintenanceSettings(validation_retries=1),
    )
    runner = _MemoryTaskRunner(repair_link=False)

    outcome = memory.run_maintenance(
        projection=_projection(_fact("fact", 9)),
        consolidator=LLMMemoryConsolidator(runner),
        timezone="Asia/Shanghai",
    )

    assert outcome.status is MemoryMaintenanceStatus.FAILED
    assert outcome.failure is MemoryMaintenanceFailure.INVALID_OUTPUT
    assert not _target(tmp_path).exists()


def test_memory_output_validates_other_date_links_and_rejects_self_or_missing(
    tmp_path: Path,
) -> None:
    other = tmp_path / "memory" / "2026" / "07" / "2026-07-11.md"
    other.parent.mkdir(parents=True)
    other.write_text("any earlier Markdown", encoding="utf-8")
    memory = _memory(tmp_path)

    valid = memory.run_maintenance(
        projection=_projection(_fact("fact", 9)),
        consolidator=_CapturingConsolidator(
            "- linked <memory:2026-07-11>"
        ),
        timezone="Asia/Shanghai",
    )
    assert valid.status is MemoryMaintenanceStatus.COMPLETED

    invalid_bodies = (
        "# duplicate date heading\n\n- invalid",
        "   # indented duplicate heading\n\n- invalid",
        "Setext duplicate heading\n===\n\n- invalid",
        "- invalid <memory:2026-07-12>",
        "- invalid <memory:2026-07-10>",
    )
    for body in invalid_bodies:
        outcome = memory.run_maintenance(
            projection=_projection(_fact("fact", 9)),
            consolidator=_CapturingConsolidator(body),
            timezone="Asia/Shanghai",
        )
        assert outcome.status is MemoryMaintenanceStatus.FAILED
        assert outcome.failure is MemoryMaintenanceFailure.INVALID_OUTPUT


def test_source_budget_failure_does_not_call_consolidator(tmp_path: Path) -> None:
    memory = _memory(
        tmp_path,
        maintenance=MemoryMaintenanceSettings(
            chunk_max_chars=512,
            source_max_chars=600,
            max_calls=10,
        ),
    )
    consolidator = _CapturingConsolidator("unused")

    outcome = memory.run_maintenance(
        projection=_projection(_fact("x" * 1000, 9)),
        consolidator=consolidator,
        timezone="Asia/Shanghai",
    )

    assert outcome.status is MemoryMaintenanceStatus.FAILED
    assert outcome.failure is MemoryMaintenanceFailure.INPUT_TOO_LARGE
    assert consolidator.requests == []
    assert not _target(tmp_path).exists()


def test_fact_start_time_must_belong_to_projection_business_day(tmp_path: Path) -> None:
    memory = _memory(tmp_path)
    wrong_day_fact = SessionMemoryFact(
        ref="session:turn/wrong_day",
        started_at=datetime(2026, 7, 13, 9, 0, tzinfo=ZONE).astimezone(UTC),
        user_inputs=("wrong day",),
    )

    with pytest.raises(MemoryInvariantError):
        memory.run_maintenance(
            projection=_projection(wrong_day_fact),
            consolidator=_CapturingConsolidator("unused"),
            timezone="Asia/Shanghai",
        )

    assert not _target(tmp_path).exists()


def test_atomic_write_failure_preserves_existing_memory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observations = _RecordingObservations()
    memory = _memory(tmp_path, observations=observations)
    target = _target(tmp_path)
    target.parent.mkdir(parents=True)
    old = "old free-form Memory"
    target.write_text(old, encoding="utf-8")

    def fail_write(path: Path, text: str, *, encoding: str = "utf-8") -> None:
        raise OSError("simulated atomic failure")

    monkeypatch.setattr(store_module, "atomic_write_text", fail_write)

    with pytest.raises(MemoryIOError):
        memory.run_maintenance(
            projection=_projection(_fact("new", 9)),
            consolidator=_CapturingConsolidator("replacement"),
            timezone="Asia/Shanghai",
        )

    assert target.read_text(encoding="utf-8") == old
    assert [event.name for event in observations.events] == [
        "memory.maintenance.started",
        "memory.maintenance.failed",
    ]
    assert observations.events[-1].payload["error_type"] == "MemoryIOError"


def test_completed_replace_then_interruption_retries_as_existing_memory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home_marker = tmp_path / "home" / "what" / "concept" / "marker.md"
    home_marker.parent.mkdir(parents=True)
    home_marker.write_text("home remains unchanged", encoding="utf-8")
    memory = _memory(tmp_path)
    original_write = store_module.MemoryStore.write

    def write_then_interrupt(
        store: store_module.MemoryStore,
        link: MemoryLink,
        text: str,
    ) -> store_module.MemoryDocument:
        document = original_write(store, link, text)
        raise MemoryIOError("simulated interruption after atomic replace")

    monkeypatch.setattr(store_module.MemoryStore, "write", write_then_interrupt)

    with pytest.raises(MemoryIOError, match="after atomic replace"):
        memory.run_maintenance(
            projection=_projection(_fact("new", 9)),
            consolidator=_CapturingConsolidator("- replacement"),
            timezone="Asia/Shanghai",
        )

    expected = "# 2026-07-12\n\n- replacement\n"
    assert _target(tmp_path).read_text(encoding="utf-8") == expected
    assert home_marker.read_text(encoding="utf-8") == "home remains unchanged"

    monkeypatch.setattr(store_module.MemoryStore, "write", original_write)
    retry = memory.run_maintenance(
        projection=_projection(_fact("new", 9)),
        consolidator=_UnexpectedConsolidator(),
        timezone="Asia/Shanghai",
        rewrite_existing=False,
    )

    assert retry.status is MemoryMaintenanceStatus.SKIPPED
    assert retry.skip_reason is MemoryMaintenanceSkipReason.MEMORY_EXISTS
    assert _target(tmp_path).read_text(encoding="utf-8") == expected
    assert home_marker.read_text(encoding="utf-8") == "home remains unchanged"


def test_memory_settings_parse_nested_budgets(tmp_path: Path) -> None:
    settings = parse_memory_settings(
        {
            "maintenance": {
                "chunk_max_chars": 2048,
                "source_max_chars": 8192,
                "link_hints_max_chars": 1024,
                "max_calls": 12,
                "validation_retries": 3,
            }
        },
        project_root=tmp_path,
    )

    assert settings.maintenance == MemoryMaintenanceSettings(
        chunk_max_chars=2048,
        source_max_chars=8192,
        link_hints_max_chars=1024,
        max_calls=12,
        validation_retries=3,
    )


class _CapturingConsolidator:
    def __init__(self, body: str) -> None:
        self.body = body
        self.requests: list[MemoryConsolidationRequest] = []

    def consolidate(
        self,
        request: MemoryConsolidationRequest,
        *,
        scope: RunScope,
    ) -> MemoryConsolidationResult:
        self.requests.append(request)
        return MemoryConsolidationResult(body=self.body, model_calls=0)


class _UnexpectedConsolidator:
    def consolidate(
        self,
        request: MemoryConsolidationRequest,
        *,
        scope: RunScope,
    ) -> MemoryConsolidationResult:
        raise AssertionError("existing Memory must not invoke consolidation")


class _MemoryTaskRunner:
    def __init__(self, *, repair_link: bool) -> None:
        self._repair_link = repair_link
        self._final_calls = 0
        self.calls: list[TaskCall] = []

    def run(self, call: TaskCall) -> TaskResult:
        self.calls.append(call)
        value: JsonObject
        final = any(
            message.label == "memory_maintenance_output"
            for message in call.messages.messages
        )
        if final:
            self._final_calls += 1
            link = (
                "home:what@concept/known"
                if self._repair_link and self._final_calls > 1
                else "home:what@concept/missing"
            )
            value = {"content": f"- retained fact <{link}>"}
        else:
            value = {
                "content": "- condensed fact <home:what@concept/known>"
            }
        return TaskResult.success(
            raw_response=RawResponse(
                answer_text=json.dumps(value),
                model_id="model",
                provider_id="provider",
            ),
            answer=JsonAnswer(value),
            tool_calls=(),
        )


def _memory(
    root: Path,
    *,
    maintenance: MemoryMaintenanceSettings | None = None,
    observations: ObservationEmitter | None = None,
) -> MemoryEngine:
    original = root / "home"
    original.mkdir(parents=True, exist_ok=True)
    home = AgentHomeEngineBuilder(
        AgentHomeSettings(
            original_root=original,
            runtime_root=root / "runtime" / "home",
        )
    ).build()
    return MemoryEngine(
        settings=MemorySettings(
            root=root / "memory",
            maintenance=maintenance or MemoryMaintenanceSettings(),
        ),
        home_catalog=home,
        observations=observations,
    )


def _projection(*facts: SessionMemoryFact) -> SessionMemoryFactsProjection:
    return SessionMemoryFactsProjection(day=DAY, revision=len(facts), facts=facts)


def _fact(text: str, hour: int) -> SessionMemoryFact:
    started_at = datetime(2026, 7, 12, hour, 0, tzinfo=ZONE).astimezone(UTC)
    return SessionMemoryFact(
        ref=f"session:turn/turn_{hour}_{len(text)}",
        started_at=started_at,
        user_inputs=(text,),
        answer=f"answer for {text}",
    )


def _target(root: Path) -> Path:
    return root / "memory" / "2026" / "07" / "2026-07-12.md"


class _RecordingObservations:
    def __init__(self) -> None:
        self.events: list[ObservationEvent] = []

    def enabled(self, level: ObservationLevel) -> bool:
        return True

    def emit(self, event: ObservationEvent) -> None:
        self.events.append(event)
