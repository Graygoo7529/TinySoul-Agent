"""Top-level capability configuration."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import cast

from tinysoul.infra.config import ConfigError, reject_unknown_keys

from .resource.config import ResourceSettings, parse_resource_settings
from .script.config import ScriptSettings, parse_script_settings
from .shell.config import ShellSettings, parse_shell_settings
from .supervised_process.config import (
    SupervisedProcessSettings,
    parse_supervised_process_settings,
)
from .web.config import WebSettings, parse_web_settings


@dataclass(frozen=True)
class CapabilitiesSettings:
    """Configured lightweight capabilities."""

    resource: ResourceSettings = field(default_factory=ResourceSettings)
    script: ScriptSettings = field(default_factory=ScriptSettings)
    shell: ShellSettings = field(default_factory=ShellSettings)
    supervised_process: SupervisedProcessSettings = field(
        default_factory=SupervisedProcessSettings
    )
    web: WebSettings = field(default_factory=WebSettings)

    def __post_init__(self) -> None:
        if not isinstance(self.resource, ResourceSettings):
            raise ConfigError(
                "Resource capability settings are invalid",
                key="capabilities.resource",
                value=type(self.resource).__name__,
                expected="ResourceSettings",
            )
        if not isinstance(self.web, WebSettings):
            raise ConfigError(
                "Web capability settings are invalid",
                key="capabilities.web",
                value=type(self.web).__name__,
                expected="WebSettings",
            )
        if not isinstance(self.script, ScriptSettings):
            raise ConfigError(
                "Script capability settings are invalid",
                key="capabilities.script",
                value=type(self.script).__name__,
                expected="ScriptSettings",
            )
        if not isinstance(self.shell, ShellSettings):
            raise ConfigError(
                "Shell capability settings are invalid",
                key="capabilities.shell",
                value=type(self.shell).__name__,
                expected="ShellSettings",
            )
        if not isinstance(self.supervised_process, SupervisedProcessSettings):
            raise ConfigError(
                "Supervised process settings are invalid",
                key="capabilities.supervised_process",
                value=type(self.supervised_process).__name__,
                expected="SupervisedProcessSettings",
            )


def parse_capabilities_settings(tree: Mapping[str, object]) -> CapabilitiesSettings:
    reject_unknown_keys(
        tree,
        {"resource", "script", "shell", "supervised_process", "web"},
        key="capabilities",
    )
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
    web_value = tree.get("web")
    if web_value is None:
        web_tree: Mapping[str, object] = {}
    elif isinstance(web_value, Mapping):
        web_tree = cast(Mapping[str, object], web_value)
    else:
        raise ConfigError(
            "Web capability configuration must be a table",
            key="capabilities.web",
            value=web_value,
            expected="table",
        )
    script_value = tree.get("script")
    if script_value is None:
        script_tree: Mapping[str, object] = {}
    elif isinstance(script_value, Mapping):
        script_tree = cast(Mapping[str, object], script_value)
    else:
        raise ConfigError(
            "Script capability configuration must be a table",
            key="capabilities.script",
            value=script_value,
            expected="table",
        )
    supervised_value = tree.get("supervised_process")
    if supervised_value is None:
        supervised_tree: Mapping[str, object] = {}
    elif isinstance(supervised_value, Mapping):
        supervised_tree = cast(Mapping[str, object], supervised_value)
    else:
        raise ConfigError(
            "Supervised process configuration must be a table",
            key="capabilities.supervised_process",
            value=supervised_value,
            expected="table",
        )
    shell_value = tree.get("shell")
    if shell_value is None:
        shell_tree: Mapping[str, object] = {}
    elif isinstance(shell_value, Mapping):
        shell_tree = cast(Mapping[str, object], shell_value)
    else:
        raise ConfigError(
            "Shell capability configuration must be a table",
            key="capabilities.shell",
            value=shell_value,
            expected="table",
        )
    return CapabilitiesSettings(
        resource=parse_resource_settings(resource_tree),
        script=parse_script_settings(script_tree),
        shell=parse_shell_settings(shell_tree),
        supervised_process=parse_supervised_process_settings(supervised_tree),
        web=parse_web_settings(web_tree),
    )
