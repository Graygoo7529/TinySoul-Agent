import { t } from "../../../i18n";
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
import { FieldSection, SettingsPageBody } from "./controls";

const INTERPRETERS = ["python", "bash", "powershell", "cmd"] as const;

export function ExecutionPage() {
  return (
    <SettingsPageBody>
      <NetworkPolicyField path="execution.network" title="执行环境代理" />
      <details><summary className="cursor-pointer text-sm text-fg-muted">解释器代理覆盖</summary>
        {INTERPRETERS.map((id) => <NetworkPolicyField key={id} path={`execution.interpreters.${id}.network`} title={id} parentLabel="执行环境代理" />)}
        <p className="p-3 text-xs text-fg-muted">代理通过环境变量传入。PowerShell HTTP 命令需使用 PowerShell 7；其它程序依其自身支持情况使用代理。</p>
      </details>
      <RunningStrip />
      <FieldSection
        title={t("settings.text.8d3c148819e9")}
        description={t("settings.text.4c61fc29ec76")}
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
        title={t("settings.text.61a0ae3b849d")}
        description={t("settings.text.e0ac00adbeef")}
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
        title={t("settings.text.437736fdb5bb")}
        description={t("settings.text.4bf86d664941")}
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
  const active = useConfigDraftStore((s) => s.active);
  if (active === null) return null;
  const enabled = activeValue(active, "execution.enabled") === true;
  const interpreters = INTERPRETERS.filter(
    (id) => activeValue(active, `execution.interpreters.${id}.enabled`) === true,
  );
  return (
    <SectionCard
      title={t("settings.text.eb560f49da05")}
      description={t("settings.text.939d704eac5b")}
      actions={
        enabled ? <Badge tone="green">启用</Badge> : <Badge tone="gray">禁用</Badge>
      }
    >
      <div className="flex flex-wrap items-center gap-2 text-[12px] text-fg-muted">
        <span>解释器：</span>
        {interpreters.length === 0 ? (
          <span className="text-fg-faint">无</span>
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
