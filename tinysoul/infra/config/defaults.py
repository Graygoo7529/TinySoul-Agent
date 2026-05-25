"""Default configuration constants for TinySoul.

All framework-wide default values live here so they can be discovered
in a single location and overridden via environment variables.
"""

from typing import Any

# ------------------------------------------------------------------------------
# LLM defaults
# ------------------------------------------------------------------------------

# Sampling temperature for LLM calls. Higher = more creative / less deterministic.
# Typical range: 0.0 – 1.5. Reduce for structured-output tasks.
DEFAULT_TEMPERATURE: float = 0.7

# Maximum tokens per LLM completion request.
DEFAULT_MAX_TOKENS: int = 8000

# How many times to retry a failed LLM call (network error, rate limit, etc.)
# on the **current model** before giving up and raising LLMTransientError.
# ErrorTrap decides whether to failover to the next model afterwards.
DEFAULT_MAX_RETRIES: int = 3

# Initial backoff delay (seconds) between retries. Exponential backoff is
# applied internally: delay = base_retry_delay × 2^attempt.
# With max_retries=3 this yields sleeps of 1s and 2s (the final attempt
# does not sleep; it raises immediately on failure).
DEFAULT_BASE_RETRY_DELAY: float = 1.0

# HTTP-level timeout for individual LLM API calls (seconds).
# This is passed directly to the OpenAI SDK's chat.completions.create().
# It controls how long the framework waits for a single LLM response.
DEFAULT_LLM_TIMEOUT: float = 120.0

# Extra wall-clock budget added when deriving default action timeouts for
# actions that perform an LLM call. This covers prompt construction, parsing,
# result application, and framework bookkeeping around the provider call.
DEFAULT_ACTION_LLM_OVERHEAD: float = 20.0

# Reserved extra wall-clock budget for actions that perform external API calls.
DEFAULT_ACTION_API_OVERHEAD: float = 10.0

# Chat routing profiles. Each profile owns an independent provider failover
# chain and may override default models for multiple providers.
DEFAULT_CHAT_PROVIDER_CHAIN: list[str] = ["kimi", "deepseek", "zhipu", "minimax"]
DEFAULT_CHAT_PROFILES: dict[str, dict[str, Any]] = {
    "step1": {
        "provider_chain": ["deepseek", "kimi", "zhipu", "minimax"],
        "required_capabilities": ["text"],
        "preferred_capabilities": [],
        "chat_model_overrides": {},
        "config": {},
    },
    "step2": {
        "provider_chain": ["zhipu", "kimi", "deepseek", "minimax"],
        "required_capabilities": ["text"],
        "preferred_capabilities": [],
        "chat_model_overrides": {},
        "config": {},
    },
    "step3": {
        "provider_chain": list(DEFAULT_CHAT_PROVIDER_CHAIN),
        "required_capabilities": ["text"],
        "preferred_capabilities": [],
        "chat_model_overrides": {
            "kimi": {
                "model": "kimi-k2.5",
                "capabilities": ["text"],
            },
        },
        "config": {},
    },
    "action_llm": {
        "provider_chain": list(DEFAULT_CHAT_PROVIDER_CHAIN),
        "required_capabilities": ["text"],
        "preferred_capabilities": ["vision"],
        "chat_model_overrides": {},
        "config": {},
    },
}

# ------------------------------------------------------------------------------
# Provider model specs
# ------------------------------------------------------------------------------

