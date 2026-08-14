import { Badge } from "../../components/ui/Badge";
import type { ConfigCatalog, ConfigStatus, JsonValue } from "../../types";
import { ConfigFieldRow } from "./ConfigFieldRow";
import { SettingsGroupSection } from "./SettingsGroupSection";
import {
  groupSurfaceFields,
  type ConfigSelectOption,
  type ConfigSettingField,
} from "./model";

export function ConfigFieldGroups({
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
  return (
    <div>
      {groupSurfaceFields(fields, catalog).map((group) => (
        <SettingsGroupSection
          key={group.id}
          title={group.title}
          description={group.description}
          meta={<Badge>{group.fields.length}</Badge>}
        >
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
                onDelete={onDelete}
                selectOptions={selectOptions?.(field)}
              />
            ))}
          </div>
        </SettingsGroupSection>
      ))}
    </div>
  );
}
