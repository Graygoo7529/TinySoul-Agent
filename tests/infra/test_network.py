"""Network policy ownership, actual routing and process environment contracts."""

import os
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import httpx
import httpx2
import pytest

from tinysoul.infra.config import (
    ConfigController,
    ConfigEnvironment,
    ConfigError,
    ConfigMutation,
)
from tinysoul.infra.http import (
    client_headers,
    httpx2_mounts,
    httpx2_sync_mounts,
    httpx_mounts,
    httpx_sync_mounts,
)
from tinysoul.infra.network import (
    NetworkMode,
    NetworkPolicy,
    ResolvedNetwork,
    network_from_environment,
    parse_network,
    resolve_project_network,
)
from tinysoul.infra.settings import parse_infra_settings


def test_policy_inheritance_replacement_and_process_environment(monkeypatch):
    monkeypatch.setenv("ALL_PROXY", "http://host-proxy:8000")
    parent = network_from_environment(
        {"http_proxy": "http://project:8000", "https_proxy": "http://project:8000"},
        {"HTTP_PROXY": "http://process:8000", "http_proxy": "http://lower:8000"},
    )
    assert parent.http_proxy == "http://lower:8000"
    assert NetworkPolicy().resolve(parent) is parent
    override = parse_network(
        {"mode": "override", "https_proxy": "http://other:9000"}, key="test.network"
    ).resolve(parent)
    assert override.http_proxy is None
    direct = NetworkPolicy(NetworkMode.DIRECT).resolve(parent)
    for result in (direct, override):
        env = result.process_environment(
            {
                "PATH": "bin",
                "ALL_PROXY": "http://host:8000",
                "HTTP_PROXY": "http://host:8000",
                "TOKEN": "explicit",
            }
        )
        assert env["PATH"] == "bin" and env["TOKEN"] == "explicit"
        assert not {"all_proxy", "http_proxy"} & {name.lower() for name in env}
    assert os.environ["ALL_PROXY"] == "http://host-proxy:8000"
    assert (
        network_from_environment(
            {"ALL_PROXY": "http://fallback:8000", "http_proxy": ""}
        ).http_proxy
        is None
    )


@pytest.mark.parametrize(
    "value",
    [
        {"mode": "direct", "https_proxy": "http://proxy:8000"},
        {"mode": "override"},
        {"mode": "override", "http_proxy": "socks5://proxy:8000"},
        {
            "mode": "override",
            "http_proxy": "http://proxy:8000",
            "no_proxy": "10.0.0.0/8",
        },
    ],
)
def test_invalid_policy_reports_owner_path(value):
    with pytest.raises(ConfigError) as failure:
        parse_network(value, key="llm.providers.test.network")
    assert failure.value.key.startswith("llm.providers.test.network")


@pytest.fixture
def http_routes():
    seen = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            seen.append(self.path)
            if self.path.endswith("/redirect"):
                self.send_response(302)
                self.send_header(
                    "Location", f"http://127.0.0.1:{server.server_port}/direct"
                )
                self.end_headers()
            else:
                self.send_response(200)
                self.send_header("Content-Length", "2")
                self.end_headers()
                self.wfile.write(b"ok")

        def log_message(self, format: str, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
    )
    thread.start()
    try:
        yield server.server_port, seen
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


@pytest.mark.integration
@pytest.mark.parametrize("implementation", ["httpx", "httpx2"])
async def test_proxy_no_proxy_and_redirect_use_actual_url(http_routes, implementation):
    port, seen = http_routes
    network = ResolvedNetwork(f"http://127.0.0.1:{port}", None, "127.0.0.1")
    client = (
        httpx.AsyncClient(
            trust_env=False, mounts=httpx_mounts(network), follow_redirects=True
        )
        if implementation == "httpx"
        else httpx2.AsyncClient(
            trust_env=False, mounts=httpx2_mounts(network), follow_redirects=True
        )
    )
    async with client:
        response = await client.get("http://remote.invalid/redirect")
    assert response.text == "ok"
    assert seen == ["http://remote.invalid/redirect", "/direct"]


@pytest.mark.integration
def test_sync_transport_and_no_proxy_all(http_routes):
    port, seen = http_routes
    network = ResolvedNetwork(f"http://127.0.0.1:{port}", None, "")
    with httpx.Client(trust_env=False, mounts=httpx_sync_mounts(network)) as client:
        assert client.get("http://remote.invalid/page").text == "ok"
    assert seen == ["http://remote.invalid/page"]
    assert replace(network, no_proxy="*").proxy_for_url("http://remote.invalid/") is None
    assert client_headers({"User-Agent": "Explicit/1"}) == {"user-agent": "Explicit/1"}


@pytest.mark.parametrize(
    ("bypass", "url", "direct"),
    (
        (".example.test", "https://example.test/", True),
        ("*.example.test", "https://docs.example.test/", True),
        ("example.test", "https://otherexample.test/", False),
        ("Example.TEST.", "https://docs.example.test/", True),
        ("127.0.0.1", "http://127.0.0.1:8080/", True),
        ("127.0.0.1", "http://127.0.0.2/", False),
        ("::1", "http://[0:0:0:0:0:0:0:1]/", True),
        ("[::1]:8080", "http://[::1]:8080/", True),
        ("[::1]:8080", "http://[::1]/", False),
        ("*", "https://other.test/", True),
        ("", "https://example.test/", False),
    ),
)
def test_bypass_domain_ip_and_port_routes(bypass: str, url: str, direct: bool) -> None:
    proxy = "http://proxy.test:8000"
    network = ResolvedNetwork(proxy, proxy, bypass)
    assert network.proxy_for_url(url) == (None if direct else proxy)


