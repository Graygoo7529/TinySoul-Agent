"""Generation-local index of Google cached content resources; TTL owns remote cleanup."""

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256

from google.genai import types
from google.genai.client import AsyncClient

from tinysoul.infra.json import dumps_json, to_json_object

from ..base import ProviderError, ProviderErrorKind


@dataclass(frozen=True)
class CachedPrefix:
    name: str
    expires_at: datetime


class GooglePromptCacheStore:
    """One provider endpoint's cache index, borrowed by its adapter."""

    def __init__(self, client: AsyncClient) -> None:
        self._client = client
        self._entries: dict[str, CachedPrefix] = {}
        self._lock = asyncio.Lock()

    async def get_or_create(
        self, model: str, config: types.CreateCachedContentConfig
    ) -> str:
        identity = config.model_dump(
            mode="json", exclude_none=True, exclude={"http_options"}
        )
        key = sha256(
            dumps_json(to_json_object({"model": model, "config": identity})).encode()
        ).hexdigest()
        async with self._lock:
            now = datetime.now(UTC)
            self._entries = {
                key: entry
                for key, entry in self._entries.items()
                if entry.expires_at > now
            }
            if key in self._entries:
                return self._entries[key].name
            created = await self._client.caches.create(model=model, config=config)
            if not created.name:
                raise ProviderError(
                    "Google cache creation returned no resource name",
                    kind=ProviderErrorKind.PARSE,
                )
            expiry = created.expire_time or now + timedelta(
                seconds=int((config.ttl or "600s")[:-1])
            )
            self._entries[key] = CachedPrefix(created.name, expiry)
            return created.name

    def invalidate(self, name: str) -> None:
        self._entries = {
            key: value for key, value in self._entries.items() if value.name != name
        }

    async def close(self) -> None:
        self._entries.clear()
