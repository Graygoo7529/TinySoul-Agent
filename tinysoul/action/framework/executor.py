"""
Action executor framework for TinySoul.

Provides the abstract base class for all action execution logic.
"""

from abc import ABC

from tinysoul.context.protocols import ContextProvider
from tinysoul.action.framework.run_config import RunConfig


class ActionExecutor(ABC):
    """
    Abstract base class for action executors.

    All concrete executors (CalculateExecutor, OneStepAIExecutor,
    TemporaryScriptExecutor, etc.) must inherit from this class.
    """

    def execute(
        self,
        action_input: dict,
        context_provider: ContextProvider,
        run_config: RunConfig,
    ) -> dict:
        """Execute the action with structured input and return a result dict."""
        raise NotImplementedError()
