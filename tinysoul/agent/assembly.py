"""TinySoul app runtime entry point."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from functools import partial
from tinysoul.agent.commands import AgentCommands
from tinysoul.plugins.reflection import (ReflectionRequest)
from .inputs import CommandReceipt

from tinysoul.kernel.loop import TurnOutcome
from tinysoul.infra.concurrency import AsyncResourceScope, CleanupDiagnostic, JoinedOperations
from tinysoul.infra.config import ConfigController
from tinysoul.kernel.registration import ServiceRegistry

from .errors import AgentInvariantError
from tinysoul.agent.scheduler import AgentRunResult, RootScheduler
from .inputs import InputDispatcher, InputEvent, InputSource
from .ingress import AgentIngress
from .outputs import ObservationRouter
from tinysoul.environment.services import EnvironmentService
from tinysoul.environment.scheduler import AgentRequestSource
from tinysoul.runtime import RuntimeHandle
from .generation import AgentRuntimeGeneration


@dataclass
class AgentAssembly:
    """Process-level TinySoul application."""

    agent_runner: RootScheduler
    input_dispatcher: InputDispatcher
    gateway: AgentIngress
    commands: AgentCommands
    generation_handle: RuntimeHandle[AgentRuntimeGeneration]
    configuration: ConfigController
    input_sources: tuple[InputSource, ...] = field(default_factory=tuple)
    agent_request_sources: tuple[AgentRequestSource, ...] = field(default_factory=tuple)
    services: tuple[EnvironmentService, ...] = field(default_factory=tuple)
    observations: ObservationRouter = field(default_factory=ObservationRouter)
    resources: AsyncResourceScope = field(default_factory=AsyncResourceScope)
    _sources: AsyncResourceScope = field(default_factory=AsyncResourceScope, init=False)
    _activated: bool = field(default=False, init=False)

    @property
    def profile_services(self) -> ServiceRegistry:
        with self.generation_handle.read() as generation:
            return generation.user_turn.profile.services

    def mount_service(self, service: EnvironmentService) -> None:
        """Attach a gateway host before source activation."""
        if self._activated:
            raise AgentInvariantError("Services must be mounted before activation")
        self.services = (*self.services, service)

    def __post_init__(self) -> None:
        object.__setattr__(self, "input_sources", tuple(self.input_sources))
        object.__setattr__(self, "services", tuple(self.services))
        object.__setattr__(
            self,
            "agent_request_sources",
            tuple(self.agent_request_sources),
        )

    async def activate(self) -> None:
        if self._activated:
            return
        started = self._sources
        self.resources.register("sources", started.close)
        thread_sink = _ThreadInputSink(self.gateway, asyncio.get_running_loop())
        request_sink = _ThreadRequestSink(self.commands, asyncio.get_running_loop())
        operations = JoinedOperations()
        try:
            await self.agent_runner.prepare()
            for index, source in enumerate(self.agent_request_sources):
                await operations.run(partial(source.start, request_sink))
                started.register(f"request_source.{index}", partial(_stop_source, source))
                operations.check_cancelled()
            for index, service in enumerate(self.services):
                await service.start()
                started.register(f"service.{index}", service.stop)
            for index, source in enumerate(self.input_sources):
                await operations.run(partial(source.start, thread_sink))
                started.register(f"input_source.{index}", partial(_stop_source, source))
                operations.check_cancelled()
            self._activated = True
        except BaseException:
            try:
                await started.close()
            except asyncio.CancelledError:
                pass
            raise

    async def run(self) -> AgentRunResult:
        await self.activate()
        try:
            return await self.agent_runner.run()
        finally:
            await self._sources.close()

    async def run_once(
        self,
        user_input: str,
        *,
        request_id: str = "",
        source: str = "",
    ) -> TurnOutcome:
        outcome = (await self.agent_runner.run_once(
            user_input,
            request_id=request_id,
            source=source,
        ))
        return outcome

    async def submit_input(self, text: str, *, source: str = "api") -> None:
        await self.submit_event(InputEvent(text=text, source=source))

    async def submit_event(self, event: InputEvent) -> None:
        await self.gateway.submit_user_event(event)

    async def submit_interactive_event(self, event: InputEvent) -> None:
        """Submit a trusted local command line."""
        await self.gateway.submit(event)

    async def submit_user_input(self, text: str, *, source: str = "api") -> None:
        await self.gateway.submit_user_input(text, source=source, metadata={})

    async def close(self) -> tuple[CleanupDiagnostic, ...]:
        """Release owned generations after all running work has returned."""
        try:
            return await self.resources.close()
        finally:
            self.observations.subscriptions.close()


async def _stop_source(source: InputSource | AgentRequestSource) -> None:
    # Source adapters may join an input/scheduler thread. The resource scope
    # shields and joins this callback before returning to its cancelled caller.
    await asyncio.to_thread(source.stop)


class _ThreadInputSink:
    """A reader thread waits for the real admission receipt on the Agent loop."""

    def __init__(self, gateway: AgentIngress, loop: asyncio.AbstractEventLoop) -> None:
        self._gateway = gateway
        self._loop = loop

    def submit(self, event: InputEvent) -> CommandReceipt:
        return asyncio.run_coroutine_threadsafe(self._gateway.submit(event), self._loop).result()


class _ThreadRequestSink:
    def __init__(self, commands: AgentCommands, loop: asyncio.AbstractEventLoop) -> None:
        self._commands = commands
        self._loop = loop

    def submit_request(self, request: ReflectionRequest) -> bool:
        from tinysoul.agent.errors import AgentClosedError, AgentQueueFullError

        try:
            asyncio.run_coroutine_threadsafe(self._commands.request_reflection(request), self._loop).result()
        except (AgentClosedError, AgentQueueFullError):
            return False
        return True
