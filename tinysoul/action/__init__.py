"""
Action management module for TinySoul.

Provides the action framework (handlers, executors, metadata) and
runtime management (registry, query action) for the action system.
"""

from .framework import (  # noqa: F401
    ActionBase,
    ActionCluster,
    ActionContract,
    ActionDetail,
    ActionExecutor,
    ActionHandler,
    ActionMeta,
    ActionProfile,
    ActionRegistry,
    Applicability,
    ApplicabilityMode,
    ClusterType,
    JsonMetaProvider,
    LLMDependency,
    Postconditions,
    QueryAction,
    get_action_schema,
    make_handler,
    parse_detail_from_json,
    parse_meta_from_json,
)
__all__ = [
    "ActionExecutor",
    "ActionCluster",
    "ActionContract",
    "ActionDetail",
    "ActionHandler",
    "ActionMeta",
    "ActionProfile",
    "ActionRegistry",
    "Applicability",
    "ApplicabilityMode",
    "ClusterType",
    "ActionBase",
    "JsonMetaProvider",
    "LLMDependency",
    "Postconditions",
    "QueryAction",
    "get_action_schema",
    "make_handler",
    "parse_detail_from_json",
    "parse_meta_from_json",
]
