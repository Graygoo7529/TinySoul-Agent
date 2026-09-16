"""Archive owner failures interpreted at the Agent day boundary."""


class ArchiveError(Exception):
    """Archive storage or lifecycle cannot continue."""


class ArchiveContractError(ArchiveError):
    """An archive input violates its contract."""


class ArchiveInvariantError(ArchiveError):
    """Archive facts cannot form a consistent active day."""
