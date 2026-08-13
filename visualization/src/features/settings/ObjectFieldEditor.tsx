import { Badge } from "../../components/ui/Badge";
import { Collapsible } from "../../components/ui/Collapsible";
import type { ConfigCatalog, ConfigStatus, JsonValue } from "../../types";
import { ConfigFieldRow } from "./ConfigFieldRow";
import {
  groupSurfaceFields,
  type ConfigSelectOption,
  type ConfigSettingField,
} from "./model";

export function ObjectFieldEditor({
  fields,
  status,
  catalog,
  canWrite,
  savingPath,
  onCommit,
  onDelete,
  selectOptions,
}: {
  fields: ConfigSettingField[];
  status: ConfigStatus;
  catalog: ConfigCatalog;
  canWrite: boolean;
  savingPath: string | null;
  onCommit: (field: ConfigSettingField, value: JsonValue) => Promise<void>;
  onDelete?: (field: ConfigSettingField) => Promise<void>;
  selectOptions?: (field: ConfigSettingField) => ConfigSelectOption[] | undefined;
}) {
  const primary = fields.filter((field) => field.descriptor.importance === "primary" && field.writable);
  const advanced = fields.filter((field) => field.descriptor.importance === "advanced" && field.writable);
  const readOnly = fields.filter((field) => !field.writable);
  const primaryGroups = groupSurfaceFields(primary, catalog);
  const advancedGroups = groupSurfaceFields(advanced, catalog);
  const readOnlyGroups = groupSurfaceFields(readOnly, catalog);
  const renderGroups = (groups: ReturnType<typeof groupSurfaceFields>, writable: boolean) => (
    <div className="divide-y divide-line">
      {groups.map((group) => (
        <section key={group.id}>
          <div className="bg-bg-sunken/30 px-5 py-2.5">
            <div className="text-[11px] font-semibold text-fg">{group.title}</div>
            <div className="mt-0.5 text-[10px] text-fg-faint">{group.description}</div>
          </div>
          <div className="divide-y divide-line">
            {group.fields.map((field) => (
              <ConfigFieldRow
                key={field.path}
                field={field}
                status={status}
                catalog={catalog}
                canWrite={canWrite && writable}
                saving={savingPath === field.path}
                onCommit={onCommit}
                onDelete={onDelete}
                selectOptions={selectOptions?.(field)}
              />
            ))}
          </div>
        </section>
      ))}
    </div>
  );
  return (
    <>
      {renderGroups(primaryGroups, true)}
      {advanced.length > 0 && (
        <div className="border-t border-line p-4">
          <Collapsible title="Advanced" meta={<Badge>{advanced.length}</Badge>}>{renderGroups(advancedGroups, true)}</Collapsible>
        </div>
      )}
      {readOnly.length > 0 && (
        <div className="border-t border-line p-4">
          <Collapsible title="Read-only" meta={<Badge>{readOnly.length}</Badge>}>{renderGroups(readOnlyGroups, false)}</Collapsible>
        </div>
      )}
    </>
  );
}
