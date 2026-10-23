"""Read model capability suggestions without changing local model declarations."""

from collections.abc import Mapping

from anthropic import (
    APIConnectionError,
    APIError,
    APIStatusError,
    AsyncAnthropic,
    DefaultAsyncHttpxClient,
)

from tinysoul.infra.http import httpx2_mounts
from tinysoul.infra.json import JsonObject, to_json_object
from tinysoul.infra.network import ResolvedNetwork
from tinysoul.llm.config.types import ProviderSpec
from tinysoul.llm.protocol.adapter_types import ApiMode

from ..base import ProviderError, ProviderErrorKind
from ..common import status_error


async def read_anthropic_model_capabilities(
    provider: ProviderSpec,
    model_id: str,
    *,
    env: Mapping[str, str],
    network: ResolvedNetwork = ResolvedNetwork(),
) -> JsonObject:
    endpoint = provider.endpoint(ApiMode.ANTHROPIC_MESSAGES)
    client = AsyncAnthropic(
        http_client=DefaultAsyncHttpxClient(
            trust_env=False,
            mounts=httpx2_mounts(
                provider.resolved_network(ApiMode.ANTHROPIC_MESSAGES, network)
            ),
        ),
        api_key=provider.resolve_api_key(env),
        base_url=endpoint.base_url,
        default_headers=provider.resolved_headers(ApiMode.ANTHROPIC_MESSAGES, env),
        max_retries=0,
        timeout=30,
    )
    try:
        async with client:
            model = await client.models.retrieve(model_id)
    except APIStatusError as exc:
        raise status_error(exc.status_code) from exc
    except (APIConnectionError, TimeoutError) as exc:
        raise ProviderError(
            "Model capability lookup failed", kind=ProviderErrorKind.TRANSIENT
        ) from exc
    except APIError as exc:
        raise ProviderError(
            "Model capability response could not be read", kind=ProviderErrorKind.PARSE
        ) from exc
    capabilities = model.capabilities
    thinking = capabilities.thinking if capabilities else None
    effort = capabilities.effort if capabilities else None
    thinking_types = thinking.types if thinking else None
    return to_json_object(
        {
            "provider_id": provider.id,
            "model_id": model.id,
            "display_name": model.display_name,
            "lifecycle": model.lifecycle,
            "max_input_tokens": model.max_input_tokens,
            "max_tokens": model.max_tokens,
            "thinking": {
                "supported": thinking.supported,
                "choices": [
                    name
                    for name in ("adaptive", "enabled", "between_tools", "disabled")
                    if getattr(getattr(thinking_types, name, None), "supported", False)
                ],
            }
            if thinking
            else None,
            "reasoning_effort": {
                "supported": effort.supported,
                "choices": [
                    name
                    for name in ("low", "medium", "high", "xhigh", "max")
                    if effort.supported
                    and getattr(getattr(effort, name, None), "supported", False)
                ],
            }
            if effort
            else None,
        }
    )
