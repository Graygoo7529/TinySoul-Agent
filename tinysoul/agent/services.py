"""Scoped SDK services and immutable projections of the active generation."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

from tinysoul.infra.concurrency import JoinedOperations
from tinysoul.infra.json import JsonObject
from tinysoul.infra.services import ServiceScope
from tinysoul.infra.time import CalendarDay
from tinysoul.kernel.registration import Service, ServiceRegistry
from tinysoul.plugins.home.services import HomeService
from tinysoul.plugins.memory.services import MemoryService
from tinysoul.plugins.session.services import SessionService
from tinysoul.plugins.workspace.services import WorkspaceService
from tinysoul.plugins.reflection.errors import ReflectionError
from tinysoul.plugins.reflection.failures import ReflectionFailureKind
from tinysoul.runtime import RuntimeHandle, RuntimeGenerationError, RuntimeException

from .errors import AgentClosedError, AgentServiceStaleError, AgentServiceUnavailableError
from .generation import AgentRuntimeGeneration
from .scheduler import RootScheduler


class AgentRuntimeServices:
    """Bind each acquired service to one generation and, when applicable, day."""

    def __init__(self, handle: RuntimeHandle[AgentRuntimeGeneration], scheduler: RootScheduler,
                 accepting: Callable[[], bool]) -> None:
        self._handle = handle
        self._scheduler = scheduler
        self._accepting = accepting
        self._key: tuple[str, CalendarDay | None] | None = None
        self._services: ServiceRegistry | None = None

    @property
    def registry(self) -> ServiceRegistry:
        self._require_open()
        snapshot = self._handle.snapshot()
        day = snapshot.generation.day.active_day
        key = snapshot.generation_id, day
        if self._key != key:
            profile = snapshot.generation.user_turn.profile.services
            generation_scope = self._scope(snapshot.generation_id)
            day_scope = self._scope(snapshot.generation_id, day=day, day_bound=True)
            self._services = ServiceRegistry((
                Service(HomeService, profile.get(HomeService)._bind(generation_scope)),
                Service(MemoryService, profile.get(MemoryService)._bind(day_scope)),
                Service(SessionService, profile.get(SessionService)._bind(day_scope)),
                Service(WorkspaceService, profile.get(WorkspaceService)._bind(day_scope)),
            ))
            self._key = key
        assert self._services is not None
        return self._services

    def _require_open(self) -> None:
        if not self._accepting() or self._handle.closed:
            raise AgentClosedError("Agent services are closed")

    def _scope(self, generation_id: str, *, day: CalendarDay | None = None,
               day_bound: bool = False) -> ServiceScope:
        @asynccontextmanager
        async def lease() -> AsyncIterator[None]:
            self._require_open()
            try:
                async with self._handle.read() as generation:
                    self._require_open()
                    if self._handle.generation_id != generation_id:
                        raise AgentServiceStaleError("Service generation has changed; acquire it again")
                    if not day_bound:
                        yield
                        return
                    if self._scheduler.active_turn is None and generation.day.current_day() != generation.day.active_day:
                        transition = await generation.day.preflight(scope=self._scheduler.scope)
                        operations = JoinedOperations()
                        await operations.run(lambda: generation.maintenance.refresh_availability(transition, scope=self._scheduler.scope))
                        operations.check_cancelled()
                    async with generation.day.active_day_lease() as current:
                        if current != day:
                            raise AgentServiceStaleError("Service CalendarDay has changed; acquire it again")
                        yield
            except RuntimeGenerationError as exc:
                raise AgentClosedError("Agent services are closed") from exc
            except RuntimeException as exc:
                module, kind = exc.payload.get("module"), exc.payload.get("kind")
                raise AgentServiceUnavailableError(
                    module=module if isinstance(module, str) else "agent",
                    kind=kind if isinstance(kind, str) else "agent.service_unavailable",
                ) from exc
            except ReflectionError as exc:
                raise AgentServiceUnavailableError(
                    module="maintenance", kind=ReflectionFailureKind.INVARIANT_VIOLATION.value,
                ) from exc
        return ServiceScope(lease)

    def runtime_status(self, *, credentials: bool = False) -> JsonObject:
        self._require_open()
        snapshot = self._handle.snapshot()
        result: JsonObject = {
            "generation_id": snapshot.generation_id, "activity": snapshot.activity.value,
            "activation": snapshot.activation.value,
            "active_day": str(snapshot.generation.day.active_day or ""),
        }
        if credentials:
            result["llm"] = {"providers": [
                {"id": item.provider_id, "credential_state": item.state.value, "api_key_envs": list(item.api_key_envs)}
                for item in snapshot.generation.llm_provider_credentials
            ]}
        return result

    async def action_catalog(self) -> JsonObject:
        self._require_open()
        async with self._handle.read() as generation:
            self._require_open()
            return generation.user_turn.action_catalog()

    async def reflection_status(self) -> JsonObject:
        self._require_open()
        async with self._handle.read() as generation:
            self._require_open()
            operations = JoinedOperations()
            try:
                result = await operations.run(generation.maintenance.availability)
            except ReflectionError as exc:
                raise AgentServiceUnavailableError(
                    module="maintenance", kind=ReflectionFailureKind.INVARIANT_VIOLATION.value,
                ) from exc
            operations.check_cancelled()
            return result.to_json()
