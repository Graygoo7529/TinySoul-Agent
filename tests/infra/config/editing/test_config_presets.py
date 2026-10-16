from pathlib import Path

import pytest

from tinysoul.infra.config import (
    ConfigController,
    ConfigEnvironment,
    ConfigError,
    ConfigMutation,
    ConfigCreateSource,
    PreparedConfigActivation,
)
from tinysoul.infra.config.editing.presets import PresetDefinition


def project(root: Path) -> ConfigEnvironment:
    (root / "configs").mkdir()
    (root / "tinysoul.toml").write_text(
        '[config]\ninclude = ["configs/a.toml", "configs/b.toml"]\n', encoding="utf-8"
    )
    (root / "configs/a.toml").write_text(
        '[llm.models.a]\nfamily = "family-a"\ncollapsed = true\n'
        '[llm.tasks.main]\nmodels = ["a"]\n'
        '[llm.providers.remote]\napi_key_envs = ["PRIVATE_KEY"]\n'
        "[loop.user]\nmax_cycles = 12\n"
        '[action.models]\nbindings = [{consumer="home.search.select", implementation="llm", target="main"}]\n'
        '[action.retrieval."home.search"]\nsources = ["query", "refs"]\noperations = ["select"]\n'
        '[action.retrieval."home.search".query]\nchannels = ["lexical"]\n',
        encoding="utf-8",
    )
    (root / "configs/b.toml").write_text("", encoding="utf-8")
    (root / ".env").write_text("PRIVATE_KEY=never-capture\n", encoding="utf-8")
    return ConfigEnvironment.from_project_root(root, env={})


async def activated(candidate: ConfigEnvironment) -> PreparedConfigActivation:
    async def commit() -> None:
        pass

    return PreparedConfigActivation(commit)


async def test_apply_prepare_write_publish_and_rollback(tmp_path: Path) -> None:
    environment = project(tmp_path)
    controller = ConfigController(
        root=tmp_path, environment=environment, activator=activated
    )
    # An earlier saved edit is retained if this batch cannot publish.
    await controller.patch(
        (ConfigMutation("project:configs/a.toml", "loop.user.max_cycles", "set", 13),)
    )
    prior = (tmp_path / "configs/a.toml").read_text(encoding="utf-8")
    aborted = []

    async def prepare(candidate: ConfigEnvironment) -> PreparedConfigActivation:
        assert candidate.runtime_env["PRIVATE_KEY"] == "new-secret"
        assert (tmp_path / ".env").read_text(
            encoding="utf-8"
        ) == "PRIVATE_KEY=never-capture\n"

        async def commit() -> None:
            assert "new-secret" in (tmp_path / ".env").read_text(encoding="utf-8")
            raise ConfigError("test publication failure")

        async def abort():
            aborted.append(True)
            return ()

        return PreparedConfigActivation(commit, abort)

    controller = ConfigController(
        root=tmp_path, environment=environment, activator=prepare
    )
    with pytest.raises(ConfigError, match="publication failure"):
        await controller.apply(
            (
                ConfigMutation("dotenv", "PRIVATE_KEY", "set", "new-secret"),
                ConfigMutation(
                    "project:configs/a.toml", "loop.user.max_cycles", "set", 14
                ),
            )
        )
    assert aborted == [True]
    assert (tmp_path / "configs/a.toml").read_text(encoding="utf-8") == prior
    assert (tmp_path / ".env").read_text(
        encoding="utf-8"
    ) == "PRIVATE_KEY=never-capture\n"
    assert controller.status()["pending_reload"] is True
    assert controller.status(view="active")["fields"] != controller.status()["fields"]


async def test_preset_replaces_strategy_groups_preserves_models_and_optional_budgets(
    tmp_path: Path,
) -> None:
    environment = project(tmp_path)
    controller = ConfigController(
        root=tmp_path, environment=environment, activator=activated
    )
    preset = await controller.save_preset(name="Original", include_budgets=False)
    identity = preset["id"]
    assert isinstance(identity, str)
    persisted = (tmp_path / "configs/presets" / f"{identity}.json").read_text(
        encoding="utf-8"
    )
    assert "never-capture" not in persisted and "PRIVATE_KEY" not in persisted
    assert "llm.providers" not in persisted
    await controller.patch(
        (
            ConfigMutation(
                "project:configs/b.toml", "llm.models.b", "set", {"family": "extra"}
            ),
            ConfigMutation(
                "project:configs/a.toml", "loop.user.max_cycles", "set", 100
            ),
            ConfigMutation(
                "project:configs/a.toml",
                "action.retrieval",
                "set",
                {
                    "home.search": {
                        "sources": ["query", "refs"],
                        "operations": ["select"],
                        "query": {"channels": ["embedding"]},
                        "max_steps": 20,
                    }
                },
            ),
        )
    )
    assert controller.preset(identity)["saved_match"] is False
    result = await controller.apply(preset_id=identity)
    values = controller.environment.effective_values()
    assert result["pending_reload"] is False
    assert values["loop.user.max_cycles"] == 100
    models = controller.environment.section_tree("llm")["models"]
    assert isinstance(models, dict) and "b" in models
    policies = controller.environment.section_tree("action")["retrieval"]
    assert isinstance(policies, dict)
    assert policies["home.search"]["max_steps"] == 20
    assert policies["home.search"]["sources"] == ["query", "refs"]
    assert policies["home.search"]["query"]["channels"] == ["lexical"]
    assert controller.preset(identity)["active_match"] is True
    await controller.delete_preset(identity)
    assert controller.presets() == ()
    assert controller.environment.effective_values() == values


