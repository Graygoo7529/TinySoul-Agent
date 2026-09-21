from pathlib import Path
import sys

import pytest

from tinysoul.infra.config import (
    ConfigController,
    ConfigEnvironment,
    ConfigError,
    ConfigMutation,
)
from tinysoul.plugins.capabilities.config import parse_capabilities_settings
from tinysoul.plugins.capabilities.expand.config import validate_expand_bindings


async def test_mcp_named_collection_preserves_tool_keys_and_checks_candidate_credentials(
    tmp_path: Path,
) -> None:
    (tmp_path / "tinysoul.toml").write_text(
        '[config]\ninclude = ["expand.toml"]\n', encoding="utf-8"
    )
    (tmp_path / "expand.toml").write_text(
        "[capabilities.expand.servers.notes]\nenabled = false\n", encoding="utf-8"
    )
    (tmp_path / ".env").write_text("MCP_TOKEN=private-test-token\n", encoding="utf-8")
    config = ConfigEnvironment.from_project_root(tmp_path, env={})

    def validate(candidate: ConfigEnvironment) -> None:
        settings = candidate.parse_section("capabilities", parse_capabilities_settings)
        validate_expand_bindings(settings.expand, candidate.runtime_env)

    controller = ConfigController(root=tmp_path, environment=config, validator=validate)
    await controller.patch(
        (
            ConfigMutation(
                "project:expand.toml",
                "capabilities.expand.servers.notes",
                "set",
                {
                    "enabled": True,
                    "command": sys.executable,
                    "env_refs": {"TOKEN": "MCP_TOKEN"},
                    "tools_default": False,
                    "tools": {"notes.search": True, "123": False},
                },
            ),
        )
    )
    settings = controller.environment.reload().parse_section(
        "capabilities", parse_capabilities_settings
    )
    server = settings.expand.servers[0]
    assert (
        server.allows("notes.search")
        and not server.allows("notes")
        and not server.allows("123")
    )
    status = controller.status()
    assert "private-test-token" not in str(status) and "MCP_TOKEN" in str(status)
    before = (tmp_path / "expand.toml").read_bytes()
    with pytest.raises(ConfigError):
        await controller.patch(
            (
                ConfigMutation(
                    "project:expand.toml",
                    "capabilities.expand.servers.notes.env_refs",
                    "set",
                    {"TOKEN": "UNCONFIGURED"},
                ),
            )
        )
    assert (tmp_path / "expand.toml").read_bytes() == before
