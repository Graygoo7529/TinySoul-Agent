from __future__ import annotations

from datetime import UTC, datetime
import json

import pytest

from tinysoul.infra.json import JsonObject
from tinysoul.infra.time import BusinessDay
from tinysoul.llm import JsonAnswer, RawResponse, TaskCall, TaskProfile, TaskResult
from tinysoul.memory import (
    ActiveMemoryDocument,
    ActiveMemorySnapshot,
    DailyCompositionRequest,
    LLMDailyMemoryComposer,
    MemoryContractError,
    MemoryDailyCompositionSettings,
)
from tinysoul.runtime import RunScope
from tinysoul.session import SessionMemoryFact, SessionMemoryFactsProjection


DAY = BusinessDay.parse("2026-07-12")


def test_daily_composer_uses_target_sources_and_current_task_profile() -> None:
    runner = _Runner()
    composer = LLMDailyMemoryComposer(runner)
    active = ActiveMemorySnapshot(
        document=ActiveMemoryDocument(
            day=DAY.value,
            revision=2,
            updated_at=datetime(2026, 7, 12, 10, tzinfo=UTC),
            content="Explicit target Memory.",
        ),
        text="active",
        digest="a" * 64,
    )
    projection = SessionMemoryFactsProjection(
        day=DAY,
        revision=3,
        facts=(
            SessionMemoryFact(
                ref="session:turn/one",
                started_at=datetime(2026, 7, 12, 9, tzinfo=UTC),
                user_inputs=("Remember the design decision",),
                answer="Done",
            ),
        ),
    )
    result = composer.compose(
        DailyCompositionRequest(
            day=DAY,
            session=projection,
            active_memory=active,
            latest=None,
            existing=None,
            settings=MemoryDailyCompositionSettings(
                chunk_max_chars=4000,
                source_max_chars=12000,
                max_calls=4,
            ),
            max_document_chars=32000,
        ),
        scope=RunScope(),
    )

    assert result.content == "## Events\n\n- Preserved target-day decision."
    assert result.model_calls == 2
    assert all(
        call.profile is TaskProfile.MEMORY_DAILY_COMPOSITION
        for call in runner.calls
    )
    rendered = repr(runner.calls[0].messages.messages)
    assert "Explicit target Memory" in rendered
    assert "Remember the design decision" in rendered


def test_daily_composer_enforces_call_budget_before_calling_model() -> None:
    runner = _Runner()
    composer = LLMDailyMemoryComposer(runner)
    active = ActiveMemorySnapshot(
        document=ActiveMemoryDocument(DAY.value, 0, None, "x" * 300),
        text="active",
        digest="b" * 64,
    )
    request = DailyCompositionRequest(
        day=DAY,
        session=SessionMemoryFactsProjection(day=DAY, revision=0),
        active_memory=active,
        latest=None,
        existing=None,
        settings=MemoryDailyCompositionSettings(
            chunk_max_chars=100,
            source_max_chars=1000,
            max_calls=2,
        ),
        max_document_chars=32000,
    )
    with pytest.raises(MemoryContractError, match="too many"):
        composer.compose(request, scope=RunScope())
    assert runner.calls == []


class _Runner:
    def __init__(self) -> None:
        self.calls: list[TaskCall] = []

    def run(self, call: TaskCall) -> TaskResult:
        self.calls.append(call)
        final = any(
            message.label == "memory_daily_output"
            for message in call.messages.messages
        )
        value: JsonObject = {
            "content": (
                "## Events\n\n- Preserved target-day decision."
                if final
                else "- Reduced target-day decision."
            )
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
