from __future__ import annotations

import json
from pathlib import Path

import pytest

import tinysoul.home.maintenance as maintenance_module
from tinysoul.home import (
    AgentHomeEngine,
    AgentHomeEngineBuilder,
    AgentHomeIOError,
    AgentHomeInvariantError,
    AgentHomeReviewError,
    AgentHomeSettings,
    HomeMaintenanceChange,
    HomeMaintenanceDecision,
    HomeMaintenanceFailure,
    HomeMaintenanceMode,
    HomeMaintenanceStatus,
    LLMHomeMaintenanceReviewer,
)
from tinysoul.home.overlay import HomeOverlayManager
from tinysoul.infra.json import JsonObject
from tinysoul.llm import JsonAnswer, RawResponse, TaskCall, TaskProfile, TaskResult
from tinysoul.runtime import (
    ObservationEmitter,
    ObservationEvent,
    ObservationLevel,
    RunLevel,
    RunScope,
)


_SKILL_TEXT = (
    "---\n"
    "title: Refactor\n"
    "description: Apply the refactoring workflow.\n"
    "---\n\n"
    "# Refactor\n"
)


def test_automatic_home_maintenance_applies_and_discards_without_writing_state(
    tmp_path: Path,
) -> None:
    modify = tmp_path / "home" / "why" / "modify.md"
    delete = tmp_path / "home" / "why" / "delete.md"
    discard = tmp_path / "home" / "why" / "discard.md"
    modify.parent.mkdir(parents=True)
    modify.write_text("old modify", encoding="utf-8")
    delete.write_text("old delete", encoding="utf-8")
    discard.write_text("old discard", encoding="utf-8")
    home = _home(tmp_path)
    home.write_top("home:why@modify", "new modify", overwrite=True)
    home.delete_top("home:why@delete")
    home.write_top("home:why@discard", "new discard", overwrite=True)
    home.write_top(
        "home:what@entity/created",
        "new entity",
    )
    modify.write_text("external modify", encoding="utf-8")
    reviewer = _MappingReviewer(
        {
            "home:why@delete": HomeMaintenanceDecision.APPLY,
            "home:why@discard": HomeMaintenanceDecision.DISCARD,
            "home:why@modify": HomeMaintenanceDecision.APPLY,
            "home:what@entity/created": HomeMaintenanceDecision.APPLY,
        }
    )

    outcome = home.run_maintenance(
        mode=HomeMaintenanceMode.AUTOMATIC,
        automatic_reviewer=reviewer,
    )

    assert outcome.status is HomeMaintenanceStatus.COMPLETED
    assert outcome.applied == 3
    assert outcome.discarded == 1
    assert outcome.remaining_changes == 0
    modified_change = next(
        change for change in reviewer.changes if change.link == "home:why@modify"
    )
    assert modified_change.actual_changed_from_baseline is True
    assert modified_change.actual_text == "external modify"
    assert modify.read_text(encoding="utf-8") == "new modify"
    assert not delete.exists()
    assert discard.read_text(encoding="utf-8") == "old discard"
    assert (
        tmp_path / "home" / "what" / "entity" / "created.md"
    ).read_text(encoding="utf-8") == "new entity"
    assert _overlay_records(tmp_path) == []
    assert not (tmp_path / "runtime" / "home" / "why").exists()
    assert not (tmp_path / "home" / ".tinysoul").exists()


def test_copied_record_cleanup_preserves_current_actual_and_never_calls_reviewer(
    tmp_path: Path,
) -> None:
    source = tmp_path / "home" / "why" / "external.md"
    source.parent.mkdir(parents=True)
    source.write_text("baseline", encoding="utf-8")
    home = _home(tmp_path)
    home.ensure_runtime_copy(home.parse_link("home:why@external"))
    source.write_text("external current", encoding="utf-8")

    outcome = home.run_maintenance(
        mode=HomeMaintenanceMode.AUTOMATIC,
        automatic_reviewer=_UnexpectedReviewer(),
    )

    assert outcome.copied_cleaned == 1
    assert outcome.items == ()
    assert source.read_text(encoding="utf-8") == "external current"
    assert "home:why@external" in home.loadable_background_links()
    assert _overlay_records(tmp_path) == []


