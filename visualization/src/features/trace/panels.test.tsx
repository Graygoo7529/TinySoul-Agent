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
const PHASE1 = { level: "phase", name: "phase1" };
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

/** Expand one phase card by its phase token (rendered as a row-end marker). */
function clickPhase(phase: string) {
  const target = container.querySelector(`button[data-phase="${phase}"]`);
  if (target === null) throw new Error(`phase "${phase}" not found`);
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
      event("llm.model.request", 3, { task_id: "t2", provenance: [{ refs: ["home:mount/domain/home"] }] }, [TURN, CYCLE, PHASE2]),
      event("context.control.applied", 4, { operation: "set_milestone", details: {
        content: "Found the relevant document\nIts section on testing explains the decision.",
      } }, [TURN, CYCLE, phase]),
    ];
    render(<ActivityTimeline events={events} turnId={TURN_ID} epoch={epoch} day={null} />);
    expect(container.textContent).toContain("Selected domains");
    // Phase group headers show in the unfiltered view…
    expect(container.textContent).toContain("更新语境");
    expect(container.textContent).toContain("规划动作");
    clickButton("Thinking");
    // …and disappear under a single-kind filter.
    expect(container.textContent).not.toContain("更新语境");
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
    expect(container.textContent).toContain("Selected domains");
    const intentButton = Array.from(container.querySelectorAll("button")).find((button) => button.textContent?.includes("Second intent"));
    expect(intentButton?.parentElement?.textContent).not.toContain("Selected domains");
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
      params: { ref: "workspace:a.md" },
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
      payload: { ref: "workspace:a.md", text: "hi" },
    }, [TURN, CYCLE, PHASE3]),
    event("action.call", 30, {
      call_id: "c2",
      action: "execution.run",
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
    // The process tree lives on the 过程 tab.
    clickButton("过程");

    expect(queryOf(endpoint.calls("/v2/events")[0]!, "turn_id")).toBe(TURN_ID);
    expect(queryOf(endpoint.calls("/v2/events")[0]!, "mode")).toBe("model");
    clickPhase("phase3");
    const text = container.textContent ?? "";
    expect(text).toContain("Cycle 1");
    expect(text).toContain("workspace.read");
    expect(text).toContain("success");
    expect(text).toContain("execution.run");
    // The expanded phase shows the action's result gist inline (payload text).
    expect(text).toContain("hi");
    // A not-executed action is shown as such — never as a tool answer.
    expect(text).toContain("not executed");
  });

  it("renders the overview metric band (elapsed, tokens, failure jump)", async () => {
    serveEvents([
      event("loop.phase.started", 10, { phase: "phase1" }, [TURN, CYCLE, PHASE1]),
      event("llm.task.started", 20, { task_id: "t1", consumer: "loop.phase1", target: "default", profile: "control" }, [TURN, CYCLE, PHASE1]),
      event("llm.model.response", 30, { task_id: "t1", usage: { input_tokens: 100, output_tokens: 5 } }, [TURN, CYCLE, PHASE1]),
      event("action.result", 40, {
        result_id: "r1", call_id: "c1", action: "workspace.read", status: "failed",
        stage: "execution", sequence: 1, domain: "workspace", invoke_id: "invoke_c1",
        batch_id: "b1", failure: { reason: "execution_failed", feedback: "boom" }, payload: null,
      }, [TURN, CYCLE, PHASE3]),
      event("loop.phase.completed", 60, { phase: "phase1" }, [TURN, CYCLE, PHASE1]),
    ]);
    render(<ProcessPanel epoch={epoch} turnId={TURN_ID} day="2026-09-29" />);
    await flush();
    // Elapsed from first phase start to last finish (10 → 60).
    expect(container.textContent).toContain("总耗时");
    expect(container.textContent).toContain("50s");
    // Tokens summed over retained usages (100 + 5).
    expect(container.textContent).toContain("105");
    const failButton = Array.from(container.querySelectorAll("button")).find(
      (button) => button.textContent?.includes("1 个失败"),
    );
    expect(failButton).toBeDefined();
    act(() => {
      failButton!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
  });

  it("pushes the action detail from a process row", async () => {
    serveEvents(processEvents);
    render(<ProcessPanel epoch={epoch} turnId={TURN_ID} day="2026-09-29" />);
    await flush();
    clickButton("过程");
    clickPhase("phase3");
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
        params: { ref: "workspace:a.md", content: "v1" },
      }, [TURN, CYCLE, PHASE2]),
      event("action.call", 20, {
        call_id: "c2", action: "workspace.write", domain: "workspace", sequence: 2,
        params: { ref: "workspace:b.md", content: "v2" },
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

  it("renders analysis intent, actual sources and the Markdown report", async () => {
    serveEvents([
      event("action.call", 10, {
        call_id: "c1", action: "workspace.analyze", domain: "workspace", sequence: 1,
        params: { intent: "核对容量恢复边界", references: ["workspace:src/context.ts"] },
      }, [TURN, CYCLE, PHASE2]),
      event("action.result", 20, {
        result_id: "r1", call_id: "c1", action: "workspace.analyze",
        status: "success", stage: "execution", sequence: 1, domain: "workspace",
        invoke_id: "invoke_c1", batch_id: "b1", failure: null,
        payload: {
          intent: "核对容量恢复边界",
          answer: "# 容量恢复分析\n\n## 结论\n\n先回收 **Context**，再重建 `MessageStack`。",
          sources: [{ ref: "workspace:src/context.ts", size: 1200 }],
          coverage: { complete: true, files_loaded: 1, source_chars: 1200 },
        },
      }, [TURN, CYCLE, PHASE3]),
    ]);
    render(
      <ActionDetailPanel epoch={epoch} turnId={TURN_ID} day="2026-09-29"
        selector={{ callId: "c1", action: "workspace.analyze", ordinal: 0 }} />,
    );
    await flush();
    expect(container.textContent).toContain("规划输入");
    expect(container.textContent).toContain("执行结果");
    expect(container.textContent).toContain("核对容量恢复边界");
    expect(container.querySelector(".md-body h1")?.textContent).toBe("容量恢复分析");
    expect(container.querySelector(".md-body strong")?.textContent).toBe("Context");
    expect(container.querySelector(".md-body code")?.textContent).toBe("MessageStack");
    expect(container.textContent).toContain("报告引用（1）");
    expect(container.textContent).toContain("1,200 source chars");
  });

  it("shows describe output as text without fabricating compose narrative", async () => {
    serveEvents([
      event("action.call", 10, {
        call_id: "c1", action: "workspace.describe", domain: "workspace", sequence: 1,
        params: { target_ref: "workspace:docs/context.md", instruction: "说明职责" },
      }, [TURN, CYCLE, PHASE2]),
      event("action.result", 20, {
        result_id: "r1", call_id: "c1", action: "workspace.describe",
        status: "success", stage: "execution", sequence: 1, domain: "workspace",
        invoke_id: "invoke_c1", batch_id: "b1", failure: null,
        payload: { ref: "workspace:docs/context.md", description: "记录 Context 的装配与恢复职责。" },
      }, [TURN, CYCLE, PHASE3]),
    ]);
    render(
      <ActionDetailPanel epoch={epoch} turnId={TURN_ID} day="2026-09-29"
        selector={{ callId: "c1", action: "workspace.describe", ordinal: 0 }} />,
    );
    await flush();
    expect(container.textContent).toContain("资源描述");
    expect(container.textContent).toContain("记录 Context 的装配与恢复职责。");

    serveEvents([
      event("action.call", 30, {
        call_id: "c2", action: "workspace.compose", domain: "workspace", sequence: 1,
        params: { target_ref: "workspace:reports/weekly.md", instruction: "汇总本周结果" },
      }, [TURN, CYCLE, PHASE2]),
      event("action.result", 40, {
        result_id: "r2", call_id: "c2", action: "workspace.compose",
        status: "success", stage: "execution", sequence: 1, domain: "workspace",
        invoke_id: "invoke_c2", batch_id: "b1", failure: null,
        payload: {
          ref: "workspace:reports/weekly.md", kind: "text", media_type: "text/markdown",
          size: 8420, description: "产物元数据，不是生成正文",
        },
      }, [TURN, CYCLE, PHASE3]),
    ]);
    render(
      <ActionDetailPanel epoch={epoch} turnId={TURN_ID} day="2026-09-29"
        selector={{ callId: "c2", action: "workspace.compose", ordinal: 0 }} />,
    );
    await flush();
    expect(container.textContent).toContain("汇总本周结果");
    expect(container.textContent).toContain("workspace:reports/weekly.md");
    expect(container.textContent).not.toContain("产物元数据，不是生成正文");
    expect(container.querySelector(".md-body")).toBeNull();
  });

  it("renders search sources and fetch extraction facts in web result cards", async () => {
    serveEvents([
      event("action.call", 10, {
        call_id: "c1", action: "web.search_by_kimi", domain: "web", sequence: 1,
        params: { query: "Context recovery" },
      }, [TURN, CYCLE, PHASE2]),
      event("action.result", 20, {
        result_id: "r1", call_id: "c1", action: "web.search_by_kimi",
        status: "success", stage: "execution", sequence: 1, domain: "web",
        invoke_id: "invoke_c1", batch_id: "b1", failure: null,
        payload: {
          answer: "Context owner drives recovery.", result_count: 1,
          results: [{ title: "Context design", url: "https://example.com/context", snippet: "Slots and recovery" }],
          untrusted_external_content: true,
        },
      }, [TURN, CYCLE, PHASE3]),
    ]);
    render(
      <ActionDetailPanel epoch={epoch} turnId={TURN_ID} day="2026-09-29"
        selector={{ callId: "c1", action: "web.search_by_kimi", ordinal: 0 }} />,
    );
    await flush();
    expect(container.textContent).toContain("Context owner drives recovery.");
    expect(container.textContent).toContain("Context design");
    expect(container.textContent).toContain("Slots and recovery");
    expect(container.textContent).toContain("https://example.com/context");

    serveEvents([
      event("action.call", 30, {
        call_id: "c2", action: "web.fetch_with_defuddle", domain: "web", sequence: 1,
        params: { url: "https://example.com/guide", target_ref: "workspace:web/guide.md" },
      }, [TURN, CYCLE, PHASE2]),
      event("action.result", 40, {
        result_id: "r2", call_id: "c2", action: "web.fetch_with_defuddle",
        status: "success", stage: "execution", sequence: 1, domain: "web",
        invoke_id: "invoke_c2", batch_id: "b1", failure: null,
        payload: {
          extractor: "defuddle", title: "Recovery guide", excerpt: "Bounded content is reclaimed.",
          content_chars: 18420, markdown_ref: "workspace:web/guide.md", untrusted_external_content: true,
        },
      }, [TURN, CYCLE, PHASE3]),
    ]);
    render(
      <ActionDetailPanel epoch={epoch} turnId={TURN_ID} day="2026-09-29"
        selector={{ callId: "c2", action: "web.fetch_with_defuddle", ordinal: 0 }} />,
    );
    await flush();
    expect(container.textContent).toContain("defuddle");
    expect(container.textContent).toContain("18,420 字符");
    expect(container.textContent).toContain("Recovery guide");
    expect(container.textContent).toContain("Bounded content is reclaimed.");
    expect(container.textContent).toContain("原始页面");
    expect(container.textContent).toContain("workspace:web/guide.md");
  });

  it("renders discovery counts, page states and failure reasons in the detail card", async () => {
    serveEvents([
      event("action.call", 10, {
        call_id: "c1", action: "web.discover_pages", domain: "web", sequence: 1,
        params: { start_url: "https://example.com/docs/", max_visit_depth: 2 },
      }, [TURN, CYCLE, PHASE2]),
      event("action.result", 20, {
        result_id: "r1", call_id: "c1", action: "web.discover_pages",
        status: "success", stage: "execution", sequence: 1, domain: "web",
        invoke_id: "invoke_c1", batch_id: "b1", failure: null,
        payload: {
          source: { title: "Example docs", url: "https://example.com/docs/" },
          page_count: 3, visited_count: 1, failed_count: 1, candidate_count: 1,
          skipped_count: 0, stop_reason: "completed",
          pages: [
            { title: "Getting started", state: "visited", url: "https://example.com/docs/start" },
            { title: "Advanced setup", state: "failed", failure_reason: "request timeout", url: "https://example.com/docs/advanced" },
            { anchor_text: "API reference", state: "candidate", url: "https://example.com/docs/api" },
          ],
          untrusted_external_content: true,
        },
      }, [TURN, CYCLE, PHASE3]),
    ]);
    render(
      <ActionDetailPanel epoch={epoch} turnId={TURN_ID} day="2026-09-29"
        selector={{ callId: "c1", action: "web.discover_pages", ordinal: 0 }} />,
    );
    await flush();
    expect(container.textContent).toContain("Example docs");
    expect(container.textContent).toContain("3 页");
    expect(container.textContent).toContain("1 已访问");
    expect(container.textContent).toContain("1 失败");
    expect(container.textContent).toContain("1 候选");
    expect(container.textContent).toContain("stop: completed");
    expect(container.textContent).toContain("request timeout");
    expect(container.textContent).toContain("API reference");
  });

  it("renders workspace.read line numbers only when an actual or requested start exists", async () => {
    serveEvents([
      event("action.call", 10, {
        call_id: "c1", action: "workspace.read", domain: "workspace", sequence: 1,
        params: { ref: "workspace:src/context.ts", start_line: 120, end_line: 140 },
      }, [TURN, CYCLE, PHASE2]),
      event("action.result", 20, {
        result_id: "r1", call_id: "c1", action: "workspace.read",
        status: "success", stage: "execution", sequence: 1, domain: "workspace",
        invoke_id: "invoke_c1", batch_id: "b1", failure: null,
        payload: {
          ref: "workspace:src/context.ts",
          requested: { start_line: 120, end_line: 140, cursor: 0, max_chars: 4000 },
          actual: { start: { line: 120, column: 1 }, end: { line: 126, column: 48 } },
          text: "alpha\nbeta", truncated: true,
        },
      }, [TURN, CYCLE, PHASE3]),
    ]);
    render(
      <ActionDetailPanel epoch={epoch} turnId={TURN_ID} day="2026-09-29"
        selector={{ callId: "c1", action: "workspace.read", ordinal: 0 }} />,
    );
    await flush();
    expect([...container.querySelectorAll("[data-line-number]")].map((node) => node.textContent))
      .toEqual(["120", "121"]);

    serveEvents([
      event("action.call", 30, {
        call_id: "c2", action: "workspace.read", domain: "workspace", sequence: 1,
        params: { ref: "workspace:src/context.ts", start_line: 42 },
      }, [TURN, CYCLE, PHASE2]),
      event("action.result", 40, {
        result_id: "r2", call_id: "c2", action: "workspace.read",
        status: "success", stage: "execution", sequence: 1, domain: "workspace",
        invoke_id: "invoke_c2", batch_id: "b1", failure: null,
        payload: {
          ref: "workspace:src/context.ts", requested: { start_line: 42 },
          actual: null, text: "first\nsecond",
        },
      }, [TURN, CYCLE, PHASE3]),
    ]);
    render(
      <ActionDetailPanel epoch={epoch} turnId={TURN_ID} day="2026-09-29"
        selector={{ callId: "c2", action: "workspace.read", ordinal: 0 }} />,
    );
    await flush();
    expect([...container.querySelectorAll("[data-line-number]")].map((node) => node.textContent))
      .toEqual(["42", "43"]);

    serveEvents([
      event("action.call", 50, {
        call_id: "c3", action: "workspace.read", domain: "workspace", sequence: 1,
        params: { ref: "workspace:src/context.ts" },
      }, [TURN, CYCLE, PHASE2]),
      event("action.result", 60, {
        result_id: "r3", call_id: "c3", action: "workspace.read",
        status: "success", stage: "execution", sequence: 1, domain: "workspace",
        invoke_id: "invoke_c3", batch_id: "b1", failure: null,
        payload: { ref: "workspace:src/context.ts", text: "plain text" },
      }, [TURN, CYCLE, PHASE3]),
    ]);
    render(
      <ActionDetailPanel epoch={epoch} turnId={TURN_ID} day="2026-09-29"
        selector={{ callId: "c3", action: "workspace.read", ordinal: 0 }} />,
    );
    await flush();
    expect(container.querySelectorAll("[data-line-number]")).toHaveLength(0);
    expect(container.textContent).toContain("plain text");
  });
});

// ---------------------------------------------------------------------------
// JobPanel
// ---------------------------------------------------------------------------

describe("JobPanel", () => {
  it("renders the owner projection and pages output on demand", async () => {
    endpoint.get(`/v2/requests/${TURN_ID}/jobs/job_1`, () =>
      jsonResponse(structuredClone(jobDetailFixture)),
    );
    endpoint.get(`/v2/requests/${TURN_ID}/jobs/job_1/output`, (request) => {
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
    expect(queryOf(endpoint.calls(`/v2/requests/${TURN_ID}/jobs/job_1/output`)[1]!, "continuation")).toBe("continuation_2");
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
