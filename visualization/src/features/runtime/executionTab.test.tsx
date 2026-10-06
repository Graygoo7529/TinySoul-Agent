// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import {
  FakeEndpoint,
  jsonResponse,
  makeStatus,
  resetAppStores,
  runningSnapshot,
  wireConnectedStores,
} from "../../app/testing";
import { useConnectionStore } from "../../store/connectionStore";
import { ExecutionTab } from "./executionTab";
import type { ActiveTurnRead } from "./overview";

(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;

const ACTIVE_TURN = "turn_active_1";
const QUEUED_A = "turn_queued_a";
const QUEUED_B = "turn_queued_b";

let container: HTMLDivElement;
let root: Root;
let endpoint: FakeEndpoint;
let epoch: number;

function makeRead(state: string, overrides: Record<string, unknown> = {}): ActiveTurnRead {
  const snapshot = {
    ...runningSnapshot(ACTIVE_TURN),
    state,
    ...overrides,
  };
  return { turnId: ACTIVE_TURN, snapshot, error: null, settled: true };
}

beforeEach(() => {
  resetAppStores();
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  endpoint = new FakeEndpoint();
  ({ epoch } = wireConnectedStores(
    endpoint,
    makeStatus({ activeTurnId: ACTIVE_TURN, queuedTurnIds: [QUEUED_A, QUEUED_B] }),
  ));
  endpoint.post(`/v2/requests/${QUEUED_A}/cancel`, () =>
    jsonResponse({ accepted: true, turn_id: QUEUED_A }),
  );
  endpoint.post(`/v2/requests/${QUEUED_B}/cancel`, () =>
    jsonResponse({ accepted: true, turn_id: QUEUED_B }),
  );
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  resetAppStores();
});

async function renderTab(read: ActiveTurnRead): Promise<void> {
  await act(async () => {
    root.render(<ExecutionTab epoch={epoch} read={read} />);
  });
}

async function flush(rounds = 8): Promise<void> {
  for (let index = 0; index < rounds; index += 1) {
    await act(async () => {});
  }
}

function cancelButtons(): HTMLButtonElement[] {
  return Array.from(container.querySelectorAll("button")).filter((button) =>
    button.textContent?.includes("Cancel"),
  ) as HTMLButtonElement[];
}

describe("ExecutionTab", () => {
  it("cancels exactly the queued turn its row names — never the running one", async () => {
    await renderTab(makeRead("running"));
    await flush();

    const buttons = cancelButtons();
    expect(buttons).toHaveLength(2);
    await act(async () => buttons[0].click());
    await flush();

    expect(endpoint.calls(`/v2/requests/${QUEUED_A}/cancel`, "POST")).toHaveLength(1);
    expect(endpoint.calls(`/v2/requests/${QUEUED_B}/cancel`, "POST")).toHaveLength(0);
    expect(endpoint.calls(`/v2/requests/${ACTIVE_TURN}/cancel`, "POST")).toHaveLength(0);
  });

  it("shows the real wait reason with the way back to the conversation", async () => {
    await renderTab(
      makeRead("waiting", {
        wait_reason: "budget",
        budget_request: { request_id: "budget_1", next_cycle_index: 3 },
      }),
    );
    await flush();

    expect(container.textContent).toContain("waiting for a budget grant");
    expect(container.textContent).toContain("cycle 3 needs a grant");
    expect(container.textContent).toContain("Open in conversation");
  });

  it("keeps an execution failure apart from after-finish diagnostics", async () => {
    await renderTab(
      makeRead("finished", {
        result: {
          turn_id: ACTIVE_TURN,
          active_day: "2026-09-29",
          status: "failed",
          output: null,
          completion: null,
          failure: { kind: "turn.budget_exhausted" },
          finish_failures: [{ kind: "session.commit_failed" }],
          cleanup: [],
        },
      }),
    );
    await flush();

    expect(container.textContent).toContain("Execution failure");
    expect(container.textContent).toContain("Finish and cleanup diagnostics");
    // The failure body is open; the after-finish diagnostics stay collapsed
    // until asked for — related, but never one merged red box.
    expect(container.textContent).toContain("turn.budget_exhausted");
    expect(container.textContent).not.toContain("session.commit_failed");

    const header = Array.from(container.querySelectorAll("button")).find(
      (button) => button.textContent?.includes("Finish and cleanup diagnostics"),
    );
    await act(async () => (header as HTMLButtonElement).click());
    expect(container.textContent).toContain("Raised while finishing");
  });

  it("shows the empty state without an active turn, keeping the queue", async () => {
    useConnectionStore.setState((state) => ({
      status: state.status === null
        ? null
        : {
            ...state.status,
            runtime: { ...state.status.runtime, active_turn_id: null },
          },
    }));
    await renderTab({ turnId: null, snapshot: null, error: null, settled: true });
    await flush();

    expect(container.textContent).toContain("No turn is running");
    expect(container.textContent).toContain("Queued turns");
    expect(cancelButtons()).toHaveLength(2);
  });
});
