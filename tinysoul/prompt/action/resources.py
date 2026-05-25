"""Action prompt resource accessors."""

from __future__ import annotations

from functools import lru_cache

from tinysoul.infra.resources import load_text_from_package


_PACKAGE = "tinysoul.prompt.action"


@lru_cache(maxsize=None)
def _load_builtin(name: str, resource: str) -> str:
    loaded = load_text_from_package(name, _PACKAGE, resource)
    if loaded is None:
        raise FileNotFoundError(f"Required action prompt missing: {resource}")
    return loaded.content.strip()


def get_action_execution_context() -> str:
    return _load_builtin(
        "action_execution_context",
        "markdown/action_execution_context.system.md",
    )


def get_one_step_default_system() -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": _load_builtin(
                "one_step_default_system",
                "markdown/one_step_default.system.md",
            ),
        }
    ]


def get_register_script_system() -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": _load_builtin(
                "register_script_system",
                "markdown/register_script.system.md",
            ),
        }
    ]


__all__ = [
    "get_action_execution_context",
    "get_one_step_default_system",
    "get_register_script_system",
]
