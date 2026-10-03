// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { JsonObject, ObservationEvent } from "../../api/v2/types";
import { useInspectorStore } from "../../store/inspectorStore";
import {
  FakeEndpoint,
  jsonResponse,
  makeStatus,
  queryOf,
  resetAppStores,
  wireConnectedStores,
} from "../../app/testing";
import { openTurnProcess, pushActionDetail, pushJobDetail } from "./entries";
import { ActivityTimeline, ProcessPanel } from "./ProcessPanel";
import { ActionDetailPanel } from "./ActionDetailPanel";
import { JobPanel } from "./JobPanel";

import jobDetailFixture from "../../../test/fixtures/contracts/job-detail.json";
import jobOutputFixture from "../../../test/fixtures/contracts/job-output.json";

(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement;
let root: Root;
let endpoint: FakeEndpoint;
let epoch: number;

const TURN_ID = "contract-turn";
const HEAD = 900;

function event(
  name: string,
  sequence: number,
  payload: JsonObject,
  scope: { level: string; name: string }[] = [],
): ObservationEvent {
  return {
    sequence,
    name,
    level: "verbose",
    source: "test",
    scope,
    message: name,
    payload,
    created_at: sequence,
  };
}

const TURN = { level: "turn", name: TURN_ID };
const CYCLE = { level: "cycle", name: "cycle_1" };
const PHASE2 = { level: "phase", name: "phase2" };
const PHASE3 = { level: "phase", name: "phase3" };

function serveEvents(events: ObservationEvent[], gap = false) {
  endpoint.get("/v2/events", () =>
    jsonResponse({
      instance_id: "instance_1",
      events,
      next_sequence: HEAD,
      gap,
    }),
  );
}

beforeEach(() => {
  resetAppStores();
  useInspectorStore.setState({ entries: [] });
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  endpoint = new FakeEndpoint();
  epoch = wireConnectedStores(
    endpoint,
    makeStatus({ activeTurnId: TURN_ID, latestEventSequence: HEAD }),
  ).epoch;
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  resetAppStores();
  useInspectorStore.setState({ entries: [] });
});

async function flush(rounds = 10) {
  for (let index = 0; index < rounds; index += 1) {
    await act(async () => {});
  }
}

function render(element: React.ReactElement) {
  act(() => {
    root.render(element);
  });
}

function clickButton(text: string) {
  const target = Array.from(container.querySelectorAll("button")).find(
    (button) => button.textContent?.includes(text),
  );
  if (target === undefined) throw new Error(`button "${text}" not found`);
  act(() => {
    target.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  });
}

// ---------------------------------------------------------------------------
// ProcessPanel
// ---------------------------------------------------------------------------

describe("ActivityTimeline", () => {
  beforeEach(() => {
    vi.stubGlobal("ResizeObserver", class { observe() {} disconnect() {} });
  });
  afterEach(() => vi.unstubAllGlobals());

  it("keeps successive intents in Thinking and expands intent and Context details inline", () => {
    const phase = { level: "phase", name: "phase1" };
    const events = [
      event("llm.model.response", 1, {
        tool_calls: [{ id: "select", name: "select_action_domains", kind: "control",
          arguments: { domains: ["home"], intent: "First intent\nRead the relevant resources." } }],
      }, [TURN, CYCLE, phase]),
      event("loop.phase.completed", 2, { phase: "phase1", selected_domains: ["home"] }, [TURN, CYCLE, phase]),
      event("llm.model.request", 3, { task_id: "t2", provenance: [{ refs: ["home:skills_domain:home"] }] }, [TURN, CYCLE, PHASE2]),
      event("context.control.applied", 4, { operation: "set_milestone", details: {
        content: "Found the relevant document\nIts section on testing explains the decision.",
      } }, [TURN, CYCLE, phase]),
    ];
    render(<ActivityTimeline events={events} turnId={TURN_ID} epoch={epoch} day={null} />);
    clickButton("Activity");
    clickButton("Thinking");
    expect(container.textContent).toContain("First intent");
    expect(container.textContent).not.toContain("Task guidance");
    const nextCycle = { level: "cycle", name: "cycle_2" };
    render(<ActivityTimeline events={[...events,
      event("llm.model.response", 5, {
        tool_calls: [{ id: "select", name: "select_action_domains", kind: "control",
          arguments: { domains: ["workspace"], intent: "Second intent\nVerify the result against the source." } }],
      }, [TURN, nextCycle, phase]),
      event("loop.phase.completed", 6, { phase: "phase1", selected_domains: ["workspace"] }, [TURN, nextCycle, phase]),
    ]} turnId={TURN_ID} epoch={epoch} day={null} />);
    expect(container.textContent).toContain("First intent");
    expect(container.textContent).toContain("Second intent");
    expect(container.textContent).not.toContain("In progress");
    expect(container.textContent).not.toContain("Selected domains");
    clickButton("Second intent");
    expect(container.textContent).toContain("Verify the result against the source.");
    expect(container.textContent).toContain("Selected domains");
    clickButton("Second intent");
    expect(container.textContent).not.toContain("Verify the result against the source.");
    clickButton("Context");
    expect(container.textContent).toContain("Task guidance");
    expect(container.textContent).not.toContain("Second intent");
    clickButton("Milestone");
    expect(container.textContent).toContain("Its section on testing explains the decision.");
    clickButton("Milestone");
    expect(container.textContent).not.toContain("Its section on testing explains the decision.");
  });
});

describe("ProcessPanel", () => {
  const processEvents = [
    event("action.call", 10, {
      call_id: "c1",
      action: "workspace.read",
      domain: "workspace",
      sequence: 1,
      params: { link: "workspace:a.md" },
    }, [TURN, CYCLE, PHASE2]),
    event("action.result", 20, {
      result_id: "r1",
      call_id: "c1",
      action: "workspace.read",
      status: "success",
      stage: "execution",
      sequence: 1,
      domain: "workspace",
      invoke_id: "invoke_c1",
      batch_id: "b1",
      failure: null,
      payload: { link: "workspace:a.md", text: "hi" },
    }, [TURN, CYCLE, PHASE3]),
    event("action.call", 30, {
      call_id: "c2",
      action: "execution.run_shell",
      domain: "execution",
      sequence: 2,
      params: { command: "ls" },
    }, [TURN, CYCLE, PHASE2]),
    event("action.execution", 40, {
      invoke_id: "invoke_c2",
      call_id: "c2",
      state: "not_executed",
    }, [TURN, CYCLE, PHASE3]),
  ];

  it("renders the Turn → Cycle → Phase → Action tree with formal states", async () => {
    serveEvents(processEvents);
    render(<ProcessPanel epoch={epoch} turnId={TURN_ID} day="2026-09-29" />);
    await flush();

    expect(queryOf(endpoint.calls("/v2/events")[0]!, "turn_id")).toBe(TURN_ID);
    expect(queryOf(endpoint.calls("/v2/events")[0]!, "mode")).toBe("model");
    clickButton("phase3");
    const text = container.textContent ?? "";
    expect(text).toContain("Cycle 1");
    expect(text).toContain("workspace.read");
    expect(text).toContain("success");
    expect(text).toContain("execution.run_shell");
    // A not-executed action is shown as such — never as a tool answer.
    expect(text).toContain("not executed");
  });

  it("pushes the action detail from a process row", async () => {
    serveEvents(processEvents);
    render(<ProcessPanel epoch={epoch} turnId={TURN_ID} day="2026-09-29" />);
    await flush();
    clickButton("phase3");
    clickButton("workspace.read");
    const entries = useInspectorStore.getState().entries;
    expect(entries).toHaveLength(1);
    expect(entries[0]!.key).toContain("trace:action:contract-turn:c1");
  });

  it("reports a truncated retained window", async () => {
    serveEvents(processEvents, true);
    render(<ProcessPanel epoch={epoch} turnId={TURN_ID} day="2026-09-29" />);
    await flush();
    expect(container.textContent).toContain("truncated");
  });
});

// ---------------------------------------------------------------------------
// ActionDetailPanel
// ---------------------------------------------------------------------------

describe("ActionDetailPanel", () => {
  it("locates by the same-name ordinal and renders the failure honestly", async () => {
    serveEvents([
      event("action.call", 10, {
        call_id: "c1", action: "workspace.write", domain: "workspace", sequence: 1,
        params: { link: "workspace:a.md", content: "v1" },
      }, [TURN, CYCLE, PHASE2]),
      event("action.call", 20, {
        call_id: "c2", action: "workspace.write", domain: "workspace", sequence: 2,
        params: { link: "workspace:b.md", content: "v2" },
      }, [TURN, CYCLE, PHASE2]),
      event("action.result", 30, {
        result_id: "r2", call_id: "c2", action: "workspace.write",
        status: "failed", stage: "execution", sequence: 2, domain: "workspace",
        invoke_id: "invoke_c2", batch_id: "b1",
        failure: { reason: "hook_rejected", stage: "execution", feedback: "write rejected by hook" },
        payload: null,
      }, [TURN, CYCLE, PHASE3]),
    ]);
    render(
      <ActionDetailPanel
        epoch={epoch}
        turnId={TURN_ID}
        day="2026-09-29"
        selector={{ action: "workspace.write", ordinal: 1 }}
      />,
    );
    await flush();
    const text = container.textContent ?? "";
    expect(text).toContain("failed");
    expect(text).toContain("hook_rejected");
    expect(text).toContain("write rejected by hook");
    // The second call's params are the ones shown.
    clickButton("Call params");
    await flush();
    expect(container.textContent).toContain("workspace:b.md");
  });

  it("states a missing result without inventing one", async () => {
    serveEvents([
      event("action.call", 10, {
        call_id: "c1", action: "execution.start", domain: "execution", sequence: 1, params: {},
      }, [TURN, CYCLE, PHASE2]),
      event("action.execution", 20, {
        invoke_id: "invoke_c1", call_id: "c1", state: "cancelled",
      }, [TURN, CYCLE, PHASE3]),
    ]);
    render(
      <ActionDetailPanel
        epoch={epoch}
        turnId={TURN_ID}
        day="2026-09-29"
        selector={{ callId: "c1", action: "execution.start", ordinal: 0 }}
      />,
    );
    await flush();
    const text = container.textContent ?? "";
    expect(text).toContain("cancelled");
    expect(text).toContain("No result was recorded");
  });

  it("links the action's model calls through the module scope", async () => {
    serveEvents([
      event("action.call", 10, {
        call_id: "c1", action: "memory.search", domain: "memory", sequence: 1,
        params: { source: { kind: "query", query: "x" }, steps: [] },
      }, [TURN, CYCLE, PHASE2]),
      event("action.result", 20, {
        result_id: "r1", call_id: "c1", action: "memory.search",
        status: "success", stage: "execution", sequence: 1, domain: "memory",
        invoke_id: "invoke_c1", batch_id: "b1", failure: null,
        payload: { items: [], coverage: {}, page: { offset: 0, count: 0, total: 0, continuation: null } },
      }, [TURN, CYCLE, PHASE3]),
      event("llm.task.started", 30, {
        task_id: "task_7", consumer: "memory.search.rerank", profile: "search_eval",
      }, [TURN, CYCLE, PHASE3, { level: "module", name: "invoke_c1" }]),
    ]);
    render(
      <ActionDetailPanel
        epoch={epoch}
        turnId={TURN_ID}
        day="2026-09-29"
        selector={{ callId: "c1", action: "memory.search", ordinal: 0 }}
      />,
    );
    await flush();
    clickButton("llm · task_7");
    const entries = useInspectorStore.getState().entries;
    expect(entries).toHaveLength(1);
    expect(entries[0]!.key).toContain("trace:model:llm:task_7");
  });
});

// ---------------------------------------------------------------------------
// JobPanel
// ---------------------------------------------------------------------------

describe("JobPanel", () => {
  it("renders the owner projection and pages output on demand", async () => {
    endpoint.get(`/v2/turns/${TURN_ID}/jobs/job_1`, () =>
      jsonResponse(structuredClone(jobDetailFixture)),
    );
    endpoint.get(`/v2/turns/${TURN_ID}/jobs/job_1/output`, (request) => {
      if (queryOf(request, "continuation") === null) {
        return jsonResponse(structuredClone(jobOutputFixture));
      }
      return jsonResponse({
        job_id: "job_1",
        items: [{ channel: "stdout", text: "more\n" }],
        next_continuation: "continuation_3",
        truncated: false,
        result_locators: [],
      });
    });
    render(<JobPanel epoch={epoch} turnId={TURN_ID} day="2026-09-29" jobId="job_1" />);
    await flush();

    const text = container.textContent ?? "";
    expect(text).toContain("job_1");
    expect(text).toContain("running");
    expect(text).toContain("execution.process");
    expect(text).toContain("ready");
    expect(text).toContain("workspace:jobs/job_1/logs/stdout.log");
    // stderr stays its own channel, collapsed until asked.
    const stderrChannel = Array.from(container.querySelectorAll("button")).find(
      (button) => button.textContent?.trim().startsWith("stderr7 chars") ||
        button.textContent?.trim() === "stderr",
    );
    expect(stderrChannel).toBeDefined();
    act(() => {
      stderrChannel!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    await flush();
    expect(container.textContent).toContain("notice");

    clickButton("Show more output");
    await flush();
    expect(queryOf(endpoint.calls(`/v2/turns/${TURN_ID}/jobs/job_1/output`)[1]!, "continuation")).toBe("continuation_2");
    expect(container.textContent).toContain("more");
  });
});

// ---------------------------------------------------------------------------
// entries
// ---------------------------------------------------------------------------

describe("trace entries", () => {
  it("openTurnProcess replaces the inspector stack", () => {
    serveEvents([]);
    act(() => openTurnProcess(epoch, TURN_ID, "2026-09-29"));
    const entries = useInspectorStore.getState().entries;
    expect(entries).toHaveLength(1);
    expect(entries[0]!.key).toBe("trace:process:contract-turn");
  });

  it("pushActionDetail and pushJobDetail stack entries", () => {
    act(() => {
      pushActionDetail(epoch, TURN_ID, "2026-09-29", {
        callId: "c1",
        action: "workspace.read",
        ordinal: 0,
      });
      pushJobDetail(epoch, TURN_ID, "2026-09-29", "job_1");
    });
    const entries = useInspectorStore.getState().entries;
    expect(entries).toHaveLength(2);
    expect(entries[0]!.key).toContain("trace:action:contract-turn:c1");
    expect(entries[1]!.key).toContain("trace:job:contract-turn:job_1");
  });
});
