"""Archive-owned failure classification at day and Reflection boundaries."""

from dataclasses import dataclass

from tinysoul.runtime import RUNTIME_AGENT_END, RUNTIME_STARTUP_FAILED, RuntimeException
from tinysoul.runtime.failures import exception_payload, runtime_exception

from .errors import ArchiveContractError, ArchiveError
from .failures import ArchiveFailureKind


ARCHIVE_RUNTIME_REASONS = {
    ArchiveFailureKind.PREPARATION_FAILED: RUNTIME_STARTUP_FAILED,
    ArchiveFailureKind.CONTRACT_VIOLATION: RUNTIME_AGENT_END,
    ArchiveFailureKind.INVARIANT_VIOLATION: RUNTIME_AGENT_END,
}

ARCHIVE_FAILURE_MESSAGES = {
    ArchiveFailureKind.PREPARATION_FAILED: "Archive could not prepare the active day.",
    ArchiveFailureKind.CONTRACT_VIOLATION: "Archive call violated its contract.",
    ArchiveFailureKind.INVARIANT_VIOLATION: "Archive state violated an invariant.",
}


@dataclass(frozen=True)
class RuntimeArchiveBridge:
    def from_archive_error(self, error: ArchiveError, *, preparing: bool = False) -> RuntimeException:
        kind = (ArchiveFailureKind.PREPARATION_FAILED if preparing else
                ArchiveFailureKind.CONTRACT_VIOLATION if isinstance(error, ArchiveContractError) else
                ArchiveFailureKind.INVARIANT_VIOLATION)
        return runtime_exception(
            module="archive", kind=kind, reason=ARCHIVE_RUNTIME_REASONS[kind],
            message=ARCHIVE_FAILURE_MESSAGES[kind], payload=exception_payload(error),
        )
