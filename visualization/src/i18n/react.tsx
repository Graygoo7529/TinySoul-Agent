import { useUiPrefsStore } from "../store/uiPrefsStore";
import { resolveText, t, type MessageId, type UiText } from "./core";
import type { MessageParams } from "./types";

export function useI18n() {
  const locale = useUiPrefsStore((state) => state.pending.locale ?? state.saved.locale);
  return { locale, t: (id: MessageId, params?: MessageParams) => t(id, params, locale), text: (value: UiText) => resolveText(value, locale) };
}

/** A message held by a drawer or other long-lived React node. */
export function LocalizedText({ value }: { value: UiText }) {
  const { text } = useI18n();
  return <>{text(value)}</>;
}
