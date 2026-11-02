import { useUiPrefs, useUiPrefsStore } from "../store/uiPrefsStore";
import type { CatalogCollection, CatalogDocumentField, CatalogField, CatalogFieldGroup, CatalogSurface, SettingsCatalog } from "../features/settings/draft/catalog";
import { matchField } from "../features/settings/draft/catalog";
import { collectionText, documentText, fieldGroupText, fieldText, surfaceText } from "./catalog/zh-CN";
import { commonMessages as zhCommon } from "./messages/zh-CN/common";
import { commonMessages as enCommon } from "./messages/en-US/common";
import { settingsMessages as zhSettings } from "./messages/zh-CN/settings";
import { settingsMessages as enSettings } from "./messages/en-US/settings";
import { protocolMessages as zhProtocol } from "./protocol/zh-CN";
import { protocolMessages as enProtocol } from "./protocol/en-US";
import type { Locale, MessageParams } from "./types";

export type { Locale, MessageParams } from "./types";

const dictionaries = {
  "zh-CN": { ...zhCommon, ...zhSettings, ...zhProtocol },
  "en-US": { ...enCommon, ...enSettings, ...enProtocol },
} as const;

export type MessageId = keyof typeof dictionaries["zh-CN"];

export function effectiveLocale(): Locale {
  const state = useUiPrefsStore.getState();
  return state.pending.locale ?? state.saved.locale ?? "zh-CN";
}

function interpolate(value: string, params?: MessageParams): string {
  if (params === undefined) return value;
  return value.replace(/\{(\w+)\}/g, (full, key: string) =>
    Object.prototype.hasOwnProperty.call(params, key) ? String(params[key]) : full,
  );
}

/** Translate a fixed visualization-owned message ID. */
export function t(id: MessageId, params?: MessageParams, locale: Locale = effectiveLocale()): string {
  const selected = dictionaries[locale][id] ?? dictionaries["en-US"][id];
  return interpolate(selected ?? id, params);
}

/** Dynamic backend/user content must remain a raw display value. */
export function rawText(value: string): string {
  return value;
}

export function useI18n() {
  const { locale } = useUiPrefs();
  return { locale, t: (id: MessageId, params?: MessageParams) => t(id, params, locale) };
}

type FieldText = readonly [title: string, description: string];

const choiceText: Record<string, Record<string, string>> = {
  "llm.models.*.reasoning_effort": {
    low: "低",
    medium: "中",
    high: "高",
    xhigh: "超高",
    max: "最大",
  },
  "llm.models.*.adapter_options.thinking": {
    adaptive: "自适应",
    enabled: "启用",
    disabled: "关闭",
    between_tools: "工具之间",
  },
};

function catalogPair(identity: string, locale: Locale): FieldText | undefined {
  return locale === "zh-CN" ? fieldText[identity] : undefined;
}

export function localizeField(field: CatalogField, locale: Locale = effectiveLocale()): CatalogField {
  const text = catalogPair(field.path, locale);
  return {
    ...field,
    title: text?.[0] ?? field.title,
    description: text?.[1] ?? field.description,
    choices: field.choices.map((choice) => ({
      ...choice,
      label: locale === "zh-CN" ? (choiceText[field.path]?.[choice.value] ?? choice.label) : choice.label,
    })),
  };
}

export function translatedField(catalog: SettingsCatalog | null, path: string, locale: Locale = effectiveLocale()): CatalogField | null {
  const field = matchField(catalog, path);
  return field === null ? null : localizeField(field, locale);
}

export function localizeDocument(field: CatalogDocumentField, locale: Locale = effectiveLocale()): CatalogDocumentField {
  const identity = `${field.documentSet}:${field.documentKind}:${field.path}`;
  const text = locale === "zh-CN" ? documentText[identity] : undefined;
  return text ? { ...field, title: text[0], description: text[1] } : field;
}

export function localizeSurface(surface: CatalogSurface, locale: Locale = effectiveLocale()): CatalogSurface {
  const text = locale === "zh-CN" ? surfaceText[surface.id] : undefined;
  return text === undefined ? surface : { ...surface, title: text[0], description: text[1] };
}

export function localizeFieldGroup(group: CatalogFieldGroup, locale: Locale = effectiveLocale()): CatalogFieldGroup {
  const text = locale === "zh-CN" ? fieldGroupText[group.id] : undefined;
  return text === undefined ? group : { ...group, title: text[0], description: text[1] };
}

export function localizeCollection(collection: CatalogCollection, locale: Locale = effectiveLocale()): CatalogCollection {
  const text = locale === "zh-CN" ? collectionText[collection.id] : undefined;
  return text === undefined ? collection : { ...collection, title: text[0], description: text[1] };
}

export function protocolText(code: string, locale: Locale = effectiveLocale()): string | undefined {
  const key = `protocol.${code}` as keyof typeof dictionaries["zh-CN"];
  return dictionaries[locale][key] ?? dictionaries["en-US"][key];
}

export function tError(code: string | undefined, message: string, locale: Locale = effectiveLocale()): string {
  return (code === undefined ? undefined : protocolText(code, locale)) ?? message;
}

/** Stable runtime and action values can use the same code-based projection. */
export function tStatus(value: string, locale: Locale = effectiveLocale()): string {
  return protocolText(`runtime.${value}`, locale) ?? value;
}

export function tActionState(value: string, locale: Locale = effectiveLocale()): string {
  return protocolText(`action.${value}`, locale) ?? value;
}
