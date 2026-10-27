from __future__ import annotations
import asyncio
from collections import deque
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from tests.support.project import create_test_project
from tinysoul.agent import Agent, InboxLimits
from tinysoul.agent.composition.builder import standard_agent
from tinysoul.agent.config import AgentSettings
from tinysoul.gateway.endpoint import (
    EndpointEngine,
    EndpointEventBuffer,
    EndpointSettings,
)
from tinysoul.gateway.presentation import PresentationService
from tinysoul.infra.clock import CalendarClock
from tinysoul.infra.config import ConfigEnvironment
from tinysoul.infra.time import CalendarDay
from tinysoul.llm.protocol.requests import TaskCall
from tinysoul.llm.protocol.responses import TextAnswer, RawResponse, TaskResult
from tinysoul.llm.protocol.tools import ToolCallRecord, ToolKind


class _LLM:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.calls: list[TaskCall] = []
        calls = (
            ToolCallRecord(
                "select",
                "select_action_domains",
                {"domains": ["core"]},
                ToolKind.CONTROL,
            ),
            ToolCallRecord(
                "answer",
                "core.answer",
                {"guide_blocks": [{"text": "answer"}]},
                ToolKind.ACTION,
            ),
        )
        self.results = deque(
            [
                *(
                    TaskResult.success(
                        raw_response=RawResponse(
                            "", "fake", "fake", tool_calls=(call,)
                        ),
                        answer=None,
                        tool_calls=(call,),
                    )
                    for call in calls
                ),
                TaskResult.success(
                    raw_response=RawResponse("done", "fake", "fake"),
                    answer=TextAnswer("done"),
                    tool_calls=(),
                ),
            ]
        )

    async def invoke(self, call: TaskCall) -> TaskResult:
        return await self.run(call)

    async def run(self, call: TaskCall) -> TaskResult:
        self.calls.append(call)
        self.started.set()
        await self.release.wait()
        return self.results.popleft()


class _Clock:
    value = datetime(2026, 9, 15, 12, tzinfo=ZoneInfo("Asia/Shanghai"))

    def now(self):
        return self.value

    def today(self):
        return CalendarDay(self.value.date())


async def _create(
    root: Path,
    llm: _LLM,
    *,
    capacity: int = 1,
    inbox_limits: InboxLimits = InboxLimits(),
    clock: CalendarClock | None = None,
    endpoints: list[EndpointEngine] | None = None,
    max_cycles: int = 20,
    watch_workspace: bool = False,
) -> Agent:
    root = root / "project"
    create_test_project(root)

    builder = (
        standard_agent(root)
        .with_config_environment(
            ConfigEnvironment.from_project_root(
                root,
                env={},
                overrides={
                    "reflection.schedule.enabled": False,
                    "loop.user.max_cycles": max_cycles,
                    **({} if watch_workspace else {"workspace.watch.enabled": False}),
                },
            )
        )
        .with_agent_settings(AgentSettings(interactive=False))
        .with_llm_runner(llm)
    )
    if clock is not None:
        builder.with_calendar_clock(clock)
    agent = await Agent.assemble(
        builder.build(), queue_capacity=capacity, inbox_limits=inbox_limits
    )
    if endpoints is not None:
        runtime = agent.runtime
        endpoints.append(
            EndpointEngine(
                presentation=PresentationService(runtime.project_root),
                settings=EndpointSettings(token="x" * 32),
                events=EndpointEventBuffer(capacity=32, max_bytes=100000),
                gateway=runtime.gateway,
                services=runtime.service_access,
                config=runtime.configuration,
                available=lambda: runtime.is_available,
            )
        )
    return agent
