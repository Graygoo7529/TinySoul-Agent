"""
Action handler and metadata definitions for TinySoul.

Provides the abstract base class for action handlers, action metadata
dataclasses, and related enums used across the action system.
"""

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from .executor import ActionExecutor
from .run_config import ActionRuntimeConfig, RunConfig
from tinysoul.infra.config import settings
from tinysoul.context.protocols import ContextProvider


# ============================================================================
# Action Trait Enums
# ============================================================================

class ClusterType(StrEnum):
    """Action cluster type: execution mechanism classification."""
    NATIVE = "NATIVE"
    CLI = "CLI"
    SCRIPT = "SCRIPT"

class ActionIntention(StrEnum):
    """Action intention classification."""
    EXTERNAL_PROBING = "EXTERNAL_PROBING"
    INTERNAL_REASONING = "INTERNAL_REASONING"
    EXECUTION = "EXECUTION"

class ActionEnvironmentEffect(StrEnum):
    """Effect on environment."""
    READ_ONLY = "READ_ONLY"
    ADDITIVE = "ADDITIVE"
    MODIFYING = "MODIFYING"
    DESTRUCTIVE = "DESTRUCTIVE"

class ActionMode(StrEnum):
    """Execution mode: single-run or ongoing."""
    SINGLE_RUN = "SINGLE_RUN"
    ONGOING = "ONGOING"

class LLMDependency(StrEnum):
    """LLM dependency level."""
    NONE = "NONE"
    OPTIONAL = "OPTIONAL"
    REQUIRED = "REQUIRED"

class ApplicabilityMode(StrEnum):
    """Applicability mode for action selection."""
    ALWAYS_CONSIDER = "ALWAYS_CONSIDER"
    CONDITIONAL = "CONDITIONAL"

# ============================================================================
# Action Metadata (Schema Dataclasses)
# ============================================================================

@dataclass
class ActionCluster:
    """Action cluster: <type, domain>."""
    type: ClusterType = ClusterType.NATIVE
    domain: str = ""

@dataclass
class ActionProfile:
    """
    Action profile.
    - action_intention: EXTERNAL_PROBING | INTERNAL_REASONING | EXECUTION
    - action_environment_effect: READ_ONLY | ADDITIVE | MODIFYING | DESTRUCTIVE
    - action_mode: SINGLE_RUN | ONGOING
    - llm_dependency: NONE | OPTIONAL | REQUIRED
    """
    action_intention: ActionIntention = ActionIntention.EXECUTION
    action_environment_effect: ActionEnvironmentEffect = ActionEnvironmentEffect.READ_ONLY
    action_mode: ActionMode = ActionMode.SINGLE_RUN
    llm_dependency: LLMDependency = LLMDependency.NONE

@dataclass
class Applicability:
    """Action applicability constraints."""
    mode: ApplicabilityMode = ApplicabilityMode.ALWAYS_CONSIDER
    conditions: list[str] = field(default_factory=list)

@dataclass
class Postconditions:
    """Action postconditions."""
    logical_state_effects: list[str] = field(default_factory=list)
    physical_environment_effects: list[str] = field(default_factory=list)

@dataclass
class ActionContract:
    """
    Action contract.
    - applicability: when to consider this action
    - preconditions: required state before execution
    - postconditions: effects after execution
    """
    applicability: Applicability = field(default_factory=Applicability)
    preconditions: list[str] = field(default_factory=list)
    postconditions: Postconditions = field(default_factory=Postconditions)

@dataclass
class ActionMeta:
    """
    Action Meta.
    (1) action_name
    (2) action_cluster
    (3) action_profile
    (4) action_contract
    """
    name: str
    cluster: ActionCluster = field(default_factory=ActionCluster)
    profile: ActionProfile = field(default_factory=ActionProfile)
    contract: ActionContract = field(default_factory=ActionContract)
    description: str = ""

@dataclass
class ActionDetail:
    """
    Action Detail.
    - parameter_schema: JSON schema for action input parameters
    - examples: example inputs
    - edge_case_handling: how to handle edge cases
    """
    parameter_schema: dict[str, Any] = field(default_factory=dict)
    examples: list[dict] = field(default_factory=list)
    edge_case_handling: list[str] = field(default_factory=list)

# ---------------------------------------------------------------------------
# JSON parsing helpers
# ---------------------------------------------------------------------------

def _profile_to_text(profile: ActionProfile) -> dict:
    """Convert ActionProfile enum values to text."""
    return {
        "action_intention": profile.action_intention.value,
        "action_environment_effect": profile.action_environment_effect.value,
        "action_mode": profile.action_mode.value,
        "llm_dependency": profile.llm_dependency.value,
    }

