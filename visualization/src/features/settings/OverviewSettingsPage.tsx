import { useState, type ReactNode } from "react";
import { ChevronRight } from "lucide-react";

import type { ConfigCatalog, ConfigStatus } from "../../types";
import { Badge } from "../../components/ui/Badge";
import { Collapsible } from "../../components/ui/Collapsible";
import { descriptorForPath } from "./model";

export function OverviewSettingsPage({
  status,
  catalog,
}: {
  status: ConfigStatus;
  catalog: ConfigCatalog;
}) {
  const unsupported = Object.entries(status.fields).filter(
    ([path]) => !descriptorForPath(catalog, path),
  );
  const foundSources = status.sources.filter((source) => source.exists).length;
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

      <OverviewSection
        title="Configuration sources"
        defaultOpen={false}
        meta={
          <div className="flex items-center gap-1.5">
            <Badge>{status.sources.length} sources</Badge>
            <Badge tone={foundSources === status.sources.length ? "green" : "yellow"}>
              {foundSources} found
            </Badge>
          </div>
        }
      >
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

      {unsupported.length > 0 && (
        <div className="p-4">
          <Collapsible title="Unsupported configuration" meta={<Badge tone="yellow">{unsupported.length}</Badge>}>
            <div className="divide-y divide-line">
              {unsupported.map(([path, field]) => (
                <div key={path} className="py-2">
                  <div className="font-mono text-[10px] text-warning">{path}</div>
                  <div className="mt-0.5 truncate text-[10px] text-fg-faint">
                    {field.source} · {JSON.stringify(field.value)}
                  </div>
                </div>
              ))}
            </div>
          </Collapsible>
        </div>
      )}
    </div>
  );
}

function OverviewSection({
  title,
  children,
  defaultOpen,
  meta,
}: {
  title: string;
  children: ReactNode;
  defaultOpen?: boolean;
  meta?: ReactNode;
}) {
  const collapsible = defaultOpen !== undefined;
  const [open, setOpen] = useState(defaultOpen ?? true);
  return (
    <section className="border-b border-line last:border-b-0">
      {collapsible ? (
        <button
          type="button"
          aria-expanded={open}
          onClick={() => setOpen((current) => !current)}
          className="flex w-full items-center gap-2 px-5 py-4 text-left"
        >
          <ChevronRight
            size={14}
            className={`shrink-0 text-fg-faint transition-transform ${open ? "rotate-90" : ""}`}
          />
          <span className="min-w-0 flex-1 text-[13px] font-semibold text-fg-muted">{title}</span>
          {meta}
        </button>
      ) : (
        <div className="px-5 pt-4">
          <h3 className="text-[13px] font-semibold text-fg-muted">{title}</h3>
        </div>
      )}
      {open && <div className="divide-y divide-line px-5 pb-4">{children}</div>}
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
