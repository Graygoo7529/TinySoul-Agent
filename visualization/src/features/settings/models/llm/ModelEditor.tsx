/**
 * Part of the LLM Models settings page (split from LlmModelsPage).
 */

import { useI18n } from "../../../../i18n";
import { translatedField as matchField } from "../../../../i18n";
import { ROOT } from "./LlmModelsPage";
import { SettingsDisclosure } from "../../SettingsDisclosure";
import {
  useState,
} from "react";
import {
  ArrowRightLeft,
} from "lucide-react";
import { Badge } from "../../../../components/ui/Badge";
import {
  Button,
} from "../../../../components/ui/Button";
import { isPlainRecord } from "../../draft/model";
import { useConfigDraftStore } from "../../draft/store";
import {
  adapterRule,
  providersForAdapter,
  optionsForAdapter,
  modelOptionChoices,
  retainAdapterOptions,
  type SettingsCatalog,
} from "../../draft/catalog";
import { useSettingsUiStore } from "../../uiStore";
import {
  fieldLockReason,
  projectCollection,
  stringField,
  stringListField,
  type ProjectedObject,
} from "../collectionDrafts";
import {
  ChoiceToggles,
  FieldRow,
  FieldSection,
  NumberInput,
  SelectInput,
  TextInput,
  Toggle,
  type SelectOption,
} from "../modelControls";
import { MODEL_CAPABILITIES } from "../capabilities";
import {
  clearObjectField,
  objectFieldDirty,
  setObjectField,
} from "../objectEditing";
import { ProviderChainSection, readBindings } from "./ProviderChainSection";
import { AdapterOptionsSection } from "./AdapterOptionsSection";
import { commitAdapterOption } from "./AdapterOptionsSection";
import { RequestOverridesSection } from "./RequestOverridesSection";
import { AdapterChangeModal } from "./AdapterChangeModal";

// ---------------------------------------------------------------------------
// Model editor
// ---------------------------------------------------------------------------

