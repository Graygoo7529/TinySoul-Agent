"""Context compression service."""

from __future__ import annotations

from .errors import ContextInvariantError
from .trace import CompressionReport, TurnTraceContext


class ContextCompressor:
    """Trim old turn trace entries when the context budget is exceeded.

    The compression flow is owned by the runtime trap handler; this service only
    applies the strategy. Background and working sections are never trimmed.
    """

    def __init__(self, *, keep_recent: int) -> None:
        if keep_recent < 0:
            raise ContextInvariantError("ContextCompressor.keep_recent cannot be negative")
        self._keep_recent = keep_recent

    @property
    def keep_recent(self) -> int:
        return self._keep_recent

    def compress(self, trace: TurnTraceContext) -> CompressionReport:
        return trace.compress_oldest(keep_recent=self._keep_recent)
