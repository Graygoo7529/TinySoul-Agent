"""Validate all built-in ACTION_JSON definitions for structural correctness."""

import importlib
import json
import pkgutil
from typing import Any

import pytest

from tinysoul.action.framework.handler import ActionBase
from tinysoul.action.framework.validation import validate_action_metadata


def _discover_action_modules():
    """Yield all leaf modules under tinysoul.action.handlers."""
    import tinysoul.action.handlers as _handlers_pkg

    for _, modname, ispkg in pkgutil.walk_packages(
        _handlers_pkg.__path__, _handlers_pkg.__name__ + "."
    ):
        if ispkg:
            continue
        yield importlib.import_module(modname)


def _extract_action_classes(module) -> list[type[ActionBase]]:
    """Return all ActionBase subclasses defined in the module."""
    result = []
    for name in dir(module):
        obj = getattr(module, name)
        if (
            isinstance(obj, type)
            and issubclass(obj, ActionBase)
            and obj is not ActionBase
            and obj.__module__ == module.__name__
        ):
            result.append(obj)
    return result


class TestActionJsonSchema:
    @pytest.mark.parametrize(
        "action_cls",
        [
            cls
            for mod in _discover_action_modules()
            for cls in _extract_action_classes(mod)
        ],
        ids=lambda cls: cls.action_name or cls.__name__,
    )
    def test_action_json_is_valid(self, action_cls: type[ActionBase]):
        """ACTION_JSON must be valid JSON passing validate_action_metadata."""
        raw = getattr(action_cls, "ACTION_JSON", None)
        assert raw is not None, f"{action_cls.__name__} missing ACTION_JSON"
        assert isinstance(raw, str), (
            f"{action_cls.__name__}.ACTION_JSON must be a str (got {type(raw).__name__}); "
            f"if you defined ACTION_SPEC, ensure ACTION_JSON = json.dumps(ACTION_SPEC)"
        )

        # ① JSON 语法正确
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            pytest.fail(f"{action_cls.__name__}.ACTION_JSON is not valid JSON: {exc}")

        # ② 结构完整性（复用生产代码的 validator）
        parsed = validate_action_metadata(raw)
        assert isinstance(parsed, dict)

        # ③ name 一致性
        assert data.get("name") == action_cls.action_name, (
            f"{action_cls.__name__}: ACTION_JSON 'name' ({data.get('name')!r}) "
            f"does not match action_name ({action_cls.action_name!r})"
        )

        # ④ 所有必填顶层键存在
        required_keys = ("name", "description", "cluster", "profile", "contract", "detail")
        for key in required_keys:
            assert key in data, f"{action_cls.__name__}: missing top-level key '{key}'"

        # ⑤ detail.parameter_schema 是 dict
        detail = data.get("detail", {})
        assert isinstance(detail.get("parameter_schema"), dict), (
            f"{action_cls.__name__}: detail.parameter_schema must be an object"
        )