def test_copied_record_cleanup_follows_external_actual_deletion(tmp_path: Path) -> None:
    source = tmp_path / "home" / "why" / "removed.md"
    source.parent.mkdir(parents=True)
    source.write_text("baseline", encoding="utf-8")
    home = _home(tmp_path)
    home.ensure_runtime_copy(home.parse_link("home:why@removed"))
    source.unlink()

    outcome = home.run_maintenance(
        mode=HomeMaintenanceMode.AUTOMATIC,
        automatic_reviewer=_UnexpectedReviewer(),
    )

    assert outcome.copied_cleaned == 1
    assert "home:why@removed" not in home.loadable_background_links()
    assert _overlay_records(tmp_path) == []


def test_home_maintenance_pending_only_counts_real_diffs_and_skill_memory(
    tmp_path: Path,
) -> None:
    source = tmp_path / "home" / "why" / "copied.md"
    source.parent.mkdir(parents=True)
    source.write_text("unchanged", encoding="utf-8")
    skill = tmp_path / "home" / "how" / "refactor" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text(_SKILL_TEXT, encoding="utf-8")
    home = _home(tmp_path)
    home.ensure_runtime_copy(home.parse_link("home:why@copied"))

    assert home.maintenance_pending().pending is False

    home.write_top("home:why@changed", "runtime only")
    home.write_resource(
        "home:how/refactor/SKILL_MEMORY.md",
        "temporary review context",
    )

    pending = home.maintenance_pending()

    assert pending.pending is True
    assert pending.change_count == 1
    assert pending.skill_memory_count == 1


def test_home_maintenance_pending_ignores_consistent_residual_record(
    tmp_path: Path,
) -> None:
    home = _home(tmp_path)
    home.write_top("home:why@recover", "same bytes")
    actual = tmp_path / "home" / "why" / "recover.md"
    actual.parent.mkdir(parents=True, exist_ok=True)
    actual.write_text("same bytes", encoding="utf-8")

    pending = home.maintenance_pending()

    assert pending.pending is False
    assert pending.change_count == 0


def test_skill_memory_is_review_context_and_clears_after_skill_review(
    tmp_path: Path,
) -> None:
    skill = tmp_path / "home" / "how" / "refactor"
    reference = skill / "references" / "check.md"
    reference.parent.mkdir(parents=True)
    (skill / "SKILL.md").write_text(_SKILL_TEXT, encoding="utf-8")
    reference.write_text("old check", encoding="utf-8")
    home = _home(tmp_path)
    home.write_resource(
        "home:how/refactor/references/check.md",
        "new check",
        overwrite=True,
    )
    home.write_resource(
        "home:how/refactor/SKILL_MEMORY.md",
        "This checklist was repeatedly confusing.",
    )
    reviewer = _MappingReviewer(
        {"home:how/refactor/references/check.md": HomeMaintenanceDecision.APPLY}
    )

    outcome = home.run_maintenance(
        mode=HomeMaintenanceMode.AUTOMATIC,
        automatic_reviewer=reviewer,
    )

    assert outcome.skill_memories_cleared == 1
    assert reviewer.changes[0].skill_memory is not None
    assert reviewer.changes[0].skill_memory.text == (
        "This checklist was repeatedly confusing."
    )
    assert reference.read_text(encoding="utf-8") == "new check"
    assert not (skill / "SKILL_MEMORY.md").exists()
    assert not (
        tmp_path / "runtime" / "home" / "how" / "refactor" / "SKILL_MEMORY.md"
    ).exists()


