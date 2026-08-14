import { useEffect, useMemo, useState } from "react";
import { AlertCircle } from "lucide-react";

import type { TinySoulClient } from "../../api/tinysoul";
import { Badge } from "../../components/ui/Badge";
import { Button } from "../../components/ui/Button";
import { EmptyState } from "../../components/ui/EmptyState";
import { useAppStore } from "../../store/appStore";
import { useConfigStore } from "../../store/configStore";
import type {
  ActionCatalog,
  ActionCatalogEntry,
  ActionCatalogSource,
  ActionDomainCatalogEntry,
  ConfigCatalog,
  ConfigDocumentFieldDescriptor,
  ConfigStatus,
  JsonValue,
} from "../../types";
import { ConfigValueControl } from "./ConfigValueControl";
import { SettingsDisclosureSection } from "./SettingsDisclosureSection";
import { SettingsGroupSection } from "./SettingsGroupSection";

export function ActionCatalogSettingsPage({
  client,
  status,
  catalog,
  actions,
}: {
  client: TinySoulClient;
  status: ConfigStatus;
  catalog: ConfigCatalog;
  actions: ActionCatalog;
}) {
  const [domainId, setDomainId] = useState(actions.domains[0]?.id ?? "");
  const domain = actions.domains.find((item) => item.id === domainId) ?? actions.domains[0];
  const domainActions = useMemo(
    () => actions.actions.filter((item) => item.domain === domain?.id),
    [actions.actions, domain?.id],
  );
  const [actionId, setActionId] = useState(domainActions[0]?.id ?? "");
  const action = domainActions.find((item) => item.id === actionId) ?? domainActions[0];

  useEffect(() => {
    if (!domain) setDomainId(actions.domains[0]?.id ?? "");
  }, [actions.domains, domain]);
  useEffect(() => {
    if (!domainActions.some((item) => item.id === actionId)) {
      setActionId(domainActions[0]?.id ?? "");
    }
  }, [actionId, domainActions]);

  if (!domain) return <EmptyState title="No Action domains configured" />;

  return (
    <div className="grid min-h-full min-w-0 grid-cols-1 lg:grid-cols-[210px_minmax(0,1fr)]">
      <aside className="border-b border-line bg-bg-sunken/25 lg:sticky lg:top-0 lg:h-[calc(100vh-8.25rem)] lg:self-start lg:overflow-hidden lg:border-r lg:border-b-0">
        <div className="border-b border-line px-3 py-2.5">
          <div className="text-[12px] font-semibold text-fg">Domains</div>
          <div className="text-[10px] text-fg-faint">{actions.domains.length} configured</div>
        </div>
        <div className="flex gap-1 overflow-x-auto p-2 lg:block lg:max-h-[calc(100vh-11.5rem)] lg:space-y-1 lg:overflow-y-auto">
          {actions.domains.map((item) => (
            <button
              key={item.id}
              type="button"
              onClick={() => setDomainId(item.id)}
              className={`min-w-44 rounded-md px-2.5 py-2 text-left transition-colors lg:w-full ${
                item.id === domain.id ? "bg-active text-accent" : "hover:bg-hover"
              }`}
            >
              <div className="flex items-center gap-2">
                <span className="min-w-0 flex-1 truncate font-mono text-[11px] font-medium">{item.id}</span>
                <AvailabilityDot available={item.available} />
              </div>
              <div className="mt-1 truncate text-[10px] text-fg-faint">{item.action_count} Actions</div>
              <p className="mt-1 line-clamp-2 text-[10px] leading-4 text-fg-muted">{item.description}</p>
            </button>
          ))}
        </div>
      </aside>
      <main className="min-w-0">
        <DomainEditor client={client} status={status} catalog={catalog} domain={domain} />
        <section className="border-t border-line">
          <header className="flex items-center justify-between border-b border-line bg-bg-sunken/40 px-5 py-3">
            <div>
              <h2 className="text-[14px] font-semibold text-fg">Actions</h2>
              <p className="mt-0.5 text-[10px] text-fg-faint">{domain.id}</p>
            </div>
            <Badge>{domainActions.length}</Badge>
          </header>
          <div className="grid min-w-0 grid-cols-1 xl:grid-cols-[240px_minmax(0,1fr)]">
            <div className="flex gap-1 overflow-x-auto border-b border-line p-2 xl:block xl:border-r xl:border-b-0">
              {domainActions.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => setActionId(item.id)}
                  className={`min-w-52 rounded-md px-2.5 py-2 text-left transition-colors xl:w-full ${
                    item.id === action?.id ? "bg-active text-accent" : "hover:bg-hover"
                  }`}
                >
                  <div className="flex items-center gap-2">
                    <span className="min-w-0 flex-1 truncate font-mono text-[11px] font-medium">{item.id}</span>
                    <ActionAvailabilityDot action={item} />
                  </div>
                  <div className="mt-1 flex gap-1.5 text-[10px] text-fg-faint">
                    <span>{item.backend.kind}</span><span>·</span><span>{timeoutLabel(item)}</span>
                  </div>
                </button>
              ))}
            </div>
            {action ? (
              <ActionEditor client={client} status={status} catalog={catalog} action={action} />
            ) : (
              <EmptyState title="No Actions in this domain" />
            )}
          </div>
        </section>
      </main>
    </div>
  );
}

