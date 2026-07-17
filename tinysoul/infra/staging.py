"""Project-scoped staging directories for capability intermediate files."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
import re
import shutil
import tempfile
from threading import RLock

from .filesystem import FilesystemBoundaryError, resolve_under_root


DEFAULT_STAGING_ROOT = "runtime/.staging"
_PREFIX_PATTERN = re.compile(r"^[a-z][a-z0-9_-]*$")


class StagingError(Exception):
    """Raised when project staging cannot be prepared or cleaned."""


class StagingDirectoryManager:
    """Own one reusable project root and isolated per-action child directories."""

    def __init__(
        self,
        project_root: Path,
        *,
        relative_root: str = DEFAULT_STAGING_ROOT,
    ) -> None:
        if not isinstance(project_root, Path):
            raise StagingError("Staging project root must be a Path")
        if not isinstance(relative_root, str) or not relative_root:
            raise StagingError("Staging relative root must be non-empty")
        try:
            self._root = resolve_under_root(project_root, relative_root)
        except FilesystemBoundaryError as exc:
            raise StagingError("Staging root must stay within the project") from exc
        self._lock = RLock()

    @property
    def root(self) -> Path:
        return self._root

    def prepare(self) -> None:
        """Create the root and remove children left by an earlier process."""

        with self._lock:
            try:
                if self._root.exists() and not self._root.is_dir():
                    raise StagingError("Staging root must be a directory")
                self._root.mkdir(parents=True, exist_ok=True)
                for child in self._root.iterdir():
                    _remove(child)
            except StagingError:
                raise
            except OSError as exc:
                raise StagingError("Project staging root could not be prepared") from exc

    @contextmanager
    def allocate(self, prefix: str) -> Iterator[Path]:
        """Yield one unique action directory and remove it on scope exit."""

        directory = self.create(prefix)
        try:
            yield directory
        finally:
            self.cleanup(directory)

    def create(self, prefix: str) -> Path:
        """Create one retained child for work spanning multiple action calls."""

        if not isinstance(prefix, str) or not _PREFIX_PATTERN.fullmatch(prefix):
            raise StagingError("Staging prefix is invalid")
        with self._lock:
            try:
                self._root.mkdir(parents=True, exist_ok=True)
                directory = Path(
                    tempfile.mkdtemp(prefix=f"{prefix}-", dir=self._root)
                )
            except OSError as exc:
                raise StagingError("Action staging directory could not be created") from exc
        return directory

    def cleanup(self, directory: Path) -> None:
        """Remove one child previously created by this manager."""

        if not isinstance(directory, Path):
            raise StagingError("Staging cleanup path must be a Path")
        try:
            resolved = directory.resolve()
            root = self._root.resolve()
        except OSError as exc:
            raise StagingError("Staging cleanup path could not be resolved") from exc
        if resolved.parent != root:
            raise StagingError("Staging cleanup path must be a direct child of the root")
        with self._lock:
            try:
                _remove(resolved)
            except OSError as exc:
                raise StagingError("Action staging directory could not be cleaned") from exc


def _remove(path: Path) -> None:
    if path.is_symlink() or not path.is_dir():
        path.unlink(missing_ok=True)
        return
    shutil.rmtree(path)
