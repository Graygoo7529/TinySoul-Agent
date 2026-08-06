"""Turn-scoped Memory Maintenance draft and action workflow."""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from datetime import date
from threading import RLock
from typing import Sequence, TypedDict, cast
from uuid import uuid4

from tinysoul.action import (
    ActionEngineBuilder,
    ActionExecution,
    ActionExecutionContext,
    ActionExecutor,
    ActionFailureDisposition,
    ActionLocalFailure,
    ActionResult,
    ActionResultStage,
)
from tinysoul.infra.json import JsonObject, to_json_object
from tinysoul.infra.time import BusinessDay
from tinysoul.memory import (
    ActiveMemorySnapshot,
    ConceptMemoryDocument,
    DailyCompositionRequest,
    DailyMemoryDocument,
    EntityMemoryDocument,
    FactMemoryDocument,
    LLMDailyMemoryComposer,
    MemoryActivity,
    MemoryChangeSet,
    MemoryConfidence,
    MemoryContractError,
    MemoryDocumentChange,
    MemoryEngine,
    MemoryInspectRequest,
    MemoryKind,
    MemoryLink,
    MemoryStatus,
    NoteMemoryDocument,
    PersistentMemoryDocument,
    StoredMemoryDocument,
    inline_memory_links,
)
from tinysoul.memory.errors import MemoryError
from tinysoul.runtime.bridge import RuntimeMemoryBridge, RuntimeWorkspaceBridge
from tinysoul.session import SessionMemoryFactsProjection
from tinysoul.workspace import (
    WorkspaceArchiveView,
    WorkspaceContractError,
    WorkspaceError,
    WorkspaceSourceChanged,
)

from ..errors import MaintenanceContractError, MaintenanceInvariantError


MEMORY_MAINTENANCE_ACTIONS = (
    "maintenance.memory.inspect_sources",
    "maintenance.memory.read_workspace",
    "maintenance.memory.inspect",
    "maintenance.memory.recall",
    "maintenance.memory.stage_create",
    "maintenance.memory.stage_rewrite",
    "maintenance.memory.stage_redirect",
    "maintenance.memory.compose_daily",
    "maintenance.memory.stage_daily",
    "maintenance.memory.preview",
    "maintenance.memory.commit",
    "maintenance.complete",
)


@dataclass(frozen=True)
class MemoryInspectionRef:
    ref: str
    mode: str
    generation: str
    query: str | None = None
    links: tuple[MemoryLink, ...] = ()
    digests: tuple[tuple[MemoryLink, str], ...] = ()


class _NewKnowledgeFields(TypedDict):
    cite: str
    status: MemoryStatus
    created_on: date
    updated_on: date
    activity: MemoryActivity
    content: str
    relations: tuple[MemoryLink, ...]
    evidence: tuple[MemoryLink, ...]
    confidence: MemoryConfidence | None


@dataclass
class MemoryMaintenanceDraft:
    changes: dict[MemoryLink, MemoryDocumentChange] = field(default_factory=dict)
    daily_candidate: str | None = None
    daily_mode: str | None = None
    daily_document: DailyMemoryDocument | None = None
    revision: int = 0
    preview_revision: int | None = None
    changeset: MemoryChangeSet | None = None

    def changed(self) -> None:
        self.revision += 1
        self.preview_revision = None
        self.changeset = None


@dataclass
class _MemoryTaskState:
    target_day: BusinessDay
    projection: SessionMemoryFactsProjection
    active_memory: ActiveMemorySnapshot
    workspace: WorkspaceArchiveView | None
    latest: StoredMemoryDocument | None
    existing_daily: StoredMemoryDocument | None
    draft: MemoryMaintenanceDraft = field(default_factory=MemoryMaintenanceDraft)
    inspections: dict[str, MemoryInspectionRef] = field(default_factory=dict)
    activated: set[MemoryLink] = field(default_factory=set)
    model_calls: int = 0
    committed: bool = False
    unchanged: bool = False
    commit_digests: dict[str, str] = field(default_factory=dict)
    completed: bool = False


