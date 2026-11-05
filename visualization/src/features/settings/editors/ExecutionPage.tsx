import { useI18n } from "../../../i18n";
import { NetworkPolicyField } from "./NetworkPolicyEditor";
/**
 * Execution & Jobs settings (config-coverage §4.1/§4.2): the running
 * generation's effective values are shown read-only on top; editing targets
 * the saved configuration and activates through the shared apply lifecycle.
 */

import { Badge } from "../../../components/ui/Badge";
import { SectionCard } from "../../../components/ui/Card";
import { activeValue } from "../draft/model";
import { useConfigDraftStore } from "../draft/store";
import { FieldSection, SettingsPageBody } from "./draftCompositeControls";

const INTERPRETERS = ["python", "bash", "powershell", "cmd"] as const;

export function ExecutionPage() {
  const { t } = useI18n();
  return (
    <SettingsPageBody>
      <NetworkPolicyField path="execution.network" title={t("settings.executionProxy")} />
      <details><summary className="cursor-pointer text-sm text-fg-muted">{t("settings.interpreterProxy")}</summary>
        {INTERPRETERS.map((id) => <NetworkPolicyField key={id} path={`execution.interpreters.${id}.network`} title={id} parentLabel={t("settings.executionProxy")} />)}
        <p className="p-3 text-xs text-fg-muted">{t("settings.executionProxyHint")}</p>
      </details>
      <RunningStrip />
      <FieldSection
        title={t("settings.interpreters")}
        description={t("settings.whichShellScriptInterpretersTheExecutionDomainMayUse")}
        paths={[
          "execution.enabled",
          ...INTERPRETERS.map((id) => `execution.interpreters.${id}.enabled`),
          ...INTERPRETERS.map((id) => `execution.interpreters.${id}.executable`),
        ]}
        forceAdvanced={INTERPRETERS.map(
          (id) => `execution.interpreters.${id}.executable`,
        )}
      />
      <FieldSection
        title={t("settings.limits")}
        description={t("settings.boundsOfASingleExecutionTheRuntimeEnforcesOne")}
        paths={[
          "execution.max_runtime_seconds",
          "execution.max_output_bytes",
          "execution.max_collect_chars",
          "execution.max_source_chars",
          "execution.max_command_chars",
          "execution.max_args",
          "execution.max_arg_chars",
        ]}
        overrides={{
          "execution.max_runtime_seconds": { min: 1 },
          "execution.max_args": { min: 1 },
        }}
        forceAdvanced={[
          "execution.max_source_chars",
          "execution.max_command_chars",
          "execution.max_args",
          "execution.max_arg_chars",
        ]}
      />
      <FieldSection
        title={t("settings.jobs")}
        description={t("settings.backgroundWorkSupervisedInsideATurnLiveJobsNever")}
        paths={["jobs.retained_capacity", "jobs.per_turn_live_capacity"]}
        overrides={{
          "jobs.retained_capacity": { min: 1 },
          "jobs.per_turn_live_capacity": { min: 1 },
        }}
      />
    </SettingsPageBody>
  );
}

/** The running generation's effective execution facts (read-only). */
function RunningStrip() {
  const { t } = useI18n();
  const active = useConfigDraftStore((s) => s.active);
  if (active === null) return null;
  const enabled = activeValue(active, "execution.enabled") === true;
  const interpreters = INTERPRETERS.filter(
    (id) => activeValue(active, `execution.interpreters.${id}.enabled`) === true,
  );
  return (
    <SectionCard
      title={t("settings.currentlyInEffect")}
      description={t("settings.valuesOfTheRunningGenerationChangesBelowActivateOn")}
      actions={
        enabled ? <Badge tone="green">{t("settings.enabled")}</Badge> : <Badge tone="gray">{t("settings.disabled")}</Badge>
      }
    >
      <div className="flex flex-wrap items-center gap-2 text-[12px] text-fg-muted">
        <span>{t("settings.interpreterLabel")}</span>
        {interpreters.length === 0 ? (
          <span className="text-fg-faint">{t("common.none")}</span>
        ) : (
          interpreters.map((id) => (
            <span key={id} className="rounded-md bg-hover px-1.5 py-0.5 font-mono text-[11px] text-fg">
              {id}
            </span>
          ))
        )}
      </div>
    </SectionCard>
  );
}
