"""Project-owned interface settings and presentation assets."""

from __future__ import annotations

import asyncio
import math
import mimetypes
import tomllib
from collections.abc import Callable, Mapping
from dataclasses import dataclass, fields, replace
from enum import StrEnum
from pathlib import Path, PurePosixPath, PureWindowsPath

from tinysoul.infra.concurrency import JoinedOperations
from tinysoul.infra.config import ConfigError, ConfigFileToml
from tinysoul.infra.filesystem import FilesystemBoundaryError, resolve_under_root
from tinysoul.infra.json import JsonObject


class PresentationFailure(StrEnum):
    INVALID_CONFIG = "presentation.invalid_config"
    NOT_FOUND = "presentation.not_found"
    INVALID_PATH = "presentation.invalid_path"
    TOO_LARGE = "presentation.too_large"
    IO_FAILED = "presentation.io_failed"


class PresentationError(Exception):
    """A request-local presentation failure, never an Agent transfer."""

    def __init__(
        self, kind: PresentationFailure, message: str, *, field: str | None = None
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.field = field


class ThemeMode(StrEnum):
    LIGHT = "light"
    DARK = "dark"


class SansFont(StrEnum):
    INTER = "inter"
    SYSTEM = "system"
    SERIF = "serif"


class MonoFont(StrEnum):
    JETBRAINS = "jetbrains"
    SYSTEM = "system"
    CASCADIA = "cascadia"


class InterfaceDensity(StrEnum):
    COMPACT = "compact"
    COMFORTABLE = "comfortable"
    ROOMY = "roomy"


def _invalid(field: str) -> PresentationError:
    return PresentationError(
        PresentationFailure.INVALID_CONFIG,
        "Interface setting has an invalid value.",
        field=field,
    )


def _enum[E: StrEnum](kind: type[E], value: object, field: str) -> E:
    if not isinstance(value, str):
        raise _invalid(field)
    try:
        return kind(value)
    except ValueError as exc:
        raise _invalid(field) from exc


@dataclass(frozen=True)
class InterfaceSettings:
    theme: ThemeMode = ThemeMode.LIGHT
    font_sans: SansFont = SansFont.INTER
    font_mono: MonoFont = MonoFont.JETBRAINS
    font_size: int = 14
    line_height: float = 1.5
    density: InterfaceDensity = InterfaceDensity.COMFORTABLE
    reduced_motion: bool = False

    def __post_init__(self) -> None:
        for name, kind in (
            ("theme", ThemeMode),
            ("font_sans", SansFont),
            ("font_mono", MonoFont),
            ("density", InterfaceDensity),
        ):
            if not isinstance(getattr(self, name), kind):
                raise _invalid(name)
        if type(self.font_size) is not int or not 12 <= self.font_size <= 18:
            raise _invalid("font_size")
        if (
            type(self.line_height) not in (int, float)
            or not math.isfinite(self.line_height)
            or not 1.3 <= self.line_height <= 1.9
        ):
            raise _invalid("line_height")
        if type(self.reduced_motion) is not bool:
            raise _invalid("reduced_motion")

    @classmethod
    def from_mapping(cls, data: Mapping[str, object]) -> InterfaceSettings:
        unknown = data.keys() - {item.name for item in fields(cls)}
        if unknown:
            raise _invalid(sorted(unknown)[0])
        defaults = cls()
        size = data.get("font_size", defaults.font_size)
        height = data.get("line_height", defaults.line_height)
        motion = data.get("reduced_motion", defaults.reduced_motion)
        if not isinstance(size, int):
            raise _invalid("font_size")
        if not isinstance(height, (int, float)):
            raise _invalid("line_height")
        if not isinstance(motion, bool):
            raise _invalid("reduced_motion")
        return cls(
            theme=_enum(ThemeMode, data.get("theme", defaults.theme), "theme"),
            font_sans=_enum(
                SansFont, data.get("font_sans", defaults.font_sans), "font_sans"
            ),
            font_mono=_enum(
                MonoFont, data.get("font_mono", defaults.font_mono), "font_mono"
            ),
            font_size=size,
            line_height=height,
            density=_enum(
                InterfaceDensity, data.get("density", defaults.density), "density"
            ),
            reduced_motion=motion,
        )

    def to_json(self) -> JsonObject:
        return {
            "theme": self.theme.value,
            "font_sans": self.font_sans.value,
            "font_mono": self.font_mono.value,
            "font_size": self.font_size,
            "line_height": self.line_height,
            "density": self.density.value,
            "reduced_motion": self.reduced_motion,
        }


@dataclass(frozen=True)
class InterfaceSettingsPatch:
    theme: ThemeMode | None = None
    font_sans: SansFont | None = None
    font_mono: MonoFont | None = None
    font_size: int | None = None
    line_height: float | None = None
    density: InterfaceDensity | None = None
    reduced_motion: bool | None = None

    def __post_init__(self) -> None:
        self.apply(InterfaceSettings())

    def apply(self, settings: InterfaceSettings) -> InterfaceSettings:
        return replace(
            settings,
            theme=self.theme if self.theme is not None else settings.theme,
            font_sans=self.font_sans
            if self.font_sans is not None
            else settings.font_sans,
            font_mono=self.font_mono
            if self.font_mono is not None
            else settings.font_mono,
            font_size=self.font_size
            if self.font_size is not None
            else settings.font_size,
            line_height=self.line_height
            if self.line_height is not None
            else settings.line_height,
            density=self.density if self.density is not None else settings.density,
            reduced_motion=self.reduced_motion
            if self.reduced_motion is not None
            else settings.reduced_motion,
        )


@dataclass(frozen=True)
class InterfaceDocument:
    values: InterfaceSettings
    exists: bool

    def to_json(self) -> JsonObject:
        return {
            "id": "interface",
            "path": "configs/interface.toml",
            "exists": self.exists,
            "values": self.values.to_json(),
            "defaults": InterfaceSettings().to_json(),
        }


@dataclass(frozen=True)
class PresentationAsset:
    path: str
    media_type: str
    size: int

    def to_json(self) -> JsonObject:
        return {"path": self.path, "media_type": self.media_type, "size": self.size}


@dataclass(frozen=True)
class PresentationContent:
    data: bytes
    media_type: str


class PresentationService:
    """Read and save a project's presentation without an Agent generation."""

    def __init__(self, project_root: Path) -> None:
        self._root = project_root.resolve() / "presentation"
        self._write_lock = asyncio.Lock()

    async def configuration(self, document_id: str) -> InterfaceDocument:
        self._require_interface(document_id)
        return await self._run(self._read_interface)

    async def save_configuration(
        self, document_id: str, changes: InterfaceSettingsPatch
    ) -> InterfaceDocument:
        self._require_interface(document_id)
        async with self._write_lock:
            return await self._run(lambda: self._save_interface(changes))

    async def assets(self) -> tuple[PresentationAsset, ...]:
        return await self._run(self._list_assets)

    async def content(self, path: str, *, max_bytes: int) -> PresentationContent:
        return await self._run(lambda: self._read_content(path, max_bytes=max_bytes))

    async def _run[T](self, operation: Callable[[], T]) -> T:
        joined = JoinedOperations()
        try:
            result = await joined.run(operation)
        except (tomllib.TOMLDecodeError, ConfigError, UnicodeError) as exc:
            raise PresentationError(
                PresentationFailure.INVALID_CONFIG,
                "Project interface configuration could not be read or saved.",
            ) from exc
        except OSError as exc:
            raise PresentationError(
                PresentationFailure.IO_FAILED,
                "Project presentation files could not be accessed.",
            ) from exc
        joined.check_cancelled()
        return result

    @staticmethod
    def _require_interface(document_id: str) -> None:
        if document_id != "interface":
            raise PresentationError(
                PresentationFailure.NOT_FOUND,
                "Presentation configuration is not supported.",
            )

    def _interface_path(self) -> Path:
        return self._resolve(self._root, "configs/interface.toml")

    def _read_interface(self) -> InterfaceDocument:
        path = self._interface_path()
        document = ConfigFileToml(path)
        return InterfaceDocument(
            InterfaceSettings.from_mapping(document.data), path.exists()
        )

    def _save_interface(self, changes: InterfaceSettingsPatch) -> InterfaceDocument:
        current = self._read_interface()
        values = changes.apply(current.values)
        ConfigFileToml(self._interface_path(), data=values.to_json()).save()
        return InterfaceDocument(values, True)

    @staticmethod
    def _resolve(root: Path, path: str) -> Path:
        if (
            not path
            or PurePosixPath(path).is_absolute()
            or PureWindowsPath(path).anchor
            or ".." in PurePosixPath(path.replace("\\", "/")).parts
            or "\x00" in path
        ):
            raise PresentationError(
                PresentationFailure.INVALID_PATH, "Invalid presentation path."
            )
        try:
            return resolve_under_root(root, path)
        except FilesystemBoundaryError as exc:
            raise PresentationError(
                PresentationFailure.INVALID_PATH,
                "Presentation path leaves its directory.",
            ) from exc

    def _list_assets(self) -> tuple[PresentationAsset, ...]:
        root = self._resolve(self._root, "assets")
        result: list[PresentationAsset] = []
        for path in sorted(root.rglob("*")):
            relative = path.relative_to(root).as_posix()
            resolved = self._resolve(root, relative)
            if resolved.is_file():
                result.append(
                    PresentationAsset(
                        relative, self._media_type(path), resolved.stat().st_size
                    )
                )
        return tuple(result)

    def _read_content(self, path: str, *, max_bytes: int) -> PresentationContent:
        root = self._resolve(self._root, "assets")
        target = self._resolve(root, path)
        if not target.is_file():
            raise PresentationError(
                PresentationFailure.NOT_FOUND, "Presentation asset was not found."
            )
        with target.open("rb") as stream:
            data = stream.read(max_bytes + 1)
        if len(data) > max_bytes:
            raise PresentationError(
                PresentationFailure.TOO_LARGE,
                "Presentation asset exceeds the read limit.",
            )
        return PresentationContent(data, self._media_type(target))

    @staticmethod
    def _media_type(path: Path) -> str:
        return mimetypes.guess_type(path.name)[0] or "application/octet-stream"
