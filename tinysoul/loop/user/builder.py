"""Build the complete User Turn mainline from typed module facades."""

from __future__ import annotations

from tinysoul.workspace.projection import workspace_segment_registration

from pathlib import Path

from tinysoul.action import ActionEngine, LoadedActionCatalog
from tinysoul.action.backends.llm_action import LLMActionTaskRunner
from tinysoul.action.config import ActionSettings, LLMActionProfileResolver
from tinysoul.capabilities import CapabilitiesSettings
from tinysoul.capabilities.script import ScriptSourceResolver
from tinysoul.capabilities.supervised_process import (
    SupervisedProcessManager,
    SupervisedProcessWaitPolicy,
)
from tinysoul.context import ContextEngine, ContextSettings
from tinysoul.home import (
    AgentHomeEngine,
    HomeActionSkillProvider,
    HomeDomainSkillProvider,
)
from tinysoul.home.errors import AgentHomeError
from tinysoul.infra import StagingDirectoryManager, StagingError
from tinysoul.loop.assembly import build_turn_kernel
from tinysoul.loop.failures import LoopFailureKind
from tinysoul.loop.runtime_bridge import RuntimeLoopBridge
from tinysoul.loop.completion import TurnCompletionHandler, TurnCompletionPipeline
from tinysoul.loop.config import LoopSettings
from tinysoul.loop.preparation import TurnPreparationPipeline
from tinysoul.loop.prompts import DomainSkillProvider
from tinysoul.memory import MemoryEngine
from tinysoul.runtime import ObservationEmitter, SignalBus
from tinysoul.home.runtime_bridge import RuntimeAgentHomeBridge
from tinysoul.context.runtime_bridge import RuntimeContextBridge
from tinysoul.session.runtime_bridge import RuntimeSessionBridge
from tinysoul.capabilities.supervised_process.runtime_bridge import RuntimeSupervisedProcessBridge
from tinysoul.workspace.runtime_bridge import RuntimeWorkspaceBridge
from tinysoul.session import SessionEngine
from tinysoul.session.projection import (
    SessionTurnCompletionHandler,
    session_segment_registration,
)
from tinysoul.workspace import (
    WorkspaceEngine,
    WorkspaceMirrorService,
    WorkspaceTurnPreparationHandler,
)

from ..phases import LLMRunner
from ..actions import CommonActionAssembly
from ..completion import AnswerCompletionDetector
from .completion import user_output_from_completion
from .context import build_user_context
from .entry import UserTurnEntry
from .prompts import USER_TURN_GUIDANCE
from .runtime import build_user_turn_trap


class UserTurnBuilder:
    """Own User Context, Action and Turn runtime composition."""

    def __init__(
        self,
        *,
        root: Path,
        context_settings: ContextSettings,
        loop_settings: LoopSettings,
        capabilities_settings: CapabilitiesSettings,
        supervised_process_wait: SupervisedProcessWaitPolicy,
        runtime_env: dict[str, str],
        llm: LLMRunner,
        home: AgentHomeEngine,
        memory: MemoryEngine,
        session: SessionEngine,
        workspace: WorkspaceEngine,
        bus: SignalBus,
        observations: ObservationEmitter,
        action_settings: ActionSettings | None = None,
        action_catalog: LoadedActionCatalog,
    ) -> None:
        self._root = root
        self._context_settings = context_settings
        self._loop_settings = loop_settings
        self._capabilities_settings = capabilities_settings
        self._supervised_process_wait = supervised_process_wait
        self._runtime_env = dict(runtime_env)
        self._action_settings = action_settings or ActionSettings()
        self._action_catalog = action_catalog
        self._llm = llm
        self._home = home
        self._memory = memory
        self._session = session
        self._workspace = workspace
        self._bus = bus
        self._observations = observations
        self._context: ContextEngine | None = None
        self._action: ActionEngine | None = None
        self._domain_skills: DomainSkillProvider | None = None
        self._completion_handlers: list[TurnCompletionHandler] = []

    def with_context(self, context: ContextEngine) -> "UserTurnBuilder":
        self._context = context
        return self

    def with_action(self, action: ActionEngine) -> "UserTurnBuilder":
        self._action = action
        return self

    def with_domain_skills(self, domain_skills: DomainSkillProvider) -> "UserTurnBuilder":
        self._domain_skills = domain_skills
        return self

    def add_completion_handler(
        self,
        handler: TurnCompletionHandler,
    ) -> "UserTurnBuilder":
        self._completion_handlers.append(handler)
        return self

    def build(self) -> UserTurnEntry:
        context = self._context or build_user_context(
            settings=self._context_settings,
            home=self._home,
            memory=self._memory,
            observations=self._observations,
        )
        context.register_segment(workspace_segment_registration())
        context.register_segment(session_segment_registration(self._session))
        domain_skills = self._domain_skills or HomeDomainSkillProvider(
            self._home,
            runtime_bridge=RuntimeAgentHomeBridge(),
        )
        process_jobs: SupervisedProcessManager | None = None
        action = self._action
        if action is None:
            builder, process_jobs = CommonActionAssembly(
                root=self._root, home=self._home, memory=self._memory,
                workspace=self._workspace, bus=self._bus, llm=self._llm,
                observations=self._observations, action_settings=self._action_settings,
                capabilities_settings=self._capabilities_settings,
                supervised_process_wait=self._supervised_process_wait,
                runtime_env=self._runtime_env,
            ).prepare(context, self._action_catalog)
            action = builder.build()
        try:
            self._home.reconcile_prompt_mounts(
                domains=action.domain_names(),
                actions=action.action_identifiers(),
            )
        except AgentHomeError as exc:
            raise RuntimeAgentHomeBridge().startup_failure(
                message="Home action guidance could not be validated.",
                payload={"error_type": type(exc).__name__},
            ) from exc

        context_bridge = RuntimeContextBridge()
        session_bridge = RuntimeSessionBridge()
        workspace_bridge = RuntimeWorkspaceBridge()
        trap = build_user_turn_trap(
            context=context,
            home=self._home,
            workspace=self._workspace,
        )
        runner = build_turn_kernel(
            context=context,
            action=action,
            llm=self._llm,
            bus=self._bus,
            trap=trap,
            settings=self._loop_settings.user,
            cycle_settings=self._loop_settings.cycle,
            turn_guidance=USER_TURN_GUIDANCE,
            completion_detector=AnswerCompletionDetector(),
            completion_to_output=user_output_from_completion,
            domain_skills=domain_skills,
            preparation_pipeline=TurnPreparationPipeline(
                (
                    WorkspaceTurnPreparationHandler(
                        self._workspace,
                        runtime_bridge=workspace_bridge,
                    ),
                )
            ),
            completion_pipeline=TurnCompletionPipeline(
                handlers=tuple(self._completion_handlers),
                recorder=SessionTurnCompletionHandler(
                    self._session,
                    runtime_bridge=session_bridge,
                ),
            ),
            activity_controller=process_jobs,
            observations=self._observations,
        )
        return UserTurnEntry(runner, action=action)
