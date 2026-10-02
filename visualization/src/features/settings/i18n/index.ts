import { matchField, type CatalogField, type CatalogDocumentField, type SettingsCatalog } from "../draft/catalog";
import { documentText, fieldText } from "./catalog.zh-CN";
import { uiText } from "./ui.zh-CN";

/** Source-copy fallback makes undeclared or newly added backend fields readable. */
export function settingsText(source: string): string {
  return uiText[source.replace(/\s+/g, " ").trim()] ?? source;
}

export function localizeField(field: CatalogField): CatalogField {
  const text = fieldText[field.path];
  return {
    ...field,
    title: text?.[0] ?? field.title,
    description: text?.[1] ?? field.description,
    choices: field.choices.map((choice) => ({ ...choice, label: settingsText(choice.label) })),
  };
}

/** Match the authoritative catalog first; localization cannot invent a field or rule. */
export function translatedField(catalog: SettingsCatalog | null, path: string): CatalogField | null {
  const field = matchField(catalog, path);
  return field === null ? null : localizeField(field);
}

export function localizeDocument(field: CatalogDocumentField): CatalogDocumentField {
  const text = field.documentSet === "action.catalog" ? documentText[`${field.documentKind}:${field.path}`] : undefined;
  return text ? { ...field, title: text[0], description: text[1] } : field;
}
