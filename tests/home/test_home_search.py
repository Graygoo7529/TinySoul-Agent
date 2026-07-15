from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from tinysoul.action.core.call import (
    ActionCall,
    ActionExecution,
    ActionExecutionBuilder,
)
from tinysoul.action.core.catalog import ActionCatalog
from tinysoul.action.core.executor import ActionExecutionContext
from tinysoul.action.core.result import ActionResultStatus
from tinysoul.action.core.specs import (
    ActionBackendKind,
    ActionBackendSpec,
    ActionDomainSpec,
    ActionRuntimeSpec,
    ActionSemanticSpec,
    ActionSpec,
    ActionToolSpec,
)
from tinysoul.home import (
    AgentHomeEngine,
    AgentHomeEngineBuilder,
    AgentHomeSettings,
    HomeMaintenanceChange,
    HomeMaintenanceDecision,
    HomeMaintenanceMode,
    HomeMaintenanceStatus,
    HomeSearchDocument,
    HomeSearchRequest,
    HomeSearchSettings,
    HomeTopLink,
    HomeTopSearchExecutor,
    HomeTopSearchService,
    LLMHomeSearchReranker,
    parse_agent_home_settings,
)
from tinysoul.infra.config import ConfigError
from tinysoul.infra.json import JsonObject
from tinysoul.llm import (
    JsonAnswer,
    RawResponse,
    TaskCall,
    TaskProfile,
    TaskResult,
)
from tinysoul.runtime import RunLevel, RunScope


@dataclass
class _StubReranker:
    links: tuple[str, ...] | None
    requests: list[HomeSearchRequest] = field(default_factory=list)

    def rerank(
        self,
        request: HomeSearchRequest,
        *,
        scope: RunScope,
    ) -> tuple[str, ...] | None:
        self.requests.append(request)
        return self.links


class _FakeLLM:
    def __init__(self, results: tuple[TaskResult, ...]) -> None:
        self._results = deque(results)
        self.calls: list[TaskCall] = []

    def run(self, call: TaskCall) -> TaskResult:
        self.calls.append(call)
        return self._results.popleft()


class _ApplyReviewer:
    def review(
        self,
        change: HomeMaintenanceChange,
        *,
        scope: RunScope,
    ) -> HomeMaintenanceDecision:
        return HomeMaintenanceDecision.APPLY


def test_home_top_search_uses_effective_metadata_without_materializing_actual(
    tmp_path: Path,
) -> None:
    home_root = tmp_path / "home"
    _write(home_root / "agent" / "AGENT.md", "# Agent\n\nCore identity.\n")
    _write(
        home_root / "what" / "concept" / "daily-lifecycle.md",
        "# Daily Lifecycle\n\nDeterministic rollover and maintenance boundaries.\n",
    )
    _write(
        home_root / "why" / "hidden.md",
        "# Hidden Reason\n\nThis entry will be tombstoned.\n",
    )
    _write(
        home_root / "how" / "review" / "SKILL.md",
        "---\n"
        "title: Review Home\n"
        "description: Review runtime changes against actual Home.\n"
        "---\n\n"
        "# Review Home\n",
    )
    home = _build_home(tmp_path)
    home.write_top(
        "home:why@runtime-only.md",
        "# Runtime Only\n\nA newly created runtime reason.\n",
    )
    home.delete_top("home:why@hidden.md")

    result = home.search_top("runtime reason", top_k=10)

    links = tuple(item.link for item in result.items)
    assert links[0] == "home:why@runtime-only.md"
    assert "home:what@concept/daily-lifecycle.md" in links
    assert "home:how@review" in links
    assert "home:why@hidden.md" not in links
    assert "home:agent@AGENT.md" not in links
    runtime_root = tmp_path / "runtime" / "home"
    assert not (runtime_root / "what" / "concept" / "daily-lifecycle.md").exists()
    assert not (runtime_root / "how" / "review" / "SKILL.md").exists()
    first = result.items[0]
    assert first.title == "Runtime Only"
    assert first.summary == "A newly created runtime reason."
    assert first.digest


def test_home_top_search_validates_rerank_and_falls_back_deterministically() -> None:
    service = HomeTopSearchService(
        HomeSearchSettings(
            candidate_limit=2,
            default_top_k=2,
            max_top_k=2,
            prefix_max_chars=128,
            summary_max_chars=64,
        )
    )
    documents = (
        HomeSearchDocument(
            HomeTopLink("what", "concept/alpha.md"),
            "# Alpha\n\nShared knowledge.\n",
            False,
            "digest-alpha",
        ),
        HomeSearchDocument(
            HomeTopLink("why", "beta.md"),
            "# Beta\n\nShared knowledge.\n",
            False,
            "digest-beta",
        ),
        HomeSearchDocument(
            HomeTopLink("how", "gamma"),
            "# Gamma\n\nUnrelated workflow.\n",
            False,
            "digest-gamma",
        ),
    )
    scope = RunScope().push(RunLevel.PHASE, "phase3")
    valid = _StubReranker(
        ("home:why@beta.md", "home:what@concept/alpha.md")
    )

    reranked = service.search(
        query="shared knowledge",
        documents=documents,
        reranker=valid,
        scope=scope,
    )
    invalid = service.search(
        query="shared knowledge",
        documents=documents,
        reranker=_StubReranker(("home:what@concept/missing.md",)),
        scope=scope,
    )
    empty = service.search(
        query="shared knowledge",
        documents=documents,
        reranker=_StubReranker(()),
        scope=scope,
    )

    assert reranked.reranked is True
    assert tuple(item.link for item in reranked.items) == (
        "home:why@beta.md",
        "home:what@concept/alpha.md",
    )
    assert reranked.candidate_count == 2
    assert len(valid.requests) == 1
    assert invalid.reranked is False
    assert tuple(item.link for item in invalid.items) == (
        "home:what@concept/alpha.md",
        "home:why@beta.md",
    )
    assert empty.reranked is True
    assert empty.items == ()


