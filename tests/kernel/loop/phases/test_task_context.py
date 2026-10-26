from __future__ import annotations
from datetime import date as CalendarDate
from tinysoul.kernel.context.background import heap_segment_registration
from tinysoul.kernel.context.segments import (
    SegmentCapability,
    SegmentDescriptor,
    SegmentShape,
    SegmentSlot,
)
from datetime import date
import pytest
from tinysoul.kernel.context import (
    BackgroundCatalog,
    BackgroundCatalogItem,
    ContextEngineBuilder,
)
from tinysoul.llm.protocol.messages import TextPart
from tinysoul.llm.protocol.requests import TaskCall
from tinysoul.llm.protocol.responses import RawResponse, TaskFailure, TaskResult
from tinysoul.llm.protocol.tools import ToolCallRecord, ToolKind
from tinysoul.kernel.loop import Phase1Unit, Phase2Unit
from tinysoul.runtime import CyclePhase, RunLevel, RunScope, RuntimeException, SignalBus
from tests.kernel.loop.phases.support import (
    FakeLLM,
    _action_engine,
    _message_stack_text,
    _tool_result,
)


@pytest.mark.parametrize("response", ["capacity", "not_sent", "responded"])
async def test_only_a_responded_request_releases_inspect_overlay(response: str) -> None:
    from tinysoul.kernel.context import build_trace_action_result_signal
    from tinysoul.llm.protocol.messages import ToolResultMessage
    from tinysoul.llm.failures import LLM_CONTEXT_CAPACITY_EXCEEDED
    from tinysoul.llm.protocol.responses import TaskResultStatus

    class CapacityLLM:
        async def invoke(self, call: TaskCall) -> TaskResult:
            return await self.run(call)

        async def run(self, call: TaskCall) -> TaskResult:
            if response == "capacity":
                raise RuntimeException(LLM_CONTEXT_CAPACITY_EXCEEDED, "capacity")
            return TaskResult(
                status=TaskResultStatus.FAILURE,
                answer=None,
                raw_response=RawResponse(
                    answer_text="", model_id="fake", provider_id="fake"
                )
                if response == "responded"
                else None,
                failure=TaskFailure(model_feedback="No usable action intent"),
            )

    context = ContextEngineBuilder(system_text="test").build()
    turn_id = context.begin_turn("inspect", turn_id="2026-10-06/120")
    await context.open_segments(CalendarDate(2026, 9, 20))
    scope = RunScope().push(RunLevel.TURN, turn_id)
    full = ToolResultMessage.from_json(
        call_id="inspect",
        tool_name="core.context.inspect",
        value={"detail": "evidence"},
    )
    folded = ToolResultMessage.from_json(
        call_id="inspect",
        tool_name="core.context.inspect",
        value={"ref": "session:map"},
    )
    bus = SignalBus()
    bus.emit(
        build_trace_action_result_signal(
            full,
            canonical_message=folded,
            origin_refs=("session:map",),
            scope=scope,
            source="test",
        )
    )
    await context.consume_signals(bus)
    phase = Phase1Unit(
        context=context,
        action=_action_engine(),
        llm=CapacityLLM(),
        bus=bus,
        task_profile="phase1",
    )
    if response == "capacity":
        with pytest.raises(RuntimeException) as failure:
            await phase.run(scope=scope, cycle_id="cycle_1")
        assert failure.value.reason == LLM_CONTEXT_CAPACITY_EXCEEDED
    else:
        await phase.run(scope=scope, cycle_id="cycle_1")
    assert context.compress(required_chars=100000).folded_overlay_count == (
        1 if response == "responded" else 0
    )
    await context.close_segments()


async def test_phase_units_use_independent_task_profiles() -> None:
    context = ContextEngineBuilder(system_text="sys").build()
    turn_id = context.begin_turn("answer now", turn_id="2026-10-06/265")
    await context.open_segments(CalendarDate(2026, 7, 12))
    action = _action_engine()
    bus = SignalBus()
    llm = FakeLLM(
        (
            _tool_result(
                ToolCallRecord(
                    id="select_1",
                    name="select_action_domains",
                    arguments={"domains": ["core"]},
                    kind=ToolKind.CONTROL,
                )
            ),
            _tool_result(
                ToolCallRecord(
                    id="answer_1",
                    name="core.answer",
                    arguments={"guide_blocks": [{"text": "answer"}]},
                    kind=ToolKind.ACTION,
                )
            ),
        )
    )
    scope = (
        RunScope()
        .push(RunLevel.AGENT, "program")
        .push(RunLevel.TURN, turn_id)
        .push(RunLevel.CYCLE, "cycle_1")
    )

    phase1 = await Phase1Unit(
        context=context,
        action=action,
        llm=llm,
        bus=bus,
        task_profile="cycle_planner",
    ).run(
        scope=scope.push(RunLevel.PHASE, CyclePhase.PHASE1.value),
        cycle_id="cycle_1",
    )
    (
        await Phase2Unit(
            context=context,
            action=action,
            llm=llm,
            bus=bus,
            task_profile="cycle_executor",
        ).run(
            selected_domains=phase1.selected_domains,
            scope=scope.push(RunLevel.PHASE, CyclePhase.PHASE2.value),
            cycle_id="cycle_1",
            turn_id=turn_id,
        )
    )

    assert [call.profile for call in llm.calls] == [
        "cycle_planner",
        "cycle_executor",
    ]
    assert all(
        call.prompt_cache is not None and call.prompt_cache.key == turn_id
        for call in llm.calls
    )


