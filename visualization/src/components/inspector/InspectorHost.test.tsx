// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  InspectorHost,
  type InspectorEntry,
  type InspectorHostProps,
} from "./InspectorHost";

(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement;
let root: Root;

// jsdom has no matchMedia; the host reads prefers-reduced-motion through it.
function mockMatchMedia(reduced: boolean) {
  window.matchMedia = vi.fn().mockImplementation((query: string) => ({
    matches: reduced,
    media: query,
    onchange: null,
    addEventListener: () => {},
    removeEventListener: () => {},
    addListener: () => {},
    removeListener: () => {},
    dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia;
}

beforeEach(() => {
  mockMatchMedia(false);
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

function entry(partial: Partial<InspectorEntry> & { key: string }): InspectorEntry {
  return {
    title: `${partial.key} title`,
    render: () => <div>{`${partial.key} body`}</div>,
    ...partial,
  };
}

function renderHost(props: InspectorHostProps) {
  act(() => {
    root.render(<InspectorHost {...props} />);
  });
}

function dialogs(): HTMLElement[] {
  return Array.from(container.querySelectorAll('[role="dialog"]'));
}

function mainPanel(): HTMLElement {
  const panel = dialogs()[0];
  if (!panel) throw new Error("inspector is not open");
  return panel;
}

function panelBody(panel: HTMLElement): HTMLDivElement {
  return panel.querySelector(".overflow-y-auto") as HTMLDivElement;
}

function buttonWithText(scope: ParentNode, text: string): HTMLElement {
  const button = Array.from(scope.querySelectorAll("button")).find(
    (candidate) => candidate.textContent === text,
  );
  if (!button) throw new Error(`button "${text}" not found`);
  return button;
}

function pressKey(target: Element, key: string, shiftKey = false) {
  act(() => {
    target.dispatchEvent(
      new KeyboardEvent("keydown", { key, shiftKey, bubbles: true, cancelable: true }),
    );
  });
}

function click(target: Element) {
  act(() => {
    (target as HTMLElement).click();
  });
}

const noop = () => {};

describe("stack behaviour", () => {
  it("renders nothing while the stack is empty", () => {
    renderHost({ entries: [], onPop: noop, onClose: noop });
    expect(dialogs()).toHaveLength(0);
    expect(container.textContent).toBe("");
  });

  it("shows only the top entry and offers Back once the stack is deeper than one", () => {
    renderHost({
      entries: [entry({ key: "a" }), entry({ key: "b" })],
      onPop: noop,
      onClose: noop,
    });
    expect(container.textContent).toContain("b body");
    expect(container.textContent).not.toContain("a body");
    expect(container.textContent).not.toContain("a title");
    expect(mainPanel().querySelector('[aria-label="Back"]')).not.toBeNull();
  });

  it("pops when Back is clicked; the caller re-renders the shorter stack", () => {
    const onPop = vi.fn();
    const onClose = vi.fn();
    renderHost({ entries: [entry({ key: "a" }), entry({ key: "b" })], onPop, onClose });
    click(mainPanel().querySelector('[aria-label="Back"]')!);
    expect(onPop).toHaveBeenCalledTimes(1);
    expect(onClose).not.toHaveBeenCalled();

    renderHost({ entries: [entry({ key: "a" })], onPop, onClose });
    expect(container.textContent).toContain("a body");
    expect(mainPanel().querySelector('[aria-label="Back"]')).toBeNull();
  });

  it("replaces the top entry in place when the caller swaps it", () => {
    renderHost({ entries: [entry({ key: "a" })], onPop: noop, onClose: noop });
    expect(container.textContent).toContain("a body");

    renderHost({ entries: [entry({ key: "c" })], onPop: noop, onClose: noop });
    expect(container.textContent).toContain("c body");
    expect(container.textContent).not.toContain("a body");
    // still a single level: no Back button
    expect(mainPanel().querySelector('[aria-label="Back"]')).toBeNull();
  });

  it("renders the subtitle under the title", () => {
    renderHost({
      entries: [entry({ key: "a", subtitle: "memory:entity/alice" })],
      onPop: noop,
      onClose: noop,
    });
    expect(mainPanel().querySelector("header")?.textContent).toContain(
      "memory:entity/alice",
    );
  });
});

describe("focus management", () => {
  it("lands focus on the detail title on open and drill, and returns it to the trigger on close", () => {
    renderHost({ entries: [], onPop: noop, onClose: noop });
    const trigger = document.createElement("button");
    trigger.textContent = "open inspector";
    document.body.appendChild(trigger);
    trigger.focus();
    expect(document.activeElement).toBe(trigger);

    renderHost({ entries: [entry({ key: "a" })], onPop: noop, onClose: noop });
    let active = document.activeElement as HTMLElement;
    expect(active.tagName).toBe("H2");
    expect(active.tabIndex).toBe(-1);
    expect(active.textContent).toBe("a title");

    renderHost({
      entries: [entry({ key: "a" }), entry({ key: "b" })],
      onPop: noop,
      onClose: noop,
    });
    active = document.activeElement as HTMLElement;
    expect(active.tagName).toBe("H2");
    expect(active.textContent).toBe("b title");

    renderHost({ entries: [], onPop: noop, onClose: noop });
    expect(document.activeElement).toBe(trigger);
    trigger.remove();
  });

  it("prefers an explicit triggerRef over the element focused at open time", () => {
    const trigger = document.createElement("button");
    const elsewhere = document.createElement("button");
    document.body.append(trigger, elsewhere);

    renderHost({ entries: [], onPop: noop, onClose: noop });
    elsewhere.focus();
    const triggerRef = { current: trigger };
    renderHost({ entries: [entry({ key: "a" })], onPop: noop, onClose: noop, triggerRef });
    renderHost({ entries: [], onPop: noop, onClose: noop, triggerRef });
    expect(document.activeElement).toBe(trigger);
    trigger.remove();
    elsewhere.remove();
  });

  it("closes the topmost layer with Esc: pop while deep, close at the root", () => {
    const onPop = vi.fn();
    const onClose = vi.fn();
    renderHost({
      entries: [entry({ key: "a" }), entry({ key: "b" })],
      onPop,
      onClose,
    });
    pressKey(mainPanel().querySelector("button")!, "Escape");
    expect(onPop).toHaveBeenCalledTimes(1);
    expect(onClose).not.toHaveBeenCalled();

    onPop.mockClear();
    renderHost({ entries: [entry({ key: "a" })], onPop, onClose });
    pressKey(mainPanel().querySelector("button")!, "Escape");
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(onPop).not.toHaveBeenCalled();
  });

  it("traps Tab inside the drawer, wrapping at both ends", () => {
    renderHost({
      entries: [
        entry({ key: "a", render: () => <button>inside action</button> }),
      ],
      onPop: noop,
      onClose: noop,
    });
    const panel = mainPanel();
    const inside = buttonWithText(panel, "inside action");
    const expand = panel.querySelector('[aria-label="Expand wide view"]') as HTMLElement;

    inside.focus();
    pressKey(inside, "Tab");
    expect(document.activeElement).toBe(expand);

    pressKey(expand, "Tab", true);
    expect(document.activeElement).toBe(inside);
  });
});

describe("copy button", () => {
  it("copies the entry link and confirms briefly", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText },
    });
    renderHost({
      entries: [entry({ key: "a", copyText: "memory:entity/alice" })],
      onPop: noop,
      onClose: noop,
    });
    const copyButton = mainPanel().querySelector('[aria-label="Copy link"]');
    expect(copyButton).not.toBeNull();

    await act(async () => {
      (copyButton as HTMLElement).click();
    });
    expect(writeText).toHaveBeenCalledWith("memory:entity/alice");
    expect(mainPanel().querySelector('[aria-label="Copied"]')).not.toBeNull();
  });

  it("is hidden when the entry has no link to copy", () => {
    renderHost({ entries: [entry({ key: "a" })], onPop: noop, onClose: noop });
    expect(mainPanel().querySelector('[aria-label="Copy link"]')).toBeNull();
  });
});

describe("scroll memory and wide view", () => {
  it("restores each entry's scroll position when navigating back and forth", () => {
    renderHost({ entries: [entry({ key: "a" })], onPop: noop, onClose: noop });
    act(() => {
      const body = panelBody(mainPanel());
      body.scrollTop = 120;
      body.dispatchEvent(new Event("scroll"));
    });

    renderHost({
      entries: [entry({ key: "a" }), entry({ key: "b" })],
      onPop: noop,
      onClose: noop,
    });
    expect(panelBody(mainPanel()).scrollTop).toBe(0);
    act(() => {
      const body = panelBody(mainPanel());
      body.scrollTop = 45;
      body.dispatchEvent(new Event("scroll"));
    });

    renderHost({ entries: [entry({ key: "a" })], onPop: noop, onClose: noop });
    expect(panelBody(mainPanel()).scrollTop).toBe(120);

    renderHost({
      entries: [entry({ key: "a" }), entry({ key: "b" })],
      onPop: noop,
      onClose: noop,
    });
    expect(panelBody(mainPanel()).scrollTop).toBe(45);
  });

  it("expands to the wide view and collapses back to the entry width without losing scroll", () => {
    renderHost({
      entries: [entry({ key: "a" })],
      onPop: noop,
      onClose: noop,
      defaultWidth: "400px",
      expandedWidth: "900px",
    });
    const panel = mainPanel();
    expect(panel.style.width).toBe("400px");
    act(() => {
      const body = panelBody(panel);
      body.scrollTop = 60;
      body.dispatchEvent(new Event("scroll"));
    });

    click(panel.querySelector('[aria-label="Expand wide view"]')!);
    expect(panel.style.width).toBe("900px");
    expect(panelBody(panel).scrollTop).toBe(60);

    click(panel.querySelector('[aria-label="Collapse wide view"]')!);
    expect(panel.style.width).toBe("400px");
    expect(panelBody(panel).scrollTop).toBe(60);
  });

  it("honours a per-entry width override", () => {
    renderHost({
      entries: [entry({ key: "a", width: "480px" })],
      onPop: noop,
      onClose: noop,
    });
    expect(mainPanel().style.width).toBe("480px");
  });
});

describe("sub-drawer", () => {
  it("layers a second panel above the drawer with its own back navigation and focus", () => {
    const onCloseSub = vi.fn();
    renderHost({
      entries: [entry({ key: "a" })],
      onPop: noop,
      onClose: noop,
      sub: entry({ key: "s", title: "Sub title" }),
      onCloseSub,
    });
    const panels = dialogs();
    expect(panels).toHaveLength(2);
    const subPanel = panels[1];
    expect(subPanel.className).toContain("z-(--z-subdrawer)");
    expect(subPanel.textContent).toContain("Sub title");
    expect(subPanel.textContent).toContain("s body");
    // opening the sub-drawer lands focus on its title
    expect((document.activeElement as HTMLElement).textContent).toBe("Sub title");

    // Back closes the sub layer only; the caller then drops the prop
    click(subPanel.querySelector('[aria-label="Back"]')!);
    expect(onCloseSub).toHaveBeenCalledTimes(1);
    renderHost({
      entries: [entry({ key: "a" })],
      onPop: noop,
      onClose: noop,
      sub: null,
      onCloseSub,
    });
    expect(dialogs()).toHaveLength(1);
    // focus returns to the main drawer control that had it before
    expect((document.activeElement as HTMLElement).textContent).toBe("a title");
  });

  it("routes Esc to the sub layer while one is open", () => {
    const onPop = vi.fn();
    const onClose = vi.fn();
    const onCloseSub = vi.fn();
    renderHost({
      entries: [entry({ key: "a" }), entry({ key: "b" })],
      onPop,
      onClose,
      sub: entry({ key: "s" }),
      onCloseSub,
    });
    pressKey(dialogs()[1].querySelector("button")!, "Escape");
    expect(onCloseSub).toHaveBeenCalledTimes(1);
    expect(onPop).not.toHaveBeenCalled();
    expect(onClose).not.toHaveBeenCalled();
  });

  it("traps Tab inside the sub layer while it is open", () => {
    renderHost({
      entries: [entry({ key: "a" })],
      onPop: noop,
      onClose: noop,
      sub: entry({ key: "s", render: () => <button>sub action</button> }),
      onCloseSub: noop,
    });
    const subPanel = dialogs()[1];
    const subAction = buttonWithText(subPanel, "sub action");
    const subBack = subPanel.querySelector('[aria-label="Back"]') as HTMLElement;

    subAction.focus();
    pressKey(subAction, "Tab");
    expect(document.activeElement).toBe(subBack);

    pressKey(subBack, "Tab", true);
    expect(document.activeElement).toBe(subAction);
  });

  it("clicking the sub overlay dismisses the sub layer, clicking the page overlay closes everything", () => {
    const onClose = vi.fn();
    const onCloseSub = vi.fn();
    renderHost({
      entries: [entry({ key: "a" })],
      onPop: noop,
      onClose,
      sub: entry({ key: "s" }),
      onCloseSub,
    });
    click(container.querySelector('[class*="z-(--z-subdrawer-overlay)"]')!);
    expect(onCloseSub).toHaveBeenCalledTimes(1);
    expect(onClose).not.toHaveBeenCalled();

    renderHost({ entries: [entry({ key: "a" })], onPop: noop, onClose });
    click(container.querySelector('[class*="backdrop-blur"]')!);
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});

describe("motion", () => {
  it("animates the drawer entrance, drill-in and sub-drawer by default", () => {
    renderHost({
      entries: [entry({ key: "a" })],
      onPop: noop,
      onClose: noop,
      sub: entry({ key: "s" }),
      onCloseSub: noop,
    });
    const [panel, subPanel] = dialogs();
    expect(panel.className).toContain("animate-slide-in-right");
    expect(subPanel.className).toContain("animate-sub-drawer-in");
    expect(panelBody(panel).firstElementChild?.className).toContain(
      "animate-sub-drawer-in",
    );
  });

  it("renders without animation under prefers-reduced-motion and stays interactive", () => {
    mockMatchMedia(true);
    const onPop = vi.fn();
    renderHost({
      entries: [entry({ key: "a" }), entry({ key: "b" })],
      onPop,
      onClose: noop,
      sub: entry({ key: "s" }),
      onCloseSub: noop,
    });
    const [panel, subPanel] = dialogs();
    expect(panel.className).not.toContain("animate-slide-in-right");
    expect(subPanel.className).not.toContain("animate-sub-drawer-in");
    expect(panelBody(panel).firstElementChild?.className ?? "").not.toContain(
      "animate-sub-drawer-in",
    );
    // content is usable immediately, animations never gate it
    expect(panel.textContent).toContain("b body");
    click(panel.querySelector('[aria-label="Back"]')!);
    expect(onPop).toHaveBeenCalledTimes(1);
  });
});
