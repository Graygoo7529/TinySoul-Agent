import { describe, expect, it } from "vitest";

import type { EndpointEvent, ScopeFrame } from "../types";
import { buildChatTurns } from "./chat";
import { turnTraceToJson, turnTraceToMarkdown } from "./export";

let seq = 0;

function event(
  name: string,
  scope: ScopeFrame[],
  payload: Record<string, unknown> = {},
  createdAt?: number,
): EndpointEvent {
  seq += 1;
  return {
    sequence: seq,
    name,
    level: "model",
    source: "test",
    scope,
    message: "",
    payload,
    created_at: createdAt ?? seq,
  };
}

const turnScope: ScopeFrame[] = [{ level: "turn", name: "turn_1" }];
const cycleScope: ScopeFrame[] = [
  { level: "turn", name: "turn_1" },
  { level: "cycle", name: "cycle_1" },
];
const phaseScope = (phase: string): ScopeFrame[] => [
  ...cycleScope,
  { level: "phase", name: phase },
];

function realisticTurnEvents(): EndpointEvent[] {
  return [
    event("app.command.accepted", [], {
      command_id: "cmd-1",
      kind: "user_turn",
      state: "queued",
      text: "hello agent",
    }),
    event("turn.started", turnScope, { turn_id: "turn_1", request_id: "cmd-1" }),
    event("loop.phase.started", phaseScope("phase1"), { phase: "phase1" }),
    event(
      "llm.model.request",
      phaseScope("phase1"),
      {
        task_id: "task-1",
        profile: "loop.phase1",
        model_id: "model-x",
        provider_id: "provider-a",
        attempt: 1,
        messages: [
          { role: "system", label: "identity", parts: [{ type: "text", text: "You are TinySoul." }] },
          { role: "user", label: "user_input", parts: [{ type: "text", text: "hello agent" }] },
          {
            role: "user",
            label: "working",
            parts: [
              {
                type: "json",
                value: { todos: [{ key: "t1", content: "do thing", status: "pending" }], milestones: [] },
              },
            ],
          },
        ],
        tools: [{ name: "set_todo" }],
      },
      2,
    ),
    event(
      "llm.model.response",
      phaseScope("phase1"),
      {
        task_id: "task-1",
        model_id: "model-x",
        provider_id: "provider-a",
        tool_calls: [
          { id: "c1", name: "set_todo", arguments: { key: "t1", content: "do thing", status: "in_progress" } },
          { id: "c2", name: "select_action_domains", arguments: { domains: ["workspace"] } },
        ],
        usage: { prompt_tokens: 100, completion_tokens: 20 },
      },
      3,
    ),
    event("loop.phase.completed", phaseScope("phase1"), { phase: "phase1" }, 4),
    event("loop.phase.started", phaseScope("phase2"), { phase: "phase2" }, 5),
    event(
      "action.call",
      phaseScope("phase2"),
      { call_id: "call-1", action: "workspace.create", domain: "workspace", sequence: 1, params: { target_link: "workspace:a.md", instruction: "Create the document." } },
      6,
    ),
    event("loop.phase.completed", phaseScope("phase2"), { phase: "phase2" }, 7),
    event("loop.phase.started", phaseScope("phase3"), { phase: "phase3" }, 8),
    event(
      "action.result",
      phaseScope("phase3"),
      { call_id: "call-1", action: "workspace.create", domain: "workspace", status: "success", stage: "executor", payload: { link: "workspace:a.md" } },
      9,
    ),
    event("loop.phase.completed", phaseScope("phase3"), { phase: "phase3" }, 10),
    event("turn.output", turnScope, { turn_id: "turn_1", text: "Done!" }, 11),
    event("turn.completed", turnScope, { turn_id: "turn_1", status: "answered" }, 12),
  ];
}

