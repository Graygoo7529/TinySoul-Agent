/**
 * Part of the LLM Models settings page (split from LlmModelsPage).
 */

import { translatedField as matchField, useI18n } from "../../../../i18n";
import { ROOT } from "./LlmModelsPage";
import { SettingsDisclosure } from "../../SettingsDisclosure";
import {
  X,
} from "lucide-react";
import { Button, IconButton } from "../../../../components/ui/Button";
import { isPlainRecord } from "../../draft/model";
import { useConfigDraftStore } from "../../draft/store";
import {
  type ProjectedObject,
} from "../collectionDrafts";
import {
  FieldRow,
  NumberInput,
} from "../modelControls";
import {
  clearObjectField,
  objectFieldDirty,
  setObjectField,
} from "../objectEditing";

// ---------------------------------------------------------------------------
// Request overrides (optional per-model request values)
// ---------------------------------------------------------------------------

export function RequestOverridesSection({
  object,
  writeSource,
}: {
  object: ProjectedObject;
  writeSource: string | null;
}) {
  const { t } = useI18n();
  const state = useConfigDraftStore();
  const overrides = isPlainRecord(object.value.request_overrides)
    ? object.value.request_overrides
    : {};
  const rows: {
    key: "temperature" | "top_p" | "max_output_tokens";
    integer: boolean;
    fallback: number;
  }[] = [
    { key: "temperature", integer: false, fallback: 0.3 },
    { key: "top_p", integer: false, fallback: 1 },
    { key: "max_output_tokens", integer: true, fallback: 32768 },
  ];
  return (
    <SettingsDisclosure title={t("settings.requestOverrides")} className="m-3" paths={[`${ROOT}.${object.id}.request_overrides`]}>
      {rows.map(({ key, integer, fallback }) => {
        const meta = matchField(state.catalog, `${ROOT}.*.request_overrides.${key}`);
        const set = Object.prototype.hasOwnProperty.call(overrides, key);
        const subpath = `request_overrides.${key}`;
        return (
          <FieldRow
            key={key}
            title={meta?.title ?? key}
            description={meta?.description}
            dirty={objectFieldDirty(ROOT, object.id, subpath)}
            actions={
              set ? (
                <IconButton
                  label={`Clear ${meta?.title ?? key}`}
                  onClick={() => clearObjectField(ROOT, object, subpath, writeSource)}
                >
                  <X size={13} />
                </IconButton>
              ) : undefined
            }
          >
            {set ? (
              <NumberInput
                ariaLabel={meta?.title ?? key}
                integer={integer}
                min={integer ? 1 : 0}
                value={typeof overrides[key] === "number" ? overrides[key] : fallback}
                onCommit={(value) =>
                  setObjectField(ROOT, object, subpath, value, writeSource)
                }
              />
            ) : (
              <div className="flex items-center justify-between gap-2">
                <span className="text-[11px] text-fg-faint">{t("settings.inheritsTheTaskChain")}</span>
                <Button
                  size="xs"
                  variant="outline"
                  onClick={() =>
                    setObjectField(ROOT, object, subpath, fallback, writeSource)
                  }
                >{t("settings.setOverride")}</Button>
              </div>
            )}
          </FieldRow>
        );
      })}
    </SettingsDisclosure>
  );
}

