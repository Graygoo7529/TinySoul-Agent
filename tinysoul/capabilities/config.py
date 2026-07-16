"""Top-level capability configuration."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import cast

from tinysoul.infra.config import ConfigError, reject_unknown_keys

from .resource.config import ResourceSettings, parse_resource_settings


@dataclass(frozen=True)
class CapabilitiesSettings:
    """Configured lightweight capabilities."""

    resource: ResourceSettings = field(default_factory=ResourceSettings)

    def __post_init__(self) -> None:
        if not isinstance(self.resource, ResourceSettings):
            raise ConfigError(
                "Resource capability settings are invalid",
                key="capabilities.resource",
                value=type(self.resource).__name__,
                expected="ResourceSettings",
            )


def parse_capabilities_settings(tree: Mapping[str, object]) -> CapabilitiesSettings:
    reject_unknown_keys(tree, {"resource"}, key="capabilities")
    value = tree.get("resource")
    if value is None:
        resource_tree: Mapping[str, object] = {}
    elif isinstance(value, Mapping):
        resource_tree = cast(Mapping[str, object], value)
    else:
        raise ConfigError(
            "Resource capability configuration must be a table",
            key="capabilities.resource",
            value=value,
            expected="table",
        )
    return CapabilitiesSettings(resource=parse_resource_settings(resource_tree))

