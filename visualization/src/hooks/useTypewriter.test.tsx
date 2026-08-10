// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useTypewriter } from "./useTypewriter";

(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  vi.useFakeTimers();
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  vi.useRealTimers();
});

function probe() {
  const states: { shown: string; typing: boolean }[] = [];
  function Probe({
    target,
    active = true,
    startDelayMs = 0,
  }: {
    target: string;
    active?: boolean;
    startDelayMs?: number;
  }) {
    states.push(useTypewriter(target, { durationMs: 200, startDelayMs, active }));
    return null;
  }
  const render = (target: string, active = true, startDelayMs = 0) =>
    act(() => {
      root.render(<Probe target={target} active={active} startDelayMs={startDelayMs} />);
    });
  const last = () => states[states.length - 1];
  return { states, render, last };
}

describe("useTypewriter", () => {
  it("reveals the target progressively within the time budget", () => {
    const { render, last } = probe();
    render("abcdefghij"); // 10 chars, 200ms budget → 2 chars per 24ms tick
    expect(last().shown).toBe("");
    expect(last().typing).toBe(true);
    act(() => {
      vi.advanceTimersByTime(24);
    });
    expect(last().shown).toBe("ab");
    act(() => {
      vi.advanceTimersByTime(200);
    });
    expect(last().shown).toBe("abcdefghij");
    expect(last().typing).toBe(false);
  });

  it("shows the full text immediately when inactive", () => {
    const { render, last } = probe();
    render("hello", false);
    expect(last().shown).toBe("hello");
    expect(last().typing).toBe(false);
  });

  it("holds the first tick back by startDelayMs", () => {
    const { render, last } = probe();
    render("abcdefgh", true, 250);
    act(() => {
      vi.advanceTimersByTime(100);
    });
    expect(last().shown).toBe("");
    act(() => {
      vi.advanceTimersByTime(250);
    });
    expect(last().shown.length).toBeGreaterThan(0);
  });

  it("restarts the reveal when the target changes", () => {
    const { render, last } = probe();
    render("aaaaaaaa");
    act(() => {
      vi.advanceTimersByTime(400);
    });
    expect(last().shown).toBe("aaaaaaaa");
    render("bb");
    expect(last().shown).toBe("");
    act(() => {
      vi.advanceTimersByTime(200);
    });
    expect(last().shown).toBe("bb");
  });
});
