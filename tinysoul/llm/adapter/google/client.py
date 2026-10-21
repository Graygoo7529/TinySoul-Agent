"""Own the Google SDK's sync facade and async transport as one registry resource."""

import httpx
from google import genai
from google.genai import types


class GoogleClient:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        api_version: str | None,
        headers: dict[str, str],
    ) -> None:
        self.sdk = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(
                base_url=base_url,
                api_version=api_version,
                headers=headers,
                retry_options=types.HttpRetryOptions(attempts=1),
                httpx_async_client=httpx.AsyncClient(),
            ),
        )

    async def close(self) -> None:
        try:
            await self.sdk.aio.aclose()
        finally:
            self.sdk.close()
