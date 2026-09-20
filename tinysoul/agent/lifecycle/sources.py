"""Activate explicit generation contributions once, outside Turn execution."""

from tinysoul.infra.concurrency import AsyncResourceScope, CleanupDiagnostic
from tinysoul.runtime import RuntimeException
from tinysoul.runtime.sources import EventSink, RuntimeSource, SourceStatus

from ..errors import AgentInvariantError
from ..runtime_bridge import RuntimeAgentBridge


class GenerationSources:
    def __init__(self, sources: tuple[RuntimeSource, ...] = ()) -> None:
        unique: dict[str, RuntimeSource] = {}
        for source in sources:
            key = source.status.source
            if key in unique and unique[key] is not source:
                raise AgentInvariantError("Conflicting runtime source contributions")
            unique[key] = source
        self._sources = tuple(unique.values())
        self._publish: EventSink | None = None
        self._running = False

    @property
    def statuses(self) -> tuple[SourceStatus, ...]:
        return tuple(source.status for source in self._sources)

    @property
    def publisher(self) -> EventSink | None:
        return self._publish

    async def start(self, publish: EventSink) -> None:
        self._publish = publish
        await self.resume()

    async def resume(self) -> None:
        if self._running or self._publish is None:
            return
        self._running = True
        try:
            for source in self._sources:
                try:
                    await source.start(self._publish)
                except RuntimeException:
                    raise
                except Exception as exc:
                    raise RuntimeAgentBridge().startup_failure(
                        message="An Agent runtime source could not start.",
                        payload={
                            "source": source.status.source,
                            "error_type": type(exc).__name__,
                        },
                    ) from exc
        except BaseException:
            await self.pause()
            raise

    async def pause(self) -> tuple[CleanupDiagnostic, ...]:
        if not self._running:
            return ()
        self._running = False
        scope = AsyncResourceScope()
        for source in self._sources:
            scope.register(source.status.source, source.stop)
        return await scope.close()

    async def close(self) -> tuple[CleanupDiagnostic, ...]:
        self._publish = None
        return await self.pause()
