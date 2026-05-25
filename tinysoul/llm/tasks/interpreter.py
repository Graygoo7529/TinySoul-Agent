"""Output interpretation for LLM Task module.

Provides unified JSON parsing of AI responses with code-fence stripping.
Interpreter consumes AIResponse and extracts the JSON dict from its content.
"""

from __future__ import annotations

import json
import re

from tinysoul.infra.config import settings
from tinysoul.trap import LLMResponseParseError

from tinysoul.llm.provider.response import AIResponse


def _extract_braced_block(text: str) -> str:
    """Extract the first top-level {...} block from *text*."""
    start = text.find("{")
    if start == -1:
        return text
    depth = 0
    for i, ch in enumerate(text[start:], start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return text[start:]


def _extract_cleaned_json(raw: str) -> str:
    """Try to obtain clean JSON text from an LLM response.

    Priority:
    1. Explicit ```json fence (unambiguous intent).
    2. Top-level braced block (structured JSON takes precedence over generic
       code fences to avoid truncation when JSON values contain markdown).
    3. Strict ``` fence (must wrap the entire response, not nested inside).
    """
    stripped = raw.strip()

    # Strategy 1: explicit ```json — highest confidence
    m = re.search(r"```json\s*\n(.*?)\n\s*```", stripped, re.DOTALL)
    if m:
        return m.group(1).strip()

    # Strategy 2: top-level braced block — protect JSON from being truncated
    # by code-fence regexes when JSON string values contain markdown ``` blocks
    if "{" in stripped:
        block = _extract_braced_block(stripped)
        if block.startswith("{") and block.endswith("}"):
            return block.strip()

    # Strategy 3: generic ``` fence, but ONLY if it wraps the entire response
    # (anchored to boundaries) to avoid matching ``` blocks nested in JSON values
    m = re.search(r"(?:^|\n)```(?:json)?\s*\n(.*?)\n\s*```\s*$", stripped, re.DOTALL)
    if m:
        return m.group(1).strip()

    # Strategy 4: legacy single-line fence (also anchored to boundaries)
    m = re.search(r"^```(?:json)?\s*(.*?)\s*```\s*$", stripped, re.DOTALL)
    if m:
        return m.group(1).strip()

    return stripped


class Interpreter:
    """Interprets AI responses as JSON objects.

    Single responsibility: extract a JSON dict from the model's text output.
    Non-JSON outputs (raw text, markdown, images) are handled by Action
    executors that bypass the Interpreter.
    """

    def interpret(self, source: str | AIResponse) -> dict:
        """Parse the response content as a JSON object."""
        raw = source if isinstance(source, str) else source.content
        cleaned = _extract_cleaned_json(raw)
        try:
            result = json.loads(cleaned)
        except json.JSONDecodeError as e:
            preview = raw[: settings.interpreter_raw_preview_chars].replace("\n", "\\n").replace("\r", "\\r")
            raise LLMResponseParseError(
                f"Failed to parse LLM response as JSON: {e}. "
                f"Cleaned preview: {cleaned[:settings.interpreter_cleaned_preview_chars]}. "
                f"Raw preview (first {settings.interpreter_raw_preview_chars} chars): {preview}"
            ) from e

        if not isinstance(result, dict):
            preview = raw[: settings.interpreter_raw_preview_chars].replace("\n", "\\n").replace("\r", "\\r")
            raise LLMResponseParseError(
                f"Expected JSON object, got {type(result).__name__}: {result!r}. "
                f"Raw preview (first {settings.interpreter_raw_preview_chars} chars): {preview}"
            )

        return result
