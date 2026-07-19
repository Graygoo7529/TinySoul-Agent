"""TinySoul action module."""

from .core.call import (
    ActionBatch,
    ActionBatchPreparation,
    ActionCall,
    ActionExecution,
    ActionFramework,
    ActionNormalization,
)
from .core.catalog import ActionCatalog
from .core.errors import ActionContractError, ActionError, ActionInvariantError
from .core.executor import ActionExecutionContext, ActionExecutionControl, ActionExecutor
from .core.hooks import HookOutcome
from .core.result import (
    ActionPhaseResult,
    ActionPhaseResultStage,
    ActionPhaseResultStatus,
    ActionResult,
    ActionResultStage,
    ActionResultStatus,
    ActionTraceMode,
    ActionTraceProjection,
)
from .core.scope import (
    DOMAIN_SELECTION_TOOL,
    ActionDomainPromptRenderer,
    ActionDomainSelection,
    ActionScopePreparation,
)
from .core.specs import (
    ActionBackendKind,
    ActionBackendSpec,
    ActionDomainSpec,
    ActionEnvironmentEffect,
    ActionHookSpec,
    ActionParallelPolicy,
    ActionResultRuntimeSpec,
    ActionRuntimeSpec,
    ActionSemanticSpec,
    ActionSpec,
    ActionToolSpec,
)
from .engine import ActionEngine, ActionEngineBuilder
from .resources import builtin_action_catalog_root

__all__ = [
    "ActionBackendKind",
    "ActionBackendSpec",
    "ActionBatch",
    "ActionBatchPreparation",
    "ActionCall",
    "ActionCatalog",
    "ActionDomainSpec",
    "ActionDomainPromptRenderer",
    "ActionDomainSelection",
    "ActionEngine",
    "ActionEngineBuilder",
    "ActionEnvironmentEffect",
    "ActionError",
    "ActionExecution",
    "ActionExecutionContext",
    "ActionExecutionControl",
    "ActionExecutor",
    "ActionFramework",
    "ActionHookSpec",
    "ActionNormalization",
    "ActionParallelPolicy",
    "ActionPhaseResult",
    "ActionPhaseResultStage",
    "ActionPhaseResultStatus",
    "ActionResult",
    "ActionResultStage",
    "ActionResultStatus",
    "ActionResultRuntimeSpec",
    "ActionTraceMode",
    "ActionTraceProjection",
    "ActionRuntimeSpec",
    "ActionSemanticSpec",
    "ActionScopePreparation",
    "ActionSpec",
    "ActionToolSpec",
    "ActionContractError",
    "ActionInvariantError",
    "DOMAIN_SELECTION_TOOL",
    "HookOutcome",
    "builtin_action_catalog_root",
]
