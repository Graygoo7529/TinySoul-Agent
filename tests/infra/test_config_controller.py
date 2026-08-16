from __future__ import annotations

from pathlib import Path
from typing import cast
from collections.abc import Mapping

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


def _project_with_document(root: Path) -> ConfigEnvironment:
    config_dir = root / "configs"
    document_dir = config_dir / "documents"
    document_dir.mkdir(parents=True)
    (root / "tinysoul.toml").write_text(
        """
        [config]
        include = ["configs/infra.toml"]

        [[config.document_sets]]
        id = "test.documents"
        include = ["configs/documents/*.toml"]
        """,
        encoding="utf-8",
    )
    (config_dir / "infra.toml").write_text(
        "[infra.embedding]\nenabled = false\n",
        encoding="utf-8",
    )
    (document_dir / "item.toml").write_text(
        'name = "item"\n[settings]\nenabled = false\n',
        encoding="utf-8",
    )
    (root / ".env").write_text("TOKEN=old\n", encoding="utf-8")
    return ConfigEnvironment.from_project_root(root, env={})


def test_config_controller_reads_sources_and_patches_toml_and_dotenv(tmp_path: Path) -> None:
    environment = _project(tmp_path)
    (tmp_path / ".env").write_text("API_KEY=old\n", encoding="utf-8")
    environment = ConfigEnvironment.from_project_root(tmp_path, env={})
    controller = ConfigController(root=tmp_path, environment=environment)

    status = controller.status()
    assert isinstance(status, dict)
    assert isinstance(status["activity"], dict)
    assert isinstance(status["sources"], list)
    assert status["activity"]["can_write"] is True
    assert any(
        isinstance(source, dict)
        and source.get("id") == "project:configs/infra.toml"
        for source in status["sources"]
    )

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


def test_document_mutation_is_candidate_local_until_commit(tmp_path: Path) -> None:
    environment = _project_with_document(tmp_path)
    target = tmp_path / "configs" / "documents" / "item.toml"
    original = target.read_text(encoding="utf-8")
    observed: list[bool] = []

    def validate(candidate: ConfigEnvironment) -> None:
        document = candidate.document_set("test.documents").documents[0]
        settings = document.data["settings"]
        assert isinstance(settings, Mapping)
        observed.append(cast(Mapping[str, object], settings)["enabled"] is True)
        assert target.read_text(encoding="utf-8") == original

    controller = ConfigController(
        root=tmp_path,
        environment=environment,
        validator=validate,
    )
    source_id = environment.document_set("test.documents").documents[0].source_id
    status = controller.status()
    sources = status["sources"]
    fields = status["fields"]
    assert isinstance(sources, list)
    assert isinstance(fields, dict)
    source_status = next(
        source
        for source in sources
        if isinstance(source, dict) and source.get("id") == source_id
    )
    assert source_status["kind"] == "project_document_toml"
    assert source_status["document_set"] == "test.documents"
    assert source_status["values"] == {}
    assert "settings.enabled" not in fields

    controller.patch(
        (
            ConfigMutation(
                source_id=source_id,
                path="settings.enabled",
                op="set",
                value=True,
            ),
        )
    )

    assert observed == [True]
    assert "enabled = true" in target.read_text(encoding="utf-8")
    assert controller.environment.document_set("test.documents").documents[0].data[
        "settings"
    ] == {"enabled": True}


