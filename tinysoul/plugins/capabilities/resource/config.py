"""Resource capability settings."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import cast

from tinysoul.infra.config import ConfigError, reject_unknown_keys


DEFAULT_MAX_SOURCE_BYTES = 20 * 1024 * 1024
DEFAULT_MAX_OUTPUT_CHARS = 1_000_000
DEFAULT_MAX_ASSETS = 64
DEFAULT_MAX_TOTAL_ASSET_BYTES = 50 * 1024 * 1024
DEFAULT_MAX_PDF_PAGES = 300
SUPPORTED_MARKITDOWN_FORMATS = frozenset({"pdf", "docx"})


class PdfPageRenderMode(StrEnum):
    DISABLED = "disabled"
    ON_NO_TEXT = "on_no_text"


@dataclass(frozen=True)
class MarkItDownConversionSettings:
    enabled: bool = True
    formats: tuple[str, ...] = ("pdf", "docx")
    extract_images: bool = True
    extract_attachments: bool = True

    def __post_init__(self) -> None:
        _bool(self.enabled, key="capabilities.resource.convert_with_markitdown.enabled")
        _bool(
            self.extract_images,
            key="capabilities.resource.convert_with_markitdown.extract_images",
        )
        _bool(
            self.extract_attachments,
            key="capabilities.resource.convert_with_markitdown.extract_attachments",
        )
        formats = _formats(self.formats)
        object.__setattr__(self, "formats", formats)


@dataclass(frozen=True)
class PdfConversionSettings:
    enabled: bool = True
    extract_images: bool = True
    extract_attachments: bool = True

    def __post_init__(self) -> None:
        _bool(self.enabled, key="capabilities.resource.convert_with_pypdf.enabled")
        _bool(
            self.extract_images,
            key="capabilities.resource.convert_with_pypdf.extract_images",
        )
        _bool(
            self.extract_attachments,
            key="capabilities.resource.convert_with_pypdf.extract_attachments",
        )


@dataclass(frozen=True)
class ResourceSettings:
    max_source_bytes: int = DEFAULT_MAX_SOURCE_BYTES
    max_output_chars: int = DEFAULT_MAX_OUTPUT_CHARS
    max_assets: int = DEFAULT_MAX_ASSETS
    max_total_asset_bytes: int = DEFAULT_MAX_TOTAL_ASSET_BYTES
    max_pdf_pages: int = DEFAULT_MAX_PDF_PAGES
    render_pdf_pages: PdfPageRenderMode = PdfPageRenderMode.ON_NO_TEXT
    convert_with_markitdown: MarkItDownConversionSettings = field(
        default_factory=MarkItDownConversionSettings
    )
    convert_with_pypdf: PdfConversionSettings = field(
        default_factory=PdfConversionSettings
    )

    def __post_init__(self) -> None:
        for name in (
            "max_source_bytes",
            "max_output_chars",
            "max_assets",
            "max_total_asset_bytes",
            "max_pdf_pages",
        ):
            _positive(getattr(self, name), key=f"capabilities.resource.{name}")
        if not isinstance(self.render_pdf_pages, PdfPageRenderMode):
            raise ConfigError(
                "Resource PDF render mode is invalid",
                key="capabilities.resource.render_pdf_pages",
                value=self.render_pdf_pages,
                expected="disabled | on_no_text",
            )
        if not isinstance(self.convert_with_markitdown, MarkItDownConversionSettings):
            raise ConfigError(
                "MarkItDown conversion settings are invalid",
                key="capabilities.resource.convert_with_markitdown",
            )
        if not isinstance(self.convert_with_pypdf, PdfConversionSettings):
            raise ConfigError(
                "pypdf conversion settings are invalid",
                key="capabilities.resource.convert_with_pypdf",
            )


def parse_resource_settings(tree: Mapping[str, object]) -> ResourceSettings:
    reject_unknown_keys(
        tree,
        {
            "max_source_bytes",
            "max_output_chars",
            "max_assets",
            "max_total_asset_bytes",
            "max_pdf_pages",
            "render_pdf_pages",
            "convert_with_markitdown",
            "convert_with_pypdf",
        },
        key="capabilities.resource",
    )
    return ResourceSettings(
        max_source_bytes=_int(tree, "max_source_bytes", DEFAULT_MAX_SOURCE_BYTES),
        max_output_chars=_int(tree, "max_output_chars", DEFAULT_MAX_OUTPUT_CHARS),
        max_assets=_int(tree, "max_assets", DEFAULT_MAX_ASSETS),
        max_total_asset_bytes=_int(
            tree,
            "max_total_asset_bytes",
            DEFAULT_MAX_TOTAL_ASSET_BYTES,
        ),
        max_pdf_pages=_int(tree, "max_pdf_pages", DEFAULT_MAX_PDF_PAGES),
        render_pdf_pages=_render_mode(tree.get("render_pdf_pages")),
        convert_with_markitdown=_parse_markitdown(
            tree.get("convert_with_markitdown")
        ),
        convert_with_pypdf=_parse_pypdf(tree.get("convert_with_pypdf")),
    )


def _parse_markitdown(value: object) -> MarkItDownConversionSettings:
    key = "capabilities.resource.convert_with_markitdown"
    tree = _table(value, key=key)
    reject_unknown_keys(
        tree,
        {"enabled", "formats", "extract_images", "extract_attachments"},
        key=key,
    )
    return MarkItDownConversionSettings(
        enabled=_bool_value(tree, "enabled", True, key=f"{key}.enabled"),
        formats=_str_tuple(
            tree,
            "formats",
            ("pdf", "docx"),
            key=f"{key}.formats",
        ),
        extract_images=_bool_value(
            tree,
            "extract_images",
            True,
            key=f"{key}.extract_images",
        ),
        extract_attachments=_bool_value(
            tree,
            "extract_attachments",
            True,
            key=f"{key}.extract_attachments",
        ),
    )


def _parse_pypdf(value: object) -> PdfConversionSettings:
    key = "capabilities.resource.convert_with_pypdf"
    tree = _table(value, key=key)
    reject_unknown_keys(
        tree,
        {"enabled", "extract_images", "extract_attachments"},
        key=key,
    )
    return PdfConversionSettings(
        enabled=_bool_value(tree, "enabled", True, key=f"{key}.enabled"),
        extract_images=_bool_value(
            tree,
            "extract_images",
            True,
            key=f"{key}.extract_images",
        ),
        extract_attachments=_bool_value(
            tree,
            "extract_attachments",
            True,
            key=f"{key}.extract_attachments",
        ),
    )


def _table(value: object, *, key: str) -> Mapping[str, object]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ConfigError(
            "Resource capability value must be a table",
            key=key,
            value=value,
            expected="table",
        )
    return cast(Mapping[str, object], value)


def _int(tree: Mapping[str, object], name: str, default: int) -> int:
    value = tree.get(name, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(
            "Resource capability value must be an integer",
            key=f"capabilities.resource.{name}",
            value=value,
            expected="int",
        )
    return value


def _bool_value(
    tree: Mapping[str, object],
    name: str,
    default: bool,
    *,
    key: str,
) -> bool:
    value = tree.get(name, default)
    _bool(value, key=key)
    return cast(bool, value)


def _str_tuple(
    tree: Mapping[str, object],
    name: str,
    default: tuple[str, ...],
    *,
    key: str,
) -> tuple[str, ...]:
    value = tree.get(name)
    if value is None:
        return default
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item for item in value
    ):
        raise ConfigError(
            "Resource capability value must be a list of non-empty strings",
            key=key,
            value=value,
            expected="list[str]",
        )
    return tuple(cast(list[str], value))


def _render_mode(value: object) -> PdfPageRenderMode:
    if value is None:
        return PdfPageRenderMode.ON_NO_TEXT
    if not isinstance(value, str):
        raise ConfigError(
            "Resource PDF render mode must be a string",
            key="capabilities.resource.render_pdf_pages",
            value=value,
            expected="disabled | on_no_text",
        )
    try:
        return PdfPageRenderMode(value)
    except ValueError as exc:
        raise ConfigError(
            "Resource PDF render mode is unsupported",
            key="capabilities.resource.render_pdf_pages",
            value=value,
            expected="disabled | on_no_text",
        ) from exc


def _formats(values: tuple[str, ...]) -> tuple[str, ...]:
    result: list[str] = []
    for value in values:
        normalized = value.lower()
        if normalized not in SUPPORTED_MARKITDOWN_FORMATS:
            raise ConfigError(
                "MarkItDown format is unsupported",
                key="capabilities.resource.convert_with_markitdown.formats",
                value=value,
                expected="pdf | docx",
            )
        if normalized not in result:
            result.append(normalized)
    if not result:
        raise ConfigError(
            "MarkItDown formats cannot be empty",
            key="capabilities.resource.convert_with_markitdown.formats",
            expected="non-empty list",
        )
    return tuple(result)


def _positive(value: object, *, key: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ConfigError(
            "Resource capability setting must be positive",
            key=key,
            value=value,
            expected="positive int",
        )


def _bool(value: object, *, key: str) -> None:
    if not isinstance(value, bool):
        raise ConfigError(
            "Resource capability setting must be a boolean",
            key=key,
            value=value,
            expected="bool",
        )
