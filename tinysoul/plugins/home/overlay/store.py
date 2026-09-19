"""Persistent effective overlay for the mutable Agent Home working copy."""

from __future__ import annotations

from pathlib import Path
import shutil

from ..errors import AgentHomeContractError, AgentHomeIOError, AgentHomeInvariantError


from .models import HomeOverlayState, HomeOverlayManifest, HomeOverlayOperation
from .files import _read_object, _write_object


class HomeOverlayStore:
    def __init__(self, runtime_root: Path) -> None:
        self.runtime_root = runtime_root
        self.metadata_root = runtime_root / ".tinysoul"
        self.manifest_path = self.metadata_root / "home_overlay.json"
        self.operations_root = self.metadata_root / "operations"

    def load(self) -> HomeOverlayManifest | None:
        if not self.manifest_path.exists():
            return None
        value = _read_object(self.manifest_path, label="overlay manifest")
        try:
            manifest = HomeOverlayManifest.from_json(value)
        except AgentHomeContractError as exc:
            raise AgentHomeInvariantError(
                f"Persisted Home overlay manifest is invalid: {exc}"
            ) from exc
        if value.get("schema_version") == 1:
            self.save(manifest)
        return manifest

    def save(self, manifest: HomeOverlayManifest) -> None:
        _write_object(self.manifest_path, manifest.to_json())

    def prepare_operation(
        self,
        operation: HomeOverlayOperation,
        *,
        content: bytes | None,
    ) -> Path:
        if content is None and operation.after.state is not HomeOverlayState.DELETED:
            raise AgentHomeContractError(
                "Active Home operation requires staged content"
            )
        directory = self.operations_root / operation.operation_id
        try:
            directory.mkdir(parents=True, exist_ok=False)
            if content is not None:
                (directory / "after").write_bytes(content)
            _write_object(directory / "operation.json", operation.to_json())
        except OSError as exc:
            raise AgentHomeIOError(f"Failed to prepare Home operation: {exc}") from exc
        return directory

    def operations(self) -> tuple[tuple[HomeOverlayOperation, Path], ...]:
        if not self.operations_root.exists():
            return ()
        result: list[tuple[HomeOverlayOperation, Path]] = []
        for directory in sorted(
            self.operations_root.iterdir(), key=lambda item: item.name
        ):
            if not directory.is_dir():
                raise AgentHomeInvariantError(
                    f"Home operation entry is not a directory: {directory}"
                )
            operation_path = directory / "operation.json"
            if not operation_path.exists():
                self.discard_operation(directory)
                continue
            value = _read_object(operation_path, label="operation")
            try:
                operation = HomeOverlayOperation.from_json(value)
            except AgentHomeContractError as exc:
                raise AgentHomeInvariantError(
                    f"Persisted Home operation is invalid: {exc}"
                ) from exc
            if operation.operation_id != directory.name:
                raise AgentHomeInvariantError(
                    "Home operation directory identity mismatch"
                )
            result.append((operation, directory))
        return tuple(result)

    @staticmethod
    def discard_operation(directory: Path) -> None:
        try:
            shutil.rmtree(directory)
        except OSError as exc:
            raise AgentHomeIOError(f"Failed to finalize Home operation: {exc}") from exc
