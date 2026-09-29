/**
 * API-05/06/07: configuration reads, candidate mutations, apply/reload and
 * named presets. patch() only saves a candidate; apply()/reload() publish a
 * generation. The frontend never mixes `operations` and `preset_id` in one
 * apply request (ConfigApplyRequest enforces the union at compile time).
 */

import type {
  ConfigActionsView,
  ConfigApplyRequest,
  ConfigCatalog,
  ConfigMutationResult,
  ConfigOperation,
  ConfigScenario,
  Configuration,
  ConfigView,
  Preset,
  PresetCreateBody,
  PresetDeleteResult,
  PresetList,
  PresetUpdateBody,
} from "../types";
import type { RequestOptions, V2Transport } from "../transport";

export class ConfigClient {
  constructor(private readonly transport: V2Transport) {}

  /** GET /v2/config?view=saved|active (default saved). */
  get(
    view: ConfigView = "saved",
    options?: RequestOptions,
  ): Promise<Configuration> {
    return this.transport.get<Configuration>("/config", {
      ...options,
      query: { view },
    });
  }

  /** GET /v2/config/catalog — Infra-owned field/collection declarations. */
  catalog(options?: RequestOptions): Promise<ConfigCatalog> {
    return this.transport.get<ConfigCatalog>("/config/catalog", options);
  }

  /** GET /v2/config/actions?scenario= — generation ActionEngine projection. */
  actions(
    scenario: ConfigScenario = "user",
    options?: RequestOptions,
  ): Promise<ConfigActionsView> {
    return this.transport.get<ConfigActionsView>("/config/actions", {
      ...options,
      query: { scenario },
    });
  }

  /** PATCH /v2/config — validate and save a candidate; nothing activates. */
  patch(
    operations: ConfigOperation[],
    options?: RequestOptions,
  ): Promise<ConfigMutationResult> {
    return this.transport.patch<ConfigMutationResult>("/config", {
      ...options,
      body: { operations },
    });
  }

  /** POST /v2/config/apply — atomic save+publish; operations xor preset_id. */
  apply(
    request: ConfigApplyRequest,
    options?: RequestOptions,
  ): Promise<ConfigMutationResult> {
    return this.transport.post<ConfigMutationResult>("/config/apply", {
      ...options,
      body: request,
    });
  }

  /** POST /v2/config/reload — activate the saved candidate (no body). */
  reload(options?: RequestOptions): Promise<ConfigMutationResult> {
    return this.transport.post<ConfigMutationResult>("/config/reload", options);
  }

  /** GET /v2/config/presets — named run-plan summaries. */
  listPresets(options?: RequestOptions): Promise<PresetList> {
    return this.transport.get<PresetList>("/config/presets", options);
  }

  /** POST /v2/config/presets — capture a plan; never applies configuration. */
  createPreset(
    body: PresetCreateBody,
    options?: RequestOptions,
  ): Promise<Preset> {
    return this.transport.post<Preset>("/config/presets", {
      ...options,
      body,
    });
  }

  /** GET /v2/config/presets/{id} — detail including the snapshot. */
  getPreset(presetId: string, options?: RequestOptions): Promise<Preset> {
    return this.transport.get<Preset>(
      `/config/presets/${encodeURIComponent(presetId)}`,
      options,
    );
  }

  /** PUT /v2/config/presets/{id} — rename, or re-capture when given. */
  updatePreset(
    presetId: string,
    body: PresetUpdateBody,
    options?: RequestOptions,
  ): Promise<Preset> {
    return this.transport.put<Preset>(
      `/config/presets/${encodeURIComponent(presetId)}`,
      { ...options, body },
    );
  }

  /** DELETE /v2/config/presets/{id} — removes the plan file only. */
  deletePreset(
    presetId: string,
    options?: RequestOptions,
  ): Promise<PresetDeleteResult> {
    return this.transport.delete<PresetDeleteResult>(
      `/config/presets/${encodeURIComponent(presetId)}`,
      options,
    );
  }
}
