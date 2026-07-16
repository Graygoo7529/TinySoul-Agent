"""Python distribution and module availability checks."""

from __future__ import annotations

from dataclasses import dataclass
from importlib import metadata, util


class DependencyError(Exception):
    """Base error for dependency-checking contracts."""


class DependencyContractError(DependencyError):
    """Raised when a dependency requirement is malformed."""


@dataclass(frozen=True)
class DependencyRequirement:
    """One stable set of Python distributions and import modules."""

    id: str
    distributions: tuple[str, ...] = ()
    modules: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not self.id:
            raise DependencyContractError("Dependency requirement id must be non-empty")
        distributions = _names(self.distributions, label="distributions")
        modules = _names(self.modules, label="modules")
        if not distributions and not modules:
            raise DependencyContractError(
                "Dependency requirement must declare a distribution or module"
            )
        object.__setattr__(self, "distributions", distributions)
        object.__setattr__(self, "modules", modules)


@dataclass(frozen=True)
class DependencyDistribution:
    """One installed distribution version."""

    name: str
    version: str

    def __post_init__(self) -> None:
        if not self.name or not self.version:
            raise DependencyContractError(
                "Dependency distribution name and version must be non-empty"
            )


@dataclass(frozen=True)
class DependencyCheck:
    """Availability result for one dependency requirement."""

    requirement_id: str
    available: bool
    distributions: tuple[DependencyDistribution, ...] = ()
    missing_distributions: tuple[str, ...] = ()
    missing_modules: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.requirement_id:
            raise DependencyContractError("Dependency check id must be non-empty")
        missing = bool(self.missing_distributions or self.missing_modules)
        if self.available == missing:
            raise DependencyContractError(
                "Dependency check availability must match missing requirements"
            )


class DependencyChecker:
    """Inspect the current interpreter without installing or importing packages."""

    def check(self, requirement: DependencyRequirement) -> DependencyCheck:
        installed: list[DependencyDistribution] = []
        missing_distributions: list[str] = []
        for name in requirement.distributions:
            try:
                version = metadata.version(name)
            except metadata.PackageNotFoundError:
                missing_distributions.append(name)
            else:
                installed.append(DependencyDistribution(name=name, version=version))

        missing_modules: list[str] = []
        for name in requirement.modules:
            try:
                found = util.find_spec(name) is not None
            except (ImportError, ModuleNotFoundError, ValueError):
                found = False
            if not found:
                missing_modules.append(name)
        return DependencyCheck(
            requirement_id=requirement.id,
            available=not missing_distributions and not missing_modules,
            distributions=tuple(installed),
            missing_distributions=tuple(missing_distributions),
            missing_modules=tuple(missing_modules),
        )

    def check_all(
        self,
        requirements: tuple[DependencyRequirement, ...],
    ) -> tuple[DependencyCheck, ...]:
        return tuple(self.check(requirement) for requirement in requirements)


def _names(values: tuple[str, ...], *, label: str) -> tuple[str, ...]:
    try:
        items = tuple(values)
    except TypeError as exc:
        raise DependencyContractError(
            f"Dependency requirement {label} must be iterable"
        ) from exc
    result: list[str] = []
    for value in items:
        if not isinstance(value, str) or not value:
            raise DependencyContractError(
                f"Dependency requirement {label} must contain non-empty strings"
            )
        if value not in result:
            result.append(value)
    return tuple(result)

