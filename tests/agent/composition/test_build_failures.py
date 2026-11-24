from __future__ import annotations
from pathlib import Path
from unittest.mock import patch
import pytest
from tinysoul.agent.composition.builder import standard_agent
from tinysoul.agent.config import AgentSettings
from tinysoul.kernel.loop import LoopSettings
from tinysoul.runtime import RUNTIME_STARTUP_FAILED, RuntimeException
from tinysoul.infra import DependencyCheck, DependencyChecker, DependencyRequirement
from tinysoul.plugins.capabilities.web import plugin as web_plugin
from tinysoul.plugins.capabilities.resource import plugin as resource_plugin
from tests.agent.composition.support import (
    FakeLLM,
    _test_config,
)

pytestmark = pytest.mark.integration

_DISABLED_CAPABILITIES: dict[str, object] = {
    "capabilities.resource.convert_with_markitdown.enabled": False,
    "capabilities.resource.convert_with_pypdf.enabled": False,
    "capabilities.web.search_by_kimi.enabled": False,
    "capabilities.web.discover_pages.enabled": False,
    "capabilities.web.fetch_with_defuddle.enabled": False,
    "capabilities.web.fetch_with_trafilatura.enabled": False,
}


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
        .with_agent_settings(AgentSettings())
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
            .with_agent_settings(AgentSettings())
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
            {"capabilities.expand.timeout_seconds": 0},
            "expand", "capabilities.expand.timeout_seconds", "expand.configuration_failed",
        ),
        (
            {"capabilities.subagent.connect_timeout_seconds": 0},
            "subagent", "capabilities.subagent.connect_timeout_seconds", "subagent.configuration_failed",
        ),
        (
            {"capabilities.web.max_source_bytes": 0},
            "web", "capabilities.web.max_source_bytes", "web.configuration_failed",
        ),
        (
            {"capabilities.resource.max_source_bytes": 0},
            "resource", "capabilities.resource.max_source_bytes", "resource.configuration_failed",
        ),
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
        "expand-config",
        "subagent-config",
        "web-config",
        "resource-config",
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
            .with_agent_settings(AgentSettings())
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


@pytest.mark.parametrize("enabled", (False, True))
async def test_capabilities_prepare_once_per_generation_not_per_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, enabled: bool
) -> None:
    def available(
        _checker: DependencyChecker, requirements: tuple[DependencyRequirement, ...]
    ) -> tuple[DependencyCheck, ...]:
        return tuple(
            DependencyCheck(requirement_id=item.id, available=True)
            for item in requirements
        )

    monkeypatch.setattr(DependencyChecker, "check_all", available)
    config = _test_config(
        tmp_path,
        {
            **_DISABLED_CAPABILITIES,
            "capabilities.web.fetch_with_trafilatura.enabled": enabled,
            "capabilities.resource.convert_with_pypdf.enabled": enabled,
            "workspace.watch.enabled": False,
        },
    )
    with (
        patch.object(
            web_plugin, "require_web_dependencies",
            wraps=web_plugin.require_web_dependencies,
        ) as web_check,
        patch.object(
            resource_plugin, "require_resource_dependencies",
            wraps=resource_plugin.require_resource_dependencies,
        ) as resource_check,
        patch.object(
            web_plugin, "WebCapabilityService", wraps=web_plugin.WebCapabilityService,
        ) as web_service,
        patch.object(
            resource_plugin, "ResourceConversionService",
            wraps=resource_plugin.ResourceConversionService,
        ) as resource_service,
        patch.object(
            web_plugin, "register_web_actions", wraps=web_plugin.register_web_actions,
        ) as web_register,
        patch.object(
            resource_plugin, "register_resource_actions",
            wraps=resource_plugin.register_resource_actions,
        ) as resource_register,
    ):
        assembly = (
            standard_agent(tmp_path).with_config_environment(config)
            .with_llm_runner(FakeLLM(())).build()
        )
        assert not any(
            item.called for item in (web_check, resource_check, web_service, resource_service)
        )
        app = await assembly.build_runtime()
        try:
            profiles = app.generation_handle.snapshot().generation.profiles
            for check, service, register in (
                (web_check, web_service, web_register),
                (resource_check, resource_service, resource_register),
            ):
                assert check.call_count == service.call_count == int(enabled)
                calls = register.call_args_list
                assert len(calls) == len(profiles) == 3
                bound = calls[0].kwargs["service"]
                assert (bound is not None) is enabled
                assert all(call.kwargs["service"] is bound for call in calls)
        finally:
            await app.close()


@pytest.mark.parametrize(
    ("owner", "missing_dependency", "key"),
    (
        ("web", True, "capabilities.web.dependencies.kimi_search"),
        ("web", False, "capabilities.web.search_by_kimi.api_key_env"),
        ("resource", True, "capabilities.resource.dependencies.pypdf"),
    ),
)
async def test_capability_readiness_is_owned_startup_failure_even_when_hidden(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    owner: str,
    missing_dependency: bool,
    key: str,
) -> None:
    def check(
        _checker: DependencyChecker, requirements: tuple[DependencyRequirement, ...]
    ) -> tuple[DependencyCheck, ...]:
        return tuple(
            DependencyCheck(
                requirement_id=item.id,
                available=not missing_dependency,
                missing_modules=(item.modules[0],) if missing_dependency else (),
            )
            for item in requirements
        )

    monkeypatch.setattr(DependencyChecker, "check_all", check)
    enabled_key = (
        "capabilities.web.search_by_kimi.enabled" if owner == "web"
        else "capabilities.resource.convert_with_pypdf.enabled"
    )
    config = _test_config(tmp_path, {**_DISABLED_CAPABILITIES, enabled_key: True})
    action_path = tmp_path / ".config-project" / "configs" / "action" / "catalog"
    action_path /= (
        "web/actions/search_by_kimi.toml" if owner == "web"
        else "workspace/actions/convert_with_pypdf.toml"
    )
    # Hide the action in all profiles without disabling its capability.
    with action_path.open("a", encoding="utf-8") as stream:
        stream.write("\n[visibility]\ndefault = false\n")
    assembly = (
        standard_agent(tmp_path).with_config_environment(config)
        .with_llm_runner(FakeLLM(())).build()
    )
    with pytest.raises(RuntimeException) as caught:
        await assembly.build_runtime()
    assert caught.value.reason == RUNTIME_STARTUP_FAILED
    assert caught.value.payload["module"] == owner
    assert caught.value.payload["kind"] == f"{owner}.configuration_failed"
    assert caught.value.payload["key"] == key


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
            .with_agent_settings(AgentSettings())
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
        .with_agent_settings(AgentSettings())
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
    config = _test_config(tmp_path, {"agent.retained_outcomes": "bad"})

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
    assert exc.payload["key"] == "agent.retained_outcomes"


async def test_agent_builder_llm_config_error_is_llm_startup_failure(
    tmp_path: Path,
) -> None:
    config = _test_config(tmp_path, {"llm.tasks.framework.models": ["missing_model"]})

    with pytest.raises(RuntimeException) as raised:
        (
            await standard_agent(root=tmp_path)
            .with_config_environment(config)
            .with_agent_settings(AgentSettings())
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
