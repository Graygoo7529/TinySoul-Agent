"""Session configuration."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from tinysoul.infra.config import ConfigError, reject_unknown_keys
from tinysoul.infra.continuation import MIN_CONTINUATION_PAGE_CHARS


@dataclass(frozen=True)
class SessionSettings:
    root: Path
    background_max_chars: int = 24000
    inspect_max_chars: int = 8000

    def __post_init__(self) -> None:
        if not isinstance(self.root, Path):
            raise ConfigError(
                "Session root must be a path",
                key="session.root",
                value=self.root,
                expected="path",
            )
        for name in {
            "background_max_chars",
            "inspect_max_chars",
        }:
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ConfigError(
                    "Session size setting must be positive",
                    key=f"session.{name}",
                    value=value,
                    expected="positive int",
                )
        if self.background_max_chars < 512:
            raise ConfigError(
                "Session background_max_chars must leave room for a recovery head",
                key="session.background_max_chars",
                value=self.background_max_chars,
                expected="int >= 512",
            )
        if self.inspect_max_chars < MIN_CONTINUATION_PAGE_CHARS:
            raise ConfigError(
                "Session inspect_max_chars must leave room for response metadata",
                key="session.inspect_max_chars",
                value=self.inspect_max_chars,
                expected=f"int >= {MIN_CONTINUATION_PAGE_CHARS}",
            )


def parse_session_settings(
    tree: Mapping[str, object],
    *,
    project_root: Path,
) -> SessionSettings:
    reject_unknown_keys(
        tree,
        {
            "root",
            "background_max_chars",
            "inspect_max_chars",
        },
        key="session",
    )
    return SessionSettings(
        root=_path(tree, "root", project_root / "runtime" / "session", project_root),
        background_max_chars=_int(tree, "background_max_chars", 24000),
        inspect_max_chars=_int(tree, "inspect_max_chars", 8000),
    )


def _path(
    tree: Mapping[str, object],
    name: str,
    default: Path,
    project_root: Path,
) -> Path:
    value = tree.get(name)
    if value is None:
        return default
    if not isinstance(value, str) or not value:
        raise ConfigError(
            "Session path must be a non-empty string",
            key=f"session.{name}",
            value=value,
            expected="str",
        )
    path = Path(value)
    return path if path.is_absolute() else project_root / path


def _int(tree: Mapping[str, object], name: str, default: int) -> int:
    value = tree.get(name, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(
            "Session setting must be an integer",
            key=f"session.{name}",
            value=value,
            expected="int",
        )
    return value
