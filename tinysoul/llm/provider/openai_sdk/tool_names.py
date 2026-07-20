"""Request-local tool name mapping for OpenAI SDK shaped providers."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from types import MappingProxyType

from tinysoul.llm.messages import AssistantMessage, ToolResultMessage
from tinysoul.llm.tools import ToolSpec

from ..base import ProviderError, ProviderErrorKind, ProviderRequest


_MAX_PROVIDER_TOOL_NAME_LENGTH = 64


@dataclass(frozen=True)
class ProviderToolNameMap:
    """Map TinySoul tool identities to unique provider-safe request aliases."""

    _provider_by_tinysoul: Mapping[str, str]
    _tinysoul_by_provider: Mapping[str, str]

    @classmethod
    def from_request(cls, request: ProviderRequest) -> "ProviderToolNameMap":
        names = [tool.name for tool in request.tool_scope.visible_tools()]
        for message in request.messages.messages:
            if isinstance(message, AssistantMessage):
                names.extend(call.name for call in message.tool_calls)
            elif isinstance(message, ToolResultMessage):
                names.append(message.tool_name)
        return cls.from_names(names)

    @classmethod
    def from_names(cls, names: Iterable[str]) -> "ProviderToolNameMap":
        unique_names = sorted(set(names))
        provider_by_tinysoul = {
            name: name for name in unique_names if _is_provider_safe_name(name)
        }
        used_provider_names = set(provider_by_tinysoul.values())

        for name in unique_names:
            if name in provider_by_tinysoul:
                continue
            candidate = _provider_name_candidate(name)
            provider_name = _unique_provider_name(candidate, used_provider_names)
            provider_by_tinysoul[name] = provider_name
            used_provider_names.add(provider_name)

        tinysoul_by_provider = {
            provider_name: name
            for name, provider_name in provider_by_tinysoul.items()
        }
        return cls(
            _provider_by_tinysoul=MappingProxyType(provider_by_tinysoul),
            _tinysoul_by_provider=MappingProxyType(tinysoul_by_provider),
        )

    def to_provider_name(self, tinysoul_name: str) -> str:
        try:
            return self._provider_by_tinysoul[tinysoul_name]
        except KeyError as exc:
            raise ProviderError(
                f"Tool name is not registered for this provider request: {tinysoul_name}",
                kind=ProviderErrorKind.CONFIG,
            ) from exc

    def to_tinysoul_name(self, provider_name: str) -> str:
        return self._tinysoul_by_provider.get(provider_name, provider_name)

    def to_provider_tool(self, tool: ToolSpec) -> ToolSpec:
        return replace(tool, name=self.to_provider_name(tool.name))


def _is_provider_safe_name(name: str) -> bool:
    if not name or len(name) > _MAX_PROVIDER_TOOL_NAME_LENGTH:
        return False
    if not (_is_ascii_letter(name[0]) or name[0] == "_"):
        return False
    return all(_is_ascii_alphanumeric(char) or char in {"_", "-"} for char in name)


def _provider_name_candidate(name: str) -> str:
    candidate = "".join(
        char if _is_ascii_alphanumeric(char) or char in {"_", "-"} else "_"
        for char in name
    )
    if not candidate:
        candidate = "tool"
    if not (_is_ascii_letter(candidate[0]) or candidate[0] == "_"):
        candidate = f"_{candidate}"
    return candidate[:_MAX_PROVIDER_TOOL_NAME_LENGTH]


def _unique_provider_name(candidate: str, used: set[str]) -> str:
    if candidate not in used:
        return candidate
    index = 2
    while True:
        suffix = f"_{index}"
        provider_name = (
            candidate[: _MAX_PROVIDER_TOOL_NAME_LENGTH - len(suffix)] + suffix
        )
        if provider_name not in used:
            return provider_name
        index += 1


def _is_ascii_letter(char: str) -> bool:
    return "A" <= char <= "Z" or "a" <= char <= "z"


def _is_ascii_alphanumeric(char: str) -> bool:
    return _is_ascii_letter(char) or "0" <= char <= "9"


__all__ = ["ProviderToolNameMap"]
