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
from tinysoul.context.prompts import PromptBlock, TaskPrompt
from tinysoul.context.trace import PendingInputs, TurnTraceContext
from tinysoul.context.working import WorkingContext
from tinysoul.llm.messages import (
    AssistantMessage,
    ImagePart,
    SystemMessage,
    TextPart,
    UserMessage,
)
from tinysoul.llm.reasoning import Reasoning


def _sections() -> tuple[PendingInputs, BackgroundContext, WorkingContext, TurnTraceContext]:
    inputs = PendingInputs()
    inputs.add("hello there", merged=True)
    background = BackgroundContext(journal="journal text")
    background.load(BackgroundEntry(link="home:what@x", content="entry text"))
    working = WorkingContext()
    trace = TurnTraceContext()
    trace.append_phase_note("trace note")
    return inputs, background, working, trace


def test_compose_section_order_and_labels() -> None:
    inputs, background, working, trace = _sections()
    composer = MessageStackComposer(system_text="identity text")
    stack = composer.compose(
        inputs=inputs,
        background=background,
        working=working,
        trace=trace,
        task_prompt=TaskPrompt(
            guide_blocks=(
                PromptBlock.from_text(
                    "task_prompt:guide:phase",
                    "# Task Guide\nDo phase one.",
                ),
                PromptBlock.from_text(
                    "task_prompt:guide:domain_how:1",
                    "# Domain HOW\nUse the workspace domain for file edits.",
                ),
            ),
            input_blocks=(
                PromptBlock.from_text(
                    "task_prompt:input:details",
                    "# Task Input\ninput details",
                ),
                PromptBlock.from_text(
                    "task_prompt:input:workspace:docs/a.md",
                    "workspace slice",
                ),
            ),
            output_blocks=(
                PromptBlock.from_text(
                    "task_prompt:output:phase",
                    "# Expected Output\ntool calls",
                ),
            ),
        ),
    )
    labels = [message.label for message in stack.messages]
    assert labels == [
        "identity",
        "user_input",
        "background:journal",
        "background:home:what@x",
        "working",
        "phase_note",
        "task_prompt:guide:phase",
        "task_prompt:guide:domain_how:1",
        "task_prompt:input:details",
        "task_prompt:input:workspace:docs/a.md",
        "task_prompt:output:phase",
    ]
    assert isinstance(stack.messages[0], SystemMessage)
    assert all(isinstance(message, UserMessage) for message in stack.messages[1:])
    task_message = stack.messages[-5]
    assert isinstance(task_message, UserMessage)
    part = task_message.parts[0]
    assert isinstance(part, TextPart)
    assert "# Task Guide" in part.text
    guidance = stack.messages[-4].parts[0]
    assert isinstance(guidance, TextPart)
    assert "# Domain HOW" in guidance.text


def test_compose_budget_exceeded_raises() -> None:
    inputs, background, working, trace = _sections()
    composer = MessageStackComposer(
        system_text="identity text",
        budget=ContextBudget(max_chars=10),
    )
    with pytest.raises(ContextBudgetError) as exc_info:
        composer.compose(
            inputs=inputs,
            background=background,
            working=working,
            trace=trace,
            task_prompt=_prompt("Do phase one."),
        )
    assert exc_info.value.max_chars == 10
    assert exc_info.value.estimated_chars > 10


def test_compose_image_budget_exceeded_raises() -> None:
    inputs, background, working, trace = _sections()
    composer = MessageStackComposer(
        system_text="identity text",
        budget=ContextBudget(max_image_bytes=2),
    )
    image_block = PromptBlock(
        label="task_prompt:input:image",
        message=UserMessage.from_parts(
            ImagePart(data=b"abc", mime_type="image/png"),
            label="task_prompt:input:image",
        ),
    )

    with pytest.raises(ContextBudgetError) as exc_info:
        composer.compose(
            inputs=inputs,
            background=background,
            working=working,
            trace=trace,
            task_prompt=TaskPrompt(
                guide_blocks=(PromptBlock.from_text("guide", "guide"),),
                input_blocks=(image_block,),
            ),
        )

    assert exc_info.value.estimated_image_bytes == 3
    assert exc_info.value.max_image_bytes == 2


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


def _prompt(text: str) -> TaskPrompt:
    return TaskPrompt(
        guide_blocks=(
            PromptBlock.from_text("task_prompt:guide:test", "# Task Guide\n" + text),
        )
    )
