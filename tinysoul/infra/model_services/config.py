"""Provider/model/use configuration for non-generative model capabilities."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from math import isfinite
from typing import cast

from tinysoul.infra.config import ConfigError, reject_unknown_keys


class ModelCapability(StrEnum):
    EMBEDDING = "embedding"
    STRUCTURED_DECISION = "structured_decision"


class ModelAdapter(StrEnum):
    OPENAI_EMBEDDING = "openai_embedding"
    TYPESAFE_SYSTEM_ONE = "typesafe_system_one"


@dataclass(frozen=True)
class ServiceProvider:
    id: str
    adapter: ModelAdapter
    base_url: str
    api_key_env: str
    enabled: bool = True
    timeout_seconds: float = 30.0
    max_retries: int = 2
    proxy: str | None = None

    def __post_init__(self) -> None:
        if (
            not self.id
            or not self.base_url.startswith(("https://", "http://"))
            or not self.api_key_env
        ):
            raise ConfigError(
                "Invalid model provider identity or connection",
                key="infra.model_services.providers",
            )
        if (
            type(self.enabled) is not bool
            or not isfinite(self.timeout_seconds)
            or self.timeout_seconds <= 0
            or type(self.max_retries) is not int
            or not 0 <= self.max_retries <= 5
        ):
            raise ConfigError(
                "Invalid model provider retry/timeout limits", key=self.id
            )
        if self.proxy is not None and not self.proxy.startswith(
            ("http://", "https://", "socks5://")
        ):
            raise ConfigError("Invalid model provider proxy", key=self.id)


@dataclass(frozen=True)
class ServiceProviderBinding:
    provider_id: str
    model: str

    def __post_init__(self) -> None:
        if not self.provider_id or not self.model:
            raise ConfigError(
                "Model provider binding requires identities",
                key="infra.model_services.models",
            )


@dataclass(frozen=True)
class ServiceModel:
    id: str
    kind: ModelCapability
    provider_bindings: tuple[ServiceProviderBinding, ...]
    dimensions: int | None = None
    batch_size: int = 64

    def __post_init__(self) -> None:
        if (
            not self.id
            or not self.provider_bindings
            or len({item.provider_id for item in self.provider_bindings})
            != len(self.provider_bindings)
        ):
            raise ConfigError(
                "Model requires unique ordered provider bindings", key=self.id
            )
        if self.kind is ModelCapability.EMBEDDING:
            if type(self.dimensions) is not int or self.dimensions <= 0:
                raise ConfigError("Embedding dimensions must be positive", key=self.id)
        elif self.dimensions is not None:
            raise ConfigError(
                "Decision models do not have vector dimensions", key=self.id
            )
        if type(self.batch_size) is not int or not 1 <= self.batch_size <= 256:
            raise ConfigError(
                "Model batch_size must be between one and 256", key=self.id
            )


@dataclass(frozen=True)
class ServiceUse:
    id: str
    kind: ModelCapability
    model_id: str

    def __post_init__(self) -> None:
        if not self.id or not self.model_id:
            raise ConfigError(
                "Model use requires identities", key="infra.model_services.uses"
            )


@dataclass(frozen=True)
class ModelServicesSettings:
    providers: tuple[ServiceProvider, ...] = ()
    models: tuple[ServiceModel, ...] = ()
    uses: tuple[ServiceUse, ...] = ()

    def __post_init__(self) -> None:
        for items in (self.providers, self.models, self.uses):
            if len({item.id for item in items}) != len(items):
                raise ConfigError(
                    "Model service IDs must be unique", key="infra.model_services"
                )
        providers = {item.id: item for item in self.providers}
        models = {item.id: item for item in self.models}
        for model in self.models:
            expected = (
                ModelAdapter.OPENAI_EMBEDDING
                if model.kind is ModelCapability.EMBEDDING
                else ModelAdapter.TYPESAFE_SYSTEM_ONE
            )
            for binding in model.provider_bindings:
                provider = providers.get(binding.provider_id)
                if provider is None or provider.adapter is not expected:
                    raise ConfigError(
                        "Unknown provider or wrong model capability", key=model.id
                    )
        for use in self.uses:
            if use.model_id not in models or models[use.model_id].kind is not use.kind:
                raise ConfigError("Unknown model or wrong use capability", key=use.id)

    def resolve(
        self, use_id: str, kind: ModelCapability, env: Mapping[str, str]
    ) -> tuple[
        ServiceModel, tuple[tuple[ServiceProvider, ServiceProviderBinding], ...]
    ]:
        use = next((item for item in self.uses if item.id == use_id), None)
        if use is None or use.kind is not kind:
            raise ConfigError(
                "Unknown use or incompatible capability",
                key=f"infra.model_services.uses.{use_id}",
            )
        model = next(item for item in self.models if item.id == use.model_id)
        providers = {item.id: item for item in self.providers}
        routes = tuple(
            (providers[item.provider_id], item)
            for item in model.provider_bindings
            if providers[item.provider_id].enabled
        )
        if not routes:
            raise ConfigError("Selected model has no enabled provider", key=model.id)
        for provider, _ in routes:
            if not env.get(provider.api_key_env):
                raise ConfigError(
                    "Selected provider credential is missing",
                    key=f"infra.model_services.providers.{provider.id}.api_key_env",
                )
        return model, routes


def parse_model_services(tree: Mapping[str, object]) -> ModelServicesSettings:
    reject_unknown_keys(
        tree, {"providers", "models", "uses"}, key="infra.model_services"
    )
    providers = []
    for t in _rows(tree.get("providers", []), "providers"):
        reject_unknown_keys(
            t,
            {
                "id",
                "adapter",
                "base_url",
                "api_key_env",
                "enabled",
                "timeout_seconds",
                "max_retries",
                "proxy",
            },
            key="infra.model_services.providers",
        )
        providers.append(
            ServiceProvider(
                text(t, "id"),
                enum_value(ModelAdapter, t, "adapter"),
                text(t, "base_url"),
                text(t, "api_key_env"),
                boolean(t.get("enabled", True)),
                number(t.get("timeout_seconds", 30)),
                integer(t.get("max_retries", 2)),
                text(t, "proxy") if "proxy" in t else None,
            )
        )
    models = []
    for t in _rows(tree.get("models", []), "models"):
        reject_unknown_keys(
            t,
            {"id", "kind", "provider_bindings", "dimensions", "batch_size"},
            key="infra.model_services.models",
        )
        bindings = []
        for binding in _rows(t.get("provider_bindings", []), "provider_bindings"):
            reject_unknown_keys(
                binding,
                {"provider_id", "model"},
                key="infra.model_services.models.provider_bindings",
            )
            bindings.append(
                ServiceProviderBinding(
                    text(binding, "provider_id"), text(binding, "model")
                )
            )
        models.append(
            ServiceModel(
                text(t, "id"),
                enum_value(ModelCapability, t, "kind"),
                tuple(bindings),
                integer(t["dimensions"]) if "dimensions" in t else None,
                integer(t.get("batch_size", 64)),
            )
        )
    uses = []
    for t in _rows(tree.get("uses", []), "uses"):
        reject_unknown_keys(
            t, {"id", "kind", "model_id"}, key="infra.model_services.uses"
        )
        uses.append(
            ServiceUse(
                text(t, "id"),
                enum_value(ModelCapability, t, "kind"),
                text(t, "model_id"),
            )
        )
    return ModelServicesSettings(tuple(providers), tuple(models), tuple(uses))


def _rows(value: object, key: str) -> tuple[dict[str, object], ...]:
    if not isinstance(value, list):
        raise ConfigError("Expected model service table array", key=key)
    result = []
    for row in value:
        if not isinstance(row, Mapping) or any(not isinstance(k, str) for k in row):
            raise ConfigError("Expected named fields", key=key)
        result.append(dict(cast(Mapping[str, object], row)))
    return tuple(result)


def text(table: Mapping[str, object], name: str) -> str:
    value = table.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError("Expected nonempty text", key=f"infra.model_services.{name}")
    return value


def integer(value: object) -> int:
    if type(value) is not int:
        raise ConfigError("Expected integer model option", key="infra.model_services")
    return value


def number(value: object) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not isfinite(value)
    ):
        raise ConfigError(
            "Expected finite numeric model option", key="infra.model_services"
        )
    return float(value)


def boolean(value: object) -> bool:
    if type(value) is not bool:
        raise ConfigError("Expected boolean model option", key="infra.model_services")
    return value


def enum_value[E: StrEnum](enum: type[E], table: Mapping[str, object], name: str) -> E:
    try:
        return enum(text(table, name))
    except ValueError as exc:
        raise ConfigError(
            "Unknown model service option", key=f"infra.model_services.{name}"
        ) from exc
