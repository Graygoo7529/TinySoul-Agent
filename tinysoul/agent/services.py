"""Scoped SDK services and immutable projections of the active generation."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from tinysoul.infra.concurrency import JoinedOperations
from tinysoul.infra.json import JsonObject, JsonValue
from tinysoul.infra.paging import PageOptions
from tinysoul.infra.references import (
    ReferenceError,
    ResourceLocator,
    append_locator_fragment,
)
from tinysoul.infra.services import ServiceScope
from tinysoul.infra.time import CalendarDay
from tinysoul.kernel.context import ContextEngine
from tinysoul.kernel.context.builtin.trace import parse_trace_reference
from tinysoul.kernel.jobs import JobSnapshot
from tinysoul.kernel.jobs.failures import JobError, JobRequestError
from tinysoul.kernel.loop.turn import TurnOutcome
from tinysoul.kernel.registration import ServiceLifetime, ServiceRegistry
from tinysoul.plugins.capabilities.expand.engine import ExpandEngine
from tinysoul.plugins.capabilities.subagent.engine import SubagentEngine
from tinysoul.plugins.home.engine import AgentHomeEngine
from tinysoul.plugins.home.links import parse_home_link
from tinysoul.plugins.memory import MemoryEngine
from tinysoul.plugins.memory.links import MemoryLink
from tinysoul.plugins.reflection.errors import ReflectionError
from tinysoul.plugins.reflection.failures import ReflectionFailureKind
from tinysoul.plugins.session import SessionEngine
from tinysoul.plugins.session.errors import (
    SessionInspectFailureReason,
    SessionInspectRequestError,
)
from tinysoul.plugins.session.views import SessionView
from tinysoul.plugins.session.views.interaction import project_current_interactions
from tinysoul.plugins.workspace.engine import WorkspaceArchiveView, WorkspaceEngine
from tinysoul.plugins.workspace.inspection.models import WorkspaceBlobRead
from tinysoul.plugins.workspace.links import WorkspaceLink
from tinysoul.runtime import RuntimeException, RuntimeGenerationError, RuntimeHandle

from .dispatch.scheduler import RootScheduler
from .errors import (
    AgentClosedError,
    AgentContractError,
    AgentServiceStaleError,
    AgentServiceUnavailableError,
    AgentTurnUnavailableError,
)
from .handles import TurnSnapshot
from .lifecycle.generation import AgentGeneration
from .requests import UserTurnRequest


class AgentRuntimeServices:
    """Bind each acquired service to one generation and, when applicable, day."""

    def __init__(
        self,
        handle: RuntimeHandle[AgentGeneration],
        scheduler: RootScheduler,
        accepting: Callable[[], bool],
    ) -> None:
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
            generation_scope = self._scope(snapshot.generation_id)
            day_scope = self._scope(snapshot.generation_id, day=day, day_bound=True)
            plugin_services = tuple(
                export.bind(
                    day_scope
                    if export.lifetime is ServiceLifetime.DAY
                    else generation_scope
                )
                for export in snapshot.generation.sdk_exports
            )
            self._services = ServiceRegistry(plugin_services)
            self._key = key
        assert self._services is not None
        return self._services

    def _require_open(self) -> None:
        if not self._accepting() or self._handle.closed:
            raise AgentClosedError("Agent services are closed")

    def _scope(
        self,
        generation_id: str,
        *,
        day: CalendarDay | None = None,
        day_bound: bool = False,
    ) -> ServiceScope:
        @asynccontextmanager
        async def lease() -> AsyncIterator[None]:
            self._require_open()
            try:
                async with self._handle.read() as generation:
                    self._require_open()
                    if self._handle.generation_id != generation_id:
                        raise AgentServiceStaleError(
                            "Service generation has changed; acquire it again"
                        )
                    if not day_bound:
                        yield
                        return
                    if (
                        self._scheduler.active_turn is None
                        and generation.day.current_day() != generation.day.active_day
                    ):
                        transition = await generation.day.preflight(
                            scope=self._scheduler.scope
                        )
                        operations = JoinedOperations()
                        await operations.run(
                            lambda: generation.reflection.refresh_availability(
                                transition, scope=self._scheduler.scope
                            )
                        )
                        operations.check_cancelled()
                    async with generation.day.active_day_lease() as current:
                        if current != day:
                            raise AgentServiceStaleError(
                                "Service CalendarDay has changed; acquire it again"
                            )
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
                    module="reflection",
                    kind=ReflectionFailureKind.INVARIANT_VIOLATION.value,
                ) from exc

        return ServiceScope(lease)

    def runtime_status(self, *, credentials: bool = False) -> JsonObject:
        self._require_open()
        snapshot = self._handle.snapshot()
        result: JsonObject = {
            "generation_id": snapshot.generation_id,
            "activity": snapshot.activity.value,
            "activation": snapshot.activation.value,
            "active_day": str(snapshot.generation.day.active_day or ""),
            "active_turn_id": self._scheduler.active_turn.turn_id
            if self._scheduler.active_turn is not None
            else None,
            "queued_turn_ids": list(self._scheduler.queued_turn_ids),
            "sources": [
                {
                    "source": item.source,
                    "state": item.state.value,
                    "topics": list(item.topics),
                    "error_type": item.error_type,
                }
                for item in snapshot.generation.sources.statuses
            ],
        }
        if credentials:
            result["llm"] = {
                "providers": [
                    {
                        "id": item.provider_id,
                        "credential_state": item.state.value,
                        "api_key_envs": list(item.api_key_envs),
                    }
                    for item in snapshot.generation.llm_provider_credentials
                ]
            }
        return result

    def turn_snapshot(self, turn_id: str) -> TurnSnapshot | None:
        """Project the retained handle and current Job owner in one loop turn."""
        self._require_open()
        handle = self._scheduler.turn_handle(turn_id)
        return handle.snapshot(jobs=self._turn_jobs(turn_id)) if handle else None

    def _context_for(self, generation: AgentGeneration, turn_id: str) -> ContextEngine:
        for profile in generation.profiles:
            if profile.context.active_turn_id == turn_id:
                return profile.context
        raise AgentServiceUnavailableError(module="context", kind="context.unavailable")

    async def context_overview(self, turn_id: str) -> JsonObject:
        self._require_open()
        async with self._handle.read() as generation:
            return {
                "generation_id": self._handle.generation_id,
                "captured_at": datetime.now(timezone.utc).isoformat(),
                **self._context_for(generation, turn_id).installed_overview(),
            }

    async def context_segment(
        self, turn_id: str, segment_id: str, page: PageOptions = PageOptions()
    ) -> JsonObject:
        self._require_open()
        async with self._handle.read() as generation:
            return self._context_for(generation, turn_id).installed_segment(
                segment_id, page
            )

    async def context_inspect(
        self,
        turn_id: str,
        ref: str,
        *,
        query: str | None = None,
        continuation: str | None = None,
    ) -> JsonObject:
        self._require_open()
        async with self._handle.read() as generation:
            context = self._context_for(generation, turn_id)
            result = await context.inspect(ref, query=query, continuation=continuation)
            self._context_for(generation, turn_id)
            return result

    async def days(
        self, *, before: CalendarDay | None = None, limit: int = 30
    ) -> JsonObject:
        self._require_open()
        PageOptions(limit=limit)
        async with self._handle.read() as generation:
            operations = JoinedOperations()
            days = await operations.run(
                lambda: generation.day.archived_days(before=before, limit=limit)
            )
            current = generation.day.active_day
            if current is not None and (before is None or current < before):
                days = tuple(sorted({current, *days}, reverse=True))
            operations.check_cancelled()
            selected = days[:limit]
            return {
                "items": [
                    {"day": str(day), "active": day == current} for day in selected
                ],
                "next_before": str(selected[-1]) if len(selected) == limit else None,
            }

    async def _session_read(
        self, read: Callable[[SessionView], JsonObject], day: CalendarDay | None
    ) -> JsonObject:
        self._require_open()
        async with self._handle.read() as generation:
            async with generation.day.active_day_lease() as current:
                selected = day or current
                owner = generation.plugin_services.get(SessionEngine)

                def project() -> JsonObject:
                    if selected == current:
                        view = owner.read_view(selected)
                    else:
                        archive = generation.day.archive_for(selected)
                        if archive is None:
                            raise AgentTurnUnavailableError(
                                "Requested day was not found"
                            )
                        view = owner.archive_view(selected, root=archive.session_root)
                    return read(view)

                operations = JoinedOperations()
                result = await operations.run(project)
                operations.check_cancelled()
                return result

    async def session_turns(
        self, day: CalendarDay | None = None, page: PageOptions = PageOptions()
    ) -> JsonObject:
        return await self._session_read(lambda view: view.turns(page), day)

    async def memory_active(
        self, day: CalendarDay | None = None, page: PageOptions = PageOptions()
    ) -> JsonObject:
        self._require_open()
        async with self._handle.read() as generation:
            async with generation.day.active_day_lease() as current:
                selected = day or current
                owner = generation.plugin_services.get(MemoryEngine)

                def read() -> JsonObject:
                    archive = (
                        generation.day.archive_for(selected)
                        if selected != current
                        else None
                    )
                    if selected != current and archive is None:
                        raise AgentTurnUnavailableError("Requested day was not found")
                    return owner.browse_active(
                        selected,
                        archive_root=archive.session_root if archive else None,
                        page=page,
                    )

                operations = JoinedOperations()
                result = await operations.run(read)
                operations.check_cancelled()
                return result

    @asynccontextmanager
    async def _workspace_view(
        self, day: CalendarDay | None
    ) -> AsyncIterator[WorkspaceEngine | WorkspaceArchiveView]:
        self._require_open()
        async with self._handle.read() as generation:
            async with generation.day.active_day_lease() as current:
                if day is None or day == current:
                    yield generation.workspace
                else:

                    def archived() -> WorkspaceArchiveView:
                        archive = generation.day.archive_for(day)
                        if archive is None:
                            raise AgentTurnUnavailableError(
                                "Requested day was not found"
                            )
                        return generation.workspace.archive_view(
                            day, root=archive.workspace_root
                        )

                    operations = JoinedOperations()
                    view = await operations.run(archived)
                    operations.check_cancelled()
                    yield view

    async def workspace_manifest(self, day: CalendarDay | None = None) -> JsonObject:
        async with self._workspace_view(day) as view:
            operations = JoinedOperations()
            result = await operations.run(
                lambda: (
                    view.load_manifest()
                    if isinstance(view, WorkspaceEngine)
                    else view.manifest
                ).to_json()
            )
            operations.check_cancelled()
            return result

    async def workspace_text(
        self,
        link: str,
        day: CalendarDay | None = None,
        *,
        page: PageOptions = PageOptions(),
        full: bool = False,
    ) -> JsonObject:
        async with self._workspace_view(day) as view:
            operations = JoinedOperations()
            result = await operations.run(
                lambda: view.browse_text(link, page=page, full=full)
            )
            operations.check_cancelled()
            return result

    async def workspace_trash(
        self, day: CalendarDay | None = None, page: PageOptions = PageOptions()
    ) -> JsonObject:
        async with self._workspace_view(day) as view:
            actual_day = (
                str(view.active_day) if isinstance(view, WorkspaceEngine) else view.day
            )
            operations = JoinedOperations()
            items = await operations.run(view.trash_items)
            operations.check_cancelled()
            return page.render(
                tuple({"ref": item.ref, **item.to_json()} for item in items),
                owner="workspace",
                ref=f"trash:{actual_day}",
                base={"day": actual_day},
            )

    @asynccontextmanager
    async def workspace_blob(
        self, link: str, day: CalendarDay | None = None
    ) -> AsyncIterator[WorkspaceBlobRead]:
        async with self._workspace_view(day) as view:
            operations = JoinedOperations()
            blob = await operations.run(lambda: view.open_blob(link))
            try:
                operations.check_cancelled()
                yield blob
            finally:
                blob.stream.close()

    async def session_interactions(
        self, turn_id: str, day: CalendarDay, page: PageOptions = PageOptions()
    ) -> JsonObject:
        return await self._session_read(
            lambda view: view.interactions(turn_id, page), day
        )

    async def session_inspect(
        self,
        day: CalendarDay | None = None,
        *,
        ref: str | None = None,
        query: str | None = None,
        continuation: str | None = None,
    ) -> JsonObject:
        return await self._session_read(
            lambda view: view.inspect(ref, query=query, continuation=continuation), day
        )

    async def turn_interactions(
        self, turn_id: str, page: PageOptions = PageOptions()
    ) -> JsonObject:
        self._require_open()
        handle = self._scheduler.turn_handle(turn_id)
        if handle is None:
            raise AgentTurnUnavailableError("Turn was not found")
        result = handle.result
        if result is not None:
            outcome = result.outcome
            if (
                isinstance(outcome, TurnOutcome)
                and outcome.context_completion is not None
            ):
                # Only the committed Session record supplies completed user history.
                try:
                    value = await self.session_interactions(
                        turn_id, outcome.active_day, page
                    )
                except AgentTurnUnavailableError:
                    value = {"items": [], "history_unavailable": True}
                except SessionInspectRequestError as exc:
                    if exc.reason is not SessionInspectFailureReason.UNKNOWN_REF:
                        raise
                    value = {"items": [], "history_unavailable": True}
            else:
                value = {"items": []}
            return {
                **value,
                "turn_id": turn_id,
                "generation_id": handle.generation_id,
                "day": str(handle.active_day) if handle.active_day else None,
                "state": handle.state.value,
                "pending_items": [],
                "result": result.to_json(),
            }
        async with self._handle.read() as generation:
            pending: tuple[JsonValue, ...] = tuple(
                {"kind": "pending", **item.to_json()}
                for item in handle.inbox.pending_items()
            )
            context = next(
                (
                    profile.context
                    for profile in generation.profiles
                    if profile.context.active_turn_id == turn_id
                ),
                None,
            )
            base: JsonObject = {
                "turn_id": turn_id,
                "generation_id": handle.generation_id,
                "day": str(handle.active_day) if handle.active_day else None,
                "state": handle.state.value,
            }
            if context is None:
                if isinstance(handle.request, UserTurnRequest):
                    base["queued_request"] = {
                        "text": handle.request.text[:240],
                        "truncated": len(handle.request.text) > 240,
                        "delivery": "queued",
                    }
                values = ()
            else:
                values = tuple(
                    item.to_json()
                    for item in project_current_interactions(context.current_facts())
                )
            result_page = page.render(
                (*values, *pending), owner="turn", ref=turn_id, base=base
            )
            visible = result_page.get("items", [])
            if isinstance(visible, list):
                result_page["pending_items"] = [
                    item
                    for item in visible
                    if isinstance(item, dict)
                    and "sequence" in item
                    and "record_id" in item
                ]
                result_page["items"] = [
                    item
                    for item in visible
                    if not (
                        isinstance(item, dict)
                        and "sequence" in item
                        and "record_id" in item
                    )
                ]
            return result_page

    def turn_jobs(self, turn_id: str) -> tuple[JobSnapshot, ...] | None:
        self._require_open()
        if self._scheduler.turn_handle(turn_id) is None:
            return None
        return self._turn_jobs(turn_id)

    def _turn_jobs(self, turn_id: str) -> tuple[JobSnapshot, ...]:
        return self._handle.snapshot().generation.jobs.snapshots(turn_id)

    async def stop_job(self, turn_id: str, job_id: str) -> JobSnapshot:
        self._require_open()
        if self._scheduler.turn_handle(turn_id) is None:
            raise AgentTurnUnavailableError("Turn is not available")
        try:
            async with self._handle.read() as generation:
                self._require_open()
                operations = JoinedOperations()
                result = await operations.run_async(
                    lambda: generation.jobs.stop(turn_id, job_id, operations=operations)
                )
                operations.check_cancelled()
                return result
        except JobRequestError as exc:
            raise AgentTurnUnavailableError(
                "Job is not available in this Turn"
            ) from exc
        except JobError as exc:
            raise AgentServiceUnavailableError(
                module="jobs", kind=exc.kind.value
            ) from exc

    async def action_catalog(self, *, scenario: str = "user") -> JsonObject:
        self._require_open()
        async with self._handle.read() as generation:
            self._require_open()
            for profile in generation.profiles:
                if profile.kind.value == scenario:
                    return profile.action.catalog_json()
            raise AgentContractError("Unknown Action scenario")

    async def job_detail(self, turn_id: str, job_id: str) -> JsonObject:
        self._require_open()
        async with self._handle.read() as generation:
            operations = JoinedOperations()
            result = await generation.jobs.describe(
                turn_id, job_id, operations=operations
            )
            operations.check_cancelled()
            return result

    async def job_output(
        self, turn_id: str, job_id: str, page: PageOptions = PageOptions()
    ) -> JsonObject:
        self._require_open()
        async with self._handle.read() as generation:
            operations = JoinedOperations()
            result = await generation.jobs.output(
                turn_id,
                job_id,
                continuation=page.continuation,
                max_chars=page.max_chars,
                operations=operations,
            )
            operations.check_cancelled()
            day = str(generation.day.active_day)
            locators = result.get("result_locators", [])
            if isinstance(locators, list):
                result["result_locators"] = [
                    {**item, "day": day} for item in locators if isinstance(item, dict)
                ]
            return result

    async def subagent_status(self) -> JsonObject:
        self._require_open()
        async with self._handle.read() as generation:
            value = generation.plugin_services.get(SubagentEngine).status_view()
            connections = value.get("connections", [])
            if isinstance(connections, list):
                for item in connections:
                    if isinstance(item, dict) and isinstance(item.get("cwd_link"), str):
                        item["cwd_locator"] = {
                            "link": item["cwd_link"],
                            "day": str(generation.day.active_day),
                        }
            return {
                "generation_id": self._handle.generation_id,
                "day": str(generation.day.active_day),
                **value,
            }

    async def resolve_resource(
        self,
        reference: str,
        *,
        origin_link: str | None = None,
        day: CalendarDay | None = None,
        turn_id: str | None = None,
        view: str = "effective",
    ) -> JsonObject:
        self._require_open()
        if turn_id is not None:
            handle = self._scheduler.turn_handle(turn_id)
            if handle is not None and handle.active_day is not None:
                if day is not None and day != handle.active_day:
                    raise ReferenceError("Resource origin day does not match its Turn")
                day = handle.active_day
        if ":" not in reference.partition("#")[0]:
            if not origin_link:
                raise ReferenceError("Relative resource requires an origin Link")
            async with self._handle.read() as generation:
                if origin_link.startswith("home:"):
                    reference = generation.plugin_services.get(
                        AgentHomeEngine
                    ).resolve_relative(reference, origin_link)
                elif origin_link.startswith("memory:"):
                    reference = generation.plugin_services.get(
                        MemoryEngine
                    ).resolve_relative(reference, origin_link)
                elif origin_link.startswith("workspace:"):
                    reference = generation.workspace.resolve_relative(
                        reference, origin_link
                    )
                else:
                    raise ReferenceError("Origin has no relative reference owner")
        resource, marker, fragment = reference.partition("#")
        context: ContextEngine | None = None
        bindings: JsonObject = {}
        if turn_id:
            async with self._handle.read() as generation:
                context = next(
                    (
                        p.context
                        for p in generation.profiles
                        if p.context.active_turn_id == turn_id
                    ),
                    None,
                )
                if context is not None:
                    bindings = context.resolved_references()
        if resource in {"memory:current", "memory:latest", "memory:target"}:
            if context is None and day and turn_id:
                bindings = await self._session_read(
                    lambda session: session.resolved_references(turn_id), day
                )
            locator = bindings.get(resource)
            if isinstance(locator, dict):
                return {
                    "kind": "memory",
                    "locator": append_locator_fragment(locator, fragment),
                    "capabilities": ["read"],
                    "resolved_from": reference,
                }
            # An explicit day binds current/target, but never reconstructs latest.
            if day and not turn_id and resource in {"memory:current", "memory:target"}:
                return {
                    "kind": "memory",
                    "locator": ResourceLocator(link=reference, day=str(day)).to_json(),
                    "resolved_from": reference,
                    "capabilities": ["read"],
                }
            raise AgentServiceUnavailableError(
                module="resource", kind="resource.unresolved_origin"
            )
        if resource.startswith("home:"):
            parse_home_link(resource)
            locator = ResourceLocator(link=reference, view=view)
            kind = "home"
        elif resource.startswith("memory:"):
            link = MemoryLink.from_resource(resource)
            locator = ResourceLocator(
                link=str(link) + ("#" + fragment if marker else "")
            )
            kind = "memory"
        elif resource.startswith("workspace:"):
            WorkspaceLink.parse(resource)
            if turn_id is not None and day is None:
                raise AgentServiceUnavailableError(
                    module="resource", kind="resource.unresolved_origin"
                )
            current = self._handle.snapshot().generation.day.active_day
            locator = ResourceLocator(link=reference, day=str(day or current))
            kind = "workspace"
        elif resource.startswith("session:"):
            if day is None:
                raise AgentServiceUnavailableError(
                    module="resource", kind="resource.unresolved_origin"
                )
            locator = ResourceLocator(ref=reference, day=str(day))
            kind = "session"
        elif resource.startswith(("turn:trace@", "turn:trace/")):
            try:
                identity = parse_trace_reference(reference)
            except Exception as exc:
                raise ReferenceError("Invalid trace resource reference") from exc
            if turn_id is not None and identity != turn_id:
                raise ReferenceError("Trace origin does not match its Turn")
            if context is not None and context.active_turn_id == identity:
                try:
                    context.resolve_reference(reference)
                except Exception as exc:
                    raise ReferenceError("Trace resource reference is unavailable") from exc
            locator = ResourceLocator(
                ref=reference, turn_id=identity, day=str(day) if day else ""
            )
            kind = "trace"
        else:
            raise ReferenceError("Resource has no supported owner")
        return {"kind": kind, "locator": locator.to_json(), "capabilities": ["read"]}

    async def expand_servers(self, page: PageOptions = PageOptions()) -> JsonObject:
        self._require_open()
        async with self._handle.read() as generation:
            return generation.plugin_services.get(ExpandEngine).servers_view(page)

    async def expand_tools(
        self,
        server_id: str,
        *,
        tool_name: str | None = None,
        page: PageOptions = PageOptions(),
    ) -> JsonObject:
        self._require_open()
        async with self._handle.read() as generation:
            return generation.plugin_services.get(ExpandEngine).tools_view(
                server_id, tool_name=tool_name, page=page
            )

    async def expand_refresh(self, server_id: str) -> JsonObject:
        self._require_open()
        async with self._handle.read() as generation:
            return await generation.plugin_services.get(ExpandEngine).refresh(server_id)

    async def reflection_status(
        self, *, before: CalendarDay | None = None
    ) -> JsonObject:
        self._require_open()
        async with self._handle.read() as generation:
            self._require_open()
            operations = JoinedOperations()
            try:
                result = await operations.run(
                    lambda: generation.reflection.availability(before=before)
                )
            except ReflectionError as exc:
                raise AgentServiceUnavailableError(
                    module="reflection",
                    kind=ReflectionFailureKind.INVARIANT_VIOLATION.value,
                ) from exc
            operations.check_cancelled()
            return result.to_json()
