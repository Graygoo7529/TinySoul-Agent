// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { resetTurnController } from "./turnController";
import { useTurnStore } from "../../store/turnStore";
import {
  FakeEndpoint,
  bodyJson,
  errorResponse,
  jsonResponse,
  makeStatus,
  questionInteractionFixture,
  replyInteractionFixture,
  resetAppStores,
  waitingSnapshot,
  wireConnectedStores,
} from "../../app/testing";
import { QuestionCard } from "./QuestionCard";

(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement;
let root: Root;
let endpoint: FakeEndpoint;
let epoch: number;

const QUESTION_ITEM = questionInteractionFixture();
const LIVE_QUESTION = waitingSnapshot().question!;

beforeEach(() => {
  resetTurnController();
  resetAppStores();
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
});

function renderLive() {
  act(() => {
    root.render(
      <QuestionCard
        epoch={epoch}
        turnId="contract-turn"
        item={QUESTION_ITEM}
        live={LIVE_QUESTION}
        reply={null}
      />,
    );
  });
}

function radio(): HTMLInputElement {
  const input = container.querySelector(
    'input[type="radio"][name="question-action_result_1"]',
  );
  if (!input) throw new Error("radio option not rendered");
  return input as HTMLInputElement;
}

function inputByPlaceholder(placeholder: string): HTMLInputElement {
  const input = container.querySelector(`input[placeholder="${placeholder}"]`);
  if (!input) throw new Error(`input "${placeholder}" not rendered`);
  return input as HTMLInputElement;
}

function replyButton(): HTMLButtonElement {
  const button = Array.from(container.querySelectorAll("button")).find(
    (candidate) => candidate.textContent === "Reply",
  );
  if (!button) throw new Error("Reply button not rendered");
  return button;
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

describe("QuestionCard: live question", () => {
  it("renders the waiting question with options and the Other entry", () => {
    renderLive();
    expect(container.textContent).toContain("Choose a direction");
    expect(container.textContent).toContain("Execute");
    expect(container.textContent).toContain("Use the approved plan");
    expect(radio()).toBeDefined();
    expect(inputByPlaceholder("Other answer…")).toBeDefined();
    // Nothing selected yet: submit stays disabled.
    expect(replyButton().disabled).toBe(true);
  });

  it("numbers the options A/B/C visually; submission keeps stable ids", () => {
    const threeOptions = {
      ...LIVE_QUESTION,
      options: [
        { id: "opt_x", label: "First" },
        { id: "opt_y", label: "Second" },
        { id: "opt_z", label: "Third" },
      ],
    };
    act(() => {
      root.render(
        <QuestionCard
          epoch={epoch}
          turnId="contract-turn"
          item={QUESTION_ITEM}
          live={threeOptions}
          reply={null}
        />,
      );
    });
    const letters = Array.from(
      container.querySelectorAll('[data-question-form="active"] label span[aria-hidden="true"]'),
    ).map((node) => node.textContent);
    expect(letters).toEqual(["A", "B", "C"]);
    // The radio group shares one stable name.
    const radios = container.querySelectorAll(
      'input[type="radio"][name="question-action_result_1"]',
    );
    expect(radios).toHaveLength(3);
  });

  it("submits a choice with an optional comment", async () => {
    let replyBody: Record<string, unknown>;
    endpoint.post("/v2/turns/contract-turn/reply", (request) => {
      replyBody = bodyJson(request) as Record<string, unknown>;
      return jsonResponse({
        accepted: true,
        record_id: "reply_action_result_1",
        sequence: 3,
      });
    });
    renderLive();

    act(() => {
      radio().click();
    });
    expect(radio().checked).toBe(true);
    expect(replyButton().disabled).toBe(false);
    typeInto(inputByPlaceholder("Comment (optional)…"), "Proceed");

    await act(async () => {
      replyButton().click();
    });
    expect(replyBody!).toEqual({
      question_id: "action_result_1",
      answer: { kind: "choice", option_id: "a", comment: "Proceed" },
    });
    // The echo waits for the formal projection; no local error is shown.
    const echo = useTurnStore.getState().outgoing[0]!;
    expect(echo.kind).toBe("reply");
    expect(echo.state).toBe("accepted");
    expect(container.textContent).not.toContain("no longer awaiting");
  });

  it("submits a free-text Other answer", async () => {
    let replyBody: Record<string, unknown>;
    endpoint.post("/v2/turns/contract-turn/reply", (request) => {
      replyBody = bodyJson(request) as Record<string, unknown>;
      return jsonResponse({
        accepted: true,
        record_id: "reply_action_result_1",
        sequence: 4,
      });
    });
    renderLive();

    typeInto(inputByPlaceholder("Other answer…"), "Custom plan");
    // Typing an Other answer clears any option selection.
    expect(radio().checked).toBe(false);

    await act(async () => {
      replyButton().click();
    });
    expect(replyBody!).toEqual({
      question_id: "action_result_1",
      answer: { kind: "text", text: "Custom plan" },
    });
  });

  it("accepts a duplicate receipt without manufacturing a second answer", async () => {
    endpoint.post("/v2/turns/contract-turn/reply", () =>
      jsonResponse({
        accepted: false,
        record_id: "reply_action_result_1",
        sequence: 3,
      }),
    );
    renderLive();
    act(() => {
      radio().click();
    });
    await act(async () => {
      replyButton().click();
    });
    // Already answered earlier: the echo converges, no error, no new answer.
    expect(useTurnStore.getState().outgoing).toEqual([]);
    expect(container.textContent).not.toContain("no longer awaiting");
  });

  it("keeps the draft and shows the error when the question went stale", async () => {
    endpoint.post("/v2/turns/contract-turn/reply", () =>
      errorResponse(409, "turn.command_rejected"),
    );
    renderLive();
    act(() => {
      radio().click();
    });
    typeInto(inputByPlaceholder("Comment (optional)…"), "Proceed");

    await act(async () => {
      replyButton().click();
    });
    expect(container.textContent).toContain(
      "This question is no longer awaiting a reply",
    );
    // The draft survives the failed submit and can be adjusted/retried.
    expect(radio().checked).toBe(true);
    expect(replyButton().disabled).toBe(false);
    expect(useTurnStore.getState().outgoing).toEqual([]);
  });
});

describe("QuestionCard: read-only question", () => {
  it("renders the answered question without a submit control", () => {
    act(() => {
      root.render(
        <QuestionCard
          epoch={epoch}
          turnId="contract-turn"
          item={QUESTION_ITEM}
          live={null}
          reply={replyInteractionFixture()}
        />,
      );
    });
    expect(container.textContent).toContain("Choose a direction");
    expect(container.textContent).toContain("Execute");
    expect(container.textContent).toContain("answered");
    expect(
      Array.from(container.querySelectorAll("button")).find(
        (button) => button.textContent === "Reply",
      ),
    ).toBeUndefined();
    expect(endpoint.requests).toHaveLength(0);
  });

  it("shows the actual question, the chosen option's label and the comment", () => {
    act(() => {
      root.render(
        <QuestionCard
          epoch={epoch}
          turnId="contract-turn"
          item={QUESTION_ITEM}
          live={null}
          reply={replyInteractionFixture()}
        />,
      );
    });
    // The fixture reply: choice "a" with comment "Proceed".
    expect(container.textContent).toContain("Proceed");
    const chosen = Array.from(container.querySelectorAll("div")).find(
      (node) =>
        node.className.includes("border-accent/50") &&
        node.textContent?.includes("Execute"),
    );
    expect(chosen).toBeDefined();
    // The A/B/C letter stays visual; the stable id drove the reply.
    expect(container.textContent).toContain("A");
    // No interactive control survives.
    expect(container.querySelectorAll('input[type="radio"]')).toHaveLength(0);
    expect(container.querySelector("input")).toBeNull();
  });
});

describe("QuestionCard: expired question", () => {
  it("marks a lapsed wait as expired and preserves the unsubmitted draft", () => {
    renderLive();
    act(() => {
      radio().click();
    });
    typeInto(inputByPlaceholder("Comment (optional)…"), "Proceed carefully");

    // The wait lapses (superseded / turn moved on) before the reply went
    // out: the same card instance flips to the expired mode.
    act(() => {
      root.render(
        <QuestionCard
          epoch={epoch}
          turnId="contract-turn"
          item={{ ...QUESTION_ITEM, answered: false }}
          live={null}
          reply={null}
        />,
      );
    });

    expect(container.textContent).toContain(
      "This question is no longer awaiting a reply",
    );
    // The unsubmitted draft text is still visible, nothing was sent.
    expect(container.textContent).toContain("Proceed carefully");
    expect(endpoint.requests).toHaveLength(0);
    expect(
      Array.from(container.querySelectorAll("button")).find(
        (button) => button.textContent === "Reply",
      ),
    ).toBeUndefined();
    // The preserved selection is visible but no longer interactive.
    expect(container.querySelectorAll('input[type="radio"]')).toHaveLength(0);
  });

  it("unanswered history reads as expired without a draft", () => {
    act(() => {
      root.render(
        <QuestionCard
          epoch={epoch}
          turnId="contract-turn"
          item={{ ...QUESTION_ITEM, answered: false }}
          live={null}
          reply={null}
        />,
      );
    });
    expect(container.textContent).toContain("Choose a direction");
    expect(container.textContent).toContain("Execute");
    expect(container.textContent).toContain(
      "This question is no longer awaiting a reply",
    );
  });
});
