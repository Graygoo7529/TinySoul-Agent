"""LLM module failure semantics."""

from __future__ import annotations

from enum import StrEnum

LLM_CONTEXT_CAPACITY_EXCEEDED = "llm.context_capacity_exceeded"


class LLMFailureKind(StrEnum):
    """Stable LLM failure kinds used by runtime bridges."""

    MODEL_CHAIN_EXHAUSTED = "llm.model_chain_exhausted"
    MODEL_CONTEXT_PRESSURE = "llm.model_context_pressure"
    MODEL_CONTEXT_LIMIT_REACHED = "llm.model_context_limit_reached"
    CONFIGURATION_FAILED = "llm.configuration_failed"
    CONTRACT_VIOLATION = "llm.contract_violation"
    INTERNAL_FAILURE = "llm.internal_failure"
