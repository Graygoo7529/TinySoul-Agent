"""Workspace integration with the Context projection protocol."""

from __future__ import annotations

from dataclasses import dataclass, field
from collections.abc import Callable
from typing import TYPE_CHECKING, Protocol

from tinysoul.kernel.context.segments import (
    ReadOnlySegmentRegistration,
    SegmentCapability,
    SegmentDescriptor,
    SegmentRegistration,
    SegmentShape,
    SegmentSlot,
    TurnInfo,
)
from tinysoul.kernel.context.errors import (
    ContextInspectFailureReason,
    ContextInspectRequestError,
)
from tinysoul.llm.protocol.messages import Message, UserMessage
from tinysoul.infra.json import JsonObject, JsonValue, to_json_object
from tinysoul.infra.concurrency import JoinedOperations
from tinysoul.runtime import RunScope, RuntimeException, Signal

from .engine import WorkspaceArchiveView, WorkspaceEngine
from .errors import WorkspaceContractError, WorkspaceError
from .runtime_bridge import RuntimeWorkspaceBridge
from .failures import WorkspaceFailureKind
from .storage.manifest import WorkspaceManifest

if TYPE_CHECKING:
    from tinysoul.kernel.loop.lifecycle.preparation import TurnPreparationRequest


SIGNAL_WORKSPACE_SYNC = "context.workspace.sync"


