"""Supervised-process policy compiled from an Action-owned contract."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import cast

from tinysoul.action import ActionSpec, LoadedActionCatalog
from tinysoul.infra.config import ConfigError


SUPERVISED_PROCESS_WAIT_ACTION = "execution.wait"
WAIT_SECONDS_SCHEMA_PATH = "tool.schema.properties.wait_seconds"


@dataclass(frozen=True)
class SupervisedProcessWaitPolicy:
    """Typed wait contract compiled from the execution.wait Action schema."""

    minimum_seconds: int
    default_seconds: int
    maximum_seconds: int


def compile_supervised_process_wait_policy(
    catalog: LoadedActionCatalog,
) -> SupervisedProcessWaitPolicy:
    """Compile the capability policy from one loaded project Action catalog."""

    if not catalog.catalog.has_action(SUPERVISED_PROCESS_WAIT_ACTION):
        raise ConfigError(
            "Project Action catalog is missing the supervised process wait Action",
            key=f"action.catalog.{SUPERVISED_PROCESS_WAIT_ACTION}",
            expected="configured Action",
        )
    source = catalog.documents.actions.get(SUPERVISED_PROCESS_WAIT_ACTION)
    return parse_supervised_process_wait_policy(
        catalog.catalog.get_action(SUPERVISED_PROCESS_WAIT_ACTION),
        source=source.source_id if source is not None else "",
    )


def parse_supervised_process_wait_policy(
    action: ActionSpec,
    *,
    source: str = "",
) -> SupervisedProcessWaitPolicy:
    """Interpret the wait Action contract for process runtime consumers."""

    if action.name != SUPERVISED_PROCESS_WAIT_ACTION:
        raise ConfigError(
            "Supervised process wait policy requires the execution.wait Action",
            key="name",
            source=source,
            value=action.name,
            expected=SUPERVISED_PROCESS_WAIT_ACTION,
        )
    properties = _mapping(
        action.tool.schema.get("properties"),
        key="tool.schema.properties",
        source=source,
    )
    wait_schema = _mapping(
        properties.get("wait_seconds"),
        key=WAIT_SECONDS_SCHEMA_PATH,
        source=source,
    )
    if wait_schema.get("type") != "integer":
        raise ConfigError(
            "Supervised process wait_seconds must use an integer schema",
            key=f"{WAIT_SECONDS_SCHEMA_PATH}.type",
            source=source,
            value=wait_schema.get("type"),
            expected="integer",
        )
    minimum = _positive_int(wait_schema, "minimum", source=source)
    default = _positive_int(wait_schema, "default", source=source)
    maximum = _positive_int(wait_schema, "maximum", source=source)
    if not minimum <= default <= maximum:
        raise ConfigError(
            "Supervised process wait policy is inconsistent",
            key=f"{WAIT_SECONDS_SCHEMA_PATH}.default",
            source=source,
            value=default,
            expected=f"between {minimum} and {maximum}",
        )
    return SupervisedProcessWaitPolicy(
        minimum_seconds=minimum,
        default_seconds=default,
        maximum_seconds=maximum,
    )


def _mapping(value: object, *, key: str, source: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ConfigError(
            "Supervised process wait schema must be an object",
            key=key,
            source=source,
            value=value,
            expected="object",
        )
    return cast(Mapping[str, object], value)


def _positive_int(
    schema: Mapping[str, object],
    name: str,
    *,
    source: str,
) -> int:
    value = schema.get(name)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ConfigError(
            "Supervised process wait boundary must be a positive integer",
            key=f"{WAIT_SECONDS_SCHEMA_PATH}.{name}",
            source=source,
            value=value,
            expected="positive int",
        )
    return value
