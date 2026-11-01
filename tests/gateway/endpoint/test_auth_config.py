from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest

from tinysoul.gateway.endpoint import (
    EndpointContractError,
    EndpointLaunchSettings,
    EndpointSettings,
    generated_auth_text,
    load_endpoint_auth,
)
from tinysoul.infra import ConfigEnvironment, ConfigError


def test_launch_settings_have_stable_deployment_defaults() -> None:
    settings = EndpointLaunchSettings()

    assert settings.bind_host == "127.0.0.1"
    assert settings.port == 1430


@pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.20", "::"])
def test_launch_settings_allow_explicit_non_loopback_bind(host: str) -> None:
    assert EndpointLaunchSettings(bind_host=host).bind_host == host
    assert EndpointSettings(host=host, token="x" * 32).host == host


def test_launch_settings_are_loaded_from_backend_dotenv(tmp_path: Path) -> None:
    (tmp_path / "tinysoul.toml").write_text("", encoding="utf-8")
    (tmp_path / ".env").write_text(
        "TINYSOUL_ENDPOINT__BIND_HOST=192.168.1.20\n"
        "TINYSOUL_ENDPOINT__PORT=1430\n",
        encoding="utf-8",
    )

    settings = ConfigEnvironment.from_project_root(tmp_path, env={}).load_section(
        "endpoint", EndpointLaunchSettings
    )

    assert settings == EndpointLaunchSettings(bind_host="192.168.1.20", port=1430)


@pytest.mark.parametrize("value", ["localhost", "", "not-an-ip"])
def test_launch_settings_reject_non_ip_bind(value: str) -> None:
    with pytest.raises(ConfigError, match="bind host"):
        EndpointLaunchSettings(bind_host=value)


@pytest.mark.parametrize("value", [0, 65536, -1, True, "1430"])
def test_launch_settings_reject_invalid_fixed_port(value: object) -> None:
    with pytest.raises(ConfigError, match="port"):
        EndpointLaunchSettings(port=cast(int, value))


def test_generated_auth_is_loadable_and_stable_until_replaced(tmp_path: Path) -> None:
    path = tmp_path / ".auth"
    path.write_text(generated_auth_text(), encoding="utf-8")

    auth = load_endpoint_auth(tmp_path)

    assert len(auth.token) >= 32
    assert load_endpoint_auth(tmp_path) == auth


@pytest.mark.parametrize(
    "contents",
    [
        "",
        "token=short",
        "token=one\ntoken=two\n",
        "unexpected=value\n",
    ],
)
def test_auth_file_requires_one_sufficient_token(tmp_path: Path, contents: str) -> None:
    (tmp_path / ".auth").write_text(contents, encoding="utf-8")

    with pytest.raises(EndpointContractError, match="auth"):
        load_endpoint_auth(tmp_path)


def test_missing_auth_prevents_endpoint_start_configuration(tmp_path: Path) -> None:
    with pytest.raises(EndpointContractError, match="missing"):
        load_endpoint_auth(tmp_path)
