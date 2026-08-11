from __future__ import annotations

from pathlib import Path
import tomllib

import pytest

from tinysoul.app import (
    AppContractError,
    AppInitializationError,
    ProjectConfigProfile,
    ProjectInitializer,
    ProjectInstanceLease,
    ProjectResetter,
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
    assert (root / "configs" / "action.toml").is_file()
    assert not (root / "tinysoul" / "action" / "catalog").exists()
    assert (root / ".env.example").is_file()
    assert (root / "README.md").is_file()
    assert (root / "memory").is_dir()
    assert not (root / "config_profiles").exists()
    skill = root / "home" / "skills" / "tinysoul-docs" / "SKILL.md"
    assert skill.read_text(encoding="utf-8").startswith("---\ntitle:")
    identity = root / "home" / "agent" / "identity"
    assert "**Name:** tt" in (identity / "identity.md").read_text(encoding="utf-8")
    assert "Core Truths" in (identity / "soul.md").read_text(encoding="utf-8")
    user = (root / "home" / "agent" / "user" / "user.md").read_text(
        encoding="utf-8"
    )
    assert "尚未记录稳定的用户画像" in user
    assert "graygoo" not in user
    assert not (root / "home" / "what").exists()
    assert not (root / "home" / "why").exists()
    assert not (root / "home" / "how").exists()
    assert not (root / "home" / "skills_domain" / "session").exists()
    assert not (root / "home" / "skills_domain" / "context").exists()
    assert (root / "home" / "skills_action" / "core" / "answer.md").is_file()
    assert not (root / "home" / "skills_action" / "session").exists()
    assert (
        root
        / "home"
        / "skills"
        / "tinysoul-docs"
        / "references"
        / "use-tinysoul-context-and-link.md"
    ).is_file()

    providers = tomllib.loads(
        (root / "configs" / "llm" / "providers.toml").read_text(
            encoding="utf-8"
        )
    )["llm"]["providers"]
    assert providers
    assert all(spec["enabled"] is False for spec in providers.values())
    assert providers["kimi"]["api_key_envs"] == ["MOONSHOT_API_KEY"]
    models = tomllib.loads(
        (root / "configs" / "llm" / "models" / "kimi.toml").read_text(
            encoding="utf-8"
        )
    )["llm"]["models"]
    assert models["kimi_k2_7"]["provider"] == "kimi"
    assert models["kimi_k2_7"]["provider_model"] == "kimi-k2.7-code-highspeed"
    assert models["kimi_k3"]["provider"] == "kimi"
    assert models["kimi_k3"]["provider_model"] == "kimi-k3"
    openai_models = tomllib.loads(
        (root / "configs" / "llm" / "models" / "openai.toml").read_text(
            encoding="utf-8"
        )
    )["llm"]["models"]
    assert openai_models["gpt_5_6_sol"]["provider"] == "openai"
    assert openai_models["gpt_5_6_terra"]["provider"] == "openai"
    assert openai_models["gpt_5_6_luna"]["provider"] == "openai"
    web = tomllib.loads(
        (root / "configs" / "capabilities" / "web.toml").read_text(
            encoding="utf-8"
        )
    )["capabilities"]["web"]
    assert web["search_by_kimi"]["model"] == "kimi-k2.6"
    script = tomllib.loads(
        (root / "configs" / "capabilities" / "script.toml").read_text(
            encoding="utf-8"
        )
    )["capabilities"]["script"]
    assert script["enabled"] is False
    assert script["python"]["enabled"] is False
    context = tomllib.loads(
        (root / "configs" / "context.toml").read_text(encoding="utf-8")
    )["context"]
    session = tomllib.loads(
        (root / "configs" / "session.toml").read_text(encoding="utf-8")
    )["session"]
    assert context["trace_inspect_max_chars"] == 8000
    assert session["inspect_max_chars"] == 8000


def test_cli_init_development_profile_copies_enabled_development_config(
    tmp_path: Path,
) -> None:
    root = tmp_path / "agent"

    result = cli.main(
        ["init", str(root), "--config-profile", "development"]
    )

    assert result == 0
    providers = tomllib.loads(
        (root / "configs" / "llm" / "providers.toml").read_text(
            encoding="utf-8"
        )
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
        (root / "configs" / "llm" / "models" / "openai.toml").read_text(
            encoding="utf-8"
        )
    )["llm"]["models"]
    assert openai_models["gpt_5_6_sol"]["provider"] == "sublyx_proxy"
    assert openai_models["gpt_5_6_terra"]["provider"] == "sublyx_proxy"
    assert openai_models["gpt_5_6_luna"]["provider"] == "sublyx_proxy"
    shell = tomllib.loads(
        (root / "configs" / "capabilities" / "shell.toml").read_text(
            encoding="utf-8"
        )
    )["capabilities"]["shell"]
    assert shell["enabled"] is True
    assert shell["powershell"]["enabled"] is True
    assert shell["cmd"]["enabled"] is True
    web = tomllib.loads(
        (root / "configs" / "capabilities" / "web.toml").read_text(
            encoding="utf-8"
        )
    )["capabilities"]["web"]
    assert web["search_by_kimi"]["enabled"] is True
    assert web["discover_pages"]["enabled"] is True
    assert web["fetch_with_defuddle"]["enabled"] is True
    assert "SUBLYX_API_KEY=" in (root / ".env.example").read_text(
        encoding="utf-8"
    )
    user = (root / "home" / "agent" / "user" / "user.md").read_text(
        encoding="utf-8"
    )
    assert user.startswith("# graygoo\n")
    assert "graygoo 与 tt 以长期伙伴关系共同工作" in user
    assert not (root / "config_profiles").exists()


def test_project_config_profiles_share_core_home_and_customize_user_profile(
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
    standard_home = _tree_snapshot(standard / "home")
    development_home = _tree_snapshot(development / "home")
    user_path = "agent/user/user.md"
    assert set(standard_home) == set(development_home)
    assert {
        path: content for path, content in standard_home.items() if path != user_path
    } == {
        path: content for path, content in development_home.items() if path != user_path
    }
    assert b"graygoo" not in standard_home[user_path]
    assert b"graygoo" in development_home[user_path]
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


def test_cli_reset_recreates_development_project_and_preserves_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = tmp_path / "agent"
    monkeypatch.setenv("TINYSOUL_INSTANCE_DIR", str(tmp_path / "instances"))
    assert cli.main(["init", str(root)]) == 0
    original_home = (root / "home" / "agent" / "AGENT.md").read_bytes()
    env = b"SUBLYX_API_KEY=secret\r\nMOONSHOT_API_KEY=other\r\n"
    (root / ".env").write_bytes(env)
    (root / "home" / "agent" / "AGENT.md").write_text(
        "custom home", encoding="utf-8"
    )
    (root / "configs" / "llm" / "providers.toml").write_text(
        "custom config", encoding="utf-8"
    )
    for relative in (
        "runtime/session/turn.json",
        "archive/old/session.json",
        "memory/2026-07-26.md",
        "unknown-project-data.txt",
    ):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("old data", encoding="utf-8")

    result = cli.main(["reset", str(root)])

    captured = capsys.readouterr()
    assert result == 0
    assert "config profile: development" in captured.out
    assert ".env preserved" in captured.out
    assert (root / ".env").read_bytes() == env
    assert (root / "home" / "agent" / "AGENT.md").read_bytes() == original_home
    assert "# graygoo" in (
        root / "home" / "agent" / "user" / "user.md"
    ).read_text(encoding="utf-8")
    assert not (root / "runtime").exists()
    assert not (root / "archive").exists()
    assert not (root / "memory" / "2026-07-26.md").exists()
    assert not (root / "unknown-project-data.txt").exists()
    assert list((root / "memory").iterdir()) == []
    providers = tomllib.loads(
        (root / "configs" / "llm" / "providers.toml").read_text(
            encoding="utf-8"
        )
    )["llm"]["providers"]
    assert providers["sublyx_proxy"]["enabled"] is True
    assert providers["kimi"]["enabled"] is True


def test_project_resetter_rejects_nonproject_and_invalid_env(
    tmp_path: Path,
) -> None:
    nonproject = tmp_path / "nonproject"
    nonproject.mkdir()
    marker = nonproject / "keep.txt"
    marker.write_text("keep", encoding="utf-8")

    with pytest.raises(AppContractError, match="not a TinySoul project"):
        ProjectResetter().reset(nonproject)
    assert marker.read_text(encoding="utf-8") == "keep"

    root = tmp_path / "agent"
    ProjectInitializer().initialize(root)
    (root / ".env").mkdir()
    with pytest.raises(AppContractError, match="env path must be a file"):
        ProjectResetter().reset(root)
    assert (root / "tinysoul.toml").is_file()


def test_project_resetter_restores_previous_project_when_install_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "agent"
    ProjectInitializer().initialize(root)
    marker = root / "previous-data.txt"
    marker.write_text("keep", encoding="utf-8")
    original_replace = Path.replace

    def replace_with_install_failure(self: Path, target: Path) -> Path:
        if self.name.startswith(f".{root.name}.tinysoul-reset-new-"):
            raise OSError("injected install failure")
        return original_replace(self, target)

    monkeypatch.setattr(Path, "replace", replace_with_install_failure)

    with pytest.raises(AppInitializationError, match="Failed to install"):
        ProjectResetter().reset(root)
    assert marker.read_text(encoding="utf-8") == "keep"
    assert not tuple(tmp_path.glob(".agent.tinysoul-reset-*"))


def test_project_resetter_retains_previous_project_when_rollback_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "agent"
    ProjectInitializer().initialize(root)
    marker = root / "previous-data.txt"
    marker.write_text("keep", encoding="utf-8")
    original_replace = Path.replace

    def replace_with_double_failure(self: Path, target: Path) -> Path:
        if self.name.startswith(f".{root.name}.tinysoul-reset-new-"):
            raise OSError("injected install failure")
        if self.name.startswith(f".{root.name}.tinysoul-reset-old-"):
            raise OSError("injected rollback failure")
        return original_replace(self, target)

    monkeypatch.setattr(Path, "replace", replace_with_double_failure)

    with pytest.raises(AppInitializationError, match="previous data remains at"):
        ProjectResetter().reset(root)
    backup = next(tmp_path.glob(".agent.tinysoul-reset-old-*"))
    assert (backup / "previous-data.txt").read_text(encoding="utf-8") == "keep"


def test_cli_reset_rejects_project_held_by_running_instance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = tmp_path / "agent"
    ProjectInitializer().initialize(root)
    marker = root / "runtime" / "session" / "active.json"
    marker.parent.mkdir(parents=True)
    marker.write_text("active", encoding="utf-8")
    instance_directory = tmp_path / "instances"
    monkeypatch.setenv("TINYSOUL_INSTANCE_DIR", str(instance_directory))

    with ProjectInstanceLease(root, directory=instance_directory):
        result = cli.main(["reset", str(root)])

    captured = capsys.readouterr()
    assert result == 1
    assert "already running for this project" in captured.err
    assert marker.read_text(encoding="utf-8") == "active"


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
