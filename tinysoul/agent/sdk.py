"""Agent lifecycle and request facade over the single root dispatcher."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from tinysoul.infra.concurrency import CleanupDiagnostic, JoinedOperations
from tinysoul.infra.config import ConfigController, ConfigMutation
from tinysoul.infra.json import JsonObject
from tinysoul.kernel.loop.inbox import InboxLimits, InboxReceipt
from tinysoul.plugins.reflection.models import ReflectionRequest
from tinysoul.runtime.events import EnvironmentEvent, EventReceipt

from .errors import AgentClosedError, AgentSDKError
from .handles import TurnHandle
from .requests import UserTurnRequest
from .commands import AgentCommands
from .observations import ObservationFilter, ObservationSubscription
from tinysoul.kernel.registration import ServiceRegistry

if TYPE_CHECKING:
    from tinysoul.agent.scheduler import AgentRunResult
    from tinysoul.agent.assembly import AgentAssembly


class AgentState(StrEnum):
    CREATED = "created"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    FAULTED = "faulted"


class _AssemblyFactory(Protocol):
    def __call__(self) -> Awaitable[AgentAssembly]: ...


@dataclass(frozen=True)
class AgentSnapshot:
    state: AgentState
    active_turn_id: str | None
    queued_turn_ids: tuple[str, ...]
    observation_failures: tuple[CleanupDiagnostic, ...] = ()


class Agent:
    """Own one assembled generation and one root scheduling task."""

    def __init__(self, assembly_factory: _AssemblyFactory, *, queue_capacity: int = 32,
                 inbox_limits: InboxLimits = InboxLimits()) -> None:
        if type(queue_capacity) is not int or queue_capacity <= 0:
            raise AgentSDKError("queue_capacity must be a positive integer")
        self._factory = assembly_factory
        self._capacity = queue_capacity
        if not isinstance(inbox_limits, InboxLimits):
            raise AgentSDKError("Agent requires typed Inbox limits")
        self._inbox_limits = inbox_limits
        self._state = AgentState.CREATED
        self._assembly: AgentAssembly | None = None
        self._worker: asyncio.Task[AgentRunResult] | None = None
        self._shutdown_task: asyncio.Task[tuple[CleanupDiagnostic, ...]] | None = None
        self._start_task: asyncio.Task[None] | None = None
        self._restart_task: asyncio.Task[tuple[CleanupDiagnostic, ...]] | None = None

    @classmethod
    async def create(
        cls, root: Path | str, *, overrides: Mapping[str, object] | None = None,
        queue_capacity: int = 32,
        inbox_limits: InboxLimits = InboxLimits(),
    ) -> Agent:
        """Build an embedded Agent from project configuration without listening."""
        from tinysoul.agent.builder import AgentBuilder
        from tinysoul.infra.config import ConfigEnvironment

        project_root = Path(root).resolve()
        config_overrides = {"app.interactive": False, **dict(overrides or {})}

        async def factory() -> AgentAssembly:
            config = ConfigEnvironment.from_project_root(project_root, overrides=config_overrides)
            return await AgentBuilder(project_root).with_config_environment(config).build()

        return await cls.assemble(factory, queue_capacity=queue_capacity, inbox_limits=inbox_limits)

    @classmethod
    async def assemble(cls, assembly_factory: _AssemblyFactory, *, queue_capacity: int = 32,
                       inbox_limits: InboxLimits = InboxLimits()) -> Agent:
        """Assemble resources without starting sources or accepting work."""
        agent = cls(assembly_factory, queue_capacity=queue_capacity, inbox_limits=inbox_limits)
        agent._assembly = await assembly_factory()
        return agent

    @property
    def state(self) -> AgentState:
        return self._state

    def status(self) -> AgentSnapshot:
        app = self._assembly
        active = app.agent_runner.active_turn if app is not None else None
        return AgentSnapshot(
            self._state, active.turn_id if active is not None else None,
            app.agent_runner.queued_turn_ids if app is not None else (),
            app.observations.failures if app is not None else (),
        )

    async def start(self) -> None:
        if self._restart_task is not None and not self._restart_task.done() and asyncio.current_task() is not self._restart_task:
            raise AgentClosedError("Agent is restarting")
        if self._state is AgentState.RUNNING:
            return
        if self._state is AgentState.STOPPING:
            raise AgentClosedError("Agent is stopping")
        if self._start_task is None or self._start_task.done():
            self._shutdown_task = None
            self._start_task = asyncio.create_task(self._start(), name="tinysoul-start")
        operation = JoinedOperations()
        task = self._start_task
        await operation.run_async(lambda: task)
        operation.check_cancelled()

    async def _start(self) -> None:
        try:
            if self._state in {AgentState.STOPPED, AgentState.FAULTED} and self._assembly is not None:
                await self._assembly.close()
                self._assembly = None
            if self._assembly is None:
                self._assembly = await self._factory()
            self._assembly.agent_runner.set_capacity(self._capacity, self._inbox_limits)
            await self._assembly.activate()
            if self._state is AgentState.STOPPING:
                raise asyncio.CancelledError
            self._worker = asyncio.create_task(self._serve(self._assembly), name="tinysoul-agent")
            self._worker.add_done_callback(self._stopped)
            self._state = AgentState.RUNNING
        except BaseException:
            if self._assembly is not None:
                try:
                    await self._assembly.close()
                finally:
                    self._assembly = None
            if self._state is not AgentState.STOPPING:
                self._state = AgentState.FAULTED
            raise

    @property
    def commands(self) -> AgentCommands:
        return self._running_assembly().commands

    @property
    def services(self) -> ServiceRegistry:
        """Current User profile's typed services for embedded integrations."""
        return self._running_assembly().profile_services

    async def submit_turn(self, request: UserTurnRequest | ReflectionRequest) -> TurnHandle:
        return await self.commands.submit_turn(request)

    async def cancel_turn(self, turn_id: str) -> bool:
        return await self.commands.cancel_turn(turn_id)

    async def append_input(self, turn_id: str, text: str, *, input_id: str = "") -> InboxReceipt:
        return await self.commands.append_input(turn_id, text, input_id=input_id)

    async def grant_cycles(self, turn_id: str, request_id: str, count: int) -> bool:
        return await self.commands.grant_cycles(turn_id, request_id, count)

    async def reply(self, turn_id: str, question_id: str, response: str) -> InboxReceipt:
        return await self.commands.reply(turn_id, question_id, response)

    async def publish(self, event: EnvironmentEvent) -> EventReceipt:
        return await self.commands.publish(event)

    async def config_status(self) -> JsonObject:
        controller = self._configuration()
        operations = JoinedOperations()
        result = await operations.run(controller.status)
        operations.check_cancelled()
        return result

    async def patch_config(self, mutations: tuple[ConfigMutation, ...]) -> JsonObject:
        return await self._configuration().patch(mutations)

    async def reload_config(self) -> JsonObject:
        return await self._configuration().reload()

    def _configuration(self) -> ConfigController:
        return self._running_assembly().configuration

    def subscribe(
        self, selection: ObservationFilter = ObservationFilter(), *,
        capacity: int = 256, max_bytes: int = 1024 * 1024,
    ) -> ObservationSubscription:
        if self._assembly is None or self._state not in {AgentState.CREATED, AgentState.RUNNING}:
            raise AgentClosedError("Agent observation source is closed")
        return self._assembly.observations.subscriptions.subscribe(selection, capacity=capacity, max_bytes=max_bytes)

    async def wait(self) -> AgentRunResult:
        if self._worker is None:
            raise AgentClosedError("Agent has not started")
        return await asyncio.shield(self._worker)

    async def shutdown(self) -> tuple[CleanupDiagnostic, ...]:
        restarting = self._restart_task
        if restarting is not None and not restarting.done() and asyncio.current_task() is not restarting:
            restarting.cancel()
        if self._shutdown_task is None:
            self._state = AgentState.STOPPING
            if self._assembly is not None:
                self._assembly.stop_accepting()
            if self._start_task is not None and not self._start_task.done():
                self._start_task.cancel()
            self._shutdown_task = asyncio.create_task(self._shutdown(), name="tinysoul-shutdown")
        task = self._shutdown_task
        operation = JoinedOperations()
        diagnostics = await operation.run_async(lambda: task)
        operation.check_cancelled()
        return diagnostics

    async def _shutdown(self) -> tuple[CleanupDiagnostic, ...]:
        diagnostics: tuple[CleanupDiagnostic, ...] = ()
        try:
            if self._start_task is not None:
                try:
                    await self._start_task
                except (Exception, asyncio.CancelledError):
                    # Startup owns its primary failure and partial resources.
                    pass
            if self._worker is not None:
                self._worker.cancel()
                try:
                    await self._worker
                except asyncio.CancelledError:
                    pass
                except Exception as exc:
                    diagnostics += (CleanupDiagnostic("agent.dispatch", type(exc).__name__),)
            if self._assembly is not None:
                await self._assembly.agent_runner.close_requests()
                diagnostics += await self._assembly.close()
        finally:
            self._worker = None
            self._assembly = None
            self._state = AgentState.STOPPED
        return diagnostics

    async def restart(self) -> tuple[CleanupDiagnostic, ...]:
        if self._restart_task is None or self._restart_task.done():
            if self._shutdown_task is not None and self._shutdown_task.done():
                self._shutdown_task = None
            self._state = AgentState.STOPPING
            if self._assembly is not None:
                self._assembly.stop_accepting()
            self._restart_task = asyncio.create_task(self._restart(), name="tinysoul-restart")
        task = self._restart_task
        operation = JoinedOperations()
        diagnostics = await operation.run_async(lambda: task)
        operation.check_cancelled()
        return diagnostics

    async def _restart(self) -> tuple[CleanupDiagnostic, ...]:
        diagnostics = await self.shutdown()
        await self.start()
        return diagnostics

    def _running_assembly(self) -> AgentAssembly:
        if self._state is not AgentState.RUNNING or self._assembly is None:
            raise AgentClosedError("Agent is not accepting work")
        return self._assembly

    async def _serve(self, app: AgentAssembly) -> AgentRunResult:
        try:
            return await app.run()
        finally:
            app.stop_accepting()
            await app.agent_runner.close_requests()
            app.observations.subscriptions.close()

    def _stopped(self, task: asyncio.Task[AgentRunResult]) -> None:
        if task is not self._worker or self._state is AgentState.STOPPING:
            return
        self._state = AgentState.FAULTED if task.cancelled() or task.exception() else AgentState.STOPPED
