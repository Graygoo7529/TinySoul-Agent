import { Badge } from "../../components/ui/Badge";
import { Collapsible } from "../../components/ui/Collapsible";
import type { ConfigCatalog, ConfigStatus, JsonValue } from "../../types";
import { ConfigFieldRow } from "./ConfigFieldRow";
import type { ConfigSettingField } from "./model";

export function ObjectFieldEditor({
  fields,
  status,
  catalog,
  canWrite,
  savingPath,
  onCommit,
}: {
  fields: ConfigSettingField[];
  status: ConfigStatus;
  catalog: ConfigCatalog;
  canWrite: boolean;
  savingPath: string | null;
  onCommit: (field: ConfigSettingField, value: JsonValue) => Promise<void>;
}) {
  const primary = fields.filter((field) => field.descriptor.importance === "primary" && field.writable);
  const advanced = fields.filter((field) => field.descriptor.importance === "advanced" && field.writable);
  const readOnly = fields.filter((field) => !field.writable);
  return (
    <>
      <div className="divide-y divide-line">
        {primary.map((field) => (
          <ConfigFieldRow
            key={field.path}
            field={field}
            status={status}
            catalog={catalog}
            canWrite={canWrite}
            saving={savingPath === field.path}
            onCommit={onCommit}
          />
        ))}
      </div>
      {advanced.length > 0 && (
        <div className="border-t border-line p-4">
          <Collapsible title="Advanced" meta={<Badge>{advanced.length}</Badge>}>
            <div className="-mx-3 -my-2.5 divide-y divide-line">
              {advanced.map((field) => (
                <ConfigFieldRow
                  key={field.path}
                  field={field}
                  status={status}
                  catalog={catalog}
                  canWrite={canWrite}
                  saving={savingPath === field.path}
                  onCommit={onCommit}
                />
              ))}
            </div>
          </Collapsible>
        </div>
      )}
      {readOnly.length > 0 && (
        <div className="border-t border-line p-4">
          <Collapsible title="Read-only" meta={<Badge>{readOnly.length}</Badge>}>
            <div className="-mx-3 -my-2.5 divide-y divide-line">
              {readOnly.map((field) => (
                <ConfigFieldRow
                  key={field.path}
                  field={field}
                  status={status}
                  catalog={catalog}
                  canWrite={false}
                  saving={savingPath === field.path}
                  onCommit={onCommit}
                />
              ))}
            </div>
          </Collapsible>
        </div>
      )}
    </>
  );
}
