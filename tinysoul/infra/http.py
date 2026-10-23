"""Public HTTP transport assembly; callers own clients, timeouts and cleanup."""

import ssl
from collections.abc import Mapping
from importlib.metadata import PackageNotFoundError, version

import httpx
import httpx2

from .network import ResolvedNetwork


def user_agent() -> str:
    try:
        return f"TinySoul-Agent/{version('tinysoul')}"
    except PackageNotFoundError:
        return "TinySoul-Agent"


def merge_headers(*sources: Mapping[str, str]) -> dict[str, str]:
    """HTTP names are case insensitive; later declarations replace earlier ones."""
    return {name.lower(): value for source in sources for name, value in source.items()}


def client_headers(headers: Mapping[str, str] | None = None) -> dict[str, str]:
    return merge_headers({"user-agent": user_agent()}, headers or {})


def httpx_mounts(
    network: ResolvedNetwork,
    *,
    limits: httpx.Limits = httpx.Limits(),
) -> dict[str, httpx.AsyncBaseTransport | None]:
    return {
        pattern: httpx.AsyncHTTPTransport(
            proxy=proxy,
            trust_env=False,
            verify=ssl.create_default_context(),
            limits=limits,
        )
        if proxy
        else None
        for pattern, proxy in network.routes().items()
    }


def httpx_sync_mounts(
    network: ResolvedNetwork,
) -> dict[str, httpx.BaseTransport | None]:
    return {
        pattern: httpx.HTTPTransport(
            proxy=proxy, trust_env=False, verify=ssl.create_default_context()
        )
        if proxy
        else None
        for pattern, proxy in network.routes().items()
    }


def httpx2_mounts(
    network: ResolvedNetwork,
    *,
    limits: httpx2.Limits = httpx2.Limits(),
) -> dict[str, httpx2.AsyncBaseTransport | None]:
    return {
        pattern: httpx2.AsyncHTTPTransport(
            proxy=proxy,
            trust_env=False,
            verify=ssl.create_default_context(),
            limits=limits,
        )
        if proxy
        else None
        for pattern, proxy in network.routes().items()
    }


def httpx2_sync_mounts(
    network: ResolvedNetwork,
) -> dict[str, httpx2.BaseTransport | None]:
    return {
        pattern: httpx2.HTTPTransport(
            proxy=proxy, trust_env=False, verify=ssl.create_default_context()
        )
        if proxy
        else None
        for pattern, proxy in network.routes().items()
    }
