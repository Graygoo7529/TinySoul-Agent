/**
 * Part of the LLM Models settings page (split from LlmModelsPage).
 */

import { SettingsDisclosure } from "../../SettingsDisclosure";
import { useConnectionStore } from "../../../../store/connectionStore";
import {
  useEffect,
  useRef,
  useState,
} from "react";
import {
  X,
} from "lucide-react";
import type { JsonValue, ModelCapabilityLookup } from "../../../../api/v2/types";
import { Badge } from "../../../../components/ui/Badge";
import { Button, IconButton } from "../../../../components/ui/Button";
import { isPlainRecord } from "../../draft/model";
import { useConfigDraftStore } from "../../draft/store";
import {
  adapterRule,
  optionsForAdapter,
  adapterOptionAvailable,
  modelOptionChoices,
  normalizeAdapterOptions,
  retainAdapterOptions,
  type AdapterOptionRule,
  type CatalogField,
} from "../../draft/catalog";
import {
  type ProjectedObject,
} from "../collectionDrafts";
import {
  FieldRow,
  FieldSection,
  JsonObjectInput,
  NumberInput,
  SelectInput,
  TextInput,
  Toggle,
  selectClass,
} from "../modelControls";
import {
  clearObjectField,
  objectFieldDirty,
  setObjectField,
} from "../objectEditing";
import type { ProviderBinding } from "./ProviderChainSection";
import { ROOT } from "./LlmModelsPage";
import { t, translatedField as matchField, useI18n } from "../../../../i18n";

// ---------------------------------------------------------------------------
// Adapter options (adapter-conditional, explicit set/clear semantics)
// ---------------------------------------------------------------------------

