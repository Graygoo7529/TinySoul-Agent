"""Structured Turn and Turn-owned Job protocol schemas."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from tinysoul.infra.json import JsonValue
from tinysoul.kernel.interaction import AnswerKind, QuestionAnswer


class TurnCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["user", "home", "memory"] = "user"
    text: str = Field(default="", max_length=16000)
    target_day: str = ""
    instructions: str = Field(default="", max_length=16000)
    metadata: dict[str, JsonValue] = Field(default_factory=dict)
    command_id: str = Field(default="", max_length=128)


class TurnInputRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1)
    input_id: str = Field(default="", max_length=128)


class ChoiceAnswerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["choice"]
    option_id: str = Field(min_length=1, max_length=128)
    comment: str = Field(default="", max_length=16000)

    def to_answer(self) -> QuestionAnswer:
        return QuestionAnswer(
            AnswerKind.CHOICE, option_id=self.option_id, comment=self.comment
        )


class TextAnswerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["text"]
    text: str = Field(min_length=1, max_length=16000)

    def to_answer(self) -> QuestionAnswer:
        return QuestionAnswer(AnswerKind.TEXT, text=self.text)


class TurnReplyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question_id: str = Field(min_length=1, max_length=128)
    answer: Annotated[
        ChoiceAnswerRequest | TextAnswerRequest, Field(discriminator="kind")
    ]


class TurnGrantRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(min_length=1, max_length=128)
    count: int = Field(gt=0, strict=True)
