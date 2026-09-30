/**
 * System & Diagnostics settings (config-coverage §7): read-only process items
 * (endpoint listener, agent/config process fields) with their ownership
 * reason, the configuration source list, and the few genuinely writable
 * system fields (context.system_text / context.journal).
 */

import type { JsonObject } from "../../../api/v2/types";
import { Badge } from "../../../components/ui/Badge";
import { SectionCard } from "../../../components/ui/Card";
import { useConfigDraftStore } from "../draft/store";
import {
  FieldSection,
  ReadOnlyValue,
  SettingsPageBody,
} from "./controls";

const PROCESS_FIELDS = [
  "agent.interactive",
  "agent.exit_commands",
  "agent.stop_turn_commands",
  "agent.retained_outcomes",
  "agent.output.mode",
  "agent.output.model_max_chars",
  "config.include",
  "config.env_file",
  "config.document_sets",
];

export function SystemPage() {
  return (
    <SettingsPageBody>
      <ProcessShellCard />
      <SourcesCard />
      <SectionCard
        title="Process-owned fields"
        description="Declared by the process itself — the CLI launch, environment or overrides; they are never writable through the endpoint."
      >
        <div className="flex flex-col divide-y divide-line">
          {PROCESS_FIELDS.map((path) => (
            <ReadOnlyValue key={path} path={path} />
          ))}
        </div>
      </SectionCard>
      <FieldSection
        title="Writable system fields"
        description="Fixed system identity text and the optional Context journal content."
        paths={["context.system_text", "context.journal"]}
        forceAdvanced={["context.journal"]}
      />
    </SettingsPageBody>
  );
}

/** The endpoint listener projection; never editable through configuration. */
function ProcessShellCard() {
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
      title="Endpoint listener"
      description="Where this backend listens; the listener belongs to the process and never comes from configuration files."
      actions={<Badge tone="gray">process-owned</Badge>}
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
  const sources = useConfigDraftStore((s) => s.saved?.sources ?? []);
  return (
    <SectionCard
      title="Configuration sources"
      description="Every source the saved view was projected from, in precedence order."
    >
      <div className="space-y-1">
        {sources.map((source) => (
          <div key={source.id} className="flex items-center gap-2 text-[12px]">
            <span className="font-mono text-fg">{source.id}</span>
            <Badge tone="gray">{source.kind}</Badge>
            <span className="min-w-0 flex-1 truncate font-mono text-[11px] text-fg-faint">
              {source.path || "—"}
            </span>
            <span className="flex shrink-0 items-center gap-1">
              {!source.exists && <Badge tone="yellow">missing</Badge>}
              {source.writable ? (
                <Badge tone="green">writable</Badge>
              ) : (
                <Badge tone="gray">read-only</Badge>
              )}
            </span>
          </div>
        ))}
        {sources.length === 0 && (
          <div className="text-[12px] text-fg-faint">No sources projected.</div>
        )}
      </div>
    </SectionCard>
  );
}
