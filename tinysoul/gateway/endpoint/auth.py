"""Stable Endpoint authentication stored beside a project deployment."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from secrets import token_urlsafe

from .errors import EndpointContractError

AUTH_FILE_NAME = ".auth"
MIN_TOKEN_LENGTH = 32


@dataclass(frozen=True)
class EndpointAuth:
    """The single stable bearer token used by one project Endpoint."""

    token: str

    def __post_init__(self) -> None:
        if not isinstance(self.token, str) or len(self.token.strip()) < MIN_TOKEN_LENGTH:
            raise EndpointContractError(
                "Endpoint auth token must contain at least 32 characters"
            )
        object.__setattr__(self, "token", self.token.strip())


def generated_auth_text() -> str:
    """Return one newly generated auth file without writing it."""

    return f"token={token_urlsafe(32)}\n"


def load_endpoint_auth(root: Path) -> EndpointAuth:
    """Read and validate the deployment-local auth file."""

    path = root / AUTH_FILE_NAME
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise EndpointContractError(
            f"Endpoint auth file is missing: {path}"
        ) from exc
    except OSError as exc:
        raise EndpointContractError(
            f"Endpoint auth file cannot be read: {path}"
        ) from exc

    entries = [
        line.strip()
        for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    if len(entries) != 1 or not entries[0].startswith("token="):
        raise EndpointContractError(
            f"Endpoint auth file must contain one token entry: {path}"
        )
    return EndpointAuth(entries[0][len("token=") :])
