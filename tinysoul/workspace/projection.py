"""Workspace integration with the Context projection protocol."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

from tinysoul.context.segments import SegmentDescriptor, SegmentRegistration, SegmentSlot, TurnInfo
from tinysoul.llm.messages import Message, UserMessage
from tinysoul.infra.json import JsonObject, JsonValue, to_json_object
from tinysoul.infra.concurrency import JoinedOperations
from tinysoul.runtime import RunScope, RuntimeException, Signal

from .engine import WorkspaceEngine
from .errors import WorkspaceContractError, WorkspaceError
from .runtime_bridge import RuntimeWorkspaceBridge
from .failures import WorkspaceFailureKind
from .manifest import WorkspaceManifest

if TYPE_CHECKING:
    from tinysoul.loop.preparation import TurnPreparationRequest



SIGNAL_WORKSPACE_SYNC = "context.workspace.sync"


@dataclass(frozen=True)
class WorkspaceResource:
    """A workspace resource handle with a short summary."""

    link: str
    summary: str

    def __post_init__(self) -> None:
        if not isinstance(self.link, str) or not self.link:
            raise WorkspaceContractError("WorkspaceResource.link must be non-empty")
        if not isinstance(self.summary, str) or not self.summary:
            raise WorkspaceContractError("WorkspaceResource.summary must be non-empty")


@dataclass(frozen=True)
class WorkspaceSnapshot:
    """A complete, versioned Workspace manifest projection."""

    revision: int
    resources: tuple[WorkspaceResource, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if (
            isinstance(self.revision, bool)
            or not isinstance(self.revision, int)
            or self.revision < 0
        ):
            raise WorkspaceContractError(
                "WorkspaceSnapshot.revision must be a non-negative integer"
            )
        resources = tuple(self.resources)
        if any(not isinstance(resource, WorkspaceResource) for resource in resources):
            raise WorkspaceContractError("Workspace projection requires typed resources")
        object.__setattr__(self, "resources", resources)
        links = tuple(resource.link for resource in resources)
        if len(set(links)) != len(links):
            raise WorkspaceContractError(
                "WorkspaceSnapshot.resources must contain unique links"
            )



def build_workspace_sync_signal(
    snapshot: WorkspaceSnapshot, *, call_id: str, scope: RunScope, source: str,
) -> Signal:
    return Signal(
        name=SIGNAL_WORKSPACE_SYNC, source=source, scope=scope,
        payload={
            "call_id": call_id,
            "revision": snapshot.revision,
            "resources": [
                {"link": item.link, "summary": item.summary} for item in snapshot.resources
            ],
        },
    )


def parse_workspace_sync_signal(signal: Signal) -> WorkspaceSnapshot:
    try:
        revision = signal.payload.get("revision")
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
            raise WorkspaceContractError("Workspace projection requires a non-negative revision")
        values = signal.payload.get("resources")
        if not isinstance(values, list):
            raise WorkspaceContractError("Workspace projection requires a resource list")
        resources: list[WorkspaceResource] = []
        for value in values:
            if not isinstance(value, dict):
                raise WorkspaceContractError("Workspace projection resource must be an object")
            link, summary = value.get("link"), value.get("summary")
            if not isinstance(link, str) or not isinstance(summary, str):
                raise WorkspaceContractError("Workspace projection resource requires text fields")
            resources.append(WorkspaceResource(link, summary))
        return WorkspaceSnapshot(revision, tuple(resources))
    except WorkspaceError as exc:
        raise RuntimeWorkspaceBridge().from_workspace_error(exc) from exc


class WorkspaceSegment:
    """Turn-local manifest projection, separate from the kernel's plan state."""

    def __init__(self) -> None:
        self._snapshot: WorkspaceSnapshot | None = None

    async def prepare(self, updates: tuple[WorkspaceSnapshot, ...]) -> WorkspaceSnapshot | None:
        candidate = self._snapshot
        for update in updates:
            if candidate is not None:
                if update.revision < candidate.revision:
                    continue
                if update.revision == candidate.revision and update != candidate:
                    exc = WorkspaceContractError("Workspace projection conflicts at the same revision")
                    raise RuntimeWorkspaceBridge().from_workspace_error(exc) from exc
            candidate = update
        return candidate

    def install(self, prepared: WorkspaceSnapshot | None) -> None:
        self._snapshot = prepared

    def seal(self) -> JsonObject:
        return {
            "revision": self._snapshot.revision if self._snapshot is not None else -1,
            "resources": self._resources(),
        }

    def render(self) -> tuple[Message, ...]:
        return (UserMessage.from_json({"resources": self._resources()}, label="workspace"),)

    def _resources(self) -> list[JsonValue]:
        return [
            {"link": item.link, "summary": item.summary}
            for item in (self._snapshot.resources if self._snapshot is not None else ())
        ]

    async def close(self) -> None:
        self._snapshot = None


