"""End-to-end integration test: dog weight query with real LLM API."""

from __future__ import annotations

import os

import pytest

from tinysoul.loop.loop import QueryLoop
from tinysoul.action.framework.registry import ActionRegistry
from tinysoul.action.handlers import bootstrap

_RUN_REAL_API_TESTS = os.environ.get("RUN_REAL_API_TESTS", "").lower() in ("1", "true", "yes")


def _bootstrapped_registry():
    registry = ActionRegistry()
    bootstrap(registry)
    return registry


@pytest.mark.skipif(not _RUN_REAL_API_TESTS, reason="Set RUN_REAL_API_TESTS=1")
@pytest.mark.real_api
class TestDogWeightQuery:
    def test_combined_dog_weight(self, capsys):
        query = (
            "I have 2 dogs, a border collie and a scottish terrier. "
            "What is their combined weight"
        )
        query_manager = QueryLoop(
            initial_query=query,
            loop_target="Compute combined weight of a border collie and a scottish terrier",
            available_action_names=["answer", "reasoning", "calculate", "average_dog_weight"],
            registry=_bootstrapped_registry(),
        )
        result = query_manager.query_loop(max_turns=5)
        assert result is not None
        assert result.final_state is not None
