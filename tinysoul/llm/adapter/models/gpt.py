"""GPT-specific sampling constraints over the generic Responses adapter."""

from tinysoul.llm.config.types import ProviderSpec
from tinysoul.llm.protocol.adapter_types import AdapterKind

from ..base import ProviderRequest
from ..openai.clients import OpenAIResponsesClient
from ..openai.responses import OpenAIResponsesAdapter


class GptAdapter(OpenAIResponsesAdapter):
    def __init__(
        self, *, provider: ProviderSpec, responses: OpenAIResponsesClient
    ) -> None:
        super().__init__(
            provider=provider, responses=responses, adapter_kind=AdapterKind.GPT
        )

    def normalize_sampling(
        self, kwargs: dict[str, object], request: ProviderRequest
    ) -> None:
        super().normalize_sampling(kwargs, request)
        # An unspecified effort uses the model's reasoning default.
        if request.model.reasoning_effort != "none":
            kwargs.pop("temperature", None)
            kwargs.pop("top_p", None)
