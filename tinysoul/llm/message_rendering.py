"""Render TinySoul message parts into provider-mappable content."""

from __future__ import annotations

from dataclasses import dataclass

from tinysoul.infra.json import dumps_json

from .messages import ImagePart, ImageUrlPart, JsonPart, MessagePart, TextPart


@dataclass(frozen=True)
class RenderedText:
    """Rendered text content ready to map into a provider text input."""

    text: str


@dataclass(frozen=True)
class RenderedImage:
    """Rendered image bytes ready to map into a provider image input."""

    data: bytes
    mime_type: str


@dataclass(frozen=True)
class RenderedImageUrl:
    """Rendered remote image URL ready to map into a provider image input."""

    url: str


RenderedContentPart = RenderedText | RenderedImage | RenderedImageUrl
RenderedMessageContent = str | tuple[RenderedContentPart, ...]


class MessageContentRenderer:
    """Render TinySoul message parts without provider-specific field names."""

    def render(self, parts: tuple[MessagePart, ...]) -> RenderedMessageContent:
        if _only_textual(parts):
            return _render_textual_parts(parts)

        rendered: list[RenderedContentPart] = []
        pending_textual: list[MessagePart] = []
        for part in parts:
            if isinstance(part, (TextPart, JsonPart)):
                pending_textual.append(part)
                continue
            self._flush_textual(rendered, pending_textual)
            if isinstance(part, ImagePart):
                rendered.append(RenderedImage(data=part.data, mime_type=part.mime_type))
            else:
                rendered.append(RenderedImageUrl(url=part.url))
        self._flush_textual(rendered, pending_textual)
        return tuple(rendered)

    def _flush_textual(
        self,
        rendered: list[RenderedContentPart],
        pending_textual: list[MessagePart],
    ) -> None:
        if not pending_textual:
            return
        rendered.append(RenderedText(_render_textual_parts(tuple(pending_textual))))
        pending_textual.clear()


def _only_textual(parts: tuple[MessagePart, ...]) -> bool:
    return all(isinstance(part, (TextPart, JsonPart)) for part in parts)


def _render_textual_parts(parts: tuple[MessagePart, ...]) -> str:
    text_blocks: list[str] = []
    for part in parts:
        if isinstance(part, TextPart):
            if part.text:
                text_blocks.append(part.text)
            continue
        if isinstance(part, JsonPart):
            text_blocks.append(f"```json\n{dumps_json(part.value)}\n```")
    return "\n\n".join(text_blocks)
