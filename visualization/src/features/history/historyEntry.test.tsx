// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { SessionTurnSummary } from "../../api/v2/types";
import {
  FakeEndpoint,
  jsonResponse,
  makeInteractionsPage,
  makeStatus,
  resetAppStores,
  wireConnectedStores,
} from "../../app/testing";
import { useConnectionStore } from "../../store/connectionStore";
import { useInspectorStore } from "../../store/inspectorStore";
import { useTurnStore } from "../../store/turnStore";
import { TopBar } from "../../components/shell/TopBar";
import { ChatView } from "../chat/ChatView";
import { openSessionTurn, resetTurnController } from "../chat/turnController";

(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement;
let root: Root;
let endpoint: FakeEndpoint;
let epoch: number;

beforeEach(() => {
  // jsdom has no matchMedia; useReducedMotion subscribes to it.
  window.matchMedia = vi.fn().mockImplementation((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addEventListener: () => {},
    removeEventListener: () => {},
    addListener: () => {},
    removeListener: () => {},
    dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia;
  resetTurnController();
  resetAppStores();
  useInspectorStore.getState().close();
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  endpoint = new FakeEndpoint();
  epoch = wireConnectedStores(endpoint, makeStatus()).epoch;
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  resetTurnController();
  resetAppStores();
  useInspectorStore.getState().close();
});

function turnSummary(
  overrides: Partial<SessionTurnSummary> = {},
): SessionTurnSummary {
  return {
    turn_id: "t-old",
    ref: "session:turn/t-old",
    day: "2026-09-29",
    status: "answered",
    initial_input_excerpt: "Summarize the release plan",
    output_excerpt: "",
    question_count: 0,
    ...overrides,
  };
}

function buttonByText(text: string): HTMLButtonElement {
  const button = Array.from(container.querySelectorAll("button")).find(
    (candidate) => candidate.textContent?.includes(text),
  );
  if (!button) throw new Error(`button "${text}" not rendered`);
  return button as HTMLButtonElement;
}

/** Put a committed turn of the given day on screen as read-only history. */
async function openHistoryTurn(turnId: string, day: string) {
  endpoint.get(`/v2/session/turns/${turnId}`, () =>
    jsonResponse(
      makeInteractionsPage({
        ref: `session:turn/${turnId}`,
        turn_id: turnId,
        day,
      }),
    ),
  );
  await act(async () => {
    await openSessionTurn(epoch, turnId, day);
  });
  expect(useTurnStore.getState().historyView).toBe(true);
}

describe("history entries", () => {
  it("opens the day directory from the empty chat day list", async () => {
    useTurnStore.getState().setSessionTurns([]);
    await act(async () => {
      root.render(<ChatView />);
    });
    expect(container.textContent).toContain("Start a conversation");
    await act(async () => {
      buttonByText("Browse earlier days").click();
    });
    const entries = useInspectorStore.getState().entries;
    expect(entries).toHaveLength(1);
    expect(entries[0].key).toBe("history:days");
  });

  it("opens the day directory from the day list header", async () => {
    useTurnStore.getState().setSessionTurns([turnSummary()]);
    await act(async () => {
      root.render(<ChatView />);
    });
    expect(container.textContent).toContain("Today's conversations");
    await act(async () => {
      buttonByText("Earlier days").click();
    });
    const entries = useInspectorStore.getState().entries;
    expect(entries).toHaveLength(1);
    expect(entries[0].key).toBe("history:days");
  });

  it("opens the day directory from the top bar when connected", async () => {
    await act(async () => {
      root.render(<TopBar />);
    });
    const history = container.querySelector(
      'button[aria-label="History"]',
    ) as HTMLButtonElement;
    expect(history.disabled).toBe(false);
    await act(async () => {
      history.click();
    });
    const entries = useInspectorStore.getState().entries;
    expect(entries).toHaveLength(1);
    expect(entries[0].key).toBe("history:days");
  });

  it("keeps the top-bar history entry disabled while disconnected", async () => {
    resetAppStores();
    await act(async () => {
      root.render(<TopBar />);
    });
    const history = container.querySelector(
      'button[aria-label="History"]',
    ) as HTMLButtonElement;
    expect(history.disabled).toBe(true);
  });
});

describe("history banner", () => {
  it("notices the archived-day origin and opens the day's Session map", async () => {
    useConnectionStore
      .getState()
      .applyStatus(
        epoch,
        makeStatus({ activity: "user_turn", activeTurnId: "live-1" }),
      );
    await openHistoryTurn("t-old", "2026-09-28");
    await act(async () => {
      root.render(<ChatView />);
    });

    expect(container.textContent).toContain(
      "Read-only history · 2026-09-28 · archived day — current resources may differ",
    );
    // Another turn is live: the back action returns to it, not to a day list.
    expect(container.textContent).toContain("Back to the live turn");

    await act(async () => {
      buttonByText("Session map").click();
    });
    const entries = useInspectorStore.getState().entries;
    expect(entries).toHaveLength(1);
    expect(entries[0].key).toBe("session-map:2026-09-28");
  });

  it("offers the plain way back to today on the active day", async () => {
    endpoint.get("/v2/session/turns", () =>
      jsonResponse({ day: "2026-09-29", items: [], next_continuation: null }),
    );
    await openHistoryTurn("t-today", "2026-09-29");
    await act(async () => {
      root.render(<ChatView />);
    });

    expect(container.textContent).toContain("Read-only history · 2026-09-29");
    expect(container.textContent).not.toContain("archived day");

    await act(async () => {
      buttonByText("Back to today").click();
    });
    expect(useTurnStore.getState().turnId).toBeNull();
    expect(container.textContent).toContain("Start a conversation");
  });
});
