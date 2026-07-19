"""Endpoint module assembly facade and business adapters."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from tinysoul.home import HomeMaintenanceChange, HomeMaintenanceDecision
from tinysoul.infra.json import JsonObject, to_json_object
from tinysoul.loop import BusinessDay, DailyLifecycleCoordinator, LoopControlKind
from tinysoul.loop.errors import LoopError
from tinysoul.runtime import (
    ObservationEmitter,
    ObservationLevel,
    RunScope,
    RuntimeGatewayError,
    RuntimeInputBlockedError,
)
from tinysoul.session import SessionEngine
from tinysoul.session.errors import SessionContractError, SessionError
from tinysoul.workspace import (
    WorkspaceEngine,
    WorkspaceBundleWrite,
    WorkspaceManifest,
    WorkspaceRetention,
    emit_workspace_changed,
)
from tinysoul.workspace.errors import WorkspaceContractError, WorkspaceError

from .config import EndpointSettings
from .errors import EndpointRequestError
from .events import EndpointEventBuffer, EndpointEventPage


class EndpointControlKind(StrEnum):
    STOP_TURN = "stop_turn"
    EXIT_PROGRAM = "exit_program"


class PendingMaintenanceDecision(Protocol):
    @property
    def decision_id(self) -> str: ...

    @property
    def change(self) -> HomeMaintenanceChange: ...


class EndpointAppGateway(Protocol):
    @property
    def active_turn_scope(self) -> RunScope | None: ...

    @property
    def current_scope(self) -> RunScope: ...

    def submit_user_input(
        self,
        text: str,
        *,
        source: str,
        metadata: JsonObject,
    ) -> None: ...

    def request_control(
        self,
        kind: LoopControlKind,
        *,
        source: str,
        text: str,
        metadata: JsonObject,
    ) -> None: ...

    def pending_maintenance_decision(
        self,
    ) -> PendingMaintenanceDecision | None: ...

    def resolve_maintenance_decision(
        self,
        decision_id: str,
        decision: HomeMaintenanceDecision | None,
    ) -> bool: ...

    def sync_workspace_context(
        self,
        manifest: WorkspaceManifest,
        *,
        source: str,
    ) -> None: ...


@dataclass(frozen=True)
class EndpointResourceBlob:
    link: str
    data: bytes
    media_type: str
    size: int
    digest: str


class EndpointEngine:
    """Authenticated local protocol facade over existing TinySoul modules."""

    def __init__(
        self,
        *,
        settings: EndpointSettings,
        events: EndpointEventBuffer,
        gateway: EndpointAppGateway,
        observations: ObservationEmitter,
        workspace: WorkspaceEngine,
        session: SessionEngine,
        daily_lifecycle: DailyLifecycleCoordinator,
    ) -> None:
        self._settings = settings
        self._events = events
        self._gateway = gateway
        self._observations = observations
        self._workspace = workspace
        self._session = session
        self._daily = daily_lifecycle

    @property
    def settings(self) -> EndpointSettings:
        return self._settings

    @property
    def events(self) -> EndpointEventBuffer:
        return self._events

    def status(self) -> JsonObject:
        turn_scope = self._gateway.active_turn_scope
        try:
            with self._daily.active_day_lease() as day:
                workspace_revision = self._workspace.load_manifest().revision
                session_revision = self._session.revision
                active_day = str(day)
        except LoopError:
            workspace_revision = -1
            session_revision = -1
            active_day = ""
        pending = self._gateway.pending_maintenance_decision()
        return {
            "protocol_version": 1,
            "ready": bool(active_day),
            "active_day": active_day,
            "turn_active": turn_scope is not None,
            "workspace_revision": workspace_revision,
            "session_revision": session_revision,
            "latest_event_sequence": self._events.latest_sequence,
            "maintenance_decision_pending": pending is not None,
        }

    def submit_user_input(self, text: str, metadata: JsonObject) -> JsonObject:
        if not isinstance(text, str) or not text.strip():
            raise EndpointRequestError(
                status_code=422,
                code="input.invalid",
                message="Input text must be non-empty.",
            )
        try:
            self._gateway.submit_user_input(
                text,
                source="endpoint",
                metadata=to_json_object(metadata),
            )
        except RuntimeInputBlockedError as exc:
            raise EndpointRequestError(
                status_code=409,
                code="maintenance.decision_required",
                message=str(exc),
            ) from exc
        except RuntimeGatewayError as exc:
            raise EndpointRequestError(
                status_code=409,
                code="input.rejected",
                message=str(exc),
            ) from exc
        return {"accepted": True}

    def submit_control(
        self,
        kind: EndpointControlKind,
        metadata: JsonObject,
    ) -> JsonObject:
        loop_kind = {
            EndpointControlKind.STOP_TURN: LoopControlKind.STOP_TURN,
            EndpointControlKind.EXIT_PROGRAM: LoopControlKind.EXIT_PROGRAM,
        }[kind]
        try:
            self._gateway.request_control(
                loop_kind,
                source="endpoint",
                text=kind.value,
                metadata=metadata,
            )
        except RuntimeGatewayError as exc:
            raise EndpointRequestError(
                status_code=409,
                code="control.rejected",
                message=str(exc),
            ) from exc
        return {"accepted": True, "kind": kind.value}

    def replay_events(
        self,
        *,
        after: int,
        mode: ObservationLevel,
        limit: int,
    ) -> EndpointEventPage:
        return self._events.replay(after=after, mode=mode, limit=limit)

    def session_history(self) -> JsonObject:
        try:
            with self._daily.active_day_lease():
                return self._session.inspect_history()
        except LoopError as exc:
            raise _not_ready(exc) from exc
        except SessionError as exc:
            raise _session_error(exc) from exc

    def session_recall(
        self,
        ref: str,
        *,
        max_chars: int | None,
        cursor: int,
    ) -> JsonObject:
        try:
            with self._daily.active_day_lease():
                return self._session.recall_history(
                    ref,
                    max_chars=max_chars,
                    cursor=cursor,
                )
        except LoopError as exc:
            raise _not_ready(exc) from exc
        except SessionError as exc:
            raise _session_error(exc) from exc

    def workspace_manifest(self) -> JsonObject:
        try:
            with self._daily.active_day_lease():
                result = self._workspace.reconcile()
                if not result.complete:
                    raise EndpointRequestError(
                        status_code=409,
                        code="workspace.reconciliation_incomplete",
                        message="Workspace reconciliation is incomplete.",
                        details=to_json_object(
                            {"skip_counts": result.skip_counts()}
                        ),
                    )
                return result.manifest.to_json()
        except EndpointRequestError:
            raise
        except LoopError as exc:
            raise _not_ready(exc) from exc
        except WorkspaceError as exc:
            raise _workspace_error(exc) from exc

    def read_workspace_text(self, link: str) -> JsonObject:
        try:
            with self._daily.active_day_lease():
                read = self._workspace.read_text(
                    link,
                    max_chars=self._settings.max_resource_chars,
                )
                return {
                    "link": read.link,
                    "text": read.text,
                    "truncated": read.truncated,
                    "size": read.size,
                    "digest": read.digest,
                }
        except LoopError as exc:
            raise _not_ready(exc) from exc
        except WorkspaceError as exc:
            raise _workspace_error(exc) from exc

    def read_workspace_blob(self, link: str) -> EndpointResourceBlob:
        try:
            with self._daily.active_day_lease():
                read = self._workspace.read_bytes(
                    link,
                    max_bytes=self._settings.max_resource_bytes,
                )
                return EndpointResourceBlob(
                    link=read.link,
                    data=read.data,
                    media_type=read.media_type,
                    size=read.size,
                    digest=read.digest,
                )
        except LoopError as exc:
            raise _not_ready(exc) from exc
        except WorkspaceError as exc:
            raise _workspace_error(exc) from exc

    def write_workspace_text(
        self,
        *,
        link: str,
        text: str,
        overwrite: bool,
        expected_digest: str,
        expected_revision: int,
        retention: WorkspaceRetention | None,
    ) -> JsonObject:
        try:
            with self._daily.active_day_lease() as day:
                record = self._workspace.write_text(
                    link,
                    text,
                    overwrite=overwrite,
                    expected_digest=expected_digest,
                    expected_revision=expected_revision,
                    retention=retention,
                )
                manifest = self._workspace.load_manifest()
                self._publish_workspace_change(
                    operation="write",
                    day=day,
                    manifest=manifest,
                    link=record.link,
                )
                return {
                    "record": record.to_json(),
                    "manifest": manifest.to_json(),
                }
        except LoopError as exc:
            raise _not_ready(exc) from exc
        except WorkspaceError as exc:
            raise _workspace_error(exc) from exc

    def trash_workspace_resource(
        self,
        *,
        link: str,
        expected_digest: str,
        expected_revision: int,
    ) -> JsonObject:
        try:
            with self._daily.active_day_lease() as day:
                item = self._workspace.trash_resource(
                    link,
                    reason="endpoint.delete",
                    expected_digest=expected_digest,
                    expected_revision=expected_revision,
                )
                manifest = self._workspace.load_manifest()
                self._publish_workspace_change(
                    operation="trash",
                    day=day,
                    manifest=manifest,
                    link=item.original.link,
                )
                return {
                    "trash": {"ref": item.ref, **item.to_json()},
                    "manifest": manifest.to_json(),
                }
        except LoopError as exc:
            raise _not_ready(exc) from exc
        except WorkspaceError as exc:
            raise _workspace_error(exc) from exc

    def write_workspace_blob(
        self,
        *,
        link: str,
        data: bytes,
        overwrite: bool,
        expected_digest: str,
        expected_revision: int,
        retention: WorkspaceRetention | None,
    ) -> JsonObject:
        if len(data) > self._settings.max_request_bytes:
            raise EndpointRequestError(
                status_code=413,
                code="request.too_large",
                message="Workspace blob is too large.",
            )
        try:
            with self._daily.active_day_lease() as day:
                result = self._workspace.write_bundle(
                    (
                        WorkspaceBundleWrite(
                            link=link,
                            data=data,
                            overwrite=overwrite,
                            expected_digest=expected_digest,
                            retention=retention,
                        ),
                    ),
                    expected_revision=expected_revision,
                )
                record = result.records[0]
                self._publish_workspace_change(
                    operation="write",
                    day=day,
                    manifest=result.manifest,
                    link=record.link,
                )
                return {
                    "record": record.to_json(),
                    "manifest": result.manifest.to_json(),
                }
        except LoopError as exc:
            raise _not_ready(exc) from exc
        except WorkspaceError as exc:
            raise _workspace_error(exc) from exc

    def workspace_trash(self) -> JsonObject:
        try:
            with self._daily.active_day_lease():
                return {
                    "items": [
                        {"ref": item.ref, **item.to_json()}
                        for item in self._workspace.trash_items()
                    ]
                }
        except LoopError as exc:
            raise _not_ready(exc) from exc
        except WorkspaceError as exc:
            raise _workspace_error(exc) from exc

    def restore_workspace_resource(
        self,
        *,
        trash_ref: str,
        expected_revision: int,
    ) -> JsonObject:
        try:
            with self._daily.active_day_lease() as day:
                record = self._workspace.restore_resource(
                    trash_ref,
                    expected_revision=expected_revision,
                )
                manifest = self._workspace.load_manifest()
                self._publish_workspace_change(
                    operation="restore",
                    day=day,
                    manifest=manifest,
                    link=record.link,
                )
                return {
                    "record": record.to_json(),
                    "manifest": manifest.to_json(),
                }
        except LoopError as exc:
            raise _not_ready(exc) from exc
        except WorkspaceError as exc:
            raise _workspace_error(exc) from exc

    def maintenance_decision(self) -> JsonObject:
        pending = self._gateway.pending_maintenance_decision()
        if pending is None:
            return {"pending": False}
        return {
            "pending": True,
            "decision_id": pending.decision_id,
            "change": pending.change.to_review_json(),
        }

    def resolve_maintenance_decision(
        self,
        *,
        decision_id: str,
        decision: HomeMaintenanceDecision | None,
    ) -> JsonObject:
        if not self._gateway.resolve_maintenance_decision(decision_id, decision):
            raise EndpointRequestError(
                status_code=409,
                code="maintenance.decision_stale",
                message="Maintenance decision is no longer pending.",
            )
        return {"accepted": True, "decision_id": decision_id}

    def _publish_workspace_change(
        self,
        *,
        operation: str,
        day: BusinessDay,
        manifest: WorkspaceManifest,
        link: str,
    ) -> None:
        self._gateway.sync_workspace_context(
            manifest,
            source="endpoint.workspace",
        )
        emit_workspace_changed(
            self._observations,
            operation=operation,
            day=str(day),
            manifest=manifest,
            link=link,
            scope=self._gateway.current_scope,
            source="endpoint.workspace",
        )


def _not_ready(error: Exception) -> EndpointRequestError:
    return EndpointRequestError(
        status_code=409,
        code="program.not_ready",
        message="TinySoul active day is not ready.",
        details={"error_type": type(error).__name__},
    )


def _workspace_error(error: WorkspaceError) -> EndpointRequestError:
    if isinstance(error, WorkspaceContractError):
        return EndpointRequestError(
            status_code=409,
            code="workspace.conflict",
            message=str(error),
        )
    return EndpointRequestError(
        status_code=500,
        code="workspace.failed",
        message="Workspace operation failed.",
        details={"error_type": type(error).__name__},
    )


def _session_error(error: SessionError) -> EndpointRequestError:
    if isinstance(error, SessionContractError):
        return EndpointRequestError(
            status_code=422,
            code="session.invalid_request",
            message=str(error),
        )
    return EndpointRequestError(
        status_code=500,
        code="session.failed",
        message="Session operation failed.",
        details={"error_type": type(error).__name__},
    )
