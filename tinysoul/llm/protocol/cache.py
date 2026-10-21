"""Provider-neutral prompt cache intent."""

from dataclasses import dataclass

from ..errors import LLMContractError


@dataclass(frozen=True)
class PromptCache:
    """Task-owned stable prefix boundary; mode and TTL belong to the model."""

    key: str | None = None
    breakpoint_message_index: int | None = None

    def __post_init__(self) -> None:
        if self.key is not None and (not isinstance(self.key, str) or not self.key):
            raise LLMContractError("PromptCache.key must be non-empty when supplied")
        index = self.breakpoint_message_index
        if index is not None and (type(index) is not int or index < 0):
            raise LLMContractError("PromptCache breakpoint must be a non-negative index")
