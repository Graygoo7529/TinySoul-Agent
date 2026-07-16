from __future__ import annotations

from tinysoul.infra import DependencyChecker, DependencyRequirement


def test_dependency_checker_reports_installed_distribution_and_module() -> None:
    result = DependencyChecker().check(
        DependencyRequirement(
            id="test.pytest",
            distributions=("pytest",),
            modules=("pytest",),
        )
    )

    assert result.available is True
    assert result.distributions[0].name == "pytest"
    assert result.missing_distributions == ()
    assert result.missing_modules == ()
    assert result.missing_executables == ()


def test_dependency_checker_reports_missing_requirements_without_importing() -> None:
    result = DependencyChecker().check(
        DependencyRequirement(
            id="test.missing",
            distributions=("tinysoul-not-installed-distribution",),
            modules=("tinysoul_not_installed_module",),
        )
    )

    assert result.available is False
    assert result.missing_distributions == ("tinysoul-not-installed-distribution",)
    assert result.missing_modules == ("tinysoul_not_installed_module",)


def test_dependency_checker_reports_executable_availability() -> None:
    available = DependencyChecker().check(
        DependencyRequirement(
            id="test.python_executable",
            executables=("python",),
        )
    )
    missing = DependencyChecker().check(
        DependencyRequirement(
            id="test.missing_executable",
            executables=("tinysoul-not-installed-executable",),
        )
    )

    assert available.available is True
    assert available.executables[0].name == "python"
    assert available.executables[0].path
    assert missing.available is False
    assert missing.missing_executables == ("tinysoul-not-installed-executable",)
