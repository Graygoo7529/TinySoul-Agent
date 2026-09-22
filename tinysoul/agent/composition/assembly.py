"""TinySoul app runtime entry point."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path
from tinysoul.agent.commands import AgentCommands
from ..dispatch.inputs import CommandReceipt

from tinysoul.infra.concurrency import (
    AsyncResourceScope,
    CleanupDiagnostic,
    JoinedOperations,
)
from tinysoul.infra.config import ConfigController
from tinysoul.kernel.registration import ServiceRegistry

from ..errors import AgentInvariantError
from tinysoul.agent.dispatch.scheduler import AgentRunResult, RootScheduler
from ..dispatch.inputs import InputDispatcher, InputEvent, InputSource
from ..dispatch.ingress import AgentIngress
from ..observation.outputs import ObservationRouter
from tinysoul.environment.services import EnvironmentService
from tinysoul.runtime import RuntimeHandle
from ..lifecycle.generation import AgentGeneration
from ..services import AgentRuntimeServices


@dataclass
class AgentRuntime:
    """One active process runtime produced from an :class:`AgentAssembly`."""

    agent_runner: RootScheduler
    input_dispatcher: InputDispatcher
    gateway: AgentIngress
    commands: AgentCommands
    generation_handle: RuntimeHandle[AgentGeneration]
    configuration: ConfigController
    input_sources: tuple[InputSource, ...] = field(default_factory=tuple)
    services: tuple[EnvironmentService, ...] = field(default_factory=tuple)
    observations: ObservationRouter = field(default_factory=ObservationRouter)
    resources: AsyncResourceScope = field(default_factory=AsyncResourceScope)
    _sources: AsyncResourceScope = field(default_factory=AsyncResourceScope, init=False)
    _activated: bool = field(default=False, init=False)
    _accepting: bool = field(default=True, init=False)
    service_access: AgentRuntimeServices = field(init=False)

    @property
    def project_root(self) -> Path:
        return self.configuration.root

    @property
    def profile_services(self) -> ServiceRegistry:
        return self.service_access.registry

    @property
    def is_available(self) -> bool:
        """Whether this generation has finished activation and accepts work."""
        return self._activated and self._accepting

    def mount_service(self, service: EnvironmentService) -> None:
        """Attach a gateway host before source activation."""
        if self._activated:
            raise AgentInvariantError("Services must be mounted before activation")
        self.services = (*self.services, service)

    def __post_init__(self) -> None:
        self.service_access = AgentRuntimeServices(
            self.generation_handle, self.agent_runner, lambda: self._accepting
        )
        object.__setattr__(self, "input_sources", tuple(self.input_sources))
        object.__setattr__(self, "services", tuple(self.services))

    async def activate(self) -> None:
        if self._activated:
            return
        started = self._sources
        self.resources.register("sources", started.close)
        thread_sink = _ThreadInputSink(self.gateway, asyncio.get_running_loop())
        operations = JoinedOperations()
        try:
            await self.agent_runner.prepare()
            await self.generation_handle.snapshot().generation.sources.start(self.commands.publish_internal)
            started.register("plugin_sources", lambda: self.generation_handle.snapshot().generation.sources.close())
            for index, service in enumerate(self.services):
                await service.start()
                started.register(f"service.{index}", service.stop)
            for index, source in enumerate(self.input_sources):
                await operations.run(partial(source.start, thread_sink))
                started.register(f"input_source.{index}", partial(_stop_source, source))
                operations.check_cancelled()
            self._activated = True
        except BaseException:
            self.stop_accepting()
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
            self.stop_accepting()
            await self._sources.close()

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
        self.stop_accepting()
        try:
            await self._sources.close()
            await self.configuration.close()
            await self.generation_handle.close()
            return await self.resources.close()
        finally:
            self.observations.subscriptions.close()

    def stop_accepting(self) -> None:
        self._accepting = False
        self.agent_runner.stop_accepting()
        self.configuration.stop_accepting()


async def _stop_source(source: InputSource) -> None:
    # Source adapters may join an input/scheduler thread. The resource scope
    # shields and joins this callback before returning to its cancelled caller.
    await asyncio.to_thread(source.stop)


class _ThreadInputSink:
    """A reader thread waits for the real admission receipt on the Agent loop."""

    def __init__(self, gateway: AgentIngress, loop: asyncio.AbstractEventLoop) -> None:
        self._gateway = gateway
        self._loop = loop

    def submit(self, event: InputEvent) -> CommandReceipt:
        return asyncio.run_coroutine_threadsafe(
            self._gateway.submit(event), self._loop
        ).result()


@dataclass(frozen=True)
class AgentAssembly:
    """Static agent composition definition.

    The definition owns no active source, scheduler, or generation.  A fresh
    :class:`AgentRuntime` is materialized for each start/restart boundary.
    """

    root: Path
    runtime_factory: Callable[[], Awaitable[AgentRuntime]]
    plugin_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.root, Path):
            raise AgentInvariantError("Agent assembly root must be a Path")
        if not callable(self.runtime_factory):
            raise AgentInvariantError("Agent assembly requires a runtime factory")
        plugin_ids = tuple(self.plugin_ids)
        if any(re.fullmatch(r"[a-z][a-z0-9_]*", item) is None for item in plugin_ids):
            raise AgentInvariantError("Agent plugin identities must use lower_snake_case")
        if len(plugin_ids) != len(set(plugin_ids)):
            raise AgentInvariantError("Agent plugin identities must be unique")
        object.__setattr__(self, "plugin_ids", plugin_ids)

    async def build_runtime(self) -> AgentRuntime:
        """Materialize one runtime without activating its sources."""
        return await self.runtime_factory()
