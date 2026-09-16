"""Registered owner lifecycle and atomic view preparation contracts."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field, replace
from datetime import date

import pytest

from tinysoul.context import ContextEngineBuilder, PromptBlock, TaskPrompt
from tinysoul.context.errors import ContextContractError, ContextInvariantError
from tinysoul.context.segments import (
    SegmentDescriptor, SegmentRegistration, SegmentRegistry, SegmentSlot, TurnInfo,
)
from tinysoul.infra.json import JsonObject
from tinysoul.llm.messages import Message, UserMessage
from tinysoul.runtime import RunLevel, RunScope, Signal, SignalBus


@dataclass
class CounterSegment:
    value: int = 0
    reject_prepare: bool = False
    reject_install: bool = False
    reject_close: bool = False
    entered: asyncio.Event | None = None
    release: asyncio.Event | None = None
    installed: int = 0
    closed: int = 0

    async def prepare(self, updates: tuple[int, ...]) -> int:
        if self.entered is not None:
            self.entered.set()
        if self.release is not None:
            await self.release.wait()
        if self.reject_prepare:
            raise ContextInvariantError("Candidate could not be read")
        return self.value + sum(updates)

    def install(self, prepared: int) -> None:
        self.installed += 1
        if self.reject_install:
            raise ContextInvariantError("Invalid installation")
        self.value = prepared

    def render(self) -> tuple[Message, ...]:
        return (UserMessage.from_json(self.seal(), label="counter"),)

    def seal(self) -> JsonObject:
        return {"value": self.value}

    async def close(self) -> None:
        self.closed += 1
        if self.reject_close:
            raise ContextInvariantError("Cannot release view")


@dataclass
class CounterProvider:
    opened: list[CounterSegment] = field(default_factory=list)
    fail_open: bool = False

    async def open(self, info: TurnInfo) -> CounterSegment:
        if self.fail_open:
            raise ContextContractError("View cannot open")
        segment = CounterSegment()
        self.opened.append(segment)
        return segment


def _decode(signal: Signal) -> int:
    value = signal.payload.get("increment")
    if isinstance(value, bool) or not isinstance(value, int):
        raise ContextContractError("Counter update requires an integer")
    return value


def _registration(name: str, provider: CounterProvider, order: int = 1) -> SegmentRegistration[int, int]:
    return SegmentRegistration(
        SegmentDescriptor(name, "test", SegmentSlot.WORKING, order),
        provider, f"context.{name}.increment", int, _decode,
    )


def _signal(name: str, turn: str, value: int) -> Signal:
    return Signal(
        name=f"context.{name}.increment", source="test",
        scope=RunScope().push(RunLevel.TURN, turn), payload={"increment": value},
    )


async def test_registered_updates_retry_fixed_batch_without_installing_other_views() -> None:
    first, second = CounterProvider(), CounterProvider()
    context = ContextEngineBuilder(system_text="identity").build()
    context.register_segment(_registration("first", first))
    context.register_segment(_registration("second", second, 2))
    turn = context.begin_turn("input")
    await context.prepare_default_background(date(2026, 9, 16))
    second.opened[0].reject_prepare = True
    bus = SignalBus()
    bus.emit(_signal("first", turn, 3))
    bus.emit(_signal("second", turn, 5))
    batch = context.take_signal_batch(bus)
    pending = _signal("first", turn, 7)
    bus.emit(pending)

    with pytest.raises(ContextInvariantError):
        await context.consume_signal_batch(batch)
    assert first.opened[0].installed == 0
    assert context.segment_snapshot("first") == {"value": 0}
    second.opened[0].reject_prepare = False
    assert await context.consume_signal_batch(batch) == ()
    assert context.segment_snapshot("first") == {"value": 3}
    assert context.segment_snapshot("second") == {"value": 5}
    assert bus.peek() == (pending,)
    prompt = TaskPrompt(guide_blocks=(PromptBlock.from_text("task_prompt:guide:test", "next"),))
    assert [item.label for item in context.compose(prompt).messages].count("counter") == 2
    completion = context.end_turn()
    assert completion.segments == {"first": {"value": 3}, "second": {"value": 5}}
    await context.close_segments()
    assert first.opened[0].closed == second.opened[0].closed == 1

    context.begin_turn("another input")
    await context.prepare_default_background(date(2026, 9, 16))
    assert context.segment_snapshot("first") == {"value": 0}
    context.end_turn()
    await context.close_segments()
    assert len(first.opened) == 2


async def test_cancelled_preparation_does_not_install_candidates() -> None:
    provider = CounterProvider()
    views = SegmentRegistry().register(_registration("counter", provider)).for_turn(
        TurnInfo("turn_cancel", date(2026, 9, 16)),
    )
    await views.open()
    segment = provider.opened[0]
    segment.entered, segment.release = asyncio.Event(), asyncio.Event()
    preparing = asyncio.create_task(views.prepare((_signal("counter", "turn_cancel", 9),)))
    await segment.entered.wait()
    preparing.cancel()
    with pytest.raises(asyncio.CancelledError):
        await preparing
    assert segment.value == segment.installed == 0
    await views.close()
    assert segment.closed == 1


async def test_install_failure_cannot_be_replayed_or_hidden_by_a_new_batch() -> None:
    provider = CounterProvider()
    views = SegmentRegistry().register(_registration("counter", provider)).for_turn(
        TurnInfo("turn_broken", date(2026, 9, 16)),
    )
    await views.open()
    provider.opened[0].reject_install = True
    signal = _signal("counter", "turn_broken", 2)
    prepared = await views.prepare((signal,))
    with pytest.raises(ContextInvariantError):
        views.install(prepared)
    with pytest.raises(ContextContractError):
        await views.prepare((signal,))
    with pytest.raises(ContextContractError):
        views.install(prepared)
    assert provider.opened[0].installed == 1
    await views.close()


async def test_open_failure_closes_partial_views_and_keeps_cleanup_diagnostics() -> None:
    first, second = CounterProvider(), CounterProvider(fail_open=True)
    views = SegmentRegistry().register(_registration("first", first)).register(
        _registration("second", second, 2),
    ).for_turn(TurnInfo("turn_open", date(2026, 9, 16)))
    with pytest.raises(ContextContractError, match="cannot open"):
        await views.open()
    assert first.opened[0].closed == 1
    assert await views.close() == ()
    assert first.opened[0].closed == 1


async def test_prepared_candidate_belongs_to_one_turn_and_is_consumed_once() -> None:
    provider = CounterProvider()
    registry = SegmentRegistry().register(_registration("counter", provider))
    first = registry.for_turn(TurnInfo("first", date(2026, 9, 16)))
    second = registry.for_turn(TurnInfo("second", date(2026, 9, 16)))
    await first.open()
    await second.open()
    candidate = await first.prepare((_signal("counter", "first", 1),))
    with pytest.raises(ContextContractError):
        second.install(candidate)
    first.install(candidate)
    with pytest.raises(ContextContractError):
        first.install(candidate)
    provider.opened[0].reject_close = True
    diagnostics = await first.close()
    assert len(diagnostics) == 1
    assert diagnostics[0].resource == "counter"
    await second.close()


def test_duplicate_metadata_and_routes_are_rejected_at_assembly() -> None:
    registration = _registration("counter", CounterProvider())
    with pytest.raises(ContextContractError):
        SegmentRegistry((registration, registration))
    with pytest.raises(ContextContractError):
        SegmentRegistry().register(registration).register(registration)
    with pytest.raises(ContextContractError):
        SegmentDescriptor("owner.counter", "test", SegmentSlot.WORKING, 1)
    context = ContextEngineBuilder(system_text="identity").build()
    with pytest.raises(ContextContractError, match="core update"):
        context.register_segment(replace(registration, signal_name="context.working.patch"))
