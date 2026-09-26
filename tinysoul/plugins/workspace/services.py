"""Current-day Workspace capabilities, excluding lifecycle and physical paths."""

from tinysoul.infra.services import ScopedService, ServiceScope
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol, Self
from tinysoul.kernel.retrieval.operations import SearchSession, SelectionInput
from tinysoul.kernel.retrieval.contracts import (
    RetrievalRequest,
    SearchPage,
    SearchFailure,
    SearchFailureKind,
)
from .engine import WorkspaceEngine, WorkspaceExecutionLocation
from .inspection.models import (
    WorkspaceTextRead,
    WorkspaceBundleWrite,
    WorkspaceBundleResult,
)


class WorkspaceExecutionPort(Protocol):
    def prepare_execution(
        self,
        job_id: str,
        *,
        cwd_link: str = "",
        source_text: str | None = None,
        source_suffix: str = "",
    ) -> WorkspaceExecutionLocation: ...

    def prepare_external_cwd(
        self, connection_id: str, *, cwd_link: str = ""
    ) -> tuple[Path, str]: ...

    def read_text(
        self, link: str, *, max_chars: int | None = None
    ) -> WorkspaceTextRead: ...

    def write_bundle(
        self,
        writes: Sequence[WorkspaceBundleWrite],
        *,
        delete_links: Sequence[str] = (),
    ) -> WorkspaceBundleResult: ...


class WorkspaceExecutionService:
    """Synchronous owner operations needed by controlled execution backends."""

    def __init__(self, owner: WorkspaceEngine) -> None:
        self._owner = owner

    def prepare_execution(
        self,
        job_id: str,
        *,
        cwd_link: str = "",
        source_text: str | None = None,
        source_suffix: str = "",
    ) -> WorkspaceExecutionLocation:
        return self._owner.prepare_execution(
            job_id,
            cwd_link=cwd_link,
            source_text=source_text,
            source_suffix=source_suffix,
        )

    def prepare_external_cwd(
        self, connection_id: str, *, cwd_link: str = ""
    ) -> tuple[Path, str]:
        return self._owner.prepare_external_cwd(connection_id, cwd_link=cwd_link)

    def read_text(
        self, link: str, *, max_chars: int | None = None
    ) -> WorkspaceTextRead:
        return self._owner.read_text(link, max_chars=max_chars)

    def write_bundle(
        self,
        writes: Sequence[WorkspaceBundleWrite],
        *,
        delete_links: Sequence[str] = (),
    ) -> WorkspaceBundleResult:
        return self._owner.write_bundle(writes, delete_links=delete_links)


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
        self.search_retrieval = scope.remote(self._search_retrieval)
        self.max_read_chars = owner.settings.max_read_chars
        self.max_write_chars = owner.settings.max_write_chars
        self.analysis_settings = owner.settings.analysis
        self.snapshot = scope.local(owner.snapshot)
        self.inspect = scope.local(owner.inspect)
        self.read_image = scope.local(owner.read_image)
        self.read_document = scope.local(owner.read_document)
        self.set_description = scope.local(
            owner.set_description, after=owner.events.flush
        )
        self.reconcile = scope.local(owner.reconcile, after=owner.events.flush)
        self.load_manifest = scope.local(owner.load_manifest)
        self.read_text = scope.local(owner.read_text)
        self.read_text_range = scope.local(owner.read_text_range)
        self.read_bytes = scope.local(owner.read_bytes)
        self.search = scope.local(owner.search, after=owner.events.flush)
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

    async def _search_retrieval(
        self, request: RetrievalRequest | str, *, inputs: SelectionInput = SelectionInput()
    ) -> SearchPage:
        if self._queries is None:
            raise SearchFailure(
                SearchFailureKind.INVALID_REQUEST,
                "Workspace retrieval search is not configured in this service",
            )
        return await self._queries.search(request, inputs=inputs)
