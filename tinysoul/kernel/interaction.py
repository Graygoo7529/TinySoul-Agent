"""Question and answer values shared by Actions, Turn admission and facts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from tinysoul.infra.json import JsonObject, JsonValue
from tinysoul.prompts.kernel import interaction as prompt_text


class QuestionError(Exception):
    """Invalid question content or an answer that cannot satisfy it."""


@dataclass(frozen=True)
class InteractionNarrative:
    """A derived reading projection, never a second interaction fact."""

    title: str
    parts: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        if not self.title or not self.parts:
            raise QuestionError("Interaction narrative requires a title and content")

    @property
    def text(self) -> str:
        return "\n".join(body for _, body in self.parts)


def _text(value: object, *, maximum: int, empty: bool = False) -> str:
    if (
        not isinstance(value, str)
        or len(value) > maximum
        or (not empty and not value.strip())
    ):
        raise QuestionError("Question or answer text is invalid")
    return value


@dataclass(frozen=True)
class QuestionOption:
    id: str
    label: str
    description: str = ""

    def __post_init__(self) -> None:
        _text(self.id, maximum=128)
        _text(self.label, maximum=256)
        _text(self.description, maximum=2000, empty=True)

    def to_json(self) -> JsonObject:
        return {"id": self.id, "label": self.label, "description": self.description}


@dataclass(frozen=True)
class QuestionContent:
    question: str
    options: tuple[QuestionOption, ...] = ()
    allow_other: bool = True
    details: str = ""

    def __post_init__(self) -> None:
        _text(self.question, maximum=16000)
        _text(self.details, maximum=16000, empty=True)
        if type(self.allow_other) is not bool or len(self.options) > 8:
            raise QuestionError("Question options or other-answer policy is invalid")
        if any(not isinstance(item, QuestionOption) for item in self.options) or len(
            {item.id for item in self.options}
        ) != len(self.options):
            raise QuestionError("Question options require unique identities")
        object.__setattr__(self, "options", tuple(self.options))
        if not self.options and not self.allow_other:
            raise QuestionError("Question must allow an answer")

    @property
    def text(self) -> str:
        return f"{self.details}\n\n{self.question}" if self.details else self.question

    def display(self) -> JsonObject:
        return {**self.to_json(), "text": self.text}

    @property
    def title(self) -> str:
        return prompt_text.question_title(self.question[:160])

    def to_json(self) -> JsonObject:
        return {
            "question": self.question,
            "details": self.details,
            "options": [item.to_json() for item in self.options],
            "allow_other": self.allow_other,
        }

    @classmethod
    def from_json(cls, value: JsonObject) -> QuestionContent:
        raw = value.get("options", [])
        if not isinstance(raw, list):
            raise QuestionError("Question options must be an array")
        options: list[QuestionOption] = []
        for option in raw:
            if not isinstance(option, dict) or set(option) - {
                "id",
                "label",
                "description",
            }:
                raise QuestionError("Question option is invalid")
            options.append(
                QuestionOption(
                    _text(option.get("id"), maximum=128),
                    _text(option.get("label"), maximum=256),
                    _text(option.get("description", ""), maximum=2000, empty=True),
                )
            )
        other = value.get("allow_other", True)
        if type(other) is not bool:
            raise QuestionError("Question other-answer policy must be boolean")
        return cls(
            question=_text(value.get("question"), maximum=16000),
            details=_text(value.get("details", ""), maximum=16000, empty=True),
            options=tuple(options),
            allow_other=other,
        )

    def answer_text(self, answer: QuestionAnswer) -> str:
        if answer.kind is AnswerKind.TEXT:
            if self.options and not self.allow_other:
                raise QuestionError("This question requires one of its options")
            return answer.text
        option = next(
            (item for item in self.options if item.id == answer.option_id), None
        )
        if option is None:
            raise QuestionError("Answer does not identify a current option")
        return "\n".join(
            part
            for part in (
                f"{option.label} ({option.id})",
                option.description,
                answer.comment,
            )
            if part
        )

    def narrative(self) -> str:
        return prompt_text.question(
            text=self.text,
            options=tuple(
                (item.id, item.label, item.description) for item in self.options
            ),
            allow_other=self.allow_other,
        )

    def narrative_parts(self) -> tuple[tuple[str, str], ...]:
        return prompt_text.question_parts(
            text=self.text,
            options=tuple(
                (item.id, item.label, item.description) for item in self.options
            ),
            allow_other=self.allow_other,
        )

    def reply_narrative(self, answer: QuestionAnswer) -> str:
        return self.reply_projection(answer).text

    def reply_projection(self, answer: QuestionAnswer) -> InteractionNarrative:
        self.answer_text(answer)  # Validate the answer against this question.
        option = next(
            (item for item in self.options if item.id == answer.option_id), None
        )
        return InteractionNarrative(
            prompt_text.reply_title(
                " ".join(self.question.split())[:100],
                " ".join((option.label if option else answer.text).split())[:80],
            ),
            prompt_text.reply_parts(
                question=self.text,
                text=answer.text,
                selected=option.label if option else "",
                description=option.description if option else "",
                comment=answer.comment,
            ),
        )


def input_narrative(text: str, *, initial: bool) -> str:
    return prompt_text.input_text(text=text, initial=initial)


def input_title(*, initial: bool) -> str:
    return prompt_text.input_title(initial)


def input_projection(text: str, *, initial: bool) -> InteractionNarrative:
    title = input_title(initial=initial)
    return InteractionNarrative(
        title, ((title, input_narrative(text, initial=initial)),)
    )


class AnswerKind(StrEnum):
    CHOICE = "choice"
    TEXT = "text"


@dataclass(frozen=True)
class QuestionAnswer:
    kind: AnswerKind
    text: str = ""
    option_id: str = ""
    comment: str = ""

    def __post_init__(self) -> None:
        if self.kind is AnswerKind.TEXT:
            _text(self.text, maximum=16000)
            if self.option_id or self.comment:
                raise QuestionError("Text answer cannot carry a choice")
        elif self.kind is AnswerKind.CHOICE:
            _text(self.option_id, maximum=128)
            _text(self.comment, maximum=16000, empty=True)
            if self.text:
                raise QuestionError("Choice answer cannot carry free text")
        else:
            raise QuestionError("Answer kind must be typed")

    def to_json(self) -> JsonObject:
        if self.kind is AnswerKind.TEXT:
            return {"kind": self.kind.value, "text": self.text}
        return {
            "kind": self.kind.value,
            "option_id": self.option_id,
            "comment": self.comment,
        }

    @classmethod
    def from_json(cls, value: JsonValue) -> QuestionAnswer:
        if not isinstance(value, dict):
            raise QuestionError("Answer must be an object")
        if value.get("kind") == "text" and not set(value) - {"kind", "text"}:
            return cls(AnswerKind.TEXT, text=_text(value.get("text"), maximum=16000))
        if value.get("kind") == "choice" and not set(value) - {
            "kind",
            "option_id",
            "comment",
        }:
            return cls(
                AnswerKind.CHOICE,
                option_id=_text(value.get("option_id"), maximum=128),
                comment=_text(value.get("comment", ""), maximum=16000, empty=True),
            )
        raise QuestionError("Answer does not match the choice/text protocol")
