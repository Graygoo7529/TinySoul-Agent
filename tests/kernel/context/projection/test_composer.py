"""Tests for message stack composition and budget."""

from __future__ import annotations

from dataclasses import replace

import pytest
from anthropic.types import Message as AnthropicMessage

from tinysoul.kernel.context.background import BackgroundContext, BackgroundEntry
from tinysoul.kernel.context.builtin.trace import PendingInputs, TurnTraceHeap
from tinysoul.kernel.context.builtin.working import WorkingContext
from tinysoul.kernel.context.engine import ContextEngine
from tinysoul.kernel.context.errors import ContextBudgetError
from tinysoul.kernel.context.projection.composer import (
    ContextBudget,
    MessageStackComposer,
    estimate_chars,
)
from tinysoul.kernel.context.prompts import PromptBlock, TaskPrompt
from tinysoul.kernel.context.segments import (
    SegmentDescriptor,
    SegmentProjection,
    SegmentSlot,
)
from tinysoul.llm.adapter.anthropic.messages import AnthropicMessagesAdapter
from tinysoul.llm.adapter.base import ProviderRequest
from tinysoul.llm.config.types import ProviderEndpoint, ProviderSpec
from tinysoul.llm.protocol.adapter_types import AdapterKind, ApiMode
from tinysoul.llm.protocol.cache import PromptCache, PromptCacheBreakpoint
from tinysoul.llm.protocol.messages import (
    AssistantMessage,
    ImagePart,
    JsonPart,
    SystemMessage,
    TextPart,
    ToolResultMessage,
    UserMessage,
)
from tinysoul.llm.protocol.models import AdapterOptions, ModelProviderBinding, ModelSpec
from tinysoul.llm.protocol.reasoning import NativeReplay, NativeReplayMode, Reasoning
from tinysoul.llm.protocol.responses import AnswerFormat
from tinysoul.llm.protocol.tools import (
    ToolCallRecord,
    ToolKind,
    ToolScope,
    ToolSpec,
    ToolUse,
)


def _sections() -> tuple[SegmentProjection, ...]:
    inputs = PendingInputs()
    inputs.add("hello there", merged=True)
    background = BackgroundContext(journal="journal text")
    background.load(BackgroundEntry(ref="home:top/skills/x", content="entry text"))
    working = WorkingContext()
    trace = TurnTraceHeap(turn_id="2026-10-06/41")
    trace.append_phase_note("trace note")
    return (
        SegmentProjection(
            SegmentDescriptor("plan", "context", SegmentSlot.WORKING, 10),
            working.render_messages(),
        ),
        SegmentProjection(
            SegmentDescriptor("trace", "context", SegmentSlot.TRACE, 10),
            trace.render_messages(),
        ),
        SegmentProjection(
            SegmentDescriptor("identity", "context", SegmentSlot.BACKGROUND, 10),
            (SystemMessage.from_text("identity text", label="identity"),),
        ),
        SegmentProjection(
            SegmentDescriptor("inputs", "context", SegmentSlot.BACKGROUND, 30),
            inputs.render_messages(),
        ),
        SegmentProjection(
            SegmentDescriptor("background", "context", SegmentSlot.BACKGROUND, 40),
            background.render_messages(),
        ),
    )


def test_provenance_uses_actual_positions_and_guidance_refs() -> None:
    prompt = TaskPrompt(
        guide_blocks=(
            PromptBlock.from_text(
                "arbitrary-label",
                "Skill body",
                owner="home",
                refs=("home:mount/domain/workspace",),
            ),
        )
    )
    stack = MessageStackComposer().compose(segments=_sections(), task_prompt=prompt)
    positions = [
        index for origin in stack.provenance for index in origin.message_indices
    ]
    assert positions == list(range(len(stack.messages)))
    assert stack.provenance[-1].refs == ("home:mount/domain/workspace",)
    assert stack.provenance[-1].owner == "home"
    assert stack.append(UserMessage.from_text("extra")).provenance == stack.provenance
    assert prompt.message_stack().provenance[0].message_indices == (0,)


def test_prompt_cache_candidates_follow_context_provenance_not_task_prompt() -> None:
    stack = MessageStackComposer().compose(
        segments=_sections(),
        task_prompt=TaskPrompt(
            guide_blocks=(PromptBlock.from_text("guide", "Guide"),),
            input_blocks=(PromptBlock.from_text("input", "Task"),),
        ),
    )

    assert ContextEngine.prompt_cache(stack) == PromptCache(
        breakpoints=(
            PromptCacheBreakpoint("background", 3),
            PromptCacheBreakpoint("trace", 4),
            PromptCacheBreakpoint("working", 5),
        )
    )