export function ModelEditor({
  object,
  providers,
  writeSource,
}: {
  object: ProjectedObject;
  providers: ProjectedObject[];
  writeSource: string | null;
}) {
  const { t } = useI18n();
  const state = useConfigDraftStore();
  const catalog = state.catalog;
  const navigateTo = useSettingsUiStore((ui) => ui.navigateTo);
  const [adapterChange, setAdapterChange] = useState<{
    adapter: string;
    providerId: string;
  } | null>(null);

  const field = (subpath: string) => ({
    meta: matchField(catalog, `${ROOT}.*.${subpath}`),
    dirty: objectFieldDirty(ROOT, object.id, subpath),
    lock: fieldLockReason(state, `${ROOT}.${object.id}.${subpath}`),
  });

  const adapter = stringField(object.value, "adapter");
  const adapterOptions = isPlainRecord(object.value.adapter_options)
    ? object.value.adapter_options
    : {};
  const providerAdapters = new Set((catalog?.adapterRules ?? []).filter((rule) => providersForAdapter(catalog, providers, rule.id).length > 0).map((rule) => rule.id));
  const adapterField = field("adapter");
  const adapterChoices: SelectOption[] = (adapterField.meta?.choices ?? []).map(
    (choice) => ({
      value: choice.value,
      label: choice.label,
      group: adapterRule(catalog, choice.value)?.apiMode,
      disabled: !providerAdapters.has(choice.value),
    }),
  );
  const adapterLocked = adapterField.lock !== null;

  const onAdapterSelect = (next: string) => {
    if (next === adapter) return;
    const matching = providersForAdapter(catalog, providers, next);
    const first = matching[0];
    if (first === undefined) return; // the disabled option cannot be chosen
    setAdapterChange({ adapter: next, providerId: first.id });
  };

  return (
    <div>
      <FieldSection
        title={t("settings.identity")}
        description={t("settings.howThisModelIsReachedAndWhereItAppears")}
      >
        <FieldRow
          title={adapterField.meta?.title ?? "Adapter"}
          description={
            adapterField.lock ??
            adapterField.meta?.description
          }
          dirty={adapterField.dirty}
        >
          <div className="flex items-center gap-1.5">
            <SelectInput
              ariaLabel={t("settings.adapter")}
              value={adapter}
              disabled={adapterLocked}
              options={adapterChoices}
              onChange={onAdapterSelect}
            />
            {!adapterLocked && (
              <ArrowRightLeft size={13} className="shrink-0 text-fg-faint" />
            )}
          </div>
        </FieldRow>
        <FieldRow title={t("settings.apiMode")}>
          <span className="font-mono text-xs">{adapterRule(catalog, adapter)?.apiMode}</span>
          {adapterRule(catalog, adapter)?.runtimeAvailable === false && <Badge tone="yellow">{t("settings.notCallable")}</Badge>}
        </FieldRow>
        {optionsForAdapter(catalog, adapter, stringField(adapterOptions, "variant")).some((option) => option.id === "reasoning_effort") &&
          <FieldRow title={t("settings.reasoningEffort")} description={t("settings.reasoningEffortHint")} dirty={field("reasoning_effort").dirty}>
            <SelectInput ariaLabel={t("settings.reasoningEffort")} value={stringField(object.value, "reasoning_effort")}
              emptyLabel={t("settings.remoteDefault")} options={modelOptionChoices("reasoning_effort", adapterOptions, [], object.value.reasoning_effort).map((value) => ({value, label: value}))}
              onChange={(value) => commitAdapterOption(object, writeSource, "reasoning_effort", value || undefined)} />
            {typeof object.value.reasoning_effort === "string" && !modelOptionChoices("reasoning_effort", adapterOptions, [], object.value.reasoning_effort).includes(object.value.reasoning_effort) &&
              <span className="text-xs text-danger">{t("settings.reasoningEffortInvalid")}</span>}
          </FieldRow>}
      </FieldSection>

      <ProviderChainSection
        object={object}
        providers={providers}
        adapter={adapter}
        writeSource={writeSource}
      />

      <FieldSection
        title={t("settings.capabilities")}
        description={t("settings.whatTinysoulMayRelyOnWhenRoutingTasksTo")}
      >
        <FieldRow
          title={field("context_window_tokens").meta?.title ?? t("settings.contextWindow")}
          description={field("context_window_tokens").meta?.description}
          dirty={field("context_window_tokens").dirty}
        >
          <NumberInput
            ariaLabel={t("settings.contextWindowTokens")}
            integer
            min={1}
            suffix="tokens"
            value={
              typeof object.value.context_window_tokens === "number"
                ? object.value.context_window_tokens
                : 0
            }
            disabled={field("context_window_tokens").lock !== null}
            onCommit={(value) =>
              setObjectField(
                ROOT,
                object,
                "context_window_tokens",
                value,
                writeSource,
              )
            }
          />
        </FieldRow>
        <Button variant="ghost" size="sm" onClick={() => navigateTo("context")}>
          {t("settings.configureTheGlobalWindowLimit")}
        </Button>
        <FieldRow
          title={t("settings.featureCapabilities")}
          description={field("capabilities").meta?.description}
          dirty={field("capabilities").dirty}
        >
          <ChoiceToggles
            options={MODEL_CAPABILITIES.map(({ value, labelId }) => ({ value, label: t(labelId) }))}
            values={stringListField(object.value, "capabilities")}
            disabled={field("capabilities").lock !== null}
            onCommit={(values) =>
              setObjectField(ROOT, object, "capabilities", values, writeSource)
            }
          />
        </FieldRow>
      </FieldSection>

      <AdapterOptionsSection
        object={object}
        writeSource={writeSource}
        adapter={adapter}
        bindings={readBindings(object.value.providers)}
      />
      <SettingsDisclosure title={t("settings.listDisplay")} className="m-3" paths={[`${ROOT}.${object.id}.family`, `${ROOT}.${object.id}.collapsed`]}>
        <FieldRow
          title={field("family").meta?.title ?? "Family"}
          description={field("family").meta?.description}
          dirty={field("family").dirty}
        >
          <TextInput
            ariaLabel={t("settings.family")}
            value={stringField(object.value, "family")}
            placeholder={t("settings.displayGroup")}
            disabled={field("family").lock !== null}
            onCommit={(value) =>
              setObjectField(ROOT, object, "family", value.trim(), writeSource)
            }
          />
        </FieldRow>
        <FieldRow
          title={field("collapsed").meta?.title ?? "Collapsed"}
          description={field("collapsed").meta?.description}
          dirty={field("collapsed").dirty}
        >
          <Toggle
            ariaLabel={t("settings.collapsed")}
            checked={object.value.collapsed === true}
            disabled={field("collapsed").lock !== null}
            onChange={(next) =>
              setObjectField(ROOT, object, "collapsed", next, writeSource)
            }
          />
        </FieldRow>
      </SettingsDisclosure>
      <RequestOverridesSection object={object} writeSource={writeSource} />

      {adapterChange !== null && (
        <AdapterChangeModal
          object={object}
          change={adapterChange}
          providers={providers}
          onClose={() => setAdapterChange(null)}
          onConfirm={(providerId, retainOptions) => {
            activateAdapter(
              object,
              adapterChange.adapter,
              providerId,
              writeSource,
              state.catalog,
              retainOptions,
            );
            setAdapterChange(null);
          }}
        />
      )}
    </div>
  );
}

/** Retain compatible bindings and options in the same adapter-switch draft. */
function activateAdapter(
  object: ProjectedObject,
  adapter: string,
  providerId: string,
  writeSource: string | null,
  catalog: SettingsCatalog | null,
  retainOptions: boolean,
): void {
  const bindings = readBindings(object.value.providers);
  const compatible = new Set(
    providersForAdapter(
      catalog,
      projectCollection(useConfigDraftStore.getState(), "llm.providers"),
      adapter,
    ).map((item) => item.id),
  );
  const retained = bindings.filter((binding) => compatible.has(binding.provider));
  const rule = adapterRule(catalog, adapter);
  const oldOptions = retainOptions && isPlainRecord(object.value.adapter_options)
    ? object.value.adapter_options
    : {};
  const variant = rule?.variants.find((item) => item.id === oldOptions.variant)?.id
    ?? rule?.variants[0]?.id;
  const specs = optionsForAdapter(catalog, adapter, variant);
  const options = { ...oldOptions };
  if (variant) options.variant = variant; else delete options.variant;
  const normalized = retainAdapterOptions(specs, options, retainOptions ? object.value.reasoning_effort : undefined);
  setObjectField(ROOT, object, "adapter", adapter, writeSource);
  setObjectField(
    ROOT, object, "providers",
    retained.length > 0 ? retained : [{ provider: providerId, provider_model: "" }],
    writeSource,
  );
  setObjectField(ROOT, object, "adapter_options", normalized.options, writeSource);
  if (object.value.reasoning_effort !== undefined && normalized.effort === undefined) {
    clearObjectField(ROOT, object, "reasoning_effort", writeSource);
  }
}

