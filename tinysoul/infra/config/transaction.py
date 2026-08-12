"""Atomic multi-file configuration transaction support."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..filesystem import atomic_write_text
from .errors import ConfigError


@dataclass(frozen=True)
class ConfigDocumentWrite:
    path: Path
    text: str


class ConfigTransactionReceipt:
    """Committed file replacements that can still be rolled back."""

    def __init__(self, backups: dict[Path, str | None]) -> None:
        self._backups = dict(backups)
        self._active = True

    def complete(self) -> None:
        self._active = False

    def rollback(self) -> None:
        if not self._active:
            return
        for path, previous in reversed(tuple(self._backups.items())):
            if previous is None:
                path.unlink(missing_ok=True)
            else:
                atomic_write_text(path, previous)
        self._active = False


class ConfigFileTransaction:
    """Stage and replace a bounded set of project configuration files."""

    def __init__(self, root: Path) -> None:
        self._root = root.resolve()

    def commit(
        self,
        writes: tuple[ConfigDocumentWrite, ...],
    ) -> ConfigTransactionReceipt:
        if not writes:
            return ConfigTransactionReceipt({})
        normalized: list[ConfigDocumentWrite] = []
        seen: set[Path] = set()
        for write in writes:
            path = write.path.resolve()
            if path != self._root and self._root not in path.parents:
                raise ConfigError(
                    "Configuration transaction path escapes project root",
                    key="config.transaction",
                    source=str(write.path),
                    expected="path under project root",
                )
            if path in seen:
                raise ConfigError(
                    "Configuration transaction contains duplicate path",
                    key="config.transaction",
                    source=str(write.path),
                )
            seen.add(path)
            normalized.append(ConfigDocumentWrite(path=path, text=write.text))

        backups = {
            write.path: (
                write.path.read_text(encoding="utf-8")
                if write.path.exists()
                else None
            )
            for write in normalized
        }
        committed: list[Path] = []
        try:
            for write in normalized:
                atomic_write_text(write.path, write.text)
                committed.append(write.path)
        except Exception:
            for path in reversed(committed):
                previous = backups[path]
                if previous is None:
                    path.unlink(missing_ok=True)
                else:
                    atomic_write_text(path, previous)
            raise
        return ConfigTransactionReceipt(backups)
