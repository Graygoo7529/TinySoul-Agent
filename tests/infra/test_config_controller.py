from __future__ import annotations

from pathlib import Path

import pytest

from tinysoul.infra.config import ConfigController, ConfigEnvironment, ConfigMutation
from tinysoul.infra.config import ConfigError, PreparedConfigActivation


def _project(root: Path) -> ConfigEnvironment:
    config_dir = root / "configs"
    config_dir.mkdir(parents=True)
    (root / "tinysoul.toml").write_text(
        '[config]\ninclude = ["configs/infra.toml"]\n',
        encoding="utf-8",
    )
    (config_dir / "infra.toml").write_text(
        "[infra.embedding]\nenabled = false\n",
        encoding="utf-8",
    )
    return ConfigEnvironment.from_project_root(root, env={})


def test_config_controller_reads_sources_and_patches_toml_and_dotenv(tmp_path: Path) -> None:
    environment = _project(tmp_path)
    (tmp_path / ".env").write_text("API_KEY=old\n", encoding="utf-8")
    environment = ConfigEnvironment.from_project_root(tmp_path, env={})
    controller = ConfigController(root=tmp_path, environment=environment)

    status = controller.status()
    assert status["activity"]["can_write"] is True
    assert any(source["id"] == "project:configs/infra.toml" for source in status["sources"])

    result = controller.patch(
        (
            ConfigMutation(
                source_id="project:configs/infra.toml",
                path="infra.embedding.enabled",
                op="set",
                value=True,
            ),
            ConfigMutation(
                source_id="dotenv",
                path="API_KEY",
                op="set",
                value="new",
            ),
        )
    )

    assert result["state"] == "active"
    assert "enabled" in (tmp_path / "configs" / "infra.toml").read_text(encoding="utf-8")
    assert "API_KEY=new" in (tmp_path / ".env").read_text(encoding="utf-8")
    assert controller.environment.runtime_env["API_KEY"] == "new"
    assert controller.environment.source_id_for("infra.embedding.enabled") == (
        "project:configs/infra.toml"
    )


def test_validate_does_not_write_documents(tmp_path: Path) -> None:
    environment = _project(tmp_path)
    target = tmp_path / "configs" / "infra.toml"
    original = target.read_text(encoding="utf-8")
    controller = ConfigController(root=tmp_path, environment=environment)

    result = controller.validate(
        (
            ConfigMutation(
                source_id="project:configs/infra.toml",
                path="infra.embedding.enabled",
                op="set",
                value=True,
            ),
        )
    )

    assert result["valid"] is True
    assert target.read_text(encoding="utf-8") == original


def test_patch_rejected_while_runtime_is_active(tmp_path: Path) -> None:
    controller = ConfigController(
        root=tmp_path,
        environment=_project(tmp_path),
        activity=lambda: "user_turn",
    )

    with pytest.raises(ConfigError) as raised:
        controller.patch(
            (
                ConfigMutation(
                    source_id="project:configs/infra.toml",
                    path="infra.embedding.enabled",
                    op="set",
                    value=True,
                ),
            )
        )

    assert raised.value.key == "config.activation_unavailable"
    assert "enabled = false" in (
        tmp_path / "configs" / "infra.toml"
    ).read_text(encoding="utf-8")


def test_activation_failure_rolls_back_documents(tmp_path: Path) -> None:
    environment = _project(tmp_path)
    target = tmp_path / "configs" / "infra.toml"
    original = target.read_text(encoding="utf-8")

    def prepare(_candidate: ConfigEnvironment) -> PreparedConfigActivation:
        def fail() -> None:
            raise RuntimeError("activation failed")

        return PreparedConfigActivation(commit=fail)

    controller = ConfigController(
        root=tmp_path,
        environment=environment,
        activator=prepare,
    )

    with pytest.raises(RuntimeError, match="activation failed"):
        controller.patch(
            (
                ConfigMutation(
                    source_id="project:configs/infra.toml",
                    path="infra.embedding.enabled",
                    op="set",
                    value=True,
                ),
            )
        )

    assert target.read_text(encoding="utf-8") == original
    assert controller.environment is environment


def test_activation_observer_receives_lifecycle_events(tmp_path: Path) -> None:
    events: list[str] = []
    controller = ConfigController(
        root=tmp_path,
        environment=_project(tmp_path),
        activation_observer=lambda state, _payload: events.append(state),
    )

    controller.patch(
        (
            ConfigMutation(
                source_id="project:configs/infra.toml",
                path="infra.embedding.enabled",
                op="set",
                value=True,
            ),
        )
    )

    assert events == ["started", "completed"]


def test_process_owned_configuration_is_read_only(tmp_path: Path) -> None:
    controller = ConfigController(root=tmp_path, environment=_project(tmp_path))

    assert controller.status()["fields"]["config.include"]["writable"] is False
    for mutation in (
        ConfigMutation(
            source_id="project:tinysoul.toml",
            path="config.env_file",
            op="set",
            value="runtime.env",
        ),
        ConfigMutation(
            source_id="dotenv",
            path="TINYSOUL_APP__INTERACTIVE",
            op="set",
            value="false",
        ),
    ):
        with pytest.raises(ConfigError, match="read-only"):
            controller.patch((mutation,))
