"""TinySoul app runtime entry point."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from functools import partial
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tinysoul.endpoint import EndpointEngine

from tinysoul.loop import TurnOutcome
from tinysoul.infra.concurrency import AsyncResourceScope, CleanupDiagnostic

from .errors import AppInvariantError
from .program import ProgramOutcome, ProgramRunner
from .inputs import InputDispatcher, InputEvent, InputSource
from .gateway import AppCommandGateway
from .outputs import ObservationRouter
from .services import AppService
from .sources import ProgramRequestSource


@dataclass(frozen=True)
class TinySoulApp:
    """Process-level TinySoul application."""

    program_runner: ProgramRunner
    input_dispatcher: InputDispatcher
    gateway: AppCommandGateway
    input_sources: tuple[InputSource, ...] = field(default_factory=tuple)
    program_request_sources: tuple[ProgramRequestSource, ...] = field(default_factory=tuple)
    services: tuple[AppService, ...] = field(default_factory=tuple)
    observations: ObservationRouter = field(default_factory=ObservationRouter)
    endpoint: EndpointEngine | None = None
    resources: AsyncResourceScope = field(default_factory=AsyncResourceScope)

    def __post_init__(self) -> None:
        object.__setattr__(self, "input_sources", tuple(self.input_sources))
        object.__setattr__(self, "services", tuple(self.services))
        object.__setattr__(
            self,
            "program_request_sources",
            tuple(self.program_request_sources),
        )

    async def run(self) -> ProgramOutcome:
        started = AsyncResourceScope()
        self.resources.register("sources", started.close)
        try:
            await self.program_runner.prepare()
            for index, source in enumerate(self.program_request_sources):
                source.start(self.program_runner)
                started.register(f"request_source.{index}", partial(_stop_source, source))
            for index, service in enumerate(self.services):
                await service.start()
                started.register(f"service.{index}", service.stop)
            for index, source in enumerate(self.input_sources):
                source.start(self.gateway)
                started.register(f"input_source.{index}", partial(_stop_source, source))
            outcome = await self.program_runner.run()
        except BaseException:
            try:
                await started.close()
            except asyncio.CancelledError:
                pass
            raise
        diagnostics = await started.close()
        if diagnostics:
            raise AppInvariantError("Failed to stop app sources")
        self.observations.raise_if_failed()
        return outcome

    async def run_once(self, user_input: str) -> TurnOutcome:
        outcome = (await self.program_runner.run_once(user_input))
        self.observations.raise_if_failed()
        return outcome

    def submit_input(self, text: str, *, source: str = "api") -> None:
        self.submit_event(InputEvent(text=text, source=source))

    def submit_event(self, event: InputEvent) -> None:
        self.gateway.submit_user_event(event)

    def submit_interactive_event(self, event: InputEvent) -> None:
        """Submit a trusted local command line."""
        self.gateway.submit(event)

    def submit_user_input(self, text: str, *, source: str = "api") -> None:
        self.gateway.submit_user_input(text, source=source, metadata={})

    async def close(self) -> tuple[CleanupDiagnostic, ...]:
        """Release owned generations after all running work has returned."""
        return await self.resources.close()


async def _stop_source(source: InputSource | ProgramRequestSource) -> None:
    # Source adapters may join an input/scheduler thread. The resource scope
    # shields and joins this callback before returning to its cancelled caller.
    await asyncio.to_thread(source.stop)
