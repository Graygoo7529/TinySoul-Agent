"""Memory module configuration parsing."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

from tinysoul.infra.config import ConfigError, reject_unknown_keys


DEFAULT_MAX_DOCUMENT_CHARS = 16000
DEFAULT_SEARCH_CANDIDATE_LIMIT = 20
DEFAULT_SEARCH_TOP_K = 5
DEFAULT_SEARCH_MAX_TOP_K = 10
DEFAULT_SEARCH_SUMMARY_MAX_CHARS = 320
DEFAULT_CONSOLIDATION_CHUNK_MAX_CHARS = 12000
DEFAULT_CONSOLIDATION_SOURCE_MAX_CHARS = 240000
DEFAULT_CONSOLIDATION_LINK_HINTS_MAX_CHARS = 4096
DEFAULT_CONSOLIDATION_MAX_CALLS = 48
DEFAULT_CONSOLIDATION_VALIDATION_RETRIES = 2


@dataclass(frozen=True)
class MemorySearchSettings:
    candidate_limit: int = DEFAULT_SEARCH_CANDIDATE_LIMIT
    default_top_k: int = DEFAULT_SEARCH_TOP_K
    max_top_k: int = DEFAULT_SEARCH_MAX_TOP_K
    summary_max_chars: int = DEFAULT_SEARCH_SUMMARY_MAX_CHARS

    def __post_init__(self) -> None:
        for name in (
            "candidate_limit",
            "default_top_k",
            "max_top_k",
            "summary_max_chars",
        ):
            _positive_setting(getattr(self, name), key=f"memory.search.{name}")
        if self.default_top_k > self.max_top_k:
            raise ConfigError(
                "Memory search default_top_k cannot exceed max_top_k",
                key="memory.search.default_top_k",
                value=self.default_top_k,
                expected="int <= max_top_k",
            )
        if self.max_top_k > self.candidate_limit:
            raise ConfigError(
                "Memory search max_top_k cannot exceed candidate_limit",
                key="memory.search.max_top_k",
                value=self.max_top_k,
                expected="int <= candidate_limit",
            )


@dataclass(frozen=True)
class MemoryConsolidationSettings:
    chunk_max_chars: int = DEFAULT_CONSOLIDATION_CHUNK_MAX_CHARS
    source_max_chars: int = DEFAULT_CONSOLIDATION_SOURCE_MAX_CHARS
    link_hints_max_chars: int = DEFAULT_CONSOLIDATION_LINK_HINTS_MAX_CHARS
    max_calls: int = DEFAULT_CONSOLIDATION_MAX_CALLS
    validation_retries: int = DEFAULT_CONSOLIDATION_VALIDATION_RETRIES

    def __post_init__(self) -> None:
        for name in (
            "chunk_max_chars",
            "source_max_chars",
            "link_hints_max_chars",
            "max_calls",
        ):
            _positive_setting(
                getattr(self, name),
                key=f"memory.consolidation.{name}",
            )
        if self.chunk_max_chars < 512:
            raise ConfigError(
                "Memory consolidation chunk budget is too small",
                key="memory.consolidation.chunk_max_chars",
                value=self.chunk_max_chars,
                expected="int >= 512",
            )
        if self.source_max_chars < self.chunk_max_chars:
            raise ConfigError(
                "Memory consolidation source budget must cover one chunk",
                key="memory.consolidation.source_max_chars",
                value=self.source_max_chars,
                expected="int >= chunk_max_chars",
            )
        if self.max_calls < 2:
            raise ConfigError(
                "Memory consolidation call budget must allow reduce and final calls",
                key="memory.consolidation.max_calls",
                value=self.max_calls,
                expected="int >= 2",
            )
        if (
            isinstance(self.validation_retries, bool)
            or not isinstance(self.validation_retries, int)
            or self.validation_retries < 0
        ):
            raise ConfigError(
                "Memory consolidation validation retries cannot be negative",
                key="memory.consolidation.validation_retries",
                value=self.validation_retries,
                expected="non-negative int",
            )


@dataclass(frozen=True)
class MemorySettings:
    root: Path
    max_document_chars: int = DEFAULT_MAX_DOCUMENT_CHARS
    search: MemorySearchSettings = field(default_factory=MemorySearchSettings)
    consolidation: MemoryConsolidationSettings = field(
        default_factory=MemoryConsolidationSettings
    )

    def __post_init__(self) -> None:
        if not isinstance(self.root, Path):
            raise ConfigError(
                "Memory root must be a path",
                key="memory.root",
                value=self.root,
                expected="path",
            )
        _positive_setting(
            self.max_document_chars,
            key="memory.max_document_chars",
        )
        if not isinstance(self.search, MemorySearchSettings):
            raise ConfigError(
                "Memory search settings are invalid",
                key="memory.search",
                value=type(self.search).__name__,
                expected="MemorySearchSettings",
            )
        if not isinstance(self.consolidation, MemoryConsolidationSettings):
            raise ConfigError(
                "Memory consolidation settings are invalid",
                key="memory.consolidation",
                value=type(self.consolidation).__name__,
                expected="MemoryConsolidationSettings",
            )


def parse_memory_settings(
    tree: Mapping[str, object],
    *,
    project_root: Path,
) -> MemorySettings:
    reject_unknown_keys(
        tree,
        {"root", "max_document_chars", "search", "consolidation"},
        key="memory",
    )
    root = _path(tree.get("root"), default=project_root / "memory")
    return MemorySettings(
        root=root,
        max_document_chars=_int(
            tree,
            "max_document_chars",
            DEFAULT_MAX_DOCUMENT_CHARS,
            prefix="memory",
        ),
        search=_parse_search(tree.get("search")),
        consolidation=_parse_consolidation(tree.get("consolidation")),
    )


def _parse_search(value: object) -> MemorySearchSettings:
    tree = _table(value, key="memory.search")
    reject_unknown_keys(
        tree,
        {"candidate_limit", "default_top_k", "max_top_k", "summary_max_chars"},
        key="memory.search",
    )
    return MemorySearchSettings(
        candidate_limit=_int(tree, "candidate_limit", DEFAULT_SEARCH_CANDIDATE_LIMIT, prefix="memory.search"),
        default_top_k=_int(tree, "default_top_k", DEFAULT_SEARCH_TOP_K, prefix="memory.search"),
        max_top_k=_int(tree, "max_top_k", DEFAULT_SEARCH_MAX_TOP_K, prefix="memory.search"),
        summary_max_chars=_int(tree, "summary_max_chars", DEFAULT_SEARCH_SUMMARY_MAX_CHARS, prefix="memory.search"),
    )


def _parse_consolidation(value: object) -> MemoryConsolidationSettings:
    tree = _table(value, key="memory.consolidation")
    reject_unknown_keys(
        tree,
        {
            "chunk_max_chars",
            "source_max_chars",
            "link_hints_max_chars",
            "max_calls",
            "validation_retries",
        },
        key="memory.consolidation",
    )
    return MemoryConsolidationSettings(
        chunk_max_chars=_int(tree, "chunk_max_chars", DEFAULT_CONSOLIDATION_CHUNK_MAX_CHARS, prefix="memory.consolidation"),
        source_max_chars=_int(tree, "source_max_chars", DEFAULT_CONSOLIDATION_SOURCE_MAX_CHARS, prefix="memory.consolidation"),
        link_hints_max_chars=_int(tree, "link_hints_max_chars", DEFAULT_CONSOLIDATION_LINK_HINTS_MAX_CHARS, prefix="memory.consolidation"),
        max_calls=_int(tree, "max_calls", DEFAULT_CONSOLIDATION_MAX_CALLS, prefix="memory.consolidation"),
        validation_retries=_int(tree, "validation_retries", DEFAULT_CONSOLIDATION_VALIDATION_RETRIES, prefix="memory.consolidation"),
    )


def _table(value: object, *, key: str) -> Mapping[str, object]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ConfigError(
            "Memory configuration value must be a table",
            key=key,
            value=value,
            expected="table",
        )
    return cast(Mapping[str, object], value)


def _path(value: object, *, default: Path) -> Path:
    if value is None:
        return default
    if not isinstance(value, str) or not value:
        raise ConfigError(
            "Memory root must be a non-empty path string",
            key="memory.root",
            value=value,
            expected="str",
        )
    path = Path(value)
    if path.is_absolute():
        return path
    project_root = default.parent.resolve()
    candidate = (project_root / path).resolve()
    if candidate == project_root or project_root not in candidate.parents:
        raise ConfigError(
            "Relative Memory root must stay inside the project root",
            key="memory.root",
            value=value,
            expected="relative path under project root",
        )
    return project_root / path


def _int(
    tree: Mapping[str, object],
    name: str,
    default: int,
    *,
    prefix: str,
) -> int:
    value = tree.get(name, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(
            "Memory configuration value must be an integer",
            key=f"{prefix}.{name}",
            value=value,
            expected="int",
        )
    return value


def _positive_setting(value: object, *, key: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ConfigError(
            "Memory setting must be positive",
            key=key,
            value=value,
            expected="positive int",
        )
