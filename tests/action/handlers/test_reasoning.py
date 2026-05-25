"""Tests for the reasoning action."""

from __future__ import annotations

import pytest

from tinysoul.action.handlers.basic.reasoning import (
    ACTION_JSON_REASONING,
    ReasoningAction,
    _apply_reasoning_result,
    _build_reasoning_prompt,
)
from tinysoul.trap.signal import Signal, SignalType
from tinysoul.context.workspace import Workspace
from tests.helpers.fakes import FakeContextProvider


class TestReasoningActionMeta:
    def test_meta_parses_correctly(self):
        action = ReasoningAction()
        meta = action.get_meta()
        assert meta.name == "reasoning"
        assert meta.profile.action_intention.value == "INTERNAL_REASONING"
        assert meta.profile.llm_dependency.value == "REQUIRED"


class TestApplyReasoningResult:
    def test_skips_step3_when_flag_true(self, tmp_path):
        ws = Workspace(workspace_location=str(tmp_path))
        signals = []

        class Ctx(FakeContextProvider):
            def emit_signal(self, signal):
                signals.append(signal)

        ctx = Ctx(_workspace=ws)
        generated = {
            "content": "Analysis",
            "conclusions": ["c1"],
            "proposed_next_actions": ["calculate"],
            "skip_step3": True,
        }
        result = _apply_reasoning_result(
            {"reasoning_type": "synthesis", "topic": "test"},
            generated, ws, ctx
        )

        assert result["skip_step3"] is True
        assert len(signals) == 1
        assert signals[0].type == SignalType.LOOP_NEXT_TURN

    def test_emits_skip_step3_when_no_proposed_actions(self, tmp_path):
        """When proposed_next_actions is empty, reasoning has no actionable output;
        Step 3 is unnecessary."""
        ws = Workspace(workspace_location=str(tmp_path))
        signals = []

        class Ctx(FakeContextProvider):
            def emit_signal(self, signal):
                signals.append(signal)

        ctx = Ctx(_workspace=ws)
        generated = {
            "content": "Analysis",
            "conclusions": ["c1"],
            "proposed_next_actions": [],
            "skip_step3": False,
        }
        result = _apply_reasoning_result(
            {"reasoning_type": "synthesis", "topic": "test"},
            generated, ws, ctx
        )

        assert len(signals) == 1
        assert signals[0].type == SignalType.LOOP_NEXT_TURN
