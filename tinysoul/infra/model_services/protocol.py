"""Typed requests and responses at the specialized model boundary."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from math import isfinite

from tinysoul.infra.json import JsonObject, JsonValue, to_json_object


class ModelFailureKind(StrEnum):
    UNAVAILABLE = "unavailable"
    AUTHENTICATION = "authentication"
    CONTRACT = "contract"
    CAPACITY = "capacity"
    OUTPUT = "output_protocol"
    STORAGE = "storage"


class ModelServiceError(Exception):
    def __init__(self, kind: ModelFailureKind, message: str) -> None:
        super().__init__(message)
        self.kind = kind

    @property
    def recoverable(self) -> bool:
        return self.kind is ModelFailureKind.UNAVAILABLE


class QuestionKind(StrEnum):
    NOUL = "noul"
    CHOICE = "choice"
    SCORE = "score"


@dataclass(frozen=True)
class EmbeddingBatch:
    model: str
    dimensions: int
    vectors: tuple[tuple[float, ...], ...]

    def __post_init__(self) -> None:
        if (
            not self.model
            or type(self.dimensions) is not int
            or self.dimensions < 1
            or any(
                len(vector) != self.dimensions
                or any(not isfinite(value) for value in vector)
                for vector in self.vectors
            )
        ):
            raise ModelServiceError(
                ModelFailureKind.CONTRACT,
                "Embedding result has invalid identity, dimensions or vectors",
            )


@dataclass(frozen=True)
class DecisionQuestion:
    id: str
    kind: QuestionKind
    instructions: str
    levels: tuple[str, ...] = ()
    choices: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        if not self.id or not self.instructions.strip():
            raise ModelServiceError(
                ModelFailureKind.CONTRACT, "Question requires identity and instructions"
            )
        if self.kind is QuestionKind.SCORE:
            valid = (
                2 <= len(self.levels) <= 10 and not self.choices and all(self.levels)
            )
        elif self.kind is QuestionKind.CHOICE:
            valid = (
                1 <= len(self.choices) <= 255
                and not self.levels
                and len({key for key, _ in self.choices}) == len(self.choices)
                and all(key for key, _ in self.choices)
            )
        else:
            valid = not self.levels and not self.choices
        if not valid:
            raise ModelServiceError(
                ModelFailureKind.CONTRACT, "Question criteria do not match its type"
            )

    def to_json(self) -> JsonObject:
        value: JsonObject = {"type": self.kind.value, "instructions": self.instructions}
        if self.levels:
            value["criteria"] = list(self.levels)
        elif self.choices:
            value["criteria"] = dict(self.choices)
        return value


@dataclass(frozen=True)
class DecisionRequest:
    state: JsonObject
    questions: tuple[DecisionQuestion, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "state", to_json_object(self.state))
        if not self.questions or len({q.id for q in self.questions}) != len(
            self.questions
        ):
            raise ModelServiceError(
                ModelFailureKind.CONTRACT,
                "Decision questions must be nonempty and unique",
            )


@dataclass(frozen=True)
class DecisionAnswer:
    id: str
    kind: QuestionKind
    value: float | str
    probabilities: tuple[tuple[str, float], ...] = ()
    confidence: float | None = None

    def __post_init__(self) -> None:
        if (
            not self.id
            or (self.kind is QuestionKind.CHOICE and not isinstance(self.value, str))
            or (
                self.kind is not QuestionKind.CHOICE
                and (
                    isinstance(self.value, bool)
                    or not isinstance(self.value, (float, int))
                    or not isfinite(self.value)
                )
            )
        ):
            raise ModelServiceError(
                ModelFailureKind.CONTRACT, "Invalid typed decision answer"
            )


@dataclass(frozen=True)
class DecisionResult:
    model: str
    answers: tuple[DecisionAnswer, ...]
    input_tokens: int = 0
    output_tokens: int = 0

    def __post_init__(self) -> None:
        if not self.model or len({a.id for a in self.answers}) != len(self.answers):
            raise ModelServiceError(
                ModelFailureKind.CONTRACT, "Invalid decision result identity"
            )


def parse_decision_response(
    value: JsonObject, request: DecisionRequest
) -> DecisionResult:
    model, raw_answers = value.get("model"), value.get("answers")
    if (
        not isinstance(model, str)
        or not isinstance(raw_answers, dict)
        or set(raw_answers) != {q.id for q in request.questions}
    ):
        raise ModelServiceError(
            ModelFailureKind.CONTRACT,
            "Decision response identities do not match questions",
        )
    answers = []
    for question in request.questions:
        raw = raw_answers[question.id]
        if not isinstance(raw, dict) or raw.get("type") != question.kind.value:
            raise ModelServiceError(
                ModelFailureKind.CONTRACT,
                "Decision response type does not match question",
            )
        result = raw.get(question.kind.value)
        probabilities: tuple[tuple[str, float], ...] = ()
        confidence = None
        if question.kind is QuestionKind.CHOICE:
            keys = {key for key, _ in question.choices}
            if not isinstance(result, str) or result not in keys:
                raise ModelServiceError(
                    ModelFailureKind.CONTRACT, "Decision returned an unknown choice"
                )
        else:
            result = bounded_number(
                result,
                1 if question.kind is QuestionKind.NOUL else len(question.levels) - 1,
            )
            keys = {str(i) for i in range(len(question.levels))}
        if question.kind is not QuestionKind.NOUL:
            if question.kind is QuestionKind.SCORE and raw.get("legend") != {
                str(index): label for index, label in enumerate(question.levels)
            }:
                raise ModelServiceError(
                    ModelFailureKind.CONTRACT,
                    "Decision score legend does not match its levels",
                )
            raw_probs = raw.get("probabilities")
            if not isinstance(raw_probs, dict) or set(raw_probs) != keys:
                raise ModelServiceError(
                    ModelFailureKind.CONTRACT,
                    "Decision probability identities are invalid",
                )
            probabilities = tuple(
                (key, bounded_number(probability, 1))
                for key, probability in raw_probs.items()
            )
            if abs(sum(p for _, p in probabilities) - 1) > 0.01:
                raise ModelServiceError(
                    ModelFailureKind.CONTRACT,
                    "Decision probabilities do not sum to one",
                )
            confidence = bounded_number(raw.get("confidence"), 1)
        answers.append(
            DecisionAnswer(
                question.id, question.kind, result, probabilities, confidence
            )
        )
    usage = value.get("usage", {})
    if not isinstance(usage, dict):
        raise ModelServiceError(
            ModelFailureKind.CONTRACT, "Decision usage must be an object"
        )
    counts = tuple(usage.get(key, 0) for key in ("input_tokens", "output_tokens"))
    if any(type(count) is not int or count < 0 for count in counts):
        raise ModelServiceError(
            ModelFailureKind.CONTRACT, "Decision token counts are invalid"
        )
    input_tokens, output_tokens = counts
    assert isinstance(input_tokens, int) and isinstance(output_tokens, int)
    return DecisionResult(model, tuple(answers), input_tokens, output_tokens)


def bounded_number(value: JsonValue, maximum: float) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not isfinite(value)
        or not 0 <= value <= maximum
    ):
        raise ModelServiceError(
            ModelFailureKind.CONTRACT, "Decision number is outside its declared range"
        )
    return float(value)