class MemoryMaintenanceActionController:
    """Own one target day's source bindings, draft, and commit postcondition."""

    def __init__(
        self,
        *,
        memory: MemoryEngine,
        composer: LLMDailyMemoryComposer,
        memory_bridge: RuntimeMemoryBridge | None = None,
        workspace_bridge: RuntimeWorkspaceBridge | None = None,
    ) -> None:
        self._memory = memory
        self._composer = composer
        self._memory_bridge = memory_bridge or RuntimeMemoryBridge()
        self._workspace_bridge = workspace_bridge or RuntimeWorkspaceBridge()
        self._lock = RLock()
        self._state: _MemoryTaskState | None = None

    def begin(
        self,
        *,
        target_day: BusinessDay,
        projection: SessionMemoryFactsProjection,
        active_memory: ActiveMemorySnapshot,
        workspace: WorkspaceArchiveView | None,
    ) -> None:
        with self._lock:
            if self._state is not None:
                raise MaintenanceInvariantError("A Memory Maintenance task is already active")
            latest = self._memory.latest_daily_before(target_day)
            existing = self._memory.read_document(MemoryLink.daily(target_day.value)) if self._memory.read_daily(target_day) is not None else None
            state = _MemoryTaskState(
                target_day=target_day,
                projection=projection,
                active_memory=active_memory,
                workspace=workspace,
                latest=latest,
                existing_daily=existing,
            )
            for link in inline_memory_links(active_memory.content):
                if link.kind is not MemoryKind.DAILY:
                    state.activated.add(link)
            for fact in projection.facts:
                serialized = json.dumps(
                    fact.to_json(),
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
                for link in inline_memory_links(serialized):
                    if link.kind is not MemoryKind.DAILY:
                        state.activated.add(link)
            self._state = state

    def finish(self) -> JsonObject:
        with self._lock:
            state = self._require_state()
            try:
                if not state.completed or not state.committed:
                    raise MaintenanceInvariantError(
                        "Memory Maintenance Turn ended before owner completion"
                    )
                return to_json_object({
                    "target_day": str(state.target_day),
                    "changed_links": sorted(state.commit_digests),
                    "document_digests": state.commit_digests,
                    "unchanged": state.unchanged,
                    "model_calls": state.model_calls,
                })
            finally:
                self._state = None

    def abort(self) -> None:
        with self._lock:
            self._state = None

    def execute(self, execution: ActionExecution, context: ActionExecutionContext) -> ActionResult:
        del context
        try:
            with self._lock:
                payload = self._execute(self._require_state(), execution)
            return _success(execution, payload)
        except (MaintenanceContractError, MaintenanceInvariantError, MemoryContractError) as exc:
            return _failed(execution, str(exc), reason="memory_request_invalid")
        except (WorkspaceContractError, WorkspaceSourceChanged) as exc:
            return _failed(execution, str(exc), reason="workspace_request_invalid")
        except MemoryError as exc:
            raise self._memory_bridge.from_memory_error(exc) from exc
        except WorkspaceError as exc:
            raise self._workspace_bridge.from_workspace_error(exc) from exc

    def _execute(self, state: _MemoryTaskState, execution: ActionExecution) -> JsonObject:
        name = execution.call.action_name
        params = execution.call.params
        if state.committed and name != "maintenance.complete":
            raise MaintenanceContractError("Memory draft is already committed")
        if name == "maintenance.memory.inspect_sources":
            return self._inspect_sources(state, params)
        if name == "maintenance.memory.read_workspace":
            return self._read_workspace(state, params)
        if name == "maintenance.memory.inspect":
            return self._inspect(state, params)
        if name == "maintenance.memory.recall":
            return self._recall(state, params)
        if name == "maintenance.memory.stage_create":
            return self._stage_create(state, params)
        if name == "maintenance.memory.stage_rewrite":
            return self._stage_rewrite(state, params)
        if name == "maintenance.memory.stage_redirect":
            return self._stage_redirect(state, params)
        if name == "maintenance.memory.compose_daily":
            return self._compose_daily(state, execution)
        if name == "maintenance.memory.stage_daily":
            return self._stage_daily(state, params)
        if name == "maintenance.memory.preview":
            return self._preview(state)
        if name == "maintenance.memory.commit":
            return self._commit(state, params)
        if name == "maintenance.complete":
            if not state.committed:
                raise MaintenanceContractError("Memory Maintenance must commit before completion")
            state.completed = True
            return {"completed": True, "task": "memory"}
        raise MaintenanceContractError(f"Unknown Memory Maintenance action: {name}")

    def _inspect_sources(self, state: _MemoryTaskState, params: JsonObject) -> JsonObject:
        offset = _int(params, "offset", 0, minimum=0, maximum=None)
        limit = _int(params, "limit", 8, minimum=1, maximum=32)
        selected = state.projection.facts[offset : offset + limit]
        return {
            "day": str(state.target_day),
            "session_revision": state.projection.revision,
            "facts": [fact.to_json() for fact in selected],
            "has_more": offset + len(selected) < len(state.projection.facts),
            "active_memory_ref": "memory:target",
            "active_memory_digest": state.active_memory.digest,
            "latest_daily_link": str(state.latest.link) if state.latest else None,
            "latest_daily_digest": state.latest.digest if state.latest else None,
            "existing_daily_link": (
                str(state.existing_daily.link) if state.existing_daily else None
            ),
            "existing_daily_digest": (
                state.existing_daily.digest if state.existing_daily else None
            ),
            "workspace_resources": (
                [
                    {"link": item.link, "kind": item.kind.value, "summary": item.summary, "digest": item.digest}
                    for item in state.workspace.manifest.resources
                ]
                if state.workspace is not None
                else []
            ),
        }

    def _read_workspace(
        self,
        state: _MemoryTaskState,
        params: JsonObject,
    ) -> JsonObject:
        if state.workspace is None:
            raise MaintenanceContractError("Target day has no archived Workspace")
        read = state.workspace.read_text(
            _text(params, "workspace_link"),
            expected_digest=_text(params, "expected_digest"),
            max_chars=_int(params, "max_chars", 12_000, minimum=1, maximum=24_000),
        )
        return {
            "link": read.link,
            "text": read.text,
            "truncated": read.truncated,
            "size": read.size,
            "digest": read.digest,
        }

    def _inspect(self, state: _MemoryTaskState, params: JsonObject) -> JsonObject:
        request = _inspect_request(params)
        if request.memory_link in state.draft.changes:
            document = state.draft.changes[request.memory_link].document
            items = [{
                "link": str(document.link),
                "kind": document.kind.value,
                "display": document.display,
                "status": document.status.value,
                "summary": document.content[:480],
                "score": 1.0,
                "reasons": ["staged"],
            }]
            links = (document.link,)
            mode = "link"
            result_payload = to_json_object(
                {"mode": mode, "items": items, "candidate_count": 1}
            )
        else:
            result = self._memory.inspect(request)
            result_payload = to_json_object({
                "mode": result.mode,
                "items": [item.to_json() for item in result.items],
                "candidate_count": result.candidate_count,
                "outgoing": list(result.outgoing),
                "backlinks": list(result.backlinks),
                "related": list(result.related),
                "continuation": result.continuation,
            })
            links = tuple(MemoryLink.parse(item.link) for item in result.items)
            mode = result.mode
        if request.memory_link is not None:
            state.activated.add(request.memory_link)
            links = (request.memory_link, *tuple(link for link in links if link != request.memory_link))
        ref = self._inspection_ref(state, mode=mode, query=request.query, links=links)
        result_payload["inspection_ref"] = ref.ref
        return result_payload

    def _recall(self, state: _MemoryTaskState, params: JsonObject) -> JsonObject:
        link = _link(params, "memory_link")
        staged = state.draft.changes.get(link)
        if staged is not None:
            document = staged.document
            payload = to_json_object({
                "link": str(link),
                "kind": link.kind.value,
                "markdown": self._memory.render_document(document),
                "digest": "staged",
                "status": document.status.value,
            })
            digest = "staged"
        else:
            recalled = self._memory.recall(link)
            payload = to_json_object({
                "link": recalled.link,
                "kind": recalled.kind,
                "markdown": recalled.content,
                "digest": recalled.digest,
                "metadata": recalled.metadata,
                "resolution_chain": list(recalled.resolution_chain),
            })
            digest = recalled.digest
        if link.kind is not MemoryKind.DAILY:
            state.activated.add(link)
        ref = self._inspection_ref(state, mode="recall", query=None, links=(link,), explicit_digests=((link, digest),))
        payload["inspection_ref"] = ref.ref
        return payload

    def _stage_create(self, state: _MemoryTaskState, params: JsonObject) -> JsonObject:
        kind = _kind(params)
        if kind is MemoryKind.DAILY:
            raise MaintenanceContractError("Use stage_daily for daily Memory")
        ref = self._require_inspection(state, params, "inspection_ref", mode="query")
        if ref.generation != self._memory.catalog_snapshot.generation:
            raise MaintenanceContractError("Memory inspection_ref is stale")
        if kind in {MemoryKind.ENTITY, MemoryKind.CONCEPT}:
            raw_cite = params.get("cite")
            if not isinstance(raw_cite, str):
                raise MaintenanceContractError("Entity/concept create requires cite")
            link = MemoryLink(kind, raw_cite)
        else:
            link = self._memory.new_link(kind)
        if link in state.draft.changes or link in self._memory.catalog_snapshot.entries:
            raise MaintenanceContractError(f"Memory already exists: {link}")
        document = _new_document(kind, link, params, state.target_day.value)
        state.draft.changes[link] = MemoryDocumentChange(document=document, expected_absent=True)
        state.activated.add(link)
        state.draft.changed()
        return {"staged": True, "link": str(link), "draft_revision": state.draft.revision}

    def _stage_rewrite(self, state: _MemoryTaskState, params: JsonObject) -> JsonObject:
        link = _link(params, "memory_link")
        ref = self._require_inspection(state, params, "inspection_ref", mode="recall")
        expected = _text(params, "expected_digest")
        _validate_exact_ref(ref, link, expected)
        stored = self._memory.read_document(link)
        if stored.digest != expected:
            raise MaintenanceContractError("Memory rewrite digest is stale")
        if link.kind is MemoryKind.DAILY:
            raise MaintenanceContractError("Use stage_daily for daily Memory")
        if stored.document.status is not MemoryStatus.ACTIVE:
            raise MaintenanceContractError("Only active Memory can be rewritten")
        document = _rewrite_document(stored.document, params, state.target_day.value)
        state.draft.changes[link] = MemoryDocumentChange(document=document, expected_digest=expected)
        state.activated.add(link)
        state.draft.changed()
        return {"staged": True, "link": str(link), "draft_revision": state.draft.revision}

    def _stage_redirect(self, state: _MemoryTaskState, params: JsonObject) -> JsonObject:
        source = _link(params, "source_link")
        target = _link(params, "target_link")
        source_ref = self._require_inspection(state, params, "source_inspection_ref", mode="recall")
        target_ref = self._require_inspection(state, params, "target_inspection_ref", mode="recall")
        expected = _text(params, "expected_digest")
        _validate_exact_ref(source_ref, source, expected)
        if target not in target_ref.links:
            raise MaintenanceContractError("Target inspection_ref does not bind target_link")
        target_change = state.draft.changes.get(target)
        if target_change is not None:
            if (target, "staged") not in target_ref.digests:
                raise MaintenanceContractError("Target inspection_ref is stale")
        else:
            target_stored = self._memory.read_document(target)
            if (target, target_stored.digest) not in target_ref.digests:
                raise MaintenanceContractError("Target inspection_ref is stale")
        stored = self._memory.read_document(source)
        if stored.digest != expected:
            raise MaintenanceContractError("Memory redirect digest is stale")
        status_raw = _text(params, "status")
        try:
            status = MemoryStatus(status_raw)
        except ValueError as exc:
            raise MaintenanceContractError("Memory redirect status is invalid") from exc
        if status is MemoryStatus.ACTIVE:
            raise MaintenanceContractError("Memory redirect status must be non-active")
        migration_content = _text(params, "migration_content")
        document = _redirect_document(
            stored.document,
            target=target,
            status=status,
            content=migration_content,
            day=state.target_day.value,
        )
        state.draft.changes[source] = MemoryDocumentChange(document=document, expected_digest=expected)
        state.activated.update({source, target})
        state.draft.changed()
        return {"staged": True, "link": str(source), "redirect_to": str(target), "draft_revision": state.draft.revision}

    def _compose_daily(self, state: _MemoryTaskState, execution: ActionExecution) -> JsonObject:
        result = self._composer.compose(
            DailyCompositionRequest(
                day=state.target_day,
                session=state.projection,
                active_memory=state.active_memory,
                latest=state.latest,
                existing=state.existing_daily,
                settings=self._memory.settings.daily_composition,
                max_document_chars=self._memory.settings.documents.daily_max_chars,
            ),
            scope=execution.framework.scope,
        )
        state.draft.daily_candidate = result.content
        state.draft.daily_mode = None
        state.draft.daily_document = None
        state.model_calls += result.model_calls
        state.draft.changed()
        return {"composed": True, "chars": len(result.content), "model_calls": result.model_calls, "draft_revision": state.draft.revision}

    def _stage_daily(self, state: _MemoryTaskState, params: JsonObject) -> JsonObject:
        if state.draft.daily_candidate is None:
            raise MaintenanceContractError("Compose daily before staging it")
        mode = _text(params, "mode")
        if mode not in {"create", "replace", "unchanged"}:
            raise MaintenanceContractError("Daily stage mode is invalid")
        existing = state.existing_daily
        existing_document: DailyMemoryDocument | None = None
        if existing is not None:
            if not isinstance(existing.document, DailyMemoryDocument):
                raise MaintenanceInvariantError(
                    "Target daily Link resolved to another Memory kind"
                )
            existing_document = existing.document
        if mode == "create" and existing is not None:
            raise MaintenanceContractError("Daily create requires an absent target")
        if mode in {"replace", "unchanged"} and existing is None:
            raise MaintenanceContractError(f"Daily {mode} requires an existing target")
        if mode == "unchanged":
            assert existing is not None
            assert existing_document is not None
            if existing_document.content.strip() != state.draft.daily_candidate.strip():
                raise MaintenanceContractError("Unchanged daily candidate differs from stored daily")
            document = existing_document
        else:
            old = existing_document
            document = DailyMemoryDocument(
                day=state.target_day.value,
                revision=(old.revision + 1 if isinstance(old, DailyMemoryDocument) else 0),
                created_on=(old.created_on if isinstance(old, DailyMemoryDocument) else state.target_day.value),
                updated_on=state.target_day.value,
                session_revision=state.projection.revision,
                active_memory_digest=state.active_memory.digest,
                content=state.draft.daily_candidate,
            )
        state.draft.daily_mode = mode
        state.draft.daily_document = document
        state.draft.changed()
        return {"staged": True, "mode": mode, "link": str(document.link), "draft_revision": state.draft.revision}

    def _preview(self, state: _MemoryTaskState) -> JsonObject:
        if state.draft.daily_mode is None or state.draft.daily_document is None:
            raise MaintenanceContractError("Memory Maintenance must stage daily before preview")
        changes = dict(state.draft.changes)
        for change in _activity_changes(state, self._memory):
            changes.setdefault(change.link, change)
        if state.draft.daily_mode != "unchanged":
            daily = state.draft.daily_document
            changes[daily.link] = MemoryDocumentChange(
                document=daily,
                expected_absent=state.existing_daily is None,
                expected_digest=(state.existing_daily.digest if state.existing_daily is not None else None),
            )
        state.draft.changes = changes
        if changes:
            state.draft.changeset = self._memory.prepare_changeset(
                target_day=state.target_day,
                changes=tuple(changes.values()),
            )
        else:
            state.draft.changeset = None
        state.draft.preview_revision = state.draft.revision
        return to_json_object({
            "preview_revision": state.draft.revision,
            "daily_mode": state.draft.daily_mode,
            "changes": [
                {"link": str(change.link), "kind": change.link.kind.value}
                for change in changes.values()
            ],
        })

    def _commit(self, state: _MemoryTaskState, params: JsonObject) -> JsonObject:
        revision = _int(params, "preview_revision", -1, minimum=0, maximum=None)
        if state.draft.preview_revision != revision or state.draft.revision != revision:
            raise MaintenanceContractError("Memory preview revision is stale")
        if state.draft.changeset is None:
            state.unchanged = True
            state.commit_digests = {}
        else:
            outcome = self._memory.commit(state.draft.changeset)
            state.commit_digests = outcome.document_digests
        state.committed = True
        return to_json_object({
            "committed": True,
            "unchanged": state.unchanged,
            "document_digests": state.commit_digests,
        })

    def _inspection_ref(
        self,
        state: _MemoryTaskState,
        *,
        mode: str,
        query: str | None,
        links: tuple[MemoryLink, ...],
        explicit_digests: tuple[tuple[MemoryLink, str], ...] = (),
    ) -> MemoryInspectionRef:
        digests = explicit_digests or tuple(
            (link, self._memory.catalog_snapshot.require(link).digest)
            for link in links
            if link in self._memory.catalog_snapshot.entries
        )
        value = MemoryInspectionRef(
            ref=f"inspection_{uuid4().hex}",
            mode=mode,
            generation=self._memory.catalog_snapshot.generation,
            query=query,
            links=links,
            digests=digests,
        )
        state.inspections[value.ref] = value
        return value

    def _require_inspection(
        self,
        state: _MemoryTaskState,
        params: JsonObject,
        key: str,
        *,
        mode: str,
    ) -> MemoryInspectionRef:
        raw = _text(params, key)
        value = state.inspections.get(raw)
        if value is None or value.mode != mode:
            raise MaintenanceContractError(f"Memory {key} is missing or has wrong mode")
        if value.generation != self._memory.catalog_snapshot.generation:
            raise MaintenanceContractError(f"Memory {key} is stale")
        return value

    def _require_state(self) -> _MemoryTaskState:
        if self._state is None:
            raise MaintenanceInvariantError("No Memory Maintenance task is active")
        return self._state


class MemoryMaintenanceActionExecutor(ActionExecutor):
    def __init__(self, controller: MemoryMaintenanceActionController) -> None:
        self._controller = controller

    def execute(self, execution: ActionExecution, context: ActionExecutionContext) -> ActionResult:
        return self._controller.execute(execution, context)


def register_memory_maintenance_actions(
    builder: ActionEngineBuilder,
    *,
    controller: MemoryMaintenanceActionController,
) -> ActionEngineBuilder:
    executor = MemoryMaintenanceActionExecutor(controller)
    for handler in MEMORY_MAINTENANCE_ACTIONS:
        builder.register_executor(handler, executor)
    return builder


def _new_document(kind: MemoryKind, link: MemoryLink, params: JsonObject, day: date) -> PersistentMemoryDocument:
    common = _common_create(params, link, day)
    if kind is MemoryKind.ENTITY:
        return EntityMemoryDocument(**common)
    if kind is MemoryKind.CONCEPT:
        return ConceptMemoryDocument(**common)
    if kind is MemoryKind.FACT:
        return FactMemoryDocument(**common, summary=_text(params, "summary"))
    if kind is MemoryKind.NOTE:
        return NoteMemoryDocument(**common, title=_text(params, "title"))
    raise MaintenanceContractError("Unsupported Memory create kind")


def _common_create(
    params: JsonObject,
    link: MemoryLink,
    day: date,
) -> _NewKnowledgeFields:
    confidence = _confidence(params.get("confidence"))
    return {
        "cite": link.cite,
        "status": MemoryStatus.ACTIVE,
        "created_on": day,
        "updated_on": day,
        "activity": MemoryActivity(day, 1),
        "content": _text(params, "content"),
        "relations": _links(params.get("relations", []), "relations"),
        "evidence": _links(params.get("evidence", []), "evidence"),
        "confidence": confidence,
    }


def _rewrite_document(document: PersistentMemoryDocument, params: JsonObject, day: date) -> PersistentMemoryDocument:
    if isinstance(document, DailyMemoryDocument):
        raise MaintenanceContractError("Daily rewrite uses stage_daily")
    values = {
        "content": _optional_text(params, "content", document.content),
        "relations": _optional_links(params, "relations", document.relations),
        "evidence": _optional_links(params, "evidence", document.evidence),
        "confidence": _optional_confidence(params, document.confidence),
        "updated_on": day,
        "activity": _activate(document.activity, day),
    }
    if isinstance(document, FactMemoryDocument):
        return replace(document, **values, summary=_optional_text(params, "summary", document.summary))
    if isinstance(document, NoteMemoryDocument):
        return replace(document, **values, title=_optional_text(params, "title", document.title))
    return replace(document, **values)


def _redirect_document(
    document: PersistentMemoryDocument,
    *,
    target: MemoryLink,
    status: MemoryStatus,
    content: str,
    day: date,
) -> PersistentMemoryDocument:
    if isinstance(document, DailyMemoryDocument):
        raise MaintenanceContractError("Daily Memory cannot redirect")
    if status in {MemoryStatus.MERGED, MemoryStatus.SUPERSEDED} and target.kind is not document.kind:
        raise MaintenanceContractError("Merged/superseded redirect must target the same kind")
    return replace(
        document,
        status=status,
        redirect_to=target,
        content=content,
        updated_on=day,
        activity=_activate(document.activity, day),
    )


def _activity_changes(state: _MemoryTaskState, memory: MemoryEngine) -> tuple[MemoryDocumentChange, ...]:
    result: list[MemoryDocumentChange] = []
    for link in sorted(state.activated, key=str):
        if link.kind is MemoryKind.DAILY or link in state.draft.changes:
            continue
        entry = memory.catalog_snapshot.get(link)
        if entry is None:
            continue
        stored = memory.read_document(link)
        document = stored.document
        if isinstance(document, DailyMemoryDocument):
            continue
        updated = replace(
            document,
            updated_on=state.target_day.value,
            activity=_activate(document.activity, state.target_day.value),
        )
        result.append(MemoryDocumentChange(document=updated, expected_digest=stored.digest))
    return tuple(result)


def _activate(activity: MemoryActivity, day: date) -> MemoryActivity:
    return MemoryActivity(last_activated_on=day, activation_count=activity.activation_count + 1)


def _validate_exact_ref(ref: MemoryInspectionRef, link: MemoryLink, digest: str) -> None:
    if link not in ref.links or (link, digest) not in ref.digests:
        raise MaintenanceContractError("Memory inspection_ref does not bind Link and digest")


def _inspect_request(params: JsonObject) -> MemoryInspectRequest:
    raw_query = params.get("query")
    raw_link = params.get("memory_link")
    query = raw_query if isinstance(raw_query, str) else None
    link = MemoryLink.parse(raw_link) if isinstance(raw_link, str) else None
    raw_kinds = params.get("kinds", [])
    if not isinstance(raw_kinds, list) or any(not isinstance(item, str) for item in raw_kinds):
        raise MaintenanceContractError("Memory inspect kinds are invalid")
    try:
        kinds = tuple(MemoryKind(item) for item in raw_kinds)
    except ValueError as exc:
        raise MaintenanceContractError("Memory inspect kind is invalid") from exc
    raw_limit = params.get("limit")
    limit = None if raw_limit is None else _int(params, "limit", 8, minimum=1, maximum=None)
    continuation = params.get("continuation")
    if continuation is not None and not isinstance(continuation, str):
        raise MaintenanceContractError("Memory inspect continuation is invalid")
    return MemoryInspectRequest(query=query, memory_link=link, kinds=kinds, limit=limit, continuation=continuation)


def _kind(params: JsonObject) -> MemoryKind:
    raw = _text(params, "kind")
    try:
        return MemoryKind(raw)
    except ValueError as exc:
        raise MaintenanceContractError("Memory kind is invalid") from exc


def _link(params: JsonObject, key: str) -> MemoryLink:
    try:
        return MemoryLink.parse(_text(params, key))
    except MemoryContractError as exc:
        raise MaintenanceContractError(f"Memory {key} is invalid") from exc


def _links(value: object, key: str) -> tuple[MemoryLink, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise MaintenanceContractError(f"Memory {key} must be a Link list")
    return tuple(
        MemoryLink.parse(item)
        for item in cast(Sequence[str], value)
    )


def _optional_links(params: JsonObject, key: str, default: tuple[MemoryLink, ...]) -> tuple[MemoryLink, ...]:
    return default if key not in params else _links(params.get(key), key)


def _confidence(value: object) -> MemoryConfidence | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise MaintenanceContractError("Memory confidence is invalid")
    try:
        return MemoryConfidence(value)
    except ValueError as exc:
        raise MaintenanceContractError("Memory confidence is invalid") from exc


def _optional_confidence(params: JsonObject, default: MemoryConfidence | None) -> MemoryConfidence | None:
    return default if "confidence" not in params else _confidence(params.get("confidence"))


def _text(params: JsonObject, key: str) -> str:
    value = params.get(key)
    if not isinstance(value, str) or not value.strip():
        raise MaintenanceContractError(f"Memory parameter {key} must be non-empty text")
    return value


def _optional_text(params: JsonObject, key: str, default: str) -> str:
    return default if key not in params else _text(params, key)


def _int(params: JsonObject, key: str, default: int, *, minimum: int, maximum: int | None) -> int:
    value = params.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise MaintenanceContractError(f"Memory parameter {key} is invalid")
    if maximum is not None and value > maximum:
        raise MaintenanceContractError(f"Memory parameter {key} exceeds {maximum}")
    return value


def _success(execution: ActionExecution, payload: JsonObject) -> ActionResult:
    return ActionResult.success(
        call_id=execution.call.call_id,
        invoke_id=execution.framework.invoke_id,
        batch_id=execution.framework.batch_id,
        action_name=execution.call.action_name,
        sequence=execution.call.sequence,
        domain=execution.framework.domain,
        payload=payload,
    )


def _failed(execution: ActionExecution, feedback: str, *, reason: str) -> ActionResult:
    return ActionResult.failed(
        call_id=execution.call.call_id,
        invoke_id=execution.framework.invoke_id,
        batch_id=execution.framework.batch_id,
        action_name=execution.call.action_name,
        stage=ActionResultStage.EXECUTE,
        sequence=execution.call.sequence,
        domain=execution.framework.domain,
        failure=ActionLocalFailure(
            reason=reason,
            scope="maintenance.memory",
            disposition=ActionFailureDisposition.CHANGE_REQUEST,
            feedback=feedback,
        ),
    )
