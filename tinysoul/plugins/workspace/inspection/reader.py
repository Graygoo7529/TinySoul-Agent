"""Bounded reads and task-local resource bundles."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path

from tinysoul.infra.continuation import ContinuationPosition, OpaqueContinuationCodec
from tinysoul.infra.filesystem import file_digest, read_text_prefix
from tinysoul.infra.json import JsonObject
from tinysoul.infra.paging import PageOptions

from ..config import WorkspaceSettings
from ..errors import (
    WorkspaceContractError,
    WorkspaceImageValidationError,
    WorkspaceIOError,
)
from ..storage.manifest import WorkspaceResourceKind, WorkspaceResourceRecord
from .classification import image_data_matches
from .models import (
    WorkspaceAnalysisBudgetFailure,
    WorkspaceAnalysisBudgetReason,
    WorkspaceAnalysisInput,
    WorkspaceAnalysisPreparation,
    WorkspaceAnalysisReference,
    WorkspaceBlobRead,
    WorkspaceByteRead,
    WorkspaceDocumentRead,
    WorkspaceImageRead,
    WorkspacePromptInput,
    WorkspaceTextRangeResult,
    WorkspaceTextRead,
    WorkspaceTextSlice,
)
from .text import read_text_range


class WorkspaceReader:
    def __init__(
        self,
        *,
        settings: WorkspaceSettings,
        inspect: Callable[[str], WorkspaceResourceRecord],
        path_for: Callable[[str], Path],
    ) -> None:
        self._settings, self._inspect, self._path_for = settings, inspect, path_for

    def read_text(
        self, link: str, *, max_chars: int | None = None
    ) -> WorkspaceTextRead:
        limit = self._settings.max_read_chars if max_chars is None else max_chars
        _positive(limit)
        record = self._inspect(link)
        if record.kind is not WorkspaceResourceKind.TEXT:
            raise WorkspaceContractError("Workspace resource is not readable text")
        try:
            read = read_text_prefix(self._path_for(link), max_chars=limit)
        except UnicodeError as exc:
            raise WorkspaceContractError(
                "Workspace resource is not UTF-8 text"
            ) from exc
        except OSError as exc:
            raise WorkspaceIOError("Workspace text cannot be read") from exc
        return WorkspaceTextRead(record.link, read.text, read.truncated, record.size)

    def read_bytes(self, link: str, *, max_bytes: int) -> WorkspaceByteRead:
        _positive(max_bytes)
        record = self._inspect(link)
        if record.kind is WorkspaceResourceKind.DIRECTORY:
            raise WorkspaceContractError("A directory has no file body")
        try:
            with self._path_for(link).open("rb") as stream:
                data = stream.read(max_bytes + 1)
        except OSError as exc:
            raise WorkspaceIOError("Workspace bytes cannot be read") from exc
        if len(data) > max_bytes:
            raise WorkspaceContractError("Workspace resource exceeds the read limit")
        return WorkspaceByteRead(
            record.link, data, record.kind, record.media_type, len(data)
        )

    def open_blob(self, link: str) -> WorkspaceBlobRead:
        record = self._inspect(link)
        if record.kind is WorkspaceResourceKind.DIRECTORY:
            raise WorkspaceContractError("A directory has no file body")
        try:
            stream = self._path_for(link).open("rb")
            stream.seek(0, 2)
            size = stream.tell()
            stream.seek(0)
        except OSError as exc:
            raise WorkspaceIOError("Workspace blob cannot be opened") from exc
        return WorkspaceBlobRead(record.link, stream, record.media_type, size)

    def browse_text(
        self,
        link: str,
        *,
        day: str,
        page: PageOptions = PageOptions(),
        full: bool = False,
        editable: bool = True,
    ) -> JsonObject:
        record = self._inspect(link)
        if record.kind is not WorkspaceResourceKind.TEXT:
            raise WorkspaceContractError("Workspace resource is not readable text")
        if full and page.continuation is not None:
            raise WorkspaceContractError("Full text reads cannot use a continuation")
        path = self._path_for(link)
        codec = OpaqueContinuationCodec(owner="workspace", operation="text")
        try:
            binding: JsonObject = {"day": day, "content": file_digest(path)}
            position = codec.decode(page.continuation, ref=link, binding=binding)
            read = read_text_range(
                path,
                start_line=1,
                end_line=2**63 - 1,
                cursor=position.item_index,
                max_chars=self._settings.max_write_chars if full else page.max_chars,
            )
        except (OSError, UnicodeError) as exc:
            raise WorkspaceIOError("Workspace text cannot be read") from exc
        if not read.cursor_valid or full and read.truncated:
            raise WorkspaceContractError(
                "Full text exceeds the editable limit or the cursor is invalid"
            )
        value: JsonObject = {
            "link": link,
            "locator": {"link": link, "day": day},
            "day": day,
            "text": read.text,
            "size": record.size,
            "media_type": record.media_type,
            "editable": editable,
            "truncated": read.truncated,
            "complete": not read.truncated and position.item_index == 0,
        }
        if read.next_cursor is not None:
            value["next_continuation"] = codec.encode(
                ContinuationPosition(item_index=read.next_cursor),
                ref=link,
                binding=binding,
            )
        return value

    def read_image(
        self, link: str, *, max_bytes: int | None = None
    ) -> WorkspaceImageRead:
        read = self.read_bytes(
            link,
            max_bytes=(
                self._settings.max_image_bytes if max_bytes is None else max_bytes
            ),
        )
        if read.kind is not WorkspaceResourceKind.IMAGE:
            raise WorkspaceContractError("Workspace resource is not an image")
        if not image_data_matches(read.media_type, read.data):
            raise WorkspaceImageValidationError(
                "Workspace image bytes do not match its media type"
            )
        return WorkspaceImageRead(read.link, read.data, read.media_type, read.size)

    def read_document(self, link: str, *, max_bytes: int) -> WorkspaceDocumentRead:
        read = self.read_bytes(link, max_bytes=max_bytes)
        if read.kind is not WorkspaceResourceKind.DOCUMENT:
            raise WorkspaceContractError("Workspace resource is not a document")
        return WorkspaceDocumentRead(
            read.link, read.data, read.media_type, Path(link).suffix.lower(), read.size
        )

    def read_text_range(
        self,
        link: str,
        *,
        start_line: int,
        end_line: int,
        cursor: int = 0,
        max_chars: int | None = None,
    ) -> WorkspaceTextRangeResult:
        _positive(start_line)
        _positive(end_line)
        limit = self._settings.max_read_chars if max_chars is None else max_chars
        _positive(limit)
        if (
            end_line < start_line
            or isinstance(cursor, bool)
            or not isinstance(cursor, int)
            or cursor < 0
        ):
            raise WorkspaceContractError("Workspace text range is invalid")
        record = self._inspect(link)
        if record.kind is not WorkspaceResourceKind.TEXT:
            raise WorkspaceContractError("Workspace resource is not readable text")
        limit = min(limit, self._settings.max_read_chars)
        try:
            page = read_text_range(
                self._path_for(link),
                start_line=start_line,
                end_line=end_line,
                cursor=cursor,
                max_chars=limit,
            )
        except UnicodeError as exc:
            raise WorkspaceContractError(
                "Workspace resource is not UTF-8 text"
            ) from exc
        except OSError as exc:
            raise WorkspaceIOError("Workspace text range cannot be read") from exc
        if not page.cursor_valid:
            raise WorkspaceContractError("Workspace cursor exceeds its requested range")
        return WorkspaceTextRangeResult(
            record.link, record.size, start_line, end_line, limit, page
        )

    def prepare_task_input(
        self, links: Sequence[str], *, max_chars_per_resource: int | None = None
    ) -> WorkspacePromptInput:
        self._validate_links(links)
        limit = (
            self._settings.max_read_chars
            if max_chars_per_resource is None
            else max_chars_per_resource
        )
        _positive(limit)
        reads = tuple(self.read_text(link, max_chars=limit) for link in links)
        return WorkspacePromptInput(
            tuple(
                WorkspaceTextSlice(
                    read.link, f"prefix:{limit}", read.text, read.truncated, read.size
                )
                for read in reads
            )
        )

    def prepare_analysis_references(
        self, links: Sequence[str]
    ) -> WorkspaceAnalysisPreparation:
        self._validate_links(links)
        settings = self._settings.analysis
        if len(links) > settings.max_reference_links:
            return WorkspaceAnalysisPreparation(
                failure=WorkspaceAnalysisBudgetFailure(
                    WorkspaceAnalysisBudgetReason.REFERENCE_COUNT,
                    settings.max_reference_links,
                    len(links),
                )
            )
        references: list[WorkspaceAnalysisReference] = []
        inspected: list[WorkspaceResourceRecord] = []
        total = 0
        for index, link in enumerate(links, 1):
            inspected.append(self._inspect(link))
            read = self.read_text(link, max_chars=settings.max_chars_per_reference)
            if read.truncated:
                return WorkspaceAnalysisPreparation(
                    failure=WorkspaceAnalysisBudgetFailure(
                        WorkspaceAnalysisBudgetReason.REFERENCE_CHARS,
                        settings.max_chars_per_reference,
                        settings.max_chars_per_reference + 1,
                        link,
                        tuple(inspected),
                    )
                )
            total += len(read.text)
            if total > settings.max_source_chars:
                return WorkspaceAnalysisPreparation(
                    failure=WorkspaceAnalysisBudgetFailure(
                        WorkspaceAnalysisBudgetReason.SOURCE_CHARS,
                        settings.max_source_chars,
                        total,
                        link,
                        tuple(inspected),
                    )
                )
            references.append(
                WorkspaceAnalysisReference(
                    f"source_{index}",
                    link,
                    read.text,
                    read.size,
                    max(1, len(read.text.splitlines())),
                )
            )
        return WorkspaceAnalysisPreparation(
            input=WorkspaceAnalysisInput(tuple(references), total)
        )

    @staticmethod
    def _validate_links(links: Sequence[str]) -> None:
        if (
            not links
            or isinstance(links, str)
            or any(not isinstance(link, str) for link in links)
            or len(set(links)) != len(links)
        ):
            raise WorkspaceContractError(
                "Workspace input requires unique resource links"
            )


def _positive(value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise WorkspaceContractError("Workspace read bounds must be positive integers")
