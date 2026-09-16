"""Home's explicit service, Context and Action contributions."""

from functools import partial

from tinysoul.kernel.loop.phases import LLMRunner
from tinysoul.kernel.registration import PluginDeclaration, Service

from .actions import register_home_actions
from .background import home_segment_registration
from .engine import AgentHomeEngine
from .search import LLMHomeSearchReranker
from .runtime_bridge import RuntimeAgentHomeBridge


def declare_home(home: AgentHomeEngine, llm: LLMRunner, *, actual: bool = False) -> PluginDeclaration:
    return PluginDeclaration(
        "home", services=(Service(AgentHomeEngine, home),),
        segments=(home_segment_registration(home, actual=actual),),
        actions=partial(register_home_actions, home=home, runtime_bridge=RuntimeAgentHomeBridge(),
                        search_reranker=LLMHomeSearchReranker(llm)),
    )
