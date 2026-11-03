import { useUiPrefsStore } from "../store/uiPrefsStore";
import type { Locale } from "./types";

export function effectiveLocale(): Locale {
  const state = useUiPrefsStore.getState();
  return state.pending.locale ?? state.saved.locale ?? "zh-CN";
}

