"""Deterministic source policy for agent-authored scripts."""

from __future__ import annotations

import ast

from .errors import ScriptPolicyError
from .models import ScriptLanguage, ScriptSource


class ScriptPolicy:
    """Validate syntax and bounded source facts without claiming hard sandboxing."""

    def __init__(self, *, max_source_chars: int) -> None:
        self._max_source_chars = max_source_chars

    def validate(self, source: ScriptSource) -> None:
        if len(source.text) > self._max_source_chars:
            raise ScriptPolicyError(
                f"Script source exceeds {self._max_source_chars} characters"
            )
        if "\x00" in source.text:
            raise ScriptPolicyError("Script source contains a NUL character")
        if source.language is ScriptLanguage.PYTHON:
            try:
                ast.parse(source.text, filename=source.link)
            except SyntaxError as exc:
                raise ScriptPolicyError(
                    f"Python script syntax is invalid at line {exc.lineno or 0}"
                ) from exc
        elif not source.text.strip():
            raise ScriptPolicyError("Bash script source must be non-empty")
