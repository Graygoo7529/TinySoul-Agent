// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { resetAppStores } from "../app/testing";
import { Toasts } from "../components/ui/Toasts";
import { SettingsNav } from "../features/settings/SettingsNav";
import { decodeCatalog } from "../features/settings/draft/catalog";
import { useConfigDraftStore } from "../features/settings/draft/store";
import { useSettingsUiStore } from "../features/settings/uiStore";
import { useAppStore } from "../store/appStore";
import { useUiPrefsStore } from "../store/uiPrefsStore";
import { localizeField, message, t, useI18n } from ".";

(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;
let container: HTMLDivElement;
let root: Root;
beforeEach(() => {
  resetAppStores();
  useConfigDraftStore.getState().reset();
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});
afterEach(() => {
  act(() => root.unmount());
  container.remove();
  vi.useRealTimers();
  resetAppStores();
});

it("updates a live toast and its action without replacing its identity, diagnostic or expiry", () => {
  vi.useFakeTimers();
  const retry = vi.fn();
  const detail = "future.provider: 保存 failed / raw detail";
  useAppStore.getState().pushToast("error", message("presentation.saveFailed", { detail }), {
    label: message("settings.retrySaving"), onClick: retry,
  });
  const toast = useAppStore.getState().toasts[0];
  act(() => root.render(<Toasts />));
  expect(container.textContent).toContain(t("presentation.saveFailed", { detail }));
  act(() => vi.advanceTimersByTime(3000));
  act(() => useUiPrefsStore.setState({ pending: { locale: "en-US" } }));
  expect(useAppStore.getState().toasts[0]).toBe(toast);
  expect(container.textContent).toContain(t("presentation.saveFailed", { detail }));
  expect(container.textContent).toContain(t("settings.retrySaving"));
  expect(container.textContent).toContain(detail);
  expect(retry).not.toHaveBeenCalled();
  act(() => vi.advanceTimersByTime(1500));
  expect(useAppStore.getState().toasts).toEqual([]);

  act(() => useAppStore.getState().pushToast("error", message("presentation.saveFailed", { detail }), {
    label: message("settings.retrySaving"), onClick: retry,
  }));
  const button = Array.from(container.querySelectorAll("button")).find((node) => node.textContent === t("settings.retrySaving"))!;
  act(() => button.click());
  expect(retry).toHaveBeenCalledTimes(1);
});

it("keeps translation functions stable until locale changes", () => {
  const values: ReturnType<typeof useI18n>[] = [];
  function Probe({ revision }: { revision: number }) {
    values.push(useI18n());
    return <span>{revision}</span>;
  }
  act(() => root.render(<Probe revision={0} />));
  act(() => root.render(<Probe revision={1} />));
  expect(values[1]).toBe(values[0]);
  act(() => useUiPrefsStore.setState({ pending: { locale: "en-US" } }));
  expect(values[values.length - 1].t).not.toBe(values[0].t);
});

it("reprojects the same settings query and routes to the same field without touching catalog facts", () => {
  const catalog = decodeCatalog({ fields: [{
    path: "llm.models.*.reasoning_effort", surface: "models", group: "models.adapter_options",
    title: "Editable source title", description: "Owner text can evolve.", value_kind: "enum",
    choices: [{ value: "future-level", label: "New owner choice" }],
  }] });
  useConfigDraftStore.setState({ catalog });
  act(() => root.render(<SettingsNav />));
  const input = container.querySelector("input")!;
  act(() => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(input, "reasoning_effort");
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
  const title = localizeField(catalog.fields[0], "zh-CN").title;
  const hit = Array.from(container.querySelectorAll("button")).find((node) => node.textContent?.includes(title))!;
  expect(hit).toBeDefined();
  act(() => useUiPrefsStore.setState({ pending: { locale: "en-US" } }));
  expect(input.value).toBe("reasoning_effort");
  expect(hit.isConnected).toBe(true);
  expect(hit.textContent).toContain(catalog.fields[0].title);
  act(() => hit.click());
  expect(useSettingsUiStore.getState().page).toBe("llm-models");
  expect(useSettingsUiStore.getState().focusPath).toBe(catalog.fields[0].path);
  expect(catalog.fields[0].choices[0]).toEqual({ value: "future-level", label: "New owner choice" });
});