export function AdapterOptionsSection({
  object,
  writeSource,
  adapter,
  bindings,
}: {
  object: ProjectedObject;
  writeSource: string | null;
  adapter: string;
  bindings: ProviderBinding[];
}) {
  const { t } = useI18n();
  const state = useConfigDraftStore();
  const clients = useConnectionStore((connection) => connection.clients);
  const [capabilityLoading, setCapabilityLoading] = useState(false);
  const [capabilityError, setCapabilityError] = useState<string | null>(null);
  const [capabilitySuggestion, setCapabilitySuggestion] = useState<ModelCapabilityLookup | null>(null);
  const [capabilityBinding, setCapabilityBinding] = useState(0);
  const capabilityRequest = useRef(0);
  const bindingIdentity = JSON.stringify(bindings);
  useEffect(() => {
    setCapabilityBinding(0);
  }, [object.id, bindingIdentity]);
  useEffect(() => {
    setCapabilityLoading(false);
    setCapabilitySuggestion(null);
    setCapabilityError(null);
    return () => { capabilityRequest.current += 1; };
  }, [object.id, adapter, bindingIdentity, capabilityBinding, clients]);
  const catalog = state.catalog;
  const rule = adapterRule(catalog, adapter);
  const adapterOptions = isPlainRecord(object.value.adapter_options)
    ? object.value.adapter_options
    : {};
  const variant =
    typeof adapterOptions.variant === "string" && adapterOptions.variant !== ""
      ? adapterOptions.variant
      : (rule?.variants[0]?.id ?? "");
  const allowed = new Map<string, AdapterOptionRule>();
  for (const option of optionsForAdapter(catalog, adapter, variant)) allowed.set(option.id, option);

  const setKeys = Object.keys(adapterOptions).filter((key) => key !== "variant" && key !== "choices" && key !== "choice_rules");
  const addable = [...allowed.keys()].filter(
    (key) => key !== "reasoning_effort" && !allowed.get(key)?.fixed && !Object.prototype.hasOwnProperty.call(adapterOptions, key) && adapterOptionAvailable(allowed.get(key)!, adapterOptions) &&
      (allowed.get(key)?.valueKind !== "enum" || modelOptionChoices(key, adapterOptions, allowed.get(key)!.choices, object.value.reasoning_effort).length > 0),
  );
  const optionMeta = (key: string) =>
    matchField(catalog, `${ROOT}.*.adapter_options.${key}`);

  const onVariantChange = (next: string) => {
    commitAdapterOption(object, writeSource, "variant", next);
  };

  return (
    <FieldSection
      title={t("settings.adapterOptions")}
      description={t("settings.adapterSpecificRequestBehaviorOnlyOptionsTheSelectedAdapter")}
    >
      {rule === null ? (
        <div className="px-5 py-3 text-[11px] text-fg-faint">
          {t("settings.noAdapterRules", { adapter })}
        </div>
      ) : (
        <>
          {rule.apiMode === "anthropic-messages" && bindings[capabilityBinding]?.provider && bindings[capabilityBinding]?.provider_model && (
            <div className="m-3 border-b border-border px-2 pb-3">
              {bindings.length > 1 && <SelectInput ariaLabel={t("settings.capabilityBinding")} value={String(capabilityBinding)}
                options={bindings.map((binding, index) => ({ value: String(index), label: `${binding.provider} / ${binding.provider_model}` }))}
                disabled={capabilityLoading}
                onChange={(value) => setCapabilityBinding(Number(value))} />}
              <Button size="sm" variant="secondary" disabled={!clients || capabilityLoading} loading={capabilityLoading} onClick={() => {
                if (!clients) return;
                const request = ++capabilityRequest.current;
                setCapabilityLoading(true);
                setCapabilityError(null);
                setCapabilitySuggestion(null);
                void clients.config.anthropicModelCapabilities(bindings[capabilityBinding]!.provider, bindings[capabilityBinding]!.provider_model)
                  .then(
                    (value) => { if (request === capabilityRequest.current) setCapabilitySuggestion(value); },
                    () => { if (request === capabilityRequest.current) setCapabilityError(t("settings.capabilityReadFailed")); },
                  )
                  .finally(() => { if (request === capabilityRequest.current) setCapabilityLoading(false); });
              }}>{t("settings.readAnthropicCapabilities")}</Button>
              {capabilityError && <p className="mt-2 text-xs text-danger">{capabilityError}</p>}
              {capabilitySuggestion !== null && <div className="mt-2 flex flex-wrap items-center gap-2 text-xs">
                <span>{anthropicSuggestionLabel(capabilitySuggestion)}</span>
                <Button size="sm" variant="ghost" onClick={() => {
                  const choices = { ...(isPlainRecord(adapterOptions.choices) ? adapterOptions.choices : {}) };
                  for (const key of ["thinking", "reasoning_effort"] as const) {
                    const capability = capabilitySuggestion[key];
                    if (capability !== null) {
                      choices[key] = capability.choices;
                    }
                  }
                  commitAdapterOption(object, writeSource, "choices", choices);
                }}>{t("settings.adoptSuggestions")}</Button>
              </div>}
            </div>
          )}
          {rule.variants.length > 0 && (
            <FieldRow
              title={optionMeta("variant")?.title ?? t("settings.adapterVariant")}
              description={optionMeta("variant")?.description}
              dirty={objectFieldDirty(ROOT, object.id, "adapter_options.variant")}
            >
              <SelectInput
                ariaLabel={t("settings.adapterVariant")}
                value={variant}
                options={rule.variants.map((item) => ({
                  value: item.id,
                  label:
                    optionMeta("variant")?.choices.find(
                      (choice) => choice.value === item.id,
                    )?.label ?? item.id,
                }))}
                onChange={onVariantChange}
              />
            </FieldRow>
          )}
          {setKeys.filter((key) => ["thinking", "native_replay", "prompt_cache_mode"].includes(key)).map((key) => (
            <AdapterOptionRow key={key} object={object} writeSource={writeSource} optionKey={key}
              rule={allowed.get(key) ?? null} meta={optionMeta(key)} unknown={!allowed.has(key)} />
          ))}
          <SettingsDisclosure title={t("settings.adapterOptions")} className="m-3" paths={[`${ROOT}.${object.id}.adapter_options`]}>
          {[...allowed.values()].filter((option) => option.fixed && adapterOptions[option.id] === undefined).map((option) => (
            <FieldRow key={option.id} title={optionMeta(option.id)?.title ?? option.id} description={t("settings.adapterFixed")}>
              <span className="text-xs">{String(option.default)}</span>
            </FieldRow>
          ))}
          {setKeys.filter((key) => !["thinking", "native_replay", "prompt_cache_mode"].includes(key)).map((key) => (
            <AdapterOptionRow
              key={key}
              object={object}
              writeSource={writeSource}
              optionKey={key}
              rule={allowed.get(key) ?? null}
              meta={optionMeta(key)}
              unknown={!allowed.has(key)}
            />
          ))}
          <SettingsDisclosure title={t("settings.modelChoices")} className="m-3" paths={[`${ROOT}.${object.id}.adapter_options.choices`]}>
            {[...allowed.values()].filter((option) => !option.fixed && (option.valueKind === "enum" || option.id === "reasoning_effort")).map((option) => {
              const candidates = isPlainRecord(adapterOptions.choices) ? adapterOptions.choices : {};
              const values = candidates[option.id];
              return <FieldRow key={option.id} title={option.id} description={t("settings.modelChoicesHint")} actions={
                <IconButton label={t("settings.clearChoice", { id: option.id })} onClick={() => {
                  const next = {...candidates}; delete next[option.id];
                  commitAdapterOption(object, writeSource, "choices", next);
                }}><X size={13} /></IconButton>
              }><TextInput ariaLabel={`choices.${option.id}`} value={Array.isArray(values) ? values.join(", ") : ""}
                placeholder={option.choices.join(", ") || "high, xhigh, max"}
                onCommit={(text) => commitAdapterOption(object, writeSource, "choices", {
                  ...candidates, [option.id]: [...new Set(text.split(",").map((item) => item.trim()).filter(Boolean))],
                })} /></FieldRow>;
            })}
            <FieldRow title={t("settings.conditionalChoices")} description={t("settings.conditionalChoicesHint")}>
              <JsonObjectInput ariaLabel={t("settings.choiceRules")} value={{rules: adapterOptions.choice_rules ?? []}}
                onCommit={(value) => commitAdapterOption(object, writeSource, "choice_rules", value.rules ?? [])} />
            </FieldRow>
          </SettingsDisclosure>
          {addable.length > 0 && (
            <div className="flex items-center justify-between gap-2 px-5 py-2.5">
              <span className="text-[11px] text-fg-faint">{t("settings.addAdapterOption")}</span>
              <select
                aria-label={t("settings.addAdapterOption")}
                value=""
                onChange={(event) => {
                  const key = event.target.value;
                  if (key === "") return;
                  const option = allowed.get(key);
                  const meta = optionMeta(key);
                  commitAdapterOption(
                    object,
                    writeSource,
                    key,
                    defaultOptionValue(
                      option?.valueKind ?? meta?.valueKind ?? "string",
                      modelOptionChoices(key, adapterOptions, option?.choices ?? [], object.value.reasoning_effort).map((value) => ({value})),
                      option?.minimum ?? undefined,
                    ),
                  );
                }}
                className={`${selectClass} max-w-56`}
              >
                <option value="">{t("settings.selectOption")}</option>
                {addable.map((key) => (
                  <option key={key} value={key}>
                    {optionMeta(key)?.title ?? key}
                  </option>
                ))}
              </select>
            </div>
          )}
          </SettingsDisclosure>
        </>
      )}
    </FieldSection>
  );
}

