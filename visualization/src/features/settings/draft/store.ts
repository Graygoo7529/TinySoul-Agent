/**
 * The shared ConfigDraft store (implementation plan §15): one zustand store
 * holds the formal snapshots (saved / active / catalog / presets), the local
 * atomic drafts, staleness marks and the apply lifecycle. All Agent settings
 * pages share it; drafts survive leaving the settings tab and are never
 * persisted to localStorage (credentials stay memory-only).
 */

import { create } from "zustand";

import type {
  ConfigCatalog,
  Configuration,
  JsonObject,
  JsonValue,
  PresetSummary,
} from "../../../api/v2/types";
import {
  applyDelete,
  applySet,
  buildOperations,
  draftKey,
  rebaseOnSaved,
  resetAtomEntries,
  savedValue,
  type DraftEntry,
  type DraftRef,
} from "./model";
import {
  decodeCatalog,
  validateDrafts,
  type FieldIssue,
  type SettingsCatalog,
} from "./catalog";

export type ConfigLoadPhase = "idle" | "loading" | "ready" | "error";

/**
 * Classified apply/reload outcome on failure. `config-invalid` with a key
 * locates one config object; without a key it is a batch error.
 * `activation-unavailable` (409) and `uncertain` (network/ambiguous result)
 * always keep the draft.
 */
export type ApplyFailure =
  | {
      kind: "config-invalid";
      key: string | null;
      message: string;
      details: JsonObject;
    }
  | { kind: "request-invalid"; message: string; details: JsonObject }
  | { kind: "activation-unavailable"; message: string }
  | { kind: "activation-failed"; message: string; details: JsonObject }
  | { kind: "api-error"; code: string; message: string; details: JsonObject }
  | { kind: "uncertain"; message: string };

export interface ConfigSnapshot {
  saved: Configuration;
  active: Configuration;
  catalog: SettingsCatalog;
  presets: PresetSummary[];
}

export interface ConfigDraftState {
  saved: Configuration | null;
  active: Configuration | null;
  catalog: SettingsCatalog | null;
  presets: PresetSummary[] | null;
  loadPhase: ConfigLoadPhase;
  loadError: string | null;

  drafts: Record<string, DraftEntry>;
  /** Dirty keys whose saved baseline moved underneath them. */
  stale: Record<string, true>;

  applyPhase: "idle" | "applying" | "reloading";
  applyFailure: ApplyFailure | null;
  /** cleanup_diagnostics of the last successful apply/reload (informational). */
  cleanupDiagnostics: JsonValue[] | null;

  // --- draft editing -------------------------------------------------------
  setValue: (sourceId: string, path: string, value: JsonValue) => void;
  deleteValue: (sourceId: string, path: string) => void;
  /**
   * Record delete drafts for refs whose ownership the caller has already
   * established (e.g. subtreeDeleteRefs for a collection object root). Unlike
   * deleteValue this skips the leaf-ownership check: a project source holds an
   * object through its flattened leaves, never through the root path itself.
   */
  deleteRefs: (refs: DraftRef[]) => void;
  /** Withdraw exactly the listed draft keys; other pages' edits stay. */
  resetEntries: (keys: string[]) => void;
  /**
   * Withdraw only the owned entries inside one shared collection atom,
   * keeping other pages' entries in the same atom (see model.resetAtomEntries).
   */
  resetEntriesWithin: (
    sourceId: string,
    path: string,
    options: {
      owns: (entryKey: string, entry: JsonValue) => boolean;
      entryKey?: (entry: JsonValue) => string | null;
    },
  ) => void;
  discardAll: () => void;
  /** Resolve a stale mark: adopt the new baseline (drop the draft) or keep the local value. */
  resolveStale: (key: string, action: "adopt" | "keep") => void;

  // --- controller-facing lifecycle -----------------------------------------
  setLoading: () => void;
  failLoading: (error: string) => void;
  /** Install fresh snapshots; dirty drafts are rebased, never reset. */
  applySnapshots: (input: {
    saved: Configuration;
    active: Configuration;
    catalogRaw: ConfigCatalog;
    presets: PresetSummary[];
  }) => void;
  beginApply: (phase: "applying" | "reloading") => void;
  /** Apply succeeded with state=active: drop exactly the submitted drafts. */
  completeApply: (
    submittedKeys: string[],
    cleanupDiagnostics: JsonValue[] | null,
  ) => void;
  failApply: (failure: ApplyFailure) => void;
  clearApplyFailure: () => void;
  dismissCleanupDiagnostics: () => void;

