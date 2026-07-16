"""Fixed subprocess worker for local document conversion."""

from __future__ import annotations

from io import BytesIO
import json
from pathlib import Path
import re
import sys
from typing import Any, cast
import zipfile


_MAX_WARNINGS = 20
_SAFE_SUFFIX = re.compile(r"^\.[a-z0-9]{1,10}$")


class WorkerFailure(Exception):
    def __init__(self, message: str, *, reason: str) -> None:
        super().__init__(message)
        self.reason = reason


class AssetCollector:
    def __init__(
        self,
        *,
        root: Path,
        link_prefix: str,
        max_assets: int,
        max_total_bytes: int,
    ) -> None:
        self._root = root
        self._link_prefix = link_prefix.rstrip("/")
        self._max_assets = max_assets
        self._max_total_bytes = max_total_bytes
        self._total_bytes = 0
        self._counts: dict[str, int] = {}
        self.items: list[dict[str, Any]] = []

    def require_capacity(self, size: int) -> None:
        """Reject an asset before an archive member is materialized in memory."""

        if isinstance(size, bool) or not isinstance(size, int) or size < 0:
            raise WorkerFailure(
                "Converted document contains an invalid asset size",
                reason="invalid_asset_size",
            )
        if len(self.items) >= self._max_assets:
            raise WorkerFailure(
                "Converted document exceeds the asset count limit",
                reason="asset_count_limit_exceeded",
            )
        if self._total_bytes + size > self._max_total_bytes:
            raise WorkerFailure(
                "Converted document exceeds the asset byte limit",
                reason="asset_bytes_limit_exceeded",
            )

    def add(
        self,
        data: bytes,
        *,
        role: str,
        suffix: str,
        label: str,
        visual: bool,
    ) -> dict[str, Any]:
        self.require_capacity(len(data))
        normalized_suffix = suffix.lower()
        if not _SAFE_SUFFIX.fullmatch(normalized_suffix):
            normalized_suffix = ".bin"
        count = self._counts.get(role, 0) + 1
        self._counts[role] = count
        filename = f"{role}-{count:03d}{normalized_suffix}"
        path = self._root / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        item = {
            "file": f"assets/{filename}",
            "link": f"{self._link_prefix}/{filename}",
            "role": role,
            "label": _safe_label(label),
            "visual": visual,
            "size": len(data),
        }
        self.items.append(item)
        self._total_bytes += len(data)
        return item


def main() -> int:
    try:
        request = _request(json.loads(sys.stdin.read()))
        response = _convert(request)
    except WorkerFailure as exc:
        print(json.dumps({"ok": False, "reason": exc.reason, "message": str(exc)}))
        return 2
    except Exception as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "reason": "worker_failed",
                    "message": "Document conversion worker failed",
                    "error_type": type(exc).__name__,
                }
            )
        )
        return 2
    print(json.dumps(response, ensure_ascii=False))
    return 0