async def test_phase1_skill_catalog_and_load_background_feed_phase2_only_for_the_turn() -> (
    None
):
    class _SkillProvider:
        async def catalog(self, active_day: date) -> BackgroundCatalog:
            return BackgroundCatalog(
                owner="home",
                loadable_refs=("home:top/skills/review",),
                items=(
                    BackgroundCatalogItem(
                        ref="home:top/skills/review",
                        title="Review Home",
                        description="Review effective Home changes.",
                    ),
                ),
            )

        async def load(self, ref: str, active_day: date) -> str:
            assert ref == "home:top/skills/review"
            return "SKILL BODY: compare runtime and actual Home."

    context = (
        ContextEngineBuilder(system_text="sys")
        .with_segment(
            heap_segment_registration(
                SegmentDescriptor(
                    "home",
                    "home",
                    SegmentSlot.BACKGROUND,
                    40,
                    shape=SegmentShape.HEAP,
                    capabilities=frozenset(
                        {SegmentCapability.SELECT, SegmentCapability.RECLAIM}
                    ),
                ),
                _SkillProvider(),
                signal_name="context.home.update",
            )
        )
        .build()
    )
    turn_id = context.begin_turn("review Home", turn_id="2026-10-06/368")
    await context.open_segments(date(2026, 7, 14))
    action = _action_engine()
    llm = FakeLLM(
        (
            _tool_result(
                ToolCallRecord(
                    id="select_core",
                    name="select_action_domains",
                    arguments={"domains": ["core"]},
                    kind=ToolKind.CONTROL,
                ),
                ToolCallRecord(
                    id="load_review",
                    name="load_background",
                    arguments={"refs": ["home:top/skills/review"]},
                    kind=ToolKind.CONTROL,
                ),
            ),
            _tool_result(
                ToolCallRecord(
                    id="reason",
                    name="core.reason",
                    arguments={
                        "guide_blocks": [{"text": "Review the change."}],
                        "output_blocks": [{"text": "Return JSON."}],
                    },
                    kind=ToolKind.ACTION,
                )
            ),
        )
    )
    bus = SignalBus()
    base_scope = (
        RunScope()
        .push(RunLevel.AGENT, "program")
        .push(RunLevel.TURN, turn_id)
        .push(RunLevel.CYCLE, "cycle_1")
    )

    phase1 = await Phase1Unit(
        context=context,
        action=action,
        llm=llm,
        bus=bus,
        task_profile="framework",
    ).run(
        scope=base_scope.push(RunLevel.PHASE, CyclePhase.PHASE1.value),
        cycle_id="cycle_1",
    )
    (
        await Phase2Unit(
            context=context,
            action=action,
            llm=llm,
            bus=bus,
            task_profile="framework",
        ).run(
            selected_domains=phase1.selected_domains,
            scope=base_scope.push(RunLevel.PHASE, CyclePhase.PHASE2.value),
            cycle_id="cycle_1",
            turn_id=turn_id,
        )
    )

    phase1_stack = llm.calls[0].messages
    catalog = next(
        message
        for message in phase1_stack.messages
        if message.label == "background:catalog:home"
    )
    assert isinstance(catalog.parts[0], TextPart)
    assert "home:top/skills/review" in catalog.parts[0].text
    assert "Review effective Home changes." in catalog.parts[0].text

    assert "SKILL BODY" not in _message_stack_text(phase1_stack)

    phase2_stack = llm.calls[1].messages
    loaded = next(
        message
        for message in phase2_stack.messages
        if message.label == "background:home:top/skills/review"
    )
    assert isinstance(loaded.parts[0], TextPart)
    assert "SKILL BODY: compare runtime and actual Home." in loaded.parts[0].text

    context.end_turn()
    await context.close_segments()
    await context.close_segments()
    context.begin_turn("next turn", turn_id="2026-10-06/461")
    await context.open_segments(date(2026, 7, 14))
    assert "home:top/skills/review" not in context.background_refs()


def test_phase_prompt_content_preserves_scenario_and_skill_boundaries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tinysoul.kernel.context.prompts import PromptGuidance
    from tinysoul.kernel.loop.prompts import phase1_task_prompt, phase2_task_prompt
    from tinysoul.llm.protocol.messages import UserMessage
    from tinysoul.prompts.kernel import loop as prompt_text

    monkeypatch.setattr(prompt_text, "PHASE1_GUIDANCE", ("phase one {literal}",))
    monkeypatch.setattr(prompt_text, "PHASE2_GUIDANCE", ("phase two {literal}",))
    scenario = "scenario {instruction}"
    feedback = "feedback {detail}"
    skill = PromptGuidance("skill {body}", "home:mount/domain/core", "home")
    first = phase1_task_prompt(
        domain_prompt="domain {data}",
        turn_guidance=(scenario,),
        feedback=(feedback,),
    )
    second = phase2_task_prompt(
        selected_domains=("core",),
        domain_skills=(skill,),
        turn_guidance=(scenario,),
        feedback=(feedback,),
    )
    for prompt, marker in (
        (first, "phase one {literal}"),
        (second, "phase two {literal}"),
    ):
        assert all(
            isinstance(message, UserMessage) for message in prompt.render_messages()
        )
        parts = prompt.guide_blocks[0].message.parts
        text = "".join(part.text for part in parts if isinstance(part, TextPart))
        assert text.index(marker) < text.index(scenario) < text.index(feedback)
    assert len(first.guide_blocks) == 1
    assert second.guide_blocks[1].owner == skill.owner
    assert second.guide_blocks[1].refs == (skill.reference,)
    assert second.provenance()[1].message_indices == (1,)