def _applicability_to_text(applicability: Applicability) -> dict:
    """Convert Applicability enum values to text."""
    return {
        "mode": applicability.mode.value,
        "conditions": applicability.conditions,
    }

def _load_str_enum(raw, enum_cls, default):
    try:
        return enum_cls(raw)
    except (ValueError, TypeError):
        return default

def parse_meta_from_json(action_name: str, schema: dict) -> ActionMeta:
    """Parse ActionMeta from action JSON schema."""
    cluster_data = schema.get("cluster", {})
    profile_data = schema.get("profile", {})
    contract_data = schema.get("contract", {})

    # Defensive: LLM-generated JSON may place postconditions as a list instead of dict
    applicability_data = contract_data.get("applicability", {})
    if not isinstance(applicability_data, dict):
        applicability_data = {}
    postconditions_data = contract_data.get("postconditions", {})
    if isinstance(postconditions_data, list):
        postconditions_data = {"logical_state_effects": postconditions_data}
    elif not isinstance(postconditions_data, dict):
        postconditions_data = {}

    return ActionMeta(
        name=schema.get("name", action_name),
        description=schema.get("description", ""),
        cluster=ActionCluster(
            type=_load_str_enum(cluster_data.get("type", "NATIVE"), ClusterType, ClusterType.NATIVE),
            domain=cluster_data.get("domain", ""),
        ),
        profile=ActionProfile(
            action_intention=_load_str_enum(profile_data.get("action_intention", "EXECUTION"), ActionIntention, ActionIntention.EXECUTION),
            action_environment_effect=_load_str_enum(profile_data.get("action_environment_effect", "READ_ONLY"), ActionEnvironmentEffect, ActionEnvironmentEffect.READ_ONLY),
            action_mode=_load_str_enum(profile_data.get("action_mode", "SINGLE_RUN"), ActionMode, ActionMode.SINGLE_RUN),
            llm_dependency=_load_str_enum(profile_data.get("llm_dependency", "NONE"), LLMDependency, LLMDependency.NONE),
        ),
        contract=ActionContract(
            applicability=Applicability(
                mode=_load_str_enum(applicability_data.get("mode", "ALWAYS_CONSIDER"), ApplicabilityMode, ApplicabilityMode.ALWAYS_CONSIDER),
                conditions=applicability_data.get("conditions", []),
            ),
            preconditions=contract_data.get("preconditions", []),
            postconditions=Postconditions(
                logical_state_effects=postconditions_data.get("logical_state_effects", []),
                physical_environment_effects=postconditions_data.get("physical_environment_effects", []),
            ),
        ),
    )

def parse_detail_from_json(schema: dict) -> ActionDetail:
    """Parse ActionDetail from action JSON schema."""
    detail_data = schema.get("detail", {})
    if not isinstance(detail_data, dict):
        detail_data = {}

    # Fallback: LLM sometimes places detail fields at the top level instead of under "detail"
    parameter_schema = detail_data.get("parameter_schema") or schema.get("parameter_schema", {})
    examples = detail_data.get("examples") or schema.get("examples", [])
    edge_case_handling = detail_data.get("edge_case_handling") or schema.get("edge_case_handling", [])

    return ActionDetail(
        parameter_schema=parameter_schema,
        examples=examples,
        edge_case_handling=edge_case_handling,
    )

# ============================================================================
# Action Handler Classes (Command Pattern)
# ============================================================================

class ActionHandler(ABC):
    """
    Abstract base class for action handlers using Command Pattern.
    """
    @abstractmethod
    def execute(
        self,
        action_input: dict,
        context_provider: ContextProvider,
        run_config: RunConfig,
    ) -> dict:
        """Execute the action with structured input."""
        pass

    @abstractmethod
    def get_meta(self) -> ActionMeta:
        """Get action metadata."""
        pass

    @abstractmethod
    def get_detail(self) -> ActionDetail:
        """Get action detail."""
        pass

class JsonMetaProvider:
    """
    Parses ActionMeta and ActionDetail from an ACTION_JSON string.

    This is a pure tool class — it does NOT inherit ActionHandler.
    It can be composed into any handler that needs JSON-based metadata.

    Parsed results are cached on the instance so that repeated calls
    (e.g. from QueryAction every turn) do not re-parse the JSON string.
    """

    def __init__(self, action_name: str, action_json: str):
        self._action_name = action_name
        self._action_json = action_json
        self._meta_cache: ActionMeta | None = None
        self._detail_cache: ActionDetail | None = None
        self._validated_schema: dict | None = None

    def _ensure_validated(self) -> dict:
        """Parse and validate ACTION_JSON, caching the result."""
        if self._validated_schema is None:
            from .validation import validate_action_metadata
            self._validated_schema = validate_action_metadata(self._action_json)
        return self._validated_schema

    def get_meta(self) -> ActionMeta:
        if self._meta_cache is None:
            schema = self._ensure_validated()
            self._meta_cache = parse_meta_from_json(self._action_name, schema)
        return self._meta_cache

    def get_detail(self) -> ActionDetail:
        if self._detail_cache is None:
            schema = self._ensure_validated()
            self._detail_cache = parse_detail_from_json(schema)
        return self._detail_cache

