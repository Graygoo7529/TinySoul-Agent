// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { useConnectionStore } from "../../store/connectionStore";
import { useInspectorStore } from "../../store/inspectorStore";
import type { InspectorEntry } from "../../components/inspector";
import {
  errorResponse,
  FakeEndpoint,
  jsonResponse,
  makeStatus,
  queryOf,
  resetAppStores,
  wireConnectedStores,
} from "../../app/testing";
import { ContextInspectPanel } from "./ContextInspectPanel";

import tracePageFixture from "../../../test/fixtures/contracts/context-trace-page.json";

(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;

const TURN_ID = "contract-turn";
const TRACE_REF = `turn:trace@${TURN_ID}`;

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

function topEntry(): InspectorEntry {
  const list = useInspectorStore.getState().entries;
  const top = list[list.length - 1];
  if (top === undefined) throw new Error("inspector stack is empty");
  return top;
}

function renderTop() {
  const entry = topEntry();
  act(() => {
    root.render(<>{entry.render()}</>);
  });
}

function inspectCalls() {
  return endpoint.calls(`/v2/turns/${TURN_ID}/context/inspect`);
}

function renderInspect(canQuery = false) {
  act(() => {
    root.render(
      <ContextInspectPanel
        epoch={epoch}
        turnId={TURN_ID}
        targetRef={TRACE_REF}
        canQuery={canQuery}
      />,
    );
  });
}

describe("ContextInspectPanel", () => {
  it("reads the live disclosure of the original ref, bound to the turn", async () => {
    endpoint.get(`/v2/turns/${TURN_ID}/context/inspect`, () =>
      jsonResponse(structuredClone(tracePageFixture)),
    );
    renderInspect(true);
    await flush();

    expect(inspectCalls()).toHaveLength(1);
    expect(queryOf(inspectCalls()[0]!, "ref")).toBe(TRACE_REF);
    // Trace children render in order with their clues.
    const text = container.textContent ?? "";
    expect(text).toContain("decision");
    expect(text).toContain("action_result");
    expect(text).toContain("phase_note");
    expect(text.indexOf("execution.start")).toBeGreaterThanOrEqual(0);
    expect(text.indexOf("execution.start")).toBeLessThan(text.indexOf("core.ask"));
    // UI inspect is user-side reading: no write requests at all.
    expect(endpoint.requests.every((request) => request.method === "GET")).toBe(
      true,
    );
  });

  it("expands a child node into its own ref page (back returns to the parent)", async () => {
    endpoint.get(`/v2/turns/${TURN_ID}/context/inspect`, (request) => {
      const ref = queryOf(request, "ref");
      if (ref === `${TRACE_REF}#entry/trace_1`) {
        return jsonResponse({
          ref,
          kind: "context_trace_entry",
          items: [{ kind: "detail", value: "entry body" }],
        });
      }
      return jsonResponse(structuredClone(tracePageFixture));
    });
    renderInspect(true);
    await flush();

    const childButton = Array.from(
      container.querySelectorAll("button"),
    ).find((button) => button.textContent?.includes("decision"));
    expect(childButton).toBeDefined();
    act(() => {
      childButton!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(topEntry().key).toContain(
      `context:inspect:${TURN_ID}:${TRACE_REF}#entry/trace_1`,
    );

    renderTop();
    await flush();
    expect(inspectCalls()).toHaveLength(2);
    expect(queryOf(inspectCalls()[1]!, "ref")).toBe(`${TRACE_REF}#entry/trace_1`);
    expect(container.textContent).toContain("entry body");
  });

  it("offers locate-in-scope only with the query capability", async () => {
    endpoint.get(`/v2/turns/${TURN_ID}/context/inspect`, () =>
      jsonResponse(structuredClone(tracePageFixture)),
    );
    renderInspect(false);
    await flush();
    expect(container.querySelector("input")).toBeNull();

    renderInspect(true);
    await flush();
    const input = container.querySelector("input");
    expect(input).not.toBeNull();
    act(() => {
      const setter = Object.getOwnPropertyDescriptor(
        window.HTMLInputElement.prototype,
        "value",
      )!.set!;
      setter.call(input, "execution.start");
      input!.dispatchEvent(new Event("input", { bubbles: true }));
    });
    const form = container.querySelector("form")!;
    act(() => {
      form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    });
    renderTop();
    await flush();
    const withQuery = inspectCalls().find(
      (request) => queryOf(request, "query") === "execution.start",
    );
    expect(withQuery).toBeDefined();
    expect(queryOf(withQuery!, "ref")).toBe(TRACE_REF);
  });

  it("pages with continuation and stops on 409 context.unavailable", async () => {
    endpoint.get(`/v2/turns/${TURN_ID}/context/inspect`, (request) => {
      if (queryOf(request, "continuation") === null) {
        return jsonResponse({
          ref: TRACE_REF,
          kind: "context_trace",
          items: [
            { kind: "child", ref: `${TRACE_REF}#entry/a`, title: "first", clue: "" },
          ],
          next_continuation: "tok-1",
        });
      }
      return errorResponse(409, "context.unavailable");
    });
    renderInspect();
    await flush();
    expect(container.textContent).toContain("first");

    const more = Array.from(container.querySelectorAll("button")).find(
      (button) => button.textContent?.includes("Show more"),
    )!;
    act(() => {
      more.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    await flush();
    expect(container.textContent).toContain("last captured view");
    expect(container.textContent).toContain("first");
    expect(inspectCalls()).toHaveLength(2);
    expect(container.textContent).not.toContain("Show more");
  });

  it("marks the page refreshable on turn activity without disturbing content", async () => {
    endpoint.get(`/v2/turns/${TURN_ID}/context/inspect`, () =>
      jsonResponse(structuredClone(tracePageFixture)),
    );
    renderInspect();
    await flush();
    expect(container.textContent).not.toContain("refresh to see the latest");
    act(() => {
      useConnectionStore
        .getState()
        .applyStatus(
          epoch,
          makeStatus({ activity: "user_turn", activeTurnId: TURN_ID }),
        );
    });
    expect(container.textContent).toContain("refresh to see the latest");
    expect(container.textContent).toContain("decision");
  });
});
