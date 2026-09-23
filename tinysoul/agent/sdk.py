"""Agent lifecycle and request facade over the single root dispatcher."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING

from tinysoul.infra.concurrency import CleanupDiagnostic, JoinedOperations
from tinysoul.infra.config import ConfigController, ConfigMutation
from tinysoul.infra.time import CalendarDay
from tinysoul.infra.json import JsonObject
from tinysoul.kernel.loop.interaction.inbox import InboxLimits, InboxReceipt
from tinysoul.plugins.reflection.models import ReflectionRequest
from tinysoul.runtime.events import EnvironmentEvent, EventReceipt
from tinysoul.runtime.sources import SourceStatus

from .errors import AgentClosedError, AgentSDKError
from .handles import RequestFailure, TurnHandle, TurnSnapshot
from tinysoul.kernel.jobs import JobSnapshot
from .requests import UserTurnRequest
from .commands import AgentCommands
from .observation.observations import ObservationFilter, ObservationSubscription
from tinysoul.kernel.registration import ServiceRegistry

if TYPE_CHECKING:
    from tinysoul.agent.dispatch.scheduler import AgentRunResult
    from tinysoul.agent.composition.assembly import AgentAssembly, AgentRuntime


class AgentState(StrEnum):
    CREATED = "created"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    FAULTED = "faulted"


@dataclass(frozen=True)
class AgentSnapshot:
    state: AgentState
    active_turn_id: str | None
    queued_turn_ids: tuple[str, ...]
    observation_failures: tuple[CleanupDiagnostic, ...] = ()
    sources: tuple[SourceStatus, ...] = ()


class Agent:
    """Own one assembled generation and one root scheduling task."""

    def __init__(
        self,
        assembly: AgentAssembly,
        *,
        queue_capacity: int = 32,
        inbox_limits: InboxLimits = InboxLimits(),
    ) -> None:
        if type(queue_capacity) is not int or queue_capacity <= 0:
            raise AgentSDKError("queue_capacity must be a positive integer")
        self._assembly_definition = assembly
        self._capacity = queue_capacity
        if not isinstance(inbox_limits, InboxLimits):
            raise AgentSDKError("Agent requires typed Inbox limits")
        self._inbox_limits = inbox_limits
        self._state = AgentState.CREATED
        self._runtime: AgentRuntime | None = None
        self._worker: asyncio.Task[AgentRunResult] | None = None
        self._completion: asyncio.Future[AgentRunResult] | None = None
        self._shutdown_task: asyncio.Task[tuple[CleanupDiagnostic, ...]] | None = None
        self._start_task: asyncio.Task[None] | None = None
        self._restart_task: asyncio.Task[tuple[CleanupDiagnostic, ...]] | None = None

    @classmethod
    async def create(
        cls,
        root: Path | str,
        *,
        overrides: Mapping[str, object] | None = None,
        queue_capacity: int = 32,
        inbox_limits: InboxLimits = InboxLimits(),
    ) -> Agent:
        """Build an embedded Agent from project configuration without listening."""
        from tinysoul.agent.composition.builder import standard_agent
        from tinysoul.infra.config import ConfigEnvironment

        project_root = Path(root).resolve()
        config_overrides = {"agent.interactive": False, **dict(overrides or {})}

        config = ConfigEnvironment.from_project_root(
            project_root, overrides=config_overrides
        )
        assembly = standard_agent(project_root).with_config_environment(config).build()
        return await cls.assemble(
            assembly, queue_capacity=queue_capacity, inbox_limits=inbox_limits
        )

    @classmethod
    async def assemble(
        cls,
        assembly: AgentAssembly,
        *,
        queue_capacity: int = 32,
        inbox_limits: InboxLimits = InboxLimits(),
    ) -> Agent:
        """Assemble resources without starting sources or accepting work."""
        agent = cls(assembly, queue_capacity=queue_capacity, inbox_limits=inbox_limits)
        agent._runtime = await assembly.build_runtime()
        return agent

    @property
    def state(self) -> AgentState:
        return self._state

    @property
    def runtime(self) -> AgentRuntime:
        """Current runtime for explicit host integration.

        Restart replaces this object; host bindings must then be reacquired.
        """
        if self._runtime is None:
            raise AgentClosedError("Agent runtime is not prepared")
        return self._runtime

    def status(self) -> AgentSnapshot:
        runtime = self._runtime
        active = runtime.agent_runner.active_turn if runtime is not None else None
        return AgentSnapshot(
            self._state,
            active.turn_id if active is not None else None,
            runtime.agent_runner.queued_turn_ids if runtime is not None else (),
            runtime.observations.failures if runtime is not None else (),
            runtime.generation_handle.snapshot().generation.sources.statuses if runtime is not None else (),
        )

    async def start(self) -> None:
        if (
            self._restart_task is not None
            and not self._restart_task.done()
            and asyncio.current_task() is not self._restart_task
        ):
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
            if (
                self._state in {AgentState.STOPPED, AgentState.FAULTED}
                and self._runtime is not None
            ):
                await self._runtime.close()
                self._runtime = None
            if self._runtime is None:
                self._runtime = await self._assembly_definition.build_runtime()
            runtime = self._runtime
            runtime.agent_runner.set_capacity(self._capacity, self._inbox_limits)
            await runtime.activate()
            if self._state is AgentState.STOPPING:
                raise asyncio.CancelledError
            if self._completion is None or self._completion.done():
                self._completion = asyncio.get_running_loop().create_future()
            self._worker = asyncio.create_task(
                self._serve(runtime), name="tinysoul-agent"
            )
            self._worker.add_done_callback(self._stopped)
            self._state = AgentState.RUNNING
        except BaseException as exc:
            if self._runtime is not None:
                runtime = self._runtime
                runtime.stop_accepting()
                cancelled = isinstance(exc, asyncio.CancelledError)

                async def close_failed_start() -> None:
                    try:
                        await runtime.agent_runner.close_requests(
                            request_failure=(
                                RequestFailure.CANCELLED if cancelled
                                else RequestFailure.FAILED
                            ),
                            error_type=None if cancelled else type(exc).__name__,
                        )
                    finally:
                        await runtime.close()

                try:
                    # Join partial-start cleanup before propagating its original
                    # failure, even when shutdown cancels startup again.
                    await JoinedOperations().finish(close_failed_start)
                finally:
                    self._runtime = None
            if self._state is not AgentState.STOPPING:
                self._state = AgentState.FAULTED
            raise

    @property
    def commands(self) -> AgentCommands:
        return self._running_runtime().commands

    @property
    def services(self) -> ServiceRegistry:
        """Plugin-exported SDK facades for the active generation and day."""
        return self._running_runtime().sdk_services

    async def submit_turn(
        self, request: UserTurnRequest | ReflectionRequest
    ) -> TurnHandle:
        return await self.commands.submit_turn(request)

    async def cancel_turn(self, turn_id: str) -> bool:
        return await self.commands.cancel_turn(turn_id)

    async def append_input(
        self, turn_id: str, text: str, *, input_id: str = ""
    ) -> InboxReceipt:
        return await self.commands.append_input(turn_id, text, input_id=input_id)

    async def grant_cycles(self, turn_id: str, request_id: str, count: int) -> bool:
        return await self.commands.grant_cycles(turn_id, request_id, count)

    async def reply(
        self, turn_id: str, question_id: str, response: str
    ) -> InboxReceipt:
        return await self.commands.reply(turn_id, question_id, response)

    async def publish(self, event: EnvironmentEvent) -> EventReceipt:
        return await self.commands.publish(event)

    async def config_status(self) -> JsonObject:
        controller = self._configuration()
        operations = JoinedOperations()
        result = await operations.run(controller.status)
        operations.check_cancelled()
        return result

    async def action_catalog(self, *, scenario: str = "user") -> JsonObject:
        """Inspect the configured and available actions of one execution scenario."""
        return await self._running_runtime().service_access.action_catalog(
            scenario=scenario
        )

    async def reflection_status(
        self, *, before: CalendarDay | None = None
    ) -> JsonObject:
        """Read a bounded page of owner-derived Reflection candidates."""
        return await self._running_runtime().service_access.reflection_status(
            before=before
        )

    def turn_snapshot(self, turn_id: str) -> TurnSnapshot | None:
        return self._running_runtime().service_access.turn_snapshot(turn_id)

    def runtime_status(self) -> JsonObject:
        return self._running_runtime().service_access.runtime_status()

    def turn_jobs(self, turn_id: str) -> tuple[JobSnapshot, ...] | None:
        return self._running_runtime().service_access.turn_jobs(turn_id)

    async def stop_job(self, turn_id: str, job_id: str) -> JobSnapshot:
        return await self._running_runtime().service_access.stop_job(turn_id, job_id)

    async def patch_config(self, mutations: tuple[ConfigMutation, ...]) -> JsonObject:
        return await self._configuration().patch(mutations)

    async def reload_config(self) -> JsonObject:
        return await self._configuration().reload()

    def _configuration(self) -> ConfigController:
        return self._running_runtime().configuration

    def subscribe(
        self,
        selection: ObservationFilter = ObservationFilter(),
        *,
        capacity: int = 256,
        max_bytes: int = 1024 * 1024,
    ) -> ObservationSubscription:
        if self._runtime is None or self._state not in {
            AgentState.CREATED,
            AgentState.RUNNING,
        }:
            raise AgentClosedError("Agent observation source is closed")
        return self._runtime.observations.subscriptions.subscribe(
            selection, capacity=capacity, max_bytes=max_bytes
        )

    async def wait_for_exit(self) -> AgentRunResult:
        """Wait across restarts for the root dispatcher to exit.

        Cancelling a waiter only detaches it. Explicit shutdown cancels pending
        exit waiters; callers must still call shutdown to release resources.
        """
        if self._completion is None:
            raise AgentClosedError("Agent has not started")
        return await asyncio.shield(self._completion)

    async def shutdown(self) -> tuple[CleanupDiagnostic, ...]:
        restarting = self._restart_task
        if (
            restarting is not None
            and not restarting.done()
            and asyncio.current_task() is not restarting
        ):
            restarting.cancel()
        if self._shutdown_task is None:
            self._state = AgentState.STOPPING
            if self._runtime is not None:
                self._runtime.stop_accepting()
            if self._start_task is not None and not self._start_task.done():
                self._start_task.cancel()
            self._shutdown_task = asyncio.create_task(
                self._shutdown(), name="tinysoul-shutdown"
            )
        task = self._shutdown_task
        operation = JoinedOperations()
        diagnostics = await operation.run_async(lambda: task)
        if asyncio.current_task() is not restarting and self._completion is not None:
            self._completion.cancel()
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
            if self._runtime is not None:
                diagnostics += await self._runtime.generation_handle.snapshot().generation.sources.pause()
            if self._worker is not None:
                self._worker.cancel()
                try:
                    await self._worker
                except asyncio.CancelledError:
                    pass
                except Exception as exc:
                    diagnostics += (
                        CleanupDiagnostic("agent.dispatch", type(exc).__name__),
                    )
            if self._runtime is not None:
                await self._runtime.agent_runner.close_requests()
                diagnostics += await self._runtime.close()
        finally:
            self._worker = None
            self._runtime = None
            self._state = AgentState.STOPPED
        return diagnostics

    async def restart(self) -> tuple[CleanupDiagnostic, ...]:
        if self._restart_task is None or self._restart_task.done():
            if self._shutdown_task is not None and self._shutdown_task.done():
                self._shutdown_task = None
            self._state = AgentState.STOPPING
            if self._runtime is not None:
                self._runtime.stop_accepting()
            self._restart_task = asyncio.create_task(
                self._restart(), name="tinysoul-restart"
            )
        task = self._restart_task
        operation = JoinedOperations()
        diagnostics = await operation.run_async(lambda: task)
        operation.check_cancelled()
        return diagnostics

    async def _restart(self) -> tuple[CleanupDiagnostic, ...]:
        diagnostics = await self.shutdown()
        await self.start()
        return diagnostics

    def _running_runtime(self) -> AgentRuntime:
        if self._state is not AgentState.RUNNING or self._runtime is None:
            raise AgentClosedError("Agent is not accepting work")
        return self._runtime

    async def _serve(self, runtime: AgentRuntime) -> AgentRunResult:
        try:
            return await runtime.run()
        finally:
            runtime.stop_accepting()
            await runtime.agent_runner.close_requests()
            runtime.observations.subscriptions.close()

    def _stopped(self, task: asyncio.Task[AgentRunResult]) -> None:
        if task is not self._worker or self._state is AgentState.STOPPING:
            return
        self._state = (
            AgentState.FAULTED
            if task.cancelled() or task.exception()
            else AgentState.STOPPED
        )
        completion = self._completion
        if completion is None or completion.done():
            return
        if task.cancelled():
            completion.cancel()
        elif (error := task.exception()) is not None:
            completion.set_exception(error)
            completion.exception()  # Status-only clients need not install a waiter.
        else:
            completion.set_result(task.result())
