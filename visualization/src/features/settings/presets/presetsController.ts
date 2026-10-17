/** Saving a plan captures current configuration; application uses the shared config publication boundary. */
import type { V2Clients } from "../../../api/v2/clients";
import { isTinySoulApiError } from "../../../api/v2/errors";
import type { PresetSummary } from "../../../api/v2/types";
import { useAppStore } from "../../../store/appStore";
import { classifyApplyError, loadConfig } from "../applyController";
import { useConfigDraftStore } from "../draft/store";
import {
  buildCreateBody,
  buildRecaptureBody,
  buildRenameBody,
  type CaptureInput,
} from "./presetsModel";

function describeError(error: unknown): string {
  if (isTinySoulApiError(error)) return `${error.code}: ${error.message}`;
  if (error instanceof Error) return error.message;
  return String(error);
}

/** Save current configuration as a plan without touching local drafts. */
export async function createPreset(
  clients: V2Clients,
  input: { name: string; description: string; capture: CaptureInput },
): Promise<PresetSummary | null> {
  const body = buildCreateBody(input.name, input.description, input.capture);
  try {
    const preset = await clients.config.createPreset(body);
    await loadConfig(clients);
    useAppStore
      .getState()
      .pushToast(
        "success",
        `Plan "${preset.name}" captured. The configuration and your local changes are untouched.`,
      );
    return preset;
  } catch (error) {
    useAppStore
      .getState()
      .pushToast("error", `Could not capture the plan: ${describeError(error)}`);
    return null;
  }
}

/** Rename a plan; the stored definition is never re-captured by a rename. */
export async function renamePreset(
  clients: V2Clients,
  presetId: string,
  input: { name: string; description: string },
): Promise<boolean> {
  try {
    await clients.config.updatePreset(
      presetId,
      buildRenameBody(input.name, input.description),
    );
    await loadConfig(clients);
    return true;
  } catch (error) {
    useAppStore
      .getState()
      .pushToast("error", `Could not rename the plan: ${describeError(error)}`);
    return false;
  }
}

/**
 * The explicit overwrite capture: replaces the stored definition from the
 * current configuration. This is the only flow that updates a plan's definition.
 */
export async function recapturePreset(
  clients: V2Clients,
  presetId: string,
  capture: CaptureInput,
): Promise<boolean> {
  const body = buildRecaptureBody(capture);
  try {
    await clients.config.updatePreset(presetId, body);
    await loadConfig(clients);
    useAppStore
      .getState()
      .pushToast("success", "Plan definition overwritten from the current configuration.");
    return true;
  } catch (error) {
    useAppStore
      .getState()
      .pushToast("error", `Could not overwrite the plan: ${describeError(error)}`);
    return false;
  }
}

/** Delete only the named plan record. */
export async function deletePreset(
  clients: V2Clients,
  preset: PresetSummary,
): Promise<boolean> {
  try {
    await clients.config.deletePreset(preset.id);
    await loadConfig(clients);
    useAppStore
      .getState()
      .pushToast(
        "success",
        `Plan "${preset.name}" deleted. The current configuration is unchanged.`,
      );
    return true;
  } catch (error) {
    useAppStore
      .getState()
      .pushToast("error", `Could not delete the plan: ${describeError(error)}`);
    return false;
  }
}

/**
 * Apply a plan: POST /config/apply `{preset_id}` — never alongside
 * operations. `discardDraftKeys` are the draft entries the user already
 * agreed to give up in the confirmation dialog; they are cleared only after
 * the activation succeeds. Returns true on success.
 */
export async function applyPreset(
  clients: V2Clients,
  preset: PresetSummary,
  options: { discardDraftKeys: string[] },
): Promise<boolean> {
  const store = useConfigDraftStore.getState();
  if (store.applyPhase !== "idle") return false;
  store.beginApply("applying");
  let result;
  try {
    result = await clients.config.apply({ preset_id: preset.id });
  } catch (error) {
    useConfigDraftStore.getState().failApply(classifyApplyError(error));
    return false;
  }
  if (result.state !== "active") {
    // The publish outcome is ambiguous — keep every draft and let the user
    // re-check the formal status instead of guessing either way.
    useConfigDraftStore.getState().failApply({
      kind: "uncertain",
      message:
        "The plan activation result was ambiguous. Refresh and check the configuration status before trying again; your local changes are kept.",
    });
    return false;
  }
  useConfigDraftStore
    .getState()
    .completeApply(options.discardDraftKeys, result.cleanup_diagnostics ?? null);
  await loadConfig(clients);
  useAppStore
    .getState()
    .pushToast(
      "success",
      `Plan "${preset.name}" applied${result.generation_id ? ` — generation ${result.generation_id}` : ""}.`,
    );
  return true;
}
