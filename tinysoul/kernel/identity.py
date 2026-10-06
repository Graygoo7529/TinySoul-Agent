"""Turn identity shared by execution, Context and persistent fact owners."""

from dataclasses import dataclass

from tinysoul.infra.time import CalendarDay, CalendarDayError


class TurnIdentityError(Exception):
    """A Turn identity does not have its canonical date/sequence form."""


@dataclass(frozen=True)
class TurnIdentity:
    day: CalendarDay
    sequence: int

    def __post_init__(self) -> None:
        if (
            not isinstance(self.day, CalendarDay)
            or type(self.sequence) is not int
            or self.sequence < 1
        ):
            raise TurnIdentityError(
                "Turn identity requires a CalendarDay and positive sequence"
            )

    def __str__(self) -> str:
        return f"{self.day}/{self.sequence}"

    @classmethod
    def parse(cls, value: str) -> "TurnIdentity":
        day, separator, sequence = value.partition("/")
        if (
            not separator
            or not sequence.isascii()
            or not sequence.isdecimal()
            or sequence.startswith("0")
        ):
            raise TurnIdentityError("Turn identity must use YYYY-MM-DD/sequence")
        try:
            return cls(CalendarDay.parse(day), int(sequence))
        except (CalendarDayError, ValueError) as exc:
            raise TurnIdentityError(
                "Turn identity must use YYYY-MM-DD/sequence"
            ) from exc
