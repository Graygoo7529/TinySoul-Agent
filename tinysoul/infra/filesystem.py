"""Small filesystem helpers shared by resource modules."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import os
import tempfile


@dataclass(frozen=True)
class TextPrefixRead:
    """A bounded text read result."""

    text: str
    truncated: bool


def resolve_under_root(root: Path, relative_path: str) -> Path:
    """Resolve a relative path and ensure it stays under root."""

    root_resolved = root.resolve()
    candidate = (root_resolved / relative_path).resolve()
    if candidate != root_resolved and root_resolved not in candidate.parents:
        raise FilesystemBoundaryError(
            f"Path escapes root: {relative_path}",
            root=root_resolved,
            path=candidate,
        )
    return candidate


def atomic_write_text(path: Path, text: str, *, encoding: str = "utf-8") -> None:
    """Write text through a temporary file in the same directory."""

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
        text=True,
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding=encoding) as handle:
            handle.write(text)
        os.replace(tmp_path, path)
    except Exception:
        try:
            tmp_path.unlink(missing_ok=True)
        finally:
            raise


def copy_file(source: Path, target: Path) -> None:
    """Copy one file without preserving metadata."""

    target.parent.mkdir(parents=True, exist_ok=True)
    with source.open("rb") as source_handle:
        with target.open("wb") as target_handle:
            while True:
                chunk = source_handle.read(1024 * 1024)
                if not chunk:
                    break
                target_handle.write(chunk)


def read_text_prefix(
    path: Path,
    *,
    max_chars: int,
    encoding: str = "utf-8",
) -> TextPrefixRead:
    """Read at most max_chars characters and report whether content remains."""

    with path.open("r", encoding=encoding) as handle:
        text = handle.read(max_chars + 1)
    truncated = len(text) > max_chars
    if truncated:
        text = text[:max_chars]
    return TextPrefixRead(text=text, truncated=truncated)


def file_digest(path: Path, *, limit_bytes: int | None = None) -> str:
    """Return a sha256 digest for a file, optionally limited to a prefix."""

    digest = sha256()
    remaining = limit_bytes
    with path.open("rb") as handle:
        while True:
            size = 1024 * 1024
            if remaining is not None:
                if remaining <= 0:
                    break
                size = min(size, remaining)
            chunk = handle.read(size)
            if not chunk:
                break
            digest.update(chunk)
            if remaining is not None:
                remaining -= len(chunk)
    return digest.hexdigest()


class FilesystemBoundaryError(Exception):
    """Raised when a path cannot be resolved within the expected root."""

    def __init__(self, message: str, *, root: Path, path: Path) -> None:
        super().__init__(message)
        self.root = root
        self.path = path