  /** Full reset on disconnect / project switch. */
  reset: () => void;
}

const initialState = {
  saved: null as Configuration | null,
  active: null as Configuration | null,
  catalog: null as SettingsCatalog | null,
  presets: null as PresetSummary[] | null,
  loadPhase: "idle" as ConfigLoadPhase,
  loadError: null as string | null,
  drafts: {} as Record<string, DraftEntry>,
  stale: {} as Record<string, true>,
  applyPhase: "idle" as ConfigDraftState["applyPhase"],
  applyFailure: null as ApplyFailure | null,
  cleanupDiagnostics: null as JsonValue[] | null,
};

export const useConfigDraftStore = create<ConfigDraftState>()((set) => ({
  ...initialState,

  setValue: (sourceId, path, value) =>
    set((state) => {
      const drafts = applySet(state.drafts, state.saved, { sourceId, path }, value);
      if (drafts === state.drafts) return state;
      const stale = { ...state.stale };
      delete stale[draftKey({ sourceId, path })];
      return { drafts, stale };
    }),

  deleteValue: (sourceId, path) =>
    set((state) => {
      const drafts = applyDelete(state.drafts, state.saved, { sourceId, path });
      if (drafts === state.drafts) return state;
      const stale = { ...state.stale };
      delete stale[draftKey({ sourceId, path })];
      return { drafts, stale };
    }),

  deleteRefs: (refs) =>
    set((state) => {
      if (refs.length === 0) return state;
      const drafts = { ...state.drafts };
      const stale = { ...state.stale };
      for (const ref of refs) {
        const key = draftKey(ref);
        // The caller established ownership (subtreeDeleteRefs); a delete
        // replaces any pending set at the same identity.
        drafts[key] = { key, ...ref, op: { op: "delete" } };
        delete stale[key];
      }
      return { drafts, stale };
    }),

  resetEntries: (keys) =>
    set((state) => {
      const drop = new Set(keys);
      const drafts = Object.fromEntries(
        Object.entries(state.drafts).filter(([key]) => !drop.has(key)),
      );
      const stale = Object.fromEntries(
        Object.entries(state.stale).filter(([key]) => !drop.has(key)),
      );
      return { drafts, stale };
    }),

  resetEntriesWithin: (sourceId, path, options) =>
    set((state) => {
      const drafts = resetAtomEntries(
        state.drafts,
        state.saved,
        { sourceId, path },
        options,
      );
      if (drafts === state.drafts) return state;
      const key = draftKey({ sourceId, path });
      const stale = { ...state.stale };
      if (drafts[key] === undefined) delete stale[key];
      return { drafts, stale };
    }),

  discardAll: () => set({ drafts: {}, stale: {} }),

  resolveStale: (key, action) =>
    set((state) => {
      const stale = { ...state.stale };
      delete stale[key];
      if (action === "keep") return { stale };
      const drafts = { ...state.drafts };
      delete drafts[key];
      return { drafts, stale };
    }),

  setLoading: () => set({ loadPhase: "loading", loadError: null }),

  failLoading: (error) =>
    set((state) => ({
      // A failed refresh keeps the last good snapshots on screen; without any
      // snapshot the page falls back to a full error state.
      loadPhase: state.saved === null ? "error" : "ready",
      loadError: error,
    })),

  applySnapshots: ({ saved, active, catalogRaw, presets }) =>
    set((state) => {
      const rebased = rebaseOnSaved(state.saved, saved, state.drafts, state.stale);
      return {
        saved,
        active,
        catalog: decodeCatalog(catalogRaw),
        presets,
        loadPhase: "ready",
        loadError: null,
        drafts: rebased.drafts,
        stale: rebased.stale,
      };
    }),

  beginApply: (phase) =>
    set({ applyPhase: phase, applyFailure: null }),

  completeApply: (submittedKeys, cleanupDiagnostics) =>
    set((state) => {
      const submitted = new Set(submittedKeys);
      const drafts = Object.fromEntries(
        Object.entries(state.drafts).filter(([key]) => !submitted.has(key)),
      );
      const stale = Object.fromEntries(
        Object.entries(state.stale).filter(([key]) => !submitted.has(key)),
      );
      return {
        drafts,
        stale,
        applyPhase: "idle",
        applyFailure: null,
        cleanupDiagnostics:
          cleanupDiagnostics !== null && cleanupDiagnostics.length > 0
            ? cleanupDiagnostics
            : null,
      };
    }),

  failApply: (failure) => set({ applyPhase: "idle", applyFailure: failure }),

  clearApplyFailure: () => set({ applyFailure: null }),

  dismissCleanupDiagnostics: () => set({ cleanupDiagnostics: null }),

  reset: () => set({ ...initialState }),
}));

