import type { CatalogCollection, CatalogDocumentField, CatalogField, SettingsCatalog } from "../../features/settings/draft/catalog";
import { matchField } from "../../features/settings/draft/catalog";
import { collectionText, documentText, fieldText } from "./zh-CN";
import { effectiveLocale } from "../locale";
import type { Locale } from "../types";

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

export function localizeCollection(collection: CatalogCollection, locale: Locale = effectiveLocale()): CatalogCollection {
  const text = locale === "zh-CN" ? collectionText[collection.id] : undefined;
  return text === undefined ? collection : { ...collection, title: text[0], description: text[1] };
}

