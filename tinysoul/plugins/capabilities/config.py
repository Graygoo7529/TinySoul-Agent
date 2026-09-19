"""Configuration of capabilities without independent execution lifecycles."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import cast

from tinysoul.infra.config import ConfigError, reject_unknown_keys
from .resource.config import ResourceSettings, parse_resource_settings
from .web.config import WebSettings, parse_web_settings


@dataclass(frozen=True)
class CapabilitiesSettings:
    resource: ResourceSettings = field(default_factory=ResourceSettings)
    web: WebSettings = field(default_factory=WebSettings)

    def __post_init__(self) -> None:
        if not isinstance(self.resource, ResourceSettings) or not isinstance(
            self.web, WebSettings
        ):
            raise ConfigError("Capability settings must be typed", key="capabilities")


def parse_capabilities_settings(tree: Mapping[str, object]) -> CapabilitiesSettings:
    reject_unknown_keys(tree, {"resource", "web"}, key="capabilities")

    def section(name: str) -> Mapping[str, object]:
        value = tree.get(name, {})
        if not isinstance(value, Mapping) or any(
            not isinstance(key, str) for key in value
        ):
            raise ConfigError(
                "Capability configuration must be a table", key=f"capabilities.{name}"
            )
        return cast(Mapping[str, object], value)

    return CapabilitiesSettings(
        resource=parse_resource_settings(section("resource")),
        web=parse_web_settings(section("web")),
    )
