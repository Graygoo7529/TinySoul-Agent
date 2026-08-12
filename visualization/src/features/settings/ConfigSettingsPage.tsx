import { AlertCircle } from "lucide-react";

import type { TinySoulClient } from "../../api/tinysoul";
import type { ConfigStatus, JsonValue } from "../../types";
import { Badge } from "../../components/ui/Badge";
import { EmptyState } from "../../components/ui/EmptyState";
import { useAppStore } from "../../store/appStore";
import { useConfigStore } from "../../store/configStore";
import {
  configFieldsForPage,
  groupConfigFields,
  type ConfigSettingField,
  type SettingsPageId,
} from "./model";
import { ConfigValueControl } from "./ConfigValueControl";

export function ConfigSettingsPage({
  client,
  status,
  page,
}: {
  client: TinySoulClient;
  status: ConfigStatus;
  page: SettingsPageId;
}) {
  const savingPath = useConfigStore((state) => state.savingPath);
  const patch = useConfigStore((state) => state.patch);
  const pushToast = useAppStore((state) => state.pushToast);
  const groups = groupConfigFields(configFieldsForPage(status, page), page);
  const canWrite = status.activity.can_write && !savingPath;

  const commit = async (field: ConfigSettingField, value: JsonValue) => {
    try {
      const result = await patch(client, {
        source_id: field.sourceId,
        path: field.path,
        op: "set",
        value,
      });
      pushToast("success", `Configuration active · ${shortId(result.generation_id)}`);
    } catch (error) {
      pushToast("error", error instanceof Error ? error.message : String(error));
    }
  };

  return (
    <div>
      {!status.activity.can_write && (
        <div className="flex items-center gap-2 border-b border-warning/30 bg-warning-soft px-5 py-2.5 text-[12px] text-warning">
          <AlertCircle size={14} />
          {status.activity.reason || "Configuration is read-only while a turn is active."}
        </div>
      )}

      {groups.length === 0 ? (
        <EmptyState title="No settings in this section" />
      ) : (
        groups.map((group) => (
          <section key={group.id} className="border-b border-line last:border-b-0">
            <div className="flex h-11 items-center justify-between bg-bg-sunken/40 px-5">
              <h3 className="text-[12px] font-semibold text-fg-muted">{group.title}</h3>
              <Badge>{group.fields.length}</Badge>
            </div>
            <div className="divide-y divide-line">
              {group.fields.map((field) => (
                <div
                  key={`${field.sourceId}:${field.path}`}
                  className="grid min-h-16 gap-3 px-5 py-3 md:grid-cols-[minmax(220px,1fr)_minmax(260px,420px)] md:items-center"
                >
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="text-[13px] font-medium text-fg">{field.label}</span>
                      {!field.writable && <Badge tone="gray">Read only</Badge>}
                      {field.overridden && <Badge tone="yellow">Overridden</Badge>}
                    </div>
                    <div className="mt-0.5 truncate font-mono text-[10px] text-fg-faint" title={field.path}>
                      {field.path}
                    </div>
                    <div className="mt-1 truncate text-[10px] text-fg-faint" title={field.sourcePath}>
                      {field.sourcePath}
                    </div>
                    {field.overridden && (
                      <div
                        className="mt-1 truncate text-[10px] text-warning"
                        title={`${field.effectiveSource}: ${formatValue(field.effectiveValue)}`}
                      >
                        Effective from {field.effectiveSource}: {formatValue(field.effectiveValue)}
                      </div>
                    )}
                  </div>
                  <div className="flex justify-start md:justify-end">
                    <ConfigValueControl
                      value={field.storedValue}
                      disabled={!canWrite || !field.writable}
                      saving={savingPath === field.path}
                      onCommit={(value) => commit(field, value)}
                    />
                  </div>
                </div>
              ))}
            </div>
          </section>
        ))
      )}
    </div>
  );
}

function shortId(value: string): string {
  return value.length > 12 ? value.slice(0, 12) : value;
}

function formatValue(value: JsonValue): string {
  return typeof value === "string" ? value : JSON.stringify(value);
}