function DomainEditor({ client, status, catalog, domain }: {
  client: TinySoulClient;
  status: ConfigStatus;
  catalog: ConfigCatalog;
  domain: ActionDomainCatalogEntry;
}) {
  return (
    <section>
      <header className="flex min-h-14 items-center gap-3 border-b border-line px-5 py-2.5">
        <h2 className="min-w-0 flex-1 truncate font-mono text-[14px] font-semibold text-fg">{domain.id}</h2>
        <Badge>{domain.available ? "Available" : "Unavailable"}</Badge>
      </header>
      <WriteNotice status={status} />
      <SettingsGroupSection {...groupProps(catalog, "action_catalog.domain")}>
        <DocumentField client={client} status={status} catalog={catalog} source={domain.source} kind="domain" path="description" value={domain.description} />
        <DocumentField client={client} status={status} catalog={catalog} source={domain.source} kind="domain" path="selection_hint" value={domain.selection_hint} />
      </SettingsGroupSection>
      <SettingsDisclosureSection title={groupTitle(catalog, "action_catalog.runtime")}>
        <DocumentField client={client} status={status} catalog={catalog} source={domain.source} kind="domain" path="runtime.enabled" value={domain.runtime.enabled} />
        <div className="flex items-center justify-end gap-2 border-t border-line px-5 py-2.5 text-[10px] text-fg-faint">
          <span>Default source: {domain.runtime.enabled_source}</span>
          {domain.runtime.enabled_source === "domain" && domain.source && (
            <DeleteFieldButton client={client} status={status} source={domain.source} path="runtime.enabled" label="Use built-in default" success="Built-in Action default active" />
          )}
        </div>
        <DocumentField client={client} status={status} catalog={catalog} source={domain.source} kind="domain" path="runtime.timeout_seconds" value={domain.runtime.timeout_seconds} />
        {domain.runtime.timeout_seconds !== null && domain.source && (
          <div className="flex justify-end border-t border-line px-5 py-2.5">
            <DeleteFieldButton client={client} status={status} source={domain.source} path="runtime.timeout_seconds" label="Clear default timeout" success="Domain timeout cleared" />
          </div>
        )}
      </SettingsDisclosureSection>
      <SettingsDisclosureSection title={groupTitle(catalog, "action_catalog.contract")}>
        <ReadOnlyField descriptor={descriptorFor(catalog, "domain", "name")} value={domain.id} />
        <ReadOnlyField descriptor={descriptorFor(catalog, "domain", "runtime.parallel_policy")} value={domain.runtime.parallel_policy} />
        <ReadOnlyField descriptor={descriptorFor(catalog, "domain", "runtime.hooks")} value={domain.runtime.hooks} />
        <ReadOnlyField descriptor={descriptorFor(catalog, "domain", "runtime.result.trace_mode")} value={domain.runtime.trace_mode} />
      </SettingsDisclosureSection>
    </section>
  );
}

