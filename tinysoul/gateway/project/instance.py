"""Project-scoped application instance lease."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import os
from pathlib import Path
import sys
from types import TracebackType
from typing import BinaryIO
from uuid import uuid4

from ..errors import ProjectInstanceError


@dataclass(frozen=True)
class ProjectInstanceIdentity:
    """Stable project identity plus one process-local instance identity."""

    project_root: Path
    project_identity: str
    instance_id: str


class ProjectInstanceLease:
    """Hold the single-process project lease and process identity."""

    def __init__(self, project_root: Path, *, directory: Path | None = None) -> None:
        root = project_root.resolve()
        project_identity = project_identity_for(root)
        self.identity = ProjectInstanceIdentity(
            project_root=root,
            project_identity=project_identity,
            instance_id=f"instance_{uuid4().hex}",
        )
        self._directory = directory or instance_directory()
        self._lock_path = self._directory / f"{project_identity}.lock"
        self._lock_file: BinaryIO | None = None

    def __enter__(self) -> "ProjectInstanceLease":
        self._directory.mkdir(parents=True, exist_ok=True)
        lock_file = self._lock_path.open("a+b")
        try:
            _lock_exclusive(lock_file)
        except OSError as exc:
            lock_file.close()
            raise ProjectInstanceError(
                "TinySoul is already running for this project"
            ) from exc
        self._lock_file = lock_file
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        lock_file = self._lock_file
        if lock_file is None:
            return
        self._lock_file = None
        try:
            _unlock(lock_file)
        finally:
            lock_file.close()


def project_identity_for(project_root: Path) -> str:
    """Return the cross-process identity for one canonical project root."""

    value = os.path.normcase(str(project_root.resolve()))
    return sha256(value.encode("utf-8")).hexdigest()


def instance_directory() -> Path:
    """Return the current-user directory used for process lock files."""

    override = os.environ.get("TINYSOUL_INSTANCE_DIR", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA", "").strip()
        if base:
            return Path(base) / "TinySoul" / "instances"
    runtime = os.environ.get("XDG_RUNTIME_DIR", "").strip()
    if runtime:
        return Path(runtime) / "tinysoul" / "instances"
    if sys.platform == "darwin":
        return (
            Path.home() / "Library" / "Application Support" / "TinySoul" / "instances"
        )
    return Path.home() / ".local" / "state" / "tinysoul" / "instances"


def _lock_exclusive(file: BinaryIO) -> None:
    file.seek(0)
    if os.name == "nt":
        import msvcrt

        if file.read(1) == b"":
            file.seek(0)
            file.write(b"0")
            file.flush()
        file.seek(0)
        msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)
        return
    import fcntl

    fcntl.flock(file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock(file: BinaryIO) -> None:
    file.seek(0)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(file.fileno(), msvcrt.LK_UNLCK, 1)
        return
    import fcntl

    fcntl.flock(file.fileno(), fcntl.LOCK_UN)
