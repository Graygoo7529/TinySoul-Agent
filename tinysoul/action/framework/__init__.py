"""Action framework contracts (handlers, executors, metadata, registry)."""

from .executor import ActionExecutor
from .run_config import ActionRuntimeConfig, RunConfig, TerminationReason
from .handler import (
    ActionCluster,
    ActionContract,
    ActionDetail,
    ActionHandler,
    ActionMeta,
    ActionProfile,
    Applicability,
    ApplicabilityMode,
    ClusterType,
    ActionBase,
    JsonMetaProvider,
    LLMDependency,
    Postconditions,
    _applicability_to_text,
    _profile_to_text,
    make_handler,
    parse_detail_from_json,
    parse_meta_from_json,
)
from .schema import get_action_schema
from .manager import QueryAction
from .registry import ActionRegistry

__all__ = [
    "ActionExecutor",
    "ActionCluster",
    "ActionContract",
    "ActionDetail",
    "ActionHandler",
    "ActionMeta",
    "ActionProfile",
    "ActionRegistry",
    "ActionRuntimeConfig",
    "Applicability",
    "ApplicabilityMode",
    "ClusterType",
    "ActionBase",
    "JsonMetaProvider",
    "LLMDependency",
    "Postconditions",
    "QueryAction",
    "RunConfig",
    "TerminationReason",
    "get_action_schema",
    "make_handler",
    "parse_detail_from_json",
    "parse_meta_from_json",
    "_applicability_to_text",
    "_profile_to_text",
]
