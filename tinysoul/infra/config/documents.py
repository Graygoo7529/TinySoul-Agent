"""Independent project TOML document sets managed by configuration transactions."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

from .errors import ConfigError
from .toml_file import deep_copy_mapping


@dataclass(frozen=True)
class ConfigDocumentSetSpec:
    """One process-owned declaration of independent project TOML documents."""

    set_id: str
    includes: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.set_id, str) or not self.set_id.strip():
            raise ConfigError(
                "Configuration document set id must be non-empty",
                key="config.document_sets.id",
            )
        includes = tuple(self.includes)
        if not includes or any(
            not isinstance(item, str) or not item.strip() for item in includes
        ):
            raise ConfigError(
                "Configuration document set includes must be non-empty strings",
                key=f"config.document_sets.{self.set_id}.include",
                expected="non-empty list[str]",
            )
        object.__setattr__(self, "includes", includes)


@dataclass(frozen=True)
class ConfigDocument:
    """One project TOML document that does not participate in config merging."""

    set_id: str
    source_id: str
    path: Path
    data: Mapping[str, object]

    def __post_init__(self) -> None:
        if not isinstance(self.set_id, str) or not self.set_id.strip():
            raise ConfigError("Configuration document set id must be non-empty")
        if not isinstance(self.source_id, str) or not self.source_id.strip():
            raise ConfigError("Configuration document source id must be non-empty")
        if not isinstance(self.path, Path):
            raise ConfigError("Configuration document path must be a Path")
        object.__setattr__(self, "data", deep_copy_mapping(self.data))

    def copy_data(self) -> dict[str, object]:
        return deep_copy_mapping(self.data)


@dataclass(frozen=True)
class ConfigDocumentSet:
    """An immutable named collection of independent configuration documents."""

    set_id: str
    documents: tuple[ConfigDocument, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.set_id, str) or not self.set_id.strip():
            raise ConfigError("Configuration document set id must be non-empty")
        documents = tuple(self.documents)
        if any(item.set_id != self.set_id for item in documents):
            raise ConfigError(
                "Configuration document belongs to another set",
                key=self.set_id,
            )
        source_ids = tuple(item.source_id for item in documents)
        if len(source_ids) != len(set(source_ids)):
            raise ConfigError(
                "Configuration document source ids must be unique",
                key=self.set_id,
            )
        paths = tuple(item.path.resolve() for item in documents)
        if len(paths) != len(set(paths)):
            raise ConfigError(
                "Configuration document paths must be unique",
                key=self.set_id,
            )
        object.__setattr__(self, "documents", documents)

    def get(self, source_id: str) -> ConfigDocument:
        for document in self.documents:
            if document.source_id == source_id:
                return document
        raise ConfigError(
            "Configuration document source does not exist",
            key=source_id,
        )


def config_documents(
    sets: Iterable[ConfigDocumentSet],
) -> tuple[ConfigDocument, ...]:
    return tuple(document for item in sets for document in item.documents)
