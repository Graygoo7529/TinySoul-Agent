"""Machine checks for the committed frontend endpoint contract fixtures."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, RefResolver


ROOT = Path(__file__).parents[3] / "docs" / "endpoint" / "contracts"


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _validate(schema_name: str, value: dict[str, Any]) -> None:
    path = ROOT / "schemas" / schema_name
    schema = _load(path)
    resolver = RefResolver(path.as_uri(), schema)
    Draft202012Validator(schema, resolver=resolver).validate(value)


def test_fixed_contract_examples_validate() -> None:
    _validate("runtime-status.json", _load(ROOT / "examples" / "runtime-status.json"))
    receipts = _load(ROOT / "examples" / "turn-receipts.json")
    for receipt in receipts.values():
        _validate("command-receipt.json", receipt)
    _validate("turn-snapshot.json", _load(ROOT / "examples" / "turn-finished.json"))
    config = _load(ROOT / "examples" / "config-views.json")
    for name in ("saved", "active"):
        _validate("configuration.json", config[name])


def test_context_resource_and_page_examples_validate() -> None:
    _validate("context-overview.json", _load(ROOT / "examples" / "context-overview.json"))
    _validate("page.json", _load(ROOT / "examples" / "context-trace-page.json"))
    _validate("page.json", _load(ROOT / "examples" / "home-effective.json"))
    _validate("page.json", _load(ROOT / "examples" / "empty-page.json"))
    _validate("search-page.json", _load(ROOT / "examples" / "search-evidence.json"))
    _validate("job.json", _load(ROOT / "examples" / "job-output.json"))
    _validate("resource-resolve.json", _load(ROOT / "examples" / "memory-fragment.json"))
    _validate(
        "error.json",
        _load(ROOT / "examples" / "home-diff-memory-redirect.json")["error"],
    )
