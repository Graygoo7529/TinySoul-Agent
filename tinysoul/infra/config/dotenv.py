"""Dotenv parsing that does not mutate process environment."""

from __future__ import annotations

from pathlib import Path

from ..filesystem import atomic_write_text
from .errors import ConfigError
from .source import ConfigSource, ConfigSourceKind


def parse_dotenv(text: str) -> dict[str, str]:
    """Parse dotenv text into key/value pairs without modifying os.environ."""

    result: dict[str, str] = {}
    for line_no, raw_line in enumerate(text.splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        if "=" not in line:
            continue
        key, raw_value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue
        result[key] = _parse_value(raw_value.strip(), line_no=line_no)
    return result


def _parse_value(raw: str, *, line_no: int) -> str:
    if not raw:
        return ""
    if raw[0] in ("'", '"'):
        quote = raw[0]
        chars: list[str] = []
        escaped = False
        for char in raw[1:]:
            if escaped:
                chars.append(_unescape(char) if quote == '"' else char)
                escaped = False
                continue
            if quote == '"' and char == "\\":
                escaped = True
                continue
            if char == quote:
                return "".join(chars)
            chars.append(char)
        raise ConfigError(
            "Unclosed quoted dotenv value",
            key=f"dotenv.line.{line_no}",
            value=raw,
            expected="closed quote",
        )
    return _strip_inline_comment(raw).strip()


def _strip_inline_comment(value: str) -> str:
    in_space = False
    for idx, char in enumerate(value):
        if char.isspace():
            in_space = True
            continue
        if char == "#" and in_space:
            return value[:idx]
        in_space = False
    return value


def _unescape(char: str) -> str:
    return {
        "n": "\n",
        "r": "\r",
        "t": "\t",
        "\\": "\\",
        '"': '"',
    }.get(char, char)


class DotenvSource:
    """File-backed dotenv configuration source."""

    def __init__(self, path: Path, *, prefix: str = "TINYSOUL_") -> None:
        self.path = path
        self.prefix = prefix

    def load(self) -> ConfigSource:
        if not self.path.exists():
            return ConfigSource.empty(
                str(self.path),
                kind=ConfigSourceKind.DOTENV,
                path=self.path,
                source_id="dotenv",
            )
        values = parse_dotenv(self.path.read_text(encoding="utf-8"))
        return ConfigSource(
            name=str(self.path),
            values=_env_mapping_to_dotted(values, prefix=self.prefix),
            kind=ConfigSourceKind.DOTENV,
            path=self.path,
            source_id="dotenv",
        )

    def load_raw(self) -> dict[str, str]:
        """Load dotenv values using their original environment variable names."""
        if not self.path.exists():
            return {}
        return parse_dotenv(self.path.read_text(encoding="utf-8"))


class DotenvDocument:
    """Editable dotenv document that preserves untouched lines and comments."""

    def __init__(self, path: Path) -> None:
        self.path = path
        text = path.read_text(encoding="utf-8") if path.exists() else ""
        self._lines = text.splitlines()

    @property
    def values(self) -> dict[str, str]:
        return parse_dotenv(self.render())

    def set_value(self, key: str, value: str) -> None:
        _validate_env_key(key)
        if not isinstance(value, str):
            raise ConfigError(
                "Dotenv value must be text",
                key=key,
                source=str(self.path),
                value=type(value).__name__,
                expected="str",
            )
        rendered = f"{key}={_format_env_value(value)}"
        indexes = _dotenv_key_indexes(self._lines, key)
        if indexes:
            first = indexes[0]
            self._lines[first] = rendered
            for index in reversed(indexes[1:]):
                del self._lines[index]
            return
        if self._lines and self._lines[-1].strip():
            self._lines.append("")
        self._lines.append(rendered)

    def delete_value(self, key: str) -> None:
        _validate_env_key(key)
        for index in reversed(_dotenv_key_indexes(self._lines, key)):
            del self._lines[index]

    def render(self) -> str:
        if not self._lines:
            return ""
        return "\n".join(self._lines).rstrip() + "\n"

    def save(self) -> None:
        atomic_write_text(self.path, self.render())


def _validate_env_key(key: str) -> None:
    if not isinstance(key, str) or not key or not (
        key[0].isalpha() or key[0] == "_"
    ) or any(not (char.isalnum() or char == "_") for char in key):
        raise ConfigError(
            "Dotenv key is invalid",
            key=str(key),
            expected="environment variable name",
        )


def _dotenv_key_indexes(lines: list[str], key: str) -> list[int]:
    indexes: list[int] = []
    for index, raw in enumerate(lines):
        line = raw.strip()
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        if "=" not in line:
            continue
        candidate, _value = line.split("=", 1)
        if candidate.strip() == key:
            indexes.append(index)
    return indexes


def _format_env_value(value: str) -> str:
    if value and all(
        char.isalnum() or char in "_./:-" for char in value
    ):
        return value
    escaped = (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )
    return f'"{escaped}"'


def _env_mapping_to_dotted(
    values: dict[str, str], *, prefix: str = "TINYSOUL_"
) -> dict[str, str]:
    result: dict[str, str] = {}
    for key, value in values.items():
        if not key.startswith(prefix):
            continue
        dotted = _env_key_to_dotted(key[len(prefix) :])
        result[dotted] = value
    return result


def _env_key_to_dotted(key: str) -> str:
    lowered = key.lower()
    if "__" in lowered:
        return ".".join(part for part in lowered.split("__") if part)

    parts = lowered.split("_")
    if len(parts) <= 2:
        return lowered
    return ".".join([parts[0], parts[1], "_".join(parts[2:])])
