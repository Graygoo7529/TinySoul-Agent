from __future__ import annotations

from pathlib import Path
import tomllib

import pytest

from tinysoul.app import (
    AppContractError,
    ProjectConfigProfile,
    ProjectInitializer,
)
from tinysoul.app import cli
from tinysoul.infra.config import parse_dotenv


def test_cli_init_copies_editable_project_without_provider_selection(
    tmp_path: Path,
) -> None:
    root = tmp_path / "agent"

    result = cli.main(["init", str(root)])

    assert result == 0
    assert (root / "tinysoul.toml").is_file()
    assert (root / "configs" / "home.toml").is_file()
    assert not (root / "configs" / "action.toml").exists()
    assert not (root / "tinysoul" / "action" / "catalog").exists()
    assert (root / ".env.example").is_file()
    assert (root / "README.md").is_file()
    assert (root / "memory").is_dir()
    assert not (root / "config_profiles").exists()
    skill = root / "home" / "how" / "tinysoul-docs" / "SKILL.md"
    assert skill.read_text(encoding="utf-8").startswith("---\ntitle:")
    assert (root / "home" / "agent" / "user" / "user.md").is_file()
    assert (root / "home" / "what" / "entity" / "tiny-soul.md").is_file()
    assert (root / "home" / "how_domain" / "session" / "DOMAIN.md").is_file()
    assert (root / "home" / "how_action" / "core" / "answer.md").is_file()
    assert not (root / "home" / "how_action" / "session").exists()
    assert (
        root
        / "home"
        / "how"
        / "tinysoul-docs"
        / "references"
        / "use-tinysoul-context-and-link.md"
    ).is_file()

    providers = tomllib.loads(
        (root / "configs" / "llm.providers.toml").read_text(encoding="utf-8")
    )["llm"]["providers"]
    assert providers
    assert all(spec["enabled"] is False for spec in providers.values())
    assert providers["kimi"]["api_key_envs"] == ["MOONSHOT_API_KEY"]
    models = tomllib.loads(
        (root / "configs" / "llm.models" / "kimi.toml").read_text(
            encoding="utf-8"
        )
    )["llm"]["models"]
    assert models["kimi_k2_7"]["provider"] == "kimi"
    assert models["kimi_k2_7"]["provider_model"] == "kimi-k2.7-code-highspeed"
    assert models["kimi_k3"]["provider"] == "kimi"
    assert models["kimi_k3"]["provider_model"] == "kimi-k3"
    openai_models = tomllib.loads(
        (root / "configs" / "llm.models" / "openai.toml").read_text(
            encoding="utf-8"
        )
    )["llm"]["models"]
    assert openai_models["gpt_5_6_sol"]["provider"] == "openai"
    assert openai_models["gpt_5_6_terra"]["provider"] == "openai"
    assert openai_models["gpt_5_6_luna"]["provider"] == "openai"
    web = tomllib.loads(
        (root / "configs" / "capabilities.web.toml").read_text(encoding="utf-8")
    )["capabilities"]["web"]
    assert web["search_by_kimi"]["model"] == "kimi-k2.6"
    context = tomllib.loads(
        (root / "configs" / "context.toml").read_text(encoding="utf-8")
    )["context"]
    session = tomllib.loads(
        (root / "configs" / "session.toml").read_text(encoding="utf-8")
    )["session"]
    assert context["trace_recall_max_entries"] == 50
    assert session["history_page_max_chars"] == 8000
    assert session["history_page_max_entries"] == 50


