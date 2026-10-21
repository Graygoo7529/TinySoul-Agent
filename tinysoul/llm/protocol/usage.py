"""Normalized token accounting without implying cross-provider billing parity."""

from dataclasses import asdict, dataclass

from tinysoul.infra.json import JsonObject

from ..errors import LLMContractError


@dataclass(frozen=True)
class TokenUsage:
    """Total input/output tokens and their optional cached/reasoning subsets."""

    input_tokens: int | None = None
    output_tokens: int | None = None
    reasoning_tokens: int | None = None
    cached_input_tokens: int | None = None
    cache_creation_input_tokens: int | None = None

    def __post_init__(self) -> None:
        for name, value in asdict(self).items():
            if value is not None and (type(value) is not int or value < 0):
                raise LLMContractError(
                    f"TokenUsage.{name} must be non-negative or absent"
                )

    def to_json(self) -> JsonObject:
        return {
            name: value for name, value in asdict(self).items() if value is not None
        }
