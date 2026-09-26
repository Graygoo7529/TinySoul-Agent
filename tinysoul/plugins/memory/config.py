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
    page_max_chars: int = 8_000

    def __post_init__(self) -> None:
        _positive(self.page_max_chars, "memory.inspect.page_max_chars")


@dataclass(frozen=True)
class MemorySearchSettings:
    embedding_use: str | None = None
    embedding_cache_max_chars: int = 16_000_000

    def __post_init__(self) -> None:
        _positive(
            self.embedding_cache_max_chars,
            "memory.search.embedding_cache_max_chars",
        )


@dataclass(frozen=True)
class MemorySettings:
    root: Path
    max_active_chars: int = 12_000
    documents: MemoryDocumentSettings = field(default_factory=MemoryDocumentSettings)
    inspect: MemoryInspectSettings = field(default_factory=MemoryInspectSettings)
    search: MemorySearchSettings = field(
        default_factory=MemorySearchSettings
    )

    def __post_init__(self) -> None:
        if not isinstance(self.root, Path):
            raise ConfigError("Memory root must be a path", key="memory.root")
        _positive(self.max_active_chars, "memory.max_active_chars")
        if not isinstance(self.documents, MemoryDocumentSettings):
            raise ConfigError(
                "Memory documents settings are invalid", key="memory.documents"
            )
        if not isinstance(self.inspect, MemoryInspectSettings):
            raise ConfigError(
                "Memory inspect settings are invalid", key="memory.inspect"
            )
        if not isinstance(self.search, MemorySearchSettings):
            raise ConfigError(
                "Memory search settings are invalid",
                key="memory.search",
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
            "search",
        },
        key="memory",
    )
    return MemorySettings(
        root=_path(tree.get("root"), project_root=project_root),
        max_active_chars=_int(tree, "max_active_chars", 12_000, "memory"),
        documents=_parse_documents(tree.get("documents")),
        inspect=_parse_inspect(tree.get("inspect")),
        search=_parse_search(tree.get("search")),
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
    reject_unknown_keys(tree, {"page_max_chars"}, key="memory.inspect")
    return MemoryInspectSettings(_int(tree, "page_max_chars", 8_000, "memory.inspect"))


def _parse_search(value: object) -> MemorySearchSettings:
    tree = _table(value, "memory.search")
    reject_unknown_keys(
        tree,
        {"embedding_cache_max_chars", "embedding_use"},
        key="memory.search",
    )
    defaults = MemorySearchSettings()
    use = tree.get("embedding_use")
    if use is not None and (not isinstance(use, str) or not use.strip()):
        raise ConfigError(
            "Memory embedding_use must name a logical use",
            key="memory.search.embedding_use",
        )
    return MemorySearchSettings(
        embedding_use=use,
        embedding_cache_max_chars=_int(
            tree,
            "embedding_cache_max_chars",
            defaults.embedding_cache_max_chars,
            "memory.search",
        ),
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
