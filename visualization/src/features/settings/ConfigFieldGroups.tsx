import type { ReactNode } from "react";

import { Badge } from "../../components/ui/Badge";
import type { ConfigCatalog, ConfigStatus, JsonValue } from "../../types";
import { ConfigFieldRow } from "./ConfigFieldRow";
import { SettingsGroupSection } from "./SettingsGroupSection";
import {
  groupSurfaceFields,
  type ConfigFieldEditLock,
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
  canDeleteField,
  selectOptions,
  editLock,
  groupFooters,
}: {
  fields: ConfigSettingField[];
  status: ConfigStatus;
  catalog: ConfigCatalog;
  canWrite: boolean;
  savingPath: string | null;
  onCommit: (field: ConfigSettingField, value: JsonValue) => Promise<void>;
  onDelete?: (field: ConfigSettingField) => Promise<void>;
  canDeleteField?: (field: ConfigSettingField) => boolean;
  selectOptions?: (field: ConfigSettingField) => ConfigSelectOption[] | undefined;
  editLock?: (field: ConfigSettingField) => ConfigFieldEditLock | undefined;
  groupFooters?: Partial<Record<string, ReactNode>>;
}) {
  const footerGroupIds = new Set(
    Object.entries(groupFooters ?? {}).flatMap(([groupId, footer]) =>
      footer === null || footer === undefined || footer === false ? [] : [groupId],
    ),
  );
  return (
    <div>
      {groupSurfaceFields(fields, catalog, footerGroupIds).map((group) => (
        <SettingsGroupSection
          key={group.id}
          title={group.title}
          description={group.description}
          meta={<Badge>{group.fields.length}</Badge>}
        >
          {group.fields.length > 0 && (
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
                  deletable={canDeleteField?.(field) ?? Boolean(onDelete)}
                  selectOptions={selectOptions?.(field)}
                  editLock={editLock?.(field)}
                />
              ))}
            </div>
          )}
          {groupFooters?.[group.id]}
        </SettingsGroupSection>
      ))}
    </div>
  );
}
