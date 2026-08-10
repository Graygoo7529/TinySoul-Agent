// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useThrottledValue } from "./useThrottledValue";

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
  const seen: string[] = [];
  function Probe({ value, ms }: { value: string; ms: number }) {
    seen.push(useThrottledValue(value, ms));
    return null;
  }
  const render = (value: string, ms: number) =>
    act(() => {
      root.render(<Probe value={value} ms={ms} />);
    });
  return { seen, render };
}

describe("useThrottledValue (the live status beat)", () => {
  it("commits the initial value immediately", () => {
    const { seen, render } = probe();
    render("a", 900);
    expect(seen[seen.length - 1]).toBe("a");
  });

  it("coalesces a rapid burst and flushes only the latest on the trailing edge", () => {
    const { seen, render } = probe();
    render("a", 900);
    render("b", 900);
    render("c", 900);
    // the burst is held back — the first beat keeps its minimum dwell
    expect(seen[seen.length - 1]).toBe("a");
    act(() => {
      vi.advanceTimersByTime(900);
    });
    // the trailing edge lands the latest value, not each intermediate one
    expect(seen[seen.length - 1]).toBe("c");
    expect(seen).not.toContain("b");
  });

  it("commits at most one beat per interval during a continuous stream", () => {
    const { seen, render } = probe();
    render("a", 900);
    render("b", 900);
    act(() => {
      vi.advanceTimersByTime(900);
    });
    expect(seen[seen.length - 1]).toBe("b");
    render("c", 900);
    // the previous flush just happened — the next value waits out its dwell
    expect(seen[seen.length - 1]).toBe("b");
    act(() => {
      vi.advanceTimersByTime(900);
    });
    expect(seen[seen.length - 1]).toBe("c");
  });

  it("commits immediately once the dwell has elapsed", () => {
    const { seen, render } = probe();
    render("a", 900);
    act(() => {
      vi.advanceTimersByTime(1000);
    });
    render("b", 900);
    expect(seen[seen.length - 1]).toBe("b");
  });

  it("passes values straight through with a zero interval", () => {
    const { seen, render } = probe();
    render("a", 0);
    render("b", 0);
    expect(seen[seen.length - 1]).toBe("b");
  });
});
