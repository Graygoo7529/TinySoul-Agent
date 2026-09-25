from __future__ import annotations

from pathlib import Path
from typing import cast
from collections.abc import Mapping

import pytest

from tinysoul.infra.config import ConfigController, ConfigEnvironment, ConfigMutation
from tinysoul.infra.config import ConfigError, PreparedConfigActivation
from tinysoul.infra.json import JsonObject


def _project(root: Path) -> ConfigEnvironment:
    config_dir = root / "configs"
    config_dir.mkdir(parents=True)
    (root / "tinysoul.toml").write_text(
        '[config]\ninclude = ["configs/infra.toml"]\n',
        encoding="utf-8",
    )
    (config_dir / "infra.toml").write_text(
        "[capabilities.web.search_by_kimi]\nenabled = false\n",
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
        "[capabilities.web.search_by_kimi]\nenabled = false\n",
        encoding="utf-8",
    )
    (document_dir / "item.toml").write_text(
        'name = "item"\n[settings]\nenabled = false\n',
        encoding="utf-8",
    )
    (root / ".env").write_text("TOKEN=old\n", encoding="utf-8")
    return ConfigEnvironment.from_project_root(root, env={})


def test_config_status_uses_one_effective_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    environment = _project(tmp_path)
    original = environment.effective_values
    calls = 0

    def effective_values() -> dict[str, object]:
        nonlocal calls
        calls += 1
        return original()

    monkeypatch.setattr(environment, "effective_values", effective_values)
    status = ConfigController(root=tmp_path, environment=environment).status()

    assert calls == 1
    assert isinstance(status["sources"], list)
    assert isinstance(status["fields"], dict)


def test_specialized_provider_array_credentials_are_redacted(tmp_path: Path) -> None:
    environment = _project(tmp_path)
    (tmp_path / "configs" / "infra.toml").write_text(
        '[[infra.model_services.providers]]\nid = "decision"\napi_key_env = "DECISION_TOKEN"\n',
        encoding="utf-8",
    )
    (tmp_path / ".env").write_text("DECISION_TOKEN=private-value\n", encoding="utf-8")
    environment = ConfigEnvironment.from_project_root(tmp_path, env={})
    status = ConfigController(root=tmp_path, environment=environment).status()
    assert "private-value" not in str(status)
    assert "DECISION_TOKEN" in str(status)


async def test_status_redaction_and_source_precedence_refresh_after_patch_and_reload(
    tmp_path: Path,
) -> None:
    _project(tmp_path)
    config_path = tmp_path / "configs" / "infra.toml"
    config_path.write_text(
        '[capabilities.web.search_by_kimi]\nenabled = false\napi_key_env = "API__TOKEN"\n'
        '[llm.providers.local]\napi_key_envs = ["LIST_TOKEN"]\n'
        '[capabilities.expand.servers.local]\nheader_refs = {Auth = "HEADER_TOKEN"}\n',
        encoding="utf-8",
    )
    (tmp_path / ".env").write_text(
        "API__TOKEN=dotenv-value\nLIST_TOKEN=list-value\nHEADER_TOKEN=header-value\n"
        "NEXT_TOKEN=next-value\nFINAL_TOKEN=final-value\n",
        encoding="utf-8",
    )
    environment = ConfigEnvironment.from_project_root(
        tmp_path,
        env={"TINYSOUL_API__TOKEN": "environment-value"},
        overrides={"api.token": "override-value"},
    )

    async def prepare(candidate: ConfigEnvironment) -> PreparedConfigActivation:
        async def commit() -> None:
            pass

        return PreparedConfigActivation(commit=commit)

    controller = ConfigController(
        root=tmp_path, environment=environment, activator=prepare
    )

    def source_values(status: JsonObject, identity: str) -> JsonObject:
        sources = status["sources"]
        assert isinstance(sources, list)
        source = next(
            item
            for item in sources
            if isinstance(item, dict) and item["id"] == identity
        )
        assert isinstance(source, dict) and isinstance(source["values"], dict)
        return source["values"]

    status = controller.status()
    dotenv = source_values(status, "dotenv")
    assert all(
        dotenv[key] == "<redacted>"
        for key in ("API__TOKEN", "LIST_TOKEN", "HEADER_TOKEN")
    )
    for source in ("environment", "overrides"):
        assert source_values(status, source)["api.token"] == "<redacted>"
    fields = status["fields"]
    assert isinstance(fields, dict)
    assert fields["api.token"] == {
        "value": "<redacted>",
        "source": "overrides",
        "writable": False,
        "redacted": True,
    }
    assert fields["capabilities.web.search_by_kimi.enabled"] == {
        "value": False,
        "source": "project:configs/infra.toml",
        "writable": True,
    }
    await controller.patch(
        (
            ConfigMutation(
                "project:configs/infra.toml",
                "capabilities.web.search_by_kimi.api_key_env",
                "set",
                "NEXT_TOKEN",
            ),
        )
    )
    assert source_values(controller.status(), "dotenv")["NEXT_TOKEN"] == "<redacted>"
    config_path.write_text(
        config_path.read_text(encoding="utf-8").replace("NEXT_TOKEN", "FINAL_TOKEN"),
        encoding="utf-8",
    )
    await controller.reload()
    assert source_values(controller.status(), "dotenv")["FINAL_TOKEN"] == "<redacted>"


