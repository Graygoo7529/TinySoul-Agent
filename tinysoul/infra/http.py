"""Public HTTP transport assembly; callers own clients, timeouts and cleanup."""

import ssl
from collections.abc import Callable, Mapping
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


class _TransportRoutes[T]:
    """One client's transports, selected by the shared network policy."""

    def __init__(
        self, network: ResolvedNetwork, factory: Callable[[str | None], T]
    ) -> None:
        self._network = network
        self.transports = {
            proxy: factory(proxy)
            for proxy in dict.fromkeys(
                (None, network.http_proxy or None, network.https_proxy or None)
            )
        }

    def for_url(self, url: str) -> T:
        return self.transports[self._network.proxy_for_url(url)]


class _HttpxTransport(httpx.BaseTransport):
    def __init__(self, routes: _TransportRoutes[httpx.BaseTransport]) -> None:
        self._routes = routes

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        return self._routes.for_url(str(request.url)).handle_request(request)

    def close(self) -> None:
        for transport in self._routes.transports.values():
            transport.close()


class _HttpxAsyncTransport(httpx.AsyncBaseTransport):
    def __init__(self, routes: _TransportRoutes[httpx.AsyncBaseTransport]) -> None:
        self._routes = routes

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        return await self._routes.for_url(str(request.url)).handle_async_request(request)

    async def aclose(self) -> None:
        for transport in self._routes.transports.values():
            await transport.aclose()


class _Httpx2Transport(httpx2.BaseTransport):
    def __init__(self, routes: _TransportRoutes[httpx2.BaseTransport]) -> None:
        self._routes = routes

    def handle_request(self, request: httpx2.Request) -> httpx2.Response:
        return self._routes.for_url(str(request.url)).handle_request(request)

    def close(self) -> None:
        for transport in self._routes.transports.values():
            transport.close()


class _Httpx2AsyncTransport(httpx2.AsyncBaseTransport):
    def __init__(self, routes: _TransportRoutes[httpx2.AsyncBaseTransport]) -> None:
        self._routes = routes

    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        return await self._routes.for_url(str(request.url)).handle_async_request(request)

    async def aclose(self) -> None:
        for transport in self._routes.transports.values():
            await transport.aclose()


def httpx_mounts(
    network: ResolvedNetwork,
    *,
    limits: httpx.Limits = httpx.Limits(),
) -> dict[str, httpx.AsyncBaseTransport | None]:
    routes = _TransportRoutes[httpx.AsyncBaseTransport](
        network,
        lambda proxy: httpx.AsyncHTTPTransport(
            proxy=proxy,
            trust_env=False,
            verify=ssl.create_default_context(),
            limits=limits,
        ),
    )
    return {"all://": _HttpxAsyncTransport(routes)}


def httpx_sync_mounts(
    network: ResolvedNetwork,
    *,
    limits: httpx.Limits = httpx.Limits(),
) -> dict[str, httpx.BaseTransport | None]:
    routes = _TransportRoutes[httpx.BaseTransport](
        network,
        lambda proxy: httpx.HTTPTransport(
            proxy=proxy, trust_env=False, verify=ssl.create_default_context(), limits=limits
        ),
    )
    return {"all://": _HttpxTransport(routes)}


def httpx2_mounts(
    network: ResolvedNetwork,
    *,
    limits: httpx2.Limits = httpx2.Limits(),
) -> dict[str, httpx2.AsyncBaseTransport | None]:
    routes = _TransportRoutes[httpx2.AsyncBaseTransport](
        network,
        lambda proxy: httpx2.AsyncHTTPTransport(
            proxy=proxy,
            trust_env=False,
            verify=ssl.create_default_context(),
            limits=limits,
        ),
    )
    return {"all://": _Httpx2AsyncTransport(routes)}


def httpx2_sync_mounts(
    network: ResolvedNetwork,
    *,
    limits: httpx2.Limits = httpx2.Limits(),
) -> dict[str, httpx2.BaseTransport | None]:
    routes = _TransportRoutes[httpx2.BaseTransport](
        network,
        lambda proxy: httpx2.HTTPTransport(
            proxy=proxy, trust_env=False, verify=ssl.create_default_context(), limits=limits
        ),
    )
    return {"all://": _Httpx2Transport(routes)}
