"""Explicit MCP servers; availability and tool policy belong to this owner."""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from math import isfinite
from typing import cast
from urllib.parse import urlsplit

from tinysoul.infra import DependencyChecker, DependencyRequirement
from tinysoul.infra.config import ConfigError, reject_unknown_keys
from tinysoul.infra.config.validation import (
    config_table,
    string_mapping,
    resolve_references,
)


class MCPTransport(StrEnum):
    STDIO = "stdio"
    HTTP = "streamable_http"


@dataclass(frozen=True)
class MCPServerSettings:
    server_id: str
    enabled: bool = False
    description: str = ""
    transport: MCPTransport = MCPTransport.STDIO
    command: str = ""
    args: tuple[str, ...] = ()
    cwd: str = ""
    env: tuple[tuple[str, str], ...] = ()
    env_refs: tuple[tuple[str, str], ...] = ()
    url: str = ""
    headers: tuple[tuple[str, str], ...] = ()
    header_refs: tuple[tuple[str, str], ...] = ()
    tools_default: bool = True
    tools: tuple[tuple[str, bool], ...] = ()

    def __post_init__(self) -> None:
        key = f"capabilities.expand.servers.{self.server_id}"
        if (
            not self.server_id
            or "." in self.server_id
            or self.server_id.strip() != self.server_id
        ):
            raise ConfigError("Server identity is invalid", key=key)
        if (
            not isinstance(self.transport, MCPTransport)
            or type(self.enabled) is not bool
            or type(self.tools_default) is not bool
        ):
            raise ConfigError("MCP transport and policies must be typed", key=key)
        if self.enabled and (
            (self.transport is MCPTransport.STDIO and not self.command)
            or (
                self.transport is MCPTransport.HTTP
                and urlsplit(self.url).scheme not in {"http", "https"}
            )
        ):
            raise ConfigError(
                "Enabled MCP server requires its transport address", key=key
            )

    def allows(self, name: str) -> bool:
        return self.enabled and dict(self.tools).get(name, self.tools_default)


@dataclass(frozen=True)
class ExpandSettings:
    servers: tuple[MCPServerSettings, ...] = ()
    timeout_seconds: float = 45.0
    max_tools: int = 2000
    max_catalog_bytes: int = 4_000_000
    max_result_bytes: int = 8_000_000
    max_inline_chars: int = 16000
    search_max_chars: int = 60000
    page_size: int = 30

    def __post_init__(self) -> None:
        if (
            type(self.timeout_seconds) not in {int, float}
            or not isfinite(self.timeout_seconds)
            or self.timeout_seconds <= 0
        ):
            raise ConfigError(
                "MCP timeout must be finite and positive",
                key="capabilities.expand.timeout_seconds",
            )
        for name in (
            "max_tools",
            "max_catalog_bytes",
            "max_result_bytes",
            "max_inline_chars",
            "search_max_chars",
            "page_size",
        ):
            if type(getattr(self, name)) is not int or getattr(self, name) <= 0:
                raise ConfigError(
                    "MCP limit must be a positive integer",
                    key=f"capabilities.expand.{name}",
                )
        if len({item.server_id for item in self.servers}) != len(self.servers):
            raise ConfigError(
                "MCP server identities must be unique",
                key="capabilities.expand.servers",
            )


def parse_expand_settings(tree: Mapping[str, object]) -> ExpandSettings:
    defaults = ExpandSettings()
    limits = (
        "max_tools",
        "max_catalog_bytes",
        "max_result_bytes",
        "max_inline_chars",
        "search_max_chars",
        "page_size",
    )
    reject_unknown_keys(
        tree, {"servers", "timeout_seconds", *limits}, key="capabilities.expand"
    )
    parsed: list[MCPServerSettings] = []
    for identity, raw in config_table(
        tree.get("servers", {}), key="capabilities.expand.servers"
    ).items():
        key = f"capabilities.expand.servers.{identity}"
        row = config_table(raw, key=key)
        reject_unknown_keys(
            row,
            {
                "enabled",
                "description",
                "transport",
                "command",
                "args",
                "cwd",
                "env",
                "env_refs",
                "url",
                "headers",
                "header_refs",
                "tools_default",
                "tools",
            },
            key=key,
        )
        text: dict[str, str] = {}
        for name in ("description", "command", "cwd", "url"):
            value = row.get(name, "")
            if not isinstance(value, str) or "\x00" in value:
                raise ConfigError("MCP field must be text", key=f"{key}.{name}")
            text[name] = value
        args = row.get("args", [])
        if not isinstance(args, list) or any(
            not isinstance(arg, str) or "\x00" in arg for arg in args
        ):
            raise ConfigError("MCP args must be text arguments", key=f"{key}.args")
        enabled, default = row.get("enabled", False), row.get("tools_default", True)
        if type(enabled) is not bool or type(default) is not bool:
            raise ConfigError("MCP switches must be boolean", key=key)
        tools = config_table(row.get("tools", {}), key=f"{key}.tools")
        if any(type(value) is not bool for value in tools.values()):
            raise ConfigError("MCP tool choices must be boolean", key=f"{key}.tools")
        try:
            transport = MCPTransport(row.get("transport", "stdio"))
        except (ValueError, TypeError) as exc:
            raise ConfigError("Unknown MCP transport", key=f"{key}.transport") from exc
        parsed.append(
            MCPServerSettings(
                identity,
                enabled=enabled,
                transport=transport,
                args=tuple(cast(list[str], args)),
                tools_default=default,
                tools=tuple((name, cast(bool, value)) for name, value in tools.items()),
                description=text["description"],
                command=text["command"],
                cwd=text["cwd"],
                url=text["url"],
                env=string_mapping(row.get("env", {}), key=f"{key}.env"),
                env_refs=string_mapping(row.get("env_refs", {}), key=f"{key}.env_refs"),
                headers=string_mapping(row.get("headers", {}), key=f"{key}.headers"),
                header_refs=string_mapping(
                    row.get("header_refs", {}), key=f"{key}.header_refs"
                ),
            )
        )
    numbers = {name: tree.get(name, getattr(defaults, name)) for name in limits}
    if any(type(value) is not int for value in numbers.values()):
        raise ConfigError("MCP limits must be integers", key="capabilities.expand")
    timeout = tree.get("timeout_seconds", defaults.timeout_seconds)
    if type(timeout) not in {int, float}:
        raise ConfigError(
            "MCP timeout must be numeric", key="capabilities.expand.timeout_seconds"
        )
    return ExpandSettings(
        tuple(parsed),
        timeout_seconds=cast(float, timeout),
        **cast(dict[str, int], numbers),
    )


def validate_expand_bindings(
    settings: ExpandSettings, environment: Mapping[str, str]
) -> None:
    """Validate local dependencies and references without enumerating remote tools."""
    for server in settings.servers:
        if not server.enabled:
            continue
        key = f"capabilities.expand.servers.{server.server_id}"
        executables = (
            (server.command,) if server.transport is MCPTransport.STDIO else ()
        )
        check = DependencyChecker().check(
            DependencyRequirement(
                "expand", modules=("mcp", "jsonschema"), executables=executables
            )
        )
        if not check.available:
            raise ConfigError(
                "Enabled MCP server requires its executable and tinysoul[external-tools]",
                key=key,
            )
        resolve_references(
            server.env, server.env_refs, environment, key=f"{key}.env_refs"
        )
        resolve_references(
            server.headers, server.header_refs, environment, key=f"{key}.header_refs"
        )
