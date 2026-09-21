"""Configuration of capabilities without independent execution lifecycles."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import cast

from tinysoul.infra.config import ConfigError, reject_unknown_keys
from .resource.config import ResourceSettings, parse_resource_settings
from .web.config import WebSettings, parse_web_settings
from .expand.config import ExpandSettings, parse_expand_settings
from .subagent.config import SubagentSettings, parse_subagent_settings


@dataclass(frozen=True)
class CapabilitiesSettings:
    resource: ResourceSettings = field(default_factory=ResourceSettings)
    web: WebSettings = field(default_factory=WebSettings)
    expand: ExpandSettings = field(default_factory=ExpandSettings)
    subagent: SubagentSettings = field(default_factory=SubagentSettings)

    def __post_init__(self) -> None:
        if (
            not isinstance(self.resource, ResourceSettings)
            or not isinstance(self.web, WebSettings)
            or not isinstance(self.expand, ExpandSettings)
            or not isinstance(self.subagent, SubagentSettings)
        ):
            raise ConfigError("Capability settings must be typed", key="capabilities")


def parse_capabilities_settings(tree: Mapping[str, object]) -> CapabilitiesSettings:
    reject_unknown_keys(
        tree, {"resource", "web", "expand", "subagent"}, key="capabilities"
    )

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
        expand=parse_expand_settings(section("expand")),
        subagent=parse_subagent_settings(section("subagent")),
    )
