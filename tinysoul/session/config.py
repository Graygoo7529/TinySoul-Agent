"""Session configuration."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from tinysoul.infra.config import ConfigError, reject_unknown_keys
from tinysoul.infra.paging import MIN_JSON_PAGE_CHARS


@dataclass(frozen=True)
class SessionSettings:
    root: Path
    background_max_chars: int = 24000
    summary_watermark_ratio: float = 0.60
    summary_target_ratio: float = 0.40
    min_recent_turns: int = 2
    history_page_max_chars: int = 8000
    history_page_max_entries: int = 50
    actions_page_max_items: int = 50
    background_action_names: tuple[str, ...] = ("core.reason",)
    background_max_actions_per_turn: int = 3

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
            "history_page_max_chars",
            "history_page_max_entries",
            "actions_page_max_items",
            "background_max_actions_per_turn",
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
        if self.history_page_max_chars < MIN_JSON_PAGE_CHARS:
            raise ConfigError(
                "Session history_page_max_chars must leave room for paging metadata",
                key="session.history_page_max_chars",
                value=self.history_page_max_chars,
                expected=f"int >= {MIN_JSON_PAGE_CHARS}",
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
        if not isinstance(self.background_action_names, tuple) or any(
            not isinstance(name, str) or not name
            for name in self.background_action_names
        ):
            raise ConfigError(
                "Session background action names must be non-empty",
                key="session.background_action_names",
                value=self.background_action_names,
                expected="list of non-empty strings",
            )
        if len(set(self.background_action_names)) != len(
            self.background_action_names
        ):
            raise ConfigError(
                "Session background action names must be unique",
                key="session.background_action_names",
                value=self.background_action_names,
                expected="unique strings",
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
            "history_page_max_chars",
            "history_page_max_entries",
            "actions_page_max_items",
            "background_action_names",
            "background_max_actions_per_turn",
        },
        key="session",
    )
    return SessionSettings(
        root=_path(tree, "root", project_root / "runtime" / "session", project_root),
        background_max_chars=_int(tree, "background_max_chars", 24000),
        summary_watermark_ratio=_float(tree, "summary_watermark_ratio", 0.60),
        summary_target_ratio=_float(tree, "summary_target_ratio", 0.40),
        min_recent_turns=_int(tree, "min_recent_turns", 2),
        history_page_max_chars=_int(tree, "history_page_max_chars", 8000),
        history_page_max_entries=_int(tree, "history_page_max_entries", 50),
        actions_page_max_items=_int(tree, "actions_page_max_items", 50),
        background_action_names=_strings(
            tree,
            "background_action_names",
            ("core.reason",),
        ),
        background_max_actions_per_turn=_int(
            tree,
            "background_max_actions_per_turn",
            3,
        ),
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


def _strings(
    tree: Mapping[str, object],
    name: str,
    default: tuple[str, ...],
) -> tuple[str, ...]:
    value = tree.get(name, list(default))
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item for item in value
    ):
        raise ConfigError(
            "Session setting must be a list of non-empty strings",
            key=f"session.{name}",
            value=value,
            expected="list[str]",
        )
    return tuple(item for item in value if isinstance(item, str))
