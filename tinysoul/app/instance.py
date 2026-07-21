"""Project-scoped application instance lease and Endpoint discovery record."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import os
from pathlib import Path
import sys
from types import TracebackType
from typing import BinaryIO
from uuid import uuid4

from tinysoul.endpoint import EndpointReady
from tinysoul.infra import atomic_write_text
from tinysoul.infra.json import JsonObject, dumps_json

from .errors import AppInstanceError


@dataclass(frozen=True)
class AppInstanceIdentity:
    """Stable project identity plus one process-local instance identity."""

    project_root: Path
    project_identity: str
    instance_id: str


class ProjectInstanceLease:
    """Hold the single-process project lease and publish Endpoint discovery."""

    def __init__(self, project_root: Path, *, directory: Path | None = None) -> None:
        root = project_root.resolve()
        project_identity = project_identity_for(root)
        self.identity = AppInstanceIdentity(
            project_root=root,
            project_identity=project_identity,
            instance_id=f"instance_{uuid4().hex}",
        )
        self._directory = directory or instance_directory()
        self._lock_path = self._directory / f"{project_identity}.lock"
        self._record_path = self._directory / f"{project_identity}.json"
        self._lock_file: BinaryIO | None = None

    @property
    def record_path(self) -> Path:
        return self._record_path

    def __enter__(self) -> "ProjectInstanceLease":
        self._directory.mkdir(parents=True, exist_ok=True)
        lock_file = self._lock_path.open("a+b")
        try:
            _lock_exclusive(lock_file)
        except OSError as exc:
            lock_file.close()
            raise AppInstanceError(
                "TinySoul is already running for this project"
            ) from exc
        self._lock_file = lock_file
        self._remove_owned_record()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def publish(self, ready: EndpointReady) -> None:
        if self._lock_file is None:
            raise AppInstanceError("Project instance lease is not active")
        if ready.instance_id != self.identity.instance_id or (
            ready.project_identity != self.identity.project_identity
        ):
            raise AppInstanceError("Endpoint ready identity does not match its lease")
        value: JsonObject = {
            "schema_version": 1,
            "instance_id": ready.instance_id,
            "project_root": str(self.identity.project_root),
            "project_identity": ready.project_identity,
            "pid": os.getpid(),
            "host": ready.host,
            "port": ready.port,
            "token": ready.token,
            "protocol_version": ready.protocol_version,
        }
        atomic_write_text(self._record_path, dumps_json(value) + "\n")

    def close(self) -> None:
        lock_file = self._lock_file
        if lock_file is None:
            return
        self._remove_owned_record()
        self._lock_file = None
        try:
            _unlock(lock_file)
        finally:
            lock_file.close()

    def _remove_owned_record(self) -> None:
        try:
            text = self._record_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return
        except OSError:
            return
        if self.identity.instance_id not in text and self._lock_file is None:
            return
        try:
            self._record_path.unlink()
        except FileNotFoundError:
            pass


def project_identity_for(project_root: Path) -> str:
    """Return the cross-process identity for one canonical project root."""

    value = os.path.normcase(str(project_root.resolve()))
    return sha256(value.encode("utf-8")).hexdigest()


def instance_directory() -> Path:
    """Return the current-user directory used for live instance records."""

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
        return Path.home() / "Library" / "Application Support" / "TinySoul" / "instances"
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
