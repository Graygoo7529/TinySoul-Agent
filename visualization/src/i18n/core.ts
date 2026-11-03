import { commonMessages as zhCommon } from "./messages/zh-CN/common";
import { commonMessages as enCommon } from "./messages/en-US/common";
import { settingsMessages as zhSettings } from "./messages/zh-CN/settings";
import { settingsMessages as enSettings } from "./messages/en-US/settings";
import { protocolMessages as zhProtocol } from "./protocol/zh-CN";
import { protocolMessages as enProtocol } from "./protocol/en-US";
import { historyMessages } from "./messages/zh-CN/history";
import { historyMessages as enHistory } from "./messages/en-US/history";
import { contextMessages } from "./messages/zh-CN/context";
import { contextMessages as enContext } from "./messages/en-US/context";
import { traceMessages } from "./messages/zh-CN/trace";
import { traceMessages as enTrace } from "./messages/en-US/trace";
import { presentationMessages } from "./messages/zh-CN/presentation";
import { presentationMessages as enPresentation } from "./messages/en-US/presentation";
import { chatMessages } from "./messages/zh-CN/chat";
import { chatMessages as enChat } from "./messages/en-US/chat";
import { homeMessages } from "./messages/zh-CN/home";
import { homeMessages as enHome } from "./messages/en-US/home";
import { memoryMessages } from "./messages/zh-CN/memory";
import { memoryMessages as enMemory } from "./messages/en-US/memory";
import { workspaceMessages } from "./messages/zh-CN/workspace";
import { workspaceMessages as enWorkspace } from "./messages/en-US/workspace";
import { runtimeMessages } from "./messages/zh-CN/runtime";
import { runtimeMessages as enRuntime } from "./messages/en-US/runtime";
import { resourcesMessages } from "./messages/zh-CN/resources";
import { resourcesMessages as enResources } from "./messages/en-US/resources";
import type { Locale, MessageParams } from "./types";

const dictionaries = {
  "zh-CN": { ...zhCommon, ...zhSettings, ...historyMessages, ...contextMessages, ...traceMessages, ...presentationMessages, ...chatMessages, ...homeMessages, ...memoryMessages, ...workspaceMessages, ...runtimeMessages, ...resourcesMessages, ...zhProtocol },
  "en-US": { ...enCommon, ...enSettings, ...enHistory, ...enContext, ...enTrace, ...enPresentation, ...enChat, ...enHome, ...enMemory, ...enWorkspace, ...enRuntime, ...enResources, ...enProtocol },
} as const;

export type MessageId = keyof typeof dictionaries["zh-CN"];

function interpolate(value: string, params?: MessageParams): string {
  if (params === undefined) return value;
  return value.replace(/\{(\w+)\}/g, (full, key: string) =>
    Object.prototype.hasOwnProperty.call(params, key) ? String(params[key]) : full,
  );
}

/** Translate a fixed visualization-owned message ID. */
export function t(id: MessageId, params?: MessageParams, locale: Locale = "zh-CN"): string {
  const selected = dictionaries[locale][id] ?? dictionaries["en-US"][id];
  return interpolate(selected ?? id, params);
}


export type UiMessage = { readonly id: MessageId; readonly params?: MessageParams };
export type UiText = string | UiMessage;

export function message(id: MessageId, params?: MessageParams): UiMessage {
  return { id, params };
}

export function resolveText(value: UiText, locale: Locale): string {
  return typeof value === "string" ? value : t(value.id, value.params, locale);
}
export function protocolText(code: string, locale: Locale = "zh-CN"): string | undefined {
  const key = `protocol.${code}` as keyof typeof dictionaries["zh-CN"];
  return dictionaries[locale][key] ?? dictionaries["en-US"][key];
}

export function tError(code: string | undefined, message: string, locale: Locale = "zh-CN"): string {
  return (code === undefined ? undefined : protocolText(code, locale)) ?? message;
}

/** Stable runtime and action values can use the same code-based projection. */
export function tStatus(value: string, locale: Locale = "zh-CN"): string {
  return protocolText(`runtime.${value}`, locale) ?? value;
}

export function tActionState(value: string, locale: Locale = "zh-CN"): string {
  return protocolText(`action.${value}`, locale) ?? value;
}
