"""F1-D e2e backend harness: real TinySoul Agent + Endpoint, scripted model.

Only model outputs are scripted; every owner, the SDK dispatch, the HTTP API
and the WebSocket event stream run the real implementation — the same approach
as the backend contract tests (tests/gateway/endpoint/test_contracts.py).

Run from anywhere with the project Python (conda env `TinySoul`):

    python visualization/test/e2e/backend_server.py \
        --port 0 --token <at least 32 chars> --project-dir <dir> \
        --ready-file <path>

The script initializes the project directory when it is empty, starts the
agent and the Endpoint ASGI server on 127.0.0.1, writes {"port": N} to the
ready file, prints "TINYSOUL_E2E_READY port=N" on stdout, and serves until
terminated. `--port 0` lets the OS assign a free port; the ready file carries
the actual bound port, so no fixed port can conflict.

Scripted model behavior (message-driven, with one resource read per ask Turn):

- frame_stage1: select `core`; ask Turns also select `workspace` and load a review Skill.
- frame_stage2 with a normal input: `core.answer` echoing the `e2e-plain` user
  input verbatim ("You said: <text>").
- frame_stage2 with the ask trigger (`e2e-ask`): first read the seeded Workspace
  resource, then `core.ask`
  with two options (opt_a/opt_b) and allow_other=true.
- frame_stage2 with the ask trigger and an accepted reply (the reply carries
  the `e2e-reply-comment` marker): `core.answer` naming the selected option
  and the comment.
- `core.answer.generate` (the answer action's own task): returns the prepared
  answer text carried between the FINAL_ANSWER markers.
- Any other consumer: a minimal {"text": ...} JSON answer.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from dataclasses import replace
from pathlib import Path

from tinysoul.agent import Agent
from tinysoul.agent.composition.builder import standard_agent
from tinysoul.agent.config import AgentSettings, OutputSettings
from tinysoul.gateway.endpoint import (
    EndpointASGIServer,
    EndpointEngine,
    EndpointEventBuffer,
    EndpointSettings,
)
from tinysoul.gateway.project.initializer import (
    ProjectConfigProfile,
    ProjectInitializer,
)
from tinysoul.infra.config import ConfigEnvironment
from tinysoul.infra.json import JsonObject, to_json_object
from tinysoul.llm.protocol.messages import MessageStack, TextPart
from tinysoul.llm.execution.observation_payloads import (
    task_request_observation,
    task_response_observation,
)
from tinysoul.llm.protocol.reasoning import Reasoning
from tinysoul.llm.protocol.requests import TaskCall, TaskProfile
from tinysoul.llm.protocol.responses import JsonAnswer, RawResponse, TaskResult
from tinysoul.llm.protocol.tools import ToolCallRecord, ToolKind
from tinysoul.runtime import ObservationEvent, ObservationLevel, RunLevel
from tinysoul.plugins.home.services import HomeService
from tinysoul.plugins.workspace.services import WorkspaceService

# Distinctive markers the Playwright spec uses inside its messages. They are
# part of the e2e protocol between this harness and chat-flow.pw.ts.
PLAIN_MARKER = "e2e-plain"
ASK_TRIGGER = "e2e-ask"
REPLY_MARKER = "e2e-reply-comment"

QUESTION_TEXT = "Which option do you pick?"
QUESTION_OPTIONS = (
    {"id": "opt_a", "label": "Option A", "description": "The first option"},
    {"id": "opt_b", "label": "Option B", "description": "The second option"},
)

_ANSWER_BEGIN = "FINAL_ANSWER_BEGIN"
_ANSWER_END = "FINAL_ANSWER_END"


def _stack_text(messages: MessageStack) -> str:
    parts: list[str] = []
    for message in messages.messages:
        for part in message.parts:
            if isinstance(part, TextPart):
                parts.append(part.text)
    return "\n".join(parts)


def _tool_result(name: str, arguments: JsonObject, kind: ToolKind) -> TaskResult:
    tool = ToolCallRecord(f"call_{name.replace('.', '_')}", name, arguments, kind)
    return TaskResult.success(
        raw_response=RawResponse("", "scripted", "scripted", tool_calls=(tool,)),
        answer=None,
        tool_calls=(tool,),
    )


def _json_result(value: JsonObject) -> TaskResult:
    return TaskResult.success(
        raw_response=RawResponse(
            json.dumps(value, ensure_ascii=False), "scripted", "scripted"
        ),
        answer=JsonAnswer(value),
        tool_calls=(),
    )


def _answer_action(answer_text: str) -> TaskResult:
    return _tool_result(
        "core.answer",
        to_json_object(
            {
                "guide_blocks": [
                    {"text": "Answer the user with the prepared final answer."}
                ],
                "input_blocks": [
                    {"text": f"{_ANSWER_BEGIN}\n{answer_text}\n{_ANSWER_END}"}
                ],
            }
        ),
        ToolKind.ACTION,
    )


class ScriptedLLM:
    """Deterministic TaskRunner: the only fake in an otherwise real backend."""

    def __init__(self, events: EndpointEventBuffer) -> None:
        self._events = events
        self._scripted_read: set[str] = set()

    def _emit(
        self, call: TaskCall, name: str, level: ObservationLevel, payload: JsonObject
    ) -> None:
        self._events.write(ObservationEvent(
            name=name, level=level, source="e2e.scripted_llm", scope=call.scope,
            payload={
                "task_id": call.task_id, "consumer": call.consumer,
                "profile": str(call.profile), "implementation": "llm_task",
                "target": str(call.profile), **payload,
            },
        ))

    async def invoke(self, call: TaskCall) -> TaskResult:
        return await self.run(call)

    async def run(self, call: TaskCall) -> TaskResult:
        # Script only the model boundary; serialize the real constructed request
        # with the same provider-neutral payloads as LLMTaskRunner.
        self._emit(call, "llm.task.started", ObservationLevel.VERBOSE, {})
        self._emit(call, "llm.model.request", ObservationLevel.MODEL, {
            **task_request_observation(call.messages, call.tool_scope),
            "model_id": "scripted", "provider_id": "scripted", "attempt": 1,
        })
        await asyncio.sleep(0.35)
        result = self._respond(call)
        if result.raw_response is not None:
            response = replace(result.raw_response, tool_calls=tuple(
                replace(tool, kind=None) for tool in result.raw_response.tool_calls
            ), reasoning=Reasoning(
                summary="I’ll use the current request and loaded context to choose the next action. "
                "The review skill describes how to inspect the working copy, compare the observed "
                "result with the intended behavior, and preserve the user’s current reading position."
            ))
            self._emit(call, "llm.model.response", ObservationLevel.MODEL, {
                **task_response_observation(response, call.tool_scope), "attempt": 1,
            })
        self._emit(call, "llm.task.completed", ObservationLevel.VERBOSE, {"status": "success"})
        return result

    def _respond(self, call: TaskCall) -> TaskResult:
        text = _stack_text(call.messages)
        if call.consumer == "core.answer.generate":
            prepared = re.findall(
                rf"{_ANSWER_BEGIN}\n(.*?)\n{_ANSWER_END}", text, re.DOTALL
            )
            return _json_result(
                to_json_object({"text": prepared[-1] if prepared else "Done."})
            )
        profile = (
            call.profile.value
            if isinstance(call.profile, TaskProfile)
            else str(call.profile)
        )
        if profile == TaskProfile.FRAME_STAGE1.value:
            if ASK_TRIGGER in text:
                controls = (
                    ToolCallRecord("select", "select_action_domains", {"domains": ["core", "workspace"], "intent": "Inspect the working copy before asking for a choice."}, ToolKind.CONTROL),
                    ToolCallRecord("load", "load_background", {"links": ["home:skills@review"]}, ToolKind.CONTROL),
                    ToolCallRecord("todo", "set_todo", {"key": "review", "content": "Verify the working copy", "status": "pending"}, ToolKind.CONTROL),
                    ToolCallRecord("milestone", "set_milestone", {"key": "baseline", "content": "The baseline review is in progress"}, ToolKind.CONTROL),
                )
                return TaskResult.success(
                    raw_response=RawResponse("", "scripted", "scripted", tool_calls=controls),
                    answer=None, tool_calls=controls,
                )
            return _tool_result(
                "select_action_domains",
                to_json_object({"domains": ["core"]}),
                ToolKind.CONTROL,
            )
        if profile == TaskProfile.FRAME_STAGE2.value:
            turn = call.scope.nearest(RunLevel.TURN)
            return self._stage2(text, turn.name if turn is not None else "")
        # Unknown consumer (retrieval rerank and similar auxiliaries): a
        # minimal well-formed JSON answer keeps the owner path functional.
        return _json_result(to_json_object({"text": "Finished response"}))

    def _stage2(self, text: str, turn_id: str) -> TaskResult:
        if ASK_TRIGGER in text:
            if turn_id not in self._scripted_read:
                self._scripted_read.add(turn_id)
                return _tool_result(
                    "workspace.read",
                    {"link": "workspace:baseline.md"},
                    ToolKind.ACTION,
                )
            if REPLY_MARKER not in text:
                return _tool_result(
                    "core.ask",
                    to_json_object(
                        {
                            "text": QUESTION_TEXT,
                            "options": list(QUESTION_OPTIONS),
                            "allow_other": True,
                        }
                    ),
                    ToolKind.ACTION,
                )
            option = re.search(r"Option [AB] \(opt_[ab]\)", text)
            comment = re.search(rf"{REPLY_MARKER}[^\n\"]*", text)
            picked = option.group(0) if option else "an option"
            noted = comment.group(0) if comment else ""
            return _answer_action(
                f"You picked {picked}. Comment noted: {noted}."
            )
        said = re.findall(rf"{PLAIN_MARKER}[^\n\"]*", text)
        return _answer_action(f"You said: {said[-1] if said else '(nothing)'}.")


async def _serve(args: argparse.Namespace) -> int:
    root = Path(args.project_dir).resolve()
    if not (root / "tinysoul.toml").is_file():
        if root.exists():
            if any(root.iterdir()):
                print(
                    f"project dir is not empty and not initialized: {root}",
                    file=sys.stderr,
                )
                return 2
            # Install onto a fresh path: replacing over an existing directory
            # is unreliable on Windows (AV/indexer holds transient handles).
            root.rmdir()
        root.parent.mkdir(parents=True, exist_ok=True)
        ProjectInitializer().initialize(
            root, config_profile=ProjectConfigProfile.STANDARD
        )
    settings = EndpointSettings(host="127.0.0.1", port=args.port, token=args.token)
    events = EndpointEventBuffer(
        capacity=settings.event_capacity,
        max_bytes=settings.event_bytes,
        page_bytes=settings.event_page_bytes,
    )
    agent = await Agent.assemble(
        standard_agent(root)
        .with_config_environment(
            ConfigEnvironment.from_project_root(
                root,
                env={},
                overrides={
                    "reflection.schedule.enabled": False,
                    "loop.user.max_cycles": 8,
                },
            )
        )
        .with_agent_settings(
            AgentSettings(
                interactive=False,
                output=OutputSettings(mode=ObservationLevel.MODEL),
            )
        )
        .with_output_sink(events)
        .with_llm_runner(ScriptedLLM(events))
        .build()
    )
    await agent.start()
    await agent.services.get(HomeService).write_top(
        "home:skills@review",
        "---\ntitle: Review baseline\ndescription: Inspect baseline behavior.\n---\n\n"
        "# Review baseline\n\nKeep the original visual rhythm and verify real owner facts.\n\n"
        + "Further reading: preserve the user’s reading position and inspect actual results.\n" * 15,
    )
    await agent.services.get(WorkspaceService).write_text(
        "workspace:baseline.md",
        "# Baseline read\n\nbaseline-output-ready\nInspect the actual resource before answering.\n",
    )
    runtime = agent.runtime
    engine = EndpointEngine(
        settings=settings,
        events=events,
        gateway=runtime.gateway,
        services=runtime.service_access,
        config=runtime.configuration,
        available=lambda: runtime.is_available,
    )
    server = EndpointASGIServer(engine=engine, settings=settings)
    await server.start()
    try:
        ready = {"port": server.port}
        if args.ready_file:
            Path(args.ready_file).write_text(
                json.dumps(ready), encoding="utf-8"
            )
        print(f"TINYSOUL_E2E_READY port={server.port}", flush=True)
        await asyncio.Event().wait()
    finally:
        await server.stop()
        await agent.shutdown()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--token", required=True)
    parser.add_argument("--project-dir", required=True)
    parser.add_argument("--ready-file", default="")
    args = parser.parse_args()
    try:
        return asyncio.run(_serve(args))
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
