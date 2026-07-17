"""Transactional execution mirrors for Workspace-scoped processes."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import shutil

from .engine import WorkspaceBundleWrite, WorkspaceEngine
from .errors import (
    WorkspaceContractError,
    WorkspaceIOError,
    WorkspaceMirrorConflict,
    WorkspaceReconciliationError,
)
from .links import WorkspaceLink
from .manifest import WorkspaceManifest, WorkspaceRetention


@dataclass(frozen=True)
class WorkspaceMirrorEntry:
    link: str
    digest: str
    size: int
    retention: WorkspaceRetention
    owner_turn_id: str


@dataclass(frozen=True)
class WorkspaceMirror:
    root: Path
    baseline_revision: int
    entries: tuple[WorkspaceMirrorEntry, ...]


@dataclass(frozen=True)
class WorkspaceMirrorCandidate:
    path: str
    change: str
    size: int
    digest: str

    @property
    def workspace_link(self) -> str:
        return str(WorkspaceLink.from_relative_path(self.path))


@dataclass(frozen=True)
class WorkspaceMirrorDiff:
    candidates: tuple[WorkspaceMirrorCandidate, ...]
    total_bytes: int


@dataclass(frozen=True)
class WorkspaceMirrorCommit:
    manifest: WorkspaceManifest
    links: tuple[str, ...]
    changes: tuple[WorkspaceMirrorCandidate, ...]


class WorkspaceMirrorService:
    """Create bounded mirrors and commit their diff through WorkspaceEngine."""

    def __init__(
        self,
        workspace: WorkspaceEngine,
        *,
        max_files: int,
        max_total_bytes: int,
        max_file_bytes: int,
    ) -> None:
        for value in (max_files, max_total_bytes, max_file_bytes):
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise WorkspaceContractError("Workspace mirror limits must be positive")
        self._workspace = workspace
        self._max_files = max_files
        self._max_total_bytes = max_total_bytes
        self._max_file_bytes = max_file_bytes

    def create(self, root: Path) -> WorkspaceMirror:
        reconciliation = self._workspace.reconcile()
        if not reconciliation.complete:
            raise WorkspaceReconciliationError(
                "Workspace mirror requires complete reconciliation"
            )
        try:
            if root.exists():
                raise WorkspaceContractError("Workspace mirror root already exists")
            root.mkdir(parents=True)
        except WorkspaceContractError:
            raise
        except OSError as exc:
            raise WorkspaceIOError("Workspace mirror root could not be created") from exc
        records = reconciliation.manifest.resources
        if len(records) > self._max_files:
            raise WorkspaceContractError("Workspace mirror file limit was exceeded")
        total = 0
        entries: list[WorkspaceMirrorEntry] = []
        try:
            for record in records:
                if record.size > self._max_file_bytes:
                    raise WorkspaceContractError(
                        f"Workspace mirror file exceeds its limit: {record.link}"
                    )
                total += record.size
                if total > self._max_total_bytes:
                    raise WorkspaceContractError(
                        "Workspace mirror total byte limit was exceeded"
                    )
                source = self._workspace.path_for(record.link)
                target = root.joinpath(*WorkspaceLink.parse(record.link).path.parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                if source.is_symlink() or not source.is_file():
                    raise WorkspaceContractError(
                        f"Workspace mirror source is not a regular file: {record.link}"
                    )
                shutil.copyfile(source, target)
                entries.append(
                    WorkspaceMirrorEntry(
                        link=record.link,
                        digest=record.digest,
                        size=record.size,
                        retention=record.retention,
                        owner_turn_id=record.owner_turn_id,
                    )
                )
        except (OSError, WorkspaceContractError) as exc:
            try:
                shutil.rmtree(root)
            except OSError:
                pass
            if isinstance(exc, WorkspaceContractError):
                raise
            raise WorkspaceIOError("Workspace mirror could not be populated") from exc
        return WorkspaceMirror(
            root=root,
            baseline_revision=reconciliation.manifest.revision,
            entries=tuple(entries),
        )

    def diff(self, mirror: WorkspaceMirror) -> WorkspaceMirrorDiff:
        baseline = {entry.link: entry for entry in mirror.entries}
        current: dict[str, tuple[bytes, str]] = {}
        total = 0
        try:
            if any(path.is_symlink() for path in mirror.root.rglob("*")):
                raise WorkspaceContractError(
                    "Workspace mirror cannot contain symbolic links"
                )
            paths = sorted(path for path in mirror.root.rglob("*") if path.is_file())
            if len(paths) > self._max_files:
                raise WorkspaceContractError("Workspace mirror file limit was exceeded")
            for path in paths:
                relative = path.relative_to(mirror.root).as_posix()
                link = str(WorkspaceLink.from_relative_path(relative))
                data = path.read_bytes()
                if len(data) > self._max_file_bytes:
                    raise WorkspaceContractError(
                        f"Workspace mirror file exceeds its limit: {link}"
                    )
                total += len(data)
                if total > self._max_total_bytes:
                    raise WorkspaceContractError(
                        "Workspace mirror total byte limit was exceeded"
                    )
                current[link] = (data, sha256(data).hexdigest())
        except WorkspaceContractError:
            raise
        except (OSError, ValueError) as exc:
            raise WorkspaceIOError("Workspace mirror could not be inspected") from exc
        candidates: list[WorkspaceMirrorCandidate] = []
        for link in sorted(set(baseline) | set(current)):
            old = baseline.get(link)
            observed = current.get(link)
            if old is None and observed is not None:
                data, digest = observed
                candidates.append(
                    WorkspaceMirrorCandidate(
                        path=WorkspaceLink.parse(link).relative_path,
                        change="created",
                        size=len(data),
                        digest=digest,
                    )
                )
            elif old is not None and observed is None:
                candidates.append(
                    WorkspaceMirrorCandidate(
                        path=WorkspaceLink.parse(link).relative_path,
                        change="deleted",
                        size=0,
                        digest="",
                    )
                )
            elif old is not None and observed is not None and old.digest != observed[1]:
                data, digest = observed
                candidates.append(
                    WorkspaceMirrorCandidate(
                        path=WorkspaceLink.parse(link).relative_path,
                        change="modified",
                        size=len(data),
                        digest=digest,
                    )
                )
        return WorkspaceMirrorDiff(candidates=tuple(candidates), total_bytes=total)

    def read_candidate(
        self,
        mirror: WorkspaceMirror,
        relative_path: str,
        *,
        cursor: int,
        max_chars: int,
    ) -> tuple[str, int, bool]:
        parsed = WorkspaceLink.from_relative_path(relative_path)
        path = mirror.root.joinpath(*parsed.path.parts)
        if path.is_symlink() or not path.is_file():
            raise WorkspaceContractError(
                f"Workspace mirror candidate does not exist: {relative_path}"
            )
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise WorkspaceContractError(
                f"Workspace mirror candidate is not UTF-8 text: {relative_path}"
            ) from exc
        except OSError as exc:
            raise WorkspaceIOError("Workspace mirror candidate could not be read") from exc
        if cursor < 0 or max_chars <= 0:
            raise WorkspaceContractError("Workspace mirror read boundaries are invalid")
        start = min(cursor, len(text))
        end = min(len(text), start + max_chars)
        return text[start:end], end, end < len(text)

    def commit(
        self,
        mirror: WorkspaceMirror,
        *,
        owner_turn_id: str,
    ) -> WorkspaceMirrorCommit:
        if not isinstance(owner_turn_id, str):
            raise WorkspaceContractError("Workspace mirror owner Turn id must be text")
        diff = self.diff(mirror)
        if not diff.candidates:
            return WorkspaceMirrorCommit(
                manifest=self._workspace.snapshot(),
                links=(),
                changes=(),
            )
        baseline = {entry.link: entry for entry in mirror.entries}
        active = self._workspace.reconcile()
        if not active.complete:
            raise WorkspaceReconciliationError(
                "Workspace mirror commit requires complete reconciliation"
            )
        current = {record.link: record for record in active.manifest.resources}
        writes: list[WorkspaceBundleWrite] = []
        deletes: list[str] = []
        delete_digests: dict[str, str] = {}
        for candidate in diff.candidates:
            link = candidate.workspace_link
            old = baseline.get(link)
            observed = current.get(link)
            if old is None:
                if observed is not None:
                    raise WorkspaceMirrorConflict(
                        f"Workspace mirror target was created concurrently: {link}"
                    )
                retention = WorkspaceRetention.DAY
                new_owner_turn_id = owner_turn_id
                expected_digest = ""
                overwrite = False
            else:
                if observed is None or observed.digest != old.digest:
                    raise WorkspaceMirrorConflict(
                        f"Workspace mirror target changed concurrently: {link}"
                    )
                retention = old.retention
                new_owner_turn_id = old.owner_turn_id
                expected_digest = old.digest
                overwrite = True
            if candidate.change == "deleted":
                deletes.append(link)
                delete_digests[link] = old.digest if old is not None else ""
                continue
            path = mirror.root.joinpath(*WorkspaceLink.parse(link).path.parts)
            try:
                data = path.read_bytes()
            except OSError as exc:
                raise WorkspaceIOError(
                    f"Workspace mirror candidate could not be committed: {link}"
                ) from exc
            writes.append(
                WorkspaceBundleWrite(
                    link=link,
                    data=data,
                    overwrite=overwrite,
                    expected_digest=expected_digest,
                    retention=retention,
                    owner_turn_id=new_owner_turn_id,
                )
            )
        result = self._workspace.write_bundle(
            writes,
            delete_links=deletes,
            expected_delete_digests=delete_digests,
        )
        return WorkspaceMirrorCommit(
            manifest=result.manifest,
            links=tuple(candidate.workspace_link for candidate in diff.candidates),
            changes=diff.candidates,
        )
