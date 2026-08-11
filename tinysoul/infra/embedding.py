"""Provider-neutral text embedding infrastructure."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import math
from typing import Protocol

from openai import OpenAI

from tinysoul.infra.config import ConfigError, reject_unknown_keys


_CONFIG_KEY = "infra.embedding"


class EmbeddingError(Exception):
    """Embedding adapter/configuration boundary failure."""


@dataclass(frozen=True)
class EmbeddingSettings:
    enabled: bool = False
    base_url: str = "https://open.bigmodel.cn/api/paas/v4"
    model: str = "embedding-3"
    api_key_env: str = "GLM_EMBEDDING_API_KEY"
    dimensions: int = 1024
    batch_size: int = 64
    timeout_seconds: float = 30.0

    def __post_init__(self) -> None:
        if not isinstance(self.enabled, bool):
            raise ConfigError(
                "Embedding enabled must be boolean",
                key=f"{_CONFIG_KEY}.enabled",
            )
        for name in ("base_url", "model"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value:
                raise ConfigError(
                    f"Embedding {name} must be non-empty",
                    key=f"{_CONFIG_KEY}.{name}",
                )
        if not isinstance(self.api_key_env, str) or not self.api_key_env:
            raise ConfigError(
                "Embedding api_key_env is invalid",
                key=f"{_CONFIG_KEY}.api_key_env",
            )
        if self.model == "embedding-3" and self.dimensions not in {
            256,
            512,
            1024,
            2048,
        }:
            raise ConfigError(
                "embedding-3 dimensions must be 256, 512, 1024, or 2048",
                key=f"{_CONFIG_KEY}.dimensions",
            )
        if (
            isinstance(self.dimensions, bool)
            or not isinstance(self.dimensions, int)
            or self.dimensions <= 0
        ):
            raise ConfigError(
                "Embedding dimensions must be positive",
                key=f"{_CONFIG_KEY}.dimensions",
            )
        if (
            isinstance(self.batch_size, bool)
            or not isinstance(self.batch_size, int)
            or not 1 <= self.batch_size <= 64
        ):
            raise ConfigError(
                "Embedding batch_size must be between 1 and 64",
                key=f"{_CONFIG_KEY}.batch_size",
            )
        if (
            isinstance(self.timeout_seconds, bool)
            or not isinstance(self.timeout_seconds, (int, float))
            or self.timeout_seconds <= 0
        ):
            raise ConfigError(
                "Embedding timeout_seconds must be positive",
                key=f"{_CONFIG_KEY}.timeout_seconds",
            )

    def resolve_api_key(self, env: Mapping[str, str]) -> str:
        value = env.get(self.api_key_env)
        if value:
            return value
        raise ConfigError(
            "Embedding API key is not configured",
            key=f"{_CONFIG_KEY}.api_key_env",
            value=self.api_key_env,
        )


@dataclass(frozen=True)
class EmbeddingBatch:
    model: str
    dimensions: int
    vectors: tuple[tuple[float, ...], ...]

    def __post_init__(self) -> None:
        if not isinstance(self.model, str) or not self.model:
            raise EmbeddingError("Embedding response model is invalid")
        if (
            isinstance(self.dimensions, bool)
            or not isinstance(self.dimensions, int)
            or self.dimensions <= 0
        ):
            raise EmbeddingError("Embedding response dimensions are invalid")
        if any(len(vector) != self.dimensions for vector in self.vectors):
            raise EmbeddingError("Embedding response vectors have inconsistent dimensions")
        if any(not math.isfinite(value) for vector in self.vectors for value in vector):
            raise EmbeddingError("Embedding response vectors must be finite")


class EmbeddingClient(Protocol):
    @property
    def identity(self) -> str:
        ...

    @property
    def max_batch_size(self) -> int:
        ...

    def embed(self, texts: Sequence[str]) -> EmbeddingBatch:
        ...


class OpenAICompatibleEmbeddingClient:
    """Narrow OpenAI SDK adapter used by BigModel Embedding-3 and peers."""

    def __init__(
        self,
        *,
        settings: EmbeddingSettings,
        api_key: str,
        client: object | None = None,
    ) -> None:
        if not settings.enabled:
            raise ConfigError(
                "Cannot build a disabled Embedding client",
                key=f"{_CONFIG_KEY}.enabled",
            )
        if not isinstance(api_key, str) or not api_key:
            raise ConfigError(
                "Embedding API key is empty",
                key=f"{_CONFIG_KEY}.api_key_env",
            )
        self._settings = settings
        self._client = client or OpenAI(
            api_key=api_key,
            base_url=settings.base_url,
            timeout=settings.timeout_seconds,
        )

    @property
    def identity(self) -> str:
        return f"{self._settings.base_url}|{self._settings.model}|{self._settings.dimensions}"

    @property
    def max_batch_size(self) -> int:
        return self._settings.batch_size

    def embed(self, texts: Sequence[str]) -> EmbeddingBatch:
        values = tuple(texts)
        if not values or len(values) > self._settings.batch_size:
            raise EmbeddingError("Embedding request batch size is invalid")
        if any(not isinstance(item, str) or not item.strip() for item in values):
            raise EmbeddingError("Embedding request texts must be non-empty")
        try:
            embeddings = getattr(self._client, "embeddings")
            create = getattr(embeddings, "create")
            response = create(
                model=self._settings.model,
                input=list(values),
                dimensions=self._settings.dimensions,
            )
        except Exception as exc:
            raise EmbeddingError(f"Embedding request failed: {type(exc).__name__}") from exc
        raw_data = getattr(response, "data", None)
        if not isinstance(raw_data, Sequence) or len(raw_data) != len(values):
            raise EmbeddingError("Embedding response data is invalid")
        indexed: dict[int, tuple[float, ...]] = {}
        for position, item in enumerate(raw_data):
            raw_index = getattr(item, "index", position)
            raw_vector = getattr(item, "embedding", None)
            if isinstance(raw_index, bool) or not isinstance(raw_index, int):
                raise EmbeddingError("Embedding response index is invalid")
            if not isinstance(raw_vector, Sequence):
                raise EmbeddingError("Embedding response vector is invalid")
            try:
                vector = tuple(float(value) for value in raw_vector)
            except (TypeError, ValueError) as exc:
                raise EmbeddingError("Embedding response vector is invalid") from exc
            indexed[raw_index] = vector
        try:
            vectors = tuple(indexed[index] for index in range(len(values)))
        except KeyError as exc:
            raise EmbeddingError("Embedding response indices are incomplete") from exc
        return EmbeddingBatch(
            model=self._settings.model,
            dimensions=self._settings.dimensions,
            vectors=vectors,
        )


def parse_embedding_settings(tree: Mapping[str, object]) -> EmbeddingSettings:
    names = {
        "enabled",
        "base_url",
        "model",
        "api_key_env",
        "dimensions",
        "batch_size",
        "timeout_seconds",
    }
    reject_unknown_keys(tree, names, key=_CONFIG_KEY)
    defaults = EmbeddingSettings()
    return EmbeddingSettings(
        enabled=_bool(tree.get("enabled", defaults.enabled), "enabled"),
        base_url=_text(tree.get("base_url", defaults.base_url), "base_url"),
        model=_text(tree.get("model", defaults.model), "model"),
        api_key_env=_text(tree.get("api_key_env", defaults.api_key_env), "api_key_env"),
        dimensions=_int(tree.get("dimensions", defaults.dimensions), "dimensions"),
        batch_size=_int(tree.get("batch_size", defaults.batch_size), "batch_size"),
        timeout_seconds=_float(
            tree.get("timeout_seconds", defaults.timeout_seconds),
            "timeout_seconds",
        ),
    )


def build_embedding_client(
    settings: EmbeddingSettings,
    *,
    env: Mapping[str, str],
) -> EmbeddingClient | None:
    if not settings.enabled:
        return None
    return OpenAICompatibleEmbeddingClient(
        settings=settings,
        api_key=settings.resolve_api_key(env),
    )


def _bool(value: object, name: str) -> bool:
    if not isinstance(value, bool):
        raise ConfigError(
            "Embedding value must be boolean",
            key=f"{_CONFIG_KEY}.{name}",
        )
    return value


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ConfigError(
            "Embedding value must be non-empty text",
            key=f"{_CONFIG_KEY}.{name}",
        )
    return value


def _int(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(
            "Embedding value must be an integer",
            key=f"{_CONFIG_KEY}.{name}",
        )
    return value


def _float(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(
            "Embedding value must be numeric",
            key=f"{_CONFIG_KEY}.{name}",
        )
    return float(value)