describe("buildChatTurns", () => {
  it("groups events into a turn with cycles, phases, actions and tasks", () => {
    const turns = buildChatTurns(realisticTurnEvents(), [
      { commandId: "cmd-1", text: "hello agent" },
    ]);
    expect(turns).toHaveLength(1);
    const turn = turns[0];
    expect(turn.status).toBe("answered");
    expect(turn.userMessages).toEqual(["hello agent"]);
    expect(turn.assistantText).toBe("Done!");
    expect(turn.cycles).toHaveLength(1);
    const cycle = turn.cycles[0];
    expect(cycle.status).toBe("completed");
    expect(cycle.phases.map((p) => p.phase)).toEqual(["phase1", "phase2", "phase3"]);
    const phase2 = cycle.phases[1];
    expect(phase2.actions).toHaveLength(1);
    expect(phase2.actions[0].action).toBe("workspace.create");
    const phase3 = cycle.phases[2];
    expect(phase3.actions[0].result?.status).toBe("success");
  });

  it("extracts Phase1 control ops and derives working state", () => {
    const [turn] = buildChatTurns(realisticTurnEvents(), []);
    const phase1 = turn.cycles[0].phases[0];
    expect(phase1.controlOps.map((op) => op.kind)).toEqual([
      "set_todo",
      "select_domains",
    ]);
    // The message-stack snapshot is adopted first (todo pending); the later
    // Phase1 control op then overrides it to in_progress.
    expect(turn.working.todos).toEqual([
      { key: "t1", content: "do thing", status: "in_progress" },
    ]);
    expect(turn.usage).toEqual({ calls: 1, promptTokens: 100, completionTokens: 20 });
  });

  it("recovers the user input from the first message stack without a local echo", () => {
    const [turn] = buildChatTurns(realisticTurnEvents(), []);
    expect(turn.userMessages).toEqual(["hello agent"]);
  });

  it("recovers accepted input when model payloads are skeletonized", () => {
    const events = [
      event("app.command.accepted", [], {
        command_id: "cmd-1",
        kind: "user_turn",
        text: "durable question",
      }),
      event("turn.started", turnScope, {
        turn_id: "turn_1",
        request_id: "cmd-1",
        business_day: "2026-08-05",
      }),
      event("llm.model.request", phaseScope("phase1"), {
        skeleton: true,
        task_id: "task-1",
      }),
      event("turn.completed", turnScope, { status: "answered" }),
    ];
    const [turn] = buildChatTurns(events, [], {
      activeDay: "2026-08-05",
    });
    expect(turn.userMessages).toEqual(["durable question"]);
  });

  it("marks a turn failed on turn.failed/turn.completed and stops the clock", () => {
    const events = [
      event("turn.started", turnScope, { turn_id: "turn_1", request_id: "cmd-1" }),
      event("loop.phase.started", phaseScope("phase1"), { phase: "phase1" }, 2),
      event("loop.phase.completed", phaseScope("phase1"), { phase: "phase1" }, 3),
      event("turn.failed", turnScope, {
        status: "failed",
        reason: "runtime.turn_end",
        module: "loop",
        kind: "loop.contract_violation",
        feedback: ["retry 1 failed", "retry 2 failed"],
      }, 4),
      event("turn.completed", turnScope, {
        turn_id: "turn_1",
        has_output: false,
        status: "failed",
      }, 5),
    ];
    const [turn] = buildChatTurns(events, []);
    expect(turn.status).toBe("failed");
    // turn.completed is the final boundary and refines endedAt.
    expect(turn.endedAt).toBe(5);
    expect(turn.currentActivity).toBeUndefined();
    expect(turn.failure).toEqual({
      reason: "runtime.turn_end",
      module: "loop",
      kind: "loop.contract_violation",
      feedback: ["retry 1 failed", "retry 2 failed"],
    });
  });

  it("marks recovered historical turns and closes interrupted running ones", () => {
    const events = [
      event("turn.started", turnScope, { turn_id: "turn_1", request_id: "cmd-1" }),
      event("loop.phase.started", phaseScope("phase1"), { phase: "phase1" }),
    ];
    const latest = events[events.length - 1].sequence;
    const [turn] = buildChatTurns(events, [], {
      recoveredThroughSequence: latest,
    });
    expect(turn.recovered).toBe(true);
    expect(turn.status).toBe("stopped");
    expect(turn.failureMessage).toContain("restart");
  });

  it("preserves an active running turn during same-instance recovery", () => {
    const events = [
      event("turn.started", turnScope, {
        turn_id: "turn_1",
        business_day: "2026-08-05",
      }),
      event("loop.phase.started", phaseScope("phase1"), { phase: "phase1" }),
    ];
    const latest = events[events.length - 1].sequence;
    const [turn] = buildChatTurns(events, [], {
      recoveredThroughSequence: latest,
      preserveRunning: true,
    });
    expect(turn.status).toBe("running");
  });

  it("builds a semantic activity feed without fixed stage texts", () => {
    const [turn] = buildChatTurns(realisticTurnEvents(), []);
    const texts = turn.activity.map((a) => a.text).join("\n");
    expect(texts).toContain("Selected domains: workspace");
    expect(texts).toContain("workspace.create succeeded");
    // Pure fixed texts ("Thinking", "Context & Domains", …) are no longer
    // emitted as activity entries; only semantic facts are.
    expect(turn.activity.some((a) => a.text === "Thinking")).toBe(false);
    expect(turn.activity.some((a) => a.text === "Context & Domains")).toBe(false);
  });
});

