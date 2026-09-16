"""Failures of Agent request admission and lifecycle contracts."""


class AgentError(Exception):
    """Base failure at the Agent module boundary."""


class AgentContractError(AgentError):
    """Invalid input to an Agent boundary."""


class AgentInvariantError(AgentError):
    """Agent assembly or lifecycle invariants were violated."""


class AgentSDKError(AgentError):
    """The embedding call cannot satisfy the Agent contract."""


class AgentQueueFullError(AgentSDKError):
    """The bounded root queue cannot accept another request."""


class AgentClosedError(AgentSDKError):
    """The Agent is not accepting work."""
