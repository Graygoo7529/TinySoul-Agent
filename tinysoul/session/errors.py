"""Session module errors."""


class SessionError(Exception):
    """Base Session module error."""


class SessionContractError(SessionError):
    """Invalid Session boundary input."""


class SessionInvariantError(SessionError):
    """Broken Session internal invariant."""


class SessionIOError(SessionError):
    """Session persistence failure."""