async def test_config_controller_reads_sources_and_patches_toml_and_dotenv(
    tmp_path: Path,
) -> None:
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
        isinstance(source, dict) and source.get("id") == "project:configs/infra.toml"
        for source in status["sources"]
    )

    result = await controller.patch(
        (
            ConfigMutation(
                source_id="project:configs/infra.toml",
                path="capabilities.web.search_by_kimi.enabled",
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

    assert result["state"] == "saved"
    assert "enabled" in (tmp_path / "configs" / "infra.toml").read_text(
        encoding="utf-8"
    )
    assert "API_KEY=new" in (tmp_path / ".env").read_text(encoding="utf-8")
    assert controller.environment.runtime_env["API_KEY"] == "new"
    assert controller.environment.source_id_for(
        "capabilities.web.search_by_kimi.enabled"
    ) == ("project:configs/infra.toml")


async def test_document_mutation_is_candidate_local_until_commit(
    tmp_path: Path,
) -> None:
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

    await controller.patch(
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


async def test_saved_sources_remain_saved_when_reload_fails(tmp_path: Path) -> None:
    environment = _project_with_document(tmp_path)

    async def prepare(_candidate: ConfigEnvironment) -> PreparedConfigActivation:
        async def commit() -> None:
            raise RuntimeError("fail")

        return PreparedConfigActivation(commit=commit)

    controller = ConfigController(
        root=tmp_path, environment=environment, activator=prepare
    )
    source_id = environment.document_set("test.documents").documents[0].source_id
    mutations = (
        ConfigMutation(
            "project:configs/infra.toml",
            "capabilities.web.search_by_kimi.enabled",
            "set",
            True,
        ),
        ConfigMutation(source_id, "settings.enabled", "set", True),
        ConfigMutation("dotenv", "TOKEN", "set", "new"),
    )
    assert (await controller.patch(mutations))["state"] == "saved"
    saved = controller.environment
    with pytest.raises(RuntimeError, match="fail"):
        await controller.reload()
    assert controller.environment is saved
    assert controller.status()["pending_reload"] is True
    assert "enabled = true" in (tmp_path / "configs/infra.toml").read_text(
        encoding="utf-8"
    )
    assert "enabled = true" in (tmp_path / "configs/documents/item.toml").read_text(
        encoding="utf-8"
    )
    assert "TOKEN=new" in (tmp_path / ".env").read_text(encoding="utf-8")


async def test_retirement_failure_does_not_roll_back_committed_activation(
    tmp_path: Path,
) -> None:
    environment = _project(tmp_path)
    activated: list[ConfigEnvironment] = []

    async def prepare(candidate: ConfigEnvironment) -> PreparedConfigActivation:
        async def retire():
            raise RuntimeError("private retired client failure")

        async def commit() -> None:
            activated.append(candidate)

        return PreparedConfigActivation(commit=commit, retire=retire)

    controller = ConfigController(
        root=tmp_path, environment=environment, activator=prepare
    )
    result = await controller.patch(
        (
            ConfigMutation(
                source_id="project:configs/infra.toml",
                path="capabilities.web.search_by_kimi.enabled",
                op="set",
                value=True,
            ),
        )
    )
    assert activated == []
    result = await controller.reload()
    assert result["state"] == "active"
    assert result["cleanup_diagnostics"] == [
        {"resource": "config.retirement", "error_type": "RuntimeError"}
    ]
    assert controller.environment is activated[0]
    assert "enabled = true" in (tmp_path / "configs" / "infra.toml").read_text(
        encoding="utf-8"
    )


async def test_abort_failure_preserves_primary_failure_and_saved_candidate(
    tmp_path: Path,
) -> None:
    environment = _project(tmp_path)
    primary = RuntimeError("activation failed")
    events: list[str] = []

    async def prepare(candidate: ConfigEnvironment) -> PreparedConfigActivation:
        async def commit() -> None:
            raise primary

        async def abort():
            raise OSError("private cleanup failure")

        return PreparedConfigActivation(commit=commit, abort=abort)

    controller = ConfigController(
        root=tmp_path,
        environment=environment,
        activator=prepare,
        activation_observer=lambda state, _payload: events.append(state),
    )
    await controller.patch(
        (
            ConfigMutation(
                "project:configs/infra.toml",
                "capabilities.web.search_by_kimi.enabled",
                "set",
                True,
            ),
        )
    )
    saved = controller.environment
    with pytest.raises(RuntimeError) as caught:
        await controller.reload()
    assert caught.value is primary
    assert controller.environment is saved
    assert events == ["started", "cleanup.failed", "failed"]
    assert "enabled = true" in (tmp_path / "configs/infra.toml").read_text(
        encoding="utf-8"
    )


async def test_save_allowed_while_active_but_reload_requires_idle(
    tmp_path: Path,
) -> None:
    activity = "user_turn"
    activated: list[ConfigEnvironment] = []

    async def prepare(candidate: ConfigEnvironment) -> PreparedConfigActivation:
        async def commit() -> None:
            activated.append(candidate)

        return PreparedConfigActivation(commit=commit)

    controller = ConfigController(
        root=tmp_path,
        environment=_project(tmp_path),
        activity=lambda: activity,
        activator=prepare,
    )
    await controller.patch(
        (
            ConfigMutation(
                "project:configs/infra.toml",
                "capabilities.web.search_by_kimi.enabled",
                "set",
                True,
            ),
        )
    )
    assert activated == []
    with pytest.raises(ConfigError) as raised:
        await controller.reload()
    assert raised.value.key == "config.activation_unavailable"
    activity = "idle"
    assert (await controller.reload())["state"] == "active"
    assert len(activated) == 1
    assert controller.status()["pending_reload"] is False


async def test_activation_observer_receives_only_explicit_reload_events(
    tmp_path: Path,
) -> None:
    events: list[str] = []

    async def prepare(candidate: ConfigEnvironment) -> PreparedConfigActivation:
        async def commit() -> None:
            pass

        return PreparedConfigActivation(commit=commit)

    controller = ConfigController(
        root=tmp_path,
        environment=_project(tmp_path),
        activator=prepare,
        activation_observer=lambda state, _payload: events.append(state),
    )
    await controller.patch(
        (
            ConfigMutation(
                "project:configs/infra.toml",
                "capabilities.web.search_by_kimi.enabled",
                "set",
                True,
            ),
        )
    )
    assert events == []
    await controller.reload()
    assert events == ["started", "completed"]


async def test_process_owned_configuration_is_read_only(tmp_path: Path) -> None:
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
            path="TINYSOUL_AGENT__INTERACTIVE",
            op="set",
            value="false",
        ),
    ):
        with pytest.raises(ConfigError, match="read-only"):
            await controller.patch((mutation,))


async def test_controller_creates_and_deletes_complete_config_object(
    tmp_path: Path,
) -> None:
    environment = _project(tmp_path)
    target = tmp_path / "configs" / "infra.toml"
    controller = ConfigController(root=tmp_path, environment=environment)

    await controller.patch(
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

    assert (
        controller.environment.effective_values()[
            "infra.external_services.embedding_secondary.endpoint"
        ]
        == "https://api.example.com/v1"
    )
    assert "[infra.external_services.embedding_secondary]" in target.read_text(
        encoding="utf-8"
    )

    await controller.patch(
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


async def test_controller_rejects_purely_numeric_mapping_path_segment(
    tmp_path: Path,
) -> None:
    environment = _project(tmp_path)
    target = tmp_path / "configs" / "infra.toml"
    controller = ConfigController(root=tmp_path, environment=environment)

    with pytest.raises(ConfigError, match="must not be purely numeric") as error:
        await controller.patch(
            (
                ConfigMutation(
                    source_id="project:configs/infra.toml",
                    path="llm.models.1233",
                    op="set",
                    value={"adapter": "openai_compatible_chat"},
                ),
            )
        )

    assert error.value.key == "llm.models.1233"
    assert error.value.source == str(target)


async def test_controller_deletes_object_subtree_from_each_project_source(
    tmp_path: Path,
) -> None:
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
        '[infra.external_services.embedding_secondary]\nendpoint = "https://api.example.com/v1"\n',
        encoding="utf-8",
    )
    environment = ConfigEnvironment.from_project_root(tmp_path, env={})
    controller = ConfigController(root=tmp_path, environment=environment)

    await controller.patch(
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
