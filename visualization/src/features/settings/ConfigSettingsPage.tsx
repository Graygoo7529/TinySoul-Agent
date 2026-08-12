import { AlertCircle } from "lucide-react";

import type { TinySoulClient } from "../../api/tinysoul";
import { Badge } from "../../components/ui/Badge";
import { Collapsible } from "../../components/ui/Collapsible";
import { EmptyState } from "../../components/ui/EmptyState";
import type { ConfigCatalog, ConfigStatus, JsonValue } from "../../types";
import { useAppStore } from "../../store/appStore";
import { useConfigStore } from "../../store/configStore";
import { ConfigFieldRow } from "./ConfigFieldRow";
import {
  groupSurfaceFields,
  surfaceFields,
  type ConfigSettingField,
} from "./model";

export function ConfigSettingsPage({
  client,
  status,
  catalog,
  surface,
}: {
  client: TinySoulClient;
  status: ConfigStatus;
  catalog: ConfigCatalog;
  surface: string;
}) {
  const savingPath = useConfigStore((state) => state.savingPath);
  const patch = useConfigStore((state) => state.patch);
  const pushToast = useAppStore((state) => state.pushToast);
  const fields = surfaceFields(status, catalog, surface);
  const writable = fields.filter((field) => field.writable);
  const primary = writable.filter((field) => field.descriptor.importance === "primary");
  const advanced = writable.filter((field) => field.descriptor.importance === "advanced");
  const readOnly = fields.filter((field) => !field.writable);
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

  if (fields.length === 0) return <EmptyState title="No settings in this section" />;

  return (
    <div>
      {!status.activity.can_write && (
        <div className="flex items-center gap-2 border-b border-warning/30 bg-warning-soft px-5 py-2.5 text-[12px] text-warning">
          <AlertCircle size={14} />
          {status.activity.reason || "Configuration is read-only while a turn is active."}
        </div>
      )}
      <FieldGroups
        fields={primary}
        surface={surface}
        status={status}
        catalog={catalog}
        canWrite={canWrite}
        savingPath={savingPath}
        onCommit={commit}
      />
      {advanced.length > 0 && (
        <div className="border-t border-line p-4">
          <Collapsible title="Advanced" meta={<Badge>{advanced.length}</Badge>}>
            <FieldGroups
              fields={advanced}
              surface={surface}
              status={status}
              catalog={catalog}
              canWrite={canWrite}
              savingPath={savingPath}
              onCommit={commit}
            />
          </Collapsible>
        </div>
      )}
      {readOnly.length > 0 && (
        <div className="border-t border-line p-4">
          <Collapsible title="Read-only" meta={<Badge>{readOnly.length}</Badge>}>
            <FieldGroups
              fields={readOnly}
              surface={surface}
              status={status}
              catalog={catalog}
              canWrite={false}
              savingPath={savingPath}
              onCommit={commit}
            />
          </Collapsible>
        </div>
      )}
    </div>
  );
}

function FieldGroups({
  fields,
  surface,
  status,
  catalog,
  canWrite,
  savingPath,
  onCommit,
}: {
  fields: ConfigSettingField[];
  surface: string;
  status: ConfigStatus;
  catalog: ConfigCatalog;
  canWrite: boolean;
  savingPath: string | null;
  onCommit: (field: ConfigSettingField, value: JsonValue) => Promise<void>;
}) {
  return (
    <>
      {groupSurfaceFields(fields, surface).map((group) => (
        <section key={group.id} className="border-b border-line last:border-b-0">
          <div className="flex h-10 items-center justify-between bg-bg-sunken/40 px-5">
            <h3 className="text-[12px] font-semibold text-fg-muted">{group.title}</h3>
            <Badge>{group.fields.length}</Badge>
          </div>
          <div className="divide-y divide-line">
            {group.fields.map((field) => (
              <ConfigFieldRow
                key={`${field.sourceId}:${field.path}`}
                field={field}
                status={status}
                catalog={catalog}
                canWrite={canWrite}
                saving={savingPath === field.path}
                onCommit={onCommit}
              />
            ))}
          </div>
        </section>
      ))}
    </>
  );
}

function shortId(value: string): string {
  return value.length > 12 ? value.slice(0, 12) : value;
}