def test_manual_home_maintenance_stops_before_unconfirmed_item(tmp_path: Path) -> None:
    home = _home(tmp_path)
    home.write_top("home:why@a", "first")
    home.write_top("home:why@b", "second")
    decisions = _SequenceDecisionProvider(
        (HomeMaintenanceDecision.APPLY, None)
    )

    outcome = home.run_maintenance(
        mode=HomeMaintenanceMode.MANUAL,
        manual_decisions=decisions,
    )

    assert outcome.status is HomeMaintenanceStatus.STOPPED
    assert outcome.applied == 1
    assert outcome.remaining_changes == 1
    assert (tmp_path / "home" / "why" / "a.md").is_file()
    assert not (tmp_path / "home" / "why" / "b.md").exists()
    assert home.read_top("home:why@b") == "second"

    completed = home.run_maintenance(
        mode=HomeMaintenanceMode.MANUAL,
        manual_decisions=_SequenceDecisionProvider(
            (HomeMaintenanceDecision.DISCARD,)
        ),
    )
    assert completed.status is HomeMaintenanceStatus.COMPLETED
    assert completed.discarded == 1
    assert completed.remaining_changes == 0


def test_manual_stop_keeps_skill_memory_until_skill_review_completes(
    tmp_path: Path,
) -> None:
    skill = tmp_path / "home" / "how" / "refactor"
    reference = skill / "references" / "check.md"
    reference.parent.mkdir(parents=True)
    (skill / "SKILL.md").write_text(_SKILL_TEXT, encoding="utf-8")
    reference.write_text("old", encoding="utf-8")
    home = _home(tmp_path)
    home.write_resource(
        "home:how/refactor/references/check.md",
        "new",
        overwrite=True,
    )
    memory_link = "home:how/refactor/SKILL_MEMORY.md"
    home.write_resource(memory_link, "keep until reviewed")

    stopped = home.run_maintenance(
        mode=HomeMaintenanceMode.MANUAL,
        manual_decisions=_SequenceDecisionProvider((None,)),
    )

    assert stopped.status is HomeMaintenanceStatus.STOPPED
    assert home.read_resource(memory_link).text == "keep until reviewed"

    completed = home.run_maintenance(
        mode=HomeMaintenanceMode.MANUAL,
        manual_decisions=_SequenceDecisionProvider(
            (HomeMaintenanceDecision.DISCARD,)
        ),
    )
    assert completed.skill_memories_cleared == 1
    assert not (
        tmp_path / "runtime" / "home" / "how" / "refactor" / "SKILL_MEMORY.md"
    ).exists()


