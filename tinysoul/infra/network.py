"""Explicit outbound network policy shared by HTTP and process owners."""

from __future__ import annotations

import ipaddress
import os
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from enum import StrEnum
from urllib.parse import urlsplit

import httpx

from .config import ConfigEnvironment, ConfigError, reject_unknown_keys
from .config.validation import config_table

_DEFAULT_NO_PROXY = "localhost,127.0.0.1,::1"
_PROXY_NAMES = frozenset({"http_proxy", "https_proxy", "all_proxy", "no_proxy"})


class NetworkMode(StrEnum):
    INHERIT = "inherit"
    DIRECT = "direct"
    OVERRIDE = "override"


def _proxy_url(value: str | None, key: str) -> None:
    if value is not None and not isinstance(value, str):
        raise ConfigError("Proxy URL must be text", key=key)
    if not value:
        return
    try:
        url = urlsplit(value)
        valid = url.scheme in {"http", "https"} and bool(url.hostname)
        valid = valid and not url.query and not url.fragment and url.path in {"", "/"}
        _ = url.port
    except ValueError:
        valid = False
    if not valid:
        raise ConfigError("Expected an HTTP or HTTPS proxy URL", key=key)


class NetworkTargetError(Exception):
    """A caller supplied a target that cannot be interpreted as a network URL."""


def _normalized_host(value: str) -> str:
    host = value.lower().rstrip(".")
    try:
        return str(ipaddress.ip_address(host))
    except ValueError:
        return httpx.URL(host=host).raw_host.decode("ascii")


@dataclass(frozen=True)
class _BypassRule:
    host: str | None
    port: int | None = None
    subdomains: bool = False

    def matches(self, host: str, port: int) -> bool:
        if self.port is not None and self.port != port:
            return False
        return (
            self.host is None
            or host == self.host
            or (self.subdomains and host.endswith("." + self.host))
        )


def _bypass_rules(value: str) -> tuple[_BypassRule, ...]:
    rules: list[_BypassRule] = []
    for item in value.split(","):
        item = item.strip().lower()
        if not item:
            continue
        if item == "*":
            return (_BypassRule(None),)
        # Bare IPv6 is a host, not a host:port pair.
        try:
            address = ipaddress.ip_address(item)
        except ValueError:
            address = None
        if address is not None:
            rules.append(_BypassRule(str(address)))
            continue
        try:
            url = urlsplit("//" + item)
            host, port = url.hostname, url.port
            if (
                not host or url.path or url.query or url.fragment
                or url.username is not None
            ):
                raise ValueError
        except ValueError as exc:
            raise ConfigError(
                "Invalid no_proxy host or port", key="network.no_proxy"
            ) from exc
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            address = None
        if address is not None:
            rules.append(_BypassRule(str(address), port))
        else:
            host = host.removeprefix("*.").removeprefix(".")
            if not host or any(c.isspace() or c in "*/\\" for c in host):
                raise ConfigError("Invalid no_proxy domain", key="network.no_proxy")
            try:
                host = _normalized_host(host)
            except httpx.InvalidURL as exc:
                raise ConfigError(
                    "Invalid no_proxy domain", key="network.no_proxy"
                ) from exc
            if not host:
                raise ConfigError("Invalid no_proxy domain", key="network.no_proxy")
            rules.append(_BypassRule(host, port, subdomains=True))
    return tuple(rules)


@dataclass(frozen=True)
class ResolvedNetwork:
    """Resolved connection inputs; clients and processes retain their own lifetime."""

    http_proxy: str | None = None
    https_proxy: str | None = None
    no_proxy: str = _DEFAULT_NO_PROXY
    _bypass: tuple[_BypassRule, ...] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        _proxy_url(self.http_proxy, "network.http_proxy")
        _proxy_url(self.https_proxy, "network.https_proxy")
        if not isinstance(self.no_proxy, str):
            raise ConfigError("no_proxy must be text", key="network.no_proxy")
        object.__setattr__(self, "_bypass", _bypass_rules(self.no_proxy))

    def proxy_for_url(self, value: str) -> str | None:
        """Choose the configured route without DNS or client-specific matching."""
        try:
            url = urlsplit(value)
            host = _normalized_host(url.hostname or "")
            port = url.port
        except (ValueError, httpx.InvalidURL) as exc:
            raise NetworkTargetError("Invalid network target URL") from exc
        if not url.scheme or not host:
            raise NetworkTargetError("Expected an absolute network target URL")
        if url.scheme == "http":
            proxy, default_port = self.http_proxy, 80
        elif url.scheme == "https":
            proxy, default_port = self.https_proxy, 443
        else:
            return None
        effective_port = default_port if port is None else port
        if any(rule.matches(host, effective_port) for rule in self._bypass):
            return None
        return proxy or None

    def process_environment(self, base: Mapping[str, str]) -> dict[str, str]:
        """Return a complete environment for a process started without inheritance."""
        result = {k: v for k, v in base.items() if k.lower() not in _PROXY_NAMES}
        for name, value in (
            ("http_proxy", self.http_proxy),
            ("https_proxy", self.https_proxy),
            (
                "no_proxy",
                self.no_proxy if self.http_proxy or self.https_proxy else None,
            ),
        ):
            if value is not None:
                result[name] = value
                if os.name != "nt":
                    result[name.upper()] = value
        return result


