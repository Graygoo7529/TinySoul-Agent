"""Filesystem store for bounded, date-scoped Memory documents."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from tinysoul.infra.filesystem import atomic_write_text, read_text_prefix

from .errors import MemoryContractError, MemoryIOError, MemoryInvariantError
from .links import MemoryLink


@dataclass(frozen=True)
class MemoryDocument:
    link: MemoryLink
    text: str
    digest: str


class MemoryStore:
    """Read and atomically replace complete Memory documents."""

    def __init__(self, *, root: Path, max_document_chars: int) -> None:
        if not isinstance(root, Path):
            raise MemoryContractError("Memory store root must be a path")
        if (
            isinstance(max_document_chars, bool)
            or not isinstance(max_document_chars, int)
            or max_document_chars <= 0
        ):
            raise MemoryContractError("Memory document limit must be positive")
        self._root = root
        self._max_document_chars = max_document_chars
        self._validate_root()

    @property
    def root(self) -> Path:
        return self._root

    @property
    def max_document_chars(self) -> int:
        return self._max_document_chars

    def exists(self, link: MemoryLink) -> bool:
        path = self.path_for(link)
        if path.is_symlink():
            raise MemoryInvariantError(f"Memory document cannot be a symlink: {path}")
        if path.exists() and not path.is_file():
            raise MemoryInvariantError(
                f"Memory document path is not a regular file: {path}"
            )
        return path.is_file()

    def links(self) -> tuple[MemoryLink, ...]:
        self._validate_root()
        if not self._root.exists():
            return ()
        links: list[MemoryLink] = []
        try:
            paths = tuple(self._root.rglob("*"))
        except OSError as exc:
            raise MemoryIOError(f"Failed to scan Memory root: {exc}") from exc
        for path in paths:
            if path.is_symlink():
                raise MemoryInvariantError(f"Memory store cannot contain symlinks: {path}")
            if path.is_dir():
                continue
            if not path.is_file():
                raise MemoryInvariantError(
                    f"Memory store entry is not a regular file: {path}"
                )
            relative = path.relative_to(self._root).as_posix()
            try:
                links.append(MemoryLink.from_relative(relative))
            except MemoryContractError as exc:
                raise MemoryInvariantError(
                    f"Memory store contains an invalid path: {relative}"
                ) from exc
        if len(links) != len(set(links)):
            raise MemoryInvariantError("Memory store contains duplicate date documents")
        return tuple(sorted(links))

    def read(self, link: MemoryLink) -> MemoryDocument:
        path = self.path_for(link)
        if not self.exists(link):
            raise MemoryContractError(f"Memory does not exist: {link}")
        try:
            read = read_text_prefix(path, max_chars=self._max_document_chars)
        except UnicodeDecodeError as exc:
            raise MemoryInvariantError(f"Memory is not UTF-8 text: {link}") from exc
        except OSError as exc:
            raise MemoryIOError(f"Failed to read Memory {link}: {exc}") from exc
        if read.truncated:
            raise MemoryInvariantError(
                f"Memory exceeds {self._max_document_chars} characters: {link}"
            )
        return MemoryDocument(
            link=link,
            text=read.text,
            digest=sha256(read.text.encode("utf-8")).hexdigest(),
        )

    def write(self, link: MemoryLink, text: str) -> MemoryDocument:
        if not isinstance(text, str) or not text:
            raise MemoryContractError("Memory document must be non-empty text")
        if len(text) > self._max_document_chars:
            raise MemoryContractError(
                f"Memory document exceeds {self._max_document_chars} characters"
            )
        self._validate_root()
        path = self.path_for(link)
        self._validate_write_path(path)
        try:
            atomic_write_text(path, text)
        except OSError as exc:
            raise MemoryIOError(f"Failed to write Memory {link}: {exc}") from exc
        return MemoryDocument(
            link=link,
            text=text,
            digest=sha256(text.encode("utf-8")).hexdigest(),
        )

    def path_for(self, link: MemoryLink) -> Path:
        if not isinstance(link, MemoryLink):
            raise MemoryContractError("Memory store requires a MemoryLink")
        path = self._root.joinpath(*link.relative_path.split("/"))
        root = self._root.resolve()
        resolved = path.resolve()
        if root not in resolved.parents:
            raise MemoryInvariantError("Memory path escapes the configured root")
        return path

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
                raise MemoryInvariantError(
                    f"Memory write path cannot contain symlinks: {current}"
                )
            if current.exists() and current == path and not current.is_file():
                raise MemoryInvariantError(
                    f"Memory target is not a regular file: {current}"
                )
            if current.exists() and current != path and not current.is_dir():
                raise MemoryInvariantError(
                    f"Memory parent is not a directory: {current}"
                )
            current = current.parent