function ActionEditor({ client, status, catalog, action }: {
  client: TinySoulClient;
  status: ConfigStatus;
  catalog: ConfigCatalog;
  action: ActionCatalogEntry;
}) {
  const timeoutDescriptor = descriptorFor(catalog, "action", "runtime.timeout_seconds");
  const waitPolicyFields = catalog.document_fields
    .filter(
      (field) => field.document_set === "action.catalog"
        && field.document_kind === "action"
        && field.group === "action_catalog.wait_policy"
        && isEditablePath(action.source, field.path),
    )
    .flatMap((field) => {
      const value = valueAtPath(action, field.path);
      return value === undefined ? [] : [{ path: field.path, value }];
    });
  return (
    <div className="min-w-0">
      <header className="flex min-h-14 items-center gap-3 border-b border-line px-5 py-2.5">
        <h3 className="min-w-0 flex-1 truncate font-mono text-[13px] font-semibold text-fg">{action.id}</h3>
        <ActionAvailabilityBadges action={action} />
      </header>
      <SettingsGroupSection {...groupProps(catalog, "action_catalog.availability")}>
        <DocumentField client={client} status={status} catalog={catalog} source={action.source} kind="action" path="runtime.enabled" value={action.runtime.enabled} />
        <div className="flex flex-wrap items-center justify-end gap-2 border-t border-line px-5 py-2.5 text-[10px] text-fg-faint">
          <span>Policy source: {action.runtime.enabled_source}</span>
          <span>Runtime owner: {action.supported ? "supported" : "unsupported"}</span>
          {action.runtime.enabled_source === "action" && action.source && (
            <DeleteFieldButton client={client} status={status} source={action.source} path="runtime.enabled" label="Use domain default" success="Domain Action default active" />
          )}
        </div>
      </SettingsGroupSection>
      <SettingsGroupSection {...groupProps(catalog, "action_catalog.semantic")}>
        <DocumentField client={client} status={status} catalog={catalog} source={action.source} kind="action" path="tool.description" value={action.tool.description} />
        <DocumentField client={client} status={status} catalog={catalog} source={action.source} kind="action" path="semantic.use_when" value={action.semantic.use_when} />
        <DocumentField client={client} status={status} catalog={catalog} source={action.source} kind="action" path="semantic.avoid_when" value={action.semantic.avoid_when} />
      </SettingsGroupSection>
      {waitPolicyFields.length > 0 && (
        <SettingsGroupSection {...groupProps(catalog, "action_catalog.wait_policy")}>
          {waitPolicyFields.map(({ path, value }) => (
            <DocumentField key={path} client={client} status={status} catalog={catalog} source={action.source} kind="action" path={path} value={value} />
          ))}
        </SettingsGroupSection>
      )}
      <SettingsDisclosureSection title="Advanced" meta={<Badge>3</Badge>}>
        <DocumentField client={client} status={status} catalog={catalog} source={action.source} kind="action" path="semantic.effects" value={action.semantic.effects} />
        <DocumentField client={client} status={status} catalog={catalog} source={action.source} kind="action" path="semantic.examples" value={action.semantic.examples} />
        {timeoutDescriptor && (
          <div>
            <DocumentField client={client} status={status} catalog={catalog} source={action.source} kind="action" path="runtime.timeout_seconds" value={action.runtime.timeout_seconds} />
            <div className="flex items-center justify-end gap-2 border-t border-line px-5 py-2.5 text-[10px] text-fg-faint">
              <span>Effective source: {action.runtime.timeout_source}</span>
              {action.runtime.timeout_source === "action" && action.source && (
                <DeleteFieldButton client={client} status={status} source={action.source} path="runtime.timeout_seconds" label="Use inherited timeout" success="Inherited timeout active" />
              )}
            </div>
          </div>
        )}
      </SettingsDisclosureSection>
      <SettingsDisclosureSection title={groupTitle(catalog, "action_catalog.contract")}>
        <ReadOnlyField descriptor={descriptorFor(catalog, "action", "name")} value={action.id} />
        <ReadOnlyField descriptor={descriptorFor(catalog, "action", "domain")} value={action.domain} />
        <ReadOnlyField descriptor={descriptorFor(catalog, "action", "tool.schema")} value={action.tool.schema} />
        <ReadOnlyField descriptor={descriptorFor(catalog, "action", "runtime.parallel_policy")} value={action.runtime.parallel_policy} />
        <ReadOnlyField descriptor={descriptorFor(catalog, "action", "runtime.hooks")} value={action.runtime.hooks} />
        <ReadOnlyField descriptor={descriptorFor(catalog, "action", "runtime.result.trace_mode")} value={action.runtime.trace_mode} />
        <ReadOnlyField descriptor={descriptorFor(catalog, "action", "backend")} value={action.backend} />
      </SettingsDisclosureSection>
    </div>
  );
}

