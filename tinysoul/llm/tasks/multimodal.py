"""Multimodal content construction for TinySoul.

Provides Attachment and ContentBuilder for constructing multimodal
messages that include text, images, and file references.
"""

from __future__ import annotations

import base64
import mimetypes
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class Attachment:
    """An attachment to be included in an LLM prompt.

    AITask converts attachments into OpenAI-compatible multimodal message
    content (image_url with base64 data URL).
    """

    type: str  # "image" | "file"
    data: str  # base64-encoded bytes for images, or text content for files
    mime_type: str | None = None
    name: str = ""  # display name or file path hint

    @classmethod
    def from_image_file(cls, path: str | Path) -> "Attachment":
        """Create an image attachment from a file path."""
        path = Path(path)
        mime = mimetypes.guess_type(str(path))[0] or "image/png"
        data = base64.b64encode(path.read_bytes()).decode()
        return cls(type="image", data=data, mime_type=mime, name=path.name)

    @classmethod
    def from_image_base64(cls, data: str, mime_type: str = "image/png") -> "Attachment":
        """Create an image attachment from a base64 string."""
        return cls(type="image", data=data, mime_type=mime_type)

    @classmethod
    def from_image_url(cls, url: str) -> "Attachment":
        """Create an image attachment from a URL.

        Note: not all providers support remote URLs; base64 is preferred
        for reliability.
        """
        return cls(type="image", data=url, mime_type=None)

    def to_content_part(self) -> dict[str, Any]:
        """Convert to OpenAI-compatible content part."""
        if self.type == "image":
            if self.mime_type:
                url = f"data:{self.mime_type};base64,{self.data}"
            else:
                url = self.data
            return {"type": "image_url", "image_url": {"url": url}}
        return {"type": "text", "text": self.data}


class ContentBuilder:
    """Convenience builder for multimodal message content parts."""

    @staticmethod
    def text(text: str) -> dict[str, Any]:
        return {"type": "text", "text": text}

    @staticmethod
    def image_url(url: str) -> dict[str, Any]:
        return {"type": "image_url", "image_url": {"url": url}}

    @staticmethod
    def image_base64(data: str, mime_type: str = "image/png") -> dict[str, Any]:
        return {
            "type": "image_url",
            "image_url": {"url": f"data:{mime_type};base64,{data}"},
        }

    @staticmethod
    def image_file(path: str | Path) -> dict[str, Any]:
        path = Path(path)
        mime = mimetypes.guess_type(str(path))[0] or "image/png"
        data = base64.b64encode(path.read_bytes()).decode()
        return ContentBuilder.image_base64(data, mime)
