"""Business-neutral process contracts and required lifecycle failures."""


class ProcessContractError(Exception):
    """The caller supplied an invalid process or stream contract."""


class ProcessEncodingError(Exception):
    """An output encoding does not name a supported text codec."""


class ManagedProcessStartError(Exception):
    """A managed child process could not be started."""


class ManagedProcessCloseError(Exception):
    """Owned execution resources did not stop within their lifecycle boundary."""


class ProcessOutputError(Exception):
    """Required output collection failed."""
