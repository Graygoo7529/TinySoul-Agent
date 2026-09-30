/**
 * Async settings flows (implementation plan §15): initial/refresh loads, the
 * batch apply and the saved-candidate reload. Controllers are module-level
 * functions like the chat turnController; the draft store holds the state.
 *
 * Result semantics (docs/endpoint/configuration.md):
 * - apply/reload success is `state=active`: the submitted drafts are cleared,
 *   snapshots are re-read, and `cleanup_diagnostics` is reported separately —
 *   it never turns the outcome back into "not applied".
 * - Every pre-publish failure keeps the local drafts. `config.invalid` with a
 *   structured details.key locates one config object; without a key the batch
 *   error is shown as-is (the message is never parsed for field names).
 * - 409 config.activation_unavailable keeps the draft and explains.
 * - A network failure leaves the result unknown: the draft is kept and the UI
 *   suggests re-reading the formal status instead of blindly re-applying.
 */

import type { V2Clients } from "../../api/v2/clients";
import {
  configErrorKey,
  hasApiCode,
  isTinySoulApiError,
} from "../../api/v2/errors";
import type { JsonValue } from "../../api/v2/types";
import { useAppStore } from "../../store/appStore";
import { buildOperations } from "./draft/model";
import {
  useConfigDraftStore,
  type ApplyFailure,
} from "./draft/store";

/** Load (or refresh) saved + active views, the catalog and the plan list. */
export async function loadConfig(clients: V2Clients): Promise<boolean> {
  const store = useConfigDraftStore.getState();
  store.setLoading();
  try {
    const [saved, active, catalog, presetList] = await Promise.all([
      clients.config.get("saved"),
      clients.config.get("active"),
      clients.config.catalog(),
      clients.config.listPresets(),
    ]);
    useConfigDraftStore.getState().applySnapshots({
      saved,
      active,
      catalogRaw: catalog,
      presets: presetList.presets,
    });
    return true;
  } catch (error) {
    useConfigDraftStore.getState().failLoading(describeError(error));
    return false;
  }
}

// The clients identity the current snapshots were loaded for. The Composer
// quick entry mounts outside the settings shell, so a same-connection remount
// must not refetch, while a new connection (new clients object) must — the
// settings tab may have been unmounted across the disconnect and missed its
// store reset.
let snapshotsLoadedFor: V2Clients | null = null;

/** Load the shared config snapshots once per connection (idempotent). */
export function ensureConfigLoaded(clients: V2Clients): void {
  if (snapshotsLoadedFor === clients) return;
  if (useConfigDraftStore.getState().loadPhase === "loading") return;
  snapshotsLoadedFor = clients;
  void loadConfig(clients).then((ok) => {
    // A failed load is retried on the next mount.
    if (!ok && snapshotsLoadedFor === clients) snapshotsLoadedFor = null;
  });
}

/** Apply every local draft as one batch. */
export async function applyDrafts(clients: V2Clients): Promise<void> {
  const store = useConfigDraftStore.getState();
  if (store.applyPhase !== "idle") return;
  const operations = buildOperations(store.drafts);
  if (operations.length === 0) return;
  const submittedKeys = Object.keys(store.drafts);
  store.beginApply("applying");
  let result;
  try {
    result = await clients.config.apply({ operations });
  } catch (error) {
    useConfigDraftStore.getState().failApply(classifyApplyError(error));
    return;
  }
  if (result.state !== "active") {
    // apply is specified to publish atomically; anything else is ambiguous —
    // keep the drafts and let the user re-check the formal status.
    useConfigDraftStore.getState().failApply({
      kind: "uncertain",
      message:
        "The apply result was ambiguous. The draft is kept; refresh and check the saved/active status before trying again.",
    });
    return;
  }
  await finishActivation(clients, submittedKeys, result.cleanup_diagnostics ?? null);
  useAppStore
    .getState()
    .pushToast(
      "success",
      `Configuration applied${result.generation_id ? ` — generation ${result.generation_id}` : ""}.`,
    );
}

/** Activate the already-saved candidate (POST /config/reload). */
export async function reloadSaved(clients: V2Clients): Promise<void> {
  const store = useConfigDraftStore.getState();
  if (store.applyPhase !== "idle") return;
  store.beginApply("reloading");
  let result;
  try {
    result = await clients.config.reload();
  } catch (error) {
    useConfigDraftStore.getState().failApply(classifyApplyError(error));
    return;
  }
  if (result.state !== "active") {
    useConfigDraftStore.getState().failApply({
      kind: "uncertain",
      message:
        "The reload result was ambiguous. Refresh and check the saved/active status before trying again.",
    });
    return;
  }
  await finishActivation(clients, [], result.cleanup_diagnostics ?? null);
  useAppStore.getState().pushToast("success", "Saved configuration activated.");
}

/**
 * Successful activation: clear exactly the submitted drafts (edits made while
 * the request was in flight survive), then re-read status/config/catalog so
 * the pages render the new generation's truth. A failed re-read keeps the
 * applied state and only surfaces a load error.
 */
async function finishActivation(
  clients: V2Clients,
  submittedKeys: string[],
  cleanupDiagnostics: JsonValue[] | null,
): Promise<void> {
  useConfigDraftStore.getState().completeApply(submittedKeys, cleanupDiagnostics);
  await loadConfig(clients);
}

/** Map a caught error to the stable failure classification. */
export function classifyApplyError(error: unknown): ApplyFailure {
  if (isTinySoulApiError(error)) {
    if (hasApiCode(error, "config.invalid")) {
      return {
        kind: "config-invalid",
        key: configErrorKey(error),
        message: error.message,
        details: error.details,
      };
    }
    if (hasApiCode(error, "config.activation_unavailable")) {
      return { kind: "activation-unavailable", message: error.message };
    }
    if (hasApiCode(error, "config.activation_failed")) {
      return {
        kind: "activation-failed",
        message: error.message,
        details: error.details,
      };
    }
    if (hasApiCode(error, "request.invalid")) {
      return {
        kind: "request-invalid",
        message: error.message,
        details: error.details,
      };
    }
    return {
      kind: "api-error",
      code: error.code,
      message: error.message,
      details: error.details,
    };
  }
  return {
    kind: "uncertain",
    message:
      "The request result is unknown (network or client failure). The draft is kept; refresh and compare saved/active before re-applying.",
  };
}

function describeError(error: unknown): string {
  if (isTinySoulApiError(error)) return `${error.code}: ${error.message}`;
  if (error instanceof Error) return error.message;
  return String(error);
}
