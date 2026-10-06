"""Current-day Workspace capabilities, excluding lifecycle and physical paths."""

from collections.abc import Sequence
from pathlib import Path
from typing import Protocol, Self

from tinysoul.infra.services import ScopedService, ServiceScope
from tinysoul.kernel.retrieval.contracts import (
    RetrievalRequest,
    SearchFailure,
    SearchFailureKind,
    SearchPage,
)
from tinysoul.kernel.retrieval.operations import SearchSession, SelectionInput

from .engine import WorkspaceEngine, WorkspaceExecutionLocation
from .inspection.models import (
    WorkspaceBundleResult,
    WorkspaceBundleWrite,
    WorkspaceTextRead,
)


class WorkspaceExecutionPort(Protocol):
    def prepare_execution(
        self,
        job_id: str,
        *,
        cwd_ref: str = "",
        source_text: str | None = None,
        source_suffix: str = "",
    ) -> WorkspaceExecutionLocation: ...

    def prepare_external_cwd(
        self, connection_id: str, *, cwd_ref: str = ""
    ) -> tuple[Path, str]: ...

    def read_text(
        self, ref: str, *, max_chars: int | None = None
    ) -> WorkspaceTextRead: ...

    def write_bundle(
        self,
        writes: Sequence[WorkspaceBundleWrite],
        *,
        delete_refs: Sequence[str] = (),
    ) -> WorkspaceBundleResult: ...


class WorkspaceExecutionService:
    """Synchronous owner operations needed by controlled execution backends."""

    def __init__(self, owner: WorkspaceEngine) -> None:
        self._owner = owner

    def prepare_execution(
        self,
        job_id: str,
        *,
        cwd_ref: str = "",
        source_text: str | None = None,
        source_suffix: str = "",
    ) -> WorkspaceExecutionLocation:
        return self._owner.prepare_execution(
            job_id,
            cwd_ref=cwd_ref,
            source_text=source_text,
            source_suffix=source_suffix,
        )

    def prepare_external_cwd(
        self, connection_id: str, *, cwd_ref: str = ""
    ) -> tuple[Path, str]:
        return self._owner.prepare_external_cwd(connection_id, cwd_ref=cwd_ref)

    def read_text(self, ref: str, *, max_chars: int | None = None) -> WorkspaceTextRead:
        return self._owner.read_text(ref, max_chars=max_chars)

    def write_bundle(
        self,
        writes: Sequence[WorkspaceBundleWrite],
        *,
        delete_refs: Sequence[str] = (),
    ) -> WorkspaceBundleResult:
        return self._owner.write_bundle(writes, delete_refs=delete_refs)


class WorkspaceService(ScopedService[WorkspaceEngine]):
    def __init__(
        self,
        owner: WorkspaceEngine,
        scope: ServiceScope = ServiceScope(),
        *,
        queries: SearchSession | None = None,
    ) -> None:
        super().__init__(owner, scope)
        self._queries = queries
        self.retrieval_policies = queries.retrieval_policies if queries else ()
        self.search = scope.remote(self._search)
        self.max_read_chars = owner.settings.max_read_chars
        self.max_write_chars = owner.settings.max_write_chars
        self.analysis_settings = owner.settings.analysis
        self.snapshot = scope.local(owner.snapshot)
        self.stat = scope.local(owner.stat)
        self.inspect = scope.local(owner.inspect)
        self.read_image = scope.local(owner.read_image)
        self.read_document = scope.local(owner.read_document)
        self.set_description = scope.local(
            owner.set_description, after=owner.events.flush
        )
        self.reconcile = scope.local(owner.reconcile, after=owner.events.flush)
        self.load_manifest = scope.local(owner.load_manifest)
        self.read_text = scope.local(owner.read_text)
        self.browse_text = scope.local(owner.browse_text)
        self.open_blob = scope.local(owner.open_blob)
        self.read_text_range = scope.local(owner.read_text_range)
        self.read_bytes = scope.local(owner.read_bytes)
        self.write_text = scope.local(owner.write_text, after=owner.events.flush)
        self.write_bundle = scope.local(owner.write_bundle, after=owner.events.flush)
        self.edit_text = scope.local(owner.edit_text, after=owner.events.flush)
        self.mkdir = scope.local(owner.mkdir, after=owner.events.flush)
        self.move = scope.local(owner.move, after=owner.events.flush)
        self.tag = scope.local(owner.tag, after=owner.events.flush)
        self.append_text = scope.local(owner.append_text, after=owner.events.flush)
        self.trash_resource = scope.local(
            owner.trash_resource, after=owner.events.flush
        )
        self.restore_resource = scope.local(
            owner.restore_resource, after=owner.events.flush
        )
        self.trash_items = scope.local(owner.trash_items)
        self.write_target_exists = scope.local(owner.write_target_exists)
        self.prepare_task_input = scope.local(owner.prepare_task_input)
        self.prepare_analysis_references = scope.local(
            owner.prepare_analysis_references
        )

    def _bind(self, scope: ServiceScope) -> Self:
        return type(self)(self._owner, scope, queries=self._queries)

    async def _search(
        self,
        request: RetrievalRequest | str,
        *,
        inputs: SelectionInput = SelectionInput(),
    ) -> SearchPage:
        if self._queries is None:
            raise SearchFailure(
                SearchFailureKind.INVALID_REQUEST,
                "Workspace retrieval search is not configured in this service",
            )
        return await self._queries.search(request, inputs=inputs)
