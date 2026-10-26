from __future__ import annotations
from pathlib import Path
import pytest
from tinysoul.agent.composition.builder import standard_agent
from tinysoul.agent.config import AgentSettings
from tinysoul.kernel.loop import LoopSettings
from tinysoul.runtime import RUNTIME_STARTUP_FAILED, RuntimeException
from tests.agent.composition.support import (
    FakeLLM,
    _test_config,
)

pytestmark = pytest.mark.integration


async def test_agent_builder_cleans_project_capability_staging_on_startup(
    tmp_path: Path,
) -> None:
    stale = tmp_path / "runtime" / ".staging" / "web-interrupted" / "source.html"
    stale.parent.mkdir(parents=True)
    stale.write_text("stale", encoding="utf-8")
    config = _test_config(
        tmp_path,
        overrides={
            "capabilities.resource.convert_with_markitdown.enabled": False,
            "capabilities.resource.convert_with_pypdf.enabled": False,
            "capabilities.web.search_by_kimi.enabled": False,
            "capabilities.web.discover_pages.enabled": False,
            "capabilities.web.fetch_with_defuddle.enabled": False,
            "capabilities.web.fetch_with_trafilatura.enabled": False,
        },
    )

    (
        await standard_agent(root=tmp_path)
        .with_config_environment(config)
        .with_agent_settings(AgentSettings(interactive=False))
        .with_llm_runner(FakeLLM(()))
        .build()
        .build_runtime()
    )

    staging = tmp_path / "runtime" / ".staging"
    assert staging.is_dir()
    assert tuple(staging.iterdir()) == ()


async def test_agent_builder_missing_agent_is_context_startup_failure(
    tmp_path: Path,
) -> None:
    config = _test_config(
        tmp_path,
        {"home.root": str(tmp_path / "missing_home")},
    )

    with pytest.raises(RuntimeException) as raised:
        (
            await standard_agent(root=tmp_path)
            .with_config_environment(config)
            .with_agent_settings(AgentSettings(interactive=False))
            .with_llm_runner(FakeLLM(()))
            .build()
            .build_runtime()
        )

    exc = raised.value
    assert exc.reason == RUNTIME_STARTUP_FAILED
    assert exc.payload["module"] == "home"


@pytest.mark.parametrize(
    ("overrides", "module", "key", "kind"),
    (
        ({"home.max_read_chars": 0}, "home", "home.max_read_chars", None),
        (
            {"infra.model_services.providers": 0},
            "agent",
            "providers",
            "agent.configuration_failed",
        ),
        (
            {"workspace.max_files": 0},
            "workspace",
            "workspace.max_files",
            None,
        ),
        (
            {"execution.max_source_chars": 0},
            "execution",
            "execution.max_source_chars",
            "execution.configuration_failed",
        ),
        (
            {
                "execution.enabled": True,
                "execution.interpreters.python.executable": "tinysoul-missing-interpreter",
            },
            "execution",
            "execution.interpreters.python.executable",
            "execution.configuration_failed",
        ),
        (
            {"jobs.retained_capacity": 0},
            "jobs",
            "jobs.retained_capacity",
            "jobs.configuration_failed",
        ),
        (
            {"loop.max_cycles_per_turn": 0},
            "loop",
            "loop.max_cycles_per_turn",
            None,
        ),
        (
            {"loop.cycle.phase1_task_profile": "missing_profile"},
            "loop",
            "loop.cycle.phase1_task_profile",
            None,
        ),
    ),
    ids=(
        "home-config",
        "infra-config",
        "workspace-config",
        "execution-config",
        "execution-dependency",
        "jobs-config",
        "loop-config",
        "loop-task-profile",
    ),
)
async def test_agent_builder_maps_owned_startup_failure(
    tmp_path: Path,
    overrides: dict[str, object],
    module: str,
    key: str,
    kind: str | None,
) -> None:
    config = _test_config(tmp_path, overrides)

    with pytest.raises(RuntimeException) as raised:
        (
            await standard_agent(root=tmp_path)
            .with_config_environment(config)
            .with_agent_settings(AgentSettings(interactive=False))
            .with_llm_runner(FakeLLM(()))
            .build()
            .build_runtime()
        )

    exc = raised.value
    assert exc.reason == RUNTIME_STARTUP_FAILED
    assert exc.payload["module"] == module
    assert exc.payload["key"] == key
    if kind is not None:
        assert exc.payload["kind"] == kind