DEFAULT_PROVIDER_MODEL_SPECS: dict[str, dict[str, dict[str, Any]]] = {
    "zhipu": {
        "chat": {
            "model_type": "chat",
            "default_model": "glm-4.7",
            "model_env": "GLM_MODEL",
            "api_key_envs": ["GLM_API_KEY", "ZHIPU_API_KEY"],
            "capabilities": ["text"],
        },
        "chat_vision": {
            "model_type": "chat",
            "default_model": "glm-4v",
            "model_env": "GLM_VISION_MODEL",
            "api_key_envs": ["GLM_API_KEY", "ZHIPU_API_KEY"],
            "capabilities": ["text", "vision"],
        },
        "embedding": {
            "model_type": "embedding",
            "default_model": "embedding-3",
            "model_env": "GLM_EMBEDDING_MODEL",
            "api_key_envs": ["GLM_API_KEY", "ZHIPU_API_KEY"],
            "capabilities": [],
        },
        "image_gen": {
            "model_type": "image_gen",
            "default_model": "cogview-3-plus",
            "model_env": "GLM_IMAGE_GEN_MODEL",
            "api_key_envs": ["GLM_API_KEY", "ZHIPU_API_KEY"],
            "capabilities": [],
        },
    },
    "kimi": {
        "chat": {
            "model_type": "chat",
            "default_model": "kimi-k2.6",
            "model_env": "KIMI_MODEL",
            "api_key_envs": ["KIMI_API_KEY", "MOONSHOT_API_KEY"],
            "capabilities": ["text", "vision"],
        },
        "embedding": {
            "model_type": "embedding",
            "default_model": "kimi-embedding-v1",
            "model_env": "KIMI_EMBEDDING_MODEL",
            "api_key_envs": ["KIMI_API_KEY", "MOONSHOT_API_KEY"],
            "capabilities": [],
        },
        "image_gen": {
            "model_type": "image_gen",
            "default_model": "kimi-k2-image",
            "model_env": "KIMI_IMAGE_GEN_MODEL",
            "api_key_envs": ["KIMI_API_KEY", "MOONSHOT_API_KEY"],
            "capabilities": [],
        },
    },
    "deepseek": {
        "chat": {
            "model_type": "chat",
            "default_model": "deepseek-v4-pro",
            "model_env": "DEEPSEEK_MODEL",
            "api_key_envs": ["DEEPSEEK_API_KEY"],
            "capabilities": ["text", "reasoning"],
        },
        "embedding": {
            "model_type": "embedding",
            "default_model": "deepseek-embedding",
            "model_env": "DEEPSEEK_EMBEDDING_MODEL",
            "api_key_envs": ["DEEPSEEK_API_KEY"],
            "capabilities": [],
        },
    },
    "minimax": {
        "chat": {
            "model_type": "chat",
            "default_model": "MiniMax-M2.7",
            "model_env": "MINIMAX_MODEL",
            "api_key_envs": ["MINIMAX_API_KEY"],
            "capabilities": ["text"],
        },
        "embedding": {
            "model_type": "embedding",
            "default_model": "minimax-embedding",
            "model_env": "MINIMAX_EMBEDDING_MODEL",
            "api_key_envs": ["MINIMAX_API_KEY"],
            "capabilities": [],
        },
        "image_gen": {
            "model_type": "image_gen",
            "default_model": "abab6.5s-image",
            "model_env": "MINIMAX_IMAGE_GEN_MODEL",
            "api_key_envs": ["MINIMAX_API_KEY"],
            "capabilities": [],
        },
    },
}

# Per-provider default generation parameters.
# These are applied when constructing the pool ModelConfig.
DEFAULT_PROVIDER_PARAMS: dict[str, dict[str, Any]] = {
    "zhipu": {},
    "kimi": {},
    "deepseek": {},
    "minimax": {},
}

# ------------------------------------------------------------------------------
# Embedding defaults
# ------------------------------------------------------------------------------

DEFAULT_EMBEDDING_PROVIDER: str = "zhipu"
DEFAULT_EMBEDDING_MODEL: str = "embedding-3"

# ------------------------------------------------------------------------------
# Image generation defaults
# ------------------------------------------------------------------------------

DEFAULT_IMAGE_GEN_PROVIDER: str = "zhipu"
DEFAULT_IMAGE_GEN_MODEL: str = "cogview-3-plus"

# ------------------------------------------------------------------------------
# Content truncation limits (prompt injection guards)
# ------------------------------------------------------------------------------

