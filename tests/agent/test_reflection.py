from __future__ import annotations
import asyncio
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import pytest
from tests.support.project import create_test_project
from tinysoul.agent import Agent, UserTurnRequest
from tinysoul.agent.composition.builder import standard_agent
from tinysoul.agent.config import AgentSettings
from tinysoul.infra.config import ConfigEnvironment, ConfigError
from tinysoul.infra.time import CalendarDay
from tinysoul.kernel.interaction import AnswerKind, QuestionAnswer
from tinysoul.kernel.loop.interaction.inbox import WaitReason
from tinysoul.kernel.loop.outcomes import TurnOutcomeStatus
from tinysoul.llm.protocol.responses import RawResponse, TaskResult
from tinysoul.llm.protocol.tools import ToolCallRecord, ToolKind
from tinysoul.plugins.home import AgentHomeEngineBuilder, AgentHomeSettings
from tinysoul.plugins.memory import MemoryEngine, MemoryRef
from tinysoul.plugins.reflection import (
    ReflectionOutcome,
    ReflectionRequest,
    ReflectionScope,
    ReflectionStatus,
    ReflectionTrigger,
)
from tests.agent.support import (
    _Clock,
    _LLM,
    _create,
)

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("source", ("current", "archive", "daily_only"))
async def test_memory_reflection_revises_daily_from_fixed_target_sources(
    tmp_path: Path, source: str
) -> None:
    from tinysoul.plugins.memory import DailyMemoryDocument, MemorySettings

    clock = _Clock()
    root = tmp_path / "project"
    create_test_project(root)
    target = CalendarDay.parse("2026-09-14" if source == "daily_only" else "2026-09-15")
    if source == "daily_only":
        seed = MemoryEngine(settings=MemorySettings(root=root / "memory"))
        seed.write_document(
            DailyMemoryDocument(
                day=target.value,
                created_on=target.value,
                updated_on=target.value,
                content="Morning notes.",
            )
        )
    llm = _LLM()
    llm.release.set()
    builder = (
        standard_agent(root)
        .with_config_environment(
            ConfigEnvironment.from_project_root(
                root, env={}, overrides={"reflection.schedule.enabled": False}
            )
        )
        .with_agent_settings(AgentSettings(interactive=False))
        .with_calendar_clock(clock)
        .with_llm_runner(llm)
    )
    agent = await Agent.assemble(builder.build())
    await agent.start()
    try:
        user = await agent.submit_turn(UserTurnRequest("Remember this discussion"))
        assert (await user.wait()).status is TurnOutcomeStatus.ANSWERED
        if source == "archive":
            clock.value = datetime(2026, 9, 16, 12, tzinfo=ZoneInfo("Asia/Shanghai"))
        for index, trigger in enumerate(
            (ReflectionTrigger.MANUAL, ReflectionTrigger.SCHEDULED)
        ):
            content = (
                "Morning and afternoon, reorganized."
                if index == 0
                else "Morning revised, afternoon and evening."
            )
            calls = [
                ToolCallRecord(
                    "select_memory",
                    "select_action_domains",
                    {"domains": ["memory"]},
                    ToolKind.CONTROL,
                )
            ]
            if index or source == "daily_only":
                calls.extend(
                    (
                        ToolCallRecord(
                            "recall_daily",
                            "memory.inspect",
                            {"ref": str(MemoryRef.daily(target.value))},
                            ToolKind.ACTION,
                        ),
                        ToolCallRecord(
                            "select_write",
                            "select_action_domains",
                            {"domains": ["memory"]},
                            ToolKind.CONTROL,
                        ),
                    )
                )
            calls.append(
                ToolCallRecord(
                    "write_daily",
                    "memory.write_daily",
                    {"markdown": content},
                    ToolKind.ACTION,
                )
            )
            for call in calls:
                llm.results.append(
                    TaskResult.success(
                        raw_response=RawResponse(
                            "", "fake", "fake", tool_calls=(call,)
                        ),
                        answer=None,
                        tool_calls=(call,),
                    )
                )
            llm.results.extend(_LLM().results)
            handle = await agent.submit_turn(
                ReflectionRequest(
                    scope=ReflectionScope.MEMORY,
                    trigger=trigger,
                    target_day=target,
                )
            )
            result = await asyncio.wait_for(handle.wait(), 10)
            assert isinstance(result.outcome, ReflectionOutcome)
            turn = next(
                task.turn_outcome
                for task in result.outcome.tasks
                if task.turn_outcome is not None
            )
            assert turn.status is TurnOutcomeStatus.COMPLETED, turn.failure
            assert turn.active_day == clock.today()
            assert turn.context_completion is not None
            segments = turn.context_completion.segments
            session = segments["session"]
            assert isinstance(session, dict) and session["day"] == str(target)
            if source == "archive":
                archived = segments["workspace_archive"]
                assert isinstance(archived, dict) and archived["source_day"] == str(
                    target
                )
            else:
                archived = segments["workspace_archive"]
                assert isinstance(archived, dict) and archived["source_day"] is None
            persisted = (
                root / "memory" / MemoryRef.daily(target.value).relative_path
            ).read_text(encoding="utf-8")
            assert content in persisted
        records = tuple((root / "runtime" / "session").rglob("turns/*.json"))
        assert len(records) == (0 if source == "archive" else 1)
    finally:
        await agent.shutdown()


