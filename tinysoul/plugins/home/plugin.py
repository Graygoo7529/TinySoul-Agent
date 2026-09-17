"""Home's explicit service, Context and Action contributions."""

from functools import partial

from tinysoul.kernel.loop.phases import LLMRunner
from tinysoul.kernel.registration import PluginDeclaration, Service

from .actions import register_home_actions
from .background import home_segment_registration
from .engine import AgentHomeEngine
from .services import HomeService
from .search import LLMHomeSearchReranker
from .runtime_bridge import RuntimeAgentHomeBridge


def declare_home(home: AgentHomeEngine, llm: LLMRunner, *, actual: bool = False) -> PluginDeclaration:
    service = HomeService(home)
    return PluginDeclaration(
        "home", services=(Service(HomeService, service),),
        segments=(home_segment_registration(service, actual=actual),),
        actions=partial(register_home_actions, home=service, runtime_bridge=RuntimeAgentHomeBridge(),
                        search_reranker=LLMHomeSearchReranker(llm)),
    )