@pytest.mark.anyio
async def test_anthropic_replay_handles_constructed_context_and_trace() -> None:
    sent: list[dict[str, object]] = []

    class Client:
        async def create(self, **kwargs: object) -> AnthropicMessage:
            sent.append(kwargs)
            return AnthropicMessage.model_validate({
                "id": "msg_1", "type": "message", "role": "assistant", "model": "claude",
                "content": [
                    {"type": "thinking", "thinking": "Plan", "signature": "opaque"},
                    {"type": "tool_use", "id": "call_1", "name": "inspect", "input": {}},
                ],
                "stop_reason": "tool_use", "stop_sequence": None,
                "usage": {"input_tokens": 10, "output_tokens": 10},
            })

    trace = TurnTraceHeap(turn_id="2026-10-21/1")
    composer = MessageStackComposer()
    def compose(identity: str, prompt: TaskPrompt):
        return composer.compose(segments=(
            SegmentProjection(SegmentDescriptor("identity", "test", SegmentSlot.BACKGROUND, 0), (SystemMessage.from_text(identity),)),
            SegmentProjection(SegmentDescriptor("trace", "context", SegmentSlot.TRACE, 0), trace.render_messages()),
        ), task_prompt=prompt)

    binding = ModelProviderBinding("anthropic", "claude")
    model = ModelSpec("claude-test", (binding,), 100000, AdapterKind.ANTHROPIC_MESSAGES,
        adapter_options=AdapterOptions({"native_replay": "signed", "replay_prefix_binding": True}))
    adapter = AnthropicMessagesAdapter(
        provider=ProviderSpec("anthropic", (ProviderEndpoint(ApiMode.ANTHROPIC_MESSAGES, "https://example.test"),), ("KEY",)),
        messages=Client(),
    )
    invocation = ProviderRequest(model=model, binding=binding, messages=compose("Identity", TaskPrompt(
        guide_blocks=(PromptBlock.from_text("guide", "Use available tools"),),
        input_blocks=(PromptBlock.from_text("task", "Temporary task"),),
    )), answer_format=AnswerFormat.TEXT, tool_scope=ToolScope(tools=(
        ToolSpec("inspect", "Read", {"type": "object"}, ToolKind.CONTROL),
    )), tool_use=ToolUse.REQUIRED)
    result = await adapter.invoke(invocation)
    assert result.reasoning is not None and result.reasoning.native_replay is not None
    original = result.reasoning.native_replay
    decision = AssistantMessage.from_text(result.answer_text, reasoning=result.reasoning, tool_calls=result.tool_calls)
    trace.append_decision(decision)
    trace.append_action_result(ToolResultMessage.from_text(call_id="call_1", tool_name="inspect", text="Fact"))

    # An unchanged append-only prefix can replay signed state.
    await adapter.invoke(replace(invocation, messages=invocation.messages.append(decision).append(
        ToolResultMessage.from_text(call_id="call_1", tool_name="inspect", text="Fact"))))
    valid_messages = sent[-1]["messages"]
    assert isinstance(valid_messages, list)
    assert valid_messages[1]["content"][0]["signature"] == "opaque"

    # The real next compose moves the Trace before the new temporary TaskPrompt.
    next_stack = compose("Updated identity", TaskPrompt(guide_blocks=(PromptBlock.from_text("guide", "Use available tools"),), input_blocks=(PromptBlock.from_text("task", "Next task"),)))
    await adapter.invoke(replace(invocation, messages=next_stack))
    mapped = sent[-1]["messages"]
    assert isinstance(mapped, list)
    blocks = [block for message in mapped for block in message["content"]]
    assert not any(block["type"] in {"thinking", "redacted_thinking"} for block in blocks)
    assert any(block["type"] == "tool_use" for block in blocks)
    assert any(block["type"] == "tool_result" for block in blocks)
    assert decision.reasoning is not None and decision.reasoning.native_replay is original


def test_compose_section_order_and_labels() -> None:
    composer = MessageStackComposer()
    stack = composer.compose(
        segments=_sections(),
        task_prompt=TaskPrompt(
            guide_blocks=(
                PromptBlock.from_text(
                    "task_prompt:guide:phase",
                    "# Task Guide\nDo phase one.",
                ),
                PromptBlock.from_text(
                    "task_prompt:guide:domain_skill:1",
                    "# Domain Skill\nUse the workspace domain for file edits.",
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
        "background:home:top/skills/x",
        "phase_note",
        "plan",
        "task_prompt:guide:phase",
        "task_prompt:guide:domain_skill:1",
        "task_prompt:input:details",
        "task_prompt:input:workspace:docs/a.md",
        "task_prompt:output:phase",
    ]
    assert isinstance(stack.messages[0], SystemMessage)
    assert all(isinstance(message, UserMessage) for message in stack.messages[1:])
    working_part = stack.messages[5].parts[0]
    assert isinstance(working_part, JsonPart)
    assert "as_of_trace" not in working_part.value
    assert "workspace_revision" not in working_part.value
    task_message = stack.messages[-5]
    assert isinstance(task_message, UserMessage)
    part = task_message.parts[0]
    assert isinstance(part, TextPart)
    assert "# Task Guide" in part.text
    guidance = stack.messages[-4].parts[0]
    assert isinstance(guidance, TextPart)
    assert "# Domain Skill" in guidance.text


def test_compose_image_budget_exceeded_raises() -> None:
    composer = MessageStackComposer(
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
            segments=_sections(),
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
                summary="thinking summary",
                native_replay=NativeReplay(
                    NativeReplayMode.ENCRYPTED,
                    ApiMode.OPENAI_RESPONSES,
                    AdapterKind.GPT,
                    "provider",
                    "remote",
                    ({"type": "reasoning", "encrypted_content": "state"},),
                    "fingerprint",
                ),
            ),
        ),
    )

    estimated = estimate_chars(messages)

    assert estimated > len("answer") + len("thinking content") + len("thinking summary")


def test_estimate_counts_tool_calls_and_result_metadata() -> None:
    call = ToolCallRecord(
        id="call_1",
        name="workspace.write_text",
        arguments={"path": "notes.txt", "content": "x" * 40},
        kind=ToolKind.ACTION,
    )
    messages = (
        AssistantMessage.from_tool_calls(call),
        ToolResultMessage.from_text(
            call_id=call.id,
            tool_name=call.name,
            text="written",
        ),
    )

    estimated = estimate_chars(messages)

    assert estimated > len("x" * 40) + len("written")


def _prompt(text: str) -> TaskPrompt:
    return TaskPrompt(
        guide_blocks=(
            PromptBlock.from_text("task_prompt:guide:test", "# Task Guide\n" + text),
        )
    )
