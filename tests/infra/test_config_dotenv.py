from __future__ import annotations

import os

import pytest

from tinysoul.infra.config.dotenv import DotenvSource, parse_dotenv


def test_parse_dotenv_basic_values() -> None:
    values = parse_dotenv(
        """
        # comment
        NAME=TinySoul
        EMPTY=
        QUOTED="hello # not comment"
        SINGLE='literal value'
        INLINE=value # comment
        export EXPORTED=yes
        """
    )

    assert values["NAME"] == "TinySoul"
    assert values["EMPTY"] == ""
    assert values["QUOTED"] == "hello # not comment"
    assert values["SINGLE"] == "literal value"
    assert values["INLINE"] == "value"
    assert values["EXPORTED"] == "yes"


def test_parse_dotenv_escaped_double_quotes() -> None:
    values = parse_dotenv('TEXT="line\\nnext"\n')

    assert values["TEXT"] == "line\nnext"


def test_parse_dotenv_rejects_unclosed_quote() -> None:
    with pytest.raises(ValueError, match="Unclosed quoted"):
        parse_dotenv('BROKEN="value\n')


from pathlib import Path


def test_dotenv_source_does_not_mutate_process_environment(local_tmp: Path) -> None:
    path = local_tmp / ".env"
    path.write_text("TINYSOUL_INFRA_RUNTIME_MAX_TURNS=33\n", encoding="utf-8")

    before = os.environ.get("TINYSOUL_INFRA_RUNTIME_MAX_TURNS")
    source = DotenvSource(path).load()
    after = os.environ.get("TINYSOUL_INFRA_RUNTIME_MAX_TURNS")

    assert before == after
    assert source.values["infra.runtime.max_turns"] == "33"
