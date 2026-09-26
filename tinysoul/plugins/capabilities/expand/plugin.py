"""MCP generation ownership and profile action contribution."""

from tinysoul.kernel.action.models import (
    ModelUseDescriptor,
    ModelOperation,
    ModelImplementation,
    ModelUseRegistry,
)
from tinysoul.kernel.action.config import ActionSettings
from tinysoul.infra.model_services import ModelServices
from tinysoul.kernel.retrieval.policy import SearchCapability
from tinysoul.kernel.retrieval.contracts import (
    SourceKind,
    OperationKind,
)
from tinysoul.kernel.retrieval.operations import SearchSession
from tinysoul.kernel.retrieval.selection import CandidateSelector
from dataclasses import dataclass
from functools import partial
from tinysoul.kernel.registration import PluginTurnResource

from tinysoul.infra.concurrency import CleanupDiagnostic
from tinysoul.infra.process import ManagedProcessCloseError
from tinysoul.kernel.registration import (
    GenerationBuildContext,
    PluginConfig,
    PluginGeneration,
    PluginProfileExtension,
    ProfileBuildContext,
    ProfileKind,
)
from tinysoul.plugins.workspace.services import WorkspaceExecutionService

from .config import ExpandSettings, parse_expand_settings, validate_expand_bindings
from .engine import ExpandEngine
from .actions import register_expand_actions
from .runtime_bridge import RuntimeExpandBridge


@dataclass(frozen=True)
class ExpandPlugin:
    id = "expand"
    search_capabilities = (
        SearchCapability("expand.search", (SourceKind.QUERY, SourceKind.DIRECTORY, SourceKind.REFS, SourceKind.RESULT), tuple(OperationKind), filters=("server_id", "tool_name"), server_scope=True, lexical_syntax=True),
    )
    model_uses = (
        ModelUseDescriptor(
            "expand.search.select",
            "expand.search",
            ModelOperation.SELECT,
            (ModelImplementation.LLM_TASK, ModelImplementation.STRUCTURED_DECISION),
        ),
        ModelUseDescriptor(
            "expand.search.rerank",
            "expand.search",
            ModelOperation.RERANK,
            (ModelImplementation.LLM_TASK, ModelImplementation.STRUCTURED_DECISION),
        ),
    )
    provides = ()
    requires = (WorkspaceExecutionService, ModelServices)
    configuration = (
        PluginConfig(
            "capabilities.expand",
            ExpandSettings,
            lambda tree, root: parse_expand_settings(tree),
            RuntimeExpandBridge().from_config_error,
            validate_expand_bindings,
        ),
    )

    async def build_generation(
        self, context: GenerationBuildContext
    ) -> PluginGeneration:
        engine = ExpandEngine(
            context.settings.get(ExpandSettings),
            root=context.root,
            workspace=context.services.get(WorkspaceExecutionService),
            environment=context.runtime_env,
        )

        async def invoke(call):
            return await context.llm.invoke(call)

        selector = CandidateSelector(
            models=context.settings.get(ModelUseRegistry),
            invoke=invoke,
            services=context.services.get(ModelServices),
        )

        def extend(
            kind: ProfileKind, profile: ProfileBuildContext
        ) -> PluginProfileExtension:
            queries = SearchSession(
                observations=context.observations,
                action_id="expand.search",
                retrieval_policies=context.settings.get(ActionSettings).retrieval_policies,
                source=partial(
                    engine.search_corpus,
                    page_budget=engine.settings.max_inline_chars,
                ),
                selector=selector,
                supported_filters=frozenset({"server_id", "tool_name"}),
            )
            return PluginProfileExtension(
                self.id,
                actions=partial(
                    register_expand_actions,
                    engine=engine,
                    tasks=profile.tasks,
                    queries=queries,
                ),
                preparation=(queries,),
                turn_resources=(PluginTurnResource(queries),),
            )

        async def release() -> tuple[CleanupDiagnostic, ...]:
            try:
                return await engine.release_day()
            except ManagedProcessCloseError as exc:
                raise RuntimeExpandBridge().close_failed(exc) from exc

        async def close() -> tuple[CleanupDiagnostic, ...]:
            try:
                return await engine.close()
            except ManagedProcessCloseError as exc:
                raise RuntimeExpandBridge().close_failed(exc) from exc

        return PluginGeneration(
            self.id, profile_extension_factory=extend, release_day=release, close=close
        )
