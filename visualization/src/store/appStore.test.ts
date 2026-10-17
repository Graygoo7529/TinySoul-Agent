import { beforeEach, describe, expect, it } from "vitest";

import { normalizePersistedActiveTab, useAppStore } from "./appStore";

describe("appStore", () => {
  beforeEach(() => {
    useAppStore.setState({ activeTab: "chat", toasts: [] });
  });

  it("switches the active tab", () => {
    useAppStore.getState().setActiveTab("runtime");
    expect(useAppStore.getState().activeTab).toBe("runtime");
  });

  it("caps toasts at five and dismisses by id", () => {
    for (let i = 0; i < 7; i += 1) {
      useAppStore.getState().pushToast("info", `toast ${i}`);
    }
    const toasts = useAppStore.getState().toasts;
    expect(toasts).toHaveLength(5);
    expect(toasts[0].text).toBe("toast 2");
    useAppStore.getState().dismissToast(toasts[0].id);
    expect(useAppStore.getState().toasts).toHaveLength(4);
  });
});

describe("normalizePersistedActiveTab", () => {
  it("keeps known v2 tabs", () => {
    expect(normalizePersistedActiveTab("workspace")).toBe("workspace");
    expect(normalizePersistedActiveTab("home")).toBe("home");
    expect(normalizePersistedActiveTab("memory")).toBe("memory");
    expect(normalizePersistedActiveTab("runtime")).toBe("runtime");
  });

  it("maps the v1 monitor tab to runtime", () => {
    expect(normalizePersistedActiveTab("monitor")).toBe("runtime");
  });

  it("never restores settings and falls back to chat", () => {
    expect(normalizePersistedActiveTab("settings")).toBe("chat");
    expect(normalizePersistedActiveTab(undefined)).toBe("chat");
    expect(normalizePersistedActiveTab(42)).toBe("chat");
  });
});
