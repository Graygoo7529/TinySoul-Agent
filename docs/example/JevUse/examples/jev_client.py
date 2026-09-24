"""Small standard-library client for the TypeSafe Jev System One API."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def load_dotenv() -> None:
    """Load simple KEY=VALUE entries from the project root .env if present."""
    here = Path(__file__).resolve()
    for parent in [here.parent, *here.parents]:
        env_path = parent / ".env"
        if env_path.exists():
            for raw_line in env_path.read_text(encoding="utf-8").splitlines():
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
            return


def call_jev(payload: dict[str, Any], *, retries: int = 3) -> dict[str, Any]:
    load_dotenv()
    api_key = os.environ.get("TYPESAFE_API_KEY")
    if not api_key:
        raise RuntimeError("TYPESAFE_API_KEY is not set; create a local .env first")
    endpoint = os.environ.get("TYPESAFE_ENDPOINT", "https://api.typesafe.ai/v1/systemone")
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = Request(
        endpoint,
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    for attempt in range(retries + 1):
        try:
            with urlopen(request, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            if exc.code not in (429, 529) or attempt == retries:
                detail = exc.read().decode("utf-8", errors="replace")
                raise RuntimeError(f"Jev API HTTP {exc.code}: {detail}") from exc
        except URLError as exc:
            if attempt == retries:
                raise RuntimeError(f"Jev API network error: {exc}") from exc
        time.sleep(2**attempt)
    raise RuntimeError("unreachable")