def _convert(request: dict[str, Any]) -> dict[str, Any]:
    source = Path(request["source_path"])
    output = Path(request["output_path"])
    output.mkdir(parents=True, exist_ok=True)
    collector = AssetCollector(
        root=output / "assets",
        link_prefix=request["asset_link_prefix"],
        max_assets=request["max_assets"],
        max_total_bytes=request["max_total_asset_bytes"],
    )
    warnings: list[str] = []
    page_count = 0
    empty_pages: tuple[int, ...] = ()
    has_extracted_text = False
    suffix = request["source_suffix"]
    converter = request["converter"]

    if converter == "markitdown":
        markdown = _markitdown(source, suffix=suffix, warnings=warnings)
        has_extracted_text = _usable_text(markdown)
        if suffix == ".docx":
            _extract_docx_assets(
                source,
                collector,
                extract_images=request["extract_images"],
                extract_attachments=request["extract_attachments"],
                warnings=warnings,
            )
        elif suffix == ".pdf":
            page_texts, page_count = _extract_pdf(
                source,
                collector,
                extract_images=request["extract_images"],
                extract_attachments=request["extract_attachments"],
                max_pages=request["max_pdf_pages"],
                warnings=warnings,
            )
            empty_pages = tuple(
                index
                for index, text in enumerate(page_texts)
                if not _usable_text(text)
            )
    elif converter == "pypdf":
        page_texts, page_count = _extract_pdf(
            source,
            collector,
            extract_images=request["extract_images"],
            extract_attachments=request["extract_attachments"],
            max_pages=request["max_pdf_pages"],
            warnings=warnings,
        )
        empty_pages = tuple(
            index for index, text in enumerate(page_texts) if not _usable_text(text)
        )
        has_extracted_text = any(_usable_text(text) for text in page_texts)
        markdown = _page_markdown(source.stem, page_texts)
    else:
        raise WorkerFailure("Unknown document converter", reason="unsupported_converter")

    if request["render_pdf_pages"] == "on_no_text" and suffix == ".pdf":
        pages_to_render = empty_pages
        if not _usable_text(markdown) and page_count:
            pages_to_render = tuple(range(page_count))
        if pages_to_render:
            _render_pdf_pages(source, pages_to_render, collector, warnings=warnings)

    markdown = _append_assets(markdown, collector.items)
    if not has_extracted_text and not collector.items:
        raise WorkerFailure(
            "Document conversion produced no usable output",
            reason="no_usable_output",
        )
    if len(markdown) > request["max_output_chars"]:
        raise WorkerFailure(
            "Converted Markdown exceeds the character limit",
            reason="output_limit_exceeded",
        )
    markdown_path = output / "document.md"
    markdown_path.write_text(markdown.rstrip() + "\n", encoding="utf-8")
    visual_links = tuple(
        item["link"] for item in collector.items if item["visual"]
    )
    status = "complete"
    if visual_links and not has_extracted_text:
        status = "visual_only"
    elif collector.items and not has_extracted_text:
        status = "partial"
    elif warnings or visual_links:
        status = "partial"
    return {
        "ok": True,
        "markdown_file": "document.md",
        "assets": collector.items,
        "content_status": status,
        "visual_reference_links": list(visual_links[:16]),
        "warning_codes": warnings[:_MAX_WARNINGS],
        "page_count": page_count,
    }


def _markitdown(source: Path, *, suffix: str, warnings: list[str]) -> str:
    try:
        from markitdown import MarkItDown

        result = MarkItDown(enable_plugins=False).convert_local(
            source,
            file_extension=suffix,
        )
        return result.markdown or ""
    except Exception as exc:
        if suffix == ".pdf":
            _warning(warnings, "markitdown_text_unavailable")
            return ""
        raise WorkerFailure(
            f"MarkItDown conversion failed: {type(exc).__name__}",
            reason="markitdown_conversion_failed",
        ) from exc


def _extract_pdf(
    source: Path,
    collector: AssetCollector,
    *,
    extract_images: bool,
    extract_attachments: bool,
    max_pages: int,
    warnings: list[str],
) -> tuple[tuple[str, ...], int]:
    try:
        from pypdf import PdfReader

        reader = PdfReader(source)
        if reader.is_encrypted:
            raise WorkerFailure(
                "Encrypted PDF is not supported",
                reason="encrypted_document",
            )
        if len(reader.pages) > max_pages:
            raise WorkerFailure(
                "PDF exceeds the page limit",
                reason="page_limit_exceeded",
            )
        page_texts: list[str] = []
        for page_number, page in enumerate(reader.pages, start=1):
            try:
                page_texts.append(page.extract_text() or "")
            except Exception:
                page_texts.append("")
                _warning(warnings, "page_text_unavailable")
            if extract_images:
                try:
                    for image in page.images:
                        collector.add(
                            image.data,
                            role="image",
                            suffix=Path(image.name).suffix or ".bin",
                            label=f"Page {page_number} image",
                            visual=True,
                        )
                except Exception:
                    _warning(warnings, "page_image_extraction_failed")
        if extract_attachments:
            try:
                for name, contents in reader.attachments.items():
                    for content in contents:
                        collector.add(
                            content,
                            role="attachment",
                            suffix=Path(name).suffix or ".bin",
                            label=name,
                            visual=False,
                        )
            except Exception:
                _warning(warnings, "attachment_extraction_failed")
        return tuple(page_texts), len(reader.pages)
    except WorkerFailure:
        raise
    except Exception as exc:
        raise WorkerFailure(
            f"PDF extraction failed: {type(exc).__name__}",
            reason="pdf_extraction_failed",
        ) from exc


