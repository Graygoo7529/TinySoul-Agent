import { t, type MessageId } from "../../i18n";
import type { SettingsGroupDef, SettingsPageDef } from "./pages";

/**
 * Settings pages keep protocol ids and configuration ownership in pages.ts.
 * This module only maps those stable ids to visualization message ids; page
 * definitions remain the source of truth for routing and dynamic metadata.
 */
function pageMessage(page: SettingsPageDef, suffix: "title" | "description"): string {
  const id = `settings.page.${page.id}.${suffix}` as MessageId;
  return t(id);
}

export function settingsTitle(page: SettingsPageDef): string {
  return pageMessage(page, "title");
}

export function settingsDescription(page: SettingsPageDef): string {
  return pageMessage(page, "description");
}

export function settingsGroupTitle(group: SettingsGroupDef): string {
  return t(`settings.group.${group.id}` as MessageId);
}
