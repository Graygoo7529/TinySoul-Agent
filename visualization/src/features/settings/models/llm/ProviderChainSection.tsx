/**
 * Part of the LLM Models settings page (split from LlmModelsPage).
 */

import { translatedField as matchField, useI18n } from "../../../../i18n";
import { ROOT } from "./LlmModelsPage";
import {
  AlertTriangle,
} from "lucide-react";
import type { JsonValue } from "../../../../api/v2/types";
import { Badge } from "../../../../components/ui/Badge";
import {
  Button,
} from "../../../../components/ui/Button";
import { isPlainRecord } from "../../draft/model";
import { useConfigDraftStore } from "../../draft/store";
import {
  providersForAdapter,
} from "../../draft/catalog";
import {
  fieldLockReason,
  moveItem,
  type ProjectedObject,
} from "../collectionDrafts";
import {
  FieldSection,
  OrderableListFooter,
  OrderableRow,
  SelectInput,
  TextInput,
} from "../modelControls";
import {
  setObjectField,
} from "../objectEditing";

// ---------------------------------------------------------------------------
// Provider chain
// ---------------------------------------------------------------------------

/** One provider chain row (a type alias so it stays assignable to JsonValue). */
export type ProviderBinding = {
  provider: string;
  provider_model: string;
};

export function readBindings(value: JsonValue | undefined): ProviderBinding[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item) => {
    if (!isPlainRecord(item)) return [];
    const provider = item.provider;
    const providerModel = item.provider_model;
    if (typeof provider !== "string" || typeof providerModel !== "string") return [];
    return [{ provider, provider_model: providerModel }];
  });
}

export function ProviderChainSection({
  object,
  providers,
  adapter,
  writeSource,
}: {
  object: ProjectedObject;
  providers: ProjectedObject[];
  adapter: string;
  writeSource: string | null;
}) {
  const { t } = useI18n();
  const state = useConfigDraftStore();
  const meta = matchField(state.catalog, `${ROOT}.*.providers`);
  const lock = fieldLockReason(state, `${ROOT}.${object.id}.providers`);
  const rows = readBindings(object.value.providers);
  const available = providersForAdapter(state.catalog, providers, adapter);
  const knownIds = new Set(providers.map((provider) => provider.id));

  const commit = (next: ProviderBinding[]) =>
    setObjectField(ROOT, object, "providers", next, writeSource);
  const addRow = () => {
    const provider = available.find(
      (item) => !rows.some((row) => row.provider === item.id),
    );
    if (provider === undefined) return;
    commit([
      ...rows,
      { provider: provider.id, provider_model: "" },
    ]);
  };

  return (
    <FieldSection
      title={meta?.title ?? t("settings.providerChain")}
      description={t("settings.tryProvidersInOrderForThisModelASuccessful")}
      meta={<Badge>{rows.length}</Badge>}
    >
      <div className="space-y-1.5 px-5 py-3">
        {rows.map((row, index) => (
          <OrderableRow
            key={`${row.provider}-${index}`}
            index={index}
            count={rows.length}
            disabled={lock !== null}
            ariaLabel={t("settings.chainPosition", { index: index + 1 })}
            onMove={(target) => commit(moveItem(rows, index, target))}
            onDrop={(source) => commit(moveItem(rows, source, index))}
            onRemove={
              rows.length > 1
                ? () => commit(rows.filter((_, itemIndex) => itemIndex !== index))
                : null
            }
          >
            <SelectInput
              ariaLabel={`Provider ${index + 1}`}
              value={row.provider}
              disabled={lock !== null}
              options={[
                ...(knownIds.has(row.provider)
                  ? []
                  : [{ value: row.provider, label: t("settings.missingId", { id: row.provider }) }]),
                ...available.map((provider) => ({
                  value: provider.id,
                  label: provider.id,
                  disabled: rows.some(
                    (item, itemIndex) =>
                      itemIndex !== index && item.provider === provider.id,
                  ),
                })),
              ]}
              onChange={(value) =>
                commit(
                  rows.map((item, itemIndex) =>
                    itemIndex === index ? { ...item, provider: value } : item,
                  ),
                )
              }
            />
            <TextInput
              ariaLabel={t("settings.providerModelNumber", { index: index + 1 })}
              value={row.provider_model}
              mono
              placeholder={t("settings.remoteModelId")}
              disabled={lock !== null}
              onCommit={(value) => {
                const trimmed = value.trim();
                commit(
                  rows.map((item, itemIndex) =>
                    itemIndex === index
                      ? { ...item, provider_model: trimmed }
                      : item,
                  ),
                );
              }}
            />
          </OrderableRow>
        ))}
        {rows.length === 0 && (
          <div className="text-[11px] text-danger">{t("settings.theChainIsEmptyThisModelCannotBeCalled")}</div>
        )}
        {available.length === 0 && (
          <div className="flex items-center gap-1.5 text-[11px] text-danger">
            <AlertTriangle size={13} /> {t("settings.noProviderForAdapter", { adapter })}
          </div>
        )}
        <OrderableListFooter>
          <Button
            size="xs"
            variant="outline"
            disabled={
              lock !== null || available.length <= rows.length || available.length === 0
            }
            onClick={addRow}
          >{t("settings.addProvider")}</Button>
        </OrderableListFooter>
      </div>
    </FieldSection>
  );
}

