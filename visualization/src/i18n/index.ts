import * as core from "./core";
import { effectiveLocale } from "./locale";
import type { Locale, MessageParams } from "./types";

export type { Locale, MessageParams } from "./types";
export type { MessageId, UiMessage, UiText } from "./core";
export { message, resolveText } from "./core";
export { effectiveLocale } from "./locale";
export { useI18n, LocalizedText } from "./react";
export { localizeCollection, localizeDocument, localizeField, translatedField } from "./catalog";

/** Imperative display helpers read the current locale at the call boundary. */
export function t(id: core.MessageId, params?: MessageParams, locale: Locale = effectiveLocale()): string {
  return core.t(id, params, locale);
}
export function protocolText(code: string, locale: Locale = effectiveLocale()): string | undefined {
  return core.protocolText(code, locale);
}
export function tStatus(value: string, locale: Locale = effectiveLocale()): string {
  return core.tStatus(value, locale);
}
