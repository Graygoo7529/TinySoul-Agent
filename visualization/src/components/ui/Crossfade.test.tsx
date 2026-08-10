// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Crossfade } from "./Crossfade";

(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  vi.useFakeTimers();
  // jsdom has no matchMedia; useReducedMotion subscribes to it
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
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  vi.useRealTimers();
});

function render(id: string, text: string) {
  act(() => {
    root.render(
      <Crossfade id={id}>
        <span>{text}</span>
      </Crossfade>,
    );
  });
}

describe("Crossfade", () => {
  it("renders the content without an exit layer initially", () => {
    render("a", "first");
    expect(container.textContent).toBe("first");
    expect(container.querySelector(".xfade-exit")).toBeNull();
  });

  it("keeps the outgoing content on an exit layer while the new one fades in", () => {
    render("a", "first");
    render("b", "second");
    // both layers coexist during the crossfade
    expect(container.textContent).toContain("first");
    expect(container.textContent).toContain("second");
    expect(container.querySelector(".xfade-exit")?.textContent).toBe("first");
    // the exit layer retires once its fade has played
    act(() => {
      vi.advanceTimersByTime(400);
    });
    expect(container.textContent).toBe("second");
    expect(container.querySelector(".xfade-exit")).toBeNull();
  });

  it("refreshes same-id content in place without an exit layer", () => {
    render("a", "first");
    render("a", "first (updated)");
    expect(container.textContent).toBe("first (updated)");
    expect(container.querySelector(".xfade-exit")).toBeNull();
  });
});
