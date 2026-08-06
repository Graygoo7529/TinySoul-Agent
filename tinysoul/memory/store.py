"""Filesystem store for strict persistent Memory Markdown documents."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from tinysoul.infra.filesystem import atomic_write_text, read_text_prefix

from .config import MemoryDocumentSettings
from .documents import (
    MemoryDocumentCodec,
    PersistentMemoryDocument,
    StoredMemoryDocument,
)
from .errors import MemoryContractError, MemoryIOError, MemoryInvariantError
from .links import MemoryKind, MemoryLink


class MemoryStore:
    """Read and atomically replace owner-validated Memory documents."""

    def __init__(
        self,
        *,
        root: Path,
        settings: MemoryDocumentSettings,
        codec: MemoryDocumentCodec | None = None,
    ) -> None:
        if not isinstance(root, Path):
            raise MemoryContractError("Memory store root must be a path")
        if not isinstance(settings, MemoryDocumentSettings):
            raise MemoryContractError("Memory document settings are invalid")
        self._root = root
        self._settings = settings
        self._codec = codec or MemoryDocumentCodec()
        self._validate_root()

    @property
    def root(self) -> Path:
        return self._root

    @property
    def internal_root(self) -> Path:
        return self._root / ".tinysoul"

    @property
    def codec(self) -> MemoryDocumentCodec:
        return self._codec

    def exists(self, link: MemoryLink) -> bool:
        path = self.path_for(link)
        _regular_or_missing(path, owner="Memory document")
        return path.is_file()

    def links(self) -> tuple[MemoryLink, ...]:
        return tuple(sorted(self.iter_links(), key=str))

    def iter_links(self) -> Iterator[MemoryLink]:
        self._validate_root()
        if not self._root.exists():
            return
        allowed_roots = {kind.value for kind in MemoryKind}
        try:
            for child in self._root.iterdir():
                if child.name == ".tinysoul":
                    _directory_no_symlink(child, owner="Memory internal root")
                    continue
                if child.name not in allowed_roots:
                    raise MemoryInvariantError(
                        f"Memory store contains an unknown root entry: {child.name}"
                    )
                _directory_no_symlink(child, owner="Memory kind root")
                for path in child.rglob("*"):
                    if path.is_symlink():
                        raise MemoryInvariantError(
                            f"Memory store cannot contain symlinks: {path.name}"
                        )
                    if path.is_dir():
                        continue
                    if not path.is_file():
                        raise MemoryInvariantError(
                            "Memory store entry is not a regular file"
                        )
                    relative = path.relative_to(self._root).as_posix()
                    try:
                        yield MemoryLink.from_relative(relative)
                    except MemoryContractError as exc:
                        raise MemoryInvariantError(
                            f"Memory store contains an invalid path: {relative}"
                        ) from exc
        except OSError as exc:
            raise MemoryIOError(f"Failed to scan Memory root: {exc}") from exc

    def read(self, link: MemoryLink) -> StoredMemoryDocument:
        if not isinstance(link, MemoryLink):
            raise MemoryContractError("Memory read requires a MemoryLink")
        path = self.path_for(link)
        if not self.exists(link):
            raise MemoryContractError(f"Memory does not exist: {link}")
        try:
            read = read_text_prefix(path, max_chars=self.max_chars(link.kind))
        except UnicodeDecodeError as exc:
            raise MemoryInvariantError(f"Memory is not UTF-8 text: {link}") from exc
        except OSError as exc:
            raise MemoryIOError(f"Failed to read Memory {link}: {exc}") from exc
        if read.truncated:
            raise MemoryInvariantError(
                f"Memory exceeds {self.max_chars(link.kind)} characters: {link}"
            )
        try:
            document = self._codec.parse(link, read.text)
        except MemoryContractError as exc:
            raise MemoryInvariantError(f"Invalid Memory document {link}: {exc}") from exc
        # Digest the decoded text as read, rather than a canonical re-render, so
        # externally changed frontmatter ordering and spacing remain CAS-visible.
        from hashlib import sha256

        return StoredMemoryDocument(
            document=document,
            text=read.text,
            digest=sha256(read.text.encode("utf-8")).hexdigest(),
        )

    def write(
        self,
        document: PersistentMemoryDocument,
        *,
        expected_digest: str | None = None,
        expected_absent: bool = False,
    ) -> StoredMemoryDocument:
        stored = self._codec.stored(document)
        if len(stored.text) > self.max_chars(document.kind):
            raise MemoryContractError(
                f"Memory exceeds {self.max_chars(document.kind)} characters: {document.link}"
            )
        path = self.validate_write_target(document.link)
        exists = path.is_file()
        if expected_absent and exists:
            raise MemoryContractError(f"Memory already exists: {document.link}")
        if expected_digest is not None:
            if not exists:
                raise MemoryContractError(f"Memory disappeared: {document.link}")
            current = self.read(document.link)
            if current.digest != expected_digest:
                raise MemoryContractError(f"Memory digest is stale: {document.link}")
        try:
            atomic_write_text(path, stored.text)
        except OSError as exc:
            raise MemoryIOError(f"Failed to write Memory {document.link}: {exc}") from exc
        return stored

    def validate_write_target(self, link: MemoryLink) -> Path:
        """Return an owner-validated target for Store and transaction writes."""

        self._validate_root()
        path = self.path_for(link)
        self._validate_write_path(path)
        return path

    def path_for(self, link: MemoryLink) -> Path:
        if not isinstance(link, MemoryLink):
            raise MemoryContractError("Memory store requires a MemoryLink")
        path = self._root.joinpath(*link.relative_path.split("/"))
        root = self._root.resolve()
        resolved = path.resolve()
        if root not in resolved.parents:
            raise MemoryInvariantError("Memory path escapes the configured root")
        return path

    def max_chars(self, kind: MemoryKind) -> int:
        return {
            MemoryKind.DAILY: self._settings.daily_max_chars,
            MemoryKind.ENTITY: self._settings.entity_max_chars,
            MemoryKind.CONCEPT: self._settings.concept_max_chars,
            MemoryKind.FACT: self._settings.fact_max_chars,
            MemoryKind.NOTE: self._settings.note_max_chars,
        }[kind]

    def _validate_root(self) -> None:
        if self._root.is_symlink():
            raise MemoryInvariantError("Memory root cannot be a symlink")
        if self._root.exists() and not self._root.is_dir():
            raise MemoryInvariantError("Memory root must be a directory")

    def _validate_write_path(self, path: Path) -> None:
        root = self._root.absolute()
        current = path.absolute()
        while current != root:
            if current.is_symlink():
                raise MemoryInvariantError("Memory write path cannot contain symlinks")
            if current.exists() and current == path and not current.is_file():
                raise MemoryInvariantError("Memory target is not a regular file")
            if current.exists() and current != path and not current.is_dir():
                raise MemoryInvariantError("Memory parent is not a directory")
            current = current.parent


def _regular_or_missing(path: Path, *, owner: str) -> None:
    if path.is_symlink():
        raise MemoryInvariantError(f"{owner} cannot be a symlink")
    if path.exists() and not path.is_file():
        raise MemoryInvariantError(f"{owner} path is not a regular file")


def _directory_no_symlink(path: Path, *, owner: str) -> None:
    if path.is_symlink() or not path.is_dir():
        raise MemoryInvariantError(f"{owner} must be a non-symlink directory")