function anthropicSuggestionLabel(value: ModelCapabilityLookup): string {
  const thinking = value.thinking !== null
    ? value.thinking.choices.join(", ")
    : t("settings.noThinkingCapability");
  const effort = value.reasoning_effort !== null
    ? value.reasoning_effort.choices.join(", ")
    : t("settings.noEffortCapability");
  return t("settings.suggestedCapabilities", { thinking, effort });
}

export function commitAdapterOption(object: ProjectedObject, source: string | null, key: string, value: JsonValue | undefined) {
  const options = { ...(isPlainRecord(object.value.adapter_options) ? object.value.adapter_options : {}) };
  let effort = key === "reasoning_effort" ? value : object.value.reasoning_effort;
  if (key !== "reasoning_effort") {
    if (value === undefined) delete options[key]; else options[key] = value;
  }
  const catalog = useConfigDraftStore.getState().catalog;
  if (adapterRule(catalog, String(object.value.adapter))?.apiMode === "google-generate-content" && value !== undefined) {
    if (key === "thinking_budget_tokens") effort = undefined;
    if (key === "reasoning_effort") delete options.thinking_budget_tokens;
  }
  const rules = optionsForAdapter(catalog, String(object.value.adapter), typeof options.variant === "string" ? options.variant : undefined);
  const normalized = key === "variant"
    ? retainAdapterOptions(rules, options, effort)
    : normalizeAdapterOptions(rules, options, effort);
  setObjectField(ROOT, object, "adapter_options", normalized.options, source);
  if (normalized.effort !== undefined) {
    setObjectField(ROOT, object, "reasoning_effort", normalized.effort, source);
  } else if (object.value.reasoning_effort !== undefined) {
    clearObjectField(ROOT, object, "reasoning_effort", source);
  }
}

