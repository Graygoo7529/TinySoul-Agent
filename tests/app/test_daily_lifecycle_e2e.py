from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

import tinysoul.context.trace as trace_module
from tinysoul.app import (
    AppSettings,
    OutputSettings,
    ProjectInitializer,
    SchedulerSettings,
    TinySoulAppBuilder,
)
from tinysoul.infra.config import ConfigEnvironment
from tinysoul.infra.json import JsonObject
from tinysoul.llm import JsonAnswer, RawResponse, TaskCall, TaskResult
from tinysoul.llm.tools import ToolCallRecord, ToolKind
from tinysoul.loop import (
    BusinessDay,
    DailySettings,
    LoopSettings,
    ProgramInputEvent,
    ProgramWorkKind,
    ProgramWorkMode,
    ProgramWorkStatus,
)
from tinysoul.runtime import ObservationEvent, ObservationLevel


OLD_DAY = BusinessDay.parse("2026-07-14")
NEW_DAY = BusinessDay.parse("2026-07-15")
ZONE = ZoneInfo("Asia/Shanghai")


def test_offline_daily_lifecycle_runs_typed_maintenance_and_continues(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    llm = _FakeLLM(
        (
            _tool_result(
                _control(
                    "old_select_home",
                    "select_action_domains",
                    {"domains": ["home"]},
                )
            ),
            _tool_result(
                _action(
                    "old_home_write",
                    "home.top.write",
                    {
                        "link": "home:why@daily_preference",
                        "text": "# Daily preference\n\nKeep the durable preference.",
                    },
                )
            ),
            _tool_result(
                _control(
                    "old_select_core",
                    "select_action_domains",
                    {"domains": ["core"]},
                )
            ),
            _tool_result(
                _action(
                    "old_answer",
                    "core.answer",
                    {"guide_blocks": [{"text": "confirm the old-day change"}]},
                )
            ),
            _json_result({"text": "old day complete"}),
            _json_result({"decision": "apply"}),
            _json_result({"content": "- durable old-day fact"}),
            _json_result(
                {
                    "content": (
                        "- durable old-day fact\n"
                        "- preference <home:why@daily_preference>"
                    )
                }
            ),
            _tool_result(
                _control(
                    "new_select_memory_search",
                    "select_action_domains",
                    {"domains": ["memory"]},
                )
            ),
            _tool_result(
                _action(
                    "new_memory_search",
                    "memory.search",
                    {"query": "older durable project fact", "top_k": 1},
                )
            ),
            _json_result({"candidate_ids": ["memory:2026-07-13"]}),
            _tool_result(
                _control(
                    "new_select_memory_recall",
                    "select_action_domains",
                    {"domains": ["memory"]},
                )
            ),
            _tool_result(
                _action(
                    "new_memory_recall",
                    "memory.recall",
                    {"memory_link": "memory:2026-07-13"},
                )
            ),
            _tool_result(
                _control(
                    "new_select_core",
                    "select_action_domains",
                    {"domains": ["core"]},
                )
            ),
            _tool_result(
                _action(
                    "new_answer",
                    "core.answer",
                    {"guide_blocks": [{"text": "continue on the new day"}]},
                )
            ),
            _json_result({"text": "new day complete"}),
        )
    )
    clock = _ControlledClock(datetime(2026, 7, 14, 23, 50, tzinfo=ZONE))
    monkeypatch.setattr(
        trace_module,
        "time",
        lambda: clock.current.timestamp(),
    )
    observations = _RecordingSink()
    older_memory = tmp_path / "memory" / "2026" / "07" / "2026-07-13.md"
    older_memory.parent.mkdir(parents=True)
    older_memory.write_text(
        "# 2026-07-13\n\n- older durable project fact\n",
        encoding="utf-8",
    )
    app = (
        TinySoulAppBuilder(root=tmp_path)
        .with_config_environment(_test_config(tmp_path))
        .with_app_settings(
            AppSettings(
                interactive=False,
                output=OutputSettings(mode=ObservationLevel.VERBOSE),
                scheduler=SchedulerSettings(enabled=False),
            )
        )
        .with_loop_settings(
            LoopSettings(
                max_cycles_per_turn=3,
                daily=DailySettings(archive_root=tmp_path / "archive"),
            )
        )
        .with_business_clock(clock)
        .with_llm_runner(llm)
        .with_output_sink(observations)
        .build()
    )

    old_turn = app.run_once("record one durable preference")
    assert old_turn.answered is True
    assert old_turn.business_day == OLD_DAY
    actual_home = tmp_path / "home" / "why" / "daily_preference.md"
    runtime_home = tmp_path / "runtime" / "home" / "why" / "daily_preference.md"
    assert not actual_home.exists()
    assert runtime_home.is_file()

    clock.current = datetime(2026, 7, 15, 0, 20, tzinfo=ZONE)
    app.program_runner.submit_event(
        ProgramInputEvent.home_maintenance(
            mode=ProgramWorkMode.AUTOMATIC,
            source="stage7-e2e",
        )
    )
    app.program_runner.submit_event(
        ProgramInputEvent.memory_maintenance(
            mode=ProgramWorkMode.AUTOMATIC,
            target_day=OLD_DAY,
            source="stage7-e2e",
        )
    )
    app.program_runner.submit_event(
        ProgramInputEvent.start_turn(
            "continue after maintenance",
            source="stage7-e2e",
        )
    )
    app.program_runner.submit_event(
        ProgramInputEvent.exit_program(source="stage7-e2e")
    )

    outcome = app.run()

    assert len(outcome.works) == 2
    assert outcome.works[1].status is ProgramWorkStatus.COMPLETED, (
        outcome.works[1].details
    )
    assert [(work.kind, work.status) for work in outcome.works] == [
        (ProgramWorkKind.HOME_MAINTENANCE, ProgramWorkStatus.COMPLETED),
        (ProgramWorkKind.MEMORY_MAINTENANCE, ProgramWorkStatus.COMPLETED),
    ]
    assert outcome.turn_count == 1
    assert outcome.turns[0].business_day == NEW_DAY
    assert outcome.turns[0].output is not None
    assert outcome.turns[0].output.text == "new day complete"
    assert outcome.turns[0].context_completion is not None
    assert "older durable project fact" in repr(
        outcome.turns[0].context_completion.trace
    )
    first_new_day_call = next(
        call
        for call in llm.calls
        if "continue after maintenance" in repr(call.messages)
    )
    assert "durable old-day fact" in repr(first_new_day_call.messages)

    archives = tuple(
        path
        for path in (tmp_path / "archive").iterdir()
        if path.is_dir() and not path.name.startswith(".pending-")
    )
    assert len(archives) == 1
    transition = json.loads(
        (archives[0] / "transition.json").read_text(encoding="utf-8")
    )
    assert transition["from_day"] == str(OLD_DAY)
    assert transition["to_day"] == str(NEW_DAY)
    assert len(tuple((archives[0] / "session" / "turns").glob("*.json"))) == 1
    assert not tuple((tmp_path / "archive").glob(".pending-*"))

    assert actual_home.read_text(encoding="utf-8") == (
        "# Daily preference\n\nKeep the durable preference."
    )
    assert not runtime_home.exists()
    manifest = json.loads(
        (
            tmp_path
            / "runtime"
            / "home"
            / ".tinysoul"
            / "home_overlay.json"
        ).read_text(encoding="utf-8")
    )
    assert all(
        record["relative_path"] != "why/daily_preference.md"
        for record in manifest["records"]
    )
    assert (
        tmp_path / "memory" / "2026" / "07" / "2026-07-14.md"
    ).read_text(encoding="utf-8") == (
        "# 2026-07-14\n\n"
        "- durable old-day fact\n"
        "- preference <home:why@daily_preference>\n"
    )

    names = [event.name for event in observations.events]
    assert names.count("daily.transition.completed") == 1
    assert names.count("home.maintenance.completed") == 1
    assert names.count("memory.maintenance.completed") == 1
    assert names.count("program.work.completed") == 2
    assert not llm.results


class _FakeLLM:
    def __init__(self, results: tuple[TaskResult, ...]) -> None:
        self.results = deque(results)
        self.calls: list[TaskCall] = []

    def run(self, call: TaskCall) -> TaskResult:
        self.calls.append(call)
        return self.results.popleft()


@dataclass
class _ControlledClock:
    current: datetime

    def now(self) -> datetime:
        return self.current

    def today(self) -> BusinessDay:
        return BusinessDay(self.current.date())


@dataclass
class _RecordingSink:
    events: list[ObservationEvent] = field(default_factory=list)

    def write(self, event: ObservationEvent) -> None:
        self.events.append(event)


def _control(
    call_id: str,
    name: str,
    arguments: JsonObject,
) -> ToolCallRecord:
    return ToolCallRecord(
        id=call_id,
        name=name,
        arguments=arguments,
        kind=ToolKind.CONTROL,
    )


def _action(
    call_id: str,
    name: str,
    arguments: JsonObject,
) -> ToolCallRecord:
    return ToolCallRecord(
        id=call_id,
        name=name,
        arguments=arguments,
        kind=ToolKind.ACTION,
    )


def _tool_result(*tool_calls: ToolCallRecord) -> TaskResult:
    return TaskResult.success(
        raw_response=RawResponse(
            answer_text="",
            model_id="fake",
            provider_id="fake",
            tool_calls=tool_calls,
        ),
        answer=None,
        tool_calls=tool_calls,
    )


def _json_result(value: JsonObject) -> TaskResult:
    return TaskResult.success(
        raw_response=RawResponse(
            answer_text="{}",
            model_id="fake",
            provider_id="fake",
        ),
        answer=JsonAnswer(value),
        tool_calls=(),
    )


def _test_config(tmp_path: Path) -> ConfigEnvironment:
    project_root = tmp_path / ".config-project"
    ProjectInitializer().initialize(project_root)
    home_root = tmp_path / "home"
    agent_path = home_root / "agent" / "AGENT.md"
    agent_path.parent.mkdir(parents=True, exist_ok=True)
    agent_path.write_text("# Test Agent\n", encoding="utf-8")
    return ConfigEnvironment.from_project_root(
        root=project_root,
        overrides={
            "app.interactive": False,
            "home.root": str(home_root),
            "home.runtime_root": str(tmp_path / "runtime" / "home"),
            "memory.root": str(tmp_path / "memory"),
            "session.root": str(tmp_path / "runtime" / "session"),
            "workspace.root": str(tmp_path / "runtime" / "workspace"),
            "loop.daily.archive_root": str(tmp_path / "archive"),
        },
    )