function DocumentField({ client, status, catalog, source, kind, path, value }: {
  client: TinySoulClient;
  status: ConfigStatus;
  catalog: ConfigCatalog;
  source: ActionCatalogSource | null;
  kind: "domain" | "action";
  path: string;
  value: JsonValue;
}) {
  const descriptor = descriptorFor(catalog, kind, path);
  const patch = useConfigStore((state) => state.patch);
  const savingPath = useConfigStore((state) => state.savingPath);
  const pushToast = useAppStore((state) => state.pushToast);
  if (!descriptor) return null;
  const editable = isEditablePath(source, path);
  const canWrite = Boolean(editable && status.activity.can_write && !savingPath);
  const commit = async (next: JsonValue) => {
    if (!source || !editable) return;
    try {
      const result = await patch(client, { source_id: source.source_id, path, op: "set", value: next });
      pushToast("success", `Action Catalog active · ${shortId(result.generation_id)}`);
    } catch (error) {
      pushToast("error", error instanceof Error ? error.message : String(error));
    }
  };
  return (
    <div className="grid min-w-0 gap-3 border-t border-line px-5 py-3 first:border-t-0 md:grid-cols-[minmax(180px,0.8fr)_minmax(260px,1.2fr)] md:items-start">
      <div className="min-w-0">
        <div className="text-[12px] font-medium text-fg">{descriptor.title}</div>
        <p className="mt-0.5 text-[10px] leading-4 text-fg-muted">{descriptor.description}</p>
      </div>
      {descriptor.value_kind === "enum_list" && Array.isArray(value) ? (
        <div className="flex min-h-8 flex-wrap items-center gap-x-4 gap-y-2">
          {descriptor.choices?.map((choice) => {
            const selected = value.includes(choice.value);
            return (
              <label key={choice.value} className="flex items-center gap-1.5 text-[11px] text-fg-muted">
                <input
                  type="checkbox"
                  checked={selected}
                  disabled={!canWrite}
                  onChange={() => void commit(
                    selected
                      ? value.filter((item) => item !== choice.value)
                      : [...value, choice.value],
                  )}
                  className="focus-ring h-3.5 w-3.5 accent-accent"
                />
                {choice.label}
              </label>
            );
          })}
        </div>
      ) : (
        <ConfigValueControl value={value} descriptor={descriptor} disabled={!canWrite} saving={savingPath === path} onCommit={commit} />
      )}
    </div>
  );
}

function ReadOnlyField({ descriptor, value }: { descriptor?: ConfigDocumentFieldDescriptor; value: JsonValue }) {
  if (!descriptor) return null;
  const text = typeof value === "string" ? value : JSON.stringify(value, null, 2);
  return (
    <div className="grid min-w-0 gap-3 border-t border-line px-5 py-3 first:border-t-0 md:grid-cols-[minmax(180px,0.8fr)_minmax(260px,1.2fr)]">
      <div>
        <div className="text-[12px] font-medium text-fg">{descriptor.title}</div>
        <p className="mt-0.5 text-[10px] leading-4 text-fg-muted">{descriptor.description}</p>
      </div>
      <pre className="max-h-56 min-w-0 overflow-auto whitespace-pre-wrap break-all rounded-md border border-line bg-bg-sunken/40 p-2.5 text-[10px] leading-4 text-fg-muted">{text}</pre>
    </div>
  );
}

