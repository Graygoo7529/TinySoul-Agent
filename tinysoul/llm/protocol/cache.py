"""Provider-neutral prompt cache intent."""

from dataclasses import dataclass

from ..errors import LLMContractError


@dataclass(frozen=True)
class PromptCacheBreakpoint:
    """A named cumulative prefix in the current message stack."""

    name: str
    message_index: int

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name:
            raise LLMContractError("Cache breakpoint name must be non-empty")
        if type(self.message_index) is not int or self.message_index < 0:
            raise LLMContractError("Cache breakpoint must be a non-negative index")


@dataclass(frozen=True)
class PromptCache:
    """Caller-owned routing key and candidate prefixes for this message stack.

    Callers reuse a key across related tasks; it does not identify cached content.
    Mode, prefix selection and TTL belong to the model configuration.
    """

    key: str | None = None
    breakpoints: tuple[PromptCacheBreakpoint, ...] = ()

    def __post_init__(self) -> None:
        if self.key is not None and (not isinstance(self.key, str) or not self.key):
            raise LLMContractError("PromptCache.key must be non-empty when supplied")
        if not isinstance(self.breakpoints, tuple) or any(
            not isinstance(item, PromptCacheBreakpoint) for item in self.breakpoints
        ):
            raise LLMContractError("PromptCache.breakpoints must be typed breakpoints")
        if len({item.name for item in self.breakpoints}) != len(self.breakpoints):
            raise LLMContractError("PromptCache breakpoint names must be unique")
