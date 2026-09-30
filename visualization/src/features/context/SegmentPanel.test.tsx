// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import type { ContextOverview, SegmentView } from "../../api/v2/types";
import { useAppStore } from "../../store/appStore";
import { useInspectorStore } from "../../store/inspectorStore";
import {
  errorResponse,
  FakeEndpoint,
  jsonResponse,
  makeStatus,
  queryOf,
  resetAppStores,
  wireConnectedStores,
} from "../../app/testing";
import { SegmentPanel, type SegmentContext } from "./SegmentPanel";

import overviewFixture from "../../../test/fixtures/contracts/context-overview.json";
import messagesFixture from "../../../test/fixtures/contracts/context-messages.json";

(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;

const overview = overviewFixture as ContextOverview;
const TURN_ID = "contract-turn";

let container: HTMLDivElement;
let root: Root;
let endpoint: FakeEndpoint;
let epoch: number;

beforeEach(() => {
  resetAppStores();
  useInspectorStore.setState({ entries: [] });
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  endpoint = new FakeEndpoint();
  epoch = wireConnectedStores(
    endpoint,
    makeStatus({ activity: "user_turn", activeTurnId: TURN_ID }),
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

function segmentOf(id: string): SegmentView {
  const found = overview.segments.find((entry) => entry.id === id);
  if (found === undefined) throw new Error(`fixture segment ${id} missing`);
  return structuredClone(found);
}

function contextFor(): SegmentContext {
  return {
    day: overview.day ?? null,
    resolvedReferences: overview.resolved_references,
    closed: false,
  };
}

function serveSegment(id: string, body: unknown) {
  endpoint.get(`/v2/turns/${TURN_ID}/context/segments/${id}`, () =>
    jsonResponse(body),
  );
}

async function renderSegment(id: string) {
  serveSegment(id, structuredClone(messagesFixture));
  act(() => {
    root.render(
      <SegmentPanel
        epoch={epoch}
        turnId={TURN_ID}
        segment={segmentOf(id)}
        context={contextFor()}
      />,
    );
  });
  await flush();
}

function clickText(text: string) {
  const target = Array.from(container.querySelectorAll("button")).find(
    (button) => button.textContent?.includes(text),
  );
  if (target === undefined) throw new Error(`button "${text}" not found`);
  act(() => {
    target.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  });
}

function segmentCalls(id: string) {
  return endpoint.calls(`/v2/turns/${TURN_ID}/context/segments/${id}`);
}

describe("SegmentPanel body", () => {
  it("renders installed messages with role/label and the message index", async () => {
    await renderSegment("inputs");
    expect(container.textContent).toContain(
      "Run the prepared job and ask before proceeding",
    );
    expect(container.textContent).toContain("#2");
    expect(container.textContent).toContain("user");
    expect(container.textContent).toContain("user_input");
    // Every request this panel makes is a read.
    expect(endpoint.requests.every((request) => request.method === "GET")).toBe(
      true,
    );
  });

  it("pages the body with the returned continuation", async () => {
    const first = {
      turn_id: TURN_ID,
      segment_id: "inputs",
      messages: [
        {
          message_index: 0,
          message: { role: "system", parts: [{ type: "text", text: "page one" }] },
        },
      ],
      next_continuation: "tok-1",
    };
    const second = {
      turn_id: TURN_ID,
      segment_id: "inputs",
      messages: [
        {
          message_index: 1,
          message: { role: "user", parts: [{ type: "text", text: "page two" }] },
        },
      ],
    };
    serveSegment("inputs", first);
    act(() => {
      root.render(
        <SegmentPanel
          epoch={epoch}
          turnId={TURN_ID}
          segment={segmentOf("inputs")}
          context={contextFor()}
        />,
      );
    });
    await flush();
    expect(container.textContent).toContain("page one");
    expect(container.textContent).not.toContain("page two");

    endpoint.get(`/v2/turns/${TURN_ID}/context/segments/inputs`, (request) => {
      void request;
      return jsonResponse(second);
    });
    clickText("Show more");
    await flush();
    expect(container.textContent).toContain("page two");
    expect(segmentCalls("inputs")).toHaveLength(2);
    expect(queryOf(segmentCalls("inputs")[1]!, "continuation")).toBe("tok-1");
  });

  it("assembles a canonical_json fragment across pages, delivered once", async () => {
    const longMessage = {
      message_index: 7,
      message: {
        role: "user",
        label: "assembled",
        parts: [{ type: "text", text: "fragment assembled body" }],
      },
    };
    const full = JSON.stringify(longMessage);
    const cut = Math.floor(full.length / 2);
    serveSegment("inputs", {
      turn_id: TURN_ID,
      segment_id: "inputs",
      messages: [
        {
          message_index: 0,
          message: { role: "system", parts: [{ type: "text", text: "regular" }] },
        },
      ],
      content_fragment: { encoding: "canonical_json", text: full.slice(0, cut) },
      next_continuation: "tok-f",
    });
    act(() => {
      root.render(
        <SegmentPanel
          epoch={epoch}
          turnId={TURN_ID}
          segment={segmentOf("inputs")}
          context={contextFor()}
        />,
      );
    });
    await flush();
    // The incomplete fragment is never rendered as body text.
    expect(container.textContent).toContain("regular");
    expect(container.textContent).not.toContain("fragment assembled body");

    endpoint.get(`/v2/turns/${TURN_ID}/context/segments/inputs`, () =>
      jsonResponse({
        turn_id: TURN_ID,
        segment_id: "inputs",
        messages: [],
        content_fragment: { encoding: "canonical_json", text: full.slice(cut) },
      }),
    );
    clickText("Show more");
    await flush();
    expect(
      container.textContent?.split("fragment assembled body").length,
    ).toBe(2); // exactly one occurrence
    expect(container.textContent).toContain("#7");
  });

  it("stops live reading on 409 context.unavailable, keeping the captured view", async () => {
    serveSegment("inputs", {
      turn_id: TURN_ID,
      segment_id: "inputs",
      messages: [
        {
          message_index: 0,
          message: { role: "system", parts: [{ type: "text", text: "kept" }] },
        },
      ],
      next_continuation: "tok-1",
    });
    act(() => {
      root.render(
        <SegmentPanel
          epoch={epoch}
          turnId={TURN_ID}
          segment={segmentOf("inputs")}
          context={contextFor()}
        />,
      );
    });
    await flush();

    endpoint.get(`/v2/turns/${TURN_ID}/context/segments/inputs`, () =>
      errorResponse(409, "context.unavailable"),
    );
    clickText("Show more");
    await flush();
    expect(container.textContent).toContain("last captured view");
    expect(container.textContent).toContain("kept");
    // No retry loop, no further reads, no load-more affordance.
    expect(segmentCalls("inputs")).toHaveLength(2);
    expect(container.textContent).not.toContain("Show more");
  });
});

describe("SegmentPanel shapes", () => {
  it("heap: partitions installed vs available refs and routes owner reads", async () => {
    await renderSegment("home");
    expect(container.textContent).toContain("home:agent@AGENT");
    expect(container.textContent).toContain("home:skills@tinysoul-docs");
    expect(container.textContent).toContain("installed");
    expect(container.textContent).toContain("available");
    // The heap declares select/reclaim only: no SELECT/RECLAIM controls.
    expect(container.textContent).not.toContain("SELECT");
    expect(container.textContent).not.toContain("RECLAIM");

    clickText("home:agent@AGENT");
    const entries = useInspectorStore.getState().entries;
    const top = entries[entries.length - 1];
    expect(top?.key).toContain("context:resource:home:agent@AGENT");
    expect(top?.subtitle).toBe("Owner's current content");
  });

  it("stack: root refs open the live inspect route for this turn", async () => {
    await renderSegment("trace");
    clickText(`turn:trace@${TURN_ID}`);
    const entries = useInspectorStore.getState().entries;
    const top = entries[entries.length - 1];
    expect(top?.key).toContain(`context:inspect:${TURN_ID}:turn:trace@${TURN_ID}`);
    expect(top?.copyText).toBe(`turn:trace@${TURN_ID}`);
  });

  it("state: the technical descriptor lives in the Details section", async () => {
    await renderSegment("inputs");
    expect(container.textContent).not.toContain("capabilities");
    clickText("Details");
    expect(container.textContent).toContain("capabilities");
    expect(container.textContent).toContain("read only");
    expect(container.textContent).toContain("46 chars");
  });

  it("working: the workspace segment links out to its owner page", async () => {
    await renderSegment("workspace");
    clickText("Open the Workspace page");
    expect(useAppStore.getState().activeTab).toBe("workspace");
    expect(useInspectorStore.getState().entries).toHaveLength(0);
  });

  it("working: the jobs segment links to runtime observation", async () => {
    await renderSegment("jobs");
    clickText("Open Runtime observation");
    expect(useAppStore.getState().activeTab).toBe("runtime");
  });
});