async def test_active_capture_and_draft_do_not_store_model_catalog(
    tmp_path: Path,
) -> None:
    environment = project(tmp_path)
    controller = ConfigController(root=tmp_path, environment=environment)
    await controller.patch(
        (
            ConfigMutation(
                "project:configs/a.toml", "llm.models.a.family", "set", "saved"
            ),
        )
    )
    preset = await controller.save_preset(
        name="active draft",
        source="active",
        mutations=(
            ConfigMutation(
                "project:configs/a.toml", "llm.models.a.collapsed", "set", False
            ),
        ),
    )
    definition = PresetDefinition.from_json(preset["definition"])
    assert "llm.models" not in definition.values
    assert "llm.models" not in (tmp_path / "configs/presets" / f"{preset['id']}.json").read_text(encoding="utf-8")
    models = controller.environment.section_tree("llm")["models"]
    assert isinstance(models, dict)
    assert models["a"]["family"] == "saved"


async def test_create_model_source_and_definition_in_one_patch(tmp_path: Path) -> None:
    (tmp_path / "configs/llm/models").mkdir(parents=True)
    (tmp_path / "tinysoul.toml").write_text(
        '[config]\ninclude = ["configs/llm/models/*.toml"]\n', encoding="utf-8"
    )
    (tmp_path / "configs/llm/models/base.toml").write_text(
        '[llm.models.base]\nfamily = "Base"\n', encoding="utf-8"
    )
    environment = ConfigEnvironment.from_project_root(tmp_path, env={})
    controller = ConfigController(root=tmp_path, environment=environment)
    source_id = "project:configs/llm/models/qwen.toml"
    await controller.patch(
        (
            ConfigCreateSource(source_id),
            ConfigMutation(
                source_id,
                "llm.models.qwen-latest",
                "set",
                {"family": "Qwen", "adapter": "openai"},
            ),
        )
    )
    assert (tmp_path / "configs/llm/models/qwen.toml").is_file()
    assert controller.environment.effective_values()["llm.models.qwen-latest.family"] == "Qwen"


async def test_create_family_source_and_include_in_one_patch(tmp_path: Path) -> None:
    (tmp_path / "configs/llm/models").mkdir(parents=True)
    (tmp_path / "tinysoul.toml").write_text(
        '[config]\ninclude = []\n', encoding="utf-8"
    )
    environment = ConfigEnvironment.from_project_root(tmp_path, env={})
    controller = ConfigController(root=tmp_path, environment=environment)
    source_id = "project:configs/llm/models/qwen.toml"
    await controller.patch(
        (
            ConfigCreateSource(source_id),
            ConfigMutation(
                "project:tinysoul.toml",
                "config.include",
                "set",
                ["configs/llm/models/*.toml"],
            ),
            ConfigMutation(
                source_id,
                "llm.models.qwen-latest",
                "set",
                {"family": "Qwen", "adapter": "openai"},
            ),
        )
    )
    assert (tmp_path / "configs/llm/models/qwen.toml").is_file()
    assert controller.environment.effective_values()["llm.models.qwen-latest.adapter"] == "openai"


@pytest.mark.parametrize(
    "activity",
    ["queued", "user_turn", "reflection_turn", "daily_transition", "config_activation"],
)
async def test_apply_requires_idle_before_writing(
    tmp_path: Path, activity: str
) -> None:
    environment = project(tmp_path)
    controller = ConfigController(
        root=tmp_path,
        environment=environment,
        activator=activated,
        activity=lambda: activity,
    )
    with pytest.raises(ConfigError) as error:
        await controller.apply(
            (
                ConfigMutation(
                    "project:configs/a.toml", "loop.user.max_cycles", "set", 99
                ),
            )
        )
    assert error.value.key == "config.activation_unavailable"
    assert controller.environment.effective_values()["loop.user.max_cycles"] == 12


async def test_readonly_source_conflict_does_not_approximate_preset(
    tmp_path: Path,
) -> None:
    project(tmp_path)
    environment = ConfigEnvironment.from_project_root(
        tmp_path, env={}, overrides={"llm.tasks.main.temperature": 0.2}
    )
    controller = ConfigController(
        root=tmp_path, environment=environment, activator=activated
    )
    preset = await controller.save_preset(name="Fixed")
    identity = preset["id"]
    assert isinstance(identity, str)
    # Reusing the project with a different read-only binding invalidates this capture.
    changed = ConfigEnvironment.from_project_root(
        tmp_path, env={}, overrides={"llm.tasks.main.temperature": 0.8}
    )
    controller = ConfigController(
        root=tmp_path, environment=changed, activator=activated
    )
    assert controller.preset(identity)["validation_issues"]
    with pytest.raises(ConfigError, match="Read-only"):
        await controller.apply(preset_id=identity)
