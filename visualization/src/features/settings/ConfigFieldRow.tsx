import { Badge } from "../../components/ui/Badge";
import { IconButton } from "../../components/ui/Button";
import { Trash2 } from "lucide-react";
import type { ConfigCatalog, ConfigStatus, JsonValue } from "../../types";
import { ConfigValueControl } from "./ConfigValueControl";
import {
  referenceOptions,
  type ConfigSelectOption,
  type ConfigSettingField,
} from "./model";

export function ConfigFieldRow({
  field,
  status,
  catalog,
  canWrite,
  saving,
  onCommit,
  onDelete,
  selectOptions,
}: {
  field: ConfigSettingField;
  status: ConfigStatus;
  catalog: ConfigCatalog;
  canWrite: boolean;
  saving: boolean;
  onCommit: (field: ConfigSettingField, value: JsonValue) => Promise<void>;
  onDelete?: (field: ConfigSettingField) => Promise<void>;
  selectOptions?: ConfigSelectOption[];
}) {
  return (
    <div className="grid min-h-20 gap-3 px-5 py-3 md:grid-cols-[minmax(240px,1fr)_minmax(260px,420px)] md:items-center">
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-[13px] font-medium text-fg">{field.descriptor.title}</span>
          {!field.writable && <Badge tone="gray">Read only</Badge>}
          {field.overridden && <Badge tone="yellow">Overridden</Badge>}
        </div>
        <p className="mt-1 max-w-2xl text-[11px] leading-4 text-fg-muted">
          {field.descriptor.description}
        </p>
        <details className="mt-1.5 text-[10px] text-fg-faint">
          <summary className="cursor-pointer select-none">Details</summary>
          <div className="mt-1 space-y-0.5 font-mono break-all">
            <div>{field.path}</div>
            <div>{field.sourcePath || field.sourceId}</div>
            {field.overridden && (
              <div className="text-warning">
                Effective from {field.effectiveSource}: {formatValue(field.effectiveValue)}
              </div>
            )}
          </div>
        </details>
      </div>
      <div className="flex min-w-0 items-center justify-start gap-1.5 md:justify-end">
        <ConfigValueControl
          value={field.storedValue}
          descriptor={field.descriptor}
          selectOptions={
            selectOptions ?? referenceOptions(status, catalog, field.descriptor)
          }
          disabled={!canWrite || !field.writable}
          saving={saving}
          onCommit={(value) => onCommit(field, value)}
          />
        {onDelete && field.writable && (
          <IconButton label="Remove option" onClick={() => void onDelete(field)} disabled={!canWrite || saving}>
            <Trash2 size={14} />
          </IconButton>
        )}
      </div>
    </div>
  );
}

function formatValue(value: JsonValue): string {
  return typeof value === "string" ? value : JSON.stringify(value);
}