def test_cli_init_development_profile_copies_enabled_development_config(
    tmp_path: Path,
) -> None:
    root = tmp_path / "agent"

    result = cli.main(
        ["init", str(root), "--config-profile", "development"]
    )

    assert result == 0
    providers = tomllib.loads(
        (root / "configs" / "llm.providers.toml").read_text(encoding="utf-8")
    )["llm"]["providers"]
    assert providers["sublyx_proxy"] == {
        "enabled": True,
        "adapter": "openai",
        "api_style": "openai_responses",
        "base_url": "https://api.sublyx.org/v1",
        "api_key_envs": ["SUBLYX_API_KEY"],
    }
    assert providers["kimi"]["enabled"] is True
    openai_models = tomllib.loads(
        (root / "configs" / "llm.models" / "openai.toml").read_text(
            encoding="utf-8"
        )
    )["llm"]["models"]
    assert openai_models["gpt_5_6_sol"]["provider"] == "sublyx_proxy"
    assert openai_models["gpt_5_6_terra"]["provider"] == "sublyx_proxy"
    assert openai_models["gpt_5_6_luna"]["provider"] == "sublyx_proxy"
    shell = tomllib.loads(
        (root / "configs" / "capabilities.shell.toml").read_text(encoding="utf-8")
    )["capabilities"]["shell"]
    assert shell["enabled"] is True
    assert shell["powershell"]["enabled"] is True
    assert shell["cmd"]["enabled"] is True
    web = tomllib.loads(
        (root / "configs" / "capabilities.web.toml").read_text(encoding="utf-8")
    )["capabilities"]["web"]
    assert web["search_by_kimi"]["enabled"] is True
    assert web["discover_pages"]["enabled"] is True
    assert web["fetch_with_defuddle"]["enabled"] is True
    assert "SUBLYX_API_KEY=" in (root / ".env.example").read_text(
        encoding="utf-8"
    )
    assert not (root / "config_profiles").exists()


def test_project_config_profiles_share_home_and_complete_config_shape(
    tmp_path: Path,
) -> None:
    standard = tmp_path / "standard"
    development = tmp_path / "development"

    standard_outcome = ProjectInitializer().initialize(standard)
    development_outcome = ProjectInitializer().initialize(
        development,
        config_profile=ProjectConfigProfile.DEVELOPMENT,
    )

    assert standard_outcome.config_profile is ProjectConfigProfile.STANDARD
    assert development_outcome.config_profile is ProjectConfigProfile.DEVELOPMENT
    assert _tree_snapshot(standard / "home") == _tree_snapshot(development / "home")
    assert set(_tree_snapshot(standard / "configs")) == set(
        _tree_snapshot(development / "configs")
    )
    for root in (standard, development):
        example = parse_dotenv(
            (root / ".env.example").read_text(encoding="utf-8")
        )
        assert example
        assert set(example.values()) == {""}
        assert set(example) == _config_environment_references(root / "configs")


def test_project_initializer_accepts_empty_directory_and_rejects_nonempty(
    tmp_path: Path,
) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()

    outcome = ProjectInitializer().initialize(empty)

    assert outcome.root == empty.resolve()
    assert outcome.file_count > 10
    marker = tmp_path / "existing" / "marker.txt"
    marker.parent.mkdir()
    marker.write_text("keep", encoding="utf-8")
    with pytest.raises(AppContractError, match="must be empty"):
        ProjectInitializer().initialize(marker.parent)
    assert marker.read_text(encoding="utf-8") == "keep"


def test_initialized_project_reports_clear_unconfigured_provider_error(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = tmp_path / "agent"
    assert cli.main(["init", str(root)]) == 0

    result = cli.main(["start", "--root", str(root), "--once", "hello"])

    captured = capsys.readouterr()
    assert result == 1
    assert "Task has no models from enabled providers" in captured.err


def _tree_snapshot(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _config_environment_references(root: Path) -> set[str]:
    references: set[str] = set()
    for path in sorted(root.rglob("*.toml")):
        references.update(
            _environment_references(
                tomllib.loads(path.read_text(encoding="utf-8"))
            )
        )
    return references


def _environment_references(value: object) -> set[str]:
    if isinstance(value, dict):
        references: set[str] = set()
        for key, child in value.items():
            if isinstance(key, str) and key.endswith("_env"):
                assert isinstance(child, str) and child
                references.add(child)
                continue
            if isinstance(key, str) and key.endswith("_envs"):
                assert isinstance(child, list)
                for item in child:
                    assert isinstance(item, str) and item
                    references.add(item)
                continue
            references.update(_environment_references(child))
        return references
    if isinstance(value, list):
        references: set[str] = set()
        for item in value:
            references.update(_environment_references(item))
        return references
    return set()
