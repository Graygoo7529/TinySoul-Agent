// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import type { DayEntry, SessionTurnSummary } from "../../api/v2/types";
import {
  FakeEndpoint,
  jsonResponse,
  makeInteractionsPage,
  makeStatus,
  queryOf,
  resetAppStores,
  runningSnapshot,
  wireConnectedStores,
} from "../../app/testing";
import { useConnectionStore } from "../../store/connectionStore";
import { useInspectorStore } from "../../store/inspectorStore";
import { useTurnStore } from "../../store/turnStore";
import { resetTurnController } from "../chat/turnController";
import { DayListPanel } from "./DayListPanel";
import { DayTurnsPanel } from "./DayTurnsPanel";

(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement;
let root: Root;
let endpoint: FakeEndpoint;
let epoch: number;

beforeEach(() => {
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

function dayEntry(day: string, active = false): DayEntry {
  return { day, active };
}

function turnSummary(
  overrides: Partial<SessionTurnSummary> = {},
): SessionTurnSummary {
  return {
    turn_id: "t-old",
    ref: "session:turn/t-old",
    day: "2026-09-28",
    status: "answered",
    initial_input_excerpt: "Summarize the release plan",
    output_excerpt: "Here is the summary…",
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

async function renderAndSettle(element: React.ReactElement) {
  await act(async () => {
    root.render(element);
  });
}

describe("DayListPanel", () => {
  it("lists days with the active badge and continues with before=", async () => {
    endpoint.get("/v2/days", (request) => {
      if (queryOf(request, "before") === null) {
        return jsonResponse({
          items: [dayEntry("2026-09-29", true), dayEntry("2026-09-28")],
          next_before: "2026-09-28",
        });
      }
      return jsonResponse({
        items: [dayEntry("2026-09-27")],
        next_before: null,
      });
    });
    await renderAndSettle(<DayListPanel epoch={epoch} />);

    expect(container.textContent).toContain("2026-09-29");
    expect(container.textContent).toContain("2026-09-28");
    expect(container.textContent).toContain("active");
    const first = endpoint.calls("/v2/days");
    expect(first).toHaveLength(1);
    expect(queryOf(first[0], "limit")).toBe("30");
    expect(queryOf(first[0], "before")).toBeNull();

    await act(async () => {
      buttonByText("Show more").click();
    });
    expect(container.textContent).toContain("2026-09-27");
    const all = endpoint.calls("/v2/days");
    expect(all).toHaveLength(2);
    expect(queryOf(all[1], "before")).toBe("2026-09-28");
    // The exhausted sequence offers no further page.
    expect(container.textContent).not.toContain("Show more");
  });

  it("shows the distinct empty state when no day is recorded", async () => {
    endpoint.get("/v2/days", () =>
      jsonResponse({ items: [], next_before: null }),
    );
    await renderAndSettle(<DayListPanel epoch={epoch} />);
    expect(container.textContent).toContain("No recorded days yet");
  });

  it("pushes the day's turns; the map action opens the day's Session map", async () => {
    endpoint.get("/v2/days", () =>
      jsonResponse({ items: [dayEntry("2026-09-28")], next_before: null }),
    );
    await renderAndSettle(<DayListPanel epoch={epoch} />);

    await act(async () => {
      buttonByText("2026-09-28").click();
    });
    let entries = useInspectorStore.getState().entries;
    expect(entries).toHaveLength(1);
    expect(entries[0].key).toBe("history:day:2026-09-28");
    expect(entries[0].subtitle).toBe("Archived day · read-only");

    await act(async () => {
      (
        container.querySelector(
          'button[aria-label="Session map of this day"]',
        ) as HTMLButtonElement
      ).click();
    });
    entries = useInspectorStore.getState().entries;
    expect(entries).toHaveLength(1);
    expect(entries[0].key).toBe("session-map:2026-09-28");
  });
});

describe("DayTurnsPanel", () => {
  it("lists committed turns and opens one read-only in the chat view", async () => {
    endpoint.get("/v2/session/turns/t-old", () =>
      jsonResponse(
        makeInteractionsPage({
          ref: "session:turn/t-old",
          turn_id: "t-old",
          day: "2026-09-28",
        }),
      ),
    );
    endpoint.get("/v2/session/turns", () =>
      jsonResponse({
        day: "2026-09-28",
        items: [turnSummary()],
        next_continuation: null,
      }),
    );
    await renderAndSettle(
      <DayTurnsPanel epoch={epoch} day={dayEntry("2026-09-28")} />,
    );

    expect(container.textContent).toContain("Archived · read-only");
    expect(container.textContent).toContain("Completed");
    expect(container.textContent).toContain("Summarize the release plan");
    expect(container.textContent).toContain("answered");
    const list = endpoint.calls("/v2/session/turns");
    expect(list).toHaveLength(1);
    expect(queryOf(list[0], "day")).toBe("2026-09-28");

    await act(async () => {
      buttonByText("Summarize the release plan").click();
    });
    // The drawer closes and the chat view takes over with the committed turn.
    expect(useInspectorStore.getState().entries).toHaveLength(0);
    const turn = useTurnStore.getState();
    expect(turn.turnId).toBe("t-old");
    expect(turn.historyView).toBe(true);
    const detail = endpoint.calls("/v2/session/turns/t-old");
    expect(detail).toHaveLength(1);
    expect(queryOf(detail[0], "day")).toBe("2026-09-28");
  });

  it("marks the live and queued turns separately from the committed record", async () => {
    useConnectionStore
      .getState()
      .applyStatus(
        epoch,
        makeStatus({
          activity: "user_turn",
          activeTurnId: "live-1",
          queuedTurnIds: ["queued-1"],
        }),
      );
    endpoint.get("/v2/session/turns", () =>
      jsonResponse({
        day: "2026-09-29",
        items: [turnSummary({ turn_id: "t-done", day: "2026-09-29" })],
        next_continuation: null,
      }),
    );
    await renderAndSettle(
      <DayTurnsPanel epoch={epoch} day={dayEntry("2026-09-29", true)} />,
    );

    expect(container.textContent).toContain("This day");
    expect(container.textContent).toContain("In progress");
    expect(container.textContent).toContain("live-1");
    expect(container.textContent).toContain("Queued");
    expect(container.textContent).toContain("queued-1");
    expect(container.textContent).toContain("Completed");
    expect(container.textContent).toContain("Summarize the release plan");
  });

  it("returns to the live turn from the in-progress row", async () => {
    useConnectionStore
      .getState()
      .applyStatus(
        epoch,
        makeStatus({ activity: "user_turn", activeTurnId: "live-1" }),
      );
    endpoint.get("/v2/session/turns", () =>
      jsonResponse({
        day: "2026-09-29",
        items: [turnSummary({ turn_id: "t-done", day: "2026-09-29" })],
        next_continuation: null,
      }),
    );
    endpoint.get("/v2/turns/live-1/interactions", () =>
      jsonResponse(makeInteractionsPage({ turn_id: "live-1" })),
    );
    endpoint.get("/v2/turns/live-1", () =>
      jsonResponse(runningSnapshot("live-1")),
    );
    await renderAndSettle(
      <DayTurnsPanel epoch={epoch} day={dayEntry("2026-09-29", true)} />,
    );

    await act(async () => {
      buttonByText("Return to the running conversation").click();
    });
    expect(useInspectorStore.getState().entries).toHaveLength(0);
    const turn = useTurnStore.getState();
    expect(turn.turnId).toBe("live-1");
    expect(turn.historyView).toBe(false);
    expect(turn.source).toBe("live");
  });

  it("distinguishes the empty states of an active and an archived day", async () => {
    endpoint.get("/v2/session/turns", () =>
      jsonResponse({ day: "2026-09-29", items: [], next_continuation: null }),
    );
    await renderAndSettle(
      <DayTurnsPanel epoch={epoch} day={dayEntry("2026-09-29", true)} />,
    );
    expect(container.textContent).toContain("No conversations on 2026-09-29 yet");
    expect(container.textContent).toContain(
      "Finished turns appear here once they are committed.",
    );

    endpoint.get("/v2/session/turns", () =>
      jsonResponse({ day: "2026-09-27", items: [], next_continuation: null }),
    );
    await act(async () => {
      root.render(
        <DayTurnsPanel epoch={epoch} day={dayEntry("2026-09-27")} />,
      );
    });
    expect(container.textContent).toContain("No conversations on 2026-09-27 yet");
    expect(container.textContent).toContain(
      "This archived day has no committed conversations.",
    );
  });
});