function AdapterOptionRow({
  object,
  writeSource,
  optionKey,
  rule,
  meta,
  unknown,
}: {
  object: ProjectedObject;
  writeSource: string | null;
  optionKey: string;
  rule: AdapterOptionRule | null;
  meta: CatalogField | null;
  unknown: boolean;
}) {
  const { t } = useI18n();
  const adapterOptions = isPlainRecord(object.value.adapter_options)
    ? object.value.adapter_options
    : {};
  const value = adapterOptions[optionKey];
  const subpath = `adapter_options.${optionKey}`;
  const dirty = objectFieldDirty(ROOT, object.id, subpath);
  return (
    <FieldRow
      title={
        <span className="flex items-center gap-1.5">
          {meta?.title ?? optionKey}
          {rule && <Badge tone="gray">{rule.source === "api-mode" ? "API" : rule.source === "variant" ? t("settings.variant") : t("settings.exclusive")}</Badge>}
          {unknown && (
            <Badge tone="yellow" title={t("settings.optionUnused")}>{t("settings.unused")}</Badge>
          )}
        </span>
      }
      description={meta?.description}
      dirty={dirty}
      actions={
        <IconButton
          label={`Clear ${meta?.title ?? optionKey}`}
          onClick={() => commitAdapterOption(object, writeSource, optionKey, undefined)}
        >
          <X size={13} />
        </IconButton>
      }
    >
      {rule?.fixed ? <span className="text-xs">{String(rule.default)} {t("settings.fixedOptionHint")}</span> : <AdapterOptionControl
        optionKey={optionKey}
        minimum={rule?.minimum ?? undefined}
        value={value}
        valueKind={rule?.valueKind ?? meta?.valueKind ?? "string"}
        choices={
          modelOptionChoices(optionKey, adapterOptions, rule?.choices ?? [], object.value.reasoning_effort).map((choice) => ({
            value: choice,
            label: choice,
          }))
        }
        onCommit={(next) =>
          commitAdapterOption(object, writeSource, optionKey, next)
        }
      />}
    </FieldRow>
  );
}

function AdapterOptionControl({
  optionKey,
  value,
  valueKind,
  minimum,
  choices,
  onCommit,
}: {
  optionKey: string;
  value: JsonValue | undefined;
  valueKind: string;
  minimum?: number;
  choices: { value: string; label: string }[];
  onCommit: (value: JsonValue) => void;
}) {
  switch (valueKind) {
    case "string_list":
      return <TextInput ariaLabel={optionKey} value={Array.isArray(value) ? value.join(", ") : ""}
        placeholder="high, xhigh, max" onCommit={(text) => onCommit([...new Set(text.split(",").map((item) => item.trim()).filter(Boolean))])} />;
    case "boolean":
      return (
        <Toggle
          ariaLabel={optionKey}
          checked={value === true}
          onChange={onCommit}
        />
      );
    case "integer":
      return (
        <NumberInput
          ariaLabel={optionKey}
          integer
          min={minimum}
          value={typeof value === "number" ? value : 0}
          onCommit={onCommit}
        />
      );
    case "number":
      return (
        <NumberInput
          ariaLabel={optionKey}
          value={typeof value === "number" ? value : 0}
          onCommit={onCommit}
        />
      );
    case "enum":
      return (
        <SelectInput
          ariaLabel={optionKey}
          value={typeof value === "string" ? value : ""}
          options={choices}
          onChange={onCommit}
        />
      );
    case "object":
      return (
        <JsonObjectInput
          ariaLabel={optionKey}
          value={isPlainRecord(value) ? value : {}}
          onCommit={onCommit}
        />
      );
    default:
      return (
        <TextInput
          ariaLabel={optionKey}
          value={typeof value === "string" ? value : ""}
          onCommit={onCommit}
        />
      );
  }
}

function defaultOptionValue(
  valueKind: string,
  choices: { value: string }[],
  minimum = 0,
): JsonValue {
  switch (valueKind) {
    case "string_list":
      return [];
    case "boolean":
      return false;
    case "integer":
    case "number":
      return minimum;
    case "object":
      return {};
    case "enum":
      return choices[0]?.value ?? "";
    default:
      return "";
  }
}

