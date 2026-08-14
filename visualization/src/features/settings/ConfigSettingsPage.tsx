import { AlertCircle } from "lucide-react";

import type { TinySoulClient } from "../../api/tinysoul";
import { Badge } from "../../components/ui/Badge";
import { EmptyState } from "../../components/ui/EmptyState";
import type { ConfigCatalog, ConfigStatus, JsonValue } from "../../types";
import { useAppStore } from "../../store/appStore";
import { useConfigStore } from "../../store/configStore";
import { ConfigFieldGroups } from "./ConfigFieldGroups";
import { SettingsDisclosureSection } from "./SettingsDisclosureSection";
import {
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
      <ConfigFieldGroups
        fields={primary}
        status={status}
        catalog={catalog}
        canWrite={canWrite}
        savingPath={savingPath}
        onCommit={commit}
      />
      {advanced.length > 0 && (
        <SettingsDisclosureSection title="Advanced" meta={<Badge>{advanced.length}</Badge>}>
          <ConfigFieldGroups
            fields={advanced}
            status={status}
            catalog={catalog}
            canWrite={canWrite}
            savingPath={savingPath}
            onCommit={commit}
          />
        </SettingsDisclosureSection>
      )}
      {readOnly.length > 0 && (
        <SettingsDisclosureSection title="Read-only" meta={<Badge>{readOnly.length}</Badge>}>
          <ConfigFieldGroups
            fields={readOnly}
            status={status}
            catalog={catalog}
            canWrite={false}
            savingPath={savingPath}
            onCommit={commit}
          />
        </SettingsDisclosureSection>
      )}
    </div>
  );
}

function shortId(value: string): string {
  return value.length > 12 ? value.slice(0, 12) : value;
}
