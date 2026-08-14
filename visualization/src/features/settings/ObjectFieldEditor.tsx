import type { ReactNode } from "react";

import { Badge } from "../../components/ui/Badge";
import type { ConfigCatalog, ConfigStatus, JsonValue } from "../../types";
import { ConfigFieldGroups } from "./ConfigFieldGroups";
import { SettingsDisclosureSection } from "./SettingsDisclosureSection";
import {
  type ConfigSelectOption,
  type ConfigFieldEditLock,
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
  canDeleteField,
  selectOptions,
  advancedGroupFooters,
  editLock,
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
  advancedGroupFooters?: Partial<Record<string, ReactNode>>;
  editLock?: (field: ConfigSettingField) => ConfigFieldEditLock | undefined;
}) {
  const primary = fields.filter((field) => field.descriptor.importance === "primary" && field.writable);
  const advanced = fields.filter((field) => field.descriptor.importance === "advanced" && field.writable);
  const readOnly = fields.filter((field) => !field.writable);
  const hasAdvancedFooters = Object.values(advancedGroupFooters ?? {}).some(
    (footer) => footer !== null && footer !== undefined && footer !== false,
  );
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
        canDeleteField={canDeleteField}
        selectOptions={selectOptions}
        editLock={editLock}
      />
      {(advanced.length > 0 || hasAdvancedFooters) && (
        <SettingsDisclosureSection
          title="Advanced"
          meta={advanced.length > 0 ? <Badge>{advanced.length}</Badge> : undefined}
        >
          <ConfigFieldGroups
            fields={advanced}
            status={status}
            catalog={catalog}
            canWrite={canWrite}
            savingPath={savingPath}
            onCommit={onCommit}
            onDelete={onDelete}
            canDeleteField={canDeleteField}
            selectOptions={selectOptions}
            editLock={editLock}
            groupFooters={advancedGroupFooters}
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
            onCommit={onCommit}
            onDelete={onDelete}
            canDeleteField={canDeleteField}
            selectOptions={selectOptions}
            editLock={editLock}
          />
        </SettingsDisclosureSection>
      )}
    </>
  );
}
