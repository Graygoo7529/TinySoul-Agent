"""Typed views of options after the adapter catalog has validated them.

The protocol keeps a model's declarative configuration; API mappers narrow that
configuration at their boundary without duplicating the catalog's validation.
"""

from typing import TypedDict

from tinysoul.infra.json import JsonObject


class OpenAIOptions(TypedDict, total=False):
    sampling: str
    reasoning_efforts: list[str]
    reasoning_keep: str
    extra_body: JsonObject
    prompt_cache_mode: str
    prompt_cache_ttl: str


class ChatOptions(OpenAIOptions, total=False):
    output_token_field: str


class ResponsesOptions(OpenAIOptions, total=False):
    reasoning_summary: str
    reasoning_context: str
    verbosity: str
    store: bool
