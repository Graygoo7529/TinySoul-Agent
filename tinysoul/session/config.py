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
    summary_watermark_ratio: float = 0.60
    summary_target_ratio: float = 0.40
    min_recent_turns: int = 2
    inspect_max_chars: int = 8000

    def __post_init__(self) -> None:
        if not isinstance(self.root, Path):
            raise ConfigError(
                "Session root must be a path",
                key="session.root",
                value=self.root,
                expected="path",
            )
        for name in {"summary_watermark_ratio", "summary_target_ratio"}:
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ConfigError(
                    "Session summary ratio must be numeric",
                    key=f"session.{name}",
                    value=value,
                    expected="float",
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
        if not 0 < self.summary_target_ratio < self.summary_watermark_ratio < 1:
            raise ConfigError(
                "Session summary ratios must satisfy 0 < target < watermark < 1",
                key="session.summary_watermark_ratio",
                value=self.summary_watermark_ratio,
                expected="ordered ratios",
            )
        if (
            isinstance(self.min_recent_turns, bool)
            or not isinstance(self.min_recent_turns, int)
            or self.min_recent_turns < 0
        ):
            raise ConfigError(
                "Session min_recent_turns cannot be negative",
                key="session.min_recent_turns",
                value=self.min_recent_turns,
                expected="non-negative int",
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
            "summary_watermark_ratio",
            "summary_target_ratio",
            "min_recent_turns",
            "inspect_max_chars",
        },
        key="session",
    )
    return SessionSettings(
        root=_path(tree, "root", project_root / "runtime" / "session", project_root),
        background_max_chars=_int(tree, "background_max_chars", 24000),
        summary_watermark_ratio=_float(tree, "summary_watermark_ratio", 0.60),
        summary_target_ratio=_float(tree, "summary_target_ratio", 0.40),
        min_recent_turns=_int(tree, "min_recent_turns", 2),
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


def _float(tree: Mapping[str, object], name: str, default: float) -> float:
    value = tree.get(name, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(
            "Session setting must be numeric",
            key=f"session.{name}",
            value=value,
            expected="float",
        )
    return float(value)
