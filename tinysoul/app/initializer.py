"""Initialize an editable TinySoul project from package resources."""

from __future__ import annotations

from dataclasses import dataclass
from importlib.resources import files
from importlib.resources.abc import Traversable
from pathlib import Path, PurePosixPath
import shutil
import tempfile

from .errors import AppContractError, AppInitializationError, AppInvariantError

_INITIAL_PROJECT_DIRECTORIES = ("memory",)


@dataclass(frozen=True)
class ProjectInitializationOutcome:
    """Result of one successful project template installation."""

    root: Path
    file_count: int

    def __post_init__(self) -> None:
        if not isinstance(self.root, Path) or not self.root.is_absolute():
            raise AppInvariantError("Initialized project root must be absolute")
        if (
            isinstance(self.file_count, bool)
            or not isinstance(self.file_count, int)
            or self.file_count <= 0
        ):
            raise AppInvariantError("Initialized project must contain files")


class ProjectInitializer:
    """Copy the package-owned project template into one empty target."""

    def initialize(self, target: Path) -> ProjectInitializationOutcome:
        if not isinstance(target, Path):
            raise AppContractError("Project initialization target must be a path")
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

        template = files("tinysoul.assets").joinpath("project")
        if not template.is_dir():
            raise AppInvariantError("Packaged TinySoul project template is missing")
        resources = _template_files(template)
        if not resources:
            raise AppInvariantError("Packaged TinySoul project template is empty")

        try:
            root.parent.mkdir(parents=True, exist_ok=True)
            staging = Path(
                tempfile.mkdtemp(
                    prefix=f".{root.name}.tinysoul-init-",
                    dir=root.parent,
                )
            )
        except OSError as exc:
            raise AppInitializationError(
                f"Failed to prepare project initialization directory: {exc}"
            ) from exc

        try:
            for relative in _INITIAL_PROJECT_DIRECTORIES:
                (staging / relative).mkdir(parents=True, exist_ok=True)
            for relative, resource in resources:
                destination = staging.joinpath(*relative.parts)
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(resource.read_bytes())
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

        return ProjectInitializationOutcome(root=root, file_count=len(resources))


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
