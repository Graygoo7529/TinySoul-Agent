from __future__ import annotations

from tinysoul.infra.json import dumps_json
from tinysoul.llm.messages import (
    AssistantMessage,
    ImagePart,
    ImageUrlPart,
    MessageStack,
    UserMessage,
)
from tinysoul.llm.observation_payloads import (
    task_request_observation,
    task_response_observation,
)
from tinysoul.llm.reasoning import Reasoning
from tinysoul.llm.responses import RawResponse
from tinysoul.llm.tools import ToolKind, ToolScope, ToolSpec


def test_model_request_observation_redacts_binary_and_reasoning_payloads() -> None:
    messages = MessageStack.of(
        UserMessage.from_parts(
            ImagePart(b"secret-image-bytes", "image/png"),
            ImageUrlPart(
                "https://user:password@example.test/image.png?token=secret#fragment"
            ),
        ),
        AssistantMessage.from_text(
            "visible answer",
            reasoning=Reasoning(
                content="private chain of thought",
                summary="safe summary",
                encrypted_items=({"ciphertext": "encrypted-secret"},),
            ),
        ),
    )
    tools = ToolScope(
        tools=(
            ToolSpec(
                name="read",
                description="Read a value",
                parameters={"type": "object"},
                kind=ToolKind.CONTROL,
            ),
        )
    )

    rendered = dumps_json(task_request_observation(messages, tools))

    assert "secret-image-bytes" not in rendered
    assert "password" not in rendered
    assert "token=secret" not in rendered
    assert "private chain of thought" not in rendered
    assert "encrypted-secret" not in rendered
    assert "safe summary" in rendered
    assert "https://example.test/image.png" in rendered


def test_model_response_observation_omits_provider_payload_and_raw_reasoning() -> None:
    response = RawResponse(
        answer_text="visible answer",
        model_id="model_a",
        provider_id="provider_a",
        reasoning=Reasoning(
            content="private chain of thought",
            summary="safe summary",
            encrypted_items=({"ciphertext": "encrypted-secret"},),
        ),
        usage={"input_tokens": 12},
        metadata={"opaque": object()},
        provider_payload={"provider_secret": "must-not-appear"},
    )

    rendered = dumps_json(task_response_observation(response))

    assert "visible answer" in rendered
    assert "safe summary" in rendered
    assert "private chain of thought" not in rendered
    assert "encrypted-secret" not in rendered
    assert "must-not-appear" not in rendered
    assert '"opaque":"object"' in rendered