@pytest.mark.parametrize("implementation", ["httpx", "httpx2"])
@pytest.mark.parametrize("asynchronous", [False, True])
async def test_route_query_matches_transport_ports_redirects_and_cleanup(
    monkeypatch, implementation, asynchronous
):
    library = httpx if implementation == "httpx" else httpx2
    plain, secure = "http://plain.test:8000", "http://secure.test:8000"
    network = ResolvedNetwork(plain, secure, "example.test:443,clear.test:80,faß.test:443")
    created, closed, seen = [], [], []
    limits = library.Limits(max_connections=7)

    def factory(*, proxy, trust_env, verify, **options):
        assert trust_env is False and verify.check_hostname
        assert options["limits"] is limits
        created.append(proxy)

        def respond(request):
            seen.append((str(request.url), proxy))
            if request.url.path == "/redirect":
                return library.Response(302, headers={"location": "https://example.test/"})
            return library.Response(200, text=proxy or "direct")

        transport = library.MockTransport(respond)

        def close():
            closed.append(proxy)

        async def aclose():
            close()

        monkeypatch.setattr(transport, "close", close)
        monkeypatch.setattr(transport, "aclose", aclose)
        return transport

    monkeypatch.setattr(
        library, "AsyncHTTPTransport" if asynchronous else "HTTPTransport", factory
    )
    cases = (
        ("https://example.test/", None),
        ("https://example.test:443/", None),
        ("https://example.test:8443/", secure),
        ("http://example.test/", plain),
        ("http://clear.test/", None),
        ("http://clear.test:80/", None),
        ("http://clear.test:8080/", plain),
        ("https://faß.test/", None),
        ("https://xn--fa-hia.test/", None),
    )
    if asynchronous:
        async_client = (
            httpx.AsyncClient(
                trust_env=False, mounts=httpx_mounts(network, limits=limits),
                follow_redirects=True,
            )
            if isinstance(limits, httpx.Limits)
            else httpx2.AsyncClient(
                trust_env=False, mounts=httpx2_mounts(network, limits=limits),
                follow_redirects=True,
            )
        )
        async with async_client as client:
            for url, expected in cases:
                assert network.proxy_for_url(url) == expected
                assert (await client.get(url)).text == (expected or "direct")
            response = await client.get("https://remote.test/redirect")
    else:
        sync_client = (
            httpx.Client(
                trust_env=False, mounts=httpx_sync_mounts(network, limits=limits),
                follow_redirects=True,
            )
            if isinstance(limits, httpx.Limits)
            else httpx2.Client(
                trust_env=False, mounts=httpx2_sync_mounts(network, limits=limits),
                follow_redirects=True,
            )
        )
        with sync_client as client:
            for url, expected in cases:
                assert network.proxy_for_url(url) == expected
                assert client.get(url).text == (expected or "direct")
            response = client.get("https://remote.test/redirect")
    assert response.text == "direct" and len(response.history) == 1
    assert seen[-2:] == [
        ("https://remote.test/redirect", secure), ("https://example.test/", None)
    ]
    assert set(created) == {None, plain, secure}
    assert closed == created


async def test_saved_network_object_replacement_and_environment_override(tmp_path):
    (tmp_path / "tinysoul.toml").write_text(
        '[infra.network]\nmode="override"\nhttps_proxy="http://project:8000"\n',
        encoding="utf-8",
    )
    (tmp_path / ".env").write_text("https_proxy=http://dotenv:9000\n", encoding="utf-8")
    environment = ConfigEnvironment.from_project_root(tmp_path, env={})

    def validate(candidate):
        settings = parse_infra_settings(candidate.section_tree("infra"))
        resolve_project_network(settings.network, candidate)

    controller = ConfigController(
        root=tmp_path, environment=environment, validator=validate
    )
    await controller.patch(
        (
            ConfigMutation(
                "project:tinysoul.toml", "infra.network", "set", {"mode": "direct"}
            ),
        )
    )
    saved = ConfigEnvironment.from_project_root(tmp_path, env={})
    assert saved.section_tree("infra")["network"] == {"mode": "direct"}
    assert (
        resolve_project_network(
            parse_infra_settings(saved.section_tree("infra")).network, saved
        ).https_proxy
        is None
    )
    overridden = ConfigEnvironment.from_project_root(
        tmp_path, env={"TINYSOUL_INFRA__NETWORK__MODE": "inherit"}
    )
    assert overridden.effective_values()["infra.network"] == {"mode": "inherit"}
    assert "infra.network.mode" not in overridden.effective_values()
    assert overridden.source_id_for("infra.network") == "environment"
    assert (
        resolve_project_network(
            parse_infra_settings(overridden.section_tree("infra")).network, overridden
        ).https_proxy
        == "http://dotenv:9000"
    )
