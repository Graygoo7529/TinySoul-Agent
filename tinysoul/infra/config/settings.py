"""Global configuration settings for TinySoul.

Loads defaults from ``defaults.py`` and allows overrides via:

1. Environment variables (``TINYSOUL_*`` prefix)
2. ``.env`` file in the current working directory

Usage::

    from tinysoul.infra.config import settings
    print(settings.max_tokens)  # 4000 (or overridden value)
"""

from __future__ import annotations

import os
import typing
import json
from copy import deepcopy
from dataclasses import dataclass, field, fields
from typing import Any

from . import defaults


# ------------------------------------------------------------------------------
# .env loader
# ------------------------------------------------------------------------------


def _load_dotenv() -> None:
    """Load environment variables from .env file if present."""
    env_path = os.path.join(os.getcwd(), ".env")
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, value = line.split("=", 1)
                    key = key.strip()
                    value = value.strip()
                    if key not in os.environ:
                        os.environ[key] = value


# Load .env once on module import
_load_dotenv()


def _env(name: str) -> str | None:
    """Return the environment variable value or None if not set/empty."""
    val = os.environ.get(name)
    return val if val is not None and val != "" else None


def _convert_env_value(raw: str, target_type: Any) -> Any:
    """Convert a raw string env value to the annotated Python type."""
    if target_type is int:
        return int(raw)
    if target_type is float:
        return float(raw)
    if target_type is bool:
        return raw.lower() in ("1", "true", "yes", "on")

    origin = typing.get_origin(target_type)
    if origin is list:
        return [p.strip() for p in raw.split(",") if p.strip()]
    if origin is dict:
        return json.loads(raw)

    # Default: str (and any unhandled type)
    return raw


# ------------------------------------------------------------------------------
# Settings dataclass
# ------------------------------------------------------------------------------


@dataclass
class GlobalSettings:
    """Unified framework configuration.

    All fields have sensible defaults (defined in ``defaults.py``) and can be
    overridden via environment variables with the ``TINYSOUL_`` prefix.

    Adding a new tunable parameter requires **only two steps**:
    1. Define ``DEFAULT_XXX`` in ``defaults.py``.
    2. Add a field here with that default.

    ``from_env()`` will automatically pick up ``TINYSOUL_XXX`` from the
    environment and coerce it to the correct type—no manual wiring needed.
    """

    # --- LLM -----------------------------------------------------------------
    temperature: float = defaults.DEFAULT_TEMPERATURE
    max_tokens: int = defaults.DEFAULT_MAX_TOKENS
    max_retries: int = defaults.DEFAULT_MAX_RETRIES
    base_retry_delay: float = defaults.DEFAULT_BASE_RETRY_DELAY
    llm_timeout: float = defaults.DEFAULT_LLM_TIMEOUT
    action_llm_overhead: float = defaults.DEFAULT_ACTION_LLM_OVERHEAD
    action_api_overhead: float = defaults.DEFAULT_ACTION_API_OVERHEAD
    chat_profiles: dict[str, dict[str, Any]] = field(
        default_factory=lambda: deepcopy(defaults.DEFAULT_CHAT_PROFILES)
    )

    # --- Embedding -----------------------------------------------------------
    embedding_provider: str = defaults.DEFAULT_EMBEDDING_PROVIDER
    embedding_model: str = defaults.DEFAULT_EMBEDDING_MODEL

    # --- Image Generation ----------------------------------------------------
    image_gen_provider: str = defaults.DEFAULT_IMAGE_GEN_PROVIDER
    image_gen_model: str = defaults.DEFAULT_IMAGE_GEN_MODEL

    # --- Limits --------------------------------------------------------------
    reference_truncate: int = defaults.DEFAULT_REFERENCE_TRUNCATE
    content_truncate: int = defaults.DEFAULT_CONTENT_TRUNCATE
    llm_parse_preview_chars: int = defaults.DEFAULT_LLM_PARSE_PREVIEW_CHARS
    interpreter_raw_preview_chars: int = defaults.DEFAULT_INTERPRETER_RAW_PREVIEW_CHARS
    interpreter_cleaned_preview_chars: int = defaults.DEFAULT_INTERPRETER_CLEANED_PREVIEW_CHARS

    # --- Timeouts ------------------------------------------------------------
    action_timeout: float = defaults.DEFAULT_ACTION_TIMEOUT
    cli_timeout: float = defaults.DEFAULT_CLI_TIMEOUT
    script_timeout: float = defaults.DEFAULT_SCRIPT_TIMEOUT

    # --- Query Loop ----------------------------------------------------------
    max_turns: int = defaults.DEFAULT_MAX_TURNS

    # --- Parallel Dispatch ---------------------------------------------------
    parallel_dispatch_buffer: float = defaults.DEFAULT_PARALLEL_DISPATCH_BUFFER
    parallel_max_workers: int = defaults.DEFAULT_PARALLEL_MAX_WORKERS

    # --- Context Compact -----------------------------------------------------
    compact_max_records: int = defaults.DEFAULT_COMPACT_MAX_RECORDS
    compact_max_errors: int = defaults.DEFAULT_COMPACT_MAX_ERRORS
    compact_max_logs: int = defaults.DEFAULT_COMPACT_MAX_LOGS

    # --- Logging -------------------------------------------------------------
    log_level: str = defaults.DEFAULT_LOG_LEVEL
    log_categories: str = defaults.DEFAULT_LOG_CATEGORIES
    log_color: str = defaults.DEFAULT_LOG_COLOR

    @classmethod
    def from_env(cls) -> "GlobalSettings":
        """Build settings from defaults + environment variable overrides.

        Environment variable names are auto-derived from field names:
        ``TINYSOUL_{FIELD_NAME.upper()}``.

        Type conversion is automatic based on the field's annotated type:
        - ``int`` / ``float`` / ``bool`` → parsed numerically / logically.
        - ``list[str]`` → comma-separated string split into list.
        - everything else → passed through as ``str``.
        """
        kwargs: dict[str, Any] = {}
        type_hints = typing.get_type_hints(cls)

        for f in fields(cls):
            env_name = f"TINYSOUL_{f.name.upper()}"
            raw = _env(env_name)
            if raw is None:
                continue
            kwargs[f.name] = _convert_env_value(raw, type_hints[f.name])

        return cls(**kwargs)


# Module-level singleton: imported once, reused everywhere
settings = GlobalSettings.from_env()
