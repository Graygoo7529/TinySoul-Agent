// @vitest-environment jsdom
/**
 * Data & Knowledge page tests: the embedding_use reference picker (draft-aware,
 * embedding-kind only) and the Session page's owned-elsewhere budget row.
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import type { Configuration, JsonValue } from "../../../api/v2/types";
import { draftOperations, useConfigDraftStore } from "../draft/store";
import { useSettingsUiStore } from "../uiStore";
import { HomePage } from "./HomePage";
import { SessionPage } from "./SessionPage";

(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;

const MAIN_SOURCE = "project:tinysoul.toml";

function makeCatalog(): Record<string, unknown> {
  const field = (path: string, valueKind: string) => ({
    path,
    surface: path.split(".")[0],
    group: "g",
    title: path.split(".").pop(),
    description: "",
    value_kind: valueKind,
    importance: "primary",
    credential_reference: false,
  });
  return {
    surfaces: [],
    field_groups: [],
    collections: [],
    fields: [
      field("home.search.embedding_use", "string"),
      field("home.search.scan_limit", "integer"),
      field("session.inspect_max_chars", "integer"),
    ],
    document_fields: [],
  };
}

function makeSaved(): Configuration {
  const uses = [
    { id: "emb-main", kind: "embedding", model_id: "m1" },
    { id: "jev-1", kind: "structured_decision", model_id: "m2" },
  ];
  const fields: Record<string, { value: JsonValue; source: string }> = {
    "infra.model_services.uses": { value: uses, source: MAIN_SOURCE },
    "home.search.scan_limit": { value: 1000, source: MAIN_SOURCE },
    "session.background_max_chars": { value: 24000, source: MAIN_SOURCE },
    "session.inspect_max_chars": { value: 8000, source: MAIN_SOURCE },
  };
  return {
    view: "saved",
    generation_id: "gen_saved",
    activity: { state: "idle", can_write: true, can_reload: true, reason: "" },
    pending_reload: false,
    sources: [
      {
        id: MAIN_SOURCE,
        kind: "project_toml",
        path: "tinysoul.toml",
        exists: true,
        writable: true,
        values: {
          "infra.model_services.uses": uses,
          "home.search.scan_limit": 1000,
          "session.background_max_chars": 24000,
          "session.inspect_max_chars": 8000,
        },
      },
    ],
    fields: Object.fromEntries(
      Object.entries(fields).map(([key, item]) => [
        key,
        { value: item.value, source: item.source, writable: true },
      ]),
    ),
  };
}

const store = () => useConfigDraftStore.getState();

let container: HTMLDivElement;
let root: Root;

async function flush(): Promise<void> {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}

beforeEach(() => {
  store().reset();
  store().applySnapshots({
    saved: makeSaved(),
    active: makeSaved(),
    catalogRaw: makeCatalog() as never,
    presets: [],
  });
  useSettingsUiStore.setState({ page: "home", focusPath: null });
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

describe("HomePage embedding_use picker", () => {
  function useSelect(): HTMLSelectElement {
    const row = container.querySelector(
      '[data-field-path="home.search.embedding_use"]',
    );
    expect(row).not.toBeNull();
    const select = row!.querySelector("select");
    expect(select).not.toBeNull();
    return select as HTMLSelectElement;
  }

  it("lists only embedding-kind uses and commits the selected id", async () => {
    await act(async () => {
      root.render(<HomePage />);
    });
    await flush();

    const select = useSelect();
    const labels = [...select.options].map((option) => option.textContent);
    expect(labels.some((label) => label?.includes("emb-main"))).toBe(true);
    expect(labels.some((label) => label?.includes("jev-1"))).toBe(false);

    const setter = Object.getOwnPropertyDescriptor(
      HTMLSelectElement.prototype,
      "value",
    )?.set;
    await act(async () => {
      setter?.call(select, "emb-main");
      select.dispatchEvent(new Event("change", { bubbles: true }));
    });
    expect(draftOperations(store())).toEqual([
      {
        op: "set",
        source_id: MAIN_SOURCE,
        path: "home.search.embedding_use",
        value: "emb-main",
      },
    ]);

    // Choosing "Not set" again records a delete (no-op against the source).
    await act(async () => {
      setter?.call(select, "");
      select.dispatchEvent(new Event("change", { bubbles: true }));
    });
    expect(draftOperations(store())).toEqual([]);
  });

  it("sees a use created in the same draft", async () => {
    const baseline = makeSaved().fields["infra.model_services.uses"]
      .value as JsonValue[];
    store().setValue(MAIN_SOURCE, "infra.model_services.uses", [
      ...baseline,
      { id: "emb-new", kind: "embedding", model_id: "m9" },
    ]);

    await act(async () => {
      root.render(<HomePage />);
    });
    await flush();

    const labels = [...useSelect().options].map((option) => option.textContent);
    expect(labels.some((label) => label?.includes("emb-new"))).toBe(true);
  });
});

describe("SessionPage background budget", () => {
  it("shows the saved value read-only and jumps to the owning Budgets page", async () => {
    await act(async () => {
      root.render(<SessionPage />);
    });
    await flush();

    expect(container.textContent).toContain("session.background_max_chars");
    expect(container.textContent).toContain("24000");
    expect(
      container.querySelector('[data-field-path="session.background_max_chars"]'),
    ).toBeNull();

    const jump = [...container.querySelectorAll("button")].find((item) =>
      item.textContent?.includes("前往预算设置"),
    );
    expect(jump).toBeDefined();
    await act(async () => {
      jump!.click();
    });
    expect(useSettingsUiStore.getState().page).toBe("budgets");
    expect(useSettingsUiStore.getState().focusPath).toBe(
      "session.background_max_chars",
    );
  });
});
