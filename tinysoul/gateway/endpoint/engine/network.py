"""Saved network configuration projection; each owner parses its own settings."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit

from tinysoul.infra.config import ConfigEnvironment
from tinysoul.infra.json import JsonObject, JsonValue
from tinysoul.infra.network import NetworkPolicy, ResolvedNetwork, resolve_project_network
from tinysoul.infra.settings import parse_infra_settings
from tinysoul.llm.config.loader import ProviderConfigParser
from tinysoul.plugins.capabilities.expand.config import parse_expand_settings
from tinysoul.plugins.capabilities.subagent.config import parse_subagent_settings
from tinysoul.plugins.capabilities.web.config import parse_web_settings
from tinysoul.plugins.execution.config import parse_execution_settings


@dataclass(frozen=True)
class _NetworkRoute:
    path: str
    resolved: ResolvedNetwork
    view: JsonObject


class EndpointNetworkProjection:
    """Describe configured routes without clients, probes or runtime mutation."""

    def __init__(self, environment: ConfigEnvironment) -> None:
        self._environment = environment

    def project(self) -> JsonObject:
        env = self._environment
        infra = env.parse_section("infra", parse_infra_settings)
        root = self._route("infra", infra.network)
        consumers: list[JsonValue] = []

        def add(
            owner: str,
            policy: NetworkPolicy,
            parent: _NetworkRoute = root,
            *,
            source_key: str | None = None,
        ) -> _NetworkRoute:
            route = self._route(owner, policy, parent, source_key=source_key)
            consumers.append(route.view)
            return route

        providers = env.parse_section("llm.providers", ProviderConfigParser().parse)
        for provider in providers:
            owner = f"llm.providers.{provider.id}"
            route = add(owner, provider.network)
            for endpoint in provider.endpoints:
                add(f"{owner}.endpoints.{endpoint.api_mode}", endpoint.network, route)

        for provider in infra.model_services.providers:
            add(
                f"infra.model_services.providers.{provider.id}",
                provider.network,
                source_key="infra.model_services.providers",
            )

        expand = env.parse_section("capabilities.expand", parse_expand_settings)
        route = add("capabilities.expand", expand.network)
        for server in expand.servers:
            add(f"capabilities.expand.servers.{server.server_id}", server.network, route)

        subagent = env.parse_section("capabilities.subagent", parse_subagent_settings)
        route = add("capabilities.subagent", subagent.network)
        for agent in subagent.agents:
            add(f"capabilities.subagent.agents.{agent.agent_id}", agent.network, route)

        web = env.parse_section("capabilities.web", parse_web_settings)
        route = add("capabilities.web", web.network)
        add("capabilities.web.search_by_kimi", web.search_by_kimi.network, route)

        execution = env.parse_section("execution", parse_execution_settings)
        route = add("execution", execution.network)
        for interpreter in execution.interpreters:
            add(f"execution.interpreters.{interpreter.name}", interpreter.network, route)

        return {"root": root.view, "consumers": consumers}

    def _route(
        self,
        owner: str,
        policy: NetworkPolicy,
        parent: _NetworkRoute | None = None,
        *,
        source_key: str | None = None,
    ) -> _NetworkRoute:
        path = f"{owner}.network"
        resolved = (
            resolve_project_network(policy, self._environment)
            if parent is None
            else policy.resolve(parent.resolved)
        )
        return _NetworkRoute(
            path,
            resolved,
            {
                "path": path,
                "mode": policy.mode.value,
                "source": self._environment.source_id_for(source_key or path),
                "parent_path": parent.path if parent is not None else None,
                "effective": {
                    "http_proxy": _proxy_descriptor(resolved.http_proxy),
                    "https_proxy": _proxy_descriptor(resolved.https_proxy),
                    "no_proxy": [
                        item.strip()
                        for item in resolved.no_proxy.split(",")
                        if item.strip()
                    ],
                },
            },
        )


def _proxy_descriptor(value: str | None) -> JsonObject | None:
    if value is None:
        return None
    parsed = urlsplit(value)
    return {"scheme": parsed.scheme, "host": parsed.hostname, "port": parsed.port}
