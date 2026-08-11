"""Project settings for optional infrastructure services."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import cast

from .config import ConfigError, reject_unknown_keys
from .embedding import EmbeddingSettings, parse_embedding_settings


@dataclass(frozen=True)
class InfraSettings:
    """Configured owner-neutral infrastructure services."""

    embedding: EmbeddingSettings = field(default_factory=EmbeddingSettings)

    def __post_init__(self) -> None:
        if not isinstance(self.embedding, EmbeddingSettings):
            raise ConfigError(
                "Embedding infrastructure settings are invalid",
                key="infra.embedding",
                expected="EmbeddingSettings",
            )


def parse_infra_settings(tree: Mapping[str, object]) -> InfraSettings:
    """Parse the complete Infra-owned project configuration tree."""

    reject_unknown_keys(tree, {"embedding"}, key="infra")
    value = tree.get("embedding")
    if value is None:
        embedding_tree: Mapping[str, object] = {}
    elif isinstance(value, Mapping):
        embedding_tree = cast(Mapping[str, object], value)
    else:
        raise ConfigError(
            "Embedding infrastructure configuration must be a table",
            key="infra.embedding",
            value=value,
            expected="table",
        )
    return InfraSettings(
        embedding=parse_embedding_settings(embedding_tree),
    )
