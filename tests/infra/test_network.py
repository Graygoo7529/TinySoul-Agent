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
    assert replace(network, no_proxy="*").routes() == {}
    assert client_headers({"User-Agent": "Explicit/1"}) == {"user-agent": "Explicit/1"}


@pytest.mark.parametrize(
    ("bypass", "pattern"),
    (
        (".example.test", "all://*example.test"),
        ("127.0.0.1", "all://127.0.0.1"),
        ("example.test:8080", "all://*example.test:8080"),
        ("::1", "all://[::1]"),
    ),
)
def test_bypass_domain_ip_and_port_routes(bypass: str, pattern: str) -> None:
    network = ResolvedNetwork("http://proxy.test:8000", None, bypass)
    assert network.routes() == {"http://": "http://proxy.test:8000", pattern: None}


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
