"""Memory module configuration parsing."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

from tinysoul.infra.config import ConfigError, reject_unknown_keys


@dataclass(frozen=True)
class MemoryDocumentSettings:
    daily_max_chars: int = 32_000
    entity_max_chars: int = 16_000
    concept_max_chars: int = 16_000
    fact_max_chars: int = 4_000
    note_max_chars: int = 24_000
    redirect_max_hops: int = 8

    def __post_init__(self) -> None:
        for name in (
            "daily_max_chars",
            "entity_max_chars",
            "concept_max_chars",
            "fact_max_chars",
            "note_max_chars",
            "redirect_max_hops",
        ):
            _positive(getattr(self, name), f"memory.documents.{name}")


@dataclass(frozen=True)
class MemoryInspectSettings:
    candidate_limit: int = 40
    default_top_k: int = 8
    max_top_k: int = 20
    summary_max_chars: int = 480
    page_max_chars: int = 8_000

    def __post_init__(self) -> None:
        for name in (
            "candidate_limit",
            "default_top_k",
            "max_top_k",
            "summary_max_chars",
            "page_max_chars",
        ):
            _positive(getattr(self, name), f"memory.inspect.{name}")
        if self.default_top_k > self.max_top_k:
            raise ConfigError(
                "Memory inspect default_top_k cannot exceed max_top_k",
                key="memory.inspect.default_top_k",
            )
        if self.max_top_k > self.candidate_limit:
            raise ConfigError(
                "Memory inspect max_top_k cannot exceed candidate_limit",
                key="memory.inspect.max_top_k",
            )
        if self.page_max_chars < self.summary_max_chars + 512:
            raise ConfigError(
                "Memory inspect page_max_chars must fit one result",
                key="memory.inspect.page_max_chars",
            )


@dataclass(frozen=True)
class MemorySemanticSearchSettings:
    embedding_cache_max_chars: int = 16_000_000

    def __post_init__(self) -> None:
        _positive(
            self.embedding_cache_max_chars,
            "memory.semantic_search.embedding_cache_max_chars",
        )


@dataclass(frozen=True)
class MemoryDailyCompositionSettings:
    chunk_max_chars: int = 12_000
    source_max_chars: int = 240_000
    max_calls: int = 48
    validation_retries: int = 2

    def __post_init__(self) -> None:
        for name in ("chunk_max_chars", "source_max_chars", "max_calls"):
            _positive(getattr(self, name), f"memory.daily_composition.{name}")
        if self.source_max_chars < self.chunk_max_chars:
            raise ConfigError(
                "Memory daily source budget must cover one chunk",
                key="memory.daily_composition.source_max_chars",
            )
        if (
            isinstance(self.validation_retries, bool)
            or not isinstance(self.validation_retries, int)
            or self.validation_retries < 0
        ):
            raise ConfigError(
                "Memory daily validation_retries cannot be negative",
                key="memory.daily_composition.validation_retries",
            )


@dataclass(frozen=True)
class MemorySettings:
    root: Path
    max_active_chars: int = 12_000
    documents: MemoryDocumentSettings = field(default_factory=MemoryDocumentSettings)
    inspect: MemoryInspectSettings = field(default_factory=MemoryInspectSettings)
    semantic_search: MemorySemanticSearchSettings = field(
        default_factory=MemorySemanticSearchSettings
    )
    daily_composition: MemoryDailyCompositionSettings = field(
        default_factory=MemoryDailyCompositionSettings
    )

    def __post_init__(self) -> None:
        if not isinstance(self.root, Path):
            raise ConfigError("Memory root must be a path", key="memory.root")
        _positive(self.max_active_chars, "memory.max_active_chars")
        if not isinstance(self.documents, MemoryDocumentSettings):
            raise ConfigError("Memory documents settings are invalid", key="memory.documents")
        if not isinstance(self.inspect, MemoryInspectSettings):
            raise ConfigError("Memory inspect settings are invalid", key="memory.inspect")
        if not isinstance(self.semantic_search, MemorySemanticSearchSettings):
            raise ConfigError(
                "Memory semantic search settings are invalid",
                key="memory.semantic_search",
            )
        if not isinstance(self.daily_composition, MemoryDailyCompositionSettings):
            raise ConfigError(
                "Memory daily composition settings are invalid",
                key="memory.daily_composition",
            )


def parse_memory_settings(
    tree: Mapping[str, object],
    *,
    project_root: Path,
) -> MemorySettings:
    reject_unknown_keys(
        tree,
        {
            "root",
            "max_active_chars",
            "documents",
            "inspect",
            "semantic_search",
            "daily_composition",
        },
        key="memory",
    )
    return MemorySettings(
        root=_path(tree.get("root"), project_root=project_root),
        max_active_chars=_int(tree, "max_active_chars", 12_000, "memory"),
        documents=_parse_documents(tree.get("documents")),
        inspect=_parse_inspect(tree.get("inspect")),
        semantic_search=_parse_semantic_search(tree.get("semantic_search")),
        daily_composition=_parse_daily(tree.get("daily_composition")),
    )


def _parse_documents(value: object) -> MemoryDocumentSettings:
    tree = _table(value, "memory.documents")
    names = {
        "daily_max_chars",
        "entity_max_chars",
        "concept_max_chars",
        "fact_max_chars",
        "note_max_chars",
        "redirect_max_hops",
    }
    reject_unknown_keys(tree, names, key="memory.documents")
    defaults = MemoryDocumentSettings()
    return MemoryDocumentSettings(
        **{
            name: _int(tree, name, getattr(defaults, name), "memory.documents")
            for name in names
        }
    )


def _parse_inspect(value: object) -> MemoryInspectSettings:
    tree = _table(value, "memory.inspect")
    names = {
        "candidate_limit",
        "default_top_k",
        "max_top_k",
        "summary_max_chars",
        "page_max_chars",
    }
    reject_unknown_keys(tree, names, key="memory.inspect")
    defaults = MemoryInspectSettings()
    return MemoryInspectSettings(
        **{
            name: _int(tree, name, getattr(defaults, name), "memory.inspect")
            for name in names
        }
    )


def _parse_semantic_search(value: object) -> MemorySemanticSearchSettings:
    tree = _table(value, "memory.semantic_search")
    reject_unknown_keys(
        tree,
        {"embedding_cache_max_chars"},
        key="memory.semantic_search",
    )
    defaults = MemorySemanticSearchSettings()
    return MemorySemanticSearchSettings(
        embedding_cache_max_chars=_int(
            tree,
            "embedding_cache_max_chars",
            defaults.embedding_cache_max_chars,
            "memory.semantic_search",
        )
    )


def _parse_daily(value: object) -> MemoryDailyCompositionSettings:
    tree = _table(value, "memory.daily_composition")
    names = {"chunk_max_chars", "source_max_chars", "max_calls", "validation_retries"}
    reject_unknown_keys(tree, names, key="memory.daily_composition")
    defaults = MemoryDailyCompositionSettings()
    return MemoryDailyCompositionSettings(
        **{
            name: _int(tree, name, getattr(defaults, name), "memory.daily_composition")
            for name in names
        }
    )


def _table(value: object, key: str) -> Mapping[str, object]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ConfigError("Memory configuration value must be a table", key=key)
    return cast(Mapping[str, object], value)


def _path(value: object, *, project_root: Path) -> Path:
    if value is None:
        return project_root / "memory"
    if not isinstance(value, str) or not value:
        raise ConfigError("Memory root must be non-empty text", key="memory.root")
    path = Path(value)
    if path.is_absolute():
        return path
    candidate = (project_root / path).resolve()
    root = project_root.resolve()
    if candidate == root or root not in candidate.parents:
        raise ConfigError(
            "Relative Memory root must stay inside the project root",
            key="memory.root",
        )
    return candidate


def _int(tree: Mapping[str, object], name: str, default: int, prefix: str) -> int:
    value = tree.get(name, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(
            "Memory configuration value must be an integer",
            key=f"{prefix}.{name}",
        )
    return value


def _positive(value: object, key: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ConfigError("Memory setting must be positive", key=key)
