"""TinySoul app runtime entry point."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from tinysoul.agent.commands import AgentCommands

from tinysoul.infra.concurrency import (
    AsyncResourceScope,
    CleanupDiagnostic,
)
from tinysoul.infra.config import ConfigController
from tinysoul.kernel.registration import ServiceRegistry

from ..errors import AgentInvariantError
from tinysoul.agent.dispatch.scheduler import AgentRunResult, RootScheduler
from ..observation.outputs import ObservationRouter
from tinysoul.environment.services import EnvironmentService
from tinysoul.runtime import RuntimeHandle
from ..lifecycle.generation import AgentGeneration
from ..services import AgentRuntimeServices


@dataclass
class AgentRuntime:
    """One active process runtime produced from an :class:`AgentAssembly`."""

    agent_runner: RootScheduler
    commands: AgentCommands
    generation_handle: RuntimeHandle[AgentGeneration]
    configuration: ConfigController
    host_services: tuple[EnvironmentService, ...] = field(default_factory=tuple)
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
    def sdk_services(self) -> ServiceRegistry:
        """SDK facades exported by plugins for the active generation and day."""
        return self.service_access.registry

    @property
    def is_available(self) -> bool:
        """Whether this generation has finished activation and accepts work."""
        return self._activated and self._accepting

    def mount_service(self, service: EnvironmentService) -> None:
        """Attach a gateway host before source activation."""
        if self._activated:
            raise AgentInvariantError("Services must be mounted before activation")
        self.host_services = (*self.host_services, service)

    def __post_init__(self) -> None:
        self.service_access = AgentRuntimeServices(
            self.generation_handle, self.agent_runner, lambda: self._accepting
        )
        object.__setattr__(self, "host_services", tuple(self.host_services))

    async def activate(self) -> None:
        if self._activated:
            return
        started = self._sources
        self.resources.register("sources", started.close)
        try:
            await self.agent_runner.prepare()
            await self.generation_handle.snapshot().generation.sources.start(self.commands.publish_internal)
            started.register("plugin_sources", lambda: self.generation_handle.snapshot().generation.sources.close())
            for index, service in enumerate(self.host_services):
                await service.start()
                started.register(f"service.{index}", service.stop)
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
