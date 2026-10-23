"""Project settings for optional infrastructure services."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import cast

from .config import ConfigError, reject_unknown_keys
from .model_services.config import ModelServicesSettings, parse_model_services
from .network import NetworkPolicy, parse_network


@dataclass(frozen=True)
class InfraSettings:
    """Configured owner-neutral infrastructure services."""

    network: NetworkPolicy = field(default_factory=NetworkPolicy)
    model_services: ModelServicesSettings = field(default_factory=ModelServicesSettings)

    def __post_init__(self) -> None:
        if not isinstance(self.network, NetworkPolicy):
            raise ConfigError("Network settings are invalid", key="infra.network")
        if not isinstance(self.model_services, ModelServicesSettings):
            raise ConfigError(
                "Model service settings are invalid",
                key="infra.model_services",
                expected="ModelServicesSettings",
            )


def parse_infra_settings(tree: Mapping[str, object]) -> InfraSettings:
    """Parse the complete Infra-owned project configuration tree."""

    reject_unknown_keys(tree, {"model_services", "network"}, key="infra")
    value = tree.get("model_services")
    if value is None:
        services_tree: Mapping[str, object] = {}
    elif isinstance(value, Mapping):
        services_tree = cast(Mapping[str, object], value)
    else:
        raise ConfigError(
            "Model service configuration must be a table",
            key="infra.model_services",
            value=value,
            expected="table",
        )
    return InfraSettings(
        network=parse_network(tree.get("network", {}), key="infra.network"),
        model_services=parse_model_services(services_tree),
    )
