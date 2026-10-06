// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

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
import { OwnerResourcePanel } from "./OwnerResourcePanel";

import homeFixture from "../../../test/fixtures/contracts/home-effective.json";
import memoryFixture from "../../../test/fixtures/contracts/memory-document.json";

(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;

const TURN_ID = "contract-turn";
const DAY = "2026-09-29";

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

function resolveCalls() {
  return endpoint.calls("/v2/resources/resolve");
}

describe("OwnerResourcePanel", () => {
  it("resolves a home ref via API-18, then reads the owner's content with its view", async () => {
    endpoint.get("/v2/resources/resolve", () =>
      jsonResponse({
        kind: "home",
        locator: { ref: "home:top/agent/contract", view: "effective" },
        capabilities: ["read"],
      }),
    );
    endpoint.get("/v2/home/content", () =>
      jsonResponse(structuredClone(homeFixture)),
    );
    act(() => {
      root.render(
        <OwnerResourcePanel
          epoch={epoch}
          reference="home:top/agent/contract"
          turnId={TURN_ID}
          day={DAY}
        />,
      );
    });
    await flush();

    expect(resolveCalls()).toHaveLength(1);
    expect(queryOf(resolveCalls()[0]!, "ref")).toBe("home:top/agent/contract");
    // The drawer's turn/day travel as the resolution binding.
    expect(queryOf(resolveCalls()[0]!, "turn_id")).toBe(TURN_ID);
    expect(queryOf(resolveCalls()[0]!, "day")).toBe(DAY);

    const contentCalls = endpoint.calls("/v2/home/content");
    expect(contentCalls).toHaveLength(1);
    expect(queryOf(contentCalls[0]!, "ref")).toBe("home:top/agent/contract");
    expect(queryOf(contentCalls[0]!, "view")).toBe("effective");

    expect(container.textContent).toContain("Workspace guidance");
    expect(container.textContent).toContain("effective");
    // Clearly annotated: owner-current, not the installed snapshot.
    expect(container.textContent).toContain("not the snapshot installed");
    expect(endpoint.requests.every((request) => request.method === "GET")).toBe(
      true,
    );
  });

  it("uses the overview-resolved locator for dynamic memory refs without re-resolving", async () => {
    const memory = structuredClone(memoryFixture) as {
      metadata: { direct_refs: string[] };
    };
    memory.metadata.direct_refs = ["memory:concept/tinysoul"];
    endpoint.get("/v2/memory/document", () => jsonResponse(memory));
    act(() => {
      root.render(
        <OwnerResourcePanel
          epoch={epoch}
          reference="memory:current"
          turnId={TURN_ID}
          day={DAY}
          resolved={{ ref: "memory:current", day: DAY }}
        />,
      );
    });
    await flush();

    expect(resolveCalls()).toHaveLength(0);
    const documentCalls = endpoint.calls("/v2/memory/document");
    expect(documentCalls).toHaveLength(1);
    expect(queryOf(documentCalls[0]!, "ref")).toBe("memory:current");
    expect(container.textContent).toContain("Project notes");
    expect(container.textContent).toContain("entity");
    // Direct refs open as further owner reads.
    const row = Array.from(container.querySelectorAll("button")).find(
      (button) => button.textContent?.includes("memory:concept/tinysoul"),
    );
    expect(row).toBeDefined();
    act(() => {
      row!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    const entries = useInspectorStore.getState().entries;
    expect(entries[entries.length - 1]?.key).toContain(
      "context:resource:memory:concept/tinysoul",
    );
  });

  it("reports an unbound dynamic reference instead of substituting today", async () => {
    endpoint.get("/v2/resources/resolve", () =>
      errorResponse(422, "resource.unresolved_origin"),
    );
    act(() => {
      root.render(
        <OwnerResourcePanel
          epoch={epoch}
          reference="memory:latest"
          turnId={TURN_ID}
          day={DAY}
        />,
      );
    });
    await flush();

    expect(container.textContent).toContain("original binding");
    // No owner read is attempted for an unbound reference.
    expect(endpoint.calls("/v2/memory/document")).toHaveLength(0);
    expect(endpoint.calls("/v2/memory/active")).toHaveLength(0);
  });
});
