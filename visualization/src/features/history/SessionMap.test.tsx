// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import type { JsonObject, JsonValue } from "../../api/v2/types";
import {
  FakeEndpoint,
  jsonResponse,
  makeInteractionsPage,
  makeStatus,
  queryOf,
  resetAppStores,
  wireConnectedStores,
} from "../../app/testing";
import { useInspectorStore } from "../../store/inspectorStore";
import { useTurnStore } from "../../store/turnStore";
import { resetTurnController } from "../chat/turnController";
import { SessionMapPanel } from "./SessionMapPanel";
import { SessionRefPanel } from "./SessionRefPanel";

(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;

const DAY = "2026-09-28";

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

function child(ref: string, title: string, clue = ""): JsonObject {
  return { kind: "child", ref, title, clue };
}

/** The map root hints, deliberately unordered — the panel sorts sections. */
const MAP_ITEMS: JsonValue[] = [
  child("session:annotations", "Interpretations"),
  child("session:history", "All conversations"),
  child("session:topics", "Topics"),
  child("session:unclassified", "Unclassified conversations"),
];

function mapRoute(items: JsonValue[] = MAP_ITEMS) {
  endpoint.get("/v2/session/map", () =>
    jsonResponse({ ref: "session:map", kind: "session_map", items }),
  );
}

/**
 * Inspect pages keyed by ref. A history page may split into two
 * continuation pages via `{ "": page1, c2: page2 }` — pass a record of
 * continuation → page for that.
 */
function inspectRoute(
  pages: Record<string, JsonObject | Record<string, JsonObject>>,
) {
  endpoint.get("/v2/session/inspect", (request) => {
    const ref = queryOf(request, "ref") ?? "session:map";
    const entry = pages[ref];
    if (entry !== undefined && !("kind" in entry || "items" in entry)) {
      const token = queryOf(request, "continuation") ?? "";
      const page = (entry as Record<string, JsonObject>)[token];
      if (page !== undefined) return jsonResponse(page);
    }
    if (entry !== undefined && "items" in entry) {
      return jsonResponse(entry);
    }
    return jsonResponse({ ref, kind: "session_list", items: [] });
  });
}

function buttonByText(text: string): HTMLButtonElement {
  const button = Array.from(container.querySelectorAll("button")).find(
    (candidate) => candidate.textContent?.includes(text),
  );
  if (!button) throw new Error(`button "${text}" not rendered`);
  return button as HTMLButtonElement;
}

function typeInto(input: HTMLInputElement, value: string): void {
  const setter = Object.getOwnPropertyDescriptor(
    window.HTMLInputElement.prototype,
    "value",
  )!.set!;
  act(() => {
    setter.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

async function renderAndSettle(element: React.ReactElement) {
  await act(async () => {
    root.render(element);
  });
}

const TOPIC_HINT = child(
  "session:node/n1",
  "Release plan",
  "active: Discussed the rollout",
);
const HISTORY_HINT = child(
  "session:turn/2026-09-28/1",
  "Summarize the release plan",
  "answered",
);
const RETRACTED_HINT = child(
  "session:edge/e1",
  "covers → Summarize the release plan",
  "retracted: superseded by a newer note",
);

describe("SessionMapPanel", () => {
  it("renders the grouped sections and mounts interpretations on demand", async () => {
    mapRoute();
    inspectRoute({
      "session:topics": { ref: "session:topics", items: [TOPIC_HINT] },
      "session:history": { ref: "session:history", items: [HISTORY_HINT] },
      "session:annotations": {
        ref: "session:annotations",
        items: [RETRACTED_HINT],
      },
    });
    await renderAndSettle(<SessionMapPanel epoch={epoch} day={DAY} />);

    // Section order: topics → unclassified → history → annotations.
    const text = container.textContent ?? "";
    expect(text.indexOf("Topics")).toBeLessThan(
      text.indexOf("Unclassified conversations"),
    );
    expect(text.indexOf("Unclassified conversations")).toBeLessThan(
      text.indexOf("All conversations"),
    );
    expect(text.indexOf("All conversations")).toBeLessThan(
      text.indexOf("Interpretations"),
    );
    // Topics open eagerly; the unclassified empty line is its own message.
    expect(text).toContain("Release plan");
    expect(text).toContain(
      "Every committed conversation is covered by a topic.",
    );
    // The interpretations list stays unloaded until the section is expanded.
    const seenRefs = () =>
      endpoint.calls("/v2/session/inspect").map((call) => queryOf(call, "ref"));
    expect(seenRefs()).toContain("session:topics");
    expect(seenRefs()).toContain("session:unclassified");
    expect(seenRefs()).toContain("session:history");
    expect(seenRefs()).not.toContain("session:annotations");

    await act(async () => {
      buttonByText("Interpretations").click();
    });
    expect(seenRefs()).toContain("session:annotations");
    // A retracted annotation hint keeps its status visible.
    const row = buttonByText("covers → Summarize the release plan");
    expect(row.querySelector(".line-through")).not.toBeNull();
    expect(row.textContent).toContain("retracted");
    expect(row.textContent).toContain("superseded by a newer note");
  });

  it("shows the single empty state when the day has no committed turns", async () => {
    mapRoute();
    inspectRoute({});
    await renderAndSettle(<SessionMapPanel epoch={epoch} day={DAY} />);
    expect(container.textContent).toContain(
      `No completed conversations on ${DAY}`,
    );
    expect(container.textContent).not.toContain("No topics yet");
  });

  it("keeps the sections when facts exist but no topic covers them", async () => {
    mapRoute();
    inspectRoute({
      "session:history": { ref: "session:history", items: [HISTORY_HINT] },
    });
    await renderAndSettle(<SessionMapPanel epoch={epoch} day={DAY} />);
    expect(container.textContent).toContain(
      "No topics yet — ask TinySoul in a conversation to organize this day.",
    );
    expect(container.textContent).not.toContain("No completed conversations");
  });

  it("pushes a topic's own inspect page from its hint", async () => {
    mapRoute();
    inspectRoute({
      "session:topics": { ref: "session:topics", items: [TOPIC_HINT] },
      "session:history": { ref: "session:history", items: [HISTORY_HINT] },
    });
    await renderAndSettle(<SessionMapPanel epoch={epoch} day={DAY} />);
    await act(async () => {
      buttonByText("Release plan").click();
    });
    const entries = useInspectorStore.getState().entries;
    expect(entries).toHaveLength(1);
    expect(entries[0].key.startsWith(`session-ref:${DAY}:session:node/n1:`)).toBe(
      true,
    );
    expect(entries[0].subtitle).toBe("session:node/n1");
  });

  it("flattens a multi-part reply clue and marks the inspect affordance with its own icon", async () => {
    mapRoute();
    inspectRoute({
      "session:unclassified": {
        ref: "session:unclassified",
        items: [
          child(
            "session:turn/2026-09-28/1",
            `${DAY} · answered`,
            "Which option? / Option B (opt_b)\nThe second option\nreply comment",
          ),
        ],
      },
      "session:history": { ref: "session:history", items: [HISTORY_HINT] },
    });
    await renderAndSettle(<SessionMapPanel epoch={epoch} day={DAY} />);

    // Question, picked option, description and comment never run together.
    expect(container.textContent).toContain(
      "Which option? · Option B (opt_b) · The second option · reply comment",
    );
    // The card body opens the conversation (chevron); the adjacent button
    // drills into the recorded facts and carries a distinct panel icon.
    const inspect = container.querySelector(
      'button[aria-label="Inspect the recorded facts"]',
    ) as HTMLButtonElement | null;
    expect(inspect).not.toBeNull();
    expect(inspect!.querySelector("svg.lucide-panel-right-open")).not.toBeNull();
    expect(inspect!.querySelector("svg.lucide-chevron-right")).toBeNull();
  });

  it("opens a history conversation from its hint", async () => {
    endpoint.get("/v2/session/turns/2026-09-28/1", () =>
      jsonResponse(
        makeInteractionsPage({
          ref: "session:turn/2026-09-28/1",
          turn_id: "2026-09-28/1",
          day: DAY,
        }),
      ),
    );
    mapRoute();
    inspectRoute({
      "session:history": { ref: "session:history", items: [HISTORY_HINT] },
    });
    await renderAndSettle(<SessionMapPanel epoch={epoch} day={DAY} />);
    await act(async () => {
      buttonByText("Summarize the release plan").click();
    });
    expect(useTurnStore.getState().turnId).toBe("2026-09-28/1");
    expect(useTurnStore.getState().historyView).toBe(true);
  });

  it("locates within the day from the query box", async () => {
    mapRoute();
    inspectRoute({});
    await renderAndSettle(<SessionMapPanel epoch={epoch} day={DAY} />);
    const input = container.querySelector(
      'input[placeholder="Locate in this day…"]',
    ) as HTMLInputElement;
    typeInto(input, "rollout");
    await act(async () => {
      buttonByText("Locate").click();
    });
    const entries = useInspectorStore.getState().entries;
    expect(entries).toHaveLength(1);
    expect(entries[0].key).toContain(":query:");
    expect(entries[0].title).toBe("Locate: rollout");
  });

  it("continues a section with its continuation token", async () => {
    mapRoute();
    inspectRoute({
      "session:history": {
        "": {
          ref: "session:history",
          items: [HISTORY_HINT],
          next_continuation: "c2",
        },
        c2: {
          ref: "session:history",
          items: [child("session:turn/2026-09-28/1er", "An older conversation")],
        },
      },
    });
    await renderAndSettle(<SessionMapPanel epoch={epoch} day={DAY} />);
    expect(container.textContent).not.toContain("An older conversation");
    await act(async () => {
      buttonByText("Show more").click();
    });
    expect(container.textContent).toContain("An older conversation");
    const calls = endpoint
      .calls("/v2/session/inspect")
      .filter((call) => queryOf(call, "ref") === "session:history");
    expect(calls).toHaveLength(2);
    expect(queryOf(calls[1], "continuation")).toBe("c2");
  });
});

// ---------------------------------------------------------------------------
// SessionRefPanel — one inspect page (topic, edge, turn, fact)
// ---------------------------------------------------------------------------

const NODE_PAGE: JsonObject = {
  ref: "session:node/n1",
  kind: "session_annotation",
  items: [
    {
      basis: "interpretation",
      ref: "session:node/n1",
      kind: "thread",
      title: "Release plan",
      body: "Discussed the rollout",
      source_refs: ["session:turn/2026-09-28/1#output"],
      status: "active",
    },
    {
      basis: "interpretation",
      ref: "session:edge/e1",
      source: "session:node/n1",
      target: "session:turn/2026-09-28/1",
      relation: "covers",
      body: "",
      source_refs: [],
      status: "active",
    },
    child("session:turn/2026-09-28/1", "History fact", "Summarize the release plan"),
    { kind: "source", ref: "session:turn/2026-09-28/1#output" },
  ],
};

describe("SessionRefPanel", () => {
  it("renders a topic page: interpretation, related edge and evidence", async () => {
    inspectRoute({ "session:node/n1": NODE_PAGE });
    await renderAndSettle(
      <SessionRefPanel epoch={epoch} day={DAY} targetRef="session:node/n1" />,
    );

    const text = container.textContent ?? "";
    expect(text).toContain("Release plan");
    expect(text).toContain("Discussed the rollout");
    expect(text).toContain("thread");
    expect(text).toContain("interpretation");
    expect(text).toContain("covers");
    expect(text).toContain("Contents");
    expect(text).toContain("History fact");
    expect(text).toContain("Evidence");
    // The evidence chip carries the compact ref and opens its own page.
    await act(async () => {
      buttonByText("2026-09-28/1#output").click();
    });
    const entries = useInspectorStore.getState().entries;
    expect(entries).toHaveLength(1);
    expect(entries[0].subtitle).toBe("session:turn/2026-09-28/1#output");
  });

  it("marks a retracted interpretation without hiding it", async () => {
    inspectRoute({
      "session:node/n1": {
        ref: "session:node/n1",
        kind: "session_annotation",
        items: [
          {
            basis: "interpretation",
            ref: "session:node/n1",
            kind: "note",
            title: "Old idea",
            body: "superseded",
            source_refs: [],
            status: "retracted",
          },
        ],
      },
    });
    await renderAndSettle(
      <SessionRefPanel epoch={epoch} day={DAY} targetRef="session:node/n1" />,
    );
    const title = Array.from(container.querySelectorAll("div")).find(
      (node) => node.textContent === "Old idea",
    );
    expect(title?.className).toContain("line-through");
    expect(container.textContent).toContain("retracted");
  });

  it("re-reads the same scope with the locate query and clears it", async () => {
    inspectRoute({
      "session:node/n1": {
        ref: "session:node/n1",
        kind: "session_query",
        items: [child("session:turn/2026-09-28/1", "Located", "rollout")],
      },
    });
    await renderAndSettle(
      <SessionRefPanel
        epoch={epoch}
        day={DAY}
        targetRef="session:node/n1"
        initialQuery="rollout"
      />,
    );
    const calls = () =>
      endpoint
        .calls("/v2/session/inspect")
        .filter((call) => queryOf(call, "ref") === "session:node/n1");
    expect(queryOf(calls()[0], "query")).toBe("rollout");
    expect(container.textContent).toContain("Locate: rollout");
    expect(container.textContent).toContain("Located");

    await act(async () => {
      buttonByText("Clear").click();
    });
    const all = calls();
    expect(all).toHaveLength(2);
    expect(queryOf(all[1], "query")).toBeNull();
    expect(container.textContent).not.toContain("Locate: rollout");
  });

  it("renders a committed turn page with facts and opens the conversation", async () => {
    endpoint.get("/v2/session/turns/2026-09-28/1", () =>
      jsonResponse(
        makeInteractionsPage({
          ref: "session:turn/2026-09-28/1",
          turn_id: "2026-09-28/1",
          day: DAY,
        }),
      ),
    );
    inspectRoute({
      "session:turn/2026-09-28/1": {
        ref: "session:turn/2026-09-28/1",
        kind: "session_turn",
        items: [
          {
            kind: "session_turn",
            ref: "session:turn/2026-09-28/1",
            day: DAY,
            status: "answered",
          },
          {
            kind: "interaction",
            id: "input/0",
            role: "user.input",
            ref: "session:turn/2026-09-28/1#input/0",
            text: "Summarize the release plan",
          },
          {
            kind: "interaction",
            id: "output",
            role: "agent.output",
            ref: "session:turn/2026-09-28/1#output",
            text: "Here is the summary…",
          },
          {
            kind: "session_action",
            ref: "session:turn/2026-09-28/1#actions/0",
            turn_ref: "session:turn/2026-09-28/1",
            action: "shell.exec",
            request: { command: "ls" },
            outcome: "success",
          },
          {
            kind: "relation",
            source: "session:turn/2026-09-28/1",
            target: "session:turn/2026-09-28/1#input/0",
            relation: "contains",
            basis: "fact",
          },
        ],
      },
    });
    await renderAndSettle(
      <SessionRefPanel epoch={epoch} day={DAY} targetRef="session:turn/2026-09-28/1" />,
    );

    const text = container.textContent ?? "";
    expect(text).toContain("Committed turn");
    expect(text).toContain("answered");
    expect(text).toContain("You");
    expect(text).toContain("Summarize the release plan");
    expect(text).toContain("Here is the summary…");
    expect(text).toContain("shell.exec");
    expect(text).toContain("success");
    expect(text).toContain("Relations");
    expect(text).toContain("contains");

    await act(async () => {
      buttonByText("Open conversation").click();
    });
    expect(useTurnStore.getState().turnId).toBe("2026-09-28/1");
    expect(useTurnStore.getState().historyView).toBe(true);
  });

  it("reports an exhausted empty page without inventing content", async () => {
    inspectRoute({
      "session:node/n1": { ref: "session:node/n1", items: [] },
    });
    await renderAndSettle(
      <SessionRefPanel epoch={epoch} day={DAY} targetRef="session:node/n1" />,
    );
    expect(container.textContent).toContain(
      "Nothing recorded under this reference.",
    );
  });
});
