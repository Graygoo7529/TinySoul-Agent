"""One atomic semantic document sharing the Session root's day lifecycle."""

import json
from pathlib import Path

from tinysoul.infra.filesystem import atomic_write_text
from tinysoul.infra.json import dumps_json
from ..errors import SessionContractError, SessionIOError, SessionInvariantError
from .models import SessionMap


class AnnotationStore:
    def __init__(self, root: Path) -> None:
        self._path = root / "map.json"

    def load(self) -> SessionMap:
        try:
            text = self._path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return SessionMap()
        except UnicodeError as exc:
            raise SessionInvariantError(
                "Session annotations are not valid UTF-8"
            ) from exc
        except OSError as exc:
            raise SessionIOError("Session annotations could not be read") from exc
        try:
            return SessionMap.parse(json.loads(text))
        except (json.JSONDecodeError, SessionContractError) as exc:
            raise SessionInvariantError("Session annotations are invalid") from exc

    def save(self, value: SessionMap) -> None:
        try:
            atomic_write_text(self._path, dumps_json(value.to_json()) + "\n")
        except OSError as exc:
            raise SessionIOError("Session annotations could not be saved") from exc