def test_document_and_merged_source_roll_back_together(tmp_path: Path) -> None:
    environment = _project_with_document(tmp_path)
    merged = tmp_path / "configs" / "infra.toml"
    document = tmp_path / "configs" / "documents" / "item.toml"
    dotenv = tmp_path / ".env"
    originals = (
        merged.read_text(encoding="utf-8"),
        document.read_text(encoding="utf-8"),
        dotenv.read_text(encoding="utf-8"),
    )

    def prepare(_candidate: ConfigEnvironment) -> PreparedConfigActivation:
        return PreparedConfigActivation(commit=lambda: (_ for _ in ()).throw(RuntimeError("fail")))

    controller = ConfigController(
        root=tmp_path,
        environment=environment,
        activator=prepare,
    )
    source_id = environment.document_set("test.documents").documents[0].source_id

    with pytest.raises(RuntimeError, match="fail"):
        controller.patch(
            (
                ConfigMutation(
                    source_id="project:configs/infra.toml",
                    path="infra.embedding.enabled",
                    op="set",
                    value=True,
                ),
                ConfigMutation(
                    source_id=source_id,
                    path="settings.enabled",
                    op="set",
                    value=True,
                ),
                ConfigMutation(
                    source_id="dotenv",
                    path="TOKEN",
                    op="set",
                    value="new",
                ),
            )
        )

    assert merged.read_text(encoding="utf-8") == originals[0]
    assert document.read_text(encoding="utf-8") == originals[1]
    assert dotenv.read_text(encoding="utf-8") == originals[2]
    assert controller.environment is environment


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

    status = controller.status()
    assert isinstance(status, dict)
    assert isinstance(status["fields"], dict)
    assert isinstance(status["fields"]["config.include"], dict)
    assert status["fields"]["config.include"]["writable"] is False
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


def test_controller_creates_and_deletes_complete_config_object(tmp_path: Path) -> None:
    environment = _project(tmp_path)
    target = tmp_path / "configs" / "infra.toml"
    controller = ConfigController(root=tmp_path, environment=environment)

    controller.patch(
        (
            ConfigMutation(
                source_id="project:configs/infra.toml",
                path="infra.external_services.embedding_secondary",
                op="set",
                value={
                    "enabled": False,
                    "endpoint": "https://api.example.com/v1",
                },
            ),
        )
    )

    assert controller.environment.effective_values()[
        "infra.external_services.embedding_secondary.endpoint"
    ] == "https://api.example.com/v1"
    assert "[infra.external_services.embedding_secondary]" in target.read_text(
        encoding="utf-8"
    )

    controller.patch(
        (
            ConfigMutation(
                source_id="project:configs/infra.toml",
                path="infra.external_services.embedding_secondary",
                op="delete",
            ),
        )
    )

    assert not any(
        key.startswith("infra.external_services.embedding_secondary")
        for key in controller.environment.effective_values()
    )


def test_controller_deletes_object_subtree_from_each_project_source(tmp_path: Path) -> None:
    config_dir = tmp_path / "configs"
    config_dir.mkdir(parents=True)
    (tmp_path / "tinysoul.toml").write_text(
        '[config]\ninclude = ["configs/base.toml", "configs/overlay.toml"]\n',
        encoding="utf-8",
    )
    base = config_dir / "base.toml"
    overlay = config_dir / "overlay.toml"
    base.write_text(
        "[infra.external_services.embedding_secondary]\nenabled = false\n",
        encoding="utf-8",
    )
    overlay.write_text(
        "[infra.external_services.embedding_secondary]\nendpoint = \"https://api.example.com/v1\"\n",
        encoding="utf-8",
    )
    environment = ConfigEnvironment.from_project_root(tmp_path, env={})
    controller = ConfigController(root=tmp_path, environment=environment)

    controller.patch(
        (
            ConfigMutation(
                source_id="project:configs/base.toml",
                path="infra.external_services.embedding_secondary",
                op="delete",
            ),
            ConfigMutation(
                source_id="project:configs/overlay.toml",
                path="infra.external_services.embedding_secondary",
                op="delete",
            ),
        )
    )

    assert "embedding_secondary" not in base.read_text(encoding="utf-8")
    assert "embedding_secondary" not in overlay.read_text(encoding="utf-8")
    assert not any(
        key.startswith("infra.external_services.embedding_secondary")
        for key in controller.environment.effective_values()
    )