class ActionBase(ActionHandler):
    """
    Composition-based action handler: JsonMetaProvider + ActionExecutor.

    All built-in actions that delegate to an ActionExecutor should inherit this.
    Metadata parsing is delegated to an internal JsonMetaProvider instance.
    The boundary wrapper (unknown exception -> ActionExecutionError) is unified here.
    """

    action_name: str = ""
    ACTION_JSON: str = ""
    _executor: ActionExecutor | None = None
    _runtime_config: ActionRuntimeConfig = ActionRuntimeConfig()

    def __init__(self):
        self._meta_provider: JsonMetaProvider | None = None
        if self.ACTION_JSON:
            self._meta_provider = JsonMetaProvider(self.action_name, self.ACTION_JSON)

    def get_meta(self) -> ActionMeta:
        if self._meta_provider is None:
            raise NotImplementedError(
                "Subclasses must define ACTION_JSON or override get_meta()"
            )
        return self._meta_provider.get_meta()

    def get_detail(self) -> ActionDetail:
        if self._meta_provider is None:
            raise NotImplementedError(
                "Subclasses must define ACTION_JSON or override get_detail()"
            )
        return self._meta_provider.get_detail()

    def execute(
        self,
        action_input: dict,
        context_provider: ContextProvider,
        run_config: RunConfig,
    ) -> dict:
        if self._executor is None:
            raise NotImplementedError(
                f"{self.__class__.__name__} must set _executor or override execute()"
            )

        resolved = self.resolve_run_config(run_config)
        resolved.raise_if_terminated()
        try:
            return self._executor.execute(action_input, context_provider, resolved)
        except Exception as e:
            from tinysoul.trap import ActionExecutionError, TinysoulError
            if isinstance(e, TinysoulError):
                raise
            raise ActionExecutionError(str(e), action_name=self.action_name, action_input=action_input) from e

    def resolve_run_config(self, incoming: RunConfig) -> RunConfig:
        meta = self.get_meta()

        # LLM timeout: individual override > global default
        llm_timeout = self._runtime_config.llm_timeout
        if llm_timeout is None:
            llm_timeout = settings.llm_timeout
        incoming.llm_timeout = llm_timeout

        # API timeout: individual override > global default (reserved for future web-search etc.)
        api_timeout = self._runtime_config.api_timeout
        if api_timeout is None:
            api_timeout = getattr(settings, "api_timeout", None)
        incoming.api_timeout = api_timeout

        # Action timeout: explicit action override wins. Otherwise derive a
        # startup/execution budget from cluster defaults plus declared runtime
        # dependencies. Dependency budgets widen the default; they do not cap
        # the LLM/API call itself.
        timeout = self._runtime_config.timeout
        if timeout is None:
            timeout = self._cluster_default_timeout(meta.cluster.type)
            if (
                meta.profile.llm_dependency != LLMDependency.NONE
                and llm_timeout is not None
            ):
                timeout = max(timeout, llm_timeout + settings.action_llm_overhead)
            if self._runtime_config.api_dependency and api_timeout is not None:
                timeout = max(timeout, api_timeout + settings.action_api_overhead)

        incoming.apply_timeout(timeout)

        return incoming

    @staticmethod
    def _cluster_default_timeout(cluster_type: ClusterType) -> float:
        if cluster_type == ClusterType.CLI:
            return settings.cli_timeout
        if cluster_type == ClusterType.SCRIPT:
            return settings.script_timeout
        return settings.action_timeout

    def get_runtime_config(self) -> ActionRuntimeConfig:
        return self._runtime_config


def make_handler(
    name: str,
    action_json: str,
    executor: ActionExecutor | None = None,
    runtime_config: ActionRuntimeConfig | None = None,
) -> ActionHandler:
    """
    Factory that constructs an ActionHandler at runtime without defining a new class.

    Replaces the old RuntimeAction. Used by register_temporary_script and
    any other dynamic action registration paths.
    """

    class _RuntimeAction(ActionBase):
        action_name = name
        ACTION_JSON = action_json
        _executor = executor
        _runtime_config = runtime_config or ActionRuntimeConfig()

    return _RuntimeAction()
