"""Tests for message stack composition and budget."""

from __future__ import annotations

import pytest

from tinysoul.context.background import BackgroundContext, BackgroundEntry
from tinysoul.context.composer import (
    ContextBudget,
    MessageStackComposer,
    estimate_chars,
)
from tinysoul.context.errors import ContextBudgetError
from tinysoul.context.prompts import TaskPrompt
from tinysoul.context.trace import TurnTraceContext
from tinysoul.context.working import WorkingContext
from tinysoul.llm.messages import AssistantMessage, SystemMessage, TextPart, UserMessage
from tinysoul.llm.reasoning import Reasoning


def _sections() -> tuple[BackgroundContext, WorkingContext, TurnTraceContext]:
    background = BackgroundContext(journal="journal text")
    background.load(BackgroundEntry(link="home:what@x", content="entry text"))
    working = WorkingContext()
    trace = TurnTraceContext()
    trace.append_user_input("hello there")
    return background, working, trace


def test_compose_section_order_and_labels() -> None:
    background, working, trace = _sections()
    composer = MessageStackComposer(system_text="identity text")
    stack = composer.compose(
        background=background,
        working=working,
        trace=trace,
        task_prompt=TaskPrompt(
            guide="Do phase one.",
            task_input="input details",
            output_desc="tool calls",
            domain_guidance=("Use the workspace domain for file edits.",),
        ),
    )
    labels = [message.label for message in stack.messages]
    assert labels == [
        "identity",
        "background:journal",
        "background:home:what@x",
        "working",
        "user_input",
        "task_prompt",
    ]
    assert isinstance(stack.messages[0], SystemMessage)
    task_message = stack.messages[-1]
    assert isinstance(task_message, UserMessage)
    part = task_message.parts[0]
    assert isinstance(part, TextPart)
    assert "# Task Guide" in part.text
    assert "# Domain Guidance" in part.text


def test_compose_budget_exceeded_raises() -> None:
    background, working, trace = _sections()
    composer = MessageStackComposer(
        system_text="identity text",
        budget=ContextBudget(max_chars=10),
    )
    with pytest.raises(ContextBudgetError) as exc_info:
        composer.compose(
            background=background,
            working=working,
            trace=trace,
            task_prompt=TaskPrompt(guide="Do phase one."),
        )
    assert exc_info.value.max_chars == 10
    assert exc_info.value.estimated_chars > 10


def test_estimate_counts_text_and_json_parts() -> None:
    messages = (
        SystemMessage.from_text("abcd"),
        UserMessage.from_json({"k": "v"}),
    )
    estimated = estimate_chars(messages)
    assert estimated >= 4 + len('{"k": "v"}') - 2


def test_estimate_counts_assistant_reasoning() -> None:
    messages = (
        AssistantMessage.from_text(
            "answer",
            reasoning=Reasoning(
                content="thinking content",
                summary="thinking summary",
                encrypted_items=({"type": "reasoning", "encrypted_content": "state"},),
            ),
        ),
    )

    estimated = estimate_chars(messages)

    assert estimated > len("answer") + len("thinking content") + len("thinking summary")
