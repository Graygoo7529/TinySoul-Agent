import { describe, expect, it } from "vitest";

import type { EndpointEvent, ScopeFrame } from "../types";
import { buildChatTurns } from "./chat";
import { buildTurnExportBundle } from "./export";
import { cycleDomains, phaseHeadline, selectedDomains } from "./phaseSummary";

let seq = 0;

function event(
  name: string,
  scope: ScopeFrame[],
  payload: Record<string, unknown> = {},
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
    created_at: seq,
  };
}

const cycleScope: ScopeFrame[] = [
  { level: "turn", name: "turn_9" },
  { level: "cycle", name: "cycle_1" },
];
const phaseScope = (phase: string): ScopeFrame[] => [
  ...cycleScope,
  { level: "phase", name: phase },
];

function turnEvents(): EndpointEvent[] {
  return [
    event("turn.started", [{ level: "turn", name: "turn_9" }], {
      turn_id: "turn_9",
      request_id: "x",
    }),
    event("loop.phase.started", phaseScope("phase1"), { phase: "phase1" }),
    event("llm.model.request", phaseScope("phase1"), {
      task_id: "t1",
      profile: "framework",
      model_id: "m",
      provider_id: "p",
      attempt: 1,
      messages: [
        { role: "user", label: "user_input", parts: [{ type: "text", text: "hi" }] },
      ],
    }),
    event("llm.model.response", phaseScope("phase1"), {
      task_id: "t1",
      model_id: "m",
      provider_id: "p",
      tool_calls: [
        {
          id: "c1",
          name: "select_action_domains",
          arguments: { domains: ["workspace"], intent: "Need to write a file." },
        },
      ],
      usage: { input_tokens: 10, output_tokens: 5 },
    }),
    event("loop.phase.completed", phaseScope("phase1"), { phase: "phase1" }),
    event("action.call", phaseScope("phase2"), {
      call_id: "a1",
      action: "workspace.create",
      domain: "workspace",
      params: {
        target_link: "workspace:x.md",
        instruction: "Create the document.",
      },
    }),
    event("action.result", phaseScope("phase3"), {
      call_id: "a1",
      action: "workspace.create",
      domain: "workspace",
      status: "success",
      stage: "execute",
      payload: { link: "workspace:x.md" },
    }),
    event("turn.completed", [{ level: "turn", name: "turn_9" }], { status: "completed" }),
  ];
}

describe("phase summaries", () => {
  const [turn] = buildChatTurns(turnEvents());
  const cycle = turn.cycles[0];
  const [phase1, phase2, phase3] = [
    cycle.phases.find((p) => p.phase === "phase1")!,
    cycle.phases.find((p) => p.phase === "phase2")!,
    cycle.phases.find((p) => p.phase === "phase3")!,
  ];

  it("extracts selected domains and intent from Phase1 control ops", () => {
    expect(selectedDomains(phase1)).toEqual(["workspace"]);
    expect(cycleDomains(cycle)).toEqual(["workspace"]);
  });

  it("states what each phase did in one direct line", () => {
    expect(phaseHeadline(phase1)).toBe("Selected 1 domain");
    expect(phaseHeadline(phase2)).toBe("Planned 1 action");
    expect(phaseHeadline(phase3)).toBe("1 action executed successfully");
  });
});

describe("folder export bundle", () => {
  it("organizes files by cycle with one JSON per LLM call", () => {
    const [turn] = buildChatTurns(turnEvents());
    const bundle = buildTurnExportBundle(turn);
    expect(bundle.dirName).toMatch(/^tinysoul-turn-turn_9-/);
    const paths = bundle.files.map((f) => f.path);
    expect(paths).toContain("turn.json");
    expect(paths).toContain("trace.md");
    expect(paths).toContain("cycle-1/phase1-llm-1-framework.json");
    const call = JSON.parse(
      bundle.files.find((f) => f.path.includes("phase1-llm-1"))!.contents,
    );
    expect(call.cycle).toBe(1);
    expect(call.phase).toBe("phase1");
    expect(call.request.messages).toHaveLength(1);
    expect(call.response.tool_calls[0].name).toBe("select_action_domains");
  });
});
