from __future__ import annotations

from tinysoul.llm.message_rendering import (
    MessageContentRenderer,
    RenderedImage,
    RenderedImageUrl,
    RenderedText,
)
from tinysoul.llm.messages import ImagePart, ImageUrlPart, JsonPart, TextPart


def test_renderer_merges_text_and_json_parts_as_visible_text() -> None:
    rendered = MessageContentRenderer().render(
        (
            TextPart("工具返回如下："),
            JsonPart({"source": "tool_result", "ok": True}),
        )
    )

    assert rendered == (
        '工具返回如下：\n\n```json\n{"ok":true,"source":"tool_result"}\n```'
    )
    assert r"{\"ok\"" not in rendered


def test_renderer_groups_textual_runs_around_images() -> None:
    rendered = MessageContentRenderer().render(
        (
            TextPart("看图："),
            JsonPart({"hint": "front"}),
            ImagePart(data=b"abc", mime_type="image/png"),
            TextPart("远程图："),
            ImageUrlPart(url="https://example.test/image.png"),
        )
    )

    assert rendered == (
        RenderedText('看图：\n\n```json\n{"hint":"front"}\n```'),
        RenderedImage(data=b"abc", mime_type="image/png"),
        RenderedText("远程图："),
        RenderedImageUrl(url="https://example.test/image.png"),
    )