// ---------------------------------------------------------------------------
// Selectors and derived views
// ---------------------------------------------------------------------------

export function selectDraftCount(state: ConfigDraftState): number {
  return Object.keys(state.drafts).length;
}

export function selectStaleCount(state: ConfigDraftState): number {
  return Object.keys(state.stale).length;
}

/** The tri-state of one config identity: local draft, saved baseline, running value. */
export interface EntryView {
  sourceId: string;
  path: string;
  draft: DraftEntry | null;
  saved: JsonValue | undefined;
  active: JsonValue | undefined;
  stale: boolean;
}

export function entryView(state: ConfigDraftState, ref: DraftRef): EntryView {
  const key = draftKey(ref);
  return {
    sourceId: ref.sourceId,
    path: ref.path,
    draft: state.drafts[key] ?? null,
    saved: savedValue(state.saved, ref.path),
    active: state.active?.fields[ref.path]?.value,
    stale: state.stale[key] === true,
  };
}

/** The value a form should display: draft when dirty, else the saved baseline. */
export function displayValue(state: ConfigDraftState, ref: DraftRef): JsonValue | undefined {
  const view = entryView(state, ref);
  return view.draft?.op.op === "set" ? view.draft.op.value : view.saved;
}

/**
 * The projected effective key set: saved fields overlaid with the drafts —
 * a `set` adds/replaces, a `delete` removes the key when the draft's source
 * supplied the effective value (lower-priority fallbacks are unknowable from
 * the projection). Used for local reference validation and for reference
 * pickers so they see objects created in the same draft.
 */
export function projectedKeys(state: ConfigDraftState): Set<string> {
  const keys = new Set(Object.keys(state.saved?.fields ?? {}));
  for (const entry of Object.values(state.drafts)) {
    if (entry.op.op === "set") {
      keys.add(entry.path);
    } else {
      // A delete removes the whole subtree at its path (keys owned by the
      // draft's source), matching the backend's delete semantics.
      for (const key of [...keys]) {
        if (key !== entry.path && !key.startsWith(`${entry.path}.`)) continue;
        if (state.saved?.fields[key]?.source === entry.sourceId) keys.delete(key);
      }
    }
  }
  return keys;
}

/** Local field issues for the current drafts (advisory; apply is authoritative). */
export function draftIssues(state: ConfigDraftState): FieldIssue[] {
  return validateDrafts(state.catalog, state.drafts, projectedKeys(state));
}

/** Operations for apply / preset capture, in deterministic order. */
export function draftOperations(state: ConfigDraftState) {
  return buildOperations(state.drafts);
}

/** Whether the apply/reload action is currently available, and why not. */
export function activationBlocker(state: ConfigDraftState): string | null {
  if (state.applyPhase !== "idle") {
    return state.applyPhase === "applying"
      ? "Applying configuration…"
      : "Reloading configuration…";
  }
  const activity = state.saved?.activity ?? state.active?.activity;
  if (activity === undefined || activity === null) {
    return "Configuration status has not been loaded yet.";
  }
  if (!activity.can_reload) {
    return activityReasonText(activity.reason);
  }
  return null;
}

export function activityReasonText(reason: string): string {
  switch (reason) {
    case "turn_active":
      return "The Agent is busy with a turn or a reflection.";
    case "activation_active":
      return "Another configuration activation is in progress.";
    case "runtime_active":
      return "The runtime is busy.";
    default:
      return reason !== "" ? reason : "Activation is currently unavailable.";
  }
}
