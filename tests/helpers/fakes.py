"""Unified fake implementations for testing TinySoul without real dependencies."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from tinysoul.action.framework.run_config import TerminationReason
from tinysoul.context.ongoing import OngoingControl, OngoingControlRegistry
from tinysoul.llm.provider.response import AIResponse
from tinysoul.context.protocols import ContextProvider


# -----------------------------------------------------------------------------
# Fake LLM Client
# -----------------------------------------------------------------------------


@dataclass
class FakeLLMClient:
    """Deterministic LLM client that returns preset responses and records all calls."""

    responses: list[str] = field(default_factory=list)
    _call_index: int = field(default=0, repr=False)
    calls: list[dict[str, Any]] = field(default_factory=list, repr=False)

    def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        profile: Any,
        system: list[dict[str, str]] | None = None,
        config: Any | None = None,
    ) -> AIResponse:
        self.calls.append(
            {
                "messages": messages,
                "profile": profile,
                "system": system,
                "config": config,
            }
        )
        if self._call_index >= len(self.responses):
            prompt_preview = ""
            if messages and isinstance(messages[0].get("content"), str):
                prompt_preview = messages[0]["content"][:200]
            raise RuntimeError(
                f"Unexpected AI call #{self._call_index}. "
                f"Prompt preview: {prompt_preview}"
            )
        response = self.responses[self._call_index]
        self._call_index += 1
        return AIResponse(content=response)

    def has_next_model(self) -> bool:
        return False

    def switch_to_next_model(self) -> None:
        pass

    def assert_call_count(self, expected: int) -> None:
        assert len(self.calls) == expected, (
            f"Expected {expected} calls, got {len(self.calls)}"
        )

    def assert_system_contains(self, call_idx: int, text: str) -> None:
        call = self.calls[call_idx]
        system = call.get("system") or []
        content = " ".join(m.get("content", "") for m in system)
        assert text in content, (
            f"Expected system to contain {text!r}, got {content!r}"
        )

    def assert_user_prompt_contains(self, call_idx: int, text: str) -> None:
        call = self.calls[call_idx]
        messages = call.get("messages", [])
        content = ""
        for msg in messages:
            c = msg.get("content", "")
            if isinstance(c, str):
                content += c
            elif isinstance(c, list):
                for part in c:
                    if isinstance(part, dict) and part.get("type") == "text":
                        content += part.get("text", "")
        assert text in content, (
            f"Expected user prompt to contain {text!r}, got {content!r}"
        )


# -----------------------------------------------------------------------------
# Fake Context Provider
# -----------------------------------------------------------------------------


@dataclass
class FakeContextProvider(ContextProvider):
    """Complete ContextProvider implementation for testing."""

    query_events: str = "test query"
    loop_target: str = "test target"
    current_turn: int = 1
    query_state: Any = None
    query_action: Any = None
    _workspace: Any = None
    _client: Any = None
    _ongoing_controls: OngoingControlRegistry = field(
        default_factory=OngoingControlRegistry
    )

    @property
    def client(self) -> Any | None:
        return self._client

    @property
    def current_state(self) -> Any:
        return self.query_state

    @property
    def workspace(self) -> Any | None:
        return self._workspace

    def get_current_state(self) -> dict:
        if self.query_state is not None:
            return self.query_state.get_current_state()
        return {
            "action_record_list": [],
            "feedback_error_list": [],
            "current_turn": self.current_turn,
            "todo_list": [],
            "milestone_list": [],
            "ongoing_action_list": [],
        }

    def get_workspace(self) -> dict:
        if self._workspace is not None:
            return self._workspace.to_dict()
        return {}

    def get_loop_level_system(self) -> list[dict[str, str]]:
        return []

    def register_ongoing_control(self, control: OngoingControl) -> None:
        self._ongoing_controls.register(control)

    def unregister_ongoing_control(self, execution_id: str) -> OngoingControl | None:
        return self._ongoing_controls.unregister(execution_id)

    def request_ongoing_termination(
        self,
        execution_id: str,
        reason: TerminationReason = TerminationReason.USER_CANCEL,
    ) -> bool:
        return self._ongoing_controls.request_termination(execution_id, reason)

    def request_all_ongoing_termination(
        self,
        reason: TerminationReason = TerminationReason.SHUTDOWN,
    ) -> int:
        return self._ongoing_controls.request_all_termination(reason)
