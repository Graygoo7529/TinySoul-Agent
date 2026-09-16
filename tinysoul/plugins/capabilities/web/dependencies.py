"""Dependency and credential requirements for enabled Web actions."""

from __future__ import annotations

from collections.abc import Mapping

from tinysoul.infra import DependencyChecker, DependencyRequirement
from tinysoul.infra.config import ConfigError

from .config import WebSettings


HTTP_REQUIREMENT = DependencyRequirement(
    id="web.http",
    distributions=("httpx", "lxml"),
    modules=("httpx", "lxml"),
)
KIMI_REQUIREMENT = DependencyRequirement(
    id="web.kimi_search",
    distributions=("openai",),
    modules=("openai",),
)
CRAWLEE_REQUIREMENT = DependencyRequirement(
    id="web.discovery",
    distributions=("crawlee",),
    modules=("crawlee",),
)
DEFUDDLE_REQUIREMENT = DependencyRequirement(
    id="web.defuddle",
    executables=("defuddle",),
)
TRAFILATURA_REQUIREMENT = DependencyRequirement(
    id="web.trafilatura",
    distributions=("trafilatura",),
    modules=("trafilatura",),
)


def web_dependency_requirements(
    settings: WebSettings,
) -> tuple[DependencyRequirement, ...]:
    """Return stable requirements for enabled Web actions."""

    requirements: list[DependencyRequirement] = []
    if settings.search_by_kimi.enabled:
        requirements.append(KIMI_REQUIREMENT)
    if settings.discover_pages.enabled:
        requirements.append(CRAWLEE_REQUIREMENT)
    if (
        settings.discover_pages.enabled
        or settings.fetch_with_defuddle.enabled
        or settings.fetch_with_trafilatura.enabled
    ):
        requirements.append(HTTP_REQUIREMENT)
    if settings.fetch_with_defuddle.enabled:
        requirements.append(DEFUDDLE_REQUIREMENT)
    if settings.fetch_with_trafilatura.enabled:
        requirements.append(TRAFILATURA_REQUIREMENT)
    return tuple(requirements)


def require_web_dependencies(
    settings: WebSettings,
    *,
    checker: DependencyChecker | None = None,
) -> None:
    """Require dependencies implied by enabled Web actions."""

    effective_checker = checker or DependencyChecker()
    for result in effective_checker.check_all(web_dependency_requirements(settings)):
        if result.available:
            continue
        missing = (
            *result.missing_distributions,
            *result.missing_modules,
            *result.missing_executables,
        )
        raise ConfigError(
            "Enabled Web capability dependency is unavailable",
            key=f"capabilities.dependencies.{result.requirement_id}",
            value=list(missing),
            expected="installed distributions, importable modules, and executables",
        )


def kimi_search_api_key(
    settings: WebSettings,
    env: Mapping[str, str],
) -> str:
    """Resolve the independent Kimi Search credential for an enabled action."""

    if not settings.search_by_kimi.enabled:
        return ""
    env_name = settings.search_by_kimi.api_key_env
    value = env.get(env_name, "").strip()
    if value:
        return value
    raise ConfigError(
        "Enabled Kimi Web Search credential is unavailable",
        key="capabilities.web.search_by_kimi.api_key_env",
        value=env_name,
        expected="name of a non-empty runtime environment variable",
    )