async def test_home_reflection_waits_and_retains_full_turn_without_user_session(
    tmp_path: Path,
) -> None:
    llm = _LLM()
    for call in reversed(
        (
            ToolCallRecord(
                "select_question",
                "select_action_domains",
                {"domains": ["core"]},
                ToolKind.CONTROL,
            ),
            ToolCallRecord(
                "ask",
                "core.ask",
                {"question": "Keep this preference?"},
                ToolKind.ACTION,
            ),
        )
    ):
        llm.results.appendleft(
            TaskResult.success(
                raw_response=RawResponse("", "fake", "fake", tool_calls=(call,)),
                answer=None,
                tool_calls=(call,),
            )
        )
    llm.release.set()
    agent = await _create(tmp_path, llm)
    root = tmp_path / "project"
    home = AgentHomeEngineBuilder(
        AgentHomeSettings(
            original_root=root / "home",
            runtime_root=root / "runtime" / "home",
        )
    ).build()
    home.write_top("home:top/agent/preference", "Use concise explanations.")
    await agent.start()
    try:
        handle = await agent.submit_turn(
            ReflectionRequest(
                scope=ReflectionScope.HOME,
                trigger=ReflectionTrigger.MANUAL,
                instructions="Only review the requested communication preference.",
            )
        )
        assert await agent.submit_turn(handle.request) is handle
        async with asyncio.timeout(4):
            while handle.wait_reason is not WaitReason.INPUT:
                assert not handle.done
                await asyncio.sleep(0.01)
        question = handle.question
        assert question is not None
        assert any(
            "Only review the requested communication preference." in str(call)
            for call in llm.calls
        )
        with pytest.raises(ConfigError) as busy:
            await agent.reload_config()
        assert busy.value.key == "config.activation_unavailable"
        await agent.reply(
            handle.request_id,
            question.question_id,
            QuestionAnswer(AnswerKind.TEXT, text="Keep it"),
        )
        result = await asyncio.wait_for(handle.wait(), 5)
        assert isinstance(result.outcome, ReflectionOutcome)
        assert result.outcome.status is ReflectionStatus.COMPLETED
        turn = result.outcome.tasks[-1].turn_outcome
        assert turn is not None and turn.context_completion is not None
        assert turn.context_completion.inputs[-1].reply_to == question.question_id
        assert result.outcome.to_json()["tasks"]
        assert not tuple((root / "runtime" / "session").rglob("turns/*.json"))
    finally:
        await agent.shutdown()
