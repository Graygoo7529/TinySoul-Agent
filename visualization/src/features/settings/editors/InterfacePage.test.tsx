// @vitest-environment jsdom
/**
 * Interface preferences: the page edits the persisted local prefs store, the
 * theme stays in appStore, and applyUiPrefsToDocument pushes the values onto
 * the document element that index.css consumes.
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { useAppStore } from "../../../store/appStore";
import {
  applyUiPrefsToDocument,
  REDUCED_MOTION_CLASS,
  UI_PREFS_DEFAULTS,
  useUiPrefsStore,
} from "../../../store/uiPrefsStore";
import { InterfacePage } from "./InterfacePage";

(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;

const prefs = () => useUiPrefsStore.getState();

let container: HTMLDivElement;
let root: Root;

async function flush(): Promise<void> {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}

beforeEach(() => {
  localStorage.clear();
  useUiPrefsStore.setState({ ...UI_PREFS_DEFAULTS });
  useAppStore.setState({ theme: "light" });
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(async () => {
  await act(async () => {
    root.unmount();
  });
  container.remove();
});

describe("applyUiPrefsToDocument", () => {
  it("sets the CSS variables and the reduced-motion class", () => {
    const target = document.createElement("html");
    applyUiPrefsToDocument(
      { ...UI_PREFS_DEFAULTS, fontSize: 16, density: "compact", reducedMotion: true },
      target,
    );
    expect(target.style.getPropertyValue("--ui-font-size")).toBe("16px");
    expect(target.style.getPropertyValue("--ui-line-height")).toBe("1.5");
    expect(target.style.getPropertyValue("--ui-density")).toBe("0.85");
    expect(target.style.getPropertyValue("--font-sans")).toContain("Inter");
    expect(target.classList.contains(REDUCED_MOTION_CLASS)).toBe(true);

    applyUiPrefsToDocument(
      { ...UI_PREFS_DEFAULTS, fontMono: "cascadia" },
      target,
    );
    expect(target.style.getPropertyValue("--font-mono")).toContain(
      "Cascadia Code",
    );
    expect(target.classList.contains(REDUCED_MOTION_CLASS)).toBe(false);
  });
});

describe("useUiPrefsStore", () => {
  it("clamps numeric ranges and resets to defaults", () => {
    prefs().setPref("fontSize", 99);
    expect(prefs().fontSize).toBe(18);
    prefs().setPref("lineHeight", 0.1);
    expect(prefs().lineHeight).toBe(1.3);
    prefs().setPref("density", "compact");
    prefs().resetDefaults();
    expect(prefs().fontSize).toBe(UI_PREFS_DEFAULTS.fontSize);
    expect(prefs().lineHeight).toBe(UI_PREFS_DEFAULTS.lineHeight);
    expect(prefs().density).toBe("comfortable");
  });

  it("persists under tinysoul-ui-prefs", () => {
    prefs().setPref("fontSize", 15);
    const stored = localStorage.getItem("tinysoul-ui-prefs");
    expect(stored).not.toBeNull();
    expect(
      (JSON.parse(stored!) as { state: { fontSize: number } }).state.fontSize,
    ).toBe(15);
  });
});

describe("InterfacePage", () => {
  it("edits prefs immediately and resets everything including the theme", async () => {
    await act(async () => {
      root.render(<InterfacePage />);
    });
    await flush();

    // Theme stays in appStore.
    const dark = [...container.querySelectorAll("button")].find(
      (item) => item.textContent === "Dark",
    );
    await act(async () => {
      dark!.click();
    });
    expect(useAppStore.getState().theme).toBe("dark");

    // Density segmented control.
    const compact = [...container.querySelectorAll("button")].find(
      (item) => item.textContent === "Compact",
    );
    await act(async () => {
      compact!.click();
    });
    expect(prefs().density).toBe("compact");

    // Reduced motion switch.
    const motionSwitch = container.querySelector("[role='switch']");
    await act(async () => {
      (motionSwitch as HTMLElement).click();
    });
    expect(prefs().reducedMotion).toBe(true);

    // No fake toggles for prefs without consumers.
    expect(container.textContent).not.toContain("auto-follow");
    expect(container.textContent).not.toContain("Notification");

    // Reset restores prefs and the theme.
    const reset = [...container.querySelectorAll("button")].find((item) =>
      item.textContent?.includes("Reset interface defaults"),
    );
    await act(async () => {
      reset!.click();
    });
    expect(prefs().density).toBe("comfortable");
    expect(prefs().reducedMotion).toBe(false);
    expect(useAppStore.getState().theme).toBe("light");
  });
});
