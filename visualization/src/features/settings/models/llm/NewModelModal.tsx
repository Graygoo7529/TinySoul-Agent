/**
 * Part of the LLM Models settings page (split from LlmModelsPage).
 */

import {
t,
  useI18n,
  translatedField as matchField,
} from "../../../../i18n";
import {
  useEffect,
  useState,
} from "react";
import type { JsonValue } from "../../../../api/v2/types";
import {
  Button,
} from "../../../../components/ui/Button";
import { Modal } from "../../../../components/ui/Modal";
import { useConfigDraftStore } from "../../draft/store";
import {
  adapterRule,
  providersForAdapter,
  type SettingsCatalog,
} from "../../draft/catalog";
import {
  cloneJsonValue,
  familyFileName,
  llmObjectIdError,
  resolveFamilySource,
  type FamilySourceTarget,
  type ProjectedObject,
} from "../collectionDrafts";
import {
  SelectInput,
  TextInput,
} from "../modelControls";

export function NewModelModal({
  open,
  onClose,
  existing,
  families,
  models,
  providers,
  template,
  catalog,
  onCreate,
}: {
  open: boolean;
  onClose: () => void;
  existing: string[];
  families: string[];
  models: ProjectedObject[];
  providers: ProjectedObject[];
  template: Record<string, JsonValue>;
  catalog: SettingsCatalog | null;
  onCreate: (id: string, value: Record<string, JsonValue>, target: Extract<FamilySourceTarget, { kind: "ready" }>) => void;
}) {
  useI18n();
  const state = useConfigDraftStore();
  const [id, setId] = useState("");
  const [family, setFamily] = useState("");
  const [newFamily, setNewFamily] = useState("");
  const [newFamilyFile, setNewFamilyFile] = useState("");
  const [adapter, setAdapter] = useState("");
  const [providerId, setProviderId] = useState("");
  const [providerModel, setProviderModel] = useState("");
  useEffect(() => {
    if (open) return;
    setId(""); setFamily(""); setNewFamily(""); setNewFamilyFile(""); setProviderModel("");
    setAdapter(""); setProviderId("");
  }, [open]);
  useEffect(() => {
    const matching = providersForAdapter(catalog, providers, adapter);
    if (matching.some((item) => item.id === providerId)) return;
    setProviderId(matching[0]?.id ?? "");
    setProviderModel("");
  }, [providers, providerId, adapter, catalog]);
  if (!open) return null;
  const chosenFamily = family === "__new__" ? newFamily.trim() : family;
  const idError = llmObjectIdError(id);
  const target = resolveFamilySource(state, models, chosenFamily, newFamilyFile);
  const matchingProviders = providersForAdapter(catalog, providers, adapter);
  const adapterChoices = (matchField(catalog, "llm.models.*.adapter")?.choices ?? []).map((choice) => ({
    value: choice.value,
    label: choice.label,
    group: adapterRule(catalog, choice.value)?.apiMode,
  }));
  const valid = id !== "" && idError === null && !existing.includes(id) && target.kind === "ready" &&
    matchingProviders.some((item) => item.id === providerId) && providerModel.trim() !== "" &&
    adapterChoices.some((choice) => choice.value === adapter);
  return (
    <Modal title={t("settings.newModel")} onClose={onClose}>
      <div className="space-y-3">
        <TextInput ariaLabel={t("settings.modelId")} value={id} onCommit={setId} placeholder="gpt-latest" mono />
        {idError !== null && <div className="text-[10px] text-danger">{idError}</div>}
        <SelectInput ariaLabel={t("settings.family")} value={family} options={[{ value: "", label: t("settings.chooseExistingFamily") }, ...families.map((item) => ({ value: item, label: item })), { value: "__new__", label: t("settings.newFamily") }]} onChange={(value) => { setFamily(value); setNewFamilyFile(""); }} />
        {family === "__new__" && <TextInput ariaLabel={t("settings.newFamilyName")} value={newFamily} onCommit={setNewFamily} placeholder="Qwen" />}
        {target.usesFileName && <TextInput ariaLabel={t("settings.familyFile")} value={newFamilyFile} onCommit={setNewFamilyFile} placeholder={familyFileName(chosenFamily) || "qwen"} mono />}
        {target.kind === "invalid" && <div className="text-[10px] text-danger">{target.message}</div>}
        <SelectInput ariaLabel={t("settings.adapter")} value={adapter} options={[{ value: "", label: t("settings.chooseAdapter") }, ...adapterChoices]} onChange={setAdapter} />
        <SelectInput ariaLabel={t("settings.provider")} value={providerId} options={[{ value: "", label: t("settings.chooseProvider") }, ...matchingProviders.map((item) => ({ value: item.id, label: item.id }))]} onChange={(value) => { setProviderId(value); setProviderModel(""); }} />
        {adapter !== "" && matchingProviders.length === 0 && <div className="text-[10px] text-fg-muted">{t("settings.addACompatibleProviderOnTheProvidersPage")}</div>}
        <TextInput ariaLabel={t("settings.providerModel")} value={providerModel} onCommit={setProviderModel} placeholder={t("settings.remoteModelName")} mono />
        {target.kind === "ready" && <div className="text-[11px] text-fg-faint">{t("settings.configFile")}{target.sourceId.replace(/^project:/, "")}</div>}
        <div className="flex justify-end gap-2 border-t border-line pt-3">
          <Button size="xs" variant="ghost" onClick={onClose}>{t("settings.cancel")}</Button>
          <Button size="xs" variant="primary" disabled={!valid} onClick={() => {
            if (target.kind !== "ready") return;
            const value = blankModelValue(adapter, providerId, template, catalog);
            value.family = chosenFamily;
            value.adapter = adapter;
            value.providers = [{ provider: providerId, provider_model: providerModel.trim() }];
            onCreate(id, value, target);
          }}>{t("settings.create")}</Button>
        </div>
      </div>
    </Modal>
  );
}

/** The starting value of a blank model created in the draft. */
function blankModelValue(
  adapter: string,
  providerId: string,
  template: Record<string, JsonValue>,
  catalog: SettingsCatalog | null,
): Record<string, JsonValue> {
  const value: Record<string, JsonValue> = {
    ...cloneJsonValue(template),
    adapter,
    providers: [
      { provider: providerId, provider_model: "" },
    ],
  };
  const rule = adapterRule(catalog, adapter);
  const firstVariant = rule?.variants[0]?.id;
  if (firstVariant !== undefined) {
    value.adapter_options = { variant: firstVariant };
  }
  return value;
}

