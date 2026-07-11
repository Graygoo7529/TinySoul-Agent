"""TurnTrace compaction policy."""

from __future__ import annotations

from dataclasses import dataclass

from .errors import ContextInvariantError
from .trace import TraceCompactionReport, TurnTraceHeap


@dataclass(frozen=True)
class ContextPressureReport:
    changed: bool
    reclaimed_chars: int
    trace: TraceCompactionReport
    evicted_background_links: tuple[str, ...] = ()


class ContextCompressor:
    """Create and compact lossless TurnTrace heaps."""

    def __init__(
        self,
        *,
        chunk_max_chars: int,
        branch_factor: int,
        min_hot_entries: int,
    ) -> None:
        if chunk_max_chars <= 0:
            raise ContextInvariantError(
                "ContextCompressor.chunk_max_chars must be positive"
            )
        if branch_factor < 2:
            raise ContextInvariantError(
                "ContextCompressor.branch_factor must be at least 2"
            )
        if min_hot_entries < 0:
            raise ContextInvariantError(
                "ContextCompressor.min_hot_entries cannot be negative"
            )
        self._chunk_max_chars = chunk_max_chars
        self._branch_factor = branch_factor
        self._min_hot_entries = min_hot_entries

    def new_trace(self, turn_id: str) -> TurnTraceHeap:
        return TurnTraceHeap(
            turn_id=turn_id,
            chunk_max_chars=self._chunk_max_chars,
            branch_factor=self._branch_factor,
            min_hot_entries=self._min_hot_entries,
        )

    def compress(
        self,
        trace: TurnTraceHeap,
        *,
        required_chars: int,
    ) -> TraceCompactionReport:
        return trace.compact(required_chars=required_chars)
