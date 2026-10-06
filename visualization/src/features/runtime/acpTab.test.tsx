// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import type { JsonObject } from "../../api/v2/types";
import {
  FakeEndpoint,
  jsonResponse,
  makeStatus,
  resetAppStores,
  wireConnectedStores,
} from "../../app/testing";
import { useAppStore } from "../../store/appStore";
import { useComposerDraft } from "../chat/composerDraft";
import { AcpTab } from "./acpTab";

(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement;
let root: Root;
let endpoint: FakeEndpoint;
let epoch: number;

function directory(targets: JsonObject[], connections: JsonObject[]): JsonObject {
  return {
    generation_id: "generation_1",
    day: "2026-09-29",
    targets,
    connections,
  };
}

beforeEach(() => {
  resetAppStores();
  useComposerDraft.setState({ draft: "" });
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  endpoint = new FakeEndpoint();
  ({ epoch } = wireConnectedStores(endpoint, makeStatus({})));
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  resetAppStores();
});

async function renderTab(): Promise<void> {
  await act(async () => {
    root.render(<AcpTab epoch={epoch} />);
  });
}

async function flush(rounds = 8): Promise<void> {
  for (let index = 0; index < rounds; index += 1) {
    await act(async () => {});
  }
}

describe("AcpTab", () => {
  it("shows honest empty states and never connects", async () => {
    endpoint.get("/v2/subagent", () => jsonResponse(directory([], [])));
    await renderTab();
    await flush();

    expect(container.textContent).toContain("No subagent targets configured");
    expect(container.textContent).toContain("No live connections");
    expect(container.textContent).toContain("never connects");
    // One side-effect-free directory read; nothing else.
    expect(endpoint.calls("/v2/subagent")).toHaveLength(1);
    expect(endpoint.requests.filter((r) => r.method === "POST")).toHaveLength(0);
  });

  it("separates configured targets from live connections", async () => {
    endpoint.get("/v2/subagent", () =>
      jsonResponse(
        directory(
          [{ agent_id: "alpha", description: "Helper agent", enabled: true }],
          [
            {
              connection_id: "conn_1",
              agent_id: "alpha",
              cwd_ref: "",
              state: "ready",
              active_job_id: null,
              turn_id: null,
            },
            {
              connection_id: "conn_2",
              agent_id: "alpha",
              cwd_ref: "",
              state: "busy",
              active_job_id: "job_9",
              turn_id: "turn_other",
            },
          ],
        ),
      ),
    );
    await renderTab();
    await flush();

    expect(container.textContent).toContain("Configured targets");
    expect(container.textContent).toContain("Helper agent");
    expect(container.textContent).toContain("ready");
    expect(container.textContent).toContain("idle — reusable across turns");
    expect(container.textContent).toContain("busy");
    // A busy connection points at its delegation job.
    expect(container.textContent).toContain("job_9".slice(0, 8));
  });

  it("fills an editable conversation draft for a delegation, never sends", async () => {
    endpoint.get("/v2/subagent", () =>
      jsonResponse(
        directory(
          [{ agent_id: "alpha", description: "Helper agent", enabled: true }],
          [],
        ),
      ),
    );
    await renderTab();
    await flush();

    const delegate = Array.from(container.querySelectorAll("button")).find(
      (button) => button.textContent?.includes("Delegate in conversation"),
    );
    expect(delegate).toBeDefined();
    await act(async () => (delegate as HTMLButtonElement).click());

    expect(useComposerDraft.getState().draft).toContain("alpha");
    expect(useAppStore.getState().activeTab).toBe("chat");
    // The draft went nowhere near the wire.
    expect(endpoint.requests.filter((r) => r.method === "POST")).toHaveLength(0);
  });
});
