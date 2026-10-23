"""Own the Google SDK's sync facade and async transport as one registry resource."""

import httpx
from google import genai
from google.genai import types

from tinysoul.infra.http import client_headers, httpx_mounts
from tinysoul.infra.network import ResolvedNetwork


class GoogleClient:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        api_version: str | None,
        headers: dict[str, str],
        network: ResolvedNetwork = ResolvedNetwork(),
    ) -> None:
        identity = client_headers(headers)["user-agent"]

        async def identify(request: httpx.Request) -> None:
            # GenAI prepends its SDK label when merging HttpOptions. The owned
            # HTTP client's public hook preserves the configured agent identity.
            request.headers["user-agent"] = identity

        self.sdk = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(
                base_url=base_url,
                api_version=api_version,
                headers=headers,
                retry_options=types.HttpRetryOptions(attempts=1),
                httpx_async_client=httpx.AsyncClient(
                    trust_env=False,
                    mounts=httpx_mounts(network),
                    timeout=600,
                    event_hooks={"request": [identify]},
                ),
            ),
        )

    async def close(self) -> None:
        try:
            await self.sdk.aio.aclose()
        finally:
            self.sdk.close()
