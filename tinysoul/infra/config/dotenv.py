"""Dotenv parsing that does not mutate process environment."""

from __future__ import annotations

from pathlib import Path

from .errors import ConfigError
from .source import ConfigSource


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
            return ConfigSource.empty(str(self.path))
        values = parse_dotenv(self.path.read_text(encoding="utf-8"))
        return ConfigSource(
            name=str(self.path),
            values=_env_mapping_to_dotted(values, prefix=self.prefix),
        )

    def load_raw(self) -> dict[str, str]:
        """Load dotenv values using their original environment variable names."""
        if not self.path.exists():
            return {}
        return parse_dotenv(self.path.read_text(encoding="utf-8"))


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
