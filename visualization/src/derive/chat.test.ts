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
      { call_id: "call-1", action: "workspace.create", domain: "workspace", status: "success", stage: "execute", invoke_id: "inv-1", batch_id: "batch-1", payload: { link: "workspace:a.md" } },
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
    // The Phase3 result is written back onto the Phase2 planned record.
    expect(phase2.actions[0].result?.status).toBe("success");
    const phase3 = cycle.phases[2];
    // Exactly one mirrored record (pre-mirrored at phase3 start, then claimed).
    expect(phase3.actions).toHaveLength(1);
    expect(phase3.actions[0].result?.status).toBe("success");
    expect(phase3.actions[0].invokeId).toBe("inv-1");
    expect(phase3.actions[0].batchId).toBe("batch-1");
    expect(phase3.actions[0].params).toEqual({
      target_link: "workspace:a.md",
      instruction: "Create the document.",
    });
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

  it("builds a semantic activity feed without fixed phase texts", () => {
    const [turn] = buildChatTurns(realisticTurnEvents(), []);
    const texts = turn.activity.map((a) => a.text).join("\n");
    expect(texts).toContain("Selected domains: workspace");
    const actionEntries = turn.activity.filter((a) => a.kind === "action");
    expect(actionEntries).toHaveLength(1);
    expect(actionEntries[0]).toMatchObject({
      text: "生成 workspace:a.md",
      callId: "call-1",
      action: "workspace.create",
      status: "succeeded",
      resultHeadline: "workspace:a.md",
    });
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

  it("mirrors planned calls into phase3 and flips the first entry to running", () => {
    const events = [
      event("turn.started", turnScope, { turn_id: "turn_1", request_id: "cmd-1" }),
      event("loop.phase.started", phaseScope("phase2"), { phase: "phase2" }),
      event(
        "action.call",
        phaseScope("phase2"),
        {
          call_id: "call-1",
          action: "web.search_by_kimi",
          domain: "web",
          sequence: 1,
          params: { query: "kimi code activity stream" },
        },
      ),
      event("loop.phase.completed", phaseScope("phase2"), { phase: "phase2" }),
      event("loop.phase.started", phaseScope("phase3"), { phase: "phase3" }),
    ];
    const [turn] = buildChatTurns(events, []);
    // The planned call is pre-mirrored into Phase3 with params, no result yet.
    const phase3 = turn.cycles[0].phases.find((p) => p.phase === "phase3")!;
    expect(phase3.actions).toHaveLength(1);
    expect(phase3.actions[0].params).toEqual({ query: "kimi code activity stream" });
    expect(phase3.actions[0].result).toBeUndefined();
    // The activity entry carries the registry headline and the running status.
    const activity = turn.activity.find((a) => a.kind === "action");
    expect(activity).toMatchObject({
      text: "检索 “kimi code activity stream”",
      callId: "call-1",
      action: "web.search_by_kimi",
      status: "running",
      target: { query: "kimi code activity stream" },
    });
    // The running headline is back: verb + target label, action as detail.
    expect(turn.currentActivity).toEqual({
      phase: "phase3",
      label: "Searching “kimi code activity stream”",
      detail: "web.search_by_kimi",
    });
  });

  it("keeps planned entries planned before phase3 starts", () => {
    const events = [
      event("turn.started", turnScope, { turn_id: "turn_1", request_id: "cmd-1" }),
      event("loop.phase.started", phaseScope("phase2"), { phase: "phase2" }),
      event(
        "action.call",
        phaseScope("phase2"),
        {
          call_id: "call-1",
          action: "workspace.read",
          domain: "workspace",
          sequence: 1,
          params: { link: "workspace:a.md", start_line: 120, end_line: 180 },
        },
      ),
      event("loop.phase.completed", phaseScope("phase2"), { phase: "phase2" }),
    ];
    const [turn] = buildChatTurns(events, []);
    const activity = turn.activity.find((a) => a.kind === "action");
    expect(activity).toMatchObject({
      text: "读取 workspace:a.md",
      detail: "120-180 行",
      status: "planned",
    });
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
      event("loop.phase.completed", phaseScope("phase2"), { phase: "phase2" }),
      event("loop.phase.started", phaseScope("phase3"), { phase: "phase3" }),
      event(
        "action.result",
        phaseScope("phase3"),
        {
          call_id: "call-1",
          action: "execution.run_bash_command",
          domain: "execution",
          status: "success",
          stage: "execute",
          payload: { exit_code: 0, duration_seconds: 2.34, stdout: "built" },
        },
      ),
    ];
    const [turn] = buildChatTurns(events, []);
    const succeeded = turn.activity.find((a) => a.kind === "action");
    expect(succeeded).toMatchObject({
      text: "执行 npm run build",
      detail: "exit 0 · 2.3s",
      status: "succeeded",
      resultHeadline: "exit 0 · 2.3s",
      target: { command: "npm run build" },
    });
  });

  it("appends a single-sided record for normalize failures and surfaces an error entry", () => {
    const events = [
      event("turn.started", turnScope, { turn_id: "turn_1", request_id: "cmd-1" }),
      event("loop.phase.started", phaseScope("phase3"), { phase: "phase3" }),
      event(
        "action.result",
        phaseScope("phase3"),
        {
          call_id: "call-x",
          action: "workspace.patch",
          domain: "workspace",
          status: "failed",
          stage: "normalize",
          failure: { reason: "invalid_params", feedback: "target_link is required" },
        },
      ),
    ];
    const [turn] = buildChatTurns(events, []);
    const phase3 = turn.cycles[0].phases.find((p) => p.phase === "phase3")!;
    expect(phase3.actions).toHaveLength(1);
    expect(phase3.actions[0].params).toEqual({});
    expect(phase3.actions[0].result?.stage).toBe("normalize");
    const entry = turn.activity.find((a) => a.callId === "call-x");
    expect(entry).toMatchObject({
      kind: "error",
      action: "workspace.patch",
      status: "failed",
      text: "编辑",
      detail: "target_link is required",
      resultHeadline: "target_link is required",
    });
  });

  it("pairs transfer-driven multi-segment phase2/phase3 correctly", () => {
    const events = [
      event("turn.started", turnScope, { turn_id: "turn_1", request_id: "cmd-1" }),
      event("loop.phase.started", phaseScope("phase2"), { phase: "phase2" }, 2),
      event(
        "action.call",
        phaseScope("phase2"),
        { call_id: "call-1", action: "workspace.scan", domain: "workspace", sequence: 1, params: {} },
        3,
      ),
      event("loop.phase.completed", phaseScope("phase2"), { phase: "phase2" }, 4),
      event("loop.phase.started", phaseScope("phase3"), { phase: "phase3" }, 5),
      event(
        "action.result",
        phaseScope("phase3"),
        { call_id: "call-1", action: "workspace.scan", domain: "workspace", status: "success", stage: "execute", payload: { count: 4 } },
        6,
      ),
      // Phase3 ends early through a transfer and Phase2 replans in the same cycle.
      event("loop.phase.completed", phaseScope("phase3"), { phase: "phase3", transfer_action: "workspace.read" }, 7),
      event("loop.phase.started", phaseScope("phase2"), { phase: "phase2" }, 8),
      event(
        "action.call",
        phaseScope("phase2"),
        { call_id: "call-2", action: "workspace.read", domain: "workspace", sequence: 2, params: { link: "workspace:a.md", start_line: 1, end_line: 10 } },
        9,
      ),
      event("loop.phase.completed", phaseScope("phase2"), { phase: "phase2" }, 10),
      event("loop.phase.started", phaseScope("phase3"), { phase: "phase3" }, 11),
      event(
        "action.result",
        phaseScope("phase3"),
        { call_id: "call-2", action: "workspace.read", domain: "workspace", status: "success", stage: "execute", payload: { actual: { start: 1, end: 10 } } },
        12,
      ),
      event("loop.phase.completed", phaseScope("phase3"), { phase: "phase3" }, 13),
    ];
    const [turn] = buildChatTurns(events, []);
    expect(turn.cycles).toHaveLength(1);
    const cycle = turn.cycles[0];
    const phase2 = cycle.phases.find((p) => p.phase === "phase2")!;
    const phase3 = cycle.phases.find((p) => p.phase === "phase3")!;
    // Both segments' calls live in the same Phase2 step and got results back.
    expect(phase2.actions.map((a) => a.callId)).toEqual(["call-1", "call-2"]);
    expect(phase2.actions.every((a) => a.result?.status === "success")).toBe(true);
    // The second phase3 segment mirrors only the newly planned call-2;
    // call-1 is not duplicated.
    expect(phase3.actions.map((a) => a.callId)).toEqual(["call-1", "call-2"]);
    expect(phase3.actions[0].result?.status).toBe("success");
    expect(phase3.actions[1].result?.status).toBe("success");
    // One activity entry per call, both resolved with registry summaries.
    const entries = turn.activity.filter((a) => a.kind === "action");
    expect(entries.map((a) => [a.callId, a.status, a.resultHeadline])).toEqual([
      ["call-1", "succeeded", "4 个资源"],
      ["call-2", "succeeded", "10 行"],
    ]);
  });

  it("mirrors planned calls on action.batch.started and carries the batch id", () => {
    const events = [
      event("turn.started", turnScope, { turn_id: "turn_1", request_id: "cmd-1" }),
      event("loop.phase.started", phaseScope("phase2"), { phase: "phase2" }),
      event(
        "action.call",
        phaseScope("phase2"),
        { call_id: "call-1", action: "workspace.create", domain: "workspace", sequence: 1, params: { target_link: "workspace:a.md", instruction: "x" } },
      ),
      event("loop.phase.completed", phaseScope("phase2"), { phase: "phase2" }),
      event("action.batch.started", phaseScope("phase3"), { batch_id: "batch-9", action_count: 1 }),
    ];
    const [turn] = buildChatTurns(events, []);
    const phase3 = turn.cycles[0].phases.find((p) => p.phase === "phase3")!;
    expect(phase3.actions).toHaveLength(1);
    expect(phase3.actions[0].result).toBeUndefined();
    const activity = turn.activity.find((a) => a.kind === "action");
    expect(activity?.status).toBe("running");
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
