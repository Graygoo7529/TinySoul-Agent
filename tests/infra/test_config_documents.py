from __future__ import annotations

from pathlib import Path

import pytest

from tinysoul.infra.config import (
    ConfigDocumentWrite,
    ConfigFileToml,
    ConfigFileTransaction,
    ConfigSourceKind,
    DotenvDocument,
    DotenvSource,
)


def test_toml_document_sets_deletes_and_saves_atomically(tmp_path: Path) -> None:
    path = tmp_path / "configs" / "infra.toml"
    path.parent.mkdir()
    path.write_text(
        "[infra.embedding]\nenabled = false\nmodel = \"old\"\n",
        encoding="utf-8",
    )

    document = ConfigFileToml(path)
    document.set_value("infra.embedding.enabled", True)
    document.delete_value("infra.embedding.model")
    document.save()

    loaded = ConfigFileToml(path)
    assert loaded.data == {"infra": {"embedding": {"enabled": True}}}
    source = loaded.to_source()
    assert source.kind is ConfigSourceKind.PROJECT_TOML
    assert source.path == path


def test_dotenv_document_preserves_comments_and_updates_values(tmp_path: Path) -> None:
    path = tmp_path / ".env"
    path.write_text(
        "# Provider credentials\nOLD=value\nKEEP=unchanged\n",
        encoding="utf-8",
    )

    document = DotenvDocument(path)
    document.delete_value("OLD")
    document.set_value("KEEP", "new value")
    document.set_value("NEW_KEY", "secret")
    document.save()

    text = path.read_text(encoding="utf-8")
    assert "# Provider credentials" in text
    assert "OLD=" not in text
    assert 'KEEP="new value"' in text
    assert "NEW_KEY=secret" in text
    assert DotenvSource(path).load_raw() == {
        "KEEP": "new value",
        "NEW_KEY": "secret",
    }


def test_config_transaction_restores_prior_files_when_commit_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = tmp_path / "first.toml"
    second = tmp_path / "second.toml"
    first.write_text("value = 1\n", encoding="utf-8")
    second.write_text("value = 2\n", encoding="utf-8")
    calls = 0

    from tinysoul.infra.config import transaction as transaction_module

    real_write = transaction_module.atomic_write_text

    def fail_second(path: Path, text: str) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("failed")
        real_write(path, text)

    monkeypatch.setattr(transaction_module, "atomic_write_text", fail_second)

    with pytest.raises(OSError, match="failed"):
        ConfigFileTransaction(tmp_path).commit(
            (
                ConfigDocumentWrite(first, "value = 10\n"),
                ConfigDocumentWrite(second, "value = 20\n"),
            )
        )

    assert first.read_text(encoding="utf-8") == "value = 1\n"
    assert second.read_text(encoding="utf-8") == "value = 2\n"