async def test_agent_builder_corrupt_manifest_is_workspace_startup_failure(
    tmp_path: Path,
) -> None:
    workspace_root = tmp_path / "workspace"
    manifest_path = workspace_root / ".tinysoul" / "workspace_manifest.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text("not-json", encoding="utf-8")
    config = _test_config(
        tmp_path,
        {"workspace.root": str(workspace_root)},
    )

    with pytest.raises(RuntimeException) as raised:
        (
            await standard_agent(root=tmp_path)
            .with_config_environment(config)
            .with_agent_settings(AgentSettings(interactive=False))
            .with_llm_runner(FakeLLM(()))
            .build()
            .build_runtime()
        )

    assert raised.value.reason == RUNTIME_STARTUP_FAILED
    assert raised.value.payload["module"] == "workspace"


async def test_agent_builder_does_not_map_programming_errors_to_startup_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    builder = (
        standard_agent(root=tmp_path)
        .with_config_environment(_test_config(tmp_path))
        .with_agent_settings(AgentSettings(interactive=False))
        .with_llm_runner(FakeLLM(()))
    )

    def explode(*args, **kwargs):
        raise RuntimeError("programming error")

    from tinysoul.plugins.workspace.engine import WorkspaceEngineBuilder

    monkeypatch.setattr(WorkspaceEngineBuilder, "build", explode)

    with pytest.raises(RuntimeError, match="programming error"):
        await builder.build().build_runtime()


async def test_agent_builder_agent_config_error_is_agent_startup_failure(
    tmp_path: Path,
) -> None:
    config = _test_config(tmp_path, {"agent.interactive": "bad"})

    with pytest.raises(RuntimeException) as raised:
        (
            await standard_agent(root=tmp_path)
            .with_config_environment(config)
            .with_loop_settings(LoopSettings())
            .with_llm_runner(FakeLLM(()))
            .build()
            .build_runtime()
        )

    exc = raised.value
    assert exc.reason == RUNTIME_STARTUP_FAILED
    assert exc.payload["module"] == "agent"
    assert exc.payload["key"] == "agent.interactive"


async def test_agent_builder_llm_config_error_is_llm_startup_failure(
    tmp_path: Path,
) -> None:
    config = _test_config(tmp_path, {"llm.tasks.framework.models": ["missing_model"]})

    with pytest.raises(RuntimeException) as raised:
        (
            await standard_agent(root=tmp_path)
            .with_config_environment(config)
            .with_agent_settings(AgentSettings(interactive=False))
            .with_loop_settings(LoopSettings())
            .build()
            .build_runtime()
        )

    exc = raised.value
    assert exc.reason == RUNTIME_STARTUP_FAILED
    assert exc.payload["module"] == "llm"
    assert exc.payload["key"] == "llm.tasks.framework.models"


async def test_generation_closes_owned_llm_on_build_failure_and_never_closes_borrowed(
    tmp_path: Path, monkeypatch
) -> None:
    closed: list[str] = []

    class OwnedLLM(FakeLLM):
        async def close(self):
            closed.append("owned")
            return ()

    owned = OwnedLLM(())

    async def build_llm(*args, **kwargs):
        return owned

    failure = RuntimeError("home construction failed")

    def build_home(*args, **kwargs):
        raise failure

    config = _test_config(tmp_path)
    builder = standard_agent(tmp_path).with_config_environment(config)
    monkeypatch.setattr(builder, "_build_llm", build_llm)
    from tinysoul.plugins.home.plugin import HomePlugin

    async def fail_home(*args, **kwargs):
        raise failure

    original = HomePlugin.build_generation
    monkeypatch.setattr(HomePlugin, "build_generation", fail_home)
    with pytest.raises(RuntimeError) as caught:
        await builder.build().build_runtime()
    assert caught.value is failure
    assert closed == ["owned"]

    monkeypatch.setattr(HomePlugin, "build_generation", original)
    borrowed = OwnedLLM(())
    app = (
        await standard_agent(tmp_path)
        .with_config_environment(config)
        .with_llm_runner(borrowed)
        .build()
        .build_runtime()
    )
    assert await app.close() == ()
    assert closed == ["owned"]