class WorkspaceSegmentProvider:
    async def open(self, info: TurnInfo) -> WorkspaceSegment:
        return WorkspaceSegment()


def workspace_segment_registration() -> SegmentRegistration[WorkspaceSnapshot, WorkspaceSnapshot | None]:
    return SegmentRegistration(
        descriptor=SegmentDescriptor("workspace", "workspace", SegmentSlot.WORKING, 20),
        provider=WorkspaceSegmentProvider(),
        signal_name=SIGNAL_WORKSPACE_SYNC,
        update_type=WorkspaceSnapshot,
        decode=parse_workspace_sync_signal,
    )


class WorkspaceRuntimeBridge(Protocol):
    """Runtime mapping surface needed by Turn preparation."""

    def from_workspace_error(self, error: Exception) -> RuntimeException:
        ...

    def from_failure(
        self,
        kind: WorkspaceFailureKind,
        *,
        message: str,
        payload: JsonObject | None = None,
    ) -> RuntimeException:
        ...


def workspace_snapshot(manifest: WorkspaceManifest) -> WorkspaceSnapshot:
    """Project a committed Workspace manifest into Context's read model."""

    return WorkspaceSnapshot(
        revision=manifest.revision,
        resources=tuple(
            WorkspaceResource(link=record.link, summary=record.context_summary)
            for record in manifest.resources
        ),
    )


def workspace_snapshot_signal(
    manifest: WorkspaceManifest,
    *,
    call_id: str,
    scope: RunScope,
    source: str,
) -> Signal:
    return build_workspace_sync_signal(
        workspace_snapshot(manifest),
        call_id=call_id,
        scope=scope,
        source=source,
    )


@dataclass(frozen=True)
class WorkspaceTurnPreparationHandler:
    """Reconcile disk and publish its Manifest before a Turn starts work."""

    workspace: WorkspaceEngine
    runtime_bridge: WorkspaceRuntimeBridge

    async def prepare(self, request: "TurnPreparationRequest") -> tuple[Signal, ...]:
        try:
            self.workspace.require_day(request.business_day)
            operations = JoinedOperations()
            result = await operations.run(self.workspace.reconcile)
            operations.check_cancelled()
        except WorkspaceError as exc:
            raise self.runtime_bridge.from_workspace_error(exc) from exc
        if not result.complete:
            payload: JsonObject = to_json_object(
                {
                    "limit_reached": result.limit_reached,
                    "skipped_count": result.skipped_count,
                    "skip_counts": result.skip_counts(),
                }
            )
            raise self.runtime_bridge.from_failure(
                WorkspaceFailureKind.IO_FAILED,
                message="Workspace reconciliation was incomplete at Turn start.",
                payload=payload,
            )
        return (
            workspace_snapshot_signal(
                result.manifest,
                call_id=f"{request.turn_id}:workspace",
                scope=request.scope,
                source="workspace.turn_prepare",
            ),
        )