def test_home_top_search_action_uses_llm_profile_and_returns_metadata(
    tmp_path: Path,
) -> None:
    home_root = tmp_path / "home"
    _write(home_root / "what" / "concept" / "alpha.md", "# Alpha\n\nKnowledge.\n")
    _write(home_root / "why" / "beta.md", "# Beta\n\nReason.\n")
    home = _build_home(tmp_path)
    llm = _FakeLLM((_json_result({"links": ["home:why@beta.md"]}),))
    executor = HomeTopSearchExecutor(
        home,
        reranker=LLMHomeSearchReranker(llm),
    )

    result = executor.execute(
        _execution({"query": "reason", "top_k": 1}),
        ActionExecutionContext(),
    )

    assert result.status is ActionResultStatus.SUCCESS
    assert result.payload["reranked"] is True
    items = result.payload["items"]
    assert isinstance(items, list)
    assert len(items) == 1
    item = items[0]
    assert isinstance(item, dict)
    assert item["link"] == "home:why@beta.md"
    assert item["title"] == "Beta"
    assert "searchable_prefix" not in item
    assert llm.calls[0].profile is TaskProfile.HOME_SEARCH
    assert not (tmp_path / "runtime" / "home" / "why" / "beta.md").exists()


def test_home_top_search_reads_applied_actual_after_home_maintenance(
    tmp_path: Path,
) -> None:
    actual = tmp_path / "home" / "why" / "review.md"
    _write(actual, "# Old Review\n\nOld guidance.\n")
    home = _build_home(tmp_path)
    home.write_top(
        "home:why@review.md",
        "# Current Review\n\nCommitted guidance.\n",
        overwrite=True,
    )
    before = home.search_top("committed guidance", top_k=1)

    outcome = home.run_maintenance(
        mode=HomeMaintenanceMode.AUTOMATIC,
        automatic_reviewer=_ApplyReviewer(),
    )
    after = home.search_top("committed guidance", top_k=1)

    assert before.items[0].title == "Current Review"
    assert outcome.status is HomeMaintenanceStatus.COMPLETED
    assert outcome.applied == 1
    assert actual.read_text(encoding="utf-8").startswith("# Current Review")
    assert after.items[0].title == "Current Review"
    assert after.items[0].digest == before.items[0].digest
    assert not (tmp_path / "runtime" / "home" / "why" / "review.md").exists()


def test_home_search_settings_parse_and_validate_bounds(tmp_path: Path) -> None:
    settings = parse_agent_home_settings(
        {
            "max_read_chars": 1000,
            "search": {
                "candidate_limit": 12,
                "default_top_k": 3,
                "max_top_k": 6,
                "prefix_max_chars": 800,
                "summary_max_chars": 240,
            },
        },
        project_root=tmp_path,
    )

    assert settings.search == HomeSearchSettings(
        candidate_limit=12,
        default_top_k=3,
        max_top_k=6,
        prefix_max_chars=800,
        summary_max_chars=240,
    )
    with pytest.raises(ConfigError, match="cannot exceed candidate_limit"):
        parse_agent_home_settings(
            {
                "search": {"candidate_limit": 4, "max_top_k": 5},
            },
            project_root=tmp_path,
        )


def _build_home(tmp_path: Path) -> AgentHomeEngine:
    home_root = tmp_path / "home"
    home_root.mkdir(parents=True, exist_ok=True)
    return AgentHomeEngineBuilder(
        AgentHomeSettings(
            original_root=home_root,
            runtime_root=tmp_path / "runtime" / "home",
        )
    ).build()


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _json_result(value: JsonObject) -> TaskResult:
    return TaskResult.success(
        raw_response=RawResponse(
            answer_text="{}",
            model_id="fake",
            provider_id="fake",
        ),
        answer=JsonAnswer(value),
        tool_calls=(),
    )


def _execution(params: JsonObject) -> ActionExecution:
    name = "home.top.search"
    catalog = ActionCatalog(
        domains=(ActionDomainSpec(name="home", description="Home."),),
        actions=(
            ActionSpec(
                name=name,
                domain="home",
                tool=ActionToolSpec(
                    name=name,
                    description="Search.",
                    schema={
                        "type": "object",
                        "properties": {
                            "query": {"type": "string"},
                            "top_k": {"type": "integer"},
                        },
                        "required": ["query"],
                        "additionalProperties": False,
                    },
                ),
                semantic=ActionSemanticSpec(),
                runtime=ActionRuntimeSpec(),
                backend=ActionBackendSpec(
                    kind=ActionBackendKind.NATIVE,
                    handler=name,
                ),
            ),
        ),
    )
    preparation = ActionExecutionBuilder().prepare_batch(
        (ActionCall("call_1", name, params, 1),),
        catalog=catalog,
        scope=RunScope().push(RunLevel.PHASE, "phase3"),
        batch_id="batch_1",
    )
    return preparation.batch.executions[0]
