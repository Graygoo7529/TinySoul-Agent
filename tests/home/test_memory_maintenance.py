"""Date-scoped Memory Maintenance tests."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

import tinysoul.home.memory as memory_module
from tinysoul.home import (
    AgentHomeEngine,
    AgentHomeEngineBuilder,
    AgentHomeIOError,
    AgentHomeInvariantError,
    AgentHomeSettings,
    LLMMemoryConsolidator,
    MemoryConsolidationRequest,
    MemoryConsolidationResult,
    MemoryMaintenanceFailure,
    MemoryMaintenanceSettings,
    MemoryMaintenanceSkipReason,
    MemoryMaintenanceStatus,
    MemoryPeriod,
    MemorySections,
    parse_agent_home_settings,
    render_memory_document,
)
from tinysoul.infra.json import JsonObject
from tinysoul.llm import JsonAnswer, RawResponse, TaskCall, TaskProfile, TaskResult
from tinysoul.loop import BusinessDay
from tinysoul.runtime import RunLevel, RunScope
from tinysoul.session import SessionMemoryFact, SessionMemoryFactsProjection


DAY = BusinessDay.parse("2026-07-12")
ZONE = ZoneInfo("Asia/Shanghai")


def test_memory_maintenance_groups_periods_and_atomically_renders_document(
    tmp_path: Path,
) -> None:
    known = tmp_path / "home" / "what" / "concept" / "known.md"
    known.parent.mkdir(parents=True)
    known.write_text("known", encoding="utf-8")
    home = _home(tmp_path)
    projection = _projection(
        _fact("morning", 9),
        _fact("afternoon", 14),
        _fact("evening", 20),
    )
    consolidator = _CapturingConsolidator(
        MemorySections(
            morning="- morning fact <home:what@known>",
            afternoon="- afternoon fact",
            evening="- evening fact",
        )
    )
    assert home.memory_maintenance_eligible(projection)

    outcome = home.run_memory_maintenance(
        projection=projection,
        consolidator=consolidator,
        timezone="Asia/Shanghai",
    )

    assert outcome.status is MemoryMaintenanceStatus.COMPLETED
    assert outcome.fact_count == 3
    assert outcome.document_digest
    request = consolidator.requests[0]
    by_period = {item.period: "\n".join(item.sources) for item in request.periods}
    assert "morning" in by_period[MemoryPeriod.MORNING]
    assert "afternoon" in by_period[MemoryPeriod.AFTERNOON]
    assert "evening" in by_period[MemoryPeriod.EVENING]
    assert "home:what@known" in request.allowed_links
    target = _target(tmp_path)
    assert target.read_text(encoding="utf-8") == render_memory_document(
        DAY,
        consolidator.sections,
    )
    assert not (tmp_path / "runtime" / "home" / "memory").exists()
    assert not home.memory_maintenance_eligible(projection)


def test_missing_and_empty_session_skip_without_touching_memory(tmp_path: Path) -> None:
    home = _home(tmp_path)
    target = _target(tmp_path)
    target.parent.mkdir(parents=True)
    target.write_text("existing bytes stay unchanged", encoding="utf-8")

    missing = home.run_memory_maintenance(
        projection=None,
        consolidator=None,
        timezone="Asia/Shanghai",
        target_day=DAY,
    )
    empty = home.run_memory_maintenance(
        projection=_projection(),
        consolidator=None,
        timezone="Asia/Shanghai",
    )

    assert missing.status is MemoryMaintenanceStatus.SKIPPED
    assert missing.skip_reason is MemoryMaintenanceSkipReason.SESSION_NOT_FOUND
    assert empty.status is MemoryMaintenanceStatus.SKIPPED
    assert empty.skip_reason is MemoryMaintenanceSkipReason.SESSION_EMPTY
    assert target.read_text(encoding="utf-8") == "existing bytes stay unchanged"


def test_existing_same_day_memory_is_a_period_source_and_is_rewritten(
    tmp_path: Path,
) -> None:
    home = _home(tmp_path)
    target = _target(tmp_path)
    target.parent.mkdir(parents=True)
    target.write_text(
        render_memory_document(
            DAY,
            MemorySections(morning="- old morning", evening="- old evening"),
        ),
        encoding="utf-8",
    )
    consolidator = _CapturingConsolidator(
        MemorySections(morning="- merged morning", evening="- merged evening")
    )

    outcome = home.run_memory_maintenance(
        projection=_projection(_fact("new", 9)),
        consolidator=consolidator,
        timezone="Asia/Shanghai",
    )

    assert outcome.status is MemoryMaintenanceStatus.COMPLETED
    sources = {
        item.period: "\n".join(item.sources)
        for item in consolidator.requests[0].periods
    }
    assert "old morning" in sources[MemoryPeriod.MORNING]
    assert "old evening" in sources[MemoryPeriod.EVENING]
    assert target.read_text(encoding="utf-8") == render_memory_document(
        DAY,
        consolidator.sections,
    )


def test_llm_consolidator_hierarchically_reduces_and_retries_missing_home_link(
    tmp_path: Path,
) -> None:
    known = tmp_path / "home" / "what" / "concept" / "known.md"
    known.parent.mkdir(parents=True)
    known.write_text("known", encoding="utf-8")
    home = _home(
        tmp_path,
        memory=MemoryMaintenanceSettings(
            chunk_max_chars=512,
            source_max_chars=10000,
            max_calls=20,
            validation_retries=2,
        ),
    )
    runner = _MemoryTaskRunner(repair_link=True)

    outcome = home.run_memory_maintenance(
        projection=_projection(_fact("x" * 1800, 9)),
        consolidator=LLMMemoryConsolidator(runner),
        timezone="Asia/Shanghai",
        scope=RunScope().push(RunLevel.PROGRAM, "program"),
    )

    assert outcome.status is MemoryMaintenanceStatus.COMPLETED
    assert outcome.model_calls > 3
    assert all(call.profile is TaskProfile.MEMORY_MAINTENANCE for call in runner.calls)
    assert any(
        any(message.label == "memory_maintenance_feedback" for message in call.messages.messages)
        for call in runner.calls
    )
    assert "<home:what@known>" in _target(tmp_path).read_text(encoding="utf-8")


def test_invalid_memory_output_fails_without_creating_target(tmp_path: Path) -> None:
    home = _home(
        tmp_path,
        memory=MemoryMaintenanceSettings(validation_retries=1),
    )
    runner = _MemoryTaskRunner(repair_link=False)

    outcome = home.run_memory_maintenance(
        projection=_projection(_fact("fact", 9)),
        consolidator=LLMMemoryConsolidator(runner),
        timezone="Asia/Shanghai",
    )

    assert outcome.status is MemoryMaintenanceStatus.FAILED
    assert outcome.failure is MemoryMaintenanceFailure.INVALID_OUTPUT
    assert not _target(tmp_path).exists()


def test_source_budget_failure_does_not_call_consolidator(tmp_path: Path) -> None:
    home = _home(
        tmp_path,
        memory=MemoryMaintenanceSettings(
            chunk_max_chars=512,
            source_max_chars=600,
            max_calls=10,
        ),
    )
    consolidator = _CapturingConsolidator(MemorySections(morning="unused"))

    outcome = home.run_memory_maintenance(
        projection=_projection(_fact("x" * 1000, 9)),
        consolidator=consolidator,
        timezone="Asia/Shanghai",
    )

    assert outcome.status is MemoryMaintenanceStatus.FAILED
    assert outcome.failure is MemoryMaintenanceFailure.INPUT_TOO_LARGE
    assert consolidator.requests == []
    assert not _target(tmp_path).exists()


def test_fact_start_time_must_belong_to_projection_business_day(tmp_path: Path) -> None:
    home = _home(tmp_path)
    wrong_day_fact = SessionMemoryFact(
        ref="session:turn/wrong_day",
        started_at=datetime(2026, 7, 13, 9, 0, tzinfo=ZONE).astimezone(UTC),
        user_inputs=("wrong day",),
    )

    with pytest.raises(AgentHomeInvariantError):
        home.run_memory_maintenance(
            projection=_projection(wrong_day_fact),
            consolidator=_CapturingConsolidator(
                MemorySections(morning="unused")
            ),
            timezone="Asia/Shanghai",
        )

    assert not _target(tmp_path).exists()


def test_atomic_write_failure_preserves_existing_memory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = _home(tmp_path)
    target = _target(tmp_path)
    target.parent.mkdir(parents=True)
    old = render_memory_document(DAY, MemorySections(morning="- old"))
    target.write_text(old, encoding="utf-8")

    def fail_write(path: Path, text: str, *, encoding: str = "utf-8") -> None:
        raise OSError("simulated atomic failure")

    monkeypatch.setattr(memory_module, "atomic_write_text", fail_write)

    with pytest.raises(AgentHomeIOError):
        home.run_memory_maintenance(
            projection=_projection(_fact("new", 9)),
            consolidator=_CapturingConsolidator(
                MemorySections(morning="- replacement")
            ),
            timezone="Asia/Shanghai",
        )

    assert target.read_text(encoding="utf-8") == old


def test_memory_settings_parse_nested_budgets(tmp_path: Path) -> None:
    settings = parse_agent_home_settings(
        {
            "memory": {
                "chunk_max_chars": 2048,
                "source_max_chars": 8192,
                "max_calls": 12,
                "validation_retries": 3,
            }
        },
        project_root=tmp_path,
    )

    assert settings.memory == MemoryMaintenanceSettings(
        chunk_max_chars=2048,
        source_max_chars=8192,
        max_calls=12,
        validation_retries=3,
    )


class _CapturingConsolidator:
    def __init__(self, sections: MemorySections) -> None:
        self.sections = sections
        self.requests: list[MemoryConsolidationRequest] = []

    def consolidate(
        self,
        request: MemoryConsolidationRequest,
        *,
        scope: RunScope,
    ) -> MemoryConsolidationResult:
        self.requests.append(request)
        return MemoryConsolidationResult(sections=self.sections, model_calls=0)


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
                "home:what@known"
                if self._repair_link and self._final_calls > 1
                else "home:what@missing"
            )
            value = {
                "morning": f"- retained fact <{link}>",
                "afternoon": "",
                "evening": "",
            }
        else:
            value = {"content": "- condensed fact"}
        return TaskResult.success(
            raw_response=RawResponse(
                answer_text=json.dumps(value),
                model_id="model",
                provider_id="provider",
            ),
            answer=JsonAnswer(value),
            tool_calls=(),
        )


def _home(
    root: Path,
    *,
    memory: MemoryMaintenanceSettings | None = None,
) -> AgentHomeEngine:
    original = root / "home"
    original.mkdir(parents=True, exist_ok=True)
    return AgentHomeEngineBuilder(
        AgentHomeSettings(
            original_root=original,
            runtime_root=root / "runtime" / "home",
            memory=memory or MemoryMaintenanceSettings(),
        )
    ).build()


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
    return root / "home" / "memory" / "2026" / "07" / "2026-07-12.md"
