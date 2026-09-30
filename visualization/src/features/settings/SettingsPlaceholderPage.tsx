import { Construction } from "lucide-react";

import { EmptyState } from "../../components/ui/EmptyState";
import { SETTINGS_GROUPS, SETTINGS_PAGES, type SettingsPageId } from "./pages";

/**
 * Fallback for a registered settings page that has no component in
 * SettingsPage's PAGE_COMPONENTS table yet (e.g. a newly added page id whose
 * implementation has not landed). Every currently registered page has a real
 * component, so this is not reachable from the navigation today.
 */
export function SettingsPlaceholderPage({ page }: { page: SettingsPageId }) {
  const def = SETTINGS_PAGES[page];
  const group = SETTINGS_GROUPS.find((item) => item.id === def.group);
  return (
    <div className="flex h-full items-center justify-center p-6">
      <EmptyState
        icon={<Construction size={22} />}
        title={def.title}
        description={
          <>
            {def.description}
            <span className="mt-1 block text-fg-faint">
              {group?.title} · this page has no implementation yet.
            </span>
          </>
        }
      />
    </div>
  );
}