@dataclass(frozen=True)
class NetworkPolicy:
    mode: NetworkMode = NetworkMode.INHERIT
    http_proxy: str | None = None
    https_proxy: str | None = None
    no_proxy: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.mode, NetworkMode):
            raise ConfigError("Invalid network mode", key="network.mode")
        for name in ("http_proxy", "https_proxy", "no_proxy"):
            value = getattr(self, name)
            if value is not None and not isinstance(value, str):
                raise ConfigError("Network setting must be text", key=f"network.{name}")
        if self.mode is not NetworkMode.OVERRIDE:
            if any(
                v is not None
                for v in (self.http_proxy, self.https_proxy, self.no_proxy)
            ):
                raise ConfigError(
                    "Only override accepts proxy addresses", key="network"
                )
        elif not (self.http_proxy or self.https_proxy):
            raise ConfigError(
                "Override requires a proxy; use direct for no proxy", key="network"
            )
        else:
            self.resolve(ResolvedNetwork())

    def resolve(self, parent: ResolvedNetwork) -> ResolvedNetwork:
        if self.mode is NetworkMode.INHERIT:
            return parent
        if self.mode is NetworkMode.DIRECT:
            return ResolvedNetwork()
        return ResolvedNetwork(
            self.http_proxy or None,
            self.https_proxy or None,
            _DEFAULT_NO_PROXY if self.no_proxy is None else self.no_proxy,
        )


def parse_network(value: object, *, key: str) -> NetworkPolicy:
    table = config_table(value, key=key)
    reject_unknown_keys(
        table, {"mode", "http_proxy", "https_proxy", "no_proxy"}, key=key
    )
    try:
        mode = NetworkMode(table.get("mode", "inherit"))
    except (ValueError, TypeError) as exc:
        raise ConfigError(
            "Expected inherit, direct or override", key=f"{key}.mode"
        ) from exc
    values: dict[str, str | None] = {}
    for name in ("http_proxy", "https_proxy", "no_proxy"):
        raw = table.get(name)
        if raw is not None and not isinstance(raw, str):
            raise ConfigError("Network setting must be text", key=f"{key}.{name}")
        values[name] = raw
    try:
        return NetworkPolicy(mode, **values)
    except ConfigError as exc:
        raise replace(exc, key=key + exc.key.removeprefix("network")) from exc


def network_from_environment(*sources: Mapping[str, str]) -> ResolvedNetwork:
    """Later sources win; lowercase wins within each individual source."""
    values: dict[str, str] = {}
    for source in sources:
        for name in _PROXY_NAMES:
            if name in source:
                values[name] = source[name]
            elif name.upper() in source:
                values[name] = source[name.upper()]
    fallback = values.get("all_proxy")
    return ResolvedNetwork(
        values.get("http_proxy", fallback) or None,
        values.get("https_proxy", fallback) or None,
        values.get("no_proxy", _DEFAULT_NO_PROXY),
    )


def resolve_project_network(
    policy: NetworkPolicy, environment: ConfigEnvironment
) -> ResolvedNetwork:
    parent = (
        network_from_environment(environment.dotenv_values, environment.process_env)
        if policy.mode is NetworkMode.INHERIT
        else ResolvedNetwork()
    )
    return policy.resolve(parent)


def reject_proxy_environment(names: Mapping[str, str], *, key: str) -> None:
    if any(name.lower() in _PROXY_NAMES for name in names):
        raise ConfigError(
            "Configure proxies through network instead of env/env_refs", key=key
        )
