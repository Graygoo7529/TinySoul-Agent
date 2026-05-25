"""Unit tests for Interpreter — JSON extraction and parsing from LLM responses."""

from __future__ import annotations

import pytest

from tinysoul.trap import LLMResponseParseError
from tinysoul.llm.provider.response import AIResponse
from tinysoul.llm.tasks.interpreter import (
    Interpreter,
    _extract_braced_block,
    _extract_cleaned_json,
)


class TestExtractBracedBlock:
    def test_extracts_first_top_level_braces(self):
        text = 'prefix {"a": 1} suffix {"b": 2}'
        assert _extract_braced_block(text) == '{"a": 1}'

    def test_no_braces_returns_text(self):
        text = "no json here"
        assert _extract_braced_block(text) == "no json here"

    def test_handles_nested_braces(self):
        text = '{"outer": {"inner": 1}}'
        assert _extract_braced_block(text) == '{"outer": {"inner": 1}}'


class TestExtractCleanedJson:
    def test_extracts_from_json_fence_with_newlines(self):
        raw = '```json\n{"a": 1}\n```'
        assert _extract_cleaned_json(raw) == '{"a": 1}'

    def test_extracts_from_plain_fence_inline(self):
        raw = '```{"a": 1}```'
        assert _extract_cleaned_json(raw) == '{"a": 1}'

    def test_extracts_bare_braces(self):
        raw = 'Here is the result: {"a": 1}'
        assert _extract_cleaned_json(raw) == '{"a": 1}'

    def test_returns_plain_text_when_no_braces(self):
        raw = "just text"
        assert _extract_cleaned_json(raw) == "just text"

    def test_extracts_with_prefix_and_suffix_text(self):
        raw = "Sure! ```json\n{\"x\": 10}\n``` Have a nice day!"
        assert _extract_cleaned_json(raw) == '{"x": 10}'


class TestInterpreterInterpret:
    def test_parses_plain_dict(self):
        interp = Interpreter()
        result = interp.interpret('{"action_name": "calculate"}')
        assert result == {"action_name": "calculate"}

    def test_parses_dict_from_code_fence(self):
        interp = Interpreter()
        result = interp.interpret('```json\n{"action_name": "calculate"}\n```')
        assert result == {"action_name": "calculate"}

    def test_parses_from_ai_response_object(self):
        interp = Interpreter()
        result = interp.interpret(AIResponse(content='{"finished": true}'))
        assert result == {"finished": True}

    def test_raises_on_invalid_json(self):
        interp = Interpreter()
        with pytest.raises(LLMResponseParseError, match="Failed to parse"):
            interp.interpret("not json at all")

    def test_raises_on_non_dict(self):
        interp = Interpreter()
        with pytest.raises(LLMResponseParseError, match="Expected JSON object"):
            interp.interpret('[1, 2, 3]')

    def test_raises_on_string(self):
        interp = Interpreter()
        with pytest.raises(LLMResponseParseError, match="Expected JSON object"):
            interp.interpret('"just a string"')

    def test_raises_on_number(self):
        interp = Interpreter()
        with pytest.raises(LLMResponseParseError, match="Expected JSON object"):
            interp.interpret('42')

    def test_parses_nested_braces_with_prefix(self):
        interp = Interpreter()
        raw = "Some explanation text before the JSON: {\"nested\": {\"key\": \"value\"}}"
        result = interp.interpret(raw)
        assert result == {"nested": {"key": "value"}}

    def test_preview_in_error_is_truncated(self, monkeypatch):
        from tinysoul.infra.config import settings
        monkeypatch.setattr(settings, "interpreter_raw_preview_chars", 50)
        monkeypatch.setattr(settings, "interpreter_cleaned_preview_chars", 30)
        interp = Interpreter()
        long_text = "x" * 500
        with pytest.raises(LLMResponseParseError) as exc_info:
            interp.interpret(long_text)
        # preview should be limited by settings
        assert len(str(exc_info.value)) < 300


    def test_does_not_truncate_json_containing_internal_code_fence(self):
        """Regression: JSON values containing markdown ``` must not be mistaken
        for wrapping code fences."""
        raw = (
            '{"content":"# Report\\n\\n```\\nBorder Collie: 37 lbs\\n```\\n\\n...",'
            '"resource_desc":{"summary":"A markdown report"}}'
        )
        # _extract_braced_block should extract the full JSON before the generic
        # code-fence regex gets a chance to truncate it
        result = _extract_cleaned_json(raw)
        assert result == raw

    def test_plain_fence_wrapping_entire_response(self):
        raw = '```\n{"a": 1}\n```'
        assert _extract_cleaned_json(raw) == '{"a": 1}'

    def test_plain_fence_not_matching_internal_fence(self):
        raw = 'prefix text\n```\ncode\n```\nsuffix {"a": 1}'
        # Should fall through to braced block, not match the internal fence
        assert _extract_cleaned_json(raw) == '{"a": 1}'
