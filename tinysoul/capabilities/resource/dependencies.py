"""Dependency requirements implied by Resource capability settings."""

from __future__ import annotations

from tinysoul.infra import DependencyChecker, DependencyRequirement
from tinysoul.infra.config import ConfigError

from .config import ResourceSettings


MARKITDOWN_REQUIREMENT = DependencyRequirement(
    id="resource.markitdown",
    distributions=("markitdown",),
    modules=("markitdown",),
)
PYPDF_REQUIREMENT = DependencyRequirement(
    id="resource.pypdf",
    distributions=("pypdf",),
    modules=("pypdf",),
)
PDF_RENDER_REQUIREMENT = DependencyRequirement(
    id="resource.pdf_render",
    distributions=("pypdfium2", "Pillow"),
    modules=("pypdfium2", "PIL"),
)


def resource_dependency_requirements(
    settings: ResourceSettings,
) -> tuple[DependencyRequirement, ...]:
    """Return stable requirements for enabled Resource actions and features."""

    requirements: list[DependencyRequirement] = []
    markitdown = settings.convert_with_markitdown
    pypdf = settings.convert_with_pypdf
    if markitdown.enabled:
        requirements.append(MARKITDOWN_REQUIREMENT)
    if pypdf.enabled or (markitdown.enabled and "pdf" in markitdown.formats):
        requirements.append(PYPDF_REQUIREMENT)
        if settings.render_pdf_pages.value != "disabled":
            requirements.append(PDF_RENDER_REQUIREMENT)
    return tuple(requirements)


def require_resource_dependencies(
    settings: ResourceSettings,
    *,
    checker: DependencyChecker | None = None,
) -> None:
    """Require all dependencies implied by enabled Resource actions."""

    effective_checker = checker or DependencyChecker()
    for result in effective_checker.check_all(
        resource_dependency_requirements(settings)
    ):
        if result.available:
            continue
        missing = (*result.missing_distributions, *result.missing_modules)
        raise ConfigError(
            "Enabled Resource capability dependency is unavailable",
            key=f"capabilities.dependencies.{result.requirement_id}",
            value=list(missing),
            expected="installed distributions and importable modules",
        )

