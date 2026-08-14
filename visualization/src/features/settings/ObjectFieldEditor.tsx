import { Badge } from "../../components/ui/Badge";
import { Collapsible } from "../../components/ui/Collapsible";
import type { ConfigCatalog, ConfigStatus, JsonValue } from "../../types";
import { ConfigFieldGroups } from "./ConfigFieldGroups";
import {
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
  return (
    <>
      <ConfigFieldGroups
        fields={primary}
        status={status}
        catalog={catalog}
        canWrite={canWrite}
        savingPath={savingPath}
        onCommit={onCommit}
        onDelete={onDelete}
        selectOptions={selectOptions}
      />
      {advanced.length > 0 && (
        <div className="border-t border-line p-4">
          <Collapsible title="Advanced" meta={<Badge>{advanced.length}</Badge>}>
            <ConfigFieldGroups
              fields={advanced}
              status={status}
              catalog={catalog}
              canWrite={canWrite}
              savingPath={savingPath}
              onCommit={onCommit}
              onDelete={onDelete}
              selectOptions={selectOptions}
            />
          </Collapsible>
        </div>
      )}
      {readOnly.length > 0 && (
        <div className="border-t border-line p-4">
          <Collapsible title="Read-only" meta={<Badge>{readOnly.length}</Badge>}>
            <ConfigFieldGroups
              fields={readOnly}
              status={status}
              catalog={catalog}
              canWrite={false}
              savingPath={savingPath}
              onCommit={onCommit}
              onDelete={onDelete}
              selectOptions={selectOptions}
            />
          </Collapsible>
        </div>
      )}
    </>
  );
}
