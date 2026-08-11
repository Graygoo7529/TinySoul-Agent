from __future__ import annotations

from dataclasses import dataclass

import pytest

from tinysoul.infra import (
    EmbeddingError,
    EmbeddingSettings,
    InfraSettings,
    OpenAICompatibleEmbeddingClient,
    build_embedding_client,
    parse_embedding_settings,
    parse_infra_settings,
)
from tinysoul.infra.config import ConfigError


def test_embedding_settings_are_strict_and_resolve_keys_only_from_environment() -> None:
    settings = parse_embedding_settings(
        {
            "enabled": True,
            "model": "embedding-3",
            "dimensions": 512,
            "batch_size": 2,
            "api_key_env": "GLM_EMBEDDING_API_KEY",
        }
    )
    assert settings.resolve_api_key({"GLM_EMBEDDING_API_KEY": "environment-secret"}) == (
        "environment-secret"
    )
    with pytest.raises(ConfigError, match="API key") as missing:
        settings.resolve_api_key({"GLM_API_KEY": "model-secret"})
    assert missing.value.key == "infra.embedding.api_key_env"
    with pytest.raises(ConfigError, match="API key"):
        settings.resolve_api_key({})
    with pytest.raises(ConfigError, match="Unknown"):
        parse_embedding_settings({"api_key": "must-not-be-configured"})
    with pytest.raises(ConfigError, match="Unknown"):
        parse_embedding_settings({"api_key_envs": ["GLM_API_KEY"]})
    with pytest.raises(ConfigError, match="Unknown"):
        parse_embedding_settings({"cache_max_chars": 1000})
    with pytest.raises(ConfigError, match="dimensions"):
        EmbeddingSettings(model="embedding-3", dimensions=768)
    assert build_embedding_client(EmbeddingSettings(), env={}) is None


def test_infra_settings_own_embedding_and_reject_unknown_children() -> None:
    settings = parse_infra_settings(
        {"embedding": {"enabled": True, "dimensions": 512}}
    )

    assert isinstance(settings, InfraSettings)
    assert settings.embedding.enabled is True
    assert settings.embedding.dimensions == 512
    with pytest.raises(ConfigError) as unknown:
        parse_infra_settings({"embeddings": {}})
    assert unknown.value.key == "infra.embeddings"
    with pytest.raises(ConfigError) as not_table:
        parse_infra_settings({"embedding": True})
    assert not_table.value.key == "infra.embedding"


def test_openai_compatible_embedding_client_restores_response_order() -> None:
    transport = _EmbeddingTransport()
    client = OpenAICompatibleEmbeddingClient(
        settings=EmbeddingSettings(enabled=True, dimensions=256, batch_size=2),
        api_key="environment-secret",
        client=transport,
    )

    result = client.embed(("first", "second"))

    assert transport.request == {
        "model": "embedding-3",
        "input": ["first", "second"],
        "dimensions": 256,
    }
    assert result.vectors[0][:2] == (1.0, 0.0)
    assert result.vectors[1][:2] == (0.0, 1.0)
    assert "environment-secret" not in client.identity


def test_embedding_client_converts_provider_failures_to_bounded_errors() -> None:
    client = OpenAICompatibleEmbeddingClient(
        settings=EmbeddingSettings(enabled=True, dimensions=256),
        api_key="environment-secret",
        client=_FailingEmbeddingTransport(),
    )
    with pytest.raises(EmbeddingError, match="RuntimeError") as captured:
        client.embed(("text",))
    assert "private provider detail" not in str(captured.value)


@dataclass
class _EmbeddingItem:
    index: int
    embedding: list[float]


@dataclass
class _EmbeddingResponse:
    data: list[_EmbeddingItem]


class _EmbeddingTransport:
    def __init__(self) -> None:
        self.embeddings = self
        self.request: dict[str, object] = {}

    def create(self, **kwargs: object) -> _EmbeddingResponse:
        self.request = dict(kwargs)
        first = [1.0, *([0.0] * 255)]
        second = [0.0, 1.0, *([0.0] * 254)]
        return _EmbeddingResponse(
            data=[
                _EmbeddingItem(index=1, embedding=second),
                _EmbeddingItem(index=0, embedding=first),
            ]
        )


class _FailingEmbeddingTransport:
    embeddings: "_FailingEmbeddingTransport"

    def __init__(self) -> None:
        self.embeddings = self

    def create(self, **kwargs: object) -> object:
        del kwargs
        raise RuntimeError("private provider detail")
