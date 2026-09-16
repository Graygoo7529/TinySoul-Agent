"""Build the complete User Turn mainline from typed module facades."""

from __future__ import annotations

from pathlib import Path

from tinysoul.kernel.action import LoadedActionCatalog
from tinysoul.kernel.action.config import ActionSettings
from tinysoul.plugins.capabilities import CapabilitiesSettings
from tinysoul.plugins.capabilities.supervised_process import (
    SupervisedProcessWaitPolicy,
)
from tinysoul.kernel.context import ContextSettings
from tinysoul.plugins.home import (
    AgentHomeEngine,
    HomeDomainSkillProvider,
)
from tinysoul.kernel.loop.assembly import TurnProfile, build_turn_context, build_turn_kernel
from tinysoul.kernel.loop.completion import TurnCompletionHandler, TurnCompletionPipeline
from tinysoul.kernel.loop.config import LoopSettings
from tinysoul.kernel.loop.preparation import TurnPreparationPipeline
from tinysoul.kernel.loop.prompts import DomainSkillProvider
from tinysoul.plugins.memory import MemoryEngine
from tinysoul.runtime import ObservationEmitter, SignalBus
from tinysoul.plugins.home.runtime_bridge import RuntimeAgentHomeBridge
from tinysoul.plugins.session.runtime_bridge import RuntimeSessionBridge
from tinysoul.plugins.workspace.runtime_bridge import RuntimeWorkspaceBridge
from tinysoul.plugins.session import SessionEngine
from tinysoul.plugins.session.projection import (
    SessionTurnCompletionHandler,
)
from tinysoul.plugins.workspace import (
    WorkspaceEngine,
    WorkspaceTurnPreparationHandler,
)

from tinysoul.kernel.loop.phases import LLMRunner
from tinysoul.plugins.capabilities.assembly import CommonActionAssembly
from tinysoul.kernel.loop.completion import AnswerCompletionDetector
from .completion import user_output_from_completion
from tinysoul.plugins.home.plugin import declare_home
from tinysoul.plugins.memory.plugin import declare_memory
from tinysoul.plugins.session.plugin import declare_session
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
        self._domain_skills: DomainSkillProvider | None = None
        self._completion_handlers: list[TurnCompletionHandler] = []

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
        context = build_turn_context(self._context_settings, self._observations)
        domain_skills = self._domain_skills or HomeDomainSkillProvider(
            self._home,
            runtime_bridge=RuntimeAgentHomeBridge(),
        )
        builder, process_jobs, services = CommonActionAssembly(
            root=self._root, home=self._home,
            workspace=self._workspace, bus=self._bus, llm=self._llm,
            observations=self._observations, action_settings=self._action_settings,
            capabilities_settings=self._capabilities_settings,
            supervised_process_wait=self._supervised_process_wait,
            runtime_env=self._runtime_env,
        ).prepare(
            context, self._action_catalog,
            plugins=(declare_home(self._home, self._llm),
                     declare_memory(self._memory), declare_session(self._session)),
        )
        action = builder.build()

        session_bridge = RuntimeSessionBridge()
        workspace_bridge = RuntimeWorkspaceBridge()
        trap = build_user_turn_trap(
            context=context,
            home=self._home,
            workspace=self._workspace,
        )
        profile = TurnProfile(
            id="user",
            context=context,
            action=action,
            services=services,
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
        )
        runner = build_turn_kernel(profile=profile, llm=self._llm, bus=self._bus, observations=self._observations)
        return UserTurnEntry(runner, profile=profile)
