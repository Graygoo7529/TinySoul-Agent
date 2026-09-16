"""Shared supervised process failures."""


class SupervisedProcessError(Exception):
    """Base class for shared supervised process failures."""


class SupervisedProcessContractError(SupervisedProcessError):
    """A caller supplied an invalid supervised process request."""


class SupervisedProcessStateError(SupervisedProcessError):
    """A job operation is invalid for its owner or current state."""


class SupervisedProcessExecutionError(SupervisedProcessError):
    """A supervised process could not be staged, started, or cleaned."""