def test_actual_write_then_cleanup_interruption_recovers_without_reviewing_again(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "home" / "why" / "recover.md"
    source.parent.mkdir(parents=True)
    source.write_text("old", encoding="utf-8")
    home = _home(tmp_path)
    home.write_top("home:why@recover", "new", overwrite=True)
    original_clear = HomeOverlayManager.clear_record
    failed = False

    def fail_once(manager: HomeOverlayManager, relative_path: str) -> bool:
        nonlocal failed
        if not failed:
            failed = True
            raise AgentHomeIOError("injected cleanup failure")
        return original_clear(manager, relative_path)

    monkeypatch.setattr(HomeOverlayManager, "clear_record", fail_once)
    with pytest.raises(AgentHomeIOError, match="injected cleanup"):
        home.run_maintenance(
            mode=HomeMaintenanceMode.AUTOMATIC,
            automatic_reviewer=_MappingReviewer(
                {"home:why@recover": HomeMaintenanceDecision.APPLY}
            ),
        )

    assert source.read_text(encoding="utf-8") == "new"
    assert _overlay_records(tmp_path)
    monkeypatch.setattr(HomeOverlayManager, "clear_record", original_clear)

    recovered = home.run_maintenance(
        mode=HomeMaintenanceMode.AUTOMATIC,
        automatic_reviewer=_UnexpectedReviewer(),
    )

    assert recovered.consistent_cleaned == 1
    assert recovered.items == ()
    assert _overlay_records(tmp_path) == []


def test_actual_delete_then_cleanup_interruption_recovers_without_reviewing_again(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "home" / "why" / "delete_recover.md"
    source.parent.mkdir(parents=True)
    source.write_text("remove", encoding="utf-8")
    home = _home(tmp_path)
    home.delete_top("home:why@delete_recover")
    original_clear = HomeOverlayManager.clear_record
    failed = False

    def fail_once(manager: HomeOverlayManager, relative_path: str) -> bool:
        nonlocal failed
        if not failed:
            failed = True
            raise AgentHomeIOError("injected tombstone cleanup failure")
        return original_clear(manager, relative_path)

    monkeypatch.setattr(HomeOverlayManager, "clear_record", fail_once)
    with pytest.raises(AgentHomeIOError, match="tombstone cleanup"):
        home.run_maintenance(
            mode=HomeMaintenanceMode.AUTOMATIC,
            automatic_reviewer=_MappingReviewer(
                {"home:why@delete_recover": HomeMaintenanceDecision.APPLY}
            ),
        )

    assert not source.exists()
    assert _overlay_records(tmp_path)
    monkeypatch.setattr(HomeOverlayManager, "clear_record", original_clear)

    recovered = home.run_maintenance(
        mode=HomeMaintenanceMode.AUTOMATIC,
        automatic_reviewer=_UnexpectedReviewer(),
    )

    assert recovered.consistent_cleaned == 1
    assert recovered.items == ()
    assert _overlay_records(tmp_path) == []


def test_partial_home_review_failure_keeps_only_unresolved_changes(
    tmp_path: Path,
) -> None:
    observations = _RecordingObservations()
    home = _home(tmp_path, observations=observations)
    home.write_top("home:why@a", "apply first")
    home.write_top("home:why@b", "leave pending")

    failed = home.run_maintenance(
        mode=HomeMaintenanceMode.AUTOMATIC,
        automatic_reviewer=_FailAfterFirstReviewer(),
    )

    assert failed.status is HomeMaintenanceStatus.FAILED
    assert failed.failure is HomeMaintenanceFailure.REVIEW_FAILED
    assert failed.applied == 1
    assert failed.remaining_changes == 1
    assert (tmp_path / "home" / "why" / "a.md").read_text(
        encoding="utf-8"
    ) == "apply first"
    assert not (tmp_path / "home" / "why" / "b.md").exists()
    assert [event.name for event in observations.events] == [
        "home.maintenance.started",
        "home.maintenance.item.resolved",
        "home.maintenance.failed",
    ]
    assert observations.events[-1].payload["failure"] == "review_failed"

    completed = home.run_maintenance(
        mode=HomeMaintenanceMode.AUTOMATIC,
        automatic_reviewer=_MappingReviewer(
            {"home:why@b": HomeMaintenanceDecision.DISCARD}
        ),
    )
    assert completed.discarded == 1
    assert completed.remaining_changes == 0


def test_skill_memory_cleanup_failure_retries_without_reviewing_change_again(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    skill = tmp_path / "home" / "how" / "refactor"
    reference = skill / "references" / "retry.md"
    reference.parent.mkdir(parents=True)
    (skill / "SKILL.md").write_text(_SKILL_TEXT, encoding="utf-8")
    reference.write_text("old", encoding="utf-8")
    home = _home(tmp_path)
    home.write_resource(
        "home:how/refactor/references/retry.md",
        "new",
        overwrite=True,
    )
    memory_link = "home:how/refactor/SKILL_MEMORY.md"
    home.write_resource(memory_link, "clear after apply")
    original_clear = HomeOverlayManager.clear_record
    failed = False

    def fail_skill_memory(
        manager: HomeOverlayManager,
        relative_path: str,
    ) -> bool:
        nonlocal failed
        if not failed and relative_path.endswith("/SKILL_MEMORY.md"):
            failed = True
            raise AgentHomeIOError("injected SKILL_MEMORY cleanup failure")
        return original_clear(manager, relative_path)

    monkeypatch.setattr(HomeOverlayManager, "clear_record", fail_skill_memory)
    with pytest.raises(AgentHomeIOError, match="SKILL_MEMORY cleanup"):
        home.run_maintenance(
            mode=HomeMaintenanceMode.AUTOMATIC,
            automatic_reviewer=_MappingReviewer(
                {
                    "home:how/refactor/references/retry.md": HomeMaintenanceDecision.APPLY,
                }
            ),
        )

    assert reference.read_text(encoding="utf-8") == "new"
    assert home.read_resource(memory_link).text == "clear after apply"
    monkeypatch.setattr(HomeOverlayManager, "clear_record", original_clear)

    recovered = home.run_maintenance(
        mode=HomeMaintenanceMode.AUTOMATIC,
        automatic_reviewer=_UnexpectedReviewer(),
    )
    assert recovered.items == ()
    assert recovered.skill_memories_cleared == 1
    assert recovered.remaining_changes == 0


def test_home_maintenance_observations_are_verbose_and_content_free(
    tmp_path: Path,
) -> None:
    observations = _RecordingObservations()
    home = _home(tmp_path, observations=observations)
    home.write_top("home:why@observed", "private Home review body")
    scope = RunScope().push(RunLevel.MODULE, "home_maintenance")

    outcome = home.run_maintenance(
        mode=HomeMaintenanceMode.AUTOMATIC,
        automatic_reviewer=_MappingReviewer(
            {"home:why@observed": HomeMaintenanceDecision.APPLY}
        ),
        scope=scope,
    )

    assert outcome.status is HomeMaintenanceStatus.COMPLETED
    assert [event.name for event in observations.events] == [
        "home.maintenance.started",
        "home.maintenance.item.resolved",
        "home.maintenance.completed",
    ]
    assert all(
        event.level is ObservationLevel.VERBOSE
        for event in observations.events
    )
    assert all(event.scope == scope for event in observations.events)
    assert observations.events[-1].payload["applied"] == 1
    assert "private Home review body" not in repr(observations.events)
    assert str(tmp_path) not in repr(observations.events)


def test_atomic_apply_failure_keeps_actual_and_runtime_diff(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "home" / "why" / "atomic.md"
    source.parent.mkdir(parents=True)
    source.write_text("old", encoding="utf-8")
    home = _home(tmp_path)
    home.write_top("home:why@atomic", "new", overwrite=True)

    def fail_write(path: Path, data: bytes) -> None:
        raise OSError("injected atomic failure")

    monkeypatch.setattr(maintenance_module, "atomic_write_bytes", fail_write)

    with pytest.raises(AgentHomeIOError, match="injected atomic failure"):
        home.run_maintenance(
            mode=HomeMaintenanceMode.AUTOMATIC,
            automatic_reviewer=_MappingReviewer(
                {"home:why@atomic": HomeMaintenanceDecision.APPLY}
            ),
        )

    assert source.read_text(encoding="utf-8") == "old"
    assert home.read_top("home:why@atomic") == "new"
    assert _overlay_records(tmp_path)


def test_core_tombstone_is_rejected_before_home_review(tmp_path: Path) -> None:
    core = tmp_path / "home" / "agent" / "AGENT.md"
    core.parent.mkdir(parents=True)
    core.write_text("core", encoding="utf-8")
    home = _home(tmp_path)
    manager = HomeOverlayManager(
        original_root=tmp_path / "home",
        runtime_root=tmp_path / "runtime" / "home",
    )
    manager.initialize()
    manager.delete("agent/AGENT.md", expected_digest="")

    with pytest.raises(AgentHomeInvariantError, match="AGENT cannot be deleted"):
        home.run_maintenance(
            mode=HomeMaintenanceMode.AUTOMATIC,
            automatic_reviewer=_UnexpectedReviewer(),
        )

    assert core.read_text(encoding="utf-8") == "core"


def test_llm_home_reviewer_uses_dedicated_profile_and_rejects_extra_fields(
    tmp_path: Path,
) -> None:
    home = _home(tmp_path)
    home.write_top("home:why@llm", "review me")
    runner = _TaskRunner({"decision": "discard"})

    outcome = home.run_maintenance(
        mode=HomeMaintenanceMode.AUTOMATIC,
        automatic_reviewer=LLMHomeMaintenanceReviewer(runner),
        scope=RunScope().push(RunLevel.PROGRAM, "program"),
    )

    assert outcome.discarded == 1
    assert runner.calls[0].profile is TaskProfile.HOME_MAINTENANCE
    assert runner.calls[0].scope.current() is not None

    home.write_top("home:why@invalid_llm", "review me")
    failed = home.run_maintenance(
        mode=HomeMaintenanceMode.AUTOMATIC,
        automatic_reviewer=LLMHomeMaintenanceReviewer(
            _TaskRunner({"decision": "apply", "reason": "not persisted"})
        ),
    )
    assert failed.status is HomeMaintenanceStatus.FAILED
    assert failed.failure is HomeMaintenanceFailure.REVIEW_FAILED
    assert failed.remaining_changes == 1
    assert home.read_top("home:why@invalid_llm") == "review me"


class _MappingReviewer:
    def __init__(
        self,
        decisions: dict[str, HomeMaintenanceDecision],
    ) -> None:
        self._decisions = decisions
        self.changes: list[HomeMaintenanceChange] = []

    def review(
        self,
        change: HomeMaintenanceChange,
        *,
        scope: RunScope,
    ) -> HomeMaintenanceDecision:
        self.changes.append(change)
        return self._decisions[change.link]


class _UnexpectedReviewer:
    def review(
        self,
        change: HomeMaintenanceChange,
        *,
        scope: RunScope,
    ) -> HomeMaintenanceDecision:
        raise AssertionError(f"Unexpected Home review: {change.link}")


class _FailAfterFirstReviewer:
    def __init__(self) -> None:
        self._calls = 0

    def review(
        self,
        change: HomeMaintenanceChange,
        *,
        scope: RunScope,
    ) -> HomeMaintenanceDecision:
        self._calls += 1
        if self._calls == 1:
            return HomeMaintenanceDecision.APPLY
        raise AgentHomeReviewError("injected second review failure")


class _SequenceDecisionProvider:
    def __init__(
        self,
        decisions: tuple[HomeMaintenanceDecision | None, ...],
    ) -> None:
        self._decisions = iter(decisions)

    def decide(
        self,
        change: HomeMaintenanceChange,
    ) -> HomeMaintenanceDecision | None:
        return next(self._decisions)


class _TaskRunner:
    def __init__(self, value: JsonObject) -> None:
        self._value = value
        self.calls: list[TaskCall] = []

    def run(self, call: TaskCall) -> TaskResult:
        self.calls.append(call)
        return TaskResult.success(
            raw_response=RawResponse(
                answer_text=json.dumps(self._value),
                model_id="model",
                provider_id="provider",
            ),
            answer=JsonAnswer(self._value),
            tool_calls=(),
        )


def _home(
    root: Path,
    *,
    observations: ObservationEmitter | None = None,
) -> AgentHomeEngine:
    original = root / "home"
    original.mkdir(parents=True, exist_ok=True)
    return AgentHomeEngineBuilder(
        AgentHomeSettings(
            original_root=original,
            runtime_root=root / "runtime" / "home",
        ),
        observations=observations,
    ).build()


def _overlay_records(root: Path) -> list[object]:
    manifest = json.loads(
        (
            root
            / "runtime"
            / "home"
            / ".tinysoul"
            / "home_overlay.json"
        ).read_text(encoding="utf-8")
    )
    records = manifest["records"]
    assert isinstance(records, list)
    return records


class _RecordingObservations:
    def __init__(self) -> None:
        self.events: list[ObservationEvent] = []

    def enabled(self, level: ObservationLevel) -> bool:
        return True

    def emit(self, event: ObservationEvent) -> None:
        self.events.append(event)
