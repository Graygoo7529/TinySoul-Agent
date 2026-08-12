import type { ConfigStatus } from "../../types";
import { Badge } from "../../components/ui/Badge";

export function OverviewSettingsPage({ status }: { status: ConfigStatus }) {
  return (
    <div>
      <OverviewSection title="Runtime">
        <Fact label="Generation" value={status.runtime.generation_id} mono />
        <Fact label="Activity" value={status.activity.state} />
        <Fact label="Activation" value={status.runtime.activation} />
        <div className="flex items-center justify-between gap-4 py-2.5">
          <span className="text-[12px] text-fg-muted">Write state</span>
          <Badge tone={status.activity.can_write ? "green" : "yellow"}>
            {status.activity.can_write ? "Writable" : "Read only"}
          </Badge>
        </div>
      </OverviewSection>

      <OverviewSection title="Configuration sources">
        {status.sources.map((source) => (
          <div key={source.id} className="grid gap-1 py-2.5 md:grid-cols-[180px_1fr_auto] md:items-center md:gap-4">
            <span className="text-[12px] font-medium text-fg">{source.kind}</span>
            <span className="truncate font-mono text-[10px] text-fg-faint" title={source.path}>
              {source.path}
            </span>
            <div className="flex items-center gap-1.5">
              <Badge tone={source.exists ? "green" : "gray"}>{source.exists ? "Found" : "Missing"}</Badge>
              <Badge>{Object.keys(source.values).length}</Badge>
            </div>
          </div>
        ))}
      </OverviewSection>

      <OverviewSection title="Endpoint host">
        <Fact label="Address" value={`${status.process_shell.endpoint.host}:${status.process_shell.endpoint.port}`} mono />
        <Fact label="Instance" value={status.process_shell.endpoint.instance_id} mono />
        <Fact label="Ownership" value={status.process_shell.reason} />
      </OverviewSection>
    </div>
  );
}

function OverviewSection({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="border-b border-line px-5 py-4 last:border-b-0">
      <h3 className="mb-2 text-[12px] font-semibold text-fg-muted">{title}</h3>
      <div className="divide-y divide-line">{children}</div>
    </section>
  );
}

function Fact({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="flex items-center justify-between gap-4 py-2.5">
      <span className="text-[12px] text-fg-muted">{label}</span>
      <span className={`min-w-0 truncate text-right text-[12px] text-fg ${mono ? "font-mono text-[11px]" : ""}`} title={value}>
        {value}
      </span>
    </div>
  );
}