function DeleteFieldButton({ client, status, source, path, label, success }: {
  client: TinySoulClient;
  status: ConfigStatus;
  source: ActionCatalogSource;
  path: string;
  label: string;
  success: string;
}) {
  const patch = useConfigStore((state) => state.patch);
  const savingPath = useConfigStore((state) => state.savingPath);
  const pushToast = useAppStore((state) => state.pushToast);
  return (
    <Button
      size="xs"
      variant="outline"
      disabled={!isEditablePath(source, path) || !status.activity.can_write || Boolean(savingPath)}
      onClick={async () => {
        if (!isEditablePath(source, path)) return;
        try {
          const result = await patch(client, { source_id: source.source_id, path, op: "delete" });
          pushToast("success", `${success} · ${shortId(result.generation_id)}`);
        } catch (error) {
          pushToast("error", error instanceof Error ? error.message : String(error));
        }
      }}
    >
      {label}
    </Button>
  );
}

function WriteNotice({ status }: { status: ConfigStatus }) {
  if (status.activity.can_write) return null;
  return (
    <div className="flex items-center gap-2 border-b border-warning/30 bg-warning-soft px-5 py-2.5 text-[12px] text-warning">
      <AlertCircle size={14} /> {status.activity.reason || "Configuration is read-only while a turn is active."}
    </div>
  );
}

function AvailabilityDot({ available }: { available: boolean }) {
  return <span title={available ? "Available" : "Unavailable"} className={`h-1.5 w-1.5 shrink-0 rounded-full ${available ? "bg-success" : "bg-fg-faint"}`} />;
}

function ActionAvailabilityDot({ action }: { action: ActionCatalogEntry }) {
  if (action.available) {
    return <span title="Available" className="h-1.5 w-1.5 shrink-0 rounded-full bg-success" />;
  }
  return (
    <span className="flex shrink-0 items-center gap-1">
      {!action.runtime.enabled && (
        <span title="Disabled by Action policy" className="h-1.5 w-1.5 rounded-full bg-fg-faint" />
      )}
      {!action.supported && (
        <span title="Unsupported by runtime owner" className="h-1.5 w-1.5 rounded-full bg-warning" />
      )}
    </span>
  );
}

function ActionAvailabilityBadges({ action }: { action: ActionCatalogEntry }) {
  if (action.available) return <Badge tone="green">Available</Badge>;
  return (
    <div className="flex flex-wrap justify-end gap-1.5">
      {!action.runtime.enabled && <Badge>Disabled</Badge>}
      {!action.supported && <Badge tone="yellow">Unsupported</Badge>}
    </div>
  );
}

function descriptorFor(catalog: ConfigCatalog, kind: "domain" | "action", path: string) {
  return catalog.document_fields.find(
    (item) => item.document_set === "action.catalog" && item.document_kind === kind && item.path === path,
  );
}

export function isEditablePath(source: ActionCatalogSource | null, path: string): boolean {
  return Boolean(source?.editable_paths.includes(path));
}

function valueAtPath(root: unknown, path: string): JsonValue | undefined {
  let current: unknown = root;
  for (const segment of path.split(".")) {
    if (typeof current !== "object" || current === null || Array.isArray(current)) return undefined;
    current = (current as Record<string, unknown>)[segment];
  }
  return current as JsonValue | undefined;
}

function groupProps(catalog: ConfigCatalog, id: string) {
  const group = catalog.field_groups.find((item) => item.id === id);
  return { title: group?.title ?? id, description: group?.description };
}

function groupTitle(catalog: ConfigCatalog, id: string) {
  return catalog.field_groups.find((item) => item.id === id)?.title ?? id;
}

function timeoutLabel(action: ActionCatalogEntry) {
  return action.runtime.timeout_seconds === null ? "No timeout" : `${action.runtime.timeout_seconds}s`;
}

function shortId(value: string): string {
  return value.length > 12 ? value.slice(0, 12) : value;
}
