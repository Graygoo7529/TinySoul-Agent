"""Script capability domain objects."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256


class ScriptLanguage(StrEnum):
    PYTHON = "python"
    BASH = "bash"

    @property
    def suffix(self) -> str:
        return ".py" if self is ScriptLanguage.PYTHON else ".sh"


@dataclass(frozen=True)
class ScriptSource:
    link: str
    text: str
    digest: str
    language: ScriptLanguage

    @property
    def snapshot_digest(self) -> str:
        """Digest the exact normalized UTF-8 snapshot checked by Script policy."""

        return sha256(self.text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ScriptMutation:
    link: str
    digest: str
    size: int
    state: str