def _extract_docx_assets(
    source: Path,
    collector: AssetCollector,
    *,
    extract_images: bool,
    extract_attachments: bool,
    warnings: list[str],
) -> None:
    try:
        with zipfile.ZipFile(source) as archive:
            for info in archive.infolist():
                role = ""
                visual = False
                if extract_images and info.filename.startswith("word/media/"):
                    role = "image"
                    visual = True
                elif extract_attachments and info.filename.startswith("word/embeddings/"):
                    role = "attachment"
                if not role or info.is_dir():
                    continue
                collector.require_capacity(info.file_size)
                data = archive.read(info)
                if len(data) != info.file_size:
                    raise WorkerFailure(
                        "DOCX asset size does not match its archive entry",
                        reason="invalid_asset_size",
                    )
                collector.add(
                    data,
                    role=role,
                    suffix=Path(info.filename).suffix or ".bin",
                    label=Path(info.filename).name,
                    visual=visual,
                )
    except (zipfile.BadZipFile, OSError, RuntimeError):
        _warning(warnings, "docx_asset_extraction_failed")


def _render_pdf_pages(
    source: Path,
    pages: tuple[int, ...],
    collector: AssetCollector,
    *,
    warnings: list[str],
) -> None:
    try:
        import pypdfium2 as pdfium

        document = pdfium.PdfDocument(source)
        try:
            for index in pages:
                page = document[index]
                try:
                    bitmap = page.render(scale=1.5)
                    try:
                        image = bitmap.to_pil()
                        stream = BytesIO()
                        image.save(stream, format="PNG")
                    finally:
                        bitmap.close()
                    collector.add(
                        stream.getvalue(),
                        role="page",
                        suffix=".png",
                        label=f"Page {index + 1}",
                        visual=True,
                    )
                finally:
                    page.close()
        finally:
            document.close()
    except WorkerFailure:
        raise
    except Exception:
        _warning(warnings, "page_render_failed")


def _page_markdown(title: str, page_texts: tuple[str, ...]) -> str:
    parts = [f"# {_safe_label(title) or 'PDF Document'}"]
    for index, text in enumerate(page_texts, start=1):
        parts.append(f"## Page {index}")
        parts.append(text.strip() or "No usable text was extracted from this page.")
    return "\n\n".join(parts)


def _append_assets(markdown: str, assets: list[dict[str, Any]]) -> str:
    if not assets:
        return markdown
    parts = [markdown.rstrip(), "## Extracted Resources"]
    for item in assets:
        label = item["label"] or item["role"].title()
        if item["visual"]:
            parts.append(f"![{label}]({item['link']})")
        else:
            parts.append(f"- [Attachment: {label}]({item['link']})")
    return "\n\n".join(part for part in parts if part)


def _request(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise WorkerFailure("Worker request must be an object", reason="invalid_request")
    typed = cast(dict[str, Any], value)
    required_strings = (
        "converter",
        "source_path",
        "source_suffix",
        "output_path",
        "asset_link_prefix",
        "render_pdf_pages",
    )
    required_ints = (
        "max_output_chars",
        "max_assets",
        "max_total_asset_bytes",
        "max_pdf_pages",
    )
    required_bools = ("extract_images", "extract_attachments")
    for name in required_strings:
        item = typed.get(name)
        if not isinstance(item, str) or not item:
            raise WorkerFailure(
                f"Worker request field is invalid: {name}", reason="invalid_request"
            )
    for name in required_ints:
        item = typed.get(name)
        if isinstance(item, bool) or not isinstance(item, int) or item <= 0:
            raise WorkerFailure(
                f"Worker request field is invalid: {name}", reason="invalid_request"
            )
    for name in required_bools:
        if not isinstance(typed.get(name), bool):
            raise WorkerFailure(
                f"Worker request field is invalid: {name}", reason="invalid_request"
            )
    return typed


def _usable_text(value: str) -> bool:
    return any(character.isalnum() for character in value)


def _warning(warnings: list[str], value: str) -> None:
    if value not in warnings and len(warnings) < _MAX_WARNINGS:
        warnings.append(value)


def _safe_label(value: str) -> str:
    return re.sub(r"[\[\]()\r\n]+", " ", value).strip()[:160]


if __name__ == "__main__":
    raise SystemExit(main())
