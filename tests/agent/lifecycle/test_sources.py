"""Shared generation contributions activate once and join before replacement."""

from dataclasses import replace

import pytest

from tinysoul.agent.errors import AgentInvariantError
from tinysoul.agent.lifecycle.sources import GenerationSources
from tinysoul.runtime.events import EnvironmentEvent, EventReceipt
from tinysoul.runtime.sources import EventSink, SourceState, SourceStatus


class Source:
    def __init__(self, identity: str) -> None:
        self.status = SourceStatus(identity, SourceState.STOPPED)
        self.starts = 0
        self.stops = 0

    async def start(self, publish: EventSink) -> None:
        self.starts += 1
        self.status = replace(self.status, state=SourceState.RUNNING)

    async def stop(self) -> None:
        self.stops += 1
        self.status = replace(self.status, state=SourceState.STOPPED)


async def test_shared_sources_start_once_and_resume_same_bindings() -> None:
    source = Source("files")
    sources = GenerationSources((source, source))

    async def publish(event: EnvironmentEvent) -> EventReceipt:
        return EventReceipt(1, event.event_id, False)

    await sources.start(publish)
    await sources.resume()
    assert source.starts == 1
    await sources.pause()
    assert source.stops == 1
    await sources.resume()
    assert source.starts == 2
    await sources.close()
    await sources.resume()
    assert source.starts == source.stops == 2


def test_distinct_sources_cannot_claim_the_same_binding() -> None:
    with pytest.raises(AgentInvariantError):
        GenerationSources((Source("files"), Source("files")))
