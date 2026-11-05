import { useI18n } from "../../../i18n";
/**
 * System & Diagnostics settings (config-coverage §7): read-only process items
 * (endpoint listener, agent/config process fields) with their ownership
 * reason and the configuration source list. Context composition fields are
 * edited on Data & Knowledge → Context.
 */

import type { JsonObject } from "../../../api/v2/types";
import { Badge } from "../../../components/ui/Badge";
import { SectionCard } from "../../../components/ui/Card";
import { isPlainRecord, savedValue } from "../draft/model";
import { useConfigDraftStore } from "../draft/store";
import { useSettingsUiStore } from "../uiStore";
import { ReadOnlyValue, SettingsPageBody } from "./draftCompositeControls";

const PROCESS_FIELDS = [
  "agent.interactive",
  "agent.exit_commands",
  "agent.stop_turn_commands",
  "agent.retained_outcomes",
  "agent.output.mode",
  "agent.output.max_model_detail_chars",
  "config.include",
  "config.env_file",
  "config.document_sets",
];

export function SystemPage() {
  const { t } = useI18n();
  const navigateTo = useSettingsUiStore((state) => state.navigateTo);
  const policy = useConfigDraftStore((state) => savedValue(state.saved, "infra.network"));
  const mode = isPlainRecord(policy) ? policy.mode : "inherit";
  const proxySummary = mode === "override" ? t("settings.rootProxyEnabled") : mode === "direct" ? t("settings.rootProxyDisabled") : t("settings.inheritEnvironment");
  return (
    <SettingsPageBody>
      <SectionCard
        title={t("settings.networkProxy2")}
        description={t("settings.editTheRootPolicyAndInspectEffectiveRoutesOn")}
        actions={
          <button type="button" className="rounded-md bg-hover px-2 py-1 text-xs text-accent hover:bg-line-strong/60" onClick={() => navigateTo("network")}>
            {t("settings.openNetworkSettings")}
          </button>
        }
      >
        <p className="text-xs text-fg-muted">{proxySummary}{t("settings.proxyOverridesHint")}</p>
      </SectionCard>
      <ProcessShellCard />
      <SourcesCard />
      <SectionCard
        title={t("settings.processOwnedFields")}
        description={t("settings.declaredByTheProcessItselfTheCliLaunchEnvironment")}
      >
        <div className="flex flex-col divide-y divide-line">
          {PROCESS_FIELDS.map((path) => (
            <ReadOnlyValue key={path} path={path} />
          ))}
        </div>
      </SectionCard>
    </SettingsPageBody>
  );
}

/** The endpoint listener projection; never editable through configuration. */
function ProcessShellCard() {
  const { t } = useI18n();
  const processShell = useConfigDraftStore((s) => s.saved?.process_shell);
  const endpoint = isEndpoint(processShell)
    ? (processShell.endpoint as JsonObject)
    : null;
  const row = (label: string, value: unknown) => (
    <>
      <dt className="text-fg-faint">{label}</dt>
      <dd className="font-mono break-all text-fg">
        {typeof value === "string" || typeof value === "number" ? String(value) : "—"}
      </dd>
    </>
  );
  return (
    <SectionCard
      title={t("settings.endpointListener")}
      description={t("settings.whereThisBackendListensTheListenerBelongsToThe")}
      actions={<Badge tone="gray">{t("settings.processManaged")}</Badge>}
    >
      <dl className="grid grid-cols-[140px_minmax(0,1fr)] gap-x-3 gap-y-1.5 text-[12px]">
        {row("Host", endpoint?.host)}
        {row("Port", endpoint?.port)}
        {row("Instance", endpoint?.instance_id)}
      </dl>
    </SectionCard>
  );
}

function isEndpoint(value: unknown): value is JsonObject & { endpoint: JsonObject } {
  return (
    typeof value === "object" &&
    value !== null &&
    !Array.isArray(value) &&
    typeof (value as JsonObject).endpoint === "object" &&
    (value as JsonObject).endpoint !== null
  );
}

/** The configuration sources with their writability, as projected by the backend. */
function SourcesCard() {
  const { t } = useI18n();
  const sources = useConfigDraftStore((s) => s.saved?.sources ?? []);
  return (
    <SectionCard
      title={t("settings.configurationSources")}
      description={t("settings.everySourceTheSavedViewWasProjectedFromIn")}
    >
      <div className="space-y-1">
        {sources.map((source) => (
          <div key={source.id} className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 rounded-md py-1 text-[12px]">
            <span className="min-w-0 break-all font-mono text-fg">{source.id}</span>
            <Badge tone="gray">{source.kind}</Badge>
            <span className="min-w-0 flex-1 truncate font-mono text-[11px] text-fg-faint">
              {source.path || "—"}
            </span>
            <span className="flex shrink-0 items-center gap-1">
              {!source.exists && <Badge tone="yellow">{t("settings.overview.sourceMissing")}</Badge>}
              {source.writable ? (
                <Badge tone="green">{t("settings.writable")}</Badge>
              ) : (
                <Badge tone="gray">{t("settings.overview.sourceReadonly")}</Badge>
              )}
            </span>
          </div>
        ))}
        {sources.length === 0 && (
          <div className="text-[12px] text-fg-faint">{t("settings.noSources")}</div>
        )}
      </div>
    </SectionCard>
  );
}