@dataclass(frozen=True)
class WorkspaceRefresh:
    """Read the committed owner projection at the Context boundary."""


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
    """A complete current Workspace manifest projection."""

    resources: tuple[WorkspaceResource, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        resources = tuple(self.resources)
        if any(not isinstance(resource, WorkspaceResource) for resource in resources):
            raise WorkspaceContractError(
                "Workspace projection requires typed resources"
            )
        object.__setattr__(self, "resources", resources)
        links = tuple(resource.link for resource in resources)
        if len(set(links)) != len(links):
            raise WorkspaceContractError(
                "WorkspaceSnapshot.resources must contain unique links"
            )


def workspace_refresh_signal(
    *,
    call_id: str,
    scope: RunScope,
    source: str,
) -> Signal:
    return Signal(
        name=SIGNAL_WORKSPACE_SYNC,
        source=source,
        scope=scope,
        payload={"call_id": call_id},
    )


def parse_workspace_refresh(signal: Signal) -> WorkspaceRefresh:
    return WorkspaceRefresh()


class WorkspaceSegment:
    """Turn-local manifest projection, separate from the kernel's plan state."""

    def __init__(self, workspace: WorkspaceEngine) -> None:
        self._workspace = workspace
        self._snapshot: WorkspaceSnapshot | None = None

    async def prepare(
        self, updates: tuple[WorkspaceRefresh, ...]
    ) -> WorkspaceSnapshot | None:
        if not updates:
            return self._snapshot
        operations = JoinedOperations()
        try:
            manifest = await operations.run(self._workspace.snapshot)
            operations.check_cancelled()
            return workspace_snapshot(manifest)
        except WorkspaceError as exc:
            raise RuntimeWorkspaceBridge().from_workspace_error(exc) from exc

    def install(self, prepared: WorkspaceSnapshot | None) -> None:
        self._snapshot = prepared

    def seal(self) -> JsonObject:
        return {
            "resources": self._resources(),
        }

    def render(self) -> tuple[Message, ...]:
        return (
            UserMessage.from_json({"resources": self._resources()}, label="workspace"),
        )

    def _resources(self) -> list[JsonValue]:
        return [
            {"link": item.link, "summary": item.summary}
            for item in (self._snapshot.resources if self._snapshot is not None else ())
        ]

    async def close(self) -> None:
        self._snapshot = None


class WorkspaceSegmentProvider:
    def __init__(self, workspace: WorkspaceEngine) -> None:
        self._workspace = workspace

    async def open(self, info: TurnInfo) -> WorkspaceSegment:
        return WorkspaceSegment(self._workspace)


def workspace_segment_registration(workspace: WorkspaceEngine) -> (
    SegmentRegistration[WorkspaceRefresh, WorkspaceSnapshot | None]
):
    return SegmentRegistration(
        descriptor=SegmentDescriptor("workspace", "workspace", SegmentSlot.WORKING, 20),
        provider=WorkspaceSegmentProvider(workspace),
        signal_name=SIGNAL_WORKSPACE_SYNC,
        update_type=WorkspaceRefresh,
        decode=parse_workspace_refresh,
    )


class ArchivedWorkspaceSegment:
    """A dated, read-only reference view, separate from the current workbench."""

    def __init__(self, view: WorkspaceArchiveView | None) -> None:
        self._view = view

    def render(self) -> tuple[Message, ...]:
        if self._view is None:
            return ()
        return (UserMessage.from_json(self._page(0), label="workspace_archive"),)

    def seal(self) -> JsonObject:
        return {"source_day": self._view.day if self._view is not None else None}

    def _page(self, offset: int) -> JsonObject:
        if self._view is None:
            return {"resources": []}
        resources = self._view.manifest.resources
        selected = resources[offset : offset + 32]
        return {
            "ref": f"workspace_archive:{self._view.day}",
            "source_day": self._view.day,
            "read_only": True,
            "resources": [
                {
                    "ref": f"workspace_archive:{self._view.day}/{item.relative_path}",
                    "summary": item.context_summary[:500],
                }
                for item in selected
            ],
            "continuation": (
                str(offset + len(selected))
                if offset + len(selected) < len(resources)
                else None
            ),
        }

    async def inspect(self, ref: str, *, query: str | None = None, continuation: str | None = None) -> JsonObject:
        if query is not None:
            raise ContextInspectRequestError(ContextInspectFailureReason.QUERY_UNSUPPORTED,
                                             "Archived Workspace supports navigation only")
        view = self._view
        if view is None:
            raise ContextInspectRequestError(
                ContextInspectFailureReason.UNKNOWN_REF,
                "No archived Workspace is bound",
            )
        root = f"workspace_archive:{view.day}"
        if ref == root:
            offset = 0
            if continuation is not None:
                if (
                    not continuation.isascii()
                    or not continuation.isdigit()
                    or len(continuation) > 9
                ):
                    raise ContextInspectRequestError(
                        ContextInspectFailureReason.UNKNOWN_REF,
                        "Invalid archive continuation",
                    )
                offset = int(continuation)
            return self._page(offset)
        record = next(
            (
                item
                for item in view.manifest.resources
                if ref == f"{root}/{item.relative_path}"
            ),
            None,
        )
        if record is None or continuation is not None:
            raise ContextInspectRequestError(
                ContextInspectFailureReason.UNKNOWN_REF,
                "Unknown archived Workspace reference",
            )
        try:
            operations = JoinedOperations()
            read = await operations.run(lambda: view.read_text(record.link))
            operations.check_cancelled()
        except WorkspaceContractError as exc:
            raise ContextInspectRequestError(
                ContextInspectFailureReason.UNKNOWN_REF,
                "Archived resource cannot be read as text",
            ) from exc
        except WorkspaceError as exc:
            raise RuntimeWorkspaceBridge().from_workspace_error(exc) from exc
        return {
            "ref": ref,
            "source_day": view.day,
            "text": read.text,
            "truncated": read.truncated,
        }

    async def close(self) -> None:
        self._view = None


class ArchivedWorkspaceSegmentProvider:
    def __init__(self, source: Callable[[], WorkspaceArchiveView | None]) -> None:
        self._source = source

    async def open(self, info: TurnInfo) -> ArchivedWorkspaceSegment:
        return ArchivedWorkspaceSegment(self._source())


def archived_workspace_segment_registration(
    source: Callable[[], WorkspaceArchiveView | None],
) -> ReadOnlySegmentRegistration:
    return ReadOnlySegmentRegistration(
        SegmentDescriptor(
            "workspace_archive",
            "workspace",
            SegmentSlot.BACKGROUND,
            60,
            ("workspace_archive:",),
            SegmentShape.STATE,
            frozenset({SegmentCapability.INSPECT}),
        ),
        ArchivedWorkspaceSegmentProvider(source),
    )


class WorkspaceRuntimeBridge(Protocol):
    """Runtime mapping surface needed by Turn preparation."""

    def from_workspace_error(self, error: Exception) -> RuntimeException: ...

    def from_failure(
        self,
        kind: WorkspaceFailureKind,
        *,
        message: str,
        payload: JsonObject | None = None,
    ) -> RuntimeException: ...


def workspace_snapshot(manifest: WorkspaceManifest) -> WorkspaceSnapshot:
    """Project a committed Workspace manifest into Context's read model."""

    return WorkspaceSnapshot(
        resources=tuple(
            WorkspaceResource(link=record.link, summary=record.context_summary)
            for record in manifest.resources
        ),
    )


@dataclass(frozen=True)
class WorkspaceTurnPreparationHandler:
    """Reconcile disk and publish its Manifest before a Turn starts work."""

    workspace: WorkspaceEngine
    runtime_bridge: WorkspaceRuntimeBridge

    async def prepare(self, request: "TurnPreparationRequest") -> tuple[Signal, ...]:
        try:
            self.workspace.require_day(request.active_day)
            operations = JoinedOperations()
            result = await operations.run(self.workspace.reconcile)
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
        await operations.finish(self.workspace.events.flush)
        operations.check_cancelled()
        return (
            workspace_refresh_signal(
                call_id=f"{request.turn_id}:workspace",
                scope=request.scope,
                source="workspace.turn_prepare",
            ),
        )
