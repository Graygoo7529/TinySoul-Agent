"""Agent Home configuration parsing."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

from tinysoul.infra.config import ConfigError, reject_unknown_keys

DEFAULT_MAX_READ_CHARS = 4000
DEFAULT_MAX_WRITE_CHARS = 16000
DEFAULT_SEARCH_CANDIDATE_LIMIT = 20
DEFAULT_SEARCH_TOP_K = 5
DEFAULT_SEARCH_MAX_TOP_K = 10
DEFAULT_SEARCH_PREFIX_MAX_CHARS = 1200
DEFAULT_SEARCH_SUMMARY_MAX_CHARS = 320


@dataclass(frozen=True)
class HomeSearchSettings:
    """Bounded effective Home top search settings."""

    candidate_limit: int = DEFAULT_SEARCH_CANDIDATE_LIMIT
    default_top_k: int = DEFAULT_SEARCH_TOP_K
    max_top_k: int = DEFAULT_SEARCH_MAX_TOP_K
    prefix_max_chars: int = DEFAULT_SEARCH_PREFIX_MAX_CHARS
    summary_max_chars: int = DEFAULT_SEARCH_SUMMARY_MAX_CHARS

    def __post_init__(self) -> None:
        for name in (
            "candidate_limit",
            "default_top_k",
            "max_top_k",
            "prefix_max_chars",
            "summary_max_chars",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ConfigError(
                    "Agent Home search setting must be positive",
                    key=f"home.search.{name}",
                    value=value,
                    expected="positive int",
                )
        if self.default_top_k > self.max_top_k:
            raise ConfigError(
                "Agent Home search default_top_k cannot exceed max_top_k",
                key="home.search.default_top_k",
                value=self.default_top_k,
                expected="int <= max_top_k",
            )
        if self.max_top_k > self.candidate_limit:
            raise ConfigError(
                "Agent Home search max_top_k cannot exceed candidate_limit",
                key="home.search.max_top_k",
                value=self.max_top_k,
                expected="int <= candidate_limit",
            )
        if self.prefix_max_chars < 128:
            raise ConfigError(
                "Agent Home search prefix budget is too small",
                key="home.search.prefix_max_chars",
                value=self.prefix_max_chars,
                expected="int >= 128",
            )
        if self.summary_max_chars > self.prefix_max_chars:
            raise ConfigError(
                "Agent Home search summary budget cannot exceed prefix budget",
                key="home.search.summary_max_chars",
                value=self.summary_max_chars,
                expected="int <= prefix_max_chars",
            )


@dataclass(frozen=True)
class AgentHomeSettings:
    """Agent Home module settings."""

    original_root: Path
    runtime_root: Path
    max_read_chars: int = DEFAULT_MAX_READ_CHARS
    max_write_chars: int = DEFAULT_MAX_WRITE_CHARS
    search: HomeSearchSettings = field(default_factory=HomeSearchSettings)

    def __post_init__(self) -> None:
        if not isinstance(self.original_root, Path):
            raise ConfigError(
                "Agent Home root must be a path",
                key="home.root",
                value=self.original_root,
                expected="path",
            )
        if not isinstance(self.runtime_root, Path):
            raise ConfigError(
                "Agent Home runtime_root must be a path",
                key="home.runtime_root",
                value=self.runtime_root,
                expected="path",
            )
        original_root = self.original_root.resolve()
        runtime_root = self.runtime_root.resolve()
        if (
            original_root == runtime_root
            or original_root in runtime_root.parents
            or runtime_root in original_root.parents
        ):
            raise ConfigError(
                "Agent Home original and runtime roots must not overlap",
                key="home.runtime_root",
                value=str(self.runtime_root),
                expected="non-overlapping path",
            )
        if (
            isinstance(self.max_read_chars, bool)
            or not isinstance(self.max_read_chars, int)
            or self.max_read_chars <= 0
        ):
            raise ConfigError(
                "Agent Home max_read_chars must be positive",
                key="home.max_read_chars",
                value=self.max_read_chars,
                expected="positive int",
            )
        if not isinstance(self.search, HomeSearchSettings):
            raise ConfigError(
                "Agent Home search settings are invalid",
                key="home.search",
                value=type(self.search).__name__,
                expected="HomeSearchSettings",
            )
        if (
            isinstance(self.max_write_chars, bool)
            or not isinstance(self.max_write_chars, int)
            or self.max_write_chars <= 0
        ):
            raise ConfigError(
                "Agent Home max_write_chars must be positive",
                key="home.max_write_chars",
                value=self.max_write_chars,
                expected="positive int",
            )


def parse_agent_home_settings(
    tree: Mapping[str, object],
    *,
    project_root: Path,
) -> AgentHomeSettings:
    reject_unknown_keys(
        tree,
        {
            "root",
            "runtime_root",
            "max_read_chars",
            "max_write_chars",
            "search",
        },
        key="home",
    )
    original_root = _optional_path(
        tree,
        "root",
        default=project_root / "home",
        project_root=project_root,
    )
    return AgentHomeSettings(
        original_root=original_root,
        runtime_root=_optional_path(
            tree,
            "runtime_root",
            default=project_root / "runtime" / "home",
            project_root=project_root,
        ),
        max_read_chars=_optional_int(
            tree,
            "max_read_chars",
            default=DEFAULT_MAX_READ_CHARS,
        ),
        max_write_chars=_optional_int(
            tree,
            "max_write_chars",
            default=DEFAULT_MAX_WRITE_CHARS,
        ),
        search=_parse_search_settings(tree.get("search")),
    )


def _parse_search_settings(value: object) -> HomeSearchSettings:
    if value is None:
        return HomeSearchSettings()
    if not isinstance(value, Mapping):
        raise ConfigError(
            "Agent Home search configuration must be a table",
            key="home.search",
            value=value,
            expected="table",
        )
    tree = cast(Mapping[str, object], value)
    reject_unknown_keys(
        tree,
        {
            "candidate_limit",
            "default_top_k",
            "max_top_k",
            "prefix_max_chars",
            "summary_max_chars",
        },
        key="home.search",
    )
    return HomeSearchSettings(
        candidate_limit=_search_int(
            tree,
            "candidate_limit",
            DEFAULT_SEARCH_CANDIDATE_LIMIT,
        ),
        default_top_k=_search_int(tree, "default_top_k", DEFAULT_SEARCH_TOP_K),
        max_top_k=_search_int(tree, "max_top_k", DEFAULT_SEARCH_MAX_TOP_K),
        prefix_max_chars=_search_int(
            tree,
            "prefix_max_chars",
            DEFAULT_SEARCH_PREFIX_MAX_CHARS,
        ),
        summary_max_chars=_search_int(
            tree,
            "summary_max_chars",
            DEFAULT_SEARCH_SUMMARY_MAX_CHARS,
        ),
    )


def _optional_path(
    tree: Mapping[str, object],
    name: str,
    *,
    default: Path,
    project_root: Path,
) -> Path:
    value = tree.get(name)
    if value is None:
        return default
    if not isinstance(value, str) or not value:
        raise ConfigError(
            "Agent Home configuration value must be a non-empty path string",
            key=f"home.{name}",
            value=value,
            expected="str",
        )
    path = Path(value)
    if path.is_absolute():
        return path
    return project_root / path


def _optional_int(
    tree: Mapping[str, object],
    name: str,
    *,
    default: int,
) -> int:
    value = tree.get(name, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(
            "Agent Home configuration value must be an integer",
            key=f"home.{name}",
            value=value,
            expected="int",
        )
    return value


def _search_int(
    tree: Mapping[str, object],
    name: str,
    default: int,
) -> int:
    value = tree.get(name, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(
            "Agent Home search configuration value must be an integer",
            key=f"home.search.{name}",
            value=value,
            expected="int",
        )
    return value