# When injecting referenced file content into LLM prompts (e.g.
# edit-markdown-file, create-markdown-file, and scripting actions),
# cap the text at this length to avoid blowing up the context window.
DEFAULT_REFERENCE_TRUNCATE: int = 8000

# When sending existing file content to the LLM (e.g. edit-markdown-file
# needs the current document to generate diffs, or read-markdown-file
# sends the doc for summarisation), truncate after this many characters.
DEFAULT_CONTENT_TRUNCATE: int = 16000

# ------------------------------------------------------------------------------
# Debug / preview limits
# ------------------------------------------------------------------------------

# How many characters of the raw LLM response to show in error logs when JSON
# parsing fails. Larger values help debugging malformed responses but may clutter
# logs.  This preview is **not** fed back to the LLM; it is for human operators only.
DEFAULT_LLM_PARSE_PREVIEW_CHARS: int = 2000

# How many characters of the raw (uncleaned) LLM response to include in
# LLMResponseParseError exception messages.  These messages are recorded in
# loop_error_list and fed back to the LLM in the next turn.
DEFAULT_INTERPRETER_RAW_PREVIEW_CHARS: int = 800

# How many characters of the cleaned response (markdown stripped, etc.) to
# include in LLMResponseParseError exception messages.  Also fed back to the LLM.
DEFAULT_INTERPRETER_CLEANED_PREVIEW_CHARS: int = 400

# ------------------------------------------------------------------------------
# Action execution timeouts (seconds)
# ------------------------------------------------------------------------------

# Default timeout for any SINGLE_RUN action whose executor does not specify
# an individual override. ONGOING actions use this for their *startup* phase.
DEFAULT_ACTION_TIMEOUT: float = 120.0

# Default for CLI-type actions (git, npm, etc.). These often involve external
# network or filesystem operations and may need more time than pure compute.
DEFAULT_CLI_TIMEOUT: float = 60.0

# Default for SCRIPT-type actions running in the sandbox. Expected to be
# lightweight; kept tight to fail fast on runaway LLM-generated code.
DEFAULT_SCRIPT_TIMEOUT: float = 15.0

# ------------------------------------------------------------------------------
# Query Loop
# ------------------------------------------------------------------------------

# Maximum number of agent ↔ LLM turns in a single query session.
DEFAULT_MAX_TURNS: int = 20

# ------------------------------------------------------------------------------
# Parallel Dispatch
# ------------------------------------------------------------------------------

# Buffer added to the slowest action's individual timeout when computing the
# default batch timeout for ParallelDispatcher. Accounts for thread scheduling
# overhead and ensures the dispatcher does not give up before the slowest
# action has had a chance to trigger its own internal timeout.
DEFAULT_PARALLEL_DISPATCH_BUFFER: float = 20.0

# Maximum number of concurrent worker threads for ParallelDispatcher.
# Limits thread creation when LLM selects a large number of parallel actions.
DEFAULT_PARALLEL_MAX_WORKERS: int = 5

# ------------------------------------------------------------------------------
# Context Compact
# ------------------------------------------------------------------------------

# Maximum number of recent action records to keep in full detail
# when building compact state for LLM prompts.
DEFAULT_COMPACT_MAX_RECORDS: int = 10

# Maximum number of recent loop errors to keep in full detail
# when building compact state for LLM prompts.
DEFAULT_COMPACT_MAX_ERRORS: int = 5

# Maximum number of recent change_log entries per resource to keep
# when building compact workspace for LLM prompts.
DEFAULT_COMPACT_MAX_LOGS: int = 3

# ------------------------------------------------------------------------------
# Logging
# ------------------------------------------------------------------------------

# Log verbosity level.
# Supported values: quiet | normal | verbose | debug
DEFAULT_LOG_LEVEL: str = "normal"

# Comma-separated list of log categories to enable, or "all".
# Supported categories depend on the logger implementation (e.g. loop, action, state, error).
DEFAULT_LOG_CATEGORIES: str = "all"

# Whether to use ANSI color codes in console log output.
# "1" = enabled, "0" = disabled.
DEFAULT_LOG_COLOR: str = "1"
