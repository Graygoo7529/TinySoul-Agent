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
      <RunningStrip />
      <FieldSection
        title="Interpreters"
        description="Which shell/script interpreters the execution domain may use."
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
        title="Limits"
        description="Bounds of a single execution; the runtime enforces one total timeout per batch."
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
        title="Jobs"
        description="Background work supervised inside a turn; live jobs never exceed the retained capacity."
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
      title="Currently in effect"
      description="Values of the running generation; changes below activate on apply."
      actions={
        enabled ? <Badge tone="green">enabled</Badge> : <Badge tone="gray">disabled</Badge>
      }
    >
      <div className="flex flex-wrap items-center gap-2 text-[12px] text-fg-muted">
        <span>Interpreters:</span>
        {interpreters.length === 0 ? (
          <span className="text-fg-faint">none</span>
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
