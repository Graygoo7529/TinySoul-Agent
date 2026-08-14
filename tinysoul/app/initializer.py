"""Initialize or reset an editable TinySoul project from package resources."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from importlib.resources import files
from importlib.resources.abc import Traversable
from pathlib import Path, PurePosixPath
import shutil
import tempfile

from .errors import AppContractError, AppInitializationError, AppInvariantError

_INITIAL_PROJECT_DIRECTORIES = ("memory",)
_COMMON_TEMPLATE_ENTRIES = (".gitignore", "README.md", "home", "tinysoul.toml")
_CONFIG_PROFILES_DIRECTORY = "config_profiles"


class ProjectConfigProfile(StrEnum):
    """Packaged configuration sets available during project initialization."""

    STANDARD = "standard"
    DEVELOPMENT = "development"


@dataclass(frozen=True)
class ProjectInitializationOutcome:
    """Result of one successful project template installation."""

    root: Path
    file_count: int
    config_profile: ProjectConfigProfile

    def __post_init__(self) -> None:
        if not isinstance(self.root, Path) or not self.root.is_absolute():
            raise AppInvariantError("Initialized project root must be absolute")
        if (
            isinstance(self.file_count, bool)
            or not isinstance(self.file_count, int)
            or self.file_count <= 0
        ):
            raise AppInvariantError("Initialized project must contain files")
        if not isinstance(self.config_profile, ProjectConfigProfile):
            raise AppInvariantError("Initialized project config profile is invalid")


@dataclass(frozen=True)
class ProjectResetOutcome:
    """Result of one successful project template reset."""

    root: Path
    file_count: int
    config_profile: ProjectConfigProfile
    env_preserved: bool

    def __post_init__(self) -> None:
        if not isinstance(self.root, Path) or not self.root.is_absolute():
            raise AppInvariantError("Reset project root must be absolute")
        if (
            isinstance(self.file_count, bool)
            or not isinstance(self.file_count, int)
            or self.file_count <= 0
        ):
            raise AppInvariantError("Reset project must contain files")
        if not isinstance(self.config_profile, ProjectConfigProfile):
            raise AppInvariantError("Reset project config profile is invalid")
        if not isinstance(self.env_preserved, bool):
            raise AppInvariantError("Reset project env preservation state is invalid")


class ProjectInitializer:
    """Copy the package-owned project template into one empty target."""

    def initialize(
        self,
        target: Path,
        *,
        config_profile: ProjectConfigProfile = ProjectConfigProfile.STANDARD,
    ) -> ProjectInitializationOutcome:
        if not isinstance(target, Path):
            raise AppContractError("Project initialization target must be a path")
        if not isinstance(config_profile, ProjectConfigProfile):
            raise AppContractError("Project config profile is invalid")
        expanded = target.expanduser()
        if expanded.is_symlink():
            raise AppContractError(
                f"Project initialization target cannot be a symlink: {expanded}"
            )
        root = expanded.resolve()
        existed = root.exists()
        if existed:
            if root.is_symlink() or not root.is_dir():
                raise AppContractError(
                    f"Project initialization target must be a directory: {root}"
                )
            try:
                if next(root.iterdir(), None) is not None:
                    raise AppContractError(
                        f"Project initialization target must be empty: {root}"
                    )
            except OSError as exc:
                raise AppInitializationError(
                    f"Failed to inspect project initialization target: {exc}"
                ) from exc

        resources = _packaged_project_files(config_profile)
        staging = _stage_project(
            root,
            resources,
            operation="initialization",
            prefix="init",
        )

        try:
            if existed:
                root.rmdir()
            staging.replace(root)
        except OSError as exc:
            if existed and not root.exists():
                try:
                    root.mkdir(parents=True, exist_ok=True)
                except OSError:
                    pass
            raise AppInitializationError(
                f"Failed to initialize TinySoul project: {exc}"
            ) from exc
        finally:
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)

        return ProjectInitializationOutcome(
            root=root,
            file_count=len(resources),
            config_profile=config_profile,
        )


class ProjectResetter:
    """Replace one existing TinySoul project while retaining its local env file."""

    def reset(
        self,
        target: Path,
        *,
        config_profile: ProjectConfigProfile = ProjectConfigProfile.DEVELOPMENT,
    ) -> ProjectResetOutcome:
        if not isinstance(target, Path):
            raise AppContractError("Project reset target must be a path")
        if not isinstance(config_profile, ProjectConfigProfile):
            raise AppContractError("Project config profile is invalid")
        expanded = target.expanduser()
        if expanded.is_symlink():
            raise AppContractError(f"Project reset target cannot be a symlink: {expanded}")
        root = expanded.resolve()
        if not root.exists() or not root.is_dir():
            raise AppContractError(
                f"Project reset target must be an existing directory: {root}"
            )
        project_file = root / "tinysoul.toml"
        if project_file.is_symlink() or not project_file.is_file():
            raise AppContractError(
                f"Project reset target is not a TinySoul project: {root}"
            )
        try:
            cwd = Path.cwd().resolve()
        except OSError as exc:
            raise AppInitializationError(
                f"Failed to inspect the current directory before project reset: {exc}"
            ) from exc
        if cwd == root or root in cwd.parents:
            raise AppContractError(
                "Project reset must be run from outside the target directory"
            )

        env_path = root / ".env"
        env_bytes: bytes | None = None
        if env_path.is_symlink():
            raise AppContractError(
                f"Project env file cannot be a symlink during reset: {env_path}"
            )
        if env_path.exists():
            if not env_path.is_file():
                raise AppContractError(
                    f"Project env path must be a file during reset: {env_path}"
                )
            try:
                env_bytes = env_path.read_bytes()
            except OSError as exc:
                raise AppInitializationError(
                    f"Failed to preserve project env file: {exc}"
                ) from exc

        resources = _packaged_project_files(config_profile)
        staging = _stage_project(
            root,
            resources,
            operation="reset",
            prefix="reset-new",
        )
        backup: Path | None = None
        backup_has_previous_project = False
        installed = False
        try:
            if env_bytes is not None:
                (staging / ".env").write_bytes(env_bytes)
            backup = Path(
                tempfile.mkdtemp(
                    prefix=f".{root.name}.tinysoul-reset-old-",
                    dir=root.parent,
                )
            )
            backup.rmdir()
            root.replace(backup)
            backup_has_previous_project = True
            try:
                staging.replace(root)
                installed = True
            except OSError as install_exc:
                try:
                    backup.replace(root)
                    backup_has_previous_project = False
                except OSError as rollback_exc:
                    raise AppInitializationError(
                        "Failed to install reset TinySoul project and restore the "
                        f"previous project at {root}; previous data remains at "
                        f"{backup}: {rollback_exc}"
                    ) from install_exc
                raise AppInitializationError(
                    f"Failed to install reset TinySoul project: {install_exc}"
                ) from install_exc
            try:
                shutil.rmtree(backup)
                backup = None
                backup_has_previous_project = False
            except OSError as exc:
                raise AppInitializationError(
                    "TinySoul project was reset, but the previous project could not "
                    f"be removed from {backup}: {exc}"
                ) from exc
        except AppInitializationError:
            raise
        except OSError as exc:
            raise AppInitializationError(f"Failed to reset TinySoul project: {exc}") from exc
        finally:
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)
            if (
                backup is not None
                and not installed
                and not backup_has_previous_project
                and backup.exists()
            ):
                shutil.rmtree(backup, ignore_errors=True)

        return ProjectResetOutcome(
            root=root,
            file_count=len(resources),
            config_profile=config_profile,
            env_preserved=env_bytes is not None,
        )


def _packaged_project_files(
    config_profile: ProjectConfigProfile,
) -> tuple[tuple[PurePosixPath, Traversable], ...]:
    template = files("tinysoul.assets").joinpath("project")
    if not template.is_dir():
        raise AppInvariantError("Packaged TinySoul project template is missing")
    resources = (
        *_project_template_files(template, config_profile=config_profile),
        *_packaged_action_catalog_files(),
    )
    if not resources:
        raise AppInvariantError("Packaged TinySoul project template is empty")
    return resources


def _packaged_action_catalog_files() -> tuple[tuple[PurePosixPath, Traversable], ...]:
    catalog = files("tinysoul.action").joinpath("catalog")
    if not catalog.is_dir():
        raise AppInvariantError("Packaged Action catalog template is missing")
    resources = _template_files(
        catalog,
        PurePosixPath("configs/action/catalog"),
    )
    if not resources:
        raise AppInvariantError("Packaged Action catalog template is empty")
    return resources


def _stage_project(
    root: Path,
    resources: tuple[tuple[PurePosixPath, Traversable], ...],
    *,
    operation: str,
    prefix: str,
) -> Path:
    staging: Path | None = None
    try:
        root.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(
            tempfile.mkdtemp(
                prefix=f".{root.name}.tinysoul-{prefix}-",
                dir=root.parent,
            )
        )
        for relative in _INITIAL_PROJECT_DIRECTORIES:
            (staging / relative).mkdir(parents=True, exist_ok=True)
        for relative, resource in resources:
            destination = staging.joinpath(*relative.parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(resource.read_bytes())
    except OSError as exc:
        if staging is not None and staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        raise AppInitializationError(
            f"Failed to prepare project {operation} directory: {exc}"
        ) from exc
    if staging is None:
        raise AppInvariantError("Project staging directory was not created")
    return staging


def _project_template_files(
    root: Traversable,
    *,
    config_profile: ProjectConfigProfile,
) -> tuple[tuple[PurePosixPath, Traversable], ...]:
    resources: list[tuple[PurePosixPath, Traversable]] = []
    for name in _COMMON_TEMPLATE_ENTRIES:
        entry = root.joinpath(name)
        relative = PurePosixPath(name)
        if entry.is_dir():
            resources.extend(_template_files(entry, relative))
        elif entry.is_file():
            resources.append((relative, entry))
        else:
            raise AppInvariantError(
                f"Packaged TinySoul common template entry is missing: {name}"
            )

    profile_root = root.joinpath(
        _CONFIG_PROFILES_DIRECTORY,
        config_profile.value,
    )
    if not profile_root.is_dir():
        raise AppInvariantError(
            f"Packaged TinySoul config profile is missing: {config_profile.value}"
        )
    profile_resources = _template_files(profile_root)
    if not profile_resources:
        raise AppInvariantError(
            f"Packaged TinySoul config profile is empty: {config_profile.value}"
        )
    resources.extend(profile_resources)

    by_path: dict[PurePosixPath, Traversable] = {}
    for relative, resource in resources:
        if relative in by_path:
            raise AppInvariantError(
                f"Packaged TinySoul template path is duplicated: {relative}"
            )
        by_path[relative] = resource
    required = (
        PurePosixPath(".env.example"),
        PurePosixPath(".gitignore"),
        PurePosixPath("README.md"),
        PurePosixPath("tinysoul.toml"),
    )
    for relative in required:
        if relative not in by_path:
            raise AppInvariantError(
                f"Packaged TinySoul template entry is missing: {relative}"
            )
    if not any(relative.parts[0] == "configs" for relative in by_path):
        raise AppInvariantError("Packaged TinySoul config profile has no configs")
    if not any(relative.parts[0] == "home" for relative in by_path):
        raise AppInvariantError("Packaged TinySoul common template has no Home")
    return tuple((relative, by_path[relative]) for relative in sorted(by_path))


def _template_files(
    root: Traversable,
    prefix: PurePosixPath = PurePosixPath(),
) -> tuple[tuple[PurePosixPath, Traversable], ...]:
    result: list[tuple[PurePosixPath, Traversable]] = []
    try:
        children = sorted(root.iterdir(), key=lambda item: item.name)
    except OSError as exc:
        raise AppInvariantError(
            f"Failed to inspect packaged TinySoul project template: {exc}"
        ) from exc
    for child in children:
        relative = prefix / child.name
        if child.is_dir():
            result.extend(_template_files(child, relative))
        elif child.is_file():
            result.append((relative, child))
        else:
            raise AppInvariantError(
                f"Unsupported packaged project template entry: {relative}"
            )
    return tuple(result)
