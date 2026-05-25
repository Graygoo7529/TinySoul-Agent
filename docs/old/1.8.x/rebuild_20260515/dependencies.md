# Dependencies

Runtime and development dependencies for TinySoul.

## Runtime

| Package | Version | Purpose |
|---------|---------|---------|
| `openai` | >=1.0 | Unified LLM client base (Chat / Embedding / Image Generation adapters for all providers) |

All other runtime functionality relies on the Python standard library:
- `dataclasses`, `enum`, `typing`, `pathlib`, `json`, `re`, `abc` — data modelling and framework plumbing
- `os`, `sys`, `time`, `threading` — system interaction and sandboxing
- `ast` — temporary script AST validation
- `datetime` — timestamping

## Development

| Package | Purpose |
|---------|---------|
| `pytest` | Test runner |

## Environment Setup

```bash
pip install openai pytest
```

> **Note:** There is no `pyproject.toml`, `requirements.txt`, or `setup.py` in the project root. Dependencies are managed manually.
