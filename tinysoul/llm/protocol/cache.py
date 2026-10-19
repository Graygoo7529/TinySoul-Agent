"""Provider-neutral prompt cache intent."""

from dataclasses import dataclass
from enum import StrEnum

from ..errors import LLMContractError


class PromptCacheMode(StrEnum):
    IMPLICIT = "implicit"
    EXPLICIT = "explicit"


class PromptCacheTTL(StrEnum):
    THIRTY_MINUTES = "30m"


@dataclass(frozen=True)
class PromptCache:
    key: str | None = None
    mode: PromptCacheMode = PromptCacheMode.IMPLICIT
    ttl: PromptCacheTTL | None = None

    def __post_init__(self) -> None:
        if self.key is not None and (not isinstance(self.key, str) or not self.key):
            raise LLMContractError("PromptCache.key must be non-empty when supplied")
        if not isinstance(self.mode, PromptCacheMode):
            raise LLMContractError("PromptCache.mode must be PromptCacheMode")
        if self.ttl is not None and not isinstance(self.ttl, PromptCacheTTL):
            raise LLMContractError("PromptCache.ttl must be PromptCacheTTL or None")
