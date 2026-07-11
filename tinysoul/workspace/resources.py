"""Workspace resource classification."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .manifest import WorkspaceResourceKind


TEXT_MEDIA_TYPES: dict[str, str] = {
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".py": "text/x-python",
    ".json": "application/json",
    ".toml": "application/toml",
    ".yaml": "application/yaml",
    ".yml": "application/yaml",
    ".csv": "text/csv",
    ".tsv": "text/tab-separated-values",
    ".html": "text/html",
    ".htm": "text/html",
    ".css": "text/css",
    ".js": "text/javascript",
    ".ts": "text/typescript",
    ".xml": "application/xml",
    ".sql": "application/sql",
    ".sh": "text/x-shellscript",
    ".ps1": "text/x-powershell",
}

IMAGE_MEDIA_TYPES: dict[str, str] = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}

DOCUMENT_MEDIA_TYPES: dict[str, str] = {
    ".pdf": "application/pdf",
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".ppt": "application/vnd.ms-powerpoint",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".xls": "application/vnd.ms-excel",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


@dataclass(frozen=True)
class WorkspaceResourceClassification:
    """Stable prompt-access classification for one workspace file."""

    kind: WorkspaceResourceKind
    media_type: str
    suffix: str
    summary_label: str


class WorkspaceResourceClassifier:
    """Classify files through explicit, platform-independent suffix maps."""

    def classify(self, path: Path) -> WorkspaceResourceClassification:
        suffix = path.suffix.lower()
        if suffix in TEXT_MEDIA_TYPES:
            return WorkspaceResourceClassification(
                kind=WorkspaceResourceKind.TEXT,
                media_type=TEXT_MEDIA_TYPES[suffix],
                suffix=suffix,
                summary_label=_text_label(suffix),
            )
        if suffix in IMAGE_MEDIA_TYPES:
            return WorkspaceResourceClassification(
                kind=WorkspaceResourceKind.IMAGE,
                media_type=IMAGE_MEDIA_TYPES[suffix],
                suffix=suffix,
                summary_label=f"{suffix[1:].upper()} image",
            )
        if suffix in DOCUMENT_MEDIA_TYPES:
            return WorkspaceResourceClassification(
                kind=WorkspaceResourceKind.DOCUMENT,
                media_type=DOCUMENT_MEDIA_TYPES[suffix],
                suffix=suffix,
                summary_label=f"{suffix[1:].upper()} document; conversion required",
            )
        return WorkspaceResourceClassification(
            kind=WorkspaceResourceKind.BINARY,
            media_type="application/octet-stream",
            suffix=suffix,
            summary_label="Binary file; direct prompt loading unavailable",
        )


def _text_label(suffix: str) -> str:
    labels = {
        ".md": "Markdown text",
        ".py": "Python source text",
        ".json": "JSON text",
        ".toml": "TOML text",
        ".yaml": "YAML text",
        ".yml": "YAML text",
        ".csv": "CSV text",
        ".tsv": "TSV text",
        ".html": "HTML text",
        ".htm": "HTML text",
        ".css": "CSS text",
        ".js": "JavaScript source text",
        ".ts": "TypeScript source text",
        ".xml": "XML text",
        ".sql": "SQL text",
        ".sh": "Shell source text",
        ".ps1": "PowerShell source text",
    }
    return labels.get(suffix, "Plain text")
