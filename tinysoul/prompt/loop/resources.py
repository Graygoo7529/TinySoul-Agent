"""Loop prompt resource accessors."""

from __future__ import annotations

from functools import lru_cache

from tinysoul.infra.resources import load_text_from_package


_PACKAGE = "tinysoul.prompt.loop"


@lru_cache(maxsize=None)
def _load_builtin(name: str, resource: str) -> str:
    loaded = load_text_from_package(name, _PACKAGE, resource)
    if loaded is None:
        raise FileNotFoundError(f"Required loop prompt missing: {resource}")
    return loaded.content.strip()


def get_query_loop_system() -> str:
    return _load_builtin("query_loop_system", "markdown/query_loop.system.md")


def get_choose_action_guide() -> str:
    return _load_builtin("choose_action_guide", "markdown/choose_action.guide.md")


def get_generate_parameters_guide() -> str:
    return _load_builtin(
        "generate_parameters_guide",
        "markdown/generate_parameters.guide.md",
    )


def get_update_state_guide() -> str:
    return _load_builtin("update_state_guide", "markdown/update_state.guide.md")


__all__ = [
    "get_query_loop_system",
    "get_choose_action_guide",
    "get_generate_parameters_guide",
    "get_update_state_guide",
]