describe("turn trace export", () => {
  it("exports a markdown document with the full message stack", () => {
    const [turn] = buildChatTurns(realisticTurnEvents(), []);
    const md = turnTraceToMarkdown(turn);
    expect(md).toContain("# Turn Trace — turn_1");
    expect(md).toContain("**Message stack (3 messages)**");
    expect(md).toContain("You are TinySoul.");
    expect(md).toContain("select_action_domains");
    expect(md).toContain("workspace.create");
    expect(md).toContain("Done!");
  });

  it("exports structured JSON", () => {
    const [turn] = buildChatTurns(realisticTurnEvents(), []);
    const parsed = JSON.parse(turnTraceToJson(turn));
    expect(parsed.turn_id).toBe("turn_1");
    expect(parsed.cycles[0].phases[0].llm_calls[0].request.messages).toHaveLength(3);
    expect(parsed.final_answer).toBe("Done!");
  });
});

describe("semantic activity details", () => {
  it("surfaces reasoning summaries as thinking activities", () => {
    const events = [
      event("turn.started", turnScope, { turn_id: "turn_1", request_id: "cmd-1" }),
      event("loop.phase.started", phaseScope("phase1"), { phase: "phase1" }),
      event("llm.model.request", phaseScope("phase1"), {
        task_id: "task-1",
        profile: "loop.phase1",
        model_id: "model-x",
        provider_id: "provider-a",
        attempt: 1,
        messages: [],
      }),
      event("llm.model.response", phaseScope("phase1"), {
        task_id: "task-1",
        model_id: "model-x",
        provider_id: "provider-a",
        reasoning: { summary: "The user wants a docs sweep.\nI should inspect first." },
        tool_calls: [],
      }),
    ];
    const [turn] = buildChatTurns(events, []);
    const thinking = turn.activity.find((a) => a.kind === "thinking");
    expect(thinking).toBeDefined();
    expect(thinking?.text).toBe("The user wants a docs sweep.");
    expect(thinking?.reasoning).toBe(
      "The user wants a docs sweep.\nI should inspect first.",
    );
    expect(thinking?.detail).toBe("Context & Domains");
    expect(thinking?.cycleIndex).toBe(1);
  });

  it("surfaces the stage1 intent with structured domains", () => {
    const events = [
      event("turn.started", turnScope, { turn_id: "turn_1", request_id: "cmd-1" }),
      event("loop.phase.started", phaseScope("phase1"), { phase: "phase1" }),
      event("llm.model.request", phaseScope("phase1"), {
        task_id: "task-1",
        profile: "loop.phase1",
        model_id: "model-x",
        provider_id: "provider-a",
        attempt: 1,
        messages: [],
      }),
      event("llm.model.response", phaseScope("phase1"), {
        task_id: "task-1",
        model_id: "model-x",
        provider_id: "provider-a",
        tool_calls: [
          {
            id: "c2",
            name: "select_action_domains",
            arguments: {
              domains: ["workspace", "web"],
              intent: "Investigate the docs before editing",
            },
          },
        ],
      }),
    ];
    const [turn] = buildChatTurns(events, []);
    const intent = turn.activity.find((a) => a.kind === "intent");
    expect(intent).toBeDefined();
    expect(intent?.text).toBe("Investigate the docs before editing");
    expect(intent?.domains).toEqual(["workspace", "web"]);
    expect(intent?.intent).toBe("Investigate the docs before editing");
  });

  it("routes stage1-loaded skill links into skills activities", () => {
    const events = [
      event("turn.started", turnScope, { turn_id: "turn_1", request_id: "cmd-1" }),
      event("loop.phase.started", phaseScope("phase1"), { phase: "phase1" }),
      event("context.background.changed", turnScope, {
        turn_id: "turn_1",
        loaded_links: [
          "home:skills@tinysoul-docs",
          "home:skills@writing-style",
          "home:agent@preferences",
        ],
        evicted_links: [],
        entries: [],
      }),
    ];
    const [turn] = buildChatTurns(events, []);
    const skills = turn.activity.find((a) => a.kind === "skills");
    expect(skills?.text).toBe("Loaded 2 skills");
    expect(skills?.skills).toEqual(["tinysoul-docs", "writing-style"]);
    const contextLoad = turn.activity.find((a) => a.kind === "context");
    expect(contextLoad?.text).toBe("Loaded 1 background link");
    expect(contextLoad?.detail).toBe("home:agent@preferences");
  });

  it("enriches executing actions with semantic targets", () => {
    const events = [
      event("turn.started", turnScope, { turn_id: "turn_1", request_id: "cmd-1" }),
      event("loop.phase.started", phaseScope("phase3"), { phase: "phase3" }),
      event(
        "action.call",
        phaseScope("phase3"),
        {
          call_id: "call-1",
          action: "web.search_by_kimi",
          domain: "web",
          sequence: 1,
          params: { query: "kimi code activity stream" },
        },
      ),
    ];
    const [turn] = buildChatTurns(events, []);
    const activity = turn.activity.find((a) => a.kind === "action");
    expect(activity?.text).toBe("Searching web.search_by_kimi");
    expect(activity?.target).toEqual({ query: "kimi code activity stream" });
    expect(activity?.callId).toBe("call-1");
    expect(turn.currentActivity?.label ?? "").not.toBe("");
  });

  it("enriches action results with factual summaries", () => {
    const events = [
      event("turn.started", turnScope, { turn_id: "turn_1", request_id: "cmd-1" }),
      event("loop.phase.started", phaseScope("phase2"), { phase: "phase2" }),
      event(
        "action.call",
        phaseScope("phase2"),
        {
          call_id: "call-1",
          action: "execution.run_bash_command",
          domain: "execution",
          sequence: 1,
          params: { command: "npm run build" },
        },
      ),
      event(
        "action.result",
        phaseScope("phase3"),
        {
          call_id: "call-1",
          action: "execution.run_bash_command",
          domain: "execution",
          status: "success",
          stage: "executor",
          payload: { exit_code: 0, duration_seconds: 2.34, stdout: "built" },
        },
      ),
    ];
    const [turn] = buildChatTurns(events, []);
    const succeeded = turn.activity.find((a) => a.text.includes("succeeded"));
    expect(succeeded?.detail).toBe("exit 0 · 2.3s");
    expect(succeeded?.target).toEqual({ command: "npm run build" });
  });

  it("records provider retries as retry activities", () => {
    const events = [
      event("turn.started", turnScope, { turn_id: "turn_1", request_id: "cmd-1" }),
      event("loop.phase.started", phaseScope("phase1"), { phase: "phase1" }),
      event("llm.model.retry", phaseScope("phase1"), {
        profile: "loop.phase1",
        model_id: "model-x",
        provider_id: "provider-a",
        attempt: 2,
      }),
    ];
    const [turn] = buildChatTurns(events, []);
    const retry = turn.activity.find((a) => a.kind === "retry");
    expect(retry?.text).toBe("Provider hiccup — retrying (attempt 2)");
  });
});
